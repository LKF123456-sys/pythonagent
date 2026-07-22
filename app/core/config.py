"""类型安全配置管理：基于 pydantic-settings，从 .env 加载并校验。"""

import os  # 导入操作系统接口模块，用于文件路径拼接与目录创建
import secrets  # 导入安全随机数生成模块，用于生成JWT密钥
from functools import lru_cache  # 从functools导入LRU缓存装饰器，实现配置单例缓存
from typing import List  # 从typing导入List类型注解，用于类型提示

from pydantic import field_validator  # 从pydantic导入字段验证器装饰器，用于自定义字段校验
from pydantic_settings import BaseSettings, SettingsConfigDict  # 导入pydantic-settings的基类与配置字典类，实现环境变量配置管理

# 弱密钥占位符黑名单：若 JWT_SECRET_KEY 匹配这些值，拒绝启动
_WEAK_SECRET_PATTERNS = (  # 定义弱密钥占位符黑名单元组，用于安全校验时检测不安全的密钥
    "change-me",  # 常见的占位符密钥示例1
    "replace_with",  # 常见的占位符密钥示例2
    "your-secret",  # 常见的占位符密钥示例3
    "secret-key-here",  # 常见的占位符密钥示例4
    "",  # 空字符串占位符，表示未配置密钥
)


class Settings(BaseSettings):
    """集中管理所有配置项，从环境变量 / .env 文件读取，带类型校验。"""

    model_config = SettingsConfigDict(  # pydantic-settings配置字典，定义配置加载行为
        env_file=os.path.join(  # 指定.env文件路径，通过路径拼接定位项目根目录下的.env文件
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),  # 向上回溯三层目录到项目根目录
            ".env",  # .env文件名
        ),
        env_file_encoding="utf-8",  # 指定.env文件编码为UTF-8，支持中文等字符
        case_sensitive=True,  # 环境变量名大小写敏感，区分大小写
        extra="ignore",  # 忽略.env中未定义的额外字段，避免报错
    )

    # ---- OpenAI 兼容接口（DeepSeek） ----
    OPENAI_API_KEY: str = ""  # OpenAI兼容接口的API密钥，默认空字符串需通过环境变量配置
    OPENAI_BASE_URL: str = "https://api.deepseek.com"  # OpenAI兼容接口的基础URL，默认指向DeepSeek服务
    MODEL_NAME: str = "deepseek-chat"  # 默认调用的模型名称，使用DeepSeek的对话模型

    # ---- LLM 容错（重试 / 熔断 / 降级 / 成本熔断） ----
    LLM_MAX_RETRIES: int = 3                # 瞬时错误最大重试次数
    LLM_RETRY_BASE_DELAY: float = 1.0       # 指数退避基础延迟（秒）
    LLM_CIRCUIT_FAILURE_THRESHOLD: int = 5  # 连续失败多少次后熔断
    LLM_CIRCUIT_RECOVERY_TIMEOUT: int = 60  # 熔断后冷却多少秒进入半开
    LLM_TOKEN_BUDGET_PER_MINUTE: int = 0    # 每分钟 token 预算（0=不限）
    FALLBACK_MODEL_NAME: str = ""           # 降级模型名（空=不启用降级）
    FALLBACK_OPENAI_BASE_URL: str = ""      # 降级模型 base_url（空=同主模型）

    # ---- Tavily 联网搜索 ----
    TAVILY_API_KEY: str = ""  # Tavily联网搜索服务的API密钥，默认空需配置

    # ---- 本地 Ollama ----
    OLLAMA_BASE_URL: str = "http://localhost:11434"  # 本地Ollama服务的基础URL，默认本机11434端口
    OLLAMA_MODEL: str = "qwen3"  # 本地Ollama默认对话模型，使用通义千问3
    OLLAMA_VISION_MODEL: str = "qwen3"  # 本地Ollama视觉模型，用于图像理解
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"  # 本地Ollama嵌入模型，用于向量编码

    # ---- 向量嵌入 ----
    EMBEDDING_DIM: int = 768  # nomic-embed-text 输出维度，嵌入向量的维度大小

    # ---- 记忆管理 ----
    MAX_HISTORY_TURNS: int = 10  # 对话历史保留的最大轮数，控制上下文长度
    LONG_TERM_TOP_K: int = 5  # 长期记忆检索返回的相似结果数量

    # ---- 文件上传 ----
    UPLOAD_FOLDER: str = os.path.join(  # 文件上传存储目录路径，位于项目根目录下的uploads文件夹
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),  # 向上回溯三层目录到项目根目录
        "uploads",  # 上传文件夹名称
    )
    MAX_UPLOAD_SIZE_MB: int = 20  # 单个上传文件的最大大小（MB），默认20MB

    # ---- JWT 认证 ----
    JWT_SECRET_KEY: str = ""  # JWT签名密钥，默认空字符串将由验证器自动生成
    JWT_ALGORITHM: str = "HS256"  # JWT签名算法，使用HMAC-SHA256
    JWT_ACCESS_EXPIRE_MINUTES: int = 30  # Access Token过期时间（分钟），默认30分钟
    JWT_REFRESH_EXPIRE_DAYS: int = 7  # Refresh Token过期时间（天），默认7天

    # ---- PostgreSQL ----
    DATABASE_URL: str = "postgresql://agent:agent-local@localhost:5433/agent"  # PostgreSQL数据库连接字符串，包含用户名密码主机端口库名
    PG_POOL_MIN_SIZE: int = 2  # 数据库连接池最小连接数，预热保持的连接
    PG_POOL_MAX_SIZE: int = 10  # 数据库连接池最大连接数，并发上限

    # ---- 日志 ----
    LOG_LEVEL: str = "INFO"  # 日志级别，默认INFO级别
    LOG_FILE: str = "logs/app.log"  # 日志文件路径，位于logs目录下
    LOG_FORMAT: str = "text"  # text | json（json 为结构化日志，供集中采集）

    # ---- 可观测性（OpenTelemetry） ----
    OTEL_ENABLED: bool = False  # 是否启用OpenTelemetry链路追踪，默认关闭
    OTEL_SERVICE_NAME: str = "multi-agent-system"  # OpenTelemetry服务名称，用于追踪中标识服务
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"  # Jaeger/OTEL Collector

    # ---- CORS ----
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"  # 允许跨域的源列表，逗号分隔

    @field_validator("JWT_SECRET_KEY", mode="before")  # pydantic字段验证器，在类型转换前对JWT_SECRET_KEY字段执行校验
    @classmethod  # 声明为类方法，可通过类或实例调用
    def _generate_secret_if_empty(cls, v: str) -> str:
        """未配置时自动生成强随机密钥（开发便利，生产应显式配置）。"""
        if not v:  # 若密钥为空字符串
            return secrets.token_hex(32)  # 生成32字节(64位十六进制字符)的强随机密钥
        return v  # 已配置密钥则原样返回

    @property  # 声明为属性访问器，通过对象.属性方式调用而非方法
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]  # 将逗号分隔的CORS源字符串拆分并去除空白后返回列表

    @property  # 声明为属性访问器，通过对象.属性方式调用
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024  # 将MB单位的文件大小限制转换为字节数

    def validate_security(self) -> None:
        """安全校验：弱密钥检测。启动时调用，不通过则拒绝启动。"""
        secret_lower = self.JWT_SECRET_KEY.lower()  # 将密钥转为小写，便于不区分大小写匹配
        for pattern in _WEAK_SECRET_PATTERNS:  # 遍历弱密钥占位符黑名单
            if pattern and pattern in secret_lower:  # 若占位符非空且存在于密钥中
                raise ValueError(  # 抛出值错误异常，阻止应用启动
                    f"JWT_SECRET_KEY 包含弱占位符 '{pattern}'，"  # 错误信息说明包含的弱占位符
                    "请生成强随机密钥: python -c \"import secrets; print(secrets.token_hex(32))\""  # 提示生成强密钥的命令
                )
        if len(self.JWT_SECRET_KEY) < 32:  # 若密钥长度不足32字符
            raise ValueError("JWT_SECRET_KEY 长度不足 32 字符，存在暴力破解风险")  # 抛出异常提示密钥过短

    def validate_required(self) -> None:
        """校验必要配置是否已设置。"""
        missing = []  # 初始化缺失配置项列表
        if not self.OPENAI_API_KEY:  # 若OpenAI API密钥未配置
            missing.append("OPENAI_API_KEY")  # 将缺失项加入列表
        if not self.TAVILY_API_KEY:  # 若Tavily API密钥未配置
            missing.append("TAVILY_API_KEY")  # 将缺失项加入列表
        if missing:  # 若存在缺失的必要配置
            raise ValueError(f"缺少必要环境变量: {', '.join(missing)}，请检查 .env 文件")  # 抛出异常提示缺失的环境变量

    def ensure_directories(self) -> None:
        """确保运行时目录存在。"""
        os.makedirs(self.UPLOAD_FOLDER, exist_ok=True)  # 创建上传目录，exist_ok=True表示已存在不报错
        log_dir = os.path.dirname(self.LOG_FILE)  # 获取日志文件所在目录路径
        if log_dir:  # 若日志目录非空（即日志文件指定了子目录）
            os.makedirs(log_dir, exist_ok=True)  # 创建日志目录，exist_ok=True表示已存在不报错


@lru_cache()  # 应用LRU缓存装饰器，使函数结果缓存，实现配置单例
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()  # 创建并返回Settings实例，由于缓存装饰器，仅首次调用时实际创建
