"""管理后台路由：用户管理 / 系统统计 / 深度健康检查。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.routers.deps import get_admin_user
from app.services import admin_service

router = APIRouter(prefix="/api/admin", tags=["管理"])


class UserActiveRequest(BaseModel):
    """启用/禁用用户请求。"""

    is_active: bool = Field(..., description="是否启用该用户")


@router.get("/users")
async def list_users(admin: dict = Depends(get_admin_user)) -> dict:
    """列出所有用户（仅管理员）。"""
    users = await admin_service.list_users()
    return {"users": users, "total": len(users)}


@router.patch("/users/{user_id}")
async def set_user_active(
    user_id: int,
    body: UserActiveRequest,
    admin: dict = Depends(get_admin_user),
) -> dict:
    """启用/禁用用户（仅管理员）。"""
    updated = await admin_service.set_user_active(user_id, body.is_active)
    return {"user": updated}


@router.get("/stats")
async def system_stats(admin: dict = Depends(get_admin_user)) -> dict:
    """系统级统计（仅管理员）。"""
    return await admin_service.get_system_stats()


# ============================================================
# 健康检查（公开端点，无需认证）
# ============================================================

health_router = APIRouter(tags=["健康"])


@health_router.get("/api/health")
async def health_check() -> dict:
    """深度健康检查：PostgreSQL / pgvector / Ollama / LLM API。"""
    return await admin_service.deep_health_check()
