"""Which CI jobs a pull request needs, from the files its merge commit changes (`git diff HEAD^1 HEAD`).

Prints `backend=`, `frontend=` and `app=` (either of the two: E2E, container scan) lines for $GITHUB_OUTPUT.
The first matching rule wins. A file no rule matches, or an empty list, runs everything, so a new folder is
safe by default. A path counts for a job when that job's build or tests read it. `--selftest` checks fixed cases.
"""
import subprocess
import sys
import tempfile
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


def changed_files(cwd=None):
    # --no-renames: a move lists its old path too, so `git mv backend/x.py docs/` still runs the backend job
    cmd = ["git", "diff", "--no-renames", "--name-only", "HEAD^1", "HEAD"]
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.splitlines()


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
    ("API contract", ["frontend/src/api/openapi.json"], "backend frontend app"),
    ("review.py", ["backend/arp/schemas/review.py"], "backend frontend app"),
    ("routing.py", ["backend/arp/extraction/routing.py"], "backend frontend app"),
    ("rule_sentences.json", ["backend/tests/fixtures/rule_sentences.json"], "backend frontend app"),
    ("docs/decision-studio", ["docs/decision-studio/example-framework/targets/x.csv"], "backend app"),
    ("docs/transition_barrier", ["docs/transition_barrier/RULE_BOOK.md"], "backend app"),
    ("docs/INSTALLATION.md", ["docs/INSTALLATION.md"], "backend app"),
    ("DESIGN.md", ["DESIGN.md"], "frontend app"),
    ("unknown top-level file", ["docker-compose.yml"], "backend frontend app"),
    ("empty list", [], "backend frontend app"),
]


def renamed_into_docs():
    """The files changed_files() sees after `git mv backend/x.py docs/x.py`, in a scratch repo."""
    with tempfile.TemporaryDirectory() as d:
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True)
        git("init", "-q")
        subprocess.run(["mkdir", "backend", "docs"], cwd=d, check=True)
        open(f"{d}/backend/x.py", "w").write("x = 1\n" * 20)
        git("add", "-A")
        git("commit", "-qm", "base")
        git("mv", "backend/x.py", "docs/x.py")
        git("commit", "-qm", "move")
        return changed_files(d)


def selftest():
    bad = 0
    for name, files, want in CASES + [("move backend/ into docs/ (git)", renamed_into_docs(), "backend app")]:
        got = " ".join(job for job, run in jobs(files).items() if run)
        bad += got != want
        print(f"{'ok  ' if got == want else 'FAIL'} {name:31} runs: {got or '(none)'}" + ("" if got == want else f"  expected: {want}"))
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    for job, run in jobs(changed_files()).items():
        print(f"{job}={'true' if run else 'false'}")
