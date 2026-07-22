"""LLM 容错层单元测试：重试 / 熔断器 / 降级 / 令牌预算 / 模型选择。

不依赖真实 LLM：用可控的 FlakyModel（前 N 次抛指定错误，之后成功）驱动全部场景。
每个用例前后重置全局熔断器与预算，避免相互污染。

测试覆盖：
- 瞬时错误判定（_is_transient_error 各种异常类型）
- 熔断器完整状态转换（closed → open → half-open → closed）
- 令牌预算用量统计与预算超限
- ResilientLLM 重试逻辑
- ResilientLLM 降级（fallback）逻辑
- ResilientLLM 模型选择逻辑
- 流式输出与工具绑定
"""

import time  # 导入时间模块，用于熔断器冷却时间测试
from typing import Any, List, Optional  # 导入类型注解

import pytest  # 导入 pytest 测试框架
from langchain_core.language_models import BaseChatModel  # 导入 LangChain 基础聊天模型类
from langchain_core.messages import AIMessage, AIMessageChunk  # 导入 AI 消息类
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # 导入聊天输出类
from pydantic import Field  # 导入 Pydantic 字段定义工具

from app.agents.resilience import (  # 导入被测的容错组件
    CircuitBreaker,  # 导入熔断器类
    CircuitBreakerOpen,  # 导入熔断器打开异常
    ResilientLLM,  # 导入容错 LLM 包装器
    TokenBudget,  # 导入令牌预算类
    TokenBudgetExceeded,  # 导入令牌预算超限异常
    _extract_token_count,  # 导入 token 用量提取函数
    _is_transient_error,  # 导入瞬时错误判定函数
    get_circuit_breaker,  # 导入获取全局熔断器函数
    get_token_budget,  # 导入获取全局令牌预算函数
    reset_resilience_state,  # 导入重置容错状态函数
)
from app.core.config import get_settings  # 导入配置获取函数


# ============================================================
# 假错误类型（用于瞬时/持久错误分类）
# ============================================================

class RateLimitError(Exception):  # 定义限流错误类
    """模拟 HTTP 429 限流错误。"""
    status_code = 429  # 状态码 429


class ServerError(Exception):  # 定义服务器错误类
    """模拟 HTTP 500 服务器错误。"""
    status_code = 500  # 状态码 500


class BadRequestError(Exception):  # 定义请求参数错误类
    """模拟 HTTP 400 参数错误（持久错误）。"""
    status_code = 400  # 状态码 400


class FakeTimeoutError(Exception):  # 定义超时错误类
    """名称含 timeout，走启发式判定。"""


class FakeConnectionError(Exception):  # 定义连接错误类
    """名称含 connection，走启发式判定。"""


class HttpStatusError(Exception):  # 定义带 http_status 的错误类
    """使用 http_status 属性而非 status_code 的错误。"""
    http_status = 429  # http_status 属性


class GenericError(Exception):  # 定义通用错误类
    """普通异常，不应被识别为瞬时错误。"""


# ============================================================
# 可控假模型
# ============================================================

class FlakyModel(BaseChatModel):  # 定义可控假模型类
    """前 fail_times 次调用抛 error，之后成功返回 response_text。"""

    fail_times: int = 0  # 失败次数，前 N 次抛错
    error: Optional[BaseException] = None  # 抛出的错误
    response_text: str = "ok"  # 成功时返回的文本
    tokens: int = 0  # 返回的 token 用量
    calls: List[int] = Field(default_factory=list)  # 调用记录列表

    class Config:  # Pydantic 配置类
        arbitrary_types_allowed = True  # 允许任意类型

    @property
    def _llm_type(self) -> str:  # 定义 LLM 类型属性
        return "flaky-model"  # 返回类型标识

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # 同步生成方法
        raise NotImplementedError("仅支持异步")  # 不支持同步

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # 异步生成方法
        self.calls.append(1)  # 记录调用
        if len(self.calls) <= self.fail_times and self.error is not None:  # 若仍在失败期
            raise self.error  # 抛出错误
        msg = AIMessage(  # 构造 AI 消息
            content=self.response_text,  # 设置内容
            response_metadata={"token_usage": {"total_tokens": self.tokens}},  # 设置 token 用量
        )  # 构造消息
        return ChatResult(generations=[ChatGeneration(message=msg)])  # 返回聊天结果

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # 异步流式方法
        self.calls.append(1)  # 记录调用
        if len(self.calls) <= self.fail_times and self.error is not None:  # 若仍在失败期
            raise self.error  # 抛出错误
        for ch in self.response_text:  # 遍历文本字符
            yield ChatGenerationChunk(message=AIMessageChunk(content=ch))  # 产出生成块

    def bind_tools(self, tools, **kwargs):  # 工具绑定方法
        return self  # 返回自身


def _make_llm(primary, fallback=None, max_retries=3) -> ResilientLLM:  # 构造容错 LLM 的工厂函数
    """构造 ResilientLLM 实例，使用短重试延迟加速测试。"""
    return ResilientLLM(  # 返回容错 LLM
        primary=primary,  # 设置主模型
        fallback=fallback,  # 设置备用模型
        max_retries=max_retries,  # 设置最大重试次数
        retry_base_delay=0.01,  # 设置短重试延迟
    )  # 返回实例


@pytest.fixture(autouse=True)  # 声明为自动使用的夹具
def _clean_state():  # 定义清理状态夹具
    """每个测试前后重置全局熔断器与预算，避免相互污染。"""
    reset_resilience_state()  # 重置状态
    yield  # 执行测试
    reset_resilience_state()  # 重置状态


# ============================================================
# 瞬时错误判定
# ============================================================

class TestTransientDetection:  # 定义瞬时错误判定测试类
    """测试 _is_transient_error 函数的各种异常类型判定。"""

    def test_rate_limit_is_transient(self):  # 测试 429 限流为瞬时错误
        """测试 429 状态码被识别为瞬时错误。"""
        assert _is_transient_error(RateLimitError()) is True  # 验证 429 为瞬时

    def test_server_error_is_transient(self):  # 测试 500 服务器错误为瞬时错误
        """测试 500 状态码被识别为瞬时错误。"""
        assert _is_transient_error(ServerError()) is True  # 验证 500 为瞬时

    def test_bad_request_is_permanent(self):  # 测试 400 参数错误为持久错误
        """测试 400 状态码被识别为持久错误。"""
        assert _is_transient_error(BadRequestError()) is False  # 验证 400 为持久

    def test_timeout_by_name_is_transient(self):  # 测试按名称识别超时为瞬时错误
        """测试名称含 timeout 的异常被识别为瞬时错误。"""
        assert _is_transient_error(FakeTimeoutError()) is True  # 验证超时为瞬时

    def test_connection_by_name_is_transient(self):  # 测试按名称识别连接错误为瞬时错误
        """测试名称含 connection 的异常被识别为瞬时错误。"""
        assert _is_transient_error(FakeConnectionError()) is True  # 验证连接错误为瞬时

    def test_generic_error_is_permanent(self):  # 测试通用错误为持久错误
        """测试普通 ValueError 被识别为持久错误。"""
        assert _is_transient_error(ValueError("boom")) is False  # 验证通用错误为持久

    def test_http_status_attribute_used(self):  # 测试 http_status 属性被使用
        """测试 http_status 属性也能被识别。"""
        assert _is_transient_error(HttpStatusError()) is True  # 验证 http_status 被识别

    def test_none_status_no_status_falls_to_name(self):  # 测试无状态码时按名称判定
        """测试无状态码属性时按异常类名启发式判定。"""
        # 名称不含瞬时关键词的异常为持久错误
        assert _is_transient_error(GenericError()) is False  # 验证名称判定


# ============================================================
# 熔断器
# ============================================================

class TestCircuitBreaker:  # 定义熔断器测试类
    """测试熔断器的状态转换与记录逻辑。"""

    def test_initial_state_closed(self):  # 测试初始状态为 closed
        """测试熔断器初始状态为 closed。"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)  # 创建熔断器
        assert cb.state == "closed"  # 验证状态
        assert cb.allow_request() is True  # 验证允许请求

    def test_opens_after_threshold_failures(self):  # 测试达到阈值后熔断器打开
        """测试连续失败达到阈值后熔断器打开。"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)  # 创建熔断器
        for _ in range(3):  # 连续失败 3 次
            cb.record_failure()  # 记录失败
        assert cb.state == "open"  # 验证状态为 open
        assert cb.allow_request() is False  # 验证拒绝请求

    def test_success_resets_failure_count(self):  # 测试成功重置失败计数
        """测试成功后失败计数被重置。"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)  # 创建熔断器
        cb.record_failure()  # 记录失败
        cb.record_failure()  # 记录失败
        cb.record_success()  # 记录成功
        cb.record_failure()  # 再记录失败
        assert cb.state == "closed"  # 验证状态为 closed（成功后计数清零）

    def test_half_open_after_recovery_timeout(self):  # 测试冷却期后进入半开状态
        """测试熔断器冷却期后进入 half-open 状态。"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)  # 创建熔断器，短冷却期
        cb.record_failure()  # 记录失败触发熔断
        assert cb.state == "open"  # 验证状态为 open
        time.sleep(0.06)  # 等待冷却期过
        assert cb.state == "half-open"  # 验证状态为 half-open
        assert cb.allow_request() is True  # 验证半开允许探测

    def test_half_open_success_closes(self):  # 测试半开探测成功后关闭
        """测试 half-open 状态探测成功后回到 closed。"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)  # 创建熔断器
        cb.record_failure()  # 触发熔断
        time.sleep(0.06)  # 等待冷却期
        cb.record_success()  # 记录成功
        assert cb.state == "closed"  # 验证回到 closed

    def test_full_state_transition_cycle(self):  # 测试完整状态转换周期
        """测试完整状态转换：closed → open → half-open → closed。"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)  # 创建熔断器
        # 初始状态为 closed
        assert cb.state == "closed"  # 验证初始状态
        # 连续失败 2 次触发熔断
        cb.record_failure()  # 第一次失败
        cb.record_failure()  # 第二次失败，触发熔断
        assert cb.state == "open"  # 验证熔断打开
        # 等待冷却期进入半开
        time.sleep(0.06)  # 等待
        assert cb.state == "half-open"  # 验证半开状态
        # 探测成功后回到 closed
        cb.record_success()  # 记录成功
        assert cb.state == "closed"  # 验证回到 closed

    def test_half_open_failure_reopens(self):  # 测试半开探测失败重新打开
        """测试 half-open 状态探测失败后重新 open。"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)  # 创建熔断器
        cb.record_failure()  # 触发熔断
        time.sleep(0.06)  # 等待冷却期
        assert cb.state == "half-open"  # 验证半开
        cb.record_failure()  # 探测失败
        assert cb.state == "open"  # 验证重新打开

    def test_failure_count_increments(self):  # 测试失败计数递增
        """测试失败计数正确递增。"""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)  # 创建熔断器
        assert cb._failure_count == 0  # 验证初始为 0
        cb.record_failure()  # 记录失败
        assert cb._failure_count == 1  # 验证计数为 1
        cb.record_failure()  # 记录失败
        assert cb._failure_count == 2  # 验证计数为 2

    def test_below_threshold_stays_closed(self):  # 测试未达阈值保持关闭
        """测试失败次数未达阈值时保持 closed。"""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)  # 创建熔断器
        for _ in range(4):  # 失败 4 次（未达 5）
            cb.record_failure()  # 记录失败
        assert cb.state == "closed"  # 验证仍为 closed
        assert cb.allow_request() is True  # 验证仍允许请求


# ============================================================
# 令牌预算
# ============================================================

class TestTokenBudget:  # 定义令牌预算测试类
    """测试令牌预算的用量统计与超限检测。"""

    def test_unlimited_never_raises(self):  # 测试不限制时永不抛出
        """测试预算为 0（不限制）时永不抛出异常。"""
        budget = TokenBudget(budget_per_minute=0)  # 创建不限制预算
        budget.record(10_000_000)  # 记录大量 token
        budget.check()  # 检查不应抛出异常

    def test_usage_accumulates(self):  # 测试用量累积
        """测试 token 用量正确累积。"""
        budget = TokenBudget(budget_per_minute=1000)  # 创建预算
        budget.record(100)  # 记录 100
        budget.record(200)  # 记录 200
        assert budget.usage() == 300  # 验证累计为 300

    def test_exceeding_budget_raises(self):  # 测试超预算抛出异常
        """测试用量超过预算时抛出 TokenBudgetExceeded。"""
        budget = TokenBudget(budget_per_minute=100)  # 创建预算
        budget.record(150)  # 记录 150（超过 100）
        with pytest.raises(TokenBudgetExceeded):  # 期望抛出异常
            budget.check()  # 检查预算

    def test_zero_tokens_not_recorded(self):  # 测试零 token 不记录
        """测试记录 0 个 token 时不计入用量。"""
        budget = TokenBudget(budget_per_minute=100)  # 创建预算
        budget.record(0)  # 记录 0
        assert budget.usage() == 0  # 验证用量为 0

    def test_negative_tokens_not_recorded(self):  # 测试负数 token 不记录
        """测试记录负数 token 时不计入用量。"""
        budget = TokenBudget(budget_per_minute=100)  # 创建预算
        budget.record(-10)  # 记录负数
        assert budget.usage() == 0  # 验证用量为 0

    def test_check_at_exact_budget_raises(self):  # 测试恰好达到预算也抛出
        """测试用量恰好等于预算时也抛出异常。"""
        budget = TokenBudget(budget_per_minute=100)  # 创建预算
        budget.record(100)  # 记录恰好 100
        with pytest.raises(TokenBudgetExceeded):  # 期望抛出异常
            budget.check()  # 检查预算

    def test_purge_removes_expired_records(self):  # 测试清理过期记录
        """测试清理窗口外的过期记录。"""
        budget = TokenBudget(budget_per_minute=1000)  # 创建预算
        budget.record(100)  # 记录 100
        # 手动添加一个过期记录
        budget._window.append((time.monotonic() - 100, 200))  # 添加 100 秒前的记录
        # 清理后过期记录应被移除
        budget._purge(time.monotonic())  # 清理过期记录
        assert budget.usage() == 100  # 验证仅剩当前记录


# ============================================================
# Token 用量提取
# ============================================================

class TestExtractTokenCount:  # 定义 token 用量提取测试类
    """测试 _extract_token_count 函数。"""

    def test_extract_from_usage_metadata(self):  # 测试从 usage_metadata 提取
        """测试从 usage_metadata 字典提取 token 用量。"""

        class FakeResponse:  # 定义假响应类
            usage_metadata = {"total_tokens": 42}  # 设置用量元数据

        result = _extract_token_count(FakeResponse())  # 提取用量
        assert result == 42  # 验证提取结果

    def test_extract_from_response_metadata(self):  # 测试从 response_metadata 提取
        """测试从 response_metadata.token_usage 提取 token 用量。"""

        class FakeResponse:  # 定义假响应类
            usage_metadata = None  # 无 usage_metadata
            response_metadata = {"token_usage": {"total_tokens": 99}}  # 设置响应元数据

        result = _extract_token_count(FakeResponse())  # 提取用量
        assert result == 99  # 验证提取结果

    def test_extract_returns_zero_when_no_metadata(self):  # 测试无元数据返回 0
        """测试无任何元数据时返回 0。"""

        class FakeResponse:  # 定义假响应类
            pass  # 无任何属性

        result = _extract_token_count(FakeResponse())  # 提取用量
        assert result == 0  # 验证返回 0

    def test_extract_with_none_values(self):  # 测试 None 值处理
        """测试元数据中 total_tokens 为 None 时返回 0。"""

        class FakeResponse:  # 定义假响应类
            usage_metadata = {"total_tokens": None}  # total_tokens 为 None

        result = _extract_token_count(FakeResponse())  # 提取用量
        assert result == 0  # 验证返回 0


# ============================================================
# ResilientLLM：模型选择逻辑
# ============================================================

class TestModelSelection:  # 定义模型选择测试类
    """测试 ResilientLLM 的模型选择逻辑。"""

    def test_select_primary_when_breaker_closed(self):  # 测试熔断关闭时选择主模型
        """测试熔断器关闭时选择主模型。"""
        primary = FlakyModel(response_text="primary")  # 创建主模型
        fallback = FlakyModel(response_text="fallback")  # 创建备用模型
        llm = _make_llm(primary, fallback=fallback)  # 创建容错 LLM
        # 熔断器关闭时应选择主模型
        selected = llm._select_model()  # 选择模型
        assert selected is primary  # 验证选择主模型

    def test_select_fallback_when_breaker_open(self, monkeypatch):  # 测试熔断打开时选择备用模型
        """测试熔断器打开时选择备用模型。"""
        monkeypatch.setattr(get_settings(), "LLM_CIRCUIT_FAILURE_THRESHOLD", 1)  # 设置阈值为 1
        breaker = get_circuit_breaker()  # 获取熔断器
        breaker.record_failure()  # 触发熔断
        assert breaker.state == "open"  # 验证熔断打开

        primary = FlakyModel(response_text="primary")  # 创建主模型
        fallback = FlakyModel(response_text="fallback")  # 创建备用模型
        llm = _make_llm(primary, fallback=fallback)  # 创建容错 LLM
        selected = llm._select_model()  # 选择模型
        assert selected is fallback  # 验证选择备用模型

    def test_select_raises_when_breaker_open_no_fallback(self, monkeypatch):  # 测试无备用时熔断抛出
        """测试熔断打开且无备用模型时抛出 CircuitBreakerOpen。"""
        monkeypatch.setattr(get_settings(), "LLM_CIRCUIT_FAILURE_THRESHOLD", 1)  # 设置阈值为 1
        get_circuit_breaker().record_failure()  # 触发熔断
        llm = _make_llm(FlakyModel())  # 创建无备用的容错 LLM
        with pytest.raises(CircuitBreakerOpen):  # 期望抛出异常
            llm._select_model()  # 选择模型

    def test_llm_type_property(self):  # 测试 LLM 类型属性
        """测试 _llm_type 属性返回正确值。"""
        llm = _make_llm(FlakyModel())  # 创建容错 LLM
        assert llm._llm_type == "resilient-llm"  # 验证类型标识


# ============================================================
# ResilientLLM：重试
# ============================================================

class TestRetry:  # 定义重试测试类
    """测试 ResilientLLM 的重试逻辑。"""

    async def test_retries_transient_then_succeeds(self):  # 测试瞬时错误重试后成功
        """测试瞬时错误重试后成功。"""
        model = FlakyModel(fail_times=2, error=RateLimitError())  # 前 2 次失败
        llm = _make_llm(model, max_retries=3)  # 最大重试 3 次
        result = await llm.ainvoke([])  # 调用
        assert result.content == "ok"  # 验证返回内容
        assert len(model.calls) == 3  # 验证调用 3 次（2 失败 + 1 成功）

    async def test_exhausts_retries_then_raises(self):  # 测试重试耗尽后抛出
        """测试重试耗尽后抛出原始异常。"""
        model = FlakyModel(fail_times=999, error=RateLimitError())  # 永远失败
        llm = _make_llm(model, max_retries=3)  # 最大重试 3 次
        with pytest.raises(RateLimitError):  # 期望抛出异常
            await llm.ainvoke([])  # 调用
        assert len(model.calls) == 3  # 验证恰好重试 3 次

    async def test_permanent_error_not_retried(self):  # 测试持久错误不重试
        """测试持久错误不重试。"""
        model = FlakyModel(fail_times=999, error=BadRequestError())  # 持久错误
        llm = _make_llm(model, max_retries=3)  # 最大重试 3 次
        with pytest.raises(BadRequestError):  # 期望抛出异常
            await llm.ainvoke([])  # 调用
        assert len(model.calls) == 1  # 验证仅调用 1 次


# ============================================================
# ResilientLLM：降级（fallback）
# ============================================================

class TestFallback:  # 定义降级测试类
    """测试 ResilientLLM 的降级逻辑。"""

    async def test_falls_back_after_primary_retries_exhausted(self):  # 测试主模型重试耗尽后降级
        """测试主模型重试耗尽后降级到备用模型。"""
        primary = FlakyModel(fail_times=999, error=RateLimitError())  # 主模型永远失败
        fallback = FlakyModel(response_text="from-fallback")  # 备用模型成功
        llm = _make_llm(primary, fallback=fallback, max_retries=2)  # 最大重试 2 次
        result = await llm.ainvoke([])  # 调用
        assert result.content == "from-fallback"  # 验证返回备用模型结果
        assert len(primary.calls) == 2  # 验证主模型重试 2 次
        assert len(fallback.calls) == 1  # 验证备用模型调用 1 次

    async def test_uses_fallback_when_breaker_open(self, monkeypatch):  # 测试熔断时使用备用
        """测试主模型熔断时使用备用模型。"""
        monkeypatch.setattr(get_settings(), "LLM_CIRCUIT_FAILURE_THRESHOLD", 2)  # 设置阈值为 2
        breaker = get_circuit_breaker()  # 获取熔断器
        breaker.record_failure()  # 第一次失败
        breaker.record_failure()  # 第二次失败，触发熔断
        assert breaker.state == "open"  # 验证熔断打开

        primary = FlakyModel(response_text="primary")  # 主模型
        fallback = FlakyModel(response_text="fallback")  # 备用模型
        llm = _make_llm(primary, fallback=fallback)  # 创建容错 LLM
        result = await llm.ainvoke([])  # 调用
        assert result.content == "fallback"  # 验证返回备用结果
        assert len(primary.calls) == 0  # 验证主模型未被调用

    async def test_breaker_open_without_fallback_raises(self, monkeypatch):  # 测试无备用熔断抛出
        """测试熔断打开且无备用模型时抛出异常。"""
        monkeypatch.setattr(get_settings(), "LLM_CIRCUIT_FAILURE_THRESHOLD", 1)  # 设置阈值为 1
        get_circuit_breaker().record_failure()  # 触发熔断
        llm = _make_llm(FlakyModel())  # 无备用
        with pytest.raises(CircuitBreakerOpen):  # 期望抛出异常
            await llm.ainvoke([])  # 调用


# ============================================================
# ResilientLLM：令牌预算（成本熔断）
# ============================================================

class TestTokenBudgetIntegration:  # 定义令牌预算集成测试类
    """测试 ResilientLLM 与令牌预算的集成。"""

    async def test_budget_exceeded_blocks_call(self, monkeypatch):  # 测试预算超限阻止调用
        """测试令牌预算超限时阻止新的 LLM 调用。"""
        monkeypatch.setattr(get_settings(), "LLM_TOKEN_BUDGET_PER_MINUTE", 100)  # 设置预算 100
        model = FlakyModel(tokens=60)  # 每次消耗 60
        llm = _make_llm(model, max_retries=1)  # 最大重试 1 次

        await llm.ainvoke([])  # 第一次调用，用量 60
        await llm.ainvoke([])  # 第二次调用，用量 120
        with pytest.raises(TokenBudgetExceeded):  # 期望抛出预算超限
            await llm.ainvoke([])  # 第三次调用应被阻止
        assert len(model.calls) == 2  # 验证第三次未真正调用模型


# ============================================================
# ResilientLLM：流式与工具绑定
# ============================================================

class TestStreamAndTools:  # 定义流式与工具测试类
    """测试 ResilientLLM 的流式输出与工具绑定。"""

    async def test_astream_yields_chunks(self):  # 测试流式产出块
        """测试 astream 正确产出流式块。"""
        model = FlakyModel(response_text="hello")  # 返回 hello
        llm = _make_llm(model)  # 创建容错 LLM
        chunks = [c async for c in llm.astream([])]  # 收集流式块
        assert "".join(c.content for c in chunks) == "hello"  # 验证拼接内容

    async def test_bind_tools_returns_resilient_wrapper(self):  # 测试工具绑定返回容错包装器
        """测试 bind_tools 返回 ResilientLLM 实例。"""
        llm = _make_llm(FlakyModel())  # 创建容错 LLM
        bound = llm.bind_tools([object()])  # 绑定工具
        assert isinstance(bound, ResilientLLM)  # 验证返回类型

    async def test_astream_fallback_on_failure(self):  # 测试流式失败时降级
        """测试主模型流式失败时降级到备用模型。"""
        primary = FlakyModel(fail_times=999, error=RateLimitError())  # 主模型流式失败
        fallback = FlakyModel(response_text="fallback-stream")  # 备用模型
        llm = _make_llm(primary, fallback=fallback, max_retries=1)  # 创建容错 LLM
        chunks = [c async for c in llm.astream([])]  # 收集流式块
        content = "".join(c.content for c in chunks)  # 拼接内容
        assert content == "fallback-stream"  # 验证返回备用模型内容


# ============================================================
# 全局实例管理
# ============================================================

class TestGlobalInstances:  # 定义全局实例测试类
    """测试全局熔断器与预算的惰性初始化。"""

    def test_get_circuit_breaker_returns_same_instance(self):  # 测试获取全局熔断器返回同一实例
        """测试 get_circuit_breaker 返回同一实例。"""
        breaker1 = get_circuit_breaker()  # 第一次获取
        breaker2 = get_circuit_breaker()  # 第二次获取
        assert breaker1 is breaker2  # 验证同一实例

    def test_get_token_budget_returns_same_instance(self):  # 测试获取全局预算返回同一实例
        """测试 get_token_budget 返回同一实例。"""
        budget1 = get_token_budget()  # 第一次获取
        budget2 = get_token_budget()  # 第二次获取
        assert budget1 is budget2  # 验证同一实例

    def test_reset_creates_new_instances(self):  # 测试重置后创建新实例
        """测试 reset_resilience_state 后获取新实例。"""
        breaker1 = get_circuit_breaker()  # 获取实例
        budget1 = get_token_budget()  # 获取实例
        reset_resilience_state()  # 重置状态
        breaker2 = get_circuit_breaker()  # 获取新实例
        budget2 = get_token_budget()  # 获取新实例
        assert breaker1 is not breaker2  # 验证实例不同
        assert budget1 is not budget2  # 验证实例不同
