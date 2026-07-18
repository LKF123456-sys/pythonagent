"""
向量记忆模块：基于ChromaDB实现长期记忆和RAG检索增强生成。
- 长期记忆：存储对话摘要，跨会话检索历史知识
- RAG文档库：存储用户上传的文档，检索增强回答
- 嵌入模型：使用Ollama本地嵌入（nomic-embed-text）
- 容错：嵌入模型未就绪时自动降级，不影响核心对话功能
- 会话管理已迁移至 database.py（SQLite）
"""

# 导入os模块，用于路径操作
import os
# 导入re模块，用于正则表达式文本处理
import re
# 导入uuid模块，用于生成唯一ID
import uuid
# 从datetime模块导入datetime类，用于时间处理
from datetime import datetime
# 导入类型提示模块
from typing import List, Dict, Optional

# 导入chromadb模块，用于向量数据库操作
import chromadb
# 从chromadb.config导入Settings，用于ChromaDB配置
from chromadb.config import Settings as ChromaSettings
# 从chromadb.utils导入embedding_functions，用于嵌入函数
from chromadb.utils import embedding_functions

# 导入配置模块
from config import Config
# 导入日志设置函数
from logger import setup_logger

# 初始化日志记录器
logger = setup_logger("memory", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# ChromaDB 懒加载（嵌入模型未就绪时降级）
# ============================================================

# ChromaDB客户端实例（懒加载）
_chroma_client = None
# 长期记忆集合实例
_long_term_collection = None
# RAG文档集合实例
_rag_collection = None
# ChromaDB可用状态标记：None=未检测, True=可用, False=不可用
_chroma_available = None


def _ensure_chroma() -> bool:
    """
    懒加载ChromaDB，仅在首次调用时初始化。
    如果嵌入模型不可用，标记为不可用并跳过后续所有向量操作。

    Returns:
        bool: ChromaDB是否可用
    """
    # 声明使用全局变量
    global _chroma_client, _long_term_collection, _rag_collection, _chroma_available
    # 如果已检测过可用性，直接返回缓存结果
    if _chroma_available is not None:
        return _chroma_available
    try:
        # 创建Ollama嵌入函数实例，使用配置的嵌入模型
        _embed_fn = embedding_functions.OllamaEmbeddingFunction(
            model_name=Config.OLLAMA_EMBED_MODEL,
            url=f"{Config.OLLAMA_BASE_URL}/api/embeddings",
        )
        # 创建持久化ChromaDB客户端
        _chroma_client = chromadb.PersistentClient(
            path=Config.CHROMA_DB_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),  # 禁用匿名遥测
        )
        # 获取或创建长期记忆集合
        _long_term_collection = _chroma_client.get_or_create_collection(
            name="long_term_memory",
            embedding_function=_embed_fn,
            metadata={"description": "长期对话记忆"},
        )
        # 获取或创建RAG文档集合
        _rag_collection = _chroma_client.get_or_create_collection(
            name="rag_documents",
            embedding_function=_embed_fn,
            metadata={"description": "RAG文档库"},
        )
        # 实际调用一次嵌入，验证模型是否可用
        _embed_fn(["test"])
        # 标记ChromaDB为可用
        _chroma_available = True
        # 记录初始化成功日志
        logger.info("ChromaDB 向量库初始化成功")
    except Exception as e:
        # 初始化失败，清空所有实例
        _chroma_client = None
        _long_term_collection = None
        _rag_collection = None
        # 标记为不可用
        _chroma_available = False
        # 记录警告日志
        logger.warning("ChromaDB 向量库暂不可用（嵌入模型未就绪）: %s", e)
    # 返回可用性状态
    return _chroma_available


# ============================================================
# 长期记忆：存储和检索对话摘要
# ============================================================

def store_conversation_turn(
    user_id: str,
    question: str,
    answer: str,
    metadata: Optional[Dict] = None,
) -> None:
    """
    将一轮对话摘要存入长期记忆向量库。
    """
    # 如果ChromaDB不可用，直接返回
    if not _ensure_chroma():
        return
    # 构建记忆摘要文本：问题+回答截断到300字符
    summary_text = f"问题: {question}\n回答: {answer[:300]}"
    # 构建元数据
    meta = {
        "user_id": user_id,                                    # 用户ID
        "question": question[:500],                            # 问题（截断500字符）
        "answer": answer[:500],                                # 回答（截断500字符）
        "timestamp": datetime.now().isoformat(),               # 时间戳
    }
    # 如果有额外元数据，合并进去
    if metadata:
        meta.update(metadata)
    # 生成唯一文档ID（12位UUID）
    doc_id = str(uuid.uuid4())[:12]
    # 将文档添加到长期记忆集合
    _long_term_collection.add(
        ids=[doc_id],
        documents=[summary_text],
        metadatas=[meta],
    )
    # 记录调试日志
    logger.debug("已存入长期记忆: %s", doc_id)


def retrieve_long_term_memories(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = None,
) -> List[Dict]:
    """
    从长期记忆中检索与当前查询最相关的历史对话。
    """
    # 如果ChromaDB不可用，返回空列表
    if not _ensure_chroma():
        return []
    # 如果未指定top_k，使用配置的默认值
    if top_k is None:
        top_k = Config.LONG_TERM_TOP_K
    # 初始化where过滤条件
    where_filter = None
    # 如果指定了user_id，添加用户过滤条件
    if user_id:
        where_filter = {"user_id": user_id}
    # 执行向量相似度查询
    results = _long_term_collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where_filter,
    )
    # 格式化查询结果
    memories = []
    # 如果有结果文档
    if results["documents"] and results["documents"][0]:
        # 遍历每条结果
        for i, doc in enumerate(results["documents"][0]):
            # 获取对应的元数据
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            # 添加到记忆列表
            memories.append({
                "content": doc,
                "metadata": meta,
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })
    # 返回记忆列表
    return memories


def format_memories_context(memories: List[Dict]) -> str:
    """
    将检索到的长期记忆格式化为可注入LLM的上下文文本。

    Args:
        memories: retrieve_long_term_memories 的返回结果

    Returns:
        str: 格式化后的记忆上下文
    """
    # 如果没有记忆，返回空字符串
    if not memories:
        return ""
    # 初始化结果行，添加标题
    lines = ["[长期记忆 - 相关历史对话]"]
    # 遍历每条记忆，格式化
    for i, mem in enumerate(memories, 1):
        # 获取时间戳，默认"未知时间"
        ts = mem.get("metadata", {}).get("timestamp", "未知时间")
        # 添加格式化行（内容截断到200字符）
        lines.append(f"{i}. [{ts}] {mem['content'][:200]}")
    # 用换行连接所有行并返回
    return "\n".join(lines)


# ============================================================
# 语义感知文档切片（Phase 2 增强）
# ============================================================

def _semantic_chunk(
    content: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> List[Dict]:
    """
    语义感知文档切片：
    1. 优先按 Markdown 标题（# / ## / ###）分段
    2. 同一标题段内按段落（双换行 \\n\\n）分割
    3. 超长段落退化为滑动窗口
    4. 每个切片携带 section_title 和前后链接关系

    Returns:
        List[Dict]: 每个元素包含 text, section_title 字段
    """
    # 按Markdown标题分割文档（正向预查：匹配换行后紧跟1-6个#和空格的位置）
    sections = re.split(r'\n(?=#{1,6}\s)', content)
    # 初始化切片列表
    chunks = []

    # 遍历每个标题段
    for section in sections:
        # 去除首尾空白
        section = section.strip()
        # 跳过空段
        if not section:
            continue

        # 提取标题：匹配开头的#号和标题文本
        title_match = re.match(r'^(#{1,6})\s+(.+)', section)
        # 提取章节标题
        section_title = title_match.group(2).strip() if title_match else ""
        # 去掉标题行，保留正文内容
        body = re.sub(r'^#{1,6}\s+.+\n?', '', section, count=1) if title_match else section

        # 按段落分割（双换行）
        paragraphs = re.split(r'\n\s*\n', body)
        # 当前累积的块文本
        current_chunk = ""
        # 当前块的标题
        current_title = section_title

        # 遍历每个段落
        for para in paragraphs:
            # 去除段落首尾空白
            para = para.strip()
            # 跳过空段落
            if not para:
                continue

            # 如果当前块加上新段落不超过chunk_size，追加到当前块
            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}".strip() if current_chunk else para
            else:
                # 当前块已满，先保存
                if current_chunk:
                    chunks.append({"text": current_chunk, "section_title": current_title})

                # 如果段落本身超长，退化为滑动窗口切片
                if len(para) > chunk_size:
                    start = 0
                    while start < len(para):
                        end = start + chunk_size
                        chunks.append({
                            "text": para[start:end],
                            "section_title": current_title,
                        })
                        # 前进（考虑重叠）
                        start += (chunk_size - chunk_overlap)
                    # 滑动窗口处理完，清空当前块
                    current_chunk = ""
                else:
                    # 段落不超长，保留overlap字符作为上下文
                    if chunks and chunk_overlap > 0:
                        # 取上一块末尾chunk_overlap字符作为重叠
                        prev_text = chunks[-1]["text"]
                        overlap_text = prev_text[-chunk_overlap:] if len(prev_text) > chunk_overlap else prev_text
                        # 将重叠文本和新段落组合成新块
                        current_chunk = f"{overlap_text}\n{para}".strip()
                    else:
                        # 没有上一块，直接用段落作为新块
                        current_chunk = para

        # 保存最后剩余的块
        if current_chunk:
            chunks.append({"text": current_chunk, "section_title": current_title})

    # 为每个切片添加前后chunk_id链接
    for i, chunk in enumerate(chunks):
        # 前一个chunk的索引（第一个为None）
        chunk["prev_chunk_id"] = i - 1 if i > 0 else None
        # 后一个chunk的索引（最后一个为None）
        chunk["next_chunk_id"] = i + 1 if i < len(chunks) - 1 else None

    # 返回切片列表
    return chunks


# ============================================================
# RAG文档库：文档上传、切片、检索
# ============================================================

def add_document(
    content: str,
    filename: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> int:
    """
    将文档内容语义切片后存入RAG向量库。

    Args:
        content: 文档文本内容
        filename: 文档文件名（用于元数据标记）
        chunk_size: 每个切片的最大字符数
        chunk_overlap: 相邻切片的重叠字符数

    Returns:
        int: 存入的切片数量
    """
    # 如果ChromaDB不可用，返回0
    if not _ensure_chroma():
        return 0

    # 对文档进行语义感知切片
    chunks = _semantic_chunk(content, chunk_size, chunk_overlap)
    # 如果没有切片，返回0
    if not chunks:
        return 0

    # 批量准备向量库数据
    # 生成每个切片的ID：文件名_索引
    ids = [f"{filename}_{i}" for i in range(len(chunks))]
    # 提取所有切片文本
    documents = [c["text"] for c in chunks]
    # 构建每个切片的元数据
    metadatas = [
        {
            "filename": filename,                              # 文件名
            "chunk_index": i,                                  # 切片索引
            "section_title": c.get("section_title", ""),       # 章节标题
            "prev_chunk_id": str(c.get("prev_chunk_id", "")),  # 前一切片ID
            "next_chunk_id": str(c.get("next_chunk_id", "")),  # 后一切片ID
            "timestamp": datetime.now().isoformat(),           # 时间戳
        }
        for i, c in enumerate(chunks)
    ]
    # 批量添加到RAG集合
    _rag_collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )
    # 记录日志
    logger.info("RAG文档已存入: %s (%d个切片)", filename, len(chunks))
    # 返回切片数量
    return len(chunks)


def retrieve_rag_context(
    query: str,
    top_k: int = 3,
) -> str:
    """
    从RAG文档库中检索与查询最相关的文档片段。
    """
    # 如果ChromaDB不可用，返回空字符串
    if not _ensure_chroma():
        return ""
    # 执行向量相似度查询
    results = _rag_collection.query(
        query_texts=[query],
        n_results=top_k,
    )
    # 如果没有结果，返回空字符串
    if not results["documents"] or not results["documents"][0]:
        return ""
    # 格式化检索结果
    parts = ["[RAG文档检索结果]"]
    # 遍历每条结果
    for i, doc in enumerate(results["documents"][0], 1):
        # 获取对应的元数据（注意索引可能有问题，这里简单处理）
        meta = results["metadatas"][0][i-1] if results["metadatas"] and i <= len(results["metadatas"][0]) else {}
        # 获取来源文件名
        source = meta.get("filename", "未知文档")
        # 获取章节标题
        section = meta.get("section_title", "")
        # 章节信息字符串
        section_info = f" (章节: {section})" if section else ""
        # 添加格式化片段（内容截断到500字符）
        parts.append(f"--- 来源: {source}{section_info} (片段{i}) ---\n{doc[:500]}")
    # 用换行连接并返回
    return "\n".join(parts)


def list_documents() -> List[Dict]:
    """
    列出RAG文档库中所有已上传的文档及其切片数。
    """
    # 如果ChromaDB不可用，返回空列表
    if not _ensure_chroma():
        return []
    # 获取集合中所有文档
    all_data = _rag_collection.get()
    # 如果没有元数据，返回空列表
    if not all_data["metadatas"]:
        return []
    # 按文件名聚合统计
    doc_map = {}
    for meta in all_data["metadatas"]:
        # 获取文件名
        fname = meta.get("filename", "未知")
        # 如果文件名不在map中，初始化
        if fname not in doc_map:
            doc_map[fname] = {"filename": fname, "chunks": 0, "timestamp": ""}
        # 切片数+1
        doc_map[fname]["chunks"] += 1
        # 更新时间戳（取最新的）
        doc_map[fname]["timestamp"] = meta.get("timestamp", "")
    # 转换为列表返回
    return list(doc_map.values())


def delete_document(filename: str) -> bool:
    """
    从RAG库中删除指定文档的所有切片。
    """
    # 如果ChromaDB不可用，返回False
    if not _ensure_chroma():
        return False
    # 获取所有文档数据
    all_data = _rag_collection.get()
    # 初始化待删除ID列表
    ids_to_delete = []
    # 遍历所有元数据，找到匹配文件名的切片ID
    for i, meta in enumerate(all_data["metadatas"]):
        if meta.get("filename") == filename:
            ids_to_delete.append(all_data["ids"][i])
    # 如果有要删除的ID
    if ids_to_delete:
        # 批量删除
        _rag_collection.delete(ids=ids_to_delete)
        # 记录日志
        logger.info("RAG文档已删除: %s (%d个切片)", filename, len(ids_to_delete))
        # 返回True表示成功
        return True
    # 没有找到文档，返回False
    return False
