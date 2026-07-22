"""请求频率限制器（slowapi）：全局单例，供 main 与 router 共用。"""

from slowapi import Limiter  # 从slowapi导入Limiter限流器类，用于API请求频率限制
from slowapi.util import get_remote_address  # 从slowapi.util导入获取远程地址函数，用作限流的key函数

# 全局默认限制：60 次/分钟/IP（登录/注册端点单独收紧）
limiter = Limiter(  # 创建全局Limiter实例，供整个应用共用
    key_func=get_remote_address,  # 指定key函数为获取客户端IP地址，按IP维度限流
    default_limits=["60/minute"],  # 设置默认限流策略为每分钟60次请求
    headers_enabled=True,  # 启用限流响应头，返回RateLimit相关头信息便于客户端感知
)
