"""
JWT 认证模块：用户注册、登录、token 验证。
使用 python-jose 签发 JWT，passlib[bcrypt] 哈希密码。
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from config import Config
from database import create_user, get_user_by_username, get_user_by_id
from logger import setup_logger

logger = setup_logger("auth", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# 密码哈希（直接使用 bcrypt，避免 passlib 与 bcrypt 5.x 的兼容问题）
# ============================================================

# bcrypt 限制明文最长 72 字节，超出部分需截断
_BCRYPT_MAX_BYTES = 72

# ============================================================
# Bearer Token 提取
# ============================================================

security = HTTPBearer()


# ============================================================
# 请求/响应模型
# ============================================================

class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


# ============================================================
# 密码工具
# ============================================================

def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。"""
    pw_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配。"""
    try:
        pw_bytes = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ============================================================
# JWT Token 签发与解析
# ============================================================

def create_access_token(user_id: int, username: str) -> str:
    """签发 JWT access token。"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=Config.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
    }
    return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict]:
    """解码 JWT token，返回 payload。过期或无效返回 None。"""
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
        user_id = payload.get("sub")
        username = payload.get("username")
        if user_id is None:
            return None
        return {"user_id": int(user_id), "username": username}
    except JWTError as e:
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
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的 token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_id(payload["user_id"])
    if user is None or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )
    return user


# ============================================================
# 注册和登录逻辑
# ============================================================

async def register_user(data: UserRegister) -> TokenResponse:
    """注册新用户并返回 token。"""
    if len(data.username) < 2 or len(data.username) > 50:
        raise HTTPException(status_code=400, detail="用户名长度需在 2-50 字符之间")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度不能少于 6 位")

    hashed = hash_password(data.password)
    user_id = await create_user(data.username, hashed)
    if user_id is None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    token = create_access_token(user_id, data.username)
    logger.info("用户注册成功: %s (id=%d)", data.username, user_id)
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        username=data.username,
    )


async def login_user(data: UserLogin) -> TokenResponse:
    """用户登录，验证密码后返回 token。"""
    user = await get_user_by_username(data.username)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="账户已被禁用")

    token = create_access_token(user["id"], user["username"])
    logger.info("用户登录成功: %s", data.username)
    return TokenResponse(
        access_token=token,
        user_id=user["id"],
        username=user["username"],
    )
