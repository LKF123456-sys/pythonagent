"""聊天路由：WebSocket 双向通信（替代 SSE）+ 非流式端点 + 图片上传。"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, WebSocket, WebSocketDisconnect

from app.core.constants import WSClientEvent, WSEventType
from app.core.exceptions import AppException, UnauthorizedError
from app.core.logging import setup_logger
from app.agents.graph import GraphStreamEvent
from app.models.chat import ChatRequest, ChatResponse, UploadResponse
from app.routers.deps import get_current_user, verify_access_token
from app.services import chat_service, document_service

logger = setup_logger("router.chat")

router = APIRouter(tags=["聊天"])


# ============================================================
# WebSocket 连接管理器
# ============================================================

class ConnectionManager:
    """管理多用户并发 WebSocket 连接。"""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}

    def connect(self, user_id: int, websocket: WebSocket) -> None:
        self._connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        conns = self._connections.get(user_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                del self._connections[user_id]

    def active_count(self, user_id: Optional[int] = None) -> int:
        if user_id is not None:
            return len(self._connections.get(user_id, set()))
        return sum(len(conns) for conns in self._connections.values())


manager = ConnectionManager()


# ============================================================
# 事件序列化
# ============================================================

def _event_to_wire(event: GraphStreamEvent, session_id: str) -> dict:
    """将 GraphStreamEvent 映射为 WebSocket 线缆协议（JSON）。"""
    if event.type == "status":
        return {
            "type": WSEventType.STATUS.value,
            "node": event.node,
            "message": event.content,
            "session_id": session_id,
        }
    if event.type == "thinking":
        return {"type": WSEventType.THINKING.value, "content": event.content}
    if event.type == "token":
        return {"type": WSEventType.TOKEN.value, "content": event.content}
    if event.type == "done":
        return {
            "type": WSEventType.DONE.value,
            "answer": event.answer,
            "session_id": session_id,
            "route": event.route,
            "token_count": event.token_count,
        }
    if event.type == "error":
        return {"type": WSEventType.ERROR.value, "message": event.content}
    return {"type": event.type}


async def _run_chat_stream(
    websocket: WebSocket,
    user_id: int,
    session_id: str,
    question: str,
    image_filename: str,
) -> None:
    """在独立任务中执行聊天流，将事件推送至 WebSocket（可被取消）。"""
    try:
        async for event in chat_service.chat_stream(
            user_id=user_id,
            question=question,
            session_id=session_id,
            image_filename=image_filename,
        ):
            await websocket.send_json(_event_to_wire(event, session_id))
    except asyncio.CancelledError:
        # 用户中断生成：由主循环发送 aborted done 事件
        raise
    except Exception as e:
        logger.exception("WebSocket 聊天流出错")
        try:
            await websocket.send_json(
                {"type": WSEventType.ERROR.value, "message": f"处理失败：{e}"}
            )
        except Exception:
            pass


# ============================================================
# WebSocket 端点
# ============================================================

@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:
    """
    聊天 WebSocket 端点。

    客户端→服务端：
      {"type": "chat", "question": "...", "image_filename": "..."}
      {"type": "abort"}
      {"type": "ping"}
    服务端→客户端：
      {"type": "status|thinking|token|done|error|pong", ...}
    """
    # 连接前认证（token 无效直接拒绝握手）
    try:
        user = await verify_access_token(token)
    except AppException:
        await websocket.close(code=4401, reason="认证失败")
        return

    await websocket.accept()
    user_id = user["id"]
    manager.connect(user_id, websocket)
    logger.info("WebSocket 已连接: user=%d session=%s", user_id, session_id)

    current_task: Optional[asyncio.Task] = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": WSEventType.ERROR.value, "message": "消息格式无效"}
                )
                continue

            mtype = msg.get("type", "")

            if mtype == WSClientEvent.PING.value:
                await websocket.send_json({"type": WSEventType.PONG.value})

            elif mtype == WSClientEvent.CHAT.value:
                question = (msg.get("question") or "").strip()
                image_filename = msg.get("image_filename") or ""
                if not question:
                    await websocket.send_json(
                        {"type": WSEventType.ERROR.value, "message": "问题不能为空"}
                    )
                    continue
                # 取消上一轮未完成的流
                if current_task and not current_task.done():
                    current_task.cancel()
                current_task = asyncio.create_task(
                    _run_chat_stream(websocket, user_id, session_id, question, image_filename)
                )

            elif mtype == WSClientEvent.ABORT.value:
                if current_task and not current_task.done():
                    current_task.cancel()
                    await websocket.send_json(
                        {
                            "type": WSEventType.DONE.value,
                            "answer": "",
                            "session_id": session_id,
                            "aborted": True,
                        }
                    )

    except WebSocketDisconnect:
        logger.info("WebSocket 断开: user=%d", user_id)
    except Exception as e:
        logger.warning("WebSocket 异常: %s", e)
    finally:
        if current_task and not current_task.done():
            current_task.cancel()
        manager.disconnect(user_id, websocket)


# ============================================================
# REST 端点（非流式 + 图片上传）
# ============================================================

@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
) -> ChatResponse:
    """非流式聊天（同步返回完整回答）。"""
    return await chat_service.chat_non_stream(
        user_id=user["id"],
        question=body.question,
        session_id=body.session_id,
        image_filename=body.image_filename or "",
    )


@router.post("/api/chat/upload-image", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> UploadResponse:
    """上传聊天图片（校验类型/大小/路径），返回存储文件名。"""
    content = await file.read()
    saved_name = document_service.save_image_upload(content, file.filename or "image.png")
    return UploadResponse(filename=saved_name)
