"""LLM 容错层单元测试：重试 / 熔断器 / 降级 / 令牌预算。

不依赖真实 LLM：用可控的 FlakyModel（前 N 次抛指定错误，之后成功）驱动全部场景。
每个用例前后重置全局熔断器与预算，避免相互污染。
"""

import time
from typing import Any, List, Optional

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from app.agents.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    ResilientLLM,
    TokenBudget,
    TokenBudgetExceeded,
    _is_transient_error,
    get_circuit_breaker,
    reset_resilience_state,
)
from app.core.config import get_settings


# ============================================================
# 假错误类型（用于瞬时/持久错误分类）
# ============================================================

class RateLimitError(Exception):
    status_code = 429


class ServerError(Exception):
    status_code = 500


class BadRequestError(Exception):
    status_code = 400


class FakeTimeoutError(Exception):
    """名称含 timeout，走启发式判定。"""


# ============================================================
# 可控假模型
# ============================================================

class FlakyModel(BaseChatModel):
    """前 fail_times 次调用抛 error，之后成功返回 response_text。"""

    fail_times: int = 0
    error: Optional[BaseException] = None
    response_text: str = "ok"
    tokens: int = 0
    calls: List[int] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "flaky-model"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise NotImplementedError("仅支持异步")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(1)
        if len(self.calls) <= self.fail_times and self.error is not None:
            raise self.error
        msg = AIMessage(
            content=self.response_text,
            response_metadata={"token_usage": {"total_tokens": self.tokens}},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(1)
        if len(self.calls) <= self.fail_times and self.error is not None:
            raise self.error
        for ch in self.response_text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=ch))

    def bind_tools(self, tools, **kwargs):
        return self


def _make_llm(primary, fallback=None, max_retries=3) -> ResilientLLM:
    return ResilientLLM(
        primary=primary, fallback=fallback, max_retries=max_retries, retry_base_delay=0.01
    )


@pytest.fixture(autouse=True)
def _clean_state():
    reset_resilience_state()
    yield
    reset_resilience_state()


# ============================================================
# 瞬时错误判定
# ============================================================

class TestTransientDetection:
    def test_rate_limit_is_transient(self):
        assert _is_transient_error(RateLimitError()) is True

    def test_server_error_is_transient(self):
        assert _is_transient_error(ServerError()) is True

    def test_bad_request_is_permanent(self):
        assert _is_transient_error(BadRequestError()) is False

    def test_timeout_by_name_is_transient(self):
        assert _is_transient_error(FakeTimeoutError()) is True

    def test_generic_error_is_permanent(self):
        assert _is_transient_error(ValueError("boom")) is False


# ============================================================
# 熔断器
# ============================================================

class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.state == "closed"  # 成功后计数清零，未达阈值

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.06)
        assert cb.state == "half-open"
        assert cb.allow_request() is True  # 半开放行探测

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        time.sleep(0.06)
        cb.record_success()
        assert cb.state == "closed"


# ============================================================
# 令牌预算
# ============================================================

class TestTokenBudget:
    def test_unlimited_never_raises(self):
        budget = TokenBudget(budget_per_minute=0)
        budget.record(10_000_000)
        budget.check()  # 不抛异常

    def test_usage_accumulates(self):
        budget = TokenBudget(budget_per_minute=1000)
        budget.record(100)
        budget.record(200)
        assert budget.usage() == 300

    def test_exceeding_budget_raises(self):
        budget = TokenBudget(budget_per_minute=100)
        budget.record(150)
        with pytest.raises(TokenBudgetExceeded):
            budget.check()

    def test_zero_tokens_not_recorded(self):
        budget = TokenBudget(budget_per_minute=100)
        budget.record(0)
        assert budget.usage() == 0


# ============================================================
# ResilientLLM：重试
# ============================================================

class TestRetry:
    async def test_retries_transient_then_succeeds(self):
        model = FlakyModel(fail_times=2, error=RateLimitError())
        llm = _make_llm(model, max_retries=3)
        result = await llm.ainvoke([])
        assert result.content == "ok"
        assert len(model.calls) == 3  # 失败2次 + 成功1次

    async def test_exhausts_retries_then_raises(self):
        model = FlakyModel(fail_times=999, error=RateLimitError())
        llm = _make_llm(model, max_retries=3)
        with pytest.raises(RateLimitError):
            await llm.ainvoke([])
        assert len(model.calls) == 3  # 恰好重试满 3 次

    async def test_permanent_error_not_retried(self):
        model = FlakyModel(fail_times=999, error=BadRequestError())
        llm = _make_llm(model, max_retries=3)
        with pytest.raises(BadRequestError):
            await llm.ainvoke([])
        assert len(model.calls) == 1  # 持久错误不重试


# ============================================================
# ResilientLLM：降级（fallback）
# ============================================================

class TestFallback:
    async def test_falls_back_after_primary_retries_exhausted(self):
        primary = FlakyModel(fail_times=999, error=RateLimitError())
        fallback = FlakyModel(response_text="from-fallback")
        llm = _make_llm(primary, fallback=fallback, max_retries=2)
        result = await llm.ainvoke([])
        assert result.content == "from-fallback"
        assert len(primary.calls) == 2  # 主模型重试耗尽
        assert len(fallback.calls) == 1

    async def test_uses_fallback_when_breaker_open(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "LLM_CIRCUIT_FAILURE_THRESHOLD", 2)
        breaker = get_circuit_breaker()
        breaker.record_failure()
        breaker.record_failure()  # 强制熔断
        assert breaker.state == "open"

        primary = FlakyModel(response_text="primary")
        fallback = FlakyModel(response_text="fallback")
        llm = _make_llm(primary, fallback=fallback)
        result = await llm.ainvoke([])
        assert result.content == "fallback"
        assert len(primary.calls) == 0  # 熔断后主模型未被调用

    async def test_breaker_open_without_fallback_raises(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "LLM_CIRCUIT_FAILURE_THRESHOLD", 1)
        get_circuit_breaker().record_failure()  # 强制熔断
        llm = _make_llm(FlakyModel())
        with pytest.raises(CircuitBreakerOpen):
            await llm.ainvoke([])


# ============================================================
# ResilientLLM：令牌预算（成本熔断）
# ============================================================

class TestTokenBudgetIntegration:
    async def test_budget_exceeded_blocks_call(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "LLM_TOKEN_BUDGET_PER_MINUTE", 100)
        model = FlakyModel(tokens=60)
        llm = _make_llm(model, max_retries=1)

        await llm.ainvoke([])  # 用量 60
        await llm.ainvoke([])  # 用量 120
        with pytest.raises(TokenBudgetExceeded):
            await llm.ainvoke([])  # 120 >= 100，拒绝
        assert len(model.calls) == 2  # 第三次未真正调用模型


# ============================================================
# ResilientLLM：流式与工具绑定
# ============================================================

class TestStreamAndTools:
    async def test_astream_yields_chunks(self):
        model = FlakyModel(response_text="hello")
        llm = _make_llm(model)
        chunks = [c async for c in llm.astream([])]
        assert "".join(c.content for c in chunks) == "hello"

    async def test_bind_tools_returns_resilient_wrapper(self):
        llm = _make_llm(FlakyModel())
        bound = llm.bind_tools([object()])
        assert isinstance(bound, ResilientLLM)
