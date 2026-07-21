"""日志配置：控制台 + 文件双输出，文件自动轮转。

支持两种格式（LOG_FORMAT）：
- ``text``（默认）：人类可读的管道分隔格式，含 request_id。
- ``json``：结构化 JSON 行，供 ELK / Loki 等集中采集与检索。
所有日志自动注入 request_id（来自 request_context），实现请求级链路关联。
"""

import json
import logging
import os
from logging.handlers import RotatingFileHandler

from app.core.config import get_settings
from app.core.request_context import request_id_var

_configured_loggers: set = set()


class RequestIdFilter(logging.Filter):
    """将当前请求的 request_id 注入日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式器：每行一个 JSON 对象，便于集中采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _build_formatter(log_format: str) -> logging.Formatter:
    """根据配置构造日志格式器。"""
    if log_format.lower() == "json":
        return JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(request_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_logger(name: str = "multi_agent") -> logging.Logger:
    """
    创建并配置日志记录器（幂等）。

    Args:
        name: 日志记录器名称

    Returns:
        配置好的 Logger 实例
    """
    if name in _configured_loggers:
        return logging.getLogger(name)

    settings = get_settings()
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    formatter = _build_formatter(settings.LOG_FORMAT)
    request_id_filter = RequestIdFilter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(request_id_filter)
    logger.addHandler(console_handler)

    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(request_id_filter)
    logger.addHandler(file_handler)

    _configured_loggers.add(name)
    return logger
