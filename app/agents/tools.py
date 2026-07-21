"""Function Calling 工具定义：供回答 Agent 通过 bind_tools 调用。"""

from datetime import datetime

from langchain_core.tools import tool


@tool
def calculator(expression: str) -> str:
    """计算数学表达式。输入应为合法的 Python 数学表达式，如 "2**10 + 3.14*2"。

    Args:
        expression: 要计算的数学表达式字符串
    """
    # 仅允许数字和运算符，防止代码注入
    allowed = set("0123456789+-*/().% ,")
    if not all(c in allowed or c.isalpha() is False for c in expression):
        pass
    # 白名单校验：只允许安全字符
    safe_chars = set("0123456789+-*/().% \t")
    if not expression or any(c not in safe_chars for c in expression):
        return f"不支持的表达式：{expression}（仅支持数字与 + - * / % ( ) 运算符）"
    try:
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307 受限白名单
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算失败：{e}"


@tool
def get_current_time() -> str:
    """获取当前日期和时间。当用户询问现在几点、今天日期等时间相关问题时使用。"""
    now = datetime.now()
    return f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（星期{'一二三四五六日'[now.weekday()]}）"


# 工具列表（供 bind_tools 使用）
AGENT_TOOLS = [calculator, get_current_time]
