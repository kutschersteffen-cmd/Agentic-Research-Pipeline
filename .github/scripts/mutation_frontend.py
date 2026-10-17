#!/usr/bin/env python3
"""Mutation testing (Stryker) on changed frontend files that a test imports.

Frontend twin of backend/scripts/mutation_check.py: plants small bugs in each changed
`frontend/src/**/*.ts(x)` file some `frontend/tests/*.test.ts` imports, runs `npm test` per mutant,
and reports a score per file plus the surviving mutants (bugs the tests miss). Files no test imports
are listed as "no tests" rather than mutated, since every mutant there would survive.

Usage (from the repo root):
    python3 .github/scripts/mutation_frontend.py --base=origin/main | --since="26 hours"
    options: --min-score 60 (exit 1 below it; default 0 = report only), --summary FILE
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FRONTEND = Path("frontend")
REPORT = FRONTEND / "reports" / "mutation" / "mutation.json"
STRYKER = ["npx", "--yes", "-p", "@stryker-mutator/core@10.0.0", "-p", "typescript@5.9.2", "stryker", "run"]
SHOW_SURVIVORS = 5


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def changed_files(base: str | None, since: str | None) -> list[str]:
    if base:
        out = git("diff", "--name-only", f"{base}...HEAD", "--", "frontend/src")
    else:
        out = git("log", f"--since={since}", "--name-only", "--format=", "--", "frontend/src")
    return sorted({f for f in out.split() if re.search(r"\.tsx?$", f) and Path(f).exists()})


def imported_by_tests(path: str) -> bool:
    """True when a frontend test imports the file (`from "../src/lib/jobs.ts"` or without extension)."""
    stem = re.escape(str(Path(path).relative_to(FRONTEND).with_suffix("")))
    pattern = re.compile(rf"""from\s+["']\.\./{stem}(\.tsx?)?["']""")
    return any(pattern.search(t.read_text()) for t in (FRONTEND / "tests").glob("*.test.ts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--base")
    src.add_argument("--since")
    ap.add_argument("--min-score", type=float, default=0)
    ap.add_argument("--summary")
    args = ap.parse_args()

    files = changed_files(args.base, args.since)
    tested = [f for f in files if imported_by_tests(f)]
    lines = ["## Mutation check (frontend)", ""]
    if not files:
        lines.append("No changed frontend source files.")
    killed = survived = 0
    failed = False
    details: list[str] = []
    if files:
        lines += ["| File | Killed | Survived | Score |", "|---|---|---|---|"]
        lines += [f"| `{f}` | – | – | **no tests import it** |" for f in files if f not in tested]
    if tested:
        mutate = ",".join(str(Path(f).relative_to(FRONTEND)) for f in tested)
        run = subprocess.run([*STRYKER, "--mutate", mutate], cwd=FRONTEND, capture_output=True, text=True)
        if run.returncode != 0 or not REPORT.exists():
            failed = True
            tail = " / ".join((run.stdout + run.stderr).strip().splitlines()[-3:])[-200:]
            lines.append(f"| {', '.join(tested)} | – | – | **Stryker failed**: {tail} |")
        else:
            report = json.loads(REPORT.read_text())
            for name, data in sorted(report["files"].items()):
                status = [m["status"] for m in data["mutants"]]
                k, s = status.count("Killed") + status.count("Timeout"), status.count("Survived") + status.count("NoCoverage")
                killed, survived = killed + k, survived + s
                lines.append(
                    f"| `frontend/{name}` | {k} | {s} | {100 * k / (k + s):.0f}% |"
                    if k + s
                    else f"| `frontend/{name}` | 0 | 0 | – |"
                )
                source = data["source"].splitlines()
                missed = [m for m in data["mutants"] if m["status"] in ("Survived", "NoCoverage")]
                missed.sort(key=lambda m: m["mutatorName"] in ("StringLiteral", "ObjectLiteral"))  # logic first, labels last
                for m in missed[:SHOW_SURVIVORS]:
                    line = m["location"]["start"]["line"]
                    details += [
                        f"- `frontend/{name}:{line}` {m['mutatorName']}: `{source[line - 1].strip()[:100]}` → `{m.get('replacement', '')[:60]}`"
                    ]
    overall = 100 * killed / (killed + survived) if killed + survived else 100.0
    if tested and not failed:
        lines += ["", f"Overall: {killed} killed, {survived} survived, score {overall:.0f}%."]
    if details:
        lines += ["", f"### Surviving mutants (first {SHOW_SURVIVORS} per file): the tests miss these bugs", ""] + details
    text = "\n".join(lines) + "\n"
    print(text)
    if args.summary:
        with open(args.summary, "a") as fh:
            fh.write(text)
    return 1 if failed or overall < args.min_score else 0


if __name__ == "__main__":
    sys.exit(main())
