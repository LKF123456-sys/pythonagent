"""认证相关数据模型。"""

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    """用户注册请求。"""

    username: str = Field(
        ..., min_length=2, max_length=50,
        description="用户名，2-50 字符",
        examples=["alice"],
    )
    password: str = Field(
        ..., min_length=6, max_length=128,
        description="密码，至少 6 位",
        examples=["secret123"],
    )


class UserLogin(BaseModel):
    """用户登录请求。"""

    username: str = Field(..., description="用户名", examples=["alice"])
    password: str = Field(..., description="密码", examples=["secret123"])


class TokenResponse(BaseModel):
    """登录/注册成功的 Token 响应。"""

    access_token: str = Field(..., description="JWT 访问令牌（30 分钟有效）")
    refresh_token: str = Field(..., description="刷新令牌（7 天有效）")
    token_type: str = Field(default="bearer", description="令牌类型")
    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    is_admin: bool = Field(default=False, description="是否为管理员")


class RefreshRequest(BaseModel):
    """刷新 Token 请求。"""

    refresh_token: str = Field(..., description="刷新令牌")


class UserInfo(BaseModel):
    """当前用户信息。"""

    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    is_admin: bool = Field(default=False, description="是否为管理员")
    created_at: str = Field(default="", description="注册时间")
