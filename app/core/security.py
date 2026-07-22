"""安全模块：密码哈希、JWT 签发/验证/黑名单、文件名消毒、路径防护。"""

import os  # 导入操作系统接口模块，用于路径操作
import re  # 导入正则表达式模块，用于文件名消毒
import uuid  # 导入UUID模块，用于生成唯一标识符
from datetime import datetime, timedelta, timezone  # 从datetime导入日期时间相关类，用于JWT过期时间计算
from typing import Optional, Dict  # 从typing导入Optional和Dict类型注解，用于类型提示

import bcrypt  # 导入bcrypt库，用于密码哈希与验证
from jose import JWTError, jwt  # 从jose导入JWT错误类和JWT编解码模块，用于JWT签发与解析

from app.core.config import get_settings  # 导入配置获取函数，读取JWT密钥与算法
from app.core.constants import BCRYPT_MAX_BYTES  # 导入bcrypt最大字节数常量，用于密码截断
from app.core.logging import setup_logger  # 导入日志配置函数，创建安全模块日志记录器

logger = setup_logger("security")  # 创建名为security的日志记录器实例


# ============================================================
# 密码哈希
# ============================================================

def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希（自动截断至 72 字节限制）。"""
    pw_bytes = password.encode("utf-8")[:BCRYPT_MAX_BYTES]  # 将密码编码为UTF-8字节并截断至bcrypt最大字节数限制
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")  # 使用bcrypt对密码进行哈希并解码为字符串返回


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配。"""
    try:  # 尝试验证密码
        pw_bytes = plain.encode("utf-8")[:BCRYPT_MAX_BYTES]  # 将明文密码编码为UTF-8字节并截断至bcrypt最大字节数
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))  # 使用bcrypt比对明文密码与哈希，返回布尔结果
    except (ValueError, TypeError):  # 若哈希格式无效或类型错误
        return False  # 验证失败返回False


# ============================================================
# JWT Token 签发与解析
# ============================================================

def create_access_token(user_id: int, username: str, is_admin: bool = False) -> str:
    """签发短期 JWT access token（含 jti 用于撤销追踪）。"""
    settings = get_settings()  # 获取全局配置实例
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES)  # 计算access token过期时间，UTC当前时间加上配置的分钟数
    payload = {  # 构建JWT负载字典
        "sub": str(user_id),  # subject字段，用户ID的字符串形式
        "username": username,  # username字段，用户名
        "is_admin": is_admin,  # is_admin字段，是否为管理员
        "jti": str(uuid.uuid4()),  # JWT ID字段，唯一标识符用于token撤销追踪
        "type": "access",  # type字段，标记为access token类型
        "exp": expire,  # expiration字段，过期时间
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)  # 使用配置的密钥与算法对负载进行JWT编码并返回


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """
    签发 Refresh Token。

    Returns:
        (token, jti, expire_at) 三元组，jti 和 expire_at 需存入数据库
    """
    settings = get_settings()  # 获取全局配置实例
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)  # 计算refresh token过期时间，UTC当前时间加上配置的天数
    jti = str(uuid.uuid4())  # 生成唯一标识符用于token撤销追踪
    payload = {  # 构建JWT负载字典
        "sub": str(user_id),  # subject字段，用户ID的字符串形式
        "jti": jti,  # JWT ID字段，唯一标识符
        "type": "refresh",  # type字段，标记为refresh token类型
        "exp": expire,  # expiration字段，过期时间
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)  # 使用配置的密钥与算法对负载进行JWT编码
    return token, jti, expire  # 返回token、jti和过期时间三元组


def decode_token(token: str) -> Optional[Dict]:
    """解码 JWT token，返回 payload。无效或过期返回 None。"""
    settings = get_settings()  # 获取全局配置实例
    try:  # 尝试解码JWT
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])  # 使用配置的密钥与算法解码token并返回负载字典
    except JWTError as e:  # 若解码失败（过期/签名错误等）
        logger.warning("JWT 解码失败: %s", e)  # 记录警告日志
        return None  # 返回None表示解码失败


# ============================================================
# 文件名消毒与路径防护（替代 werkzeug.secure_filename）
# ============================================================

# 匹配不安全字符：路径分隔符、控制字符、特殊符号
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')  # 编译正则表达式，匹配文件名中的不安全字符


def sanitize_filename(filename: str) -> str:
    """
    纯 Python 文件名消毒：
    1. 去除路径分隔符和危险字符
    2. 仅保留最后一个路径段（防止 ../ 注入）
    3. 添加 UUID 前缀确保唯一性
    """
    # 取最后一个路径段，防止目录穿越
    basename = os.path.basename(filename.replace("\\", "/"))  # 将反斜杠替换为正斜杠后取最后一段路径，防止目录穿越
    # 移除不安全字符
    cleaned = _UNSAFE_FILENAME_RE.sub("", basename)  # 使用正则替换移除文件名中的不安全字符
    # 移除前导点号（防止隐藏文件）和空格
    cleaned = cleaned.lstrip(". ")  # 移除文件名开头的前导点号和空格，防止创建隐藏文件
    # 如果清理后为空，使用默认名
    if not cleaned:  # 若清理后文件名为空
        cleaned = "upload"  # 使用默认文件名upload
    # UUID 前缀确保唯一且不可预测
    return f"{uuid.uuid4().hex[:12]}_{cleaned}"  # 拼接12位UUID十六进制前缀与清理后的文件名，确保唯一性和不可预测性


def validate_upload_path(filepath: str, allowed_root: str) -> bool:
    """路径遍历防护：校验最终路径必须在允许的根目录内。"""
    real_root = os.path.realpath(allowed_root)  # 获取允许根目录的真实绝对路径（解析符号链接）
    real_path = os.path.realpath(filepath)  # 获取文件路径的真实绝对路径（解析符号链接和../）
    return real_path.startswith(real_root + os.sep) or real_path == real_root  # 校验文件路径是否在根目录内（是根目录本身或其子路径）


def is_allowed_extension(filename: str, allowed_set: set) -> bool:
    """检查文件扩展名是否在允许集合中。"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set  # 检查文件名含点且扩展名(小写)在允许集合中
