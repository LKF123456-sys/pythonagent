"""管理后台业务逻辑：用户管理 / 系统统计 / 深度健康检查。"""

import time

import httpx

from app.core.config import get_settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import setup_logger
from app.agents.runtime import get_vector_store
from app.db.connection import get_pool
from app.repositories import message_repo, user_repo

logger = setup_logger("service.admin")


# ============================================================
# 用户管理
# ============================================================

async def list_users() -> list[dict]:
    """列出所有用户。"""
    return await user_repo.list_users()


async def set_user_active(user_id: int, is_active: bool) -> dict:
    """启用/禁用用户，返回更新后的用户信息。"""
    target = await user_repo.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError("用户不存在")
    if target["is_admin"] and not is_active:
        raise BadRequestError("不能禁用管理员账号")

    ok = await user_repo.set_user_active(user_id, is_active)
    if not ok:
        raise NotFoundError("用户不存在")
    logger.info("用户状态变更: id=%d is_active=%s", user_id, is_active)
    return await user_repo.get_user_by_id(user_id)


# ============================================================
# 系统统计
# ============================================================

async def get_system_stats() -> dict:
    """系统级统计：用户数 / 会话数 / 消息数 / Token 用量。"""
    return await message_repo.get_system_stats()


# ============================================================
# 深度健康检查
# ============================================================

async def deep_health_check() -> dict:
    """
    深度健康检查：PostgreSQL / pgvector / Ollama / LLM API。

    返回各组件状态 + 整体 healthy/degraded 判定。
    """
    settings = get_settings()
    components: dict = {}

    # PostgreSQL 连通性
    components["database"] = await _check_database()

    # pgvector 可用性
    components["vector_store"] = _check_vector_store()

    # Ollama 可达
    components["ollama"] = await _check_ollama(settings.OLLAMA_BASE_URL)

    # LLM API 可达（可选，超时 2s）
    components["llm_api"] = await _check_llm_api(settings)

    all_ok = all(c["status"] == "ok" for c in components.values())
    # LLM API 为可选项，其失败只导致 degraded 而非 unhealthy
    critical_ok = all(
        components[k]["status"] == "ok" for k in ("database",)
    )
    overall = "healthy" if all_ok else ("degraded" if critical_ok else "unhealthy")

    return {"status": overall, "components": components}


async def _check_database() -> dict:
    try:
        pool = get_pool()
        row = await pool.fetch_one('SELECT 1 AS "ok"')
        return {"status": "ok" if row and row["ok"] == 1 else "error"}
    except Exception as e:
        logger.warning("健康检查: PostgreSQL 失败 - %s", e)
        return {"status": "error", "detail": str(e)}


def _check_vector_store() -> dict:
    try:
        store = get_vector_store()
        if store.available:
            return {"status": "ok"}
        return {"status": "degraded", "detail": "pgvector 未就绪"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


async def _check_ollama(base_url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                return {"status": "ok", "models": models}
            return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "detail": f"Ollama 不可达: {e}"}


async def _check_llm_api(settings) -> dict:
    """LLM API 可达性探测（列出模型，超时 2s）。"""
    if not settings.OPENAI_API_KEY:
        return {"status": "degraded", "detail": "未配置 API Key"}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                f"{settings.OPENAI_BASE_URL}/models",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            )
            return {"status": "ok" if resp.status_code == 200 else "degraded"}
    except Exception as e:
        return {"status": "degraded", "detail": f"LLM API 探测超时: {e}"}
