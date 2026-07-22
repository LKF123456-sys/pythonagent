"""配置管理模块单元测试：覆盖 Settings 实例化、密钥校验、目录创建等核心逻辑。

测试策略：
- 通过 monkeypatch 注入测试环境变量，确保测试间相互隔离
- 覆盖弱密钥检测（黑名单 + 长度不足）、自动生成强密钥等安全场景
- 覆盖 cors_origins_list / max_upload_bytes 属性计算
- 覆盖 ensure_directories / validate_security / validate_required 方法
"""

import os  # 导入操作系统接口模块，用于路径操作与环境变量
import secrets  # 导入安全随机数生成模块，用于断言强密钥格式
import tempfile  # 导入临时文件模块，用于创建测试用临时目录

import pytest  # 导入 pytest 测试框架

from app.core.config import Settings, get_settings, _WEAK_SECRET_PATTERNS  # 导入被测的配置类与获取函数


# ============================================================
# 测试夹具：提供隔离的测试配置环境
# ============================================================

@pytest.fixture  # 声明为 pytest 夹具
def isolated_settings(monkeypatch, tmp_path):  # 定义隔离配置夹具，使用 monkeypatch 与临时路径
    """创建一个隔离环境的 Settings 实例，避免污染全局单例。"""
    # 设置测试用临时目录，避免影响真实文件系统
    upload_dir = tmp_path / "uploads"  # 定义上传目录路径
    log_dir = tmp_path / "logs"  # 定义日志目录路径
    log_file = log_dir / "test.log"  # 定义日志文件路径

    # 通过 monkeypatch 设置环境变量，确保测试隔离
    monkeypatch.setenv("UPLOAD_FOLDER", str(upload_dir))  # 设置上传目录环境变量
    monkeypatch.setenv("LOG_FILE", str(log_file))  # 设置日志文件环境变量
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)  # 设置强密钥，64个字符a

    # 清除 get_settings 的 LRU 缓存，确保重新读取环境变量
    get_settings.cache_clear()  # 清除缓存

    # 创建并返回新的 Settings 实例
    settings = Settings()  # 实例化配置对象
    yield settings  # 产出配置实例供测试使用
    # 测试结束后再次清除缓存，避免后续测试受影响
    get_settings.cache_clear()  # 清除缓存


# ============================================================
# Settings 实例化测试
# ============================================================

class TestSettingsInstantiation:
    """测试 Settings 类的实例化与字段默认值。"""

    def test_settings_can_be_instantiated(self, isolated_settings):
        """测试 Settings 实例能够正常创建。"""
        # 断言实例是 Settings 类型
        assert isinstance(isolated_settings, Settings)  # 验证实例类型正确

    def test_default_model_name(self, isolated_settings):
        """测试默认模型名称字段。"""
        # 断言默认模型名为 deepseek-chat
        assert isolated_settings.MODEL_NAME == "deepseek-chat"  # 验证默认模型名称

    def test_default_openai_base_url(self, isolated_settings):
        """测试默认 OpenAI 基础 URL。"""
        # 断言默认 URL 指向 DeepSeek
        assert isolated_settings.OPENAI_BASE_URL == "https://api.deepseek.com"  # 验证默认基础 URL

    def test_default_jwt_algorithm(self, isolated_settings):
        """测试默认 JWT 算法。"""
        # 断言默认算法为 HS256
        assert isolated_settings.JWT_ALGORITHM == "HS256"  # 验证默认签名算法

    def test_default_jwt_expire_minutes(self, isolated_settings):
        """测试默认 Access Token 过期时间。"""
        # 断言默认过期时间为 30 分钟
        assert isolated_settings.JWT_ACCESS_EXPIRE_MINUTES == 30  # 验证默认过期分钟数

    def test_default_jwt_refresh_expire_days(self, isolated_settings):
        """测试默认 Refresh Token 过期时间。"""
        # 断言默认刷新令牌过期天数为 7 天
        assert isolated_settings.JWT_REFRESH_EXPIRE_DAYS == 7  # 验证默认刷新令牌过期天数

    def test_default_max_upload_size_mb(self, isolated_settings):
        """测试默认最大上传文件大小。"""
        # 断言默认最大上传大小为 20MB
        assert isolated_settings.MAX_UPLOAD_SIZE_MB == 20  # 验证默认上传大小限制

    def test_default_embedding_dimension(self, isolated_settings):
        """测试默认嵌入向量维度。"""
        # 断言默认嵌入维度为 768
        assert isolated_settings.EMBEDDING_DIM == 768  # 验证默认嵌入维度

    def test_default_max_history_turns(self, isolated_settings):
        """测试默认对话历史保留轮数。"""
        # 断言默认保留 10 轮对话
        assert isolated_settings.MAX_HISTORY_TURNS == 10  # 验证默认历史保留轮数


# ============================================================
# JWT_SECRET_KEY 自动生成测试
# ============================================================

class TestJwtSecretAutoGeneration:
    """测试 JWT_SECRET_KEY 为空时自动生成强随机密钥。"""

    def test_empty_secret_generates_random_key(self, monkeypatch):
        """测试空密钥会自动生成随机密钥。"""
        # 设置空密钥环境变量
        monkeypatch.setenv("JWT_SECRET_KEY", "")  # 设置空密钥
        # 清除缓存以确保重新读取
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言密钥非空且长度为 64（32 字节十六进制）
        assert settings.JWT_SECRET_KEY != ""  # 密钥不应为空
        assert len(settings.JWT_SECRET_KEY) == 64  # 32 字节的十六进制字符串长度为 64
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存

    def test_explicit_secret_not_overwritten(self, monkeypatch):
        """测试显式配置的密钥不会被覆盖。"""
        # 设置显式密钥
        explicit_secret = "my-explicit-strong-secret-key-1234567890"  # 定义显式密钥
        monkeypatch.setenv("JWT_SECRET_KEY", explicit_secret)  # 设置环境变量
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言密钥与显式设置一致
        assert settings.JWT_SECRET_KEY == explicit_secret  # 验证密钥未被覆盖
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存

    def test_generated_secret_is_hex(self, monkeypatch):
        """测试自动生成的密钥为十六进制字符串。"""
        # 设置空密钥
        monkeypatch.setenv("JWT_SECRET_KEY", "")  # 设置空密钥
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言密钥只包含十六进制字符
        assert all(c in "0123456789abcdef" for c in settings.JWT_SECRET_KEY)  # 验证为十六进制
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存


# ============================================================
# 弱密钥检测测试
# ============================================================

class TestWeakSecretDetection:
    """测试弱密钥检测逻辑。"""

    def test_change_me_pattern_rejected(self, monkeypatch):
        """测试 change-me 占位符被拒绝。"""
        # 设置包含弱占位符的密钥
        monkeypatch.setenv("JWT_SECRET_KEY", "change-me" + "a" * 50)  # 设置弱密钥
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言调用安全校验时抛出 ValueError
        with pytest.raises(ValueError, match="弱占位符"):  # 期望抛出包含"弱占位符"的异常
            settings.validate_security()  # 调用安全校验
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存

    def test_replace_with_pattern_rejected(self, monkeypatch):
        """测试 replace_with 占位符被拒绝。"""
        # 设置包含 replace_with 占位符的密钥
        monkeypatch.setenv("JWT_SECRET_KEY", "replace_with" + "b" * 50)  # 设置弱密钥
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言抛出 ValueError
        with pytest.raises(ValueError):  # 期望抛出 ValueError
            settings.validate_security()  # 调用安全校验
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存

    def test_your_secret_pattern_rejected(self, monkeypatch):
        """测试 your-secret 占位符被拒绝。"""
        # 设置包含 your-secret 占位符的密钥
        monkeypatch.setenv("JWT_SECRET_KEY", "your-secret" + "c" * 50)  # 设置弱密钥
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言抛出 ValueError
        with pytest.raises(ValueError):  # 期望抛出 ValueError
            settings.validate_security()  # 调用安全校验
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存

    def test_short_secret_rejected(self, monkeypatch):
        """测试长度不足 32 字符的密钥被拒绝。"""
        # 设置长度不足的密钥
        monkeypatch.setenv("JWT_SECRET_KEY", "shortkey123")  # 设置短密钥
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言抛出 ValueError 并包含长度提示
        with pytest.raises(ValueError, match="长度不足"):  # 期望抛出长度相关异常
            settings.validate_security()  # 调用安全校验
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存

    def test_strong_secret_accepted(self, monkeypatch):
        """测试强密钥通过校验。"""
        # 设置强密钥（64 个字符随机十六进制）
        strong_secret = secrets.token_hex(32)  # 生成强密钥
        monkeypatch.setenv("JWT_SECRET_KEY", strong_secret)  # 设置环境变量
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 创建 Settings 实例
        settings = Settings()  # 实例化配置
        # 断言不抛出异常
        settings.validate_security()  # 调用安全校验，不应抛出异常
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存


# ============================================================
# cors_origins_list 属性测试
# ============================================================

class TestCorsOriginsList:
    """测试 cors_origins_list 属性。"""

    def test_default_cors_origins(self, isolated_settings):
        """测试默认 CORS 源列表。"""
        # 重置 CORS_ORIGINS 为默认值
        isolated_settings.CORS_ORIGINS = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
        # 获取源列表
        origins = isolated_settings.cors_origins_list  # 获取 CORS 源列表
        # 断言列表包含 3 个源
        assert len(origins) == 3  # 验证源数量
        # 断言包含 localhost:5173
        assert "http://localhost:5173" in origins  # 验证包含特定源
        # 断言包含 localhost:3000
        assert "http://localhost:3000" in origins  # 验证包含特定源

    def test_cors_origins_with_spaces(self, isolated_settings):
        """测试带空格的 CORS 源被正确去除空格。"""
        # 设置带空格的 CORS 源字符串
        isolated_settings.CORS_ORIGINS = " http://a.com , http://b.com , "  # 设置带空格的源
        # 获取源列表
        origins = isolated_settings.cors_origins_list  # 获取源列表
        # 断言空格被去除
        assert origins == ["http://a.com", "http://b.com"]  # 验证空格被去除

    def test_empty_cors_origins(self, isolated_settings):
        """测试空 CORS 源返回空列表。"""
        # 设置空 CORS 源字符串
        isolated_settings.CORS_ORIGINS = ""  # 设置空字符串
        # 获取源列表
        origins = isolated_settings.cors_origins_list  # 获取源列表
        # 断言返回空列表
        assert origins == []  # 验证返回空列表

    def test_single_cors_origin(self, isolated_settings):
        """测试单个 CORS 源。"""
        # 设置单个 CORS 源
        isolated_settings.CORS_ORIGINS = "http://example.com"  # 设置单个源
        # 获取源列表
        origins = isolated_settings.cors_origins_list  # 获取源列表
        # 断言列表只包含一个源
        assert origins == ["http://example.com"]  # 验证单个源


# ============================================================
# max_upload_bytes 属性测试
# ============================================================

class TestMaxUploadBytes:
    """测试 max_upload_bytes 属性。"""

    def test_default_max_upload_bytes(self, isolated_settings):
        """测试默认上传大小字节数。"""
        # 设置默认上传大小为 20MB
        isolated_settings.MAX_UPLOAD_SIZE_MB = 20  # 设置为 20MB
        # 断言字节数为 20 * 1024 * 1024
        assert isolated_settings.max_upload_bytes == 20 * 1024 * 1024  # 验证字节转换

    def test_custom_max_upload_bytes(self, isolated_settings):
        """测试自定义上传大小字节数。"""
        # 设置自定义上传大小为 50MB
        isolated_settings.MAX_UPLOAD_SIZE_MB = 50  # 设置为 50MB
        # 断言字节数为 50 * 1024 * 1024
        assert isolated_settings.max_upload_bytes == 50 * 1024 * 1024  # 验证字节转换

    def test_zero_max_upload_bytes(self, isolated_settings):
        """测试 0MB 上传大小。"""
        # 设置上传大小为 0MB
        isolated_settings.MAX_UPLOAD_SIZE_MB = 0  # 设置为 0MB
        # 断言字节数为 0
        assert isolated_settings.max_upload_bytes == 0  # 验证零字节


# ============================================================
# ensure_directories 方法测试
# ============================================================

class TestEnsureDirectories:
    """测试 ensure_directories 方法。"""

    def test_ensure_directories_creates_upload_folder(self, isolated_settings, tmp_path):
        """测试 ensure_directories 创建上传目录。"""
        # 设置上传目录到临时路径
        upload_dir = tmp_path / "uploads"  # 定义上传目录
        isolated_settings.UPLOAD_FOLDER = str(upload_dir)  # 设置上传目录
        # 断言目录开始不存在
        assert not upload_dir.exists()  # 验证目录不存在
        # 调用方法创建目录
        isolated_settings.ensure_directories()  # 调用方法
        # 断言目录已创建
        assert upload_dir.exists()  # 验证目录已创建
        assert upload_dir.is_dir()  # 验证是目录

    def test_ensure_directories_creates_log_folder(self, isolated_settings, tmp_path):
        """测试 ensure_directories 创建日志目录。"""
        # 设置日志文件到临时路径的子目录
        log_dir = tmp_path / "logs"  # 定义日志目录
        isolated_settings.LOG_FILE = str(log_dir / "app.log")  # 设置日志文件路径
        # 断言日志目录开始不存在
        assert not log_dir.exists()  # 验证目录不存在
        # 调用方法创建目录
        isolated_settings.ensure_directories()  # 调用方法
        # 断言日志目录已创建
        assert log_dir.exists()  # 验证目录已创建

    def test_ensure_directories_idempotent(self, isolated_settings, tmp_path):
        """测试 ensure_directories 幂等性（已存在目录不报错）。"""
        # 设置上传目录
        upload_dir = tmp_path / "uploads"  # 定义上传目录
        isolated_settings.UPLOAD_FOLDER = str(upload_dir)  # 设置上传目录
        # 第一次调用
        isolated_settings.ensure_directories()  # 第一次调用
        # 第二次调用不应抛出异常
        isolated_settings.ensure_directories()  # 第二次调用，验证幂等

    def test_ensure_directories_with_empty_log_dir(self, isolated_settings, tmp_path):
        """测试 LOG_FILE 无目录路径时不报错。"""
        # 设置日志文件仅为文件名（无目录前缀）
        isolated_settings.LOG_FILE = "app.log"  # 设置无目录的日志文件
        # 调用方法不应抛出异常
        isolated_settings.ensure_directories()  # 调用方法


# ============================================================
# validate_security 方法测试
# ============================================================

class TestValidateSecurity:
    """测试 validate_security 方法。"""

    def test_strong_secret_passes(self, isolated_settings):
        """测试强密钥通过校验。"""
        # 设置强密钥
        isolated_settings.JWT_SECRET_KEY = secrets.token_hex(32)  # 设置强密钥
        # 调用校验不应抛出异常
        isolated_settings.validate_security()  # 调用校验

    def test_weak_pattern_rejected(self, isolated_settings):
        """测试弱占位符密钥被拒绝。"""
        # 设置包含 change-me 的弱密钥
        isolated_settings.JWT_SECRET_KEY = "change-me-and-other-stuff-here-to-make-it-long-enough"  # 设置弱密钥
        # 断言抛出 ValueError
        with pytest.raises(ValueError, match="弱占位符"):  # 期望抛出异常
            isolated_settings.validate_security()  # 调用校验

    def test_too_short_secret_rejected(self, isolated_settings):
        """测试过短密钥被拒绝。"""
        # 设置长度不足 32 的密钥
        isolated_settings.JWT_SECRET_KEY = "onlythirtyonecharslong1234567"  # 设置短密钥（31 字符）
        # 断言抛出 ValueError
        with pytest.raises(ValueError, match="长度不足"):  # 期望抛出异常
            isolated_settings.validate_security()  # 调用校验


# ============================================================
# validate_required 方法测试
# ============================================================

class TestValidateRequired:
    """测试 validate_required 方法。"""

    def test_all_required_set_passes(self, isolated_settings):
        """测试所有必要配置已设置时通过校验。"""
        # 设置必要配置
        isolated_settings.OPENAI_API_KEY = "sk-test-key"  # 设置 OpenAI 密钥
        isolated_settings.TAVILY_API_KEY = "tvly-test-key"  # 设置 Tavily 密钥
        # 调用校验不应抛出异常
        isolated_settings.validate_required()  # 调用校验

    def test_missing_openai_key_raises(self, isolated_settings):
        """测试缺失 OpenAI 密钥抛出异常。"""
        # 设置 OpenAI 密钥为空
        isolated_settings.OPENAI_API_KEY = ""  # 设置为空
        isolated_settings.TAVILY_API_KEY = "tvly-test-key"  # 设置 Tavily 密钥
        # 断言抛出 ValueError 并包含 OPENAI_API_KEY
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):  # 期望抛出包含密钥名的异常
            isolated_settings.validate_required()  # 调用校验

    def test_missing_tavily_key_raises(self, isolated_settings):
        """测试缺失 Tavily 密钥抛出异常。"""
        # 设置 Tavily 密钥为空
        isolated_settings.OPENAI_API_KEY = "sk-test-key"  # 设置 OpenAI 密钥
        isolated_settings.TAVILY_API_KEY = ""  # 设置为空
        # 断言抛出 ValueError 并包含 TAVILY_API_KEY
        with pytest.raises(ValueError, match="TAVILY_API_KEY"):  # 期望抛出包含密钥名的异常
            isolated_settings.validate_required()  # 调用校验

    def test_all_missing_raises_with_both_keys(self, isolated_settings):
        """测试两个必要密钥都缺失时抛出异常。"""
        # 两个密钥都设置为空
        isolated_settings.OPENAI_API_KEY = ""  # 设置为空
        isolated_settings.TAVILY_API_KEY = ""  # 设置为空
        # 断言抛出 ValueError 并包含两个密钥名
        with pytest.raises(ValueError) as exc_info:  # 期望抛出异常
            isolated_settings.validate_required()  # 调用校验
        # 断言错误消息包含两个密钥名
        assert "OPENAI_API_KEY" in str(exc_info.value)  # 验证包含 OpenAI 密钥名
        assert "TAVILY_API_KEY" in str(exc_info.value)  # 验证包含 Tavily 密钥名


# ============================================================
# get_settings 单例缓存测试
# ============================================================

class TestGetSettings:
    """测试 get_settings 单例缓存机制。"""

    def test_get_settings_returns_same_instance(self):
        """测试 get_settings 返回同一实例（LRU 缓存）。"""
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 第一次获取
        s1 = get_settings()  # 第一次获取
        # 第二次获取
        s2 = get_settings()  # 第二次获取
        # 断言两次获取的是同一实例
        assert s1 is s2  # 验证为同一实例
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存

    def test_cache_clear_returns_new_instance(self):
        """测试清除缓存后返回新实例。"""
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 获取第一个实例
        s1 = get_settings()  # 获取实例
        # 清除缓存
        get_settings.cache_clear()  # 清除缓存
        # 获取第二个实例
        s2 = get_settings()  # 获取新实例
        # 断言不是同一实例
        assert s1 is not s2  # 验证为不同实例
        # 清理缓存
        get_settings.cache_clear()  # 清除缓存
