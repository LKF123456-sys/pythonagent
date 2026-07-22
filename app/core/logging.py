"""日志配置：控制台 + 文件双输出，文件自动轮转。

支持两种格式（LOG_FORMAT）：
- ``text``（默认）：人类可读的管道分隔格式，含 request_id。
- ``json``：结构化 JSON 行，供 ELK / Loki 等集中采集与检索。
所有日志自动注入 request_id（来自 request_context），实现请求级链路关联。
"""

import json  # 导入json模块，用于结构化日志的JSON序列化
import logging  # 导入logging模块，Python标准日志库
import os  # 导入os模块，用于日志目录创建
from logging.handlers import RotatingFileHandler  # 从logging.handlers导入轮转文件处理器，实现日志文件自动轮转

from app.core.config import get_settings  # 导入配置获取函数，读取日志相关配置
from app.core.request_context import request_id_var  # 导入请求ID上下文变量，用于日志中注入request_id

_configured_loggers: set = set()  # 已配置的日志记录器名称集合，用于幂等控制避免重复配置


class RequestIdFilter(logging.Filter):
    """将当前请求的 request_id 注入日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()  # 从上下文变量获取当前请求ID并附加到日志记录对象
        return True  # 返回True表示允许该日志记录通过


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式器：每行一个 JSON 对象，便于集中采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {  # 构建日志的JSON字典负载
            "ts": self.formatTime(record, self.datefmt),  # 时间戳字段，格式化后的时间
            "level": record.levelname,  # 日志级别字段，如INFO/WARNING/ERROR
            "logger": record.name,  # 日志记录器名称字段
            "request_id": getattr(record, "request_id", "-"),  # 请求ID字段，默认"-"表示无请求上下文
            "msg": record.getMessage(),  # 日志消息字段，格式化后的消息内容
        }
        if record.exc_info:  # 若存在异常信息
            payload["exc"] = self.formatException(record.exc_info)  # 将异常堆栈格式化为字符串并加入负载
        return json.dumps(payload, ensure_ascii=False)  # 将字典序列化为JSON字符串，ensure_ascii=False支持中文


def _build_formatter(log_format: str) -> logging.Formatter:
    """根据配置构造日志格式器。"""
    if log_format.lower() == "json":  # 若配置为JSON格式
        return JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")  # 返回JSON格式器，带时区的ISO时间格式
    return logging.Formatter(  # 返回文本格式器，管道分隔的可读格式
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(request_id)s | %(message)s",  # 格式字符串：时间|级别|记录器名|请求ID|消息
        datefmt="%Y-%m-%d %H:%M:%S",  # 日期格式，不含时区
    )


def setup_logger(name: str = "multi_agent") -> logging.Logger:
    """
    创建并配置日志记录器（幂等）。

    Args:
        name: 日志记录器名称

    Returns:
        配置好的 Logger 实例
    """
    if name in _configured_loggers:  # 若该名称的日志记录器已配置过
        return logging.getLogger(name)  # 直接返回已存在的日志记录器，避免重复添加handler

    settings = get_settings()  # 获取全局配置实例
    logger = logging.getLogger(name)  # 创建或获取指定名称的日志记录器
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))  # 设置日志级别，从配置读取并转为logging常量，默认INFO

    formatter = _build_formatter(settings.LOG_FORMAT)  # 根据配置构造日志格式器
    request_id_filter = RequestIdFilter()  # 创建请求ID过滤器实例

    console_handler = logging.StreamHandler()  # 创建控制台输出handler
    console_handler.setFormatter(formatter)  # 为控制台handler设置格式器
    console_handler.addFilter(request_id_filter)  # 为控制台handler添加请求ID过滤器
    logger.addHandler(console_handler)  # 将控制台handler添加到日志记录器

    log_dir = os.path.dirname(settings.LOG_FILE)  # 获取日志文件所在目录路径
    if log_dir:  # 若日志目录非空
        os.makedirs(log_dir, exist_ok=True)  # 创建日志目录，exist_ok=True表示已存在不报错

    file_handler = RotatingFileHandler(  # 创建轮转文件handler，支持日志文件自动轮转
        settings.LOG_FILE,  # 日志文件路径
        maxBytes=5 * 1024 * 1024,  # 单个日志文件最大字节数，5MB
        backupCount=3,  # 保留的备份文件数量，最多3个历史文件
        encoding="utf-8",  # 文件编码为UTF-8，支持中文
    )
    file_handler.setFormatter(formatter)  # 为文件handler设置格式器
    file_handler.addFilter(request_id_filter)  # 为文件handler添加请求ID过滤器
    logger.addHandler(file_handler)  # 将文件handler添加到日志记录器

    _configured_loggers.add(name)  # 将日志记录器名称加入已配置集合，标记为已配置
    return logger  # 返回配置好的日志记录器
