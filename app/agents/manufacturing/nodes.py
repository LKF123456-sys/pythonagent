"""工业智能制造 LangGraph 节点实现：全部异步，支持领域工具调用与流式输出。"""

import os  # 导入操作系统接口模块，用于文件路径检查等
import time  # 导入时间模块，用于性能计时
from typing import Annotated, Literal, TypedDict  # 导入类型注解工具：Annotated用于添加元数据、Literal用于字面量类型、TypedDict用于字典类型定义

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # 导入LangChain消息类型：AI消息、人类消息、系统消息
from langgraph.graph.message import add_messages  # 导入消息累加函数，用于状态中messages字段的自动累加

from app.core.config import get_settings  # 导入配置获取函数，用于读取应用配置
from app.core.logging import setup_logger  # 导入日志初始化函数，用于创建模块专属日志器
from app.agents.llm import create_llm, supervisor_decide_cached  # 导入LLM创建函数和带缓存的调度决策函数
from app.agents.manufacturing.prompts import (  # 从工业提示词模块导入所有系统提示词
    MFG_ANSWER_SYSTEM_PROMPT,  # 工业回答系统提示词
    MFG_FAULT_DIAGNOSIS_PROMPT,  # 故障诊断提示词
    MFG_KNOWLEDGE_QA_PROMPT,  # 知识问答提示词
    MFG_PREDICTIVE_MAINTENANCE_PROMPT,  # 预测性维护提示词
    MFG_PROCESS_OPTIMIZATION_PROMPT,  # 工艺优化提示词
    MFG_SUPERVISOR_SYSTEM_PROMPT,  # 调度主管系统提示词
)

logger = setup_logger("agents.manufacturing.nodes")  # 创建工业节点模块的专属日志器


# ============================================================
# 工业路由枚举
# ============================================================

class MfgRouteAction:  # 工业调度主管路由决策类
    """工业 Supervisor 路由决策。"""

    FAULT = "FAULT"  # 故障诊断路由常量
    PROCESS = "PROCESS"  # 工艺优化路由常量
    PREDICT = "PREDICT"  # 预测性维护路由常量
    KNOWLEDGE = "KNOWLEDGE"  # 知识问答路由常量


# ============================================================
# 工作流状态定义
# ============================================================

class MfgAgentState(TypedDict):  # 工业多智能体工作流状态类型定义
    """工业多智能体工作流状态。"""

    messages: Annotated[list, add_messages]  # 消息列表，使用add_messages累加器自动合并
    user_question: str  # 用户问题文本
    action: str  # 路由决策结果
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
    user_id: int               # 用户ID


# ============================================================
# Prometheus 指标（可选）
# ============================================================

_mfg_requests_total = None  # 工业请求总数计数器，初始为None
_mfg_llm_duration = None  # 工业LLM调用耗时直方图，初始为None


def _init_metrics() -> None:  # 初始化Prometheus指标
    """初始化 Prometheus 指标（可选）。"""
    global _mfg_requests_total, _mfg_llm_duration  # 声明使用全局指标变量
    if _mfg_requests_total is not None:  # 如果请求计数器已初始化
        return  # 直接返回，避免重复初始化
    try:  # 尝试导入prometheus_client
        from prometheus_client import Counter, Histogram  # 导入Counter计数器和Histogram直方图
        _mfg_requests_total = Counter(  # 创建请求总数计数器
            "mfg_agent_requests_total", "Total manufacturing agent routing decisions", ["route_type"]  # 指标名、描述、标签
        )
        _mfg_llm_duration = Histogram(  # 创建LLM耗时直方图
            "mfg_llm_response_duration_seconds", "Manufacturing LLM call duration",  # 指标名和描述
            ["agent_name"], buckets=[0.5, 1, 2, 5, 10, 30, 60],  # 标签和分桶配置
        )
    except ImportError:  # 如果导入失败
        logger.warning("prometheus_client 未安装，工业指标不可用")  # 记录警告日志


def _record_route(route_type: str) -> None:  # 记录路由决策指标
    """记录路由决策类型到Prometheus指标。"""
    if _mfg_requests_total:  # 如果计数器可用
        _mfg_requests_total.labels(route_type=route_type).inc()  # 按路由类型递增计数


def _record_llm_duration(agent_name: str, duration: float) -> None:  # 记录LLM调用耗时指标
    """记录LLM调用耗时到Prometheus指标。"""
    if _mfg_llm_duration:  # 如果直方图可用
        _mfg_llm_duration.labels(agent_name=agent_name).observe(duration)  # 按agent名称观察耗时值


_init_metrics()  # 模块加载时初始化指标


# ============================================================
# 节点1：预处理（加载领域知识上下文）
# ============================================================

async def mfg_preprocess_node(state: MfgAgentState) -> dict:  # 工业预处理节点（异步）
    """预处理节点：图片视觉分析 + 加载相关领域知识（故障码/设备参数/RAG）。"""
    user_question = state["user_question"]  # 从状态中获取用户问题
    image_path = state.get("image_path", "")  # 从状态中获取图片路径，默认为空
    updates: dict = {}  # 初始化状态更新字典

    # 图片视觉分析（工业场景：设备铭牌、故障截图、仪表盘等）
    if image_path and os.path.exists(image_path):  # 如果图片路径存在且文件存在
        logger.info("工业视觉Agent: 正在分析图片...")  # 记录分析开始日志
        t0 = time.time()  # 记录开始时间
        updates["image_analysis"] = await _analyze_mfg_image(image_path, user_question)  # 调用视觉分析函数
        _record_llm_duration("mfg_vision", time.time() - t0)  # 记录视觉分析耗时
    else:  # 否则无图片
        updates["image_analysis"] = ""  # 图片分析结果设为空

    # 尝试 RAG 检索工业文档（容错）
    try:  # 尝试RAG检索
        from app.agents.runtime import get_vector_store  # 导入向量存储获取函数
        store = get_vector_store()  # 获取向量存储实例
        rag_context = await store.retrieve_rag_context(user_question, top_k=3)  # 检索与问题相关的文档片段，取前3条
        updates["rag_context"] = rag_context  # 将检索结果存入更新字典
        if rag_context:  # 如果检索到相关文档
            logger.info("工业RAG: 检索到相关文档片段")  # 记录检索成功日志
    except Exception as e:  # 捕获异常
        updates["rag_context"] = ""  # RAG上下文设为空
        logger.debug("工业RAG暂不可用: %s", e)  # 记录调试日志

    # 初始化其他字段
    updates.setdefault("fault_code_info", "")  # 故障码信息默认为空
    updates.setdefault("equipment_params", "")  # 设备参数默认为空
    updates.setdefault("sensor_data", "")  # 传感器数据默认为空
    updates.setdefault("maintenance_info", "")  # 维护信息默认为空
    updates.setdefault("process_analysis", "")  # 工艺分析结果默认为空

    return updates  # 返回状态更新字典


async def _analyze_mfg_image(image_path: str, user_question: str) -> str:  # 工业视觉分析函数（异步）
    """工业视觉 Agent：使用本地 Ollama 多模态模型识别工业图片。"""
    import base64  # 导入base64编码模块
    import ollama  # 导入ollama客户端

    settings = get_settings()  # 获取应用配置
    with open(image_path, "rb") as f:  # 以二进制读模式打开图片文件
        image_data = base64.b64encode(f.read()).decode("utf-8")  # 读取并base64编码图片数据

    prompt = (  # 构建视觉分析提示词
        "你是一位工业视觉分析专家。请仔细观察图片内容，识别其中的设备、铭牌、"
        "仪表盘读数、故障现象、工艺状态等信息，并给出专业分析。"
    )
    if user_question:  # 如果有用户问题
        prompt = f"用户问题：{user_question}\n\n{prompt}"  # 将用户问题加入提示词

    try:  # 尝试调用ollama
        response = await ollama.AsyncClient(host=settings.OLLAMA_BASE_URL).chat(  # 异步调用ollama聊天接口
            model=settings.OLLAMA_VISION_MODEL,  # 使用配置的视觉模型
            messages=[{"role": "user", "content": prompt, "images": [image_data]}],  # 传入提示词和图片数据
        )
        logger.info("工业视觉Agent: 图片分析完成")  # 记录分析完成日志
        return response["message"]["content"]  # 返回分析结果文本
    except Exception as e:  # 捕获异常
        logger.error("工业视觉Agent失败：%s", e)  # 记录错误日志
        return f"[视觉识别失败] 请确保 Ollama 服务已启动且已安装{settings.OLLAMA_VISION_MODEL}模型。错误：{str(e)}"  # 返回错误提示


# ============================================================
# 节点2：工业调度主管（路由决策）
# ============================================================

async def mfg_supervisor_node(state: MfgAgentState) -> dict:  # 工业调度主管节点（异步）
    """工业调度主管：判断子领域（FAULT / PROCESS / PREDICT / KNOWLEDGE）。"""
    user_question = state["user_question"]  # 从状态中获取用户问题
    history_context = state.get("history_context", "")  # 从状态中获取对话历史，默认为空

    async def _decide(question: str, history: str) -> str:  # 内部决策函数（异步）
        """执行LLM决策的内部函数。"""
        llm = create_llm(temperature=0.0)  # 创建温度为0的LLM实例（确定性输出）
        prompt = f"用户问题：{question}"  # 构建基础提示词
        if history:  # 如果有历史上下文
            prompt = f"对话历史：\n{history}\n\n当前用户问题：{question}"  # 将历史加入提示词
        response = await llm.ainvoke([  # 异步调用LLM
            SystemMessage(MFG_SUPERVISOR_SYSTEM_PROMPT),  # 系统消息：调度主管提示词
            HumanMessage(content=prompt),  # 人类消息：用户问题
        ])
        result_text = response.content.strip().upper()  # 获取响应文本并大写化
        if MfgRouteAction.FAULT in result_text:  # 如果结果包含FAULT
            return MfgRouteAction.FAULT  # 返回故障路由
        if MfgRouteAction.PROCESS in result_text:  # 如果结果包含PROCESS
            return MfgRouteAction.PROCESS  # 返回工艺路由
        if MfgRouteAction.PREDICT in result_text:  # 如果结果包含PREDICT
            return MfgRouteAction.PREDICT  # 返回预测路由
        return MfgRouteAction.KNOWLEDGE  # 默认返回知识路由

    t0 = time.time()  # 记录开始时间
    action = await supervisor_decide_cached(user_question, history_context, _decide)  # 带缓存地执行调度决策
    _record_llm_duration("mfg_supervisor", time.time() - t0)  # 记录调度耗时
    _record_route(action)  # 记录路由决策
    logger.info("工业调度主管: 路由决策=%s", action)  # 记录路由决策日志
    return {"action": action}  # 返回路由决策结果


# ============================================================
# 节点3a：故障诊断 Agent
# ============================================================

async def fault_diagnosis_node(state: MfgAgentState) -> dict:  # 故障诊断节点（异步）
    """故障诊断节点：调用领域工具查询故障码，生成诊断上下文。"""
    user_question = state["user_question"]  # 从状态中获取用户问题
    logger.info("故障诊断Agent: 分析故障...")  # 记录分析开始日志
    t0 = time.time()  # 记录开始时间

    # 尝试从问题中提取故障码并查询
    fault_info = ""  # 初始化故障信息为空
    try:  # 尝试查询故障码
        from app.agents.manufacturing.tools import query_fault_code_by_text  # 导入故障码查询函数
        fault_info = query_fault_code_by_text(user_question)  # 从用户问题查询故障码信息
    except Exception as e:  # 捕获异常
        logger.warning("故障码查询失败: %s", e)  # 记录警告日志

    _record_llm_duration("fault_diagnosis", time.time() - t0)  # 记录故障诊断耗时
    return {"fault_code_info": fault_info}  # 返回故障码信息


# ============================================================
# 节点3b：工艺优化 Agent
# ============================================================

async def process_optimization_node(state: MfgAgentState) -> dict:  # 工艺优化节点（异步）
    """工艺优化节点：加载工艺标准，分析参数偏差。"""
    user_question = state["user_question"]  # 从状态中获取用户问题
    logger.info("工艺优化Agent: 分析工艺参数...")  # 记录分析开始日志
    t0 = time.time()  # 记录开始时间

    process_info = ""  # 初始化工艺信息为空
    try:  # 尝试查询工艺参数
        from app.agents.manufacturing.tools import analyze_process_params_by_text  # 导入工艺参数分析函数
        process_info = analyze_process_params_by_text(user_question)  # 从用户问题分析工艺参数
    except Exception as e:  # 捕获异常
        logger.warning("工艺参数分析失败: %s", e)  # 记录警告日志

    _record_llm_duration("process_optimization", time.time() - t0)  # 记录工艺优化耗时
    return {"process_analysis": process_info}  # 返回工艺分析结果


# ============================================================
# 节点3c：预测性维护 Agent
# ============================================================

async def predictive_maintenance_node(state: MfgAgentState) -> dict:  # 预测性维护节点（异步）
    """预测性维护节点：模拟传感器数据 + 查询维护计划。"""
    user_question = state["user_question"]  # 从状态中获取用户问题
    logger.info("预测维护Agent: 评估设备健康...")  # 记录评估开始日志
    t0 = time.time()  # 记录开始时间

    sensor_info = ""  # 初始化传感器信息为空
    maintenance_info = ""  # 初始化维护信息为空
    try:  # 尝试获取预测维护数据
        from app.agents.manufacturing.tools import (  # 导入预测维护工具函数
            check_maintenance_by_text,  # 维护计划查询函数
            simulate_sensor_by_text,  # 传感器数据模拟函数
        )
        sensor_info = simulate_sensor_by_text(user_question)  # 模拟传感器数据
        maintenance_info = check_maintenance_by_text(user_question)  # 查询维护计划
    except Exception as e:  # 捕获异常
        logger.warning("预测维护数据获取失败: %s", e)  # 记录警告日志

    _record_llm_duration("predictive_maintenance", time.time() - t0)  # 记录预测维护耗时
    return {"sensor_data": sensor_info, "maintenance_info": maintenance_info}  # 返回传感器数据和维护信息


# ============================================================
# 节点3d：工业知识问答 Agent
# ============================================================

async def knowledge_qa_node(state: MfgAgentState) -> dict:  # 知识问答节点（异步）
    """工业知识问答节点：无需特殊工具，直接由 answer 节点回答。"""
    logger.info("工业知识Agent: 准备知识问答上下文")  # 记录准备日志
    return {}  # 返回空字典，无需额外上下文


# ============================================================
# 节点4：工业回答 Agent（综合生成）
# ============================================================

async def mfg_answer_node(state: MfgAgentState) -> dict:  # 工业回答节点（异步）
    """工业回答节点：根据路由结果和所有上下文生成专业回答。"""
    action = state.get("action", MfgRouteAction.KNOWLEDGE)  # 从状态获取路由决策，默认为知识问答
    user_message = _build_mfg_answer_context(state)  # 构建回答上下文消息

    # 根据路由选择对应的领域 Prompt
    prompt_map = {  # 路由决策到提示词的映射表
        MfgRouteAction.FAULT: MFG_FAULT_DIAGNOSIS_PROMPT,  # 故障诊断提示词
        MfgRouteAction.PROCESS: MFG_PROCESS_OPTIMIZATION_PROMPT,  # 工艺优化提示词
        MfgRouteAction.PREDICT: MFG_PREDICTIVE_MAINTENANCE_PROMPT,  # 预测性维护提示词
        MfgRouteAction.KNOWLEDGE: MFG_KNOWLEDGE_QA_PROMPT,  # 知识问答提示词
    }
    system_prompt = prompt_map.get(action, MFG_ANSWER_SYSTEM_PROMPT)  # 根据路由获取对应提示词，默认为综合回答提示词

    logger.info("工业回答Agent: 生成回答（路由=%s）", action)  # 记录回答生成日志
    t0 = time.time()  # 记录开始时间

    llm = create_llm(temperature=0.3)  # 创建温度为0.3的LLM实例（适度创造性）
    messages = [  # 构建消息列表
        SystemMessage(system_prompt),  # 系统消息：领域提示词
        HumanMessage(content=user_message),  # 人类消息：用户上下文
    ]

    # 流式生成（供 astream_events 捕获 token）
    full = None  # 初始化完整响应为None
    async for chunk in llm.astream(messages):  # 异步流式生成
        full = chunk if full is None else full + chunk  # 累加chunk到完整响应

    answer = ""  # 初始化回答为空
    if full is not None:  # 如果有完整响应
        answer = getattr(full, "content", "")  # 提取响应内容

    _record_llm_duration("mfg_answer", time.time() - t0)  # 记录回答生成耗时
    return {"messages": [AIMessage(content=answer)]}  # 返回AI消息


# ============================================================
# 节点5：记忆存储
# ============================================================

async def mfg_store_memory_node(state: MfgAgentState) -> dict:  # 记忆存储节点（异步）
    """记忆存储节点：将本轮工业对话存入长期记忆。"""
    messages = state.get("messages", [])  # 从状态获取消息列表，默认为空
    user_question = state["user_question"]  # 从状态获取用户问题
    user_id = state.get("user_id", 0)  # 从状态获取用户ID，默认为0

    answer_text = ""  # 初始化回答文本为空
    for msg in reversed(messages):  # 逆序遍历消息列表
        if isinstance(msg, AIMessage):  # 如果是AI消息
            answer_text = msg.content  # 提取回答内容
            break  # 找到最新AI消息后退出循环

    if answer_text:  # 如果有回答文本
        try:  # 尝试存储对话
            from app.agents.runtime import get_vector_store  # 导入向量存储获取函数
            store = get_vector_store()  # 获取向量存储实例
            await store.store_conversation_turn(  # 异步存储对话轮次
                user_id=f"mfg_{user_id}" if user_id else "mfg_default",  # 构建用户ID标识
                question=user_question,  # 用户问题
                answer=answer_text,  # 回答文本
            )
            logger.info("工业记忆存储: 已存入长期记忆")  # 记录存储成功日志
        except Exception as e:  # 捕获异常
            logger.warning("工业记忆存储失败（不影响回答）: %s", e)  # 记录警告日志

    return {}  # 返回空字典


# ============================================================
# 条件路由
# ============================================================

def route_after_mfg_supervisor(  # 调度主管后的条件路由函数
    state: MfgAgentState,  # 工作流状态
) -> Literal["fault_diagnosis", "process_optimization", "predictive_maintenance", "knowledge_qa"]:  # 返回字面量类型
    """根据工业主管决策路由到对应子领域节点。"""
    action = state.get("action", MfgRouteAction.KNOWLEDGE)  # 从状态获取路由决策，默认为知识问答
    if action == MfgRouteAction.FAULT:  # 如果是故障诊断
        return "fault_diagnosis"  # 返回故障诊断节点名
    if action == MfgRouteAction.PROCESS:  # 如果是工艺优化
        return "process_optimization"  # 返回工艺优化节点名
    if action == MfgRouteAction.PREDICT:  # 如果是预测性维护
        return "predictive_maintenance"  # 返回预测性维护节点名
    return "knowledge_qa"  # 默认返回知识问答节点名


# ============================================================
# 辅助：构建工业回答上下文
# ============================================================

def _build_mfg_answer_context(state: MfgAgentState) -> str:  # 构建工业回答上下文函数
    """综合所有工业上下文构建回答 Agent 的用户消息。"""
    user_question = state["user_question"]  # 从状态获取用户问题
    context_parts = [f"用户问题：{user_question}"]  # 初始化上下文部分列表，包含用户问题

    history_context = state.get("history_context", "")  # 从状态获取对话历史，默认为空
    if history_context:  # 如果有对话历史
        context_parts.insert(0, f"对话历史：\n{history_context}")  # 将历史插入到列表开头

    # 图片视觉分析结果
    image_analysis = state.get("image_analysis", "")  # 从状态获取图片分析结果，默认为空
    if image_analysis:  # 如果有图片分析结果
        context_parts.append(f"\n[图片视觉分析]\n{image_analysis}")  # 添加图片分析到上下文

    fault_code_info = state.get("fault_code_info", "")  # 从状态获取故障码信息，默认为空
    if fault_code_info:  # 如果有故障码信息
        context_parts.append(f"\n[故障码查询结果]\n{fault_code_info}")  # 添加故障码信息到上下文

    equipment_params = state.get("equipment_params", "")  # 从状态获取设备参数，默认为空
    if equipment_params:  # 如果有设备参数
        context_parts.append(f"\n[设备参数]\n{equipment_params}")  # 添加设备参数到上下文

    sensor_data = state.get("sensor_data", "")  # 从状态获取传感器数据，默认为空
    if sensor_data:  # 如果有传感器数据
        context_parts.append(f"\n[传感器数据]\n{sensor_data}")  # 添加传感器数据到上下文

    maintenance_info = state.get("maintenance_info", "")  # 从状态获取维护信息，默认为空
    if maintenance_info:  # 如果有维护信息
        context_parts.append(f"\n[维护计划]\n{maintenance_info}")  # 添加维护信息到上下文

    process_analysis = state.get("process_analysis", "")  # 从状态获取工艺分析结果，默认为空
    if process_analysis:  # 如果有工艺分析结果
        context_parts.append(f"\n[工艺分析]\n{process_analysis}")  # 添加工艺分析到上下文

    rag_context = state.get("rag_context", "")  # 从状态获取RAG上下文，默认为空
    if rag_context:  # 如果有RAG上下文
        context_parts.append(f"\n{rag_context}")  # 添加RAG上下文到列表

    return "\n\n".join(context_parts)  # 用双换行拼接所有上下文部分并返回
