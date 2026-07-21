"""文档业务逻辑：安全上传 + 多格式解析（PDF/docx/文本）+ RAG 入库。"""

import io
import os

from app.core.config import get_settings
from app.core.constants import ALLOWED_DOC_EXTENSIONS, ALLOWED_IMAGE_EXTENSIONS
from app.core.exceptions import BadRequestError, ConflictError, PayloadTooLargeError
from app.core.logging import setup_logger
from app.core.security import is_allowed_extension, sanitize_filename, validate_upload_path
from app.agents.runtime import get_vector_store
from app.memory.rag import semantic_chunk

logger = setup_logger("service.document")


# ============================================================
# 安全上传
# ============================================================

def save_upload(file_bytes: bytes, filename: str, allowed_set: set) -> str:
    """
    安全保存上传文件，返回存储后的文件名。

    校验链：扩展名白名单 → 大小限制 → 文件名消毒 → 路径遍历防护。
    """
    settings = get_settings()

    if not is_allowed_extension(filename, allowed_set):
        raise BadRequestError(f"不支持的文件类型：{filename}")

    if len(file_bytes) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制"
        )

    safe_name = sanitize_filename(filename)
    filepath = os.path.join(settings.UPLOAD_FOLDER, safe_name)
    if not validate_upload_path(filepath, settings.UPLOAD_FOLDER):
        raise BadRequestError("非法的文件路径")

    with open(filepath, "wb") as f:
        f.write(file_bytes)
    logger.info("文件已保存: %s (%d 字节)", safe_name, len(file_bytes))
    return safe_name


def save_image_upload(file_bytes: bytes, filename: str) -> str:
    """保存聊天图片上传。"""
    return save_upload(file_bytes, filename, ALLOWED_IMAGE_EXTENSIONS)


# ============================================================
# 多格式文档解析
# ============================================================

def parse_document(file_bytes: bytes, filename: str) -> str:
    """
    统一文档解析接口：parse_document(bytes, filename) -> str。

    支持 PDF（pdfplumber）、Word（python-docx）及各类纯文本格式。
    """
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""

    if ext == "pdf":
        return _parse_pdf(file_bytes)
    if ext == "docx":
        return _parse_docx(file_bytes)
    return _parse_text(file_bytes, filename)


def _parse_pdf(file_bytes: bytes) -> str:
    """使用 pdfplumber 提取 PDF 文本（含表格）。"""
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
            # 提取表格（转为简单文本行）
            for table in page.extract_tables():
                for row in table:
                    cells = [str(cell).strip() if cell else "" for cell in row]
                    if any(cells):
                        parts.append(" | ".join(cells))
    if not parts:
        raise BadRequestError("PDF 未提取到任何文本（可能是扫描件）")
    return "\n\n".join(parts)


def _parse_docx(file_bytes: bytes) -> str:
    """使用 python-docx 提取 Word 段落与表格。"""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    if not parts:
        raise BadRequestError("Word 文档未提取到任何文本")
    return "\n\n".join(parts)


def _parse_text(file_bytes: bytes, filename: str) -> str:
    """纯文本格式解码（txt/md/csv/json/html/py 等）。"""
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            if text.strip():
                return text
        except (UnicodeDecodeError, ValueError):
            continue
    raise BadRequestError(f"无法解析文件内容：{filename}")


# ============================================================
# RAG 入库与管理
# ============================================================

async def ingest_document(file_bytes: bytes, filename: str) -> int:
    """解析文档 → 语义切片 → 存入 RAG 向量库，返回切片数。"""
    if not is_allowed_extension(filename, ALLOWED_DOC_EXTENSIONS):
        raise BadRequestError(f"不支持的文档类型：{filename}")

    text = parse_document(file_bytes, filename)
    chunks = semantic_chunk(text)
    if not chunks:
        raise BadRequestError("文档切片为空，请检查文档内容")

    store = get_vector_store()
    count = await store.add_document_chunks(chunks, filename)
    if count == 0:
        raise ConflictError("向量库暂不可用（嵌入模型未就绪），文档未入库")
    logger.info("文档已入库 RAG: %s (%d 个切片)", filename, count)
    return count


async def list_documents() -> list[dict]:
    """列出所有 RAG 文档（文件名 + 切片数 + 时间）。"""
    store = get_vector_store()
    return await store.list_documents()


async def delete_document(filename: str) -> bool:
    """删除指定 RAG 文档的全部切片。"""
    store = get_vector_store()
    return await store.delete_document(filename)
