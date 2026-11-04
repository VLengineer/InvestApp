"""Зонд #3: тред-пул для sync-инструментов, templates, конвертация результатов."""
import inspect
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata as FM

print("=== call_fn_with_arg_validation: sync offload? ===")
print(inspect.getsource(FM.call_fn_with_arg_validation))
print("\n=== convert_result ===")
print(inspect.getsource(FM.convert_result))

app = FastMCP("p3")

@app.resource("proj://{name}")
async def _t(name: str) -> str:
    return f"v-{name}"

print("\n=== template listing ===")
print("has list_resource_templates:", hasattr(app, "list_resource_templates"))
import asyncio
async def main():
    print("resources:", await app.list_resources())
    if hasattr(app, "list_resource_templates"):
        print("templates:", await app.list_resource_templates())
    print("read:", await app.read_resource("proj://abc"))
asyncio.run(main())
