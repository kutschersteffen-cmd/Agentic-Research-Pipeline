"""Fail when a PR changes generated OpenWiki files outside a context-refresh/YYYY-MM-DD branch.

Everything under openwiki/ is generated except openwiki/INSTRUCTIONS.md, which is hand-written.
graphify-out/ is gitignored and never on main, so it needs no guard.

Usage: python3 context_guard.py --head-ref <ref> [--changed <path>...]   without --changed: origin/main...HEAD
       python3 context_guard.py --selftest
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

GENERATED = re.compile(r"^openwiki/(?!INSTRUCTIONS\.md$)")
REFRESH_BRANCH = re.compile(r"^context-refresh/\d{4}-\d{2}-\d{2}$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def check(head_ref: str, changed: list[str]) -> list[str]:
    """Generated paths in `changed` that this branch may not touch."""
    if REFRESH_BRANCH.match(head_ref):
        return []
    return [p for p in changed if GENERATED.match(p)]


def changed_paths() -> list[str]:
    # --no-renames: moving a generated file out of openwiki/ must still list its old path.
    return git("-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", "origin/main...HEAD").splitlines()


def selftest() -> None:
    cases = [
        ("feat/x", ["openwiki/a.md"], ["openwiki/a.md"]),
        ("feat/x", ["openwiki/INSTRUCTIONS.md"], []),
        ("context-refresh/2026-10-19", ["openwiki/a.md"], []),
        ("feat/x", ["backend/arp/config.py"], []),
        ("context-refresh/x", ["openwiki/a.md"], ["openwiki/a.md"]),
    ]
    for ref, changed, want in cases:
        got = check(ref, changed)
        assert got == want, (ref, changed, got, want)
    # A rename out of openwiki/ in a real repo: the guard must see the old path.
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            git("init", "-q")
            os.mkdir("openwiki")
            with open("openwiki/a.md", "w") as f:
                f.write("# A\n" * 20)
            git("add", "-A")
            git("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "base")
            git("update-ref", "refs/remotes/origin/main", "HEAD")
            git("mv", "openwiki/a.md", "a.md")
            git("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "move")
            assert check("feat/x", changed_paths()) == ["openwiki/a.md"], changed_paths()
        finally:
            os.chdir(cwd)
    print("selftest ok")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--head-ref")
    ap.add_argument("--changed", nargs="*")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0
    if args.head_ref is None:
        ap.error("--head-ref is required")
    changed = args.changed
    if changed is None:
        changed = changed_paths()
    bad = check(args.head_ref, changed)
    for path in bad:
        print(f"generated file changed outside context-refresh/*: {path}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
