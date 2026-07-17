"""
配置管理模块：统一加载 .env 环境变量，禁止硬编码密钥。
"""

import os
import secrets
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


class Config:
    """集中管理所有配置项，从环境变量读取。"""

    # ============================================================
    # OpenAI 兼容接口配置（DeepSeek，用于调度主管和回答Agent）
    # ============================================================
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "deepseek-chat")

    # ============================================================
    # Tavily 联网搜索配置
    # ============================================================
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # ============================================================
    # 本地Ollama配置（视觉识别 + 嵌入模型）
    # ============================================================
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3")
    OLLAMA_VISION_MODEL: str = os.getenv("OLLAMA_VISION_MODEL", "qwen3")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    # ============================================================
    # ChromaDB向量库配置
    # ============================================================
    CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")

    # ============================================================
    # 记忆管理配置
    # ============================================================
    MAX_HISTORY_TURNS: int = 10  # 短期记忆：最多保留最近N轮对话
    LONG_TERM_TOP_K: int = 5     # 长期记忆：每次检索最多召回K条

    # ============================================================
    # 上传配置
    # ============================================================
    UPLOAD_FOLDER: str = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "uploads"
    )
    MAX_UPLOAD_SIZE_MB: int = 20  # 最大上传文件大小（MB）

    # ============================================================
    # JWT 认证配置
    # ============================================================
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "") or secrets.token_hex(32)
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 默认24小时

    # ============================================================
    # SQLite 数据库配置
    # ============================================================
    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db"),
    )

    # ============================================================
    # 日志配置
    # ============================================================
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/app.log")

    # ============================================================
    # CORS 配置（允许前端跨域）
    # ============================================================
    CORS_ORIGINS: list = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
    ).split(",")

    @classmethod
    def validate(cls) -> None:
        """校验必要配置是否已设置，缺少则抛出异常。"""
        missing = []
        if not cls.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not cls.TAVILY_API_KEY:
            missing.append("TAVILY_API_KEY")
        if missing:
            raise ValueError(
                f"缺少必要环境变量: {', '.join(missing)}，请检查 .env 文件"
            )
        # 确保上传目录和日志目录存在
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(os.path.dirname(cls.LOG_FILE), exist_ok=True)
        os.makedirs(os.path.dirname(cls.DATABASE_PATH), exist_ok=True)
