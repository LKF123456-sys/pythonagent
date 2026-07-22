"""会话数据访问（PostgreSQL 方言）。"""  # 模块级文档字符串，描述会话数据访问层

from datetime import datetime  # 从datetime导入datetime类
from typing import Optional  # 从typing导入Optional，用于可选类型注解

from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.db.connection import get_pool  # 导入数据库连接池获取函数

logger = setup_logger("repo.conversation")  # 创建名为repo.conversation的日志记录器


async def create_conversation(conv_id: str, user_id: int, title: str, conv_type: str = "general") -> None:  # 定义创建会话协程函数
    """创建新会话（幂等）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    now = datetime.now()  # 获取当前时间
    await pool.execute(  # 执行SQL插入
        "INSERT INTO conversations (id, user_id, title, conv_type, created_at, updated_at) "  # 插入字段
        "VALUES ($1, $2, $3, $4, $5, $6) "  # 占位符
        "ON CONFLICT (id) DO UPDATE SET title = $3, updated_at = $6",  # 冲突时更新标题和更新时间
        (conv_id, user_id, title[:50], conv_type, now, now),  # 参数，标题截断为50字符
    )


async def list_conversations(user_id: int, conv_type: str = "general") -> list[dict]:  # 定义列出会话协程函数
    """获取用户指定类型的会话，按更新时间倒序。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    return await pool.fetch_all(  # 执行查询并返回所有行
        "SELECT id as session_id, title, created_at, updated_at "  # 查询字段，id重命名为session_id
        "FROM conversations WHERE user_id = $1 AND conv_type = $2 ORDER BY updated_at DESC",  # 条件和排序
        (user_id, conv_type),  # 参数：用户ID和会话类型
    )


async def get_conversation(conv_id: str, user_id: int) -> Optional[dict]:  # 定义获取单个会话协程函数
    """获取单个会话（验证用户归属）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    return await pool.fetch_one(  # 执行查询并返回单行
        "SELECT id as session_id, title, created_at, updated_at "  # 查询字段
        "FROM conversations WHERE id = $1 AND user_id = $2",  # 条件：会话ID和用户ID
        (conv_id, user_id),  # 参数
    )


async def update_conversation_time(conv_id: str) -> None:  # 定义更新会话时间协程函数
    """更新会话的最后活跃时间。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    await pool.execute(  # 执行更新
        "UPDATE conversations SET updated_at = $1 WHERE id = $2",  # SQL更新语句
        (datetime.now(), conv_id),  # 参数：当前时间和会话ID
    )


async def rename_conversation(conv_id: str, user_id: int, title: str) -> bool:  # 定义重命名会话协程函数
    """重命名会话，返回是否影响行。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    row = await pool.fetch_one(  # 执行更新并返回影响的行
        "UPDATE conversations SET title = $1, updated_at = $2 "  # SQL更新字段
        "WHERE id = $3 AND user_id = $4 RETURNING id",  # 条件和返回ID
        (title[:100], datetime.now(), conv_id, user_id),  # 参数，标题截断为100字符
    )
    return row is not None  # 返回是否影响了行


async def delete_conversation(conv_id: str) -> None:  # 定义删除会话协程函数
    """删除会话（消息由 ON DELETE CASCADE 自动级联删除）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    await pool.execute("DELETE FROM conversations WHERE id = $1", (conv_id,))  # 执行删除
    logger.debug("会话已删除: %s", conv_id)  # 记录调试日志
