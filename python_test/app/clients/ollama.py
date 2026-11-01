"""Клиент Ollama (порт 11435) для эмбеддингов: Circuit Breaker + Retry + таймауты.

Используется нативный REST API: POST /api/embeddings {"model", "prompt"} -> {"embedding": [...]}.
Модель: nomic-embed-text (768 измерений).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from enum import StrEnum

import httpx

from app.core.exceptions import EmbeddingError
from app.core.config import Settings

logger = logging.getLogger(__name__)


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Не заслоняем upstream бесконечными попытками: после N ошибок — пауза."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout_s: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.CLOSED
        if time.monotonic() - self._opened_at >= self.recovery_timeout_s:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    async def acquire(self) -> None:
        async with self._lock:
            state = self.state
            if state is BreakerState.OPEN:
                raise EmbeddingError(
                    "Ollama недоступна: circuit breaker открыт, повторите позже",
                    details={"retry_after_s": round(self.recovery_timeout_s)},
                )

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()
                logger.error("Circuit breaker переведён в OPEN (ошибок подряд: %d)", self._failures)


class OllamaEmbeddingClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.request_timeout_s, connect=10.0),
            limits=httpx.Limits(max_connections=settings.index_concurrency * 2, max_keepalive_connections=4),
        )
        self._breaker = CircuitBreaker()

    # ------------------------------ lifecycle --------------------------------
    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> dict[str, str]:
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            wanted = self._settings.embedding_model
            present = any(name == wanted or name.startswith(f"{wanted}:") for name in models)
            if not present:
                return {"status": "degraded", "detail": f"модель '{wanted}' не загружена в ollama"}
            return {"status": "ok", "detail": f"model={wanted}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "down", "detail": exc.__class__.__name__}

    # ------------------------------- запросы ---------------------------------
    async def _embed_once(self, text: str) -> list[float]:
        await self._breaker.acquire()
        payload = {"model": self._settings.embedding_model, "prompt": text, "keep_alive": "5m"}
        url = f"{self._client.base_url}api/embeddings"
        started = time.perf_counter()
        logger.info("Ollama >>> POST %s (model=%s, prompt %d симв.)", url, self._settings.embedding_model, len(text))
        try:
            resp = await self._client.post("/api/embeddings", json=payload)
            resp.raise_for_status()
            vector = resp.json().get("embedding")
        except httpx.HTTPStatusError as exc:
            await self._breaker.record_failure()
            code = exc.response.status_code
            body = ""
            try:
                body = exc.response.text[:300]
            except Exception:  # noqa: BLE001
                pass
            logger.error("Ollama <<< HTTP %d за %.2fs: %s", code, time.perf_counter() - started, body)
            raise EmbeddingError(
                f"Ollama вернула HTTP {code}: {body}",
                details={"status_code": code},
            ) from exc
        except httpx.HTTPError as exc:
            await self._breaker.record_failure()
            logger.error(
                "Ollama <<< сетевая ошибка %s за %.2fs (%s)",
                exc.__class__.__name__, time.perf_counter() - started, url,
            )
            raise EmbeddingError(f"Сетевая ошибка при обращении к Ollama: {exc.__class__.__name__}") from exc
        else:
            elapsed = time.perf_counter() - started
            if not isinstance(vector, list) or not vector:
                await self._breaker.record_failure()
                logger.error("Ollama <<< ответ без поля 'embedding' (за %.2fs)", elapsed)
                raise EmbeddingError("Пустой или некорректный ответ эмбеддинга от Ollama")
            if len(vector) != self._settings.embedding_dim:
                await self._breaker.record_failure()
                logger.error(
                    "Ollama <<< размерность %d != ожидаемая %d — проверьте EMBEDDING_MODEL/EMBEDDING_DIM",
                    len(vector), self._settings.embedding_dim,
                )
                raise EmbeddingError(
                    f"Размерность эмбеддинга {len(vector)} != ожидаемой {self._settings.embedding_dim}",
                    details={"got": len(vector), "expected": self._settings.embedding_dim},
                )
            await self._breaker.record_success()
            logger.info("Ollama <<< OK за %.2fs: вектор размерности %d", elapsed, len(vector))
            return [float(x) for x in vector]

    async def embed(self, text: str) -> list[float]:
        """Эмбеддинг одного текста с экспоненциальным backoff + jitter."""
        attempt = 0
        while True:
            try:
                return await self._embed_once(text)
            except EmbeddingError as exc:
                attempt += 1
                if attempt > self._settings.max_retries:
                    logger.error(
                        "Ollama: все %d попыток исчерпаны, последняя ошибка: %s",
                        self._settings.max_retries + 1, exc,
                    )
                    raise
                delay = min(
                    self._settings.retry_max_backoff_s,
                    self._settings.retry_backoff_base_s * (2 ** (attempt - 1)),
                ) * (0.5 + random.random())
                logger.warning(
                    "Эмбеддинг: попытка %d/%d через %.2fs (причина: %s)",
                    attempt, self._settings.max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Последовательная пакетная обработка («по очереди») софт-ограничена семафором."""
        semaphore = asyncio.Semaphore(self._settings.index_concurrency)

        async def _one(text: str) -> list[float]:
            async with semaphore:
                return await self.embed(text)

        return await asyncio.gather(*(_one(t) for t in texts))
