"""路由层（Controller）：仅做请求解析、调用 Service、返回响应。"""

from app.routers.admin import health_router, router as admin_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.conversations import router as conversations_router, stats_router
from app.routers.documents import router as documents_router
from app.routers.manufacturing import router as manufacturing_router

ALL_ROUTERS = [
    auth_router,
    chat_router,
    conversations_router,
    stats_router,
    documents_router,
    admin_router,
    health_router,
    manufacturing_router,
]

__all__ = ["ALL_ROUTERS"]
