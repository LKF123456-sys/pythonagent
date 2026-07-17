"""
向量记忆模块：基于ChromaDB实现长期记忆和RAG检索增强生成。
- 长期记忆：存储对话摘要，跨会话检索历史知识
- RAG文档库：存储用户上传的文档，检索增强回答
- 嵌入模型：使用Ollama本地嵌入（nomic-embed-text）
- 容错：嵌入模型未就绪时自动降级，不影响核心对话功能
- 会话管理已迁移至 database.py（SQLite）
"""

import os
import re
import uuid
from datetime import datetime
from typing import List, Dict, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions

from config import Config
from logger import setup_logger

logger = setup_logger("memory", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# ChromaDB 懒加载（嵌入模型未就绪时降级）
# ============================================================

_chroma_client = None
_long_term_collection = None
_rag_collection = None
_chroma_available = None  # None=未检测, True=可用, False=不可用


def _ensure_chroma() -> bool:
    """
    懒加载ChromaDB，仅在首次调用时初始化。
    如果嵌入模型不可用，标记为不可用并跳过后续所有向量操作。

    Returns:
        bool: ChromaDB是否可用
    """
    global _chroma_client, _long_term_collection, _rag_collection, _chroma_available
    if _chroma_available is not None:
        return _chroma_available
    try:
        _embed_fn = embedding_functions.OllamaEmbeddingFunction(
            model_name=Config.OLLAMA_EMBED_MODEL,
            url=f"{Config.OLLAMA_BASE_URL}/api/embeddings",
        )
        _chroma_client = chromadb.PersistentClient(
            path=Config.CHROMA_DB_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _long_term_collection = _chroma_client.get_or_create_collection(
            name="long_term_memory",
            embedding_function=_embed_fn,
            metadata={"description": "长期对话记忆"},
        )
        _rag_collection = _chroma_client.get_or_create_collection(
            name="rag_documents",
            embedding_function=_embed_fn,
            metadata={"description": "RAG文档库"},
        )
        # 实际调用一次嵌入验证模型是否可用
        _embed_fn(["test"])
        _chroma_available = True
        logger.info("ChromaDB 向量库初始化成功")
    except Exception as e:
        _chroma_client = None
        _long_term_collection = None
        _rag_collection = None
        _chroma_available = False
        logger.warning("ChromaDB 向量库暂不可用（嵌入模型未就绪）: %s", e)
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
    if not _ensure_chroma():
        return
    summary_text = f"问题: {question}\n回答: {answer[:300]}"
    meta = {
        "user_id": user_id,
        "question": question[:500],
        "answer": answer[:500],
        "timestamp": datetime.now().isoformat(),
    }
    if metadata:
        meta.update(metadata)
    doc_id = str(uuid.uuid4())[:12]
    _long_term_collection.add(
        ids=[doc_id],
        documents=[summary_text],
        metadatas=[meta],
    )
    logger.debug("已存入长期记忆: %s", doc_id)


def retrieve_long_term_memories(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = None,
) -> List[Dict]:
    """
    从长期记忆中检索与当前查询最相关的历史对话。
    """
    if not _ensure_chroma():
        return []
    if top_k is None:
        top_k = Config.LONG_TERM_TOP_K
    where_filter = None
    if user_id:
        where_filter = {"user_id": user_id}
    results = _long_term_collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where_filter,
    )
    memories = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            memories.append({
                "content": doc,
                "metadata": meta,
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })
    return memories


def format_memories_context(memories: List[Dict]) -> str:
    """
    将检索到的长期记忆格式化为可注入LLM的上下文文本。

    Args:
        memories: retrieve_long_term_memories 的返回结果

    Returns:
        str: 格式化后的记忆上下文
    """
    if not memories:
        return ""
    lines = ["[长期记忆 - 相关历史对话]"]
    for i, mem in enumerate(memories, 1):
        ts = mem.get("metadata", {}).get("timestamp", "未知时间")
        lines.append(f"{i}. [{ts}] {mem['content'][:200]}")
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
    # 按标题分段
    sections = re.split(r'\n(?=#{1,6}\s)', content)
    chunks = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 提取标题
        title_match = re.match(r'^(#{1,6})\s+(.+)', section)
        section_title = title_match.group(2).strip() if title_match else ""
        # 去掉标题行，保留正文
        body = re.sub(r'^#{1,6}\s+.+\n?', '', section, count=1) if title_match else section

        # 按段落分割
        paragraphs = re.split(r'\n\s*\n', body)
        current_chunk = ""
        current_title = section_title

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}".strip() if current_chunk else para
            else:
                # 当前块已满，保存
                if current_chunk:
                    chunks.append({"text": current_chunk, "section_title": current_title})

                # 如果段落本身就超长，退化为滑动窗口
                if len(para) > chunk_size:
                    start = 0
                    while start < len(para):
                        end = start + chunk_size
                        chunks.append({
                            "text": para[start:end],
                            "section_title": current_title,
                        })
                        start += (chunk_size - chunk_overlap)
                    current_chunk = ""
                else:
                    # 保留 overlap：取上一块末尾 chunk_overlap 字符
                    if chunks and chunk_overlap > 0:
                        prev_text = chunks[-1]["text"]
                        overlap_text = prev_text[-chunk_overlap:] if len(prev_text) > chunk_overlap else prev_text
                        current_chunk = f"{overlap_text}\n{para}".strip()
                    else:
                        current_chunk = para

        # 保存最后剩余块
        if current_chunk:
            chunks.append({"text": current_chunk, "section_title": current_title})

    # 为每个切片添加前后链接
    for i, chunk in enumerate(chunks):
        chunk["prev_chunk_id"] = i - 1 if i > 0 else None
        chunk["next_chunk_id"] = i + 1 if i < len(chunks) - 1 else None

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
    if not _ensure_chroma():
        return 0

    # 语义感知切片
    chunks = _semantic_chunk(content, chunk_size, chunk_overlap)
    if not chunks:
        return 0

    # 批量存入向量库
    ids = [f"{filename}_{i}" for i in range(len(chunks))]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {
            "filename": filename,
            "chunk_index": i,
            "section_title": c.get("section_title", ""),
            "prev_chunk_id": str(c.get("prev_chunk_id", "")),
            "next_chunk_id": str(c.get("next_chunk_id", "")),
            "timestamp": datetime.now().isoformat(),
        }
        for i, c in enumerate(chunks)
    ]
    _rag_collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )
    logger.info("RAG文档已存入: %s (%d个切片)", filename, len(chunks))
    return len(chunks)


def retrieve_rag_context(
    query: str,
    top_k: int = 3,
) -> str:
    """
    从RAG文档库中检索与查询最相关的文档片段。
    """
    if not _ensure_chroma():
        return ""
    results = _rag_collection.query(
        query_texts=[query],
        n_results=top_k,
    )
    if not results["documents"] or not results["documents"][0]:
        return ""
    # 格式化检索结果
    parts = ["[RAG文档检索结果]"]
    for i, doc in enumerate(results["documents"][0], 1):
        meta = results["metadatas"][0][i] if results["metadatas"] else {}
        source = meta.get("filename", "未知文档")
        section = meta.get("section_title", "")
        section_info = f" (章节: {section})" if section else ""
        parts.append(f"--- 来源: {source}{section_info} (片段{i}) ---\n{doc[:500]}")
    return "\n".join(parts)


def list_documents() -> List[Dict]:
    """
    列出RAG文档库中所有已上传的文档及其切片数。
    """
    if not _ensure_chroma():
        return []
    all_data = _rag_collection.get()
    if not all_data["metadatas"]:
        return []
    # 按文件名聚合
    doc_map = {}
    for meta in all_data["metadatas"]:
        fname = meta.get("filename", "未知")
        if fname not in doc_map:
            doc_map[fname] = {"filename": fname, "chunks": 0, "timestamp": ""}
        doc_map[fname]["chunks"] += 1
        doc_map[fname]["timestamp"] = meta.get("timestamp", "")
    return list(doc_map.values())


def delete_document(filename: str) -> bool:
    """
    从RAG库中删除指定文档的所有切片。
    """
    if not _ensure_chroma():
        return False
    all_data = _rag_collection.get()
    ids_to_delete = []
    for i, meta in enumerate(all_data["metadatas"]):
        if meta.get("filename") == filename:
            ids_to_delete.append(all_data["ids"][i])
    if ids_to_delete:
        _rag_collection.delete(ids=ids_to_delete)
        logger.info("RAG文档已删除: %s (%d个切片)", filename, len(ids_to_delete))
        return True
    return False

