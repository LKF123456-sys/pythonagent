"""
多智能体系统单元测试（FastAPI + JWT + SQLite 架构）。
运行方式: python -m pytest tests/ -v

覆盖：
- config: JWT/SQLite 配置字段与校验
- logger: 日志单例
- auth: 密码哈希、JWT 签发/解析
- database: 异步 SQLite CRUD（用 asyncio.run 包装，无需 pytest-asyncio）
- memory: 语义感知切片 _semantic_chunk
- graph: Graph 缓存 + 路由决策
- web_app: FastAPI 路由 + JWT 鉴权（TestClient）
"""

import sys
import os
import asyncio
import tempfile
import pytest

# 将项目根目录和 libs 加入路径
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIBS_DIR = os.path.join(_PROJECT_DIR, "libs")
sys.path.insert(0, _PROJECT_DIR)
if os.path.isdir(_LIBS_DIR):
    sys.path.insert(0, _LIBS_DIR)


def _run(coro):
    """在同步测试中运行协程（避免依赖 pytest-asyncio）。"""
    return asyncio.run(coro)


# ============================================================
# 测试 config 模块
# ============================================================

class TestConfig:
    """测试配置管理模块。"""

    def test_config_has_required_fields(self):
        """Config 类应包含所有必要字段。"""
        from config import Config
        assert hasattr(Config, "OPENAI_API_KEY")
        assert hasattr(Config, "OPENAI_BASE_URL")
        assert hasattr(Config, "MODEL_NAME")
        assert hasattr(Config, "TAVILY_API_KEY")
        assert hasattr(Config, "JWT_SECRET_KEY")
        assert hasattr(Config, "JWT_ALGORITHM")
        assert hasattr(Config, "JWT_EXPIRE_MINUTES")
        assert hasattr(Config, "DATABASE_PATH")
        assert hasattr(Config, "CORS_ORIGINS")
        assert hasattr(Config, "LOG_LEVEL")
        assert hasattr(Config, "LOG_FILE")

    def test_jwt_secret_key_not_hardcoded(self):
        """JWT_SECRET_KEY 不应是硬编码的短固定值。"""
        from config import Config
        # 未设置环境变量时应生成随机值（token_hex(32) = 64字符）
        key = Config.JWT_SECRET_KEY
        assert len(key) >= 32, f"JWT_SECRET_KEY 太短: {len(key)}"

    def test_cors_origins_is_list(self):
        """CORS_ORIGINS 应为列表。"""
        from config import Config
        assert isinstance(Config.CORS_ORIGINS, list)
        assert len(Config.CORS_ORIGINS) >= 1

    def test_validate_missing_keys_raises(self, monkeypatch):
        """缺少必要 key 时应抛出 ValueError。"""
        from config import Config
        original_key = Config.OPENAI_API_KEY
        original_tavily = Config.TAVILY_API_KEY
        Config.OPENAI_API_KEY = ""
        Config.TAVILY_API_KEY = ""
        try:
            with pytest.raises(ValueError, match="缺少必要环境变量"):
                Config.validate()
        finally:
            Config.OPENAI_API_KEY = original_key
            Config.TAVILY_API_KEY = original_tavily


# ============================================================
# 测试 logger 模块
# ============================================================

class TestLogger:
    """测试日志模块。"""

    def test_setup_logger_returns_logger(self):
        """setup_logger 应返回有效的 Logger 实例。"""
        import logging
        from logger import setup_logger
        log = setup_logger("test_logger", "DEBUG", "logs/test_agent.log")
        assert isinstance(log, logging.Logger)
        assert log.name == "test_logger"

    def test_logger_no_duplicate_handlers(self):
        """重复调用 setup_logger 不应添加重复 handler。"""
        from logger import setup_logger
        log1 = setup_logger("test_no_dup", "INFO", "logs/test_agent.log")
        handler_count = len(log1.handlers)
        log2 = setup_logger("test_no_dup", "INFO", "logs/test_agent.log")
        assert len(log2.handlers) == handler_count
        assert log1 is log2


# ============================================================
# 测试 auth 模块（密码哈希 + JWT）
# ============================================================

class TestAuth:
    """测试 JWT 认证模块。"""

    def test_hash_and_verify_password(self):
        """哈希后的密码应能被正确验证。"""
        from auth import hash_password, verify_password
        hashed = hash_password("secret123")
        assert hashed != "secret123", "密码不应以明文存储"
        assert verify_password("secret123", hashed) is True
        assert verify_password("wrongpass", hashed) is False

    def test_create_and_decode_token(self):
        """签发的 token 应能被解析回原始信息。"""
        from auth import create_access_token, decode_access_token
        token = create_access_token(42, "alice")
        assert isinstance(token, str) and len(token) > 0
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["user_id"] == 42
        assert payload["username"] == "alice"

    def test_decode_invalid_token_returns_none(self):
        """无效 token 应返回 None。"""
        from auth import decode_access_token
        assert decode_access_token("not.a.valid.token") is None
        assert decode_access_token("") is None


# ============================================================
# 测试 database 模块（异步 SQLite CRUD）
# ============================================================

class TestDatabase:
    """测试异步 SQLite 数据库层。"""

    def setup_method(self):
        """每个测试前将 DATABASE_PATH 指向临时库并初始化表。"""
        from config import Config
        from database import init_db
        self._orig_db = Config.DATABASE_PATH
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._tmp_db = tmp.name
        Config.DATABASE_PATH = self._tmp_db
        _run(init_db())

    def teardown_method(self):
        """恢复原始库路径并清理临时文件。"""
        from config import Config
        Config.DATABASE_PATH = self._orig_db
        try:
            os.unlink(self._tmp_db)
        except OSError:
            pass

    def test_create_and_get_user(self):
        """创建用户后应能按用户名和 ID 查询。"""
        from database import create_user, get_user_by_username, get_user_by_id
        uid = _run(create_user("bob", "hashed_pw"))
        assert isinstance(uid, int)
        by_name = _run(get_user_by_username("bob"))
        assert by_name is not None
        assert by_name["username"] == "bob"
        assert by_name["password_hash"] == "hashed_pw"
        by_id = _run(get_user_by_id(uid))
        assert by_id is not None
        assert by_id["id"] == uid

    def test_duplicate_username_returns_none(self):
        """重复用户名应返回 None。"""
        from database import create_user
        _run(create_user("dup", "pw1"))
        second = _run(create_user("dup", "pw2"))
        assert second is None

    def test_conversation_crud(self):
        """会话创建、列表、删除应正常工作。"""
        from database import (
            create_user, create_conversation, list_conversations,
            get_conversation, delete_conversation,
        )
        uid = _run(create_user("conv_user", "pw"))
        _run(create_conversation("sess-001", uid, "测试对话"))
        convs = _run(list_conversations(uid))
        assert len(convs) == 1
        assert convs[0]["session_id"] == "sess-001"
        assert convs[0]["title"] == "测试对话"

        one = _run(get_conversation("sess-001", uid))
        assert one is not None and one["session_id"] == "sess-001"

        _run(delete_conversation("sess-001"))
        convs_after = _run(list_conversations(uid))
        assert all(c["session_id"] != "sess-001" for c in convs_after)

    def test_message_crud(self):
        """消息添加和读取应按时间正序返回。"""
        from database import create_user, create_conversation, add_message, get_messages
        uid = _run(create_user("msg_user", "pw"))
        _run(create_conversation("sess-msg", uid, "消息测试"))
        _run(add_message("sess-msg", "user", "你好"))
        _run(add_message("sess-msg", "assistant", "你好！有什么可以帮你？"))
        msgs = _run(get_messages("sess-msg"))
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["role"] == "assistant"

    def test_delete_conversation_cascades_messages(self):
        """删除会话应同时删除其消息。"""
        from database import create_user, create_conversation, add_message, get_messages, delete_conversation
        uid = _run(create_user("casc_user", "pw"))
        _run(create_conversation("sess-casc", uid, "级联测试"))
        _run(add_message("sess-casc", "user", "hi"))
        _run(delete_conversation("sess-casc"))
        msgs = _run(get_messages("sess-casc"))
        assert msgs == []


# ============================================================
# 测试 memory 模块（语义感知切片）
# ============================================================

class TestMemorySemanticChunk:
    """测试 RAG 语义感知切片。"""

    def test_chunk_by_markdown_headers(self):
        """应按 Markdown 标题分段并携带 section_title。"""
        from memory import _semantic_chunk
        content = (
            "# 第一章\n"
            "这是第一章的内容。\n\n"
            "## 第二节\n"
            "这是第二节的内容。"
        )
        chunks = _semantic_chunk(content, chunk_size=500, chunk_overlap=50)
        assert len(chunks) >= 2
        titles = {c["section_title"] for c in chunks}
        assert "第一章" in titles
        assert "第二节" in titles

    def test_chunk_has_link_fields(self):
        """每个切片应携带 prev/next 链接字段。"""
        from memory import _semantic_chunk
        content = "# A\n段落一\n\n# B\n段落二\n\n# C\n段落三"
        chunks = _semantic_chunk(content)
        assert chunks[0]["prev_chunk_id"] is None
        assert chunks[-1]["next_chunk_id"] is None
        if len(chunks) >= 2:
            assert chunks[0]["next_chunk_id"] == 1

    def test_long_paragraph_sliding_window(self):
        """超长段落应退化为滑动窗口切分。"""
        from memory import _semantic_chunk
        long_text = "字" * 1200  # 远超 chunk_size=500
        chunks = _semantic_chunk(long_text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) >= 2
        assert all(len(c["text"]) <= 500 for c in chunks)

    def test_empty_content_returns_empty(self):
        """空内容应返回空列表。"""
        from memory import _semantic_chunk
        assert _semantic_chunk("") == []
        assert _semantic_chunk("   \n\n  ") == []


# ============================================================
# 测试 graph 模块（Graph 缓存 + 路由）
# ============================================================

class TestGraph:
    """测试 LangGraph 工作流。"""

    def test_build_graph_returns_compiled(self):
        """build_graph 应返回编译后的 Graph。"""
        from graph import build_graph
        g = build_graph()
        assert g is not None

    def test_graph_is_cached(self):
        """多次调用 build_graph 应返回同一实例。"""
        import graph
        graph._compiled_graph = None  # 重置缓存
        g1 = graph.build_graph()
        g2 = graph.build_graph()
        assert g1 is g2, "Graph 应被缓存，不应重复编译"

    def test_route_after_supervisor_search(self):
        """SEARCH 动作应路由到 search。"""
        from graph import route_after_supervisor
        assert route_after_supervisor({"action": "SEARCH"}) == "search"

    def test_route_after_supervisor_rag(self):
        """RAG 动作应路由到 rag（修复验证）。"""
        from graph import route_after_supervisor
        assert route_after_supervisor({"action": "RAG"}) == "rag"

    def test_route_after_supervisor_direct(self):
        """DIRECT 动作应路由到 answer。"""
        from graph import route_after_supervisor
        assert route_after_supervisor({"action": "DIRECT"}) == "answer"

    def test_route_after_supervisor_unknown(self):
        """未知动作应默认路由到 answer。"""
        from graph import route_after_supervisor
        assert route_after_supervisor({"action": "UNKNOWN"}) == "answer"

    def test_extract_history_context_empty(self):
        """空消息列表应返回空字符串。"""
        from graph import _extract_history_context
        assert _extract_history_context([], "test") == ""

    def test_extract_history_context_with_history(self):
        """有历史消息时应返回上下文。"""
        from langchain_core.messages import HumanMessage, AIMessage
        from graph import _extract_history_context
        messages = [
            HumanMessage(content="你好"),
            AIMessage(content="你好！有什么可以帮你的？"),
            HumanMessage(content="新问题"),
        ]
        result = _extract_history_context(messages, "新问题")
        assert "你好" in result
        assert "助手" in result


# ============================================================
# 测试 web_app 模块（FastAPI 路由 + JWT 鉴权）
# ============================================================

class TestWebApp:
    """测试 FastAPI Web 应用。"""

    def setup_method(self):
        """将 DATABASE_PATH 指向临时库，确保 validate 可通过，创建 TestClient。"""
        from config import Config
        from fastapi.testclient import TestClient
        import web_app

        self._orig_db = Config.DATABASE_PATH
        self._orig_openai = Config.OPENAI_API_KEY
        self._orig_tavily = Config.TAVILY_API_KEY

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._tmp_db = tmp.name
        Config.DATABASE_PATH = self._tmp_db
        # 保证 startup 时 Config.validate() 通过（测试环境可能无真实密钥）
        if not Config.OPENAI_API_KEY:
            Config.OPENAI_API_KEY = "test-key"
        if not Config.TAVILY_API_KEY:
            Config.TAVILY_API_KEY = "test-key"

        self.app = web_app.app
        self._TestClient = TestClient
        self.client = TestClient(self.app)

    def teardown_method(self):
        """恢复配置并清理临时库。"""
        from config import Config
        Config.DATABASE_PATH = self._orig_db
        Config.OPENAI_API_KEY = self._orig_openai
        Config.TAVILY_API_KEY = self._orig_tavily
        try:
            os.unlink(self._tmp_db)
        except OSError:
            pass

    # -------- 无需认证的端点 --------

    def test_health_returns_200(self):
        """健康检查端点应返回 200。"""
        resp = self.client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_protected_endpoint_without_token(self):
        """未携带 token 访问受保护端点应被拒绝（401/403）。"""
        resp = self.client.get("/api/conversations")
        assert resp.status_code in (401, 403)

    def test_protected_endpoint_invalid_token(self):
        """携带无效 token 应返回 401。"""
        resp = self.client.get(
            "/api/conversations",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    def test_login_wrong_credentials(self):
        """错误的登录凭据应返回 401。"""
        with self._TestClient(self.app) as client:  # 触发 startup → init_db
            resp = client.post(
                "/api/auth/login",
                json={"username": "nouser", "password": "whatever"},
            )
            assert resp.status_code == 401

    # -------- 完整认证流程（需 DB） --------

    def test_register_login_and_access_flow(self):
        """注册 → 获取 token → 访问受保护端点。"""
        with self._TestClient(self.app) as client:  # 触发 startup → init_db
            reg = client.post(
                "/api/auth/register",
                json={"username": "flowuser", "password": "secret123"},
            )
            assert reg.status_code == 200, reg.text
            token = reg.json()["access_token"]
            assert token

            headers = {"Authorization": f"Bearer {token}"}
            me = client.get("/api/auth/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["username"] == "flowuser"

            convs = client.get("/api/conversations", headers=headers)
            assert convs.status_code == 200
            assert "conversations" in convs.json()

    def test_register_short_password_rejected(self):
        """密码过短应返回 400。"""
        with self._TestClient(self.app) as client:
            resp = client.post(
                "/api/auth/register",
                json={"username": "shortpw", "password": "123"},
            )
            assert resp.status_code == 400

    def test_chat_empty_question_returns_400(self):
        """已认证但空问题应返回 400。"""
        with self._TestClient(self.app) as client:
            reg = client.post(
                "/api/auth/register",
                json={"username": "chatuser", "password": "secret123"},
            )
            assert reg.status_code == 200, reg.text
            token = reg.json()["access_token"]
            resp = client.post(
                "/api/chat",
                json={"question": "", "session_id": "test"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 400
