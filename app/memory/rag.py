"""RAG 语义切片与记忆上下文格式化。"""

import re  # 导入正则表达式模块，用于按 Markdown 标题与段落切分文档
from typing import Dict, List  # 导入类型注解：字典与列表类型


def semantic_chunk(
    content: str,  # 待切分的原始文档内容
    chunk_size: int = 500,  # 单个切片的目标字符数上限
    chunk_overlap: int = 50,  # 滑动窗口切片时的重叠字符数，用于保留上下文
) -> List[Dict]:  # 返回切片列表
    """
    语义感知文档切片：
    1. 优先按 Markdown 标题（# / ## / ###）分段
    2. 同一标题段内按段落（双换行）分割
    3. 超长段落退化为滑动窗口
    4. 每个切片携带 section_title 和前后链接关系

    Returns:
        每个元素包含 text, section_title, prev_chunk_id, next_chunk_id 字段
    """
    sections = re.split(r'\n(?=#{1,6}\s)', content)  # 按行首 Markdown 标题（1-6 级）拆分为多个章节
    chunks: List[Dict] = []  # 初始化切片结果列表

    for section in sections:  # 遍历每个章节
        section = section.strip()  # 去除章节首尾空白字符
        if not section:  # 若章节为空则跳过
            continue

        title_match = re.match(r'^(#{1,6})\s+(.+)', section)  # 尝试匹配章节开头的 Markdown 标题
        section_title = title_match.group(2).strip() if title_match else ""  # 提取标题文本；无标题则空字符串
        body = re.sub(r'^#{1,6}\s+.+\n?', '', section, count=1) if title_match else section  # 移除章节开头的标题行，得到正文

        paragraphs = re.split(r'\n\s*\n', body)  # 按空行将正文拆分为多个段落
        current_chunk = ""  # 当前正在累积的切片文本
        current_title = section_title  # 当前切片所属的章节标题

        for para in paragraphs:  # 遍历每个段落
            para = para.strip()  # 去除段落首尾空白
            if not para:  # 空段落跳过
                continue

            if len(current_chunk) + len(para) + 1 <= chunk_size:  # 若当前切片加入该段落未超上限
                current_chunk = f"{current_chunk}\n\n{para}".strip() if current_chunk else para  # 用双换行拼接段落
            else:  # 当前切片已达上限
                if current_chunk:  # 先保存已累积的切片
                    chunks.append({"text": current_chunk, "section_title": current_title})

                if len(para) > chunk_size:  # 若单个段落超过切片上限，使用滑动窗口切分
                    start = 0  # 滑动窗口起始位置
                    while start < len(para):  # 循环直到处理完整个段落
                        end = start + chunk_size  # 计算窗口结束位置
                        chunks.append({"text": para[start:end], "section_title": current_title})  # 截取窗口内容作为切片
                        start += (chunk_size - chunk_overlap)  # 按步长（切片大小减重叠）滑动窗口
                    current_chunk = ""  # 重置当前切片为空
                else:  # 段落未超上限，但当前切片已满
                    if chunks and chunk_overlap > 0:  # 若存在上一切片且需要重叠
                        prev_text = chunks[-1]["text"]  # 取上一切片的文本
                        overlap_text = prev_text[-chunk_overlap:] if len(prev_text) > chunk_overlap else prev_text  # 取末尾 overlap 字符作为重叠
                        current_chunk = f"{overlap_text}\n{para}".strip()  # 用重叠内容拼接新段落作为新切片起点
                    else:  # 无需重叠
                        current_chunk = para  # 直接以该段落作为新切片起点

        if current_chunk:  # 章节处理完毕，保存剩余切片
            chunks.append({"text": current_chunk, "section_title": current_title})

    # 添加前后 chunk 链接
    for i, chunk in enumerate(chunks):  # 遍历所有切片以补充前后链接关系
        chunk["prev_chunk_id"] = i - 1 if i > 0 else None  # 前一切片索引；首切片无前驱
        chunk["next_chunk_id"] = i + 1 if i < len(chunks) - 1 else None  # 后一切片索引；末切片无后继

    return chunks  # 返回带链接关系的切片列表


def format_memories_context(memories: List[Dict]) -> str:
    """将检索到的长期记忆格式化为可注入 LLM 的上下文文本。"""
    if not memories:  # 若无记忆则返回空字符串
        return ""
    lines = ["[长期记忆 - 相关历史对话]"]  # 上下文首行标题
    for i, mem in enumerate(memories, 1):  # 遍历记忆列表，编号从 1 开始
        ts = mem.get("metadata", {}).get("timestamp", "未知时间")  # 从元数据中提取时间戳，缺失时标记未知
        lines.append(f"{i}. [{ts}] {mem['content'][:200]}")  # 拼接编号、时间戳、内容前 200 字
    return "\n".join(lines)  # 用换行符拼接为完整上下文文本返回
