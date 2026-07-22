"""管理后台业务逻辑：用户管理 / 系统统计 / 深度健康检查。"""  # 模块级文档字符串，描述管理后台业务逻辑

import time  # 导入时间标准库（注：本模块未直接使用，保留导入）

import httpx  # 导入httpx异步HTTP客户端库

from app.core.config import get_settings  # 导入配置获取函数
from app.core.exceptions import BadRequestError, NotFoundError  # 导入错误请求和未找到异常
from app.core.logging import setup_logger  # 导入日志记录器配置函数
from app.agents.runtime import get_vector_store  # 导入向量库获取函数
from app.db.connection import get_pool  # 导入数据库连接池获取函数
from app.repositories import message_repo, user_repo  # 导入消息和用户数据访问仓库

logger = setup_logger("service.admin")  # 创建名为service.admin的日志记录器


# ============================================================  # 分隔注释
# 用户管理  # 说明该部分为用户管理逻辑
# ============================================================  # 分隔注释

async def list_users() -> list[dict]:  # 定义列出所有用户协程函数
    """列出所有用户。"""  # 函数文档字符串
    return await user_repo.list_users()  # 调用仓库层获取用户列表


async def set_user_active(user_id: int, is_active: bool) -> dict:  # 定义启用/禁用用户协程函数
    """启用/禁用用户，返回更新后的用户信息。"""  # 函数文档字符串
    target = await user_repo.get_user_by_id(user_id)  # 查询目标用户
    if target is None:  # 如果用户不存在
        raise NotFoundError("用户不存在")  # 抛出未找到异常
    if target["is_admin"] and not is_active:  # 如果尝试禁用管理员
        raise BadRequestError("不能禁用管理员账号")  # 抛出错误请求异常

    ok = await user_repo.set_user_active(user_id, is_active)  # 更新用户激活状态
    if not ok:  # 如果更新失败
        raise NotFoundError("用户不存在")  # 抛出未找到异常
    logger.info("用户状态变更: id=%d is_active=%s", user_id, is_active)  # 记录状态变更日志
    return await user_repo.get_user_by_id(user_id)  # 返回更新后的用户信息


# ============================================================  # 分隔注释
# 系统统计  # 说明该部分为系统统计逻辑
# ============================================================  # 分隔注释

async def get_system_stats() -> dict:  # 定义系统统计协程函数
    """系统级统计：用户数 / 会话数 / 消息数 / Token 用量。"""  # 函数文档字符串
    return await message_repo.get_system_stats()  # 调用仓库层获取系统统计


# ============================================================  # 分隔注释
# 深度健康检查  # 说明该部分为深度健康检查逻辑
# ============================================================  # 分隔注释

async def deep_health_check() -> dict:  # 定义深度健康检查协程函数
    """
    深度健康检查：PostgreSQL / pgvector / Ollama / LLM API。

    返回各组件状态 + 整体 healthy/degraded 判定。
    """  # 函数文档字符串
    settings = get_settings()  # 获取配置
    components: dict = {}  # 初始化组件状态字典

    # PostgreSQL 连通性  # 内部注释，检查PostgreSQL
    components["database"] = await _check_database()  # 检查数据库

    # pgvector 可用性  # 内部注释，检查pgvector
    components["vector_store"] = _check_vector_store()  # 检查向量库

    # Ollama 可达  # 内部注释，检查Ollama
    components["ollama"] = await _check_ollama(settings.OLLAMA_BASE_URL)  # 检查Ollama服务

    # LLM API 可达（可选，超时 2s）  # 内部注释，检查LLM API
    components["llm_api"] = await _check_llm_api(settings)  # 检查LLM API

    all_ok = all(c["status"] == "ok" for c in components.values())  # 判断所有组件是否都正常
    # LLM API 为可选项，其失败只导致 degraded 而非 unhealthy  # 内部注释说明降级逻辑
    critical_ok = all(  # 判断关键组件（仅数据库）是否正常
        components[k]["status"] == "ok" for k in ("database",)  # 关键组件为数据库
    )
    overall = "healthy" if all_ok else ("degraded" if critical_ok else "unhealthy")  # 综合判定整体状态

    return {"status": overall, "components": components}  # 返回整体状态和组件详情


async def _check_database() -> dict:  # 定义数据库检查协程函数
    try:  # 尝试查询数据库
        pool = get_pool()  # 获取连接池
        row = await pool.fetch_one('SELECT 1 AS "ok"')  # 执行简单查询测试连通性
        return {"status": "ok" if row and row["ok"] == 1 else "error"}  # 返回状态字典
    except Exception as e:  # 捕获异常
        logger.warning("健康检查: PostgreSQL 失败 - %s", e)  # 记录警告日志
        return {"status": "error", "detail": str(e)}  # 返回错误状态


def _check_vector_store() -> dict:  # 定义向量库检查函数
    try:  # 尝试检查向量库
        store = get_vector_store()  # 获取向量库实例
        if store.available:  # 如果向量库可用
            return {"status": "ok"}  # 返回正常状态
        return {"status": "degraded", "detail": "pgvector 未就绪"}  # 返回降级状态
    except Exception as e:  # 捕获异常
        return {"status": "error", "detail": str(e)}  # 返回错误状态


async def _check_ollama(base_url: str) -> dict:  # 定义Ollama检查协程函数
    try:  # 尝试访问Ollama
        async with httpx.AsyncClient(timeout=2.0) as client:  # 创建异步HTTP客户端，2秒超时
            resp = await client.get(f"{base_url}/api/tags")  # 请求Ollama模型列表接口
            if resp.status_code == 200:  # 如果响应正常
                models = [m.get("name", "") for m in resp.json().get("models", [])]  # 提取模型名称列表
                return {"status": "ok", "models": models}  # 返回正常状态和模型列表
            return {"status": "error", "detail": f"HTTP {resp.status_code}"}  # 返回错误状态
    except Exception as e:  # 捕获异常
        return {"status": "error", "detail": f"Ollama 不可达: {e}"}  # 返回错误状态


async def _check_llm_api(settings) -> dict:  # 定义LLM API检查协程函数
    """LLM API 可达性探测（列出模型，超时 2s）。"""  # 函数文档字符串
    if not settings.OPENAI_API_KEY:  # 如果未配置API Key
        return {"status": "degraded", "detail": "未配置 API Key"}  # 返回降级状态
    try:  # 尝试访问LLM API
        async with httpx.AsyncClient(timeout=2.0) as client:  # 创建异步HTTP客户端，2秒超时
            resp = await client.get(  # 请求模型列表接口
                f"{settings.OPENAI_BASE_URL}/models",  # 模型列表URL
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},  # 认证头
            )
            return {"status": "ok" if resp.status_code == 200 else "degraded"}  # 返回状态
    except Exception as e:  # 捕获异常
        return {"status": "degraded", "detail": f"LLM API 探测超时: {e}"}  # 返回降级状态
