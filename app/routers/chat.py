"""聊天路由：WebSocket 双向通信（替代 SSE）+ 非流式端点 + 图片上传。"""  # 模块级文档字符串，描述聊天路由功能

import asyncio  # 导入异步IO标准库
import json  # 导入JSON处理标准库
from typing import Optional  # 从typing导入Optional，用于可选类型注解

from fastapi import APIRouter, Depends, File, Query, UploadFile, WebSocket, WebSocketDisconnect  # 从FastAPI导入路由器和相关组件
from app.core.constants import WSClientEvent, WSEventType  # 导入WebSocket客户端事件和服务端事件类型常量
from app.core.exceptions import AppException, UnauthorizedError  # 导入应用异常基类和未授权异常
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.agents.graph import GraphStreamEvent  # 导入图流事件类型
from app.models.chat import ChatRequest, ChatResponse, UploadResponse  # 导入聊天相关的Pydantic模型
from app.routers.deps import get_current_user, verify_access_token  # 导入当前用户依赖和令牌校验函数
from app.services import chat_service, document_service  # 导入聊天和文档业务服务

logger = setup_logger("router.chat")  # 创建名为router.chat的日志记录器

router = APIRouter(tags=["聊天"])  # 创建聊天路由器，仅设置API文档标签


# ============================================================  # 分隔注释
# WebSocket 连接管理器  # 说明该部分为WebSocket连接管理器
# ============================================================  # 分隔注释

class ConnectionManager:  # 定义WebSocket连接管理器类
    """管理多用户并发 WebSocket 连接。"""  # 类文档字符串

    def __init__(self) -> None:  # 初始化方法
        self._connections: dict[int, set[WebSocket]] = {}  # 用户ID到WebSocket集合的映射字典

    def connect(self, user_id: int, websocket: WebSocket) -> None:  # 添加连接的方法
        self._connections.setdefault(user_id, set()).add(websocket)  # 为用户添加WebSocket连接到集合

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:  # 移除连接的方法
        conns = self._connections.get(user_id)  # 获取该用户的所有连接
        if conns:  # 如果存在连接集合
            conns.discard(websocket)  # 从集合中移除指定连接
            if not conns:  # 如果集合已空
                del self._connections[user_id]  # 删除该用户的键值对，避免空集合占用内存

    def active_count(self, user_id: Optional[int] = None) -> int:  # 获取活跃连接数的方法
        if user_id is not None:  # 如果指定了用户ID
            return len(self._connections.get(user_id, set()))  # 返回该用户的连接数
        return sum(len(conns) for conns in self._connections.values())  # 否则返回所有用户的总连接数


manager = ConnectionManager()  # 实例化全局连接管理器


# ============================================================  # 分隔注释
# 事件序列化  # 说明该部分为事件序列化逻辑
# ============================================================  # 分隔注释

def _event_to_wire(event: GraphStreamEvent, session_id: str) -> dict:  # 定义事件到线缆协议的转换函数
    """将 GraphStreamEvent 映射为 WebSocket 线缆协议（JSON）。"""  # 函数文档字符串
    if event.type == "status":  # 如果事件类型为status（状态）
        return {  # 返回状态事件字典
            "type": WSEventType.STATUS.value,  # 事件类型字符串
            "node": event.node,  # 当前节点名称
            "message": event.content,  # 状态消息内容
            "session_id": session_id,  # 会话ID
        }
    if event.type == "thinking":  # 如果事件类型为thinking（思考过程）
        return {"type": WSEventType.THINKING.value, "content": event.content}  # 返回思考事件字典
    if event.type == "token":  # 如果事件类型为token（流式token）
        return {"type": WSEventType.TOKEN.value, "content": event.content}  # 返回token事件字典
    if event.type == "done":  # 如果事件类型为done（完成）
        return {  # 返回完成事件字典
            "type": WSEventType.DONE.value,  # 事件类型字符串
            "answer": event.answer,  # 最终回答内容
            "session_id": session_id,  # 会话ID
            "route": event.route,  # 路由信息
            "token_count": event.token_count,  # token用量统计
        }
    if event.type == "error":  # 如果事件类型为error（错误）
        return {"type": WSEventType.ERROR.value, "message": event.content}  # 返回错误事件字典
    return {"type": event.type}  # 其他未知类型，仅返回类型字段


async def _run_chat_stream(  # 定义在独立任务中执行聊天流的协程函数
    websocket: WebSocket,  # WebSocket连接对象
    user_id: int,  # 用户ID
    session_id: str,  # 会话ID
    question: str,  # 用户问题
    image_filename: str,  # 图片文件名（可选）
) -> None:  # 无返回值
    """在独立任务中执行聊天流，将事件推送至 WebSocket（可被取消）。"""  # 函数文档字符串
    try:  # 开始异常捕获
        async for event in chat_service.chat_stream(  # 异步迭代聊天服务产生的流事件
            user_id=user_id,  # 用户ID
            question=question,  # 用户问题
            session_id=session_id,  # 会话ID
            image_filename=image_filename,  # 图片文件名
        ):
            await websocket.send_json(_event_to_wire(event, session_id))  # 将事件序列化后发送到WebSocket
    except asyncio.CancelledError:  # 如果任务被取消
        # 用户中断生成：由主循环发送 aborted done 事件  # 内部注释说明取消原因
        raise  # 重新抛出取消异常，交由上层处理
    except Exception as e:  # 捕获其他异常
        logger.exception("WebSocket 聊天流出错")  # 记录异常日志
        try:  # 尝试发送错误事件
            await websocket.send_json(  # 向客户端发送错误JSON
                {"type": WSEventType.ERROR.value, "message": f"处理失败：{e}"}  # 错误事件内容
            )
        except Exception:  # 如果发送失败
            pass  # 忽略发送错误


# ============================================================  # 分隔注释
# WebSocket 端点  # 说明该部分为WebSocket端点定义
# ============================================================  # 分隔注释

@router.websocket("/ws/chat/{session_id}")  # 注册WebSocket路由，路径为/ws/chat/{session_id}
async def websocket_chat(  # 定义WebSocket聊天处理函数
    websocket: WebSocket,  # WebSocket连接对象
    session_id: str,  # 路径参数，会话ID
    token: str = Query(default=""),  # 查询参数，认证令牌
) -> None:  # 无返回值
    """
    聊天 WebSocket 端点。

    客户端→服务端：
      {"type": "chat", "question": "...", "image_filename": "..."}
      {"type": "abort"}
      {"type": "ping"}
    服务端→客户端：
      {"type": "status|thinking|token|done|error|pong", ...}
    """  # 端点文档字符串，描述双向通信协议
    # 连接前认证（token 无效直接拒绝握手）  # 内部注释说明认证时机
    try:  # 尝试验证令牌
        user = await verify_access_token(token)  # 校验访问令牌并获取用户信息
    except AppException:  # 如果认证失败
        await websocket.close(code=4401, reason="认证失败")  # 关闭WebSocket连接，返回自定义码4401
        return  # 直接返回，不继续处理

    await websocket.accept()  # 接受WebSocket连接
    user_id = user["id"]  # 获取用户ID
    manager.connect(user_id, websocket)  # 将连接注册到管理器
    logger.info("WebSocket 已连接: user=%d session=%s", user_id, session_id)  # 记录连接日志

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
                    _run_chat_stream(websocket, user_id, session_id, question, image_filename)  # 执行聊天流
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
        logger.info("WebSocket 断开: user=%d", user_id)  # 记录断开日志
    except Exception as e:  # 捕获其他异常
        logger.warning("WebSocket 异常: %s", e)  # 记录警告日志
    finally:  # 最终清理
        if current_task and not current_task.done():  # 如果仍有未完成任务
            current_task.cancel()  # 取消任务避免泄露
        manager.disconnect(user_id, websocket)  # 从管理器移除连接


# ============================================================  # 分隔注释
# REST 端点（非流式 + 图片上传）  # 说明该部分为REST端点
# ============================================================  # 分隔注释

@router.post("/chat", response_model=ChatResponse)  # 注册POST路由，非流式聊天
async def chat(  # 定义异步聊天函数
    body: ChatRequest,  # 请求体，包含问题和会话信息
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> ChatResponse:  # 返回聊天响应模型
    """非流式聊天（同步返回完整回答）。"""  # 路由文档字符串
    return await chat_service.chat_non_stream(  # 调用服务层非流式聊天
        user_id=user["id"],  # 用户ID
        question=body.question,  # 用户问题
        session_id=body.session_id,  # 会话ID
        image_filename=body.image_filename or "",  # 图片文件名，默认空
    )


@router.post("/chat/upload-image", response_model=UploadResponse)  # 注册POST路由，上传图片
async def upload_image(  # 定义异步图片上传函数
    file: UploadFile = File(...),  # 必填上传文件参数
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> UploadResponse:  # 返回上传响应模型
    """上传聊天图片（校验类型/大小/路径），返回存储文件名。"""  # 路由文档字符串
    content = await file.read()  # 读取上传文件内容为字节
    saved_name = document_service.save_image_upload(content, file.filename or "image.png")  # 安全保存图片并返回文件名
    return UploadResponse(filename=saved_name)  # 返回上传响应，包含存储文件名
