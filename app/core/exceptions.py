"""业务异常定义：Service 层抛出，由全局异常处理器映射为 HTTP 响应。"""


class AppException(Exception):
    """应用异常基类。"""

    status_code: int = 500  # 默认HTTP状态码，500表示服务器内部错误
    detail: str = "服务器内部错误"  # 默认错误详情描述

    def __init__(self, detail: str | None = None):
        if detail is not None:  # 若传入了自定义错误详情
            self.detail = detail  # 用传入的详情覆盖默认详情
        super().__init__(self.detail)  # 调用父类构造函数，传入错误详情


class BadRequestError(AppException):
    """400 请求参数错误。"""

    status_code = 400  # HTTP状态码400，表示客户端请求参数错误


class UnauthorizedError(AppException):
    """401 未认证或凭证无效。"""

    status_code = 401  # HTTP状态码401，表示未认证
    detail = "未认证或凭证已失效"  # 错误详情，说明认证缺失或凭证过期


class ForbiddenError(AppException):
    """403 权限不足。"""

    status_code = 403  # HTTP状态码403，表示权限不足
    detail = "权限不足"  # 错误详情，说明用户权限不够


class NotFoundError(AppException):
    """404 资源不存在。"""

    status_code = 404  # HTTP状态码404，表示资源未找到
    detail = "资源不存在"  # 错误详情，说明请求的资源不存在


class ConflictError(AppException):
    """409 资源冲突（如用户名已存在）。"""

    status_code = 409  # HTTP状态码409，表示资源冲突


class PayloadTooLargeError(AppException):
    """413 文件超过大小限制。"""

    status_code = 413  # HTTP状态码413，表示请求体过大
    detail = "文件超过大小限制"  # 错误详情，说明上传文件超过大小限制
