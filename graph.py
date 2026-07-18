"""
LangGraph工作流编排模块：完整的6节点工作流 + Prometheus 监控指标。
START → preprocess(视觉) → supervisor(路由) → [search|rag|direct] → answer → store_memory → END

改进：
- 编译后的 Graph 使用单例缓存，避免每次请求重建
- 修复 RAG 路由分支（supervisor 输出 RAG 时正确路由到 rag_node）
- 所有 print 替换为 logging
- 新增 astream 流式运行方法
- Prometheus 业务指标埋点
"""

# 导入os模块，用于文件路径检查
import os
# 导入time模块，用于计时
import time
# 导入asyncio模块，用于异步操作
import asyncio
# 导入类型提示模块
from typing import TypedDict, Annotated, Literal, Optional, AsyncGenerator
# 从langgraph.graph导入StateGraph和END，用于构建状态图
from langgraph.graph import StateGraph, END
# 从langgraph.graph.message导入add_messages，用于消息累积
from langgraph.graph.message import add_messages
# 从langgraph.checkpoint.memory导入MemorySaver，用于内存检查点
from langgraph.checkpoint.memory import MemorySaver
# 从langchain_core.messages导入消息类型
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# 导入配置模块
from config import Config
# 导入日志设置函数
from logger import setup_logger
# 导入智能体函数
from agents import (
    supervisor_decide, search_web, analyze_image, generate_answer,
)
# 导入记忆相关函数
from memory import (
    retrieve_long_term_memories, format_memories_context,
    retrieve_rag_context, store_conversation_turn,
)
# 导入数据库操作函数
from database import (
    create_conversation, update_conversation_time, add_message,
)

# 初始化日志记录器
logger = setup_logger("graph", Config.LOG_LEVEL, Config.LOG_FILE)

# ============================================================
# Prometheus 业务指标（延迟导入，避免循环依赖）
# ============================================================

# 智能体请求总数计数器
_agent_requests_total = None
# LLM响应耗时直方图
_llm_response_duration = None
# RAG切片存储总数计数器
_rag_chunks_total = None


def _init_metrics():
    """初始化 Prometheus 自定义指标（幂等）。"""
    # 声明使用全局变量
    global _agent_requests_total, _llm_response_duration, _rag_chunks_total
    # 如果已初始化，直接返回
    if _agent_requests_total is not None:
        return
    try:
        # 从prometheus_client导入Counter和Histogram
        from prometheus_client import Counter, Histogram
        # 创建路由请求计数器，按route_type标签区分
        _agent_requests_total = Counter(
            "agent_requests_total",
            "Total agent routing decisions",
            ["route_type"],
        )
        # 创建LLM耗时直方图，按agent_name标签区分，定义分桶
        _llm_response_duration = Histogram(
            "llm_response_duration_seconds",
            "LLM call duration in seconds",
            ["agent_name"],
            buckets=[0.5, 1, 2, 5, 10, 30, 60],
        )
        # 创建RAG切片计数器
        _rag_chunks_total = Counter(
            "rag_chunks_stored_total",
            "Total RAG document chunks stored",
        )
    except ImportError:
        # 如果prometheus_client未安装，记录警告
        logger.warning("prometheus_client 未安装，业务指标不可用")


def _record_route(route_type: str):
    """记录一次路由决策"""
    # 如果指标已初始化，递增计数器
    if _agent_requests_total:
        _agent_requests_total.labels(route_type=route_type).inc()


def _record_llm_duration(agent_name: str, duration: float):
    """记录LLM调用耗时"""
    # 如果指标已初始化，记录耗时
    if _llm_response_duration:
        _llm_response_duration.labels(agent_name=agent_name).observe(duration)


def _record_rag_chunks(count: int):
    """记录RAG切片存储数量"""
    # 如果指标已初始化且count>0，递增计数器
    if _rag_chunks_total and count > 0:
        _rag_chunks_total.inc(count)


# ============================================================
# 状态定义
# ============================================================

class AgentState(TypedDict):
    """多智能体工作流状态。"""
    # 对话历史消息列表，使用add_messages reducer自动累积
    messages: Annotated[list, add_messages]
    # 当前用户问题
    user_question: str
    # 主管路由决策: SEARCH/RAG/DIRECT
    action: str
    # 上传图片路径（空字符串表示无图片）
    image_path: str
    # 视觉分析结果
    image_analysis: str
    # 搜索结果
    search_results: str
    # RAG检索结果
    rag_context: str
    # 长期记忆检索结果
    long_term_memories: str
    # 是否本轮对话的第一条消息
    is_first_turn: bool
    # 当前用户ID
    user_id: int


# ============================================================
# 辅助函数：从消息历史中提取对话上下文
# ============================================================

def _extract_history_context(messages: list, current_question: str) -> str:
    """从消息列表中提取对话历史摘要（短期记忆）。"""
    # 初始化截止索引为-1
    cutoff_idx = -1
    # 从后向前遍历消息列表，找到当前问题对应的HumanMessage位置
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        # 找到匹配当前问题的HumanMessage
        if isinstance(msg, HumanMessage) and msg.content == current_question:
            cutoff_idx = i
            break
    # 截取截止索引之前的消息作为历史
    history_msgs = messages[:cutoff_idx] if cutoff_idx > 0 else []
    # 限制历史消息数量：最近N轮对话*2（用户+助手）
    max_msgs = Config.MAX_HISTORY_TURNS * 2
    # 只保留最近的max_msgs条消息
    history_msgs = history_msgs[-max_msgs:]
    # 如果没有历史消息，返回空字符串
    if not history_msgs:
        return ""
    # 格式化历史消息
    lines = []
    for msg in history_msgs:
        # 判断角色：用户或助手
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        # 内容截断到200字符，超出加...
        content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
        lines.append(f"{role}: {content}")
    # 用换行连接并返回
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
    # 从状态中获取用户问题
    user_question = state["user_question"]
    # 从状态中获取图片路径
    image_path = state.get("image_path", "")
    # 初始化更新字典
    updates = {}

    # 步骤1：图片识别
    if image_path and os.path.exists(image_path):
        # 记录日志：正在分析图片
        logger.info("视觉Agent: 正在分析图片...")
        # 记录开始时间
        t0 = time.time()
        # 调用视觉Agent分析图片
        image_analysis = analyze_image(image_path, user_question)
        # 记录LLM耗时
        _record_llm_duration("vision", time.time() - t0)
        # 记录日志：分析完成
        logger.info("视觉Agent: 分析完成（%d字符）", len(image_analysis))
        # 将图片分析结果存入更新字典
        updates["image_analysis"] = image_analysis
    else:
        # 无图片，设置为空字符串
        updates["image_analysis"] = ""

    # 步骤2：检索长期记忆（容错：嵌入模型未就绪时跳过）
    try:
        # 检索长期记忆
        memories = retrieve_long_term_memories(
            user_question,
            user_id=None,
            top_k=Config.LONG_TERM_TOP_K,
        )
        # 格式化记忆上下文
        lt_context = format_memories_context(memories)
        # 存入更新字典
        updates["long_term_memories"] = lt_context
        # 如果有记忆，记录日志
        if lt_context:
            logger.info("长期记忆: 检索到 %d 条相关记忆", len(memories))
    except Exception as e:
        # 检索失败，设置为空字符串
        updates["long_term_memories"] = ""
        # 记录警告日志
        logger.warning("长期记忆暂不可用: %s", e)

    # 步骤3：检索RAG文档（容错：嵌入模型未就绪时跳过）
    try:
        # 检索RAG上下文
        rag_context = retrieve_rag_context(user_question, top_k=3)
        # 存入更新字典
        updates["rag_context"] = rag_context
        # 如果有RAG结果，记录日志
        if rag_context:
            logger.info("RAG: 检索到相关文档片段")
    except Exception as e:
        # 检索失败，设置为空字符串
        updates["rag_context"] = ""
        # 记录警告日志
        logger.warning("RAG暂不可用: %s", e)

    # 返回状态更新
    return updates


# ============================================================
# 节点2：调度主管节点
# ============================================================

def supervisor_node(state: AgentState) -> dict:
    """
    调度主管节点：判断处理方式（SEARCH / RAG / DIRECT）。
    """
    # 从状态中获取用户问题
    user_question = state["user_question"]
    # 从状态中获取消息历史
    messages = state.get("messages", [])
    # 提取对话历史上下文
    history_context = _extract_history_context(messages, user_question)
    # 记录开始时间
    t0 = time.time()
    # 调用调度主管做决策
    action = supervisor_decide(user_question, history_context)
    # 记录LLM耗时
    _record_llm_duration("supervisor", time.time() - t0)
    # 记录路由决策指标
    _record_route(action)
    # 记录日志
    logger.info(
        "调度主管: 路由决策=%s（历史: %s）",
        action, "有" if history_context else "无",
    )
    # 返回动作决策
    return {"action": action}


# ============================================================
# 节点3：搜索Agent节点
# ============================================================

def search_node(state: AgentState) -> dict:
    """搜索Agent节点：执行Tavily联网搜索。"""
    # 从状态中获取用户问题
    user_question = state["user_question"]
    # 记录日志：正在搜索
    logger.info("搜索Agent: 正在执行联网搜索...")
    # 记录开始时间
    t0 = time.time()
    # 调用搜索Agent执行搜索
    results = search_web(user_question)
    # 记录LLM耗时
    _record_llm_duration("search", time.time() - t0)
    # 记录日志：搜索完成
    logger.info("搜索Agent: 搜索完成（%d字符）", len(results))
    # 返回搜索结果
    return {"search_results": results}


# ============================================================
# 节点3b：RAG检索节点
# ============================================================

def rag_node(state: AgentState) -> dict:
    """
    RAG检索节点：当supervisor判断需要文档检索时，
    确保 RAG 上下文被加载。
    """
    # 从状态中获取用户问题
    user_question = state["user_question"]
    # 获取已有的RAG上下文
    existing_rag = state.get("rag_context", "")
    # 如果已有RAG上下文，跳过重复检索
    if existing_rag:
        logger.info("RAG节点: 已有RAG上下文，跳过重复检索")
        return {}
    try:
        # 增强检索（top_k=5，比预处理时更多）
        rag_context = retrieve_rag_context(user_question, top_k=5)
        # 记录日志
        logger.info("RAG节点: 增强检索完成（%d字符）", len(rag_context))
        # 返回RAG上下文
        return {"rag_context": rag_context}
    except Exception as e:
        # 检索失败，记录警告并返回空
        logger.warning("RAG节点: 检索失败: %s", e)
        return {}


# ============================================================
# 节点4：回答Agent节点
# ============================================================

def answer_node(state: AgentState) -> dict:
    """
    回答Agent节点：综合所有上下文生成最终回答。
    """
    # 从状态中获取用户问题
    user_question = state["user_question"]
    # 从状态中获取消息历史
    messages = state.get("messages", [])
    # 提取对话历史上下文
    history_context = _extract_history_context(messages, user_question)
    # 获取搜索结果
    search_results = state.get("search_results", "")
    # 获取RAG上下文
    rag_context = state.get("rag_context", "")
    # 获取长期记忆
    long_term_memories = state.get("long_term_memories", "")
    # 获取图片分析结果
    image_analysis = state.get("image_analysis", "")

    # 记录日志：生成回答中
    logger.info(
        "回答Agent: 生成回答中（搜索:%s RAG:%s 图片:%s 记忆:%s）",
        bool(search_results), bool(rag_context),
        bool(image_analysis), bool(long_term_memories),
    )

    # 记录开始时间
    t0 = time.time()
    # 调用回答Agent生成回答
    answer = generate_answer(
        user_question=user_question,
        search_results=search_results,
        rag_context=rag_context,
        long_term_memories=long_term_memories,
        image_analysis=image_analysis,
        history_context=history_context,
    )
    # 记录LLM耗时
    _record_llm_duration("answer", time.time() - t0)
    # 返回AI消息
    return {"messages": [AIMessage(content=answer)]}


# ============================================================
# 节点5：记忆存储节点
# ============================================================

def store_memory_node(state: AgentState) -> dict:
    """
    记忆存储节点：将本轮对话存入长期记忆向量库 + SQLite 消息表。
    """
    # 从状态中获取消息列表
    messages = state.get("messages", [])
    # 获取用户问题
    user_question = state["user_question"]
    # 获取会话ID
    thread_id = state.get("thread_id", "")

    # 提取最后一轮的回答（从后向前找最后一条AIMessage）
    answer_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            answer_text = msg.content
            break

    # 如果有回答文本，存入长期记忆
    if answer_text:
        # 存入长期记忆（ChromaDB）
        store_conversation_turn(
            user_id=thread_id or "default",
            question=user_question,
            answer=answer_text,
        )
        # 记录日志
        logger.info("记忆存储: 已存入长期记忆")

    # 返回空（无状态更新）
    return {}


# ============================================================
# 条件路由
# ============================================================

def route_after_supervisor(
    state: AgentState,
) -> Literal["search", "rag", "answer"]:
    """根据主管决策路由到搜索、RAG检索或直接回答。"""
    # 从状态中获取动作决策
    action = state.get("action", "DIRECT")
    # SEARCH路由到search节点
    if action == "SEARCH":
        return "search"
    # RAG路由到rag节点
    if action == "RAG":
        return "rag"
    # 默认路由到answer节点（DIRECT）
    return "answer"


# ============================================================
# 全局 Checkpointer + Graph 单例缓存
# ============================================================

# 创建内存检查点保存器
_checkpointer = MemorySaver()
# 编译后的图缓存（单例）
_compiled_graph = None


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
    # 声明使用全局变量
    global _compiled_graph
    # 如果已编译，直接返回缓存的图
    if _compiled_graph is not None:
        return _compiled_graph

    # 初始化Prometheus指标
    _init_metrics()

    # 创建状态图，传入AgentState类型
    workflow = StateGraph(AgentState)

    # 注册6个节点
    workflow.add_node("preprocess", preprocess_node)     # 预处理节点
    workflow.add_node("supervisor", supervisor_node)     # 调度主管节点
    workflow.add_node("search", search_node)             # 搜索Agent节点
    workflow.add_node("rag", rag_node)                   # RAG检索Agent节点
    workflow.add_node("answer", answer_node)             # 回答Agent节点
    workflow.add_node("store_memory", store_memory_node) # 记忆存储节点

    # 设置入口点为preprocess
    workflow.set_entry_point("preprocess")

    # 添加边：preprocess → supervisor
    workflow.add_edge("preprocess", "supervisor")

    # 添加条件边：supervisor根据决策路由到不同节点
    workflow.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"search": "search", "rag": "rag", "answer": "answer"},
    )

    # 添加边：search → answer
    workflow.add_edge("search", "answer")

    # 添加边：rag → answer
    workflow.add_edge("rag", "answer")

    # 添加边：answer → store_memory → END
    workflow.add_edge("answer", "store_memory")
    workflow.add_edge("store_memory", END)

    # 编译工作流，使用内存检查点
    _compiled_graph = workflow.compile(checkpointer=_checkpointer)
    # 记录日志
    logger.info("LangGraph 工作流已编译并缓存")
    # 返回编译后的图
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
    # 构建并获取编译后的图
    graph = build_graph()
    # 构建配置，包含thread_id用于检查点
    config = {"configurable": {"thread_id": thread_id}}
    # 构建初始输入状态
    input_state = {
        "messages": [HumanMessage(content=user_question)],
        "user_question": user_question,
        "image_path": image_path,
        "is_first_turn": is_first_turn,
        "user_id": user_id,
    }
    # 同步调用图执行
    final_state = graph.invoke(input_state, config)

    # 从最终状态中提取最后一条AI消息作为回答
    final_messages = final_state["messages"]
    # 从后向前遍历消息
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage):
            return msg.content
    # 如果没有AI消息，返回错误提示
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
    异步流式执行多智能体工作流，产出回答。

    手动执行工作流各节点，在回答节点使用真正的 LLM 流式调用。
    在搜索节点显示"联网搜索中"。

    Yields:
        str: JSON 格式的 SSE 事件数据
    """
    # 导入json模块（延迟导入）
    import json as _json
    # 导入流式回答生成函数
    from agents import generate_answer_stream

    # 初始化最终回答文本
    answer_text = ""

    try:
        # 步骤1：预处理节点（图片识别 + 长期记忆 + RAG）
        yield f"data: {_json.dumps({'type': 'status', 'node': 'preprocess'}, ensure_ascii=False)}\n\n"
        # 构建预处理节点状态
        preprocess_state = {
            "user_question": user_question,
            "image_path": image_path,
            "messages": [],
        }
        # 执行预处理节点
        preprocess_result = preprocess_node(preprocess_state)
        # 获取图片分析结果
        image_analysis = preprocess_result.get("image_analysis", "")
        # 获取长期记忆
        long_term_memories = preprocess_result.get("long_term_memories", "")
        # 获取RAG上下文
        rag_context = preprocess_result.get("rag_context", "")

        # 步骤2：调度主管节点
        yield f"data: {_json.dumps({'type': 'status', 'node': 'supervisor'}, ensure_ascii=False)}\n\n"
        # 构建调度主管节点状态
        supervisor_state = {
            "user_question": user_question,
            "messages": [HumanMessage(content=user_question)],
        }
        # 执行调度主管节点
        supervisor_result = supervisor_node(supervisor_state)
        # 获取路由决策
        action = supervisor_result.get("action", "DIRECT")

        # 步骤3：根据路由执行搜索或RAG
        search_results = ""
        if action == "SEARCH":
            # 搜索路径：推送search状态
            yield f"data: {_json.dumps({'type': 'status', 'node': 'search'}, ensure_ascii=False)}\n\n"
            # 推送"联网搜索中"提示token
            yield f"data: {_json.dumps({'type': 'token', 'content': '联网搜索中'}, ensure_ascii=False)}\n\n"
            # 执行搜索节点
            search_state = {"user_question": user_question}
            search_result = search_node(search_state)
            search_results = search_result.get("search_results", "")
        elif action == "RAG":
            # RAG路径：推送rag状态
            yield f"data: {_json.dumps({'type': 'status', 'node': 'rag'}, ensure_ascii=False)}\n\n"
            # 执行RAG节点
            rag_state = {"user_question": user_question, "rag_context": rag_context}
            rag_result = rag_node(rag_state)
            rag_context = rag_result.get("rag_context", rag_context)

        # 步骤4：回答节点（流式输出）
        yield f"data: {_json.dumps({'type': 'status', 'node': 'answer'}, ensure_ascii=False)}\n\n"

        # 提取对话历史（流式模式下简化处理，暂不提取历史）
        history_context = ""

        # 使用流式LLM调用，解析thinking和answer标签
        # 状态标记：是否在thinking标签内
        in_thinking = False
        # 状态标记：是否在answer标签内
        in_answer = False
        # 内容缓冲区
        buffer = ""
        # 标签缓冲区（用于累积可能的不完整标签）
        tag_buffer = ""

        # 异步迭代流式LLM输出
        async for token in generate_answer_stream(
            user_question=user_question,
            search_results=search_results,
            rag_context=rag_context,
            long_term_memories=long_term_memories,
            image_analysis=image_analysis,
            history_context=history_context,
        ):
            # 将token添加到缓冲区
            buffer += token

            # 检查是否有标签开始
            if "<" in buffer and not in_thinking and not in_answer:
                # 检查是否是<thinking>标签
                if "<thinking>" in buffer:
                    in_thinking = True
                    buffer = buffer.replace("<thinking>", "", 1)
                    continue
                # 检查是否是<answer>标签
                elif "<answer>" in buffer:
                    in_answer = True
                    buffer = buffer.replace("<answer>", "", 1)
                    continue
                # 检查是否是不完整的开始标签前缀，缓冲等待
                elif buffer.endswith("<") or buffer.endswith("<t") or buffer.endswith("<th") or \
                     buffer.endswith("<thi") or buffer.endswith("<thin") or buffer.endswith("<think") or \
                     buffer.endswith("<thinki") or buffer.endswith("<thinkin") or buffer.endswith("<thinking") or \
                     buffer.endswith("<a") or buffer.endswith("<an") or buffer.endswith("<ans") or \
                     buffer.endswith("<answ") or buffer.endswith("<answe") or buffer.endswith("<answer"):
                    # 不完整标签，继续累积
                    continue

            # 检查是否有</thinking>结束标签
            if "</thinking>" in buffer and in_thinking:
                parts = buffer.split("</thinking>", 1)
                # 如果结束标签前有内容，推送thinking事件
                if parts[0].strip():
                    yield f"data: {_json.dumps({'type': 'thinking', 'content': parts[0]}, ensure_ascii=False)}\n\n"
                # 保留剩余内容到缓冲区
                buffer = parts[1] if len(parts) > 1 else ""
                # 退出thinking状态
                in_thinking = False
                continue
            # 检查是否有</answer>结束标签
            elif "</answer>" in buffer and in_answer:
                parts = buffer.split("</answer>", 1)
                # 如果结束标签前有内容，推送token事件
                if parts[0].strip():
                    yield f"data: {_json.dumps({'type': 'token', 'content': parts[0]}, ensure_ascii=False)}\n\n"
                    answer_text += parts[0]
                # 保留剩余内容
                buffer = parts[1] if len(parts) > 1 else ""
                # 退出answer状态
                in_answer = False
                continue

            # 检查是否有不完整的</thinking>结束标签前缀
            if in_thinking and (buffer.endswith("</") or buffer.endswith("</t") or buffer.endswith("</th") or \
               buffer.endswith("</thi") or buffer.endswith("</thin") or buffer.endswith("</think") or \
               buffer.endswith("</thinki") or buffer.endswith("</thinkin") or buffer.endswith("</thinking")):
                continue
            # 检查是否有不完整的</answer>结束标签前缀
            elif in_answer and (buffer.endswith("</") or buffer.endswith("</a") or buffer.endswith("</an") or \
               buffer.endswith("</ans") or buffer.endswith("</answ") or buffer.endswith("</answe") or \
               buffer.endswith("</answer")):
                continue

            # 推送缓冲区内容
            if buffer:
                if in_thinking:
                    # 在thinking状态下，推送thinking事件
                    yield f"data: {_json.dumps({'type': 'thinking', 'content': buffer}, ensure_ascii=False)}\n\n"
                elif in_answer or not buffer.startswith("<"):
                    # 在answer状态下，或内容不是标签开始，推送token事件
                    yield f"data: {_json.dumps({'type': 'token', 'content': buffer}, ensure_ascii=False)}\n\n"
                    answer_text += buffer
                # 清空缓冲区
                buffer = ""

        # 步骤5：记忆存储节点
        yield f"data: {_json.dumps({'type': 'status', 'node': 'store_memory'}, ensure_ascii=False)}\n\n"

        # 流结束：保存会话元数据（异步）
        try:
            if is_first_turn:
                # 首轮对话：创建新会话，标题为用户问题前30字符
                title = user_question[:30] + ("..." if len(user_question) > 30 else "")
                await create_conversation(thread_id, user_id, title)
            else:
                # 非首轮：更新会话最后活跃时间
                await update_conversation_time(thread_id)

            # 保存用户消息到SQLite
            await add_message(thread_id, "user", user_question)
            # 如果有回答，保存助手消息到SQLite
            if answer_text:
                await add_message(thread_id, "assistant", answer_text)
        except Exception as db_err:
            # 数据库保存失败不影响回答，只记录警告
            logger.warning("数据库保存失败（不影响回答）: %s", db_err)

        # 推送完成信号
        yield f"data: {_json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    except Exception as e:
        # 捕获所有异常，记录错误日志
        logger.error("流式执行失败: %s", e, exc_info=True)
        # 推送错误事件
        yield f"data: {_json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
