"""文档路由：RAG 文档上传 / 列表 / 删除。"""  # 模块级文档字符串，描述文档路由功能

from fastapi import APIRouter, Depends, File, UploadFile  # 从FastAPI导入路由器、依赖注入、文件上传相关组件

from app.core.exceptions import NotFoundError  # 导入未找到异常类
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.models.chat import DocumentUploadResponse  # 导入文档上传响应模型
from app.routers.deps import get_current_user  # 导入当前用户依赖，用于身份校验
from app.services import document_service  # 导入文档业务逻辑服务模块

logger = setup_logger("router.documents")  # 创建名为router.documents的日志记录器

router = APIRouter(prefix="/documents", tags=["文档"])  # 创建文档路由器，设置URL前缀和API文档标签


@router.post("/upload", response_model=DocumentUploadResponse)  # 注册POST路由，上传文档
async def upload_document(  # 定义异步上传文档函数
    file: UploadFile = File(...),  # 必填上传文件参数
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> DocumentUploadResponse:  # 返回文档上传响应模型
    """上传文档到 RAG 知识库（解析 + 语义切片 + 向量化入库）。"""  # 路由文档字符串
    content = await file.read()  # 读取上传文件内容为字节
    filename = file.filename or "document.txt"  # 获取文件名，默认document.txt
    chunks = await document_service.ingest_document(content, filename)  # 调用服务层解析并入库文档，返回切片数
    return DocumentUploadResponse(filename=filename, chunks=chunks)  # 返回上传响应


@router.get("")  # 注册GET路由，路径为/api/documents，获取文档列表
async def list_documents(user: dict = Depends(get_current_user)) -> dict:  # 定义异步获取文档列表函数
    """列出 RAG 知识库中的所有文档。"""  # 路由文档字符串
    documents = await document_service.list_documents()  # 调用服务层获取文档列表
    return {"documents": documents, "total": len(documents)}  # 返回文档列表和总数


@router.delete("/{filename}", status_code=204)  # 注册DELETE路由，删除文档，返回204无内容
async def delete_document(  # 定义异步删除文档函数
    filename: str,  # 路径参数，文档文件名
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> None:  # 无返回值
    """删除指定文档及其全部向量切片。"""  # 路由文档字符串
    deleted = await document_service.delete_document(filename)  # 调用服务层删除文档
    if not deleted:  # 如果删除失败（文档不存在）
        raise NotFoundError("文档不存在")  # 抛出未找到异常
