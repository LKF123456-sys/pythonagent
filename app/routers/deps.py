"""FastAPI 依赖注入：当前用户 / 管理员守卫 / Token 校验。"""  # 模块级文档字符串，描述本模块提供依赖注入功能

from fastapi import Depends  # 从FastAPI导入依赖注入装饰器
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # 从FastAPI安全模块导入Bearer认证相关组件

from app.core.exceptions import ForbiddenError, UnauthorizedError  # 导入禁止访问和未授权异常类
from app.core.security import decode_token  # 导入JWT令牌解码函数
from app.repositories import user_repo  # 导入用户数据访问仓库

_bearer_scheme = HTTPBearer(auto_error=False)  # 创建Bearer认证方案，auto_error=False表示缺失时不自动报错


async def verify_access_token(token: str) -> dict:  # 定义访问令牌校验协程函数
    """
    校验 Access Token 并返回用户信息。

    供 HTTP Bearer 依赖与 WebSocket 查询参数共用。
    校验链：解码 → 类型 → 黑名单 → 用户存在且激活。
    """  # 函数文档字符串，描述校验流程
    payload = decode_token(token)  # 解码JWT令牌，获取负载字典
    if payload is None or payload.get("type") != "access":  # 如果解码失败或类型不是access
        raise UnauthorizedError("认证凭证无效或已过期")  # 抛出未授权异常

    jti = payload.get("jti", "")  # 获取令牌唯一标识jti
    if await user_repo.is_access_token_blacklisted(jti):  # 检查令牌是否在黑名单中
        raise UnauthorizedError("认证凭证已被撤销")  # 已撤销则抛出异常

    user_id = int(payload.get("sub", "0"))  # 从负载获取用户ID并转为整数
    user = await user_repo.get_user_by_id(user_id)  # 根据用户ID查询用户信息
    if user is None or not user["is_active"]:  # 如果用户不存在或被禁用
        raise UnauthorizedError("用户不存在或已被禁用")  # 抛出未授权异常
    return user  # 返回用户信息字典


async def get_current_user(  # 定义获取当前用户的依赖函数
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # 依赖注入Bearer认证凭证
) -> dict:  # 返回用户字典
    """从 Authorization: Bearer <token> 解析当前用户。"""  # 函数文档字符串
    if credentials is None:  # 如果凭证缺失
        raise UnauthorizedError("缺少认证凭证")  # 抛出未授权异常
    return await verify_access_token(credentials.credentials)  # 校验令牌并返回用户


async def get_admin_user(user: dict = Depends(get_current_user)) -> dict:  # 定义管理员守卫依赖函数，依赖当前用户
    """管理员守卫：非管理员抛出 403。"""  # 函数文档字符串
    if not user["is_admin"]:  # 如果当前用户不是管理员
        raise ForbiddenError("需要管理员权限")  # 抛出禁止访问异常
    return user  # 返回管理员用户信息
