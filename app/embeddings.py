"""Клиент Ollama для получения эмбеддингов (по подобию rag/embeddings.py).

Модель: hf.co/unsloth/embeddinggemma-2-GGUF:UD-Q6_K_XL, dim = 768.
"""
from __future__ import annotations

import logging
from typing import Sequence

import ollama

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self, model: str | None = None, base_url: str | None = None, dim: int | None = None):
        self.model = model or settings.embedding_model
        self.dim = dim or settings.embedding_dim
        self._client = ollama.Client(host=base_url or settings.ollama_base_url)

    def embed(self, text: str) -> list[float]:
        """Вернуть вектор размерности self.dim для одного текста."""
        resp = self._client.embeddings(model=self.model, prompt=text)
        vec: Sequence[float] = resp["embedding"] if isinstance(resp, dict) else resp.embedding
        return self._fit_dim(list(vec))

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def _fit_dim(self, vec: list[float]) -> list[float]:
        """Привести вектор к нужной размерности (модель может вернуть иную dim)."""
        if len(vec) == self.dim:
            return vec
        if len(vec) > self.dim:
            truncated = vec[: self.dim]
            norm = sum(x * x for x in truncated) ** 0.5 or 1.0
            return [x / norm for x in truncated]
        logger.warning("Embedding dim mismatch: got %d, expected %d; padding with zeros", len(vec), self.dim)
        return vec + [0.0] * (self.dim - len(vec))


embedding_client = EmbeddingClient()
