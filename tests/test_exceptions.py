"""异常类单元测试：覆盖所有业务异常类的实例化、状态码、详情。

测试策略：
- 实例化：覆盖默认构造与自定义详情构造
- 状态码：验证每种异常的 HTTP 状态码正确
- 详情：验证默认详情与自定义详情
- 继承：验证所有异常继承自 AppException 与 Exception
"""

import pytest  # 导入 pytest 测试框架

from app.core.exceptions import (  # 导入被测的异常类
    AppException,  # 导入应用异常基类
    BadRequestError,  # 导入 400 异常
    ConflictError,  # 导入 409 异常
    ForbiddenError,  # 导入 403 异常
    NotFoundError,  # 导入 404 异常
    PayloadTooLargeError,  # 导入 413 异常
    UnauthorizedError,  # 导入 401 异常
)


# ============================================================
# AppException 基类测试
# ============================================================

class TestAppException:
    """测试应用异常基类。"""

    def test_default_status_code(self):
        """测试默认状态码为 500。"""
        # 创建异常实例
        exc = AppException()  # 创建实例
        # 断言状态码为 500
        assert exc.status_code == 500  # 验证状态码

    def test_default_detail(self):
        """测试默认详情。"""
        # 创建异常实例
        exc = AppException()  # 创建实例
        # 断言默认详情为"服务器内部错误"
        assert exc.detail == "服务器内部错误"  # 验证默认详情

    def test_custom_detail(self):
        """测试自定义详情。"""
        # 创建带自定义详情的异常
        exc = AppException(detail="自定义错误")  # 创建实例
        # 断言详情为自定义值
        assert exc.detail == "自定义错误"  # 验证自定义详情

    def test_none_detail_uses_default(self):
        """测试传入 None 详情使用默认值。"""
        # 创建传入 None 详情的异常
        exc = AppException(detail=None)  # 创建实例
        # 断言使用默认详情
        assert exc.detail == "服务器内部错误"  # 验证默认详情

    def test_is_exception_subclass(self):
        """测试 AppException 继承自 Exception。"""
        # 断言 AppException 是 Exception 的子类
        assert issubclass(AppException, Exception)  # 验证继承关系

    def test_can_be_raised(self):
        """测试异常可以被抛出。"""
        # 断言抛出 AppException
        with pytest.raises(AppException):  # 期望抛出异常
            raise AppException("测试异常")  # 抛出异常

    def test_str_representation(self):
        """测试异常的字符串表示。"""
        # 创建异常实例
        exc = AppException(detail="错误信息")  # 创建实例
        # 断言字符串表示包含错误信息
        assert "错误信息" in str(exc)  # 验证字符串表示


# ============================================================
# BadRequestError 测试
# ============================================================

class TestBadRequestError:
    """测试 400 请求参数错误。"""

    def test_status_code(self):
        """测试状态码为 400。"""
        # 创建异常实例
        exc = BadRequestError()  # 创建实例
        # 断言状态码为 400
        assert exc.status_code == 400  # 验证状态码

    def test_is_app_exception_subclass(self):
        """测试继承自 AppException。"""
        # 断言继承关系
        assert issubclass(BadRequestError, AppException)  # 验证继承

    def test_custom_detail(self):
        """测试自定义详情。"""
        # 创建带自定义详情的异常
        exc = BadRequestError(detail="参数错误")  # 创建实例
        # 断言详情为自定义值
        assert exc.detail == "参数错误"  # 验证详情

    def test_default_detail(self):
        """测试默认详情。"""
        # 创建异常实例
        exc = BadRequestError()  # 创建实例
        # 断言默认详情为"服务器内部错误"（继承自基类）
        assert exc.detail == "服务器内部错误"  # 验证默认详情


# ============================================================
# UnauthorizedError 测试
# ============================================================

class TestUnauthorizedError:
    """测试 401 未认证错误。"""

    def test_status_code(self):
        """测试状态码为 401。"""
        # 创建异常实例
        exc = UnauthorizedError()  # 创建实例
        # 断言状态码为 401
        assert exc.status_code == 401  # 验证状态码

    def test_default_detail(self):
        """测试默认详情。"""
        # 创建异常实例
        exc = UnauthorizedError()  # 创建实例
        # 断言默认详情
        assert exc.detail == "未认证或凭证已失效"  # 验证默认详情

    def test_custom_detail(self):
        """测试自定义详情。"""
        # 创建带自定义详情的异常
        exc = UnauthorizedError(detail="token 过期")  # 创建实例
        # 断言详情为自定义值
        assert exc.detail == "token 过期"  # 验证详情


# ============================================================
# ForbiddenError 测试
# ============================================================

class TestForbiddenError:
    """测试 403 权限不足错误。"""

    def test_status_code(self):
        """测试状态码为 403。"""
        # 创建异常实例
        exc = ForbiddenError()  # 创建实例
        # 断言状态码为 403
        assert exc.status_code == 403  # 验证状态码

    def test_default_detail(self):
        """测试默认详情。"""
        # 创建异常实例
        exc = ForbiddenError()  # 创建实例
        # 断言默认详情
        assert exc.detail == "权限不足"  # 验证默认详情

    def test_custom_detail(self):
        """测试自定义详情。"""
        # 创建带自定义详情的异常
        exc = ForbiddenError(detail="无管理员权限")  # 创建实例
        # 断言详情为自定义值
        assert exc.detail == "无管理员权限"  # 验证详情


# ============================================================
# NotFoundError 测试
# ============================================================

class TestNotFoundError:
    """测试 404 资源不存在错误。"""

    def test_status_code(self):
        """测试状态码为 404。"""
        # 创建异常实例
        exc = NotFoundError()  # 创建实例
        # 断言状态码为 404
        assert exc.status_code == 404  # 验证状态码

    def test_default_detail(self):
        """测试默认详情。"""
        # 创建异常实例
        exc = NotFoundError()  # 创建实例
        # 断言默认详情
        assert exc.detail == "资源不存在"  # 验证默认详情

    def test_custom_detail(self):
        """测试自定义详情。"""
        # 创建带自定义详情的异常
        exc = NotFoundError(detail="用户不存在")  # 创建实例
        # 断言详情为自定义值
        assert exc.detail == "用户不存在"  # 验证详情


# ============================================================
# ConflictError 测试
# ============================================================

class TestConflictError:
    """测试 409 资源冲突错误。"""

    def test_status_code(self):
        """测试状态码为 409。"""
        # 创建异常实例
        exc = ConflictError()  # 创建实例
        # 断言状态码为 409
        assert exc.status_code == 409  # 验证状态码

    def test_custom_detail(self):
        """测试自定义详情。"""
        # 创建带自定义详情的异常
        exc = ConflictError(detail="用户名已存在")  # 创建实例
        # 断言详情为自定义值
        assert exc.detail == "用户名已存在"  # 验证详情


# ============================================================
# PayloadTooLargeError 测试
# ============================================================

class TestPayloadTooLargeError:
    """测试 413 请求体过大错误。"""

    def test_status_code(self):
        """测试状态码为 413。"""
        # 创建异常实例
        exc = PayloadTooLargeError()  # 创建实例
        # 断言状态码为 413
        assert exc.status_code == 413  # 验证状态码

    def test_default_detail(self):
        """测试默认详情。"""
        # 创建异常实例
        exc = PayloadTooLargeError()  # 创建实例
        # 断言默认详情
        assert exc.detail == "文件超过大小限制"  # 验证默认详情

    def test_custom_detail(self):
        """测试自定义详情。"""
        # 创建带自定义详情的异常
        exc = PayloadTooLargeError(detail="文件超过 20MB")  # 创建实例
        # 断言详情为自定义值
        assert exc.detail == "文件超过 20MB"  # 验证详情


# ============================================================
# 异常继承关系测试
# ============================================================

class TestExceptionInheritance:
    """测试异常类的继承关系。"""

    def test_all_exceptions_inherit_app_exception(self):
        """测试所有异常继承自 AppException。"""
        # 遍历所有异常类
        exceptions = [  # 定义异常类列表
            BadRequestError,  # 400 异常
            UnauthorizedError,  # 401 异常
            ForbiddenError,  # 403 异常
            NotFoundError,  # 404 异常
            ConflictError,  # 409 异常
            PayloadTooLargeError,  # 413 异常
        ]  # 异常类列表
        # 遍历验证继承关系
        for exc_class in exceptions:  # 遍历异常类
            # 断言继承自 AppException
            assert issubclass(exc_class, AppException)  # 验证继承关系

    def test_all_exceptions_inherit_exception(self):
        """测试所有异常继承自 Exception。"""
        # 遍历所有异常类
        exceptions = [  # 定义异常类列表
            AppException,  # 基类
            BadRequestError,  # 400 异常
            UnauthorizedError,  # 401 异常
            ForbiddenError,  # 403 异常
            NotFoundError,  # 404 异常
            ConflictError,  # 409 异常
            PayloadTooLargeError,  # 413 异常
        ]  # 异常类列表
        # 遍历验证继承关系
        for exc_class in exceptions:  # 遍历异常类
            # 断言继承自 Exception
            assert issubclass(exc_class, Exception)  # 验证继承关系

    def test_status_codes_distinct(self):
        """测试各异常状态码不同。"""
        # 收集所有状态码
        status_codes = [  # 定义状态码列表
            AppException().status_code,  # 500
            BadRequestError().status_code,  # 400
            UnauthorizedError().status_code,  # 401
            ForbiddenError().status_code,  # 403
            NotFoundError().status_code,  # 404
            ConflictError().status_code,  # 409
            PayloadTooLargeError().status_code,  # 413
        ]  # 状态码列表
        # 断言状态码唯一
        assert len(status_codes) == len(set(status_codes))  # 验证状态码唯一
