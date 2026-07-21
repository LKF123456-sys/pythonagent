"""LangGraph 工作流编排：astream_events 原生流式。

核心修复（Phase 2.3）：
- 废弃旧版手动逐节点执行（run_agent_stream 脱离 LangGraph 编排的问题）
- 使用 LangGraph 原生 graph.astream_events(version="v2")：
  - 监听 on_chain_start 事件 → 推送节点状态
  - 捕获 answer 节点的 on_chat_model_stream → 经 TagStreamParser 产出 token 流
  - 保留检查点恢复 + 状态追踪能力，节点逻辑单一维护点
"""

import asyncio
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.core.constants import (
    NODE_ANSWER,
    NODE_PREPROCESS,
    NODE_RAG,
    NODE_SEARCH,
    NODE_STORE_MEMORY,
    NODE_SUPERVISOR,
)
from app.core.logging import setup_logger
from app.core.tracing import get_tracer
from app.agents.nodes import (
    AgentState,
    answer_node,
    preprocess_node,
    rag_node,
    route_after_supervisor,
    search_node,
    store_memory_node,
    supervisor_node,
)
from app.agents.stream_parser import TagStreamParser

logger = setup_logger("agents.graph")
tracer = get_tracer("app.agents.graph")

# 节点名集合（用于过滤 astream_events 中的节点级事件）
NODE_NAMES = {
    NODE_PREPROCESS,
    NODE_SUPERVISOR,
    NODE_SEARCH,
    NODE_RAG,
    NODE_ANSWER,
    NODE_STORE_MEMORY,
}

# 节点展示名（用于前端状态推送）
NODE_DISPLAY_NAMES = {
    NODE_PREPROCESS: "理解问题",
    NODE_SUPERVISOR: "任务路由",
    NODE_SEARCH: "联网搜索",
    NODE_RAG: "知识检索",
    NODE_ANSWER: "生成回答",
    NODE_STORE_MEMORY: "写入记忆",
}


@dataclass
class GraphStreamEvent:
    """图执行产出的统一流事件（供 Service / WebSocket 层消费）。"""

    type: str  # status | thinking | token | done | error
    node: str = ""        # status 事件对应的节点名
    content: str = ""     # thinking / token / error 的文本内容
    answer: str = ""      # done 事件的完整回答
    route: str = ""       # supervisor 路由决策（SEARCH/RAG/DIRECT）
    token_count: int = 0  # LLM token 用量（如可获取）


# ============================================================
# 图构建与单例管理
# ============================================================

_graph = None


def _build_workflow() -> StateGraph:
    """构建多智能体工作流（未编译）。"""
    workflow = StateGraph(AgentState)

    workflow.add_node(NODE_PREPROCESS, preprocess_node)
    workflow.add_node(NODE_SUPERVISOR, supervisor_node)
    workflow.add_node(NODE_SEARCH, search_node)
    workflow.add_node(NODE_RAG, rag_node)
    workflow.add_node(NODE_ANSWER, answer_node)
    workflow.add_node(NODE_STORE_MEMORY, store_memory_node)

    workflow.add_edge(START, NODE_PREPROCESS)
    workflow.add_edge(NODE_PREPROCESS, NODE_SUPERVISOR)
    workflow.add_conditional_edges(
        NODE_SUPERVISOR,
        route_after_supervisor,
        {
            "search": NODE_SEARCH,
            "rag": NODE_RAG,
            "answer": NODE_ANSWER,
        },
    )
    workflow.add_edge(NODE_SEARCH, NODE_ANSWER)
    workflow.add_edge(NODE_RAG, NODE_ANSWER)
    workflow.add_edge(NODE_ANSWER, NODE_STORE_MEMORY)
    workflow.add_edge(NODE_STORE_MEMORY, END)

    return workflow


def compile_graph(checkpointer=None):
    """编译图单例。checkpointer 可注入（默认 MemorySaver）。"""
    global _graph
    if checkpointer is None:
        checkpointer = MemorySaver()
    _graph = _build_workflow().compile(checkpointer=checkpointer)
    logger.info("LangGraph 工作流编译完成（checkpointer=%s）", type(checkpointer).__name__)
    return _graph


def get_graph():
    """获取编译后的图单例（首次调用自动编译）。"""
    global _graph
    if _graph is None:
        compile_graph()
    return _graph


def _make_initial_state(
    user_question: str,
    image_path: str = "",
    history_context: str = "",
    is_first_turn: bool = False,
    user_id: int = 0,
) -> dict:
    """构建工作流初始状态。"""
    return {
        "messages": [],
        "user_question": user_question,
        "action": "",
        "image_path": image_path,
        "image_analysis": "",
        "search_results": "",
        "rag_context": "",
        "long_term_memories": "",
        "history_context": history_context,
        "is_first_turn": is_first_turn,
        "user_id": user_id,
    }


# ============================================================
# 非流式执行入口
# ============================================================

async def run_agent(
    user_question: str,
    thread_id: str = "default",
    image_path: str = "",
    history_context: str = "",
    is_first_turn: bool = False,
    user_id: int = 0,
) -> str:
    """非流式执行（ainvoke），返回最终回答文本。"""
    graph = get_graph()
    initial_state = _make_initial_state(
        user_question, image_path, history_context, is_first_turn, user_id
    )
    config = {"configurable": {"thread_id": thread_id}}
    with tracer.start_as_current_span("graph.invoke") as span:
        span.set_attribute("graph.thread_id", thread_id)
        span.set_attribute("graph.user_id", user_id)
        result = await graph.ainvoke(initial_state, config=config)

    for msg in reversed(result.get("messages", [])):
        if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
            return msg.content
    return ""


# ============================================================
# 流式执行入口（astream_events 原生流式）
# ============================================================

async def run_agent_stream(
    user_question: str,
    thread_id: str = "default",
    image_path: str = "",
    history_context: str = "",
    is_first_turn: bool = False,
    user_id: int = 0,
) -> AsyncGenerator[GraphStreamEvent, None]:
    """流式执行入口（包裹追踪 span，具体逻辑委托给 _run_agent_stream_impl）。"""
    with tracer.start_as_current_span("graph.stream") as span:
        span.set_attribute("graph.thread_id", thread_id)
        span.set_attribute("graph.user_id", user_id)
        async for event in _run_agent_stream_impl(
            user_question, thread_id, image_path, history_context, is_first_turn, user_id
        ):
            yield event


async def _run_agent_stream_impl(
    user_question: str,
    thread_id: str = "default",
    image_path: str = "",
    history_context: str = "",
    is_first_turn: bool = False,
    user_id: int = 0,
) -> AsyncGenerator[GraphStreamEvent, None]:
    """
    流式执行（astream_events version="v2"）。

    事件协议：
    - status   : 节点开始（node + 展示名）
    - thinking : <thinking> 标签内的思考内容
    - token    : 回答正文 token
    - done     : 完成（携带完整 answer / route / token_count）
    - error    : 执行异常
    """
    graph = get_graph()
    initial_state = _make_initial_state(
        user_question, image_path, history_context, is_first_turn, user_id
    )
    config = {"configurable": {"thread_id": thread_id}}

    parser = TagStreamParser()
    current_node = ""
    answer_parts: list[str] = []
    route_action = ""
    token_count = 0

    def _drain_parser() -> list:
        """刷出解析器剩余内容，返回待发送事件。"""
        out = []
        for ev in parser.flush():
            if ev.type == "thinking":
                out.append(GraphStreamEvent(type="thinking", content=ev.content))
            elif ev.content:
                answer_parts.append(ev.content)
                out.append(GraphStreamEvent(type="token", content=ev.content))
        return out

    try:
        async for event in graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            event_type = event.get("event", "")
            event_name = event.get("name", "")

            # 节点开始 → 状态推送（按节点名去重）
            if event_type == "on_chain_start" and event_name in NODE_NAMES:
                if event_name != current_node:
                    current_node = event_name
                    yield GraphStreamEvent(
                        type="status",
                        node=event_name,
                        content=NODE_DISPLAY_NAMES.get(event_name, event_name),
                    )
                continue

            # 仅捕获 answer 节点的 LLM token 流
            if event_type == "on_chat_model_stream" and current_node == NODE_ANSWER:
                chunk = event.get("data", {}).get("chunk")
                if chunk is None:
                    continue
                content = _chunk_text(chunk)
                if not content:
                    continue
                for ev in parser.feed(content):
                    if ev.type == "thinking":
                        yield GraphStreamEvent(type="thinking", content=ev.content)
                    elif ev.content:
                        answer_parts.append(ev.content)
                        yield GraphStreamEvent(type="token", content=ev.content)
                continue

            # 捕获 supervisor 路由决策
            if event_type == "on_chain_end" and event_name == NODE_SUPERVISOR:
                action = _extract_action(event.get("data", {}).get("output"))
                if action:
                    route_action = action
                continue

            # 捕获 answer 节点 LLM 的 token 用量
            if event_type == "on_chat_model_end" and current_node == NODE_ANSWER:
                usage = _extract_token_usage(event.get("data", {}).get("output"))
                if usage:
                    token_count = usage
                continue

        # 正常结束：刷出解析器剩余内容
        for ev in _drain_parser():
            yield ev

        yield GraphStreamEvent(
            type="done",
            answer="".join(answer_parts),
            route=route_action,
            token_count=token_count,
        )

    except asyncio.CancelledError:
        # 用户中断生成：记录日志并向上传播（WebSocket 层负责取消）
        logger.info("流式生成被中断（thread=%s）", thread_id)
        raise
    except Exception as e:
        logger.exception("图流式执行失败")
        yield GraphStreamEvent(type="error", content=f"处理失败：{e}")


# ============================================================
# 辅助提取函数
# ============================================================

def _chunk_text(chunk) -> str:
    """从 LLM 流 chunk 中安全提取文本内容。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, list):
        # 多模态/分块内容：拼接其中的文本部分
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text", ""))
            else:
                parts.append(str(part))
        return "".join(parts)
    return content or ""


def _extract_action(output) -> str:
    """从 supervisor 节点输出中提取路由决策。"""
    if isinstance(output, dict):
        action = output.get("action", "")
        if action:
            return action
    return ""


def _extract_token_usage(output) -> int:
    """从 LLM 输出中提取 token 用量（兼容多种返回结构）。"""
    if output is None:
        return 0
    usage = getattr(output, "usage_metadata", None)
    if usage:
        if isinstance(usage, dict):
            return int(usage.get("total_tokens", 0) or 0)
        return int(getattr(usage, "total_tokens", 0) or 0)
    meta = getattr(output, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            return int(token_usage.get("total_tokens", 0) or 0)
    return 0
