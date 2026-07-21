"""用户数据访问 + Refresh Token / 黑名单管理（PostgreSQL 方言）。"""

from datetime import datetime
from typing import Optional

from asyncpg import UniqueViolationError

from app.core.logging import setup_logger
from app.db.connection import get_pool

logger = setup_logger("repo.user")


# ============================================================
# 用户 CRUD
# ============================================================

async def create_user(username: str, password_hash: str) -> Optional[int]:
    """创建新用户，返回 user_id。用户名已存在则返回 None。"""
    pool = get_pool()
    try:
        return await pool.execute_returning(
            "INSERT INTO users (username, password_hash) VALUES ($1, $2) RETURNING id",
            (username, password_hash),
        )
    except UniqueViolationError:
        logger.warning("用户名已存在: %s", username)
        return None


async def get_user_by_username(username: str) -> Optional[dict]:
    """根据用户名查询用户（含密码哈希，用于登录验证）。"""
    pool = get_pool()
    return await pool.fetch_one(
        "SELECT id, username, password_hash, created_at, is_active, is_admin "
        "FROM users WHERE username = $1",
        (username,),
    )


async def get_user_by_id(user_id: int) -> Optional[dict]:
    """根据 ID 查询用户（不含密码哈希）。"""
    pool = get_pool()
    return await pool.fetch_one(
        "SELECT id, username, created_at, is_active, is_admin FROM users WHERE id = $1",
        (user_id,),
    )


async def list_users() -> list[dict]:
    """列出所有用户（管理后台）。"""
    pool = get_pool()
    return await pool.fetch_all(
        "SELECT id, username, created_at, is_active, is_admin FROM users ORDER BY id"
    )


async def set_user_active(user_id: int, is_active: bool) -> bool:
    """启用/禁用用户，返回是否影响行。"""
    pool = get_pool()
    row = await pool.fetch_one(
        "UPDATE users SET is_active = $1 WHERE id = $2 RETURNING id",
        (1 if is_active else 0, user_id),
    )
    return row is not None


# ============================================================
# Refresh Token 管理
# ============================================================

async def store_refresh_token(jti: str, user_id: int, expires_at: datetime) -> None:
    """存储 Refresh Token 的 jti（用于撤销追踪）。"""
    pool = get_pool()
    await pool.execute(
        "INSERT INTO refresh_tokens (jti, user_id, expires_at) VALUES ($1, $2, $3) "
        "ON CONFLICT (jti) DO UPDATE SET user_id = $2, expires_at = $3",
        (jti, user_id, expires_at.isoformat()),
    )


async def is_refresh_token_valid(jti: str) -> bool:
    """检查 Refresh Token 是否有效（未被撤销）。"""
    pool = get_pool()
    row = await pool.fetch_one(
        "SELECT revoked FROM refresh_tokens WHERE jti = $1", (jti,)
    )
    return row is not None and not row["revoked"]


async def revoke_refresh_token(jti: str) -> None:
    """撤销 Refresh Token。"""
    pool = get_pool()
    await pool.execute(
        "UPDATE refresh_tokens SET revoked = 1 WHERE jti = $1", (jti,)
    )


# ============================================================
# Access Token 黑名单
# ============================================================

async def blacklist_access_token(jti: str, expires_at: datetime) -> None:
    """将 Access Token 的 jti 加入黑名单（登出时调用）。"""
    pool = get_pool()
    await pool.execute(
        "INSERT INTO token_blacklist (jti, expires_at) VALUES ($1, $2) "
        "ON CONFLICT (jti) DO NOTHING",
        (jti, expires_at.isoformat()),
    )


async def is_access_token_blacklisted(jti: str) -> bool:
    """检查 Access Token 是否已被撤销。"""
    pool = get_pool()
    row = await pool.fetch_one(
        "SELECT jti FROM token_blacklist WHERE jti = $1", (jti,)
    )
    return row is not None
