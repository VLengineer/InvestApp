"""Маппинг типов цены для БД."""

# Все типы цены для сбора индикаторов
PRICE_TYPES = [
    "TYPE_OF_PRICE_CLOSE",
    "TYPE_OF_PRICE_OPEN",
    "TYPE_OF_PRICE_HIGH",
    "TYPE_OF_PRICE_LOW",
    "TYPE_OF_PRICE_AVG",
]

# Маппинг типа цены к короткому префиксу для колонок БД
PRICE_TYPE_PREFIX = {
    "TYPE_OF_PRICE_CLOSE": "close",
    "TYPE_OF_PRICE_OPEN": "open",
    "TYPE_OF_PRICE_HIGH": "high",
    "TYPE_OF_PRICE_LOW": "low",
    "TYPE_OF_PRICE_AVG": "avg",
}
