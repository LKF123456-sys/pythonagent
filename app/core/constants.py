"""全局常量定义：消除代码中的魔法字符串。"""

from enum import Enum


class RouteAction(str, Enum):
    """Supervisor 路由决策枚举。"""

    SEARCH = "SEARCH"
    RAG = "RAG"
    DIRECT = "DIRECT"


class MessageRole(str, Enum):
    """消息角色。"""

    USER = "user"
    ASSISTANT = "assistant"


class WSEventType(str, Enum):
    """WebSocket 事件类型。"""

    STATUS = "status"
    THINKING = "thinking"
    TOKEN = "token"
    DONE = "done"
    ERROR = "error"
    PONG = "pong"


class WSClientEvent(str, Enum):
    """客户端发送的 WebSocket 事件类型。"""

    CHAT = "chat"
    ABORT = "abort"
    PING = "ping"


# 默认会话线程 ID
DEFAULT_THREAD_ID = "default"

# 向量存储表名（pgvector）
TABLE_LONG_TERM_MEMORY = "long_term_memories"
TABLE_RAG_CHUNKS = "rag_chunks"

# 节点名称（用于状态推送）
NODE_PREPROCESS = "preprocess"
NODE_SUPERVISOR = "supervisor"
NODE_SEARCH = "search"
NODE_RAG = "rag"
NODE_ANSWER = "answer"
NODE_STORE_MEMORY = "store_memory"

# 允许的图片扩展名
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}

# 允许的文档扩展名
ALLOWED_DOC_EXTENSIONS = {
    "txt", "md", "csv", "json", "pdf", "docx", "html", "py", "java", "js", "ts",
}

# bcrypt 密码最大字节数限制
BCRYPT_MAX_BYTES = 72

# 上下文压缩阈值（字符数）
CONTEXT_COMPRESS_THRESHOLD = 3000

# LLM 路由缓存 TTL（秒）
ROUTE_CACHE_TTL_SECONDS = 600

# ============================================================
# 工业智能制造垂直领域常量
# ============================================================

# 工业 RAG 向量存储表名（与通用 RAG 隔离）
TABLE_MFG_RAG_CHUNKS = "mfg_rag_chunks"

# 工业节点名称（用于状态推送）
NODE_MFG_PREPROCESS = "mfg_preprocess"
NODE_MFG_SUPERVISOR = "mfg_supervisor"
NODE_MFG_FAULT = "fault_diagnosis"
NODE_MFG_PROCESS = "process_optimization"
NODE_MFG_PREDICT = "predictive_maintenance"
NODE_MFG_KNOWLEDGE = "knowledge_qa"
NODE_MFG_ANSWER = "mfg_answer"
NODE_MFG_STORE = "mfg_store_memory"
