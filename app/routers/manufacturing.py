"""工业智能制造路由：WebSocket 双向通信 + 故障码查询 + 文档上传 + 会话持久化 REST 端点。"""

import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.constants import WSClientEvent, WSEventType
from app.core.exceptions import AppException
from app.core.logging import setup_logger
from app.core.security import validate_upload_path
from app.agents.manufacturing.graph import MfgGraphStreamEvent, run_mfg_agent_stream
from app.repositories import conversation_repo, message_repo
from app.routers.deps import get_current_user, verify_access_token
from app.services import document_service

logger = setup_logger("router.manufacturing")

router = APIRouter(tags=["工业智能制造"])


# ============================================================
# WebSocket 连接管理器（工业专属）
# ============================================================

class MfgConnectionManager:
    """管理工业模块多用户并发 WebSocket 连接。"""

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


mfg_manager = MfgConnectionManager()


# ============================================================
# 事件序列化
# ============================================================

def _mfg_event_to_wire(event: MfgGraphStreamEvent, session_id: str) -> dict:
    """将 MfgGraphStreamEvent 映射为 WebSocket 线缆协议。"""
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


async def _run_mfg_chat_stream(
    websocket: WebSocket,
    user_id: int,
    session_id: str,
    question: str,
    image_filename: str = "",
) -> None:
    """在独立任务中执行工业聊天流，将事件推送至 WebSocket，并持久化会话。"""
    # 解析图片路径
    image_path = ""
    if image_filename:
        settings = get_settings()
        candidate = os.path.join(settings.UPLOAD_FOLDER, image_filename)
        if validate_upload_path(candidate, settings.UPLOAD_FOLDER) and os.path.isfile(candidate):
            image_path = candidate

    # 持久化：确保会话存在 + 存储用户消息
    try:
        existing = await conversation_repo.get_conversation(session_id, user_id)
        if existing is None:
            title = question[:20] + ("..." if len(question) > 20 else "")
            await conversation_repo.create_conversation(session_id, user_id, title, conv_type="mfg")
        await message_repo.add_message(session_id, "user", question, image_filename=image_filename)
    except Exception as e:
        logger.warning("工业会话持久化失败（不影响回答）: %s", e)

    try:
        final_answer = ""
        final_tokens = 0
        async for event in run_mfg_agent_stream(
            user_question=question,
            thread_id=f"mfg_{session_id}",
            history_context="",
            user_id=user_id,
            image_path=image_path,
        ):
            await websocket.send_json(_mfg_event_to_wire(event, session_id))
            if event.type == "done":
                final_answer = event.answer
                final_tokens = event.token_count

        # 持久化：存储助手回答
        if final_answer:
            try:
                await message_repo.add_message(session_id, "assistant", final_answer, final_tokens)
                await conversation_repo.update_conversation_time(session_id)
            except Exception as e:
                logger.warning("工业回答持久化失败: %s", e)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("WebSocket 工业聊天流出错")
        try:
            await websocket.send_json(
                {"type": WSEventType.ERROR.value, "message": f"处理失败：{e}"}
            )
        except Exception:
            pass


# ============================================================
# WebSocket 端点
# ============================================================

@router.websocket("/ws/manufacturing/{session_id}")
async def websocket_manufacturing(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:
    """
    工业智能制造 WebSocket 端点。

    客户端→服务端：
      {"type": "chat", "question": "..."}
      {"type": "abort"}
      {"type": "ping"}
    服务端→客户端：
      {"type": "status|thinking|token|done|error|pong", ...}
    """
    # 连接前认证
    try:
        user = await verify_access_token(token)
    except AppException:
        await websocket.close(code=4401, reason="认证失败")
        return

    await websocket.accept()
    user_id = user["id"]
    mfg_manager.connect(user_id, websocket)
    logger.info("工业 WebSocket 已连接: user=%d session=%s", user_id, session_id)

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
                    _run_mfg_chat_stream(websocket, user_id, session_id, question, image_filename)
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
        logger.info("工业 WebSocket 断开: user=%d", user_id)
    except Exception as e:
        logger.warning("工业 WebSocket 异常: %s", e)
    finally:
        if current_task and not current_task.done():
            current_task.cancel()
        mfg_manager.disconnect(user_id, websocket)


# ============================================================
# REST 端点：故障码查询
# ============================================================

@router.get("/api/manufacturing/fault-codes")
async def query_fault_codes(code: str = Query(default="", description="故障码关键词")):
    """查询故障码信息（支持模糊搜索）。"""
    try:
        from app.agents.manufacturing.knowledge import search_fault_codes
        results = search_fault_codes(code)
        return {"success": True, "data": results, "count": len(results)}
    except Exception as e:
        logger.warning("故障码查询失败: %s", e)
        return {"success": False, "error": str(e), "data": [], "count": 0}


@router.get("/api/manufacturing/equipment")
async def query_equipment(model: str = Query(default="", description="设备型号")):
    """查询设备参数信息。"""
    try:
        from app.agents.manufacturing.knowledge import search_equipment_specs
        results = search_equipment_specs(model)
        return {"success": True, "data": results, "count": len(results)}
    except Exception as e:
        logger.warning("设备参数查询失败: %s", e)
        return {"success": False, "error": str(e), "data": [], "count": 0}


# ============================================================
# REST 端点：工业图片上传（复用通用上传逻辑）
# ============================================================

@router.post("/api/manufacturing/upload-image")
async def upload_mfg_image(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """上传工业场景图片（设备铭牌、故障截图、仪表盘等），返回存储文件名。"""
    content = await file.read()
    saved_name = document_service.save_image_upload(content, file.filename or "image.png")
    return {"filename": saved_name}


# ============================================================
# REST 端点：工业 RAG 文档上传
# ============================================================

@router.post("/api/manufacturing/documents/upload")
async def upload_mfg_document(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """上传工业文档到 RAG 知识库（解析 + 语义切片 + 向量化入库）。"""
    content = await file.read()
    filename = file.filename or "document.txt"
    chunks = await document_service.ingest_document(content, filename)
    return {"filename": filename, "chunks": chunks}


@router.get("/api/manufacturing/documents")
async def list_mfg_documents(user: dict = Depends(get_current_user)):
    """列出工业 RAG 知识库中的所有文档。"""
    documents = await document_service.list_documents()
    return {"documents": documents, "total": len(documents)}


@router.delete("/api/manufacturing/documents/{filename}", status_code=204)
async def delete_mfg_document(
    filename: str,
    user: dict = Depends(get_current_user),
) -> None:
    """删除指定工业文档及其全部向量切片。"""
    from app.core.exceptions import NotFoundError
    deleted = await document_service.delete_document(filename)
    if not deleted:
        raise NotFoundError("文档不存在")


# ============================================================
# REST 端点：图片服务（让前端能在对话中显示图片）
# ============================================================

@router.get("/api/uploads/{filename}")
async def serve_upload(filename: str, token: str = Query(default="")):
    """提供已上传图片的访问（支持 query token 认证，用于 img src）。"""
    try:
        await verify_access_token(token)
    except AppException:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="认证失败")
    settings = get_settings()
    filepath = os.path.join(settings.UPLOAD_FOLDER, filename)
    if not validate_upload_path(filepath, settings.UPLOAD_FOLDER) or not os.path.isfile(filepath):
        from app.core.exceptions import NotFoundError
        raise NotFoundError("文件不存在")
    return FileResponse(filepath)
