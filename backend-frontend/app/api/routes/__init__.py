"""Единая точка сборки API-роутеров микросервиса (паттерн python_test)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, market_data

api_router = APIRouter()
api_router.include_router(health.router)
# REST рынка для Vue-дашборда: /api/market/*
api_router.include_router(market_data.router)

__all__ = ["api_router"]
