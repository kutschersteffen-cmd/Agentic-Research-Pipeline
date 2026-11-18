# Factory: intake stage, path-routed reviewers, model by risk

Three changes to `.claude/skills/factory/SKILL.md`, taken from an outside "software factory" diagram.
No app code changes.

## 1. Intake stage (new stage 0)

`/factory <feature>` first starts an intake session (model `sonnet`) with this job: read the request, the
wiki/graph and the open board, then answer in one comment on the board card:

- `GO`: one-paragraph scope (what is in, what is out), a proposed risk (`low|normal|high`, per the
  steward table) and a size (`S` ≤ 1 PR, `M` 2-3 PRs, `L` more; `L` must be split into features first).
- `NEEDS-INFO`: at most 3 questions, asked to the owner with `AskUserQuestion`. The feature waits.
- `REJECT`: the reason (already built, duplicate of an open card, out of scope). The card closes.

Stage 1 (spec) starts only on `GO`, and its prompt includes the intake scope. The proposed risk is a
floor: the steward may raise it at PR time, never lower it.

## 2. Reviewers routed by changed paths

Stage 4 keeps the code review and adds, started together with it:

- **Security review** when the PR touches any `risk:high` path from the steward table: run
  `/security-review`, same `Proof:` and verifier rules, comment headed `Security review (factory)`.
- **UI review** when the PR touches `frontend/src/**`: Playwright screenshot of each changed page,
  `/impeccable:impeccable audit`, comment headed `UI review (factory)`; only accessibility failures
  and broken layout are `blocking`.

The merge gate (stage 5) waits for every review comment the PR's paths require.

## 3. Model by risk

`create_session` gets `model` from the PR's risk label:

| Stage | risk:low | risk:normal | risk:high |
|---|---|---|---|
| Intake | sonnet | sonnet | sonnet |
| Code review, UI review | sonnet | opus | opus |
| Security review | - | opus | opus |
| Spec, implement, evaluator | unchanged (session default) | | |

If the risk label is missing, use the `risk:high` column.

## Out of scope

GitHub issues as the input queue; keeping the builder session across review rounds (fresh sessions per
stage stay).

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | owner types `/factory add CSV export to dossiers` | dispatcher runs | the first session started has title `factory: <slug> - intake` and model `sonnet`; no spec session exists yet | evaluator |
| AC-2 | intake answered `GO` | dispatcher's next status | spec session starts and its prompt contains the intake scope paragraph | evaluator |
| AC-3 | intake answered `NEEDS-INFO` | status | no spec session starts; board card shows `waiting: intake questions` | evaluator |
| AC-4 | intake answered `REJECT` | status | board card closes with the reason; no further session starts | evaluator |
| AC-5 | intake proposed `normal`, PR opened with `risk:low` | steward labels | label ends as `risk:normal` | evaluator |
| AC-6 | implementing PR changes `backend/arp/api/auth.py` and is green | stage 4 starts | three sessions start: code review, security review, plus evaluator if rows exist; security review posts `Security review (factory)` | evaluator |
| AC-7 | PR changes `frontend/src/pages/X.tsx` only | stage 4 starts | code review and UI review start; no security review | evaluator |
| AC-8 | PR changes only `backend/arp/bi/*.py` | stage 4 starts | only code review (plus evaluator); no security or UI review | evaluator |
| AC-9 | `risk:low` PR | code review starts | its session model is `sonnet` | evaluator |
| AC-10 | `risk:high` PR, or no risk label | code review starts | its session model is `opus` | evaluator |
| AC-11 | security review comment missing on a PR that needs one | merge gate | no merge button offered; owner told `waiting: Security review` | evaluator |

Must not change: max 3 agent PRs in flight; merge only via the owner's `Approve`; holdout never
attached outside test-writer sessions; three-round fix limit (each also covered by existing steward text).
