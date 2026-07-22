"""LangGraph 节点实现：全部异步，支持 Function Calling 与真流式。"""

import asyncio  # 导入异步IO模块，用于异步等待、超时控制和线程池调度
import os  # 导入操作系统模块，用于检查文件路径是否存在
import time  # 导入时间模块，用于记录LLM调用耗时
from typing import Annotated, Literal, TypedDict  # 从typing导入Annotated（带注解类型）、Literal（字面量类型）、TypedDict（类型化字典）

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # 导入LangChain核心消息类型：AI消息、人类消息、系统消息
from langgraph.graph.message import add_messages  # 导入LangGraph消息累加器函数，用于状态中消息列表的合并

from app.core.config import get_settings  # 导入配置获取函数，用于读取应用配置
from app.core.constants import RouteAction  # 导入路由动作常量类
from app.core.logging import setup_logger  # 导入日志设置函数，用于创建模块专用logger
from app.agents.llm import create_llm, supervisor_decide_cached  # 导入LLM创建函数和带缓存的路由决策函数
from app.agents.prompts import (  # 从提示词模块导入各智能体的系统提示词
    ANSWER_SYSTEM_PROMPT,  # 回答Agent系统提示词
    SEARCH_SYSTEM_PROMPT,  # 搜索Agent系统提示词
    SUPERVISOR_SYSTEM_PROMPT,  # 调度主管系统提示词
    VISION_SYSTEM_PROMPT,  # 视觉Agent系统提示词
)
from app.agents.runtime import get_vector_store  # 导入向量存储获取函数，用于访问共享向量存储
from app.agents.tools import AGENT_TOOLS  # 导入Agent工具列表，供回答Agent通过Function Calling调用
from app.memory.rag import format_memories_context  # 导入记忆格式化函数，将检索到的记忆格式化为上下文文本

logger = setup_logger("agents.nodes")  # 创建本模块专用的日志记录器，名称为agents.nodes


# ============================================================
# 工作流状态定义
# ============================================================

class AgentState(TypedDict):  # 定义工作流状态类型，继承自TypedDict
    """多智能体工作流状态。"""

    messages: Annotated[list, add_messages]  # 消息列表，使用add_messages注解实现消息累加合并
    user_question: str  # 用户问题文本
    action: str  # 调度主管的路由决策动作
    image_path: str  # 用户上传的图片路径
    image_analysis: str  # 视觉Agent对图片的分析结果
    search_results: str  # 联网搜索返回的结果
    rag_context: str  # RAG检索到的文档上下文
    long_term_memories: str  # 长期记忆检索结果
    history_context: str  # 对话历史上下文
    is_first_turn: bool  # 是否为首次对话标志
    user_id: int  # 用户ID


# ============================================================
# Prometheus 指标（可选）
# ============================================================

_agent_requests_total = None  # Agent请求总数计数器，初始为None
_llm_response_duration = None  # LLM响应耗时直方图，初始为None
_circuit_breaker_state = None  # 熔断器状态Gauge指标，初始为None


def _init_metrics() -> None:  # 定义初始化Prometheus指标的私有函数
    global _agent_requests_total, _llm_response_duration, _circuit_breaker_state  # 声明使用全局变量
    if _agent_requests_total is not None:  # 如果计数器已初始化
        return  # 直接返回，避免重复初始化
    try:  # 开始异常捕获块
        from prometheus_client import Counter, Gauge, Histogram  # 尝试导入Prometheus客户端的Counter、Gauge和Histogram
        _agent_requests_total = Counter(  # 创建请求总数计数器
            "agent_requests_total", "Total agent routing decisions", ["route_type"]  # 指标名、描述、标签（路由类型）
        )
        _llm_response_duration = Histogram(  # 创建LLM响应耗时直方图
            "llm_response_duration_seconds", "LLM call duration in seconds",  # 指标名和描述
            ["agent_name"], buckets=[0.5, 1, 2, 5, 10, 30, 60],  # 标签（Agent名）和分桶区间
        )
        _circuit_breaker_state = Gauge(  # 创建熔断器状态Gauge指标
            "circuit_breaker_state",  # 指标名
            "Circuit breaker state (0=closed, 1=half-open, 2=open)",  # 指标描述，0=关闭，1=半开，2=打开
        )  # Gauge创建完毕
    except ImportError:  # 捕获导入失败异常
        logger.warning("prometheus_client 未安装，业务指标不可用")  # 记录警告日志


def _record_route(route_type: str) -> None:  # 定义记录路由指标的私有函数
    if _agent_requests_total:  # 如果计数器已初始化
        _agent_requests_total.labels(route_type=route_type).inc()  # 按路由类型标签递增计数


def _record_llm_duration(agent_name: str, duration: float) -> None:  # 定义记录LLM耗时的私有函数
    if _llm_response_duration:  # 如果直方图已初始化
        _llm_response_duration.labels(agent_name=agent_name).observe(duration)  # 按Agent名标签记录耗时观测值


_init_metrics()  # 模块加载时初始化Prometheus指标


# ============================================================
# 辅助：构建回答上下文
# ============================================================

def _build_answer_context(state: AgentState) -> str:  # 定义构建回答上下文的私有函数
    """综合所有上下文构建回答 Agent 的用户消息。"""
    user_question = state["user_question"]  # 获取用户问题
    context_parts = [f"用户问题：{user_question}"]  # 上下文片段列表，首项为用户问题

    history_context = state.get("history_context", "")  # 获取对话历史上下文
    if history_context:  # 如果存在历史上下文
        context_parts.insert(0, f"对话历史：\n{history_context}")  # 将历史上下文插入到列表开头

    image_analysis = state.get("image_analysis", "")  # 获取图片分析结果
    if image_analysis:  # 如果存在图片分析
        context_parts.append(f"\n[图片分析结果]\n{image_analysis}")  # 追加图片分析结果片段

    search_results = state.get("search_results", "")  # 获取搜索结果
    if search_results:  # 如果存在搜索结果
        context_parts.append(f"\n[联网搜索结果]\n{search_results}")  # 追加搜索结果片段

    rag_context = state.get("rag_context", "")  # 获取RAG上下文
    if rag_context:  # 如果存在RAG上下文
        context_parts.append(f"\n{rag_context}")  # 追加RAG上下文片段

    long_term_memories = state.get("long_term_memories", "")  # 获取长期记忆
    if long_term_memories:  # 如果存在长期记忆
        context_parts.append(f"\n{long_term_memories}")  # 追加长期记忆片段

    return "\n\n".join(context_parts)  # 用双换行符拼接所有上下文片段并返回


# ============================================================
# 节点1：预处理（图片识别 + 长期记忆 + RAG 检索）
# ============================================================

async def preprocess_node(state: AgentState) -> dict:  # 定义预处理节点异步函数，返回状态更新字典
    """预处理节点：图片视觉分析 + 长期记忆检索 + RAG 检索。"""
    user_question = state["user_question"]  # 获取用户问题
    image_path = state.get("image_path", "")  # 获取图片路径
    updates: dict = {}  # 创建状态更新字典

    # 图片识别
    if image_path and os.path.exists(image_path):  # 如果有图片路径且文件存在
        logger.info("视觉Agent: 正在分析图片...")  # 记录日志：正在分析图片
        t0 = time.time()  # 记录开始时间
        updates["image_analysis"] = await _analyze_image(image_path, user_question)  # 调用图片分析函数
        _record_llm_duration("vision", time.time() - t0)  # 记录视觉Agent耗时指标
    else:  # 否则
        updates["image_analysis"] = ""  # 图片分析结果设为空字符串

    store = get_vector_store()  # 获取向量存储实例

    # 长期记忆检索（容错）
    try:  # 开始异常捕获块
        user_id_str = str(state.get("user_id", 0)) or "default"  # 从状态中获取用户ID并转为字符串，无则用"default"实现用户隔离
        memories = await store.retrieve_long_term_memories(  # 异步检索长期记忆
            user_question, user_id=user_id_str, top_k=get_settings().LONG_TERM_TOP_K  # 传入问题、实际用户ID、检索数量，确保记忆按用户隔离
        )
        lt_context = format_memories_context(memories)  # 将检索到的记忆格式化为上下文文本
        updates["long_term_memories"] = lt_context  # 更新长期记忆字段
        if lt_context:  # 如果有检索到记忆
            logger.info("长期记忆: 检索到 %d 条相关记忆", len(memories))  # 记录日志：检索到的记忆数量
    except Exception as e:  # 捕获异常
        updates["long_term_memories"] = ""  # 长期记忆设为空字符串
        logger.warning("长期记忆暂不可用: %s", e)  # 记录警告日志

    # RAG 检索（容错）
    try:  # 开始异常捕获块
        rag_context = await store.retrieve_rag_context(user_question, top_k=3)  # 异步检索RAG上下文，返回3条
        updates["rag_context"] = rag_context  # 更新RAG上下文字段
        if rag_context:  # 如果检索到RAG上下文
            logger.info("RAG: 检索到相关文档片段")  # 记录日志
    except Exception as e:  # 捕获异常
        updates["rag_context"] = ""  # RAG上下文设为空字符串
        logger.warning("RAG暂不可用: %s", e)  # 记录警告日志

    return updates  # 返回状态更新字典


async def _analyze_image(image_path: str, user_question: str) -> str:  # 定义图片分析的私有异步函数
    """视觉 Agent：使用本地 Ollama 多模态模型识别图片。"""
    import base64  # 导入base64模块，用于图片编码
    import ollama  # 导入ollama模块，用于调用本地多模态模型

    settings = get_settings()  # 获取应用配置
    with open(image_path, "rb") as f:  # 以二进制读模式打开图片文件
        image_data = base64.b64encode(f.read()).decode("utf-8")  # 读取并编码为base64字符串

    prompt = VISION_SYSTEM_PROMPT  # 使用默认视觉系统提示词
    if user_question:  # 如果有用户问题
        prompt = f"用户问题：{user_question}\n\n请根据图片内容回答用户的问题。"  # 构造带用户问题的提示词

    try:  # 开始异常捕获块
        response = await asyncio.wait_for(  # 用wait_for包裹异步调用，添加超时控制避免长时间阻塞
            ollama.AsyncClient(host=settings.OLLAMA_BASE_URL).chat(  # 异步调用Ollama客户端
                model=settings.OLLAMA_VISION_MODEL,  # 指定视觉模型
                messages=[{"role": "user", "content": prompt, "images": [image_data]}],  # 构造消息，包含提示词和图片数据
            ),
            timeout=get_settings().LLM_TIMEOUT_SECONDS,  # 从配置读取超时秒数，超时抛出TimeoutError
        )
        logger.info("视觉 Agent: 图片分析完成")  # 记录日志：图片分析完成
        return response["message"]["content"]  # 返回模型响应内容
    except Exception as e:  # 捕获异常
        logger.error("视觉 Agent 失败：%s", e)  # 记录错误日志
        return f"[视觉识别失败] 请确保 Ollama 服务已启动且已安装{settings.OLLAMA_VISION_MODEL}模型。错误：{str(e)}"  # 返回失败提示信息


# ============================================================
# 节点2：调度主管（路由决策，带缓存）
# ============================================================

async def supervisor_node(state: AgentState) -> dict:  # 定义调度主管节点异步函数
    """调度主管节点：判断处理方式（SEARCH / RAG / DIRECT）。"""
    user_question = state["user_question"]  # 获取用户问题
    history_context = state.get("history_context", "")  # 获取历史上下文

    async def _decide(question: str, history: str) -> str:  # 定义内部决策异步函数
        llm = create_llm(temperature=0.0)  # 创建温度为0的LLM实例，保证确定性输出
        prompt = f"用户问题：{question}"  # 构造基础提示词
        if history:  # 如果有历史上下文
            prompt = f"对话历史：\n{history}\n\n当前用户问题：{question}"  # 构造带历史的提示词
        response = await asyncio.wait_for(  # 用wait_for包裹LLM调用，添加超时控制避免长时间阻塞
            llm.ainvoke([  # 异步调用LLM
                SystemMessage(SUPERVISOR_SYSTEM_PROMPT),  # 系统消息：调度主管提示词
                HumanMessage(content=prompt),  # 人类消息：构造的提示词
            ]),
            timeout=get_settings().LLM_TIMEOUT_SECONDS,  # 从配置读取超时秒数，超时抛出TimeoutError
        )
        result_text = response.content.strip().upper()  # 提取响应内容并转为大写
        # 取第一行非空文本作为决策结果，避免正文中的关键词干扰（如"不建议搜索"）
        first_line = ""  # 第一行文本初始为空字符串
        for line in result_text.split("\n"):  # 按换行符拆分响应文本逐行遍历
            stripped = line.strip()  # 去除当前行的首尾空白字符
            if stripped:  # 如果当前行非空
                first_line = stripped  # 将当前行作为第一行非空文本
                break  # 找到第一行非空文本后跳出循环
        # 只在第一行中匹配决策关键词，避免正文中出现关键词导致误判
        if RouteAction.SEARCH in first_line:  # 如果第一行包含SEARCH
            return RouteAction.SEARCH  # 返回搜索路由
        if RouteAction.RAG in first_line:  # 如果第一行包含RAG
            return RouteAction.RAG  # 返回RAG路由
        return RouteAction.DIRECT  # 默认返回直接回答路由

    t0 = time.time()  # 记录开始时间
    action = await supervisor_decide_cached(user_question, history_context, _decide)  # 调用带缓存的路由决策
    _record_llm_duration("supervisor", time.time() - t0)  # 记录主管耗时指标
    _record_route(action)  # 记录路由类型指标
    logger.info("调度主管: 路由决策=%s", action)  # 记录路由决策日志

    # 更新熔断器状态Prometheus指标（0=closed, 1=half-open, 2=open）
    if _circuit_breaker_state is not None:  # 如果熔断器状态Gauge已初始化
        try:  # 开始异常捕获块
            from app.agents.resilience import get_circuit_breaker  # 导入熔断器获取函数
            breaker = get_circuit_breaker()  # 获取全局熔断器实例
            state_map = {"closed": 0, "half-open": 1, "open": 2}  # 状态字符串到数值的映射字典
            _circuit_breaker_state.set(state_map.get(breaker.state, 0))  # 设置Gauge指标值为对应数值
        except Exception as e:  # 捕获异常
            logger.warning("熔断器状态指标更新失败: %s", e)  # 记录警告日志，不影响主流程

    return {"action": action}  # 返回包含路由动作的状态更新


# ============================================================
# 节点3：搜索 Agent
# ============================================================

async def search_node(state: AgentState) -> dict:  # 定义搜索节点异步函数
    """搜索 Agent 节点：执行 Tavily 联网搜索。"""
    user_question = state["user_question"]  # 获取用户问题
    logger.info("搜索Agent: 正在执行联网搜索...")  # 记录日志：正在搜索
    t0 = time.time()  # 记录开始时间
    try:  # 捕获联网搜索内部异常，避免搜索失败导致整条智能体链路中断
        results = await _search_web(user_question)  # 调用联网搜索函数
    except Exception as e:  # 如果关键词提取或Tavily搜索失败
        logger.exception("搜索Agent: 联网搜索失败，进入降级回答")  # 记录完整异常堆栈，便于后续排查真实外部服务问题
        results = f"联网搜索暂时不可用，原因：{e}。请基于已有知识回答用户，并明确说明无法获取实时搜索结果。"  # 构造可传给回答节点的降级上下文
    _record_llm_duration("search", time.time() - t0)  # 记录搜索耗时指标
    logger.info("搜索Agent: 搜索完成（%d字符）", len(results))  # 记录搜索完成日志，含结果字符数
    return {"search_results": results}  # 返回包含搜索结果的状态更新


async def _search_web(user_question: str) -> str:  # 定义联网搜索的私有异步函数
    """使用 Tavily 执行联网搜索，返回结构化摘要。"""
    from tavily import TavilyClient  # 导入Tavily搜索客户端

    settings = get_settings()  # 获取应用配置
    llm = create_llm(temperature=0.0)  # 创建温度为0的LLM实例
    keyword_response = await asyncio.wait_for(  # 用wait_for包裹LLM调用，添加超时控制避免长时间阻塞
        llm.ainvoke([  # 异步调用LLM提取搜索关键词
            SystemMessage(SEARCH_SYSTEM_PROMPT),  # 系统消息：搜索专家提示词
            HumanMessage(content=f"请为以下问题提取搜索关键词：{user_question}"),  # 人类消息：要求提取关键词
        ]),
        timeout=get_settings().LLM_TIMEOUT_SECONDS,  # 从配置读取超时秒数，超时抛出TimeoutError
    )
    search_query = keyword_response.content.strip().strip('"').strip("'")  # 提取关键词并去除空白和引号
    logger.debug("搜索关键词：%s", search_query)  # 记录搜索关键词调试日志

    tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)  # 创建Tavily客户端实例
    search_response = await asyncio.to_thread(  # 用to_thread包装同步调用，将其放入线程池执行避免阻塞事件循环
        tavily_client.search, query=search_query, search_depth="basic", max_results=3, include_answer=True  # 设置查询、深度、最大结果数、包含AI摘要
    )

    formatted_parts = []  # 格式化结果片段列表
    if search_response.get("answer"):  # 如果有AI摘要
        formatted_parts.append(f"[AI 摘要] {search_response['answer']}")  # 追加AI摘要片段
    for i, result in enumerate(search_response.get("results", []), 1):  # 遍历搜索结果，序号从1开始
        title = result.get("title", "无标题")  # 获取结果标题
        url = result.get("url", "")  # 获取结果链接
        content = result.get("content", "无内容")  # 获取结果内容
        content_short = content[:300] + "..." if len(content) > 300 else content  # 截断内容到300字符
        formatted_parts.append(f"[结果{i}] {title}\n链接：{url}\n摘要：{content_short}")  # 格式化并追加结果片段

    return "\n\n".join(formatted_parts) if formatted_parts else "未找到相关搜索结果。"  # 拼接所有片段，无结果时返回提示


# ============================================================
# 节点3b：RAG 检索节点
# ============================================================

async def rag_node(state: AgentState) -> dict:  # 定义RAG检索节点异步函数
    """RAG 检索节点：确保 RAG 上下文被加载（增强检索）。"""
    user_question = state["user_question"]  # 获取用户问题
    existing_rag = state.get("rag_context", "")  # 获取已有的RAG上下文
    if existing_rag:  # 如果已有RAG上下文
        logger.info("RAG节点: 已有RAG上下文，跳过重复检索")  # 记录日志：跳过重复检索
        return {}  # 返回空字典，不更新状态
    try:  # 开始异常捕获块
        store = get_vector_store()  # 获取向量存储实例
        rag_context = await store.retrieve_rag_context(user_question, top_k=5)  # 异步检索RAG上下文，返回5条
        logger.info("RAG节点: 增强检索完成（%d字符）", len(rag_context))  # 记录检索完成日志
        return {"rag_context": rag_context}  # 返回包含RAG上下文的状态更新
    except Exception as e:  # 捕获异常
        logger.warning("RAG节点: 检索失败: %s", e)  # 记录警告日志
        return {}  # 返回空字典，不更新状态


# ============================================================
# 节点3c：人工审批（Human-in-the-loop）
# ============================================================

async def human_review_node(state: AgentState) -> dict:  # 定义人工审批节点异步函数，返回状态更新字典
    """
    人工审批节点：检测用户问题是否包含敏感操作关键词。

    - 启用HITL时：检测到敏感关键词则标记需要审批，等待人工确认后才继续执行
    - 未启用HITL时：直接跳过，不阻断流程
    """
    from langgraph.types import interrupt  # 从LangGraph导入interrupt函数
    settings = get_settings()  # 获取配置
    if not settings.HITL_ENABLED:  # 如果未启用人工审批
        return {}  # 直接跳过，不更新状态
    user_question = state["user_question"]  # 获取用户问题
    keywords = [k.strip() for k in settings.HITL_SENSITIVE_KEYWORDS.split(",")]  # 解析敏感关键词列表
    # 检查用户问题是否包含任何敏感关键词
    needs_review = any(kw in user_question for kw in keywords if kw)  # 任一关键词匹配则需要审批
    if not needs_review:  # 如果不需要审批
        return {}  # 直接跳过
    # 需要人工审批：调用interrupt暂停图执行，等待人工确认
    logger.info("检测到敏感操作，等待人工审批: %s", user_question[:50])  # 记录审批日志
    approval = interrupt(  # 调用LangGraph interrupt暂停执行，等待人工输入
        {"question": user_question, "reason": "包含敏感操作关键词，需要人工确认"}  # 传递审批上下文信息给人工审核者
    )  # interrupt返回人工审批结果
    if approval == "approved":  # 如果审批通过
        logger.info("人工审批通过，继续执行")  # 记录审批通过日志
        return {}  # 返回空字典，继续执行后续节点
    else:  # 如果审批被拒绝
        logger.info("人工审批拒绝，终止执行")  # 记录审批拒绝日志
        return {"messages": [AIMessage(content="您的请求已被管理员拒绝。")]}, "reject"  # 返回拒绝消息


# ============================================================
# 节点4：回答 Agent（Function Calling + 真流式）
# ============================================================

async def answer_node(state: AgentState) -> dict:  # 定义回答节点异步函数
    """
    回答 Agent 节点：综合所有上下文生成最终回答。

    - 绑定 Function Calling 工具（计算器、时间查询）
    - 使用 astream 实现真流式（供 astream_events 捕获 token）
    - 若模型调用工具，执行工具后进行第二轮生成
    """
    user_message = _build_answer_context(state)  # 构建回答上下文消息

    logger.info(  # 记录日志：生成回答中，含各上下文标志
        "回答Agent: 生成回答中（搜索:%s RAG:%s 图片:%s 记忆:%s）",  # 日志格式
        bool(state.get("search_results")), bool(state.get("rag_context")),  # 搜索和RAG标志
        bool(state.get("image_analysis")), bool(state.get("long_term_memories")),  # 图片和记忆标志
    )

    t0 = time.time()  # 记录开始时间
    answer = await _generate_with_tools(user_message)  # 调用带工具的回答生成函数
    _record_llm_duration("answer", time.time() - t0)  # 记录回答耗时指标

    return {"messages": [AIMessage(content=answer)]}  # 返回包含AI消息的状态更新


async def _generate_with_tools(user_message: str) -> str:  # 定义带工具的回答生成私有异步函数
    """带 Function Calling 的回答生成（支持多轮工具调用）。

    策略：绑定工具后流式生成，循环执行工具调用直到模型不再调用工具或达到最大轮数。
    - 若模型直接回答：content 流式输出，无 tool_calls，单轮完成。
    - 若模型调用工具：执行工具后将结果注入上下文，进入下一轮生成。
    - 达到最大轮数后：用不带工具的LLM生成最终回答，避免无限循环。
    """
    llm = create_llm(temperature=0.3)  # 创建温度0.3的LLM实例
    llm_with_tools = llm.bind_tools(AGENT_TOOLS)  # 绑定Function Calling工具
    messages = [  # 构造消息列表
        SystemMessage(ANSWER_SYSTEM_PROMPT),  # 系统消息：回答Agent提示词
        HumanMessage(content=user_message),  # 人类消息：回答上下文
    ]
    max_rounds = get_settings().MAX_TOOL_CALL_ROUNDS  # 从配置读取最大工具调用轮数，防止无限循环

    for round_num in range(max_rounds):  # 循环执行最多max_rounds轮工具调用
        first_message = await _stream_full_message(llm_with_tools, messages)  # 流式生成当前轮次的完整消息
        tool_calls = getattr(first_message, "tool_calls", None)  # 获取消息中的工具调用列表
        if not tool_calls:  # 如果没有工具调用
            return first_message.content  # 模型已直接回答，返回内容不再继续循环
        # 有工具调用，执行工具并将结果加入上下文供下一轮使用
        tool_results = _execute_tool_calls(tool_calls)  # 执行工具调用获取结果文本
        if tool_results:  # 如果工具执行有结果
            messages.append(first_message)  # 将当前轮次的AI消息加入上下文，保留工具调用历史
            messages.append(HumanMessage(content=f"[工具执行结果]\n{tool_results}"))  # 将工具结果作为人类消息注入上下文
        else:  # 如果工具执行失败无结果
            return first_message.content  # 工具执行失败，返回当前已有内容避免空回答

    # 达到最大轮数仍有工具调用，用不带工具的LLM生成最终回答，强制收尾
    final_message = await _stream_full_message(llm, messages)  # 用不带工具绑定的LLM流式生成最终消息
    return final_message.content  # 返回最终消息内容


async def _stream_full_message(llm, messages: list) -> AIMessage:  # 定义流式生成完整消息的私有异步函数
    """流式调用 LLM 并累积为完整 AIMessage（供 astream_events 捕获 token）。"""
    full = None  # 完整消息初始为None
    async for chunk in llm.astream(messages):  # 异步迭代LLM的流式输出
        full = chunk if full is None else full + chunk  # 累积chunk到full，首个chunk直接赋值
    if full is None:  # 如果没有任何输出
        return AIMessage(content="")  # 返回空内容的AI消息
    return AIMessage(  # 返回构造的AI消息
        content=getattr(full, "content", ""),  # 设置内容
        tool_calls=getattr(full, "tool_calls", None) or [],  # 设置工具调用列表，默认为空列表
    )


def _execute_tool_calls(tool_calls: list) -> str:  # 定义执行工具调用的私有函数
    """执行工具调用，返回结果文本。"""
    results = []  # 工具结果列表
    tool_map = {t.name: t for t in AGENT_TOOLS}  # 构建工具名到工具对象的映射字典
    for call in tool_calls:  # 遍历工具调用列表
        tool_name = call.get("name", "")  # 获取工具名称
        tool_args = call.get("args", {})  # 获取工具参数
        tool = tool_map.get(tool_name)  # 从映射中获取工具对象
        if tool:  # 如果找到工具
            try:  # 开始异常捕获块
                result = tool.invoke(tool_args)  # 调用工具执行
                results.append(f"{tool_name}: {result}")  # 将结果加入列表
                logger.info("工具调用: %s(%s) -> %s", tool_name, tool_args, result)  # 记录工具调用日志
            except Exception as e:  # 捕获异常
                logger.warning("工具 %s 执行失败: %s", tool_name, e)  # 记录警告日志
    return "\n".join(results)  # 用换行符拼接所有工具结果并返回


# ============================================================
# 节点5：记忆存储
# ============================================================

async def store_memory_node(state: AgentState) -> dict:  # 定义记忆存储节点异步函数
    """记忆存储节点：将本轮对话存入长期记忆向量库。"""
    messages = state.get("messages", [])  # 获取消息列表
    user_question = state["user_question"]  # 获取用户问题
    user_id = state.get("user_id", 0)  # 获取用户ID

    answer_text = ""  # 回答文本初始为空
    for msg in reversed(messages):  # 逆序遍历消息列表
        if isinstance(msg, AIMessage):  # 找到AI消息
            answer_text = msg.content  # 提取AI消息内容
            break  # 跳出循环

    if answer_text:  # 如果有回答文本
        try:  # 开始异常捕获块
            store = get_vector_store()  # 获取向量存储实例
            await store.store_conversation_turn(  # 异步存储对话轮次
                user_id=str(user_id) if user_id else "default",  # 设置用户ID，无则用"default"
                question=user_question,  # 设置用户问题
                answer=answer_text,  # 设置回答文本
            )
            logger.info("记忆存储: 已存入长期记忆")  # 记录日志：已存入记忆
        except Exception as e:  # 捕获异常
            logger.warning("记忆存储失败（不影响回答）: %s", e)  # 记录警告日志

    return {}  # 返回空字典，不更新状态


# ============================================================
# 条件路由
# ============================================================

def route_after_supervisor(state: AgentState) -> Literal["search", "rag", "answer"]:  # 定义条件路由函数，返回字面量类型
    """根据主管决策路由到搜索、RAG 检索或直接回答。"""
    action = state.get("action", RouteAction.DIRECT)  # 获取路由动作，默认为DIRECT
    if action == RouteAction.SEARCH:  # 如果动作是搜索
        return "search"  # 返回search
    if action == RouteAction.RAG:  # 如果动作是RAG
        return "rag"  # 返回rag
    return "answer"  # 默认返回answer
