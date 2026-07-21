"""RAG 语义切片与记忆上下文格式化。"""

import re
from typing import Dict, List


def semantic_chunk(
    content: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> List[Dict]:
    """
    语义感知文档切片：
    1. 优先按 Markdown 标题（# / ## / ###）分段
    2. 同一标题段内按段落（双换行）分割
    3. 超长段落退化为滑动窗口
    4. 每个切片携带 section_title 和前后链接关系

    Returns:
        每个元素包含 text, section_title, prev_chunk_id, next_chunk_id 字段
    """
    sections = re.split(r'\n(?=#{1,6}\s)', content)
    chunks: List[Dict] = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        title_match = re.match(r'^(#{1,6})\s+(.+)', section)
        section_title = title_match.group(2).strip() if title_match else ""
        body = re.sub(r'^#{1,6}\s+.+\n?', '', section, count=1) if title_match else section

        paragraphs = re.split(r'\n\s*\n', body)
        current_chunk = ""
        current_title = section_title

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}".strip() if current_chunk else para
            else:
                if current_chunk:
                    chunks.append({"text": current_chunk, "section_title": current_title})

                if len(para) > chunk_size:
                    start = 0
                    while start < len(para):
                        end = start + chunk_size
                        chunks.append({"text": para[start:end], "section_title": current_title})
                        start += (chunk_size - chunk_overlap)
                    current_chunk = ""
                else:
                    if chunks and chunk_overlap > 0:
                        prev_text = chunks[-1]["text"]
                        overlap_text = prev_text[-chunk_overlap:] if len(prev_text) > chunk_overlap else prev_text
                        current_chunk = f"{overlap_text}\n{para}".strip()
                    else:
                        current_chunk = para

        if current_chunk:
            chunks.append({"text": current_chunk, "section_title": current_title})

    # 添加前后 chunk 链接
    for i, chunk in enumerate(chunks):
        chunk["prev_chunk_id"] = i - 1 if i > 0 else None
        chunk["next_chunk_id"] = i + 1 if i < len(chunks) - 1 else None

    return chunks


def format_memories_context(memories: List[Dict]) -> str:
    """将检索到的长期记忆格式化为可注入 LLM 的上下文文本。"""
    if not memories:
        return ""
    lines = ["[长期记忆 - 相关历史对话]"]
    for i, mem in enumerate(memories, 1):
        ts = mem.get("metadata", {}).get("timestamp", "未知时间")
        lines.append(f"{i}. [{ts}] {mem['content'][:200]}")
    return "\n".join(lines)
