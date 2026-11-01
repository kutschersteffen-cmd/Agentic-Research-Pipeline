# Research Orchestrator — design (v1: plan + approve + run)

## Problem

ARP has 19 functions, each runnable alone. A person chains them by hand: build a universe, discover
documents, extract, score in Decision Studio, construct an index, render a report. Every hand-off is a
copy of ids between pages. The orchestrator lets one question drive the whole chain.

## Goal

The owner types a research brief ("grid-storage index, EU listed, PAB-aligned, deck for Friday"). An agent
drafts a **plan**: a typed DAG of existing ARP run types with their parameters. The owner approves or edits
it. Deterministic code then runs the DAG, step by step, pausing at review gates, and links every output
back to the plan.

House rules hold: **the LLM plans, deterministic code computes.** The orchestrator adds no analytics; it
only composes run types that already exist.

## Design

### 1. Step catalogue (closed)
A registry `arp/orchestration/plan_catalogue.py` lists each run type the planner may use, with a Pydantic
input model, the output it produces (e.g. `universe_id`, `extraction_run_id`) and whether it ends in a
review gate. v1 entries: `universe_build`, `document_discovery`, `extraction`, `financials_extraction`,
`xbrl_facts`, `decision_score`, `index_construct`, `report_render`. Same pattern as the BI designer's
closed catalogue.

### 2. Planner (one LLM call)
`draft_plan(brief) -> ResearchPlan`. Output is a list of steps `{id, kind, params, depends_on}`;
params may reference an upstream output as `{"$ref": "<step_id>.<output>"}`. A deterministic validator
rejects unknown kinds, invalid params, cycles and refs to outputs a step does not produce. On rejection the
planner gets the validator errors once and retries; a second failure returns the errors to the user.

### 3. Approval
Plans are stored with status `draft → approved → running ⇄ awaiting_review → done | failed | cancelled`. Only `approved`
plans run. Editing an approved plan returns it to `draft`. Approval records who and when.

### 4. Executor (no LLM)
A job walks the DAG in topological order, resolves `$ref`s from finished steps, starts each step through
the run type's existing entry point, and waits for it. Steps with a review gate move the plan to
`awaiting_review` until the existing review flow marks the run reviewed. A failed step fails the plan;
`resume` restarts from the first unfinished step. Reuses `run_lease` so one worker drives one plan.

### 5. Surfaces
- CLI: `arp plan draft "<brief>"`, `arp plan validate <file>`, `arp plan show <id>`, `arp plan approve <id>`, `arp plan run <id>`,
  `arp plan resume <id>`, `arp plan cancel <id>`, `arp plan golden --cases <file> --min-pass <n>`.
- API: `POST /plans`, `GET /plans/{id}`, `POST /plans/{id}/approve`, `POST /plans/{id}/run`,
  `PUT /plans/{id}` (edit steps/params), `POST /plans/{id}/cancel`.
- UI: a **Plans** page: brief box, the DAG as an ordered step list with params, Approve button, live step
  status with links to each run.

## Out of scope (v1)
Re-planning on failure, autonomous step choice at run time, new analytics, parallel step execution,
cost budgets per plan (cost_tracker already logs spend per run).

## Acceptance

Rows using stub run types or forced failures stay `unit`: the e2e app cannot reach those states.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A plan file with a step whose `kind` is `foo` | `arp plan validate plan.json` | exit 1, stdout contains `unknown step kind: foo` | unit |
| AC-2 | A plan file listing step A first, A depends on B, B depends on A | `arp plan validate plan.json` | exit 1, stdout contains `cycle: A -> B -> A` | unit |
| AC-3 | Step B refs `A.universe_id`, A is `document_discovery` | `arp plan validate plan.json` | exit 1, stdout contains `A does not produce universe_id` | unit |
| AC-4 | A plan in status `draft` | `POST /plans/{id}/run` | HTTP 409, body `{"detail": "plan is not approved"}` | unit |
| AC-5 | A draft plan | `PUT /plans/{id}` with new params for step A | `GET /plans/{id}` shows the new params and `status: "draft"` | unit |
| AC-6 | A draft plan | `POST /plans/{id}/approve` as user `alice` | `GET` shows `status: "approved"`, `approved_by: "alice"`, non-null `approved_at` | unit |
| AC-7 | An approved plan | `PUT /plans/{id}` with any change | `GET` shows `status: "draft"` | unit |
| AC-8 | An approved plan | `PUT /plans/{id}` with any change | `GET` shows `approved_by: null` | unit |
| AC-9 | Approved plan, stubs: step1 returns `u_1`, step2 refs `step1.universe_id` | `arp plan run` | step 2's stored params show `universe_id: "u_1"` | unit |
| AC-10 | Same plan, 3 stub steps chained | `arp plan run` | step `started_at` values are in order 1 < 2 < 3; plan ends `status: "done"` | unit |
| AC-11 | Step 2's run type ends in a review gate | step 2 finishes | `GET` shows plan `status: "awaiting_review"`, step 3 `status: "pending"` | unit |
| AC-12 | Plan in `awaiting_review` | step 2's run is marked reviewed | step 3 `status` becomes `running`; plan `status: "running"` | unit |
| AC-13 | Stub step 2 raises | `arp plan run` | plan `status: "failed"`, step 2 `status: "failed"`, step 3 `status: "pending"` | unit |
| AC-14 | Plan failed at step 2, step 1 has run id `r_1` | `arp plan resume` | step 1 run id is still `r_1`; step 2 has a new run id; plan ends `done` | unit |
| AC-15 | A plan in `running` | second `POST /plans/{id}/run` | HTTP 409, body `{"detail": "plan is already running"}` | unit |
| AC-16 | A plan in `running` | `POST /plans/{id}/cancel` | plan `status: "cancelled"`; no further step starts | unit |
| AC-17 | Stub planner returns an invalid plan twice | `arp plan draft "x"` | exit 1, stdout contains the validator errors of the second attempt | unit |
| AC-18 | The Plans page, demo data | brief submitted, Approve clicked, Run clicked | each step row shows one of `pending`, `running`, `awaiting_review`, `done`, `failed` | evaluator |
| AC-19 | Plans page, a step is `done` | look at the step row | it links to that run's existing page | evaluator |
| AC-20 | Golden file of 10 briefs, each with expected kinds in relative order (extra steps allowed) | `arp plan golden --cases tests/golden/plans.jsonl --min-pass 8` | exit 0 | golden |

Must not change: every existing run type behaves as before when started on its own.

| AC-21 | Existing backend suite | `python3 -m pytest` | passes with no test edited | unit |
