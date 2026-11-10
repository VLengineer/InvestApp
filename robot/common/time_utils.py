"""Утилиты для работы с временем."""
from datetime import datetime


def parse_iso_timestamp(ts_str: str) -> datetime:
    """
    Парсит ISO-8601 timestamp строку в datetime с timezone.
    
    Поддерживает форматы:
    - '2024-11-10T04:00:00Z'
    - '2024-11-10T04:00:00+00:00'
    """
    ts_str = ts_str.replace('Z', '+00:00')
    return datetime.fromisoformat(ts_str)
