#!/usr/bin/env python3
"""Mutation testing (mutmut) on changed backend modules, to check that the tests would catch a bug.

For each changed `arp/**/*.py` file, mutmut makes small deliberate bugs in it and runs only the tests
that import that module. A mutant the tests don't catch ("survived") marks a spot where the tests are
weak; the script reports a score per file (killed / (killed + survived)) and shows the survivors.

Usage (from backend/):
    python scripts/mutation_check.py --base origin/main        files this branch changed
    python scripts/mutation_check.py --since "24 hours"        files main changed recently (nightly)
    options: --min-score 60 (exit 1 below it; default 0 = report only), --summary FILE (markdown)
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

CFG = Path("setup.cfg")  # mutmut's fallback config; written per file, removed afterwards
SHOW_SURVIVORS = 5


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def changed_files(base: str | None, since: str | None) -> list[str]:
    if base:
        out = git("diff", "--name-only", f"{base}...HEAD", "--", "arp/")
    else:
        out = git("log", f"--since={since}", "--name-only", "--format=", "--", "arp/")
    files = {f.removeprefix("backend/") for f in out.split()}
    return sorted(f for f in files if f.endswith(".py") and Path(f).exists())


def tests_for(path: str) -> list[str]:
    """Test files that import the module, as `arp.x.y` or `from arp.x import y`."""
    module = path[:-3].replace("/", ".").removesuffix(".__init__")
    package, _, name = module.rpartition(".")
    pattern = re.compile(rf"\b{re.escape(module)}\b|from {re.escape(package)} import [^\n]*\b{re.escape(name)}\b")
    return sorted(str(t) for t in Path("tests").rglob("test_*.py") if pattern.search(t.read_text(errors="ignore")))


def mutate(path: str, tests: list[str]) -> dict[str, list[str]]:
    """Run mutmut on one file; return mutant names grouped by outcome ("error": mutmut's last output lines)."""
    selection = "".join(f"\n    {t}" for t in tests)
    CFG.write_text(
        f"[mutmut]\nsource_paths = arp/\nonly_mutate = {path}\nmutate_only_covered_lines = true\n"
        f"pytest_add_cli_args_test_selection ={selection}\n"
    )
    shutil.rmtree("mutants", ignore_errors=True)
    run = subprocess.run(["mutmut", "run"], capture_output=True, text=True, timeout=1800)
    out = subprocess.run(["mutmut", "results", "--all", "true"], capture_output=True, text=True).stdout
    groups: dict[str, list[str]] = {}
    if run.returncode != 0:  # e.g. a selected test fails before any mutant runs
        groups["error"] = (run.stdout + run.stderr).strip().splitlines()[-3:]
    for line in out.splitlines():
        name, sep, outcome = line.strip().rpartition(": ")
        if sep and "__mutmut_" in name:
            groups.setdefault(outcome, []).append(name)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--base")
    src.add_argument("--since")
    ap.add_argument("--min-score", type=float, default=0)
    ap.add_argument("--summary")
    args = ap.parse_args()

    files = changed_files(args.base, args.since)
    lines = ["## Mutation check", ""]
    if not files:
        lines.append("No changed backend modules.")
    else:
        lines += ["| File | Tests used | Killed | Survived | Score |", "|---|---|---|---|---|"]
    total_killed = total_survived = 0
    failed = False
    details: list[str] = []
    try:
        for f in files:
            tests = tests_for(f)
            if not tests:
                lines.append(f"| `{f}` | none import it | – | – | **no tests** |")
                continue
            g = mutate(f, tests)
            if "error" in g:
                lines.append(f"| `{f}` | {len(tests)} | – | – | **mutmut failed**: {' / '.join(g['error'])[-160:]} |")
                failed = True
                continue
            killed, survived = len(g.get("killed", [])), len(g.get("survived", []))
            total_killed += killed
            total_survived += survived
            score = f"{100 * killed / (killed + survived):.0f}%" if killed + survived else "–"
            lines.append(f"| `{f}` | {len(tests)} | {killed} | {survived} | {score} |")
            for name in g.get("survived", [])[:SHOW_SURVIVORS]:
                diff = subprocess.run(["mutmut", "show", name], capture_output=True, text=True).stdout.strip()
                details += [f"<details><summary>{name}</summary>", "", "```diff", diff, "```", "</details>", ""]
    finally:
        CFG.unlink(missing_ok=True)
        shutil.rmtree("mutants", ignore_errors=True)

    overall = 100 * total_killed / (total_killed + total_survived) if total_killed + total_survived else 100.0
    if files:
        lines += ["", f"Overall: {total_killed} killed, {total_survived} survived, score {overall:.0f}%."]
    if details:
        lines += ["", f"### Surviving mutants (first {SHOW_SURVIVORS} per file): the tests miss these bugs", ""] + details
    report = "\n".join(lines) + "\n"
    print(report)
    if args.summary:
        with open(args.summary, "a") as fh:
            fh.write(report)
    return 1 if failed or overall < args.min_score else 0


if __name__ == "__main__":
    sys.exit(main())
