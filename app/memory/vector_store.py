"""pgvector 向量存储封装：基于 PostgreSQL 的长期记忆与 RAG 文档库。

- 嵌入向量通过 Ollama HTTP /api/embeddings 计算（nomic-embed-text, 768 维）
- 向量存储与相似度检索使用 pgvector 扩展（cosine 距离 <=> 算子）
- 复用全局 PG 连接池，所有操作原生异步
- 实例由 FastAPI app.state 管理生命周期
"""

import json  # 导入 json 模块，用于序列化/反序列化元数据字段
import uuid  # 导入 uuid 模块（保留以备生成唯一 ID 使用）
from datetime import datetime  # 导入 datetime 类，用于生成时间戳
from typing import Dict, List, Optional  # 导入类型注解：字典、列表、可选类型

import httpx  # 导入 httpx 异步 HTTP 客户端，用于调用 Ollama 嵌入接口

from app.core.config import get_settings  # 导入配置获取函数，读取 Ollama 与模型相关配置
from app.core.logging import setup_logger  # 导入日志初始化函数
from app.db.connection import get_pool  # 导入全局连接池获取函数

logger = setup_logger("memory.vector_store")  # 创建名为 memory.vector_store 的日志记录器实例


async def _embed(text: str) -> list[float]:
    """调用 Ollama /api/embeddings 获取文本嵌入向量。"""
    settings = get_settings()  # 获取应用配置（包含 Ollama 地址与模型名）
    async with httpx.AsyncClient(timeout=10.0) as client:  # 创建异步 HTTP 客户端，超时 10 秒
        resp = await client.post(  # 发起 POST 请求获取嵌入
            f"{settings.OLLAMA_BASE_URL}/api/embeddings",  # 拼接 Ollama 嵌入接口地址
            json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text},  # 请求体：模型名与待嵌入文本
        )
        resp.raise_for_status()  # 检查响应状态码，非 2xx 抛出异常
        return resp.json()["embedding"]  # 从响应中解析并返回嵌入向量


class VectorStore:
    """pgvector 向量存储（长期记忆 + RAG 文档库）。"""

    def __init__(self) -> None:  # 构造函数
        self._available: Optional[bool] = None  # 可用性标志，None 表示尚未检查

    async def initialize(self) -> bool:
        """检查 PG 连接池与 pgvector 扩展是否可用（幂等）。"""
        if self._available is not None:  # 若已检查过则直接返回缓存结果
            return self._available
        try:  # 尝试验证 pgvector 可用性
            pool = get_pool()  # 获取全局连接池实例
            # 验证 pgvector 扩展已加载
            row = await pool.fetch_one(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') AS ok"  # 查询 vector 扩展是否已安装
            )
            self._available = row is not None and row.get("ok") is True  # 根据查询结果设置可用性
            if self._available:  # 若可用则记录日志
                logger.info("pgvector 向量库已就绪")
        except Exception as e:  # 出现异常时标记为不可用
            self._available = False
            logger.warning("pgvector 向量库不可用: %s", e)  # 记录警告日志
        return self._available is True  # 返回可用性布尔值

    async def warmup(self) -> None:
        """预热（兼容旧接口，实际无需操作）。"""
        await self.initialize()  # 复用 initialize 方法作为预热实现

    @property
    def available(self) -> bool:  # 可用性属性
        return self._available is True  # 返回当前可用性状态

    # ============================================================
    # 混合检索（向量 + 关键词 + reranking 融合）
    # ============================================================

    async def _keyword_search(
        self, query: str, table: str, top_k: int, user_id: Optional[int] = None
    ) -> list[dict]:  # 关键词全文检索方法，返回字典列表
        """PostgreSQL 全文检索（关键词匹配）。

        利用 tsvector 列与 GIN 索引执行高效全文检索，
        按ts_rank相关度降序返回结果。
        可选 user_id 参数用于长期记忆按用户过滤。
        """
        pool = get_pool()  # 获取数据库连接池实例
        if user_id is not None:  # 若指定了用户ID则按用户过滤检索
            # 构建带用户过滤的全文检索SQL
            sql = f"""  -- 带用户过滤的全文检索SQL
                SELECT *, ts_rank(tsv, plainto_tsquery('simple', $1)) AS rank  -- 查询所有列并计算全文检索相关度分数
                FROM {table}  -- 指定检索的表
                WHERE tsv @@ plainto_tsquery('simple', $1) AND user_id = $2  -- 全文匹配且用户ID匹配
                ORDER BY rank DESC  -- 按相关度降序排列
                LIMIT $3  -- 限制返回数量
            """  # SQL结束
            rows = await pool.fetch_all(sql, (query, user_id, top_k))  # 执行带用户过滤的查询
        else:  # 未指定用户ID则全局检索
            # 构建全文检索SQL（无用户过滤）
            sql = f"""  -- 全文检索SQL
                SELECT *, ts_rank(tsv, plainto_tsquery('simple', $1)) AS rank  -- 查询所有列并计算全文检索相关度分数
                FROM {table}  -- 指定检索的表
                WHERE tsv @@ plainto_tsquery('simple', $1)  -- 全文匹配条件
                ORDER BY rank DESC  -- 按相关度降序排列
                LIMIT $2  -- 限制返回数量
            """  # SQL结束
            rows = await pool.fetch_all(sql, (query, top_k))  # 执行查询
        return rows  # 返回结果列表

    def _rerank_fusion(
        self,
        vector_results: list[dict],
        keyword_results: list[dict],
        vector_weight: float,
        keyword_weight: float,
        top_k: int,
    ) -> list[dict]:  # 加权分数融合reranking方法
        """加权分数融合 reranking：合并向量检索和关键词检索结果。

        对两组结果分别归一化后按权重加权累加，
        最终按融合分数降序取top_k返回。
        """
        scores: dict[str, float] = {}  # 内容到融合分数的映射
        items: dict[str, dict] = {}  # 内容到数据项的映射

        # 处理向量检索结果（分数归一化后按权重加权）
        if vector_results:  # 如果向量检索有结果
            max_score = max((r.get('similarity', 0) for r in vector_results), default=1)  # 获取最大相似度用于归一化
            for r in vector_results:  # 遍历向量检索结果
                content = r.get('content', '')  # 获取内容作为唯一键
                normalized = r.get('similarity', 0) / max_score if max_score > 0 else 0  # 归一化分数到0-1
                scores[content] = scores.get(content, 0) + normalized * vector_weight  # 加权累加
                items[content] = r  # 保存数据项

        # 处理关键词检索结果（分数归一化后按权重加权）
        if keyword_results:  # 如果关键词检索有结果
            max_rank = max((r.get('rank', 0) for r in keyword_results), default=1)  # 获取最大rank用于归一化
            for r in keyword_results:  # 遍历关键词检索结果
                content = r.get('content', '')  # 获取内容作为唯一键
                normalized = r.get('rank', 0) / max_rank if max_rank > 0 else 0  # 归一化分数到0-1
                scores[content] = scores.get(content, 0) + normalized * keyword_weight  # 加权累加
                if content not in items:  # 如果该内容不在items中（仅关键词检索命中）
                    items[content] = r  # 保存数据项

        # 按融合分数降序排序，取top_k
        sorted_contents = sorted(scores.items(), key=lambda x: x[1], reverse=True)  # 按分数降序排序
        result = []  # 结果列表
        for content, score in sorted_contents[:top_k]:  # 取前top_k个
            item = items[content].copy()  # 复制数据项
            item['fusion_score'] = score  # 添加融合分数
            result.append(item)  # 加入结果列表
        return result  # 返回融合排序后的结果

    # ============================================================
    # 长期记忆
    # ============================================================

    async def store_conversation_turn(
        self, user_id: str, question: str, answer: str, metadata: Optional[Dict] = None
    ) -> None:  # 将一轮对话存入长期记忆向量库
        """将一轮对话存入长期记忆向量库。"""
        if not await self.initialize():  # 若向量库不可用则直接返回
            return
        summary_text = f"问题: {question}\n回答: {answer[:300]}"  # 拼接问题与回答前 300 字作为嵌入文本
        try:  # 尝试计算嵌入向量
            embedding = await _embed(summary_text)
        except Exception as e:  # 嵌入计算失败时跳过存储
            logger.warning("嵌入计算失败，跳过存储: %s", e)
            return
        pool = get_pool()  # 获取连接池
        meta = {  # 构造元数据字典
            "user_id": user_id,  # 用户 ID
            "question": question[:500],  # 问题文本（截断 500 字）
            "answer": answer[:500],  # 回答文本（截断 500 字）
            "timestamp": datetime.now().isoformat(),  # 当前时间戳 ISO 字符串
        }
        if metadata:  # 若调用方传入额外元数据
            meta.update(metadata)  # 合并到元数据字典
        await pool.execute(  # 执行插入语句
            "INSERT INTO long_term_memories (user_id, content, question, answer, metadata, embedding) "
            "VALUES ($1, $2, $3, $4, $5, $6)",  # 插入长期记忆表的 SQL
            (
                int(user_id) if isinstance(user_id, str) and user_id.isdigit() else None,  # user_id 转为整数；非数字则存 None
                summary_text,  # 摘要内容
                question[:500],  # 问题字段
                answer[:500],  # 回答字段
                json.dumps(meta, ensure_ascii=False),  # 元数据序列化为 JSON 字符串（保留中文）
                embedding,  # 嵌入向量
            ),
        )
        logger.debug("已存入长期记忆")  # 记录调试日志

    async def retrieve_long_term_memories(
        self, query: str, user_id: Optional[str] = None, top_k: int = 5
    ) -> List[Dict]:  # 检索与查询相关的历史对话
        """从长期记忆中检索相关历史对话。

        当 HYBRID_SEARCH_ENABLED 为 True 时启用混合检索（向量+关键词+融合重排），
        否则保持原有纯向量检索逻辑。
        """
        if not await self.initialize():  # 若向量库不可用则返回空列表
            return []
        try:  # 计算查询的嵌入向量
            embedding = await _embed(query)
        except Exception as e:  # 嵌入计算失败时返回空列表
            logger.warning("嵌入计算失败，跳过检索: %s", e)
            return []
        pool = get_pool()  # 获取连接池
        settings = get_settings()  # 获取配置用于判断是否启用混合检索
        # 解析 user_id：尝试转换为整数，非数字则置为 None
        uid = None  # 初始化用户ID为None
        if user_id:  # 若提供了 user_id
            uid = int(user_id) if isinstance(user_id, str) and user_id.isdigit() else None  # 尝试转换为整数

        if settings.HYBRID_SEARCH_ENABLED:  # 启用混合检索分支
            candidate_k = settings.HYBRID_RERANK_TOP_K  # 候选数量（reranking前的检索数量）
            # ---- 向量检索：取 candidate_k 条候选 ----
            if uid is not None:  # 有有效用户ID则按用户过滤向量检索
                vector_rows = await pool.fetch_all(
                    "SELECT content, metadata, embedding <=> $1 AS distance "  # cosine 距离算子 <=>
                    "FROM long_term_memories WHERE user_id = $2 "  # 过滤指定用户
                    "ORDER BY embedding <=> $1 LIMIT $3",  # 按距离升序取候选数量
                    (embedding, uid, candidate_k),  # 参数：嵌入向量、用户ID、候选数量
                )
            else:  # 无有效用户ID则全局向量检索
                vector_rows = await pool.fetch_all(
                    "SELECT content, metadata, embedding <=> $1 AS distance "  # cosine 距离算子 <=>
                    "FROM long_term_memories "  # 不限用户
                    "ORDER BY embedding <=> $1 LIMIT $2",  # 按距离升序取候选数量
                    (embedding, candidate_k),  # 参数：嵌入向量、候选数量
                )
            # 将向量检索的 distance 转换为 similarity 供融合使用
            vector_results = []  # 向量检索结果列表（含similarity字段）
            for r in vector_rows:  # 遍历向量检索原始行
                item = r.copy()  # 复制行字典避免修改原始数据
                item['similarity'] = 1.0 - float(r.get('distance', 1.0))  # 距离转相似度（cosine distance → similarity）
                vector_results.append(item)  # 加入向量结果列表
            # ---- 关键词检索：取 candidate_k 条候选 ----
            keyword_results = await self._keyword_search(query, 'long_term_memories', candidate_k, user_id=uid)  # 全文检索
            # ---- 加权分数融合 reranking ----
            fused_rows = self._rerank_fusion(  # 调用融合方法合并两组结果
                vector_results,  # 向量检索结果
                keyword_results,  # 关键词检索结果
                1.0 - settings.HYBRID_KEYWORD_WEIGHT,  # 向量权重 = 1 - 关键词权重
                settings.HYBRID_KEYWORD_WEIGHT,  # 关键词权重
                top_k,  # 最终返回数量
            )
            # ---- 格式化融合后的结果为记忆列表 ----
            memories = []  # 初始化结果列表
            for r in fused_rows:  # 遍历融合后的结果行
                meta = r.get("metadata")  # 获取元数据
                if meta is None:  # 元数据为None时使用空字典
                    meta = {}
                elif not isinstance(meta, dict):  # 元数据若为字符串则解析为字典
                    meta = json.loads(meta)
                memories.append({  # 构造记忆字典
                    "content": r.get("content", ""),  # 记忆内容
                    "metadata": meta,  # 元数据
                    "fusion_score": r.get("fusion_score", 0.0),  # 融合分数（混合检索时使用）
                })
            return memories  # 返回记忆列表

        # ---- 非混合检索：保持原有纯向量检索逻辑 ----
        if uid is not None:  # 转换成功则按用户 ID 检索
            rows = await pool.fetch_all(
                "SELECT content, metadata, embedding <=> $1 AS distance "  # cosine 距离算子 <=>
                "FROM long_term_memories WHERE user_id = $2 "  # 过滤指定用户
                "ORDER BY embedding <=> $1 LIMIT $3",  # 按距离升序取 top_k
                (embedding, uid, top_k),  # 参数：嵌入向量、用户 ID、返回条数
            )
        else:  # user_id 非数字或未提供，全局检索
            rows = await pool.fetch_all(
                "SELECT content, metadata, embedding <=> $1 AS distance "
                "FROM long_term_memories "
                "ORDER BY embedding <=> $1 LIMIT $2",
                (embedding, top_k),
            )
        memories = []  # 初始化结果列表
        for r in rows:  # 遍历数据库返回的行
            meta = r["metadata"] if isinstance(r["metadata"], dict) else json.loads(r["metadata"])  # 元数据若为字符串则解析为字典
            memories.append({  # 构造记忆字典
                "content": r["content"],  # 记忆内容
                "metadata": meta,  # 元数据
                "distance": float(r["distance"]),  # 相似度距离（越小越相似）
            })
        return memories  # 返回记忆列表

    # ============================================================
    # RAG 文档库
    # ============================================================

    async def add_document_chunks(self, chunks: List[Dict], filename: str) -> int:
        """将文档切片批量存入 RAG 向量库，返回切片数。"""
        if not await self.initialize():  # 若向量库不可用则返回 0
            return 0
        if not chunks:  # 若无切片则返回 0
            return 0
        pool = get_pool()  # 获取连接池
        count = 0  # 已成功存入的切片计数
        for i, chunk in enumerate(chunks):  # 遍历切片及其索引
            doc_id = f"{filename}_{i}"  # 拼接切片唯一 ID
            text = chunk["text"]  # 获取切片文本
            try:  # 计算切片嵌入
                embedding = await _embed(text)
            except Exception as e:  # 嵌入失败则跳过该切片
                logger.warning("嵌入计算失败（chunk %d），跳过: %s", i, e)
                continue
            await pool.execute(  # 插入或更新切片
                "INSERT INTO rag_chunks (id, filename, chunk_index, content, section_title, "
                "prev_chunk_id, next_chunk_id, embedding) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT (id) DO UPDATE SET content = $4, embedding = $8",  # 主键冲突时更新内容与嵌入
                (
                    doc_id,  # 切片 ID
                    filename,  # 文件名
                    i,  # 切片序号
                    text,  # 内容
                    chunk.get("section_title", ""),  # 章节标题，默认空字符串
                    str(chunk.get("prev_chunk_id", "")),  # 前驱 ID 转字符串
                    str(chunk.get("next_chunk_id", "")),  # 后继 ID 转字符串
                    embedding,  # 嵌入向量
                ),
            )
            count += 1  # 成功计数加一
        logger.info("RAG文档已存入: %s (%d个切片)", filename, count)  # 记录存入日志
        return count  # 返回成功存入的切片数

    async def retrieve_rag_context(self, query: str, top_k: int = 3) -> str:
        """从 RAG 文档库检索相关文档片段。

        当 HYBRID_SEARCH_ENABLED 为 True 时启用混合检索（向量+关键词+融合重排），
        否则保持原有纯向量检索逻辑。
        """
        if not await self.initialize():  # 若向量库不可用则返回空字符串
            return ""
        try:  # 计算查询嵌入
            embedding = await _embed(query)
        except Exception as e:  # 嵌入失败返回空字符串
            logger.warning("嵌入计算失败，跳过RAG检索: %s", e)
            return ""
        pool = get_pool()  # 获取连接池
        settings = get_settings()  # 获取配置用于判断是否启用混合检索

        if settings.HYBRID_SEARCH_ENABLED:  # 启用混合检索分支
            candidate_k = settings.HYBRID_RERANK_TOP_K  # 候选数量（reranking前的检索数量）
            # ---- 向量检索：取 candidate_k 条候选 ----
            vector_rows = await pool.fetch_all(
                "SELECT content, filename, section_title, embedding <=> $1 AS distance "  # 查询内容、文件名、章节与距离
                "FROM rag_chunks ORDER BY embedding <=> $1 LIMIT $2",  # 按距离升序取候选数量
                (embedding, candidate_k),  # 参数：嵌入向量、候选数量
            )
            # 将向量检索的 distance 转换为 similarity 供融合使用
            vector_results = []  # 向量检索结果列表（含similarity字段）
            for r in vector_rows:  # 遍历向量检索原始行
                item = r.copy()  # 复制行字典避免修改原始数据
                item['similarity'] = 1.0 - float(r.get('distance', 1.0))  # 距离转相似度（cosine distance → similarity）
                vector_results.append(item)  # 加入向量结果列表
            # ---- 关键词检索：取 candidate_k 条候选 ----
            keyword_results = await self._keyword_search(query, 'rag_chunks', candidate_k)  # 全文检索（无用户过滤）
            # ---- 加权分数融合 reranking ----
            rows = self._rerank_fusion(  # 调用融合方法合并两组结果
                vector_results,  # 向量检索结果
                keyword_results,  # 关键词检索结果
                1.0 - settings.HYBRID_KEYWORD_WEIGHT,  # 向量权重 = 1 - 关键词权重
                settings.HYBRID_KEYWORD_WEIGHT,  # 关键词权重
                top_k,  # 最终返回数量
            )
        else:  # 非混合检索：保持原有纯向量检索逻辑
            rows = await pool.fetch_all(
                "SELECT content, filename, section_title, embedding <=> $1 AS distance "  # 查询内容、文件名、章节与距离
                "FROM rag_chunks ORDER BY embedding <=> $1 LIMIT $2",  # 按距离升序取 top_k
                (embedding, top_k),
            )
        if not rows:  # 若无结果则返回空字符串
            return ""
        parts = ["[RAG文档检索结果]"]  # 上下文首行标题
        for i, r in enumerate(rows, 1):  # 遍历结果行，编号从 1 开始
            section = r.get("section_title", "")  # 获取章节标题
            section_info = f" (章节: {section})" if section else ""  # 若有章节则拼接显示
            source = r.get("filename", "未知文档")  # 获取文件名，缺失标记未知
            parts.append(f"--- 来源: {source}{section_info} (片段{i}) ---\n{r['content'][:500]}")  # 拼接片段信息与内容前 500 字
        return "\n".join(parts)  # 用换行符拼接为完整上下文返回

    async def list_documents(self) -> List[Dict]:
        """列出所有已上传的 RAG 文档。"""
        if not await self.initialize():  # 若向量库不可用则返回空列表
            return []
        pool = get_pool()  # 获取连接池
        rows = await pool.fetch_all(
            "SELECT filename, COUNT(*) as chunks, MAX(created_at) as timestamp "  # 按文件名聚合切片数与最新时间
            "FROM rag_chunks GROUP BY filename ORDER BY MAX(created_at) DESC"  # 按最新时间倒序排列
        )
        return [  # 构造文档列表
            {
                "filename": r["filename"],  # 文件名
                "chunks": r["chunks"],  # 切片数量
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else "",  # 时间戳转 ISO 字符串，缺失则空串
            }
            for r in rows  # 遍历每一行
        ]

    async def delete_document(self, filename: str) -> bool:
        """删除指定文档的所有切片。"""
        if not await self.initialize():  # 若向量库不可用则返回 False
            return False
        pool = get_pool()  # 获取连接池
        async with pool.acquire() as conn:  # 获取连接用于执行删除
            result = await conn.execute(
                "DELETE FROM rag_chunks WHERE filename = $1", filename  # 删除指定文件名的所有切片
            )
            # asyncpg returns "DELETE N"
            count = int(result.split()[-1]) if result else 0  # 解析删除的行数
        if count > 0:  # 若有切片被删除
            logger.info("RAG文档已删除: %s (%d个切片)", filename, count)  # 记录删除日志
            return True  # 返回成功
        return False  # 无切片被删除则返回 False
