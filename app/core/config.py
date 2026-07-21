"""类型安全配置管理：基于 pydantic-settings，从 .env 加载并校验。"""

import os
import secrets
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 弱密钥占位符黑名单：若 JWT_SECRET_KEY 匹配这些值，拒绝启动
_WEAK_SECRET_PATTERNS = (
    "change-me",
    "replace_with",
    "your-secret",
    "secret-key-here",
    "",
)


class Settings(BaseSettings):
    """集中管理所有配置项，从环境变量 / .env 文件读取，带类型校验。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- OpenAI 兼容接口（DeepSeek） ----
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.deepseek.com"
    MODEL_NAME: str = "deepseek-chat"

    # ---- LLM 容错（重试 / 熔断 / 降级 / 成本熔断） ----
    LLM_MAX_RETRIES: int = 3                # 瞬时错误最大重试次数
    LLM_RETRY_BASE_DELAY: float = 1.0       # 指数退避基础延迟（秒）
    LLM_CIRCUIT_FAILURE_THRESHOLD: int = 5  # 连续失败多少次后熔断
    LLM_CIRCUIT_RECOVERY_TIMEOUT: int = 60  # 熔断后冷却多少秒进入半开
    LLM_TOKEN_BUDGET_PER_MINUTE: int = 0    # 每分钟 token 预算（0=不限）
    FALLBACK_MODEL_NAME: str = ""           # 降级模型名（空=不启用降级）
    FALLBACK_OPENAI_BASE_URL: str = ""      # 降级模型 base_url（空=同主模型）

    # ---- Tavily 联网搜索 ----
    TAVILY_API_KEY: str = ""

    # ---- 本地 Ollama ----
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3"
    OLLAMA_VISION_MODEL: str = "qwen3"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # ---- 向量嵌入 ----
    EMBEDDING_DIM: int = 768  # nomic-embed-text 输出维度

    # ---- 记忆管理 ----
    MAX_HISTORY_TURNS: int = 10
    LONG_TERM_TOP_K: int = 5

    # ---- 文件上传 ----
    UPLOAD_FOLDER: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "uploads",
    )
    MAX_UPLOAD_SIZE_MB: int = 20

    # ---- JWT 认证 ----
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_EXPIRE_DAYS: int = 7

    # ---- PostgreSQL ----
    DATABASE_URL: str = "postgresql://agent:agent-local@localhost:5433/agent"
    PG_POOL_MIN_SIZE: int = 2
    PG_POOL_MAX_SIZE: int = 10

    # ---- 日志 ----
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"
    LOG_FORMAT: str = "text"  # text | json（json 为结构化日志，供集中采集）

    # ---- 可观测性（OpenTelemetry） ----
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "multi-agent-system"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"  # Jaeger/OTEL Collector

    # ---- CORS ----
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    @field_validator("JWT_SECRET_KEY", mode="before")
    @classmethod
    def _generate_secret_if_empty(cls, v: str) -> str:
        """未配置时自动生成强随机密钥（开发便利，生产应显式配置）。"""
        if not v:
            return secrets.token_hex(32)
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    def validate_security(self) -> None:
        """安全校验：弱密钥检测。启动时调用，不通过则拒绝启动。"""
        secret_lower = self.JWT_SECRET_KEY.lower()
        for pattern in _WEAK_SECRET_PATTERNS:
            if pattern and pattern in secret_lower:
                raise ValueError(
                    f"JWT_SECRET_KEY 包含弱占位符 '{pattern}'，"
                    "请生成强随机密钥: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        if len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY 长度不足 32 字符，存在暴力破解风险")

    def validate_required(self) -> None:
        """校验必要配置是否已设置。"""
        missing = []
        if not self.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not self.TAVILY_API_KEY:
            missing.append("TAVILY_API_KEY")
        if missing:
            raise ValueError(f"缺少必要环境变量: {', '.join(missing)}，请检查 .env 文件")

    def ensure_directories(self) -> None:
        """确保运行时目录存在。"""
        os.makedirs(self.UPLOAD_FOLDER, exist_ok=True)
        log_dir = os.path.dirname(self.LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()
