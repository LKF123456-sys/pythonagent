"""FastAPI 依赖注入：当前用户 / 管理员守卫 / Token 校验。"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.repositories import user_repo

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_access_token(token: str) -> dict:
    """
    校验 Access Token 并返回用户信息。

    供 HTTP Bearer 依赖与 WebSocket 查询参数共用。
    校验链：解码 → 类型 → 黑名单 → 用户存在且激活。
    """
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise UnauthorizedError("认证凭证无效或已过期")

    jti = payload.get("jti", "")
    if await user_repo.is_access_token_blacklisted(jti):
        raise UnauthorizedError("认证凭证已被撤销")

    user_id = int(payload.get("sub", "0"))
    user = await user_repo.get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        raise UnauthorizedError("用户不存在或已被禁用")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """从 Authorization: Bearer <token> 解析当前用户。"""
    if credentials is None:
        raise UnauthorizedError("缺少认证凭证")
    return await verify_access_token(credentials.credentials)


async def get_admin_user(user: dict = Depends(get_current_user)) -> dict:
    """管理员守卫：非管理员抛出 403。"""
    if not user["is_admin"]:
        raise ForbiddenError("需要管理员权限")
    return user
