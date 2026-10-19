"""Fail when a PR removes tests or asserts under backend/tests or frontend/tests.

CI twin of the test-guard mod (.claude/mods/test-guard): same paths, same markers, but it
blocks instead of warning. The owner overrides it with the `tests-weakened-ok` PR label.

Usage: python3 test_guard.py <base-ref>        compare <base-ref>...HEAD
       python3 test_guard.py --selftest
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = re.compile(r"^(backend|frontend)/tests/")
# Same markers as .claude/mods/test-guard/hooks/register.ts, except skip/todo variants, which
# count against the file here: skipping a test weakens it as much as deleting it.
MARKERS = re.compile(r"\bdef test_|\bassert\b|\b(it|test)(\.(?!skip\b|todo\b)\w+)?\(|\bexpect\(")
SKIPS = re.compile(r"\.(skip|todo)\(|\bpytest\.mark\.(skip|skipif|xfail)\b|\bpytest\.skip\(|\bunittest\.skip")


def count(text: str) -> int:
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", "//")))
    return len(MARKERS.findall(code)) - len(SKIPS.findall(code))


def git(*args: str, cwd: str | None = None) -> str:
    # errors="replace": binary fixtures under tests/ (PDFs) have no markers but must not crash the decode
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, errors="replace").stdout


def show(rev: str, path: str, cwd: str | None) -> str:
    try:
        return git("show", f"{rev}:{path}", cwd=cwd)
    except subprocess.CalledProcessError as e:
        if "does not exist" in e.stderr or "exists on disk, but not in" in e.stderr:
            return ""  # file absent on that side
        raise


def weakenings(base: str, cwd: str | None = None) -> list[tuple[str, int, int]]:
    """(path, before, after) for every test file whose marker count dropped since the merge base."""
    mb = git("merge-base", base, "HEAD", cwd=cwd).strip()
    out = []
    for line in git("-c", "core.quotePath=false", "diff", "--name-status", "-M", mb, "HEAD", cwd=cwd).splitlines():
        status, *paths = line.split("\t")
        old, new = paths[0], paths[-1]  # equal unless renamed
        if not (TESTS.match(old) or TESTS.match(new)):
            continue
        before = count(show(mb, old, cwd)) if TESTS.match(old) else 0
        after = 0 if status == "D" or not TESTS.match(new) else count(show("HEAD", new, cwd))
        if after < before:
            out.append((new, before, after))
    return out


def selftest() -> None:
    with tempfile.TemporaryDirectory() as d:

        def commit(files: dict[str, str | None], msg: str) -> None:
            for path, text in files.items():
                p = f"{d}/{path}"
                if text is None:
                    git("rm", "-q", path, cwd=d)
                    continue
                Path(p).parent.mkdir(parents=True, exist_ok=True)
                Path(p).write_text(text)
                git("add", path, cwd=d)
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, cwd=d)

        git("init", "-q", "-b", "main", cwd=d)
        commit(
            {
                "backend/tests/test_a.py": "def test_a():\n    assert 1\n    assert 2\n",
                "backend/tests/test_gone.py": "def test_b():\n    assert 1\n",
                "frontend/tests/x.test.ts": "test('x', () => { expect(1).toBe(1) })\n",
                "frontend/tests/skip.test.ts": "test('y', () => { expect(1).toBe(1) })\n",
                "backend/tests/test_c.py": "def test_c():\n    assert 1\n",
                "backend/tests/test_d.py": "def test_d():\n    assert 1\n",
                "backend/arp/mod.py": "assert True\n",
            },
            "base",
        )
        git("checkout", "-qb", "pr", cwd=d)
        commit(
            {
                "backend/tests/test_a.py": "def test_a():\n    assert 1\n",  # one assert dropped
                "backend/tests/test_gone.py": None,  # file deleted
                "frontend/tests/x.test.ts": "test('x', () => { expect(1).toBe(1); expect(2).toBe(2) })\n",  # grew
                "frontend/tests/skip.test.ts": "test.skip('y', () => { expect(1).toBe(1) })\n",  # skipped
                "backend/tests/test_c.py": "def test_c():\n    # assert 1\n",  # commented out
                "backend/tests/test_d.py": "@pytest.mark.skip\ndef test_d():\n    assert 1\n",  # skipped
                "backend/arp/mod.py": "",  # not a test file
            },
            "pr",
        )
        got = sorted(weakenings("main", cwd=d))
        assert got == [
            ("backend/tests/test_a.py", 3, 2),
            ("backend/tests/test_c.py", 2, 1),
            ("backend/tests/test_d.py", 2, 1),
            ("backend/tests/test_gone.py", 2, 0),
            ("frontend/tests/skip.test.ts", 2, 0),
        ], got
        git("mv", "backend/tests/test_a.py", "backend/tests/test_renamed.py", cwd=d)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "rename", cwd=d)
        assert ("backend/tests/test_renamed.py", 3, 2) in weakenings("main", cwd=d)
        Path(f"{d}/backend/tests/fixtures/doc.pdf").parent.mkdir(parents=True)
        Path(f"{d}/backend/tests/fixtures/doc.pdf").write_bytes(b"%PDF-1.4\n\x93\xff\x00binary")
        git("add", "backend/tests/fixtures/doc.pdf", cwd=d)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "binary fixture", cwd=d)
        assert ("backend/tests/test_renamed.py", 3, 2) in weakenings("main", cwd=d)  # no decode crash
    print("selftest ok")


def main() -> int:
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        return 0
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    found = weakenings(sys.argv[1])
    if not found:
        print("No tests or asserts removed.")
        return 0
    print("Tests or asserts were removed (test functions + asserts + it/test/expect calls):")
    for path, before, after in found:
        print(f"  {path}: {before} -> {after}")
    print("\nRestore them, or have the owner add the `tests-weakened-ok` label if the removal is intended.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
