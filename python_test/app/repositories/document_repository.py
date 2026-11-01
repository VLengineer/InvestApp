"""Repository-слой: единственный модуль, знающий SQL. Маппинг домен <-> строки БД."""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence
from uuid import UUID

import asyncpg

from app.core.exceptions import DatabaseError
from app.services.domain import Concept

logger = logging.getLogger(__name__)


def vector_literal(vector: Sequence[float]) -> str:
    """Формат pgvector: '[0.1,0.2,...]' (параметризованная передача, без интерполяции)."""
    return "[" + ",".join(f"{float(x):.8f}" for x in vector) + "]"


class DocumentRepository:
    def __init__(self, pool: asyncpg.Pool, *, model: str) -> None:
        self._pool = pool
        self._model = model

    # --------------------------- существующие hash'и -------------------------
    async def existing_hashes(self) -> dict[str, UUID]:
        rows = await self._pool.fetch("SELECT content_hash, document_id FROM kb_documents")
        return {str(r["content_hash"]).strip(): r["document_id"] for r in rows}

    async def embedded_document_ids(self) -> set[UUID]:
        rows = await self._pool.fetch(
            "SELECT DISTINCT document_id FROM kb_embeddings WHERE model = $1", self._model
        )
        return {r["document_id"] for r in rows}

    # ------------------------------ upsert пары -------------------------------
    async def save_with_embedding(
        self, concept: Concept, embedding: Sequence[float]
    ) -> tuple[UUID, bool]:
        """Атомарно пишет документ и вектор рядом с его uuid.

        Возвращает (document_id, created_new). Идемпотентно благодаря уникальному
        content_hash: повторный запуск не создаёт дублей и не ломает FK.
        """
        if len(embedding) != 768:  # проверка до отправки в БД
            raise DatabaseError(f"Некорректная размерность вектора: {len(embedding)}")

        logger.debug(
            "БД INSERT kb_documents (source=%s, concept_id=%s, hash=%s) + kb_embeddings (model=%s)",
            concept.source_path, concept.concept_id, concept.short_hash, self._model,
        )
        async with self._pool.acquire() as conn, conn.transaction():
            doc_row = await conn.fetchrow(
                """
                INSERT INTO kb_documents (source_path, concept_id, title, category, payload, content_hash)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                ON CONFLICT (content_hash) DO UPDATE
                    SET source_path = EXCLUDED.source_path,
                        concept_id  = EXCLUDED.concept_id,
                        title       = EXCLUDED.title,
                        category    = EXCLUDED.category,
                        payload     = EXCLUDED.payload,
                        indexed_at  = now()
                RETURNING document_id, (xmax = 0) AS inserted
                """,
                concept.source_path,
                concept.concept_id,
                concept.title,
                concept.category,
                json.dumps(concept.payload, ensure_ascii=False),
                concept.hash,
            )
            if doc_row is None:
                raise DatabaseError("Не удалось сохранить документ (пустой RETURNING)")

            document_id: UUID = doc_row["document_id"]
            created_new: bool = doc_row["inserted"]

            await conn.execute(
                """
                INSERT INTO kb_embeddings (document_id, chunk_index, model, embedding)
                VALUES ($1::uuid, 0, $2, $3::vector)
                ON CONFLICT (document_id, chunk_index, model) DO UPDATE
                    SET embedding = EXCLUDED.embedding,
                        created_at = now()
                """,
                str(document_id),
                self._model,
                vector_literal(embedding),
            )
        return document_id, created_new

    # -------------------------------- чтение ---------------------------------
    async def list_concepts(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT d.document_id, d.concept_id, d.title, d.category, d.source_path,
                   (e.embedding IS NOT NULL) AS has_embedding
            FROM kb_documents d
            LEFT JOIN kb_embeddings e ON e.document_id = d.document_id AND e.model = $2
            ORDER BY d.indexed_at DESC
            LIMIT $1
            """,
            limit,
            self._model,
        )
        return [dict(r) for r in rows]

    async def search_by_vector(self, query_vec: Sequence[float], top_k: int, min_similarity: float) -> list[dict]:
        """KNN по косинусному расстоянию (cosine_distance = 1 - similarity)."""
        literal = vector_literal(query_vec)
        rows = await self._pool.fetch(
            """
            SELECT d.document_id, d.concept_id, d.title, d.category, d.source_path, d.payload,
                   1 - (e.embedding <=> $1::vector) AS similarity
            FROM kb_embeddings e
            JOIN kb_documents d ON d.document_id = e.document_id
            WHERE e.model = $2
              AND 1 - (e.embedding <=> $1::vector) >= $3
            ORDER BY e.embedding <=> $1::vector
            LIMIT $4
            """,
            literal,
            self._model,
            float(min_similarity),
            int(top_k),
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if isinstance(item.get("payload"), str):
                item["payload"] = json.loads(item["payload"])
            out.append(item)
        return out

    async def stats(self) -> dict[str, Any]:
        row = await self._pool.fetchrow(
            """
            SELECT (SELECT count(*) FROM kb_documents)   AS documents,
                   (SELECT count(*) FROM kb_embeddings WHERE model = $1) AS embeddings,
                   (SELECT count(*) FROM pg_indexes WHERE tablename IN ('kb_documents','kb_embeddings')) AS indexes
            """,
            self._model,
        )
        return dict(row or {})
