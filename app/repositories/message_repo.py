"""消息数据访问 + Token 统计（PostgreSQL 方言）。"""

from app.core.logging import setup_logger
from app.db.connection import get_pool

logger = setup_logger("repo.message")


async def add_message(conv_id: str, role: str, content: str, token_count: int = 0, image_filename: str = "") -> None:
    """添加一条消息到会话。"""
    pool = get_pool()
    await pool.execute(
        "INSERT INTO messages (conversation_id, role, content, token_count, image_filename) VALUES ($1, $2, $3, $4, $5)",
        (conv_id, role, content, token_count, image_filename),
    )


async def get_messages(conv_id: str, limit: int = 200) -> list[dict]:
    """获取会话的消息列表（按时间正序）。"""
    pool = get_pool()
    return await pool.fetch_all(
        "SELECT role, content, token_count, image_filename, created_at "
        "FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC LIMIT $2",
        (conv_id, limit),
    )


async def get_total_token_count(user_id: int) -> int:
    """获取用户的累计 token 用量。"""
    pool = get_pool()
    row = await pool.fetch_one(
        "SELECT COALESCE(SUM(m.token_count), 0) as total "
        "FROM messages m JOIN conversations c ON m.conversation_id = c.id "
        "WHERE c.user_id = $1",
        (user_id,),
    )
    return row["total"] if row else 0


async def get_daily_token_stats(user_id: int, days: int = 30) -> list[dict]:
    """按日聚合 token 用量（最近 N 天）。"""
    pool = get_pool()
    return await pool.fetch_all(
        "SELECT DATE(m.created_at)::text as date, "
        "COALESCE(SUM(m.token_count), 0) as total_tokens, "
        "COUNT(*) as message_count "
        "FROM messages m JOIN conversations c ON m.conversation_id = c.id "
        "WHERE c.user_id = $1 AND m.created_at >= CURRENT_DATE - make_interval(days => $2::int) "
        "GROUP BY DATE(m.created_at) ORDER BY date ASC",
        (user_id, days),
    )


async def get_system_stats() -> dict:
    """系统级统计（管理后台）。"""
    pool = get_pool()
    users = await pool.fetch_one("SELECT COUNT(*) as c FROM users")
    convs = await pool.fetch_one("SELECT COUNT(*) as c FROM conversations")
    msgs = await pool.fetch_one("SELECT COUNT(*) as c FROM messages")
    tokens = await pool.fetch_one("SELECT COALESCE(SUM(token_count), 0) as c FROM messages")
    return {
        "user_count": users["c"] if users else 0,
        "conversation_count": convs["c"] if convs else 0,
        "message_count": msgs["c"] if msgs else 0,
        "total_tokens": tokens["c"] if tokens else 0,
    }
