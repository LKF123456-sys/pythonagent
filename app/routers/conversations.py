"""会话路由：列表 / 消息 / 重命名 / 删除 / 导出 / Token 统计。"""

from fastapi import APIRouter, Depends, Query, Response

from app.models.conversation import (
    ConversationItem,
    ConversationListResponse,
    MessageItem,
    MessageListResponse,
    RenameRequest,
    TokenStatsItem,
    TokenStatsResponse,
)
from app.routers.deps import get_current_user
from app.services import conversation_service

router = APIRouter(prefix="/api/conversations", tags=["会话"])


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    conv_type: str = Query(default="general", pattern="^(general|mfg)$"),
    user: dict = Depends(get_current_user),
) -> ConversationListResponse:
    """获取当前用户的会话列表（支持按类型过滤：general/mfg）。"""
    rows = await conversation_service.list_conversations(user["id"], conv_type)
    return ConversationListResponse(
        conversations=[ConversationItem(**row) for row in rows]
    )


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def get_messages(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> MessageListResponse:
    """获取会话的消息列表。"""
    rows = await conversation_service.get_messages(session_id, user["id"])
    return MessageListResponse(messages=[MessageItem(**row) for row in rows])


@router.patch("/{session_id}", status_code=204)
async def rename_conversation(
    session_id: str,
    body: RenameRequest,
    user: dict = Depends(get_current_user),
) -> None:
    """重命名会话。"""
    await conversation_service.rename_conversation(session_id, user["id"], body.title)


@router.delete("/{session_id}", status_code=204)
async def delete_conversation(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> None:
    """删除会话及其全部消息。"""
    await conversation_service.delete_conversation(session_id, user["id"])


@router.get("/{session_id}/export")
async def export_conversation(
    session_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    user: dict = Depends(get_current_user),
) -> Response:
    """导出会话为 Markdown 或 JSON 文件。"""
    content = await conversation_service.export_conversation(session_id, user["id"], format)
    if format == "json":
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}.json"'
            },
        )
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{session_id}.md"'
        },
    )


# ============================================================
# Token 统计（独立前缀，避免与 /{session_id} 冲突）
# ============================================================

stats_router = APIRouter(prefix="/api/stats", tags=["统计"])


@stats_router.get("/tokens", response_model=TokenStatsResponse)
async def token_stats(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(get_current_user),
) -> TokenStatsResponse:
    """获取当前用户的 Token 用量统计（累计 + 按日）。"""
    stats = await conversation_service.get_token_stats(user["id"], days)
    return TokenStatsResponse(
        total_tokens=stats["total_tokens"],
        daily=[TokenStatsItem(**row) for row in stats["daily"]],
    )
