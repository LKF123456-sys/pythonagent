"""消息数据访问 + Token 统计（PostgreSQL 方言）。"""  # 模块级文档字符串，描述消息数据访问层

from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.db.connection import get_pool  # 导入数据库连接池获取函数

logger = setup_logger("repo.message")  # 创建名为repo.message的日志记录器


async def add_message(conv_id: str, role: str, content: str, token_count: int = 0, image_filename: str = "") -> None:  # 定义添加消息协程函数
    """添加一条消息到会话。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    await pool.execute(  # 执行插入
        "INSERT INTO messages (conversation_id, role, content, token_count, image_filename) VALUES ($1, $2, $3, $4, $5)",  # SQL插入语句
        (conv_id, role, content, token_count, image_filename),  # 参数：会话ID、角色、内容、token数、图片文件名
    )


async def get_messages(conv_id: str, limit: int = 200) -> list[dict]:  # 定义获取消息列表协程函数
    """获取会话的消息列表（按时间正序）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    return await pool.fetch_all(  # 执行查询并返回所有行
        "SELECT role, content, token_count, image_filename, created_at "  # 查询字段
        "FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC LIMIT $2",  # 条件、排序和限制
        (conv_id, limit),  # 参数：会话ID和限制数
    )


async def get_total_token_count(user_id: int) -> int:  # 定义获取累计Token用量协程函数
    """获取用户的累计 token 用量。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    row = await pool.fetch_one(  # 执行查询并返回单行
        "SELECT COALESCE(SUM(m.token_count), 0) as total "  # 求和，NULL转为0
        "FROM messages m JOIN conversations c ON m.conversation_id = c.id "  # 关联会话表
        "WHERE c.user_id = $1",  # 条件：用户ID
        (user_id,),  # 参数
    )
    return row["total"] if row else 0  # 返回总量，无结果则0


async def get_daily_token_stats(user_id: int, days: int = 30) -> list[dict]:  # 定义按日Token统计协程函数
    """按日聚合 token 用量（最近 N 天）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    return await pool.fetch_all(  # 执行查询并返回所有行
        "SELECT DATE(m.created_at)::text as date, "  # 日期字段，转为文本
        "COALESCE(SUM(m.token_count), 0) as total_tokens, "  # 当日token总和
        "COUNT(*) as message_count "  # 当日消息数
        "FROM messages m JOIN conversations c ON m.conversation_id = c.id "  # 关联会话表
        "WHERE c.user_id = $1 AND m.created_at >= CURRENT_DATE - make_interval(days => $2::int) "  # 条件：用户和时间范围
        "GROUP BY DATE(m.created_at) ORDER BY date ASC",  # 按日期分组和排序
        (user_id, days),  # 参数：用户ID和天数
    )


async def get_system_stats() -> dict:  # 定义系统统计协程函数
    """系统级统计（管理后台）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    users = await pool.fetch_one("SELECT COUNT(*) as c FROM users")  # 统计用户数
    convs = await pool.fetch_one("SELECT COUNT(*) as c FROM conversations")  # 统计会话数
    msgs = await pool.fetch_one("SELECT COUNT(*) as c FROM messages")  # 统计消息数
    tokens = await pool.fetch_one("SELECT COALESCE(SUM(token_count), 0) as c FROM messages")  # 统计token总量
    return {  # 返回统计结果字典
        "user_count": users["c"] if users else 0,  # 用户数
        "conversation_count": convs["c"] if convs else 0,  # 会话数
        "message_count": msgs["c"] if msgs else 0,  # 消息数
        "total_tokens": tokens["c"] if tokens else 0,  # token总量
    }
