"""聊天相关数据模型。"""

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """非流式聊天请求。"""

    question: str = Field(
        ..., min_length=1, max_length=10000,
        description="用户问题文本",
        examples=["什么是量子计算？"],
    )
    session_id: Optional[str] = Field(
        default=None, description="会话 ID，不传则自动生成"
    )
    image_filename: Optional[str] = Field(
        default="", description="已上传图片的文件名（可选）"
    )
    is_first_turn: bool = Field(
        default=True, description="是否为本轮会话的第一条消息"
    )


class ChatResponse(BaseModel):
    """非流式聊天响应。"""

    answer: str = Field(..., description="AI 回答")
    session_id: str = Field(..., description="会话 ID")
    token_count: int = Field(default=0, description="本次回答消耗的 token 数")
    error: Optional[str] = Field(default=None, description="错误信息（无错误为 null）")


class UploadResponse(BaseModel):
    """文件上传响应。"""

    filename: str = Field(..., description="存储后的文件名")
    error: Optional[str] = Field(default=None, description="错误信息")


class DocumentUploadResponse(BaseModel):
    """文档上传（RAG）响应。"""

    filename: str = Field(..., description="文档文件名")
    chunks: int = Field(..., description="向量切片数量")
    error: Optional[str] = Field(default=None, description="错误信息")
