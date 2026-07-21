"""请求级上下文：request_id 贯穿日志 / 响应头，实现请求链路关联。

- `request_id_var`：ContextVar，供日志 Filter 注入，使同一请求的所有日志可聚合。
- `RequestIdMiddleware`：纯 ASGI 中间件（不新建任务，contextvar 天然向下传播）：
    - 优先复用上游传入的 ``X-Request-ID``（便于网关/前端串联链路）
    - 否则生成 16 位十六进制短 ID
    - 响应头回写 ``X-Request-ID``，便于前端/排查时与服务端日志对账
"""

import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 当前请求的 request_id（默认 "-" 表示请求上下文之外，如启动日志）
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """获取当前请求的 request_id。"""
    return request_id_var.get()


class RequestIdMiddleware:
    """为每个 HTTP 请求注入 request_id 的纯 ASGI 中间件。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 优先复用上游 X-Request-ID，否则生成短 ID
        request_id = ""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"x-request-id":
                request_id = header_value.decode("latin-1")
                break
        if not request_id:
            request_id = uuid.uuid4().hex[:16]

        token = request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
