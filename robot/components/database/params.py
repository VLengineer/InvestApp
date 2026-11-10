"""Параметры для компонента database."""
from dataclasses import dataclass


@dataclass
class DatabaseParams:
    """Параметры для сохранения данных."""
    figi: str
