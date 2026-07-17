"""
智能体定义模块：调度主管、搜索Agent、视觉Agent、回答Agent。
每个智能体职责单一，不持有超出自身职责的工具。
"""

import base64
import os
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from tavily import TavilyClient
import ollama

from config import Config
from logger import setup_logger

logger = setup_logger("agents", Config.LOG_LEVEL, Config.LOG_FILE)


# ============================================================
# 通用 LLM 实例（所有智能体共用同一个模型客户端）
# ============================================================

def _create_llm(temperature: float = 0.0) -> ChatOpenAI:
    """创建 OpenAI 兼容的 LLM 实例（DeepSeek）。"""
    return ChatOpenAI(
        model=Config.MODEL_NAME,
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
        temperature=temperature,
    )


# ============================================================
# 1. 调度主管Agent
# ============================================================

SUPERVISOR_SYSTEM_PROMPT = """你是一个调度主管，负责判断用户的问题需要哪种处理方式。

判断规则：
- SEARCH：需要联网搜索（实时信息、最新新闻、近期事件、特定数据查询）
- RAG：需要从已上传的文档中检索信息（用户明确提到"文档"、"资料"、"上传的文件"）
- DIRECT：不需要搜索也不需要文档检索（常识、计算、推理、翻译、聊天等）

请只输出一个单词：SEARCH、RAG 或 DIRECT，不要输出任何其他内容。"""


def supervisor_decide(user_question: str, history_context: str = "") -> str:
    """
    调度主管Agent：分析用户问题，结合对话历史判断处理方式。

    Args:
        user_question: 用户原始问题文本
        history_context: 对话历史摘要（可为空）

    Returns:
        str: "SEARCH" / "RAG" / "DIRECT"
    """
    llm = _create_llm(temperature=0.0)
    prompt = f"用户问题：{user_question}"
    if history_context:
        prompt = f"对话历史：\n{history_context}\n\n当前用户问题：{user_question}"
    response = llm.invoke([
        SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    result_text = response.content.strip().upper()
    # 解析路由决策
    if "SEARCH" in result_text:
        return "SEARCH"
    elif "RAG" in result_text:
        return "RAG"
    return "DIRECT"


# ============================================================
# 2. 搜索Agent（唯一持有联网搜索能力）
# ============================================================

SEARCH_SYSTEM_PROMPT = """你是一个搜索专家，负责从用户问题中提取最精准的搜索关键词。
只输出搜索关键词，不要输出任何其他内容。"""


def search_web(user_question: str) -> str:
    """
    搜索Agent：使用Tavily执行联网搜索，返回结构化摘要。
    """
    llm = _create_llm(temperature=0.0)
    keyword_response = llm.invoke([
        SystemMessage(content=SEARCH_SYSTEM_PROMPT),
        HumanMessage(content=f"请为以下问题提取搜索关键词：{user_question}"),
    ])
    search_query = keyword_response.content.strip().strip('"').strip("'")
    logger.debug("搜索关键词: %s", search_query)

    tavily_client = TavilyClient(api_key=Config.TAVILY_API_KEY)
    search_response = tavily_client.search(
        query=search_query,
        search_depth="basic",
        max_results=3,
        include_answer=True,
    )

    formatted_parts = []
    if search_response.get("answer"):
        formatted_parts.append(f"[AI摘要] {search_response['answer']}")

    for i, result in enumerate(search_response.get("results", []), 1):
        title = result.get("title", "无标题")
        url = result.get("url", "")
        content = result.get("content", "无内容")
        content_short = content[:300] + "..." if len(content) > 300 else content
        formatted_parts.append(
            f"[结果{i}] {title}\n链接: {url}\n摘要: {content_short}"
        )

    return "\n\n".join(formatted_parts) if formatted_parts else "未找到相关搜索结果。"


# ============================================================
# 3. 视觉Agent（使用本地Ollama qwen3多模态识别图片）
# ============================================================

VISION_SYSTEM_PROMPT = """你是一个视觉分析专家，请仔细观察用户上传的图片，给出详细描述。
如果图片中包含文字，请完整提取文字内容。
如果图片是图表或表格，请分析其结构和数据含义。
请用中文回答。"""


def analyze_image(image_path: str, user_question: str = "") -> str:
    """
    视觉Agent：使用本地Ollama多模态模型识别图片内容。

    Args:
        image_path: 图片文件路径
        user_question: 用户关于图片的问题（可选）

    Returns:
        str: 图片分析结果
    """
    # 将图片编码为base64
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # 构建提示词
    prompt = VISION_SYSTEM_PROMPT
    if user_question:
        prompt = f"用户问题：{user_question}\n\n请根据图片内容回答用户的问题。"

    # 调用Ollama多模态API
    try:
        response = ollama.chat(
            model=Config.OLLAMA_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [image_data],
            }],
        )
        logger.info("视觉Agent: 图片分析完成")
        return response["message"]["content"]
    except Exception as e:
        # 如果Ollama不可用，返回错误提示
        logger.error("视觉Agent失败: %s", e)
        return f"[视觉识别失败] 请确保Ollama服务已启动且已安装{Config.OLLAMA_VISION_MODEL}模型。错误: {str(e)}"


# ============================================================
# 4. 回答Agent（综合所有上下文生成最终答案）
# ============================================================

ANSWER_SYSTEM_PROMPT = """你是一个智能助手，负责根据用户问题和所有参考资料生成准确、有帮助的回答。

回答要求：
- 综合所有提供的上下文（搜索结果、RAG文档、长期记忆、视觉分析结果）
- 如果有图片分析结果，优先基于图片内容回答
- 如果有搜索结果，请基于搜索结果回答，并在末尾标注信息来源
- 如果有RAG文档，引用文档中的相关片段
- 如果有对话历史，请结合上下文理解用户意图
- 保持回答简洁、准确、有条理"""


def generate_answer(
    user_question: str,
    search_results: str = "",
    rag_context: str = "",
    long_term_memories: str = "",
    image_analysis: str = "",
    history_context: str = "",
) -> str:
    """
    回答Agent：综合所有上下文生成最终回答。

    Args:
        user_question: 用户原始问题
        search_results: 联网搜索结果
        rag_context: RAG文档检索结果
        long_term_memories: 长期记忆检索结果
        image_analysis: 图片分析结果
        history_context: 对话历史摘要

    Returns:
        str: 最终回答文本
    """
    llm = _create_llm(temperature=0.3)
    # 构建综合上下文
    context_parts = [f"用户问题：{user_question}"]
    if history_context:
        context_parts.insert(0, f"对话历史：\n{history_context}")
    if image_analysis:
        context_parts.append(f"\n[图片分析结果]\n{image_analysis}")
    if search_results:
        context_parts.append(f"\n[联网搜索结果]\n{search_results}")
    if rag_context:
        context_parts.append(f"\n{rag_context}")
    if long_term_memories:
        context_parts.append(f"\n{long_term_memories}")

    user_message = "\n\n".join(context_parts)
    response = llm.invoke([
        SystemMessage(content=ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    return response.content
