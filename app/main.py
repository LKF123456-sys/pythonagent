"""FastAPI 应用工厂 + lifespan 生命周期管理。

启动流程：安全校验 → 目录准备 → DB 连接池 + 迁移 → 向量库注入 → 图编译。
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import setup_logger
from app.core.rate_limit import limiter
from app.core.request_context import RequestIdMiddleware
from app.core.tracing import setup_tracing
from app.agents.graph import compile_graph
from app.agents.runtime import set_vector_store
from app.db.connection import close_pool, init_pool
from app.db.migrations import run_migrations
from app.memory.vector_store import VectorStore
from app.routers import ALL_ROUTERS

logger = setup_logger("main")

# 项目根目录（app/ 的上一级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 生命周期管理
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化资源，关闭时清理。"""
    settings = get_settings()

    # 安全校验：弱密钥拒绝启动
    settings.validate_security()

    # 必要配置校验：缺失仅告警（不阻塞启动，便于前端/健康检查独立运行）
    try:
        settings.validate_required()
    except ValueError as e:
        logger.warning("配置提示：%s（相关智能体功能将不可用）", e)

    settings.ensure_directories()

    # 分布式追踪初始化（OTEL_ENABLED=False 时为空操作）
    setup_tracing()

    # 数据库连接池 + 迁移
    pool = await init_pool()
    await run_migrations(pool)

    # 向量库初始化并注入智能体运行时（pgvector 封装，接口稳定）
    vector_store = VectorStore()
    await vector_store.initialize()
    set_vector_store(vector_store)
    app.state.vector_store = vector_store

    # 图编译（单例，checkpointer 可注入）
    compile_graph()

    logger.info("应用启动完成")
    try:
        yield
    finally:
        await close_pool()
        logger.info("应用已关闭")


# ============================================================
# 异常处理
# ============================================================

async def _app_exception_handler(request, exc: AppException) -> JSONResponse:
    """业务异常 → 统一 JSON 错误响应。"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# ============================================================
# 前端静态文件挂载（SPA 回退）
# ============================================================

def _mount_frontend(app: FastAPI) -> None:
    """若前端构建产物存在，挂载静态资源并支持 SPA 路由回退。"""
    dist_dir = os.path.join(_PROJECT_ROOT, "frontend", "dist")
    index_file = os.path.join(dist_dir, "index.html")
    if not os.path.isfile(index_file):
        logger.info("前端构建产物不存在，跳过静态挂载（%s）", index_file)
        return

    assets_dir = os.path.join(dist_dir, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # API / WS / 指标路径不回退到前端，返回 404
        if full_path.startswith(("api/", "ws/", "metrics")):
            raise HTTPException(status_code=404)
        return FileResponse(index_file)

    logger.info("前端静态资源已挂载: %s", dist_dir)


# ============================================================
# 应用工厂
# ============================================================

def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings = get_settings()
    app = FastAPI(
        title="多智能体对话系统",
        description="基于 LangGraph 的多智能体对话系统（联网搜索 + RAG + 长期记忆）",
        version="2.0.0",
        lifespan=lifespan,
    )

    # 异常处理器
    app.add_exception_handler(AppException, _app_exception_handler)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # 中间件（后添加者位于外层）
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 频率限制器
    app.state.limiter = limiter

    # 注册路由
    for router in ALL_ROUTERS:
        app.include_router(router)

    # Prometheus 指标（可选）
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    except Exception as e:
        logger.warning("Prometheus 指标不可用: %s", e)

    # 前端静态文件
    _mount_frontend(app)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
