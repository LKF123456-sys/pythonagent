"""
Web对话后端：FastAPI 提供完整API，支持多会话、图片上传、文档上传、
历史记录、流式响应（SSE）、JWT 认证、Prometheus 监控。

从 Flask 迁移至 FastAPI，原生异步支持。
"""

# 导入sys模块，用于修改Python路径
import sys
# 导入os模块，用于文件和路径操作
import os
# 导入uuid模块，用于生成唯一会话ID
import uuid
# 导入time模块，用于时间戳生成
import time
# 导入json模块，用于JSON处理
import json
# 导入asyncio模块，用于异步操作
import asyncio
# 从contextlib导入asynccontextmanager，用于应用生命周期管理
from contextlib import asynccontextmanager

# 将本地 libs 目录加入 Python 搜索路径（可选 fallback）
# 获取当前文件所在目录下的libs子目录路径
_LIBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
# 如果libs目录存在，将其插入到Python搜索路径最前面
if os.path.isdir(_LIBS_DIR):
    sys.path.insert(0, _LIBS_DIR)

# 从fastapi导入核心组件：FastAPI应用类、依赖注入、HTTP异常、文件上传、表单
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
# 从fastapi.middleware.cors导入CORSMiddleware，用于跨域支持
from fastapi.middleware.cors import CORSMiddleware
# 从fastapi.responses导入响应类型：JSON响应、流式响应、文件响应、HTML响应
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, HTMLResponse
# 从pydantic导入BaseModel，用于请求数据验证
from pydantic import BaseModel
# 从typing导入Optional，用于类型提示（可选字段）
from typing import Optional

# 导入项目配置类
from config import Config
# 导入日志设置函数
from logger import setup_logger
# 导入数据库操作函数：初始化DB、列出会话、删除会话、获取消息
from database import init_db, list_conversations, delete_conversation, get_messages
# 导入认证相关类和函数：用户注册模型、用户登录模型、Token响应模型、注册用户、登录用户、获取当前用户
from auth import (
    UserRegister, UserLogin, TokenResponse,
    register_user, login_user, get_current_user,
)
# 导入工作流运行函数：同步运行和异步流式运行
from graph import run_agent, run_agent_stream
# 导入记忆模块函数：添加文档、列出文档、删除文档
from memory import (
    add_document, list_documents, delete_document,
)

# 初始化日志记录器
logger = setup_logger("web_app", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# 生命周期事件
# ============================================================

# 注册应用生命周期上下文管理器
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库，关闭时清理资源。"""
    # 验证配置项是否完整
    Config.validate()
    # 异步初始化数据库表结构
    await init_db()
    # 打印启动信息分隔线
    logger.info("=" * 60)
    # 打印系统名称
    logger.info("多智能体系统 - FastAPI 异步版（完整版）")
    # 打印API文档地址
    logger.info("API 文档: http://127.0.0.1:8000/docs")
    # 打印监控指标地址
    logger.info("监控指标: http://127.0.0.1:8000/metrics")
    # 打印功能列表
    logger.info("功能: 搜索 | 视觉识别 | RAG | 长期记忆 | SSE流式 | JWT认证")
    # 打印启动信息分隔线
    logger.info("=" * 60)
    # yield表示应用运行期间
    yield
    # 应用关闭时打印日志
    logger.info("应用已关闭")


# ============================================================
# FastAPI 应用初始化
# ============================================================

# 创建FastAPI应用实例
app = FastAPI(
    title="多智能体对话系统",  # 应用标题
    version="2.0.0",  # 版本号
    description="基于 LangGraph 的多智能体 AI 对话系统，支持搜索、RAG、视觉识别、流式响应",  # 应用描述
    lifespan=lifespan,  # 生命周期管理器
)

# 添加CORS跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,  # 允许的源列表
    allow_credentials=True,  # 允许携带凭证
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
)

# Prometheus 监控指标
try:
    # 延迟导入Prometheus仪表器
    from prometheus_fastapi_instrumentator import Instrumentator
    # 启用HTTP请求指标自动埋点并暴露/metrics端点
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    # 记录指标启用日志
    logger.info("Prometheus 指标已启用: /metrics")
except ImportError:
    # 如果未安装prometheus_fastapi_instrumentator，记录警告
    logger.warning("prometheus-fastapi-instrumentator 未安装，/metrics 不可用")

# 允许的图片扩展名集合
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
# 允许的文档扩展名集合
ALLOWED_DOC_EXT = {"txt", "md", "csv", "json", "pdf", "html", "py", "java", "js", "ts"}


def _allowed_file(filename: str, allowed_set: set) -> bool:
    """检查文件扩展名是否允许。"""
    # 判断文件名中是否包含点，且扩展名（小写）在允许集合中
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set


# ============================================================
# 全局异常处理
# ============================================================

# 注册全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """捕获所有未处理异常，返回500错误。"""
    # 记录错误日志，包含堆栈信息
    logger.error("未捕获异常: %s", exc, exc_info=True)
    # 返回JSON格式的500错误响应
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "detail": str(exc)},
    )


# ============================================================
# 前端页面
# ============================================================

# 根路径路由，返回HTML响应
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """提供聊天前端页面。"""
    # 构建index.html文件路径（templates目录下）
    index_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    # 返回文件响应
    return FileResponse(index_path)


# ============================================================
# 认证 API（无需 JWT）
# ============================================================

# 用户注册接口，返回Token响应
@app.post("/api/auth/register", response_model=TokenResponse, tags=["认证"])
async def api_register(data: UserRegister):
    """注册新用户，返回 JWT token。"""
    # 调用注册用户函数
    return await register_user(data)


# 用户登录接口
@app.post("/api/auth/login", response_model=TokenResponse, tags=["认证"])
async def api_login(data: UserLogin):
    """用户登录，返回 JWT token。"""
    # 调用登录用户函数
    return await login_user(data)


# 获取当前用户信息接口
@app.get("/api/auth/me", tags=["认证"])
async def api_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    # 返回用户ID、用户名和创建时间
    return {
        "user_id": current_user["id"],
        "username": current_user["username"],
        "created_at": current_user.get("created_at", ""),
    }


# ============================================================
# 会话 API
# ============================================================

# 获取新会话ID接口
@app.get("/api/session", tags=["会话"])
async def get_session(current_user: dict = Depends(get_current_user)):
    """获取当前会话信息（创建新 session_id）。"""
    # 生成8位短UUID作为会话ID
    session_id = str(uuid.uuid4())[:8]
    # 返回会话ID和is_new标记
    return {"session_id": session_id, "is_new": True}


# 创建新会话接口
@app.post("/api/session/new", tags=["会话"])
async def new_session(current_user: dict = Depends(get_current_user)):
    """创建新会话。"""
    # 生成8位短UUID作为会话ID
    session_id = str(uuid.uuid4())[:8]
    # 返回会话ID
    return {"session_id": session_id}


# 获取用户对话列表接口
@app.get("/api/conversations", tags=["会话"])
async def api_list_conversations(current_user: dict = Depends(get_current_user)):
    """获取当前用户的历史对话列表。"""
    # 异步列出当前用户的所有会话
    convs = await list_conversations(current_user["id"])
    # 返回会话列表
    return {"conversations": convs}


# 获取指定会话的消息历史接口
@app.get("/api/conversations/{conv_id}/messages", tags=["会话"])
async def api_get_messages(conv_id: str, current_user: dict = Depends(get_current_user)):
    """获取指定会话的消息历史。"""
    # 异步获取指定会话的所有消息
    msgs = await get_messages(conv_id)
    # 返回消息列表
    return {"messages": msgs}


# 删除指定对话接口
@app.delete("/api/conversations/{conv_id}", tags=["会话"])
async def api_delete_conversation(conv_id: str, current_user: dict = Depends(get_current_user)):
    """删除指定对话。"""
    # 异步删除指定会话
    await delete_conversation(conv_id)
    # 返回成功标记
    return {"success": True}


# ============================================================
# 请求模型
# ============================================================

class ChatRequest(BaseModel):
    """聊天请求数据模型，用于请求体验证。"""
    # 用户问题文本（必填）
    question: str
    # 会话ID（可选）
    session_id: Optional[str] = None
    # 上传图片的文件名（可选，默认为空字符串）
    image_filename: Optional[str] = ""
    # 是否是本轮会话的第一条消息（默认为True）
    is_first_turn: bool = True


# ============================================================
# 聊天 API（非流式，兼容旧接口）
# ============================================================

# 非流式聊天接口
@app.post("/api/chat", tags=["聊天"])
async def api_chat(
    data: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    聊天API（非流式）：支持文本+图片。
    """
    # 获取会话ID，如果未提供则生成新的8位UUID
    thread_id = data.session_id or str(uuid.uuid4())[:8]
    # 去除用户问题两端空白字符
    user_question = data.question.strip()

    # 如果问题为空，抛出400异常
    if not user_question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 初始化图片路径为空字符串
    image_path = ""
    # 如果提供了图片文件名
    if data.image_filename:
        # 构建图片完整路径
        image_path = os.path.join(Config.UPLOAD_FOLDER, data.image_filename)
        # 如果图片文件不存在，置空
        if not os.path.exists(image_path):
            image_path = ""

    try:
        # 同步调用多智能体工作流
        answer = run_agent(
            user_question=user_question,
            thread_id=thread_id,
            image_path=image_path,
            is_first_turn=data.is_first_turn,
            user_id=current_user["id"],
        )
        # 返回回答、会话ID、图片路径和无错误标记
        return {
            "answer": answer,
            "session_id": thread_id,
            "image_path": image_path,
            "error": None,
        }
    except Exception as e:
        # 记录错误日志
        logger.error("聊天处理失败: %s", e, exc_info=True)
        # 抛出500异常
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 流式聊天 API（SSE）
# ============================================================

# 流式聊天接口（Server-Sent Events）
@app.post("/api/chat/stream", tags=["聊天"])
async def api_chat_stream(
    data: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    流式聊天API：使用 SSE 逐 token 推送回答。

    SSE 事件格式：
        data: {"type": "status", "node": "supervisor"}     — 节点状态
        data: {"type": "token", "content": "你好"}           — 文本增量
        data: {"type": "done"}                               — 完成信号
        data: {"type": "error", "error": "..."}              — 错误信号
    """
    # 获取会话ID，如果未提供则生成新的8位UUID
    thread_id = data.session_id or str(uuid.uuid4())[:8]
    # 去除用户问题两端空白字符
    user_question = data.question.strip()

    # 如果问题为空，抛出400异常
    if not user_question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 初始化图片路径为空字符串
    image_path = ""
    # 如果提供了图片文件名
    if data.image_filename:
        # 构建图片完整路径
        image_path = os.path.join(Config.UPLOAD_FOLDER, data.image_filename)
        # 如果图片文件不存在，置空
        if not os.path.exists(image_path):
            image_path = ""

    # 记录流式聊天请求日志
    logger.info(
        "流式聊天: user=%s, session=%s, question=%s..., first_turn=%s",
        current_user.get("username"), thread_id,
        user_question[:50], data.is_first_turn,
    )

    # 定义异步事件生成器函数
    async def event_generator():
        """异步生成 SSE 事件流。"""
        # 异步迭代流式工作流输出的每个事件
        async for event in run_agent_stream(
            user_question=user_question,
            thread_id=thread_id,
            image_path=image_path,
            is_first_turn=data.is_first_turn,
            user_id=current_user["id"],
        ):
            # yield事件数据（SSE格式：data: ...\n\n）
            yield event

    # 返回流式响应，设置SSE相关头
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",  # SSE媒体类型
        headers={
            "Cache-Control": "no-cache",  # 禁用缓存
            "X-Accel-Buffering": "no",  # 禁用Nginx缓冲（重要：确保流式传输）
            "Connection": "keep-alive",  # 保持连接
        },
    )


# ============================================================
# 图片上传 API
# ============================================================

# 图片上传接口
@app.post("/api/upload/image", tags=["上传"])
async def api_upload_image(
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传图片，返回文件名供后续chat使用。"""
    # 如果文件名为空，抛出400异常
    if not image.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    # 检查文件扩展名是否允许
    if not _allowed_file(image.filename, ALLOWED_IMAGE_EXT):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，允许: {ALLOWED_IMAGE_EXT}")

    # 延迟导入werkzeug的secure_filename函数（安全文件名处理）
    from werkzeug.utils import secure_filename
    # 获取安全化处理后的文件名
    filename = secure_filename(image.filename)
    # 分割文件名和扩展名
    name, ext = os.path.splitext(filename)
    # 生成带时间戳的唯一文件名，防止重名覆盖
    filename = f"{name}_{int(time.time())}{ext}"
    # 构建保存文件的完整路径
    filepath = os.path.join(Config.UPLOAD_FOLDER, filename)

    # 异步读取上传的图片内容
    content = await image.read()
    # 以二进制写入模式打开文件
    with open(filepath, "wb") as f:
        # 写入文件内容
        f.write(content)

    # 记录图片上传日志
    logger.info("图片已上传: %s", filename)
    # 返回文件名、完整路径和无错误标记
    return {"filename": filename, "path": filepath, "error": None}


# ============================================================
# 文档上传 API（RAG）
# ============================================================

# 文档上传接口（用于RAG知识库）
@app.post("/api/upload/document", tags=["上传"])
async def api_upload_document(
    document: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传文档到RAG向量库。"""
    # 如果文件名为空，抛出400异常
    if not document.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    # 检查文件扩展名是否允许
    if not _allowed_file(document.filename, ALLOWED_DOC_EXT):
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    # 延迟导入werkzeug的secure_filename函数
    from werkzeug.utils import secure_filename
    # 获取安全化处理后的文件名
    filename = secure_filename(document.filename)

    # 异步读取上传的文档原始内容
    raw = await document.read()
    try:
        # 尝试用UTF-8解码，错误字符替换为占位符
        content = raw.decode("utf-8", errors="replace")
    except Exception:
        # UTF-8解码失败时，回退到latin-1编码（几乎不会失败）
        content = raw.decode("latin-1", errors="replace")

    # 如果文档内容为空（去除空白后），抛出400异常
    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 将文档内容存入RAG向量库（同步调用ChromaDB），返回切片数量
    chunk_count = add_document(content, filename)
    # 记录文档上传日志，包含切片数量
    logger.info("文档已上传: %s (%d个切片)", filename, chunk_count)
    # 返回文件名、切片数量和无错误标记
    return {"filename": filename, "chunks": chunk_count, "error": None}


# 获取RAG文档列表接口
@app.get("/api/documents", tags=["文档"])
async def api_get_documents(current_user: dict = Depends(get_current_user)):
    """获取已上传的RAG文档列表。"""
    # 调用list_documents获取所有已上传文档
    docs = list_documents()
    # 返回文档列表
    return {"documents": docs}


# 删除指定RAG文档接口
@app.delete("/api/documents/{filename}", tags=["文档"])
async def api_remove_document(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """删除指定RAG文档。"""
    # 调用delete_document删除文档，返回成功标记
    success = delete_document(filename)
    # 返回成功标记
    return {"success": success}


# ============================================================
# 健康检查（无需认证）
# ============================================================

# 健康检查端点
@app.get("/api/health", tags=["系统"])
async def health_check():
    """健康检查端点。"""
    # 返回状态ok和版本号
    return {"status": "ok", "version": "2.0.0"}


# ============================================================
# 启动入口
# ============================================================

# 当直接运行此脚本时
if __name__ == "__main__":
    # 导入uvicorn ASGI服务器
    import uvicorn
    # 启动uvicorn服务器，监听127.0.0.1:8000，启用热重载
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, reload=True)
