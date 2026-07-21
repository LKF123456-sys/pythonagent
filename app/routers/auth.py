"""认证路由：注册 / 登录 / 刷新 / 登出 / 当前用户。"""

from fastapi import APIRouter, Depends, Request, Response

from app.core.rate_limit import limiter
from app.core.security import decode_token
from app.models.auth import (
    RefreshRequest,
    TokenResponse,
    UserInfo,
    UserLogin,
    UserRegister,
)
from app.routers.deps import get_current_user
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("10/minute")
async def register(request: Request, response: Response, body: UserRegister) -> TokenResponse:
    """注册新用户并返回令牌对。"""
    return await auth_service.register_user(body.username, body.password)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("15/minute")
async def login(request: Request, response: Response, body: UserLogin) -> TokenResponse:
    """用户登录，返回令牌对。"""
    return await auth_service.authenticate_user(body.username, body.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest) -> TokenResponse:
    """使用 Refresh Token 换取新令牌对（旧 refresh token 轮换作废）。"""
    return await auth_service.refresh_tokens(body.refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    user: dict = Depends(get_current_user),
    body: RefreshRequest | None = None,
) -> None:
    """登出：撤销当前 access token，并可选撤销 refresh token。"""
    # 从请求头取出 access token 的 jti
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    payload = decode_token(access_token) or {}
    await auth_service.logout(payload, body.refresh_token if body else None)


@router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)) -> UserInfo:
    """获取当前登录用户信息。"""
    return UserInfo(
        user_id=user["id"],
        username=user["username"],
        is_admin=bool(user["is_admin"]),
        created_at=user.get("created_at", ""),
    )
