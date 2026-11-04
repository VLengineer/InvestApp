"""Временная диагностика: почему запрос 'null' даёт similarity ~0.65.

Запускается внутри контейнера python_test:  python _tmp_diag_search.py
"""
from __future__ import annotations

import asyncio
import json
import math
import os

import httpx
import asyncpg

MODEL = os.environ["EMBEDDING_MODEL"]
OLLAMA = os.environ["OLLAMA_BASE_URL"].rstrip("/")
DSN = (
    "postgresql://admin:sip4308@postgres:5432/vectordb"
)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


async def embed(client: httpx.AsyncClient, text: str) -> list[float]:
    r = await client.post(
        "/api/embed",
        json={"model": MODEL, "input": text, "keep_alive": "5m"},
    )
    r.raise_for_status()
    d = r.json()
    return d["embeddings"][0] if "embeddings" in d else d["embedding"]


async def main() -> None:
    queries = {
        "null": "null",
        "'search: null'": "search: null",
        "empty": "",
        "банан": "search: банан",
        "zzzzz": "search: zzzzz",
    }
    async with httpx.AsyncClient(base_url=OLLAMA + "/", timeout=120.0) as c:
        vecs = {k: await embed(c, v) for k, v in queries.items()}

    print("=== векторы запросов ===")
    for k, v in vecs.items():
        print(f"{k:16s} dim={len(v):4d} ||v||={norm(v):.4f} "
              f"mean={sum(v)/len(v):+.5f} min={min(v):+.4f} max={max(v):+.4f}")

    print("\n=== попарный косинус между векторами запросов ===")
    keys = list(vecs)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            print(f"cos({a}, {b}) = {cosine(vecs[a], vecs[b]):+.6f}")

    conn = await asyncpg.connect(DSN)
    print("\n=== состояние БД ===")
    try:
        n = await conn.fetchval("SELECT count(*) FROM company_profiles")
        print("rows in company_profiles:", n)
        row = await conn.fetchrow(
            "SELECT count(*) AS with_emb, max(embedding_model) AS m, max(embedding_dim) AS d "
            "FROM company_profiles WHERE embedding IS NOT NULL"
        )
        print("with embedding:", dict(row))
    except Exception as exc:  # noqa: BLE001
        print("company_profiles недоступна:", exc)
        await conn.close()
        return

    if n:
        rows = await conn.fetch(
            "SELECT figi, company_name, embedding::text AS e, length(embed_text) AS tlen "
            "FROM company_profiles WHERE embedding IS NOT NULL LIMIT 5"
        )
        print("\n=== сравнение с первыми 5 строками БД ===")
        for r in rows:
            db_vec = json.loads(r["e"])
            print(f"\n{r['company_name']} ({r['figi']}) embed_text_len={r['tlen']} db_dim={len(db_vec)}")
            for k in vecs:
                print(f"   cos('{k}', row) = {cosine(vecs[k], db_vec):+.6f}  "
                      f"similarity(1-dist)={1 - cosine(vecs[k], db_vec):.6f}")

        # как выглядит "корректный" запрос к той же строке
        target = rows[0]
        tb = json.loads(target["e"])
        print("\n=== sanity: косинус к себе ===")
        print(f"cos(row0, row0) = {cosine(tb, tb):+.6f}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
