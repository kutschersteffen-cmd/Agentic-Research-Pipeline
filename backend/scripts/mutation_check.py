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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CFG = Path("setup.cfg")  # mutmut's fallback config; written per file, removed afterwards
SHOW_SURVIVORS = 5
_NOTHING_COVERED = "could not find any test case for any mutant"  # mutmut 3.8 stops with exit 1
# Inside mutmut's backend/mutants/ copy, config.py's REPO_ROOT resolves to backend/, so every
# selected test that reads repo files (docs/, schemas/, ...) fails before a mutant runs.
SKIP = {
    "arp/config.py": "skipped: in mutmut's copy REPO_ROOT points at backend/",
    "arp/db/models.py": "skipped: models only; mutmut can't force a failure",
    "arp/schemas/common.py": "skipped: shared enums; its 180+ importing tests include browser-only ones",
}


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
        "also_copy =\n    scripts/\n"  # tests run inside mutants/; test_mutation_check.py reads scripts/ from there
        f"pytest_add_cli_args_test_selection ={selection}\n"
    )
    shutil.rmtree("mutants", ignore_errors=True)
    # Same REPO_ROOT problem as SKIP: tests that start the API check the rule book, so point at the real one.
    env = {
        **os.environ,
        "ARP_TRANSITION_BARRIER_DATA_DIR": str(Path("arp/transition_barrier/data").resolve()),
        "ARP_TRANSITION_ALIGNMENT_DATA_DIR": str(Path("arp/transition_alignment/data").resolve()),
    }
    run = subprocess.run(["mutmut", "run"], capture_output=True, text=True, timeout=1800, env=env)
    out = subprocess.run(["mutmut", "results", "--all", "true"], capture_output=True, text=True).stdout
    groups: dict[str, list[str]] = {}
    if run.returncode != 0 and _NOTHING_COVERED in run.stdout:  # e.g. an empty __init__.py: nothing to judge
        groups["uncovered"] = []
    elif run.returncode != 0:  # e.g. a selected test fails before any mutant runs
        groups["error"] = (run.stdout + run.stderr).strip().splitlines()[-3:]
    for line in out.splitlines():
        name, sep, outcome = line.strip().rpartition(": ")
        if sep and "__mutmut_" in name:
            groups.setdefault(outcome, []).append(name)
    return groups


def link_repo_root(src: Path = Path(".."), dst: Path = Path(".")) -> list[Path]:
    """In mutmut's backend/mutants/ copy, code and tests resolve the repo root to backend/. Link each repo entry
    missing from backend/ (backend itself included, folders present in both merged entry by entry) so that
    REPO_ROOT / "docs" or REPO / "scripts" / "x.js" resolve. Returns the links made, for removal."""
    made = []
    for entry in sorted(src.iterdir()):
        target = dst / entry.name
        if entry.name == ".git" or target.is_symlink():
            continue
        if not target.exists():
            target.symlink_to(os.path.relpath(entry, dst))
            made.append(target)
        elif entry.is_dir() and target.is_dir() and entry.resolve() != target.resolve():
            made += link_repo_root(entry, target)
    return made

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
    links = link_repo_root()
    try:
        for f in files:
            if f in SKIP:
                lines.append(f"| `{f}` | – | – | – | {SKIP[f]} |")
                continue
            tests = tests_for(f)
            if not tests:
                lines.append(f"| `{f}` | none import it | – | – | **no tests** |")
                continue
            g = mutate(f, tests)
            if "uncovered" in g:
                lines.append(f"| `{f}` | {len(tests)} | – | – | no mutant is covered by these tests |")
                continue
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
        for link in links:
            link.unlink()
        CFG.unlink(missing_ok=True)
        shutil.rmtree("mutants", ignore_errors=True)

    overall = 100 * total_killed / (total_killed + total_survived) if total_killed + total_survived else 100.0
    if files:
        lines += ["", f"Overall: {total_killed} killed, {total_survived} survived, score {overall:.0f}%."]
        if failed:
            lines.append("mutmut failed on at least one file (see the table), so the score is incomplete.")
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
