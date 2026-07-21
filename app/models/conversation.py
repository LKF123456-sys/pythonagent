"""会话相关数据模型。"""

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class ConversationItem(BaseModel):
    """会话列表项。"""

    session_id: str = Field(..., description="会话 ID")
    title: str = Field(..., description="会话标题")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后活跃时间")


class ConversationListResponse(BaseModel):
    """会话列表响应。"""

    conversations: List[ConversationItem] = Field(default_factory=list, description="会话列表")


class MessageItem(BaseModel):
    """消息项。"""

    role: str = Field(..., description="消息角色：user / assistant")
    content: str = Field(..., description="消息内容")
    token_count: int = Field(default=0, description="token 用量")
    image_filename: str = Field(default="", description="关联图片文件名")
    created_at: datetime = Field(default=None, description="创建时间")


class MessageListResponse(BaseModel):
    """消息列表响应。"""

    messages: List[MessageItem] = Field(default_factory=list, description="消息列表")


class RenameRequest(BaseModel):
    """会话重命名请求。"""

    title: str = Field(..., min_length=1, max_length=100, description="新标题")


class TokenStatsItem(BaseModel):
    """Token 统计项。"""

    date: str = Field(..., description="日期 (YYYY-MM-DD)")
    total_tokens: int = Field(..., description="当日 token 总量")
    message_count: int = Field(..., description="当日消息数")


class TokenStatsResponse(BaseModel):
    """Token 统计响应。"""

    total_tokens: int = Field(..., description="累计 token 总量")
    daily: List[TokenStatsItem] = Field(default_factory=list, description="按日统计")
