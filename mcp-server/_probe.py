"""Одноразовый зонд API: проверяет поведение mcp 1.30.0 и docker-py."""
import inspect
import json

import docker
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp import utilities as U


def show(title):
    print(f"\n===== {title} =====")


c = docker.from_env()

show("containers: compose labels + names + ports")
for ct in c.containers.list(all=True):
    lb = ct.labels or {}
    svc = lb.get("com.docker.compose.service")
    if svc or "mcp" in ct.name:
        print(svc, "|", ct.name, "|", ct.status, "|", json.dumps(ct.attrs.get("NetworkSettings", {}).get("Ports")))

show("images availability (source of list_services 404)")
try:
    print("images.list ok:", len(c.images.list(all=True)))
except Exception as e:
    print("images.list FAILED:", type(e).__name__, str(e)[:150])
try:
    print("image get python_test-ish:", c.images.get("python_test").short_id)
except Exception as e:
    print("images.get FAILED:", type(e).__name__, str(e)[:150])

show("exec_run demux=True -> tuple")
tgt = c.containers.get("python_test")
r = tgt.exec_run(["sh", "-c", "echo OUT; echo ERR 1>&2; exit 3"], demux=True)
print("exit_code", r.exit_code, "stdout", r.output[0], "stderr", r.output[1])
print("run signature:", inspect.signature(tgt.client.api.exec_start))

show("_convert_to_content (bytes/str/Image handling)")
src = inspect.getsource(U)
i = src.find("def _convert_to_content")
print(src[i : i + 1600] if i >= 0 else "NOT FOUND in utilities")

show("FastMCP API surface")
print("has add_resource_template:", hasattr(FastMCP, "add_resource_template"))
print("has list_resources:", hasattr(FastMCP, "list_resources"))
print("resource:", inspect.signature(FastMCP.resource))
print("prompt:", inspect.signature(FastMCP.prompt))
print("run:", inspect.signature(FastMCP.run))
print("tool:", inspect.signature(FastMCP.tool))
f = FastMCP("x")
print("settings keys of interest:", [k for k in f.settings.model_fields if any(s in k for s in ("path", "mount", "sse", "stateless", "host", "port", "auth", "log"))])

show("Context capabilities")
print([m for m in dir(Context) if not m.startswith("_")])
