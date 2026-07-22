"""管理后台路由：用户管理 / 系统统计 / 深度健康检查。"""  # 模块级文档字符串，描述本模块的职责

from fastapi import APIRouter, Depends  # 从FastAPI导入API路由器和依赖注入功能
from pydantic import BaseModel, Field  # 从Pydantic导入数据模型基类和字段定义工具

from app.routers.deps import get_admin_user  # 导入管理员权限校验依赖，用于保护管理后台路由
from app.services import admin_service  # 导入管理后台业务逻辑服务模块

router = APIRouter(prefix="/api/admin", tags=["管理"])  # 创建管理后台路由器，设置URL前缀为/api/admin和API文档标签


class UserActiveRequest(BaseModel):  # 定义用户启用/禁用请求的Pydantic数据模型
    """启用/禁用用户请求。"""  # 模型文档字符串

    is_active: bool = Field(..., description="是否启用该用户")  # 必填布尔字段，表示是否启用该用户


@router.get("/users")  # 注册GET路由，路径为/api/admin/users，用于获取用户列表
async def list_users(admin: dict = Depends(get_admin_user)) -> dict:  # 定义异步函数，依赖注入管理员校验
    """列出所有用户（仅管理员）。"""  # 路由文档字符串
    users = await admin_service.list_users()  # 调用服务层获取所有用户列表
    return {"users": users, "total": len(users)}  # 返回用户列表和总数


@router.patch("/users/{user_id}")  # 注册PATCH路由，路径为/api/admin/users/{user_id}，用于部分更新用户状态
async def set_user_active(  # 定义异步函数，用于启用或禁用用户
    user_id: int,  # 路径参数，要操作的用户ID
    body: UserActiveRequest,  # 请求体参数，包含is_active字段
    admin: dict = Depends(get_admin_user),  # 依赖注入，校验管理员权限
) -> dict:  # 返回类型为字典
    """启用/禁用用户（仅管理员）。"""  # 路由文档字符串
    updated = await admin_service.set_user_active(user_id, body.is_active)  # 调用服务层更新用户激活状态
    return {"user": updated}  # 返回更新后的用户信息


@router.get("/stats")  # 注册GET路由，路径为/api/admin/stats，用于获取系统统计信息
async def system_stats(admin: dict = Depends(get_admin_user)) -> dict:  # 定义异步函数，依赖注入管理员校验
    """系统级统计（仅管理员）。"""  # 路由文档字符串
    return await admin_service.get_system_stats()  # 调用服务层获取系统统计数据并返回


# ============================================================  # 分隔注释
# 健康检查（公开端点，无需认证）  # 说明该部分为健康检查端点，无需身份认证
# ============================================================  # 分隔注释

health_router = APIRouter(tags=["健康"])  # 创建健康检查路由器，仅设置API文档标签，无URL前缀


@health_router.get("/api/health")  # 注册GET路由，路径为/api/health，用于深度健康检查
async def health_check() -> dict:  # 定义异步函数，无参数
    """深度健康检查：PostgreSQL / pgvector / Ollama / LLM API。"""  # 路由文档字符串
    return await admin_service.deep_health_check()  # 调用服务层执行深度健康检查并返回结果
