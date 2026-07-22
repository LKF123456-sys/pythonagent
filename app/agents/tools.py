"""Function Calling 工具定义：供回答 Agent 通过 bind_tools 调用。"""  # 模块文档字符串：定义供回答Agent使用的Function Calling工具

from datetime import datetime  # 从datetime模块导入datetime类，用于获取当前时间

from langchain_core.tools import tool  # 从LangChain核心工具模块导入tool装饰器，用于将函数转换为工具


@tool  # 应用tool装饰器，将函数注册为LangChain工具
def calculator(expression: str) -> str:  # 定义计算器工具函数，接收表达式字符串，返回结果字符串
    """计算数学表达式。输入应为合法的 Python 数学表达式，如 "2**10 + 3.14*2"。

    Args:
        expression: 要计算的数学表达式字符串
    """
    # 仅允许数字和运算符，防止代码注入
    allowed = set("0123456789+-*/().% ,")  # 定义允许的字符集合（含逗号和空格）
    if not all(c in allowed or c.isalpha() is False for c in expression):  # 检查表达式字符是否在允许范围内
        pass  # 此处仅做检查占位，实际校验在下方白名单中完成
    # 白名单校验：只允许安全字符
    safe_chars = set("0123456789+-*/().% \t")  # 定义安全字符集合（数字、运算符、空格、制表符）
    if not expression or any(c not in safe_chars for c in expression):  # 如果表达式为空或包含非安全字符
        return f"不支持的表达式：{expression}（仅支持数字与 + - * / % ( ) 运算符）"  # 返回不支持提示
    try:  # 开始异常捕获块
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307 受限白名单  # 在受限环境下计算表达式（禁用内置函数）
        return f"{expression} = {result}"  # 返回表达式和计算结果
    except Exception as e:  # 捕获计算异常
        return f"计算失败：{e}"  # 返回失败信息


@tool  # 应用tool装饰器，将函数注册为LangChain工具
def get_current_time() -> str:  # 定义获取当前时间工具函数，无参数，返回时间字符串
    """获取当前日期和时间。当用户询问现在几点、今天日期等时间相关问题时使用。"""
    now = datetime.now()  # 获取当前日期时间
    return f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（星期{'一二三四五六日'[now.weekday()]}）"  # 格式化返回当前时间和星期几


# 工具列表（供 bind_tools 使用）
AGENT_TOOLS = [calculator, get_current_time]  # 定义工具列表，包含计算器和时间查询两个工具，供bind_tools使用
