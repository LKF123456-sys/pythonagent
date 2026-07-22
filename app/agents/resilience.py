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

import threading  # 导入线程模块，用于线程锁保证线程安全
import time  # 导入时间模块，用于获取时间戳和单调时钟
from typing import Any, List, Optional  # 从typing导入Any、List、Optional类型，用于类型注解

from langchain_core.language_models import BaseChatModel  # 导入LangChain基础聊天模型类，作为ResilientLLM的基类
from langchain_core.messages import BaseMessageChunk  # 导入LangChain基础消息分块类，用于流式输出类型检查
from tenacity import (  # 从tenacity库导入重试相关组件
    AsyncRetrying,  # 异步重试控制器
    retry_if_exception,  # 按异常类型决定是否重试
    stop_after_attempt,  # 达到指定尝试次数后停止
    wait_exponential,  # 指数退避等待策略
)

from app.core.config import get_settings  # 导入配置获取函数，用于读取容错相关配置
from app.core.logging import setup_logger  # 导入日志设置函数，用于创建模块专用logger
from app.core.tracing import get_tracer  # 导入追踪器获取函数，用于链路追踪

logger = setup_logger("agents.resilience")  # 创建本模块专用的日志记录器，名称为agents.resilience
tracer = get_tracer("app.agents.resilience")  # 创建本模块专用的追踪器，用于链路追踪


# ============================================================
# 异常定义
# ============================================================

class CircuitBreakerOpen(Exception):  # 定义熔断器打开异常，继承自Exception
    """熔断器处于打开状态：请求被快速失败。"""


class TokenBudgetExceeded(Exception):  # 定义令牌预算超限异常，继承自Exception
    """令牌预算耗尽：成本熔断触发，拒绝新的 LLM 调用。"""


# ============================================================
# 瞬时错误判定
# ============================================================

def _is_transient_error(exc: BaseException) -> bool:  # 定义瞬时错误判定的私有函数，返回布尔值
    """
    判定是否为值得重试的瞬时错误。

    瞬时错误：HTTP 429（限流）、5xx（服务端故障）、超时、连接失败。
    持久错误（如 400/401/404 参数或鉴权问题）重试无意义，直接失败。
    """
    status = getattr(exc, "status_code", None)  # 获取异常的status_code属性
    if status is None:  # 如果status_code不存在
        status = getattr(exc, "http_status", None)  # 尝试获取http_status属性
    if isinstance(status, int):  # 如果状态码是整数
        return status == 429 or status >= 500  # 429限流或5xx服务端错误返回True

    # 无明确状态码时按异常类型名称启发式判断
    name = type(exc).__name__.lower()  # 获取异常类名并转为小写
    transient_keywords = (  # 定义瞬时错误关键词元组
        "timeout", "timedout", "connection", "ratelimit", "rate_limit",  # 超时、连接、限流相关
        "unavailable", "temporarily", "network",  # 不可用、临时、网络相关
    )
    return any(keyword in name for keyword in transient_keywords)  # 异常名包含任一关键词则返回True


# ============================================================
# 熔断器
# ============================================================

class CircuitBreaker:  # 定义熔断器类
    """
    熔断器（线程安全）。

    状态机：
        closed   --连续失败>=阈值-->  open
        open     --冷却期结束-->      half-open
        half-open --探测成功-->       closed
        half-open --探测失败-->       open
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:  # 熔断器构造函数
        self.failure_threshold = failure_threshold  # 设置连续失败跳闸阈值
        self.recovery_timeout = recovery_timeout  # 设置冷却恢复超时时间（秒）
        self._failure_count = 0  # 当前连续失败计数，初始为0
        self._opened_at: Optional[float] = None  # 熔断器打开时间戳，初始为None
        self._lock = threading.Lock()  # 创建线程锁，保证状态变更线程安全

    @property  # 声明为属性
    def state(self) -> str:  # 定义状态属性，返回当前状态字符串
        """当前状态：closed / open / half-open。"""
        with self._lock:  # 获取线程锁
            if self._opened_at is None:  # 如果从未打开过
                return "closed"  # 返回关闭状态
            if time.monotonic() - self._opened_at >= self.recovery_timeout:  # 如果冷却期已过
                return "half-open"  # 返回半开状态
            return "open"  # 否则返回打开状态

    def allow_request(self) -> bool:  # 定义是否放行请求的方法
        """是否放行请求（open 状态拒绝，half-open 放行探测）。"""
        return self.state != "open"  # 状态不为open时放行

    def record_success(self) -> None:  # 定义记录成功的方法
        """记录成功：重置计数并关闭熔断。"""
        with self._lock:  # 获取线程锁
            self._failure_count = 0  # 重置失败计数为0
            self._opened_at = None  # 清除打开时间戳，关闭熔断

    def record_failure(self) -> None:  # 定义记录失败的方法
        """记录失败：累计计数，达到阈值则跳闸。"""
        with self._lock:  # 获取线程锁
            self._failure_count += 1  # 失败计数加1
            if self._failure_count >= self.failure_threshold:  # 如果失败计数达到阈值
                if self._opened_at is None:  # 如果熔断器之前未打开
                    logger.warning("熔断器打开：连续失败 %d 次", self._failure_count)  # 记录警告日志
                self._opened_at = time.monotonic()  # 记录熔断打开的单调时间戳


# ============================================================
# 令牌预算（成本熔断）
# ============================================================

class TokenBudget:  # 定义令牌预算类
    """
    60 秒滑动窗口令牌预算（线程安全）。

    用量达到预算上限时，`check()` 抛出 TokenBudgetExceeded，
    拒绝新的 LLM 调用，防止成本失控。budget<=0 表示不限制。
    """

    WINDOW_SECONDS = 60.0  # 滑动窗口时间长度，60秒

    def __init__(self, budget_per_minute: int) -> None:  # 令牌预算构造函数
        self.budget_per_minute = budget_per_minute  # 设置每分钟令牌预算上限
        self._window: List[tuple] = []  # (monotonic 时间戳, token 数)  # 滑动窗口记录列表，存(时间戳, token数)元组
        self._lock = threading.Lock()  # 创建线程锁，保证线程安全

    def _purge(self, now: float) -> None:  # 定义清理过期记录的私有方法
        """清理窗口外的过期记录。"""
        cutoff = now - self.WINDOW_SECONDS  # 计算窗口起始时间点
        self._window = [(ts, n) for ts, n in self._window if ts >= cutoff]  # 仅保留窗口内的记录

    def usage(self) -> int:  # 定义获取当前用量的方法，返回token总数
        """最近 60 秒的累计 token 用量。"""
        now = time.monotonic()  # 获取当前单调时间
        with self._lock:  # 获取线程锁
            self._purge(now)  # 清理过期记录
            return sum(n for _, n in self._window)  # 返回窗口内所有token数的总和

    def check(self) -> None:  # 定义预算检查方法
        """预算检查：超限时抛出 TokenBudgetExceeded。"""
        if self.budget_per_minute <= 0:  # 如果预算不大于0（表示不限制）
            return  # 直接返回，不做检查
        current = self.usage()  # 获取当前用量
        if current >= self.budget_per_minute:  # 如果当前用量达到或超过预算
            raise TokenBudgetExceeded(  # 抛出令牌预算超限异常
                f"最近 60 秒已消耗 {current} tokens，超出预算 {self.budget_per_minute}"  # 异常消息含当前用量和预算
            )

    def record(self, tokens: int) -> None:  # 定义记录token用量的方法
        """记录一次调用的 token 用量。"""
        if tokens <= 0:  # 如果token数不大于0
            return  # 不记录，直接返回
        now = time.monotonic()  # 获取当前单调时间
        with self._lock:  # 获取线程锁
            self._purge(now)  # 清理过期记录
            self._window.append((now, tokens))  # 将当前调用的(时间戳, token数)追加到窗口


# ============================================================
# 全局共享实例（所有 LLM 调用共用同一熔断器与预算）
# ============================================================

_circuit_breaker: Optional[CircuitBreaker] = None  # 全局熔断器实例，初始为None
_token_budget: Optional[TokenBudget] = None  # 全局令牌预算实例，初始为None


def get_circuit_breaker() -> CircuitBreaker:  # 定义获取全局熔断器的函数
    """获取全局熔断器（惰性初始化）。"""
    global _circuit_breaker  # 声明使用全局_circuit_breaker变量
    if _circuit_breaker is None:  # 如果熔断器尚未初始化
        settings = get_settings()  # 获取应用配置
        _circuit_breaker = CircuitBreaker(  # 创建熔断器实例
            failure_threshold=settings.LLM_CIRCUIT_FAILURE_THRESHOLD,  # 设置失败阈值
            recovery_timeout=float(settings.LLM_CIRCUIT_RECOVERY_TIMEOUT),  # 设置恢复超时时间
        )
    return _circuit_breaker  # 返回熔断器实例


def get_token_budget() -> TokenBudget:  # 定义获取全局令牌预算的函数
    """获取全局令牌预算（惰性初始化）。"""
    global _token_budget  # 声明使用全局_token_budget变量
    if _token_budget is None:  # 如果令牌预算尚未初始化
        _token_budget = TokenBudget(get_settings().LLM_TOKEN_BUDGET_PER_MINUTE)  # 创建令牌预算实例
    return _token_budget  # 返回令牌预算实例


def reset_resilience_state() -> None:  # 定义重置容错状态的函数
    """重置全局熔断器与预算（主要供测试使用）。"""
    global _circuit_breaker, _token_budget  # 声明使用全局变量
    _circuit_breaker = None  # 重置熔断器为None
    _token_budget = None  # 重置令牌预算为None


# ============================================================
# Token 用量提取
# ============================================================

def _extract_token_count(response: Any) -> int:  # 定义从LLM响应提取token用量的私有函数
    """从 LLM 响应中提取 total_tokens（兼容多种返回结构）。"""
    usage = getattr(response, "usage_metadata", None)  # 获取usage_metadata属性
    if isinstance(usage, dict):  # 如果用量元数据是字典
        return int(usage.get("total_tokens", 0) or 0)  # 返回total_tokens字段值
    meta = getattr(response, "response_metadata", None)  # 获取response_metadata属性
    if isinstance(meta, dict):  # 如果响应元数据是字典
        token_usage = meta.get("token_usage") or {}  # 获取token_usage字段，默认空字典
        return int(token_usage.get("total_tokens", 0) or 0)  # 返回total_tokens字段值
    return 0  # 都未找到则返回0


# ============================================================
# 容错 LLM 包装器
# ============================================================

class ResilientLLM(BaseChatModel):  # 定义容错LLM包装器类，继承自BaseChatModel
    """
    具备重试 / 熔断 / 降级 / 令牌预算的 LLM 包装器。

    包装任意聊天模型，对外保持标准接口（ainvoke / astream / bind_tools），
    使上层节点代码无需感知容错逻辑。
    """

    primary: Any = None                  # 主模型（如 ChatOpenAI）  # 主模型字段，初始为None
    fallback: Optional[Any] = None       # 备用模型（可选）  # 备用模型字段，初始为None
    max_retries: int = 3  # 最大重试次数，默认3
    retry_base_delay: float = 1.0  # 重试基础延迟（秒），默认1.0

    class Config:  # Pydantic配置类
        arbitrary_types_allowed = True  # 允许任意类型字段（兼容非Pydantic模型）

    @property  # 声明为属性
    def _llm_type(self) -> str:  # 定义LLM类型属性
        return "resilient-llm"  # 返回类型标识字符串

    def _select_model(self) -> Any:  # 定义选择当前使用模型的私有方法
        """选择当前应使用的模型：主模型熔断时切换备用模型。"""
        breaker = get_circuit_breaker()  # 获取全局熔断器
        if breaker.allow_request():  # 如果熔断器允许请求
            return self.primary  # 返回主模型
        if self.fallback is not None:  # 如果配置了备用模型
            logger.info("主模型熔断，切换到备用模型")  # 记录切换日志
            return self.fallback  # 返回备用模型
        raise CircuitBreakerOpen("LLM 熔断器已打开且未配置备用模型")  # 抛出熔断器打开异常

    async def _call_with_retry(self, model: Any, messages: List[Any], **kwargs: Any) -> Any:  # 定义带重试的异步调用方法
        """对模型调用应用指数退避重试；失败时记录到熔断器。"""
        breaker = get_circuit_breaker()  # 获取全局熔断器
        retrying = AsyncRetrying(  # 创建异步重试控制器
            stop=stop_after_attempt(self.max_retries),  # 达到最大重试次数后停止
            wait=wait_exponential(  # 指数退避等待
                multiplier=self.retry_base_delay,  # 乘数为基础延迟
                min=self.retry_base_delay,  # 最小等待时间
                max=10.0,  # 最大等待时间10秒
            ),
            retry=retry_if_exception(_is_transient_error),  # 仅对瞬时错误重试
            reraise=True,  # 重试耗尽后重新抛出原始异常
        )
        attempts = 0  # 尝试次数计数器，初始为0
        try:  # 开始异常捕获块
            with tracer.start_as_current_span("llm.invoke") as span:  # 开启LLM调用追踪span
                span.set_attribute("llm.model", getattr(model, "_llm_type", type(model).__name__))  # 设置span属性：模型类型
                span.set_attribute("llm.max_retries", self.max_retries)  # 设置span属性：最大重试次数
                async for attempt in retrying:  # 异步迭代重试控制器的尝试
                    with attempt:  # 进入尝试上下文
                        attempts += 1  # 尝试次数加1
                        result = await model.ainvoke(messages, **kwargs)  # 异步调用模型
                        span.set_attribute("llm.attempts", attempts)  # 设置span属性：实际尝试次数
                        return result  # 返回调用结果
        except Exception:  # 捕获所有异常
            breaker.record_failure()  # 向熔断器记录失败
            raise  # 重新抛出异常

    # ---- 同步路径（应用主要走异步，此处保持接口完整） ----
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # 定义同步生成方法
        get_token_budget().check()  # 检查令牌预算
        model = self._select_model()  # 选择当前模型
        result = model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)  # 调用模型同步生成
        get_circuit_breaker().record_success()  # 向熔断器记录成功
        get_token_budget().record(_extract_token_count(result.generations[0].message))  # 记录token用量
        return result  # 返回生成结果

    # ---- 异步非流式：完整容错（重试 + 熔断 + 降级 + 预算） ----
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # 定义异步生成方法
        get_token_budget().check()  # 检查令牌预算
        model = self._select_model()  # 选择当前模型
        try:  # 开始异常捕获块
            response = await self._call_with_retry(model, messages, stop=stop, **kwargs)  # 带重试地调用模型
        except Exception:  # 捕获异常
            # 主模型重试耗尽后，若配置了备用模型则降级一次
            if model is self.primary and self.fallback is not None:  # 如果是主模型且配置了备用模型
                logger.warning("主模型调用失败，降级到备用模型重试")  # 记录降级日志
                response = await self.fallback.ainvoke(messages, stop=stop, **kwargs)  # 调用备用模型
            else:  # 否则
                raise  # 重新抛出异常
        get_circuit_breaker().record_success()  # 向熔断器记录成功
        get_token_budget().record(_extract_token_count(response))  # 记录token用量
        # 转换为 ChatResult 以满足 BaseChatModel 协议
        from langchain_core.outputs import ChatGeneration, ChatResult  # 导入ChatGeneration和ChatResult类

        return ChatResult(generations=[ChatGeneration(message=response)])  # 返回构造的ChatResult

    # ---- 异步流式：熔断 + 预算 + 降级（不做中途重试，避免重复输出） ----
    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # 定义异步流式生成方法
        from langchain_core.messages import AIMessageChunk  # 导入AI消息分块类
        from langchain_core.outputs import ChatGenerationChunk  # 导入聊天生成分块类

        get_token_budget().check()  # 检查令牌预算
        model = self._select_model()  # 选择当前模型
        last_usage = 0  # 最后一次记录的token用量，初始为0
        with tracer.start_as_current_span("llm.stream") as span:  # 开启LLM流式追踪span
            span.set_attribute("llm.model", getattr(model, "_llm_type", type(model).__name__))  # 设置span属性：模型类型
            try:  # 开始异常捕获块
                async for chunk in model.astream(messages, stop=stop, **kwargs):  # 异步迭代模型的流式输出
                    usage = _extract_token_count(chunk)  # 提取chunk中的token用量
                    if usage:  # 如果有用量信息
                        last_usage = usage  # 更新最后用量
                    # 确保 chunk 是 MessageChunk 类型（兼容某些 provider 返回 AIMessage）
                    if not isinstance(chunk, BaseMessageChunk):  # 如果chunk不是BaseMessageChunk类型
                        chunk = AIMessageChunk(content=chunk.content)  # 转换为AIMessageChunk
                    yield ChatGenerationChunk(message=chunk)  # 产出生成分块
            except Exception:  # 捕获异常
                # 流建立阶段失败时尝试降级到备用模型
                if model is self.primary and self.fallback is not None:  # 如果是主模型且配置了备用模型
                    logger.warning("主模型流式失败，降级到备用模型")  # 记录降级日志
                    async for chunk in self.fallback.astream(messages, stop=stop, **kwargs):  # 异步迭代备用模型流式输出
                        if not isinstance(chunk, BaseMessageChunk):  # 如果chunk不是BaseMessageChunk类型
                            chunk = AIMessageChunk(content=chunk.content)  # 转换为AIMessageChunk
                        yield ChatGenerationChunk(message=chunk)  # 产出生成分块
                else:  # 否则
                    get_circuit_breaker().record_failure()  # 向熔断器记录失败
                    raise  # 重新抛出异常
        get_circuit_breaker().record_success()  # 向熔断器记录成功
        get_token_budget().record(last_usage)  # 记录token用量

    # ---- 工具绑定：返回同样具备容错能力的新包装器 ----
    def bind_tools(self, tools, **kwargs):  # 定义工具绑定方法
        return ResilientLLM(  # 返回新的ResilientLLM实例
            primary=self.primary.bind_tools(tools, **kwargs),  # 主模型绑定工具
            fallback=self.fallback.bind_tools(tools, **kwargs) if self.fallback else None,  # 备用模型绑定工具，无备用则None
            max_retries=self.max_retries,  # 继承最大重试次数
            retry_base_delay=self.retry_base_delay,  # 继承重试基础延迟
        )
