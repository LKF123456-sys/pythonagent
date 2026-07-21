"""pgvector 向量存储封装：基于 PostgreSQL 的长期记忆与 RAG 文档库。

- 嵌入向量通过 Ollama HTTP /api/embeddings 计算（nomic-embed-text, 768 维）
- 向量存储与相似度检索使用 pgvector 扩展（cosine 距离 <=> 算子）
- 复用全局 PG 连接池，所有操作原生异步
- 实例由 FastAPI app.state 管理生命周期
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import setup_logger
from app.db.connection import get_pool

logger = setup_logger("memory.vector_store")


async def _embed(text: str) -> list[float]:
    """调用 Ollama /api/embeddings 获取文本嵌入向量。"""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/embeddings",
            json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


class VectorStore:
    """pgvector 向量存储（长期记忆 + RAG 文档库）。"""

    def __init__(self) -> None:
        self._available: Optional[bool] = None

    async def initialize(self) -> bool:
        """检查 PG 连接池与 pgvector 扩展是否可用（幂等）。"""
        if self._available is not None:
            return self._available
        try:
            pool = get_pool()
            # 验证 pgvector 扩展已加载
            row = await pool.fetch_one(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') AS ok"
            )
            self._available = row is not None and row.get("ok") is True
            if self._available:
                logger.info("pgvector 向量库已就绪")
        except Exception as e:
            self._available = False
            logger.warning("pgvector 向量库不可用: %s", e)
        return self._available is True

    async def warmup(self) -> None:
        """预热（兼容旧接口，实际无需操作）。"""
        await self.initialize()

    @property
    def available(self) -> bool:
        return self._available is True

    # ============================================================
    # 长期记忆
    # ============================================================

    async def store_conversation_turn(
        self, user_id: str, question: str, answer: str, metadata: Optional[Dict] = None
    ) -> None:
        """将一轮对话存入长期记忆向量库。"""
        if not await self.initialize():
            return
        summary_text = f"问题: {question}\n回答: {answer[:300]}"
        try:
            embedding = await _embed(summary_text)
        except Exception as e:
            logger.warning("嵌入计算失败，跳过存储: %s", e)
            return
        pool = get_pool()
        meta = {
            "user_id": user_id,
            "question": question[:500],
            "answer": answer[:500],
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            meta.update(metadata)
        await pool.execute(
            "INSERT INTO long_term_memories (user_id, content, question, answer, metadata, embedding) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            (
                int(user_id) if isinstance(user_id, str) and user_id.isdigit() else None,
                summary_text,
                question[:500],
                answer[:500],
                json.dumps(meta, ensure_ascii=False),
                embedding,
            ),
        )
        logger.debug("已存入长期记忆")

    async def retrieve_long_term_memories(
        self, query: str, user_id: Optional[str] = None, top_k: int = 5
    ) -> List[Dict]:
        """从长期记忆中检索相关历史对话。"""
        if not await self.initialize():
            return []
        try:
            embedding = await _embed(query)
        except Exception as e:
            logger.warning("嵌入计算失败，跳过检索: %s", e)
            return []
        pool = get_pool()
        if user_id:
            uid = int(user_id) if isinstance(user_id, str) and user_id.isdigit() else None
            if uid is not None:
                rows = await pool.fetch_all(
                    "SELECT content, metadata, embedding <=> $1 AS distance "
                    "FROM long_term_memories WHERE user_id = $2 "
                    "ORDER BY embedding <=> $1 LIMIT $3",
                    (embedding, uid, top_k),
                )
            else:
                rows = await pool.fetch_all(
                    "SELECT content, metadata, embedding <=> $1 AS distance "
                    "FROM long_term_memories "
                    "ORDER BY embedding <=> $1 LIMIT $2",
                    (embedding, top_k),
                )
        else:
            rows = await pool.fetch_all(
                "SELECT content, metadata, embedding <=> $1 AS distance "
                "FROM long_term_memories "
                "ORDER BY embedding <=> $1 LIMIT $2",
                (embedding, top_k),
            )
        memories = []
        for r in rows:
            meta = r["metadata"] if isinstance(r["metadata"], dict) else json.loads(r["metadata"])
            memories.append({
                "content": r["content"],
                "metadata": meta,
                "distance": float(r["distance"]),
            })
        return memories

    # ============================================================
    # RAG 文档库
    # ============================================================

    async def add_document_chunks(self, chunks: List[Dict], filename: str) -> int:
        """将文档切片批量存入 RAG 向量库，返回切片数。"""
        if not await self.initialize():
            return 0
        if not chunks:
            return 0
        pool = get_pool()
        count = 0
        for i, chunk in enumerate(chunks):
            doc_id = f"{filename}_{i}"
            text = chunk["text"]
            try:
                embedding = await _embed(text)
            except Exception as e:
                logger.warning("嵌入计算失败（chunk %d），跳过: %s", i, e)
                continue
            await pool.execute(
                "INSERT INTO rag_chunks (id, filename, chunk_index, content, section_title, "
                "prev_chunk_id, next_chunk_id, embedding) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT (id) DO UPDATE SET content = $4, embedding = $8",
                (
                    doc_id,
                    filename,
                    i,
                    text,
                    chunk.get("section_title", ""),
                    str(chunk.get("prev_chunk_id", "")),
                    str(chunk.get("next_chunk_id", "")),
                    embedding,
                ),
            )
            count += 1
        logger.info("RAG文档已存入: %s (%d个切片)", filename, count)
        return count

    async def retrieve_rag_context(self, query: str, top_k: int = 3) -> str:
        """从 RAG 文档库检索相关文档片段。"""
        if not await self.initialize():
            return ""
        try:
            embedding = await _embed(query)
        except Exception as e:
            logger.warning("嵌入计算失败，跳过RAG检索: %s", e)
            return ""
        pool = get_pool()
        rows = await pool.fetch_all(
            "SELECT content, filename, section_title, embedding <=> $1 AS distance "
            "FROM rag_chunks ORDER BY embedding <=> $1 LIMIT $2",
            (embedding, top_k),
        )
        if not rows:
            return ""
        parts = ["[RAG文档检索结果]"]
        for i, r in enumerate(rows, 1):
            section = r.get("section_title", "")
            section_info = f" (章节: {section})" if section else ""
            source = r.get("filename", "未知文档")
            parts.append(f"--- 来源: {source}{section_info} (片段{i}) ---\n{r['content'][:500]}")
        return "\n".join(parts)

    async def list_documents(self) -> List[Dict]:
        """列出所有已上传的 RAG 文档。"""
        if not await self.initialize():
            return []
        pool = get_pool()
        rows = await pool.fetch_all(
            "SELECT filename, COUNT(*) as chunks, MAX(created_at) as timestamp "
            "FROM rag_chunks GROUP BY filename ORDER BY MAX(created_at) DESC"
        )
        return [
            {
                "filename": r["filename"],
                "chunks": r["chunks"],
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else "",
            }
            for r in rows
        ]

    async def delete_document(self, filename: str) -> bool:
        """删除指定文档的所有切片。"""
        if not await self.initialize():
            return False
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM rag_chunks WHERE filename = $1", filename
            )
            # asyncpg returns "DELETE N"
            count = int(result.split()[-1]) if result else 0
        if count > 0:
            logger.info("RAG文档已删除: %s (%d个切片)", filename, count)
            return True
        return False

