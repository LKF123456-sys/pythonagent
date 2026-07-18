"""
JWT 认证模块：用户注册、登录、token 验证。
使用 python-jose 签发 JWT，bcrypt 哈希密码。
"""

# 从datetime模块导入datetime、timedelta和timezone，用于时间处理
from datetime import datetime, timedelta, timezone
# 导入类型提示模块
from typing import Optional, Dict

# 导入bcrypt库，用于密码哈希
import bcrypt
# 从fastapi导入Depends、HTTPException和status，用于依赖注入和HTTP异常处理
from fastapi import Depends, HTTPException, status
# 从fastapi.security导入HTTPBearer和HTTPAuthorizationCredentials，用于Bearer Token认证
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# 从jose导入JWTError和jwt，用于JWT token的签发和解析
from jose import JWTError, jwt
# 从pydantic导入BaseModel，用于请求/响应数据模型定义
from pydantic import BaseModel

# 导入配置模块
from config import Config
# 导入数据库操作函数
from database import create_user, get_user_by_username, get_user_by_id
# 导入日志设置函数
from logger import setup_logger

# 初始化日志记录器
logger = setup_logger("auth", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# 密码哈希（直接使用 bcrypt，避免 passlib 与 bcrypt 5.x 的兼容问题）
# ============================================================

# bcrypt算法限制明文密码最长为72字节，超出部分需要截断
_BCRYPT_MAX_BYTES = 72

# ============================================================
# Bearer Token 提取
# ============================================================

# 创建HTTPBearer实例，用于从请求头中提取Bearer Token
security = HTTPBearer()


# ============================================================
# 请求/响应模型
# ============================================================

class UserRegister(BaseModel):
    """用户注册请求模型"""
    # 用户名字段，字符串类型
    username: str
    # 密码字段，字符串类型
    password: str


class UserLogin(BaseModel):
    """用户登录请求模型"""
    # 用户名字段，字符串类型
    username: str
    # 密码字段，字符串类型
    password: str


class TokenResponse(BaseModel):
    """Token响应模型"""
    # JWT访问token字段
    access_token: str
    # token类型，默认为"bearer"
    token_type: str = "bearer"
    # 用户ID字段
    user_id: int
    # 用户名字段
    username: str


# ============================================================
# 密码工具
# ============================================================

def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。"""
    # 将密码字符串编码为UTF-8字节，并截断到bcrypt支持的最大72字节
    pw_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    # 使用bcrypt生成盐值并哈希密码，返回解码后的字符串
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配。"""
    try:
        # 将明文密码编码为UTF-8字节并截断
        pw_bytes = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        # 使用bcrypt验证密码是否匹配
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # 捕获值错误或类型错误（如哈希格式不正确），返回False
        return False


# ============================================================
# JWT Token 签发与解析
# ============================================================

def create_access_token(user_id: int, username: str) -> str:
    """签发 JWT access token。"""
    # 计算token过期时间：当前UTC时间 + 配置的过期分钟数
    expire = datetime.now(timezone.utc) + timedelta(minutes=Config.JWT_EXPIRE_MINUTES)
    # 构建JWT payload
    payload = {
        "sub": str(user_id),      # subject：用户ID（字符串类型）
        "username": username,      # 用户名
        "exp": expire,             # 过期时间
    }
    # 使用配置的密钥和算法签发JWT token并返回
    return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict]:
    """解码 JWT token，返回 payload。过期或无效返回 None。"""
    try:
        # 使用密钥和算法解码JWT token
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
        # 从payload中提取用户ID
        user_id = payload.get("sub")
        # 从payload中提取用户名
        username = payload.get("username")
        # 如果用户ID为空，返回None
        if user_id is None:
            return None
        # 返回包含用户ID和用户名的字典（user_id转换为整数）
        return {"user_id": int(user_id), "username": username}
    except JWTError as e:
        # 捕获JWT错误（过期、签名无效等），记录警告日志并返回None
        logger.warning("JWT 解码失败: %s", e)
        return None


# ============================================================
# FastAPI 依赖注入：获取当前用户
# ============================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict:
    """
    FastAPI 依赖：从 Authorization header 提取并验证 JWT，返回当前用户信息。
    如果 token 无效，抛出 401。
    """
    # 从凭证中提取token字符串
    token = credentials.credentials
    # 解码JWT token获取payload
    payload = decode_access_token(token)
    # 如果payload为空（token无效或过期），抛出401未授权异常
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的 token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 根据payload中的user_id从数据库查询用户信息
    user = await get_user_by_id(payload["user_id"])
    # 如果用户不存在或账户已禁用，抛出401未授权异常
    if user is None or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )
    # 返回用户信息字典
    return user


# ============================================================
# 注册和登录逻辑
# ============================================================

async def register_user(data: UserRegister) -> TokenResponse:
    """注册新用户并返回 token。"""
    # 验证用户名长度：2-50字符之间
    if len(data.username) < 2 or len(data.username) > 50:
        raise HTTPException(status_code=400, detail="用户名长度需在 2-50 字符之间")
    # 验证密码长度：至少6位
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度不能少于 6 位")

    # 对密码进行bcrypt哈希
    hashed = hash_password(data.password)
    # 在数据库中创建用户，获取用户ID
    user_id = await create_user(data.username, hashed)
    # 如果user_id为None，说明用户名已存在，抛出409冲突异常
    if user_id is None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    # 为新用户签发JWT access token
    token = create_access_token(user_id, data.username)
    # 记录用户注册成功日志
    logger.info("用户注册成功: %s (id=%d)", data.username, user_id)
    # 返回TokenResponse对象
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        username=data.username,
    )


async def login_user(data: UserLogin) -> TokenResponse:
    """用户登录，验证密码后返回 token。"""
    # 根据用户名从数据库查询用户信息
    user = await get_user_by_username(data.username)
    # 如果用户不存在，抛出401未授权异常
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # 验证密码是否匹配，不匹配则抛出401异常
    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # 检查账户是否激活，未激活则抛出403禁止访问异常
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="账户已被禁用")

    # 为用户签发JWT access token
    token = create_access_token(user["id"], user["username"])
    # 记录用户登录成功日志
    logger.info("用户登录成功: %s", data.username)
    # 返回TokenResponse对象
    return TokenResponse(
        access_token=token,
        user_id=user["id"],
        username=user["username"],
    )
