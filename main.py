"""
主入口：多智能体系统的启动（新分层架构）。
支持命令行模式（交互式）和 Web 模式（FastAPI + uvicorn）。

Web 模式指向 app.main:app（新架构应用工厂）。
CLI 模式直接调用 app.agents.graph.run_agent。
"""  # 模块级文档字符串，描述主入口的功能和两种启动模式

import asyncio  # 导入异步IO标准库
import sys  # 导入系统相关标准库
import uuid  # 导入UUID生成标准库


def main_cli() -> None:  # 定义命令行模式启动函数
    """命令行模式：交互式多轮对话。"""  # 函数文档字符串
    from app.core.config import get_settings  # 延迟导入配置获取函数
    from app.core.logging import setup_logger  # 延迟导入日志记录器配置函数
    from app.agents.graph import run_agent  # 延迟导入智能体运行函数
    from app.agents.runtime import set_vector_store  # 延迟导入向量库注入函数
    from app.memory.vector_store import VectorStore  # 延迟导入向量库类

    settings = get_settings()  # 获取配置
    try:  # 尝试校验配置
        settings.validate_security()  # 安全校验
        settings.validate_required()  # 必要配置校验
    except ValueError as e:  # 如果校验失败
        print(f"\n[配置错误] {e}")  # 打印错误信息
        sys.exit(1)  # 退出程序，返回错误码1

    logger = setup_logger("main")  # 创建名为main的日志记录器
    logger.info("多智能体系统启动（命令行模式）")  # 记录启动日志

    # CLI 模式初始化向量库（记忆 / RAG 节点依赖）  # 内部注释
    set_vector_store(VectorStore())  # 注入向量库实例到运行时

    async def _loop() -> None:  # 定义异步交互循环
        thread_id = str(uuid.uuid4())[:8]  # 生成8字符的会话ID
        print(f"\n系统就绪。会话ID: {thread_id}")  # 打印会话ID
        print("输入 'quit' 或 'exit' 退出，输入 'new' 开始新对话。\n")  # 打印使用说明

        while True:  # 无限循环
            try:  # 尝试读取输入
                user_input = input(">>> 请输入问题: ").strip()  # 读取用户输入并去除空白
            except (EOFError, KeyboardInterrupt):  # 如果遇到EOF或中断
                print("\n再见！")  # 打印告别信息
                break  # 退出循环

            if user_input.lower() in ("quit", "exit", "q"):  # 如果输入退出命令
                print("再见！")  # 打印告别信息
                break  # 退出循环

            if user_input.lower() == "new":  # 如果输入new命令
                thread_id = str(uuid.uuid4())[:8]  # 生成新会话ID
                print(f"\n新对话已开始！会话ID: {thread_id}\n")  # 打印新会话信息
                continue  # 跳过本次循环

            if not user_input:  # 如果输入为空
                continue  # 跳过本次循环

            try:  # 尝试运行智能体
                answer = await run_agent(user_input, thread_id=thread_id)  # 调用智能体获取回答
                print(f"\n{'=' * 60}")  # 打印分隔线
                print(f"[最终回答]\n{answer}")  # 打印最终回答
                print(f"{'=' * 60}\n")  # 打印分隔线
            except Exception as e:  # 捕获异常
                logger.error("运行错误: %s", e, exc_info=True)  # 记录错误日志
                print(f"\n[运行错误] {e}\n")  # 打印错误信息

    asyncio.run(_loop())  # 运行异步交互循环


def main_web() -> None:  # 定义Web模式启动函数
    """Web 模式：启动 FastAPI 服务（新架构 app.main:app）。"""  # 函数文档字符串
    import uvicorn  # 延迟导入uvicorn服务器

    from app.core.config import get_settings  # 延迟导入配置获取函数

    settings = get_settings()  # 获取配置

    print("\n" + "=" * 60)  # 打印分隔线
    print("  多智能体对话系统 v2.0（FastAPI 异步版）")  # 打印系统标题
    print("  API 文档:  http://127.0.0.1:8000/docs")  # 打印API文档地址
    print("  监控指标:  http://127.0.0.1:8000/metrics")  # 打印监控指标地址
    print("  健康检查:  http://127.0.0.1:8000/api/health")  # 打印健康检查地址
    print("=" * 60 + "\n")  # 打印分隔线

    uvicorn.run(  # 启动uvicorn服务
        "app.main:app",  # 应用路径
        host="127.0.0.1",  # 监听地址
        port=8000,  # 监听端口
        reload=False,  # 不启用热重载
        log_level=settings.LOG_LEVEL.lower(),  # 日志级别，转小写
    )


def main() -> None:  # 定义主入口函数
    """根据参数选择启动模式。"""  # 函数文档字符串
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":  # 如果第一个参数是--cli
        main_cli()  # 启动命令行模式
    else:  # 否则
        main_web()  # 启动Web模式


if __name__ == "__main__":  # 如果直接运行本模块
    main()  # 调用主入口函数
