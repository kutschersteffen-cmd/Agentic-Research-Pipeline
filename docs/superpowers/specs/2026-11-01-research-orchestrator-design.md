# Research Orchestrator — design (v1: code mode, approve, run)

## Problem

ARP has 19 functions, each runnable alone. A person chains them by hand: build a universe, discover
documents, extract, score in Decision Studio, construct an index, render a report. Every hand-off is a
copy of ids between pages. The orchestrator lets one brief drive the whole chain.

## Goal

The owner types a research brief ("grid-storage index, EU listed, drop names under 10% exposure, deck for
Friday"). An agent writes a **plan script**: a short, restricted Python program that calls ARP's existing
run types as functions, with loops, branches and filters ("code mode"). Deterministic code checks the
script, dry-runs it to show the owner the steps it will take, and after approval runs it, pausing at
review gates.

House rules hold: **the LLM plans, deterministic code computes.** The script only composes run types that
exist; it adds no analytics, and every number still comes from the run types themselves.

## Design

### 1. Step API (closed)
`arp/orchestration/plan_api.py` exposes one typed function per run type the script may call:
`universe_build`, `document_discovery`, `extraction`, `financials_extraction`, `xbrl_facts`,
`decision_score`, `index_construct`, `report_render`. Each takes keyword arguments validated by a Pydantic
model and returns a small typed result (ids plus the per-company fields a script may filter on, e.g.
`exposure`, `has_xbrl`). The planner prompt receives these signatures as Python stubs.

### 2. Allowed language
Checked on the syntax tree before anything runs. Allowed: assignments, `for`, `if`/`else`, comparisons,
boolean ops, list/dict literals and comprehensions, attribute and index reads, calls to the step API
functions and to `len`, `min`, `max`, `sorted`, `sum`, `range`. Arithmetic operators (`+ - * / % **`) are rejected, so a script cannot compute a number it then passes on. Everything else is rejected, including
`import`, `def`, `class`, `lambda`, `while`, `try`, `with`, `global`, any name starting with `_`, and
calls to any other name. Limits: script ≤ 200 lines, ≤ 500 step calls per execution.

### 3. Planner (one LLM call)
`draft_plan(brief) -> PlanScript`. The checker runs on the output; on rejection the planner gets the
checker errors once and retries; a second failure returns the errors to the user.

### 4. Dry run
The interpreter runs the script with placeholder step functions; it never reads the database or starts
a run. Each placeholder returns ids `"<kind>_<seq>"` and marks its per-company fields unknown. A branch or
loop filter on an unknown value takes the `True` path once and marks every call inside it
`depends on <seq>` (the seq of the step whose result it read). It records `[{seq, kind, params, depends_on}]`.
The owner approves the script together with this list. Tests may inject stub step functions in place of
placeholders.

### 5. Approval
Status: `draft → approved → running ⇄ awaiting_review → done | failed | cancelled`. Only `approved` scripts
run. Editing the script returns it to `draft` and re-runs the checker and dry run. Approval records who and
when.

### 6. Executor (no LLM)
A small tree-walking interpreter over the allowed subset (not `exec`) runs the approved script. Each step
call starts the real run type through its existing entry point, waits for it, and stores the call
`{seq, kind, params, run_id, status}`. A step that ends in a review gate sets `awaiting_review` until the
existing review flow marks it reviewed. A failed step fails the plan. `resume` re-runs the script from the
top, reusing stored results for calls whose `(seq, kind, params)` match a `done` call, so finished runs are
not repeated. `run_lease` keeps one worker per plan.

### 7. Surfaces
- CLI: `arp plan draft "<brief>"`, `arp plan check <file.py>`, `arp plan dry-run <id>`, `arp plan show <id>`,
  `arp plan approve <id>`, `arp plan run <id>`, `arp plan resume <id>`, `arp plan cancel <id>`,
  `arp plan golden --cases <file> --min-pass <n>`.
- API: `POST /plans`, `GET /plans/{id}`, `PUT /plans/{id}` (edit script), `POST /plans/{id}/approve`,
  `POST /plans/{id}/run`, `POST /plans/{id}/cancel`.
- UI: a **Plans** page: brief box, the script (read-only code view), the dry-run step list, Approve
  button, live step status with links to each run.

## Out of scope (v1)
Stopping a run type already in progress on cancel (it finishes; no later step starts), re-planning on failure, parallel step execution, user-defined functions in scripts, per-plan cost budgets.

## Acceptance

Rows using stub run types or forced failures stay `unit`: the e2e app cannot reach those states.
`evaluator` rows use the demo plan seeded by a new `arp plan seed-demo` (script and dry run stored, no LLM call).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A script containing `import os` | `arp plan check s.py` | exit 1, stdout contains `line 1: import not allowed` | unit |
| AC-2 | A script calling `open("x")` | `arp plan check s.py` | exit 1, stdout contains `line 1: call to open not allowed` | unit |
| AC-3 | A script reading `x.__class__` | `arp plan check s.py` | exit 1, stdout contains `line 1: name __class__ not allowed` | unit |
| AC-4 | A script calling `extraction(foo=1)` | `arp plan check s.py` | exit 1, stdout contains `line 1: extraction: unexpected argument foo` | unit |
| AC-5 | A script with `w = x * 2` | `arp plan check s.py` | exit 1, stdout contains `line 1: arithmetic not allowed` | unit |
| AC-6 | A 201-line script | `arp plan check s.py` | exit 1, stdout contains `script exceeds 200 lines` | unit |
| AC-7 | A valid 3-line script using `for` and `if` over step results | `arp plan check s.py` | exit 0, stdout `ok` | unit |
| AC-8 | A script whose loop makes 501 step calls (injected stubs) | `arp plan dry-run` | exit 1, stdout contains `step limit 500 exceeded` | unit |
| AC-9 | Injected stubs: universe of 3 companies, `extraction` only where `exposure >= 0.1` (2 match) | `arp plan dry-run` | list is `universe_build` (seq 1) then exactly 2 `extraction` (seq 2, 3) | unit |
| AC-10 | Same script, placeholders (no stubs) | `arp plan dry-run` | list is `universe_build` (seq 1), one `extraction` (seq 2) with `depends_on: 1` | unit |
| AC-11 | Stub planner rejected once, valid the second time | `arp plan draft "x"` | exit 0; plan stored with `status: "draft"` | unit |
| AC-12 | Stub planner rejected twice | `arp plan draft "x"` | exit 1, stdout contains the checker errors of the second attempt | unit |
| AC-13 | A plan in status `draft` | `POST /plans/{id}/run` | HTTP 409, body `{"detail": "plan is not approved"}` | unit |
| AC-14 | A draft plan | `POST /plans/{id}/approve` as user `alice` | `GET` shows `status: "approved"`, `approved_by: "alice"`, non-null `approved_at` | unit |
| AC-15 | An approved plan | `PUT /plans/{id}` with a changed script | `GET` shows `status: "draft"` | unit |
| AC-16 | An approved plan | `PUT /plans/{id}` with a changed script | `GET` shows `approved_by: null`, `approved_at: null` | unit |
| AC-17 | Approved plan whose script has 1 `universe_build` call | `PUT` adds a second `universe_build` call | `GET` dry-run list has 2 `universe_build` rows | unit |
| AC-18 | Approved plan, stub step 1 returns `universe_id: "u_1"`, step 2 uses it | `arp plan run` | step 2's stored params show `universe_id: "u_1"` | unit |
| AC-19 | Approved plan with 3 chained stub steps | `arp plan run` | stored calls have `started_at` ordered seq 1 < 2 < 3 | unit |
| AC-20 | Same plan | `arp plan run` finishes | plan `status: "done"` | unit |
| AC-21 | Step 2's run type ends in a review gate | step 2 finishes | plan `status: "awaiting_review"` | unit |
| AC-22 | Same | step 2 finishes | no call with seq 3 is stored | unit |
| AC-23 | Plan in `awaiting_review` | step 2's run is marked reviewed | a call with seq 3 is stored with `status: "running"` | unit |
| AC-24 | Same | step 2's run is marked reviewed | plan `status: "running"` | unit |
| AC-25 | Stub step 2 raises | `arp plan run` | plan `status: "failed"` | unit |
| AC-26 | Same | `arp plan run` | call seq 2 `status: "failed"` | unit |
| AC-27 | Same | `arp plan run` | no call with seq 3 is stored | unit |
| AC-28 | Plan failed at seq 2, seq 1 has run id `r_1` | `arp plan resume` | seq 1 run id is still `r_1`; seq 2 has a new run id | unit |
| AC-29 | Same | `arp plan resume` finishes | plan `status: "done"` | unit |
| AC-30 | A plan in `running` | second `POST /plans/{id}/run` | HTTP 409, body `{"detail": "plan is already running"}` | unit |
| AC-31 | A plan in `running` | `arp plan run <id>` | exit 1, stdout contains `plan is already running` | unit |
| AC-32 | A plan running seq 2 (stub, blocking) | `POST /plans/{id}/cancel`, then seq 2 finishes | plan `status: "cancelled"`; seq 2 `status: "done"`; no call with seq 3 is ever stored | unit |
| AC-33 | Plans page, seeded demo plan | open the plan | the page shows the script text and 4 dry-run step rows | evaluator |
| AC-34 | Plans page, a plan with stored calls | look at the step list | each row's status label equals that call's stored `status` (`pending`, `running`, `awaiting_review`, `done`, `failed`, `cancelled`) | evaluator |
| AC-35 | Plans page, a `done` step | click its link | the browser opens the same URL the existing Runs list links to for that run id | evaluator |
| AC-36 | Golden file of 10 briefs, each with expected step kinds in relative order (extra steps allowed); a case passes if the script passes the checker and its dry run contains those kinds in that order | `arp plan golden --cases tests/golden/plans.jsonl --min-pass 8` | exit 0 | golden |
| AC-37 | Existing backend suite (must not change: run types started on their own behave as before) | `python3 -m pytest` | passes with no test edited | unit |
