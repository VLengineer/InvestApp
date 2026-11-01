"""Слой работы с PostgreSQL + pgvector (psycopg3, пул соединений).

Две таблицы (см. init_db/01_init_rag.sql):
  * kb_documents  — сами документы (payload jsonb, uuid document_id);
  * kb_embeddings — вектор эмбеддинга + uuid документа (document_id).

Индексация идемпотентна: дубликаты по content_hash не создают новых строк,
эмбеддинги вставляются через ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.services.loader import Concept

log = logging.getLogger("python_test.storage")

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS kb_documents (
    document_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_path   text        NOT NULL,
    concept_id    text        NOT NULL,
    title         text,
    category      text,
    payload       jsonb       NOT NULL,
    content_hash  char(64)    NOT NULL,
    indexed_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_documents_content_hash ON kb_documents (content_hash);
CREATE INDEX IF NOT EXISTS ix_kb_documents_concept_id ON kb_documents (concept_id);
CREATE INDEX IF NOT EXISTS ix_kb_documents_source_path ON kb_documents (source_path);

CREATE TABLE IF NOT EXISTS kb_embeddings (
    embedding_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id   uuid NOT NULL REFERENCES kb_documents (document_id) ON DELETE CASCADE,
    chunk_index   int  NOT NULL DEFAULT 0,
    model         text NOT NULL,
    embedding     vector(768) NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index, model)
);
CREATE INDEX IF NOT EXISTS ix_kb_embeddings_vector_hnsw
    ON kb_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_kb_embeddings_document_id ON kb_embeddings (document_id);
"""


def _vec_literal(vec: Sequence[float]) -> str:
    """Сериализация вектора в формат pgvector ('[a,b,c]')."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class RagStorage:
    def __init__(self, conninfo: str, min_size: int = 1, max_size: int = 5) -> None:
        self._pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": False},
            check=AsyncConnectionPool.check_connection,
            max_idle=300,
        )

    async def open(self, timeout: float = 30) -> None:
        # wait=True синхронизируется с event loop и ждёт реального соединения
        # (пул может стартовать раньше postgres)
        await self._pool.open(wait=True, timeout=timeout)

    async def close(self) -> None:
        await self._pool.close(timeout=5)

    async def ensure_schema(self, embedding_dim: int | None = None) -> None:
        """Создаёт таблицы, если их нет (прод-схема всё же в init_db/01_init_rag.sql)."""
        script = SCHEMA_SQL
        if embedding_dim and embedding_dim != 768:
            script = script.replace("vector(768)", f"vector({embedding_dim})")
        async with self._pool.connection() as conn:
            await conn.execute(script)
            await conn.commit()

    async def check_embedding_dim(self, expected_dim: int) -> int | None:
        """Возвращает размерность колонки kb_embeddings.embedding (или None, если таблицы нет)."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT a.atttypmod AS typmod
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'kb_embeddings'
                  AND a.attname = 'embedding' AND a.attnum > 0 AND NOT a.attisdropped
                """
            )
            row = await cur.fetchone()
        if not row:
            return None
        typmod = row["typmod"]
        dim = typmod - 4 if isinstance(typmod, int) and typmod > 4 else None
        if dim is not None and expected_dim and dim != expected_dim:
            raise RuntimeError(
                f"Колонка kb_embeddings.embedding имеет размерность {dim}, "
                f"а модель даёт {expected_dim}. Измените EMBEDDING_DIM или пересоздайте таблицу."
            )
        return dim

    async def upsert_documents(self, concepts: Iterable[Concept]) -> dict[str, list[str]]:
        """Вставляет документы, возвращая map content_hash -> document_id (uuid строкой).

        Дубликаты (по уникальному content_hash) не вставляются повторно, но их uuid
        возвращается, чтобы эмбеддинг мог быть дописан к существующей строке.
        """
        concepts = list(concepts)
        if not concepts:
            return {}
        result: dict[str, str] = {}
        batch_size = 200
        insert_sql = """
            INSERT INTO kb_documents
                (source_path, concept_id, title, category, payload, content_hash)
            VALUES (%s::text, %s::text, %s::text, %s::text, %s::jsonb, %s::char(64))
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING content_hash, document_id::text
        """
        async with self._pool.connection() as conn:
            try:
                for i in range(0, len(concepts), batch_size):
                    chunk = concepts[i : i + batch_size]
                    values = [
                        (c.source_path, c.concept_id, c.title, c.category,
                         psycopg.types.json.Jsonb(c.payload), c.content_hash)
                        for c in chunk
                    ]
                    async with conn.cursor() as cur:
                        await cur.executemany(insert_sql, values)
                        async for ch, doc_id in cur:  # только реально вставленные строки
                            result[ch] = doc_id
                    log.info(
                        "Документы: обработано %d/%d (новых: %d)",
                        min(i + batch_size, len(concepts)), len(concepts), len(result),
                    )
                # uuid уже существующих документов (дублей по content_hash) — одним запросом
                pending_hashes = sorted({c.content_hash for c in concepts if c.content_hash not in result})
                for i in range(0, len(pending_hashes), 500):
                    part = pending_hashes[i : i + 500]
                    cur = await conn.execute(
                        "SELECT content_hash, document_id::text FROM kb_documents "
                        "WHERE content_hash = ANY(%s)",
                        (part,),
                    )
                    async for row in cur:
                        result[row["content_hash"]] = row["document_id"]
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        return result

    async def save_embeddings(
        self,
        rows: Sequence[tuple[str, str, int]],  # (document_id, vector_literal, chunk_index)
        model: str,
    ) -> int:
        """Сохраняет векторы во вторую таблицу. Возвращает количество вставленных строк."""
        if not rows:
            return 0
        inserted = 0
        insert_sql = """
            INSERT INTO kb_embeddings (document_id, chunk_index, model, embedding)
            VALUES (%s::uuid, %s, %s, %s::vector)
            ON CONFLICT (document_id, chunk_index, model) DO NOTHING
            RETURNING embedding_id
        """
        async with self._pool.connection() as conn:
            try:
                for i in range(0, len(rows), 200):
                    chunk = rows[i : i + 200]
                    async with conn.cursor() as cur:
                        await cur.executemany(insert_sql, chunk)
                        async for _ in cur:
                            inserted += 1
                    log.info("Эмбеддинги: обработано %d/%d", min(i + 200, len(rows)), len(rows))
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        return inserted

    async def search(
        self, query_vec: Sequence[float], limit: int = 5, min_similarity: float | None = None
    ) -> list[dict[str, Any]]:
        """Косинусный семантический поиск по двум таблицам (JOIN через представление)."""
        vec = _vec_literal(query_vec)
        base = """
            SELECT d.document_id::text AS document_id, d.source_path, d.concept_id,
                   d.title, d.category, d.payload, e.model,
                   1 - (e.embedding <=> %s::vector) AS similarity
            FROM kb_documents d
            JOIN kb_embeddings e ON e.document_id = d.document_id
        """
        params: list[Any] = [vec]
        if min_similarity is not None:
            base += " WHERE 1 - (e.embedding <=> %s::vector) >= %s"
            params.extend([vec, float(min_similarity)])
        base += " ORDER BY e.embedding <=> %s::vector LIMIT %s"
        params.extend([vec, int(limit)])
        async with self._pool.connection() as conn:
            cur = await conn.execute(base, tuple(params))
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def stats(self) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT
                  (SELECT count(*) FROM kb_documents)      AS documents,
                  (SELECT count(*) FROM kb_embeddings)     AS embeddings,
                  (SELECT count(DISTINCT source_path) FROM kb_documents) AS files,
                  (SELECT max(indexed_at) FROM kb_documents) AS last_indexed_at
                """
            )
            row = await cur.fetchone()
        out = dict(row or {})
        if out.get("last_indexed_at") is not None:
            out["last_indexed_at"] = out["last_indexed_at"].isoformat()
        return out

    async def indexed_hashes(self, model: str) -> set[str]:
        """content_hash документов, у которых уже есть эмбеддинг указанной модели."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT d.content_hash AS h
                FROM kb_documents d
                JOIN kb_embeddings e ON e.document_id = d.document_id AND e.model = %s
                """,
                (model,),
            )
            return {row["h"] async for row in cur}

    async def truncate_all(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("TRUNCATE kb_documents CASCADE")
            await conn.commit()
