"""一次性脚本：将指定文档入库到 RAG 向量知识库。

用法：
    python scripts/ingest_doc.py <文件路径>

依赖：PostgreSQL（pgvector）+ Ollama（nomic-embed-text）均需运行。
"""

import asyncio
import sys
import os

# 确保项目根 + libs 在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIBS_DIR = os.path.join(_PROJECT_ROOT, "libs")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if os.path.isdir(_LIBS_DIR) and _LIBS_DIR not in sys.path:
    sys.path.insert(0, _LIBS_DIR)

from app.core.config import get_settings
from app.db.connection import init_pool, close_pool
from app.memory.vector_store import VectorStore
from app.memory.rag import semantic_chunk
from app.services.document_service import parse_document


async def ingest(filepath: str) -> None:
    """解析文档 → 语义切片 → 向量化 → 存入 pgvector RAG 表。"""
    if not os.path.isfile(filepath):
        print(f"[错误] 文件不存在: {filepath}")
        return

    filename = os.path.basename(filepath)
    print(f"[1/4] 读取文件: {filename}")
    with open(filepath, "rb") as f:
        file_bytes = f.read()
    print(f"      文件大小: {len(file_bytes)} 字节")

    print("[2/4] 解析文档内容...")
    text = parse_document(file_bytes, filename)
    print(f"      提取文本: {len(text)} 字符")

    print("[3/4] 语义切片...")
    chunks = semantic_chunk(text)
    print(f"      切片数量: {len(chunks)}")

    print("[4/4] 向量化入库（调用 Ollama 嵌入 + pgvector 存储）...")
    # 初始化连接池
    await init_pool()

    store = VectorStore()
    await store.initialize()
    if not store.available:
        print("[错误] pgvector 不可用，请检查数据库")
        await close_pool()
        return

    count = await store.add_document_chunks(chunks, filename)
    await close_pool()

    if count > 0:
        print(f"\n[OK] 入库成功! 文档 '{filename}' 已存入 RAG 知识库 ({count} 个向量切片)")
    else:
        print("\n[FAIL] 入库失败: 嵌入模型可能未就绪")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/ingest_doc.py <文件路径>")
        sys.exit(1)
    asyncio.run(ingest(sys.argv[1]))
