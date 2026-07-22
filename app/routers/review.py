"""人工审批路由：查看待审批请求并批准/拒绝。"""  # 模块级文档字符串，描述人工审批路由功能

from fastapi import APIRouter, Depends  # 导入FastAPI路由和依赖注入
from pydantic import BaseModel  # 导入Pydantic基础模型
from app.core.config import get_settings  # 导入配置
from app.core.logging import setup_logger  # 导入日志

router = APIRouter(prefix="/review", tags=["人工审批"])  # 创建审批路由器

logger = setup_logger("routers.review")  # 创建专用日志记录器

class ReviewRequest(BaseModel):  # 审批请求模型
    """人工审批请求模型。"""
    thread_id: str  # 会话线程ID
    action: str  # 审批动作：approved 或 rejected

class ReviewResponse(BaseModel):  # 审批响应模型
    """人工审批响应模型。"""
    success: bool  # 是否成功
    message: str  # 结果消息

@router.post("/approve", response_model=ReviewResponse)  # 批准审批接口
async def approve_request(req: ReviewRequest):  # 定义批准异步函数
    """批准一个等待人工审批的请求。"""
    # 使用 LangGraph 的 Command 恢复执行
    from langgraph.types import Command  # 导入Command用于恢复图执行
    from app.agents.graph import get_graph  # 导入图实例获取函数
    graph = get_graph()  # 获取编译后的图单例
    config = {"configurable": {"thread_id": req.thread_id}}  # 构建配置
    try:  # 尝试恢复执行
        await graph.ainvoke(Command(resume="approved"), config=config)  # 传入approved恢复执行
        return ReviewResponse(success=True, message="审批已通过，请求继续执行")  # 返回成功响应
    except Exception as e:  # 捕获异常
        logger.error("审批恢复失败: %s", e)  # 记录错误日志
        return ReviewResponse(success=False, message=f"审批恢复失败: {e}")  # 返回失败响应

@router.post("/reject", response_model=ReviewResponse)  # 拒绝审批接口
async def reject_request(req: ReviewRequest):  # 定义拒绝异步函数
    """拒绝一个等待人工审批的请求。"""
    from langgraph.types import Command  # 导入Command
    from app.agents.graph import get_graph  # 导入图实例
    graph = get_graph()  # 获取图单例
    config = {"configurable": {"thread_id": req.thread_id}}  # 构建配置
    try:  # 尝试恢复执行
        await graph.ainvoke(Command(resume="rejected"), config=config)  # 传入rejected恢复执行
        return ReviewResponse(success=True, message="审批已拒绝，请求已终止")  # 返回成功响应
    except Exception as e:  # 捕获异常
        logger.error("拒绝恢复失败: %s", e)  # 记录错误日志
        return ReviewResponse(success=False, message=f"拒绝操作失败: {e}")  # 返回失败响应
