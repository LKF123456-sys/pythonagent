"""Test conversations API directly."""
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
    # Test list_conversations for user 7
    print("=== Testing conversation_repo.list_conversations(user_id=7) ===")
    rows = await conversation_repo.list_conversations(7, "general")
    print(f"Got {len(rows)} rows")
    for r in rows[:3]:
        print(f"  raw row: {dict(r)}")
        try:
            item = ConversationItem(**r)
            print(f"  ConversationItem OK: {item.session_id} / {item.title}")
        except Exception as e:
            print(f"  ConversationItem ERROR: {e}")

    # Test get_messages
    if rows:
        sid = rows[0]["session_id"]
        print(f"\n=== Testing message_repo.get_messages({sid}) ===")
        msgs = await message_repo.get_messages(sid)
        print(f"Got {len(msgs)} messages")
        for m in msgs[:3]:
            print(f"  raw row: {dict(m)}")
            try:
                item = MessageItem(**m)
                print(f"  MessageItem OK: {item.role}")
            except Exception as e:
                print(f"  MessageItem ERROR: {e}")

    await pool.close()


asyncio.run(main())
