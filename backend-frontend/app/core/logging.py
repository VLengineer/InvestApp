"""Настройка логирования: вывод в консоль, маскирование секретов (паттерн python_test/scheduler_service)."""

from __future__ import annotations

import logging
import re
import sys

_SENSITIVE_RE = re.compile(r"://[^:/\s]+:[^@\s/]+@")


def mask(value: str) -> str:
    """Маскирует учётные данные в URL (пароли в DSN не должны попадать в логи)."""
    return _SENSITIVE_RE.sub("://***:***@", value)


class SensitiveDataFilter(logging.Filter):
    """Не пускает секреты ни в один лог (defense-in-depth)."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.msg = mask(record.getMessage())
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
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
