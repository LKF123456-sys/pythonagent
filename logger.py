"""
日志配置模块：统一日志管理，替代 print 输出。
支持控制台 + 文件双输出，文件自动轮转。
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(
    name: str = "multi_agent",
    level: str = "INFO",
    log_file: str = "logs/app.log",
) -> logging.Logger:
    """
    创建并配置日志记录器。

    Args:
        name: 日志记录器名称
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_file: 日志文件路径

    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 统一日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出（自动轮转，单文件最大 5MB，保留 3 个备份）
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
