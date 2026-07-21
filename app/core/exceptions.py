"""业务异常定义：Service 层抛出，由全局异常处理器映射为 HTTP 响应。"""


class AppException(Exception):
    """应用异常基类。"""

    status_code: int = 500
    detail: str = "服务器内部错误"

    def __init__(self, detail: str | None = None):
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class BadRequestError(AppException):
    """400 请求参数错误。"""

    status_code = 400


class UnauthorizedError(AppException):
    """401 未认证或凭证无效。"""

    status_code = 401
    detail = "未认证或凭证已失效"


class ForbiddenError(AppException):
    """403 权限不足。"""

    status_code = 403
    detail = "权限不足"


class NotFoundError(AppException):
    """404 资源不存在。"""

    status_code = 404
    detail = "资源不存在"


class ConflictError(AppException):
    """409 资源冲突（如用户名已存在）。"""

    status_code = 409


class PayloadTooLargeError(AppException):
    """413 文件超过大小限制。"""

    status_code = 413
    detail = "文件超过大小限制"
