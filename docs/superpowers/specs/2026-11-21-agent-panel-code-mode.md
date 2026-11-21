# Agent panel and Code Mode roadmap

Slug: agent-panel-code-mode

Risk: this spec PR is `risk:low`. The build is size L, delivered as 11 PRs (see `## Slices`); each slice names its own
risk label.

Status: **draft, waiting for the owner's approval.**
Source: thread "Explore Code Mode for ARP" (21 Nov 2026). The owner compared two proposals with today's Research Plans
(comparison page https://claude.ai/artifact/GiUvnmesyFuvPtVvXnDwcH): "ARP native research workspaces" (Markdown) and
"Agentic Workspace Architecture: Gemini 4 Argon + Code Mode + OpenShell" (PDF). He asked for an agent panel screen
inside ARP and for the sandbox objectives of the PDF, and picked one spec for the whole roadmap. Checked against
`origin/main` `c7e65f5`.

## Decisions for the owner

Approving this spec accepts all eight as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | Plans run in a **plan worker**: a scheduler job in the API process that scans Postgres every 5 s, plus the same loop as `arp plan worker` for a separate process. `POST /run` no longer starts an in-process task. | Yes (AC-4 to AC-9) | A separate Cloud Run worker service in `arp-gcp`; more infrastructure, same rows. |
| D2 | The new **Agent** screen replaces the Plans page; `#/plans/<id>` opens `#/agent/<id>`. | Yes (AC-37) | Both screens stay; two places show the same plan. |
| D3 | The sandbox lane runs **JavaScript in workerd isolates via `@cloudflare/codemode`**, in a Node sidecar `sandbox/` next to the backend. | Yes (AC-39 to AC-47) | A Python sandbox (Pyodide in Deno). Same rows, different runtime. |
| D4 | The sandbox gets **read capabilities only**. Its results are labelled `exploratory` until a person accepts them, and nothing in the plan lane can read them. | Yes (AC-45, AC-46, AC-52) | Sandbox code may start runs; every such call then needs an approval card, which this spec does not design. |
| D5 | **OpenShell** hardening gets its own spec after slice 10, starting with a spike on the `arp-gcp` deployment. This roadmap ships the sandbox with workerd's isolation (`globalOutbound: null`) and only read access. | Yes (`## Later`) | OpenShell becomes slice 12 here, without a verified GCP setup. |
| D6 | The panel updates by **polling every 3 s** while a plan runs, as the Plans page does today. | Yes (AC-34) | Server-sent events; a new streaming endpoint and reconnect logic. |
| D7 | Explorations use the configured model (`ARP_LLM_MODEL` through `LLMClient`: Claude or Gemini 4 Argon). | Yes (AC-47) | Gemini 4 Argon only. |
| D8 | Two run types join plans: `identity_resolution` and `tnfd_extraction`. | Yes (AC-14, AC-15) | Plans keep their 8 run types. |

## Why

ARP already has Code Mode for actions. A brief becomes a restricted Python plan script. A checker and a dry run gate it,
the owner approves it, and an interpreter that never calls `exec` runs it, pausing at review gates (specs
`2026-11-01-research-orchestrator-design`, `2026-11-02-research-orchestrator-replan-design`). Four things are missing:

1. **Durability.** A plan runs as an `asyncio` task inside the API process (`api/routers/plans.py:136`), so a restart
   drops it until someone presses Run again. A step's run id is stored only after the step finishes
   (`plan_executor.py`, `record_call` then `steps[kind]()` then `update_call`), so a resume after a crash mid-step starts
   a **second run** of the same step.
2. **Reach and reuse.** Plans can call 8 of about 19 functions. An approved plan cannot be run again on another universe,
   and nothing caps what a plan spends.
3. **A place to work.** The Plans page shows one plan at a time. Waiting approvals sit on several screens, and there is
   no audit view of what a plan did.
4. **Exploration.** Questions like "which holdings lack a reviewed transition plan, by sector weight" need ad hoc code
   over ARP data. The plan language rightly cannot do that (no arithmetic), and ARP has no safe place to run model-written
   code.

## What exists today

| Piece | Where | Used by this spec |
|---|---|---|
| Plan language, checker, interpreter, dry run | `orchestration/plan_check.py`, `plan_interp.py` | Unchanged |
| Step input models | `orchestration/plan_api.py` (`STEPS`) | Becomes the plan half of the catalog |
| Step adapters | `orchestration/plan_steps.py` (`build_steps`) | Split into start and finish (Phase 1) |
| Executor, lease, cancel | `orchestration/plan_executor.py`, `orchestration/jobs.py` (`run_lease`) | Executor records the run id before waiting |
| Plan store and tables | `orchestration/plan_store.py`, `plan_models.py` (`research_plans`, `research_plan_calls`) | New columns (Phases 1 and 2) |
| Plan API | `api/routers/plans.py` | New routes; `POST /run` hands over to the worker |
| Schedulers in the API lifespan | `api/main.py` | The plan worker joins them |
| Waiting count | `GET /api/waiting` (`review/waiting.py`) | The inbox shows its total |
| Read-only Ask tools | `ask.py` (`portfolio`, `smart_search`, `transition_plan`, `benchmark_sectors`) | The sandbox's read capabilities |
| Run cost | `RunManifest.estimated_cost_usd` | The plan budget |
| Plans page | `frontend/src/pages/Plans.tsx`, `lib/plans.ts`, nav entry in `lib/nav.ts` | Replaced by the Agent screen |

## Goals

- G1. A plan survives an API restart and never starts a run twice for the same step.
- G2. One capability catalog describes every function an agent may call, with its effect (`read` or `run`) and lane.
- G3. An approved plan can be saved as a template and run again on another universe.
- G4. A plan can carry a cost budget and stops before a step once the budget is reached.
- G5. An Agent screen inside ARP: threads and inbox on the left, a stream of step and approval cards in the middle, a
  stage on the right with script, diff, audit and mini-app tabs.
- G6. A sandbox lane runs model-written JavaScript over ARP's read capabilities, with no network, no secrets and fixed
  limits.
- G7. An exploration can be shown as a mini-app on the stage, in an iframe that can reach nothing.

## Non-goals

- Multi-user workspaces, memberships and source grants (the Markdown plan's P1). ARP has one owner today.
- Writes from the sandbox: no run starts, no edits, no publishing.
- Webhook and cron triggers for agents.
- Claude-hosted Programmatic Tool Calling.
- Parallel steps inside one plan.
- Server-sent events (D6).

## Anti-goals

- The sandbox never receives an ARP API token, a model key or any other secret.
- A plan step never reads an exploration's result. Official numbers keep coming from run types only.
- No second front end: the Agent screen is a page of the existing React app.

## Design

### Phase 1. Durable dispatch (slices 1 and 2)

**Start and finish.** Each step adapter becomes two functions:
- `start(launch_key, **params) -> str | None` creates the run and returns its id. It first looks for a run whose manifest
  `params["launch_key"]` equals `launch_key` and returns that id instead of creating a second one.
- `finish(run_id, **params) -> dict` executes the run, or attaches to it, and returns the result the script sees.

The launch key is `plan:<plan_id>:v<version>:<seq>:a<attempt>`. `attempt` starts at 1 and goes up by one each time a
call with the same `(seq, kind, params)` was stored as `failed`, so a resume after a failure starts a new run (v1 AC-28
still holds). Slice 1 adds `research_plan_calls.attempt` (integer, not null, default 1); retrying a `failed` call sets
`attempt` to the previous value plus one on the same row. Synchronous kinds (`decision_score`, `index_construct`) have no run;
their `start` returns `None` and `finish` does the work as today. `report_render` starts with `create_and_plan` (the
report id is its run id) and finishes with `render_from_plan` or its storyline gate.

**Executor order.** For each call the executor:
1. records the call with status `starting` (a new status beside the existing `pending`, `running`, `awaiting_review`,
   `done`, `failed`, `cancelled`);
2. calls `start` and stores the returned run id with status `running`, in one committed write;
3. calls `finish`.

On resume, a call with the same `(seq, kind, params)`:
- with status `done`: its stored result is reused (as today);
- with status `running` and a run id: `start` is skipped and `finish(run_id)` attaches. If the run is finished, `finish`
  reads its result. If it is still pending or running, `finish` executes it again; the existing pipelines skip every
  company already stored.
- with status `starting`: `start` runs again and finds the run by its launch key if the crash came after the create.
- with status `failed`: a new attempt, with a new launch key and a new run.

**Plan worker (D1).** `arp.orchestration.plan_worker.scan(store, steps, reviewed) -> list[str]` claims plans in one pass
and returns the ids it advanced:
- a plan with status `running` whose lease nobody holds: the worker runs it (`run_plan` with `return_at_gate=True`);
- a plan with status `awaiting_review` whose waiting call `reviewed()` now accepts: the worker moves it to `running` and
  runs it.

`POST /api/plans/{id}/run` claims the plan (status `running`, as today), returns 202, and starts nothing itself. The scan
runs every `ARP_PLAN_WORKER_SECONDS` (default 5) as a scheduler started in the API lifespan, and as `arp plan worker`
(loops until stopped; `--once` does one scan and exits). `ARP_PLAN_WORKER_SECONDS=0` turns the lifespan scheduler off;
`arp plan worker` still works. The lease (`run_lease`) keeps one worker per plan across both.

### Phase 2. Catalog, more run types, templates, budget (slices 3 to 5)

**Catalog.** `arp/orchestration/capabilities.py` holds `CATALOG: list[Capability]`:
`Capability(id, summary, effect: "read" | "run", lane: "plan" | "sandbox", input_model, output_note)`.
- Plan lane, effect `run`: the 8 existing steps plus `identity_resolution(universe_run_id, companies=None)` and
  `tnfd_extraction(universe_run_id, as_of, companies=None)` (D8).
- Sandbox lane, effect `read`: `portfolio_exposure`, `smart_search`, `transition_plan`, `benchmark_sectors`, wrapping the
  four Ask tools with their existing input and card models. Each returns its card's `model_dump(mode="json")`, without
  the answer text; an omitted argument means `null`.

`STEPS`, the checker, the planner's stubs and the new route `GET /api/capabilities` all read the catalog.
`GET /api/capabilities` returns `[{id, summary, effect, lane, input_schema}]`, sandbox lane first, then plan lane, each sorted by `id`;
`input_schema` is the Pydantic JSON schema.

**Templates.** `POST /api/plans/{id}/template` with `{"name": str}` saves the plan's script when the plan is `approved`
or `done`. Templates are immutable and versioned: a second save under the same name gets version 2. The table is
`research_plan_templates(name, version, script, source_plan_id, created_by, created_at)` with key `(name, version)`.
`POST /api/plan-templates/{name}/instantiate` with `{"source": str, "version": int | null}` (null means newest) creates
a **draft** plan. Its script is the template's script with the string literal passed as `source=` to every
`universe_build` call replaced by the new `source`. The new plan stores `template_name` and `template_version`. It is
checked and dry-run like any draft, and runs only after approval. Outcomes:
- the template's script has no `universe_build` call: `422 {"detail": "template has no universe_build source to replace"}`;
- a `universe_build` call whose `source` is not a string literal: `422 {"detail": "template source is not a string literal"}`;
- several `universe_build` calls: every one of their `source` literals is replaced by the new source;
- an unknown name or version: `404 {"detail": "template not found"}`;
- a body without `version`: same as `null`.

`GET /api/plan-templates/{name}?version=<n>` (newest when omitted) returns `{name, version, script, source_plan_id,
created_by, created_at}`, or the same 404.

**Budget.** `research_plans.budget_usd` (nullable). `PUT /api/plans/{id}` accepts `{"script"?: str, "budget_usd"?:
number | null}`. A PUT with `script` behaves as today. A PUT that changes only `budget_usd` sets an `approved`, `done` or
`failed` plan to `draft`, clears its approval and keeps every stored call. `GET
/api/plans/{id}` adds `spent_usd`: the sum of `estimated_cost_usd` over the manifests of the plan's call run ids, plus
the planner's own calls. `draft_plan` and `replan_plan` already receive each call's `LLMUsage`; they now add
`estimate_cost_usd(model, usage)` of every attempt to a new column `planner_cost_usd` (default 0). `PUT` on a `running` or
`awaiting_review` plan stays `409 {"detail": "plan is already running"}`. Before `start` of each call, if
`budget_usd` is set and `spent_usd >= budget_usd`, the plan becomes `failed` with error
`budget reached: spent $<spent> of $<budget>` (two decimals) and the call is not recorded. `resume` checks the budget again before the next call, so after the
owner raises the budget (back to draft, approve) the plan continues.

### Phase 3. Agent screen (slices 6 to 8)

A new page `frontend/src/pages/Agent.tsx` at `#/agent` and `#/agent/<plan_id>`, in the nav where "Research plans" is
today, labelled "Agent". Three columns on wide screens; below 900 px the left and right columns become drawers opened
from the header.

**Left: threads and inbox.**
- *Threads*: every plan, newest first, each with its brief's first 60 characters and a status chip (`draft`,
  `approved`, `running`, `awaiting review`, `done`, `failed`, `cancelled`). Explorations (Phase 4) also appear, with
  chip `exploratory` or `accepted`.
- *Inbox*: one row per thing waiting on a person in the agent lanes, from the new `GET /api/agent/inbox`, sorted ascending by the plan's `created_at`
  (`plan_approval`), the call's `started_at` (`step_review`) or the exploration's `created_at` (`exploration`).
  Each row is `{kind, plan_id, seq, exploration_id, title, href}`:
  - `plan_approval`: a draft plan. `seq` and `exploration_id` null, `title` the brief's first 60 characters,
    `href` `#/agent/<plan_id>`.
  - `step_review`: a call `awaiting_review`. `exploration_id` null, `title` `<kind> step <seq>`, `href`
    `#/review/<run_type>/<run_id>` (the route `App.tsx` opens for a reviewable run), or `#/agent/<plan_id>` for a call
    without a run id (a report storyline).
  - `exploration`: an exploration not yet accepted. `plan_id` and `seq` null, `title` the question's first 60
    characters, `href` `#/agent/exploration/<id>`.
  Under the list, one line: `<n> more waiting in the Review Queue`, where `n` is the `total` field of `GET /api/waiting`,
  unchanged, linking to `#/review`.

**Middle: stream.** For the selected plan, in order: the brief; a script card; the dry-run steps; an approval card
(Approve, Edit) while the plan is a draft; one step card per stored call (kind, status, run link, cost); a failure card
with Re-plan for a failed plan. A composer at the bottom drafts a new plan from a brief (`POST /api/plans`) and selects
it. With "Explore" toggled on (Phase 4), the composer sends the text to the sandbox lane instead.

**Right: stage tabs.**
- *Script*: the current script, read-only, with line numbers.
- *Diff*: the dry-run steps against the stored calls (planned, started, skipped); after a re-plan, also a line diff of
  the previous script against the current one (from `previous_scripts`), headed `-<a> +<b>` with the counts of removed
  and added lines.
- *Audit*: one row per call: `seq`, `kind`, `params`, `run_id`, `started_at`, `status`, model, `estimated_cost_usd`;
  above it, `approved_by` and `approved_at`, and the budget line `spent $x of $y`.
- *Mini-app* (Phase 5).

While the selected plan is `running` or `awaiting_review`, the screen re-reads `GET /api/plans/{id}` and the inbox every
3 s (D6).

### Phase 4. Sandbox lane (slices 9 and 10)

**Runtime (D3).** `sandbox/` is a Node 22 service with `@cloudflare/codemode` and `workerd`. ARP's backend calls it on
`ARP_SANDBOX_URL` (default `http://127.0.0.1:8790`). Each execution runs in a fresh isolate with
`globalOutbound: null`: sockets and the file system are unavailable inside it, and the isolate's `fetch` throws
`Error("network access is not allowed")`. The isolate sees one object,
`codemode`, a Proxy: any method name is sent to the host worker. A name outside the sandbox lane rejects with
`Error("<id> is not available in the sandbox")` without calling ARP. A method call leaves the isolate as RPC to the host worker,
which calls ARP's `POST /api/sandbox/tools/{capability_id}` with a per-execution token. The token is minted by the
backend for that execution, valid for its capability list and `ARP_SANDBOX_TOKEN_SECONDS` (default 60), and never
passed into the isolate. A capability that is not in the sandbox lane has no route: `404`.

**Limits.** Each breach stores the exploration with `status: "failed"` (or `timeout`) and the error shown:
- wall time 30 s: `status: "timeout"`;
- at most 50 capability calls: `capability call limit 50 exceeded`;
- result at most 262 144 bytes as UTF-8 JSON: `result exceeds 256 KB`;
- code at most 400 lines, checked before it runs: `code exceeds 400 lines`;
- a call to a capability outside the sandbox lane: `<id> is not available in the sandbox`.

`POST /api/agent/explorations` answers HTTP 200 with the stored row in every one of these cases.

**Exploration flow.** `POST /api/agent/explorations` with `{"question": str}`:
1. One `LLMClient` call (D7) writes the code. It receives the sandbox capabilities as TypeScript declarations generated
   from the catalog, and returns `{code}`. Code that fails to parse gets one retry with the parse error; a second
   failure stores `status: "failed"` with `code does not parse: <error>`.
2. The sandbox runs it.
3. The result is stored in `agent_explorations(id, question, code, status, result, error, tool_calls, model, cost_usd,
   created_at, accepted_by, accepted_at)`. `status` is `done`, `failed` or `timeout`. `tool_calls` is
   `[{capability_id, args, result_bytes}]`.

The response is the stored row plus `"label": "exploratory"`. `POST /api/agent/explorations/{id}/accept` sets
`accepted_by` and `accepted_at`, and the label becomes `accepted`. In the stream an exploration shows as a card with the
question, the code (collapsed), the result as a table when it is a list of flat objects (JSON otherwise), the tool
calls, and a badge `Exploratory: not reviewed` until accepted.

### Phase 5. Mini-apps (slice 11)

A done exploration has a "Show as mini-app" action, which calls `POST /api/agent/explorations/{id}/miniapp`. One
`LLMClient` call writes a single HTML file that reads its data
from `window.ARP_DATA` (the exploration's stored result, injected by the screen) and may compute nothing it then labels
as an ARP figure. It is stored on the exploration as `miniapp_html`, and the route returns the exploration. A
not-done exploration answers `409 {"detail": "only a done exploration can be shown as a mini-app"}`. The stage renders it in
`<iframe sandbox="allow-scripts" srcdoc=...>`, with the HTML wrapped in a page whose CSP is
`default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:`. The page accepts one
message from the frame, `{"action": "ask", "text": str}`, which puts `text` in the composer without sending it; it
ignores every other message.

## Fixtures

- **P3** (unit tests only): the script `u = universe_build(taxonomy_id="t", source="s.csv")`,
  `e = extraction(universe_run_id=u.run_id, schema_id="x")`, `r = report_render(source_ids=[e.run_id])`, with stub
  start and finish functions injected for those three kinds, the way today's executor tests inject steps. `s1`, `s2`,
  `s3` below mean the stubs for seq 1, 2 and 3, and `reviewed` is the injected review check. Each stub's `start` returns `r_<seq>` and writes a run manifest with that id, its launch
  key and the `estimated_cost_usd` the row names; each stub counts its `start` and `finish` calls.
- **Demo plan**: `arp plan seed-demo` (exists), a draft with 4 dry-run steps, for the API and browser rows.
- **Stand-ins**: `backend/scripts/e2e_stack.sh up` starts the real `sandbox/` service (slice 9 adds it) with
  `ARP_STANDINS_DIR` set. Exploration code comes from `$ARP_STANDINS_DIR/explore.json`, shaped
  `{"<question>": [{"code": "<js>"}, ...]}`: entry 1 answers the first attempt, entry 2 the retry. Each exploration
  model call logs `{"kind": "model", "name": "ExplorationCode", "question": "<question>"}` to `calls.jsonl`. Mini-app HTML from
  `$ARP_STANDINS_DIR/miniapp.json`, shaped `{"<exploration question>": {"html": "<html>"}}`. Both are read on every call
  through `arp/standins.py`, which logs each call to `calls.jsonl`.
- **Superseded tests**: slice 1 adapts the step stubs in `backend/tests/test_plan_executor_pg.py` (`Stubs.step`) and the
  adapter cases in `backend/tests/test_plan_steps_pg.py` to start and finish, without changing what they assert. Slice 2
  adapts the tests in `backend/tests/test_plan_api_pg.py` that wait for `POST /run` to drive a plan
  (`test_run_then_second_run_refused_then_cancel`, `test_cli_run_refused_while_running`) to call `scan()` after the 202.
  Slice 6 replaces `frontend/tests/plans.test.ts` with tests of the Agent screen, and each PR lists
  every retired case with the row or new test that replaces it.

## Acceptance

Superseded: no v1 or v2 row is retired. v1 rows that say a plan runs after `POST /run` (AC-18 to AC-32 through the API)
now hold once the worker has scanned; their tests are adapted as listed under Fixtures.

Rows that need stub steps (P3) or forced crashes are `unit`: the app started by `e2e_stack.sh` runs the real steps.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | P3 approved; `s2.finish` raises `SystemExit` once | `run_plan` | call seq 2 is stored with `status: "running"` and `run_id: "r_2"` | unit |
| AC-2 | Same plan after AC-1 | `run_plan` again | `s2.start` was called 1 time in total; call seq 2 `run_id` is `r_2`; plan `status: "done"` | unit |
| AC-3 | P3 approved; `s2.start` writes the manifest for `r_2` with launch key `plan:<id>:v1:2:a1`, then raises `SystemExit` once; `run_plan` exited | `run_plan` again | exactly 1 manifest has that launch key; call seq 2 `run_id` is `r_2`; plan `status: "done"` | unit |
| AC-3b | P3 approved; `s2.start` raises `RuntimeError` once; `run_plan` returned `failed` | `run_plan` again | call seq 2 has `attempt: 2`; `s2.start` was called 2 times; 2 manifests exist with launch keys ending `:2:a1` and `:2:a2` | unit |
| AC-4 | `ARP_PLAN_WORKER_SECONDS=0`; P3 with status `running`, no lease held | `scan()` once | returns `[<id>]`; afterwards plan `status: "done"` | unit |
| AC-5 | `ARP_PLAN_WORKER_SECONDS=0`; P3 `awaiting_review` at seq 2; `reviewed` returns True for call seq 2 | `scan()` once | call seq 3 stored; plan `status: "done"` | unit |
| AC-6 | `ARP_PLAN_WORKER_SECONDS=0`; P3 `awaiting_review` at seq 2; `reviewed` returns False for call seq 2 | `scan()` once | returns `[]`; plan `status: "awaiting_review"`; no call seq 3 stored | unit |
| AC-7 | `ARP_PLAN_WORKER_SECONDS=0`; P3 `running`; two `scan()` calls started at the same time | both return | each stub's `start` was called exactly 1 time | unit |
| AC-8 | Demo plan approved (`POST /api/plans/{id}/approve`) | `POST /api/plans/{id}/run` | HTTP 202, body `{"plan_id": "<id>", "status": "running"}` | holdout |
| AC-8b | `ARP_PLAN_WORKER_SECONDS=0`; P3 approved | `POST /api/plans/{id}/run`, then wait 2 s | `GET /api/plans/{id}` shows `status: "running"` and `calls: []` | unit |
| AC-9 | `ARP_PLAN_WORKER_SECONDS=0`; P3 after `POST /run` returned 202 | `arp plan worker --once` | exit 0; plan `status: "done"` | unit |
| AC-10 | Must not change: the v1 orchestrator rows AC-1 to AC-36 and the v2 re-plan rows | `python3 -m pytest backend/tests/test_plan_api_pg.py backend/tests/test_plan_executor_pg.py backend/tests/test_plan_replan_pg.py backend/tests/test_plan_store_pg.py backend/tests/test_plan_script.py backend/tests/test_plan_steps_pg.py` | passes; the only edited tests are the ones listed under Fixtures, and the PR lists each edit | unit |
| AC-11 | The app | `GET /api/capabilities` | HTTP 200; ids in this order: `benchmark_sectors`, `portfolio_exposure`, `smart_search`, `transition_plan`, `decision_score`, `document_discovery`, `extraction`, `financials_extraction`, `identity_resolution`, `index_construct`, `report_render`, `tnfd_extraction`, `universe_build`, `xbrl_facts` | holdout |
| AC-12 | Same | `GET /api/capabilities` | the first 4 entries have `lane: "sandbox"`, `effect: "read"`; the other 10 have `lane: "plan"`, `effect: "run"` | holdout |
| AC-13 | A script calling `smart_search(query="x")` | `arp plan check s.py` | exit 1, stdout contains `line 1: call to smart_search not allowed` | holdout |
| AC-14 | A script `u = universe_build(taxonomy_id="t", source="s.csv")` then `identity_resolution(universe_run_id=u.run_id)` | `arp plan check s.py` | exit 0, stdout `ok` | holdout |
| AC-15 | A script calling `tnfd_extraction(universe_run_id="r", as_of="2025-12-31", foo=1)` | `arp plan check s.py` | exit 1, stdout contains `line 1: tnfd_extraction: unexpected argument foo` | holdout |
| AC-16 | The planner with a stand-in model | `arp plan draft "x"` | the system prompt logged in `calls.jsonl` contains `def identity_resolution(` and `def tnfd_extraction(` and not `def smart_search(` | holdout |
| AC-17 | Demo plan approved | `POST /api/plans/{id}/template` `{"name": "grid_ac17"}` | HTTP 200, body has `name: "grid_ac17"`, `version: 1`, `source_plan_id: <id>` | holdout |
| AC-18 | An approved plan saved as `grid_ac18` (version 1) | save a second approved plan as `grid_ac18` | body has `version: 2`; `GET /api/plan-templates/grid_ac18?version=1` returns the first plan's script unchanged | holdout |
| AC-19 | A draft plan | `POST /api/plans/{id}/template` `{"name": "grid_ac19"}` | HTTP 409, `{"detail": "only an approved or done plan can be saved as a template"}` | holdout |
| AC-20 | Template `grid_ac20` v1 saved from the approved demo plan, whose `universe_build` passes the literal `source="<S>"` | `POST /api/plan-templates/grid_ac20/instantiate` `{"source": "us_listed.csv"}` | HTTP 200; new plan `status: "draft"`, `template_name: "grid_ac20"`, `template_version: 1`; its script equals the template's with `"<S>"` replaced by `"us_listed.csv"` and no other change | holdout |
| AC-21 | The plan from AC-20 | `POST /api/plans/{id}/run` | HTTP 409, `{"detail": "plan is not approved"}` | holdout |
| AC-22 | A template saved from a script with no `universe_build` call | instantiate it | HTTP 422, `{"detail": "template has no universe_build source to replace"}` | unit |
| AC-22b | No template `nope` | `POST /api/plan-templates/nope/instantiate` `{"source": "x.csv"}` | HTTP 404, `{"detail": "template not found"}` | holdout |
| AC-22c | A template whose `universe_build` passes `source=name` (a variable) | instantiate it | HTTP 422, `{"detail": "template source is not a string literal"}` | unit |
| AC-23 | P3 with `budget_usd: 1.00`; manifest `r_1` has `estimated_cost_usd: 1.20` | `run_plan` | plan `status: "failed"`, `error: "budget reached: spent $1.20 of $1.00"`; no call seq 2 stored | unit |
| AC-24 | P3 with `budget_usd: 5.00`; manifests cost 1.20, 0.30, 0.50; `planner_cost_usd: 0.05` | `GET /api/plans/{id}` after done | `spent_usd: 2.05` | unit |
| AC-24b | The plan from AC-23 | `PUT` `{"budget_usd": 5}`, approve, `run_plan` | plan `status: "done"`; `s1.start` was called 1 time in total | unit |
| AC-25 | Demo plan approved | `PUT /api/plans/{id}` `{"budget_usd": 3}` | `GET` shows `status: "draft"`, `budget_usd: 3`, `approved_by: null` | holdout |
| AC-25b | A plan with status `running` | `PUT /api/plans/{id}` `{"budget_usd": 3}` | HTTP 409, `{"detail": "plan is already running"}` | unit |
| AC-26 | P3 with `budget_usd: null`; manifests cost 100.00 each | `run_plan` | plan `status: "done"` | unit |
| AC-26b | Injected planner usage: model `claude-sonnet-5-5`, 1 000 000 input and 100 000 output tokens, one attempt | `draft_plan` | the stored plan has `planner_cost_usd: 3.00` (at $2 / $10 per 1M) | unit |
| AC-27 | Demo plan | open `#/agent` | the left column lists the demo plan's thread with chip `draft` | evaluator |
| AC-28 | Demo plan selected | look at the stream | a script card, 4 dry-run step rows and an approval card with buttons `Approve` and `Edit` | evaluator |
| AC-29 | Demo plan selected | click `Approve` | the thread's chip reads `approved`; the approval card is gone; the Audit tab shows the signed-in user as approver | evaluator |
| AC-29b | Demo plan selected | open the Script tab | the demo script, read-only, with line numbers from 1 to its last line | evaluator |
| AC-30 | No other drafts, waiting calls or explorations; draft plan A created before plan B's call seq 2 started; plan B `awaiting_review` at seq 2 on run `r_2` of type `extraction` | `GET /api/agent/inbox` | exactly 2 rows: `{kind: "plan_approval", plan_id: A, seq: null, exploration_id: null, href: "#/agent/A"}` then `{kind: "step_review", plan_id: B, seq: 2, exploration_id: null, href: "#/review/extraction/r_2"}` | unit |
| AC-31 | `GET /api/waiting` returns `total: 7` | open `#/agent` | the inbox footer reads `7 more waiting in the Review Queue` and links to `#/review` | evaluator |
| AC-32 | A plan re-planned once (version 2) | open its Diff tab | the header reads `-<a> +<b>`, where a and b count the lines starting `-` and `+` (headers excluded) in `diff -u` of the version 1 and version 2 scripts | evaluator |
| AC-33 | A done plan with 3 calls | open its Audit tab | 3 rows, each showing seq, kind, run id, status and cost equal to `GET /api/plans/{id}` `calls` | evaluator |
| AC-34 | A running plan selected; a call changes from `running` to `done` | wait 4 s | that step card shows `done` without a page reload | evaluator |
| AC-35 | Stand-in planner | type a brief in the composer and press Enter | a new thread appears at the top of the list, selected, with chip `draft` | evaluator |
| AC-36 | Viewport 390 px wide | open `#/agent/<demo>` | the stream fills the width; no horizontal page scroll; header buttons open the threads and the stage as drawers | evaluator |
| AC-37 | Any plan | open `#/plans/<id>` | the address becomes `#/agent/<id>` and that plan is selected | evaluator |
| AC-38 | The nav | open the Runs group | it shows `Agent` and no `Research plans` | evaluator |
| AC-39 | Stand-in code `return await codemode.benchmark_sectors({})` | `POST /api/agent/explorations` | HTTP 200; `status: "done"`; `label: "exploratory"`; `result` equals `BenchmarkCard.model_dump(mode="json")` of the card `ask.benchmark_sectors` returns for `benchmark_id: null` (the sample card, `is_sample: true`), without its text | holdout |
| AC-40 | Stand-in code `return await fetch("https://example.com")` | same | HTTP 200; `status: "failed"`; `error` contains `network access is not allowed` | holdout |
| AC-41 | Stand-in code `while (true) {}` | same | HTTP 200 within 35 s; `status: "timeout"` | holdout |
| AC-42 | Stand-in code making 51 `codemode.smart_search` calls in a loop | same | HTTP 200; `status: "failed"`; `error` contains `capability call limit 50 exceeded`; `tool_calls` has 50 rows | holdout |
| AC-43 | Stand-in code `return typeof process + "," + typeof globalThis.ARP_TOKEN` | same | HTTP 200; `result` is `"undefined,undefined"` | holdout |
| AC-44 | Stand-in code returning a string of 300 000 ASCII characters | same | HTTP 200; `status: "failed"`; `error` contains `result exceeds 256 KB` | holdout |
| AC-45 | Stand-in code `return await codemode.universe_build({})` | same | HTTP 200; `status: "failed"`; `error` contains `universe_build is not available in the sandbox` | holdout |
| AC-45b | Stand-in code of 401 lines | same | HTTP 200; `status: "failed"`; `error` contains `code exceeds 400 lines`; `tool_calls: []` | holdout |
| AC-45c | Stand-in codes: first `return (`, then `return 1` | same | HTTP 200; `status: "done"`; `result: 1`; `calls.jsonl` has 2 lines with `name: "ExplorationCode"` and that question | holdout |
| AC-46 | A valid execution token minted in the test | `POST /api/sandbox/tools/universe_build` | HTTP 404 | unit |
| AC-47 | `ARP_SANDBOX_TOKEN_SECONDS=1`; a token minted 2 s ago | `POST /api/sandbox/tools/smart_search` with it | HTTP 401 | unit |
| AC-48 | A done exploration | `POST /api/agent/explorations/{id}/accept` as `alice` | `GET` shows `label: "accepted"`, `accepted_by: "alice"`, non-null `accepted_at` | holdout |
| AC-49 | An exploration not yet accepted | open it in the stream | the card shows the badge `Exploratory: not reviewed` | evaluator |
| AC-50 | An exploration E not yet accepted | `GET /api/agent/inbox` | exactly 1 row has `exploration_id: E`, and it equals `{kind: "exploration", plan_id: null, seq: null, exploration_id: E, href: "#/agent/exploration/E"}` | holdout |
| AC-51 | Golden file of 10 questions, each with the capabilities its code must call; a case passes if the code runs to `done` and calls each listed capability at least once | `arp agent golden --cases tests/golden/explore.jsonl --min-pass 8` | exit 0 | golden |
| AC-52 | Must not change: a script `x = exploration` | `arp plan dry-run s.py` | exit 1, stdout contains `line 1: name exploration is not defined` | holdout |
| AC-53 | Must not change: the v1 checker rows AC-1 to AC-8 | `python3 -m pytest backend/tests/test_plan_script.py` | passes with no test edited | unit |
| AC-54 | A done exploration; stand-in mini-app HTML | click `Show as mini-app` | the Mini-app tab opens and shows the frame; `GET` of the exploration has non-null `miniapp_html` | evaluator |
| AC-54b | An exploration with `status: "failed"` | `POST /api/agent/explorations/{id}/miniapp` | HTTP 409, `{"detail": "only a done exploration can be shown as a mini-app"}` | holdout |
| AC-54c | A done exploration with `miniapp_html` stored | open its Mini-app tab | the iframe's `sandbox` attribute is exactly `allow-scripts` | evaluator |
| AC-55 | No other page open; stand-in mini-app HTML that calls `fetch("/api/plans")` and shows the outcome | open its Mini-app tab | the frame shows the fetch failed; the API access log has no `GET /api/plans` from opening the tab until 5 s later | evaluator |
| AC-56 | Mini-app HTML that posts `{"action": "ask", "text": "why sector X?"}` | it loads | the composer contains `why sector X?`; no new thread appears | evaluator |
| AC-57 | Mini-app HTML that posts `{"action": "run", "plan_id": "<demo>"}` | it loads | the demo plan's status is unchanged and the composer is empty | evaluator |
| AC-58 | Must not change: the backend suite apart from the cases slice 1 retires openly | `python3 -m pytest` | passes | unit |
| AC-59 | Must not change: the frontend suite apart from the cases slice 6 retires openly | `npm test` | passes | unit |

Must not change: v1 and v2 plan behaviour (AC-10, AC-53), the plan language (AC-52), both suites (AC-58, AC-59).

## Slices

Each PR puts `Spec: agent-panel-code-mode` and its `Rows:` line in its description.

| Slice | PR contents | Risk | Rows |
|---|---|---|---|
| 1 | Start and finish adapters, launch keys with attempts, `starting` status, executor order | `risk:high` (schema) | AC-1, AC-2, AC-3, AC-3b, AC-10, AC-58 |
| 2 | Plan worker: `scan()`, lifespan scheduler, `ARP_PLAN_WORKER_SECONDS`, `arp plan worker`, `POST /run` hands over | `risk:normal` | AC-4, AC-5, AC-6, AC-7, AC-8, AC-8b, AC-9, AC-10, AC-58 |
| 3 | Capability catalog, `GET /api/capabilities`, `identity_resolution` and `tnfd_extraction` steps | `risk:normal` | AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-53, AC-58 |
| 4 | Plan templates: table, save, get, instantiate | `risk:high` (schema) | AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-22b, AC-22c, AC-58 |
| 5 | Plan budget: columns, planner cost, `spent_usd`, stop before a step | `risk:high` (schema) | AC-23, AC-24, AC-24b, AC-25, AC-25b, AC-26, AC-26b, AC-58 |
| 6 | Agent screen shell: threads, stream, approval card, composer, Script tab, nav and redirect | `risk:normal` | AC-27, AC-28, AC-29, AC-29b, AC-35, AC-36, AC-37, AC-38, AC-59 |
| 7 | Inbox endpoint and column | `risk:normal` | AC-30, AC-31, AC-58, AC-59 |
| 8 | Stage tabs: Diff, Audit; 3 s refresh | `risk:normal` | AC-32, AC-33, AC-34, AC-59 |
| 9 | `sandbox/` service, tool route and tokens, limits, `e2e_stack.sh` starts it | `risk:high` (secrets, auth) | AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-45b, AC-46, AC-47, AC-58 |
| 10 | Explorations: model call and retry, table, accept, stream card, inbox rows, golden set | `risk:high` (schema) | AC-39, AC-45c, AC-48, AC-49, AC-50, AC-51, AC-52, AC-58, AC-59 |
| 11 | Mini-apps: route, generation, iframe, message bridge | `risk:high` (security boundary) | AC-54, AC-54b, AC-54c, AC-55, AC-56, AC-57, AC-58, AC-59 |

Slices go in this order. Slices 3 to 5 may run in parallel after slice 2; slices 6 to 8 need slice 2; slice 10 needs 9;
slice 11 needs 10.

## Later (own specs)

- **OpenShell hardening (D5).** Run `sandbox/` inside NVIDIA OpenShell with a deny-all egress policy except the ARP API
  host, and gateway secret injection. Entry: a spike on the `arp-gcp` deployment shows OpenShell's kernel needs
  (Landlock, seccomp) are met where the sandbox will run. Exit rows: egress to an unlisted host is blocked at the OS
  layer and logged.
- **Write actions from the agent.** A sandbox call that proposes a run would create a draft plan for approval, never
  start one.
- **Workspaces and grants**, once ARP has a second user.

## Defaults decided without the owner

- Launch key format `plan:<plan_id>:v<version>:<seq>:a<attempt>`, stored in run manifest `params["launch_key"]`.
- Worker interval 5 s; panel refresh 3 s; tool token lifetime 60 s (`ARP_SANDBOX_TOKEN_SECONDS`).
- Sandbox limits: 30 s, 50 calls, 262 144-byte result, 400 lines.
- `ARP_SANDBOX_URL` default `http://127.0.0.1:8790`.
- `@cloudflare/codemode` and `workerd` pinned to the newest release more than two weeks old when slice 9 starts.
- Template parameters: only `universe_build`'s `source`. More parameters need a new spec.
- The Agent screen breaks to one column with drawers below 900 px.

## Watch

- Some pipelines must find a run by its launch key. If `RunStore.list_runs` cannot filter on `params`, slice 1 adds a
  lookup instead of scanning every manifest.
- `@cloudflare/codemode` targets the Workers runtime. If it cannot run on plain `workerd` with a Worker Loader binding,
  slice 9 stops and raises `factory:blocked` with the finding. That is a spec question, not a builder's choice.
