"""测试基建：环境隔离 + Fake 依赖（LLM/向量库/搜索）+ 应用与客户端 fixtures。

关键设计：
- 环境变量必须在导入任何 app 模块之前设置（setup_logger 会在模块导入期调用 get_settings）
- FakeChatModel 按 System Prompt 内容区分 supervisor/search/title/summary/answer 场景
- HTTP 测试使用 httpx AsyncClient + 手动触发 lifespan（同一事件循环，连接池一致）
- WebSocket 测试使用 starlette TestClient（其上下文管理器自行触发 lifespan）
- 集成测试需真实 PostgreSQL 实例（Docker: docker-compose.test.yml）
"""

import os
import sys
import tempfile

# ============================================================
# 环境隔离：必须在导入任何 app 模块之前设置
# ============================================================
_TEST_ROOT = tempfile.mkdtemp(prefix="mas_test_")

os.environ["JWT_SECRET_KEY"] = "a" * 64  # 强密钥（仅测试）
# 测试数据库：默认指向 docker-compose.test.yml 的 test_db 服务（端口 5433）
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://agent:agent-local@localhost:5433/agent_test",
)
os.environ["UPLOAD_FOLDER"] = os.path.join(_TEST_ROOT, "uploads")
os.environ["LOG_FILE"] = os.path.join(_TEST_ROOT, "logs", "test.log")
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["OPENAI_API_KEY"] = "fake-key-for-tests"
os.environ["TAVILY_API_KEY"] = "fake-tavily-key"
os.environ["OLLAMA_BASE_URL"] = "http://localhost:59999"  # 不可达端口，避免触碰真实服务

os.makedirs(os.path.join(_TEST_ROOT, "uploads"), exist_ok=True)
os.makedirs(os.path.join(_TEST_ROOT, "logs"), exist_ok=True)

# 项目根 + libs 加入路径（与 pytest.ini 的 pythonpath 双保险）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIBS_DIR = os.path.join(_PROJECT_DIR, "libs")
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
if os.path.isdir(_LIBS_DIR) and _LIBS_DIR not in sys.path:
    sys.path.insert(0, _LIBS_DIR)

import asyncio
import uuid
from typing import Any, List

import pytest
import pytest_asyncio
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# 默认回答：包含 thinking/answer 标签，供 TagStreamParser 解析
DEFAULT_ANSWER = "<thinking>这是假的思考过程</thinking><answer>这是假的最终回答</answer>"


# ============================================================
# Fake LLM
# ============================================================

class FakeLLMConfig:
    """可变的假 LLM 配置：测试可动态调整路由决策、回答内容与流式速度。"""

    def __init__(self) -> None:
        self.route: str = "DIRECT"
        self.answer: str = DEFAULT_ANSWER
        self.stream_delay: float = 0.0  # 每个 chunk 间的延迟（秒），用于中断测试


class FakeChatModel(BaseChatModel):
    """假 LLM：按 System Prompt 内容返回预设响应，支持 ainvoke / astream / bind_tools。"""

    route: str = "DIRECT"
    answer: str = DEFAULT_ANSWER
    stream_delay: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def _resolve_response(self, messages: List[Any]) -> str:
        """根据消息中的 System Prompt 判断调用场景并返回对应文本。"""
        for m in messages:
            content = getattr(m, "content", "") or ""
            if "调度主管" in content:
                return self.route
            if "搜索专家" in content:
                return "假的搜索关键词"
            if "对话标题生成器" in content:
                return "假的对话标题"
            if "对话摘要专家" in content:
                return "这是压缩后的对话摘要"
        return self.answer

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        text = self._resolve_response(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop=stop, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        text = self._resolve_response(messages)
        for ch in text:
            if self.stream_delay:
                await asyncio.sleep(self.stream_delay)
            yield ChatGenerationChunk(message=AIMessageChunk(content=ch))

    def bind_tools(self, tools, **kwargs):
        """不实际绑定工具，直接返回自身（回答节点随后可正常 astream）。"""
        return self


def _make_llm_factory(config: FakeLLMConfig):
    """构造 create_llm 的替身：每次调用返回读取当前配置的 FakeChatModel。"""

    def factory(temperature: float = 0.0, streaming: bool = False) -> FakeChatModel:
        return FakeChatModel(
            route=config.route, answer=config.answer, stream_delay=config.stream_delay
        )

    return factory


# ============================================================
# Fake 向量库（内存实现，接口与 VectorStore 对齐）
# ============================================================

class FakeVectorStore:
    """内存向量库：替代 pgvector，供测试断言存储行为。"""

    def __init__(self) -> None:
        self.memories: List[dict] = []
        self.documents: dict = {}

    async def warmup(self) -> None:
        pass

    async def initialize(self) -> bool:
        return True

    @property
    def available(self) -> bool:
        return True

    async def store_conversation_turn(self, user_id, question, answer, metadata=None) -> None:
        self.memories.append({"user_id": user_id, "question": question, "answer": answer})

    async def retrieve_long_term_memories(self, query, user_id=None, top_k=5) -> List[dict]:
        return [
            {
                "content": f"问题: {m['question']}\n回答: {m['answer']}",
                "metadata": {"timestamp": "2024-01-01T00:00:00"},
                "distance": 0.1,
            }
            for m in self.memories[:top_k]
        ]

    async def add_document_chunks(self, chunks, filename) -> int:
        self.documents[filename] = list(chunks)
        return len(chunks)

    async def retrieve_rag_context(self, query, top_k=3) -> str:
        if not self.documents:
            return ""
        parts = ["[RAG文档检索结果]"]
        for fname, chunks in self.documents.items():
            for c in chunks[:top_k]:
                parts.append(f"--- 来源: {fname} ---\n{c['text'][:200]}")
        return "\n".join(parts)

    async def list_documents(self) -> List[dict]:
        return [
            {"filename": fname, "chunks": len(chunks), "timestamp": "2024-01-01T00:00:00"}
            for fname, chunks in self.documents.items()
        ]

    async def delete_document(self, filename) -> bool:
        if filename in self.documents:
            del self.documents[filename]
            return True
        return False


# ============================================================
# Fake Tavily 搜索客户端
# ============================================================

class FakeTavilyClient:
    """假 Tavily 客户端：返回固定搜索结果。"""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def search(self, query, search_depth="basic", max_results=3, include_answer=True) -> dict:
        return {
            "answer": "假的搜索摘要",
            "results": [
                {
                    "title": "假结果一",
                    "url": "https://example.com/1",
                    "content": "假搜索结果内容一",
                },
                {
                    "title": "假结果二",
                    "url": "https://example.com/2",
                    "content": "假搜索结果内容二",
                },
            ],
        }


# ============================================================
# 依赖注入补丁
# ============================================================

def _patch_external_deps(monkeypatch, fake_llm: FakeLLMConfig) -> None:
    """统一替换外部依赖：向量库 / LLM 工厂 / Tavily。"""
    import app.agents.llm as llm_module
    import app.agents.nodes as nodes_module
    import app.main as main_module
    import tavily

    factory = _make_llm_factory(fake_llm)
    monkeypatch.setattr(main_module, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(nodes_module, "create_llm", factory)
    monkeypatch.setattr(llm_module, "create_llm", factory)
    monkeypatch.setattr(tavily, "TavilyClient", FakeTavilyClient)


# ============================================================
# 表截断（测试隔离）
# ============================================================

_TRUNCATE_SQL = """
    TRUNCATE TABLE long_term_memories, rag_chunks, messages,
    conversations, refresh_tokens, token_blacklist, users
    RESTART IDENTITY CASCADE
"""


async def _truncate_tables() -> None:
    """截断所有业务表（测试隔离用，仅在池已初始化时调用）。"""
    from app.db.connection import _pool
    if _pool is not None:
        async with _pool.acquire() as conn:
            await conn.execute(_TRUNCATE_SQL)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def fake_llm() -> FakeLLMConfig:
    """可配置的假 LLM：测试内可修改 route / answer。"""
    return FakeLLMConfig()


@pytest_asyncio.fixture
async def app(monkeypatch, fake_llm):
    """隔离的 FastAPI 应用（HTTP 测试用）：手动触发 lifespan，与请求共用同一事件循环。"""
    from app.core.rate_limit import limiter
    import app.main as main_module

    limiter.enabled = False  # 默认关闭限流，避免测试相互干扰
    _patch_external_deps(monkeypatch, fake_llm)

    application = main_module.create_app()
    async with application.router.lifespan_context(application):
        # 表截断：确保每个测试从干净状态开始
        await _truncate_tables()
        yield application
    limiter.enabled = True


@pytest_asyncio.fixture
async def client(app):
    """httpx 异步测试客户端。"""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def ws_app(monkeypatch, fake_llm):
    """WebSocket 测试专用应用：不手动触发 lifespan，交由 TestClient 管理生命周期。"""
    from app.core.rate_limit import limiter
    import app.main as main_module

    limiter.enabled = False
    _patch_external_deps(monkeypatch, fake_llm)

    application = main_module.create_app()
    yield application
    limiter.enabled = True


# ============================================================
# 认证辅助
# ============================================================

async def register_user(client, username: str = None, password: str = "secret123") -> dict:
    """注册一个新用户并返回令牌响应。"""
    username = username or f"u_{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    assert resp.status_code == 201, f"注册失败: {resp.text}"
    return resp.json()


@pytest_asyncio.fixture
async def auth_headers(client) -> dict:
    """已注册用户的 Authorization 请求头。"""
    data = await register_user(client)
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest_asyncio.fixture
async def auth_tokens(client) -> dict:
    """已注册用户的完整令牌响应（含 access/refresh）。"""
    return await register_user(client)
