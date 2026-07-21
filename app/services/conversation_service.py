"""会话业务逻辑：列表 / 消息 / 重命名 / 删除 / 导出 / Token 统计。"""

import json

from app.core.exceptions import NotFoundError
from app.core.logging import setup_logger
from app.repositories import conversation_repo, message_repo

logger = setup_logger("service.conversation")


async def list_conversations(user_id: int, conv_type: str = "general") -> list[dict]:
    """获取用户指定类型的会话列表（按更新时间倒序）。"""
    return await conversation_repo.list_conversations(user_id, conv_type)


async def get_messages(session_id: str, user_id: int) -> list[dict]:
    """获取会话消息（校验用户归属）。"""
    await _assert_ownership(session_id, user_id)
    return await message_repo.get_messages(session_id)


async def rename_conversation(session_id: str, user_id: int, title: str) -> None:
    """重命名会话（校验归属）。"""
    ok = await conversation_repo.rename_conversation(session_id, user_id, title)
    if not ok:
        raise NotFoundError("会话不存在")


async def delete_conversation(session_id: str, user_id: int) -> None:
    """删除会话及其全部消息（校验归属）。"""
    await _assert_ownership(session_id, user_id)
    await conversation_repo.delete_conversation(session_id)
    logger.info("会话已删除: %s (user=%d)", session_id, user_id)


async def export_conversation(session_id: str, user_id: int, fmt: str) -> str:
    """
    导出会话为 Markdown 或 JSON 文本。

    Args:
        fmt: "markdown" 或 "json"
    """
    conv = await _assert_ownership(session_id, user_id)
    messages = await message_repo.get_messages(session_id)

    if fmt == "json":
        payload = {
            "session_id": session_id,
            "title": conv["title"],
            "created_at": conv["created_at"],
            "messages": messages,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # Markdown 格式
    lines = [f"# {conv['title']}", "", f"> 创建时间：{conv['created_at']}", ""]
    for msg in messages:
        role_label = "**用户**" if msg["role"] == "user" else "**助手**"
        lines.append(f"## {role_label}")
        lines.append("")
        lines.append(msg["content"])
        lines.append("")
    return "\n".join(lines)


async def get_token_stats(user_id: int, days: int = 30) -> dict:
    """获取用户的 Token 用量统计（累计 + 按日）。"""
    total = await message_repo.get_total_token_count(user_id)
    daily = await message_repo.get_daily_token_stats(user_id, days)
    return {"total_tokens": total, "daily": daily}


async def _assert_ownership(session_id: str, user_id: int) -> dict:
    """校验会话归属，不存在则抛 NotFoundError。"""
    conv = await conversation_repo.get_conversation(session_id, user_id)
    if conv is None:
        raise NotFoundError("会话不存在")
    return conv

