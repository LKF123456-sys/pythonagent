"""工业智能制造路由：WebSocket 双向通信 + 故障码查询 + 文档上传 + 会话持久化 REST 端点。"""  # 模块级文档字符串，描述工业智能制造路由功能

import asyncio  # 导入异步IO标准库
import json  # 导入JSON处理标准库
import os  # 导入操作系统接口标准库
from typing import Optional  # 从typing导入Optional，用于可选类型注解

from fastapi import APIRouter, Depends, File, Query, UploadFile, WebSocket, WebSocketDisconnect  # 从FastAPI导入路由器及相关组件
from fastapi.responses import FileResponse  # 从FastAPI响应模块导入文件响应类

from app.core.config import get_settings  # 导入配置获取函数
from app.core.constants import WSClientEvent, WSEventType  # 导入WebSocket客户端和服务端事件类型常量
from app.core.exceptions import AppException  # 导入应用异常基类
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.core.security import validate_upload_path  # 导入上传路径校验函数
from app.agents.manufacturing.graph import MfgGraphStreamEvent, run_mfg_agent_stream  # 导入工业图流事件类型和运行函数
from app.repositories import conversation_repo, message_repo  # 导入会话和消息数据访问仓库
from app.routers.deps import get_current_user, verify_access_token  # 导入当前用户依赖和令牌校验函数
from app.services import document_service  # 导入文档业务服务

logger = setup_logger("router.manufacturing")  # 创建名为router.manufacturing的日志记录器

router = APIRouter(tags=["工业智能制造"])  # 创建工业路由器，仅设置API文档标签


# ============================================================  # 分隔注释
# WebSocket 连接管理器（工业专属）  # 说明该部分为工业专属连接管理器
# ============================================================  # 分隔注释

class MfgConnectionManager:  # 定义工业WebSocket连接管理器类
    """管理工业模块多用户并发 WebSocket 连接。"""  # 类文档字符串

    def __init__(self) -> None:  # 初始化方法
        self._connections: dict[int, set[WebSocket]] = {}  # 用户ID到WebSocket集合的映射字典

    def connect(self, user_id: int, websocket: WebSocket) -> None:  # 添加连接的方法
        self._connections.setdefault(user_id, set()).add(websocket)  # 为用户添加WebSocket连接到集合

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:  # 移除连接的方法
        conns = self._connections.get(user_id)  # 获取该用户的所有连接
        if conns:  # 如果存在连接集合
            conns.discard(websocket)  # 从集合中移除指定连接
            if not conns:  # 如果集合已空
                del self._connections[user_id]  # 删除该用户的键值对

    def active_count(self, user_id: Optional[int] = None) -> int:  # 获取活跃连接数的方法
        if user_id is not None:  # 如果指定了用户ID
            return len(self._connections.get(user_id, set()))  # 返回该用户的连接数
        return sum(len(conns) for conns in self._connections.values())  # 否则返回所有用户的总连接数


mfg_manager = MfgConnectionManager()  # 实例化全局工业连接管理器


# ============================================================  # 分隔注释
# 事件序列化  # 说明该部分为事件序列化逻辑
# ============================================================  # 分隔注释

def _mfg_event_to_wire(event: MfgGraphStreamEvent, session_id: str) -> dict:  # 定义工业事件到线缆协议的转换函数
    """将 MfgGraphStreamEvent 映射为 WebSocket 线缆协议。"""  # 函数文档字符串
    if event.type == "status":  # 如果事件类型为status
        return {  # 返回状态事件字典
            "type": WSEventType.STATUS.value,  # 事件类型字符串
            "node": event.node,  # 当前节点名称
            "message": event.content,  # 状态消息内容
            "session_id": session_id,  # 会话ID
        }
    if event.type == "thinking":  # 如果事件类型为thinking
        return {"type": WSEventType.THINKING.value, "content": event.content}  # 返回思考事件字典
    if event.type == "token":  # 如果事件类型为token
        return {"type": WSEventType.TOKEN.value, "content": event.content}  # 返回token事件字典
    if event.type == "done":  # 如果事件类型为done
        return {  # 返回完成事件字典
            "type": WSEventType.DONE.value,  # 事件类型字符串
            "answer": event.answer,  # 最终回答内容
            "session_id": session_id,  # 会话ID
            "route": event.route,  # 路由信息
            "token_count": event.token_count,  # token用量统计
        }
    if event.type == "error":  # 如果事件类型为error
        return {"type": WSEventType.ERROR.value, "message": event.content}  # 返回错误事件字典
    return {"type": event.type}  # 其他未知类型，仅返回类型字段


async def _run_mfg_chat_stream(  # 定义工业聊天流执行协程函数
    websocket: WebSocket,  # WebSocket连接对象
    user_id: int,  # 用户ID
    session_id: str,  # 会话ID
    question: str,  # 用户问题
    image_filename: str = "",  # 图片文件名，默认空
) -> None:  # 无返回值
    """在独立任务中执行工业聊天流，将事件推送至 WebSocket，并持久化会话。"""  # 函数文档字符串
    # 解析图片路径  # 内部注释，说明下面解析图片路径
    image_path = ""  # 初始化图片路径为空
    if image_filename:  # 如果提供了图片文件名
        settings = get_settings()  # 获取配置
        candidate = os.path.join(settings.UPLOAD_FOLDER, image_filename)  # 拼接候选完整路径
        if validate_upload_path(candidate, settings.UPLOAD_FOLDER) and os.path.isfile(candidate):  # 校验路径合法且文件存在
            image_path = candidate  # 设置图片路径为候选路径

    # 持久化：确保会话存在 + 存储用户消息  # 内部注释，说明持久化逻辑
    try:  # 尝试持久化
        existing = await conversation_repo.get_conversation(session_id, user_id)  # 查询会话是否存在
        if existing is None:  # 如果会话不存在
            title = question[:20] + ("..." if len(question) > 20 else "")  # 截取问题前20字符作为标题
            await conversation_repo.create_conversation(session_id, user_id, title, conv_type="mfg")  # 创建工业会话
        await message_repo.add_message(session_id, "user", question, image_filename=image_filename)  # 存储用户消息
    except Exception as e:  # 持久化失败
        logger.warning("工业会话持久化失败（不影响回答）: %s", e)  # 记录警告日志，不影响后续处理

    try:  # 开始聊天流执行
        final_answer = ""  # 最终回答，初始为空
        final_tokens = 0  # 最终token用量，初始为0
        async for event in run_mfg_agent_stream(  # 异步迭代工业智能体产生的事件
            user_question=question,  # 用户问题
            thread_id=f"mfg_{session_id}",  # 线程ID，工业前缀
            history_context="",  # 历史上下文，暂为空
            user_id=user_id,  # 用户ID
            image_path=image_path,  # 图片路径
        ):
            await websocket.send_json(_mfg_event_to_wire(event, session_id))  # 序列化并发送事件
            if event.type == "done":  # 如果是完成事件
                final_answer = event.answer  # 记录最终回答
                final_tokens = event.token_count  # 记录token用量

        # 持久化：存储助手回答  # 内部注释，说明持久化助手回答
        if final_answer:  # 如果有最终回答
            try:  # 尝试持久化助手回答
                await message_repo.add_message(session_id, "assistant", final_answer, final_tokens)  # 存储助手消息
                await conversation_repo.update_conversation_time(session_id)  # 更新会话活跃时间
            except Exception as e:  # 持久化失败
                logger.warning("工业回答持久化失败: %s", e)  # 记录警告日志

    except asyncio.CancelledError:  # 如果任务被取消
        raise  # 重新抛出取消异常
    except Exception as e:  # 捕获其他异常
        logger.exception("WebSocket 工业聊天流出错")  # 记录异常日志
        try:  # 尝试发送错误事件
            await websocket.send_json(  # 向客户端发送错误JSON
                {"type": WSEventType.ERROR.value, "message": f"处理失败：{e}"}  # 错误事件内容
            )
        except Exception:  # 如果发送失败
            pass  # 忽略发送错误


# ============================================================  # 分隔注释
# WebSocket 端点  # 说明该部分为WebSocket端点定义
# ============================================================  # 分隔注释

@router.websocket("/ws/manufacturing/{session_id}")  # 注册WebSocket路由，路径为/ws/manufacturing/{session_id}
async def websocket_manufacturing(  # 定义工业WebSocket处理函数
    websocket: WebSocket,  # WebSocket连接对象
    session_id: str,  # 路径参数，会话ID
    token: str = Query(default=""),  # 查询参数，认证令牌
) -> None:  # 无返回值
    """
    工业智能制造 WebSocket 端点。

    客户端→服务端：
      {"type": "chat", "question": "..."}
      {"type": "abort"}
      {"type": "ping"}
    服务端→客户端：
      {"type": "status|thinking|token|done|error|pong", ...}
    """  # 端点文档字符串，描述双向通信协议
    # 连接前认证  # 内部注释说明认证时机
    try:  # 尝试验证令牌
        user = await verify_access_token(token)  # 校验访问令牌并获取用户信息
    except AppException:  # 如果认证失败
        await websocket.close(code=4401, reason="认证失败")  # 关闭WebSocket连接
        return  # 直接返回

    await websocket.accept()  # 接受WebSocket连接
    user_id = user["id"]  # 获取用户ID
    mfg_manager.connect(user_id, websocket)  # 将连接注册到管理器
    logger.info("工业 WebSocket 已连接: user=%d session=%s", user_id, session_id)  # 记录连接日志

    current_task: Optional[asyncio.Task] = None  # 当前聊天流任务，初始为空
    try:  # 开始主循环异常捕获
        while True:  # 无限循环接收消息
            raw = await websocket.receive_text()  # 接收客户端发送的文本消息
            try:  # 尝试解析JSON
                msg = json.loads(raw)  # 将文本消息解析为JSON字典
            except json.JSONDecodeError:  # 如果JSON解析失败
                await websocket.send_json(  # 发送错误事件
                    {"type": WSEventType.ERROR.value, "message": "消息格式无效"}  # 错误内容
                )
                continue  # 跳过本次循环

            mtype = msg.get("type", "")  # 获取消息类型字段

            if mtype == WSClientEvent.PING.value:  # 如果是ping消息
                await websocket.send_json({"type": WSEventType.PONG.value})  # 回复pong消息

            elif mtype == WSClientEvent.CHAT.value:  # 如果是聊天消息
                question = (msg.get("question") or "").strip()  # 获取并去除首尾空白的问题
                image_filename = msg.get("image_filename") or ""  # 获取图片文件名，默认空字符串
                if not question:  # 如果问题为空
                    await websocket.send_json(  # 发送错误事件
                        {"type": WSEventType.ERROR.value, "message": "问题不能为空"}  # 错误内容
                    )
                    continue  # 跳过本次循环
                # 取消上一轮未完成的流  # 内部注释说明取消逻辑
                if current_task and not current_task.done():  # 如果存在未完成的上轮任务
                    current_task.cancel()  # 取消上轮任务
                current_task = asyncio.create_task(  # 创建新的聊天流任务
                    _run_mfg_chat_stream(websocket, user_id, session_id, question, image_filename)  # 执行工业聊天流
                )

            elif mtype == WSClientEvent.ABORT.value:  # 如果是中止消息
                if current_task and not current_task.done():  # 如果存在未完成的任务
                    current_task.cancel()  # 取消当前任务
                    await websocket.send_json(  # 发送已中止的完成事件
                        {
                            "type": WSEventType.DONE.value,  # 事件类型为done
                            "answer": "",  # 空回答
                            "session_id": session_id,  # 会话ID
                            "aborted": True,  # 标记为已中止
                        }
                    )

    except WebSocketDisconnect:  # 如果客户端断开连接
        logger.info("工业 WebSocket 断开: user=%d", user_id)  # 记录断开日志
    except Exception as e:  # 捕获其他异常
        logger.warning("工业 WebSocket 异常: %s", e)  # 记录警告日志
    finally:  # 最终清理
        if current_task and not current_task.done():  # 如果仍有未完成任务
            current_task.cancel()  # 取消任务避免泄露
        mfg_manager.disconnect(user_id, websocket)  # 从管理器移除连接


# ============================================================  # 分隔注释
# REST 端点：故障码查询  # 说明该部分为故障码查询REST端点
# ============================================================  # 分隔注释

@router.get("/api/manufacturing/fault-codes")  # 注册GET路由，查询故障码
async def query_fault_codes(code: str = Query(default="", description="故障码关键词")):  # 定义异步查询故障码函数
    """查询故障码信息（支持模糊搜索）。"""  # 路由文档字符串
    try:  # 尝试查询
        from app.agents.manufacturing.knowledge import search_fault_codes  # 延迟导入故障码搜索函数
        results = search_fault_codes(code)  # 执行故障码搜索
        return {"success": True, "data": results, "count": len(results)}  # 返回成功响应
    except Exception as e:  # 捕获异常
        logger.warning("故障码查询失败: %s", e)  # 记录警告日志
        return {"success": False, "error": str(e), "data": [], "count": 0}  # 返回失败响应


@router.get("/api/manufacturing/equipment")  # 注册GET路由，查询设备参数
async def query_equipment(model: str = Query(default="", description="设备型号")):  # 定义异步查询设备函数
    """查询设备参数信息。"""  # 路由文档字符串
    try:  # 尝试查询
        from app.agents.manufacturing.knowledge import search_equipment_specs  # 延迟导入设备规格搜索函数
        results = search_equipment_specs(model)  # 执行设备规格搜索
        return {"success": True, "data": results, "count": len(results)}  # 返回成功响应
    except Exception as e:  # 捕获异常
        logger.warning("设备参数查询失败: %s", e)  # 记录警告日志
        return {"success": False, "error": str(e), "data": [], "count": 0}  # 返回失败响应


# ============================================================  # 分隔注释
# REST 端点：工业图片上传（复用通用上传逻辑）  # 说明该部分为工业图片上传
# ============================================================  # 分隔注释

@router.post("/api/manufacturing/upload-image")  # 注册POST路由，上传工业图片
async def upload_mfg_image(  # 定义异步上传工业图片函数
    file: UploadFile = File(...),  # 必填上传文件参数
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
):  # 返回类型由返回值推断
    """上传工业场景图片（设备铭牌、故障截图、仪表盘等），返回存储文件名。"""  # 路由文档字符串
    content = await file.read()  # 读取上传文件内容为字节
    saved_name = document_service.save_image_upload(content, file.filename or "image.png")  # 安全保存图片并返回文件名
    return {"filename": saved_name}  # 返回存储文件名


# ============================================================  # 分隔注释
# REST 端点：工业 RAG 文档上传  # 说明该部分为工业RAG文档上传
# ============================================================  # 分隔注释

@router.post("/api/manufacturing/documents/upload")  # 注册POST路由，上传工业文档
async def upload_mfg_document(  # 定义异步上传工业文档函数
    file: UploadFile = File(...),  # 必填上传文件参数
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
):  # 返回类型由返回值推断
    """上传工业文档到 RAG 知识库（解析 + 语义切片 + 向量化入库）。"""  # 路由文档字符串
    content = await file.read()  # 读取上传文件内容为字节
    filename = file.filename or "document.txt"  # 获取文件名，默认document.txt
    chunks = await document_service.ingest_document(content, filename)  # 调用服务层解析并入库文档
    return {"filename": filename, "chunks": chunks}  # 返回文件名和切片数


@router.get("/api/manufacturing/documents")  # 注册GET路由，获取工业文档列表
async def list_mfg_documents(user: dict = Depends(get_current_user)):  # 定义异步获取工业文档列表函数
    """列出工业 RAG 知识库中的所有文档。"""  # 路由文档字符串
    documents = await document_service.list_documents()  # 调用服务层获取文档列表
    return {"documents": documents, "total": len(documents)}  # 返回文档列表和总数


@router.delete("/api/manufacturing/documents/{filename}", status_code=204)  # 注册DELETE路由，删除工业文档
async def delete_mfg_document(  # 定义异步删除工业文档函数
    filename: str,  # 路径参数，文档文件名
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> None:  # 无返回值
    """删除指定工业文档及其全部向量切片。"""  # 路由文档字符串
    from app.core.exceptions import NotFoundError  # 延迟导入未找到异常类
    deleted = await document_service.delete_document(filename)  # 调用服务层删除文档
    if not deleted:  # 如果删除失败
        raise NotFoundError("文档不存在")  # 抛出未找到异常


# ============================================================  # 分隔注释
# REST 端点：图片服务（让前端能在对话中显示图片）  # 说明该部分为图片服务端点
# ============================================================  # 分隔注释

@router.get("/api/uploads/{filename}")  # 注册GET路由，提供已上传图片访问
async def serve_upload(filename: str, token: str = Query(default="")):  # 定义异步图片服务函数
    """提供已上传图片的访问（支持 query token 认证，用于 img src）。"""  # 路由文档字符串
    try:  # 尝试验证令牌
        await verify_access_token(token)  # 校验访问令牌
    except AppException:  # 如果认证失败
        from fastapi import HTTPException  # 延迟导入HTTPException
        raise HTTPException(status_code=401, detail="认证失败")  # 抛出401异常
    settings = get_settings()  # 获取配置
    filepath = os.path.join(settings.UPLOAD_FOLDER, filename)  # 拼接完整文件路径
    if not validate_upload_path(filepath, settings.UPLOAD_FOLDER) or not os.path.isfile(filepath):  # 校验路径合法且文件存在
        from app.core.exceptions import NotFoundError  # 延迟导入未找到异常类
        raise NotFoundError("文件不存在")  # 抛出未找到异常
    return FileResponse(filepath)  # 返回文件响应
