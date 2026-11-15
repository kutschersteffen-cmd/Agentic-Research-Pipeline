# Faster PR checks: hidden tests and backend tests split, full hidden suite after merge (`holdout-faster-runs`)

Status: draft for owner approval, 15 Nov 2026. Size L, delivered as 4 PRs (see Slices). Proposed risk:
`risk:high` for the two workflow PRs (`.github/workflows/**`), `risk:normal` for the rule PR, the holdout PR
is in the private holdout repo. Phase 1 only; phase 2 (merge queue) is its own feature, `holdout-merge-queue`.

## Decisions for the owner (open)

1. **When the full hidden suite runs on `main`.** Recommended: after **every** merge (about 35 to 45 min,
   blocks no PR) **and** nightly. The alternative is nightly only. Why every merge: a post-merge run names
   the merge that broke an older feature, so a `Revert <sha>` PR can be opened within about an hour. A
   nightly-only failure covers all of a day's merges, cannot say which one broke it, and today only opens an
   issue. Cost: 6 extra machines for about 30 min per merge, which never delays a PR check.
2. **One re-run before a revert is proposed.** Default: when the hidden suite fails on `main`, its failed
   parts run once more; only a second failure opens the `Revert <sha>` PR. This keeps a one-off timeout from
   asking you to revert a good merge, and adds about 25 min before the revert PR appears.
3. **Revert PRs stay `risk:high`**, so you merge them on GitHub (as today); the dispatcher tells you when one
   is open. They cannot use the merge button: CI does not start on PRs opened by the Actions token.
4. **One GitHub setting to check once** (only you can see it): Settings → Branches → rule for `main` →
   "Require branches to be up to date before merging". If it is ticked, untick it; otherwise GitHub itself
   blocks the docs-only exception you approved (decision 5 below). Nothing else in GitHub settings changes:
   the required check names stay the same.

## Owner decisions taken (15 Nov 2026)

1. **Docs-only exception to "not behind main": approved** (button, dispatcher session, 15 Nov 2026). Allowlist
   `docs/superpowers/**`, `docs/adr/**`, `docs/handoffs/**`, `docs/FACTORY_RETRO_LOG.md`. Not on it, because
   the app reads them at run time: `docs/decision-studio/example-framework/*.csv`,
   `docs/transition_barrier/RULE_BOOK.md`.
2. **Direction** (owner's pasted blueprint, 15 Nov 2026): move work out of the critical path, run only what
   is needed on a PR, defer heavy and hidden suites to post-merge or nightly with rollback or alerting, split
   and cache what remains. Targets: per commit under 5 min, merge gate 10 to 15 min, nightly 30 to 60+ min.
   How this repo maps it, and where it deviates, is in "Blueprint mapping" below.
3. **What must be green before a PR merges: "Own rows only, full suite nightly"** (button, dispatcher session,
   15 Nov 2026, about 20:10 UTC). A PR merges with the normal CI checks and its own hidden rows (`Spec:` /
   `Rows:`) green. The full hidden regression suite is not a pre-merge gate; it runs on `main`, and a failure
   there leads to a revert PR or an alert.
4. **Who starts a merge-gate run: "The dispatcher, automatically"** (button, same session). Phase 1 has no
   pre-merge full run, so this applies to phase 2: the merge queue is filled by the dispatcher, with no extra
   tap for the owner.
5. **Backend tests split over 4 machines under the same check name `Backend (lint + tests)`: approved**
   (button, same session). Target for the whole PR check: about 12 to 15 minutes, not the blueprint's 5 (see
   "Blueprint mapping").
6. **Timing: "Phase 1 now, merge queue after 27 Nov"** (button, same session). Phase 1: splitting, own rows
   per push, caching, the docs-only exception. Phase 2 (`holdout-merge-queue`): GitHub merge queue, a repo
   setting only the owner can change, a new merge-button flow.

## Why

Six showcase fix PRs plus the workbench and cockpit PRs are in flight for the 27 Nov 2026 showcase. Each push
to a PR waits for the "Holdout acceptance" check, which runs all about 1,170 hidden rows on one machine:
1 h 40 min to 2 h 35 min. A push cancels the run for the older commit, and every merge into `main` puts the
other open PRs "behind main", so they merge `main` in and wait again. A day's merges can cost each open PR
several 2-hour waits.

After this change a PR push is checked in about 12 to 15 minutes, every hidden row still runs on every merge,
and a merge that breaks an older feature produces a revert PR within about 70 minutes.

## Today (measured 15 Nov 2026)

| Check | Workflow | Time | Notes |
|---|---|---|---|
| Holdout acceptance | `holdout.yml` | 1 h 45 min to 2 h 35 min | One job. Setup about 4 min (checkout, pip from cache, `npm ci`, Playwright with `--with-deps`, `e2e_stack.sh up`), then `python .holdout/run.py [--spec <slug> [--rows ...]]`: `regression/` always plus `specs/<slug>/`. About 32 groups, one pytest process each, 600 s per-test timeout. No job timeout. |
| Backend (lint + tests) | `ci.yml` | about 26 min | Setup about 4 min, `pytest -q --cov=arp` about 22 min on one machine, then diff coverage (changed lines >= 80 %). |
| E2E (browser) | `ci.yml` | about 8 min | Setup about 3.5 min, browser tests about 4.5 min. |
| Container image scan (Trivy) | `ci.yml` | about 10 min | Builds both images (backend about 7 min). |
| Frontend, secret scan, audits | `ci.yml` | under 3 min | |

- Skips that already exist in `holdout.yml`: a title-only edit when the commit already passed; PRs whose files
  are all under `docs/` or `.claude/` or are `*.md`; no `HOLDOUT_TOKEN` (warns, passes).
- Nightly at 02:17 UTC `holdout.yml` runs `run.py` with no arguments on `main`; a failure opens an issue
  `Nightly Holdout failed <date>`. No revert.
- `main-guard.yml` watches only the `CI` workflow. When a push-event CI run on `main` fails, it opens
  `Revert <short>: CI red on main` (`risk:high`) for that commit, but only if the commit is still the tip of
  `main` ("main moved past <short>; nothing to do" otherwise). While a `revert-*` PR is open it comments on
  that PR instead. `revert_red_main.sh` branches from the failing commit itself, so it can revert a commit
  that is no longer the tip.
- Nightly mutation check (`mutation.yml`, 03:23 UTC, and on `risk:high` PRs): unchanged by this spec.

## Blueprint mapping

| Blueprint stage | This repo after phase 1 | Time |
|---|---|---|
| **PR check, every commit** (lint, types, unit, smoke) | `ci.yml` as today but backend tests on 4 machines; E2E browser tests; Trivy; **Holdout acceptance runs only the PR's own rows** (`Spec:`/`Rows:`); PRs without a `Spec:` line run no hidden rows | about 12 to 15 min (slowest: backend about 10 to 12, Holdout own rows about 6 to 14, Trivy about 10, E2E about 8) |
| **Merge gate** (queued, full integration) | Phase 2 (`holdout-merge-queue`). In phase 1 the only pre-merge full run is opt-in: label `holdout:full` (required when re-landing a reverted PR) | about 35 to 45 min, opt-in |
| **Post-merge / nightly** (hidden suites, full E2E) | Full hidden suite on 6 machines on every push to `main` (decision 1) and nightly; a second failure on `main` opens `Revert <sha>: hidden tests red on main` | about 35 to 45 min, blocks nothing |
| Mutation check | unchanged (nightly and `risk:high` PRs) | |

Where this repo deviates from the blueprint, and why:

- **Not under 5 minutes per commit.** The E2E browser job takes about 8 min and Trivy about 10 min on their
  own, and every job pays about 3 to 4 min of setup. Getting under 5 would need (next step up, not in this
  spec): a prebuilt CI image with dependencies installed, Trivy image builds cached or moved to post-merge,
  the E2E job split, and selecting only the backend tests a change touches.
- **Own hidden rows stay before the merge.** The hidden tests are the factory's acceptance gate: the builder
  never sees them, so the PR's own rows are the only proof that the PR does what its spec says. They stay a
  required pre-merge check. Only the regression rows of other, already merged specs move after the merge.
- **No "affected tests only" selection** in phase 1. A wrong mapping would silently skip tests; hidden tests
  also drive the real UI, so a frontend-only change can break any of them.
- **No cross-job "abort early".** Jobs run in parallel, so cancelling the others when lint fails saves
  machine time but not waiting time. Lint already runs first inside each job.

What can reach `main` unseen, and for how long:

- A change that breaks an older feature's hidden rows (rows not in the PR's own spec): from the merge until
  the post-merge run fails twice (about 35 to 45 min plus about 25 min for the re-run) and the owner merges the
  revert PR. Other PRs merged in that window build on it; the revert targets the named merge, and if it does
  not apply cleanly, Main guard opens an issue instead.
- A PR without a `Spec:` line (fix PRs, workflow PRs) runs no hidden rows before the merge at all; same window.
- With nightly only (the alternative in decision 1): up to about 24 hours, and an issue instead of a revert PR.

## Goals

1. A PR push gets its `Holdout acceptance` result from its own rows only, in at most 15 min for a spec of up
   to 60 rows.
2. `Backend (lint + tests)` finishes in at most 12 min, on 4 machines, with the same tests, lint and diff
   coverage rule as today.
3. Every hidden row still runs: on every push to `main` (if decision 1 is taken as recommended) and nightly,
   split over 6 machines, in at most 45 min.
4. A hidden-suite failure on `main` that repeats on a re-run produces a `Revert <sha>` PR for the merge that
   ran it, even when `main` has moved on.
5. A PR behind `main` only by allowlisted docs commits can be offered for merge without merging `main` in.
6. Required check names stay `Holdout acceptance` and `Backend (lint + tests)`; the owner changes no
   required-check setting.

Anti-goals (a failure even if everything is faster):

- A hidden or backend test silently stops running (lost in the split). Each split run prints how many tests
  ran against how many exist and fails when they differ.
- A failed or cancelled part shows as a green `Holdout acceptance` or `Backend (lint + tests)`.
- A builder session sees hidden test code or names beyond what it sees today.
- An open fix PR is blocked or turned red by the roll-out before 27 Nov.

## Non-goals

- Phase 2, `holdout-merge-queue`: GitHub merge queue, `merge_group` triggers in `holdout.yml` and `ci.yml`, the
  dispatcher queuing PRs automatically (owner decision 4), the new merge-button flow.
- Making the per-commit check faster than about 12 min (see "next step up").
- Splitting or speeding up E2E (browser), Trivy, golden-set or mutation jobs.
- Selecting tests by changed files ("affected tests").
- Changing which hidden rows exist, the 600 s per-test timeout or the `AC-n pass|fail` output.
- Making revert PRs mergeable by the merge button.

## Approaches considered

1. **Every push runs everything, split over 6 machines** (about 35 to 45 min per push). Coverage unchanged,
   nothing reaches `main` unseen. Rejected by owner decision 3: still well above the 10 to 15 min target, and
   about 2.5 machine-hours per push.
2. **Own rows per push, full suite once when the PR is ready** (agent adds a label). Pre-merge coverage kept,
   but one more step per PR and a second long wait right before every merge. Rejected by owner decision 3; kept
   as the opt-in `holdout:full` label for re-lands.
3. **Own rows per push, full suite after merge and nightly, revert on failure** (chosen, owner decision 3).
   Fastest PR check; the cost is the unseen window above.

## Design

### Hidden-test runner flags (holdout repo; interface only)

Built by a test-writer-style session that has the holdout repo attached and has not worked on the app side.
The app builder never attaches the holdout repo and only calls these flags.

| Flag | Behaviour |
|---|---|
| `--no-regression` | Runs only the rows `--spec <slug>` (and `--rows`) select; nothing from the regression suite. Without `--spec` it runs nothing, prints `holdout: nothing to run` and exits 0. |
| `--shard K/N` | Runs only part K of N (1-based, N from 1 to 8) of what `run.py` runs with no `--spec` today (the full suite). The N parts are disjoint and together are the whole suite; the split is the same on every run of the same holdout commit; new groups and rows land in some part automatically. The longest part takes at most 1.3 times the average part. Invalid values (`0/6`, `7/6`, `1/0`, `x/6`) exit 2 with a message starting `invalid --shard`. |
| `--count` | Prints one line `holdout rows: <n>`, the number of rows the other flags select, and runs nothing. |

Unchanged: plain `run.py`, `--spec`, `--rows`, the output lines (`<slug> AC-n: pass|fail`, `<group>: done in N
s`), exit 1 when any row fails, the 600 s per-test timeout. How the runner balances its parts (stored timings,
row counts) is the holdout session's choice.

### `holdout.yml`

- **Triggers:** as today plus `push` to `main`, and `labeled` / `unlabeled` on pull requests (for
  `holdout:full`).
- **PR, no `holdout:full` label:** one test job runs
  `run.py --spec <slug> [--rows ...] --no-regression`. Without a `Spec:` line it starts no app, prints
  `Holdout acceptance: no Spec: line; hidden rows run on main after merge.` and succeeds. Existing skips (title
  edit, docs-only, no token) stay as they are.
- **PR with `holdout:full`, push to `main`, nightly, manual run:** 6 shard jobs named `Holdout shard K/6`,
  each `run.py --shard K/6`; a PR with `holdout:full` also runs its own-rows job.
- **Aggregate job named exactly `Holdout acceptance`** (the required check), runs always, needs every test job.
  Success only when every needed job succeeded or was skipped by the existing skip rules; failure when any
  failed or was cancelled. For a full run it prints `holdout rows: <sum of the shards' --count> of <run.py
  --count>` and fails when the two differ.
- **Concurrency:** PRs as today (one run per PR, a push cancels the older one; an edit queues). Push runs on
  `main` get one group per commit and are never cancelled, so each merge has its own result.
- **Timeouts:** own-rows job 45 min, shard 60 min, so a hung test fails the check instead of running for hours.
- **Caching:** the Playwright browser download is cached (key: installed Playwright version); system
  dependencies still install. pip and npm caches stay as they are.
- **Drill:** a manual run with input `drill_fail: true` runs no tests, fails `Holdout shard 1/6`, and is named
  `Holdout drill` (`run-name`), so the revert path can be tested at any time without breaking `main`.
- The nightly issue on failure stays.

### `main-guard.yml`

- Also watches the `Holdout acceptance` workflow on `main`.
- A failed push-event Holdout run on attempt 1: re-run its failed jobs once and stop (decision 2).
- A failed push-event Holdout run on attempt 2 or later: open `Revert <short>: hidden tests red on main`
  (`risk:high`) for that run's commit **even if `main` has moved past it**, body: failed job names, the
  `<slug> AC-n: fail` lines from the failed jobs' logs, the run link. If the revert does not apply, open an
  issue `Hidden tests red on main at <short> (not reverted automatically)`. The existing rules stay: no second
  revert while a `revert-*` PR is open (comment on it instead), never revert a revert.
- A failed `Holdout drill` run on attempt 2: same, but a **draft** PR titled `[drill] Revert <short>: hidden
  tests red on main`, for the evaluator to check and close.
- The `CI` path is unchanged, including "main moved past <short>; nothing to do".

### `ci.yml`, backend

- 4 jobs `Backend shard K/4` each run lint, the API contract check and part K of the pytest suite, with the
  same service containers and coverage collection as today. The split is by test file or test, the builder's
  choice, with no new dependency unless it is a pinned test plugin; parts should take about the same time.
- Aggregate job named exactly `Backend (lint + tests)`, runs always: success only when all 4 succeeded;
  combines the 4 coverage results and runs the same diff-coverage rule (changed lines >= 80 %, PRs only);
  prints `backend tests: <sum of tests selected by the shards> of <tests collected unsplit>` and fails when
  they differ.
- The Chromium download for the deck fit checks is cached as in `holdout.yml`.

### Docs-only "not behind main" check

`.github/scripts/main_ahead_docs_only.sh` (run by the agent in its PR branch, after `git fetch origin main`):

- prints `docs-only`, exit 0, when every file changed on `origin/main` since the merge base with `HEAD` matches
  the allowlist (owner decision 1) and `git merge-tree --write-tree HEAD origin/main` reports no conflict;
- prints `code: <path>` (first file outside the allowlist), exit 1;
- prints `conflict`, exit 1, when the merge would conflict;
- `--selftest` builds a throwaway repo, checks all three cases and the two run-time docs files, prints
  `selftest ok`; the `PR guards` workflow runs it.

### Rules (`.claude/CLAUDE.md` merge button, steward skill, factory skill)

- **Merge button** asks `Merge PR #<n>?` when: required checks green on the current head (they now mean "own
  hidden rows green"), mergeable, no review thread waiting on the agent, and either not behind `main` or
  `main_ahead_docs_only.sh` prints `docs-only`. If GitHub refuses the merge as out of date, merge `origin/main`
  in and ask again after green. When a `Revert <sha>: hidden tests red on main` PR is open, the question adds
  one line: `main has an open hidden-test revert: #<n>`. It does not block the merge.
- **Steward skill:** when a post-merge revert names your merge, the revert lands first; then a new PR
  re-applies the change with the fix, keeps the `Spec:` line and carries the `holdout:full` label, so the full
  suite runs before it merges. The fix-round count of section 2 applies to it.
- **Factory skill:** `/factory` lists any open `Revert <sha>: hidden tests red on main` PR at the top of its
  status, with the merge it reverts, and tells the owner it waits for them on GitHub.

### Roll-out without blocking open PRs (before 27 Nov)

1. Holdout PR (runner flags) merges first. Old flags and output are unchanged, so open PRs keep working.
2. Workflow PR (`holdout.yml`, `main-guard.yml`, the docs-only script and its self-test). Its own
   `pull_request` run already uses the new `holdout.yml`, which proves the green path. A throwaway branch off
   it, whose shard step is changed to fail, proves the red path and is closed unmerged. Merged at a quiet time;
   right after, a manual `drill_fail` run proves the revert path. Open PRs pick up the new workflow at their
   next push or `main` merge; they are not re-run.
3. Backend-split PR (`ci.yml`), proved the same way. Independent of 2; if it misbehaves, revert only it.
4. Rule PR (`.claude/CLAUDE.md`, steward, factory skills), after 2.

## Slices

| # | PR | Repo | Risk | Rows |
|---|---|---|---|---|
| 1 | Runner flags `--no-regression`, `--shard`, `--count` (test-writer-style session) | holdout | n/a | AC-1 to AC-5 |
| 2 | `holdout.yml`, `main-guard.yml`, docs-only script + self-test in `pr-guards.yml` | app | `risk:high` | AC-6 to AC-20 |
| 3 | `ci.yml` backend split over 4 machines | app | `risk:high` | AC-21 to AC-26, AC-30 |
| 4 | Merge-button, steward and factory rules | app | `risk:normal` | AC-27 to AC-29 |

Each app PR description puts `Spec: holdout-faster-runs` and its `Rows:` line. This spec has no `holdout`
rows: the checks are about CI itself, so they are `unit` (self-tests) or `evaluator` (an agent reads the PR's
check runs, timings and logs on GitHub).

## Left to the builder (defaults chosen here)

- Number of hidden shards: 6; backend shards: 4. One constant each in the workflow.
- "Idle queue" in the timing rows: the run's jobs started within 2 min of the run being created.
- Job and step names other than the two required checks, `Holdout shard K/6` and `Backend shard K/4`.
- How coverage files travel between jobs (artifacts) and how backend tests are split.
- Exact wording of issue bodies and PR bodies beyond the titles fixed here.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The holdout repo at the slice-1 commit | `python run.py --count` runs | It prints exactly one line `holdout rows: <n>`, where n is the number of `AC-n` lines a plain `python run.py` prints, and runs no test | unit (holdout repo) |
| AC-2 | Same | `run.py --shard K/6` runs for K = 1 to 6 | The six sets of printed `AC-n` lines are pairwise disjoint and their union equals the set a plain `run.py` prints; the six `--shard K/6 --count` values sum to the `--count` of AC-1 | unit (holdout repo) |
| AC-3 | Same | `run.py --shard 0/6`, `--shard 7/6`, `--shard 1/0`, `--shard x/6` | Each exits 2 and prints a line starting `invalid --shard`; no test runs | unit (holdout repo) |
| AC-4 | Same | `run.py --spec <slug> --no-regression` runs | Only `<slug> AC-n` lines of that spec are printed (only the `--rows` ones when given); `run.py --no-regression` alone prints `holdout: nothing to run` and exits 0 | unit (holdout repo) |
| AC-5 | Must not change: same | plain `run.py`, `--spec`, `--spec --rows` run | Output line formats and exit codes are as before slice 1 (exit 1 when a row fails, 0 when all pass) | unit (holdout repo) |
| AC-6 | Slice 2 merged; a PR with `Spec: <slug>`, no `holdout:full` label | a commit is pushed | Its Holdout run has exactly one test job plus `Holdout acceptance`; no `Holdout shard` job runs; the log has no row outside `<slug>` | evaluator |
| AC-7 | Same, spec of at most 60 rows, idle queue | the run finishes | `Holdout acceptance` completes at most 15 min after the run started (median of the first 3 such PRs after slice 2) | evaluator |
| AC-8 | Slice 2 merged; a PR with no `Spec:` line and no `holdout:full` label, app files changed | a commit is pushed | `Holdout acceptance` succeeds within 3 min, starts no app, and its log contains `Holdout acceptance: no Spec: line; hidden rows run on main after merge.` | evaluator |
| AC-9 | Slice 2 merged; a PR with `Spec: <slug>` | the label `holdout:full` is added | A new Holdout run starts with the own-rows job and 6 jobs `Holdout shard 1/6` to `Holdout shard 6/6`; `Holdout acceptance` completes at most 45 min after the run started (idle queue) | evaluator |
| AC-10 | Slice 2's throwaway branch, where `Holdout shard 3/6`'s test step exits 1 | the run finishes | `Holdout shard 3/6` is red and `Holdout acceptance` concludes `failure` | evaluator |
| AC-11 | Same branch, `Holdout shard 3/6` cancelled by hand while running | the run finishes | `Holdout acceptance` concludes `failure`, not `success` | evaluator |
| AC-12 | Slice 2 merged | a full run (push to `main`) finishes | The `Holdout acceptance` log has `holdout rows: <a> of <b>` with a = b; when a ≠ b the job fails | evaluator |
| AC-13 | Slice 2 merged; decision 1 as recommended | two PRs merge into `main` within 10 min of each other | Each merge commit gets its own push-event Holdout run with 6 shards; neither is cancelled; each `Holdout acceptance` completes at most 45 min after its run started (idle queue) | evaluator |
| AC-14 | Must not change: slice 2 merged; a PR whose files are all under `docs/` or `.claude/` or are `*.md` | a commit is pushed | `Holdout acceptance` succeeds and no test job starts the app | evaluator |
| AC-15 | Must not change: slice 2 merged | the nightly run (02:17 UTC) fails | An issue `Nightly Holdout failed <date>` is opened, as today | evaluator |
| AC-16 | Slice 2 merged | a manual Holdout run on `main` with `drill_fail: true` fails, attempt 1 | Main guard re-runs its failed jobs once (attempt 2 starts) and opens no PR or issue | evaluator |
| AC-17 | Same | attempt 2 fails | Main guard opens a draft PR titled `[drill] Revert <short>: hidden tests red on main` whose body links the run | evaluator |
| AC-18 | Slice 2 merged; a push-event Holdout run on `main` failed on attempt 2 for merge commit X, and `main` has since moved past X | Main guard runs | A PR `Revert <short X>: hidden tests red on main` with label `risk:high` exists, branch `revert-<short X>`; its body lists the failed jobs, the `AC-n: fail` lines and the run link | evaluator (first real occurrence) |
| AC-19 | Must not change: slice 2 merged; a push-event CI run on `main` fails for a commit that is no longer the tip | Main guard runs | It opens nothing and logs `main moved past <short>; nothing to do`, as today | evaluator (first real occurrence) |
| AC-20 | Slice 2 merged | `bash .github/scripts/main_ahead_docs_only.sh --selftest` runs (also in the `PR guards` workflow) | It prints `selftest ok` after checking: only allowlisted files ahead → `docs-only`, exit 0; a `backend/` file ahead → `code: backend/...`, exit 1; `docs/decision-studio/example-framework/x.csv` ahead → `code: docs/decision-studio/example-framework/x.csv`, exit 1; `docs/transition_barrier/RULE_BOOK.md` ahead → `code: docs/transition_barrier/RULE_BOOK.md`, exit 1; a conflicting change → `conflict`, exit 1 | unit |
| AC-21 | Slice 3 merged; a PR changing backend code | its CI run finishes | It has 4 jobs `Backend shard 1/4` to `Backend shard 4/4` and one `Backend (lint + tests)`; `Backend (lint + tests)` completes at most 12 min after the run started (median of the first 3 such PRs, idle queue) | evaluator |
| AC-22 | Same | the run finishes | The `Backend (lint + tests)` log has `backend tests: <a> of <b>` with a = b; when a ≠ b the job fails | evaluator |
| AC-23 | Slice 3's throwaway branch where one test in shard 2's part fails | the run finishes | `Backend shard 2/4` is red and `Backend (lint + tests)` concludes `failure` | evaluator |
| AC-24 | Must not change: slice 3's throwaway branch adding 20 backend lines no test covers | the run finishes | `Backend (lint + tests)` concludes `failure` with diff-cover's under-80 % message | evaluator |
| AC-25 | Must not change: slice 3's throwaway branch with a ruff error | the run finishes | `Backend (lint + tests)` concludes `failure` | evaluator |
| AC-26 | Slices 2 and 3 merged; a PR with `Spec:` of at most 60 rows, no label, idle queue | a commit is pushed | Every required check on the head is green at most 15 min after the first job started (median of the first 3 such PRs) | evaluator |
| AC-27 | Slice 4 merged; an open `risk:normal` PR, green, whose branch lacks only `main` commits that touch allowlisted docs | the dispatcher checks it | It asks `Merge PR #<n>?` without merging `origin/main` into the branch first, and the question names the head SHA | evaluator (first real occurrence) |
| AC-28 | Slice 4 merged; an open `Revert <sha>: hidden tests red on main` PR | `/factory` runs | Its status starts with that PR's number and the merge it reverts, and says it waits for the owner on GitHub | evaluator |
| AC-29 | Slice 4 merged; a merge reverted by a hidden-test revert PR | the builder re-lands the change | The new PR carries `Spec: <slug>` and the label `holdout:full`, and its Holdout run has 6 shard jobs | evaluator (first real occurrence) |
| AC-30 | Slices 2 and 3 merged | the PR check list of any PR is read | It contains exactly one check named `Holdout acceptance` and one named `Backend (lint + tests)`, and a PR with both green is mergeable without any change to branch protection | evaluator |

Must not change: the skips in `holdout.yml` (AC-14), the nightly issue (AC-15), Main guard's CI path (AC-19),
the diff-coverage and lint rules (AC-24, AC-25), the runner's output and exit codes (AC-5).
