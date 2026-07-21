"""验证 RAG 知识库内容"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs"))

from app.db.connection import init_pool, close_pool

async def main():
    await init_pool()
    from app.db.connection import get_pool
    pool = get_pool()
    rows = await pool.fetch_all(
        "SELECT filename, COUNT(*) as chunks FROM rag_chunks GROUP BY filename ORDER BY COUNT(*) DESC"
    )
    print("=" * 60)
    print("RAG Knowledge Base Documents:")
    print("=" * 60)
    for r in rows:
        print(f"  {r['filename']}  ->  {r['chunks']} chunks")
    print("=" * 60)
    
    # Show a sample chunk
    sample = await pool.fetch_all(
        "SELECT content, section_title FROM rag_chunks LIMIT 1"
    )
    if sample:
        print("\nSample chunk:")
        print(f"  Section: {sample[0].get('section_title', 'N/A')}")
        print(f"  Content: {sample[0]['content'][:100]}...")
    await close_pool()

asyncio.run(main())
