"""FastAPI 应用工厂 + lifespan 生命周期管理。

启动流程：安全校验 → 目录准备 → DB 连接池 + 迁移 → 向量库注入 → 图编译。
"""  # 模块级文档字符串，描述应用工厂和生命周期管理

import os  # 导入操作系统接口标准库
from contextlib import asynccontextmanager  # 从contextlib导入异步上下文管理器装饰器

from fastapi import FastAPI, HTTPException  # 从FastAPI导入应用类和HTTP异常类
from fastapi.middleware.cors import CORSMiddleware  # 导入CORS中间件
from fastapi.middleware.gzip import GZipMiddleware  # 导入GZip压缩中间件
from fastapi.responses import FileResponse, JSONResponse  # 导入文件响应和JSON响应类
from fastapi.staticfiles import StaticFiles  # 导入静态文件服务类
from slowapi import _rate_limit_exceeded_handler  # 从slowapi导入限流超限处理器
from slowapi.errors import RateLimitExceeded  # 从slowapi导入限流超限异常

from app.core.config import get_settings  # 导入配置获取函数
from app.core.exceptions import AppException  # 导入应用异常基类
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.core.rate_limit import limiter  # 导入频率限制器实例
from app.core.request_context import RequestIdMiddleware  # 导入请求ID中间件
from app.core.tracing import setup_tracing  # 导入追踪初始化函数
from app.agents.graph import compile_graph  # 导入图编译函数
from app.agents.runtime import set_vector_store  # 导入向量库注入函数
from app.db.connection import close_pool, init_pool  # 导入数据库连接池初始化和关闭函数
from app.db.migrations import run_migrations  # 导入数据库迁移函数
from app.memory.vector_store import VectorStore  # 导入向量库类
from app.routers import ALL_ROUTERS  # 导入所有路由器列表

logger = setup_logger("main")  # 创建名为main的日志记录器

# 项目根目录（app/ 的上一级）  # 内部注释，说明项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 计算项目根目录绝对路径


# ============================================================  # 分隔注释
# 生命周期管理  # 说明该部分为生命周期管理
# ============================================================  # 分隔注释

@asynccontextmanager  # 应用异步上下文管理器装饰器
async def lifespan(app: FastAPI):  # 定义应用生命周期协程函数
    """应用生命周期：启动时初始化资源，关闭时清理。"""  # 函数文档字符串
    settings = get_settings()  # 获取配置

    # 安全校验：弱密钥拒绝启动  # 内部注释，说明安全校验
    settings.validate_security()  # 执行安全配置校验

    # 必要配置校验：缺失仅告警（不阻塞启动，便于前端/健康检查独立运行）  # 内部注释
    try:  # 尝试校验必要配置
        settings.validate_required()  # 执行必要配置校验
    except ValueError as e:  # 如果校验失败
        logger.warning("配置提示：%s（相关智能体功能将不可用）", e)  # 记录警告日志，不阻塞启动

    settings.ensure_directories()  # 确保必要目录存在

    # 分布式追踪初始化（OTEL_ENABLED=False 时为空操作）  # 内部注释
    setup_tracing()  # 初始化分布式追踪

    # 数据库连接池 + 迁移  # 内部注释
    pool = await init_pool()  # 初始化数据库连接池
    await run_migrations(pool)  # 执行数据库迁移

    # 向量库初始化并注入智能体运行时（pgvector 封装，接口稳定）  # 内部注释
    vector_store = VectorStore()  # 创建向量库实例
    await vector_store.initialize()  # 初始化向量库
    set_vector_store(vector_store)  # 注入到智能体运行时
    app.state.vector_store = vector_store  # 保存到应用状态

    # 图编译（单例，checkpointer 可注入）  # 内部注释
    compile_graph()  # 编译智能体图

    logger.info("应用启动完成")  # 记录启动完成日志
    try:  # 尝试进入运行态
        yield  # 让出控制权，应用进入服务状态
    finally:  # 应用关闭时清理
        await close_pool()  # 关闭数据库连接池
        logger.info("应用已关闭")  # 记录关闭日志


# ============================================================  # 分隔注释
# 异常处理  # 说明该部分为异常处理
# ============================================================  # 分隔注释

async def _app_exception_handler(request, exc: AppException) -> JSONResponse:  # 定义应用异常处理器
    """业务异常 → 统一 JSON 错误响应。"""  # 函数文档字符串
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})  # 返回JSON错误响应


# ============================================================  # 分隔注释
# 前端静态文件挂载（SPA 回退）  # 说明该部分为前端静态文件挂载
# ============================================================  # 分隔注释

def _mount_frontend(app: FastAPI) -> None:  # 定义挂载前端静态文件的内部函数
    """若前端构建产物存在，挂载静态资源并支持 SPA 路由回退。"""  # 函数文档字符串
    dist_dir = os.path.join(_PROJECT_ROOT, "frontend", "dist")  # 前端构建目录
    index_file = os.path.join(dist_dir, "index.html")  # 入口HTML文件
    if not os.path.isfile(index_file):  # 如果入口文件不存在
        logger.info("前端构建产物不存在，跳过静态挂载（%s）", index_file)  # 记录日志
        return  # 直接返回

    assets_dir = os.path.join(dist_dir, "assets")  # 静态资源目录
    if os.path.isdir(assets_dir):  # 如果资源目录存在
        app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")  # 挂载静态资源

    @app.get("/{full_path:path}", include_in_schema=False)  # 注册SPA回退路由，不显示在API文档
    async def spa_fallback(full_path: str):  # 定义SPA回退函数
        # API / WS / 指标路径不回退到前端，返回 404  # 内部注释说明排除路径
        if full_path.startswith(("api/", "ws/", "metrics")):  # 如果是API/WS/指标路径
            raise HTTPException(status_code=404)  # 抛出404异常
        return FileResponse(index_file)  # 返回入口HTML

    logger.info("前端静态资源已挂载: %s", dist_dir)  # 记录挂载日志


# ============================================================  # 分隔注释
# 应用工厂  # 说明该部分为应用工厂
# ============================================================  # 分隔注释

def create_app() -> FastAPI:  # 定义应用工厂函数
    """创建并配置 FastAPI 应用实例。"""  # 函数文档字符串
    settings = get_settings()  # 获取配置
    app = FastAPI(  # 创建FastAPI应用实例
        title="多智能体对话系统",  # 应用标题
        description="基于 LangGraph 的多智能体对话系统（联网搜索 + RAG + 长期记忆）",  # 应用描述
        version="2.0.0",  # 应用版本
        lifespan=lifespan,  # 生命周期管理
    )

    # 异常处理器  # 内部注释
    app.add_exception_handler(AppException, _app_exception_handler)  # 注册业务异常处理器
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # 注册限流异常处理器

    # 中间件（后添加者位于外层）  # 内部注释说明中间件顺序
    app.add_middleware(GZipMiddleware, minimum_size=1000)  # 添加GZip压缩中间件
    app.add_middleware(RequestIdMiddleware)  # 添加请求ID中间件
    app.add_middleware(  # 添加CORS中间件
        CORSMiddleware,  # CORS中间件类
        allow_origins=settings.cors_origins_list,  # 允许的源
        allow_credentials=True,  # 允许携带凭证
        allow_methods=["*"],  # 允许所有方法
        allow_headers=["*"],  # 允许所有头
    )

    # 频率限制器  # 内部注释
    app.state.limiter = limiter  # 将限流器保存到应用状态

    # 注册路由  # 内部注释
    for router in ALL_ROUTERS:  # 遍历所有路由器
        app.include_router(router)  # 注册路由器到应用

    # Prometheus 指标（可选）  # 内部注释
    try:  # 尝试启用Prometheus
        from prometheus_fastapi_instrumentator import Instrumentator  # 延迟导入Prometheus工具

        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)  # 启用指标暴露
    except Exception as e:  # 如果启用失败
        logger.warning("Prometheus 指标不可用: %s", e)  # 记录警告日志

    # 前端静态文件  # 内部注释
    _mount_frontend(app)  # 挂载前端静态文件

    return app  # 返回配置完成的应用实例


app = create_app()  # 创建全局应用实例


if __name__ == "__main__":  # 如果直接运行本模块
    import uvicorn  # 导入uvicorn服务器

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)  # 启动uvicorn服务
