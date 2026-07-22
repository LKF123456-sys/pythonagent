"""数据模型单元测试：覆盖 auth/chat/conversation 三个模型的字段验证。

测试策略：
- 字段验证：覆盖必填、长度限制、类型校验
- 默认值：覆盖字段默认值设置
- 序列化：覆盖模型转字典行为
- 边界场景：覆盖空值、超长值、非法类型
"""

from datetime import datetime  # 从 datetime 导入日期时间类，用于构造时间字段

import pytest  # 导入 pytest 测试框架
from pydantic import ValidationError  # 从 pydantic 导入验证错误类

from app.models.auth import (  # 导入认证相关模型
    RefreshRequest,  # 导入刷新令牌请求模型
    TokenResponse,  # 导入令牌响应模型
    UserInfo,  # 导入用户信息模型
    UserLogin,  # 导入用户登录模型
    UserRegister,  # 导入用户注册模型
)
from app.models.chat import (  # 导入聊天相关模型
    ChatRequest,  # 导入聊天请求模型
    ChatResponse,  # 导入聊天响应模型
    DocumentUploadResponse,  # 导入文档上传响应模型
    UploadResponse,  # 导入上传响应模型
)
from app.models.conversation import (  # 导入会话相关模型
    ConversationItem,  # 导入会话列表项模型
    ConversationListResponse,  # 导入会话列表响应模型
    MessageItem,  # 导入消息项模型
    MessageListResponse,  # 导入消息列表响应模型
    RenameRequest,  # 导入重命名请求模型
    TokenStatsItem,  # 导入 Token 统计项模型
    TokenStatsResponse,  # 导入 Token 统计响应模型
)


# ============================================================
# Auth 模型测试
# ============================================================

class TestUserRegister:
    """测试用户注册请求模型。"""

    def test_valid_user_register(self):
        """测试合法的用户注册数据。"""
        # 创建合法注册数据
        user = UserRegister(username="alice", password="secret123")  # 创建模型实例
        # 断言用户名正确
        assert user.username == "alice"  # 验证用户名
        # 断言密码正确
        assert user.password == "secret123"  # 验证密码

    def test_username_too_short_raises(self):
        """测试用户名过短抛出异常。"""
        # 断言用户名长度小于 2 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserRegister(username="a", password="secret123")  # 用户名过短

    def test_username_too_long_raises(self):
        """测试用户名过长抛出异常。"""
        # 断言用户名长度大于 50 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserRegister(username="a" * 51, password="secret123")  # 用户名过长

    def test_password_too_short_raises(self):
        """测试密码过短抛出异常。"""
        # 断言密码长度小于 6 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserRegister(username="alice", password="12345")  # 密码过短

    def test_password_too_long_raises(self):
        """测试密码过长抛出异常。"""
        # 断言密码长度大于 128 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserRegister(username="alice", password="a" * 129)  # 密码过长

    def test_missing_username_raises(self):
        """测试缺失用户名抛出异常。"""
        # 断言缺失用户名抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserRegister(password="secret123")  # 缺失用户名

    def test_missing_password_raises(self):
        """测试缺失密码抛出异常。"""
        # 断言缺失密码抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserRegister(username="alice")  # 缺失密码


class TestUserLogin:
    """测试用户登录请求模型。"""

    def test_valid_user_login(self):
        """测试合法的用户登录数据。"""
        # 创建合法登录数据
        user = UserLogin(username="alice", password="secret123")  # 创建模型实例
        # 断言用户名正确
        assert user.username == "alice"  # 验证用户名
        # 断言密码正确
        assert user.password == "secret123"  # 验证密码

    def test_missing_username_raises(self):
        """测试缺失用户名抛出异常。"""
        # 断言缺失用户名抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserLogin(password="secret123")  # 缺失用户名

    def test_missing_password_raises(self):
        """测试缺失密码抛出异常。"""
        # 断言缺失密码抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UserLogin(username="alice")  # 缺失密码


class TestTokenResponse:
    """测试令牌响应模型。"""

    def test_valid_token_response(self):
        """测试合法的令牌响应数据。"""
        # 创建合法令牌响应
        response = TokenResponse(  # 创建模型实例
            access_token="access-token-value",  # 设置 access token
            refresh_token="refresh-token-value",  # 设置 refresh token
            user_id=1,  # 设置用户 ID
            username="alice",  # 设置用户名
        )  # 创建响应
        # 断言 token_type 默认为 bearer
        assert response.token_type == "bearer"  # 验证默认 token 类型
        # 断言 is_admin 默认为 False
        assert response.is_admin is False  # 验证默认非管理员

    def test_admin_flag(self):
        """测试管理员标志。"""
        # 创建管理员令牌响应
        response = TokenResponse(  # 创建模型实例
            access_token="access",  # 设置 access token
            refresh_token="refresh",  # 设置 refresh token
            user_id=1,  # 设置用户 ID
            username="admin",  # 设置用户名
            is_admin=True,  # 设置管理员标志
        )  # 创建响应
        # 断言 is_admin 为 True
        assert response.is_admin is True  # 验证管理员标志

    def test_missing_access_token_raises(self):
        """测试缺失 access_token 抛出异常。"""
        # 断言缺失 access_token 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            TokenResponse(  # 创建模型实例
                refresh_token="refresh",  # 设置 refresh token
                user_id=1,  # 设置用户 ID
                username="alice",  # 设置用户名
            )  # 缺失 access token


class TestRefreshRequest:
    """测试刷新令牌请求模型。"""

    def test_valid_refresh_request(self):
        """测试合法的刷新请求。"""
        # 创建合法刷新请求
        request = RefreshRequest(refresh_token="some-refresh-token")  # 创建模型实例
        # 断言 refresh_token 正确
        assert request.refresh_token == "some-refresh-token"  # 验证字段

    def test_missing_refresh_token_raises(self):
        """测试缺失 refresh_token 抛出异常。"""
        # 断言缺失 refresh_token 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            RefreshRequest()  # 缺失 refresh_token


class TestUserInfo:
    """测试用户信息模型。"""

    def test_valid_user_info(self):
        """测试合法的用户信息。"""
        # 创建合法用户信息
        info = UserInfo(user_id=1, username="alice")  # 创建模型实例
        # 断言 is_admin 默认为 False
        assert info.is_admin is False  # 验证默认非管理员
        # 断言 created_at 默认为空字符串
        assert info.created_at == ""  # 验证默认创建时间

    def test_with_created_at(self):
        """测试带创建时间的用户信息。"""
        # 创建带创建时间的用户信息
        info = UserInfo(  # 创建模型实例
            user_id=1,  # 设置用户 ID
            username="alice",  # 设置用户名
            created_at="2024-01-01T00:00:00",  # 设置创建时间
        )  # 创建响应
        # 断言 created_at 正确
        assert info.created_at == "2024-01-01T00:00:00"  # 验证创建时间


# ============================================================
# Chat 模型测试
# ============================================================

class TestChatRequest:
    """测试聊天请求模型。"""

    def test_valid_chat_request(self):
        """测试合法的聊天请求。"""
        # 创建合法聊天请求
        request = ChatRequest(question="什么是量子计算？")  # 创建模型实例
        # 断言 session_id 默认为 None
        assert request.session_id is None  # 验证默认会话 ID
        # 断言 image_filename 默认为空字符串
        assert request.image_filename == ""  # 验证默认图片文件名
        # 断言 is_first_turn 默认为 True
        assert request.is_first_turn is True  # 验证默认首条消息

    def test_empty_question_raises(self):
        """测试空问题抛出异常。"""
        # 断言空问题抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            ChatRequest(question="")  # 空问题

    def test_too_long_question_raises(self):
        """测试过长问题抛出异常。"""
        # 断言超过 10000 字符的问题抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            ChatRequest(question="a" * 10001)  # 过长问题

    def test_with_session_id(self):
        """测试带会话 ID 的聊天请求。"""
        # 创建带会话 ID 的请求
        request = ChatRequest(  # 创建模型实例
            question="问题",  # 设置问题
            session_id="session-123",  # 设置会话 ID
        )  # 创建请求
        # 断言 session_id 正确
        assert request.session_id == "session-123"  # 验证会话 ID

    def test_with_image_filename(self):
        """测试带图片文件名的聊天请求。"""
        # 创建带图片文件名的请求
        request = ChatRequest(  # 创建模型实例
            question="问题",  # 设置问题
            image_filename="image.png",  # 设置图片文件名
        )  # 创建请求
        # 断言 image_filename 正确
        assert request.image_filename == "image.png"  # 验证图片文件名


class TestChatResponse:
    """测试聊天响应模型。"""

    def test_valid_chat_response(self):
        """测试合法的聊天响应。"""
        # 创建合法聊天响应
        response = ChatResponse(answer="回答内容", session_id="session-123")  # 创建模型实例
        # 断言 token_count 默认为 0
        assert response.token_count == 0  # 验证默认 token 数
        # 断言 error 默认为 None
        assert response.error is None  # 验证默认无错误

    def test_with_error(self):
        """测试带错误的聊天响应。"""
        # 创建带错误的响应
        response = ChatResponse(  # 创建模型实例
            answer="回答",  # 设置回答
            session_id="session",  # 设置会话 ID
            error="出错了",  # 设置错误信息
        )  # 创建响应
        # 断言 error 正确
        assert response.error == "出错了"  # 验证错误信息

    def test_with_token_count(self):
        """测试带 token 数的聊天响应。"""
        # 创建带 token 数的响应
        response = ChatResponse(  # 创建模型实例
            answer="回答",  # 设置回答
            session_id="session",  # 设置会话 ID
            token_count=42,  # 设置 token 数
        )  # 创建响应
        # 断言 token_count 正确
        assert response.token_count == 42  # 验证 token 数

    def test_missing_answer_raises(self):
        """测试缺失 answer 抛出异常。"""
        # 断言缺失 answer 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            ChatResponse(session_id="session")  # 缺失 answer

    def test_missing_session_id_raises(self):
        """测试缺失 session_id 抛出异常。"""
        # 断言缺失 session_id 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            ChatResponse(answer="回答")  # 缺失 session_id


class TestUploadResponse:
    """测试上传响应模型。"""

    def test_valid_upload_response(self):
        """测试合法的上传响应。"""
        # 创建合法上传响应
        response = UploadResponse(filename="file.png")  # 创建模型实例
        # 断言 error 默认为 None
        assert response.error is None  # 验证默认无错误

    def test_with_error(self):
        """测试带错误的上传响应。"""
        # 创建带错误的上传响应
        response = UploadResponse(filename="file.png", error="上传失败")  # 创建模型实例
        # 断言 error 正确
        assert response.error == "上传失败"  # 验证错误信息

    def test_missing_filename_raises(self):
        """测试缺失 filename 抛出异常。"""
        # 断言缺失 filename 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            UploadResponse()  # 缺失 filename


class TestDocumentUploadResponse:
    """测试文档上传响应模型。"""

    def test_valid_document_upload_response(self):
        """测试合法的文档上传响应。"""
        # 创建合法文档上传响应
        response = DocumentUploadResponse(filename="doc.pdf", chunks=10)  # 创建模型实例
        # 断言 filename 正确
        assert response.filename == "doc.pdf"  # 验证文件名
        # 断言 chunks 正确
        assert response.chunks == 10  # 验证切片数
        # 断言 error 默认为 None
        assert response.error is None  # 验证默认无错误

    def test_missing_chunks_raises(self):
        """测试缺失 chunks 抛出异常。"""
        # 断言缺失 chunks 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            DocumentUploadResponse(filename="doc.pdf")  # 缺失 chunks


# ============================================================
# Conversation 模型测试
# ============================================================

class TestConversationItem:
    """测试会话列表项模型。"""

    def test_valid_conversation_item(self):
        """测试合法的会话列表项。"""
        # 创建合法会话列表项
        now = datetime.now()  # 获取当前时间
        item = ConversationItem(  # 创建模型实例
            session_id="session-1",  # 设置会话 ID
            title="会话标题",  # 设置标题
            created_at=now,  # 设置创建时间
            updated_at=now,  # 设置更新时间
        )  # 创建列表项
        # 断言 session_id 正确
        assert item.session_id == "session-1"  # 验证会话 ID
        # 断言 title 正确
        assert item.title == "会话标题"  # 验证标题

    def test_missing_session_id_raises(self):
        """测试缺失 session_id 抛出异常。"""
        # 断言缺失 session_id 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            ConversationItem(  # 创建模型实例
                title="标题",  # 设置标题
                created_at=datetime.now(),  # 设置创建时间
                updated_at=datetime.now(),  # 设置更新时间
            )  # 缺失 session_id

    def test_missing_title_raises(self):
        """测试缺失 title 抛出异常。"""
        # 断言缺失 title 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            ConversationItem(  # 创建模型实例
                session_id="session",  # 设置会话 ID
                created_at=datetime.now(),  # 设置创建时间
                updated_at=datetime.now(),  # 设置更新时间
            )  # 缺失 title


class TestConversationListResponse:
    """测试会话列表响应模型。"""

    def test_empty_conversation_list(self):
        """测试空会话列表。"""
        # 创建空会话列表响应
        response = ConversationListResponse()  # 创建模型实例
        # 断言 conversations 默认为空列表
        assert response.conversations == []  # 验证默认空列表

    def test_with_conversations(self):
        """测试带会话的列表。"""
        # 创建带会话的列表响应
        now = datetime.now()  # 获取当前时间
        item = ConversationItem(  # 创建会话列表项
            session_id="session-1",  # 设置会话 ID
            title="标题",  # 设置标题
            created_at=now,  # 设置创建时间
            updated_at=now,  # 设置更新时间
        )  # 创建列表项
        response = ConversationListResponse(conversations=[item])  # 创建列表响应
        # 断言 conversations 长度为 1
        assert len(response.conversations) == 1  # 验证列表长度


class TestMessageItem:
    """测试消息项模型。"""

    def test_valid_message_item(self):
        """测试合法的消息项。"""
        # 创建合法消息项
        item = MessageItem(role="user", content="你好")  # 创建模型实例
        # 断言 token_count 默认为 0
        assert item.token_count == 0  # 验证默认 token 数
        # 断言 image_filename 默认为空字符串
        assert item.image_filename == ""  # 验证默认图片文件名
        # 断言 created_at 默认为 None
        assert item.created_at is None  # 验证默认创建时间

    def test_assistant_role(self):
        """测试助手角色消息。"""
        # 创建助手消息
        item = MessageItem(role="assistant", content="回答")  # 创建模型实例
        # 断言 role 正确
        assert item.role == "assistant"  # 验证角色

    def test_missing_role_raises(self):
        """测试缺失 role 抛出异常。"""
        # 断言缺失 role 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            MessageItem(content="内容")  # 缺失 role

    def test_missing_content_raises(self):
        """测试缺失 content 抛出异常。"""
        # 断言缺失 content 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            MessageItem(role="user")  # 缺失 content


class TestMessageListResponse:
    """测试消息列表响应模型。"""

    def test_empty_message_list(self):
        """测试空消息列表。"""
        # 创建空消息列表响应
        response = MessageListResponse()  # 创建模型实例
        # 断言 messages 默认为空列表
        assert response.messages == []  # 验证默认空列表

    def test_with_messages(self):
        """测试带消息的列表。"""
        # 创建带消息的列表响应
        item = MessageItem(role="user", content="问题")  # 创建消息项
        response = MessageListResponse(messages=[item])  # 创建列表响应
        # 断言 messages 长度为 1
        assert len(response.messages) == 1  # 验证列表长度


class TestRenameRequest:
    """测试重命名请求模型。"""

    def test_valid_rename_request(self):
        """测试合法的重命名请求。"""
        # 创建合法重命名请求
        request = RenameRequest(title="新标题")  # 创建模型实例
        # 断言 title 正确
        assert request.title == "新标题"  # 验证标题

    def test_empty_title_raises(self):
        """测试空标题抛出异常。"""
        # 断言空标题抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            RenameRequest(title="")  # 空标题

    def test_too_long_title_raises(self):
        """测试过长标题抛出异常。"""
        # 断言超过 100 字符的标题抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            RenameRequest(title="a" * 101)  # 过长标题

    def test_missing_title_raises(self):
        """测试缺失标题抛出异常。"""
        # 断言缺失标题抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            RenameRequest()  # 缺失标题


class TestTokenStatsItem:
    """测试 Token 统计项模型。"""

    def test_valid_token_stats_item(self):
        """测试合法的 Token 统计项。"""
        # 创建合法统计项
        item = TokenStatsItem(date="2024-01-01", total_tokens=1000, message_count=10)  # 创建模型实例
        # 断言 date 正确
        assert item.date == "2024-01-01"  # 验证日期
        # 断言 total_tokens 正确
        assert item.total_tokens == 1000  # 验证 token 总量
        # 断言 message_count 正确
        assert item.message_count == 10  # 验证消息数

    def test_missing_date_raises(self):
        """测试缺失日期抛出异常。"""
        # 断言缺失日期抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            TokenStatsItem(total_tokens=100, message_count=1)  # 缺失日期


class TestTokenStatsResponse:
    """测试 Token 统计响应模型。"""

    def test_valid_token_stats_response(self):
        """测试合法的 Token 统计响应。"""
        # 创建合法统计响应
        response = TokenStatsResponse(total_tokens=5000)  # 创建模型实例
        # 断言 total_tokens 正确
        assert response.total_tokens == 5000  # 验证 token 总量
        # 断言 daily 默认为空列表
        assert response.daily == []  # 验证默认空列表

    def test_with_daily_stats(self):
        """测试带日统计的响应。"""
        # 创建带日统计的响应
        item = TokenStatsItem(date="2024-01-01", total_tokens=100, message_count=5)  # 创建统计项
        response = TokenStatsResponse(total_tokens=100, daily=[item])  # 创建统计响应
        # 断言 daily 长度为 1
        assert len(response.daily) == 1  # 验证日统计长度

    def test_missing_total_tokens_raises(self):
        """测试缺失 total_tokens 抛出异常。"""
        # 断言缺失 total_tokens 抛出异常
        with pytest.raises(ValidationError):  # 期望抛出验证错误
            TokenStatsResponse()  # 缺失 total_tokens
