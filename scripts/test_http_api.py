"""通过 HTTP 测试 conversations API - 直接生成 token。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs"))

from app.db.connection import init_pool, get_pool
from app.core.security import create_access_token


async def main():
    await init_pool()
    pool = get_pool()
    
    # Find user 7
    user = await pool.fetch_one("SELECT id, username FROM users WHERE id = 7")
    if user:
        print(f"User 7: {dict(user)}")
        token = create_access_token(user["id"], user["username"])
        print(f"Token: {token[:40]}...")
    else:
        print("User 7 not found!")
        return
    
    await pool.close()

    import httpx
    base = "http://localhost:8000"
    async with httpx.AsyncClient(base_url=base) as client:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Test conversations list
        r2 = await client.get("/api/conversations", params={"conv_type": "general"}, headers=headers)
        print(f"\nConversations: {r2.status_code}")
        if r2.status_code == 200:
            data = r2.json()
            convs = data.get("conversations", [])
            print(f"  Count: {len(convs)}")
            for c in convs[:3]:
                print(f"  - {c['session_id'][:8]}... title={c['title']} created_at={c['created_at']}")
        else:
            print(f"  ERROR: {r2.text[:300]}")

        # Test messages for first conversation
        if r2.status_code == 200 and convs:
            sid = convs[0]["session_id"]
            r3 = await client.get(f"/api/conversations/{sid}/messages", headers=headers)
            print(f"\nMessages ({sid[:8]}...): {r3.status_code}")
            if r3.status_code == 200:
                msgs = r3.json().get("messages", [])
                print(f"  Count: {len(msgs)}")
                for m in msgs[:3]:
                    img = m.get("image_filename", "FIELD_MISSING")
                    print(f"  - role={m['role']} image_filename='{img}'")


asyncio.run(main())
