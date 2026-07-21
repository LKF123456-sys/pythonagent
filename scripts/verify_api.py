"""验证 API 修复：直接测试 conversations 和 messages 端点。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs"))

from app.db.connection import init_pool, get_pool
from app.repositories import conversation_repo, message_repo
from app.models.conversation import ConversationItem, MessageItem


async def main():
    await init_pool()
    rows = await conversation_repo.list_conversations(7, "general")
    print(f"Conversations for user 7: {len(rows)} rows")
    for r in rows[:2]:
        item = ConversationItem(**r)
        print(f"  OK: {item.session_id[:8]}... title={item.title} created={item.created_at.isoformat()}")

    if rows:
        sid = rows[0]["session_id"]
        msgs = await message_repo.get_messages(sid)
        print(f"\nMessages for {sid[:8]}...: {len(msgs)} rows")
        for m in msgs[:3]:
            item = MessageItem(**m)
            print(f"  OK: role={item.role} image_filename='{item.image_filename}' content_preview={item.content[:20]}")

    print("\n=== ALL PASS ===")
    await pool.close()


asyncio.run(main())
