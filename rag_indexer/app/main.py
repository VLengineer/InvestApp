"""Точка входа FastAPI-микросервиса индексации базы знаний (RAG).

Запуск:  uvicorn app.main:app --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.indexing import router as indexing_router
from app.config import get_settings
from app.services.embedder import OllamaEmbedder
from app.services.indexer import Indexer
from app.services.storage import RagStorage


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    storage = RagStorage(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    try:
        await storage.open(timeout=60)
    except Exception as exc:  # noqa: BLE001 - сервис стартует и без БД, health покажет degraded
        logging.getLogger("rag_indexer").warning("PostgreSQL пока недоступен: %s", exc)
    embedder = OllamaEmbedder(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embed_model,
        timeout=settings.embed_request_timeout,
        max_retries=settings.embed_max_retries,
        expected_dim=settings.embedding_dim,
        concurrency=settings.index_concurrency,
    )
    app.state.settings = settings
    app.state.storage = storage
    app.state.embedder = embedder
    app.state.indexer = Indexer(settings, storage)
    logging.getLogger("rag_indexer").info(
        "RAG-индексатор запущен (kb=%s, ollama=%s, model=%s)",
        settings.knowledge_base_dir, settings.ollama_base_url, settings.ollama_embed_model,
    )
    try:
        yield
    finally:
        if app.state.indexer.busy:
            await app.state.indexer.cancel()
        await embedder.aclose()
        await storage.close()


setup_logging(get_settings().log_level)

app = FastAPI(
    title="RAG Knowledge Base Indexer",
    description=(
        "Микросервис: обход knowledge_base/**/*.json, эмбеддинги через Ollama "
        "(embeddinggemma-2), хранение в PostgreSQL + pgvector "
        "(kb_documents — документ и uuid, kb_embeddings — вектор и uuid документа)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(indexing_router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": "rag-indexer", "docs": "/docs", "health": "/health"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("rag_indexer").exception("Необработанная ошибка на %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Внутренняя ошибка: {type(exc).__name__}"})
