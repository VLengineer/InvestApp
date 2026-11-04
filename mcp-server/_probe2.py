"""Зонд #2: семантика FastMCP, влияющая на дизайн сервера."""
import inspect
import json

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations

app = FastMCP("probe")

print("=== ToolAnnotations fields ===")
print(list(ToolAnnotations.model_fields.keys()))

print("\n=== resources module ===")
import mcp.server.fastmcp.resources as R
print([n for n in dir(R) if not n.startswith("__")])

print("\n=== does resource() support {param} templates? ===")
try:
    @app.resource("thing://{name}")
    async def _t(name: str) -> str:
        return name
    print("registered ok")
    import asyncio
    print(asyncio.get_event_loop_policy().new_event_loop().run_until_complete(app.list_resources())[:5] if True else "")
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:300])

print("\n=== call_tool error semantics (raise vs return) ===")
src = inspect.getsource(FastMCP.call_tool)
print(src[:1400])

print("\n=== sync tool -> threadpool? ===")
print(inspect.getsource(Tool.run)[:1200])
