"""聊天业务编排：会话管理 + 历史上下文构建 + 图调用 + 持久化。"""

import asyncio
import os
import uuid
from typing import AsyncGenerator, Optional

from app.core.config import get_settings
from app.core.constants import MessageRole
from app.core.logging import setup_logger
from app.core.security import validate_upload_path
from app.agents.graph import GraphStreamEvent, run_agent, run_agent_stream
from app.agents.llm import compress_context, generate_title
from app.models.chat import ChatResponse
from app.repositories import conversation_repo, message_repo

logger = setup_logger("service.chat")


# ============================================================
# 内部辅助
# ============================================================

def _resolve_image_path(image_filename: str) -> str:
    """将已上传图片的文件名解析为安全绝对路径（路径遍历防护）。"""
    if not image_filename:
        return ""
    settings = get_settings()
    path = os.path.join(settings.UPLOAD_FOLDER, image_filename)
    if not validate_upload_path(path, settings.UPLOAD_FOLDER):
        logger.warning("检测到非法图片路径: %s", image_filename)
        return ""
    return path if os.path.exists(path) else ""


async def _build_history_context(session_id: str) -> tuple[str, bool]:
    """
    从数据库构建历史上下文（不含当前轮）。

    Returns:
        (history_context, is_first_turn)
    """
    settings = get_settings()
    messages = await message_repo.get_messages(session_id, limit=settings.MAX_HISTORY_TURNS * 2)
    if not messages:
        return "", True

    lines = []
    for msg in messages:
        role_label = "用户" if msg["role"] == MessageRole.USER.value else "助手"
        lines.append(f"{role_label}: {msg['content']}")
    history_text = "\n".join(lines)

    # 上下文压缩（超阈值时 LLM 摘要，替代简单截断）
    history_context = await compress_context(history_text)
    return history_context, False


async def _ensure_conversation(session_id: str, user_id: int, question: str) -> None:
    """确保会话记录存在（首轮创建，标题暂用问题截断）。"""
    existing = await conversation_repo.get_conversation(session_id, user_id)
    if existing is None:
        title = question[:20] + ("..." if len(question) > 20 else "")
        await conversation_repo.create_conversation(session_id, user_id, title)


async def _set_conversation_title(session_id: str, user_id: int, question: str) -> None:
    """异步生成并更新会话标题（首轮结束后调用）。"""
    try:
        title = await generate_title(question)
        await conversation_repo.rename_conversation(session_id, user_id, title)
        logger.info("会话标题已生成: %s -> %s", session_id, title)
    except Exception as e:
        logger.warning("会话标题生成失败（不影响主流程）: %s", e)


async def _finalize_turn(
    session_id: str,
    user_id: int,
    question: str,
    event: GraphStreamEvent,
    is_first_turn: bool,
) -> None:
    """一轮对话结束后的持久化：存助手消息、更新时间、异步生成标题。"""
    if event.answer:
        await message_repo.add_message(
            session_id, MessageRole.ASSISTANT.value, event.answer, event.token_count
        )
    await conversation_repo.update_conversation_time(session_id)
    if is_first_turn:
        asyncio.create_task(_set_conversation_title(session_id, user_id, question))


# ============================================================
# 流式聊天（WebSocket 消费）
# ============================================================

async def chat_stream(
    user_id: int,
    question: str,
    session_id: Optional[str] = None,
    image_filename: str = "",
) -> AsyncGenerator[GraphStreamEvent, None]:
    """
    流式聊天编排。

    产出 GraphStreamEvent 流（status/thinking/token/done/error），
    并在 done 事件时完成消息持久化与标题生成。
    """
    if not session_id:
        session_id = uuid.uuid4().hex

    image_path = _resolve_image_path(image_filename)
    history_context, is_first_turn = await _build_history_context(session_id)
    await _ensure_conversation(session_id, user_id, question)
    await message_repo.add_message(session_id, MessageRole.USER.value, question, image_filename=image_filename)

    async for event in run_agent_stream(
        user_question=question,
        thread_id=session_id,
        image_path=image_path,
        history_context=history_context,
        is_first_turn=is_first_turn,
        user_id=user_id,
    ):
        if event.type == "done":
            await _finalize_turn(session_id, user_id, question, event, is_first_turn)
        yield event


# ============================================================
# 非流式聊天（REST 消费）
# ============================================================

async def chat_non_stream(
    user_id: int,
    question: str,
    session_id: Optional[str] = None,
    image_filename: str = "",
) -> ChatResponse:
    """非流式聊天（ainvoke），返回完整回答。"""
    if not session_id:
        session_id = uuid.uuid4().hex

    image_path = _resolve_image_path(image_filename)
    history_context, is_first_turn = await _build_history_context(session_id)
    await _ensure_conversation(session_id, user_id, question)
    await message_repo.add_message(session_id, MessageRole.USER.value, question, image_filename=image_filename)

    try:
        answer = await run_agent(
            user_question=question,
            thread_id=session_id,
            image_path=image_path,
            history_context=history_context,
            is_first_turn=is_first_turn,
            user_id=user_id,
        )
    except Exception as e:
        logger.exception("非流式聊天失败")
        return ChatResponse(answer="", session_id=session_id, error=str(e))

    await message_repo.add_message(session_id, MessageRole.ASSISTANT.value, answer)
    await conversation_repo.update_conversation_time(session_id)
    if is_first_turn:
        asyncio.create_task(_set_conversation_title(session_id, user_id, question))

    return ChatResponse(answer=answer, session_id=session_id)
