"""
异步 SQLite 数据库模块：替代 JSON 文件存储，支持多用户并发。
提供 users / conversations / messages 三张表的 CRUD 操作。
"""

# 导入aiosqlite模块，用于异步SQLite数据库操作
import aiosqlite
# 从datetime模块导入datetime类，用于时间处理
from datetime import datetime
# 导入类型提示相关模块
from typing import List, Dict, Optional

# 导入配置模块
from config import Config
# 导入日志设置函数
from logger import setup_logger

# 初始化日志记录器
logger = setup_logger("database", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# 数据库初始化
# ============================================================

# 数据库表结构定义SQL语句
_SCHEMA = """
-- 用户表：存储用户账号信息
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 用户ID，自增主键
    username TEXT UNIQUE NOT NULL,         -- 用户名，唯一且非空
    password_hash TEXT NOT NULL,           -- 密码哈希值，非空
    created_at TEXT NOT NULL DEFAULT (datetime('now')),  -- 创建时间，默认当前时间
    is_active INTEGER NOT NULL DEFAULT 1   -- 账户是否激活，1=激活，0=禁用
);

-- 会话表：存储对话会话信息
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,                   -- 会话ID，字符串主键
    user_id INTEGER NOT NULL,              -- 所属用户ID，外键关联users表
    title TEXT NOT NULL DEFAULT '未命名对话', -- 会话标题，默认"未命名对话"
    created_at TEXT NOT NULL DEFAULT (datetime('now')),  -- 创建时间
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),  -- 更新时间
    FOREIGN KEY (user_id) REFERENCES users(id)  -- 外键约束，关联用户表
);

-- 消息表：存储对话中的每条消息
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 消息ID，自增主键
    conversation_id TEXT NOT NULL,         -- 所属会话ID，外键关联conversations表
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),  -- 消息角色：user或assistant
    content TEXT NOT NULL,                 -- 消息内容，非空
    created_at TEXT NOT NULL DEFAULT (datetime('now')),  -- 创建时间
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE  -- 外键约束，级联删除
);

-- 索引：加速按用户ID查询会话
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
-- 索引：加速按会话ID查询消息
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
"""


async def init_db() -> None:
    """初始化数据库表结构（幂等操作）。"""
    # 异步连接到SQLite数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 执行表结构创建SQL语句
        await db.executescript(_SCHEMA)
        # 提交事务
        await db.commit()
    # 记录数据库初始化日志
    logger.info("SQLite 数据库已初始化: %s", Config.DATABASE_PATH)


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接（用于 FastAPI 依赖注入）。"""
    # 创建新的数据库连接
    db = await aiosqlite.connect(Config.DATABASE_PATH)
    # 设置行工厂，使查询结果可以通过字段名访问
    db.row_factory = aiosqlite.Row
    # 返回数据库连接对象
    return db


# ============================================================
# 用户 CRUD
# ============================================================

async def create_user(username: str, password_hash: str) -> Optional[int]:
    """创建新用户，返回 user_id。用户名已存在则返回 None。"""
    try:
        # 异步连接数据库
        async with aiosqlite.connect(Config.DATABASE_PATH) as db:
            # 执行插入用户SQL语句
            cursor = await db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            # 提交事务
            await db.commit()
            # 获取新插入用户的ID
            user_id = cursor.lastrowid
            # 记录用户创建日志
            logger.info("用户已创建: %s (id=%d)", username, user_id)
            # 返回用户ID
            return user_id
    except aiosqlite.IntegrityError:
        # 捕获唯一约束冲突（用户名已存在）
        logger.warning("用户名已存在: %s", username)
        # 返回None表示创建失败
        return None


async def get_user_by_username(username: str) -> Optional[Dict]:
    """根据用户名查询用户。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 设置行工厂，支持字段名访问
        db.row_factory = aiosqlite.Row
        # 执行按用户名查询SQL
        cursor = await db.execute(
            "SELECT id, username, password_hash, created_at, is_active FROM users WHERE username = ?",
            (username,),
        )
        # 获取查询结果的第一行
        row = await cursor.fetchone()
        # 如果找到用户，转换为字典返回
        if row:
            return dict(row)
        # 未找到用户返回None
        return None


async def get_user_by_id(user_id: int) -> Optional[Dict]:
    """根据 ID 查询用户。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 设置行工厂
        db.row_factory = aiosqlite.Row
        # 执行按ID查询SQL（注意：不查询password_hash字段）
        cursor = await db.execute(
            "SELECT id, username, created_at, is_active FROM users WHERE id = ?",
            (user_id,),
        )
        # 获取第一行结果
        row = await cursor.fetchone()
        # 如果找到，转换为字典返回
        if row:
            return dict(row)
        # 未找到返回None
        return None


# ============================================================
# 会话 CRUD
# ============================================================

async def create_conversation(conv_id: str, user_id: int, title: str) -> None:
    """创建新会话。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 获取当前时间的ISO格式字符串
        now = datetime.now().isoformat()
        # 执行插入或替换会话SQL（INSERT OR REPLACE保证幂等）
        await db.execute(
            "INSERT OR REPLACE INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (conv_id, user_id, title[:50], now, now),
        )
        # 提交事务
        await db.commit()
    # 记录调试日志
    logger.debug("会话已创建: %s (user=%d)", conv_id, user_id)


async def list_conversations(user_id: int) -> List[Dict]:
    """获取用户的所有会话，按更新时间倒序。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 设置行工厂
        db.row_factory = aiosqlite.Row
        # 执行查询用户会话列表SQL，按更新时间倒序排列
        cursor = await db.execute(
            "SELECT id as session_id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        # 获取所有结果行
        rows = await cursor.fetchall()
        # 将每一行转换为字典，组成列表返回
        return [dict(r) for r in rows]


async def update_conversation_time(conv_id: str) -> None:
    """更新会话的最后活跃时间。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 执行更新会话时间SQL
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), conv_id),
        )
        # 提交事务
        await db.commit()


async def delete_conversation(conv_id: str) -> None:
    """删除会话及其所有消息。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 先删除该会话的所有消息（由于外键级联删除，理论上不需要，但显式删除更安全）
        await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        # 删除会话记录
        await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        # 提交事务
        await db.commit()
    # 记录调试日志
    logger.debug("会话已删除: %s", conv_id)


async def get_conversation(conv_id: str, user_id: int) -> Optional[Dict]:
    """获取单个会话信息（验证用户归属）。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 设置行工厂
        db.row_factory = aiosqlite.Row
        # 执行查询会话SQL，同时验证会话属于指定用户
        cursor = await db.execute(
            "SELECT id as session_id, title, created_at, updated_at FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        )
        # 获取第一行结果
        row = await cursor.fetchone()
        # 如果找到，转换为字典返回
        if row:
            return dict(row)
        # 未找到返回None
        return None


# ============================================================
# 消息 CRUD
# ============================================================

async def add_message(conv_id: str, role: str, content: str) -> None:
    """添加一条消息到会话。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 执行插入消息SQL
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conv_id, role, content),
        )
        # 提交事务
        await db.commit()


async def get_messages(conv_id: str, limit: int = 100) -> List[Dict]:
    """获取会话的消息列表（按时间正序）。"""
    # 异步连接数据库
    async with aiosqlite.connect(Config.DATABASE_PATH) as db:
        # 设置行工厂
        db.row_factory = aiosqlite.Row
        # 执行查询消息SQL，按创建时间正序排列，限制返回数量
        cursor = await db.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
            (conv_id, limit),
        )
        # 获取所有结果行
        rows = await cursor.fetchall()
        # 将每一行转换为字典，组成列表返回
        return [dict(r) for r in rows]
