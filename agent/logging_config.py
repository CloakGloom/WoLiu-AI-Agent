"""
统一结构化日志模块
用法：
    from agent.logging_config import get_logger
    logger = get_logger("mymodule")
    logger.info("event_name", extra={"key": "value"})

所有日志自动带时间戳、模块名、级别，方便 grep / 日志分析。
"""
import logging
import sys
from datetime import datetime


class StructuredFormatter(logging.Formatter):
    """结构化日志格式：时间 [模块] 级别 消息 | key=value ..."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        base = f"{ts} [{record.name}] {record.levelname} {record.getMessage()}"
        # 附加 extra 字段（排除标准字段）
        std_keys = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process",
        }
        extras = {k: v for k, v in record.__dict__.items()
                  if k not in std_keys and not k.startswith("_")}
        if extras:
            parts = [f"{k}={v}" for k, v in extras.items()]
            base += " | " + " | ".join(parts)
        if record.exc_info and record.exc_info[0]:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str = "INFO"):
    """初始化全局日志配置（模块级单次调用）"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 清除已有 handler，避免重复
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)
    # 抑制第三方库的噪音日志
    for noisy in ("chromadb", "httpx", "httpcore", "urllib3", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取结构化日志 Logger"""
    return logging.getLogger(name)
