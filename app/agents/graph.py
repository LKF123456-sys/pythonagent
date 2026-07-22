"""LangGraph 工作流编排：astream_events 原生流式。

核心修复（Phase 2.3）：
- 废弃旧版手动逐节点执行（run_agent_stream 脱离 LangGraph 编排的问题）
- 使用 LangGraph 原生 graph.astream_events(version="v2")：
  - 监听 on_chain_start 事件 → 推送节点状态
  - 捕获 answer 节点的 on_chat_model_stream → 经 TagStreamParser 产出 token 流
  - 保留检查点恢复 + 状态追踪能力，节点逻辑单一维护点
"""

import asyncio  # 导入异步IO模块，用于异步编程支持
from dataclasses import dataclass  # 导入dataclass装饰器，用于简化数据类定义
from typing import AsyncGenerator, Optional  # 从typing导入异步生成器类型和可选类型，用于类型注解

from langgraph.checkpoint.memory import MemorySaver  # 导入LangGraph内存检查点保存器，用于工作流状态持久化
from langgraph.graph import END, START, StateGraph  # 导入LangGraph图的END、START常量和StateGraph类，用于构建状态图

from app.core.constants import (  # 从核心常量模块导入各节点名称常量
    NODE_ANSWER,  # 回答节点名称常量
    NODE_HUMAN_REVIEW,  # 人工审批节点名称常量
    NODE_PREPROCESS,  # 预处理节点名称常量
    NODE_RAG,  # RAG检索节点名称常量
    NODE_SEARCH,  # 搜索节点名称常量
    NODE_STORE_MEMORY,  # 记忆存储节点名称常量
    NODE_SUPERVISOR,  # 调度主管节点名称常量
)
from app.core.logging import setup_logger  # 导入日志设置函数，用于创建模块专用logger
from app.core.tracing import get_tracer  # 导入追踪器获取函数，用于分布式链路追踪
from app.agents.nodes import (  # 从节点模块导入状态类和各节点处理函数
    AgentState,  # 工作流状态类型定义
    answer_node,  # 回答节点处理函数
    human_review_node,  # 人工审批节点处理函数
    preprocess_node,  # 预处理节点处理函数
    rag_node,  # RAG检索节点处理函数
    route_after_supervisor,  # 主管节点后的条件路由函数
    search_node,  # 搜索节点处理函数
    store_memory_node,  # 记忆存储节点处理函数
    supervisor_node,  # 调度主管节点处理函数
)
from app.agents.stream_parser import TagStreamParser  # 导入标签流解析器，用于解析thinking/answer标签

logger = setup_logger("agents.graph")  # 创建本模块专用的日志记录器，名称为agents.graph
tracer = get_tracer("app.agents.graph")  # 创建本模块专用的追踪器，用于链路追踪

# 节点名集合（用于过滤 astream_events 中的节点级事件）
NODE_NAMES = {  # 定义节点名称集合，用于事件过滤
    NODE_PREPROCESS,  # 包含预处理节点
    NODE_SUPERVISOR,  # 包含调度主管节点
    NODE_SEARCH,  # 包含搜索节点
    NODE_RAG,  # 包含RAG检索节点
    NODE_HUMAN_REVIEW,  # 包含人工审批节点
    NODE_ANSWER,  # 包含回答节点
    NODE_STORE_MEMORY,  # 包含记忆存储节点
}

# 节点展示名（用于前端状态推送）
NODE_DISPLAY_NAMES = {  # 定义节点展示名称字典，将内部节点名映射为用户可读的中文展示名
    NODE_PREPROCESS: "理解问题",  # 预处理节点展示为"理解问题"
    NODE_SUPERVISOR: "任务路由",  # 主管节点展示为"任务路由"
    NODE_SEARCH: "联网搜索",  # 搜索节点展示为"联网搜索"
    NODE_RAG: "知识检索",  # RAG节点展示为"知识检索"
    NODE_HUMAN_REVIEW: "人工审批",  # 人工审批节点展示为"人工审批"
    NODE_ANSWER: "生成回答",  # 回答节点展示为"生成回答"
    NODE_STORE_MEMORY: "写入记忆",  # 记忆节点展示为"写入记忆"
}


@dataclass  # 应用dataclass装饰器，自动生成__init__等方法
class GraphStreamEvent:  # 定义图流事件数据类
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

_graph = None  # 全局图单例变量，初始为None，首次使用时编译填充


def _build_workflow() -> StateGraph:  # 定义构建工作流的私有函数，返回StateGraph实例
    """构建多智能体工作流（未编译）。"""
    workflow = StateGraph(AgentState)  # 以AgentState为状态类型创建状态图

    workflow.add_node(NODE_PREPROCESS, preprocess_node)  # 添加预处理节点
    workflow.add_node(NODE_SUPERVISOR, supervisor_node)  # 添加调度主管节点
    workflow.add_node(NODE_SEARCH, search_node)  # 添加搜索节点
    workflow.add_node(NODE_RAG, rag_node)  # 添加RAG检索节点
    workflow.add_node(NODE_HUMAN_REVIEW, human_review_node)  # 添加人工审批节点
    workflow.add_node(NODE_ANSWER, answer_node)  # 添加回答节点
    workflow.add_node(NODE_STORE_MEMORY, store_memory_node)  # 添加记忆存储节点

    workflow.add_edge(START, NODE_PREPROCESS)  # 添加从起点到预处理节点的边
    workflow.add_edge(NODE_PREPROCESS, NODE_SUPERVISOR)  # 添加从预处理到主管节点的边
    workflow.add_conditional_edges(  # 添加条件边，根据主管决策路由到不同节点
        NODE_SUPERVISOR,  # 条件边的源节点为调度主管
        route_after_supervisor,  # 路由判定函数
        {  # 路由映射字典
            "search": NODE_SEARCH,  # search 路由到搜索节点
            "rag": NODE_RAG,  # rag 路由到RAG节点
            "answer": NODE_HUMAN_REVIEW,  # answer 路由到人工审批节点（再由审批节点到回答节点）
        },
    )
    workflow.add_edge(NODE_SEARCH, NODE_HUMAN_REVIEW)  # 添加从搜索节点到人工审批节点的边
    workflow.add_edge(NODE_RAG, NODE_HUMAN_REVIEW)  # 添加从RAG节点到人工审批节点的边
    workflow.add_edge(NODE_HUMAN_REVIEW, NODE_ANSWER)  # 添加从人工审批节点到回答节点的边
    workflow.add_edge(NODE_ANSWER, NODE_STORE_MEMORY)  # 添加从回答节点到记忆存储节点的边
    workflow.add_edge(NODE_STORE_MEMORY, END)  # 添加从记忆存储节点到终点的边

    return workflow  # 返回构建好的工作流


def compile_graph(checkpointer=None):  # 定义编译图函数，可注入检查点保存器
    """编译图单例。checkpointer 可注入（默认 MemorySaver）。"""
    global _graph  # 声明使用全局_graph变量
    if checkpointer is None:  # 如果未提供检查点保存器
        checkpointer = MemorySaver()  # 使用默认的内存检查点保存器
    _graph = _build_workflow().compile(checkpointer=checkpointer)  # 构建并编译工作流，注入检查点保存器
    logger.info("LangGraph 工作流编译完成（checkpointer=%s）", type(checkpointer).__name__)  # 记录编译完成日志
    return _graph  # 返回编译后的可执行图


def get_graph():  # 定义获取图单例函数
    """获取编译后的图单例（首次调用自动编译）。"""
    global _graph  # 声明使用全局_graph变量
    if _graph is None:  # 如果图尚未编译
        compile_graph()  # 编译图
    return _graph  # 返回图单例


def _make_initial_state(  # 定义构建初始状态的私有函数
    user_question: str,  # 用户问题文本
    image_path: str = "",  # 图片路径，默认为空
    history_context: str = "",  # 历史对话上下文，默认为空
    is_first_turn: bool = False,  # 是否为首次对话，默认为False
    user_id: int = 0,  # 用户ID，默认为0
) -> dict:  # 返回字典类型
    """构建工作流初始状态。"""
    return {  # 返回初始状态字典
        "messages": [],  # 消息列表初始为空
        "user_question": user_question,  # 设置用户问题
        "action": "",  # 路由动作初始为空
        "image_path": image_path,  # 设置图片路径
        "image_analysis": "",  # 图片分析结果初始为空
        "search_results": "",  # 搜索结果初始为空
        "rag_context": "",  # RAG上下文初始为空
        "long_term_memories": "",  # 长期记忆初始为空
        "history_context": history_context,  # 设置历史对话上下文
        "is_first_turn": is_first_turn,  # 设置是否为首次对话
        "user_id": user_id,  # 设置用户ID
    }


# ============================================================
# 非流式执行入口
# ============================================================

async def run_agent(  # 定义非流式执行入口异步函数
    user_question: str,  # 用户问题文本
    thread_id: str = "default",  # 会话线程ID，用于检查点恢复，默认为"default"
    image_path: str = "",  # 图片路径，默认为空
    history_context: str = "",  # 历史对话上下文，默认为空
    is_first_turn: bool = False,  # 是否为首次对话，默认为False
    user_id: int = 0,  # 用户ID，默认为0
) -> str:  # 返回字符串类型的最终回答
    """非流式执行（ainvoke），返回最终回答文本。"""
    graph = get_graph()  # 获取编译后的图单例
    initial_state = _make_initial_state(  # 构建初始状态
        user_question, image_path, history_context, is_first_turn, user_id  # 传入所有参数
    )
    config = {"configurable": {"thread_id": thread_id}}  # 构建配置，指定线程ID用于检查点恢复
    with tracer.start_as_current_span("graph.invoke") as span:  # 开启追踪span
        span.set_attribute("graph.thread_id", thread_id)  # 设置span属性：线程ID
        span.set_attribute("graph.user_id", user_id)  # 设置span属性：用户ID
        result = await graph.ainvoke(initial_state, config=config)  # 异步调用图执行，返回最终状态

    for msg in reversed(result.get("messages", [])):  # 逆序遍历结果中的消息列表
        if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):  # 找到第一条有内容的AI消息
            return msg.content  # 返回AI消息内容作为最终回答
    return ""  # 若没有AI消息则返回空字符串


# ============================================================
# 流式执行入口（astream_events 原生流式）
# ============================================================

async def run_agent_stream(  # 定义流式执行入口异步生成器函数
    user_question: str,  # 用户问题文本
    thread_id: str = "default",  # 会话线程ID，默认为"default"
    image_path: str = "",  # 图片路径，默认为空
    history_context: str = "",  # 历史对话上下文，默认为空
    is_first_turn: bool = False,  # 是否为首次对话，默认为False
    user_id: int = 0,  # 用户ID，默认为0
) -> AsyncGenerator[GraphStreamEvent, None]:  # 返回GraphStreamEvent的异步生成器
    """流式执行入口（包裹追踪 span，具体逻辑委托给 _run_agent_stream_impl）。"""
    with tracer.start_as_current_span("graph.stream") as span:  # 开启流式执行追踪span
        span.set_attribute("graph.thread_id", thread_id)  # 设置span属性：线程ID
        span.set_attribute("graph.user_id", user_id)  # 设置span属性：用户ID
        async for event in _run_agent_stream_impl(  # 异步迭代实际实现函数产出的事件
            user_question, thread_id, image_path, history_context, is_first_turn, user_id  # 传入所有参数
        ):
            yield event  # 将事件向上游传递


async def _run_agent_stream_impl(  # 定义流式执行的实际实现函数
    user_question: str,  # 用户问题文本
    thread_id: str = "default",  # 会话线程ID，默认为"default"
    image_path: str = "",  # 图片路径，默认为空
    history_context: str = "",  # 历史对话上下文，默认为空
    is_first_turn: bool = False,  # 是否为首次对话，默认为False
    user_id: int = 0,  # 用户ID，默认为0
) -> AsyncGenerator[GraphStreamEvent, None]:  # 返回GraphStreamEvent的异步生成器
    """
    流式执行（astream_events version="v2"）。

    事件协议：
    - status   : 节点开始（node + 展示名）
    - thinking : <thinking> 标签内的思考内容
    - token    : 回答正文 token
    - done     : 完成（携带完整 answer / route / token_count）
    - error    : 执行异常
    """
    graph = get_graph()  # 获取编译后的图单例
    initial_state = _make_initial_state(  # 构建初始状态
        user_question, image_path, history_context, is_first_turn, user_id  # 传入所有参数
    )
    config = {"configurable": {"thread_id": thread_id}}  # 构建配置，指定线程ID用于检查点恢复

    parser = TagStreamParser()  # 创建标签流解析器实例，用于解析thinking/answer标签
    current_node = ""  # 当前正在执行的节点名，初始为空
    answer_parts: list[str] = []  # 回答文本片段列表，用于累积完整回答
    route_action = ""  # 主管路由决策，初始为空
    token_count = 0  # LLM token用量计数，初始为0

    def _drain_parser() -> list:  # 定义刷出解析器剩余内容的内部函数
        """刷出解析器剩余内容，返回待发送事件。"""
        out = []  # 待发送事件列表
        for ev in parser.flush():  # 调用解析器的flush方法获取剩余事件
            if ev.type == "thinking":  # 如果是思考事件
                out.append(GraphStreamEvent(type="thinking", content=ev.content))  # 包装为thinking事件加入列表
            elif ev.content:  # 如果是token事件且有内容
                answer_parts.append(ev.content)  # 累积回答文本
                out.append(GraphStreamEvent(type="token", content=ev.content))  # 包装为token事件加入列表
        return out  # 返回待发送事件列表

    try:  # 开始异常捕获块
        async for event in graph.astream_events(  # 异步迭代图的事件流
            initial_state, config=config, version="v2"  # 使用v2版本的事件流协议
        ):
            event_type = event.get("event", "")  # 获取事件类型
            event_name = event.get("name", "")  # 获取事件名称

            # 节点开始 → 状态推送（按节点名去重）
            if event_type == "on_chain_start" and event_name in NODE_NAMES:  # 如果是节点开始事件且节点名在集合中
                if event_name != current_node:  # 如果节点名与当前节点不同（去重）
                    current_node = event_name  # 更新当前节点名
                    yield GraphStreamEvent(  # 产出状态事件
                        type="status",  # 事件类型为status
                        node=event_name,  # 设置节点名
                        content=NODE_DISPLAY_NAMES.get(event_name, event_name),  # 获取节点展示名，回退为节点名
                    )
                continue  # 跳过后续处理，处理下一个事件

            # 仅捕获 answer 节点的 LLM token 流
            if event_type == "on_chat_model_stream" and current_node == NODE_ANSWER:  # 如果是聊天模型流事件且当前在回答节点
                chunk = event.get("data", {}).get("chunk")  # 获取数据中的chunk
                if chunk is None:  # 如果chunk为None
                    continue  # 跳过
                content = _chunk_text(chunk)  # 从chunk中提取文本内容
                if not content:  # 如果没有内容
                    continue  # 跳过
                for ev in parser.feed(content):  # 将内容喂给解析器，遍历产出的事件
                    if ev.type == "thinking":  # 如果是思考事件
                        yield GraphStreamEvent(type="thinking", content=ev.content)  # 产出thinking事件
                    elif ev.content:  # 如果是token事件且有内容
                        answer_parts.append(ev.content)  # 累积回答文本
                        yield GraphStreamEvent(type="token", content=ev.content)  # 产出token事件
                continue  # 跳过后续处理，处理下一个事件

            # 捕获 supervisor 路由决策
            if event_type == "on_chain_end" and event_name == NODE_SUPERVISOR:  # 如果是链结束事件且为主管节点
                action = _extract_action(event.get("data", {}).get("output"))  # 从输出中提取路由动作
                if action:  # 如果提取到动作
                    route_action = action  # 更新路由决策
                continue  # 跳过后续处理

            # 捕获 answer 节点 LLM 的 token 用量
            if event_type == "on_chat_model_end" and current_node == NODE_ANSWER:  # 如果是聊天模型结束事件且当前在回答节点
                usage = _extract_token_usage(event.get("data", {}).get("output"))  # 从输出中提取token用量
                if usage:  # 如果提取到用量
                    token_count = usage  # 更新token计数
                continue  # 跳过后续处理

        # 正常结束：刷出解析器剩余内容
        for ev in _drain_parser():  # 遍历解析器剩余事件
            yield ev  # 产出事件

        yield GraphStreamEvent(  # 产出完成事件
            type="done",  # 事件类型为done
            answer="".join(answer_parts),  # 拼接完整回答
            route=route_action,  # 设置路由决策
            token_count=token_count,  # 设置token用量
        )

    except asyncio.CancelledError:  # 捕获异步任务取消异常
        # 用户中断生成：记录日志并向上传播（WebSocket 层负责取消）
        logger.info("流式生成被中断（thread=%s）", thread_id)  # 记录中断日志
        raise  # 重新抛出异常，向上传播
    except Exception as e:  # 捕获其他所有异常
        logger.exception("图流式执行失败")  # 记录异常堆栈日志
        yield GraphStreamEvent(type="error", content=f"处理失败：{e}")  # 产出错误事件


# ============================================================
# 辅助提取函数
# ============================================================

def _chunk_text(chunk) -> str:  # 定义从LLM流chunk中提取文本的私有函数
    """从 LLM 流 chunk 中安全提取文本内容。"""
    content = getattr(chunk, "content", "")  # 获取chunk的content属性，默认为空字符串
    if isinstance(content, list):  # 如果内容是列表类型（多模态/分块内容）
        # 多模态/分块内容：拼接其中的文本部分
        parts = []  # 文本片段列表
        for part in content:  # 遍历每个部分
            if isinstance(part, dict):  # 如果部分是字典
                parts.append(part.get("text", ""))  # 提取text字段，默认为空
            else:  # 否则
                parts.append(str(part))  # 转换为字符串后加入列表
        return "".join(parts)  # 拼接所有文本片段返回
    return content or ""  # 返回内容，若为空则返回空字符串


def _extract_action(output) -> str:  # 定义从supervisor输出提取路由决策的私有函数
    """从 supervisor 节点输出中提取路由决策。"""
    if isinstance(output, dict):  # 如果输出是字典类型
        action = output.get("action", "")  # 提取action字段，默认为空
        if action:  # 如果提取到动作
            return action  # 返回动作
    return ""  # 返回空字符串


def _extract_token_usage(output) -> int:  # 定义从LLM输出提取token用量的私有函数
    """从 LLM 输出中提取 token 用量（兼容多种返回结构）。"""
    if output is None:  # 如果输出为None
        return 0  # 返回0
    usage = getattr(output, "usage_metadata", None)  # 获取usage_metadata属性
    if usage:  # 如果存在用量元数据
        if isinstance(usage, dict):  # 如果是字典
            return int(usage.get("total_tokens", 0) or 0)  # 返回total_tokens字段值
        return int(getattr(usage, "total_tokens", 0) or 0)  # 否则从对象属性获取
    meta = getattr(output, "response_metadata", None)  # 获取response_metadata属性
    if isinstance(meta, dict):  # 如果是字典
        token_usage = meta.get("token_usage") or meta.get("usage") or {}  # 尝试获取token_usage或usage字段
        if isinstance(token_usage, dict):  # 如果token用量是字典
            return int(token_usage.get("total_tokens", 0) or 0)  # 返回total_tokens字段值
    return 0  # 都未找到则返回0
