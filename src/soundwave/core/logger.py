from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogFlow(Enum):
    SOURCE = "source"
    FILTER = "filter"
    STORAGE = "storage"
    AI = "ai"
    CONFIG = "config"


class Logger:
    _instance = None
    _use_color = True

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "RESET": "\033[0m",
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def set_color(cls, enabled: bool):
        cls._use_color = enabled

    @classmethod
    def _format(cls, level: LogLevel, flow: LogFlow, module: str, message: str) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_str = level.value
        flow_str = flow.value

        if cls._use_color:
            color = cls.COLORS.get(level_str, "")
            reset = cls.COLORS["RESET"]
            return f"[{timestamp}][{color}{level_str}{reset}][{flow_str}][{module}] {message}"
        else:
            return f"[{timestamp}][{level_str}][{flow_str}][{module}] {message}"

    @classmethod
    def debug(cls, flow: LogFlow, module: str, message: str):
        print(cls._format(LogLevel.DEBUG, flow, module, message), flush=True)

    @classmethod
    def info(cls, flow: LogFlow, module: str, message: str):
        print(cls._format(LogLevel.INFO, flow, module, message), flush=True)

    @classmethod
    def warning(cls, flow: LogFlow, module: str, message: str):
        print(cls._format(LogLevel.WARNING, flow, module, message), flush=True)

    @classmethod
    def error(cls, flow: LogFlow, module: str, message: str):
        print(cls._format(LogLevel.ERROR, flow, module, message), flush=True)


def get_logger() -> Logger:
    return Logger()


__all__ = ["Logger", "LogLevel", "LogFlow", "get_logger"]