"""智能体模块：LangGraph 工作流、节点、提示词、工具、流解析器。"""  # 模块级文档字符串，描述本模块职责

from app.agents.graph import (  # 从 graph 子模块导入工作流编排相关组件
    GraphStreamEvent,  # 图执行产出的统一流事件数据类
    compile_graph,  # 编译 LangGraph 工作流的函数
    get_graph,  # 获取已编译图单例的函数
    run_agent,  # 非流式执行入口函数
    run_agent_stream,  # 流式执行入口函数
)
from app.agents.stream_parser import StreamEvent, TagStreamParser  # 从流解析器子模块导入流事件类和标签解析器类

__all__ = [  # 定义模块的公开接口列表，控制 from module import * 的行为
    "GraphStreamEvent",  # 公开流事件数据类
    "compile_graph",  # 公开图编译函数
    "get_graph",  # 公开图获取函数
    "run_agent",  # 公开非流式执行函数
    "run_agent_stream",  # 公开流式执行函数
    "StreamEvent",  # 公开解析器流事件类
    "TagStreamParser",  # 公开标签流解析器类
]
