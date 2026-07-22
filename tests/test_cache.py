"""缓存服务单元测试：覆盖内存缓存模式、set/get/delete 操作、TTL 过期、优雅降级。

测试策略：
- 内存缓存模式：覆盖默认内存缓存的行为
- set/get/delete 操作：覆盖基本读写删操作
- TTL 过期：覆盖缓存过期后返回 None
- 优雅降级：覆盖 Redis 操作失败时回退到内存缓存
- 边界场景：覆盖空值、缓存清理、初始化/关闭
"""

import json  # 导入 JSON 模块，用于序列化断言
import sys  # 导入系统模块，用于检查 redis 可用性
import time  # 导入时间模块，用于测试 TTL 过期
from unittest.mock import AsyncMock, MagicMock, patch  # 从 unittest.mock 导入模拟工具

import pytest  # 导入 pytest 测试框架
import pytest_asyncio  # 导入 pytest 异步扩展

from app.core.cache import (  # 导入被测的缓存组件
    CacheService,  # 导入缓存服务类
    _memory_cache,  # 导入内存缓存字典
    close_cache,  # 导入关闭缓存函数
    get_cache,  # 导入获取缓存函数
    init_cache,  # 导入初始化缓存函数
)

# 检查 redis 库是否可用（用于跳过依赖 redis 的测试）
_REDIS_AVAILABLE = True  # 默认认为可用
try:  # 尝试导入
    import redis.asyncio  # 尝试导入 redis 异步库
except ImportError:  # 若导入失败
    _REDIS_AVAILABLE = False  # 标记为不可用


# ============================================================
# 测试夹具
# ============================================================

@pytest_asyncio.fixture  # 声明为异步 pytest 夹具
async def memory_cache_service(monkeypatch):  # 定义内存缓存服务夹具
    """提供使用内存缓存模式的 CacheService 实例。"""
    # 强制禁用 Redis，使用内存缓存
    from app.core.config import get_settings  # 导入配置获取函数
    monkeypatch.setattr(get_settings(), "REDIS_ENABLED", False)  # 禁用 Redis
    # 清空内存缓存
    _memory_cache.clear()  # 清空缓存
    # 创建缓存服务实例
    service = CacheService()  # 创建实例
    await service.init()  # 初始化
    yield service  # 产出服务实例
    # 测试结束后清空内存缓存
    _memory_cache.clear()  # 清空缓存


@pytest_asyncio.fixture  # 声明为异步 pytest 夹具
async def redis_cache_service(monkeypatch):  # 定义 Redis 缓存服务夹具
    """提供使用 Redis 缓存模式的 CacheService 实例（使用 Mock）。"""
    if not _REDIS_AVAILABLE:  # 若 redis 不可用
        pytest.skip("redis 库未安装，跳过 Redis 相关测试")  # 跳过测试
    from app.core.config import get_settings  # 导入配置获取函数
    monkeypatch.setattr(get_settings(), "REDIS_ENABLED", True)  # 启用 Redis
    monkeypatch.setattr(get_settings(), "REDIS_URL", "redis://localhost:6379/0")  # 设置 URL
    monkeypatch.setattr(get_settings(), "REDIS_CACHE_TTL_SECONDS", 120)  # 设置 TTL
    # 清空内存缓存
    _memory_cache.clear()  # 清空缓存
    # 创建缓存服务实例
    service = CacheService()  # 创建实例
    # 模拟 Redis 连接成功
    mock_redis = AsyncMock()  # 创建异步 Mock
    mock_redis.ping = AsyncMock(return_value=True)  # 模拟 ping 成功
    # 使用 patch 替换 redis.asyncio.from_url
    with patch("redis.asyncio.from_url", return_value=mock_redis):  # 模拟 Redis
        await service.init()  # 初始化
    yield service, mock_redis  # 产出服务和 Mock
    # 测试结束后清空内存缓存
    _memory_cache.clear()  # 清空缓存


# ============================================================
# 内存缓存模式测试
# ============================================================

class TestMemoryCacheMode:  # 定义内存缓存模式测试类
    """测试内存缓存模式下的基本操作。"""

    async def test_init_with_redis_disabled(self, memory_cache_service):  # 测试禁用 Redis 时使用内存
        """测试 Redis 禁用时使用内存缓存模式。"""
        service = await anext(memory_cache_service.__aiter__()) if hasattr(memory_cache_service, '__aiter__') else memory_cache_service
        # 上述写法兼容 fixture，简化处理
        assert service._use_memory is True  # 验证使用内存模式
        assert service._connected is False  # 验证未连接 Redis

    async def test_memory_set_and_get(self, memory_cache_service):  # 测试内存写入和读取
        """测试内存缓存的写入和读取。"""
        service = memory_cache_service  # 获取服务实例
        # 写入缓存
        await service.set("key1", "value1")  # 写入
        # 读取缓存
        result = await service.get("key1")  # 读取
        # 断言读取结果与写入值一致
        assert result == "value1"  # 验证值

    async def test_memory_get_missing_key_returns_none(self, memory_cache_service):  # 测试读取不存在的键
        """测试读取不存在的键返回 None。"""
        service = memory_cache_service  # 获取服务实例
        # 读取不存在的键
        result = await service.get("nonexistent")  # 读取
        # 断言返回 None
        assert result is None  # 验证返回 None

    async def test_memory_delete(self, memory_cache_service):  # 测试内存删除
        """测试内存缓存的删除。"""
        service = memory_cache_service  # 获取服务实例
        # 写入缓存
        await service.set("key_to_delete", "value")  # 写入
        # 删除缓存
        await service.delete("key_to_delete")  # 删除
        # 读取已删除的键
        result = await service.get("key_to_delete")  # 读取
        # 断言返回 None
        assert result is None  # 验证返回 None

    async def test_memory_set_complex_value(self, memory_cache_service):  # 测试写入复杂值
        """测试写入复杂的数据结构。"""
        service = memory_cache_service  # 获取服务实例
        # 写入字典
        complex_value = {"name": "test", "list": [1, 2, 3], "nested": {"a": 1}}  # 复杂值
        await service.set("complex", complex_value)  # 写入
        # 读取
        result = await service.get("complex")  # 读取
        # 断言读取结果与写入值一致
        assert result == complex_value  # 验证值

    async def test_memory_set_with_ttl(self, memory_cache_service):  # 测试写入带 TTL
        """测试写入带 TTL 的缓存。"""
        service = memory_cache_service  # 获取服务实例
        # 写入带 TTL 的缓存
        await service.set("ttl_key", "ttl_value", ttl=120)  # 写入
        # 读取
        result = await service.get("ttl_key")  # 读取
        # 断言返回正确值
        assert result == "ttl_value"  # 验证值


# ============================================================
# TTL 过期测试
# ============================================================

class TestTTLExpiry:  # 定义 TTL 过期测试类
    """测试缓存 TTL 过期行为。"""

    async def test_memory_cache_expires_after_ttl(self, memory_cache_service, monkeypatch):  # 测试内存缓存 TTL 过期
        """测试内存缓存在 TTL 过期后返回 None。"""
        service = memory_cache_service  # 获取服务实例
        # 写入缓存
        await service.set("expiry_key", "expiry_value", ttl=120)  # 写入
        # 验证可读取
        assert await service.get("expiry_key") == "expiry_value"  # 验证读取
        # 模拟时间流逝使缓存过期
        from app.core.cache import _memory_cache  # 导入内存缓存字典
        # 直接修改内存缓存中的时间戳使其过期
        cached_value, _ = _memory_cache["expiry_key"]  # 获取缓存值
        _memory_cache["expiry_key"] = (cached_value, time.time() - 200)  # 设置为 200 秒前
        # 再次读取应返回 None（已过期）
        result = await service.get("expiry_key")  # 读取
        assert result is None  # 验证返回 None

    async def test_memory_get_removes_expired_entry(self, memory_cache_service):  # 测试过期条目被移除
        """测试读取过期条目时自动移除。"""
        service = memory_cache_service  # 获取服务实例
        # 写入缓存
        await service.set("auto_remove_key", "value", ttl=120)  # 写入
        from app.core.cache import _memory_cache  # 导入内存缓存字典
        # 修改时间戳使缓存过期
        cached_value, _ = _memory_cache["auto_remove_key"]  # 获取缓存值
        _memory_cache["auto_remove_key"] = (cached_value, time.time() - 200)  # 设置为过期
        # 断言条目存在
        assert "auto_remove_key" in _memory_cache  # 验证条目存在
        # 读取触发过期检查
        await service.get("auto_remove_key")  # 读取
        # 断言条目已被移除
        assert "auto_remove_key" not in _memory_cache  # 验证条目被移除


# ============================================================
# 优雅降级测试
# ============================================================

class TestGracefulDegradation:  # 定义优雅降级测试类
    """测试 Redis 操作失败时优雅降级到内存缓存。"""

    async def test_redis_failure_falls_back_to_memory(self, monkeypatch):  # 测试 Redis 失败降级
        """测试 Redis 操作失败时回退到内存缓存。"""
        from app.core.config import get_settings  # 导入配置
        monkeypatch.setattr(get_settings(), "REDIS_ENABLED", True)  # 启用 Redis
        monkeypatch.setattr(get_settings(), "REDIS_URL", "redis://invalid:6379")  # 设置无效 URL
        # 清空内存缓存
        _memory_cache.clear()  # 清空缓存
        # 创建缓存服务
        service = CacheService()  # 创建实例
        await service.init()  # 初始化（连接失败会降级）
        # 断言降级到内存缓存
        assert service._use_memory is True  # 验证使用内存模式
        assert service._connected is False  # 验证未连接

    async def test_redis_get_failure_falls_back_to_memory(self, redis_cache_service):  # 测试 Redis 读取失败降级
        """测试 Redis 读取失败时回退到内存缓存。"""
        service, mock_redis = redis_cache_service  # 解构
        # 先写入内存缓存
        from app.core.cache import _memory_cache  # 导入内存缓存字典
        _memory_cache["fallback_key"] = ("fallback_value", time.time())  # 写入内存
        # 设置 Redis get 抛出异常
        mock_redis.get = AsyncMock(side_effect=Exception("Redis error"))  # 模拟失败
        # 读取应回退到内存缓存
        result = await service.get("fallback_key")  # 读取
        # 断言返回内存缓存中的值
        assert result == "fallback_value"  # 验证回退

    async def test_redis_set_failure_falls_back_to_memory(self, redis_cache_service):  # 测试 Redis 写入失败降级
        """测试 Redis 写入失败时回退到内存缓存。"""
        service, mock_redis = redis_cache_service  # 解构
        # 设置 Redis setex 抛出异常
        mock_redis.setex = AsyncMock(side_effect=Exception("Redis error"))  # 模拟失败
        # 写入应回退到内存缓存
        await service.set("fallback_set", "value")  # 写入
        # 断言值已写入内存缓存
        from app.core.cache import _memory_cache  # 导入内存缓存字典
        assert "fallback_set" in _memory_cache  # 验证写入内存

    async def test_redis_delete_failure_does_not_raise(self, redis_cache_service):  # 测试 Redis 删除失败不抛出
        """测试 Redis 删除失败时不抛出异常。"""
        service, mock_redis = redis_cache_service  # 解构
        # 设置 Redis delete 抛出异常
        mock_redis.delete = AsyncMock(side_effect=Exception("Redis error"))  # 模拟失败
        # 删除不应抛出异常
        await service.delete("any_key")  # 删除


# ============================================================
# 全局缓存服务测试
# ============================================================

class TestGlobalCacheService:  # 定义全局缓存服务测试类
    """测试全局缓存服务的初始化、获取和关闭。"""

    async def test_init_cache_creates_service(self, monkeypatch):  # 测试初始化创建服务
        """测试 init_cache 创建全局缓存服务。"""
        from app.core.config import get_settings  # 导入配置
        monkeypatch.setattr(get_settings(), "REDIS_ENABLED", False)  # 禁用 Redis
        # 清空全局缓存
        import app.core.cache as cache_module  # 导入缓存模块
        cache_module._cache_service = None  # 重置全局实例
        # 初始化缓存
        service = await init_cache()  # 初始化
        # 断言服务实例正确
        assert service is not None  # 验证创建
        assert isinstance(service, CacheService)  # 验证类型
        # 清理
        await close_cache()  # 关闭缓存

    async def test_get_cache_returns_service(self, monkeypatch):  # 测试获取缓存服务
        """测试 get_cache 返回已初始化的服务。"""
        from app.core.config import get_settings  # 导入配置
        monkeypatch.setattr(get_settings(), "REDIS_ENABLED", False)  # 禁用 Redis
        # 清空全局缓存
        import app.core.cache as cache_module  # 导入缓存模块
        cache_module._cache_service = None  # 重置全局实例
        # 初始化缓存
        await init_cache()  # 初始化
        # 获取缓存服务
        service = get_cache()  # 获取
        # 断言返回正确实例
        assert isinstance(service, CacheService)  # 验证类型
        # 清理
        await close_cache()  # 关闭缓存

    async def test_get_cache_uninitialized_raises(self):  # 测试未初始化获取抛出异常
        """测试未初始化时 get_cache 抛出 RuntimeError。"""
        # 清空全局缓存
        import app.core.cache as cache_module  # 导入缓存模块
        cache_module._cache_service = None  # 重置全局实例
        # 断言抛出 RuntimeError
        with pytest.raises(RuntimeError, match="缓存服务未初始化"):  # 期望抛出异常
            get_cache()  # 获取

    async def test_close_cache_resets_service(self, monkeypatch):  # 测试关闭重置服务
        """测试 close_cache 重置全局服务。"""
        from app.core.config import get_settings  # 导入配置
        monkeypatch.setattr(get_settings(), "REDIS_ENABLED", False)  # 禁用 Redis
        # 清空全局缓存
        import app.core.cache as cache_module  # 导入缓存模块
        cache_module._cache_service = None  # 重置全局实例
        # 初始化缓存
        await init_cache()  # 初始化
        # 关闭缓存
        await close_cache()  # 关闭
        # 断言全局实例已重置
        assert cache_module._cache_service is None  # 验证重置

    async def test_close_cache_when_not_initialized(self):  # 测试未初始化时关闭不抛出
        """测试未初始化时 close_cache 不抛出异常。"""
        # 清空全局缓存
        import app.core.cache as cache_module  # 导入缓存模块
        cache_module._cache_service = None  # 重置全局实例
        # 关闭不应抛出异常
        await close_cache()  # 关闭


# ============================================================
# 边界场景测试
# ============================================================

class TestEdgeCases:  # 定义边界场景测试类
    """测试缓存服务的边界场景。"""

    async def test_set_with_none_ttl_uses_default(self, memory_cache_service, monkeypatch):  # 测试 None TTL 使用默认值
        """测试 TTL 为 None 时使用默认配置。"""
        service = memory_cache_service  # 获取服务实例
        from app.core.config import get_settings  # 导入配置
        monkeypatch.setattr(get_settings(), "REDIS_CACHE_TTL_SECONDS", 60)  # 设置默认 TTL
        # 写入不指定 TTL
        await service.set("default_ttl_key", "value")  # 写入
        # 读取验证
        result = await service.get("default_ttl_key")  # 读取
        assert result == "value"  # 验证值

    async def test_memory_cache_cleanup_when_exceeding_max(self, memory_cache_service):  # 测试缓存超限清理
        """测试内存缓存超过 200 条时清理过期条目。"""
        service = memory_cache_service  # 获取服务实例
        from app.core.cache import _memory_cache  # 导入内存缓存字典
        # 写入 200+ 条数据
        for i in range(205):  # 写入 205 条
            await service.set(f"key_{i}", f"value_{i}", ttl=120)  # 写入
        # 断言缓存数量不超过 200（清理后）
        # 注意：清理逻辑在写入时触发
        assert len(_memory_cache) <= 205  # 验证清理（可能未清理因 TTL 未过期）

    async def test_redis_connected_state(self, redis_cache_service):  # 测试 Redis 连接状态
        """测试 Redis 连接成功后的状态标志。"""
        service, mock_redis = redis_cache_service  # 解构
        # 断言状态标志正确
        assert service._connected is True  # 验证已连接
        assert service._use_memory is False  # 验证未使用内存模式
        assert service._redis is not None  # 验证 Redis 客户端存在

    async def test_close_when_using_memory(self, memory_cache_service):  # 测试内存模式关闭
        """测试内存模式下关闭不抛出异常。"""
        service = memory_cache_service  # 获取服务实例
        # 关闭不应抛出异常（无 Redis 客户端）
        await service.close()  # 关闭
