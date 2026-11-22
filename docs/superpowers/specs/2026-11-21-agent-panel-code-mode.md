# Agent panel and Code Mode roadmap

Slug: agent-panel-code-mode

Risk: this spec PR is `risk:low`. The build is size L, delivered as 14 PRs (see `## Slices`); each slice names its own
risk label.

Status: **approved by the owner on 21 Nov 2026** (button in the spec session, after three spec-critic rounds; decisions D1–D8 as recommended). Slice 12 (write actions, D9, AC-60 to AC-67)
added on 21 Nov 2026 at the owner's request, **approved by the owner on 21 Nov 2026** (button, after three spec-critic rounds).
Phase 7 (Ask in the Agent screen, D10 to D13, AC-68 to AC-81, slices 13 and 14, amended AC-31 and AC-35) added on
22 Nov 2026 at the owner's request ("Do it", project chat, on merging Ask ARP into the Agent screen), **approved by the owner on 22 Nov 2026** (button, after six spec-critic rounds).
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
| D9 | A **write action** is a button a person presses: "Turn into a plan…" on an accepted exploration drafts a plan with the planner. The plan is a draft and runs only after Approve. The sandbox itself still cannot create anything (D4 holds). | Yes (AC-60 to AC-67) | A sandbox capability `propose_plan` that model code may call; drafts then appear without a click, which needs a cap per exploration and its own rows. |
| D10 | **Ask threads are stored** in a new table `agent_asks`; a follow-up in a thread sends the thread id and the server builds the history from that thread's stored asks. | Yes (AC-68 to AC-72) | The browser keeps the history as the Ask panel does today (session storage); a reload or another device loses the thread. |
| D11 | A **bigger question grows inside its ask thread**: every answered ask has `Draft a plan` (slice 13) and `Explore` (slice 14). The new plan or exploration records `source_ask_id`, shows as a linked card under that answer, and keeps its own thread row for its approval and review cards. | Yes (AC-73 to AC-77b, AC-80 to AC-81b) | The whole plan stream (script, approval, steps) is embedded inside the ask thread, and the plan gets no row of its own. |
| D12 | **The Ask panel goes.** Ctrl/⌘J and the palette's `Ask ARP: "…"` option open the Agent screen and send the text as a new ask thread. `POST /api/ask` stays for API callers, unchanged. | Yes (AC-70, AC-75 to AC-76b) | `POST /api/ask` is removed too; any script calling it breaks. |
| D13 | The composer gets a **mode switch** `Ask`, `Plan`, `Explore` (Explore from slice 10), default `Ask`. | Yes (AC-35, AC-74, AC-78) | Default `Plan`, as the composer behaves today; a question typed in the composer then drafts a plan. |

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
| Ask ARP | `api/routers/ask.py` (`POST /api/ask`, model routes to one tool), `components/AskPanel.tsx`, `AskCards.tsx`, `lib/askHistory.ts` (history in session storage) | Asks become threads on the Agent screen (Phase 7); the panel goes |
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
- G8. An accepted exploration can be turned into a draft plan by a person, so a finding becomes a reviewed run.
- G9. Every question asked through the top bar, Ctrl/⌘J or the Agent composer opens as a thread on the Agent screen.
  Questions, explorations and plans share one history, and there is no separate Ask panel. `POST /api/ask` and the Ask
  the Portfolio page stay as they are.

## Non-goals

- Multi-user workspaces, memberships and source grants (the Markdown plan's P1). ARP has one owner today.
- Writes from the sandbox: no run starts, no edits, no publishing. Slice 12's write action is a person's click on the
  screen, not a sandbox call.
- Webhook and cron triggers for agents.
- Claude-hosted Programmatic Tool Calling.
- Parallel steps inside one plan.
- Server-sent events (D6).

## Anti-goals

- The sandbox never receives an ARP API token, a model key or any other secret.
- A plan step never reads an exploration's result. Official numbers keep coming from run types only. The planner may
  see an accepted exploration as context when a person turns it into a plan (slice 12); the script it writes still
  cannot reference it (AC-52).
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
- Sandbox lane, effect `read`: the four tools Ask ARP routes to (`api/routers/ask.py`), called directly instead of
  through Ask's routing call. Each returns the `model_dump(mode="json")` of what the wrapped function returns, without
  answer text; an omitted argument means `null`:

  | Capability | Arguments | Wraps | Returns | Model call |
  |---|---|---|---|---|
  | `benchmark_sectors` | `{benchmark_id: string \| null}` | `ask.benchmark_sectors` | `BenchmarkCard` | none |
  | `transition_plan` | `{company: string \| null}` | `ask.newest_transition_plan` | `TransitionPlanCard` | none |
  | `portfolio_exposure` | `{question: string}` | `qa_agent.answer_question` | its answer model | one `LLMClient` call |
  | `smart_search` | `{question: string}` | `smart_search.smart_search` | `SearchAnswer` | one `LLMClient` call |

  The tool route acts as the principal who asked for the exploration, carried in its token.

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
    `#/review/<manifest run_type>/<run_id>` (the route `App.tsx` opens for a reviewable run), except
    `#/agent/<plan_id>` when the call's kind is `report_render` (its gate is the report storyline).
  - `exploration`: an exploration not yet accepted. `plan_id` and `seq` null, `title` the question's first 60
    characters, `href` `#/agent/exploration/<id>`.
  Under the list, one line: `<n> more waiting in the Review Queue`, where `n` is the `total` field of `GET /api/waiting`,
  unchanged, linking to `#/review`.

**Middle: stream.** For the selected plan, in order: the brief; a script card; the dry-run steps; an approval card
(Approve, Edit) while the plan is a draft; one step card per stored call (kind, status, run link, cost); a failure card
with Re-plan for a failed plan. A composer at the bottom drafts a new plan from a brief (`POST /api/plans`) and selects
it. With "Explore" toggled on (Phase 4), the composer sends the text to the sandbox lane instead. Phase 7 replaces both
with a mode switch (D13): `Ask` (default) sends a question, `Plan` drafts a plan as above, `Explore` sends the text to
the sandbox lane.

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

**Code checks.** The `sandbox/` service checks code before it runs: first lines (`code.split("\n").length` at most 400),
then a parse with `acorn` (pinned like `workerd`). The same check is exposed as `POST /check` (`{code}` →
`{ok, error}`) for the backend's retry.

**Exploration flow.** `POST /api/agent/explorations` with `{"question": str}`:
1. One `LLMClient` call (D7) writes the code. It receives the sandbox capabilities as TypeScript declarations generated
   from the catalog, and returns `{code}`. Code that fails to parse gets one retry with the parse error; a second
   failure stores `status: "failed"` with `code does not parse: <error>`.
2. The sandbox runs it.
3. The result is stored in `agent_explorations(id, question, code, status, result, error, tool_calls, model, cost_usd,
   created_at, accepted_by, accepted_at)`. `status` is `done`, `failed` or `timeout`. `tool_calls` is
   `[{capability_id, args, result_bytes}]`.

The response is the stored row plus `"label": "exploratory"`. `GET /api/agent/explorations` lists them newest first in
the same shape; `GET /api/agent/explorations/{id}` returns one, or `404 {"detail": "exploration not found"}`. `POST /api/agent/explorations/{id}/accept` sets
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

### Phase 6. Write action: exploration to draft plan (slice 12)

An accepted exploration has a "Turn into a plan…" action in its stream card (D9). It opens a field for a brief,
prefilled with the exploration's question, and a "Draft plan" button, which calls
`POST /api/agent/explorations/{id}/plan` with the body model `ExplorationPlanRequest(brief: str | None = None)`:

1. An unknown id answers `404 {"detail": "exploration not found"}`. An exploration whose `status` is not `done`, or
   whose `accepted_at` is null, answers `409 {"detail": "only an accepted exploration can become a plan"}`. Both
   conditions are checked; the accept route is not changed.
2. `brief` missing, `null`, or empty after stripping whitespace means the exploration's question.
3. The route calls the existing `draft_plan` exactly as `POST /api/plans` does (`_context()` and
   `check=_check_sources`), except that `context` is `_context()` followed by `"\n\n" + exploration_context`, where
   `exploration_context = f"From exploration {id}, question: {question}\nResult:\n{json_text}"` and
   `json_text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))`. If `json_text` is over 20 000 bytes
   as UTF-8, it is cut to the longest prefix of whole characters that fits in 20 000 bytes, followed by
   `"\n(result truncated at 20000 bytes)"`. A `json_text` of 20 000 bytes or less is passed whole, with no such line.
4. `research_plans` gets `source_exploration_id`, nullable, the same type as `agent_explorations.id`, a foreign key to
   it with no cascade. `draft_plan` and `PlanStore.create` take an optional `source_exploration_id`, written in the
   same insert. Plans drafted any other way have it `null`; `GET /api/plans` and `GET /api/plans/{id}` show the field
   on every plan. The new plan keeps `status: "draft"` and `approved_by: null`, and the route returns it as
   `GET /api/plans/{id}` does.
5. A planner rejection answers `422 {"detail": "<the checker's errors>"}` as `POST /api/plans` does today, and
   stores no plan.

Nothing else changes: the plan worker skips drafts, so no call is stored and no run starts until a person approves.

On the screen, `Draft plan` is disabled while the request runs. On a 200 the screen selects the new thread; its brief
card shows a line `From exploration: <question>` linking to `#/agent/exploration/<id>`. On any other status the field
stays open with the response's `detail` shown under it. An exploration that is not both `done` and accepted shows no
"Turn into a plan…" action.

### Phase 7. Ask in the Agent screen (slices 13 and 14)

Ask ARP today is a panel beside every page that routes one question to one read-only tool and keeps its history in
session storage. Phase 7 makes every question a thread on the Agent screen (G9).

**Ask threads (D10).** A new table `agent_asks(id text primary key, thread_id text, question text, standalone_question
text, tool text, response jsonb, error text, asked_by text, created_at timestamptz)`. `id` is a new UUID4 string, stored
as `text` like `research_plans.id`. A thread's id is the `id` of its first ask, the one ask whose `thread_id` equals its own `id`. A `thread_id` must
equal such an id; any other value, including the `id` of a follow-up ask or a string that is not a UUID, answers
`404 {"detail": "ask thread not found"}`. A `source_ask_id` may name any ask; one that names no ask answers
`404 {"detail": "ask not found"}`.
The routing and tool code of `POST /api/ask` moves into one function in `ask.py` that both routes call; `POST /api/ask`
answers exactly as before (AC-70).

- `POST /api/agent/asks`, body `AgentAskRequest(question, thread_id: str | None = None)`, `question` with the same
  constraints as `AskRequest.question` (stripped, 1 to 1000 characters).
  - A `thread_id` with no ask answers `404 {"detail": "ask thread not found"}` and stores nothing.
  - The history is the thread's newest 5 asks whose `tool` is not null, oldest first, as `HistoryTurn`s, with each
    turn's `question` and `standalone_question` cut to their first 1000 characters, as `historyFor` does today. Asks
    that failed are never sent.
  - On success the row stores `tool`, `standalone_question`, `response` (the `AskResponse` as JSON) and `error: null`.
  - When the model call or the tool fails, the row stores `tool: null`, `standalone_question: null`, `response: null`
    and `error: "Ask could not answer this question. Try again."`, and the route still answers HTTP 200 with it.
  - The route returns the stored row as `AgentAsk {id, thread_id, question, standalone_question, tool, response,
    error, asked_by, created_at, plans, explorations}`; `asked_by` is the signed-in user's `user_id` (`dev` in the e2e
    app).
  - Every call that reaches the model leaves one audit row through `qa_audit.record_answer`, exactly as `POST /api/ask`
    does, and a call answered 403, 404 or 422 leaves none: `endpoint` is
    `ask.<routed tool>` once the model has routed, also when the tool then raises (the stored row still has
    `tool: null`), and `ask.error` when the routing call itself fails.
  - Like every route behind `authorize`, a viewer may read (`GET` answers 200) and `POST /api/agent/asks` answers
    `403` for a viewer.
- `GET /api/agent/asks?thread_id=<id>`: the thread's asks, oldest first, as `AgentAsk`; an unknown thread answers
  `404 {"detail": "ask thread not found"}`.
- `GET /api/agent/ask-threads`: one row per thread, newest first by its first ask's `created_at`:
  `{thread_id, title, status, created_at, asks}`. `title` is the first question's first 60 characters, `status` is
  `answered` when the thread's newest ask has `error: null` and `failed` otherwise, `asks` is the number of asks.
- `plans` on an `AgentAsk` is `[{plan_id, brief, status}]` for every plan whose `source_ask_id` is that ask, oldest
  first; `explorations` is `[{exploration_id, question, status, label}]` likewise. Both keys are always present and `[]`
  when none; `explorations` is always `[]` until slice 14.

**From an answer to a plan or an exploration (D11).**
- `research_plans` gets `source_ask_id text NULL REFERENCES agent_asks(id)`, with no cascade. Because the additive
  reconciliation in `storage/postgres_schema.py` adds a column without its foreign key, slice 13 adds a step there that
  creates the constraint on an existing database when it is missing (slice 14 does the same for `agent_explorations`). `POST /api/plans`
  takes an optional `source_ask_id` in its body; an id with no ask answers `404 {"detail": "ask not found"}` and drafts
  nothing. `GET /api/plans` and `GET /api/plans/{id}` show the field on every plan, `null` when unset, and next to it
  `source_ask: {question, thread_id}` of that ask, or `null`. Nothing else in drafting changes.
- Slice 14 gives `agent_explorations` the same column (`text`, same foreign key), `POST /api/agent/explorations` the
  same optional field and `404`, and the exploration routes the same `source_ask` field.

**Screen.**
- *Threads*: ask threads join the list with plans and explorations, all newest first by `created_at`, each ask thread
  with its `title` and a chip `answered` or `failed`. Selecting one opens `#/agent/ask/<thread_id>`.
- *Composer*: the mode switch (D13) is an element with `role="group"` and accessible name `Mode`, holding toggle buttons
  named `Ask`, `Plan` and `Explore` (from slice 10), each with `aria-pressed`. While a request runs, the text box and
  the submit button are disabled. In `Ask` mode, Enter sends the text to `POST /api/agent/asks`: with an ask thread
  selected, as a follow-up in that thread; otherwise as a new thread, which appears at the top of the list, selected.
  The composer clears on send. While a new thread's first ask runs, the stream shows its question and `Working…` and
  no thread is selected; on HTTP 200 the thread appears at the top, selected, and the address becomes
  `#/agent/ask/<thread_id>`. Per mode, the composer's label, submit button (while sending) and help line are: `Ask`:
  "Question", "Ask" ("Asking…"), "Enter asks ARP; Shift+Enter adds a line."; `Plan`: today's "Research brief",
  "Draft plan" ("Drafting…") and help text, unchanged; `Explore` (slice 10): "Question", "Explore" ("Exploring…"),
  "Enter runs an exploration; Shift+Enter adds a line.". In `Plan` and `Explore` modes it never sends `source_ask_id`, even with an ask thread
  selected; selecting a thread never changes the mode. With `canAsk` false (`App.tsx`: role `viewer`) the `Ask` button is not shown and the
  composer opens in `Plan` mode. The frontend suite has no DOM, so the composer's rules live in pure functions in
  `lib/agent.ts` that the screen calls (`composerModes`, `composerRequest`, `ctrlJTarget`, `draftPlanFromAsk`), and the
  `unit` rows test those.
- *Stream of an ask thread*: one turn per ask, oldest first: the question, then the answer card that `AskCards.tsx`
  renders today, or the `error` text, or `Working…` while the request runs. Under an answered ask: the buttons
  `Draft a plan` and (slice 14) `Explore`, then one link card per entry in its `plans` (`Plan: <brief's first 60
  characters>` with its status chip, linking to `#/agent/<plan_id>`) and `explorations` (`Exploration: <question's
  first 60 characters>` with its label, linking to `#/agent/exploration/<id>`).
- With `canAsk` false (a viewer, who may read ask threads), an answered ask shows no `Draft a plan` and no `Explore`
  button; `answerActions(canAsk)` in `lib/agent.ts` decides which buttons show.
- `Draft a plan` calls `POST /api/plans` with `{brief: <the ask's standalone_question>, source_ask_id: <ask id>}`. It is
  disabled while the request runs. On 200 the link card appears under that answer and the plan's thread row joins the
  list; the screen stays on the ask thread. On any other status the response's `detail` shows under that answer.
  `Explore` (slice 14) does the same with `POST /api/agent/explorations` and `{question: <standalone_question>,
  source_ask_id}`.
- A plan or exploration with `source_ask` shows a line `From ask: <source_ask.question>` in its brief or question card,
  linking to `#/agent/ask/<source_ask.thread_id>`.
- *Inbox footer*: from slice 13 it reads `<n> more in Needs you` (the UI trim spec renames the Review Queue to Needs
  you), still linking to `#/review`. Asks never appear in the inbox: nothing in them waits on a person.
- *Mode switch and slice 10*: whichever of slices 10 and 13 merges second adds `Explore` as the third mode button; the
  first one builds only its own mode (slice 10's toggle, or `Ask` and `Plan`).

**Top bar (D12).** Builds on the UI trim spec's search-or-ask box (`2026-11-22-ui-trim-workspaces.md`, PR #630):
- The palette's last option `Ask ARP: "<typed text>"`, and Enter when no screen matches, close the palette, open
  `#/agent` in `Ask` mode and send the typed text as a new ask thread.
- Ctrl/⌘J, when `canAsk` is true, always goes to `#/agent` with no thread selected (also from an ask thread), with the
  composer focused in `Ask` mode, so the next ask starts a new thread.
- `components/AskPanel.tsx` and `lib/askHistory.ts` are deleted, and nothing reads the session storage key
  `arp.ask.turns`. `AskCards.tsx` stays, used by the stream. `askErrorText` and `ASK_ERROR_TEXT` move unchanged to a
  new `lib/askError.ts`, which `pages/portfolio-monitoring/AskThePortfolio.tsx` then imports.
  `frontend/tests/askHistory.test.ts` is retired with the module: its `askErrorText` cases move unchanged to a new
  `frontend/tests/askError.test.ts`, and slice 13's PR lists every retired case. `api.ask` in `api/client.ts` and the
  `AskHistoryTurn` type lose their last caller and are removed from the frontend; `POST /api/ask` stays on the server.
- This supersedes the UI trim spec's AC-4, AC-4b and AC-7, the panel rows of `2026-10-24-ask-arp-panel-design.md`
  (AC-35 to AC-45, AC-48, AC-51, AC-52, AC-54; AC-68c re-covers its history rows, AC-69b its failed-turn row, AC-76e its
  disabled-while-working row), `2026-11-15-app-wide-top-bar-design.md` AC-17 (Esc closes the panel) and AC-22b (Ctrl+J
  opens the panel; AC-76 and AC-76a replace it), and `2026-11-15-start-page-simplified-design.md` AC-6b and AC-6c (the
  panel opens, focus after it closes). `2026-11-15-showcase-curated-company-keys.md` AC-26 is re-pointed to the same
  question asked in the composer's `Ask` mode on `#/agent/ask/<id>`. That spec's answer-card rows (AC-29 to AC-34, AC-46, AC-49) stay and now apply to the answer card
  in an ask thread on `#/agent/ask/<id>`. `2026-11-15-ask-portfolio-provider-error.md` AC-9 is re-pointed: its case now
  lives in `frontend/tests/askError.test.ts`, importing `askErrorText` from `lib/askError.ts`. Slice 13's PR adds a line
  saying so under each of those specs' `## Acceptance`. The test-writer for slice 13 retires those three hidden tests, from
  `specs/ui-trim-workspaces/` or `regression/` wherever they are then, in a holdout PR of its own, separate from the
  one that adds AC-75 to AC-76a under `specs/agent-panel-code-mode/`. That retirement PR is the owner's to merge, and
  slice 13 merges only after it has.

## Fixtures

- **P3** (unit tests only): the script `u = universe_build(taxonomy_id="t", source="s.csv")`,
  `e = extraction(universe_run_id=u.run_id, schema_id="x")`, `r = report_render(source_ids=[e.run_id])`, with stub
  start and finish functions injected for those three kinds, the way today's executor tests inject steps. `s1`, `s2`,
  `s3` below mean the stubs for seq 1, 2 and 3, and `reviewed` is the injected review check. Each stub's `start` returns `r_<seq>` and writes a run manifest with that id, its launch
  key and the `estimated_cost_usd` the row names; each stub counts its `start` and `finish` calls.
- **Demo plan**: `arp plan seed-demo` (exists), a draft with 4 dry-run steps, for the API and browser rows.
- **Ask stand-in**: `$ARP_STANDINS_DIR/model/AskRouting.json` (the existing model stand-in, logged as
  `{"kind": "model", "name": "AskRouting", ...}` in `calls.jsonl`) set to
  `{"output": {"tool": "benchmark_sectors", "standalone_question": "Sector weights of MSCI World?", "benchmark_id": null}}`.
  The answer is whatever `ask.benchmark_sectors(<streams root>, None)` returns on that stack at that moment (the sample
  card when no benchmark is uploaded); rows compare against that call, not a fixed card.
  The sample benchmark card needs no other model call. "No Ask stand-in" means that file is absent, so the model call
  raises.
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
  every retired case with the row or new test that replaces it. Slice 13 retires
  `backend/tests/e2e/test_top_bar_pr3.py::test_esc_leaves_ask_panel_open` (Ctrl+J no longer opens a panel; AC-76 and
  AC-76a replace it), `frontend/tests/askHistory.test.ts` (Phase 7, Top bar) and any other e2e or frontend test that
  opens the Ask panel, and lists each one in its PR.

## Acceptance

Superseded: Phase 7 (slice 13) supersedes `2026-11-22-ui-trim-workspaces.md` AC-4, AC-4b, AC-7;
`2026-10-24-ask-arp-panel-design.md` AC-35 to AC-45, AC-48, AC-51, AC-52, AC-54; and
`2026-11-15-app-wide-top-bar-design.md` AC-17 and AC-22b; and `2026-11-15-start-page-simplified-design.md` AC-6b and
AC-6c. It re-points `2026-11-15-showcase-curated-company-keys.md` AC-26 (to the same question asked in the Agent
composer's `Ask` mode, on `#/agent/ask/<id>`), ask-arp-panel AC-29 to AC-34, AC-46, AC-49 (to the answer
card in an ask thread) and `2026-11-15-ask-portfolio-provider-error.md` AC-9 (to `frontend/tests/askError.test.ts`).
No v1 or v2 row is retired. v1 rows that say a plan runs after `POST /run` (AC-18 to AC-32 through the API)
now hold once the worker has scanned; their tests are adapted as listed under Fixtures.

Rows that need stub steps (P3) or forced crashes are `unit`: the app started by `e2e_stack.sh` runs the real steps.
In rows, `\n` inside code means one newline character.

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
| AC-29 | Demo plan selected | click `Approve` | the thread's chip reads `approved` and the approval card is gone | evaluator |
| AC-29c | The plan approved in AC-29 | open its Audit tab | the approver line shows the signed-in user | evaluator |
| AC-29b | Demo plan selected | open the Script tab | the demo script, read-only, with line numbers from 1 to its last line | evaluator |
| AC-30 | No other drafts, waiting calls or explorations; draft plan A created before plan B's call seq 2 started; plan B `awaiting_review` at seq 2 on run `r_2` of type `extraction` | `GET /api/agent/inbox` | exactly 2 rows: `{kind: "plan_approval", plan_id: A, seq: null, exploration_id: null, href: "#/agent/A"}` then `{kind: "step_review", plan_id: B, seq: 2, exploration_id: null, href: "#/review/extraction/r_2"}` | unit |
| AC-31 | `GET /api/waiting` returns `total: n` | open `#/agent` | the inbox footer reads `<n> more waiting in the Review Queue` and links to `#/review`. From slice 13: it reads `<n> more in Needs you` and links to `#/review` | evaluator |
| AC-32 | A plan re-planned once (version 2) | open its Diff tab | the header reads `-<a> +<b>`, where a and b count the lines starting `-` and `+` (headers excluded) in `diff -u` of the version 1 and version 2 scripts | evaluator |
| AC-33 | A done plan with 3 calls | open its Audit tab | 3 rows, each showing seq, kind, run id, status and cost equal to `GET /api/plans/{id}` `calls` | evaluator |
| AC-34 | A running plan selected; a call changes from `running` to `done` | wait 4 s | that step card shows `done` without a page reload | evaluator |
| AC-35 | Stand-in planner; from slice 13, the composer's `Plan` mode selected | type a brief in the composer and press Enter | a new thread appears at the top of the list, selected, with chip `draft` | evaluator |
| AC-36 | Viewport 390 px wide | open `#/agent/<demo>` | the stream fills the width; no horizontal page scroll; header buttons open the threads and the stage as drawers | evaluator |
| AC-37 | Any plan | open `#/plans/<id>` | the address becomes `#/agent/<id>` and that plan is selected | evaluator |
| AC-38 | The nav | open the Runs group | it shows `Agent` and no `Research plans` | evaluator |
| AC-39 | Stand-in code `return await codemode.benchmark_sectors({})` | `POST /api/agent/explorations` | HTTP 200; `status: "done"`; `label: "exploratory"`; `result` equals `BenchmarkCard.model_dump(mode="json")` of the card `ask.benchmark_sectors` returns for `benchmark_id: null` (the sample card, `is_sample: true`), without its text | holdout |
| AC-40 | Stand-in code `return await fetch("https://example.com")` | same | HTTP 200; `status: "failed"`; `error` contains `network access is not allowed` | holdout |
| AC-41 | Stand-in code `while (true) {}` | same | HTTP 200 within 35 s; `status: "timeout"` | holdout |
| AC-42 | Stand-in code calling `codemode.benchmark_sectors({benchmark_id: null})` 51 times in a loop | same | HTTP 200; `status: "failed"`; `error` contains `capability call limit 50 exceeded`; `tool_calls` has 50 rows | holdout |
| AC-43 | Stand-in code `return typeof process + "," + typeof globalThis.ARP_TOKEN` | same | HTTP 200; `result` is `"undefined,undefined"` | holdout |
| AC-44 | Stand-in code returning a string of 300 000 ASCII characters | same | HTTP 200; `status: "failed"`; `error` contains `result exceeds 256 KB` | holdout |
| AC-45 | Stand-in code `return await codemode.universe_build({})` | same | HTTP 200; `status: "failed"`; `error` contains `universe_build is not available in the sandbox` | holdout |
| AC-45b | Stand-in code of 401 lines | same | HTTP 200; `status: "failed"`; `error` contains `code exceeds 400 lines`; `tool_calls: []` | holdout |
| AC-45c | Stand-in codes: first `return (`, then `return 1` | same | HTTP 200; `status: "done"`; `result: 1`; `calls.jsonl` has 2 lines with `name: "ExplorationCode"` and that question | holdout |
| AC-46 | A valid execution token minted in the test | `POST /api/sandbox/tools/universe_build` | HTTP 404 | unit |
| AC-47 | `ARP_SANDBOX_TOKEN_SECONDS=1`; a token minted 2 s ago | `POST /api/sandbox/tools/smart_search` with it | HTTP 401 | unit |
| AC-48 | A done exploration | `POST /api/agent/explorations/{id}/accept` | `GET /api/agent/explorations/{id}` shows `label: "accepted"`, `accepted_by` equal to the signed-in user (`dev` in the e2e app), non-null `accepted_at` | holdout |
| AC-49 | An exploration not yet accepted | open it in the stream | the card shows the badge `Exploratory: not reviewed` | evaluator |
| AC-50 | An exploration E not yet accepted | `GET /api/agent/inbox` | exactly 1 row has `exploration_id: E`, and it equals `{kind: "exploration", plan_id: null, seq: null, exploration_id: E, href: "#/agent/exploration/E"}` | holdout |
| AC-51 | Golden file of 10 questions, each with the capabilities its code must call; a case passes if the code runs to `done` and calls each listed capability at least once | `cd backend && arp agent golden --cases tests/golden/explore.jsonl --min-pass 8` (one `{id, question, expected_capabilities: [str]}` per line; the command starts `sandbox/` itself if `ARP_SANDBOX_URL` does not answer) | exit 0 | golden |
| AC-52 | Must not change: a script `x = exploration` | `arp plan dry-run s.py` | exit 1, stdout contains `line 1: name exploration is not defined` | holdout |
| AC-53 | Must not change: the v1 checker rows AC-1 to AC-8 | `python3 -m pytest backend/tests/test_plan_script.py` | passes with no test edited | unit |
| AC-54 | A done exploration; stand-in mini-app HTML | click `Show as mini-app` | the Mini-app tab opens and shows the frame; `GET /api/agent/explorations/{id}` has non-null `miniapp_html` | evaluator |
| AC-54b | An exploration with `status: "failed"` | `POST /api/agent/explorations/{id}/miniapp` | HTTP 409, `{"detail": "only a done exploration can be shown as a mini-app"}` | holdout |
| AC-54c | A done exploration with `miniapp_html` stored | open its Mini-app tab | the iframe's `sandbox` attribute is exactly `allow-scripts` | evaluator |
| AC-55 | No other page open; stand-in mini-app HTML that calls `fetch("/api/plans")` and shows the outcome | open its Mini-app tab | the frame shows the fetch failed; the API access log has no `GET /api/plans` from opening the tab until 5 s later | evaluator |
| AC-56 | Mini-app HTML that posts `{"action": "ask", "text": "why sector X?"}` | it loads | the composer contains `why sector X?`; no new thread appears | evaluator |
| AC-57 | Mini-app HTML that posts `{"action": "run", "plan_id": "<demo>"}` | it loads | the demo plan's status is unchanged and the composer is empty | evaluator |
| AC-58 | Must not change: the backend suite, apart from the cases listed under Fixtures, each listed in the PR that edits it | `python3 -m pytest` | passes | unit |
| AC-59 | Must not change: the frontend suite apart from the cases slices 6 and 13 retire openly, each listed in the PR | `npm test` | passes | unit |
| AC-60 | Accepted exploration E with question `Q60`; stand-in planner | `POST /api/agent/explorations/E/plan` `{"brief": "fetch missing reports"}` | HTTP 200; `status: "draft"`, `approved_by: null`, `brief: "fetch missing reports"`, `source_exploration_id: E` | holdout |
| AC-60b | A plan drafted with `POST /api/plans` | `GET /api/plans/{id}` | `source_exploration_id: null`; every other key the response had before slice 12 is still present | holdout |
| AC-61 | Done exploration not accepted | `POST /api/agent/explorations/E/plan` `{"brief": "x"}` | HTTP 409, `{"detail": "only an accepted exploration can become a plan"}`; `GET /api/plans` returns as many plans as before | holdout |
| AC-61b | No exploration with id `00000000-0000-0000-0000-000000000000` | `POST /api/agent/explorations/00000000-0000-0000-0000-000000000000/plan` `{"brief": "x"}` | HTTP 404, `{"detail": "exploration not found"}` | holdout |
| AC-61c | Exploration with `status: "failed"` and `accepted_at` set directly in the table | the route, `{"brief": "x"}` | HTTP 409, `{"detail": "only an accepted exploration can become a plan"}` | unit |
| AC-62 | Accepted exploration E with question `Q62`; stand-in planner | `POST /api/agent/explorations/E/plan` `{"brief": "   "}` | HTTP 200; `brief: "Q62"` | holdout |
| AC-62b | Accepted exploration E with question `Q62b` and result `[{"a":1}]`; stand-in planner | `POST /api/agent/explorations/E/plan` `{}` | the last `calls.jsonl` line with `name: "PlanScript"` has a `prompt` containing the lines `From exploration E, question: Q62b`, `Result:` and `[{"a":1}]`, one after another, each separated by a single newline character | holdout |
| AC-63 | Accepted exploration whose result is a string of 29 998 ASCII `a` characters (30 000 bytes as JSON); injected planner | the route | the `context` passed to `draft_plan` starts with `_context()`'s output and ends with `Result:\n` + the first 20 000 bytes of that JSON + `\n(result truncated at 20000 bytes)` | unit |
| AC-63b | Result a string whose JSON text has one 3-byte character at bytes 19 999 to 20 001 (counting from 1) and is longer than 20 000 bytes; injected planner | the route | the result text in `context` is 19 998 bytes, decodes as UTF-8, and is followed by `\n(result truncated at 20000 bytes)` | unit |
| AC-63c | Result whose JSON is exactly 20 000 bytes; injected planner | the route | `context` ends with the whole JSON and contains no `result truncated` | unit |
| AC-63d | Accepted exploration E; stand-in planner whose script the checker rejects twice | the route | HTTP 422, `detail` equals the checker's errors joined by newlines; no plan has `source_exploration_id: E` | unit |
| AC-64 | `ARP_PLAN_WORKER_SECONDS=0`; a draft plan with `source_exploration_id` set | `scan()` twice | both return `[]`; the plan is `draft`; `store.calls(id) == []`; no manifest under `runs_dir` has `params["launch_key"]` starting `plan:<id>:` | unit |
| AC-65 | Accepted exploration; stand-in planner | click `Turn into a plan…`, then `Draft plan` | a new thread with chip `draft` is at the top and selected | evaluator |
| AC-65b | The plan from AC-65 | click `From exploration: <question>` in its brief card | the address becomes `#/agent/exploration/<id>` and that exploration's card shows | evaluator |
| AC-65c | Frontend test: an accepted exploration; the route mocked to answer `422 {"detail": "line 1: bad"}` | click `Turn into a plan…`, then `Draft plan` | the field stays open with `line 1: bad` under it; the thread list is unchanged | unit |
| AC-66 | Exploration not accepted | open it in the stream | no `Turn into a plan…` action | evaluator |
| AC-66b | Frontend test: an exploration with `status: "failed"` and `accepted_at` set | render its stream card | no `Turn into a plan…` action | unit |
| AC-67 | Must not change: stand-in code `return await codemode.propose_plan({brief: "x"})` | `POST /api/agent/explorations` | HTTP 200; `status: "failed"`; `error` contains `propose_plan is not available in the sandbox`; `GET /api/plans` returns as many plans as before | holdout |

| AC-68 | Ask stand-in | `POST /api/agent/asks` `{"question": "sector weights of msci world"}` | HTTP 200; `thread_id` equals `id`; `tool: "benchmark_sectors"`; `standalone_question: "Sector weights of MSCI World?"`; `response.benchmark_sectors` and `response.answer_text` equal the card and text `ask.benchmark_sectors(<streams root>, None)` returns on that stack; `error: null`; `asked_by: "dev"`; `plans: []`; `explorations: []` | holdout |
| AC-68b | Thread T from AC-68; Ask stand-in | `POST /api/agent/asks` `{"question": "and only the top 3", "thread_id": T}` | HTTP 200; `thread_id: T`; the last `calls.jsonl` line with `name: "AskRouting"` has a `prompt` containing the line `- Sector weights of MSCI World? [benchmark_sectors]` | holdout |
| AC-68c | A thread with 6 answered asks whose standalone questions are `S1` to `S6`, oldest first; injected model | another ask in that thread | the routing prompt contains `S2`, `S3`, `S4`, `S5`, `S6` in that order and does not contain `S1` | unit |
| AC-68d | No ask has id `00000000-0000-0000-0000-000000000000` | `POST /api/agent/asks` `{"question": "x", "thread_id": "00000000-0000-0000-0000-000000000000"}` | HTTP 404, `{"detail": "ask thread not found"}`; `GET /api/agent/ask-threads` returns as many rows as before | holdout |
| AC-68f | Thread T after AC-68b; F the `id` of its second ask | `POST /api/agent/asks` `{"question": "x", "thread_id": F}` | HTTP 404, `{"detail": "ask thread not found"}`; `GET /api/agent/asks?thread_id=T` still returns 2 rows | holdout |
| AC-68e | Any | `POST /api/agent/asks` `{"question": "   "}` | HTTP 422; no row stored | unit |
| AC-69 | No Ask stand-in | `POST /api/agent/asks` `{"question": "q69"}` | HTTP 200; `tool: null`; `standalone_question: null`; `response: null`; `error: "Ask could not answer this question. Try again."`; `GET /api/agent/asks?thread_id=<its id>` returns that one row | holdout |
| AC-69b | Thread T whose only ask failed (as AC-69); then the Ask stand-in | `POST /api/agent/asks` `{"question": "again", "thread_id": T}` | HTTP 200; the last `calls.jsonl` line with `name: "AskRouting"` has a `prompt` containing `Earlier questions, oldest first:\n(none)` | holdout |
| AC-70 | Must not change: `POST /api/ask`; `ARP_TEST_POSTGRES_DSN` set | `cd backend && python3 -m pytest tests/test_api_ask.py tests/test_ask_tools.py tests/test_ask_transition_plan.py` | passes with no test edited | unit |
| AC-71 | Injected model answering `benchmark_sectors`, then one that raises | `POST /api/agent/asks` once with each | the audit store has 2 new rows, with `endpoint` `ask.benchmark_sectors` and `ask.error` | unit |
| AC-71b | Injected model routing to `transition_plan`; the run store raises | `POST /api/agent/asks` `{"question": "q71b"}` | HTTP 200; the row has `tool: null` and `error: "Ask could not answer this question. Try again."`; the new audit row has `endpoint: "ask.transition_plan"` | unit |
| AC-71c | Signed in as a viewer | `POST /api/agent/asks` `{"question": "x"}` | HTTP 403; no row stored | unit |
| AC-71e | Signed in as a viewer | `GET /api/agent/ask-threads` | HTTP 200 | unit |
| AC-71f | Injected model; an unknown `thread_id`, then a viewer, then `{"question": "   "}` | `POST /api/agent/asks` once each | 404, 403, 422; the audit store has no new row | unit |
| AC-71g | A thread whose stored ask has a 1200-character `standalone_question`; injected model | a follow-up ask in that thread | HTTP 200 with `error: null`; the routing prompt contains that standalone question's first 1000 characters and not its 1001st | unit |
| AC-71d | One answered ask thread T (Ask stand-in) | `GET /api/agent/inbox` | no row has an `href` starting `#/agent/ask/`, and every row's `kind` is `plan_approval`, `step_review` or `exploration` | holdout |
| AC-72 | Thread T after AC-68b | `GET /api/agent/asks?thread_id=T` | 2 rows; the first has `question: "sector weights of msci world"`, the second `question: "and only the top 3"` | holdout |
| AC-72a | Thread T after AC-68b | `GET /api/agent/asks?thread_id=T` | each row has exactly the keys `id`, `thread_id`, `question`, `standalone_question`, `tool`, `response`, `error`, `asked_by`, `created_at`, `plans`, `explorations` | holdout |
| AC-72b | Ask stand-in; thread A created with the 70-character first question `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` (70 `a`), then thread B | `GET /api/agent/ask-threads` | B's row comes before A's; A's row is `{thread_id: A, title: <60 a>, status: "answered", created_at: <A's first ask's created_at>, asks: 1}` | holdout |
| AC-72c | No ask has id `00000000-0000-0000-0000-000000000000` | `GET /api/agent/asks?thread_id=00000000-0000-0000-0000-000000000000` | HTTP 404, `{"detail": "ask thread not found"}` | holdout |
| AC-72d | Any | `POST /api/agent/asks` `{"question": "x", "thread_id": "abc"}` | HTTP 404 `{"detail": "ask thread not found"}`; no ask stored | unit |
| AC-72e | Any; stand-in planner | `POST /api/plans` `{"brief": "b", "source_ask_id": "abc"}` | HTTP 404 `{"detail": "ask not found"}`; no plan stored | unit |
| AC-73 | Ask A in thread T (AC-68); stand-in planner | `POST /api/plans` `{"brief": "b73", "source_ask_id": A}` | HTTP 200; `source_ask_id: A`; `status: "draft"` | holdout |
| AC-73e | The plan P from AC-73 | `GET /api/agent/asks?thread_id=T` | A's row has `plans` equal to `[{plan_id: P, brief: "b73", status: "draft"}]` | holdout |
| AC-73b | No ask has id `00000000-0000-0000-0000-000000000000`; stand-in planner | `POST /api/plans` `{"brief": "b", "source_ask_id": "00000000-0000-0000-0000-000000000000"}` | HTTP 404, `{"detail": "ask not found"}`; `GET /api/plans` returns as many plans as before | holdout |
| AC-73c | A plan drafted with `POST /api/plans` without `source_ask_id` | `GET /api/plans/{id}` | `source_ask_id: null`; `source_ask: null`; the keys `id`, `brief`, `script`, `dry_run`, `status`, `approved_by`, `approved_at`, `created_at`, `error`, `version`, `previous_scripts` are present | holdout |
| AC-73d | The plan from AC-73 | `GET /api/plans/{id}` | `source_ask: {question: "sector weights of msci world", thread_id: T}` | holdout |
| AC-74 | Ask stand-in | open `#/agent`, leave `Ask` pressed, type `sector weights of msci world`, press Enter | a new thread with chip `answered` is at the top and selected; the address is `#/agent/ask/<id>`; the stream shows the question and an answer card under it | evaluator |
| AC-74b | The thread from AC-74 selected; Ask stand-in | type `and only the top 3`, press Enter | the stream shows 2 turns | evaluator |
| AC-74c | The thread from AC-74 selected; Ask stand-in | type `and only the top 3`, press Enter | the thread list has as many rows as before | evaluator |
| AC-75 | e2e stack; Ask stand-in | press Ctrl+K, type `zzqx nothing matches`, press Enter | the address starts `#/agent/ask/` | holdout |
| AC-75c | e2e stack; Ask stand-in | press Ctrl+K, type `zzqx nothing matches`, press Enter | the stream's first turn shows `zzqx nothing matches` | holdout |
| AC-75a | e2e stack; Ask stand-in | press Ctrl+K, type `zzqx nothing matches`, press Enter | no dialog named `Search or ask` or `Ask ARP` is in the page | holdout |
| AC-75b | e2e stack; Ask stand-in | press Ctrl+K, type `outputs nobody uses`, press ArrowDown until the `Ask ARP: …` option is active, press Enter | the address starts `#/agent/ask/` | holdout |
| AC-75d | As AC-75b | as AC-75b | the stream's first turn shows `outputs nobody uses` | holdout |
| AC-76 | e2e stack | press Ctrl+J on `#/home` | the address is `#/agent` | holdout |
| AC-76a | e2e stack | press Ctrl+J on `#/home` | the composer's text box has focus | holdout |
| AC-76d | e2e stack | press Ctrl+J on `#/home` | in the group named `Mode`, the button `Ask` has `aria-pressed="true"` | holdout |
| AC-76e | Ask stand-in with `"delay_seconds": 2` added to its entry | on `#/agent` in `Ask` mode, type `q`, press Enter | while `Working…` shows, the composer's text box and submit button are disabled and the submit reads `Asking…` | evaluator |
| AC-76b | The frontend source | look for `frontend/src/components/AskPanel.tsx` and `frontend/src/lib/askHistory.ts`, and search `frontend/src` for `arp.ask.turns` | neither file exists; the search finds nothing | unit |
| AC-76c | e2e stack | open `#/portfolio-monitoring/ask` | an `h2` "Ask the Portfolio" and a text box named "Question" are visible | holdout |
| AC-77 | The thread from AC-74 selected, its first answer showing; stand-in planner | click `Draft a plan` | under that answer a link card reads `Plan: Sector weights of MSCI World?` with chip `draft` | evaluator |
| AC-77d | As AC-77 | click `Draft a plan` | the address is unchanged | evaluator |
| AC-77c | As AC-77 | click `Draft a plan` | the thread list has one more row than before, with chip `draft` | evaluator |
| AC-77a | The link card from AC-77 | click it | the address becomes `#/agent/<plan_id>` | evaluator |
| AC-77e | The plan from AC-77 selected | click `From ask: sector weights of msci world` in its brief card | the address becomes `#/agent/ask/<thread_id>` | evaluator |
| AC-77b | Frontend test of `draftPlanFromAsk(ask, request)` in `lib/agent.ts` (what `Draft a plan` calls): an answered ask; `request` rejects with `new Error("422: line 1: bad")` (what `api/client.ts` throws for that response) | call it | it resolves to `{ok: false, error: "line 1: bad"}` | unit |
| AC-78 | Frontend test of `composerModes(canAsk)` in `lib/agent.ts` (the composer renders one button per mode and presses `initial`) | call it with `true`, then `false` | `true`: `{modes: ["Ask", "Plan"], initial: "Ask"}`, with `"Explore"` appended once slice 10 is merged; `false`: `{modes: ["Plan"], initial: "Plan"}`, likewise | unit |
| AC-79 | Frontend test of `ctrlJTarget(canAsk)` in `lib/agent.ts` (what the Ctrl/⌘J handler in `App.tsx` navigates to) | call it with `false`, then `true` | `null`, then `"#/agent"` | unit |
| AC-79c | Frontend test of `answerActions(canAsk)` in `lib/agent.ts` | call it with `false`, then `true` | `[]`, then `["Draft a plan"]` (and `["Draft a plan", "Explore"]` once slice 14 is merged) | unit |
| AC-79b | Frontend test of `composerRequest(mode, text, selected)` in `lib/agent.ts` (what the composer sends on Enter) | call it with `"Plan"`, `"b"` and an ask thread `T` selected | `{path: "/api/plans", body: {"brief": "b"}}`, with no `source_ask_id` | unit |
| AC-80 | Ask A in thread T; stand-in code `return 1` | `POST /api/agent/explorations` `{"question": "q80", "source_ask_id": A}` | HTTP 200; `source_ask_id: A`; in `GET /api/agent/asks?thread_id=T`, A's row has `explorations` equal to `[{exploration_id: <the new id>, question: "q80", status: "done", label: "exploratory"}]` | holdout |
| AC-80b | No ask has id `00000000-0000-0000-0000-000000000000` | `POST /api/agent/explorations` `{"question": "q", "source_ask_id": "00000000-0000-0000-0000-000000000000"}` | HTTP 404, `{"detail": "ask not found"}`; `GET /api/agent/explorations` returns as many rows as before | holdout |
| AC-81 | The thread from AC-74 selected; `explore.json` is `{"Sector weights of MSCI World?": [{"code": "return 1"}]}` | click the `Explore` button inside its first answer's turn | under that answer a link card reads `Exploration: Sector weights of MSCI World?` with label `exploratory` | evaluator |
| AC-81c | As AC-81 | click the `Explore` button inside its first answer's turn | the address is unchanged | evaluator |
| AC-81b | The exploration from AC-81 | open it, click `From ask: <question>` | the address becomes `#/agent/ask/<thread_id>` | evaluator |
Must not change: v1 and v2 plan behaviour (AC-10, AC-53), the plan language (AC-52), the sandbox's read-only lane
(AC-45, AC-67), `POST /api/ask` (AC-70), the Ask the Portfolio page (AC-76c), both suites (AC-58, AC-59).

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
| 8 | Stage tabs: Diff, Audit; 3 s refresh | `risk:normal` | AC-29c, AC-32, AC-33, AC-34, AC-59 |
| 9 | `sandbox/` service with code checks, tool route and tokens, limits, `e2e_stack.sh` starts it; `agent_explorations` table and `POST /api/agent/explorations` taking code from `explore.json` entry 1 only (no retry yet) | `risk:high` (secrets, auth, schema) | AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-45b, AC-46, AC-47, AC-58 |
| 10 | Explorations: model call and retry, list and get routes, accept, stream card, inbox rows, golden set | `risk:normal` | AC-39, AC-45c, AC-48, AC-49, AC-50, AC-51, AC-52, AC-58, AC-59 |
| 11 | Mini-apps: route, generation, iframe, message bridge | `risk:high` (security boundary) | AC-54, AC-54b, AC-54c, AC-55, AC-56, AC-57, AC-58, AC-59 |
| 12 | Write action: `source_exploration_id` column, `POST /api/agent/explorations/{id}/plan`, "Turn into a plan…" in the stream | `risk:high` (schema) | AC-52, AC-60, AC-60b, AC-61, AC-61b, AC-61c, AC-62, AC-62b, AC-63, AC-63b, AC-63c, AC-63d, AC-64, AC-65, AC-65b, AC-65c, AC-66, AC-66b, AC-67, AC-58, AC-59 |
| 13 | Ask threads: `agent_asks` table, `POST /api/agent/asks`, `GET /api/agent/asks`, `GET /api/agent/ask-threads`, `source_ask_id` on plans, composer mode switch, ask thread stream with `Draft a plan`, top bar and Ctrl/⌘J open the Agent screen, Ask panel removed, inbox footer text, UI trim spec note | `risk:high` (schema) | AC-31, AC-35, AC-68, AC-68b, AC-68c, AC-68d, AC-68e, AC-68f, AC-69, AC-69b, AC-70, AC-71, AC-71b, AC-71c, AC-71d, AC-71e, AC-71f, AC-71g, AC-72, AC-72a, AC-72b, AC-72c, AC-72d, AC-72e, AC-73, AC-73b, AC-73c, AC-73d, AC-73e, AC-74, AC-74b, AC-74c, AC-75, AC-75a, AC-75b, AC-75c, AC-75d, AC-76, AC-76a, AC-76b, AC-76c, AC-76d, AC-76e, AC-77, AC-77a, AC-77b, AC-77c, AC-77d, AC-77e, AC-78, AC-79, AC-79b, AC-79c, AC-58, AC-59 |
| 14 | `Explore` from an answer: `source_ask_id` on explorations, its `404`, `explorations` on asks, `Explore` button and link card | `risk:high` (schema) | AC-80, AC-80b, AC-81, AC-81b, AC-81c, AC-58, AC-59 |

Slices go in this order. Slices 3 to 5 may run in parallel after slice 2; slices 6 to 8 need slice 2; slice 10 needs 9;
slice 11 needs 10; slice 12 needs 6 and 10 and may run in parallel with 11. Slice 13 needs 6, 7 and the UI trim
spec's slice 1 (PR #630); slice 14 needs 10 and 13.

## Later (own specs)

- **OpenShell hardening (D5).** Run `sandbox/` inside NVIDIA OpenShell with a deny-all egress policy except the ARP API
  host, and gateway secret injection. Entry: a spike on the `arp-gcp` deployment shows OpenShell's kernel needs
  (Landlock, seccomp) are met where the sandbox will run. Exit rows: egress to an unlisted host is blocked at the OS
  layer and logged.
- **Sandbox-initiated drafts.** A `propose_plan` capability that model code may call (D9's alternative), once slice 12
  has shown how drafts from explorations are used.
- **Workspaces and grants**, once ARP has a second user.

## Defaults decided without the owner

- The golden job joins the existing golden-set CI check, triggered also by `backend/arp/agent/**`,
  `backend/arp/orchestration/capabilities.py` and `sandbox/**`.
- Launch key format `plan:<plan_id>:v<version>:<seq>:a<attempt>`, stored in run manifest `params["launch_key"]`.
- Worker interval 5 s; panel refresh 3 s; tool token lifetime 60 s (`ARP_SANDBOX_TOKEN_SECONDS`).
- Sandbox limits: 30 s, 50 calls, 262 144-byte result, 400 lines.
- `ARP_SANDBOX_URL` default `http://127.0.0.1:8790`.
- `@cloudflare/codemode` and `workerd` pinned to the newest release more than two weeks old when slice 9 starts.
- Template parameters: only `universe_build`'s `source`. More parameters need a new spec.
- The Agent screen breaks to one column with drawers below 900 px.
- Exploration context for the planner is cut at 20 000 bytes.
- Ask threads are shared by all users, like plans: a viewer can read them but not ask; ARP has one owner today.
- An ask thread's history keeps the newest 5 answered asks, the limit `POST /api/ask` already has.
- A failed ask is stored and answered with HTTP 200, as a failed exploration is, so the thread keeps the turn.
- Between the UI trim spec's slice 1 and slice 13, the inbox footer still says `Review Queue` while the top bar says
  `Needs you`; slice 13 closes the gap.
- `Draft a plan` uses the ask's `standalone_question` as the brief without opening a field; the brief can be edited
  later with Edit on the plan.

## Watch

- Some pipelines must find a run by its launch key. If `RunStore.list_runs` cannot filter on `params`, slice 1 adds a
  lookup instead of scanning every manifest.
- `@cloudflare/codemode` targets the Workers runtime. If it cannot run on plain `workerd` with a Worker Loader binding,
  slice 9 stops and raises `factory:blocked` with the finding. That is a spec question, not a builder's choice.
