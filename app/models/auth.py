"""认证相关数据模型。"""

from pydantic import BaseModel, Field  # 导入 Pydantic 模型基类与字段定义工具


class UserRegister(BaseModel):
    """用户注册请求。"""

    username: str = Field(  # 用户名字段
        ..., min_length=2, max_length=50,  # 必填，长度 2-50
        description="用户名，2-50 字符",  # 字段描述（用于 OpenAPI 文档）
        examples=["alice"],  # 示例值
    )
    password: str = Field(  # 密码字段
        ..., min_length=6, max_length=128,  # 必填，长度 6-128
        description="密码，至少 6 位",  # 字段描述
        examples=["secret123"],  # 示例值
    )


class UserLogin(BaseModel):
    """用户登录请求。"""

    username: str = Field(..., description="用户名", examples=["alice"])  # 用户名字段，必填
    password: str = Field(..., description="密码", examples=["secret123"])  # 密码字段，必填


class TokenResponse(BaseModel):
    """登录/注册成功的 Token 响应。"""

    access_token: str = Field(..., description="JWT 访问令牌（30 分钟有效）")  # 访问令牌字段
    refresh_token: str = Field(..., description="刷新令牌（7 天有效）")  # 刷新令牌字段
    token_type: str = Field(default="bearer", description="令牌类型")  # 令牌类型，默认 bearer
    user_id: int = Field(..., description="用户 ID")  # 用户 ID 字段
    username: str = Field(..., description="用户名")  # 用户名字段
    is_admin: bool = Field(default=False, description="是否为管理员")  # 是否管理员标志，默认 False


class RefreshRequest(BaseModel):
    """刷新 Token 请求。"""

    refresh_token: str = Field(..., description="刷新令牌")  # 刷新令牌字段，必填


class UserInfo(BaseModel):
    """当前用户信息。"""

    user_id: int = Field(..., description="用户 ID")  # 用户 ID 字段
    username: str = Field(..., description="用户名")  # 用户名字段
    is_admin: bool = Field(default=False, description="是否为管理员")  # 是否管理员标志
    created_at: str = Field(default="", description="注册时间")  # 注册时间字段，默认空字符串
