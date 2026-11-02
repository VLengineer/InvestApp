"""FastAPI-приложение (по подобию существующего rag-сервиса)."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.routers import company_profiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

app = FastAPI(title="Company Profiles RAG Service")

app.include_router(company_profiles.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
