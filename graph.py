"""
LangGraph工作流编排模块：完整的6节点工作流 + Prometheus 监控指标。
START → preprocess(视觉) → supervisor(路由) → [search|rag] → answer → store_memory → END

改进：
- 编译后的 Graph 使用单例缓存，避免每次请求重建
- 修复 RAG 路由分支（supervisor 输出 RAG 时正确路由到 rag_node）
- 所有 print 替换为 logging
- 新增 astream 流式运行方法
- Prometheus 业务指标埋点
"""

import os
import time
import asyncio
from typing import TypedDict, Annotated, Literal, Optional, AsyncGenerator
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from config import Config
from logger import setup_logger
from agents import (
    supervisor_decide, search_web, analyze_image, generate_answer,
)
from memory import (
    retrieve_long_term_memories, format_memories_context,
    retrieve_rag_context, store_conversation_turn,
)
from database import (
    create_conversation, update_conversation_time, add_message,
)

logger = setup_logger("graph", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# Prometheus 业务指标（延迟导入，避免循环依赖）
# ============================================================

_agent_requests_total = None
_llm_response_duration = None
_rag_chunks_total = None


def _init_metrics():
    """初始化 Prometheus 自定义指标（幂等）。"""
    global _agent_requests_total, _llm_response_duration, _rag_chunks_total
    if _agent_requests_total is not None:
        return
    try:
        from prometheus_client import Counter, Histogram
        _agent_requests_total = Counter(
            "agent_requests_total",
            "Total agent routing decisions",
            ["route_type"],
        )
        _llm_response_duration = Histogram(
            "llm_response_duration_seconds",
            "LLM call duration in seconds",
            ["agent_name"],
            buckets=[0.5, 1, 2, 5, 10, 30, 60],
        )
        _rag_chunks_total = Counter(
            "rag_chunks_stored_total",
            "Total RAG document chunks stored",
        )
    except ImportError:
        logger.warning("prometheus_client 未安装，业务指标不可用")


def _record_route(route_type: str):
    if _agent_requests_total:
        _agent_requests_total.labels(route_type=route_type).inc()


def _record_llm_duration(agent_name: str, duration: float):
    if _llm_response_duration:
        _llm_response_duration.labels(agent_name=agent_name).observe(duration)


def _record_rag_chunks(count: int):
    if _rag_chunks_total and count > 0:
        _rag_chunks_total.inc(count)


# ============================================================
# 状态定义
# ============================================================

class AgentState(TypedDict):
    """多智能体工作流状态。"""
    messages: Annotated[list, add_messages]  # 对话历史（自动累积）
    user_question: str                       # 当前用户问题
    action: str                              # 主管路由决策: SEARCH/RAG/DIRECT
    image_path: str                          # 上传图片路径（空=无图片）
    image_analysis: str                      # 视觉分析结果
    search_results: str                      # 搜索结果
    rag_context: str                         # RAG检索结果
    long_term_memories: str                  # 长期记忆检索结果
    is_first_turn: bool                      # 是否本轮对话的第一条消息
    user_id: int                             # 当前用户 ID


# ============================================================
# 辅助函数：从消息历史中提取对话上下文
# ============================================================

def _extract_history_context(messages: list, current_question: str) -> str:
    """从消息列表中提取对话历史摘要（短期记忆）。"""
    cutoff_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, HumanMessage) and msg.content == current_question:
            cutoff_idx = i
            break
    history_msgs = messages[:cutoff_idx] if cutoff_idx > 0 else []
    max_msgs = Config.MAX_HISTORY_TURNS * 2
    history_msgs = history_msgs[-max_msgs:]
    if not history_msgs:
        return ""
    lines = []
    for msg in history_msgs:
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


# ============================================================
# 节点1：预处理节点（处理图片 + 长期记忆检索）
# ============================================================

def preprocess_node(state: AgentState) -> dict:
    """
    预处理节点：处理图片识别 + 检索长期记忆 + 检索RAG。

    如果用户上传了图片，调用视觉Agent分析。
    同时检索长期记忆和RAG文档库。
    """
    user_question = state["user_question"]
    image_path = state.get("image_path", "")
    updates = {}

    # 步骤1：图片识别
    if image_path and os.path.exists(image_path):
        logger.info("视觉Agent: 正在分析图片...")
        t0 = time.time()
        image_analysis = analyze_image(image_path, user_question)
        _record_llm_duration("vision", time.time() - t0)
        logger.info("视觉Agent: 分析完成（%d字符）", len(image_analysis))
        updates["image_analysis"] = image_analysis
    else:
        updates["image_analysis"] = ""

    # 步骤2：检索长期记忆（容错：嵌入模型未就绪时跳过）
    try:
        memories = retrieve_long_term_memories(
            user_question,
            user_id=None,
            top_k=Config.LONG_TERM_TOP_K,
        )
        lt_context = format_memories_context(memories)
        updates["long_term_memories"] = lt_context
        if lt_context:
            logger.info("长期记忆: 检索到 %d 条相关记忆", len(memories))
    except Exception as e:
        updates["long_term_memories"] = ""
        logger.warning("长期记忆暂不可用: %s", e)

    # 步骤3：检索RAG文档（容错：嵌入模型未就绪时跳过）
    try:
        rag_context = retrieve_rag_context(user_question, top_k=3)
        updates["rag_context"] = rag_context
        if rag_context:
            logger.info("RAG: 检索到相关文档片段")
    except Exception as e:
        updates["rag_context"] = ""
        logger.warning("RAG暂不可用: %s", e)

    return updates


# ============================================================
# 节点2：调度主管节点
# ============================================================

def supervisor_node(state: AgentState) -> dict:
    """
    调度主管节点：判断处理方式（SEARCH / RAG / DIRECT）。
    """
    user_question = state["user_question"]
    messages = state.get("messages", [])
    history_context = _extract_history_context(messages, user_question)
    t0 = time.time()
    action = supervisor_decide(user_question, history_context)
    _record_llm_duration("supervisor", time.time() - t0)
    _record_route(action)
    logger.info(
        "调度主管: 路由决策=%s（历史: %s）",
        action, "有" if history_context else "无",
    )
    return {"action": action}


# ============================================================
# 节点3：搜索Agent节点
# ============================================================

def search_node(state: AgentState) -> dict:
    """搜索Agent节点：执行Tavily联网搜索。"""
    user_question = state["user_question"]
    logger.info("搜索Agent: 正在执行联网搜索...")
    t0 = time.time()
    results = search_web(user_question)
    _record_llm_duration("search", time.time() - t0)
    logger.info("搜索Agent: 搜索完成（%d字符）", len(results))
    return {"search_results": results}


# ============================================================
# 节点3b：RAG检索节点
# ============================================================

def rag_node(state: AgentState) -> dict:
    """
    RAG检索节点：当supervisor判断需要文档检索时，
    确保 RAG 上下文被加载。
    """
    user_question = state["user_question"]
    existing_rag = state.get("rag_context", "")
    if existing_rag:
        logger.info("RAG节点: 已有RAG上下文，跳过重复检索")
        return {}
    try:
        rag_context = retrieve_rag_context(user_question, top_k=5)
        logger.info("RAG节点: 增强检索完成（%d字符）", len(rag_context))
        return {"rag_context": rag_context}
    except Exception as e:
        logger.warning("RAG节点: 检索失败: %s", e)
        return {}


# ============================================================
# 节点4：回答Agent节点
# ============================================================

def answer_node(state: AgentState) -> dict:
    """
    回答Agent节点：综合所有上下文生成最终回答。
    """
    user_question = state["user_question"]
    messages = state.get("messages", [])
    history_context = _extract_history_context(messages, user_question)
    search_results = state.get("search_results", "")
    rag_context = state.get("rag_context", "")
    long_term_memories = state.get("long_term_memories", "")
    image_analysis = state.get("image_analysis", "")

    logger.info(
        "回答Agent: 生成回答中（搜索:%s RAG:%s 图片:%s 记忆:%s）",
        bool(search_results), bool(rag_context),
        bool(image_analysis), bool(long_term_memories),
    )

    t0 = time.time()
    answer = generate_answer(
        user_question=user_question,
        search_results=search_results,
        rag_context=rag_context,
        long_term_memories=long_term_memories,
        image_analysis=image_analysis,
        history_context=history_context,
    )
    _record_llm_duration("answer", time.time() - t0)
    return {"messages": [AIMessage(content=answer)]}


# ============================================================
# 节点5：记忆存储节点
# ============================================================

def store_memory_node(state: AgentState) -> dict:
    """
    记忆存储节点：将本轮对话存入长期记忆向量库 + SQLite 消息表。
    """
    messages = state.get("messages", [])
    user_question = state["user_question"]
    thread_id = state.get("thread_id", "")

    # 提取最后一轮的回答
    answer_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            answer_text = msg.content
            break

    if answer_text:
        # 存入长期记忆（ChromaDB）
        store_conversation_turn(
            user_id=thread_id or "default",
            question=user_question,
            answer=answer_text,
        )
        logger.info("记忆存储: 已存入长期记忆")

    return {}


# ============================================================
# 条件路由
# ============================================================

def route_after_supervisor(
    state: AgentState,
) -> Literal["search", "rag", "answer"]:
    """根据主管决策路由到搜索、RAG检索或直接回答。"""
    action = state.get("action", "DIRECT")
    if action == "SEARCH":
        return "search"
    if action == "RAG":
        return "rag"
    return "answer"


# ============================================================
# 全局 Checkpointer + Graph 单例缓存
# ============================================================

_checkpointer = MemorySaver()
_compiled_graph = None  # 缓存编译后的 Graph


def build_graph():
    """
    构建并编译多智能体工作流图（带单例缓存）。

    工作流：
        START → preprocess → supervisor
                              ├─ SEARCH → search → answer
                              ├─ RAG    → rag    → answer
                              └─ DIRECT → answer
                            answer → store_memory → END
    """
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    _init_metrics()

    workflow = StateGraph(AgentState)

    # 注册6个节点
    workflow.add_node("preprocess", preprocess_node)     # 预处理
    workflow.add_node("supervisor", supervisor_node)     # 调度主管
    workflow.add_node("search", search_node)             # 搜索Agent
    workflow.add_node("rag", rag_node)                   # RAG检索Agent
    workflow.add_node("answer", answer_node)             # 回答Agent
    workflow.add_node("store_memory", store_memory_node) # 记忆存储

    # 设置入口
    workflow.set_entry_point("preprocess")

    # preprocess → supervisor
    workflow.add_edge("preprocess", "supervisor")

    # supervisor 条件路由
    workflow.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"search": "search", "rag": "rag", "answer": "answer"},
    )

    # search → answer
    workflow.add_edge("search", "answer")

    # rag → answer
    workflow.add_edge("rag", "answer")

    # answer → store_memory → END
    workflow.add_edge("answer", "store_memory")
    workflow.add_edge("store_memory", END)

    _compiled_graph = workflow.compile(checkpointer=_checkpointer)
    logger.info("LangGraph 工作流已编译并缓存")
    return _compiled_graph


# ============================================================
# 同步运行入口
# ============================================================

def run_agent(
    user_question: str,
    thread_id: str = "default",
    image_path: str = "",
    is_first_turn: bool = False,
    user_id: int = 0,
) -> str:
    """
    执行多智能体工作流。

    Args:
        user_question: 用户问题
        thread_id: 会话ID
        image_path: 上传图片路径（可选）
        is_first_turn: 是否本轮会话第一条消息
        user_id: 当前用户 ID

    Returns:
        str: 最终回答
    """
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    input_state = {
        "messages": [HumanMessage(content=user_question)],
        "user_question": user_question,
        "image_path": image_path,
        "is_first_turn": is_first_turn,
        "user_id": user_id,
    }
    final_state = graph.invoke(input_state, config)

    # 提取最终回答
    final_messages = final_state["messages"]
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage):
            return msg.content
    return "无法生成回答。"


# ============================================================
# 异步流式运行入口（SSE 支持）
# ============================================================

async def run_agent_stream(
    user_question: str,
    thread_id: str = "default",
    image_path: str = "",
    is_first_turn: bool = False,
    user_id: int = 0,
) -> AsyncGenerator[str, None]:
    """
    异步流式执行多智能体工作流，逐 token 产出回答。

    使用 LangGraph 的 astream_events 接口，在回答节点
    实时产出文本 token，供 SSE 推送给前端。

    Yields:
        str: JSON 格式的 SSE 事件数据
    """
    import json as _json

    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    input_state = {
        "messages": [HumanMessage(content=user_question)],
        "user_question": user_question,
        "image_path": image_path,
        "is_first_turn": is_first_turn,
        "user_id": user_id,
    }

    answer_text = ""

    try:
        async for event in graph.astream_events(input_state, config, version="v2"):
            kind = event.get("event")

            # 节点开始/结束：推送状态信息
            if kind == "on_chain_start" and event.get("name") in (
                "preprocess", "supervisor", "search", "rag", "answer", "store_memory"
            ):
                node_name = event["name"]
                yield f"data: {_json.dumps({'type': 'status', 'node': node_name}, ensure_ascii=False)}\n\n"

            # LLM 流式 token：推送文本增量
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    answer_text += token
                    yield f"data: {_json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

        # 流结束：保存会话元数据（异步）
        try:
            if is_first_turn:
                title = user_question[:30] + ("..." if len(user_question) > 30 else "")
                await create_conversation(thread_id, user_id, title)
            else:
                await update_conversation_time(thread_id)

            # 保存消息到 SQLite
            await add_message(thread_id, "user", user_question)
            if answer_text:
                await add_message(thread_id, "assistant", answer_text)
        except Exception as db_err:
            logger.warning("数据库保存失败（不影响回答）: %s", db_err)

        # 推送完成信号
        yield f"data: {_json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    except Exception as e:
        logger.error("流式执行失败: %s", e, exc_info=True)
        yield f"data: {_json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
