"""工业智能制造 LangGraph 节点实现：全部异步，支持领域工具调用与流式输出。"""

import os
import time
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

from app.core.config import get_settings
from app.core.logging import setup_logger
from app.agents.llm import create_llm, supervisor_decide_cached
from app.agents.manufacturing.prompts import (
    MFG_ANSWER_SYSTEM_PROMPT,
    MFG_FAULT_DIAGNOSIS_PROMPT,
    MFG_KNOWLEDGE_QA_PROMPT,
    MFG_PREDICTIVE_MAINTENANCE_PROMPT,
    MFG_PROCESS_OPTIMIZATION_PROMPT,
    MFG_SUPERVISOR_SYSTEM_PROMPT,
)

logger = setup_logger("agents.manufacturing.nodes")


# ============================================================
# 工业路由枚举
# ============================================================

class MfgRouteAction:
    """工业 Supervisor 路由决策。"""

    FAULT = "FAULT"
    PROCESS = "PROCESS"
    PREDICT = "PREDICT"
    KNOWLEDGE = "KNOWLEDGE"


# ============================================================
# 工作流状态定义
# ============================================================

class MfgAgentState(TypedDict):
    """工业多智能体工作流状态。"""

    messages: Annotated[list, add_messages]
    user_question: str
    action: str
    # 图片视觉
    image_path: str            # 上传图片路径
    image_analysis: str        # 视觉分析结果
    # 领域上下文
    fault_code_info: str       # 故障码查询结果
    equipment_params: str      # 设备参数
    sensor_data: str           # 传感器模拟数据
    maintenance_info: str      # 维护计划信息
    process_analysis: str      # 工艺分析结果
    rag_context: str           # RAG 检索的工业文档
    history_context: str       # 对话历史
    user_id: int


# ============================================================
# Prometheus 指标（可选）
# ============================================================

_mfg_requests_total = None
_mfg_llm_duration = None


def _init_metrics() -> None:
    global _mfg_requests_total, _mfg_llm_duration
    if _mfg_requests_total is not None:
        return
    try:
        from prometheus_client import Counter, Histogram
        _mfg_requests_total = Counter(
            "mfg_agent_requests_total", "Total manufacturing agent routing decisions", ["route_type"]
        )
        _mfg_llm_duration = Histogram(
            "mfg_llm_response_duration_seconds", "Manufacturing LLM call duration",
            ["agent_name"], buckets=[0.5, 1, 2, 5, 10, 30, 60],
        )
    except ImportError:
        logger.warning("prometheus_client 未安装，工业指标不可用")


def _record_route(route_type: str) -> None:
    if _mfg_requests_total:
        _mfg_requests_total.labels(route_type=route_type).inc()


def _record_llm_duration(agent_name: str, duration: float) -> None:
    if _mfg_llm_duration:
        _mfg_llm_duration.labels(agent_name=agent_name).observe(duration)


_init_metrics()


# ============================================================
# 节点1：预处理（加载领域知识上下文）
# ============================================================

async def mfg_preprocess_node(state: MfgAgentState) -> dict:
    """预处理节点：图片视觉分析 + 加载相关领域知识（故障码/设备参数/RAG）。"""
    user_question = state["user_question"]
    image_path = state.get("image_path", "")
    updates: dict = {}

    # 图片视觉分析（工业场景：设备铭牌、故障截图、仪表盘等）
    if image_path and os.path.exists(image_path):
        logger.info("工业视觉Agent: 正在分析图片...")
        t0 = time.time()
        updates["image_analysis"] = await _analyze_mfg_image(image_path, user_question)
        _record_llm_duration("mfg_vision", time.time() - t0)
    else:
        updates["image_analysis"] = ""

    # 尝试 RAG 检索工业文档（容错）
    try:
        from app.agents.runtime import get_vector_store
        store = get_vector_store()
        rag_context = await store.retrieve_rag_context(user_question, top_k=3)
        updates["rag_context"] = rag_context
        if rag_context:
            logger.info("工业RAG: 检索到相关文档片段")
    except Exception as e:
        updates["rag_context"] = ""
        logger.debug("工业RAG暂不可用: %s", e)

    # 初始化其他字段
    updates.setdefault("fault_code_info", "")
    updates.setdefault("equipment_params", "")
    updates.setdefault("sensor_data", "")
    updates.setdefault("maintenance_info", "")
    updates.setdefault("process_analysis", "")

    return updates


async def _analyze_mfg_image(image_path: str, user_question: str) -> str:
    """工业视觉 Agent：使用本地 Ollama 多模态模型识别工业图片。"""
    import base64
    import ollama

    settings = get_settings()
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        "你是一位工业视觉分析专家。请仔细观察图片内容，识别其中的设备、铭牌、"
        "仪表盘读数、故障现象、工艺状态等信息，并给出专业分析。"
    )
    if user_question:
        prompt = f"用户问题：{user_question}\n\n{prompt}"

    try:
        response = await ollama.AsyncClient(host=settings.OLLAMA_BASE_URL).chat(
            model=settings.OLLAMA_VISION_MODEL,
            messages=[{"role": "user", "content": prompt, "images": [image_data]}],
        )
        logger.info("工业视觉Agent: 图片分析完成")
        return response["message"]["content"]
    except Exception as e:
        logger.error("工业视觉Agent失败：%s", e)
        return f"[视觉识别失败] 请确保 Ollama 服务已启动且已安装{settings.OLLAMA_VISION_MODEL}模型。错误：{str(e)}"


# ============================================================
# 节点2：工业调度主管（路由决策）
# ============================================================

async def mfg_supervisor_node(state: MfgAgentState) -> dict:
    """工业调度主管：判断子领域（FAULT / PROCESS / PREDICT / KNOWLEDGE）。"""
    user_question = state["user_question"]
    history_context = state.get("history_context", "")

    async def _decide(question: str, history: str) -> str:
        llm = create_llm(temperature=0.0)
        prompt = f"用户问题：{question}"
        if history:
            prompt = f"对话历史：\n{history}\n\n当前用户问题：{question}"
        response = await llm.ainvoke([
            SystemMessage(MFG_SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        result_text = response.content.strip().upper()
        if MfgRouteAction.FAULT in result_text:
            return MfgRouteAction.FAULT
        if MfgRouteAction.PROCESS in result_text:
            return MfgRouteAction.PROCESS
        if MfgRouteAction.PREDICT in result_text:
            return MfgRouteAction.PREDICT
        return MfgRouteAction.KNOWLEDGE

    t0 = time.time()
    action = await supervisor_decide_cached(user_question, history_context, _decide)
    _record_llm_duration("mfg_supervisor", time.time() - t0)
    _record_route(action)
    logger.info("工业调度主管: 路由决策=%s", action)
    return {"action": action}


# ============================================================
# 节点3a：故障诊断 Agent
# ============================================================

async def fault_diagnosis_node(state: MfgAgentState) -> dict:
    """故障诊断节点：调用领域工具查询故障码，生成诊断上下文。"""
    user_question = state["user_question"]
    logger.info("故障诊断Agent: 分析故障...")
    t0 = time.time()

    # 尝试从问题中提取故障码并查询
    fault_info = ""
    try:
        from app.agents.manufacturing.tools import query_fault_code_by_text
        fault_info = query_fault_code_by_text(user_question)
    except Exception as e:
        logger.warning("故障码查询失败: %s", e)

    _record_llm_duration("fault_diagnosis", time.time() - t0)
    return {"fault_code_info": fault_info}


# ============================================================
# 节点3b：工艺优化 Agent
# ============================================================

async def process_optimization_node(state: MfgAgentState) -> dict:
    """工艺优化节点：加载工艺标准，分析参数偏差。"""
    user_question = state["user_question"]
    logger.info("工艺优化Agent: 分析工艺参数...")
    t0 = time.time()

    process_info = ""
    try:
        from app.agents.manufacturing.tools import analyze_process_params_by_text
        process_info = analyze_process_params_by_text(user_question)
    except Exception as e:
        logger.warning("工艺参数分析失败: %s", e)

    _record_llm_duration("process_optimization", time.time() - t0)
    return {"process_analysis": process_info}


# ============================================================
# 节点3c：预测性维护 Agent
# ============================================================

async def predictive_maintenance_node(state: MfgAgentState) -> dict:
    """预测性维护节点：模拟传感器数据 + 查询维护计划。"""
    user_question = state["user_question"]
    logger.info("预测维护Agent: 评估设备健康...")
    t0 = time.time()

    sensor_info = ""
    maintenance_info = ""
    try:
        from app.agents.manufacturing.tools import (
            check_maintenance_by_text,
            simulate_sensor_by_text,
        )
        sensor_info = simulate_sensor_by_text(user_question)
        maintenance_info = check_maintenance_by_text(user_question)
    except Exception as e:
        logger.warning("预测维护数据获取失败: %s", e)

    _record_llm_duration("predictive_maintenance", time.time() - t0)
    return {"sensor_data": sensor_info, "maintenance_info": maintenance_info}


# ============================================================
# 节点3d：工业知识问答 Agent
# ============================================================

async def knowledge_qa_node(state: MfgAgentState) -> dict:
    """工业知识问答节点：无需特殊工具，直接由 answer 节点回答。"""
    logger.info("工业知识Agent: 准备知识问答上下文")
    return {}


# ============================================================
# 节点4：工业回答 Agent（综合生成）
# ============================================================

async def mfg_answer_node(state: MfgAgentState) -> dict:
    """工业回答节点：根据路由结果和所有上下文生成专业回答。"""
    action = state.get("action", MfgRouteAction.KNOWLEDGE)
    user_message = _build_mfg_answer_context(state)

    # 根据路由选择对应的领域 Prompt
    prompt_map = {
        MfgRouteAction.FAULT: MFG_FAULT_DIAGNOSIS_PROMPT,
        MfgRouteAction.PROCESS: MFG_PROCESS_OPTIMIZATION_PROMPT,
        MfgRouteAction.PREDICT: MFG_PREDICTIVE_MAINTENANCE_PROMPT,
        MfgRouteAction.KNOWLEDGE: MFG_KNOWLEDGE_QA_PROMPT,
    }
    system_prompt = prompt_map.get(action, MFG_ANSWER_SYSTEM_PROMPT)

    logger.info("工业回答Agent: 生成回答（路由=%s）", action)
    t0 = time.time()

    llm = create_llm(temperature=0.3)
    messages = [
        SystemMessage(system_prompt),
        HumanMessage(content=user_message),
    ]

    # 流式生成（供 astream_events 捕获 token）
    full = None
    async for chunk in llm.astream(messages):
        full = chunk if full is None else full + chunk

    answer = ""
    if full is not None:
        answer = getattr(full, "content", "")

    _record_llm_duration("mfg_answer", time.time() - t0)
    return {"messages": [AIMessage(content=answer)]}


# ============================================================
# 节点5：记忆存储
# ============================================================

async def mfg_store_memory_node(state: MfgAgentState) -> dict:
    """记忆存储节点：将本轮工业对话存入长期记忆。"""
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
            from app.agents.runtime import get_vector_store
            store = get_vector_store()
            await store.store_conversation_turn(
                user_id=f"mfg_{user_id}" if user_id else "mfg_default",
                question=user_question,
                answer=answer_text,
            )
            logger.info("工业记忆存储: 已存入长期记忆")
        except Exception as e:
            logger.warning("工业记忆存储失败（不影响回答）: %s", e)

    return {}


# ============================================================
# 条件路由
# ============================================================

def route_after_mfg_supervisor(
    state: MfgAgentState,
) -> Literal["fault_diagnosis", "process_optimization", "predictive_maintenance", "knowledge_qa"]:
    """根据工业主管决策路由到对应子领域节点。"""
    action = state.get("action", MfgRouteAction.KNOWLEDGE)
    if action == MfgRouteAction.FAULT:
        return "fault_diagnosis"
    if action == MfgRouteAction.PROCESS:
        return "process_optimization"
    if action == MfgRouteAction.PREDICT:
        return "predictive_maintenance"
    return "knowledge_qa"


# ============================================================
# 辅助：构建工业回答上下文
# ============================================================

def _build_mfg_answer_context(state: MfgAgentState) -> str:
    """综合所有工业上下文构建回答 Agent 的用户消息。"""
    user_question = state["user_question"]
    context_parts = [f"用户问题：{user_question}"]

    history_context = state.get("history_context", "")
    if history_context:
        context_parts.insert(0, f"对话历史：\n{history_context}")

    # 图片视觉分析结果
    image_analysis = state.get("image_analysis", "")
    if image_analysis:
        context_parts.append(f"\n[图片视觉分析]\n{image_analysis}")

    fault_code_info = state.get("fault_code_info", "")
    if fault_code_info:
        context_parts.append(f"\n[故障码查询结果]\n{fault_code_info}")

    equipment_params = state.get("equipment_params", "")
    if equipment_params:
        context_parts.append(f"\n[设备参数]\n{equipment_params}")

    sensor_data = state.get("sensor_data", "")
    if sensor_data:
        context_parts.append(f"\n[传感器数据]\n{sensor_data}")

    maintenance_info = state.get("maintenance_info", "")
    if maintenance_info:
        context_parts.append(f"\n[维护计划]\n{maintenance_info}")

    process_analysis = state.get("process_analysis", "")
    if process_analysis:
        context_parts.append(f"\n[工艺分析]\n{process_analysis}")

    rag_context = state.get("rag_context", "")
    if rag_context:
        context_parts.append(f"\n{rag_context}")

    return "\n\n".join(context_parts)
