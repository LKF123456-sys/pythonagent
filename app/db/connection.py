"""asyncpg 连接池：维持持久连接，提供与原 SQLitePool 兼容的 API。"""

from contextlib import asynccontextmanager  # 导入异步上下文管理器装饰器，用于实现连接的自动获取与释放
from typing import Any, AsyncGenerator, Optional  # 导入类型注解工具：任意类型、异步生成器、可选类型

import asyncpg  # 导入异步 PostgreSQL 驱动，用于异步数据库操作

from app.core.config import get_settings  # 导入配置获取函数，用于读取数据库连接配置
from app.core.logging import setup_logger  # 导入日志初始化函数，用于创建模块级日志器

logger = setup_logger("db.pool")  # 创建名为 db.pool 的日志记录器实例，用于输出连接池相关日志


class PostgresPool:
    """
    asyncpg 连接池包装器。

    提供与原 SQLitePool 相同的公共接口（execute / fetch_one / fetch_all / execute_returning），
    使上层 repositories 无需感知底层驱动变化。
    """

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):  # 构造函数：接收 DSN 与连接池大小参数
        self._dsn = dsn  # 保存 PostgreSQL 数据源名称（连接字符串）
        self._min_size = min_size  # 保存连接池最小连接数（保持的空闲连接数）
        self._max_size = max_size  # 保存连接池最大连接数（并发上限）
        self._pool: Optional[asyncpg.Pool] = None  # 初始化底层连接池对象为 None，待 init() 时创建

    async def init(self) -> None:
        """初始化连接池（自动注册 pgvector 类型编解码器）。"""
        if self._pool is not None:  # 若连接池已存在则直接返回，避免重复初始化
            return

        async def _init_conn(conn: asyncpg.Connection) -> None:
            """每个新连接创建时注册 pgvector 类型。"""
            try:  # 尝试注册 pgvector 类型编解码器
                from pgvector.asyncpg import register_vector  # 延迟导入 pgvector 异步编解码器
                await register_vector(conn)  # 在当前连接上注册 vector 类型，使其可直接读写向量
            except Exception:  # 若 pgvector 未安装或扩展未启用，则忽略异常
                pass  # pgvector 未安装或扩展未启用时静默跳过

        self._pool = await asyncpg.create_pool(  # 创建 asyncpg 连接池
            dsn=self._dsn,  # 指定连接字符串
            min_size=self._min_size,  # 指定连接池最小连接数
            max_size=self._max_size,  # 指定连接池最大连接数
            init=_init_conn,  # 指定每个新连接初始化时调用的回调（注册 pgvector）
        )
        logger.info("PostgreSQL 连接池已初始化 (min=%d, max=%d)", self._min_size, self._max_size)  # 记录连接池初始化成功的日志

    async def close(self) -> None:
        """关闭连接池。"""
        if self._pool is not None:  # 若连接池存在则关闭
            await self._pool.close()  # 关闭所有连接并释放资源
            self._pool = None  # 重置连接池对象为 None
        logger.info("PostgreSQL 连接池已关闭")  # 记录连接池已关闭的日志

    @asynccontextmanager  # 装饰为异步上下文管理器，支持 async with 语法
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """从池中获取连接（上下文管理器，自动归还）。"""
        if self._pool is None:  # 若连接池未初始化则抛出异常
            raise RuntimeError("连接池未初始化，请先调用 init()")  # 抛出运行时错误提示先调用 init()
        async with self._pool.acquire() as conn:  # 从池中获取一个连接
            yield conn  # 将连接交给调用方使用，离开上下文时自动归还

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """执行写操作（INSERT/UPDATE/DELETE）。"""
        if self._pool is None:  # 若连接池未初始化则抛出异常
            raise RuntimeError("连接池未初始化")  # 抛出运行时错误
        async with self._pool.acquire() as conn:  # 从池中获取连接
            await conn.execute(sql, *params)  # 执行 SQL 语句（无返回结果集）

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """查询单行，返回字典或 None。"""
        if self._pool is None:  # 若连接池未初始化则抛出异常
            raise RuntimeError("连接池未初始化")  # 抛出运行时错误
        async with self._pool.acquire() as conn:  # 从池中获取连接
            row = await conn.fetchrow(sql, *params)  # 执行查询并取回单行记录
            return dict(row) if row else None  # 将记录转为字典返回；无结果时返回 None

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询多行，返回字典列表。"""
        if self._pool is None:  # 若连接池未初始化则抛出异常
            raise RuntimeError("连接池未初始化")  # 抛出运行时错误
        async with self._pool.acquire() as conn:  # 从池中获取连接
            rows = await conn.fetch(sql, *params)  # 执行查询并取回所有匹配行
            return [dict(r) for r in rows]  # 将每行记录转换为字典后组成列表返回

    async def execute_returning(self, sql: str, params: tuple = ()) -> Any:
        """执行带 RETURNING 的语句，返回第一行第一列的值。"""
        if self._pool is None:  # 若连接池未初始化则抛出异常
            raise RuntimeError("连接池未初始化")  # 抛出运行时错误
        async with self._pool.acquire() as conn:  # 从池中获取连接
            row = await conn.fetchrow(sql, *params)  # 执行带 RETURNING 的语句并取回结果行
            return row[0] if row else None  # 返回第一列的值；无结果时返回 None


# 全局连接池单例（由 FastAPI lifespan 管理生命周期）
_pool: Optional[PostgresPool] = None  # 模块级单例变量，初始为 None，由 init_pool() 设置


def get_pool() -> PostgresPool:
    """获取全局连接池实例。"""
    if _pool is None:  # 若单例尚未初始化
        raise RuntimeError("数据库连接池未初始化")  # 抛出运行时错误提示调用方
    return _pool  # 返回全局连接池实例


async def init_pool() -> PostgresPool:
    """初始化全局连接池（应用启动时调用）。"""
    global _pool  # 声明使用模块级全局变量 _pool
    settings = get_settings()  # 获取应用配置对象
    _pool = PostgresPool(  # 创建 PostgresPool 实例并赋值给全局变量
        dsn=settings.DATABASE_URL,  # 使用配置中的数据库连接字符串
        min_size=settings.PG_POOL_MIN_SIZE,  # 使用配置中的最小连接数
        max_size=settings.PG_POOL_MAX_SIZE,  # 使用配置中的最大连接数
    )
    await _pool.init()  # 异步初始化连接池（创建底层 asyncpg 池）
    return _pool  # 返回初始化后的连接池实例


async def close_pool() -> None:
    """关闭全局连接池（应用关闭时调用）。"""
    global _pool  # 声明使用模块级全局变量 _pool
    if _pool is not None:  # 若连接池存在则关闭
        await _pool.close()  # 关闭连接池并释放资源
        _pool = None  # 重置全局变量为 None
