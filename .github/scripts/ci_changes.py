"""Which CI jobs a pull request needs, from its changed files (one path per line on stdin).

Prints `backend=`, `frontend=` and `app=` (either of the two: E2E, container scan) lines for $GITHUB_OUTPUT.
The first matching rule wins. A file no rule matches, or an empty list, runs everything, so a new folder is
safe by default. A path counts for a job when that job's build or tests read it. `--selftest` checks fixed cases.
"""
import sys
from fnmatch import fnmatch

B, F, BF, NONE = {"backend"}, {"frontend"}, {"backend", "frontend"}, set()
RULES = [
    (".github/*", BF),
    ("frontend/src/api/openapi.json", BF),  # the API contract: backend's `export_openapi.py --check` reads it
    ("backend/arp/schemas/review.py", BF),  # frontend/tests/argusShowcaseFixesPr3.test.ts reads these two
    ("backend/arp/extraction/routing.py", BF),
    ("backend/tests/fixtures/rule_sentences.json", BF),  # frontend/tests/ruleSentence.test.ts
    ("backend/*", B),
    ("frontend/*", F),
    ("DESIGN.md", F),  # frontend/tests/designDoc.test.ts, workspaceCard.test.ts
    ("docs/decision-studio/*", B),  # docs the backend tests read
    ("docs/transition_barrier/*", B),
    ("docs/INSTALLATION.md", B),
    ("docs/*", NONE),
    (".claude/*", NONE),
    ("openwiki/*", NONE),
    ("notes/*", NONE),
    ("README.md", NONE),
    ("GLOSSARY.md", NONE),
    ("PRODUCT.md", NONE),
]


def jobs(files):
    files = [f for f in files if f]
    need = set() if files else BF
    for f in files:
        need |= next((areas for pattern, areas in RULES if fnmatch(f, pattern)), BF)
    return {"backend": "backend" in need, "frontend": "frontend" in need, "app": bool(need)}


CASES = [  # (name, changed files, jobs that run)
    ("frontend only", ["frontend/src/pages/Home.tsx", "frontend/tests/landing.test.ts"], "frontend app"),
    ("backend only", ["backend/arp/api/main.py", "backend/tests/test_api.py"], "backend app"),
    ("docs only", ["docs/superpowers/specs/2026-11-16-x-design.md", "README.md"], ""),
    (".claude only", [".claude/skills/steward/SKILL.md", ".claude/hooks/check.sh"], ""),
    ("mixed", ["backend/arp/api/main.py", "frontend/src/App.tsx", "docs/x.md"], "backend frontend app"),
    (".github", [".github/scripts/test_guard.py", "docs/x.md"], "backend frontend app"),
    ("API contract", ["backend/arp/api/routers/x.py", "frontend/src/api/openapi.json"], "backend frontend app"),
    ("docs a backend test reads", ["docs/INSTALLATION.md"], "backend app"),
    ("DESIGN.md", ["DESIGN.md"], "frontend app"),
    ("unknown top-level file", ["docker-compose.yml"], "backend frontend app"),
    ("empty list", [], "backend frontend app"),
]


def selftest():
    bad = 0
    for name, files, want in CASES:
        got = " ".join(job for job, run in jobs(files).items() if run)
        bad += got != want
        print(f"{'ok  ' if got == want else 'FAIL'} {name:26} runs: {got or '(none)'}" + ("" if got == want else f"  expected: {want}"))
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    for job, run in jobs(sys.stdin.read().splitlines()).items():
        print(f"{job}={'true' if run else 'false'}")
