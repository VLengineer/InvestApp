"""Временная диагностика №2: калибровка порога + проверка анизотропии пространства.
Запускается в контейнере backend-frontend, потом удаляется."""
import asyncio
import json

import httpx
import psycopg
from psycopg.rows import dict_row

BASE = "http://localhost:8000"
DSN = "host=pg17-local-tunnel.postgres_database_219703 port=5432 dbname=rag_db user=rag_user password=rag_password"
M = "hf.co/unsloth/Bm2TM-EmbeddingGemma2-768-GGUF:Q6_K_XL"


async def emb(client, texts):
    r = await client.post("/api/embeddings", json={"model": M, "prompt": ""})
    out = []
    for t in texts:
        rr = await client.post("/api/embed", json={"model": M, "input": t})
        rr.raise_for_status()
        j = rr.json()
        e = j["embeddings"][0] if j.get("embeddings") else []
        out.append(e or [0.0] * 768)
    return out


def cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return num / (na * nb) if na and nb else 0.0


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=300) as c:
        rows = []
        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            rows = conn.execute("select figi, company, embed_text, embedding::text e from company_profiles").fetchall()

        prof_vecs = {r["figi"]: json.loads(r["e"]) for r in rows}
        queries = {
            "null (мусор)": "search: null",
            "zzzz (мусор)": "search: zzzz",
            "зомби (мусор)": "search: зомби с марсом",
            "банк": "search: банк",
            "сеть кофеен": "search: сеть кофеен",
            "произв. микросхем": "search: производитель микро чипов",
            "добыча нефти": "search: добыча нефти",
        }
        qvecs = await emb(c, list(queries.values()))

        print("\n=== TOP-1 similarity по запросу (модель как есть) ===")
        for name, qv in zip(queries, qvecs):
            sims = sorted(((qv, prof_vecs[f["figi"]], f["company"]) for f in rows),
                          key=lambda x: -cos(x[0], x[1]))
            top = cos(sims[0][0], sims[0][1])
            top5 = [round(cos(a, b), 3) for a, b, _ in sims[:5]]
            print(f"  {name:22s} top1={top:.4f}  {sims[0][2]:28s} top5={top5}")

        # baseline: mean pairwise similarity ВСЕХ профилей между собой
        alls = list(prof_vecs.values())
        pair = [cos(a, b) for i, a in enumerate(alls) for b in alls[i + 1:]]
        print(f"\n=== Анизотропия: mean pairwise similarity профилей = {sum(pair)/len(pair):.4f}")
        print(f"    min={min(pair):.4f}  max={max(pair):.4f}")

        # центрирование (removing 'all-implicit-knowledge')
        mu = [sum(v[d] for v in alls) / len(alls) for d in range(768)]
        cen = {k: [x - m for x, m in zip(v, mu)] for k, v in prof_vecs.items()}
        print("\n=== После центрирования (top1, та же модель) ===")
        for name, qv in zip(queries, qvecs):
            qc = [x - m for x, m in zip(qv, mu)]
            sims = sorted(((qc, cen[f["figi"]], f["company"]) for f in rows),
                          key=lambda x: -cos(x[0], x[1]))
            print(f"  {name:22s} top1={cos(sims[0][0], sims[0][1]):+.4f}  {sims[0][2]:28s} "
                  f"top3={[round(cos(a, b), 3) for a, b, _ in sims[:3]]}")

        # per-field: поиск по Company / Description отдельно
        print("\n=== Per-field эмбеддинги (field-level similarity) ===")
        fields = ["Company", "Description", "Business Model", "Financial Model"]
        body = {"fields": fields, "texts": [rows[0]["company"], rows[0]["embed_text"], "x", "y"]}
        q_field = await emb(c, ["search: null"] * 4)
        for figi_sel, label in [("'774A160'", "Yandex")]:
            with psycopg.connect(DSN, row_factory=dict_row) as conn:
                fr = conn.execute(
                    f"select company, description, business_model, financial_model, "
                    f"embed_text from company_profiles where figi in ('774A160','692022203956','YKUAP') "
                    ).fetchall()
            for row_ in fr:
                vals = [row_.get(f) or "" for f in fields]
                fv = await emb(c, vals)
                s = [round(cos(q_field[0], x), 4) for x in fv]
                print(f"  {row_['company'][:26]:26s} " + "  ".join(f"{n}={v}" for n, v in zip(fields, s)))


asyncio.run(main())
