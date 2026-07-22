"""Gunicorn + Uvicorn worker 配置：多进程部署。"""

import multiprocessing  # 导入多进程模块，用于自动计算worker数量
import os  # 导入操作系统模块，用于读取环境变量

# 绑定地址：从环境变量读取或默认0.0.0.0:8000
bind = os.getenv("BIND", "0.0.0.0:8000")  # 服务绑定地址和端口

# Worker数量：默认CPU核数*2+1，也可通过环境变量覆盖
workers = int(os.getenv("WORKERS", multiprocessing.cpu_count() * 2 + 1))  # worker进程数

# Worker类：使用uvicorn的ASGI worker支持异步
worker_class = "uvicorn.workers.UvicornWorker"  # 使用UvicornWorker处理异步请求

# 每个worker的并发请求数
worker_connections = int(os.getenv("WORKER_CONNECTIONS", 1000))  # 每个worker最大并发连接数

# 超时设置：长对话需要较长超时
timeout = int(os.getenv("TIMEOUT", 120))  # 请求超时时间（秒），AI对话可能较慢

# 优雅关闭超时
graceful_timeout = int(os.getenv("GRACEFUL_TIMEOUT", 30))  # 优雅关闭等待时间（秒）

# keepalive 设置
keepalive = int(os.getenv("KEEPALIVE", 5))  # keepalive连接保持时间（秒）

# 最大请求数：防止内存泄漏，处理指定数量请求后重启worker
max_requests = int(os.getenv("MAX_REQUESTS", 1000))  # 每个worker处理的最大请求数
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", 50))  # 添加随机抖动避免所有worker同时重启

# 预加载应用：减少内存使用但加快启动
preload_app = True  # 预加载应用代码，所有worker共享

# 日志配置
accesslog = "-"  # 访问日志输出到标准输出
errorlog = "-"  # 错误日志输出到标准错误
loglevel = os.getenv("LOG_LEVEL", "info")  # 日志级别

# 进程名
proc_name = "multi_agent_system"  # 进程名称，便于监控识别
