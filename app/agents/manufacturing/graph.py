"""工业智能制造 LangGraph 工作流编排：astream_events 原生流式。

图结构：
START → mfg_preprocess → mfg_supervisor → ┬→ fault_diagnosis
                                           ├→ process_optimization
                                           ├→ predictive_maintenance
                                           └→ knowledge_qa
                                                ↓
                                           mfg_answer → mfg_store_memory → END
"""

import asyncio
from dataclasses import dataclass
from typing import AsyncGenerator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.core.logging import setup_logger
from app.core.tracing import get_tracer
from app.agents.manufacturing.nodes import (
    MfgAgentState,
    fault_diagnosis_node,
    knowledge_qa_node,
    mfg_answer_node,
    mfg_preprocess_node,
    mfg_store_memory_node,
    mfg_supervisor_node,
    predictive_maintenance_node,
    process_optimization_node,
    route_after_mfg_supervisor,
)
from app.agents.stream_parser import TagStreamParser

logger = setup_logger("agents.manufacturing.graph")
tracer = get_tracer("app.agents.manufacturing.graph")

# 节点名常量
NODE_MFG_PREPROCESS = "mfg_preprocess"
NODE_MFG_SUPERVISOR = "mfg_supervisor"
NODE_MFG_FAULT = "fault_diagnosis"
NODE_MFG_PROCESS = "process_optimization"
NODE_MFG_PREDICT = "predictive_maintenance"
NODE_MFG_KNOWLEDGE = "knowledge_qa"
NODE_MFG_ANSWER = "mfg_answer"
NODE_MFG_STORE = "mfg_store_memory"

# 节点名集合（用于过滤 astream_events）
MFG_NODE_NAMES = {
    NODE_MFG_PREPROCESS,
    NODE_MFG_SUPERVISOR,
    NODE_MFG_FAULT,
    NODE_MFG_PROCESS,
    NODE_MFG_PREDICT,
    NODE_MFG_KNOWLEDGE,
    NODE_MFG_ANSWER,
    NODE_MFG_STORE,
}

# 节点展示名（用于前端状态推送）
MFG_NODE_DISPLAY_NAMES = {
    NODE_MFG_PREPROCESS: "加载领域知识",
    NODE_MFG_SUPERVISOR: "工业任务路由",
    NODE_MFG_FAULT: "故障诊断分析",
    NODE_MFG_PROCESS: "工艺参数分析",
    NODE_MFG_PREDICT: "设备健康评估",
    NODE_MFG_KNOWLEDGE: "工业知识检索",
    NODE_MFG_ANSWER: "生成专业回答",
    NODE_MFG_STORE: "写入工业记忆",
}


@dataclass
class MfgGraphStreamEvent:
    """工业图执行产出的统一流事件。"""

    type: str  # status | thinking | token | done | error
    node: str = ""
    content: str = ""
    answer: str = ""
    route: str = ""
    token_count: int = 0


# ============================================================
# 图构建与单例管理
# ============================================================

_mfg_graph = None


def _build_mfg_workflow() -> StateGraph:
    """构建工业多智能体工作流（未编译）。"""
    workflow = StateGraph(MfgAgentState)

    workflow.add_node(NODE_MFG_PREPROCESS, mfg_preprocess_node)
    workflow.add_node(NODE_MFG_SUPERVISOR, mfg_supervisor_node)
    workflow.add_node(NODE_MFG_FAULT, fault_diagnosis_node)
    workflow.add_node(NODE_MFG_PROCESS, process_optimization_node)
    workflow.add_node(NODE_MFG_PREDICT, predictive_maintenance_node)
    workflow.add_node(NODE_MFG_KNOWLEDGE, knowledge_qa_node)
    workflow.add_node(NODE_MFG_ANSWER, mfg_answer_node)
    workflow.add_node(NODE_MFG_STORE, mfg_store_memory_node)

    # 边定义
    workflow.add_edge(START, NODE_MFG_PREPROCESS)
    workflow.add_edge(NODE_MFG_PREPROCESS, NODE_MFG_SUPERVISOR)
    workflow.add_conditional_edges(
        NODE_MFG_SUPERVISOR,
        route_after_mfg_supervisor,
        {
            "fault_diagnosis": NODE_MFG_FAULT,
            "process_optimization": NODE_MFG_PROCESS,
            "predictive_maintenance": NODE_MFG_PREDICT,
            "knowledge_qa": NODE_MFG_KNOWLEDGE,
        },
    )
    # 所有子领域节点汇聚到回答节点
    workflow.add_edge(NODE_MFG_FAULT, NODE_MFG_ANSWER)
    workflow.add_edge(NODE_MFG_PROCESS, NODE_MFG_ANSWER)
    workflow.add_edge(NODE_MFG_PREDICT, NODE_MFG_ANSWER)
    workflow.add_edge(NODE_MFG_KNOWLEDGE, NODE_MFG_ANSWER)
    workflow.add_edge(NODE_MFG_ANSWER, NODE_MFG_STORE)
    workflow.add_edge(NODE_MFG_STORE, END)

    return workflow


def compile_mfg_graph(checkpointer=None):
    """编译工业图单例。"""
    global _mfg_graph
    if checkpointer is None:
        checkpointer = MemorySaver()
    _mfg_graph = _build_mfg_workflow().compile(checkpointer=checkpointer)
    logger.info("工业 LangGraph 工作流编译完成（checkpointer=%s）", type(checkpointer).__name__)
    return _mfg_graph


def get_mfg_graph():
    """获取编译后的工业图单例（首次调用自动编译）。"""
    global _mfg_graph
    if _mfg_graph is None:
        compile_mfg_graph()
    return _mfg_graph


def _make_mfg_initial_state(
    user_question: str,
    history_context: str = "",
    user_id: int = 0,
    image_path: str = "",
) -> dict:
    """构建工业工作流初始状态。"""
    return {
        "messages": [],
        "user_question": user_question,
        "action": "",
        "image_path": image_path,
        "image_analysis": "",
        "fault_code_info": "",
        "equipment_params": "",
        "sensor_data": "",
        "maintenance_info": "",
        "process_analysis": "",
        "rag_context": "",
        "history_context": history_context,
        "user_id": user_id,
    }


# ============================================================
# 流式执行入口
# ============================================================

async def run_mfg_agent_stream(
    user_question: str,
    thread_id: str = "mfg_default",
    history_context: str = "",
    user_id: int = 0,
    image_path: str = "",
) -> AsyncGenerator[MfgGraphStreamEvent, None]:
    """工业流式执行入口（包裹追踪 span）。"""
    with tracer.start_as_current_span("mfg_graph.stream") as span:
        span.set_attribute("mfg_graph.thread_id", thread_id)
        span.set_attribute("mfg_graph.user_id", user_id)
        async for event in _run_mfg_stream_impl(
            user_question, thread_id, history_context, user_id, image_path
        ):
            yield event


async def _run_mfg_stream_impl(
    user_question: str,
    thread_id: str = "mfg_default",
    history_context: str = "",
    user_id: int = 0,
    image_path: str = "",
) -> AsyncGenerator[MfgGraphStreamEvent, None]:
    """
    工业流式执行（astream_events version="v2"）。

    事件协议与通用管线一致：status / thinking / token / done / error
    """
    graph = get_mfg_graph()
    initial_state = _make_mfg_initial_state(user_question, history_context, user_id, image_path)
    config = {"configurable": {"thread_id": thread_id}}

    parser = TagStreamParser()
    current_node = ""
    answer_parts: list[str] = []
    route_action = ""
    token_count = 0

    def _drain_parser() -> list:
        """刷出解析器剩余内容。"""
        out = []
        for ev in parser.flush():
            if ev.type == "thinking":
                out.append(MfgGraphStreamEvent(type="thinking", content=ev.content))
            elif ev.content:
                answer_parts.append(ev.content)
                out.append(MfgGraphStreamEvent(type="token", content=ev.content))
        return out

    try:
        async for event in graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            event_type = event.get("event", "")
            event_name = event.get("name", "")

            # 节点开始 → 状态推送
            if event_type == "on_chain_start" and event_name in MFG_NODE_NAMES:
                if event_name != current_node:
                    current_node = event_name
                    yield MfgGraphStreamEvent(
                        type="status",
                        node=event_name,
                        content=MFG_NODE_DISPLAY_NAMES.get(event_name, event_name),
                    )
                continue

            # 捕获 answer 节点的 LLM token 流
            if event_type == "on_chat_model_stream" and current_node == NODE_MFG_ANSWER:
                chunk = event.get("data", {}).get("chunk")
                if chunk is None:
                    continue
                content = _chunk_text(chunk)
                if not content:
                    continue
                for ev in parser.feed(content):
                    if ev.type == "thinking":
                        yield MfgGraphStreamEvent(type="thinking", content=ev.content)
                    elif ev.content:
                        answer_parts.append(ev.content)
                        yield MfgGraphStreamEvent(type="token", content=ev.content)
                continue

            # 捕获 supervisor 路由决策
            if event_type == "on_chain_end" and event_name == NODE_MFG_SUPERVISOR:
                action = _extract_action(event.get("data", {}).get("output"))
                if action:
                    route_action = action
                continue

            # 捕获 token 用量
            if event_type == "on_chat_model_end" and current_node == NODE_MFG_ANSWER:
                usage = _extract_token_usage(event.get("data", {}).get("output"))
                if usage:
                    token_count = usage
                continue

        # 正常结束
        for ev in _drain_parser():
            yield ev

        yield MfgGraphStreamEvent(
            type="done",
            answer="".join(answer_parts),
            route=route_action,
            token_count=token_count,
        )

    except asyncio.CancelledError:
        logger.info("工业流式生成被中断（thread=%s）", thread_id)
        raise
    except Exception as e:
        logger.exception("工业图流式执行失败")
        yield MfgGraphStreamEvent(type="error", content=f"处理失败：{e}")


# ============================================================
# 辅助函数
# ============================================================

def _chunk_text(chunk) -> str:
    """从 LLM 流 chunk 中安全提取文本。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, list):
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
    """从 LLM 输出中提取 token 用量。"""
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
