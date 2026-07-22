"""管理后台路由：用户管理 / 系统统计 / 深度健康检查。"""  # 模块级文档字符串，描述本模块的职责

from fastapi import APIRouter, Depends  # 从FastAPI导入API路由器和依赖注入功能
from pydantic import BaseModel, Field  # 从Pydantic导入数据模型基类和字段定义工具

from app.core.config import get_settings  # 导入配置获取函数，用于深度健康检查读取LLM API配置
from app.routers.deps import get_admin_user  # 导入管理员权限校验依赖，用于保护管理后台路由
from app.services import admin_service  # 导入管理后台业务逻辑服务模块

router = APIRouter(prefix="/admin", tags=["管理"])  # 创建管理后台路由器，设置URL前缀为/admin和API文档标签


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


@health_router.get("/health")  # 注册GET路由，路径为/health，用于深度健康检查
async def health_check() -> dict:  # 定义异步函数，无参数
    """深度健康检查：PostgreSQL / pgvector / Ollama / LLM API。"""  # 路由文档字符串
    return await admin_service.deep_health_check()  # 调用服务层执行深度健康检查并返回结果


@health_router.get("/health/deep")  # 深度健康检查路由，路径为/health/deep
async def deep_health_check():  # 定义深度健康检查异步函数
    """深度健康检查：检查所有依赖服务的连通性。"""  # 路由文档字符串
    checks = {}  # 检查结果字典，存储各组件检查状态
    overall_healthy = True  # 总体健康状态，初始为True

    # 检查数据库连接
    try:  # 开始异常捕获块
        from app.db.connection import get_pool  # 导入连接池获取函数
        pool = get_pool()  # 获取数据库连接池实例
        async with pool.acquire() as conn:  # 从连接池获取一个连接
            await conn.fetchval("SELECT 1")  # 执行简单查询测试连通性
        checks["database"] = {"status": "healthy", "latency_ms": 0}  # 数据库健康，记录状态和延迟
    except Exception as e:  # 捕获异常
        checks["database"] = {"status": "unhealthy", "error": str(e)}  # 数据库异常，记录错误信息
        overall_healthy = False  # 总体不健康

    # 检查Redis缓存
    try:  # 开始异常捕获块
        from app.core.cache import get_cache  # 导入缓存服务获取函数
        cache = get_cache()  # 获取缓存实例
        await cache.set("health_check", "ok", ttl=10)  # 写入测试数据，TTL为10秒
        result = await cache.get("health_check")  # 读取测试数据验证连通性
        checks["redis"] = {"status": "healthy" if result == "ok" else "unhealthy"}  # Redis健康状态判定
        if result != "ok":  # 如果读取结果不正确
            overall_healthy = False  # Redis不健康，总体不健康
    except Exception as e:  # 捕获异常
        checks["redis"] = {"status": "unhealthy", "error": str(e)}  # Redis异常，记录错误信息
        overall_healthy = False  # 总体不健康

    # 检查熔断器状态
    try:  # 开始异常捕获块
        from app.agents.resilience import get_circuit_breaker  # 导入熔断器获取函数
        breaker = get_circuit_breaker()  # 获取熔断器实例
        checks["circuit_breaker"] = {"state": breaker.state}  # 记录熔断器当前状态
        if breaker.state == "open":  # 如果熔断器处于打开状态
            overall_healthy = False  # 熔断器打开则总体不健康
    except Exception as e:  # 捕获异常
        checks["circuit_breaker"] = {"status": "unknown", "error": str(e)}  # 熔断器状态未知，记录错误

    # 检查LLM API配置
    settings = get_settings()  # 获取应用配置
    checks["llm_api"] = {"status": "configured" if settings.OPENAI_API_KEY else "not_configured"}  # 判断LLM API是否已配置
    if not settings.OPENAI_API_KEY:  # 如果未配置API密钥
        overall_healthy = False  # 未配置API密钥则总体不健康

    status_code = 200 if overall_healthy else 503  # 健康返回200，不健康返回503
    from fastapi.responses import JSONResponse  # 导入JSON响应类
    return JSONResponse(status_code=status_code, content={"healthy": overall_healthy, "checks": checks})  # 返回检查结果
