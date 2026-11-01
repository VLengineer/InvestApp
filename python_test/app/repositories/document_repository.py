"""Repository-слой: единственный модуль, знающий SQL. Маппинг домен <-> строки БД."""

from __future__ import annotations

import json
import logging
import time
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

    # --------------------------- логирование обращений к БД ------------------
    @staticmethod
    def _log_sql_ok(op: str, started: float, detail: str = "") -> None:
        logger.info(
            "PostgreSQL <<< %s OK за %.3fs%s", op, time.perf_counter() - started,
            f": {detail}" if detail else "",
        )

    @staticmethod
    def _log_sql_error(op: str, started: float, exc: Exception) -> None:
        logger.error(
            "PostgreSQL <<< %s ОШИБКА за %.3fs (%s): %s — проверьте доступность контейнера postgres",
            op, time.perf_counter() - started, exc.__class__.__name__, exc,
        )

    # --------------------------- существующие hash'и -------------------------
    async def existing_hashes(self) -> dict[str, UUID]:
        logger.info("PostgreSQL >>> SELECT content_hash, document_id FROM kb_documents…")
        started = time.perf_counter()
        try:
            rows = await self._pool.fetch("SELECT content_hash, document_id FROM kb_documents")
        except Exception as exc:  # noqa: BLE001
            self._log_sql_error("SELECT kb_documents (existing_hashes)", started, exc)
            raise
        self._log_sql_ok("SELECT kb_documents (existing_hashes)", started, f"строк={len(rows)}")
        return {str(r["content_hash"]).strip(): r["document_id"] for r in rows}

    async def embedded_document_ids(self) -> set[UUID]:
        logger.info(
            "PostgreSQL >>> SELECT DISTINCT document_id FROM kb_embeddings WHERE model='%s'…", self._model
        )
        started = time.perf_counter()
        try:
            rows = await self._pool.fetch(
                "SELECT DISTINCT document_id FROM kb_embeddings WHERE model = $1", self._model
            )
        except Exception as exc:  # noqa: BLE001
            self._log_sql_error("SELECT kb_embeddings (embedded_document_ids)", started, exc)
            raise
        self._log_sql_ok("SELECT kb_embeddings (embedded_document_ids)", started, f"строк={len(rows)}")
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

        logger.info(
            "PostgreSQL >>> транзакция: UPSERT kb_documents (source=%s, concept_id=%s, hash=%s, "
            "вектор %d измерений) + kb_embeddings (model=%s)…",
            concept.source_path, concept.concept_id, concept.short_hash, len(embedding), self._model,
        )
        started = time.perf_counter()
        try:
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
        except Exception as exc:  # noqa: BLE001
            self._log_sql_error(f"UPSERT документа '{concept.concept_id}'", started, exc)
            raise
        self._log_sql_ok(
            f"UPSERT документа '{concept.concept_id}'", started,
            f"document_id={document_id}, новый={created_new}",
        )
        return document_id, created_new

    # -------------------------------- чтение ---------------------------------
    async def list_concepts(self, limit: int = 100) -> list[dict[str, Any]]:
        logger.info("PostgreSQL >>> SELECT список концептов (limit=%d)…", limit)
        started = time.perf_counter()
        try:
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
        except Exception as exc:  # noqa: BLE001
            self._log_sql_error("SELECT список концептов (list_concepts)", started, exc)
            raise
        self._log_sql_ok("SELECT список концептов (list_concepts)", started, f"строк={len(rows)}")
        return [dict(r) for r in rows]

    async def search_by_vector(self, query_vec: Sequence[float], top_k: int, min_similarity: float) -> list[dict]:
        """KNN по косинусному расстоянию (cosine_distance = 1 - similarity)."""
        literal = vector_literal(query_vec)
        logger.info(
            "PostgreSQL >>> KNN-поиск по вектору (%d измерений), top_k=%d, min_similarity=%.3f…",
            len(query_vec), top_k, min_similarity,
        )
        started = time.perf_counter()
        try:
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
        except Exception as exc:  # noqa: BLE001
            self._log_sql_error("KNN-поиск (search_by_vector)", started, exc)
            raise
        self._log_sql_ok("KNN-поиск (search_by_vector)", started, f"совпадений={len(rows)}")
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if isinstance(item.get("payload"), str):
                item["payload"] = json.loads(item["payload"])
            out.append(item)
        return out

    async def stats(self) -> dict[str, Any]:
        logger.info("PostgreSQL >>> SELECT статистика индекса (documents/embeddings/indexes)…")
        started = time.perf_counter()
        try:
            row = await self._pool.fetchrow(
                """
                SELECT (SELECT count(*) FROM kb_documents)   AS documents,
                       (SELECT count(*) FROM kb_embeddings WHERE model = $1) AS embeddings,
                       (SELECT count(*) FROM pg_indexes WHERE tablename IN ('kb_documents','kb_embeddings')) AS indexes
                """,
                self._model,
            )
        except Exception as exc:  # noqa: BLE001
            self._log_sql_error("SELECT статистика (stats)", started, exc)
            raise
        self._log_sql_ok("SELECT статистика (stats)", started, f"результат={dict(row or {})}")
        return dict(row or {})
