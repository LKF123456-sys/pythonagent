"""聊天相关数据模型。"""

from typing import Optional  # 导入可选类型注解

from pydantic import BaseModel, Field  # 导入 Pydantic 模型基类与字段定义工具


class ChatRequest(BaseModel):
    """非流式聊天请求。"""

    question: str = Field(  # 用户问题字段
        ..., min_length=1, max_length=10000,  # 必填，长度 1-10000
        description="用户问题文本",  # 字段描述
        examples=["什么是量子计算？"],  # 示例值
    )
    session_id: Optional[str] = Field(
        default=None, description="会话 ID，不传则自动生成"  # 会话 ID，可选，不传时后端自动生成
    )
    image_filename: Optional[str] = Field(
        default="", description="已上传图片的文件名（可选）"  # 关联图片文件名，可选
    )
    is_first_turn: bool = Field(
        default=True, description="是否为本轮会话的第一条消息"  # 是否为会话首条消息标志
    )


class ChatResponse(BaseModel):
    """非流式聊天响应。"""

    answer: str = Field(..., description="AI 回答")  # AI 回答文本字段
    session_id: str = Field(..., description="会话 ID")  # 会话 ID 字段
    token_count: int = Field(default=0, description="本次回答消耗的 token 数")  # 本次回答的 token 用量
    error: Optional[str] = Field(default=None, description="错误信息（无错误为 null）")  # 错误信息字段，无错误为 None


class UploadResponse(BaseModel):
    """文件上传响应。"""

    filename: str = Field(..., description="存储后的文件名")  # 存储后的文件名字段
    error: Optional[str] = Field(default=None, description="错误信息")  # 错误信息字段，无错误为 None


class DocumentUploadResponse(BaseModel):
    """文档上传（RAG）响应。"""

    filename: str = Field(..., description="文档文件名")  # 文档文件名字段
    chunks: int = Field(..., description="向量切片数量")  # 向量切片数量字段
    error: Optional[str] = Field(default=None, description="错误信息")  # 错误信息字段，无错误为 None
