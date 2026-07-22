"""全局常量定义：消除代码中的魔法字符串。"""

from enum import Enum  # 从enum模块导入Enum基类，用于创建枚举类型


class RouteAction(str, Enum):
    """Supervisor 路由决策枚举。"""

    SEARCH = "SEARCH"  # 路由到联网搜索节点
    RAG = "RAG"  # 路由到RAG检索节点
    DIRECT = "DIRECT"  # 直接由LLM回答，不检索


class MessageRole(str, Enum):
    """消息角色。"""

    USER = "user"  # 用户角色，表示用户发送的消息
    ASSISTANT = "assistant"  # 助手角色，表示AI回复的消息


class WSEventType(str, Enum):
    """WebSocket 事件类型。"""

    STATUS = "status"  # 状态更新事件，推送节点处理状态
    THINKING = "thinking"  # 思考过程事件，推送LLM思考内容
    TOKEN = "token"  # 流式Token事件，推送生成的token
    DONE = "done"  # 完成事件，表示本次对话结束
    ERROR = "error"  # 错误事件，推送异常信息
    PONG = "pong"  # 心跳响应事件，响应客户端ping


class WSClientEvent(str, Enum):
    """客户端发送的 WebSocket 事件类型。"""

    CHAT = "chat"  # 聊天事件，客户端发起对话请求
    ABORT = "abort"  # 中止事件，客户端请求中止当前生成
    PING = "ping"  # 心跳事件，客户端心跳检测


# 默认会话线程 ID
DEFAULT_THREAD_ID = "default"  # 默认会话线程标识符，用于无显式线程ID时的默认会话

# 向量存储表名（pgvector）
TABLE_LONG_TERM_MEMORY = "long_term_memories"  # 长期记忆向量存储表名，存储对话记忆向量
TABLE_RAG_CHUNKS = "rag_chunks"  # RAG文档分块向量存储表名，存储文档块向量

# 节点名称（用于状态推送）
NODE_PREPROCESS = "preprocess"  # 预处理节点名称，负责输入预处理
NODE_SUPERVISOR = "supervisor"  # 主管节点名称，负责路由决策
NODE_SEARCH = "search"  # 搜索节点名称，负责联网搜索
NODE_RAG = "rag"  # RAG节点名称，负责知识库检索
NODE_ANSWER = "answer"  # 回答节点名称，负责生成最终答案
NODE_STORE_MEMORY = "store_memory"  # 记忆存储节点名称，负责保存对话记忆

# 允许的图片扩展名
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}  # 允许上传的图片文件扩展名集合

# 允许的文档扩展名
ALLOWED_DOC_EXTENSIONS = {  # 允许上传的文档文件扩展名集合
    "txt", "md", "csv", "json", "pdf", "docx", "html", "py", "java", "js", "ts",  # 包含文本、标记、数据、文档、代码等多种格式
}

# bcrypt 密码最大字节数限制
BCRYPT_MAX_BYTES = 72  # bcrypt算法的密码最大字节限制，超出部分将被截断

# 上下文压缩阈值（字符数）
CONTEXT_COMPRESS_THRESHOLD = 3000  # 上下文字符数超过此阈值时触发压缩，控制Token消耗

# LLM 路由缓存 TTL（秒）
ROUTE_CACHE_TTL_SECONDS = 600  # 路由决策缓存的有效时间（秒），默认10分钟

# ============================================================
# 工业智能制造垂直领域常量
# ============================================================

# 工业 RAG 向量存储表名（与通用 RAG 隔离）
TABLE_MFG_RAG_CHUNKS = "mfg_rag_chunks"  # 工业领域RAG文档分块向量存储表名，与通用RAG隔离

# 工业节点名称（用于状态推送）
NODE_MFG_PREPROCESS = "mfg_preprocess"  # 工业预处理节点名称，负责工业输入预处理
NODE_MFG_SUPERVISOR = "mfg_supervisor"  # 工业主管节点名称，负责工业路由决策
NODE_MFG_FAULT = "fault_diagnosis"  # 故障诊断节点名称，负责设备故障诊断
NODE_MFG_PROCESS = "process_optimization"  # 工艺优化节点名称，负责生产工艺优化
NODE_MFG_PREDICT = "predictive_maintenance"  # 预测性维护节点名称，负责设备预测维护
NODE_MFG_KNOWLEDGE = "knowledge_qa"  # 知识问答节点名称，负责工业知识库问答
NODE_MFG_ANSWER = "mfg_answer"  # 工业回答节点名称，负责生成工业领域最终答案
NODE_MFG_STORE = "mfg_store_memory"  # 工业记忆存储节点名称，负责保存工业对话记忆
