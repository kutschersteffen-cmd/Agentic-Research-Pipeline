# Faster PR checks: own hidden rows per push, full hidden suite nightly on 6 machines, backend tests on 4 (`holdout-faster-runs`)

Status: approved by the owner (button), 15 Nov 2026. Size L, delivered as 4 PRs (see Slices). Risk: `risk:high` for
the two workflow PRs (`.github/workflows/**`), `risk:normal` for the rule PR; the runner PR is in the private
holdout repo. Phase 1 only; phase 2 (merge queue) is its own feature, `holdout-merge-queue`.

## For the owner: what you accept, and one setting to check

- **What can reach `main` unchecked, and for how long.** A merge that breaks an older feature's hidden rows
  (rows that are not in the PR's own spec) is first noticed by the next nightly run: up to about 24 hours
  (02:17 UTC plus about 45 min). A PR without a `Spec:` line (fix PRs, workflow PRs) runs no hidden rows
  before the merge at all. The alert is an issue, not a revert PR: a nightly run covers a whole day's merges,
  so it cannot say which merge broke it. The issue lists the failing rows and the merges since the last green
  night; the dispatcher shows it first and a fix PR (or a revert by hand) follows.
- **Before the showcase:** when you tell the dispatcher "showcase freeze", it starts one manual full run on
  `main` (about 45 min) and tells you the result, so the showcase build has been checked in full.
- **One GitHub setting to look at once** (only you can see it): Settings → Branches → rule for `main` →
  "Require branches to be up to date before merging". If it is ticked, GitHub itself blocks the docs-only
  exception you approved; untick it to use the exception. Nothing else in GitHub settings changes: the
  required check names stay the same.

## Owner decisions (15 Nov 2026)

1. **Docs-only exception to "not behind main": approved** (button, dispatcher session). Allowlist
   `docs/superpowers/**`, `docs/adr/**`, `docs/handoffs/**`, `docs/FACTORY_RETRO_LOG.md`. Not on it, because
   the app reads them at run time: `docs/decision-studio/example-framework/*.csv`,
   `docs/transition_barrier/RULE_BOOK.md`.
2. **Direction** (owner's pasted blueprint): move work out of the critical path, run only what is needed on a
   PR, defer heavy and hidden suites to post-merge or nightly with rollback or alerting, split and cache what
   remains. Targets: per commit under 5 min, merge gate 10 to 15 min, nightly 30 to 60+ min. The mapping and
   where this repo deviates are in "Blueprint mapping".
3. **Before a PR merges: "Own rows only, full suite nightly"** (button, dispatcher session, about 20:10 UTC).
   A PR merges with the normal CI checks and its own hidden rows (`Spec:` / `Rows:`) green. The full hidden
   suite is not a pre-merge gate.
4. **Who starts a merge-gate run: "The dispatcher, automatically"** (button, dispatcher session). Phase 1 has
   no merge gate, so this applies to phase 2: the dispatcher fills the merge queue, with no extra tap.
5. **Backend tests over 4 machines under the same check name `Backend (lint + tests)`: approved** (button,
   dispatcher session). Target for the whole PR check about 12 to 15 min, not the blueprint's 5.
6. **Timing: "Phase 1 now, merge queue after 27 Nov"** (button, dispatcher session).
7. **The full hidden suite on `main` runs nightly only**, not after every merge (button, this session). A
   post-merge run per merge was offered so a failure could name its merge and open a revert PR; the owner
   chose nightly only, with an issue as the alert.
8. **A part that runs into its time limit opens the issue: "Yes, open the issue"** (button, dispatcher session,
   16 Nov 2026). GitHub marks such a job `cancelled`, not `timed_out` (seen on the slice-2 proof PR #516), so a
   `cancelled` job whose check run says it exceeded its maximum execution time counts as `timed_out` and opens the
   issue. A run cancelled by hand still opens none.

## Why

Six showcase fix PRs plus the workbench and cockpit PRs are in flight for the 27 Nov 2026 showcase. Each push
to a PR waits for the "Holdout acceptance" check, which runs all about 1,170 hidden rows on one machine:
1 h 40 min to 2 h 35 min. A push cancels the run for the older commit, and every merge into `main` puts the
other open PRs behind `main`, so they merge `main` in and wait again. A day's merges can cost each open PR
several 2-hour waits.

After this change a PR push is checked in about 12 to 15 minutes, every hidden row still runs every night
(and on demand) in about 45 minutes, and PRs behind `main` only by planning docs can merge without waiting.

## Today (measured 15 Nov 2026)

| Check | Workflow | Time | Notes |
|---|---|---|---|
| Holdout acceptance | `holdout.yml` | 1 h 45 min to 2 h 35 min | One job. Setup about 4 min (checkout, pip from cache, `npm ci`, Playwright with `--with-deps`, `e2e_stack.sh up`), then `python .holdout/run.py [--spec <slug> [--rows ...]]`: the regression suite always, plus `specs/<slug>/`. About 32 groups, 600 s per-test timeout, no job timeout. |
| Backend (lint + tests) | `ci.yml` | about 26 min | Setup about 4 min, `pytest -q --cov=arp` about 22 min, then diff coverage (changed lines >= 80 %). |
| E2E (browser) | `ci.yml` | about 8 min | Setup about 3.5 min, browser tests about 4.5 min. |
| Container image scan (Trivy) | `ci.yml` | about 10 min | Builds both images. |
| Frontend, secret scan, audits | `ci.yml` | under 3 min | |

- `holdout.yml` skips today: a title-only edit when the commit already passed; PRs whose files are all under
  `docs/` or `.claude/` or are `*.md`; no `HOLDOUT_TOKEN` (warns, passes). Triggers: PR `opened`,
  `synchronize`, `reopened`, `edited`; nightly 02:17 UTC; manual.
- A failed nightly or manual run opens an issue `Nightly Holdout failed <date>`. No revert.
- `main-guard.yml` watches only the `CI` workflow; unchanged by this spec.
- Nightly mutation check (`mutation.yml`): unchanged.

## Blueprint mapping

| Blueprint stage | This repo after phase 1 | Time |
|---|---|---|
| **PR check, every commit** | `ci.yml` with backend tests on 4 machines; E2E; Trivy; **Holdout acceptance runs only the PR's own rows**; a PR without `Spec:` runs no hidden rows | about 12 to 15 min (backend about 10 to 12, own hidden rows about 6 to 14, Trivy about 10, E2E about 8) |
| **Merge gate** | Phase 2 (`holdout-merge-queue`). In phase 1 only opt-in: a `Holdout: full` line in the PR body (required for fixes of a nightly failure) | about 35 to 45 min |
| **Nightly / on demand** | Full hidden suite on 6 machines; a failure opens one issue with the failing rows and the suspect merges | about 35 to 45 min |
| Mutation check | unchanged (nightly and `risk:high` PRs) | |

Where this repo deviates from the blueprint, and why:

- **Not under 5 minutes per commit.** E2E takes about 8 min and Trivy about 10 min on their own, and every job
  pays about 3 to 4 min of setup. Next step up (not in this spec): a prebuilt CI image with dependencies
  installed, Trivy image builds cached or moved to nightly, the E2E job split, and running only the backend
  tests a change touches.
- **Own hidden rows stay before the merge.** The hidden tests are the factory's acceptance gate: the builder
  never sees them, so the PR's own rows are the only proof that the PR does what its spec says. Only the rows
  of other, already merged specs move to the nightly run.
- **No automatic rollback.** With nightly only (decision 7) a failure cannot be pinned to one merge, so the
  alert is an issue. Phase 2's merge queue brings the full suite back before the merge.
- **No "affected tests only".** A wrong mapping would skip tests silently; hidden tests drive the real UI, so a
  frontend-only change can break any of them.
- **No cross-job "abort early".** Jobs run in parallel, so cancelling the others when lint fails saves machine
  time, not waiting time. Lint already runs first inside each job.

## Goals

1. A PR push gets `Holdout acceptance` from its own rows only: median of the first 3 such PRs at most 15 min,
   none over 20 min, for a spec of up to 60 rows.
2. `Backend (lint + tests)` on 4 machines: median of the first 3 PRs at most 12 min, none over 16 min, with
   the same tests, lint, API contract check and diff-coverage rule as today.
3. Every hidden row still runs nightly and on demand, split over 6 machines, in at most 45 min.
4. A failed nightly run opens exactly one issue that names the failing rows and the merges since the last
   green nightly, and the next green full run closes it.
5. A PR behind `main` only by allowlisted docs commits can be offered for merge without merging `main` in.
6. Required check names stay `Holdout acceptance` and `Backend (lint + tests)`.

Anti-goals (a failure even if everything is faster):

- A hidden or backend test silently stops running in the split. Every split run checks that its parts are
  exactly 1 to N and that their counts add up to the whole, and fails otherwise.
- A failed, timed-out or cancelled part shows as a green `Holdout acceptance` or `Backend (lint + tests)`.
- A builder sees more of the hidden tests than today: logs and issue bodies carry only result lines,
  `<group>: done in N s`, `holdout shard: ...`, `holdout rows: ...`, `holdout commit: ...` and
  `holdout: nothing to run`; no artifact holds hidden-test content.
- An open PR is blocked or turned red by the roll-out other than by its own rows.

## Non-goals

- Phase 2, `holdout-merge-queue`: GitHub merge queue, `merge_group` triggers in `holdout.yml` and `ci.yml`, the
  dispatcher queuing PRs automatically (decision 4), the new merge-button flow.
- A full hidden run after every merge, and automatic revert PRs for hidden-test failures (decision 7).
  `main-guard.yml` is unchanged.
- Making the per-commit check faster than about 12 min; splitting E2E, Trivy, golden-set or mutation jobs.
- Selecting tests by changed files.
- Changing which hidden rows exist, the 600 s per-test timeout or the runner's output lines.

## Approaches considered

1. **Every push runs everything, split over 6 machines** (about 35 to 45 min per push). Coverage unchanged.
   Rejected by decision 3: above the 10 to 15 min target and about 2.5 machine-hours per push.
2. **Own rows per push, full suite once when the PR is ready.** Keeps pre-merge coverage but adds a step and
   a second long wait before every merge. Rejected by decision 3; kept as the opt-in `Holdout: full` line.
3. **Own rows per push, full suite after every merge and nightly, revert PR on failure.** Offered; the owner
   chose nightly only (decision 7).
4. **Own rows per push, full suite nightly, issue on failure** (chosen).

## Design

### Hidden-test runner flags (holdout repo; interface only)

Built by a test-writer-style session that has the holdout repo attached and has not worked on the app side.
The app builder never attaches the holdout repo and only calls these flags.

| Flag | Behaviour |
|---|---|
| `--no-regression` | With `--spec <slug>` (and optional `--rows`): runs only those rows, nothing from the regression suite. Without `--spec`, or when the slug has no hidden rows: runs nothing, prints `holdout: nothing to run`, exits 0. |
| `--shard K/N` | Runs only part K of N (1-based, N from 1 to 8) of the full suite, which is what `run.py` runs without `--spec` today. The N parts are disjoint and together are the whole suite; the split is the same on every run of the same holdout commit; new rows land in some part automatically. The longest part takes at most 1.3 times the average part. Invalid values (`0/6`, `7/6`, `1/0`, `x/6`) and `--shard` combined with `--spec` or `--no-regression` exit 2 with a line starting `invalid --shard`. |
| `--count` | Prints one line `holdout rows: <n>`, the number of rows the other flags select, and runs nothing. |
| `--list` | Prints one row ID per line for the rows the other flags select, and runs nothing. A row ID is the row's identity exactly as it appears in that row's result line (the line that ends in pass or fail). |
| (with `--shard K/N`) | Before any result line, prints `holdout shard: K/N` with the K and N it was given. |

**What "the full suite" covers.** `--shard` splits exactly what a plain `run.py` runs today (the regression
suite). Today a merged spec's rows run after its merge only if they are part of that suite, and this spec does
not change that. The slice-1 PR states in its description how a merged spec's rows join the regression suite;
if they do not today, slice 1 adds that step, because after this change PRs no longer run the regression suite
and the nightly run is the only place older rows run.

Unchanged: plain `run.py`, `--spec`, `--rows`, the existing result lines (one per row, ending in pass or fail;
`holdout.yml`'s header calls them `AC-n pass|fail`, the steward skill quotes a failure as `<slug> AC-n: fail`),
the `<group>: done in N s` lines, exit 1 when any row fails and 0 when all pass, the 600 s per-test timeout. The
slice-1 PR states the exact result-line format in its description; this spec calls those lines "result lines".
How the parts are balanced (stored timings, row counts) is the holdout session's choice.

### `holdout.yml`

- **Triggers:** unchanged (PR `opened`, `synchronize`, `reopened`, `edited`; nightly 02:17 UTC; manual). No
  label trigger: the opt-in is a body line, so label changes start nothing and cancel nothing.
- **The opt-in line:** a PR body line that is exactly `Holdout: full` (case-sensitive, trailing whitespace
  allowed, nothing else on the line). The words inside a sentence or after other text do not count.
- **Holdout commit:** the first job resolves the holdout repo's current commit once; every job that checks out
  the holdout repo uses that commit, so all parts of a run use the same split.
- **PR without the opt-in line:** one test job. Without a `Spec:` line it starts no app, prints
  `Holdout acceptance: no Spec: line; hidden rows run nightly on main.` and succeeds. With a `Spec:` line it
  starts the app as today, then runs `run.py --spec <slug> [--rows ...] --count` and
  `run.py --spec <slug> [--rows ...] --no-regression`; a slug with no hidden rows prints
  `holdout: nothing to run` and succeeds. Existing skips (title-only edit, docs-only, no token) stay.
- **PR with the opt-in line, nightly run, manual run:** 6 shard jobs `Holdout shard K/6`, each
  `run.py --shard K/6`. Each passes to the aggregate the K/N from the runner's own `holdout shard: K/N` line and
  its result lines (row ID plus pass or fail). A PR with the opt-in line and a `Spec:` line also runs its own-rows job;
  without `Spec:` only the shards run.
- **Aggregate job named exactly `Holdout acceptance`** (the required check), runs always, needs every other
  job. Success only when the setup job (skip checks, holdout commit) succeeded or took one of the existing skips,
  and every job expected for this run type succeeded: the own-rows job for a PR with a `Spec:` line; shards 1 to
  6 for a PR with the opt-in line and for nightly and manual runs. Jobs not expected for the run type are
  ignored. Anything else, including a failed, timed-out, cancelled or unexpectedly skipped expected job, is
  failure. For a full run it checks out the same holdout commit, runs `run.py --list`
  (no app needed), prints `holdout commit: <sha>` and `holdout rows: <rows reported by the shards> of <rows
  in --list>`, and fails with `holdout shards: missing <K>/6` for each K from 1 to 6 no shard reported, with
  `holdout rows: duplicate <row ID>` for a row reported twice, and with `holdout rows: <a> of <b>` when the
  reported rows are not exactly the `--list` rows.
- **Issue on failure:** a nightly run, or a manual run on `main`, opens exactly one issue
  `Nightly Holdout failed <date>`, from the aggregate job, when a job's check-run conclusion (Checks API) is
  `failure` or `timed_out`, where a `cancelled` job whose check run says it exceeded its maximum execution time
  counts as `timed_out` (owner decision 16 Nov 2026), or when the aggregate's completeness check fails. A run that was itself cancelled by hand, a manual run on
  another branch, and PR runs open no issue. Body: the failed result lines,
  any completeness lines (`holdout shards: missing ...`, `holdout rows: ...`) with the shards that reported no
  result, the holdout commit, the `main` commits since the last green nightly (`<sha>..<sha>`, one line per merge with
  its PR title) and the run link. "Last green nightly" is the newest `schedule` run of `holdout.yml` on `main`
  with conclusion `success` in the last 30 days; if there is none, the body says
  `no green nightly in 30 days` and lists the last 30 merges.
- **Closing:** a full run on `main` (nightly or manual) that succeeds closes every open `Nightly Holdout failed`
  issue with a comment linking the run.
- **Drill:** a manual run with input `drill_fail: true` runs no tests; `Holdout shard 1/6` prints
  `drill AC-1: fail` and fails. Its issue is titled `Holdout drill failed <date>` (same body rules) and is not
  closed automatically; the evaluator closes it.
- **Concurrency:** PRs unchanged (one run per PR; a push cancels the older run; an edit queues). Nightly runs
  keep their group. Manual runs get a group per run and never cancel or get cancelled by another run.
- **Timeouts:** own-rows job 45 min, shard 60 min.
- **Caching:** the Playwright browser download is cached (key: installed Playwright version); system
  dependencies still install. pip and npm caches stay as they are.

### `ci.yml`, backend

- 4 jobs `Backend shard K/4`, each with today's service containers, run lint, the API contract check and part K
  of the pytest suite with coverage. The split unit is the pytest node id; the method is the builder's choice,
  with no new dependency unless it is a pinned test plugin; parts should take about the same time. Each shard
  passes to the aggregate the part K it actually ran (from the split's own argument, not the matrix index), the
  pytest node IDs it ran (as pytest reports them, e.g. from `-rA` summary lines or a small plugin hook that
  writes `item.nodeid`), and the full collected list from `pytest --collect-only -q`. Both lists use the same
  node-ID format (`path::Class::test[param]`).
- Aggregate job named exactly `Backend (lint + tests)`, runs always: success only when all 4 succeeded;
  combines the 4 coverage results and runs the same diff-coverage rule (changed lines >= 80 %, PRs only) on the
  combined result; prints `backend tests: <node ids run> of <node ids collected>` and fails with
  `backend shards: missing <K>/4` for each part no shard reported, `backend tests: duplicate <node id>` for a
  node id run twice, and `backend tests: <a> of <b>` when the node ids run are not exactly the collected list.
- The Chromium download for the deck fit checks is cached as in `holdout.yml`.

### Docs-only "not behind main" check

`.github/scripts/main_ahead_docs_only.sh`, run by the agent in its PR branch after `git fetch origin main`:

- lists the files changed on `origin/main` since the merge base with `HEAD` with
  `git diff --name-only --no-renames` (a rename counts as its old and its new path);
- first: prints `code: <path>`, exit 1, for the first listed path outside the allowlist (decision 1);
- then: prints `conflict`, exit 1, when `git merge-tree --write-tree HEAD origin/main` reports a conflict;
- otherwise (including when nothing is listed) prints `docs-only`, exit 0;
- `--selftest` builds a throwaway repo, checks the cases of AC-37, prints `selftest ok`; the `PR guards`
  workflow runs it.

### Rules (`.claude/CLAUDE.md` merge button, steward skill, factory skill)

Amended by owner decision 16 Nov 2026 (automatic merge when every gate is clean): the merge question
below is replaced by the auto-merge in `.claude/CLAUDE.md`; AC-49 and AC-50 describe it.

- **Merge button.** The agent driving the PR asks `Merge PR #<n>?` when: required checks green on the current
  head (`Holdout acceptance` now means "own hidden rows green"), mergeable, no review thread waiting on the
  agent, and either not behind `main` or `main_ahead_docs_only.sh` prints `docs-only`. If GitHub refuses the
  merge as out of date, it merges `origin/main` in and asks again once green. While a
  `Nightly Holdout failed` issue is open, the question adds the line `main has failing hidden tests: issue
  #<n>`; it does not block the merge.
- **Steward skill.** A PR that fixes a nightly failure puts `Holdout: full` on its own line in the body, so the
  full suite runs before it merges, and `Refs #<issue>` for the nightly issue. Its fix-round count starts at 0.
  The issue closes on the next green full run on `main`, not by the PR.
- **Factory skill.** `/factory` starts its status with each open `Nightly Holdout failed` issue as
  `Hidden tests red on main: issue #<n>, merges <sha>..<sha>`. When the owner tells the dispatcher
  "showcase freeze", it starts a manual `holdout.yml` run on `main` and reports its result to the owner with
  the head SHA it checked. (The nightly run of 27 Nov at 02:17 UTC also covers every merge of 26 Nov.)

### Roll-out without blocking open PRs (before 27 Nov)

1. Runner PR (holdout repo) merges first. Old flags and output are unchanged, so open PRs keep working.
2. Workflow PR (`holdout.yml`, the docs-only script and its self-test in `pr-guards.yml`). Its own
   `pull_request` run uses the new `holdout.yml` (no hidden rows for this spec, so it shows the no-rows path).
   Throwaway PRs off it, closed unmerged, prove the rest: one with `Spec: <an existing spec>`, one with
   `Holdout: full`, one whose shard 3 exits 1, one with `timeout-minutes: 1` on shard 3, one where shard 2 runs
   `--shard 1/6`. After the merge a manual `drill_fail` run proves the issue path. Open PRs pick up the new
   workflow at their next push or `main` merge; nothing is re-run.
3. Backend-split PR (`ci.yml`), proved the same way with throwaway PRs. Independent of 2; if it misbehaves,
   revert only it.
4. Rule PR (`.claude/CLAUDE.md`, steward, factory skills), after 2.

## Slices

| # | PR | Repo | Risk | Rows |
|---|---|---|---|---|
| 1 | Runner flags `--no-regression`, `--shard`, `--count`, `--list` (test-writer-style session) | holdout | n/a | AC-1 to AC-11 |
| 2 | `holdout.yml`; docs-only script + self-test in `pr-guards.yml` | app | `risk:high` | AC-12 to AC-37 |
| 3 | `ci.yml` backend over 4 machines | app | `risk:high` | AC-38 to AC-46 |
| 4 | Merge-button, steward and factory rules | app | `risk:normal` | AC-49 to AC-53 |

Each app PR description has `Spec: holdout-faster-runs` and a `Rows:` line as a comma list (`Rows: AC-12,
AC-13, ...`). This spec has no `holdout` rows: the checks are about CI itself, so rows are `unit` (self-tests in
the holdout repo or this repo) or `evaluator` (an agent reads the check runs, timings, logs and issues on
GitHub).

When a row is checked: **PR** rows on the slice's own PR or its throwaway PRs, before the merge, and they gate
it. **After merge** rows can only be seen once the slice is on `main` (timings over the next PRs, the first
nightly run, the first real case); they do not gate the slice's PR, and a failure there is fixed by a follow-up
PR. AC-47 and AC-48 need slices 2 and 3 and are checked after whichever merges last.

## Left to the builder (defaults chosen here)

- Number of hidden shards 6, backend shards 4: one constant each in the workflow.
- Timing rows: time is measured from the run's `run_started_at` to the named check's `completed_at`. A run
  counts ("idle queue") when every job with no `needs` started within 2 min of `run_started_at`, and every
  other job started within 2 min of the last job it needs completing. Per PR, the first completed
  run that meets this counts, failed runs included; PRs with no such run are skipped and the next PR is taken.
- Job names other than the two required checks, `Holdout shard K/6` and `Backend shard K/4`.
- How results travel between jobs (job outputs, artifacts that hold no hidden-test content) and how backend
  tests are split.
- Exact issue body layout beyond the content fixed here.

## Acceptance

"Result lines" are the runner's existing one-per-row lines ending in pass or fail (see "Hidden-test runner
flags"). Timing rows follow the measuring rule in "Left to the builder".

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Holdout repo at the slice-1 commit | `python run.py --list` runs | It prints one row ID per line, no ID twice, and runs no test | unit (holdout repo) |
| AC-2 | Same | `run.py --count` runs | It prints exactly one line `holdout rows: <n>`, n = the number of lines of `run.py --list`, and runs no test | unit (holdout repo) |
| AC-3 | Same | `run.py --shard K/6 --list` runs for K = 1 to 6 | The six sets of IDs are pairwise disjoint and their union equals the set of `run.py --list` | unit (holdout repo) |
| AC-4 | Same | `run.py --shard K/6 --count` runs for K = 1 to 6 | The six counts add up to the n of AC-2 | unit (holdout repo) |
| AC-5 | Same | `run.py --shard 3/6` runs | `holdout shard: 3/6` appears in its output before the first result line | unit (holdout repo) |
| AC-6 | Same | `run.py --shard 0/6`, `--shard 7/6`, `--shard 1/0`, `--shard x/6` | Each exits 2 and prints a line starting `invalid --shard`; no test runs | unit (holdout repo) |
| AC-7 | Same | `run.py --shard 1/6 --spec <slug>` and `run.py --shard 1/6 --no-regression` | Each exits 2 and prints a line starting `invalid --shard`; no test runs | unit (holdout repo) |
| AC-8 | Same, a slug with hidden rows | `run.py --spec <slug> --no-regression` and `... --rows AC-1,AC-2` | The row IDs of the result lines equal `run.py --spec <slug> --list` (with `--rows`, only that spec's AC-1 and AC-2); no other row runs | unit (holdout repo) |
| AC-9 | Same | `run.py --no-regression` with no `--spec` | It prints `holdout: nothing to run` and exits 0 | unit (holdout repo) |
| AC-10 | Same, a slug with no hidden rows | `run.py --spec <slug> --no-regression` | It prints `holdout: nothing to run` and exits 0 | unit (holdout repo) |
| AC-11 | Must not change: same | plain `run.py`, `--spec`, `--spec --rows` | Result-line and `<group>: done in N s` formats and exit codes as before slice 1 (1 when a row fails, 0 when all pass) | unit (holdout repo) |
| AC-12 | Slice 2: a PR with `Spec: <slug>` whose spec has `holdout` rows, no opt-in line | a commit is pushed | The run has exactly one test job plus `Holdout acceptance`; no `Holdout shard` job with a conclusion other than `skipped`; the test job prints `holdout rows: <n>` and exactly n result lines, n no more than the `holdout` rows of that spec's Acceptance table | evaluator (PR, throwaway) |
| AC-13 | Slice 2 merged; PRs as in AC-12 with at most 60 rows | their runs finish | `Holdout acceptance` takes at most 15 min (median of the first 3 PRs) and none over 20 min | evaluator (after merge) |
| AC-14 | Slice 2: a PR with no `Spec:` line and no opt-in line, app files changed | a commit is pushed | `Holdout acceptance` succeeds within 3 min, no step starts the app, and the log contains `Holdout acceptance: no Spec: line; hidden rows run nightly on main.` | evaluator (PR) |
| AC-15 | Slice 2: a PR with `Spec: <slug>` whose spec has no `holdout` rows (slice 2's own PR) | a commit is pushed | `Holdout acceptance` succeeds within 10 min and the log contains `holdout: nothing to run` | evaluator (PR) |
| AC-16 | Slice 2: a PR with `Spec: <slug>` and the opt-in line | a commit is pushed | The run has the own-rows job and 6 jobs `Holdout shard 1/6` to `Holdout shard 6/6`; `Holdout acceptance` is green only when all 7 are | evaluator (PR, throwaway) |
| AC-17 | Same | the run finishes | `Holdout acceptance` takes at most 45 min | evaluator (PR, throwaway) |
| AC-18 | Slice 2: a PR with the opt-in line and no `Spec:` line | a commit is pushed | The run has the 6 shard jobs and no own-rows job with a conclusion other than `skipped` | evaluator (PR, throwaway) |
| AC-19 | Slice 2: a PR whose body has the sentence `We may need Holdout: full later.` and no opt-in line | a commit is pushed | No `Holdout shard` job has a conclusion other than `skipped` | evaluator (PR, throwaway) |
| AC-20 | Slice 2: an open PR with a running Holdout run | its body is edited to add the opt-in line | A new run with 6 shard jobs starts after the running one ends; the running one is not cancelled | evaluator (PR, throwaway) |
| AC-21 | Slice 2: a throwaway PR with the opt-in line where `Holdout shard 3/6`'s test step exits 1 | the run finishes | `Holdout shard 3/6` is red and `Holdout acceptance` concludes `failure` | evaluator (PR, throwaway) |
| AC-22 | Slice 2: a throwaway PR with the opt-in line and `timeout-minutes: 1` on `Holdout shard 3/6` | the run finishes | `Holdout shard 3/6` does not succeed and `Holdout acceptance` concludes `failure` | evaluator (PR, throwaway) |
| AC-23 | Slice 2: a throwaway PR with the opt-in line where the shard-2 job runs `run.py --shard 1/6` | the run finishes | `Holdout acceptance` concludes `failure` and its log contains `holdout shards: missing 2/6` | evaluator (PR, throwaway) |
| AC-24 | Slice 2: a PR with the opt-in line | the run finishes green | The `Holdout acceptance` log contains exactly one `holdout commit: <sha>` line and `holdout rows: <a> of <b>` with a = b | evaluator (PR, throwaway) |
| AC-25 | Slice 2 merged | the first nightly run on `main` finishes | It has 6 jobs `Holdout shard 1/6` to `Holdout shard 6/6`, and its log has `holdout rows: <a> of <b>` with a = b | evaluator (after merge) |
| AC-26 | Same | the first nightly run finishes | `Holdout acceptance` takes at most 45 min | evaluator (after merge) |
| AC-27 | Slice 2 merged | a manual run on `main` with `drill_fail: true` finishes | Exactly one issue `Holdout drill failed <date>` exists for it, opened by the `Holdout acceptance` job; its body contains `drill AC-1: fail`, the holdout commit, a `<sha>..<sha>` range with one line per merge that includes its PR title (or `no green nightly in 30 days` and the last 30 merges), and the run link | evaluator (after merge) |
| AC-28 | Slice 2 merged | a nightly run fails on a row, or one of its parts runs into its time limit (owner decision 16 Nov 2026) (new behaviour; today the body is only the run link) | Exactly one issue `Nightly Holdout failed <date>` is opened, with the body content of AC-27 and the failed result lines instead of `drill AC-1: fail` (for a part that ran into its time limit: that part listed as `timed_out`, and its `holdout shards: missing K/6` line or a `holdout rows: <a> of <b>` line with a < b) | evaluator (after merge, first real failure) |
| AC-29 | Slice 2 merged; an open issue titled `Nightly Holdout failed 2000-01-01` | a manual run on `main` succeeds | The issue is closed, with a comment linking that run | evaluator (after merge) |
| AC-30 | Slice 2 merged | a manual run on `main` is cancelled by hand | No issue is opened | evaluator (after merge) |
| AC-31 | Slice 2 merged | a manual run on `main` is started while the nightly run is running | Neither run is cancelled; both reach a conclusion other than `cancelled` | evaluator (after merge) |
| AC-32 | Slice 2: a PR whose own rows fail | the run finishes | No issue is opened | evaluator (PR, throwaway) |
| AC-33 | Must not change: slice 2: a PR whose files are all under `docs/` or `.claude/` or are `*.md` | a commit is pushed | `Holdout acceptance` succeeds and no step starts the app | evaluator (PR) |
| AC-34 | Slice 2 | the logs of the runs in AC-12 to AC-27 and the issue of AC-27 are read | They contain no hidden test code, test function name or hidden-test file path; runner output is only result lines, `<group>: done in N s`, `holdout shard: ...`, `holdout rows: ...`, `holdout commit: ...`, `holdout: nothing to run`; no run has an artifact with hidden-test content | evaluator (PR and after merge) |
| AC-35 | Slice 2 merged; a PR opened before the merge, with `Spec: <slug>` | it pushes a commit | Its run has one own-rows job and no shard job with a conclusion other than `skipped`, and `Holdout acceptance` is red only if one of its result lines is a fail | evaluator (after merge) |
| AC-36 | Slice 2: an open PR | a label is added to or removed from it | No Holdout run starts and none is cancelled | evaluator (PR, throwaway) |
| AC-37 | Slice 2 | `bash .github/scripts/main_ahead_docs_only.sh --selftest` runs (also in the `PR guards` workflow) | It prints `selftest ok` after checking: nothing ahead → `docs-only`, exit 0; only allowlisted files ahead → `docs-only`, exit 0; `backend/x.py` ahead → `code: backend/x.py`, exit 1; `docs/decision-studio/example-framework/x.csv` ahead → `code: docs/decision-studio/example-framework/x.csv`, exit 1; `docs/transition_barrier/RULE_BOOK.md` ahead → `code: docs/transition_barrier/RULE_BOOK.md`, exit 1; a conflicting allowlisted change → `conflict`, exit 1; `backend/y.py` ahead and a conflict → `code: backend/y.py`, exit 1; `backend/z.py` renamed to `docs/superpowers/z.md` on main → `code: backend/z.py`, exit 1 | unit |
| AC-38 | Slice 3: a PR changing backend code | its CI run finishes | It has 4 jobs `Backend shard 1/4` to `Backend shard 4/4` and one `Backend (lint + tests)`, which is green only when all 4 are | evaluator (PR) |
| AC-39 | Slice 3 merged; the first 3 PRs changing backend code | their runs finish | `Backend (lint + tests)` takes at most 12 min (median) and none over 16 min | evaluator (after merge) |
| AC-40 | Slice 3: a green PR run | the `Backend (lint + tests)` log is read | It contains `backend tests: <a> of <b>` with a = b | evaluator (PR) |
| AC-41 | Slice 3: a throwaway PR where the shard-2 job runs part 1 | the run finishes | `Backend (lint + tests)` concludes `failure` and its log contains `backend shards: missing 2/4` | evaluator (PR, throwaway) |
| AC-42 | Slice 3: a throwaway PR with one failing test that runs in shard 2 | the run finishes | `Backend shard 2/4` is red and `Backend (lint + tests)` concludes `failure` | evaluator (PR, throwaway) |
| AC-43 | Slice 3: a throwaway PR adding 10 backend lines covered only by a new test that runs in shard 4 | the run finishes | The diff-coverage step passes and `Backend (lint + tests)` concludes `success` | evaluator (PR, throwaway) |
| AC-44 | Must not change: slice 3: a throwaway PR adding 20 backend lines no test covers | the run finishes | The diff-coverage step exits 1 and `Backend (lint + tests)` concludes `failure` | evaluator (PR, throwaway) |
| AC-45 | Must not change: slice 3: a throwaway PR with a ruff error | the run finishes | `Backend (lint + tests)` concludes `failure` | evaluator (PR, throwaway) |
| AC-46 | Must not change: slice 3: a throwaway PR that changes a response model without regenerating `openapi.json` | the run finishes | `Backend (lint + tests)` concludes `failure` | evaluator (PR, throwaway) |
| AC-47 | Slices 2 and 3 merged; the first 3 PRs with `Spec:` of at most 60 rows, no opt-in line | a commit is pushed | Every required check on the head is green at most 15 min after `run_started_at` of the earliest run for that head (median), none over 20 min | evaluator (after merge) |
| AC-48 | Slices 2 and 3 merged | the check list of any PR is read | It has exactly one check `Holdout acceptance` and one `Backend (lint + tests)`, and a PR with all required checks green is mergeable with no change to the required-check settings | evaluator (after merge) |
| AC-49 | Slice 4 merged; "Require branches to be up to date" unticked; a `risk:normal` PR behind `main`, every auto-merge gate in `.claude/CLAUDE.md` clean | the factory dispatcher checks the merge gates | It merges the PR without a merge question and without first merging `origin/main` into the branch, then sends the owner the one-line merge report with the short head SHA. Amended by owner decision 16 Nov 2026 (automatic merge when every gate is clean) | evaluator (after merge, first real case) |
| AC-50 | Slice 4 merged; an open `Nightly Holdout failed` issue; a `risk:low` or `risk:normal` PR with every auto-merge gate clean | the factory dispatcher merges it | The PR is merged and the one-line merge report to the owner contains `main has failing hidden tests: issue #<n>`. Amended by owner decision 16 Nov 2026 (automatic merge when every gate is clean) | evaluator (after merge, first real case) |
| AC-51 | Slice 4 merged; an open `Nightly Holdout failed` issue | `/factory` runs | Its status starts with `Hidden tests red on main: issue #<n>, merges <sha>..<sha>` | evaluator (after merge) |
| AC-52 | Slice 4 merged; a nightly failure being fixed | the fix PR is opened | Its body has a line `Holdout: full` and a line `Refs #<issue>`, and its Holdout run has 6 shard jobs | evaluator (after merge, first real case) |
| AC-53 | Slice 4 merged | the owner tells the dispatcher "showcase freeze" | A manual `holdout.yml` run on `main` starts, and once it ends the dispatcher sends the owner `Showcase check: full hidden run on <short sha>: <success\|failure>, <run link>` | evaluator (after merge, first real case) |

Must not change: the runner's output and exit codes (AC-11), the `holdout.yml` skips (AC-33), the
diff-coverage, lint and API contract rules (AC-44 to AC-46). `main-guard.yml` is not touched.
