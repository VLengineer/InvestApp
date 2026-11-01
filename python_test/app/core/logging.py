"""Настройка логирования: структурированный вывод, маскирование секретов."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

_SENSITIVE_KEYS = ("password", "secret", "token", "api_key", "authorization", "dsn")
_URL_CREDENTIALS_RE = re.compile(r"://[^:/\s]+:[^@/\s]+@")


def mask(value: str) -> str:
    """Маскирует учётные данные в URL и значения чувствительных ключей."""
    masked = _URL_CREDENTIALS_RE.sub("://***:***@", value)
    return masked


class SensitiveDataFilter(logging.Filter):
    """Не пускает секреты ни в один лог (defense-in-depth)."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        msg = record.getMessage()
        record.msg = mask(msg)
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)
    root.setLevel(level)

    # Болтливые библиотеки — только ошибки
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter:
    return logging.LoggerAdapter(logging.getLogger(name), {})


def log_safe(logger: logging.Logger, level: int, message: Any, **kwargs: Any) -> None:
    logger.log(level, mask(str(message)), **kwargs)
