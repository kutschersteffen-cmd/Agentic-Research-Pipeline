# Engineering Process Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce lint and tests automatically: a Stop hook for changed code, ruff in pre-commit, frontend tests in CI, and three `CLAUDE.md` additions.

**Architecture:** One bash script (`.claude/hooks/check.sh`) registered as a command-type Stop hook selects and runs checks for files changed since the branch base. Pre-commit and CI get one entry each. `CLAUDE.md` gets about 12 lines.

**Tech Stack:** bash, git, ruff, pytest, npm (oxlint, tsc, node --test), pre-commit, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-11-engineering-process-design.md`

## Global Constraints

- Stop hook: command type, `timeout: 600`, exit 2 on failure with output on stderr, exit 0 silently on success.
- `stop_hook_active: true` on stdin → exit 0 immediately.
- Changed files = `git diff --name-only <base>` + `git ls-files --others --exclude-standard`; `<base>` = `git merge-base HEAD origin/main`, else `HEAD`. Deleted files dropped.
- Backend test selection: changed `backend/tests/**` files + test files that contain the changed module's dotted path (`backend/arp/index/calc.py` → `arp.index.calc`).
- Frontend checks, from `frontend/`: `npm run lint`, `npx tsc -b`, `npm test`.
- Missing tool is a failure whose message names the install command: `pip install -e "backend[dev]"` / `npm ci`.
- Failure output: failing command plus its last ~50 lines.
- `CLAUDE.md` keeps the plugin section; total stays under 200 lines.
- Coding rules: no edits to adjacent code; nothing unrequested.

## Review Focus

1. Only non-code files changed (docs, `.claude/`) → hook exits 0 with no output, no tool invoked.
2. `origin/main` missing (fresh clone without fetch) → falls back to `HEAD`, no error.
3. A changed backend module with no matching tests → ruff still runs; pytest skipped, no "no tests ran" failure (pytest exit 5 must not count as failure).
4. File paths with spaces → handled (read paths line by line, quote them).
5. A deleted `.py` file in the diff → not passed to ruff or grep.

Tests for 1, 3 and 5 are in Task 1's self-check. 2 and 4 are handled by construction and checked in the Task 1 code review.

---

### Task 0: Bring the branch up to date

The branch `ccr-a333a9a2-2d2ftu` is 27 commits behind `origin/main` (checked 2026-10-12). None
of those commits touch the files this plan changes.

- [ ] Run `git fetch origin main && git merge --no-edit origin/main`. Expected: no conflicts.
- [ ] Push.

### Task 1: Stop hook (Gate A)

**Files:**
- Create: `.claude/hooks/check.sh`
- Create: `.claude/hooks/check_selftest.sh`
- Modify: `.claude/settings.json` (add `hooks.Stop`)

**Interfaces:**
- Consumes: nothing.
- Produces: `bash .claude/hooks/check.sh` reading hook JSON on stdin; exit 0 = pass or nothing to check, exit 2 = failure with details on stderr. Run from any directory; it `cd`s to `git rev-parse --show-toplevel`.

- [ ] **Step 1: Write the self-check `check_selftest.sh`**

It clones the repo into a temp dir (`git clone -q "$repo" "$tmp"`), runs each scenario there with `echo '{}' | bash .claude/hooks/check.sh`, asserts the exit code, and resets the clone between scenarios (`git -C "$tmp" clean -fdq && git -C "$tmp" checkout -q .`). It prints `PASS <name>` / `FAIL <name>` and exits non-zero if any scenario fails.

| Scenario | Setup in clone | Expected exit |
|---|---|---|
| `clean_tree` | nothing | 0 |
| `stop_hook_active` | add `backend/arp/_bad.py` with `import os` (unused, F401); stdin `{"stop_hook_active": true}` | 0 |
| `docs_only` | add `docs/_x.md` | 0 |
| `ruff_failure` | add `backend/arp/_bad.py` with `import os` | 2, and stderr contains `F401` |
| `test_failure` | add `backend/tests/test__bad.py` with `def test_x(): assert False` | 2, and stderr contains `test__bad.py` |
| `no_matching_tests` | add `backend/arp/_ok.py` with `X = 1` | 0 |
| `deleted_file` | `git rm -q` any one `backend/arp/**.py` that no test imports (staged, not committed) | 0 (ruff is not called on the missing file) |

- [ ] **Step 2: Run it to make sure it fails**

Run: `bash .claude/hooks/check_selftest.sh`
Expected: every scenario except `clean_tree` and `docs_only` FAILs, because `check.sh` doesn't exist.

- [ ] **Step 3: Implement `.claude/hooks/check.sh`**

`#!/bin/bash`, no `set -e`. Steps in order, as in Global Constraints. Notes:
- Parse `stop_hook_active` with `python3 -c 'import json,sys; print(json.load(sys.stdin).get("stop_hook_active", False))'`. Python is always present in this repo's environments; don't add a `jq` dependency.
- Keep only paths that still exist (`[ -f "$f" ]`).
- Run ruff and pytest from `backend/` with paths relative to it. A pytest exit code of 5 (no tests collected) counts as a pass.
- Collect failures into one buffer; print them all, then exit 2.

- [ ] **Step 4: Run the self-check to verify it passes**

Run: `bash .claude/hooks/check_selftest.sh`
Expected: 7 × `PASS`, exit 0.

- [ ] **Step 5: Register the hook in `.claude/settings.json`**

Add `"Stop"` next to `"SessionStart"` inside `"hooks"`:
```json
"Stop": [{"hooks": [{"type": "command", "command": "bash \"${CLAUDE_PROJECT_DIR}/.claude/hooks/check.sh\"", "timeout": 600}]}]
```
Verify: `python3 -m json.tool .claude/settings.json > /dev/null` exits 0.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/check.sh .claude/hooks/check_selftest.sh .claude/settings.json
git commit -m "feat: add Stop hook that lints and tests changed code"
```

### Task 2: ruff in pre-commit (Gate B)

**Files:**
- Modify: `.pre-commit-config.yaml`

**Interfaces:** none.

- [ ] **Step 1: Add the ruff repo after the gitleaks entry**

```yaml
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.8
    hooks:
      - id: ruff
        args: [--config=backend/pyproject.toml]
        files: ^backend/
```
`v0.16.8` matches the ruff that `backend[dev]` installs (checked 2026-10-11). If that tag doesn't exist upstream, use the nearest existing tag and say so in the commit message.

- [ ] **Step 2: Verify**

Run: `pip install -q pre-commit && pre-commit run ruff --all-files`
Expected: `Passed`. If it fails on existing files, stop and report: CI's `ruff check .` should already pass, so a failure means a config mismatch, not something to fix file by file.

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: run ruff on backend files in pre-commit"
```

### Task 3: frontend tests in CI (Gate C)

**Files:**
- Modify: `.github/workflows/ci.yml` (frontend job, after the `Typecheck + build` step at line ~101)

**Interfaces:** none.

- [ ] **Step 1: Add the step**

```yaml
      - name: Test
        run: npm test
```
Match the indentation of `Typecheck + build`. The job's `working-directory: frontend` default applies.

- [ ] **Step 2: Verify**

Run: `cd frontend && npm test` → `# pass 160`, `# fail 0`.
Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` → exit 0.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run frontend tests"
```

### Task 4: `CLAUDE.md` additions

**Files:**
- Modify: `.claude/CLAUDE.md`

**Interfaces:** Consumes: the commands from Tasks 1–3.

- [ ] **Step 1: In "Which plugin does what", extend the "Frontend design" bullet**

Append: "After a UI change, screenshot the affected page with Playwright and run `/impeccable:impeccable audit`."

- [ ] **Step 2: In "Coding rules", add one bullet**

"Never delete or weaken an existing test to make it pass. List every test change in the PR description."

- [ ] **Step 3: Add a `## Checks` section directly after "Coding rules"**

Content: the backend command `cd backend && ruff check . && pytest tests/<file>`; the frontend command `cd frontend && npm run lint && npx tsc -b && npm test`; one sentence: "The Stop hook (`.claude/hooks/check.sh`) runs these on the code you changed and blocks finishing on failure; CI runs the full suites."

- [ ] **Step 4: Verify**

Run: `wc -l .claude/CLAUDE.md` → under 200 (expected about 147).
Run: `git diff --stat .claude/CLAUDE.md` → insertions only, no deletions.

- [ ] **Step 5: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: add checks, test rule and UI rule to CLAUDE.md"
```

### Task 5: Review and PR

- [ ] Run `/ponytail:ponytail-review` and `/code-review` on the branch diff; fix findings.
- [ ] Open a PR against `main` (per `CLAUDE.md`). Never merge locally.
