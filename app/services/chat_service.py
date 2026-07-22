"""聊天业务编排：会话管理 + 历史上下文构建 + 图调用 + 持久化。"""  # 模块级文档字符串，描述聊天业务编排

import asyncio  # 导入异步IO标准库
import os  # 导入操作系统接口标准库
import uuid  # 导入UUID生成标准库
from typing import AsyncGenerator, Optional  # 从typing导入异步生成器和可选类型

from app.core.config import get_settings  # 导入配置获取函数
from app.core.constants import MessageRole  # 导入消息角色常量
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.core.security import validate_upload_path  # 导入上传路径校验函数
from app.agents.graph import GraphStreamEvent, run_agent, run_agent_stream  # 导入图流事件类型和运行函数
from app.agents.llm import compress_context, generate_title  # 导入上下文压缩和标题生成函数
from app.models.chat import ChatResponse  # 导入聊天响应模型
from app.repositories import conversation_repo, message_repo  # 导入会话和消息数据访问仓库

logger = setup_logger("service.chat")  # 创建名为service.chat的日志记录器


# ============================================================  # 分隔注释
# 内部辅助  # 说明该部分为内部辅助函数
# ============================================================  # 分隔注释

def _resolve_image_path(image_filename: str) -> str:  # 定义解析图片路径的内部函数
    """将已上传图片的文件名解析为安全绝对路径（路径遍历防护）。"""  # 函数文档字符串
    if not image_filename:  # 如果文件名为空
        return ""  # 返回空字符串
    settings = get_settings()  # 获取配置
    path = os.path.join(settings.UPLOAD_FOLDER, image_filename)  # 拼接完整路径
    if not validate_upload_path(path, settings.UPLOAD_FOLDER):  # 校验路径合法性
        logger.warning("检测到非法图片路径: %s", image_filename)  # 记录警告日志
        return ""  # 返回空字符串表示非法
    return path if os.path.exists(path) else ""  # 文件存在则返回路径，否则空


async def _build_history_context(session_id: str) -> tuple[str, bool]:  # 定义构建历史上下文的内部协程函数
    """
    从数据库构建历史上下文（不含当前轮）。

    Returns:
        (history_context, is_first_turn)
    """  # 函数文档字符串
    settings = get_settings()  # 获取配置
    messages = await message_repo.get_messages(session_id, limit=settings.MAX_HISTORY_TURNS * 2)  # 获取历史消息
    if not messages:  # 如果没有历史消息
        return "", True  # 返回空上下文和"首轮"标记

    lines = []  # 初始化历史文本行列表
    for msg in messages:  # 遍历每条消息
        role_label = "用户" if msg["role"] == MessageRole.USER.value else "助手"  # 根据角色设置标签
        lines.append(f"{role_label}: {msg['content']}")  # 拼接角色和内容为一行
    history_text = "\n".join(lines)  # 用换行符连接所有行

    # 上下文压缩（超阈值时 LLM 摘要，替代简单截断）  # 内部注释说明压缩逻辑
    history_context = await compress_context(history_text)  # 调用LLM压缩历史上下文
    return history_context, False  # 返回压缩后的上下文和"非首轮"标记


async def _ensure_conversation(session_id: str, user_id: int, question: str) -> None:  # 定义确保会话存在的内部协程函数
    """确保会话记录存在（首轮创建，标题暂用问题截断）。"""  # 函数文档字符串
    existing = await conversation_repo.get_conversation(session_id, user_id)  # 查询会话是否存在
    if existing is None:  # 如果会话不存在
        title = question[:20] + ("..." if len(question) > 20 else "")  # 截取问题前20字符作为标题
        await conversation_repo.create_conversation(session_id, user_id, title)  # 创建新会话


async def _set_conversation_title(session_id: str, user_id: int, question: str) -> None:  # 定义异步生成标题的内部协程函数
    """异步生成并更新会话标题（首轮结束后调用）。"""  # 函数文档字符串
    try:  # 尝试生成标题
        title = await generate_title(question)  # 调用LLM生成会话标题
        await conversation_repo.rename_conversation(session_id, user_id, title)  # 更新会话标题
        logger.info("会话标题已生成: %s -> %s", session_id, title)  # 记录成功日志
    except Exception as e:  # 捕获异常
        logger.warning("会话标题生成失败（不影响主流程）: %s", e)  # 记录警告日志


async def _finalize_turn(  # 定义一轮对话结束后的持久化内部协程函数
    session_id: str,  # 会话ID
    user_id: int,  # 用户ID
    question: str,  # 用户问题
    event: GraphStreamEvent,  # 完成事件
    is_first_turn: bool,  # 是否首轮
) -> None:  # 无返回值
    """一轮对话结束后的持久化：存助手消息、更新时间、异步生成标题。"""  # 函数文档字符串
    if event.answer:  # 如果有回答内容
        await message_repo.add_message(  # 添加助手消息到数据库
            session_id, MessageRole.ASSISTANT.value, event.answer, event.token_count  # 会话ID、角色、内容、token数
        )
    await conversation_repo.update_conversation_time(session_id)  # 更新会话活跃时间
    if is_first_turn:  # 如果是首轮对话
        asyncio.create_task(_set_conversation_title(session_id, user_id, question))  # 异步生成会话标题


# ============================================================  # 分隔注释
# 流式聊天（WebSocket 消费）  # 说明该部分为流式聊天逻辑
# ============================================================  # 分隔注释

async def chat_stream(  # 定义流式聊天协程函数
    user_id: int,  # 用户ID
    question: str,  # 用户问题
    session_id: Optional[str] = None,  # 可选会话ID
    image_filename: str = "",  # 图片文件名，默认空
) -> AsyncGenerator[GraphStreamEvent, None]:  # 返回异步生成器
    """
    流式聊天编排。

    产出 GraphStreamEvent 流（status/thinking/token/done/error），
    并在 done 事件时完成消息持久化与标题生成。
    """  # 函数文档字符串
    if not session_id:  # 如果未提供会话ID
        session_id = uuid.uuid4().hex  # 生成新的会话ID

    image_path = _resolve_image_path(image_filename)  # 解析图片路径
    history_context, is_first_turn = await _build_history_context(session_id)  # 构建历史上下文
    await _ensure_conversation(session_id, user_id, question)  # 确保会话存在
    await message_repo.add_message(session_id, MessageRole.USER.value, question, image_filename=image_filename)  # 存储用户消息

    async for event in run_agent_stream(  # 异步迭代智能体产生的流事件
        user_question=question,  # 用户问题
        thread_id=session_id,  # 线程ID
        image_path=image_path,  # 图片路径
        history_context=history_context,  # 历史上下文
        is_first_turn=is_first_turn,  # 是否首轮
        user_id=user_id,  # 用户ID
    ):
        if event.type == "done":  # 如果是完成事件
            await _finalize_turn(session_id, user_id, question, event, is_first_turn)  # 执行持久化
        yield event  # 产出事件给调用方


# ============================================================  # 分隔注释
# 非流式聊天（REST 消费）  # 说明该部分为非流式聊天逻辑
# ============================================================  # 分隔注释

async def chat_non_stream(  # 定义非流式聊天协程函数
    user_id: int,  # 用户ID
    question: str,  # 用户问题
    session_id: Optional[str] = None,  # 可选会话ID
    image_filename: str = "",  # 图片文件名，默认空
) -> ChatResponse:  # 返回聊天响应模型
    """非流式聊天（ainvoke），返回完整回答。"""  # 函数文档字符串
    if not session_id:  # 如果未提供会话ID
        session_id = uuid.uuid4().hex  # 生成新的会话ID

    image_path = _resolve_image_path(image_filename)  # 解析图片路径
    history_context, is_first_turn = await _build_history_context(session_id)  # 构建历史上下文
    await _ensure_conversation(session_id, user_id, question)  # 确保会话存在
    await message_repo.add_message(session_id, MessageRole.USER.value, question, image_filename=image_filename)  # 存储用户消息

    try:  # 尝试调用智能体
        answer = await run_agent(  # 调用非流式智能体运行函数
            user_question=question,  # 用户问题
            thread_id=session_id,  # 线程ID
            image_path=image_path,  # 图片路径
            history_context=history_context,  # 历史上下文
            is_first_turn=is_first_turn,  # 是否首轮
            user_id=user_id,  # 用户ID
        )
    except Exception as e:  # 捕获异常
        logger.exception("非流式聊天失败")  # 记录异常日志
        return ChatResponse(answer="", session_id=session_id, error=str(e))  # 返回错误响应

    await message_repo.add_message(session_id, MessageRole.ASSISTANT.value, answer)  # 存储助手回答
    await conversation_repo.update_conversation_time(session_id)  # 更新会话活跃时间
    if is_first_turn:  # 如果是首轮对话
        asyncio.create_task(_set_conversation_title(session_id, user_id, question))  # 异步生成会话标题

    return ChatResponse(answer=answer, session_id=session_id)  # 返回成功响应
