"""文档路由：RAG 文档上传 / 列表 / 删除。"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.exceptions import NotFoundError
from app.core.logging import setup_logger
from app.models.chat import DocumentUploadResponse
from app.routers.deps import get_current_user
from app.services import document_service

logger = setup_logger("router.documents")

router = APIRouter(prefix="/api/documents", tags=["文档"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> DocumentUploadResponse:
    """上传文档到 RAG 知识库（解析 + 语义切片 + 向量化入库）。"""
    content = await file.read()
    filename = file.filename or "document.txt"
    chunks = await document_service.ingest_document(content, filename)
    return DocumentUploadResponse(filename=filename, chunks=chunks)


@router.get("")
async def list_documents(user: dict = Depends(get_current_user)) -> dict:
    """列出 RAG 知识库中的所有文档。"""
    documents = await document_service.list_documents()
    return {"documents": documents, "total": len(documents)}


@router.delete("/{filename}", status_code=204)
async def delete_document(
    filename: str,
    user: dict = Depends(get_current_user),
) -> None:
    """删除指定文档及其全部向量切片。"""
    deleted = await document_service.delete_document(filename)
    if not deleted:
        raise NotFoundError("文档不存在")
