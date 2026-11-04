"""Зонд #5: psql-через-exec (demux), structured output, таймаут висящего exec."""
import asyncio
import json

import docker
from mcp.server.fastmcp import FastMCP

c = docker.from_env()
pg = c.containers.get("postgres")

print("=== psql via exec_run(demux=True) ===")
r = pg.exec_run(
    ["sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -c "select current_database(), current_user, count(*) from pg_catalog.pg_tables"'],
    demux=True,
)
print("exit:", r.exit_code, "stdout:", r.output[0], "stderr:", r.output[1])

r2 = pg.exec_run(
    ["sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select table_schema, table_name from information_schema.tables where table_schema not in (\'pg_catalog\',\'information_schema\') order by 1,2 limit 40"'],
    demux=True,
)
print("app tables exit:", r2.exit_code)
print((r2.output[0] or b"").decode("utf-8", "replace")[:800])

print("\n=== hanging exec + wait_for(to_thread) ===")
tgt = c.containers.get("python_test")


async def main():
    loop_ex = tgt.client.api.exec_create(tgt.id, ["sh", "-c", "sleep 30"], stdout=True, stderr=True)
    try:
        await asyncio.wait_for(asyncio.to_thread(tgt.client.api.exec_start, loop_ex["Id"], socket=False, demux=True), timeout=2)
        print("!! completed unexpectedly")
    except asyncio.TimeoutError:
        print("TIMEOUT OK — wait_for returned control in ~2s")
    print("still alive, event loop responsive")


asyncio.run(main())

print("\n=== dict -> structuredContent ===")
app = FastMCP("p5")


@app.tool()
async def t() -> dict:
    return {"exit_code": 0, "rows": [{"a": 1}]}


res = asyncio.run(app.call_tool("t", {}))
print("call_tool:", res)
tools = asyncio.run(app.list_tools())
print("outputSchema:", json.dumps(tools[0].outputSchema, ensure_ascii=False)[:220])

print("\n=== pydantic BaseModel return ===")
from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    path: str
    line: int = Field(description="1-based")


@app.tool()
async def s() -> list[SearchHit]:
    return [SearchHit(path="a.py", line=3)]


print(asyncio.run(app.call_tool("s", {})))
print("list schema:", json.dumps((await_tools := asyncio.run(app.list_tools()))[1].outputSchema, ensure_ascii=False)[:220])
