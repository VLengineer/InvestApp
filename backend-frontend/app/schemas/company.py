"""Pydantic-схемы для данных компаний (таблица company_profiles).

Используются в эндпоинтах /api/market/companies — лёгкий справочник
FIGI → название компании для селекторов дашборда.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyFigiItem(BaseModel):
    """Пара FIGI + название компании для dropdown-селектора."""

    figi: str = Field(..., min_length=1, max_length=32, description="FIGI инструмента")
    company_name: str = Field(..., min_length=1, description="Название компании")


class CompanyFigiListResponse(BaseModel):
    """Ответ GET /api/market/companies."""

    companies: list[CompanyFigiItem] = Field(
        default_factory=list,
        description="Список FIGI с названиями компаний",
    )
