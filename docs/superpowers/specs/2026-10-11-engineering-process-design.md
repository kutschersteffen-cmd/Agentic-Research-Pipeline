# Engineering process: written rules plus automatic gates

Date: 2026-10-11. Status: draft for review.
Background research: [`docs/AGENTIC_ENGINEERING_PROCESS_RESEARCH.md`](../../AGENTIC_ENGINEERING_PROCESS_RESEARCH.md).

## Goal

One process for this repo that keeps complexity low, keeps the code maintainable, keeps frontend
UX quality up, and catches bugs before a human has to. Anything a machine can check is enforced
by a hook, pre-commit or CI. `CLAUDE.md` holds only judgement calls and pointers.

Success means: Claude cannot finish a turn with failing lint or tests on the code it changed,
and every check that exists in the repo runs somewhere automatically.

## Target process

| # | Stage | What happens | Enforced by | Change |
|---|---|---|---|---|
| 1 | Frame | Trivial: skip. Otherwise brainstorm → spec → agree test seams → plan | Human approves spec | None |
| 2 | Build | Failing test first, then the smallest change that passes | ponytail + TDD skill (advisory) | None |
| 3 | Self-check | Lint, typecheck and matching tests on changed code | Stop hook (Gate A) | **New** |
| 4 | Review | `/ponytail:ponytail-review` + `/code-review` | `CLAUDE.md` rule | None |
| 5 | Commit | gitleaks + ruff | pre-commit (Gate B) | **Extend** |
| 6 | Merge | Full backend suite, frontend lint + build + tests; PR to `main`; human merges | CI (Gate C) + human | **Extend** |

Rules everywhere: check at the cheapest stage that can catch the problem; never weaken a test
to make it pass; nothing merges without a human.

## Gate A: Stop hook

New script `.claude/hooks/check.sh`, registered in `.claude/settings.json` under `hooks.Stop`
as a command hook with `timeout: 600`.

1. Read the hook's JSON from stdin. If `stop_hook_active` is true, exit 0. This lets Claude
   stop after one blocked attempt, so the hook can never loop.
2. Changed files = `git diff --name-only <base>` plus untracked files
   (`git ls-files --others --exclude-standard`), where `<base>` is
   `git merge-base HEAD origin/main`, falling back to `HEAD` if `origin/main` is missing.
   Diffing against the branch base (not `HEAD`) matters because Claude often commits before
   stopping. Deleted files are dropped.
3. Nothing under `backend/` or `frontend/` changed → exit 0.
4. Backend `.py` files changed:
   - `ruff check` on those files (run from `backend/`, so `pyproject.toml` config applies).
   - Tests to run = changed files under `backend/tests/`, plus every test file that mentions a
     changed module's dotted path (`backend/arp/index/calc.py` → grep `arp.index.calc` in
     `backend/tests/`). Measured: this finds tests for 395 of 497 modules; the rest are left
     to CI.
   - `pytest -q` on that set, if non-empty.
5. Anything under `frontend/` changed (excluding `node_modules/`): `npm run lint`,
   `npx tsc -b`, `npm test`, from `frontend/`.
6. If a tool is missing (`pytest`, `ruff`, `frontend/node_modules`), treat it as a failure
   whose message says what to install (`pip install -e "backend[dev]"` / `npm ci`).
7. Any failure → print the failing command and its last ~50 lines of output to stderr, exit 2.
   All pass → exit 0, no output.

Not in Gate A: the full backend suite (CI only), screenshots, LLM judgement.

## Gate B: pre-commit

Add `ruff` from `astral-sh/ruff-pre-commit` (pinned `rev`) to `.pre-commit-config.yaml`,
next to `gitleaks`, with `args: [--config=backend/pyproject.toml]` and `files: ^backend/`.
Frontend checks stay in Gate A and CI because they need `node_modules`.

## Gate C: CI

Add a `Test` step running `npm test` after `Typecheck + build` in the frontend job of
`.github/workflows/ci.yml`. The 18 frontend test files start running on every PR.

## `CLAUDE.md` changes

The plugin section stays. Additions, about 12 lines, giving roughly 147 lines in total:

1. New `## Checks` section after "Coding rules": the backend commands
   (`cd backend && ruff check . && pytest tests/<file>`), the frontend commands
   (`cd frontend && npm run lint && npx tsc -b && npm test`), and one line saying the Stop hook
   runs the matching subset automatically and CI runs everything.
2. Coding rules gain: "Never delete or weaken an existing test to make it pass. List every
   test change in the PR description."
3. "Frontend design" bullet gains: "After a UI change, screenshot the affected page with
   Playwright and run `/impeccable:impeccable audit`."

## Deferred

- PR review bot (`claude-code-action` running `/code-review --comment`, Opus 5.5). Add once CI
  is reliably green.
- Separate verification agent (subagent or agent-type Stop hook, Opus 5.5). Add if Claude
  passes tests with code that misses the spec.
- Moving the plugin install text out of `CLAUDE.md`. Do it if the file passes 200 lines.

## Testing this change

- Gate A: run the script against three states: a backend change that fails ruff, a backend
  change with a failing test, and a clean tree. Expect exit 2, exit 2 and exit 0. Also check
  that `stop_hook_active: true` exits 0.
- Gate B: `pre-commit run --all-files` passes on the current tree.
- Gate C: `cd frontend && npm test` passes locally before the CI step is added.

## Open risks

- Frontend `npm test` has never run in CI and may fail on its first run. If so, fix it or
  report it before enabling the step.
- `ruff` in pre-commit may flag existing files on `--all-files`. It only checks staged files
  on normal commits, so it doesn't block unrelated work.
- Gate A runtime depends on how many tests match. Not yet measured.
