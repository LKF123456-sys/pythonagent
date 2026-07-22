"""请求级上下文：request_id 贯穿日志 / 响应头，实现请求链路关联。

- `request_id_var`：ContextVar，供日志 Filter 注入，使同一请求的所有日志可聚合。
- `RequestIdMiddleware`：纯 ASGI 中间件（不新建任务，contextvar 天然向下传播）：
    - 优先复用上游传入的 ``X-Request-ID``（便于网关/前端串联链路）
    - 否则生成 16 位十六进制短 ID
    - 响应头回写 ``X-Request-ID``，便于前端/排查时与服务端日志对账
"""

import uuid  # 导入uuid模块，用于生成请求ID
from contextvars import ContextVar  # 从contextvars导入ContextVar，实现请求级上下文变量传播

from starlette.datastructures import MutableHeaders  # 从starlette导入可变头部结构，用于修改响应头
from starlette.types import ASGIApp, Message, Receive, Scope, Send  # 从starlette导入ASGI类型注解，用于中间件类型提示

# 当前请求的 request_id（默认 "-" 表示请求上下文之外，如启动日志）
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")  # 创建请求ID上下文变量，默认值"-"表示无请求上下文


def get_request_id() -> str:
    """获取当前请求的 request_id。"""
    return request_id_var.get()  # 返回当前上下文中的请求ID，无上下文时返回默认值"-"


class RequestIdMiddleware:
    """为每个 HTTP 请求注入 request_id 的纯 ASGI 中间件。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app  # 保存被包装的ASGI应用实例，用于后续调用

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # 若请求类型非HTTP（如websocket/lifespan）
            await self.app(scope, receive, send)  # 直接透传给下游应用，不做request_id处理
            return  # 返回，结束处理

        # 优先复用上游 X-Request-ID，否则生成短 ID
        request_id = ""  # 初始化请求ID为空字符串
        for header_name, header_value in scope.get("headers", []):  # 遍历请求头列表
            if header_name == b"x-request-id":  # 若找到X-Request-ID请求头
                request_id = header_value.decode("latin-1")  # 解码为字符串作为请求ID
                break  # 找到后跳出循环
        if not request_id:  # 若上游未传入请求ID
            request_id = uuid.uuid4().hex[:16]  # 生成16位十六进制短ID作为请求ID

        token = request_id_var.set(request_id)  # 将请求ID设置到上下文变量，返回token用于后续重置

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":  # 若为响应开始消息
                headers = MutableHeaders(scope=message)  # 创建可变头部对象，用于修改响应头
                headers.append("X-Request-ID", request_id)  # 向响应头追加X-Request-ID，便于前端对账
            await send(message)  # 调用原始send函数发送响应消息

        try:  # 尝试执行下游应用
            await self.app(scope, receive, send_with_request_id)  # 调用下游应用，传入包装后的send函数
        finally:  # 无论成功失败都执行清理
            request_id_var.reset(token)  # 重置上下文变量到设置前的状态，避免请求间串扰
