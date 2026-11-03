"""Единая точка сборки API-роутеров микросервиса."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import company_profiles, health, indicators, rag

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(rag.router)
# Теханализ: POST /indicators/calculate (код — в app/services/indicators_service.py)
api_router.include_router(indicators.router)
# Профили компаний: /company-profiles/* (код — в app/services/company_profiles_service.py)
api_router.include_router(company_profiles.router)

__all__ = ["api_router"]
