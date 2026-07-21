"""请求频率限制器（slowapi）：全局单例，供 main 与 router 共用。"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# 全局默认限制：60 次/分钟/IP（登录/注册端点单独收紧）
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    headers_enabled=True,
)
