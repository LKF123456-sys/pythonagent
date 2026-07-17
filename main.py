"""
主入口：多智能体系统的启动。
支持命令行模式（交互式）和 Web 模式（FastAPI + uvicorn）。
"""

import sys
import os
import uuid

# 将本地 libs 目录加入 Python 搜索路径（可选 fallback）
_LIBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
if os.path.isdir(_LIBS_DIR):
    sys.path.insert(0, _LIBS_DIR)

from config import Config
from logger import setup_logger
from graph import run_agent


def main_cli() -> None:
    """命令行模式：交互式多轮对话。"""
    try:
        Config.validate()
    except ValueError as e:
        print(f"\n[配置错误] {e}")
        sys.exit(1)

    logger = setup_logger("main", Config.LOG_LEVEL, Config.LOG_FILE)
    logger.info("多智能体系统启动（命令行模式）")

    thread_id = str(uuid.uuid4())[:8]
    print(f"\n系统就绪。会话ID: {thread_id}")
    print("输入 'quit' 或 'exit' 退出，输入 'new' 开始新对话。\n")

    while True:
        try:
            user_input = input(">>> 请输入问题: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("再见！")
            break

        if user_input.lower() == "new":
            thread_id = str(uuid.uuid4())[:8]
            print(f"\n新对话已开始！会话ID: {thread_id}\n")
            continue

        if not user_input:
            continue

        try:
            answer = run_agent(user_input, thread_id=thread_id)
            print(f"\n{'=' * 60}")
            print(f"[最终回答]\n{answer}")
            print(f"{'=' * 60}\n")
        except Exception as e:
            logger.error("运行错误: %s", e, exc_info=True)
            print(f"\n[运行错误] {e}\n")


def main_web() -> None:
    """Web 模式：启动 FastAPI 服务。"""
    import uvicorn
    try:
        Config.validate()
    except ValueError as e:
        print(f"\n[配置错误] {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  多智能体对话系统 v2.0（FastAPI 异步版）")
    print("  API 文档:  http://127.0.0.1:8000/docs")
    print("  监控指标:  http://127.0.0.1:8000/metrics")
    print("  健康检查:  http://127.0.0.1:8000/api/health")
    print("=" * 60 + "\n")

    uvicorn.run(
        "web_app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level=Config.LOG_LEVEL.lower(),
    )


def main() -> None:
    """根据参数选择启动模式。"""
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        main_cli()
    else:
        main_web()


if __name__ == "__main__":
    main()
