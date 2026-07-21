"""安全模块：密码哈希、JWT 签发/验证/黑名单、文件名消毒、路径防护。"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.constants import BCRYPT_MAX_BYTES
from app.core.logging import setup_logger

logger = setup_logger("security")


# ============================================================
# 密码哈希
# ============================================================

def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希（自动截断至 72 字节限制）。"""
    pw_bytes = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配。"""
    try:
        pw_bytes = plain.encode("utf-8")[:BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ============================================================
# JWT Token 签发与解析
# ============================================================

def create_access_token(user_id: int, username: str, is_admin: bool = False) -> str:
    """签发短期 JWT access token（含 jti 用于撤销追踪）。"""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "jti": str(uuid.uuid4()),
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """
    签发 Refresh Token。

    Returns:
        (token, jti, expire_at) 三元组，jti 和 expire_at 需存入数据库
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "exp": expire,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti, expire


def decode_token(token: str) -> Optional[Dict]:
    """解码 JWT token，返回 payload。无效或过期返回 None。"""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        logger.warning("JWT 解码失败: %s", e)
        return None


# ============================================================
# 文件名消毒与路径防护（替代 werkzeug.secure_filename）
# ============================================================

# 匹配不安全字符：路径分隔符、控制字符、特殊符号
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(filename: str) -> str:
    """
    纯 Python 文件名消毒：
    1. 去除路径分隔符和危险字符
    2. 仅保留最后一个路径段（防止 ../ 注入）
    3. 添加 UUID 前缀确保唯一性
    """
    # 取最后一个路径段，防止目录穿越
    basename = os.path.basename(filename.replace("\\", "/"))
    # 移除不安全字符
    cleaned = _UNSAFE_FILENAME_RE.sub("", basename)
    # 移除前导点号（防止隐藏文件）和空格
    cleaned = cleaned.lstrip(". ")
    # 如果清理后为空，使用默认名
    if not cleaned:
        cleaned = "upload"
    # UUID 前缀确保唯一且不可预测
    return f"{uuid.uuid4().hex[:12]}_{cleaned}"


def validate_upload_path(filepath: str, allowed_root: str) -> bool:
    """路径遍历防护：校验最终路径必须在允许的根目录内。"""
    real_root = os.path.realpath(allowed_root)
    real_path = os.path.realpath(filepath)
    return real_path.startswith(real_root + os.sep) or real_path == real_root


def is_allowed_extension(filename: str, allowed_set: set) -> bool:
    """检查文件扩展名是否在允许集合中。"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set
