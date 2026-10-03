# Repository conventions

Python (FastAPI + Typer) backend in `backend/`, React/TypeScript (Vite) frontend in `frontend/`,
file-based run state in `runs/`. Two rules hold everywhere: the LLM plans and deterministic code
computes, and every citation is re-verified programmatically against the source document
(`backend/arp/grounding.py`).

## Pull requests

**The base branch for every pull request is `main`.** Always target `main`, regardless of what
GitHub reports as the default branch (it currently points at a `claude/*` feature branch and is
wrong). Do not read the base off `git remote show origin` or `refs/remotes/origin/HEAD`.
`.claude/hooks/pr-base-main.sh` blocks `create_pull_request` for any other base.

Branch off `main`. If a branch was created from anything else, merge `origin/main` into it before
opening the PR so the diff shows only the intended change.

## Commands

Run all of these before saying a task is done, and show the output.

- Backend tests (no API key or network needed): `cd backend && pytest -q`
- Backend lint: `cd backend && ruff check .`
- Frontend lint: `cd frontend && npm run lint`
- Frontend typecheck and build: `cd frontend && npm run build`
- Frontend unit tests: `cd frontend && npm test`

If a test fails, fix the code, not the test. Never skip, delete or weaken a failing test.

## Rules that must hold

- Standing agents (Taxonomy Researcher, Calibration Agent) propose changes for human review. They
  never apply them.
- A figure that reaches a report must trace to a grounded citation. Correct a wrong extracted
  value through the review/override flow, which keeps the audit trail, never by editing results
  files.
- Do not edit ratified frameworks or taxonomies in place. They are versioned; add a new version.
- No auth sits in front of the API yet (`docs/CORPORATE_READINESS_PLAN.md`). Do not add secrets to
  the repo; CI scans for them.

## Things Claude gets wrong

When Claude makes the same mistake twice, add the correction here.

- Opening a PR against the repo's reported default branch instead of `main`.
- Using `superpowers:requesting-code-review` or `receiving-code-review` (banned, see below).

## Which plugin does what

Install steps and per-plugin notes are in `docs/PLUGINS.md`. Each plugin owns a phase:

- **Planning → superpowers.** For non-trivial work use `superpowers:brainstorming`, then
  `superpowers:writing-plans`. Apply ponytail's ladder to the plan: cut tasks that don't need to
  exist. Trivial changes skip planning.
- **Spec, tickets, handoff → mattpocock-skills.** `grill-with-docs`, `to-spec`, `to-tickets`,
  `handoff`, `research`. Where it overlaps superpowers or `/code-review` (`tdd`, `diagnosing-bugs`,
  `code-review`), use the superpowers or built-in one. Never use its `pr` skill. Ignore
  `in-progress/`.
- **Implementation → ponytail.** Smallest working diff; follow the plan's tasks, not more.
- **Verifying → `prove-it-works`.** Check the real artifact before claiming done. Measured numbers
  also go through `explain-the-number`. Long or unattended work keeps a trail with
  `show-me-your-work`.
- **Frontend design → impeccable and ui-ux-pro-max.**
- **Review → ponytail plus `/code-review`**, following `REVIEW.md`. Do not use
  `superpowers:requesting-code-review` or `superpowers:receiving-code-review`.
- **Finishing → no auto-merge.** `superpowers:finishing-a-development-branch` must open a PR
  against `main`; never merge locally.

Plugin skills are namespaced (`/ponytail:ponytail-review`). In cloud sessions there is no `/`
picker: type the skill name and send it, or describe what you want.

# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.
