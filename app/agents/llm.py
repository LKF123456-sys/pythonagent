"""LLM 实例管理 + 路由缓存 + 标题生成 + 上下文压缩。"""

import asyncio
import hashlib
import time
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
from app.core.constants import CONTEXT_COMPRESS_THRESHOLD, ROUTE_CACHE_TTL_SECONDS
from app.core.logging import setup_logger
from app.agents.prompts import TITLE_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT
from app.agents.resilience import ResilientLLM

logger = setup_logger("agents.llm")

# 路由决策 LRU 缓存：key -> (result, timestamp)
_route_cache: dict[str, tuple[str, float]] = {}


def create_llm(temperature: float = 0.0, streaming: bool = False) -> ResilientLLM:
    """
    创建带容错能力的 LLM 实例（重试 / 熔断 / 降级 / 成本熔断）。

    返回 ResilientLLM 包装器，对外保持 ainvoke / astream / bind_tools 接口，
    上层节点无需感知容错逻辑。
    """
    settings = get_settings()
    primary = ChatOpenAI(
        model=settings.MODEL_NAME,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=temperature,
        streaming=streaming,
    )

    fallback = None
    if settings.FALLBACK_MODEL_NAME:
        fallback = ChatOpenAI(
            model=settings.FALLBACK_MODEL_NAME,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.FALLBACK_OPENAI_BASE_URL or settings.OPENAI_BASE_URL,
            temperature=temperature,
            streaming=streaming,
        )

    return ResilientLLM(
        primary=primary,
        fallback=fallback,
        max_retries=settings.LLM_MAX_RETRIES,
        retry_base_delay=settings.LLM_RETRY_BASE_DELAY,
    )


def _cache_key(question: str, history: str) -> str:
    return hashlib.md5(f"{question}|{history}".encode("utf-8")).hexdigest()


async def supervisor_decide_cached(question: str, history_context: str, decide_fn) -> str:
    """
    带 LRU 缓存的路由决策包装器。

    supervisor 使用 temperature=0 的确定性输出，相同输入可安全缓存。
    """
    key = _cache_key(question, history_context)
    now = time.time()

    cached = _route_cache.get(key)
    if cached and (now - cached[1]) < ROUTE_CACHE_TTL_SECONDS:
        logger.debug("路由缓存命中: %s", question[:30])
        return cached[0]

    result = await decide_fn(question, history_context)
    _route_cache[key] = (result, now)

    # 简单清理过期缓存，防止无限增长
    if len(_route_cache) > 1000:
        expired = [k for k, (_, ts) in _route_cache.items() if now - ts >= ROUTE_CACHE_TTL_SECONDS]
        for k in expired:
            _route_cache.pop(k, None)

    return result


async def generate_title(question: str) -> str:
    """异步生成对话标题（<=20 字）。失败时回退为问题截断。"""
    fallback = question[:20] + ("..." if len(question) > 20 else "")
    try:
        llm = create_llm(temperature=0.3)
        response = await llm.ainvoke([
            SystemMessage(content=TITLE_SYSTEM_PROMPT),
            HumanMessage(content=question),
        ])
        title = response.content.strip().strip('"').strip("'")
        return title[:20] if title else fallback
    except Exception as e:
        logger.warning("标题生成失败，使用截断标题: %s", e)
        return fallback


async def compress_context(history_text: str) -> str:
    """
    上下文压缩：当历史文本超过阈值时，调用 LLM 生成摘要替代原文。

    替代简单的 200 字符截断，保留关键信息。
    """
    if len(history_text) <= CONTEXT_COMPRESS_THRESHOLD:
        return history_text
    try:
        llm = create_llm(temperature=0.0)
        response = await llm.ainvoke([
            SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
            HumanMessage(content=history_text),
        ])
        summary = response.content.strip()
        logger.info("上下文已压缩: %d -> %d 字符", len(history_text), len(summary))
        return f"[历史摘要] {summary}"
    except Exception as e:
        logger.warning("上下文压缩失败，回退截断: %s", e)
        return history_text[:CONTEXT_COMPRESS_THRESHOLD] + "..."
