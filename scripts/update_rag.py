"""删除旧版文档并重新入库最新版本"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs"))

from app.db.connection import init_pool, close_pool
from app.memory.vector_store import VectorStore
from app.memory.rag import semantic_chunk
from app.services.document_service import parse_document

FILENAME = "合肥工业产业全景知识库.txt"

async def main():
    await init_pool()
    store = VectorStore()
    await store.initialize()

    # Step 1: Delete old chunks
    print("[1/2] Deleting old version...")
    deleted = await store.delete_document(FILENAME)
    print(f"      Deleted: {deleted}")

    # Step 2: Re-ingest updated file
    filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", FILENAME)
    with open(filepath, "rb") as f:
        file_bytes = f.read()
    print(f"[2/2] Re-ingesting updated doc ({len(file_bytes)} bytes)...")
    text = parse_document(file_bytes, FILENAME)
    chunks = semantic_chunk(text)
    print(f"      Chunks: {len(chunks)}")
    count = await store.add_document_chunks(chunks, FILENAME)
    print(f"      Stored: {count} chunks")

    await close_pool()
    print(f"\n[OK] Update complete: {count} vector chunks in RAG")

asyncio.run(main())

