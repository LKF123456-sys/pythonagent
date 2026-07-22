"""路由层（Controller）：仅做请求解析、调用 Service、返回响应。"""  # 模块级文档字符串，描述路由层职责

from app.routers.admin import health_router, router as admin_router  # 从管理路由模块导入健康检查路由器和管理路由器
from app.routers.auth import router as auth_router  # 从认证路由模块导入认证路由器
from app.routers.chat import router as chat_router  # 从聊天路由模块导入聊天路由器
from app.routers.conversations import router as conversations_router, stats_router  # 从会话路由模块导入会话路由器和统计路由器
from app.routers.documents import router as documents_router  # 从文档路由模块导入文档路由器
from app.routers.manufacturing import router as manufacturing_router  # 从工业路由模块导入工业制造路由器
from app.routers.review import router as review_router  # 从审批路由模块导入人工审批路由器

ALL_ROUTERS = [  # 所有路由器列表，供 FastAPI 应用工厂统一注册
    auth_router,  # 认证路由器（注册/登录/刷新/登出/当前用户）
    chat_router,  # 聊天路由器（WebSocket 流式 + REST 非流式 + 图片上传）
    conversations_router,  # 会话路由器（列表/消息/重命名/删除/导出）
    stats_router,  # 统计路由器（Token 用量统计）
    documents_router,  # 文档路由器（RAG 文档上传/列表/删除）
    admin_router,  # 管理路由器（用户管理/系统统计）
    health_router,  # 健康检查路由器（深度健康检查）
    manufacturing_router,  # 工业制造路由器（WebSocket + 故障码 + 文档上传）
    review_router,  # 人工审批路由器（批准/拒绝待审批请求）
]

__all__ = ["ALL_ROUTERS"]  # 公开接口：所有路由器列表
