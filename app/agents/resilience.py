"""LLM 容错层：重试（指数退避）+ 熔断器 + 降级（fallback）+ 令牌预算（成本熔断）。

设计目标：让 LLM 调用在面对瞬时故障与成本失控时具备弹性。

- **重试**：仅对瞬时错误（429 限流 / 5xx / 超时 / 连接错误）指数退避重试，
  业务错误（如 4xx 参数错误）不重试，直接抛出。
- **熔断器**：连续失败达到阈值后"跳闸"，后续请求快速失败，避免雪崩；
  冷却期后进入"半开"状态放行探测请求，成功则恢复。
- **降级**：主模型熔断且配置了备用模型时，自动切换到备用模型。
- **令牌预算**：按 60 秒滑动窗口统计 token 用量，超出预算拒绝新调用（成本熔断）。

`ResilientLLM` 透明包装任意聊天模型（保持 ainvoke / astream / bind_tools 接口），
由 `app.agents.llm.create_llm` 在创建主模型后自动套上，对调用方无感。
"""

import threading
import time
from typing import Any, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessageChunk
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import setup_logger
from app.core.tracing import get_tracer

logger = setup_logger("agents.resilience")
tracer = get_tracer("app.agents.resilience")


# ============================================================
# 异常定义
# ============================================================

class CircuitBreakerOpen(Exception):
    """熔断器处于打开状态：请求被快速失败。"""


class TokenBudgetExceeded(Exception):
    """令牌预算耗尽：成本熔断触发，拒绝新的 LLM 调用。"""


# ============================================================
# 瞬时错误判定
# ============================================================

def _is_transient_error(exc: BaseException) -> bool:
    """
    判定是否为值得重试的瞬时错误。

    瞬时错误：HTTP 429（限流）、5xx（服务端故障）、超时、连接失败。
    持久错误（如 400/401/404 参数或鉴权问题）重试无意义，直接失败。
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "http_status", None)
    if isinstance(status, int):
        return status == 429 or status >= 500

    # 无明确状态码时按异常类型名称启发式判断
    name = type(exc).__name__.lower()
    transient_keywords = (
        "timeout", "timedout", "connection", "ratelimit", "rate_limit",
        "unavailable", "temporarily", "network",
    )
    return any(keyword in name for keyword in transient_keywords)


# ============================================================
# 熔断器
# ============================================================

class CircuitBreaker:
    """
    熔断器（线程安全）。

    状态机：
        closed   --连续失败>=阈值-->  open
        open     --冷却期结束-->      half-open
        half-open --探测成功-->       closed
        half-open --探测失败-->       open
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """当前状态：closed / open / half-open。"""
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                return "half-open"
            return "open"

    def allow_request(self) -> bool:
        """是否放行请求（open 状态拒绝，half-open 放行探测）。"""
        return self.state != "open"

    def record_success(self) -> None:
        """记录成功：重置计数并关闭熔断。"""
        with self._lock:
            self._failure_count = 0
            self._opened_at = None

    def record_failure(self) -> None:
        """记录失败：累计计数，达到阈值则跳闸。"""
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._opened_at is None:
                    logger.warning("熔断器打开：连续失败 %d 次", self._failure_count)
                self._opened_at = time.monotonic()


# ============================================================
# 令牌预算（成本熔断）
# ============================================================

class TokenBudget:
    """
    60 秒滑动窗口令牌预算（线程安全）。

    用量达到预算上限时，`check()` 抛出 TokenBudgetExceeded，
    拒绝新的 LLM 调用，防止成本失控。budget<=0 表示不限制。
    """

    WINDOW_SECONDS = 60.0

    def __init__(self, budget_per_minute: int) -> None:
        self.budget_per_minute = budget_per_minute
        self._window: List[tuple] = []  # (monotonic 时间戳, token 数)
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        """清理窗口外的过期记录。"""
        cutoff = now - self.WINDOW_SECONDS
        self._window = [(ts, n) for ts, n in self._window if ts >= cutoff]

    def usage(self) -> int:
        """最近 60 秒的累计 token 用量。"""
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            return sum(n for _, n in self._window)

    def check(self) -> None:
        """预算检查：超限时抛出 TokenBudgetExceeded。"""
        if self.budget_per_minute <= 0:
            return
        current = self.usage()
        if current >= self.budget_per_minute:
            raise TokenBudgetExceeded(
                f"最近 60 秒已消耗 {current} tokens，超出预算 {self.budget_per_minute}"
            )

    def record(self, tokens: int) -> None:
        """记录一次调用的 token 用量。"""
        if tokens <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            self._window.append((now, tokens))


# ============================================================
# 全局共享实例（所有 LLM 调用共用同一熔断器与预算）
# ============================================================

_circuit_breaker: Optional[CircuitBreaker] = None
_token_budget: Optional[TokenBudget] = None


def get_circuit_breaker() -> CircuitBreaker:
    """获取全局熔断器（惰性初始化）。"""
    global _circuit_breaker
    if _circuit_breaker is None:
        settings = get_settings()
        _circuit_breaker = CircuitBreaker(
            failure_threshold=settings.LLM_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout=float(settings.LLM_CIRCUIT_RECOVERY_TIMEOUT),
        )
    return _circuit_breaker


def get_token_budget() -> TokenBudget:
    """获取全局令牌预算（惰性初始化）。"""
    global _token_budget
    if _token_budget is None:
        _token_budget = TokenBudget(get_settings().LLM_TOKEN_BUDGET_PER_MINUTE)
    return _token_budget


def reset_resilience_state() -> None:
    """重置全局熔断器与预算（主要供测试使用）。"""
    global _circuit_breaker, _token_budget
    _circuit_breaker = None
    _token_budget = None


# ============================================================
# Token 用量提取
# ============================================================

def _extract_token_count(response: Any) -> int:
    """从 LLM 响应中提取 total_tokens（兼容多种返回结构）。"""
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        return int(usage.get("total_tokens", 0) or 0)
    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or {}
        return int(token_usage.get("total_tokens", 0) or 0)
    return 0


# ============================================================
# 容错 LLM 包装器
# ============================================================

class ResilientLLM(BaseChatModel):
    """
    具备重试 / 熔断 / 降级 / 令牌预算的 LLM 包装器。

    包装任意聊天模型，对外保持标准接口（ainvoke / astream / bind_tools），
    使上层节点代码无需感知容错逻辑。
    """

    primary: Any = None                  # 主模型（如 ChatOpenAI）
    fallback: Optional[Any] = None       # 备用模型（可选）
    max_retries: int = 3
    retry_base_delay: float = 1.0

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "resilient-llm"

    def _select_model(self) -> Any:
        """选择当前应使用的模型：主模型熔断时切换备用模型。"""
        breaker = get_circuit_breaker()
        if breaker.allow_request():
            return self.primary
        if self.fallback is not None:
            logger.info("主模型熔断，切换到备用模型")
            return self.fallback
        raise CircuitBreakerOpen("LLM 熔断器已打开且未配置备用模型")

    async def _call_with_retry(self, model: Any, messages: List[Any], **kwargs: Any) -> Any:
        """对模型调用应用指数退避重试；失败时记录到熔断器。"""
        breaker = get_circuit_breaker()
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(
                multiplier=self.retry_base_delay,
                min=self.retry_base_delay,
                max=10.0,
            ),
            retry=retry_if_exception(_is_transient_error),
            reraise=True,
        )
        attempts = 0
        try:
            with tracer.start_as_current_span("llm.invoke") as span:
                span.set_attribute("llm.model", getattr(model, "_llm_type", type(model).__name__))
                span.set_attribute("llm.max_retries", self.max_retries)
                async for attempt in retrying:
                    with attempt:
                        attempts += 1
                        result = await model.ainvoke(messages, **kwargs)
                        span.set_attribute("llm.attempts", attempts)
                        return result
        except Exception:
            breaker.record_failure()
            raise

    # ---- 同步路径（应用主要走异步，此处保持接口完整） ----
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        get_token_budget().check()
        model = self._select_model()
        result = model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        get_circuit_breaker().record_success()
        get_token_budget().record(_extract_token_count(result.generations[0].message))
        return result

    # ---- 异步非流式：完整容错（重试 + 熔断 + 降级 + 预算） ----
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        get_token_budget().check()
        model = self._select_model()
        try:
            response = await self._call_with_retry(model, messages, stop=stop, **kwargs)
        except Exception:
            # 主模型重试耗尽后，若配置了备用模型则降级一次
            if model is self.primary and self.fallback is not None:
                logger.warning("主模型调用失败，降级到备用模型重试")
                response = await self.fallback.ainvoke(messages, stop=stop, **kwargs)
            else:
                raise
        get_circuit_breaker().record_success()
        get_token_budget().record(_extract_token_count(response))
        # 转换为 ChatResult 以满足 BaseChatModel 协议
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=response)])

    # ---- 异步流式：熔断 + 预算 + 降级（不做中途重试，避免重复输出） ----
    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        get_token_budget().check()
        model = self._select_model()
        last_usage = 0
        with tracer.start_as_current_span("llm.stream") as span:
            span.set_attribute("llm.model", getattr(model, "_llm_type", type(model).__name__))
            try:
                async for chunk in model.astream(messages, stop=stop, **kwargs):
                    usage = _extract_token_count(chunk)
                    if usage:
                        last_usage = usage
                    # 确保 chunk 是 MessageChunk 类型（兼容某些 provider 返回 AIMessage）
                    if not isinstance(chunk, BaseMessageChunk):
                        chunk = AIMessageChunk(content=chunk.content)
                    yield ChatGenerationChunk(message=chunk)
            except Exception:
                # 流建立阶段失败时尝试降级到备用模型
                if model is self.primary and self.fallback is not None:
                    logger.warning("主模型流式失败，降级到备用模型")
                    async for chunk in self.fallback.astream(messages, stop=stop, **kwargs):
                        if not isinstance(chunk, BaseMessageChunk):
                            chunk = AIMessageChunk(content=chunk.content)
                        yield ChatGenerationChunk(message=chunk)
                else:
                    get_circuit_breaker().record_failure()
                    raise
        get_circuit_breaker().record_success()
        get_token_budget().record(last_usage)

    # ---- 工具绑定：返回同样具备容错能力的新包装器 ----
    def bind_tools(self, tools, **kwargs):
        return ResilientLLM(
            primary=self.primary.bind_tools(tools, **kwargs),
            fallback=self.fallback.bind_tools(tools, **kwargs) if self.fallback else None,
            max_retries=self.max_retries,
            retry_base_delay=self.retry_base_delay,
        )
