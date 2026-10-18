"""Fail when a PR changes generated OpenWiki files outside a context-refresh/YYYY-MM-DD branch.

Everything under openwiki/ is generated except openwiki/INSTRUCTIONS.md, which is hand-written.
graphify-out/ is gitignored and never on main, so it needs no guard.

Usage: python3 context_guard.py --head-ref <ref> [--changed <path>...]   without --changed: origin/main...HEAD
       python3 context_guard.py --selftest
"""

import argparse
import re
import subprocess
import sys

GENERATED = re.compile(r"^openwiki/(?!INSTRUCTIONS\.md$)")
REFRESH_BRANCH = re.compile(r"^context-refresh/\d{4}-\d{2}-\d{2}$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def check(head_ref: str, changed: list[str]) -> list[str]:
    """Generated paths in `changed` that this branch may not touch."""
    if REFRESH_BRANCH.match(head_ref):
        return []
    return [p for p in changed if GENERATED.match(p)]


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
        changed = git("-c", "core.quotePath=false", "diff", "--name-only", "origin/main...HEAD").splitlines()
    bad = check(args.head_ref, changed)
    for path in bad:
        print(f"generated file changed outside context-refresh/*: {path}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
