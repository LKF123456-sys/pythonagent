"""用户数据访问 + Refresh Token / 黑名单管理（PostgreSQL 方言）。"""  # 模块级文档字符串，描述用户数据访问层

from datetime import datetime  # 从datetime导入datetime类
from typing import Optional  # 从typing导入Optional，用于可选类型注解

from asyncpg import UniqueViolationError  # 从asyncpg导入唯一约束冲突异常

from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.db.connection import get_pool  # 导入数据库连接池获取函数

logger = setup_logger("repo.user")  # 创建名为repo.user的日志记录器


# ============================================================  # 分隔注释
# 用户 CRUD  # 说明该部分为用户增删改查操作
# ============================================================  # 分隔注释

async def create_user(username: str, password_hash: str) -> Optional[int]:  # 定义创建用户协程函数
    """创建新用户，返回 user_id。用户名已存在则返回 None。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    try:  # 尝试插入用户
        return await pool.execute_returning(  # 执行插入并返回新ID
            "INSERT INTO users (username, password_hash) VALUES ($1, $2) RETURNING id",  # SQL插入语句
            (username, password_hash),  # 参数：用户名和密码哈希
        )
    except UniqueViolationError:  # 如果用户名唯一约束冲突
        logger.warning("用户名已存在: %s", username)  # 记录警告日志
        return None  # 返回None表示创建失败


async def get_user_by_username(username: str) -> Optional[dict]:  # 定义按用户名查询用户协程函数
    """根据用户名查询用户（含密码哈希，用于登录验证）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    return await pool.fetch_one(  # 执行查询并返回单行
        "SELECT id, username, password_hash, created_at, is_active, is_admin "  # SQL查询字段
        "FROM users WHERE username = $1",  # SQL查询条件
        (username,),  # 参数：用户名
    )


async def get_user_by_id(user_id: int) -> Optional[dict]:  # 定义按ID查询用户协程函数
    """根据 ID 查询用户（不含密码哈希）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    return await pool.fetch_one(  # 执行查询并返回单行
        "SELECT id, username, created_at, is_active, is_admin FROM users WHERE id = $1",  # SQL查询语句
        (user_id,),  # 参数：用户ID
    )


async def list_users() -> list[dict]:  # 定义列出所有用户协程函数
    """列出所有用户（管理后台）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    return await pool.fetch_all(  # 执行查询并返回所有行
        "SELECT id, username, created_at, is_active, is_admin FROM users ORDER BY id"  # SQL查询语句，按ID排序
    )


async def set_user_active(user_id: int, is_active: bool) -> bool:  # 定义设置用户激活状态协程函数
    """启用/禁用用户，返回是否影响行。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    row = await pool.fetch_one(  # 执行更新并返回影响的行
        "UPDATE users SET is_active = $1 WHERE id = $2 RETURNING id",  # SQL更新语句
        (1 if is_active else 0, user_id),  # 参数：激活状态（1/0）和用户ID
    )
    return row is not None  # 返回是否影响了行


# ============================================================  # 分隔注释
# Refresh Token 管理  # 说明该部分为刷新令牌管理
# ============================================================  # 分隔注释

async def store_refresh_token(jti: str, user_id: int, expires_at: datetime) -> None:  # 定义存储刷新令牌协程函数
    """存储 Refresh Token 的 jti（用于撤销追踪）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    await pool.execute(  # 执行SQL
        "INSERT INTO refresh_tokens (jti, user_id, expires_at) VALUES ($1, $2, $3) "  # 插入语句
        "ON CONFLICT (jti) DO UPDATE SET user_id = $2, expires_at = $3",  # 冲突时更新
        (jti, user_id, expires_at.isoformat()),  # 参数：jti、用户ID、过期时间
    )


async def is_refresh_token_valid(jti: str) -> bool:  # 定义检查刷新令牌有效性协程函数
    """检查 Refresh Token 是否有效（未被撤销）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    row = await pool.fetch_one(  # 执行查询
        "SELECT revoked FROM refresh_tokens WHERE jti = $1", (jti,)  # SQL查询语句和参数
    )
    return row is not None and not row["revoked"]  # 存在且未被撤销则为有效


async def revoke_refresh_token(jti: str) -> None:  # 定义撤销刷新令牌协程函数
    """撤销 Refresh Token。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    await pool.execute(  # 执行更新
        "UPDATE refresh_tokens SET revoked = 1 WHERE jti = $1", (jti,)  # SQL更新语句和参数
    )


# ============================================================  # 分隔注释
# Access Token 黑名单  # 说明该部分为访问令牌黑名单管理
# ============================================================  # 分隔注释

async def blacklist_access_token(jti: str, expires_at: datetime) -> None:  # 定义加入黑名单协程函数
    """将 Access Token 的 jti 加入黑名单（登出时调用）。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    await pool.execute(  # 执行插入
        "INSERT INTO token_blacklist (jti, expires_at) VALUES ($1, $2) "  # 插入语句
        "ON CONFLICT (jti) DO NOTHING",  # 冲突时忽略
        (jti, expires_at.isoformat()),  # 参数：jti和过期时间
    )


async def is_access_token_blacklisted(jti: str) -> bool:  # 定义检查黑名单协程函数
    """检查 Access Token 是否已被撤销。"""  # 函数文档字符串
    pool = get_pool()  # 获取数据库连接池
    row = await pool.fetch_one(  # 执行查询
        "SELECT jti FROM token_blacklist WHERE jti = $1", (jti,)  # SQL查询语句和参数
    )
    return row is not None  # 存在则表示已被撤销
