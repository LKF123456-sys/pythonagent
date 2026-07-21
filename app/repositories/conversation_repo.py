"""会话数据访问（PostgreSQL 方言）。"""

from datetime import datetime
from typing import Optional

from app.core.logging import setup_logger
from app.db.connection import get_pool

logger = setup_logger("repo.conversation")


async def create_conversation(conv_id: str, user_id: int, title: str, conv_type: str = "general") -> None:
    """创建新会话（幂等）。"""
    pool = get_pool()
    now = datetime.now()
    await pool.execute(
        "INSERT INTO conversations (id, user_id, title, conv_type, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6) "
        "ON CONFLICT (id) DO UPDATE SET title = $3, updated_at = $6",
        (conv_id, user_id, title[:50], conv_type, now, now),
    )


async def list_conversations(user_id: int, conv_type: str = "general") -> list[dict]:
    """获取用户指定类型的会话，按更新时间倒序。"""
    pool = get_pool()
    return await pool.fetch_all(
        "SELECT id as session_id, title, created_at, updated_at "
        "FROM conversations WHERE user_id = $1 AND conv_type = $2 ORDER BY updated_at DESC",
        (user_id, conv_type),
    )


async def get_conversation(conv_id: str, user_id: int) -> Optional[dict]:
    """获取单个会话（验证用户归属）。"""
    pool = get_pool()
    return await pool.fetch_one(
        "SELECT id as session_id, title, created_at, updated_at "
        "FROM conversations WHERE id = $1 AND user_id = $2",
        (conv_id, user_id),
    )


async def update_conversation_time(conv_id: str) -> None:
    """更新会话的最后活跃时间。"""
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET updated_at = $1 WHERE id = $2",
        (datetime.now(), conv_id),
    )


async def rename_conversation(conv_id: str, user_id: int, title: str) -> bool:
    """重命名会话，返回是否影响行。"""
    pool = get_pool()
    row = await pool.fetch_one(
        "UPDATE conversations SET title = $1, updated_at = $2 "
        "WHERE id = $3 AND user_id = $4 RETURNING id",
        (title[:100], datetime.now(), conv_id, user_id),
    )
    return row is not None


async def delete_conversation(conv_id: str) -> None:
    """删除会话（消息由 ON DELETE CASCADE 自动级联删除）。"""
    pool = get_pool()
    await pool.execute("DELETE FROM conversations WHERE id = $1", (conv_id,))
    logger.debug("会话已删除: %s", conv_id)

