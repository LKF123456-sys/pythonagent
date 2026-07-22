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

from typing import Any  # 从typing导入Any类型注解，用于动态类型的类型提示

from app.core.config import get_settings  # 导入配置获取函数，读取OTEL相关配置
from app.core.logging import setup_logger  # 导入日志配置函数，创建追踪模块日志记录器

logger = setup_logger("core.tracing")  # 创建名为core.tracing的日志记录器实例

_initialized = False  # 追踪初始化状态标志，False表示未初始化，用于幂等控制


# ============================================================
# no-op 兜底（OTEL 未安装时使用）
# ============================================================

class _NoOpSpan:
    """空操作 span：实现插桩代码所需的最小接口。"""

    def set_attribute(self, key: str, value: Any) -> None:
        pass  # 空实现，设置span属性时不做任何操作

    def set_attributes(self, attributes: dict) -> None:
        pass  # 空实现，批量设置span属性时不做任何操作

    def record_exception(self, exception: BaseException) -> None:
        pass  # 空实现，记录异常到span时不做任何操作

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass  # 空实现，设置span状态时不做任何操作

    def add_event(self, *args: Any, **kwargs: Any) -> None:
        pass  # 空实现，添加span事件时不做任何操作

    def __enter__(self) -> "_NoOpSpan":
        return self  # 上下文管理器进入方法，返回自身支持with语句

    def __exit__(self, *args: Any) -> bool:
        return False  # 上下文管理器退出方法，返回False表示不抑制异常


class _NoOpTracer:
    """空操作 tracer：start_as_current_span 返回 no-op span。"""

    def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()  # 返回一个新的空操作span实例，实现无追踪降级


_NO_OP_TRACER = _NoOpTracer()  # 创建全局空操作tracer单例实例，OTEL未安装时使用


# ============================================================
# 初始化与获取
# ============================================================

def setup_tracing() -> None:
    """初始化追踪管线（幂等）。OTEL 未启用时为空操作。"""
    global _initialized  # 声明使用全局变量_initialized
    if _initialized:  # 若已初始化
        return  # 直接返回，避免重复初始化

    settings = get_settings()  # 获取全局配置实例
    if not settings.OTEL_ENABLED:  # 若OTEL未启用
        logger.info("OpenTelemetry 追踪未启用（OTEL_ENABLED=False）")  # 记录信息日志说明未启用
        return  # 直接返回，不执行初始化

    try:  # 尝试初始化OTEL追踪
        from opentelemetry import trace  # 导入OTEL trace API模块
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # 导入资源定义相关类，用于标识服务
        from opentelemetry.sdk.trace import TracerProvider  # 导入TracerProvider，追踪提供者
        from opentelemetry.sdk.trace.export import (  # 导入span导出相关组件
            BatchSpanProcessor,  # 批量span处理器，异步批量导出
            ConsoleSpanExporter,  # 控制台span导出器，打印到标准输出
            SimpleSpanProcessor,  # 简单span处理器，同步导出
        )

        resource = Resource.create({SERVICE_NAME: settings.OTEL_SERVICE_NAME})  # 创建资源，包含服务名称用于标识
        provider = TracerProvider(resource=resource)  # 创建TracerProvider并关联资源

        endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT  # 获取OTLP导出端点配置
        if endpoint.strip().lower() == "console":  # 若端点配置为console
            # 本地调试：直接打印 span 到标准输出
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))  # 添加控制台导出处理器，同步打印span
        else:  # 否则为远程导出
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # 导入OTLP gRPC导出器
                OTLPSpanExporter,  # OTLP span导出器类
            )

            provider.add_span_processor(  # 添加批量span处理器
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))  # 创建批量处理器，导出到OTLP端点，insecure=True允许非加密连接
            )

        trace.set_tracer_provider(provider)  # 设置全局tracer提供者
        _initialized = True  # 标记为已初始化
        logger.info(  # 记录信息日志说明追踪已启用
            "OpenTelemetry 追踪已启用: service=%s endpoint=%s",  # 日志格式字符串
            settings.OTEL_SERVICE_NAME,  # 服务名称
            endpoint,  # 导出端点
        )
    except Exception as e:  # noqa: BLE001 - 追踪为可选能力，失败不应阻塞应用
        logger.warning("OpenTelemetry 初始化失败，将以无追踪模式运行: %s", e)  # 记录警告日志，说明将以无追踪模式运行


def get_tracer(name: str) -> Any:
    """
    获取 tracer。

    OTEL 已安装时返回 API tracer（未初始化 provider 时为 no-op 代理，初始化后自动生效）；
    OTEL 未安装时返回内置 no-op tracer，保证插桩代码永远可用。
    """
    try:  # 尝试导入OTEL并获取tracer
        from opentelemetry import trace  # 导入OTEL trace API模块

        return trace.get_tracer(name)  # 返回OTEL API tracer，未初始化provider时为no-op代理
    except ImportError:  # 若OTEL未安装
        return _NO_OP_TRACER  # 返回内置空操作tracer，保证插桩代码可用
