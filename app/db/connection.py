"""asyncpg 连接池：维持持久连接，提供与原 SQLitePool 兼容的 API。"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

import asyncpg

from app.core.config import get_settings
from app.core.logging import setup_logger

logger = setup_logger("db.pool")


class PostgresPool:
    """
    asyncpg 连接池包装器。

    提供与原 SQLitePool 相同的公共接口（execute / fetch_one / fetch_all / execute_returning），
    使上层 repositories 无需感知底层驱动变化。
    """

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def init(self) -> None:
        """初始化连接池（自动注册 pgvector 类型编解码器）。"""
        if self._pool is not None:
            return

        async def _init_conn(conn: asyncpg.Connection) -> None:
            """每个新连接创建时注册 pgvector 类型。"""
            try:
                from pgvector.asyncpg import register_vector
                await register_vector(conn)
            except Exception:
                pass  # pgvector 未安装或扩展未启用时静默跳过

        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            init=_init_conn,
        )
        logger.info("PostgreSQL 连接池已初始化 (min=%d, max=%d)", self._min_size, self._max_size)

    async def close(self) -> None:
        """关闭连接池。"""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        logger.info("PostgreSQL 连接池已关闭")

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """从池中获取连接（上下文管理器，自动归还）。"""
        if self._pool is None:
            raise RuntimeError("连接池未初始化，请先调用 init()")
        async with self._pool.acquire() as conn:
            yield conn

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """执行写操作（INSERT/UPDATE/DELETE）。"""
        if self._pool is None:
            raise RuntimeError("连接池未初始化")
        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """查询单行，返回字典或 None。"""
        if self._pool is None:
            raise RuntimeError("连接池未初始化")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return dict(row) if row else None

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询多行，返回字典列表。"""
        if self._pool is None:
            raise RuntimeError("连接池未初始化")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    async def execute_returning(self, sql: str, params: tuple = ()) -> Any:
        """执行带 RETURNING 的语句，返回第一行第一列的值。"""
        if self._pool is None:
            raise RuntimeError("连接池未初始化")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return row[0] if row else None


# 全局连接池单例（由 FastAPI lifespan 管理生命周期）
_pool: Optional[PostgresPool] = None


def get_pool() -> PostgresPool:
    """获取全局连接池实例。"""
    if _pool is None:
        raise RuntimeError("数据库连接池未初始化")
    return _pool


async def init_pool() -> PostgresPool:
    """初始化全局连接池（应用启动时调用）。"""
    global _pool
    settings = get_settings()
    _pool = PostgresPool(
        dsn=settings.DATABASE_URL,
        min_size=settings.PG_POOL_MIN_SIZE,
        max_size=settings.PG_POOL_MAX_SIZE,
    )
    await _pool.init()
    return _pool


async def close_pool() -> None:
    """关闭全局连接池（应用关闭时调用）。"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
