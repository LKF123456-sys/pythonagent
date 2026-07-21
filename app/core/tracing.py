"""分布式链路追踪（OpenTelemetry）：可选启用，未启用/未安装时自动降级为 no-op。

设计原则：
- **零侵入降级**：`get_tracer()` 永远可安全调用。OTEL 未安装或未启用时返回 no-op
  tracer，插桩代码近乎零开销，且绝不因追踪问题影响主业务流程。
- **可选导出**：`OTEL_ENABLED=True` 时初始化 TracerProvider + BatchSpanProcessor：
    - 默认 OTLP gRPC 导出到 Jaeger / OTEL Collector（`OTEL_EXPORTER_OTLP_ENDPOINT`）
    - endpoint 设为 ``console`` 时打印到标准输出（本地无 Jaeger 时验证用）
- **LangSmith 互补**：LangGraph 原生支持 LangSmith，设置环境变量
  ``LANGCHAIN_TRACING_V2=true`` + ``LANGCHAIN_API_KEY`` 即可开启，与本模块互不冲突。
"""

from typing import Any

from app.core.config import get_settings
from app.core.logging import setup_logger

logger = setup_logger("core.tracing")

_initialized = False


# ============================================================
# no-op 兜底（OTEL 未安装时使用）
# ============================================================

class _NoOpSpan:
    """空操作 span：实现插桩代码所需的最小接口。"""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: dict) -> None:
        pass

    def record_exception(self, exception: BaseException) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _NoOpTracer:
    """空操作 tracer：start_as_current_span 返回 no-op span。"""

    def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()


_NO_OP_TRACER = _NoOpTracer()


# ============================================================
# 初始化与获取
# ============================================================

def setup_tracing() -> None:
    """初始化追踪管线（幂等）。OTEL 未启用时为空操作。"""
    global _initialized
    if _initialized:
        return

    settings = get_settings()
    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry 追踪未启用（OTEL_ENABLED=False）")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        resource = Resource.create({SERVICE_NAME: settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
        if endpoint.strip().lower() == "console":
            # 本地调试：直接打印 span 到标准输出
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
            )

        trace.set_tracer_provider(provider)
        _initialized = True
        logger.info(
            "OpenTelemetry 追踪已启用: service=%s endpoint=%s",
            settings.OTEL_SERVICE_NAME,
            endpoint,
        )
    except Exception as e:  # noqa: BLE001 - 追踪为可选能力，失败不应阻塞应用
        logger.warning("OpenTelemetry 初始化失败，将以无追踪模式运行: %s", e)


def get_tracer(name: str) -> Any:
    """
    获取 tracer。

    OTEL 已安装时返回 API tracer（未初始化 provider 时为 no-op 代理，初始化后自动生效）；
    OTEL 未安装时返回内置 no-op tracer，保证插桩代码永远可用。
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NO_OP_TRACER
