"""认证业务逻辑：注册 / 登录 / 刷新 / 登出 + Token 黑名单。"""  # 模块级文档字符串，描述认证业务逻辑

from datetime import datetime, timezone  # 从datetime导入datetime类和timezone时区模块

from app.core.exceptions import ConflictError, UnauthorizedError  # 导入冲突错误和未授权异常
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.core.security import (  # 从安全模块导入多个函数
    create_access_token,  # 创建访问令牌函数
    create_refresh_token,  # 创建刷新令牌函数
    decode_token,  # 解码令牌函数
    hash_password,  # 密码哈希函数
    verify_password,  # 密码校验函数
)
from app.models.auth import TokenResponse  # 导入令牌响应模型
from app.repositories import user_repo  # 导入用户数据访问仓库

logger = setup_logger("service.auth")  # 创建名为service.auth的日志记录器


async def _build_token_response(user: dict) -> TokenResponse:  # 定义构造令牌响应的内部协程函数
    """为用户签发 access + refresh token，并将 refresh jti 入库。"""  # 函数文档字符串
    user_id = user["id"]  # 获取用户ID
    username = user["username"]  # 获取用户名
    is_admin = bool(user["is_admin"])  # 获取是否为管理员并转为布尔

    access_token = create_access_token(user_id, username, is_admin)  # 创建访问令牌
    refresh_token, refresh_jti, refresh_expire = create_refresh_token(user_id)  # 创建刷新令牌及其jti和过期时间
    await user_repo.store_refresh_token(refresh_jti, user_id, refresh_expire)  # 将刷新令牌的jti存入数据库

    return TokenResponse(  # 构造并返回令牌响应
        access_token=access_token,  # 访问令牌
        refresh_token=refresh_token,  # 刷新令牌
        token_type="bearer",  # 令牌类型为bearer
        user_id=user_id,  # 用户ID
        username=username,  # 用户名
        is_admin=is_admin,  # 是否管理员
    )


async def register_user(username: str, password: str) -> TokenResponse:  # 定义用户注册协程函数
    """注册新用户并直接签发令牌。用户名重复时抛出 ConflictError。"""  # 函数文档字符串
    username = username.strip()  # 去除用户名首尾空白
    password_hash = hash_password(password)  # 对密码进行哈希处理
    user_id = await user_repo.create_user(username, password_hash)  # 创建用户并获取ID
    if user_id is None:  # 如果用户ID为空（用户名已存在）
        raise ConflictError("用户名已存在")  # 抛出冲突异常

    logger.info("新用户注册: %s (id=%d)", username, user_id)  # 记录注册日志
    user = await user_repo.get_user_by_id(user_id)  # 查询新用户信息
    return await _build_token_response(user)  # 构造并返回令牌响应


async def authenticate_user(username: str, password: str) -> TokenResponse:  # 定义用户认证协程函数
    """验证用户名密码，成功则签发令牌。"""  # 函数文档字符串
    user = await user_repo.get_user_by_username(username.strip())  # 根据用户名查询用户
    if user is None or not verify_password(password, user["password_hash"]):  # 用户不存在或密码错误
        raise UnauthorizedError("用户名或密码错误")  # 抛出未授权异常
    if not user["is_active"]:  # 如果用户被禁用
        raise UnauthorizedError("账号已被禁用，请联系管理员")  # 抛出未授权异常

    return await _build_token_response(user)  # 构造并返回令牌响应


async def refresh_tokens(refresh_token: str) -> TokenResponse:  # 定义刷新令牌协程函数
    """
    使用 Refresh Token 换取新的令牌对（Refresh Token 轮换）。

    旧 refresh token 会被撤销，防止重放。
    """  # 函数文档字符串，描述轮换机制
    payload = decode_token(refresh_token)  # 解码刷新令牌
    if payload is None or payload.get("type") != "refresh":  # 解码失败或类型非refresh
        raise UnauthorizedError("刷新令牌无效或已过期")  # 抛出未授权异常

    jti = payload.get("jti", "")  # 获取令牌唯一标识
    user_id = int(payload.get("sub", "0"))  # 获取用户ID并转为整数

    if not await user_repo.is_refresh_token_valid(jti):  # 检查刷新令牌是否有效（未撤销）
        raise UnauthorizedError("刷新令牌已被撤销")  # 抛出未授权异常

    user = await user_repo.get_user_by_id(user_id)  # 查询用户信息
    if user is None or not user["is_active"]:  # 用户不存在或被禁用
        raise UnauthorizedError("用户不存在或已被禁用")  # 抛出未授权异常

    # 轮换：撤销旧 refresh token  # 内部注释说明轮换操作
    await user_repo.revoke_refresh_token(jti)  # 撤销旧刷新令牌
    return await _build_token_response(user)  # 构造并返回新令牌响应


async def logout(access_payload: dict, refresh_token: str | None = None) -> None:  # 定义登出协程函数
    """
    登出：将 access token 的 jti 加入黑名单，并撤销关联的 refresh token。
    """  # 函数文档字符串
    jti = access_payload.get("jti", "")  # 获取访问令牌的jti
    exp = access_payload.get("exp")  # 获取访问令牌的过期时间戳
    if jti and exp:  # 如果jti和exp都存在
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)  # 将时间戳转为UTC datetime
        await user_repo.blacklist_access_token(jti, expires_at)  # 将访问令牌加入黑名单

    if refresh_token:  # 如果提供了刷新令牌
        refresh_payload = decode_token(refresh_token)  # 解码刷新令牌
        if refresh_payload and refresh_payload.get("type") == "refresh":  # 如果解码成功且类型正确
            await user_repo.revoke_refresh_token(refresh_payload.get("jti", ""))  # 撤销刷新令牌

    logger.info("用户登出: sub=%s", access_payload.get("sub"))  # 记录登出日志
