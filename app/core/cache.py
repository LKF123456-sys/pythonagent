"""Redis 分布式缓存：支持优雅降级到内存缓存。"""  # 模块级文档字符串，说明本模块提供分布式缓存能力

import asyncio  # 导入异步IO模块
import json  # 导入JSON模块，用于序列化/反序列化缓存数据
import time  # 导入时间模块，用于内存缓存的TTL时间戳
from typing import Any, Optional  # 导入类型注解

from app.core.config import get_settings  # 导入配置获取函数
from app.core.logging import setup_logger  # 导入日志设置函数

logger = setup_logger("core.cache")  # 创建缓存模块专用日志记录器

# 内存缓存回退字典：当Redis不可用时使用
_memory_cache: dict[str, tuple[Any, float]] = {}  # 内存缓存字典，键为缓存键，值为(缓存值, 过期时间戳)

class CacheService:
    """分布式缓存服务：优先使用Redis，不可用时降级到内存缓存。"""  # 类文档字符串

    def __init__(self) -> None:
        # 初始化缓存服务
        self._redis = None  # Redis客户端实例，初始为None
        self._use_memory = True  # 是否使用内存缓存模式，默认为True
        self._connected = False  # Redis连接状态标志，初始为未连接

    async def init(self) -> None:
        """初始化缓存服务：尝试连接Redis，失败则降级到内存缓存。"""  # 方法文档字符串
        settings = get_settings()  # 获取应用配置
        if not settings.REDIS_ENABLED:  # 如果未启用Redis
            logger.info("Redis缓存未启用，使用内存缓存")  # 记录日志
            return  # 直接返回，使用内存缓存模式
        try:
            # 延迟导入redis异步库
            import redis.asyncio as aioredis  # 导入redis异步客户端
            self._redis = aioredis.from_url(  # 从URL创建Redis客户端
                settings.REDIS_URL,  # 使用配置中的Redis连接地址
                decode_responses=True,  # 自动解码响应为字符串
                socket_timeout=5,  # 设置socket超时5秒
                socket_connect_timeout=5,  # 设置连接超时5秒
            )  # 创建Redis异步客户端
            await self._redis.ping()  # 发送PING测试连接是否正常
            self._use_memory = False  # Redis连接成功，关闭内存缓存模式
            self._connected = True  # 标记Redis已连接
            logger.info("Redis缓存已连接: %s", settings.REDIS_URL)  # 记录连接成功日志
        except Exception as e:  # 捕获Redis连接异常
            logger.warning("Redis连接失败，降级到内存缓存: %s", e)  # 记录降级警告
            self._use_memory = True  # 强制使用内存缓存模式
            self._connected = False  # 标记Redis未连接

    async def close(self) -> None:
        """关闭缓存连接。"""  # 方法文档字符串
        if self._redis is not None:  # 如果Redis客户端存在
            await self._redis.close()  # 关闭Redis连接
            self._connected = False  # 标记已断开
            logger.info("Redis缓存连接已关闭")  # 记录关闭日志

    async def get(self, key: str) -> Optional[Any]:
        """从缓存获取数据，未命中返回None。"""  # 方法文档字符串
        if self._use_memory:  # 如果使用内存缓存模式
            return self._memory_get(key)  # 调用内存缓存获取方法
        try:
            data = await self._redis.get(key)  # 从Redis获取缓存数据
            if data is None:  # 如果数据不存在
                return None  # 返回None
            return json.loads(data)  # 反序列化JSON数据并返回
        except Exception as e:  # 捕获Redis操作异常
            logger.warning("Redis读取失败，回退内存: %s", e)  # 记录警告
            return self._memory_get(key)  # 回退到内存缓存

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """写入缓存数据。"""  # 方法文档字符串
        if ttl is None:  # 如果未指定TTL
            ttl = get_settings().REDIS_CACHE_TTL_SECONDS  # 使用默认TTL配置
        if self._use_memory:  # 如果使用内存缓存模式
            self._memory_set(key, value, ttl)  # 调用内存缓存写入方法
            return  # 返回
        try:
            await self._redis.setex(key, ttl, json.dumps(value, ensure_ascii=False))  # 写入Redis并设置过期时间
        except Exception as e:  # 捕获Redis操作异常
            logger.warning("Redis写入失败，回退内存: %s", e)  # 记录警告
            self._memory_set(key, value, ttl)  # 回退到内存缓存

    async def delete(self, key: str) -> None:
        """删除缓存数据。"""  # 方法文档字符串
        if self._use_memory:  # 如果使用内存缓存模式
            _memory_cache.pop(key, None)  # 从内存缓存中删除
            return  # 返回
        try:
            await self._redis.delete(key)  # 从Redis删除缓存
        except Exception as e:  # 捕获Redis操作异常
            logger.warning("Redis删除失败: %s", e)  # 记录警告
            _memory_cache.pop(key, None)  # 同时从内存缓存中删除

    def _memory_get(self, key: str) -> Optional[Any]:  # 内存缓存获取方法
        """从内存缓存获取数据。"""  # 方法文档字符串
        cached = _memory_cache.get(key)  # 从内存字典获取数据
        if cached and time.time() - cached[1] < get_settings().REDIS_CACHE_TTL_SECONDS:  # 如果存在且未过期
            return cached[0]  # 返回缓存值
        if cached:  # 如果存在但已过期
            _memory_cache.pop(key, None)  # 删除过期缓存
        return None  # 返回None

    def _memory_set(self, key: str, value: Any, ttl: int) -> None:  # 内存缓存写入方法
        """写入内存缓存。"""  # 方法文档字符串
        _memory_cache[key] = (value, time.time())  # 写入值和时间戳
        # 超过最大缓存数时清理过期条目
        if len(_memory_cache) > 200:  # 如果缓存条目超过200
            now = time.time()  # 获取当前时间
            expired = [k for k, (_, ts) in _memory_cache.items() if now - ts >= ttl]  # 收集过期键
            for k in expired:  # 遍历过期键
                _memory_cache.pop(k, None)  # 删除过期缓存

# 全局缓存服务单例
_cache_service: Optional[CacheService] = None  # 全局缓存服务实例

async def init_cache() -> CacheService:  # 初始化缓存服务函数
    """初始化全局缓存服务。"""  # 函数文档字符串
    global _cache_service  # 声明使用全局变量
    _cache_service = CacheService()  # 创建缓存服务实例
    await _cache_service.init()  # 初始化缓存服务
    return _cache_service  # 返回实例

async def close_cache() -> None:  # 关闭缓存服务函数
    """关闭全局缓存服务。"""  # 函数文档字符串
    global _cache_service  # 声明使用全局变量
    if _cache_service is not None:  # 如果服务实例存在
        await _cache_service.close()  # 关闭缓存服务
        _cache_service = None  # 重置为None

def get_cache() -> CacheService:  # 获取缓存服务函数
    """获取全局缓存服务实例。"""  # 函数文档字符串
    if _cache_service is None:  # 如果服务未初始化
        raise RuntimeError("缓存服务未初始化，请先调用init_cache()")  # 抛出运行时错误
    return _cache_service  # 返回缓存服务实例
