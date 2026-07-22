"""会话业务逻辑：列表 / 消息 / 重命名 / 删除 / 导出 / Token 统计。"""  # 模块级文档字符串，描述会话业务逻辑

import json  # 导入JSON处理标准库

from app.core.exceptions import NotFoundError  # 导入未找到异常类
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.repositories import conversation_repo, message_repo  # 导入会话和消息数据访问仓库

logger = setup_logger("service.conversation")  # 创建名为service.conversation的日志记录器


async def list_conversations(user_id: int, conv_type: str = "general") -> list[dict]:  # 定义获取会话列表协程函数
    """获取用户指定类型的会话列表（按更新时间倒序）。"""  # 函数文档字符串
    return await conversation_repo.list_conversations(user_id, conv_type)  # 调用仓库层获取会话列表


async def get_messages(session_id: str, user_id: int) -> list[dict]:  # 定义获取消息协程函数
    """获取会话消息（校验用户归属）。"""  # 函数文档字符串
    await _assert_ownership(session_id, user_id)  # 校验会话归属
    return await message_repo.get_messages(session_id)  # 调用仓库层获取消息列表


async def rename_conversation(session_id: str, user_id: int, title: str) -> None:  # 定义重命名会话协程函数
    """重命名会话（校验归属）。"""  # 函数文档字符串
    ok = await conversation_repo.rename_conversation(session_id, user_id, title)  # 调用仓库层重命名
    if not ok:  # 如果重命名失败
        raise NotFoundError("会话不存在")  # 抛出未找到异常


async def delete_conversation(session_id: str, user_id: int) -> None:  # 定义删除会话协程函数
    """删除会话及其全部消息（校验归属）。"""  # 函数文档字符串
    await _assert_ownership(session_id, user_id)  # 校验会话归属
    await conversation_repo.delete_conversation(session_id)  # 调用仓库层删除会话
    logger.info("会话已删除: %s (user=%d)", session_id, user_id)  # 记录删除日志


async def export_conversation(session_id: str, user_id: int, fmt: str) -> str:  # 定义导出会话协程函数
    """
    导出会话为 Markdown 或 JSON 文本。

    Args:
        fmt: "markdown" 或 "json"
    """  # 函数文档字符串
    conv = await _assert_ownership(session_id, user_id)  # 校验归属并获取会话
    messages = await message_repo.get_messages(session_id)  # 获取会话所有消息

    if fmt == "json":  # 如果格式为JSON
        payload = {  # 构造JSON负载
            "session_id": session_id,  # 会话ID
            "title": conv["title"],  # 会话标题
            "created_at": conv["created_at"],  # 创建时间
            "messages": messages,  # 消息列表
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)  # 序列化为JSON字符串

    # Markdown 格式  # 内部注释，说明Markdown格式处理
    lines = [f"# {conv['title']}", "", f"> 创建时间：{conv['created_at']}", ""]  # 初始化Markdown行
    for msg in messages:  # 遍历消息
        role_label = "**用户**" if msg["role"] == "user" else "**助手**"  # 根据角色设置标签
        lines.append(f"## {role_label}")  # 添加角色标题
        lines.append("")  # 添加空行
        lines.append(msg["content"])  # 添加消息内容
        lines.append("")  # 添加空行
    return "\n".join(lines)  # 用换行符连接所有行


async def get_token_stats(user_id: int, days: int = 30) -> dict:  # 定义获取Token统计协程函数
    """获取用户的 Token 用量统计（累计 + 按日）。"""  # 函数文档字符串
    total = await message_repo.get_total_token_count(user_id)  # 获取累计Token用量
    daily = await message_repo.get_daily_token_stats(user_id, days)  # 获取按日Token统计
    return {"total_tokens": total, "daily": daily}  # 返回统计结果字典


async def _assert_ownership(session_id: str, user_id: int) -> dict:  # 定义校验会话归属的内部协程函数
    """校验会话归属，不存在则抛 NotFoundError。"""  # 函数文档字符串
    conv = await conversation_repo.get_conversation(session_id, user_id)  # 查询会话
    if conv is None:  # 如果会话不存在
        raise NotFoundError("会话不存在")  # 抛出未找到异常
    return conv  # 返回会话信息
