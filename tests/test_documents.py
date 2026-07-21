"""文档处理测试：多格式解析（PDF/docx/文本）+ 上传安全 + RAG 端点。"""

import io
import os
import uuid

import pytest

from app.core.config import get_settings
from app.core.exceptions import BadRequestError, PayloadTooLargeError
from app.core.security import is_allowed_extension, sanitize_filename, validate_upload_path
from app.services import document_service
from app.core.constants import ALLOWED_DOC_EXTENSIONS, ALLOWED_IMAGE_EXTENSIONS


# ============================================================
# 测试文件构造辅助
# ============================================================

def _make_pdf(text: str) -> bytes:
    """构造一个最小有效 PDF（含正确 xref 偏移），供 pdfplumber 解析。"""
    content_stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content_stream)).encode() + b" >>\nstream\n"
        + content_stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n")
    xref_pos = out.tell()
    out.write(b"xref\n0 " + str(len(objs) + 1).encode() + b"\n")
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(("%010d 00000 n \n" % off).encode())
    out.write(
        b"trailer\n<< /Size " + str(len(objs) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return out.getvalue()


def _make_docx(paragraphs: list) -> bytes:
    """使用 python-docx 构造真实 Word 文档字节。"""
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ============================================================
# 文档解析
# ============================================================

class TestParseDocument:
    def test_parse_txt(self):
        text = document_service.parse_document(b"hello plain text", "note.txt")
        assert text == "hello plain text"

    def test_parse_markdown(self):
        content = "# 标题\n\n正文内容"
        text = document_service.parse_document(content.encode("utf-8"), "doc.md")
        assert "标题" in text and "正文内容" in text

    def test_parse_gbk_fallback(self):
        """UTF-8 解码失败时应回退到 GBK。"""
        gbk_bytes = "中文GBK编码内容".encode("gbk")
        text = document_service.parse_document(gbk_bytes, "gbk.txt")
        assert "中文GBK编码内容" in text

    def test_parse_pdf(self):
        pdf_bytes = _make_pdf("Hello PDF World 12345")
        text = document_service.parse_document(pdf_bytes, "sample.pdf")
        assert "Hello PDF World 12345" in text

    def test_parse_docx(self):
        docx_bytes = _make_docx(["Word 第一段", "Word 第二段"])
        text = document_service.parse_document(docx_bytes, "sample.docx")
        assert "Word 第一段" in text
        assert "Word 第二段" in text

    def test_parse_empty_text_raises(self):
        with pytest.raises(BadRequestError):
            document_service.parse_document(b"   \n  ", "empty.txt")


# ============================================================
# 文件名消毒与路径防护
# ============================================================

class TestFilenameSanitization:
    def test_strips_path_traversal(self):
        """../ 注入应被剥离，仅保留最后路径段。"""
        safe = sanitize_filename("../../etc/passwd")
        assert ".." not in safe
        assert "/" not in safe
        assert "passwd" in safe

    def test_strips_backslash_traversal(self):
        safe = sanitize_filename("..\\..\\windows\\system32.dll")
        assert ".." not in safe
        assert "\\" not in safe

    def test_removes_unsafe_chars(self):
        safe = sanitize_filename('a<b>c:d"e|f?g*h.txt')
        assert all(c not in safe for c in '<>:"|?*')

    def test_uuid_prefix_uniqueness(self):
        a = sanitize_filename("same.txt")
        b = sanitize_filename("same.txt")
        assert a != b  # UUID 前缀保证唯一

    def test_empty_becomes_default(self):
        safe = sanitize_filename("....")
        assert safe.endswith("upload")

    def test_validate_path_inside_allowed(self, tmp_path):
        root = str(tmp_path)
        good = os.path.join(root, "file.txt")
        assert validate_upload_path(good, root) is True

    def test_validate_path_traversal_blocked(self, tmp_path):
        root = str(tmp_path)
        evil = os.path.join(root, "..", "outside.txt")
        assert validate_upload_path(evil, root) is False

    def test_is_allowed_extension(self):
        assert is_allowed_extension("a.pdf", ALLOWED_DOC_EXTENSIONS) is True
        assert is_allowed_extension("a.exe", ALLOWED_DOC_EXTENSIONS) is False
        assert is_allowed_extension("noext", ALLOWED_DOC_EXTENSIONS) is False
        assert is_allowed_extension("a.PNG", ALLOWED_IMAGE_EXTENSIONS) is True


# ============================================================
# 安全上传（save_upload）
# ============================================================

class TestSaveUpload:
    def test_save_upload_success(self, app):
        name = document_service.save_upload(b"data", "ok.txt", ALLOWED_DOC_EXTENSIONS)
        settings = get_settings()
        assert os.path.isfile(os.path.join(settings.UPLOAD_FOLDER, name))

    def test_save_upload_rejects_bad_extension(self, app):
        with pytest.raises(BadRequestError):
            document_service.save_upload(b"data", "virus.exe", ALLOWED_DOC_EXTENSIONS)

    def test_save_upload_rejects_oversize(self, app):
        """超过 MAX_UPLOAD_SIZE_MB 应抛出 PayloadTooLargeError。"""
        settings = get_settings()
        original = settings.MAX_UPLOAD_SIZE_MB
        settings.MAX_UPLOAD_SIZE_MB = 1  # 临时收紧到 1MB
        try:
            big = b"x" * (2 * 1024 * 1024)  # 2MB
            with pytest.raises(PayloadTooLargeError):
                document_service.save_upload(big, "big.txt", ALLOWED_DOC_EXTENSIONS)
        finally:
            settings.MAX_UPLOAD_SIZE_MB = original


# ============================================================
# RAG 文档端点（集成测试，使用 FakeVectorStore）
# ============================================================

class TestDocumentEndpoints:
    async def test_upload_document(self, client, auth_headers):
        files = {"file": ("知识.txt", "# 章节\n\n这是知识库内容".encode("utf-8"), "text/plain")}
        resp = await client.post("/api/documents/upload", headers=auth_headers, files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "知识.txt"
        assert data["chunks"] >= 1

    async def test_upload_rejects_bad_type(self, client, auth_headers):
        files = {"file": ("bad.exe", b"MZ...", "application/octet-stream")}
        resp = await client.post("/api/documents/upload", headers=auth_headers, files=files)
        assert resp.status_code == 400

    async def test_list_documents(self, client, auth_headers):
        files = {"file": ("list.txt", b"content for listing", "text/plain")}
        await client.post("/api/documents/upload", headers=auth_headers, files=files)
        resp = await client.get("/api/documents", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(d["filename"] == "list.txt" for d in data["documents"])

    async def test_delete_document(self, client, auth_headers):
        files = {"file": ("todelete.txt", b"to be deleted", "text/plain")}
        await client.post("/api/documents/upload", headers=auth_headers, files=files)
        resp = await client.delete("/api/documents/todelete.txt", headers=auth_headers)
        assert resp.status_code == 204
        # 删除后列表中不再出现
        listing = await client.get("/api/documents", headers=auth_headers)
        assert all(d["filename"] != "todelete.txt" for d in listing.json()["documents"])

    async def test_delete_nonexistent_404(self, client, auth_headers):
        resp = await client.delete("/api/documents/no_such_doc.txt", headers=auth_headers)
        assert resp.status_code == 404

    async def test_upload_requires_auth(self, client):
        files = {"file": ("x.txt", b"data", "text/plain")}
        resp = await client.post("/api/documents/upload", files=files)
        assert resp.status_code in (401, 403)
