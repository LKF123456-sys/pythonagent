"""认证业务逻辑：注册 / 登录 / 刷新 / 登出 + Token 黑名单。"""

from datetime import datetime, timezone

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.logging import setup_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.auth import TokenResponse
from app.repositories import user_repo

logger = setup_logger("service.auth")


async def _build_token_response(user: dict) -> TokenResponse:
    """为用户签发 access + refresh token，并将 refresh jti 入库。"""
    user_id = user["id"]
    username = user["username"]
    is_admin = bool(user["is_admin"])

    access_token = create_access_token(user_id, username, is_admin)
    refresh_token, refresh_jti, refresh_expire = create_refresh_token(user_id)
    await user_repo.store_refresh_token(refresh_jti, user_id, refresh_expire)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user_id=user_id,
        username=username,
        is_admin=is_admin,
    )


async def register_user(username: str, password: str) -> TokenResponse:
    """注册新用户并直接签发令牌。用户名重复时抛出 ConflictError。"""
    username = username.strip()
    password_hash = hash_password(password)
    user_id = await user_repo.create_user(username, password_hash)
    if user_id is None:
        raise ConflictError("用户名已存在")

    logger.info("新用户注册: %s (id=%d)", username, user_id)
    user = await user_repo.get_user_by_id(user_id)
    return await _build_token_response(user)


async def authenticate_user(username: str, password: str) -> TokenResponse:
    """验证用户名密码，成功则签发令牌。"""
    user = await user_repo.get_user_by_username(username.strip())
    if user is None or not verify_password(password, user["password_hash"]):
        raise UnauthorizedError("用户名或密码错误")
    if not user["is_active"]:
        raise UnauthorizedError("账号已被禁用，请联系管理员")

    return await _build_token_response(user)


async def refresh_tokens(refresh_token: str) -> TokenResponse:
    """
    使用 Refresh Token 换取新的令牌对（Refresh Token 轮换）。

    旧 refresh token 会被撤销，防止重放。
    """
    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise UnauthorizedError("刷新令牌无效或已过期")

    jti = payload.get("jti", "")
    user_id = int(payload.get("sub", "0"))

    if not await user_repo.is_refresh_token_valid(jti):
        raise UnauthorizedError("刷新令牌已被撤销")

    user = await user_repo.get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        raise UnauthorizedError("用户不存在或已被禁用")

    # 轮换：撤销旧 refresh token
    await user_repo.revoke_refresh_token(jti)
    return await _build_token_response(user)


async def logout(access_payload: dict, refresh_token: str | None = None) -> None:
    """
    登出：将 access token 的 jti 加入黑名单，并撤销关联的 refresh token。
    """
    jti = access_payload.get("jti", "")
    exp = access_payload.get("exp")
    if jti and exp:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        await user_repo.blacklist_access_token(jti, expires_at)

    if refresh_token:
        refresh_payload = decode_token(refresh_token)
        if refresh_payload and refresh_payload.get("type") == "refresh":
            await user_repo.revoke_refresh_token(refresh_payload.get("jti", ""))

    logger.info("用户登出: sub=%s", access_payload.get("sub"))
