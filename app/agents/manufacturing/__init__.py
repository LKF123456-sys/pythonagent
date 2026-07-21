"""工业智能制造垂直多智能体模块。

提供独立的 LangGraph 工业工作流，覆盖：
- 设备故障诊断（FAULT）
- 生产工艺优化（PROCESS）
- 预测性维护（PREDICT）
- 工业知识问答（KNOWLEDGE）
"""

from app.agents.manufacturing.graph import (
    MfgGraphStreamEvent,
    compile_mfg_graph,
    get_mfg_graph,
    run_mfg_agent_stream,
)

__all__ = [
    "MfgGraphStreamEvent",
    "compile_mfg_graph",
    "get_mfg_graph",
    "run_mfg_agent_stream",
]
