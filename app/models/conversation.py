"""会话相关数据模型。"""

from datetime import datetime  # 导入 datetime 类型，用于时间字段注解
from typing import List  # 导入列表类型注解

from pydantic import BaseModel, Field  # 导入 Pydantic 模型基类与字段定义工具


class ConversationItem(BaseModel):
    """会话列表项。"""

    session_id: str = Field(..., description="会话 ID")  # 会话 ID 字段
    title: str = Field(..., description="会话标题")  # 会话标题字段
    created_at: datetime = Field(..., description="创建时间")  # 创建时间字段
    updated_at: datetime = Field(..., description="最后活跃时间")  # 最后活跃时间字段


class ConversationListResponse(BaseModel):
    """会话列表响应。"""

    conversations: List[ConversationItem] = Field(default_factory=list, description="会话列表")  # 会话列表，默认空列表


class MessageItem(BaseModel):
    """消息项。"""

    role: str = Field(..., description="消息角色：user / assistant")  # 消息角色字段
    content: str = Field(..., description="消息内容")  # 消息内容字段
    token_count: int = Field(default=0, description="token 用量")  # token 用量字段，默认 0
    image_filename: str = Field(default="", description="关联图片文件名")  # 关联图片文件名字段，默认空字符串
    created_at: datetime = Field(default=None, description="创建时间")  # 创建时间字段，默认 None


class MessageListResponse(BaseModel):
    """消息列表响应。"""

    messages: List[MessageItem] = Field(default_factory=list, description="消息列表")  # 消息列表，默认空列表


class RenameRequest(BaseModel):
    """会话重命名请求。"""

    title: str = Field(..., min_length=1, max_length=100, description="新标题")  # 新标题字段，必填，长度 1-100


class TokenStatsItem(BaseModel):
    """Token 统计项。"""

    date: str = Field(..., description="日期 (YYYY-MM-DD)")  # 日期字符串字段
    total_tokens: int = Field(..., description="当日 token 总量")  # 当日 token 总量字段
    message_count: int = Field(..., description="当日消息数")  # 当日消息数字段


class TokenStatsResponse(BaseModel):
    """Token 统计响应。"""

    total_tokens: int = Field(..., description="累计 token 总量")  # 累计 token 总量字段
    daily: List[TokenStatsItem] = Field(default_factory=list, description="按日统计")  # 按日统计列表，默认空列表
