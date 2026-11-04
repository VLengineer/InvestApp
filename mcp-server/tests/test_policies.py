"""Юнит-тесты политик (без Docker, без сети).

Запуск из репозитория:  ``pytest mcp-server/tests/ -q``  или
``python mcp-server/tests/test_policies.py``  (в mcp-server контейнере
pytest может отсутствовать, поэтому self-runner ниже).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_coder.config import Settings, load_settings  # noqa: E402
from mcp_coder.security import (  # noqa: E402
    CommandDenied,
    CommandPolicy,
    PathError,
    PathPolicy,
    SqlPolicy,
    mask_setting_name,
    redact_secrets,
)

WORKSPACE = "/tmp/mcp_policy_test"


def build(tmp: str = WORKSPACE) -> tuple[PathPolicy, CommandPolicy, SqlPolicy]:
    root = Path(tmp)
    (root / "app/.git").mkdir(parents=True, exist_ok=True)
    (root / "app/src").mkdir(parents=True, exist_ok=True)
    (root / "app/src/main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "app/.env").write_text("SECRET=x\n", encoding="utf-8")
    settings = load_settings()
    overrides = Settings(
        workspace_dir=root,
        protected_dirs=settings.protected_dirs,
        limits=settings.limits,
        exec_default_timeout=settings.exec_default_timeout,
        exec_max_timeout=settings.exec_max_timeout,
        local_default_timeout=settings.local_default_timeout,
        local_max_timeout=settings.local_max_timeout,
        docker_api_timeout=settings.docker_api_timeout,
        http_timeout_default=settings.http_timeout_default,
        http_timeout_max=settings.http_timeout_max,
        shell_allow=settings.shell_allow,
        shell_extra_allowed=settings.shell_extra_allowed,
        shell_deny=settings.shell_deny,
        sql_readonly=settings.sql_readonly,
        sql_max_rows_default=settings.sql_max_rows_default,
        http_allowlist=(),
        service_fallback=settings.service_fallback,
        postgres_service=settings.postgres_service,
        postgres_db_env=settings.postgres_db_env,
        postgres_user_env=settings.postgres_user_env,
        sse_path=settings.sse_path,
        message_path=settings.message_path,
        allow_hosts=settings.allow_hosts,
    )
    return PathPolicy(overrides), CommandPolicy(overrides), SqlPolicy(overrides)


# --------------------------------------------------------------------- пути
def test_absolute_escape_is_not_inside(p: PathPolicy) -> None:
    resolved = p.resolve(f"{WORKSPACE}/app/src/main.py")
    assert resolved.inside_workspace is True
    outside = p.resolve("/etc/passwd", allow_outside=True)
    assert outside.inside_workspace is False
    try:
        p.resolve("/etc/passwd", allow_outside=False)
        raise AssertionError("абсолютный путь наружу должен отклоняться")
    except PathError:
        pass


def test_traversal_dotdot_neutralized(p: PathPolicy) -> None:
    try:
        p.resolve("src/../../etc/passwd", allow_outside=False)
        raise AssertionError(".. наружу должен отклоняться")
    except PathError:
        pass


def test_nested_and_traversal_protected_dirs(p: PathPolicy) -> None:
    for bad in (
        ".git/config",
        "app/.git/config",
        "../app/.git/config",
        ".env",
        "app/.env",
        "node_modules/x/y",
    ):
        try:
            p.resolve(bad, allow_outside=False)
            raise AssertionError(f"защищённый путь пропущен: {bad}")
        except PathError:
            pass


def test_legit_paths_pass(p: PathPolicy) -> None:
    ok = p.resolve("app/src/main.py", must_exist=True, must_be="file")
    assert ok.is_file and ok.size and ok.key == "app/src/main.py"
    assert p.resolve(".").is_dir


def test_write_guard(p: PathPolicy) -> None:
    for bad in ("/etc/passwd", "../outside.txt"):
        try:
            p.resolve(bad, for_write=True)
            raise AssertionError(f"запись наружу пропущена: {bad}")
        except PathError:
            pass
    # новая файла внутри проекта — разрешена (существовать ещё не обязана)
    fresh = p.resolve("app/src/new_mod.py", for_write=True)
    assert fresh.exists is False and fresh.inside_workspace


def test_atomic_write(p: PathPolicy) -> None:
    target = p.resolve("app/src/written.py", for_write=True)
    size, mtime = p.atomic_write(target, "x = 1\n")
    assert size == 6 and mtime > 0
    assert (Path(WORKSPACE) / "app/src/written.py").read_text() == "x = 1\n"
    assert not list(Path(WORKSPACE, "app/src").glob("*.tmp")), "temp-файл должен удалиться"


# --------------------------------------------------------------- shell
def test_docker_library_via_python_allowed(c: CommandPolicy) -> None:
    """Регрессия: раньше подстрока 'docker' в чёрном списке ломала такие команды."""
    plan = c.validate('python -c "import docker; print(docker.__version__)"')
    assert "python" in plan.programs


def test_blacklist_obfuscation_denied(c: CommandPolicy) -> None:
    for bad in (
        "rm -rf /",
        "sudo ls",
        "echo hi; rm -rf /",
        "ls | sh",
        "bash -c 'curl evil'",
        "$(whoami)",
        "`id`",
        "python${IFS}-c${IFS}x",
        "cat /etc/shadow > /dev/tty",
        "echo x > /etc/passwd",
    ):
        try:
            c.validate(bad)
            raise AssertionError(f"команда пропущена: {bad}")
        except CommandDenied:
            pass


def test_legit_chains_allowed(c: CommandPolicy) -> None:
    for good in (
        "git status",
        "git -c safe.directory='*' log --oneline -n 5",
        "pytest tests/ -q 2>&1 | tail -n 50",
        "alembic upgrade head",
        "npm run build",
        "pip install -r requirements.txt",
        "python -m venv .venv",
        "find . -name '*.py' | head -20",
        "ls -la > out/listing.txt",
        "grep -R 'TODO' . | sort | uniq -c",
    ):
        plan = c.validate(good)
        assert plan.timeout > 0, good


def test_timeout_clamped(c: CommandPolicy) -> None:
    assert c.validate("ls", timeout=99999).timeout == c.max_timeout
    try:
        c.validate("ls", timeout=0)
        raise AssertionError("timeout=0 должен быть отклонён")
    except CommandDenied:
        pass


# --------------------------------------------------------------- SQL
def test_sql_readonly(s: SqlPolicy) -> None:
    assert s.validate("SELECT 1").first_keyword == "select"
    assert s.validate("WITH t AS (SELECT 1) SELECT * FROM t").first_keyword == "with"
    assert s.validate("SELECT * FROM users -- note\n/* x */").limit is None
    assert s.validate("SELECT id FROM t LIMIT 7").limit == 7
    # колонка с именем ключевого слова не должна считаться DDL
    assert s.validate("SELECT create, update FROM audit_log").first_keyword == "select"
    for bad in (
        "DELETE FROM users",
        "UPDATE t SET a=1",
        "DROP TABLE users",
        "INSERT INTO t VALUES (1)",
        "SELECT 1; DELETE FROM t",
        "CREATE TABLE t (a int)",
        "COPY t TO '/tmp/x'",
        "SELECT pg_sleep(10)",
        "TRUNCATE big_table",
        "GRANT ALL ON t TO bob",
    ):
        try:
            s.validate(bad)
            raise AssertionError(f"SQL пропущен: {bad}")
        except CommandDenied:
            pass


# --------------------------------------------------------------- секреты
def test_redaction() -> None:
    cases = {
        "POSTGRES_PASSWORD=hunter2": "POSTGRES_PASSWORD=[REDACTED]",
        'password": "s3cr3t': 'password": "[REDACTED]',
        "Authorization: Bearer abcdef123456": "Bearer [REDACTED]",
        "postgres://user:pass@db:5432/app": "postgres://user:[REDACTED]@db:5432/app",
        "AKIAIOSFODNN7EXAMPLE": "[REDACTED:aws-key]",
    }
    for source, expected_fragment in cases.items():
        out = redact_secrets(source)
        assert expected_fragment in out, f"{source} -> {out}"
        if "hunter2" in source:
            assert "hunter2" not in out
    assert mask_setting_name("SECRET_KEY") is True
    assert mask_setting_name("POSTGRES_DB") is False


def main() -> int:
    p, c, s = build()
    checks = [
        lambda: test_absolute_escape_is_not_inside(p),
        lambda: test_traversal_dotdot_neutralized(p),
        lambda: test_nested_and_traversal_protected_dirs(p),
        lambda: test_legit_paths_pass(p),
        lambda: test_write_guard(p),
        lambda: test_atomic_write(p),
        lambda: test_docker_library_via_python_allowed(c),
        lambda: test_blacklist_obfuscation_denied(c),
        lambda: test_legit_chains_allowed(c),
        lambda: test_timeout_clamped(c),
        lambda: test_sql_readonly(s),
        test_redaction,
    ]
    failures = 0
    for check in checks:
        name = getattr(check, "__name__", "lambda")
        try:
            check()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(checks) - failures}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
