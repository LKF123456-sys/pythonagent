"""
异步 SQLite 数据库模块：替代 JSON 文件存储，支持多用户并发。
提供 users / conversations / messages 三张表的 CRUD 操作。
"""

import aiosqlite
from datetime import datetime
from typing import List, Dict, Optional

from config import Config
from logger import setup_logger

logger = setup_logger("database", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# 数据库初始化
# ============================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '未命名对话',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
"""


async def init_db() -> None:
    """初始化数据库表结构（幂等操作）。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("SQLite 数据库已初始化: %s", Config.DATABASE_PATH)


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接（用于 FastAPI 依赖注入）。"""
    db = await aiosqlite.connect(Config.DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db


# ============================================================
# 用户 CRUD
# ============================================================

async def create_user(username: str, password_hash: str) -> Optional[int]:
    """创建新用户，返回 user_id。用户名已存在则返回 None。"""
    try:
        async with aiosqlite.connect(Config.DATABASE_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            await db.commit()
            user_id = cursor.lastrowid
            logger.info("用户已创建: %s (id=%d)", username, user_id)
            return user_id
    except aiosqlite.IntegrityError:
        logger.warning("用户名已存在: %s", username)
        return None


async def get_user_by_username(username: str) -> Optional[Dict]:
    """根据用户名查询用户。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, username, password_hash, created_at, is_active FROM users WHERE username = ?",
            (username,),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def get_user_by_id(user_id: int) -> Optional[Dict]:
    """根据 ID 查询用户。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, username, created_at, is_active FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


# ============================================================
# 会话 CRUD
# ============================================================

async def create_conversation(conv_id: str, user_id: int, title: str) -> None:
    """创建新会话。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        now = datetime.now().isoformat()
        await db.execute(
            "INSERT OR REPLACE INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (conv_id, user_id, title[:50], now, now),
        )
        await db.commit()
    logger.debug("会话已创建: %s (user=%d)", conv_id, user_id)


async def list_conversations(user_id: int) -> List[Dict]:
    """获取用户的所有会话，按更新时间倒序。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id as session_id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_conversation_time(conv_id: str) -> None:
    """更新会话的最后活跃时间。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), conv_id),
        )
        await db.commit()


async def delete_conversation(conv_id: str) -> None:
    """删除会话及其所有消息。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        await db.commit()
    logger.debug("会话已删除: %s", conv_id)


async def get_conversation(conv_id: str, user_id: int) -> Optional[Dict]:
    """获取单个会话信息（验证用户归属）。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id as session_id, title, created_at, updated_at FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


# ============================================================
# 消息 CRUD
# ============================================================

async def add_message(conv_id: str, role: str, content: str) -> None:
    """添加一条消息到会话。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conv_id, role, content),
        )
        await db.commit()


async def get_messages(conv_id: str, limit: int = 100) -> List[Dict]:
    """获取会话的消息列表（按时间正序）。"""
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
            (conv_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

