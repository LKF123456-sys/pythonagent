"""
智能体定义模块：调度主管、搜索Agent、视觉Agent、回答Agent。
每个智能体职责单一，不持有超出自身职责的工具。
"""

# 导入base64模块，用于图片base64编码
import base64
# 导入os模块，用于文件路径操作
import os
# 导入类型提示模块
from typing import Optional

# 从langchain_openai导入ChatOpenAI，用于调用OpenAI兼容的LLM接口
from langchain_openai import ChatOpenAI
# 从langchain_core.messages导入HumanMessage和SystemMessage，用于构建消息
from langchain_core.messages import HumanMessage, SystemMessage
# 从tavily导入TavilyClient，用于联网搜索
from tavily import TavilyClient
# 导入ollama模块，用于调用本地Ollama模型
import ollama

# 导入配置模块
from config import Config
# 导入日志设置函数
from logger import setup_logger

# 初始化日志记录器
logger = setup_logger("agents", Config.LOG_LEVEL, Config.LOG_FILE)


# ============================================================
# 通用 LLM 实例（所有智能体共用同一个模型客户端）
# ============================================================

def _create_llm(temperature: float = 0.0) -> ChatOpenAI:
    """创建 OpenAI 兼容的 LLM 实例（DeepSeek）。"""
    # 返回配置好的ChatOpenAI实例，指向DeepSeek API
    return ChatOpenAI(
        model=Config.MODEL_NAME,               # 模型名称
        api_key=Config.OPENAI_API_KEY,         # API密钥
        base_url=Config.OPENAI_BASE_URL,       # API基础URL
        temperature=temperature,                # 温度参数（控制随机性）
    )


# ============================================================
# 1. 调度主管Agent
# ============================================================

# 调度主管系统提示词：定义调度主管的角色和判断规则
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
    # 创建温度为0的LLM实例（确定性输出）
    llm = _create_llm(temperature=0.0)
    # 构建提示词，默认只包含用户问题
    prompt = f"用户问题：{user_question}"
    # 如果有对话历史上下文，将历史添加到提示词前面
    if history_context:
        prompt = f"对话历史：\n{history_context}\n\n当前用户问题：{user_question}"
    # 调用LLM获取路由决策
    response = llm.invoke([
        SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    # 获取LLM返回内容，去除首尾空白并转换为大写
    result_text = response.content.strip().upper()
    # 通过文本包含判断路由结果（DeepSeek不支持结构化输出，用简单字符串匹配）
    if "SEARCH" in result_text:
        return "SEARCH"
    elif "RAG" in result_text:
        return "RAG"
    # 默认返回DIRECT（直接回答）
    return "DIRECT"


# ============================================================
# 2. 搜索Agent（唯一持有联网搜索能力）
# ============================================================

# 搜索Agent系统提示词：只输出搜索关键词
SEARCH_SYSTEM_PROMPT = """你是一个搜索专家，负责从用户问题中提取最精准的搜索关键词。
只输出搜索关键词，不要输出任何其他内容。"""


def search_web(user_question: str) -> str:
    """
    搜索Agent：使用Tavily执行联网搜索，返回结构化摘要。
    """
    # 创建温度为0的LLM实例
    llm = _create_llm(temperature=0.0)
    # 调用LLM提取搜索关键词
    keyword_response = llm.invoke([
        SystemMessage(content=SEARCH_SYSTEM_PROMPT),
        HumanMessage(content=f"请为以下问题提取搜索关键词：{user_question}"),
    ])
    # 提取并清理搜索关键词（去除首尾空白和引号）
    search_query = keyword_response.content.strip().strip('"').strip("'")
    # 记录搜索关键词日志
    logger.debug("搜索关键词: %s", search_query)

    # 创建Tavily搜索客户端
    tavily_client = TavilyClient(api_key=Config.TAVILY_API_KEY)
    # 执行搜索：基础深度，最多3条结果，包含AI摘要
    search_response = tavily_client.search(
        query=search_query,
        search_depth="basic",
        max_results=3,
        include_answer=True,
    )

    # 格式化搜索结果
    formatted_parts = []
    # 如果有AI摘要，添加到结果中
    if search_response.get("answer"):
        formatted_parts.append(f"[AI摘要] {search_response['answer']}")

    # 遍历搜索结果，格式化每条结果
    for i, result in enumerate(search_response.get("results", []), 1):
        # 获取标题，默认"无标题"
        title = result.get("title", "无标题")
        # 获取URL
        url = result.get("url", "")
        # 获取内容，默认"无内容"
        content = result.get("content", "无内容")
        # 内容截断到300字符，超出部分加...
        content_short = content[:300] + "..." if len(content) > 300 else content
        # 格式化单条结果
        formatted_parts.append(
            f"[结果{i}] {title}\n链接: {url}\n摘要: {content_short}"
        )

    # 返回格式化后的结果，如果没有结果则返回提示
    return "\n\n".join(formatted_parts) if formatted_parts else "未找到相关搜索结果。"


# ============================================================
# 3. 视觉Agent（使用本地Ollama qwen3多模态识别图片）
# ============================================================

# 视觉Agent系统提示词：定义视觉分析的要求
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
    # 以二进制模式读取图片文件
    with open(image_path, "rb") as f:
        # 将图片数据编码为base64字符串
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # 构建提示词，默认使用视觉分析系统提示
    prompt = VISION_SYSTEM_PROMPT
    # 如果用户有关于图片的具体问题，使用用户问题作为提示
    if user_question:
        prompt = f"用户问题：{user_question}\n\n请根据图片内容回答用户的问题。"

    # 调用Ollama多模态API进行图片分析
    try:
        response = ollama.chat(
            model=Config.OLLAMA_VISION_MODEL,  # 使用配置的视觉模型
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [image_data],       # 传入base64编码的图片
            }],
        )
        # 记录图片分析完成日志
        logger.info("视觉Agent: 图片分析完成")
        # 返回模型生成的分析结果
        return response["message"]["content"]
    except Exception as e:
        # 如果Ollama调用失败，记录错误日志并返回错误提示
        logger.error("视觉Agent失败: %s", e)
        return f"[视觉识别失败] 请确保Ollama服务已启动且已安装{Config.OLLAMA_VISION_MODEL}模型。错误: {str(e)}"


# ============================================================
# 4. 回答Agent（综合所有上下文生成最终答案）
# ============================================================

# 回答Agent系统提示词：要求按指定格式输出思考过程和最终回答
ANSWER_SYSTEM_PROMPT = """你是一个智能助手，负责根据用户问题和所有参考资料生成准确、有帮助的回答。

你必须按照以下格式回答：

<thinking>
在这里写下你的思考过程：
- 分析用户问题的核心意图
- 评估可用的参考资料
- 确定回答策略
- 组织回答结构
</thinking>

<answer>
在这里写下最终回答：
- 综合所有提供的上下文（搜索结果、RAG文档、长期记忆、视觉分析结果）
- 如果有图片分析结果，优先基于图片内容回答
- 如果有搜索结果，请基于搜索结果回答，并在末尾标注信息来源
- 如果有RAG文档，引用文档中的相关片段
- 如果有对话历史，请结合上下文理解用户意图
- 保持回答简洁、准确、有条理、格式美观
- 使用 Markdown 格式（标题、列表、代码块等）让回答更易读
</answer>"""


def generate_answer(
    user_question: str,
    search_results: str = "",
    rag_context: str = "",
    long_term_memories: str = "",
    image_analysis: str = "",
    history_context: str = "",
) -> str:
    """
    回答Agent：综合所有上下文生成最终回答（非流式）。

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
    # 创建温度为0.3的LLM实例（适度创造性）
    llm = _create_llm(temperature=0.3)
    # 构建综合上下文，默认包含用户问题
    context_parts = [f"用户问题：{user_question}"]
    # 如果有对话历史，将历史插入到最前面
    if history_context:
        context_parts.insert(0, f"对话历史：\n{history_context}")
    # 如果有图片分析结果，添加到上下文
    if image_analysis:
        context_parts.append(f"\n[图片分析结果]\n{image_analysis}")
    # 如果有搜索结果，添加到上下文
    if search_results:
        context_parts.append(f"\n[联网搜索结果]\n{search_results}")
    # 如果有RAG上下文，添加到上下文
    if rag_context:
        context_parts.append(f"\n{rag_context}")
    # 如果有长期记忆，添加到上下文
    if long_term_memories:
        context_parts.append(f"\n{long_term_memories}")

    # 将所有上下文部分用双换行连接成完整消息
    user_message = "\n\n".join(context_parts)
    # 调用LLM生成回答
    response = llm.invoke([
        SystemMessage(content=ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    # 返回完整回答内容
    return response.content


async def generate_answer_stream(
    user_question: str,
    search_results: str = "",
    rag_context: str = "",
    long_term_memories: str = "",
    image_analysis: str = "",
    history_context: str = "",
) -> AsyncGenerator[str, None]:
    """
    回答Agent：综合所有上下文生成最终回答（流式）。

    Args:
        user_question: 用户原始问题
        search_results: 联网搜索结果
        rag_context: RAG文档检索结果
        long_term_memories: 长期记忆检索结果
        image_analysis: 图片分析结果
        history_context: 对话历史摘要

    Yields:
        str: 逐 token 的回答文本
    """
    # 导入AsyncGenerator类型（延迟导入避免循环引用）
    from typing import AsyncGenerator
    # 创建温度为0.3的LLM实例
    llm = _create_llm(temperature=0.3)
    # 构建综合上下文，默认包含用户问题
    context_parts = [f"用户问题：{user_question}"]
    # 如果有对话历史，插入到最前面
    if history_context:
        context_parts.insert(0, f"对话历史：\n{history_context}")
    # 如果有图片分析结果，添加到上下文
    if image_analysis:
        context_parts.append(f"\n[图片分析结果]\n{image_analysis}")
    # 如果有搜索结果，添加到上下文
    if search_results:
        context_parts.append(f"\n[联网搜索结果]\n{search_results}")
    # 如果有RAG上下文，添加到上下文
    if rag_context:
        context_parts.append(f"\n{rag_context}")
    # 如果有长期记忆，添加到上下文
    if long_term_memories:
        context_parts.append(f"\n{long_term_memories}")

    # 将上下文连接成完整消息
    user_message = "\n\n".join(context_parts)

    # 使用流式API调用LLM，逐token产出
    async for chunk in llm.astream([
        SystemMessage(content=ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]):
        # 如果chunk有content属性，yield该内容
        if hasattr(chunk, 'content'):
            yield chunk.content
