"""LangGraph 节点实现：全部异步，支持 Function Calling 与真流式。"""

import os
import time
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

from app.core.config import get_settings
from app.core.constants import RouteAction
from app.core.logging import setup_logger
from app.agents.llm import create_llm, supervisor_decide_cached
from app.agents.prompts import (
    ANSWER_SYSTEM_PROMPT,
    SEARCH_SYSTEM_PROMPT,
    SUPERVISOR_SYSTEM_PROMPT,
    VISION_SYSTEM_PROMPT,
)
from app.agents.runtime import get_vector_store
from app.agents.tools import AGENT_TOOLS
from app.memory.rag import format_memories_context

logger = setup_logger("agents.nodes")


# ============================================================
# 工作流状态定义
# ============================================================

class AgentState(TypedDict):
    """多智能体工作流状态。"""

    messages: Annotated[list, add_messages]
    user_question: str
    action: str
    image_path: str
    image_analysis: str
    search_results: str
    rag_context: str
    long_term_memories: str
    history_context: str
    is_first_turn: bool
    user_id: int


# ============================================================
# Prometheus 指标（可选）
# ============================================================

_agent_requests_total = None
_llm_response_duration = None


def _init_metrics() -> None:
    global _agent_requests_total, _llm_response_duration
    if _agent_requests_total is not None:
        return
    try:
        from prometheus_client import Counter, Histogram
        _agent_requests_total = Counter(
            "agent_requests_total", "Total agent routing decisions", ["route_type"]
        )
        _llm_response_duration = Histogram(
            "llm_response_duration_seconds", "LLM call duration in seconds",
            ["agent_name"], buckets=[0.5, 1, 2, 5, 10, 30, 60],
        )
    except ImportError:
        logger.warning("prometheus_client 未安装，业务指标不可用")


def _record_route(route_type: str) -> None:
    if _agent_requests_total:
        _agent_requests_total.labels(route_type=route_type).inc()


def _record_llm_duration(agent_name: str, duration: float) -> None:
    if _llm_response_duration:
        _llm_response_duration.labels(agent_name=agent_name).observe(duration)


_init_metrics()


# ============================================================
# 辅助：构建回答上下文
# ============================================================

def _build_answer_context(state: AgentState) -> str:
    """综合所有上下文构建回答 Agent 的用户消息。"""
    user_question = state["user_question"]
    context_parts = [f"用户问题：{user_question}"]

    history_context = state.get("history_context", "")
    if history_context:
        context_parts.insert(0, f"对话历史：\n{history_context}")

    image_analysis = state.get("image_analysis", "")
    if image_analysis:
        context_parts.append(f"\n[图片分析结果]\n{image_analysis}")

    search_results = state.get("search_results", "")
    if search_results:
        context_parts.append(f"\n[联网搜索结果]\n{search_results}")

    rag_context = state.get("rag_context", "")
    if rag_context:
        context_parts.append(f"\n{rag_context}")

    long_term_memories = state.get("long_term_memories", "")
    if long_term_memories:
        context_parts.append(f"\n{long_term_memories}")

    return "\n\n".join(context_parts)


# ============================================================
# 节点1：预处理（图片识别 + 长期记忆 + RAG 检索）
# ============================================================

async def preprocess_node(state: AgentState) -> dict:
    """预处理节点：图片视觉分析 + 长期记忆检索 + RAG 检索。"""
    user_question = state["user_question"]
    image_path = state.get("image_path", "")
    updates: dict = {}

    # 图片识别
    if image_path and os.path.exists(image_path):
        logger.info("视觉Agent: 正在分析图片...")
        t0 = time.time()
        updates["image_analysis"] = await _analyze_image(image_path, user_question)
        _record_llm_duration("vision", time.time() - t0)
    else:
        updates["image_analysis"] = ""

    store = get_vector_store()

    # 长期记忆检索（容错）
    try:
        memories = await store.retrieve_long_term_memories(
            user_question, user_id=None, top_k=get_settings().LONG_TERM_TOP_K
        )
        lt_context = format_memories_context(memories)
        updates["long_term_memories"] = lt_context
        if lt_context:
            logger.info("长期记忆: 检索到 %d 条相关记忆", len(memories))
    except Exception as e:
        updates["long_term_memories"] = ""
        logger.warning("长期记忆暂不可用: %s", e)

    # RAG 检索（容错）
    try:
        rag_context = await store.retrieve_rag_context(user_question, top_k=3)
        updates["rag_context"] = rag_context
        if rag_context:
            logger.info("RAG: 检索到相关文档片段")
    except Exception as e:
        updates["rag_context"] = ""
        logger.warning("RAG暂不可用: %s", e)

    return updates


async def _analyze_image(image_path: str, user_question: str) -> str:
    """视觉 Agent：使用本地 Ollama 多模态模型识别图片。"""
    import base64
    import ollama

    settings = get_settings()
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    prompt = VISION_SYSTEM_PROMPT
    if user_question:
        prompt = f"用户问题：{user_question}\n\n请根据图片内容回答用户的问题。"

    try:
        response = await ollama.AsyncClient(host=settings.OLLAMA_BASE_URL).chat(
            model=settings.OLLAMA_VISION_MODEL,
            messages=[{"role": "user", "content": prompt, "images": [image_data]}],
        )
        logger.info("视觉 Agent: 图片分析完成")
        return response["message"]["content"]
    except Exception as e:
        logger.error("视觉 Agent 失败：%s", e)
        return f"[视觉识别失败] 请确保 Ollama 服务已启动且已安装{settings.OLLAMA_VISION_MODEL}模型。错误：{str(e)}"


# ============================================================
# 节点2：调度主管（路由决策，带缓存）
# ============================================================

async def supervisor_node(state: AgentState) -> dict:
    """调度主管节点：判断处理方式（SEARCH / RAG / DIRECT）。"""
    user_question = state["user_question"]
    history_context = state.get("history_context", "")

    async def _decide(question: str, history: str) -> str:
        llm = create_llm(temperature=0.0)
        prompt = f"用户问题：{question}"
        if history:
            prompt = f"对话历史：\n{history}\n\n当前用户问题：{question}"
        response = await llm.ainvoke([
            SystemMessage(SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        result_text = response.content.strip().upper()
        if RouteAction.SEARCH in result_text:
            return RouteAction.SEARCH
        if RouteAction.RAG in result_text:
            return RouteAction.RAG
        return RouteAction.DIRECT

    t0 = time.time()
    action = await supervisor_decide_cached(user_question, history_context, _decide)
    _record_llm_duration("supervisor", time.time() - t0)
    _record_route(action)
    logger.info("调度主管: 路由决策=%s", action)
    return {"action": action}


# ============================================================
# 节点3：搜索 Agent
# ============================================================

async def search_node(state: AgentState) -> dict:
    """搜索 Agent 节点：执行 Tavily 联网搜索。"""
    user_question = state["user_question"]
    logger.info("搜索Agent: 正在执行联网搜索...")
    t0 = time.time()
    results = await _search_web(user_question)
    _record_llm_duration("search", time.time() - t0)
    logger.info("搜索Agent: 搜索完成（%d字符）", len(results))
    return {"search_results": results}


async def _search_web(user_question: str) -> str:
    """使用 Tavily 执行联网搜索，返回结构化摘要。"""
    from tavily import TavilyClient

    settings = get_settings()
    llm = create_llm(temperature=0.0)
    keyword_response = await llm.ainvoke([
        SystemMessage(SEARCH_SYSTEM_PROMPT),
        HumanMessage(content=f"请为以下问题提取搜索关键词：{user_question}"),
    ])
    search_query = keyword_response.content.strip().strip('"').strip("'")
    logger.debug("搜索关键词：%s", search_query)

    tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    search_response = tavily_client.search(
        query=search_query, search_depth="basic", max_results=3, include_answer=True
    )

    formatted_parts = []
    if search_response.get("answer"):
        formatted_parts.append(f"[AI 摘要] {search_response['answer']}")
    for i, result in enumerate(search_response.get("results", []), 1):
        title = result.get("title", "无标题")
        url = result.get("url", "")
        content = result.get("content", "无内容")
        content_short = content[:300] + "..." if len(content) > 300 else content
        formatted_parts.append(f"[结果{i}] {title}\n链接：{url}\n摘要：{content_short}")

    return "\n\n".join(formatted_parts) if formatted_parts else "未找到相关搜索结果。"


# ============================================================
# 节点3b：RAG 检索节点
# ============================================================

async def rag_node(state: AgentState) -> dict:
    """RAG 检索节点：确保 RAG 上下文被加载（增强检索）。"""
    user_question = state["user_question"]
    existing_rag = state.get("rag_context", "")
    if existing_rag:
        logger.info("RAG节点: 已有RAG上下文，跳过重复检索")
        return {}
    try:
        store = get_vector_store()
        rag_context = await store.retrieve_rag_context(user_question, top_k=5)
        logger.info("RAG节点: 增强检索完成（%d字符）", len(rag_context))
        return {"rag_context": rag_context}
    except Exception as e:
        logger.warning("RAG节点: 检索失败: %s", e)
        return {}


# ============================================================
# 节点4：回答 Agent（Function Calling + 真流式）
# ============================================================

async def answer_node(state: AgentState) -> dict:
    """
    回答 Agent 节点：综合所有上下文生成最终回答。

    - 绑定 Function Calling 工具（计算器、时间查询）
    - 使用 astream 实现真流式（供 astream_events 捕获 token）
    - 若模型调用工具，执行工具后进行第二轮生成
    """
    user_message = _build_answer_context(state)

    logger.info(
        "回答Agent: 生成回答中（搜索:%s RAG:%s 图片:%s 记忆:%s）",
        bool(state.get("search_results")), bool(state.get("rag_context")),
        bool(state.get("image_analysis")), bool(state.get("long_term_memories")),
    )

    t0 = time.time()
    answer = await _generate_with_tools(user_message)
    _record_llm_duration("answer", time.time() - t0)

    return {"messages": [AIMessage(content=answer)]}


async def _generate_with_tools(user_message: str) -> str:
    """带 Function Calling 的回答生成（最多一轮工具调用）。

    策略：绑定工具后流式生成。
    - 若模型直接回答：content 流式输出，无 tool_calls，单轮完成。
    - 若模型调用工具：首轮 content 为空（仅 tool_call），执行工具后
      将结果注入上下文进行第二轮生成。
    """
    llm = create_llm(temperature=0.3)
    llm_with_tools = llm.bind_tools(AGENT_TOOLS)

    messages = [
        SystemMessage(ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    # 第一轮：流式生成并累积完整消息（含 tool_calls）
    first_message = await _stream_full_message(llm_with_tools, messages)

    tool_calls = getattr(first_message, "tool_calls", None)
    if tool_calls:
        # 执行工具并注入结果，第二轮生成最终回答
        tool_results = _execute_tool_calls(tool_calls)
        if tool_results:
            enhanced_message = f"{user_message}\n\n[工具执行结果]\n{tool_results}"
            messages = [
                SystemMessage(ANSWER_SYSTEM_PROMPT),
                HumanMessage(content=enhanced_message),
            ]
            final_message = await _stream_full_message(llm, messages)
            return final_message.content

    return first_message.content


async def _stream_full_message(llm, messages: list) -> AIMessage:
    """流式调用 LLM 并累积为完整 AIMessage（供 astream_events 捕获 token）。"""
    full = None
    async for chunk in llm.astream(messages):
        full = chunk if full is None else full + chunk
    if full is None:
        return AIMessage(content="")
    return AIMessage(
        content=getattr(full, "content", ""),
        tool_calls=getattr(full, "tool_calls", None) or [],
    )


def _execute_tool_calls(tool_calls: list) -> str:
    """执行工具调用，返回结果文本。"""
    results = []
    tool_map = {t.name: t for t in AGENT_TOOLS}
    for call in tool_calls:
        tool_name = call.get("name", "")
        tool_args = call.get("args", {})
        tool = tool_map.get(tool_name)
        if tool:
            try:
                result = tool.invoke(tool_args)
                results.append(f"{tool_name}: {result}")
                logger.info("工具调用: %s(%s) -> %s", tool_name, tool_args, result)
            except Exception as e:
                logger.warning("工具 %s 执行失败: %s", tool_name, e)
    return "\n".join(results)


# ============================================================
# 节点5：记忆存储
# ============================================================

async def store_memory_node(state: AgentState) -> dict:
    """记忆存储节点：将本轮对话存入长期记忆向量库。"""
    messages = state.get("messages", [])
    user_question = state["user_question"]
    user_id = state.get("user_id", 0)

    answer_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            answer_text = msg.content
            break

    if answer_text:
        try:
            store = get_vector_store()
            await store.store_conversation_turn(
                user_id=str(user_id) if user_id else "default",
                question=user_question,
                answer=answer_text,
            )
            logger.info("记忆存储: 已存入长期记忆")
        except Exception as e:
            logger.warning("记忆存储失败（不影响回答）: %s", e)

    return {}


# ============================================================
# 条件路由
# ============================================================

def route_after_supervisor(state: AgentState) -> Literal["search", "rag", "answer"]:
    """根据主管决策路由到搜索、RAG 检索或直接回答。"""
    action = state.get("action", RouteAction.DIRECT)
    if action == RouteAction.SEARCH:
        return "search"
    if action == RouteAction.RAG:
        return "rag"
    return "answer"
