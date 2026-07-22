"""认证路由：注册 / 登录 / 刷新 / 登出 / 当前用户。"""  # 模块级文档字符串，描述认证路由提供的服务

from fastapi import APIRouter, Depends, Request, Response  # 从FastAPI导入路由器、依赖注入、请求和响应对象

from app.core.rate_limit import limiter  # 导入频率限制器实例，用于对敏感接口限流
from app.core.security import decode_token  # 导入JWT令牌解码函数
from app.models.auth import (  # 从认证模型模块导入多个Pydantic模型
    RefreshRequest,  # 刷新令牌请求模型
    TokenResponse,  # 令牌响应模型
    UserInfo,  # 用户信息模型
    UserLogin,  # 用户登录模型
    UserRegister,  # 用户注册模型
)
from app.routers.deps import get_current_user  # 导入获取当前用户的依赖，用于身份校验
from app.services import auth_service  # 导入认证业务逻辑服务模块

router = APIRouter(prefix="/auth", tags=["认证"])  # 创建认证路由器，设置URL前缀为/auth和API文档标签


@router.post("/register", response_model=TokenResponse, status_code=201)  # 注册POST路由，注册新用户，成功返回201
@limiter.limit("10/minute")  # 应用频率限制：每分钟最多10次
async def register(request: Request, response: Response, body: UserRegister) -> TokenResponse:  # 定义异步注册函数
    """注册新用户并返回令牌对。"""  # 路由文档字符串
    return await auth_service.register_user(body.username, body.password)  # 调用服务层注册用户并返回令牌


@router.post("/login", response_model=TokenResponse)  # 注册POST路由，用户登录
@limiter.limit("15/minute")  # 应用频率限制：每分钟最多15次
async def login(request: Request, response: Response, body: UserLogin) -> TokenResponse:  # 定义异步登录函数
    """用户登录，返回令牌对。"""  # 路由文档字符串
    return await auth_service.authenticate_user(body.username, body.password)  # 调用服务层进行身份认证并返回令牌


@router.post("/refresh", response_model=TokenResponse)  # 注册POST路由，使用刷新令牌换取新令牌
async def refresh(body: RefreshRequest) -> TokenResponse:  # 定义异步刷新令牌函数
    """使用 Refresh Token 换取新令牌对（旧 refresh token 轮换作废）。"""  # 路由文档字符串
    return await auth_service.refresh_tokens(body.refresh_token)  # 调用服务层刷新令牌


@router.post("/logout", status_code=204)  # 注册POST路由，用户登出，返回204无内容
async def logout(  # 定义异步登出函数
    request: Request,  # 请求对象，用于获取请求头
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
    body: RefreshRequest | None = None,  # 可选请求体，包含刷新令牌
) -> None:  # 无返回值
    """登出：撤销当前 access token，并可选撤销 refresh token。"""  # 路由文档字符串
    # 从请求头取出 access token 的 jti  # 内部注释，说明下面从请求头取令牌
    auth_header = request.headers.get("Authorization", "")  # 从请求头获取Authorization字段，默认空字符串
    access_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""  # 去除Bearer前缀，得到纯令牌
    payload = decode_token(access_token) or {}  # 解码令牌获取负载，失败则使用空字典
    await auth_service.logout(payload, body.refresh_token if body else None)  # 调用服务层执行登出操作


@router.get("/me", response_model=UserInfo)  # 注册GET路由，获取当前登录用户信息
async def me(user: dict = Depends(get_current_user)) -> UserInfo:  # 定义异步函数，依赖注入当前用户
    """获取当前登录用户信息。"""  # 路由文档字符串
    return UserInfo(  # 构造并返回用户信息响应模型
        user_id=user["id"],  # 用户ID
        username=user["username"],  # 用户名
        is_admin=bool(user["is_admin"]),  # 是否为管理员，转为布尔类型
        created_at=user.get("created_at", ""),  # 创建时间，不存在则空字符串
    )
