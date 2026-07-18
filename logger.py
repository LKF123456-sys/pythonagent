"""
日志配置模块：统一日志管理，替代 print 输出。
支持控制台 + 文件双输出，文件自动轮转。
"""

# 导入logging模块，用于日志记录
import logging
# 导入os模块，用于目录和路径操作
import os
# 从logging.handlers导入RotatingFileHandler，用于日志文件自动轮转
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
    # 获取或创建指定名称的日志记录器
    logger = logging.getLogger(name)

    # 如果日志记录器已有handler，说明已配置过，直接返回避免重复添加
    if logger.handlers:
        return logger

    # 设置日志级别，将字符串级别转换为logging模块对应的常量
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 定义统一的日志输出格式：时间 | 级别 | 模块名 | 消息
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 创建控制台输出handler，将日志输出到标准输出
    console_handler = logging.StreamHandler()
    # 为控制台handler设置日志格式
    console_handler.setFormatter(formatter)
    # 将控制台handler添加到日志记录器
    logger.addHandler(console_handler)

    # 创建文件输出handler，支持日志文件自动轮转
    # 提取日志文件所在目录路径
    log_dir = os.path.dirname(log_file)
    # 如果日志目录非空（即不是当前目录）
    if log_dir:
        # 确保日志目录存在，若不存在则递归创建
        os.makedirs(log_dir, exist_ok=True)
    # 创建RotatingFileHandler实例：
    # - log_file: 日志文件路径
    # - maxBytes: 单个日志文件最大大小（5MB = 5*1024*1024字节）
    # - backupCount: 保留的备份日志文件数量（最多3个）
    # - encoding: 文件编码为utf-8
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    # 为文件handler设置日志格式
    file_handler.setFormatter(formatter)
    # 将文件handler添加到日志记录器
    logger.addHandler(file_handler)

    # 返回配置完成的日志记录器
    return logger
