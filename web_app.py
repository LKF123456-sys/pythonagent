"""
Web对话后端：FastAPI 提供完整API，支持多会话、图片上传、文档上传、
历史记录、流式响应（SSE）、JWT 认证、Prometheus 监控。

从 Flask 迁移至 FastAPI，原生异步支持。
"""

import sys
import os
import uuid
import time
import json
import asyncio
from contextlib import asynccontextmanager

# 将本地 libs 目录加入 Python 搜索路径（可选 fallback）
_LIBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
if os.path.isdir(_LIBS_DIR):
    sys.path.insert(0, _LIBS_DIR)

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional

from config import Config
from logger import setup_logger
from database import init_db, list_conversations, delete_conversation, get_messages
from auth import (
    UserRegister, UserLogin, TokenResponse,
    register_user, login_user, get_current_user,
)
from graph import run_agent, run_agent_stream
from memory import (
    add_document, list_documents, delete_document,
)

# 初始化日志
logger = setup_logger("web_app", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# 生命周期事件
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库，关闭时清理资源。"""
    Config.validate()
    await init_db()
    logger.info("=" * 60)
    logger.info("多智能体系统 - FastAPI 异步版（完整版）")
    logger.info("API 文档: http://127.0.0.1:8000/docs")
    logger.info("监控指标: http://127.0.0.1:8000/metrics")
    logger.info("功能: 搜索 | 视觉识别 | RAG | 长期记忆 | SSE流式 | JWT认证")
    logger.info("=" * 60)
    yield
    logger.info("应用已关闭")


# ============================================================
# FastAPI 应用初始化
# ============================================================

app = FastAPI(
    title="多智能体对话系统",
    version="2.0.0",
    description="基于 LangGraph 的多智能体 AI 对话系统，支持搜索、RAG、视觉识别、流式响应",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus 监控指标
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    logger.info("Prometheus 指标已启用: /metrics")
except ImportError:
    logger.warning("prometheus-fastapi-instrumentator 未安装，/metrics 不可用")

# 允许的图片和文档扩展名
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
ALLOWED_DOC_EXT = {"txt", "md", "csv", "json", "pdf", "html", "py", "java", "js", "ts"}


def _allowed_file(filename: str, allowed_set: set) -> bool:
    """检查文件扩展名是否允许。"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set


# ============================================================
# 全局异常处理
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("未捕获异常: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "detail": str(exc)},
    )


# ============================================================
# 前端页面
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """提供聊天前端页面。"""
    index_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    return FileResponse(index_path)


# ============================================================
# 认证 API（无需 JWT）
# ============================================================

@app.post("/api/auth/register", response_model=TokenResponse, tags=["认证"])
async def api_register(data: UserRegister):
    """注册新用户，返回 JWT token。"""
    return await register_user(data)


@app.post("/api/auth/login", response_model=TokenResponse, tags=["认证"])
async def api_login(data: UserLogin):
    """用户登录，返回 JWT token。"""
    return await login_user(data)


@app.get("/api/auth/me", tags=["认证"])
async def api_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return {
        "user_id": current_user["id"],
        "username": current_user["username"],
        "created_at": current_user.get("created_at", ""),
    }


# ============================================================
# 会话 API
# ============================================================

@app.get("/api/session", tags=["会话"])
async def get_session(current_user: dict = Depends(get_current_user)):
    """获取当前会话信息（创建新 session_id）。"""
    session_id = str(uuid.uuid4())[:8]
    return {"session_id": session_id, "is_new": True}


@app.post("/api/session/new", tags=["会话"])
async def new_session(current_user: dict = Depends(get_current_user)):
    """创建新会话。"""
    session_id = str(uuid.uuid4())[:8]
    return {"session_id": session_id}


@app.get("/api/conversations", tags=["会话"])
async def api_list_conversations(current_user: dict = Depends(get_current_user)):
    """获取当前用户的历史对话列表。"""
    convs = await list_conversations(current_user["id"])
    return {"conversations": convs}


@app.get("/api/conversations/{conv_id}/messages", tags=["会话"])
async def api_get_messages(conv_id: str, current_user: dict = Depends(get_current_user)):
    """获取指定会话的消息历史。"""
    msgs = await get_messages(conv_id)
    return {"messages": msgs}


@app.delete("/api/conversations/{conv_id}", tags=["会话"])
async def api_delete_conversation(conv_id: str, current_user: dict = Depends(get_current_user)):
    """删除指定对话。"""
    await delete_conversation(conv_id)
    return {"success": True}


# ============================================================
# 请求模型
# ============================================================

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    image_filename: Optional[str] = ""
    is_first_turn: bool = True


# ============================================================
# 聊天 API（非流式，兼容旧接口）
# ============================================================

@app.post("/api/chat", tags=["聊天"])
async def api_chat(
    data: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    聊天API（非流式）：支持文本+图片。
    """
    thread_id = data.session_id or str(uuid.uuid4())[:8]
    user_question = data.question.strip()

    if not user_question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    image_path = ""
    if data.image_filename:
        image_path = os.path.join(Config.UPLOAD_FOLDER, data.image_filename)
        if not os.path.exists(image_path):
            image_path = ""

    try:
        answer = run_agent(
            user_question=user_question,
            thread_id=thread_id,
            image_path=image_path,
            is_first_turn=data.is_first_turn,
            user_id=current_user["id"],
        )
        return {
            "answer": answer,
            "session_id": thread_id,
            "image_path": image_path,
            "error": None,
        }
    except Exception as e:
        logger.error("聊天处理失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 流式聊天 API（SSE）
# ============================================================

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
    thread_id = data.session_id or str(uuid.uuid4())[:8]
    user_question = data.question.strip()

    if not user_question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    image_path = ""
    if data.image_filename:
        image_path = os.path.join(Config.UPLOAD_FOLDER, data.image_filename)
        if not os.path.exists(image_path):
            image_path = ""

    logger.info(
        "流式聊天: user=%s, session=%s, question=%s..., first_turn=%s",
        current_user.get("username"), thread_id,
        user_question[:50], data.is_first_turn,
    )

    async def event_generator():
        """异步生成 SSE 事件流。"""
        async for event in run_agent_stream(
            user_question=user_question,
            thread_id=thread_id,
            image_path=image_path,
            is_first_turn=data.is_first_turn,
            user_id=current_user["id"],
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ============================================================
# 图片上传 API
# ============================================================

@app.post("/api/upload/image", tags=["上传"])
async def api_upload_image(
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传图片，返回文件名供后续chat使用。"""
    if not image.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    if not _allowed_file(image.filename, ALLOWED_IMAGE_EXT):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，允许: {ALLOWED_IMAGE_EXT}")

    from werkzeug.utils import secure_filename
    filename = secure_filename(image.filename)
    name, ext = os.path.splitext(filename)
    filename = f"{name}_{int(time.time())}{ext}"
    filepath = os.path.join(Config.UPLOAD_FOLDER, filename)

    content = await image.read()
    with open(filepath, "wb") as f:
        f.write(content)

    logger.info("图片已上传: %s", filename)
    return {"filename": filename, "path": filepath, "error": None}


# ============================================================
# 文档上传 API（RAG）
# ============================================================

@app.post("/api/upload/document", tags=["上传"])
async def api_upload_document(
    document: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传文档到RAG向量库。"""
    if not document.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    if not _allowed_file(document.filename, ALLOWED_DOC_EXT):
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    from werkzeug.utils import secure_filename
    filename = secure_filename(document.filename)

    raw = await document.read()
    try:
        content = raw.decode("utf-8", errors="replace")
    except Exception:
        content = raw.decode("latin-1", errors="replace")

    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 存入RAG向量库（同步调用 ChromaDB）
    chunk_count = add_document(content, filename)
    logger.info("文档已上传: %s (%d个切片)", filename, chunk_count)
    return {"filename": filename, "chunks": chunk_count, "error": None}


@app.get("/api/documents", tags=["文档"])
async def api_get_documents(current_user: dict = Depends(get_current_user)):
    """获取已上传的RAG文档列表。"""
    docs = list_documents()
    return {"documents": docs}


@app.delete("/api/documents/{filename}", tags=["文档"])
async def api_remove_document(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """删除指定RAG文档。"""
    success = delete_document(filename)
    return {"success": success}


# ============================================================
# 健康检查（无需认证）
# ============================================================

@app.get("/api/health", tags=["系统"])
async def health_check():
    """健康检查端点。"""
    return {"status": "ok", "version": "2.0.0"}


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, reload=True)