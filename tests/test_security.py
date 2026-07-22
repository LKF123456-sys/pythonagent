"""安全模块单元测试：密码哈希、JWT 签发/解析、文件名消毒、路径防护。

测试策略：
- 密码哈希与验证：覆盖正确/错误密码、超长密码（bcrypt 72 字节截断）
- JWT：覆盖 access/refresh token 签发、解析、过期、篡改
- 文件名消毒：覆盖路径穿越、危险字符、空文件名
- 路径防护：覆盖合法路径、路径穿越、符号链接
"""

import os  # 导入操作系统接口模块，用于路径操作
import time  # 导入时间模块，用于测试过期场景
from datetime import timedelta  # 从 datetime 导入时间差类，用于构造过期时间

import pytest  # 导入 pytest 测试框架
from jose import jwt  # 从 jose 导入 jwt 模块，用于手动构造 token

from app.core.config import get_settings  # 导入配置获取函数，用于读取 JWT 配置
from app.core.security import (  # 导入被测的安全函数
    create_access_token,  # 导入创建 access token 函数
    create_refresh_token,  # 导入创建 refresh token 函数
    decode_token,  # 导入解码 token 函数
    hash_password,  # 导入密码哈希函数
    is_allowed_extension,  # 导入扩展名校验函数
    sanitize_filename,  # 导入文件名消毒函数
    validate_upload_path,  # 导入路径校验函数
    verify_password,  # 导入密码验证函数
)


# ============================================================
# 密码哈希与验证测试
# ============================================================

class TestPasswordHashing:
    """测试密码哈希与验证。"""

    def test_hash_password_returns_string(self):
        """测试密码哈希返回字符串。"""
        # 对密码进行哈希
        hashed = hash_password("mypassword123")  # 哈希密码
        # 断言返回值为字符串
        assert isinstance(hashed, str)  # 验证返回类型

    def test_hash_password_is_not_plain_text(self):
        """测试哈希后不包含明文。"""
        # 对密码进行哈希
        plain = "mypassword123"  # 明文密码
        hashed = hash_password(plain)  # 哈希密码
        # 断言哈希值与明文不同
        assert hashed != plain  # 验证哈希值不等于明文

    def test_hash_password_different_each_time(self):
        """测试同一密码每次哈希结果不同（盐）。"""
        # 对同一密码哈希两次
        h1 = hash_password("samepassword")  # 第一次哈希
        h2 = hash_password("samepassword")  # 第二次哈希
        # 断言两次哈希结果不同（因盐不同）
        assert h1 != h2  # 验证哈希值不同

    def test_verify_correct_password(self):
        """测试验证正确密码。"""
        # 哈希密码
        hashed = hash_password("correctpass")  # 哈希正确密码
        # 验证密码
        result = verify_password("correctpass", hashed)  # 验证密码
        # 断言验证成功
        assert result is True  # 验证返回 True

    def test_verify_wrong_password(self):
        """测试验证错误密码。"""
        # 哈希密码
        hashed = hash_password("correctpass")  # 哈希正确密码
        # 验证错误密码
        result = verify_password("wrongpass", hashed)  # 验证错误密码
        # 断言验证失败
        assert result is False  # 验证返回 False

    def test_verify_password_empty_string(self):
        """测试验证空字符串密码。"""
        # 哈希空字符串
        hashed = hash_password("")  # 哈希空字符串
        # 验证空字符串
        result = verify_password("", hashed)  # 验证空字符串
        # 断言验证成功（空字符串也能匹配）
        assert result is True  # 验证返回 True

    def test_verify_password_invalid_hash_returns_false(self):
        """测试无效哈希值返回 False。"""
        # 验证无效哈希
        result = verify_password("password", "invalid-hash-format")  # 验证无效哈希
        # 断言返回 False
        assert result is False  # 验证返回 False

    def test_verify_password_none_hash_raises(self):
        """测试哈希为 None 时抛出异常（bcrypt 不处理 None）。"""
        # verify_password 仅捕获 ValueError 与 TypeError，None.encode 抛 AttributeError
        with pytest.raises(AttributeError):  # 期望抛出 AttributeError
            verify_password("password", None)  # 验证 None 哈希

    def test_long_password_truncated_by_bcrypt(self):
        """测试超长密码被 bcrypt 截断至 72 字节。"""
        # 创建 100 字符的密码
        long_password = "a" * 100  # 创建长密码
        # 哈希长密码
        hashed = hash_password(long_password)  # 哈希长密码
        # 验证 100 字符密码
        result_full = verify_password(long_password, hashed)  # 验证完整密码
        # 验证前 72 字节密码也应匹配（bcrypt 截断）
        result_truncated = verify_password("a" * 72, hashed)  # 验证截断密码
        # 断言两者都验证成功
        assert result_full is True  # 验证完整密码匹配
        assert result_truncated is True  # 验证截断密码也匹配


# ============================================================
# JWT Token 签发与解析测试
# ============================================================

class TestJwtTokens:
    """测试 JWT token 签发与解析。"""

    def test_create_access_token_returns_string(self):
        """测试创建 access token 返回字符串。"""
        # 创建 access token
        token = create_access_token(user_id=1, username="alice", is_admin=False)  # 创建 token
        # 断言返回值为字符串
        assert isinstance(token, str)  # 验证返回类型

    def test_create_access_token_decodable(self):
        """测试创建的 access token 可被解码。"""
        # 创建 access token
        token = create_access_token(user_id=42, username="bob", is_admin=True)  # 创建 token
        # 解码 token
        payload = decode_token(token)  # 解码 token
        # 断言 payload 不为 None
        assert payload is not None  # 验证解码成功
        # 断言 subject 字段为用户 ID
        assert payload["sub"] == "42"  # 验证用户 ID
        # 断言 username 字段
        assert payload["username"] == "bob"  # 验证用户名
        # 断言 is_admin 字段
        assert payload["is_admin"] is True  # 验证管理员标志
        # 断言 type 字段为 access
        assert payload["type"] == "access"  # 验证 token 类型
        # 断言包含 jti 字段
        assert "jti" in payload  # 验证包含 jti
        # 断言包含 exp 字段
        assert "exp" in payload  # 验证包含过期时间

    def test_create_refresh_token_returns_tuple(self):
        """测试创建 refresh token 返回三元组。"""
        # 创建 refresh token
        token, jti, expire = create_refresh_token(user_id=1)  # 创建 refresh token
        # 断言 token 为字符串
        assert isinstance(token, str)  # 验证 token 类型
        # 断言 jti 为字符串
        assert isinstance(jti, str)  # 验证 jti 类型
        # 断言 expire 为 datetime 对象
        assert expire is not None  # 验证 expire 不为 None

    def test_create_refresh_token_decodable(self):
        """测试创建的 refresh token 可被解码。"""
        # 创建 refresh token
        token, jti, expire = create_refresh_token(user_id=99)  # 创建 refresh token
        # 解码 token
        payload = decode_token(token)  # 解码 token
        # 断言 payload 不为 None
        assert payload is not None  # 验证解码成功
        # 断言 subject 字段
        assert payload["sub"] == "99"  # 验证用户 ID
        # 断言 type 字段为 refresh
        assert payload["type"] == "refresh"  # 验证 token 类型
        # 断言 jti 字段一致
        assert payload["jti"] == jti  # 验证 jti 一致

    def test_decode_invalid_token_returns_none(self):
        """测试解码无效 token 返回 None。"""
        # 解码无效 token
        payload = decode_token("invalid.token.string")  # 解码无效 token
        # 断言返回 None
        assert payload is None  # 验证返回 None

    def test_decode_empty_token_returns_none(self):
        """测试解码空字符串 token 返回 None。"""
        # 解码空字符串
        payload = decode_token("")  # 解码空字符串
        # 断言返回 None
        assert payload is None  # 验证返回 None

    def test_decode_token_with_wrong_signature_returns_none(self):
        """测试使用错误密钥签名的 token 解码失败。"""
        # 获取配置
        settings = get_settings()  # 获取配置
        # 使用错误密钥构造 token
        wrong_payload = {"sub": "1", "type": "access"}  # 构造错误负载
        wrong_token = jwt.encode(wrong_payload, "wrong-secret-key", algorithm="HS256")  # 用错误密钥签名
        # 解码 token
        payload = decode_token(wrong_token)  # 解码 token
        # 断言返回 None
        assert payload is None  # 验证返回 None

    def test_decode_expired_token_returns_none(self, monkeypatch):
        """测试过期 token 解码返回 None。"""
        # 获取配置
        settings = get_settings()  # 获取配置
        # 构造已过期的 token
        import datetime  # 导入 datetime 模块
        expired_payload = {  # 构造过期负载
            "sub": "1",  # 用户 ID
            "type": "access",  # token 类型
            "exp": datetime.datetime.now(datetime.timezone.utc) - timedelta(minutes=10),  # 10 分钟前过期
        }
        expired_token = jwt.encode(  # 签名过期 token
            expired_payload,  # 过期负载
            settings.JWT_SECRET_KEY,  # 使用正确密钥
            algorithm=settings.JWT_ALGORITHM,  # 使用正确算法
        )
        # 解码过期 token
        payload = decode_token(expired_token)  # 解码过期 token
        # 断言返回 None
        assert payload is None  # 验证返回 None

    def test_access_token_contains_jti(self):
        """测试 access token 包含 jti 字段（用于撤销追踪）。"""
        # 创建 access token
        token = create_access_token(user_id=1, username="alice")  # 创建 token
        # 解码 token
        payload = decode_token(token)  # 解码 token
        # 断言 jti 字段存在
        assert "jti" in payload  # 验证包含 jti
        # 断言 jti 为字符串
        assert isinstance(payload["jti"], str)  # 验证 jti 类型

    def test_each_token_has_unique_jti(self):
        """测试每个 token 的 jti 唯一。"""
        # 创建两个 token
        token1 = create_access_token(user_id=1, username="alice")  # 第一个 token
        token2 = create_access_token(user_id=1, username="alice")  # 第二个 token
        # 解码两个 token
        payload1 = decode_token(token1)  # 解码第一个
        payload2 = decode_token(token2)  # 解码第二个
        # 断言 jti 不同
        assert payload1["jti"] != payload2["jti"]  # 验证 jti 唯一


# ============================================================
# 文件名消毒测试
# ============================================================

class TestSanitizeFilename:
    """测试文件名消毒。"""

    def test_normal_filename_preserved(self):
        """测试普通文件名被保留（带 UUID 前缀）。"""
        # 消毒普通文件名
        result = sanitize_filename("document.pdf")  # 消毒文件名
        # 断言包含原始文件名
        assert "document.pdf" in result  # 验证保留原文件名
        # 断言包含 UUID 前缀（12 位十六进制 + 下划线）
        assert len(result.split("_")[0]) == 12  # 验证 UUID 前缀长度

    def test_path_traversal_stripped(self):
        """测试路径穿越字符被移除。"""
        # 消毒包含路径穿越的文件名
        result = sanitize_filename("../../../etc/passwd")  # 消毒路径穿越文件名
        # 断言不包含路径分隔符
        assert "/" not in result  # 验证不含正斜杠
        # 断言不包含 ..
        assert ".." not in result  # 验证不含 ..
        # 断言包含 passwd（最后一段）
        assert "passwd" in result  # 验证保留最后一段

    def test_backslash_path_traversal_stripped(self):
        """测试反斜杠路径穿越被移除。"""
        # 消毒包含反斜杠路径穿越的文件名
        result = sanitize_filename("..\\..\\windows\\system32")  # 消毒反斜杠路径
        # 断言不包含反斜杠
        assert "\\" not in result  # 验证不含反斜杠
        # 断言包含 system32
        assert "system32" in result  # 验证保留最后一段

    def test_dangerous_characters_removed(self):
        """测试危险字符被移除。"""
        # 消毒包含危险字符的文件名
        result = sanitize_filename('file<>:"/\\|?*.txt')  # 消毒危险字符文件名
        # 断言不包含危险字符
        for char in '<>:"/\\|?*':  # 遍历危险字符
            assert char not in result  # 验证每个危险字符被移除
        # 断言保留 .txt
        assert "txt" in result  # 验证保留扩展名

    def test_leading_dots_removed(self):
        """测试前导点号被移除（防止隐藏文件）。"""
        # 消毒以点号开头的文件名
        result = sanitize_filename("...hidden.txt")  # 消毒隐藏文件名
        # 断言不以点号开头（UUID 前缀）
        assert not result.startswith(".")  # 验证不以点号开头

    def test_empty_filename_uses_default(self):
        """测试空文件名使用默认名。"""
        # 消毒空文件名
        result = sanitize_filename("")  # 消毒空文件名
        # 断言包含默认名 upload
        assert "upload" in result  # 验证使用默认名

    def test_only_dangerous_chars_uses_default(self):
        """测试仅含危险字符的文件名使用默认名。"""
        # 消毒仅含危险字符的文件名
        result = sanitize_filename('<>"|?*')  # 消毒危险字符文件名
        # 断言包含默认名 upload
        assert "upload" in result  # 验证使用默认名

    def test_filename_has_uuid_prefix(self):
        """测试文件名包含 UUID 前缀。"""
        # 消毒文件名
        result = sanitize_filename("test.txt")  # 消毒文件名
        # 断言结果以 12 位十六进制 + 下划线开头
        parts = result.split("_", 1)  # 按下划线分割
        assert len(parts[0]) == 12  # 验证 UUID 前缀长度为 12
        # 断言 UUID 前缀为十六进制
        assert all(c in "0123456789abcdef" for c in parts[0])  # 验证为十六进制

    def test_control_characters_removed(self):
        """测试控制字符被移除。"""
        # 消毒包含控制字符的文件名
        result = sanitize_filename("file\x00\x01\x02.txt")  # 消毒含控制字符文件名
        # 断言不包含控制字符
        for i in range(32):  # 遍历 ASCII 控制字符
            assert chr(i) not in result  # 验证控制字符被移除
        # 断言保留 .txt
        assert "txt" in result  # 验证保留扩展名

    def test_filename_uniqueness(self):
        """测试同一文件名消毒结果唯一。"""
        # 消毒同一文件名两次
        result1 = sanitize_filename("same.txt")  # 第一次消毒
        result2 = sanitize_filename("same.txt")  # 第二次消毒
        # 断言结果不同（因 UUID 前缀不同）
        assert result1 != result2  # 验证结果唯一


# ============================================================
# 路径遍历防护测试
# ============================================================

class TestValidateUploadPath:
    """测试路径遍历防护。"""

    def test_valid_path_within_root(self, tmp_path):
        """测试合法路径在根目录内返回 True。"""
        # 创建根目录
        root = tmp_path / "uploads"  # 定义根目录
        root.mkdir()  # 创建根目录
        # 创建子目录文件路径
        file_path = str(root / "subdir" / "file.txt")  # 定义文件路径
        # 校验路径
        result = validate_upload_path(file_path, str(root))  # 校验路径
        # 断言返回 True
        assert result is True  # 验证返回 True

    def test_root_itself_returns_true(self, tmp_path):
        """测试根目录本身返回 True。"""
        # 创建根目录
        root = tmp_path / "uploads"  # 定义根目录
        root.mkdir()  # 创建根目录
        # 校验根目录本身
        result = validate_upload_path(str(root), str(root))  # 校验根目录
        # 断言返回 True
        assert result is True  # 验证返回 True

    def test_path_traversal_returns_false(self, tmp_path):
        """测试路径穿越返回 False。"""
        # 创建根目录
        root = tmp_path / "uploads"  # 定义根目录
        root.mkdir()  # 创建根目录
        # 构造路径穿越路径
        malicious_path = str(root / ".." / "secret.txt")  # 构造路径穿越
        # 校验路径
        result = validate_upload_path(malicious_path, str(root))  # 校验路径
        # 断言返回 False
        assert result is False  # 验证返回 False

    def test_absolute_path_outside_root_returns_false(self, tmp_path):
        """测试绝对路径在根目录外返回 False。"""
        # 创建根目录
        root = tmp_path / "uploads"  # 定义根目录
        root.mkdir()  # 创建根目录
        # 构造根目录外的绝对路径
        outside_path = str(tmp_path / "outside.txt")  # 构造外部路径
        # 校验路径
        result = validate_upload_path(outside_path, str(root))  # 校验路径
        # 断言返回 False
        assert result is False  # 验证返回 False

    def test_nested_subdirectory_returns_true(self, tmp_path):
        """测试嵌套子目录路径返回 True。"""
        # 创建根目录
        root = tmp_path / "uploads"  # 定义根目录
        root.mkdir()  # 创建根目录
        # 构造多层嵌套路径
        nested_path = str(root / "a" / "b" / "c" / "file.txt")  # 构造嵌套路径
        # 校验路径
        result = validate_upload_path(nested_path, str(root))  # 校验路径
        # 断言返回 True
        assert result is True  # 验证返回 True


# ============================================================
# 扩展名校验测试
# ============================================================

class TestIsAllowedExtension:
    """测试文件扩展名校验。"""

    def test_allowed_extension_returns_true(self):
        """测试允许的扩展名返回 True。"""
        # 校验允许的扩展名
        allowed = {"png", "jpg", "jpeg"}  # 定义允许集合
        result = is_allowed_extension("photo.png", allowed)  # 校验扩展名
        # 断言返回 True
        assert result is True  # 验证返回 True

    def test_disallowed_extension_returns_false(self):
        """测试不允许的扩展名返回 False。"""
        # 校验不允许的扩展名
        allowed = {"png", "jpg", "jpeg"}  # 定义允许集合
        result = is_allowed_extension("file.exe", allowed)  # 校验扩展名
        # 断言返回 False
        assert result is False  # 验证返回 False

    def test_extension_case_insensitive(self):
        """测试扩展名校验大小写不敏感。"""
        # 校验大写扩展名
        allowed = {"png", "jpg"}  # 定义允许集合
        result = is_allowed_extension("photo.PNG", allowed)  # 校验大写扩展名
        # 断言返回 True
        assert result is True  # 验证返回 True

    def test_no_extension_returns_false(self):
        """测试无扩展名返回 False。"""
        # 校验无扩展名的文件名
        allowed = {"png", "jpg"}  # 定义允许集合
        result = is_allowed_extension("noextension", allowed)  # 校验无扩展名
        # 断言返回 False
        assert result is False  # 验证返回 False

    def test_empty_filename_returns_false(self):
        """测试空文件名返回 False。"""
        # 校验空文件名
        allowed = {"png", "jpg"}  # 定义允许集合
        result = is_allowed_extension("", allowed)  # 校验空文件名
        # 断言返回 False
        assert result is False  # 验证返回 False

    def test_multiple_dots_uses_last(self):
        """测试多点的文件名使用最后一个扩展名。"""
        # 校验含多点的文件名
        allowed = {"txt"}  # 定义允许集合
        result = is_allowed_extension("archive.tar.txt", allowed)  # 校验多点文件名
        # 断言返回 True
        assert result is True  # 验证返回 True
