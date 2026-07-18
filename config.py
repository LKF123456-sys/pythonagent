"""
配置管理模块：统一加载 .env 环境变量，禁止硬编码密钥。
"""

# 导入os模块，用于文件路径操作和环境变量读取
import os
# 导入secrets模块，用于生成安全的随机密钥
import secrets
# 从dotenv库导入load_dotenv函数，用于加载.env文件中的环境变量
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量到系统环境变量中
load_dotenv()


class Config:
    """集中管理所有配置项，从环境变量读取。"""

    # ============================================================
    # OpenAI 兼容接口配置（DeepSeek，用于调度主管和回答Agent）
    # ============================================================
    # DeepSeek API密钥，从环境变量OPENAI_API_KEY读取，默认为空字符串
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    # DeepSeek API基础URL，默认为官方地址https://api.deepseek.com
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    # 使用的模型名称，默认为deepseek-chat
    MODEL_NAME: str = os.getenv("MODEL_NAME", "deepseek-chat")

    # ============================================================
    # Tavily 联网搜索配置
    # ============================================================
    # Tavily搜索API密钥，从环境变量TAVILY_API_KEY读取，默认为空
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # ============================================================
    # 本地Ollama配置（视觉识别 + 嵌入模型）
    # ============================================================
    # Ollama服务基础URL，默认为本地地址http://localhost:11434
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    # Ollama文本模型名称，默认为qwen3
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3")
    # Ollama视觉多模态模型名称，默认为qwen3（实际使用qwen3-vl:8b）
    OLLAMA_VISION_MODEL: str = os.getenv("OLLAMA_VISION_MODEL", "qwen3")
    # Ollama嵌入模型名称，默认为nomic-embed-text
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    # ============================================================
    # ChromaDB向量库配置
    # ============================================================
    # ChromaDB数据库存储路径，默认为./data/chroma_db
    CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")

    # ============================================================
    # 记忆管理配置
    # ============================================================
    # 短期记忆：最多保留最近10轮对话
    MAX_HISTORY_TURNS: int = 10
    # 长期记忆：每次检索最多召回5条相关记忆
    LONG_TERM_TOP_K: int = 5

    # ============================================================
    # 上传配置
    # ============================================================
    # 文件上传目录路径，默认为当前文件所在目录下的uploads文件夹
    UPLOAD_FOLDER: str = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "uploads"
    )
    # 最大上传文件大小，单位为MB，默认为20MB
    MAX_UPLOAD_SIZE_MB: int = 20

    # ============================================================
    # JWT 认证配置
    # ============================================================
    # JWT签名密钥，从环境变量读取，若未设置则自动生成32字节随机十六进制字符串
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "") or secrets.token_hex(32)
    # JWT签名算法，默认为HS256（HMAC-SHA256）
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    # JWT过期时间，单位为分钟，默认为1440分钟（24小时）
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

    # ============================================================
    # SQLite 数据库配置
    # ============================================================
    # SQLite数据库文件路径，默认为当前文件所在目录下的data/app.db
    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db"),
    )

    # ============================================================
    # 日志配置
    # ============================================================
    # 日志级别，默认为INFO
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # 日志文件路径，默认为logs/app.log
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/app.log")

    # ============================================================
    # CORS 配置（允许前端跨域）
    # ============================================================
    # 允许的跨域来源列表，从环境变量读取，按逗号分割，默认为本地开发地址
    CORS_ORIGINS: list = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
    ).split(",")

    @classmethod
    def validate(cls) -> None:
        """校验必要配置是否已设置，缺少则抛出异常。"""
        # 初始化缺失配置列表
        missing = []
        # 检查OPENAI_API_KEY是否已配置
        if not cls.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        # 检查TAVILY_API_KEY是否已配置
        if not cls.TAVILY_API_KEY:
            missing.append("TAVILY_API_KEY")
        # 如果有缺失的配置项，抛出ValueError异常
        if missing:
            raise ValueError(
                f"缺少必要环境变量: {', '.join(missing)}，请检查 .env 文件"
            )
        # 确保上传目录存在，若不存在则创建
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        # 确保日志文件所在目录存在，若不存在则创建
        os.makedirs(os.path.dirname(cls.LOG_FILE), exist_ok=True)
        # 确保数据库文件所在目录存在，若不存在则创建
        os.makedirs(os.path.dirname(cls.DATABASE_PATH), exist_ok=True)
