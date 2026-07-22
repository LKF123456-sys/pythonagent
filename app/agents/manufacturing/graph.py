"""工业智能制造 LangGraph 工作流编排：astream_events 原生流式。

图结构：
START → mfg_preprocess → mfg_supervisor → ┬→ fault_diagnosis
                                           ├→ process_optimization
                                           ├→ predictive_maintenance
                                           └→ knowledge_qa
                                                ↓
                                           mfg_answer → mfg_store_memory → END
"""

import asyncio  # 导入异步IO模块，用于异步编程支持
from dataclasses import dataclass  # 导入dataclass装饰器，用于简化数据类定义
from typing import AsyncGenerator  # 导入异步生成器类型，用于类型注解

from langgraph.checkpoint.memory import MemorySaver  # 导入内存检查点保存器，用于图状态持久化
from langgraph.graph import END, START, StateGraph  # 导入LangGraph图相关组件：结束节点、起始节点、状态图

from app.core.logging import setup_logger  # 导入日志初始化函数，用于创建模块专属日志器
from app.core.tracing import get_tracer  # 导入链路追踪获取函数，用于创建追踪器
from app.agents.manufacturing.nodes import (  # 从工业节点模块导入所有节点函数和状态类型
    MfgAgentState,  # 工业智能体状态类型
    fault_diagnosis_node,  # 故障诊断节点函数
    knowledge_qa_node,  # 知识问答节点函数
    mfg_answer_node,  # 工业回答生成节点函数
    mfg_preprocess_node,  # 工业预处理节点函数
    mfg_store_memory_node,  # 记忆存储节点函数
    mfg_supervisor_node,  # 工业调度主管节点函数
    predictive_maintenance_node,  # 预测性维护节点函数
    process_optimization_node,  # 工艺优化节点函数
    route_after_mfg_supervisor,  # 主管节点后的条件路由函数
)
from app.agents.stream_parser import TagStreamParser  # 导入流式标签解析器，用于解析thinking/answer标签

logger = setup_logger("agents.manufacturing.graph")  # 创建工业图模块的专属日志器
tracer = get_tracer("app.agents.manufacturing.graph")  # 创建工业图模块的链路追踪器

# 节点名常量
NODE_MFG_PREPROCESS = "mfg_preprocess"  # 预处理节点名称常量
NODE_MFG_SUPERVISOR = "mfg_supervisor"  # 调度主管节点名称常量
NODE_MFG_FAULT = "fault_diagnosis"  # 故障诊断节点名称常量
NODE_MFG_PROCESS = "process_optimization"  # 工艺优化节点名称常量
NODE_MFG_PREDICT = "predictive_maintenance"  # 预测性维护节点名称常量
NODE_MFG_KNOWLEDGE = "knowledge_qa"  # 知识问答节点名称常量
NODE_MFG_ANSWER = "mfg_answer"  # 回答生成节点名称常量
NODE_MFG_STORE = "mfg_store_memory"  # 记忆存储节点名称常量

# 节点名集合（用于过滤 astream_events）
MFG_NODE_NAMES = {  # 工业图所有节点名称集合，用于流式事件过滤
    NODE_MFG_PREPROCESS,  # 预处理节点
    NODE_MFG_SUPERVISOR,  # 调度主管节点
    NODE_MFG_FAULT,  # 故障诊断节点
    NODE_MFG_PROCESS,  # 工艺优化节点
    NODE_MFG_PREDICT,  # 预测性维护节点
    NODE_MFG_KNOWLEDGE,  # 知识问答节点
    NODE_MFG_ANSWER,  # 回答生成节点
    NODE_MFG_STORE,  # 记忆存储节点
}

# 节点展示名（用于前端状态推送）
MFG_NODE_DISPLAY_NAMES = {  # 节点名称到中文展示名的映射，供前端状态展示使用
    NODE_MFG_PREPROCESS: "加载领域知识",  # 预处理节点展示名
    NODE_MFG_SUPERVISOR: "工业任务路由",  # 调度主管节点展示名
    NODE_MFG_FAULT: "故障诊断分析",  # 故障诊断节点展示名
    NODE_MFG_PROCESS: "工艺参数分析",  # 工艺优化节点展示名
    NODE_MFG_PREDICT: "设备健康评估",  # 预测性维护节点展示名
    NODE_MFG_KNOWLEDGE: "工业知识检索",  # 知识问答节点展示名
    NODE_MFG_ANSWER: "生成专业回答",  # 回答生成节点展示名
    NODE_MFG_STORE: "写入工业记忆",  # 记忆存储节点展示名
}


@dataclass  # 使用dataclass装饰器，自动生成__init__等方法
class MfgGraphStreamEvent:  # 工业图执行产出的统一流事件数据类
    """工业图执行产出的统一流事件。"""

    type: str  # 事件类型：status | thinking | token | done | error
    node: str = ""  # 当前节点名称，默认为空字符串
    content: str = ""  # 事件内容，默认为空字符串
    answer: str = ""  # 完整回答文本，默认为空字符串
    route: str = ""  # 路由决策结果，默认为空字符串
    token_count: int = 0  # token消耗数量，默认为0


# ============================================================
# 图构建与单例管理
# ============================================================

_mfg_graph = None  # 工业图单例变量，初始为None


def _build_mfg_workflow() -> StateGraph:  # 构建工业多智能体工作流（未编译）
    """构建工业多智能体工作流（未编译）。"""
    workflow = StateGraph(MfgAgentState)  # 创建以工业智能体状态为状态类型的状态图

    workflow.add_node(NODE_MFG_PREPROCESS, mfg_preprocess_node)  # 添加预处理节点
    workflow.add_node(NODE_MFG_SUPERVISOR, mfg_supervisor_node)  # 添加调度主管节点
    workflow.add_node(NODE_MFG_FAULT, fault_diagnosis_node)  # 添加故障诊断节点
    workflow.add_node(NODE_MFG_PROCESS, process_optimization_node)  # 添加工艺优化节点
    workflow.add_node(NODE_MFG_PREDICT, predictive_maintenance_node)  # 添加预测性维护节点
    workflow.add_node(NODE_MFG_KNOWLEDGE, knowledge_qa_node)  # 添加知识问答节点
    workflow.add_node(NODE_MFG_ANSWER, mfg_answer_node)  # 添加回答生成节点
    workflow.add_node(NODE_MFG_STORE, mfg_store_memory_node)  # 添加记忆存储节点

    # 边定义
    workflow.add_edge(START, NODE_MFG_PREPROCESS)  # 从起始节点到预处理节点的边
    workflow.add_edge(NODE_MFG_PREPROCESS, NODE_MFG_SUPERVISOR)  # 从预处理节点到调度主管节点的边
    workflow.add_conditional_edges(  # 添加条件边，根据调度主管决策路由到不同子领域节点
        NODE_MFG_SUPERVISOR,  # 条件边的起始节点为调度主管
        route_after_mfg_supervisor,  # 条件路由函数
        {  # 路由映射表：决策结果到目标节点
            "fault_diagnosis": NODE_MFG_FAULT,  # 故障诊断路由
            "process_optimization": NODE_MFG_PROCESS,  # 工艺优化路由
            "predictive_maintenance": NODE_MFG_PREDICT,  # 预测性维护路由
            "knowledge_qa": NODE_MFG_KNOWLEDGE,  # 知识问答路由
        },
    )
    # 所有子领域节点汇聚到回答节点
    workflow.add_edge(NODE_MFG_FAULT, NODE_MFG_ANSWER)  # 故障诊断节点到回答节点的边
    workflow.add_edge(NODE_MFG_PROCESS, NODE_MFG_ANSWER)  # 工艺优化节点到回答节点的边
    workflow.add_edge(NODE_MFG_PREDICT, NODE_MFG_ANSWER)  # 预测性维护节点到回答节点的边
    workflow.add_edge(NODE_MFG_KNOWLEDGE, NODE_MFG_ANSWER)  # 知识问答节点到回答节点的边
    workflow.add_edge(NODE_MFG_ANSWER, NODE_MFG_STORE)  # 回答节点到记忆存储节点的边
    workflow.add_edge(NODE_MFG_STORE, END)  # 记忆存储节点到结束节点的边

    return workflow  # 返回构建好的工作流对象


def compile_mfg_graph(checkpointer=None):  # 编译工业图单例
    """编译工业图单例。"""
    global _mfg_graph  # 声明使用全局工业图单例变量
    if checkpointer is None:  # 如果未提供检查点保存器
        checkpointer = MemorySaver()  # 默认使用内存检查点保存器
    _mfg_graph = _build_mfg_workflow().compile(checkpointer=checkpointer)  # 构建并编译工作流，传入检查点保存器
    logger.info("工业 LangGraph 工作流编译完成（checkpointer=%s）", type(checkpointer).__name__)  # 记录编译完成日志
    return _mfg_graph  # 返回编译后的图


def get_mfg_graph():  # 获取编译后的工业图单例
    """获取编译后的工业图单例（首次调用自动编译）。"""
    global _mfg_graph  # 声明使用全局工业图单例变量
    if _mfg_graph is None:  # 如果单例尚未初始化
        compile_mfg_graph()  # 调用编译函数初始化单例
    return _mfg_graph  # 返回工业图单例


def _make_mfg_initial_state(  # 构建工业工作流初始状态
    user_question: str,  # 用户问题文本
    history_context: str = "",  # 对话历史上下文，默认为空
    user_id: int = 0,  # 用户ID，默认为0
    image_path: str = "",  # 图片路径，默认为空
) -> dict:  # 返回状态字典
    """构建工业工作流初始状态。"""
    return {  # 返回初始状态字典
        "messages": [],  # 消息列表，初始为空
        "user_question": user_question,  # 用户问题
        "action": "",  # 路由决策，初始为空
        "image_path": image_path,  # 图片路径
        "image_analysis": "",  # 图片分析结果，初始为空
        "fault_code_info": "",  # 故障码信息，初始为空
        "equipment_params": "",  # 设备参数，初始为空
        "sensor_data": "",  # 传感器数据，初始为空
        "maintenance_info": "",  # 维护信息，初始为空
        "process_analysis": "",  # 工艺分析结果，初始为空
        "rag_context": "",  # RAG检索上下文，初始为空
        "history_context": history_context,  # 对话历史上下文
        "user_id": user_id,  # 用户ID
    }


# ============================================================
# 流式执行入口
# ============================================================

async def run_mfg_agent_stream(  # 工业流式执行入口函数（异步）
    user_question: str,  # 用户问题文本
    thread_id: str = "mfg_default",  # 会话线程ID，默认为mfg_default
    history_context: str = "",  # 对话历史上下文，默认为空
    user_id: int = 0,  # 用户ID，默认为0
    image_path: str = "",  # 图片路径，默认为空
) -> AsyncGenerator[MfgGraphStreamEvent, None]:  # 返回工业图流事件异步生成器
    """工业流式执行入口（包裹追踪 span）。"""
    with tracer.start_as_current_span("mfg_graph.stream") as span:  # 开启链路追踪span
        span.set_attribute("mfg_graph.thread_id", thread_id)  # 设置线程ID属性到追踪span
        span.set_attribute("mfg_graph.user_id", user_id)  # 设置用户ID属性到追踪span
        async for event in _run_mfg_stream_impl(  # 异步迭代内部流式实现生成的事件
            user_question, thread_id, history_context, user_id, image_path  # 透传所有参数
        ):
            yield event  # 向上层透传事件


async def _run_mfg_stream_impl(  # 工业流式执行内部实现（异步）
    user_question: str,  # 用户问题文本
    thread_id: str = "mfg_default",  # 会话线程ID，默认为mfg_default
    history_context: str = "",  # 对话历史上下文，默认为空
    user_id: int = 0,  # 用户ID，默认为0
    image_path: str = "",  # 图片路径，默认为空
) -> AsyncGenerator[MfgGraphStreamEvent, None]:  # 返回工业图流事件异步生成器
    """
    工业流式执行（astream_events version="v2"）。

    事件协议与通用管线一致：status / thinking / token / done / error
    """
    graph = get_mfg_graph()  # 获取编译后的工业图单例
    initial_state = _make_mfg_initial_state(user_question, history_context, user_id, image_path)  # 构建初始状态
    config = {"configurable": {"thread_id": thread_id}}  # 构建图执行配置，包含会话线程ID

    parser = TagStreamParser()  # 创建流式标签解析器实例
    current_node = ""  # 当前节点名称，初始为空
    answer_parts: list[str] = []  # 回答文本片段列表，用于拼接完整回答
    route_action = ""  # 路由决策结果，初始为空
    token_count = 0  # token消耗计数，初始为0

    def _drain_parser() -> list:  # 刷出解析器剩余内容的内部函数
        """刷出解析器剩余内容。"""
        out = []  # 初始化输出列表
        for ev in parser.flush():  # 遍历解析器刷出的所有剩余事件
            if ev.type == "thinking":  # 如果是思考事件
                out.append(MfgGraphStreamEvent(type="thinking", content=ev.content))  # 添加思考事件到输出
            elif ev.content:  # 否则如果有内容
                answer_parts.append(ev.content)  # 将内容追加到回答片段列表
                out.append(MfgGraphStreamEvent(type="token", content=ev.content))  # 添加token事件到输出
        return out  # 返回输出列表

    try:  # 开始异常捕获块
        async for event in graph.astream_events(  # 异步迭代图流式事件
            initial_state, config=config, version="v2"  # 传入初始状态、配置和事件版本
        ):
            event_type = event.get("event", "")  # 获取事件类型
            event_name = event.get("name", "")  # 获取事件名称

            # 节点开始 → 状态推送
            if event_type == "on_chain_start" and event_name in MFG_NODE_NAMES:  # 如果是节点开始事件且属于工业节点
                if event_name != current_node:  # 如果节点发生变化
                    current_node = event_name  # 更新当前节点
                    yield MfgGraphStreamEvent(  # 生成状态推送事件
                        type="status",  # 事件类型为状态
                        node=event_name,  # 节点名称
                        content=MFG_NODE_DISPLAY_NAMES.get(event_name, event_name),  # 节点中文展示名
                    )
                continue  # 跳过后续处理

            # 捕获 answer 节点的 LLM token 流
            if event_type == "on_chat_model_stream" and current_node == NODE_MFG_ANSWER:  # 如果是LLM流式事件且当前在回答节点
                chunk = event.get("data", {}).get("chunk")  # 获取流式数据块
                if chunk is None:  # 如果数据块为空
                    continue  # 跳过
                content = _chunk_text(chunk)  # 从数据块提取文本
                if not content:  # 如果无文本内容
                    continue  # 跳过
                for ev in parser.feed(content):  # 将文本喂给解析器并遍历输出事件
                    if ev.type == "thinking":  # 如果是思考事件
                        yield MfgGraphStreamEvent(type="thinking", content=ev.content)  # 生成思考事件
                    elif ev.content:  # 否则如果有内容
                        answer_parts.append(ev.content)  # 追加到回答片段列表
                        yield MfgGraphStreamEvent(type="token", content=ev.content)  # 生成token事件
                continue  # 跳过后续处理

            # 捕获 supervisor 路由决策
            if event_type == "on_chain_end" and event_name == NODE_MFG_SUPERVISOR:  # 如果是链结束事件且为调度主管节点
                action = _extract_action(event.get("data", {}).get("output"))  # 从输出中提取路由决策
                if action:  # 如果提取到决策
                    route_action = action  # 更新路由决策结果
                continue  # 跳过后续处理

            # 捕获 token 用量
            if event_type == "on_chat_model_end" and current_node == NODE_MFG_ANSWER:  # 如果是LLM结束事件且当前在回答节点
                usage = _extract_token_usage(event.get("data", {}).get("output"))  # 从输出中提取token用量
                if usage:  # 如果提取到用量
                    token_count = usage  # 更新token计数
                continue  # 跳过后续处理

        # 正常结束
        for ev in _drain_parser():  # 刷出解析器剩余内容并遍历
            yield ev  # 透传剩余事件

        yield MfgGraphStreamEvent(  # 生成完成事件
            type="done",  # 事件类型为完成
            answer="".join(answer_parts),  # 拼接完整回答
            route=route_action,  # 路由决策
            token_count=token_count,  # token消耗数
        )

    except asyncio.CancelledError:  # 捕获异步取消异常
        logger.info("工业流式生成被中断（thread=%s）", thread_id)  # 记录中断日志
        raise  # 重新抛出异常
    except Exception as e:  # 捕获其他异常
        logger.exception("工业图流式执行失败")  # 记录异常堆栈
        yield MfgGraphStreamEvent(type="error", content=f"处理失败：{e}")  # 生成错误事件


# ============================================================
# 辅助函数
# ============================================================

def _chunk_text(chunk) -> str:  # 从LLM流chunk中安全提取文本
    """从 LLM 流 chunk 中安全提取文本。"""
    content = getattr(chunk, "content", "")  # 获取chunk的content属性，默认为空字符串
    if isinstance(content, list):  # 如果content是列表类型
        parts = []  # 初始化部分列表
        for part in content:  # 遍历每个部分
            if isinstance(part, dict):  # 如果部分是字典类型
                parts.append(part.get("text", ""))  # 提取text字段，默认为空
            else:  # 否则
                parts.append(str(part))  # 转换为字符串
        return "".join(parts)  # 拼接并返回所有部分
    return content or ""  # 返回content，如果为None则返回空字符串


def _extract_action(output) -> str:  # 从supervisor节点输出中提取路由决策
    """从 supervisor 节点输出中提取路由决策。"""
    if isinstance(output, dict):  # 如果输出是字典类型
        action = output.get("action", "")  # 获取action字段，默认为空字符串
        if action:  # 如果存在action
            return action  # 返回action
    return ""  # 返回空字符串


def _extract_token_usage(output) -> int:  # 从LLM输出中提取token用量
    """从 LLM 输出中提取 token 用量。"""
    if output is None:  # 如果输出为None
        return 0  # 返回0
    usage = getattr(output, "usage_metadata", None)  # 获取usage_metadata属性
    if usage:  # 如果存在usage_metadata
        if isinstance(usage, dict):  # 如果是字典类型
            return int(usage.get("total_tokens", 0) or 0)  # 返回total_tokens字段值
        return int(getattr(usage, "total_tokens", 0) or 0)  # 返回对象的total_tokens属性值
    meta = getattr(output, "response_metadata", None)  # 获取response_metadata属性
    if isinstance(meta, dict):  # 如果是字典类型
        token_usage = meta.get("token_usage") or meta.get("usage") or {}  # 获取token用量字段
        if isinstance(token_usage, dict):  # 如果token用量是字典
            return int(token_usage.get("total_tokens", 0) or 0)  # 返回total_tokens字段值
    return 0  # 返回0
