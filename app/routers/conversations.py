"""会话路由：列表 / 消息 / 重命名 / 删除 / 导出 / Token 统计。"""  # 模块级文档字符串，描述会话路由功能

from fastapi import APIRouter, Depends, Query, Response  # 从FastAPI导入路由器、依赖注入、查询参数和响应对象

from app.models.conversation import (  # 从会话模型模块导入多个Pydantic模型
    ConversationItem,  # 单个会话项模型
    ConversationListResponse,  # 会话列表响应模型
    MessageItem,  # 单条消息项模型
    MessageListResponse,  # 消息列表响应模型
    RenameRequest,  # 重命名请求模型
    TokenStatsItem,  # Token统计项模型
    TokenStatsResponse,  # Token统计响应模型
)
from app.routers.deps import get_current_user  # 导入当前用户依赖，用于身份校验
from app.services import conversation_service  # 导入会话业务逻辑服务模块

router = APIRouter(prefix="/api/conversations", tags=["会话"])  # 创建会话路由器，设置URL前缀和API文档标签


@router.get("", response_model=ConversationListResponse)  # 注册GET路由，路径为/api/conversations，获取会话列表
async def list_conversations(  # 定义异步获取会话列表函数
    conv_type: str = Query(default="general", pattern="^(general|mfg)$"),  # 查询参数，会话类型，限定为general或mfg
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> ConversationListResponse:  # 返回会话列表响应模型
    """获取当前用户的会话列表（支持按类型过滤：general/mfg）。"""  # 路由文档字符串
    rows = await conversation_service.list_conversations(user["id"], conv_type)  # 调用服务层获取会话列表
    return ConversationListResponse(  # 构造并返回响应
        conversations=[ConversationItem(**row) for row in rows]  # 将每行数据转换为会话项模型
    )


@router.get("/{session_id}/messages", response_model=MessageListResponse)  # 注册GET路由，获取会话消息列表
async def get_messages(  # 定义异步获取消息函数
    session_id: str,  # 路径参数，会话ID
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> MessageListResponse:  # 返回消息列表响应模型
    """获取会话的消息列表。"""  # 路由文档字符串
    rows = await conversation_service.get_messages(session_id, user["id"])  # 调用服务层获取消息列表
    return MessageListResponse(messages=[MessageItem(**row) for row in rows])  # 转换并返回消息列表响应


@router.patch("/{session_id}", status_code=204)  # 注册PATCH路由，重命名会话，返回204无内容
async def rename_conversation(  # 定义异步重命名会话函数
    session_id: str,  # 路径参数，会话ID
    body: RenameRequest,  # 请求体，包含新标题
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> None:  # 无返回值
    """重命名会话。"""  # 路由文档字符串
    await conversation_service.rename_conversation(session_id, user["id"], body.title)  # 调用服务层重命名会话


@router.delete("/{session_id}", status_code=204)  # 注册DELETE路由，删除会话，返回204无内容
async def delete_conversation(  # 定义异步删除会话函数
    session_id: str,  # 路径参数，会话ID
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> None:  # 无返回值
    """删除会话及其全部消息。"""  # 路由文档字符串
    await conversation_service.delete_conversation(session_id, user["id"])  # 调用服务层删除会话


@router.get("/{session_id}/export")  # 注册GET路由，导出会话内容
async def export_conversation(  # 定义异步导出会话函数
    session_id: str,  # 路径参数，会话ID
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),  # 查询参数，导出格式
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> Response:  # 返回HTTP响应对象
    """导出会话为 Markdown 或 JSON 文件。"""  # 路由文档字符串
    content = await conversation_service.export_conversation(session_id, user["id"], format)  # 调用服务层生成导出内容
    if format == "json":  # 如果格式为JSON
        return Response(  # 返回JSON响应
            content=content,  # 响应内容
            media_type="application/json",  # 媒体类型为JSON
            headers={  # 设置响应头
                "Content-Disposition": f'attachment; filename="{session_id}.json"'  # 指定下载文件名
            },
        )
    return Response(  # 返回Markdown响应
        content=content,  # 响应内容
        media_type="text/markdown; charset=utf-8",  # 媒体类型为Markdown，UTF-8编码
        headers={  # 设置响应头
            "Content-Disposition": f'attachment; filename="{session_id}.md"'  # 指定下载文件名
        },
    )


# ============================================================  # 分隔注释
# Token 统计（独立前缀，避免与 /{session_id} 冲突）  # 说明该部分为Token统计，使用独立前缀避免路由冲突
# ============================================================  # 分隔注释

stats_router = APIRouter(prefix="/api/stats", tags=["统计"])  # 创建统计路由器，设置URL前缀和API文档标签


@stats_router.get("/tokens", response_model=TokenStatsResponse)  # 注册GET路由，获取Token统计
async def token_stats(  # 定义异步Token统计函数
    days: int = Query(default=30, ge=1, le=365),  # 查询参数，统计天数，1-365之间
    user: dict = Depends(get_current_user),  # 依赖注入当前用户校验
) -> TokenStatsResponse:  # 返回Token统计响应模型
    """获取当前用户的 Token 用量统计（累计 + 按日）。"""  # 路由文档字符串
    stats = await conversation_service.get_token_stats(user["id"], days)  # 调用服务层获取Token统计
    return TokenStatsResponse(  # 构造并返回响应
        total_tokens=stats["total_tokens"],  # 累计Token用量
        daily=[TokenStatsItem(**row) for row in stats["daily"]],  # 按日统计列表
    )
