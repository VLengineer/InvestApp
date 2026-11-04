"""Зонд #4 (исправленный): рискованные гипотезы перед проектированием."""
import asyncio
import select
import shutil
import struct
import time

import docker

c = docker.from_env()

HDR = struct.Struct(">BI")
DATA, OOB = 1, 2


def exec_sh(container, cmd, timeout=15):
    """Multiplexed exec with deadline. Возвращает (exit_code, stdout, stderr)."""
    api = container.client.api
    ex = api.exec_create(container.id, ["sh", "-c", cmd], stdout=True, stderr=True, stdin=False)
    sock = api.exec_start(ex["Id"], socket=True, tty=False)
    raw = getattr(sock, "_sock", sock)
    out, err = bytearray(), bytearray()
    buf = bytearray()
    end = time.monotonic() + timeout

    def pump(chunk):
        buf.extend(chunk)
        while len(buf) >= HDR.size:
            stream, ln = HDR.unpack_from(buf, 0)
            if len(buf) < HDR.size + ln:
                return
            payload = bytes(buf[HDR.size : HDR.size + ln])
            del buf[: HDR.size + ln]
            if stream == DATA:
                out.extend(payload)
            elif stream == OOB:
                err.extend(payload)

    while time.monotonic() < end:
        r, _, _ = select.select([raw], [], [], max(0.001, end - time.monotonic()))
        if not r:
            break
        chunk = raw.recv(65536)
        if not chunk:
            break
        pump(chunk)
    if buf:
        print("  !! leftover undecoded bytes:", len(buf))
    info = api.exec_inspect(ex["Id"])
    try:
        sock.close()
    except Exception:
        pass
    return info["ExitCode"], out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


print("=== 1. multiplexed exec (python_test) ===")
tgt = c.containers.get("python_test")
code, o, e = exec_sh(tgt, "echo A; echo B 1>&2; echo C")
print("exit:", code, "| stdout:", repr(o), "| stderr:", repr(e))
print("WorkingDir:", repr(tgt.attrs["Config"].get("WorkingDir")))

print("\n=== 2. psql via exec inside postgres container ===")
pg = c.containers.get("postgres")
cmd = 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -c "select current_database(), version(), pg_is_in_recovery()"'
code, o, e = exec_sh(pg, cmd, timeout=25)
print("exit:", code, "| out:", repr(o[:300]), "| err:", repr(e[:200]))

print("\n=== 3. exec inside mcp-server itself (self-check via docker) ===")
me = c.containers.get("project_mcp")
code, o, e = exec_sh(me, "python -V; echo hi")
print("exit:", code, "| out:", repr(o))

print("\n=== 4. bins in mcp-server ===")
print({b: shutil.which(b) for b in ["pytest", "pip", "tar", "gzip", "git"]})
