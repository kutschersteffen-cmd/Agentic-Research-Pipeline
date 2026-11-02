# Research Orchestrator v2: re-planning on request

## Problem

In v1 a failed plan stops. The owner can edit the script by hand and resume, which reuses finished steps
only when the edited script calls them with the same arguments. Recovering from a failure, such as a step
that needs a different schema or a filter that leaves no companies, means rewriting the script yourself.

## Goal

A failed plan gets a **Re-plan** action. The planner sees the brief, the script, the finished steps and the
error, and writes a script for the **remaining work only**. Finished steps are kept and never re-run. The
new script is checked and dry-run like any plan script and comes back as a **draft for approval**. Nothing
runs until the owner approves it. Re-planning happens only when the owner asks; never automatically.

## Design

### 1. Finished steps as a read-only input
A re-planned script receives one extra name, `previous`: the list of results of the plan's `done` calls in
seq order (the same Result shape steps return: `id`, `run_id`, `companies`). It may read
`previous[i].run_id`, `previous[i].companies` and so on. It cannot assign to `previous`. The checker allows
the name; the dry run gives it the stored results, so data-dependent branches on finished steps resolve to
real values instead of placeholders.

### 2. Plan versions
`research_plans` gains `version` (int, starts at 1) and `previous_scripts` (JSON list of
`{version, script, error, replanned_at, replanned_by}`). Re-planning:
- keeps every `done` call; deletes the plan's `failed` and `cancelled` calls;
- stores the old script and error in `previous_scripts`, puts the new script in `script`, bumps `version`;
- sets status `draft`, clears approval, stores the new dry run.

New calls are numbered after the last kept call (a kept seq is never reused). Running a re-planned plan
injects `previous` and does not re-run kept calls.

### 3. Planner
`replan_plan(plan_id, llm)`: one structured call (`PlanScript`) whose prompt holds the brief, the failed
script, the error, the finished steps (kind, params, run_id, company count) and the same context as
drafting. Same one retry on checker or dry-run errors; a second rejection leaves the plan unchanged
(`failed`) and returns the errors.

### 4. Surfaces
- CLI: `arp plan replan <id>` prints `version N` on the first line, then the dry run in the `arp plan draft`
  format; on two rejections it exits 1 and prints the errors.
- Demo: `arp plan seed-demo --replanned` stores a second demo plan already at `version: 2` (fixed old script
  and error in `previous_scripts`, no model call), so the page can be checked without a model.
- API: `POST /api/plans/{id}/replan` returns the plan; 409 `only a failed plan can be re-planned` unless
  status is `failed`; 422 with body `{"detail": [<error lines>]}` after two rejected attempts.
- Plans page: a **Re-plan** button on failed plans; the plan header shows `version N`; a "Previous
  versions" list shows each older script with its error.

## Out of scope
Automatic re-planning; a `replan()` call inside scripts; parallel steps; editing `previous`.

## Acceptance

Rows that need a scripted model or stub steps stay `unit`: the e2e app has no model. Rows with neither are
`holdout` (owed as `unit` while `HOLDOUT_TOKEN` is unset).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A plan in status `draft`, `approved`, `running`, `done` or `cancelled` | `POST /api/plans/{id}/replan` | HTTP 409, body `{"detail": "only a failed plan can be re-planned"}` | holdout |
| AC-2 | A failed plan: seq 1 `done` (run id `r_1`), seq 2 `failed`; scripted model returns a valid remaining script | `arp plan replan <id>` | exit 0; first stdout line is `version 2` | unit |
| AC-3 | Same | `arp plan replan <id>` | `GET` shows `status: "draft"`, `version: 2`, `approved_by: null` | unit |
| AC-4 | Same, plus a `cancelled` call at seq 3 | `arp plan replan <id>` | `GET` calls: exactly one, seq 1 `done` with run id `r_1` | unit |
| AC-5 | Same | `arp plan replan <id>` | `previous_scripts` has 1 entry with `version: 1`, the old script and the step-2 error text | unit |
| AC-6 | Same | `arp plan replan <id>`, new script reads `previous[0].run_id` as an argument | `GET` `dry_run` first entry has that argument equal to `"r_1"` | unit |
| AC-7 | A re-planned plan in `draft` | `arp plan run <id>` | exit 1, stdout contains `plan is not approved`; no new call stored | unit |
| AC-8 | A re-planned plan (seq 1 kept), new script makes 2 step calls, approved, stub steps | `arp plan run <id>` | stored new calls have seq 2 and 3 | unit |
| AC-9 | Same | `arp plan run <id>` | the stub records no call for the kept step | unit |
| AC-10 | Same | `arp plan run <id>` | plan `status: "done"` | unit |
| AC-11 | Scripted model returns a rejected script twice | `POST /api/plans/{id}/replan` | HTTP 422, body `{"detail": [...]}` equal to the second attempt's error lines | unit |
| AC-12 | Same | `POST /api/plans/{id}/replan` | `GET` shows `status: "failed"`, `version: 1`, calls unchanged | unit |
| AC-13 | Same | `arp plan replan <id>` | exit 1, stdout contains the second attempt's error lines | unit |
| AC-14 | A failed plan being re-planned | the model is called | the prompt contains the brief, the failed script, the error text, and one line per kept call with its kind and run id | unit |
| AC-15 | A plan whose step fails during `arp plan run` | the run ends | `GET` shows `status: "failed"`, `version: 1`, `previous_scripts: []`; the model received no call | unit |
| AC-16 | A script that assigns `previous = []` | `arp plan check s.py` | exit 1, stdout contains `line 1: name previous cannot be assigned` | holdout |
| AC-17 | Plans page; `arp plan seed-demo`, then that plan approved and run to `failed` | look at the plan | a `Re-plan` button is shown | evaluator |
| AC-18 | Plans page, a plan in status `done` | look at the plan | no `Re-plan` button | unit |
| AC-19 | Plans page; `arp plan seed-demo --replanned` | open that plan | the header shows `version 2`; "Previous versions" lists 1 entry with its script and error | evaluator |

Must not change:

| AC-20 | Existing `tests/test_plan_*.py` | run them | pass with no test edited | unit |
| AC-21 | A v1 plan run with fixed stub steps | `arp plan run <id>` | same calls, seqs and final status as on `main`; `version: 1`, `previous_scripts: []` | unit |
