"""Юнит-тесты чистого слоя форматирования (без I/O)."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_coder.formatting import (  # noqa: E402
    Edit,
    PatchError,
    apply_edits,
    build_slice,
    cap_bytes,
    clamp,
    decode,
    diff_stats,
    format_grep_hit,
    human_bytes,
    join_kv,
    match_line_numbers,
    number_lines,
    paginate_note,
    render_table,
    split_lines,
    truncate_out,
    unified_diff,
)

FAILED = []


def check(name: str, cond: bool) -> None:
    if cond:
        print(f"ok   {name}")
    else:
        FAILED.append(name)
        print(f"FAIL {name}")


def expect_error(name: str, fn, exc) -> None:
    try:
        fn()
    except exc:
        check(name, True)
    except Exception as err:  # noqa: BLE001
        FAILED.append(name)
        print(f"FAIL {name}: wrong type {type(err).__name__}: {err}")
    else:
        FAILED.append(name)
        print(f"FAIL {name}: no error raised")


# --- clamp / truncate / decode / cap_bytes ---------------------------------
check("clamp no-op", clamp("hello", 100) == ("hello", 0))
check("clamp head", clamp("abcdefgh", 3) == ("abc", 5))
check("clamp tail", clamp("abcdefgh", 3, tail=True) == ("fgh", 5))
check("clamp zero budget passthrough", clamp("abc", 0) == ("abc", 0))
check("truncate marks", "truncated 2 chars" in truncate_out("abcdef", 4))
check("decode None", decode(None) == "")
check("decode bytes", decode(b"caf\xc3\xa9") == "café")
check("decode bad bytes lossy", len(decode(b"\xff\xfe")) == 2)
check("cap_bytes under", cap_bytes(["a", "b"], 100) == ("a\nb", False))
check("cap_bytes over", cap_bytes(["x" * 50], 20)[1] is True)
check("human_bytes", human_bytes(1500) == "1.5KiB" and human_bytes(None) == "?")

# --- split / number --------------------------------------------------------
check("split empty file", split_lines("") == [])
check("split one blank line", split_lines("\n") == ["", ""])
check("number padding", number_lines(["a", "bb"], 1).startswith("   1 | a"))
check("number strips CR", "\r" not in number_lines(["a\r\n"], 1))
check("number empty", number_lines([], 5) == "")

# --- build_slice -----------------------------------------------------------
src = "\n".join(f"line {i}" for i in range(1, 201))

full = build_slice(src, max_lines=500, max_chars=100_000)
check("slice whole file", full.first_line == 1 and full.last_line == 200)
check("slice header", "lines 1-200 of 200" in full.header)
check("slice no drop", full.dropped_tail_lines == 0)

part = build_slice(src, start_line=10, end_line=20, max_lines=500, max_chars=100_000)
check("slice range", part.first_line == 10 and part.last_line == 20)
check("slice range starts at 10", part.text.splitlines()[0] == "  10 | line 10")

clipped = build_slice(src, max_lines=15, max_chars=100_000)
check("slice max_lines", clipped.last_line == 15)
check("slice line cap noted", clipped.truncated_by_lines is True)
check("slice line header PARTIAL", "PARTIAL" in clipped.header)
check("slice line drop count", clipped.dropped_tail_lines == 185)

byte_cap = build_slice(src, start_line=1, end_line=50, max_lines=500, max_chars=200)
check("slice byte cap keeps head", byte_cap.text.startswith("   1 | line 1"))
check("slice byte cap flag", byte_cap.truncated_by_bytes is True)
check("slice byte cap last_line", byte_cap.last_line == 1 + byte_cap.text.count("\n"))
shown = byte_cap.text.count("\n") + 1
check("slice byte cap drop = total-shown", byte_cap.dropped_tail_lines == 200 - shown)
check("slice header hints next page", f"start_line={byte_cap.last_line + 1}" in byte_cap.header)
check("slice header PARTIAL on byte cap", "PARTIAL" in byte_cap.header)

empty = build_slice("", max_lines=10, max_chars=100)
check("slice empty file", empty.total_lines == 0 and empty.header == "empty file")

past_end = build_slice(src, start_line=500, max_lines=10, max_chars=1000)
check("slice start past EOF clamps", past_end.first_line == 200)

check("slice start<=0 means 1", build_slice(src, start_line=0, max_lines=3, max_chars=1000).first_line == 1)

# --- diff ------------------------------------------------------------------
d = unified_diff("a\nb\nc\n", "a\nB\nc\n", "pkg/mod.py")
check("diff paths", "a/pkg/mod.py" in d and "b/pkg/mod.py" in d)
check("diff content", "-b" in d and "+B" in d)
check("diff identical empty", unified_diff("same\n", "same\n", "x.py") == "")

big_old = "\n".join(f"l{i}" for i in range(200)) + "\n"
big_new = "\n".join(f"x{i}" if i % 60 == 0 else f"l{i}" for i in range(200)) + "\n"
check("diff hunk cap", "diff truncated after" in unified_diff(big_old, big_new, "f", max_hunks=2))
check("diff stats", diff_stats("a\nb\nc\n", "a\nx\nc\nd\n") == (2, 1))
check("diff stats identity", diff_stats("a\n", "a\n") == (0, 0))

# --- apply_edits -----------------------------------------------------------
base = "alpha\nbeta\ngamma\n"

one = apply_edits(base, [Edit("beta", "BETA")])
check("edit single", one.text == "alpha\nBETA\ngamma\n" and one.per_edit == [1])

seq = apply_edits(base, [Edit("alpha", "A"), Edit("A\nbeta", "AB")])
check("edits are sequential", seq.text == "AB\ngamma\n")

multi = apply_edits("a a a", [Edit("a", "b", replace_all=True)])
check("edit replace_all", multi.text == "b b b" and multi.per_edit == [3])

crlf = apply_edits("x\r\ny\r\n", [Edit("x", "z")])
check("edit normalizes CRLF", "\r" not in crlf.text and crlf.text.startswith("z"))

expect_error("edit not found", lambda: apply_edits(base, [Edit("nope", "x")]), PatchError)
expect_error("edit ambiguous", lambda: apply_edits("dup dup", [Edit("dup", "D")]), PatchError)
expect_error("edit empty old", lambda: apply_edits(base, [Edit("", "x")]), PatchError)
expect_error(
    "edit atomic rollback",
    lambda: apply_edits(base, [Edit("alpha", "A"), Edit("missing", "M")]),
    PatchError,
)

# --- grep / match ----------------------------------------------------------
hit = format_grep_hit("app/svc.py", 42, "    def handle(self):")
check("grep format", hit == "app/svc.py:42:     def handle(self):")
check("grep long line trimmed", "…" in format_grep_hit("f.py", 1, "z" * 300, max_line_chars=10))
check(
    "grep context markers",
    "f.py:9-" in format_grep_hit("f.py", 10, "x", before=["p"], after=["n"])
    and "f.py:11-" in format_grep_hit("f.py", 10, "x", after=["n"]),
)

lines = ["Foo bar", "baz Foo", "foo only"]
check("match case-sensitive", match_line_numbers(lines, "Foo") == [0, 1])
check("match ignore case", match_line_numbers(lines, "foo", ignore_case=True) == [0, 1, 2])
check("match whole word", match_line_numbers(["cat", "concat cat"], "cat", whole_word=True) == [0, 1])
check("match regex", match_line_numbers(["a1", "b2", "c"], r"^[ab]\d$", regex=True) == [0, 1])
check("match regex icase", match_line_numbers(["AB"], "ab", regex=True, ignore_case=True) == [0])
expect_error("match invalid regex raises", lambda: match_line_numbers(["a"], "(", regex=True), re.error)

# --- table / kv / paginate -------------------------------------------------
table = render_table(["id", "name"], [(1, "api"), (2, None), (3, "x" * 100)])
check("table NULL", "NULL" in table)
check("table cell clamp", "…" in table)
check("table rows", table.count("\n") == 6)  # sep + header + sep + 3 data + sep
check("table empty rows", render_table(["a"], []).count("\n") == 3)
check("kv skips empty", join_kv([("a", 1), ("b", ""), ("c", None)]) == "a=1")
check("paginate note", paginate_note(20, 100) == "[shown 20/100 items; next page: offset=20]")
check("paginate silent when complete", paginate_note(3, 3) == "")

print()
if FAILED:
    print(f"{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("ALL FORMATTING TESTS PASSED")
