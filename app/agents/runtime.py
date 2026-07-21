"""智能体运行时依赖注册表：由 FastAPI lifespan 在启动时注入共享服务。

避免在节点函数中使用模块级全局可变状态，
同时让 LangGraph 节点能够访问 VectorStore 等共享服务。
"""

from typing import Optional

from app.memory.vector_store import VectorStore

_vector_store: Optional[VectorStore] = None


def set_vector_store(store: VectorStore) -> None:
    """注入向量存储实例（应用启动时调用）。"""
    global _vector_store
    _vector_store = store


def get_vector_store() -> VectorStore:
    """获取向量存储实例。"""
    if _vector_store is None:
        raise RuntimeError("VectorStore 未初始化，请检查应用启动流程")
    return _vector_store
