"""Клиент Ollama для получения эмбеддингов (модель embeddinggemma-2).

Используется нативный эндпоинт ``POST /api/embed`` (поддерживает батчи),
с повторными попытками и проверкой размерности вектора.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

import httpx

log = logging.getLogger("rag_indexer.embedder")


class EmbeddingError(RuntimeError):
    pass


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int = 120,
        max_retries: int = 3,
        expected_dim: int | None = None,
        concurrency: int = 2,
    ) -> None:
        # base_url может быть как ".../api", так и ".../" — нормализуем к ".../api"
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/api"):
            self.base_url = f"{self.base_url}/api"
        self.model = model
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.expected_dim = expected_dim
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Эмбеддинги для списка текстов (порядок сохраняется)."""
        if not texts:
            return []
        payload = {"model": self.model, "input": list(texts)}
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._semaphore:
                    client = await self._get_client()
                    resp = await client.post("/embed", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                vectors = data.get("embeddings")
                if not isinstance(vectors, list) or len(vectors) != len(texts):
                    raise EmbeddingError(
                        f"Ollama вернула {len(vectors) if isinstance(vectors, list) else 'нет'} "
                        f"векторов вместо {len(texts)}"
                    )
                for vec in vectors:
                    self._check_vector(vec)
                return [[float(x) for x in vec] for vec in vectors]
            except (httpx.HTTPError, EmbeddingError, ValueError) as exc:
                last_error = exc
                log.warning(
                    "Запрос эмбеддингов (попытка %d/%d) завершилась ошибкой: %s",
                    attempt, self.max_retries, exc,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 15))
        raise EmbeddingError(f"Не удалось получить эмбеддинги: {last_error}")

    def _check_vector(self, vec: object) -> None:
        if not isinstance(vec, list) or not vec:
            raise EmbeddingError("Пустой или некорректный вектор в ответе Ollama")
        if self.expected_dim and len(vec) != self.expected_dim:
            raise EmbeddingError(
                f"Размерность вектора {len(vec)} не совпадает с ожидаемой {self.expected_dim} "
                f"(проверьте EMBEDDING_DIM и модель {self.model})"
            )

    async def embed_batched(self, texts: Sequence[str], batch_size: int = 8) -> list[list[float]]:
        """Эмбеддинги большого списка текстов батчами (батчи выполняются параллельно)."""
        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
        results = await asyncio.gather(*(self.embed(b) for b in batches))
        return [vec for batch in results for vec in batch]

    async def health(self) -> dict[str, object]:
        """Проверяет доступность Ollama и наличие модели; возвращает краткую сводку."""
        client = await self._get_client()
        info: dict[str, object] = {"base_url": self.base_url, "model": self.model}
        try:
            resp = await client.get("/tags")
            resp.raise_for_status()
            names = [m.get("name") for m in resp.json().get("models", [])]
            info["available_models"] = names
            info["model_present"] = any(
                n == self.model or (n or "").startswith(f"{self.model}:") for n in names
            )
        except httpx.HTTPError as exc:
            info["error"] = str(exc)
            return info
        try:
            vec = (await self.embed(["ping"]))[0]
            info["dim"] = len(vec)
        except EmbeddingError as exc:
            info["embed_error"] = str(exc)
        return info
