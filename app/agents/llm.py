"""LLM 实例管理 + 路由缓存 + 标题生成 + 上下文压缩。"""

import asyncio  # 导入异步IO模块，用于异步编程支持
import hashlib  # 导入哈希模块，用于生成缓存键的MD5哈希
import time  # 导入时间模块，用于获取时间戳判断缓存过期
from typing import Optional  # 从typing导入Optional类型，用于可选类型注解

from langchain_openai import ChatOpenAI  # 导入LangChain的OpenAI聊天模型类
from langchain_core.messages import HumanMessage, SystemMessage  # 导入LangChain核心消息类型：人类消息和系统消息

from app.core.config import get_settings  # 导入配置获取函数，用于读取应用配置
from app.core.constants import CONTEXT_COMPRESS_THRESHOLD, ROUTE_CACHE_TTL_SECONDS, RouteAction  # 导入上下文压缩阈值常量、路由缓存TTL秒数常量和路由动作枚举
from app.core.logging import setup_logger  # 导入日志设置函数，用于创建模块专用logger
from app.agents.prompts import TITLE_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT  # 导入标题生成和摘要生成的系统提示词
from app.agents.resilience import ResilientLLM  # 导入容错LLM包装器类

logger = setup_logger("agents.llm")  # 创建本模块专用的日志记录器，名称为agents.llm

# 路由决策 LRU 缓存：key -> (result, timestamp)
_route_cache: dict[str, tuple[str, float]] = {}  # 路由缓存字典，键为MD5哈希，值为(路由结果, 时间戳)元组


def create_llm(temperature: float = 0.0, streaming: bool = False) -> ResilientLLM:  # 定义创建LLM实例的函数，返回ResilientLLM包装器
    """
    创建带容错能力的 LLM 实例（重试 / 熔断 / 降级 / 成本熔断）。

    返回 ResilientLLM 包装器，对外保持 ainvoke / astream / bind_tools 接口，
    上层节点无需感知容错逻辑。
    """
    settings = get_settings()  # 获取应用配置实例
    primary = ChatOpenAI(  # 创建主模型实例
        model=settings.MODEL_NAME,  # 设置模型名称
        api_key=settings.OPENAI_API_KEY,  # 设置API密钥
        base_url=settings.OPENAI_BASE_URL,  # 设置API基础URL
        temperature=temperature,  # 设置温度参数控制随机性
        streaming=streaming,  # 设置是否启用流式输出
    )

    fallback = None  # 备用模型初始为None
    if settings.FALLBACK_MODEL_NAME:  # 如果配置了备用模型名称
        fallback = ChatOpenAI(  # 创建备用模型实例
            model=settings.FALLBACK_MODEL_NAME,  # 设置备用模型名称
            api_key=settings.OPENAI_API_KEY,  # 设置API密钥（与主模型相同）
            base_url=settings.FALLBACK_OPENAI_BASE_URL or settings.OPENAI_BASE_URL,  # 设置备用API基础URL，回退到主URL
            temperature=temperature,  # 设置温度参数
            streaming=streaming,  # 设置是否启用流式输出
        )

    return ResilientLLM(  # 返回容错LLM包装器实例
        primary=primary,  # 传入主模型
        fallback=fallback,  # 传入备用模型
        max_retries=settings.LLM_MAX_RETRIES,  # 设置最大重试次数
        retry_base_delay=settings.LLM_RETRY_BASE_DELAY,  # 设置重试基础延迟
    )


def _cache_key(question: str, history: str) -> str:  # 定义生成缓存键的私有函数
    return hashlib.md5(f"{question}|{history}".encode("utf-8")).hexdigest()  # 将问题和历史的拼接字符串进行MD5哈希后返回十六进制摘要


async def supervisor_decide_cached(question: str, history_context: str, decide_fn) -> str:  # 定义带缓存的路由决策异步函数
    """
    带 LRU 缓存的路由决策包装器。

    supervisor 使用 temperature=0 的确定性输出，相同输入可安全缓存。
    """
    key = _cache_key(question, history_context)  # 根据问题和历史上下文生成缓存键
    now = time.time()  # 获取当前时间戳

    cached = _route_cache.get(key)  # 从缓存中获取对应键的数据
    if cached and (now - cached[1]) < ROUTE_CACHE_TTL_SECONDS:  # 如果缓存存在且未过期
        logger.debug("路由缓存命中: %s", question[:30])  # 记录缓存命中调试日志
        return cached[0]  # 返回缓存的路由结果

    timeout_seconds = get_settings().LLM_TIMEOUT_SECONDS  # 从配置读取LLM调用超时秒数，避免DeepSeek API卡住时无限等待
    try:  # 开始超时捕获块，包裹决策函数调用
        result = await asyncio.wait_for(  # 在超时限制内调用决策函数，超时则抛出asyncio.TimeoutError
            decide_fn(question, history_context),  # 传入问题和历史上下文执行决策协程
            timeout=timeout_seconds,  # 设置超时秒数，取自全局配置LLM_TIMEOUT_SECONDS
        )  # 等待决策结果返回
    except asyncio.TimeoutError:  # 捕获路由决策超时异常
        logger.warning(  # 记录超时警告日志，便于运维定位卡顿问题
            "路由决策超时(>%ds)，降级为DIRECT直接回答: %s",  # 警告信息模板，包含超时阈值和问题摘要
            timeout_seconds, question[:30],  # 超时时长和问题前30字符摘要
        )  # 日志调用结束
        return RouteAction.DIRECT  # 超时降级：返回DIRECT直接回答，避免用户长时间等待

    _route_cache[key] = (result, now)  # 将结果和当前时间戳存入缓存

    # 简单清理过期缓存，防止无限增长
    if len(_route_cache) > 1000:  # 如果缓存条目超过1000
        expired = [k for k, (_, ts) in _route_cache.items() if now - ts >= ROUTE_CACHE_TTL_SECONDS]  # 找出所有过期的缓存键
        for k in expired:  # 遍历过期键
            _route_cache.pop(k, None)  # 删除过期缓存项

    return result  # 返回决策结果


async def generate_title(question: str) -> str:  # 定义生成对话标题的异步函数
    """异步生成对话标题（<=20 字）。失败时回退为问题截断。"""
    fallback = question[:20] + ("..." if len(question) > 20 else "")  # 构造回退标题：截取前20字并视情况加省略号
    timeout_seconds = get_settings().LLM_TIMEOUT_SECONDS  # 从配置读取LLM调用超时秒数，避免标题生成请求卡住
    try:  # 开始异常捕获块
        llm = create_llm(temperature=0.3)  # 创建LLM实例，温度0.3以获得一定创造性
        response = await asyncio.wait_for(  # 在超时限制内异步调用LLM，超时则抛出asyncio.TimeoutError
            llm.ainvoke([  # 构造LLM调用消息列表
                SystemMessage(content=TITLE_SYSTEM_PROMPT),  # 系统消息：标题生成提示词
                HumanMessage(content=question),  # 人类消息：用户问题
            ]),  # 消息列表结束
            timeout=timeout_seconds,  # 设置超时秒数，取自全局配置LLM_TIMEOUT_SECONDS
        )  # 等待LLM响应返回
        title = response.content.strip().strip('"').strip("'")  # 提取响应内容并去除首尾空白和引号
        return title[:20] if title else fallback  # 返回不超过20字的标题，若为空则返回回退标题
    except asyncio.TimeoutError:  # 捕获标题生成超时异常
        logger.warning(  # 记录超时警告日志，便于排查API响应缓慢问题
            "标题生成超时(>%ds)，使用截断标题",  # 警告信息模板，包含超时阈值
            timeout_seconds,  # 超时时长
        )  # 日志调用结束
        return fallback  # 超时降级：返回截断标题，保证对话流程继续
    except Exception as e:  # 捕获所有其他异常
        logger.warning("标题生成失败，使用截断标题: %s", e)  # 记录警告日志
        return fallback  # 返回回退标题


async def compress_context(history_text: str) -> str:  # 定义压缩上下文的异步函数
    """
    上下文压缩：当历史文本超过阈值时，调用 LLM 生成摘要替代原文。

    替代简单的 200 字符截断，保留关键信息。
    """
    if len(history_text) <= CONTEXT_COMPRESS_THRESHOLD:  # 如果历史文本长度未超过阈值
        return history_text  # 直接返回原文，无需压缩
    timeout_seconds = get_settings().LLM_TIMEOUT_SECONDS  # 从配置读取LLM调用超时秒数，避免压缩请求卡住
    try:  # 开始异常捕获块
        llm = create_llm(temperature=0.0)  # 创建LLM实例，温度0.0以保证确定性输出
        response = await asyncio.wait_for(  # 在超时限制内异步调用LLM，超时则抛出asyncio.TimeoutError
            llm.ainvoke([  # 构造LLM调用消息列表
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),  # 系统消息：摘要生成提示词
                HumanMessage(content=history_text),  # 人类消息：历史文本
            ]),  # 消息列表结束
            timeout=timeout_seconds,  # 设置超时秒数，取自全局配置LLM_TIMEOUT_SECONDS
        )  # 等待LLM响应返回
        summary = response.content.strip()  # 提取响应内容并去除首尾空白
        logger.info("上下文已压缩: %d -> %d 字符", len(history_text), len(summary))  # 记录压缩信息日志
        return f"[历史摘要] {summary}"  # 返回带前缀的摘要文本
    except asyncio.TimeoutError:  # 捕获上下文压缩超时异常
        logger.warning(  # 记录超时警告日志，便于排查API响应缓慢问题
            "上下文压缩超时(>%ds)，回退截断",  # 警告信息模板，包含超时阈值
            timeout_seconds,  # 超时时长
        )  # 日志调用结束
        return history_text[:CONTEXT_COMPRESS_THRESHOLD] + "..."  # 超时降级：截断到阈值长度并加省略号，保证流程继续
    except Exception as e:  # 捕获所有其他异常
        logger.warning("上下文压缩失败，回退截断: %s", e)  # 记录警告日志
        return history_text[:CONTEXT_COMPRESS_THRESHOLD] + "..."  # 压缩失败则截断到阈值长度并加省略号
