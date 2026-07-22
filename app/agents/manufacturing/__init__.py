"""工业智能制造垂直多智能体模块。

提供独立的 LangGraph 工业工作流，覆盖：
- 设备故障诊断（FAULT）
- 生产工艺优化（PROCESS）
- 预测性维护（PREDICT）
- 工业知识问答（KNOWLEDGE）
"""  # 模块级文档字符串，描述工业智能制造多智能体模块的职责和覆盖领域

from app.agents.manufacturing.graph import (  # 从工业图编排子模块导入工作流组件
    MfgGraphStreamEvent,  # 工业图执行产出的统一流事件数据类
    compile_mfg_graph,  # 编译工业 LangGraph 工作流的函数
    get_mfg_graph,  # 获取已编译工业图单例的函数
    run_mfg_agent_stream,  # 工业流式执行入口函数
)

__all__ = [  # 定义模块的公开接口列表
    "MfgGraphStreamEvent",  # 公开工业流事件数据类
    "compile_mfg_graph",  # 公开工业图编译函数
    "get_mfg_graph",  # 公开工业图获取函数
    "run_mfg_agent_stream",  # 公开工业流式执行函数
]
