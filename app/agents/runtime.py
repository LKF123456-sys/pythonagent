"""智能体运行时依赖注册表：由 FastAPI lifespan 在启动时注入共享服务。

避免在节点函数中使用模块级全局可变状态，
同时让 LangGraph 节点能够访问 VectorStore 等共享服务。
"""

from typing import Optional  # 从typing导入Optional类型，用于可选类型注解

from app.memory.vector_store import VectorStore  # 导入向量存储类，用于类型注解和实例引用

_vector_store: Optional[VectorStore] = None  # 全局向量存储实例，初始为None，由FastAPI启动时注入


def set_vector_store(store: VectorStore) -> None:  # 定义注入向量存储实例的函数
    """注入向量存储实例（应用启动时调用）。"""
    global _vector_store  # 声明使用全局_vector_store变量
    _vector_store = store  # 将传入的store赋值给全局变量


def get_vector_store() -> VectorStore:  # 定义获取向量存储实例的函数，返回VectorStore实例
    """获取向量存储实例。"""
    if _vector_store is None:  # 如果向量存储实例尚未初始化
        raise RuntimeError("VectorStore 未初始化，请检查应用启动流程")  # 抛出运行时错误，提示检查启动流程
    return _vector_store  # 返回已注入的向量存储实例
