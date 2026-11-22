# Agent research examples: holdings, votes, more plan steps, lineage and board to deck

Slug: agent-research-examples

Risk: this spec PR is `risk:low`. The build is size L, delivered as 6 PRs (see `## Slices`); each slice names its own
risk label.

Status: **approved by the owner on 22 Nov 2026** (button in the spec session, after two spec-critic rounds; decisions D1–D7 as recommended).

Source: thread "Check research workspaces deck" (22 Nov 2026). The owner reviewed the deck "ARP Native Research
Workspaces, Engineering" and asked that the agent can do what its examples show (climate shortlist, grid portfolio,
benchmark lookup, proxy voting), and that the UI shows the same logic: a Plan, Run, Review, Output strip, cited
quotes, saved output with its lineage, and a deck at the end. He agreed to three read tools (`holdings`,
`vote_summary`, `sector_issuers`), to plan steps for Argus and Strategy runs the agent cannot start today, and to adding
the presentation builder. Builds on the approved specs `2026-11-21-agent-panel-code-mode` and `2026-11-22-agent-board`.
Checked against `origin/main` `49ef8ee`.

## Decisions for the owner

Approving this spec accepts all seven as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | **Three specific read tools**, not one general query tool. Each is plain code over existing tables or files, with no model call. | Yes (AC-1 to AC-17) | A `query(sql)` tool over the `bi` views: one tool for every question, but model-written SQL to check and limit. |
| D2 | **The vote rate is "against management"**, with the cockpit's rules for ledger rows: abstentions never count against, a withhold counts as abstain, a re-cast item counts once with its latest decision. Votes cast in a voting run but not yet filed to the ledger are not counted, so the tool can show fewer votes than the cockpit until they are filed. | Yes (AC-9 to AC-12) | The deck's "votes Against ÷ all votes", a different rate from the cockpit's for the same votes. |
| D3 | **Strategy Replication becomes two plan steps**: `strategy_spec` drafts the spec from a paper and waits until a person approves it on the Strategy Replication screen; `strategy_backtest` runs the backtest of an approved spec. | Yes (AC-22 to AC-25) | One step that drafts and backtests without the approval; the spec's own approval rule (backtest only an approved spec) would be skipped. |
| D4 | **Lineage is a new stage tab**, `Lineage`, after `Audit`. | Yes (AC-31 to AC-34) | A section at the top of the Audit tab; one tab fewer, a longer Audit tab. |
| D5 | **Quote cells** in board tables carry a source link to an ARP page or API path only (`#/…` or `/api/…`), and a quote not found in the thread data is listed, as D4 of `agent-board` does for numbers. | Yes (AC-40 to AC-46) | Quotes as plain text; no link to the page and no check. |
| D6 | **Send board to deck builds the deck with no model call and no storyline gate**: the board is already a person's selection, so each block maps to one slide as it is. | Yes (AC-47 to AC-58) | Board blocks go to the storyline planner, which drafts a storyline for approval and fills slides with the model; more polish, less control over what the slides say. |
| D7 | **Charts go into the deck as pictures** (the board chart rendered to PNG with the light house theme), so a slide looks exactly like the board. | Yes (AC-51) | Native PowerPoint charts, which only work for the deck's six chart kinds and need the Vega-Lite spec converted. |

## Why

The deck's four examples are the work the owner wants the agent to do, and today it can do almost none of it:

1. **The agent cannot read holdings or votes.** The data is in Postgres (`holdings`, `vote_meetings`, `vote_items`,
   `vote_decisions`), but the sandbox lane has only four tools: `benchmark_sectors`, `transition_plan`,
   `portfolio_exposure` (a model answers a question in words) and `smart_search`. No tool returns a dated holdings list
   or vote counts, and `benchmark_sectors` has no issuers, so "which issuer leads each sector" cannot be answered.
2. **Plans cannot start half the Argus and Strategy runs.** The transition plan assessment, Emerging Themes,
   Taxonomy Researcher and Strategy Replication have no plan step.
3. **The screens do not show the logic of a result.** Nothing shows where a thread stands (planned, running, waiting
   on you, ready), which inputs and method versions produced an output, or a quote next to the number it supports.
4. **A board cannot become a deck.** ARP has a house deck builder and plans can call it (`report_render`), but the
   board the owner curates cannot be sent to it (`agent-board` lists "board to deck" under Later).

## What exists today

| Piece | Where | Used by this spec |
|---|---|---|
| Holdings snapshot per date | `PostgresPortfolioStore.load_holdings_as_of(as_of, portfolio_ids)` (each portfolio's newest snapshot on or before the date) | `holdings` |
| Zero-model aggregation | `portfolio/aggregation.py` `aggregate(…, group_by="company_id", metric="market_value_sum")` | `holdings` |
| Vote ledger | `vote_meetings` → `vote_items` → `vote_decisions` (`storage/postgres_models.py`) | `vote_summary` |
| Cockpit vote counting | `stewardship/cockpit.py`: `_vote_bucket`, `ledger_topic`, `TOPICS`, latest decision per re-cast item | `vote_summary` (same rules) |
| Benchmarks | `stewardship/benchmark.py` `BenchmarkStore` (uploaded constituents with `issuer_id`, `name`, `sector`, `weight_pct`); `ask.benchmark_sectors` (falls back to the synthetic sample `stewardship/data/examples/sample_meetings.json`) | `sector_issuers` |
| Capability catalog, sandbox lane, tool route | `agent-panel-code-mode` slice 3 (PR #628) and slice 9 | The new tools and steps join it |
| Plan steps | `orchestration/plan_steps.py` `build_steps`, `build_reviewed` | New steps |
| Runs the new steps start | transition plan preset (`presets/transition_plan.py`, schema `transition_plan_indicators`, started from `#/argus/new/transition_plan`), `emerging_themes/pipeline.py`, `agents/taxonomy_researcher.py`, `api/routers/replication.py` (spec draft, approve, backtest) | New steps |
| Agent screen stream and stage | `agent-panel-code-mode` slices 6 to 8 (PR #629 open) | Status strip, Lineage tab |
| Board blocks and checks | `agent-board` slices 1 to 3 (PR #634 open) | Quote cells, Send to deck |
| House deck | `reporting/service.py` (`ReportingService`, `_rerender`), `reporting/house_pipeline.py` `render_house_outputs`, `schemas/reporting.py` (`Deck`, `SlideContent`), `schemas/visuals.py` (`Cover`, `ComparisonTable`, `Flow`, `ImageVisual`), report images (`storage/report_images.py`, at most 20) | Send to deck |

## Goals

- G1. The sandbox can read a dated holdings list with weights, the issuers of a benchmark sector, and vote counts by
  topic, issuer or month.
- G2. Plans can start the transition plan assessment, Emerging Themes, Taxonomy Researcher and Strategy Replication.
- G3. Every step result names the method version it used, and a Lineage tab shows each step's inputs, method and run.
- G4. Every plan and exploration shows one strip, Plan (or Code), Run, Review, Output, saying where it stands.
- G5. A board table can hold a quote with a link to its source, and a quote the agent wrote that is not in the thread
  data is flagged.
- G6. A board can be sent to a house deck in one click; the deck lists in Presentations & Reports.

## Non-goals

- A general SQL or query tool (D1).
- Writes from the sandbox (`agent-panel-code-mode` D4 holds).
- A read tool for reviewed facts with source quotes (see `## Later`).
- Plan steps for Signals and Value Chain Explorer.
- Ratifying a taxonomy, promoting an emerging theme or publishing scores from a plan: these stay a person's clicks.
- Superset dashboards built by the agent.

## Anti-goals

- No new tool or step makes a model call that the run it wraps did not already make.
- A link in a quote cell never leaves ARP.
- The deck never shows an agent number or quote that the board flags without the same flag.

## Design

### Part 1. Read tools (slice 1)

Three new catalog entries, lane `sandbox`, effect `read`, served by the slice 9 tool route
`POST /api/sandbox/tools/{capability_id}` like the other four. A tool that rejects its arguments answers
`422 {"detail": "<message>"}`; inside the sandbox the call then rejects with `Error("<capability_id>: <message>")`.

**`holdings({as_of: string, portfolio_ids: [string] | null, limit: integer | null})`**
- `as_of` must match `YYYY-MM-DD`, else `as_of must be YYYY-MM-DD`. `limit` defaults to 500 and must be 1 to 2000,
  else `limit must be 1 to 2000`.
- Reads `load_holdings_as_of(as_of, portfolio_ids)` and runs `aggregate(group_by="company_id",
  metric="market_value_sum")` over them, with the store's securities and companies.
- Returns `{as_of, portfolio_ids, total_market_value_eur, rows, rows_omitted}`. `portfolio_ids` is the list passed, or
  the ids of every portfolio whose holdings were read when `null`, sorted. Each row is `{company_id, company_name,
  sector, market_value_eur, weight_pct}`: `company_name` and `sector` from the company (`null` when unknown),
  `weight_pct` = `round(market_value_eur / total_market_value_eur * 100, 4)` (0 when the total is 0). Holdings with no
  company form one row with `company_id: "(unresolved)"`. Rows are sorted by `weight_pct` descending, then
  `company_id`; the first `limit` are returned and `rows_omitted` counts the rest.

**`sector_issuers({benchmark_id: string | null, sector: string})`**
- Picks the benchmark as `ask.benchmark_sectors` does. With benchmarks uploaded: `benchmark_id` null answers
  `benchmark_id is required`, an id that names none answers `unknown benchmark: <benchmark_id>`. With none uploaded,
  any `benchmark_id` is ignored and the synthetic sample answers.
- The `sector` argument and each constituent's sector are `strip()`ped and compared case-sensitively; a constituent
  whose sector is empty after stripping belongs to `Unclassified`.
- Returns `{benchmark_id, name, is_sample, sector, issuers: [{issuer_id, name, weight_pct}]}`, `weight_pct` rounded to 4
  decimals, sorted by `weight_pct` descending, then `issuer_id`. An unknown sector returns `issuers: []`.

**`vote_summary({season: integer | null, group_by: "topic" | "issuer" | "month", limit: integer | null})`**
- `season` is a calendar year, default the current UTC year. `group_by` other than the three answers
  `group_by must be topic, issuer or month`. `limit` defaults to 200 and must be 1 to 2000.
- Counts the vote ledger only: every `vote_decisions` row joined to its item and meeting whose `meeting_date` falls in
  the season (UTC). For an item with decisions that carry a `run_id`, only the latest one counts, by
  (`decided_at`, `decision_id`), as the cockpit does; decisions without a `run_id` all count. Each counted decision adds
  1 to `votes`, 1 to its bucket by `_vote_bucket` (`for`, `against`, `abstain` with withhold, `other`), and 1 to
  `against_management` when that column is true (D2).
- Keys: `topic` is `ledger_topic(proponent, categories)`; `issuer` is the meeting's `company_id`, or its
  `issuer_name` when that is null, or `(unknown issuer)` when both are null, with `name` the `issuer_name` as stored
  (possibly null); `month` is `YYYY-MM` of `meeting_date` (UTC).
- Returns `{season, group_by, totals, rows, rows_omitted}`. `totals` is `{votes, for, against, abstain, other,
  against_management, against_management_pct}`; each row is `{key, name, votes, for, against, abstain, other,
  against_management, against_management_pct}` (`name` is `null` for topic and month).
  `against_management_pct` is `round(against_management / votes * 100, 1)`, `null` when `votes` is 0.
- Order: `topic` lists all five `TOPICS` in their order, also with 0 votes; `month` ascending, only months with votes;
  `issuer` by `against_management_pct` descending, then `votes` descending, then `key`. Only `issuer` applies `limit`;
  `rows_omitted` counts the rest (0 otherwise).

The ten old ids keep their order rule: `GET /api/capabilities` lists the sandbox lane first, then the plan lane, each
sorted by `id`. The TypeScript declarations the exploration model receives come from the catalog, so they include the
new tools without other changes.

### Part 2. Plan steps (slice 2)

Five new catalog entries, lane `plan`, effect `run`, each with an input model in `STEPS` and an adapter in
`build_steps` (start and finish, launch keys, as slice 1 of `agent-panel-code-mode` set up):

| Step | Arguments | Starts | Gate |
|---|---|---|---|
| `transition_plan_assessment` | `universe_run_id: str, companies: list[str] \| None = None` | the same extraction run `#/argus/new/transition_plan` starts (schema `transition_plan_indicators`) | pending review items, as `extraction` |
| `emerging_themes` | `universe_run_id: str, companies: list[str] \| None = None` | `create_emerging_themes_run` / `execute_emerging_themes_run`, with the sources and stores `POST /api/emerging-themes/runs` uses, `triggered_by: "research_plan"` | none |
| `taxonomy_research` | `taxonomy_ids: list[str] \| None = None` | `create_taxonomy_research_run` / `execute_taxonomy_research_run`, as `POST /api/taxonomy-researcher/runs` does, `triggered_by: "research_plan"` | none |
| `strategy_spec` | `paper_citation: str, paper_text: str` | the spec draft `POST /api/replication/specs` makes (run type `strategy_replication_spec`) | until the spec's latest decision is `approve` (D3) |
| `strategy_backtest` | `spec_run_id: str, tickers: list[str], prices_ref: str, price_kind: str = "price", benchmark: str \| None = None, out_of_sample_start: str \| None = None, out_of_sample_end: str \| None = None` | `run_replication` exactly as `POST /api/replication/specs/{id}/backtest` does | none |

- `transition_plan_assessment` and `emerging_themes` resolve their companies as `extraction` does:
  `_companies(run_store, universe_run_id, companies)`.
- `strategy_spec`'s result is `{"id": <spec_run_id>, "run_id": <spec_run_id>, "result_ref": "strategy_spec:<spec_run_id>",
  "companies": [], "gate": true}` while the spec's latest decision for item `spec` is not `approve`, and
  `"gate": false` once it is. `build_reviewed` accepts a call whose `result_ref` starts `strategy_spec:`
  once that spec's latest decision for item `spec` is `approve`.
- `strategy_backtest` on a spec that is not approved fails the step with `spec <id> is not approved`. Its result is
  `{"id": <run_id>, "run_id": <run_id>, "verdict": <verdict>, "companies": []}`.
- The inbox (`agent-panel-code-mode` slice 7) links a waiting `strategy_spec` step to `#/strategyReplication`.
- `price_kind` takes the values `BacktestRequest.price_kind` accepts.

**Method in every result (G3).** Each step's result gains a key `method`, an object:

| Step | `method` |
|---|---|
| `universe_build` | `{taxonomy_id, taxonomy_version}`: the released version the run matched against |
| `extraction` | `{schema_id}` |
| `transition_plan_assessment` | `{schema_id: "transition_plan_indicators"}` |
| `decision_score` | `{framework_id, framework_version}`: the ratified version attached (or already on the run) |
| `index_construct` | `{calibration_id, calibration_version, review_date}`: the version in force on `review_date` |
| `strategy_backtest` | `{spec_run_id}` |
| `report_render` | `{template_id}` |
| every other step | `{}` |

A result stored before this slice has no `method`; readers treat that as `{}`.

### Part 3. Lineage tab (slice 3)

`GET /api/plans/{id}/lineage` returns `{plan_id, version, approved_by, approved_at, template_name, template_version,
source_exploration_id, steps}`, with `steps` one entry per stored call sorted by `seq`: `{seq, kind, status, run_id,
inputs, method}`. `inputs` is the call's `params` unchanged; `method` its result's `method`, or `{}`. An unknown plan
answers `404 {"detail": "plan not found"}`. A field the plan lacks (`template_name` before slice 4 of
`agent-panel-code-mode`) is `null`.

The stage gets a tab `Lineage` after `Audit` (D4). It shows, at the top, `Version <version> · approved by <approved_by>
on <approved_at as a UTC date, YYYY-MM-DD>` (or `Not approved`), then `From template <name> v<version>` and
`From exploration <id>` (a link to `#/agent/exploration/<id>`) when set. Below, one card per step:
- heading `<seq>. <kind>` and the status chip;
- `Inputs:` the `inputs` as `key=value` pairs sorted by key, joined by ` · `; a list value is its items joined by `, `;
- `Method:` the `method` pairs in the same form, or `—` when empty;
- `Run:` the run id, linked to `#/review/<run_type>/<run_id>` (the run type from its manifest) when the run has at
  least one review queue item, else shown as plain text; `—` when `run_id` is null.

### Part 4. Status strip (slice 4)

A strip of four cells sits at the top of the stream for the selected thread, under its title. Each cell is a label and a
state word.

For a plan, the labels are `Plan`, `Run`, `Review`, `Output`:

| Plan status | Plan | Run | Review | Output |
|---|---|---|---|---|
| `draft` | Needs you | Not started | — | — |
| `approved` | Approved | Not started | — | — |
| `running` | Approved | Running | — | — |
| `awaiting_review` | Approved | Waiting | Needs you | — |
| `done` | Approved | Complete | — | Ready |
| `failed` | Approved | Failed | — | — |
| `cancelled` | Approved | Cancelled | — | — |

For an exploration, the labels are `Code`, `Run`, `Review`, `Output`:

| Exploration | Code | Run | Review | Output |
|---|---|---|---|---|
| `failed`, `error` starts `code does not parse` or `code exceeds 400 lines` | Failed | — | — | — |
| `failed`, any other error | Checked | Failed | — | — |
| `timeout` | Checked | Timed out | — | — |
| `done`, not accepted | Checked | Complete | Needs you | Exploratory |
| `done`, accepted | Checked | Complete | Accepted | Accepted |

`Needs you` cells use the amber "a person decides" colour of `DESIGN.md`. `Needs you` in a plan's `Plan` cell scrolls
the stream to the approval card; in its `Review` cell it links to the waiting call's inbox `href`. `Ready` opens the
Lineage tab. The strip refreshes with the 3 s poll of `agent-panel-code-mode` D6. Below 900 px the four cells stay on
one row, each label above its state word.

### Part 5. Quote cells on board tables (slice 5)

A `table` block's cell may also be an object `{"text": str, "source": {"label": str, "href": str}}` (D5). Checks, in
order, with `<r>` and `<c>` counted from 1 (row, column), each answering `422` with the message and storing nothing:

| Check | Message |
|---|---|
| keys are exactly `text` and `source`; `source` keys exactly `label` and `href`; all four strings | `cell <r>,<c>: invalid quote cell` |
| `text` 1 to 500 characters after stripping | `cell <r>,<c>: quote must be 1 to 500 characters` |
| `label` 1 to 120 characters after stripping | `cell <r>,<c>: source label must be 1 to 120 characters` |
| `href` starts `#/` or `/api/`, and contains no `//` after its first character and no `\` | `cell <r>,<c>: source link must start with #/ or /api/` |

**Quote check.** Each block response gains `unverified_quotes: [str]`: the `text` of every quote cell whose text is
not a substring of any JSON string at any depth of the thread data (as `agent-board` builds it for draws, but whole,
never truncated), in table order (row by row), without duplicates. Before comparing, the quote and every thread string
have each run of whitespace collapsed to one space; the comparison is case-sensitive. It is computed on every create,
source edit and draw of a `table`, and is `[]` for other kinds, except that a `POST /blocks` whose body carries
`unverified_quotes` (the delete-undo restore) stores the list as given. Undo restores it with the version (a new column on `agent_board_blocks` and
`agent_board_versions`, `jsonb`, default `[]`).

On screen, a quote cell shows its text in quotation marks, then a small link with the label. A `/api/` link opens in a
new tab with the API base prepended, as `api.barrierDocumentUrl` does; a `#/` link navigates in the app. A non-empty
`unverified_quotes` shows one line under the block: `Quotes not in ARP data: <n>`.

A table with at least one quote cell is edited as formatted JSON instead of CSV. Its CSV download writes a quote cell
as `<text> (<label>)`.

The draw system prompt adds the quote cell format and: "quote only text that appears in the thread data".

### Part 6. Send board to deck (slice 6)

`POST /api/agent/boards/{thread_kind}/{thread_id}/deck` with `{"title": str | null}` builds a house deck from the
board with no model call (D6):

1. Thread and kind checks as the other board routes (`404`). A board with no `chart`, `table` or `flow` block answers
   `422 {"detail": "the board has no chart, table or flowchart"}`. More than 20 chart blocks answers
   `422 {"detail": "a deck holds at most 20 charts"}` (the report image limit). A table with fewer than 2 or more than 6 columns answers
   `422 {"detail": "table \"<title>\" has <n> columns; a deck table has 2 to 6"}`. These checks run before anything
   is saved. Any other validation error while building the `Deck` (a flowchart the deck's `Flow` refuses, duplicate
   column names) answers `422 {"detail": "<block title>: <message>"}`, also before anything is saved.
2. `title`, stripped, defaults to the plan's brief or the exploration's question; it is cut to its first 10 words.
3. Slides, in board order:
   - first, a `Cover` with that title and `context` `From the Agent board`;
   - `chart` → one slide with an `ImageVisual` `hero` of one image: the block's source rendered to PNG by
     `vl-convert` with the same config as its `rendered.light` (D7), registered as report image `block-<n>.png`
     where `n` is the block's position + 1;
   - `table` → one `ComparisonTable` slide per 8 rows (`row_offset` 0, 8, 16, …) over a dataset made from the block
     (its columns; every cell as `str()` of its JSON value, `null` as an empty string, each quote cell as
     `<text> (<label>)`); a table with 0 rows gives one slide with the header;
   - `flow` → one `Flow` slide with `mermaid` set to the block's source;
   - `note` → no slide: its text becomes the `speaker_notes` of the next non-note slide, or of the previous one when no
     slide follows; several notes join with a blank line.
   Each slide's `headline` is the block's title. Its `source_line` is, in this order and joined by ` · `:
   `Exploratory: not reviewed` for an exploration that is not accepted; `Not in ARP data: …` as the board shows it
   for a non-empty `unverified`; `Quotes not in ARP data: <n>` for a non-empty `unverified_quotes`; else empty.
4. The route saves a report (`output_format` house deck, the default template) with that `Deck` as its deck, renders
   it with `render_house_outputs`, and answers `201` with the report manifest (`status: "completed"`,
   `output_files` holding `output.pdf` and `output.pptx`). The report's `title` is the deck title, and its request
   records `{"board": {"thread_kind", "thread_id", "block_versions": {<block id>: <version>}}}` in
   `qualitative_notes` as compact JSON. A render error leaves the report `failed` with the error, and the route answers
   `502 {"detail": "deck render failed: <error>"}`.

The Board tab header gets one button, `Send to deck`, shown when the board has at least one chart, table or flow. While
the request runs it reads `Building deck…` and is disabled. On 201 a bar shows `Deck ready · Open` for 10 s, where
`Open` links to `#/reporting`; on any other status the bar shows the `detail`.

## Fixtures

- **Demo plan**, **Done plan D**, **Bar chart C**, **Flow F**: as in `agent-board`.
- **Seed holdings**: the e2e stack's `arp portfolio seed-demo`.
- **Season 2031 votes** (written straight to the tables by the test, `source: "ac_vote_2031"`):

  | Meeting | Issuer (`company_id` null) | `meeting_date` | Item | `proponent`, `categories` | Decisions (`vote`, `against_management`, `run_id`, `decided_at`) |
  |---|---|---|---|---|---|
  | M1 | `issuer_name` `Alpha AG` | 2031-03-10 | i1 | management, `["SAY-ON-PAY"]` | against, true, null |
  | M1 | | | i2 | management, `["DIRECTOR ELECTION"]` | for, false, null |
  | M2 | `issuer_name` `Beta plc` | 2031-04-02 | i3 | shareholder, `[]` | for, true, null |
  | M2 | | | i4 | management, `["AUDITOR"]` | withhold, false, null |
  | M2 | | | i5 | management, `["CAPITAL"]` | for, false, `r1`, 2031-04-01T09:00Z; then against, true, `r2`, 2031-04-03T09:00Z |

  Expected: `votes` 5, `for` 2, `against` 2, `abstain` 1, `other` 0, `against_management` 3.
- **Stand-in code** comes from `$ARP_STANDINS_DIR/explore.json` as in `agent-panel-code-mode`.
- **Done plan D** additionally has `brief` `Rank the sectors of the demo index by weight and explain each change since June`.
- **Board B4** on Done plan D: note `N` (source `Why: weights from step 1`), chart `C` (Bar chart C), table `T`
  (columns `["sector", "weight"]`, rows `[["Energy", 0.125], ["Utilities", 0.31]]`), flow `F` (Flow F), in that order.

## Acceptance

Superseded: `agent-panel-code-mode` AC-11 and AC-12 (the catalog's ids and lanes) are replaced by AC-1 and AC-2 here;
their hidden tests retire with slice 1, which owns AC-1 (the sandbox lane), and slice 2 owns AC-1b and AC-2 (the
whole list). In rows, `E(code)` means `POST /api/agent/explorations` with a stand-in whose
code is `code`, and `B` is `/api/agent/boards/plan/<id>` for the plan named in "Given".

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The app after slice 1 | `GET /api/capabilities` | the entries with `lane: "sandbox"` come first, all with `effect: "read"`, ids in this order: `benchmark_sectors`, `holdings`, `portfolio_exposure`, `sector_issuers`, `smart_search`, `transition_plan`, `vote_summary` | holdout |
| AC-1b | The app after slice 2 | `GET /api/capabilities` | ids in this order: `benchmark_sectors`, `holdings`, `portfolio_exposure`, `sector_issuers`, `smart_search`, `transition_plan`, `vote_summary`, `decision_score`, `document_discovery`, `emerging_themes`, `extraction`, `financials_extraction`, `identity_resolution`, `index_construct`, `report_render`, `strategy_backtest`, `strategy_spec`, `taxonomy_research`, `tnfd_extraction`, `transition_plan_assessment`, `universe_build`, `xbrl_facts` | holdout |
| AC-2 | The app after slice 2 | `GET /api/capabilities` | the first 7 entries have `lane: "sandbox"`, `effect: "read"`; the other 15 have `lane: "plan"`, `effect: "run"` | holdout |
| AC-3 | No benchmark uploaded | `E(return await codemode.sector_issuers({sector: "Utilities"}))` | `status: "done"`; `result` is `{"benchmark_id": null, "name": "Synthetic sample", "is_sample": true, "sector": "Utilities", "issuers": [{"issuer_id": "SYN02", "name": "Synthetic Company 02", "weight_pct": 0.3}, {"issuer_id": "SYN11", "name": "Synthetic Company 11", "weight_pct": 0.08}]}` | holdout |
| AC-4 | No benchmark uploaded | `E` with the deck's benchmark program: `const {sectors} = await codemode.benchmark_sectors({}); return Promise.all(sectors.slice(0, 2).map(async s => ({sector: s.sector, weight_pct: s.weight_pct, largest: (await codemode.sector_issuers({sector: s.sector})).issuers[0].name})))` | `result` is `[{"sector": "Information Technology", "weight_pct": 3.1, "largest": "Synthetic Company 03"}, {"sector": "Financials", "weight_pct": 1.4, "largest": "Synthetic Company 07"}]`; `tool_calls` has 3 rows | holdout |
| AC-5 | No benchmark uploaded | `E(return await codemode.sector_issuers({sector: "Nope"}))` | `result.issuers` is `[]` | holdout |
| AC-6b | One benchmark uploaded | `sector_issuers` with `benchmark_id: null`, `sector: "Energy"` | 422, `{"detail": "benchmark_id is required"}` | unit |
| AC-6 | One benchmark uploaded | `E(return await codemode.sector_issuers({benchmark_id: "zz", sector: "Energy"}))` | `status: "failed"`; `error` contains `sector_issuers: unknown benchmark: zz` | unit |
| AC-7 | Seed holdings (fewer than 500 companies) | `E(return await codemode.holdings({as_of: "2099-12-31"}))` (each portfolio's newest snapshot) | `status: "done"`; `rows_omitted: 0`; the `weight_pct` values sum to 100 within 0.01; rows sorted by `weight_pct` descending | holdout |
| AC-8 | Same | `E(return await codemode.holdings({as_of: "30.09.2026"}))` | `status: "failed"`; `error` contains `holdings: as_of must be YYYY-MM-DD` | holdout |
| AC-8b | A store with portfolio P holding company X (market value 300 EUR) and Y (100 EUR), and one security without a company (100 EUR), as of 2026-09-30 | `holdings` with `as_of: "2026-09-30"`, `limit: 2` | `total_market_value_eur: 500`; rows `X` 60.0, then `(unresolved)` 20.0 (tie broken by `company_id`: `(` sorts before `Y`); `rows_omitted: 1` | unit |
| AC-9 | Season 2031 votes | `E(return await codemode.vote_summary({season: 2031, group_by: "topic"}))` | `result.totals` is `{"votes": 5, "for": 2, "against": 2, "abstain": 1, "other": 0, "against_management": 3, "against_management_pct": 60.0}` | holdout |
| AC-10 | Same | same | `result.rows` keys in order `Shareholder proposals`, `Remuneration`, `Director elections`, `Auditors`, `Capital and other`, with `votes` 1 each and `against_management` 1, 1, 0, 0, 1 | holdout |
| AC-11 | Same | `vote_summary({season: 2031, group_by: "issuer"})` | rows in order: `Beta plc` (`votes` 3, `against_management` 2, `against_management_pct` 66.7), `Alpha AG` (2, 1, 50.0); each `name` equals its `key` | holdout |
| AC-12 | Same | `vote_summary({season: 2031, group_by: "month"})` | rows `2031-03` (`votes` 2, `against_management` 1) then `2031-04` (3, 2) | holdout |
| AC-13 | Same | `vote_summary({season: 2031, group_by: "fund"})` | `status: "failed"`; `error` contains `vote_summary: group_by must be topic, issuer or month` | holdout |
| AC-14 | Season 2031 votes plus 3 more issuers with one decision each | `vote_summary({season: 2031, group_by: "issuer", limit: 2})` | 2 rows; `rows_omitted: 3` | unit |
| AC-15 | Season 2031 votes | `vote_summary({season: 2030, group_by: "topic"})` and no 2030 ledger rows | `totals.votes: 0`, `totals.against_management_pct: null`; 5 topic rows, each `votes: 0` | unit |
| AC-16 | Must not change: the Steward Cockpit | `GET /api/stewardship/cockpit` before and after slice 1 on the same data | the `voting` section is identical | unit |
| AC-17 | Must not change: no benchmark uploaded | `E(return await codemode.benchmark_sectors({}))` | `result` equals the JSON of the card `ask.benchmark_sectors` returns for `benchmark_id: null` (the sample card), as before slice 1 | holdout |
| AC-18 | A script `u = universe_build(taxonomy_id="t", source="s.csv")` then `transition_plan_assessment(universe_run_id=u.run_id)` | `arp plan check s.py` | exit 0, stdout `ok` | holdout |
| AC-19 | A script `emerging_themes(universe_run_id="r", companies=["a"])` then `taxonomy_research(taxonomy_ids=["t"])` | `arp plan check s.py` | exit 0, stdout `ok` | holdout |
| AC-20 | A script `strategy_backtest(spec_run_id="s", tickers=["A"], prices_ref="p.csv", foo=1)` | `arp plan check s.py` | exit 1, stdout contains `line 1: strategy_backtest: unexpected argument foo` | holdout |
| AC-21 | The planner with a stand-in model | `arp plan draft "x"` | the system prompt in `calls.jsonl` contains `def transition_plan_assessment(`, `def emerging_themes(`, `def taxonomy_research(`, `def strategy_spec(` and `def strategy_backtest(`, and not `def vote_summary(` | holdout |
| AC-22 | A plan `s = strategy_spec(paper_citation="c", paper_text="t")` then `strategy_backtest(spec_run_id=s.id, tickers=["A"], prices_ref="p.csv")`, stub spec extractor and backtest; spec not approved | `scan()` | plan `awaiting_review`; call seq 1 `awaiting_review`; no call seq 2 | unit |
| AC-23 | The plan after AC-22; `POST /api/replication/specs/{id}/approve` | `scan()` | call seq 2 stored with `status: "done"` and `verdict` from the stub; plan `done` | unit |
| AC-24 | A plan `strategy_backtest(spec_run_id=<unapproved spec>, tickers=["A"], prices_ref="p.csv")` | run it | plan `failed`, `error` contains `spec <id> is not approved` | unit |
| AC-25 | The plan of AC-22 waiting | `GET /api/agent/inbox` | one row `{kind: "step_review", plan_id: <id>, seq: 1, exploration_id: null, href: "#/strategyReplication"}` | unit |
| AC-26 | A plan with one `emerging_themes` step, stub pipeline; `s1.finish` raises `SystemExit` once | run it twice | 1 manifest with run type `emerging_themes` and the step's launch key; plan `done` | unit |
| AC-27 | A plan `u = universe_build(...)` then `transition_plan_assessment(universe_run_id=u.run_id)`, the extraction pipeline stubbed | run it | the call's `run_id` names a manifest of run type `extraction` whose `params.schema_id` is `transition_plan_indicators` | unit |
| AC-28 | P3-style stubs where `decision_score` attaches framework `f` version 2 | run a plan with that step | the call's `result.method` is `{"framework_id": "f", "framework_version": 2}` | unit |
| AC-29 | An `index_construct` step on calibration `c` with versions 1 (effective 2026-01-01) and 2 (effective 2026-07-01), `review_date: "2026-09-30"` | run it | `result.method` is `{"calibration_id": "c", "calibration_version": 2, "review_date": "2026-09-30"}` | unit |
| AC-29b | Taxonomy `t` with released versions 1 and 2, stub theme run | run a plan with `universe_build(taxonomy_id="t", source="s.csv")` | the call's `result.method` is `{"taxonomy_id": "t", "taxonomy_version": 2}` | unit |
| AC-29c | Stub extraction | run a plan with `extraction(universe_run_id="r", schema_id="x")` | `result.method` is `{"schema_id": "x"}` | unit |
| AC-30 | A stored call result without `method` | `GET /api/plans/{id}/lineage` | that step's `method` is `{}` | unit |
| AC-31 | Done plan D, with `approved_by: "dev"` written by the test | `GET /api/plans/<D>/lineage` | HTTP 200; `steps` has 1 entry `{seq: 1, kind: "index_construct", status: "done", inputs: <its params>}`; `approved_by: "dev"` | holdout |
| AC-31b | — | `GET /api/plans/nope/lineage` | HTTP 404, `{"detail": "plan not found"}` | holdout |
| AC-32 | Demo plan selected | look at the stage | the tabs read `Board`, `Script`, `Diff`, `Audit`, `Lineage` (then `Mini-app` once shipped) | evaluator |
| AC-33 | A done plan whose `decision_score` call has `method` `{"framework_id": "f", "framework_version": 2}` and params `{"source_run_id": "r9", "framework_id": "f"}` | open its Lineage tab | that step's card reads `Inputs: framework_id=f · source_run_id=r9` and `Method: framework_id=f · framework_version=2` | evaluator |
| AC-34 | A draft plan | open its Lineage tab | the top line reads `Not approved` | evaluator |
| AC-35 | Demo plan (draft) selected | look at the stream | the strip reads `Plan Needs you`, `Run Not started`, `Review —`, `Output —` | evaluator |
| AC-36 | A plan `awaiting_review` at seq 2 on run `r_2` of type `extraction` | look at the strip | `Review` reads `Needs you` and links to `#/review/extraction/r_2` | evaluator |
| AC-37 | Done plan D | press `Ready` in the strip | the Lineage tab is selected | evaluator |
| AC-38 | Frontend test: each row of both mapping tables | render the strip | the four state words equal that row | unit |
| AC-39 | An exploration `done`, not accepted | look at the strip | `Code Checked`, `Run Complete`, `Review Needs you`, `Output Exploratory` | evaluator |
| AC-40 | Done plan D, empty board | `POST B/blocks` table `T` with columns `["issuer", "quote"]`, rows `[["Harbor Steel", {"text": "24% of capex", "source": {"label": "p. 18", "href": "#/review/extraction/r1"}}]]` | HTTP 201; `unverified_quotes: ["24% of capex"]` (not in Done plan D's data) | holdout |
| AC-41 | Same | same with `"href": "https://example.com"` | HTTP 422, `{"detail": "cell 1,2: source link must start with #/ or /api/"}` | holdout |
| AC-42 | Same | same with `"href": "/api//evil"` | HTTP 422, same detail | holdout |
| AC-43 | Same | same with the cell `{"text": "x"}` | HTTP 422, `{"detail": "cell 1,2: invalid quote cell"}` | holdout |
| AC-44 | A plan whose stored result holds the string `Lower-emissions capex was   24% of capex in FY2025` (three spaces after `was`) | `POST B/blocks` with the quote cell text `capex was 24% of capex` | `unverified_quotes: []` | holdout |
| AC-44b | Done plan D | `POST B/blocks` the table of AC-40 with `"unverified_quotes": ["x"]` in the body | `unverified_quotes: ["x"]` | holdout |
| AC-45 | The block of AC-40 | open the Board tab | the cell shows `“24% of capex”` and a link `p. 18` to `#/review/extraction/r1`; under the table a line reads `Quotes not in ARP data: 1` | evaluator |
| AC-46 | The block of AC-40 | `⋯`, `Download` | `T.csv` line 2 reads `Harbor Steel,24% of capex (p. 18)` | evaluator |
| AC-47 | Done plan D with Board B4 | `POST B/deck` `{}` | HTTP 201; `status: "completed"`; `output_files` contains `output.pptx` and `output.pdf` | unit |
| AC-48 | Same | open `output.pptx` | 4 slides: cover, chart, table, flow, in that order; slide titles `Rank the sectors of the demo index by weight and`, `C`, `T`, `F` | unit |
| AC-49 | Same | read the chart slide's speaker notes | they equal `Why: weights from step 1` | unit |
| AC-50 | Same | look at the table slide | it shows the cells `Energy`, `0.125`, `Utilities`, `0.31` | unit |
| AC-51 | Same | look at the chart slide | it holds one picture, the PNG registered as report image `block-2.png` | unit |
| AC-52 | Done plan D, board with one table of 3 columns and 20 rows | `POST B/deck` | the deck has 4 slides: cover and 3 table slides (rows 1–8, 9–16, 17–20) | unit |
| AC-53 | Done plan D, board with only a note | `POST B/deck` `{}` | HTTP 422, `{"detail": "the board has no chart, table or flowchart"}`; `GET /api/reporting` lists as many reports as before | holdout |
| AC-54 | Done plan D, board with a table of 7 columns titled `Wide` | `POST B/deck` `{}` | HTTP 422, `{"detail": "table \"Wide\" has 7 columns; a deck table has 2 to 6"}` | holdout |
| AC-55 | Done plan D, board with 21 charts | `POST B/deck` `{}` | HTTP 422, `{"detail": "a deck holds at most 20 charts"}` | holdout |
| AC-55b | Done plan D, board with a table titled `Dup` whose columns are `["a", "a"]` | `POST B/deck` `{}` | HTTP 422 whose `detail` starts `Dup: `; `GET /api/reporting` lists as many reports as before | holdout |
| AC-56 | An exploration not accepted, with a board holding one table | `POST /api/agent/boards/exploration/<E>/deck` `{}` | the table slide's source line reads `Exploratory: not reviewed` | unit |
| AC-57 | The table from `agent-board` AC-17 (`unverified: [0.435]`) on its board | `POST B/deck` | its slide's source line reads `Not in ARP data: 0.435` | unit |
| AC-58 | Done plan D with Board B4 | press `Send to deck` | the button reads `Building deck…`, then a bar `Deck ready · Open`; `Open` goes to `#/reporting`, which lists the new deck | evaluator |
| AC-59 | Must not change: the hidden tests of `agent-panel-code-mode` (other than AC-11 and AC-12) and of `agent-board` that are in the holdout regression set when a slice's PR opens | the Holdout acceptance job's regression run on that PR | passes | unit |
| AC-60 | Must not change: the backend suite | `python3 -m pytest` | passes, with no edited test except those each PR lists | unit |
| AC-61 | Must not change: the frontend suite | `npm test` | passes, with no edited test except those each PR lists | unit |

Must not change: the cockpit's vote numbers (AC-16), Ask ARP's benchmark card (AC-17), the earlier specs' rows
(AC-59), both suites (AC-60, AC-61).

## Slices

Each PR puts `Spec: agent-research-examples` and its `Rows:` line in its description.

| Slice | PR contents | Risk | Needs | Rows |
|---|---|---|---|---|
| 1 | Read tools `holdings`, `sector_issuers`, `vote_summary` in the catalog and the tool route | `risk:normal` | `agent-panel-code-mode` slice 9 | AC-1, AC-3 to AC-17, AC-59, AC-60 |
| 2 | Plan steps `transition_plan_assessment`, `emerging_themes`, `taxonomy_research`, `strategy_spec`, `strategy_backtest`; `method` in results; inbox link | `risk:normal` | slice 1; `agent-panel-code-mode` slices 3 and 7 | AC-1b, AC-2, AC-18 to AC-30, AC-59, AC-60 |
| 3 | `GET /api/plans/{id}/lineage` and the Lineage tab | `risk:normal` | slice 2; `agent-panel-code-mode` slice 8 | AC-31 to AC-34, AC-59, AC-60, AC-61 |
| 4 | Status strip for plans and explorations | `risk:normal` | `agent-panel-code-mode` slices 7 and 10 | AC-35 to AC-39, AC-59, AC-61 |
| 5 | Quote cells: checks, `unverified_quotes` column, display, CSV, draw prompt | `risk:high` (schema) | `agent-board` slice 3 | AC-40 to AC-46, AC-59, AC-60, AC-61 |
| 6 | Send board to deck: route, PNG charts, slide mapping, button | `risk:normal` | slice 5; `agent-board` slice 4 | AC-47 to AC-58, AC-59, AC-60, AC-61 |

Slices 1 to 3 run in this order. Slice 4 needs only the `agent-panel-code-mode` slices it names. Slice 5, then 6.

## Later (own specs)

- **A read tool for reviewed facts with their source quotes** (`reviewed_facts(company, field_ids)`), so the climate
  example's quotes come from ARP data and pass the quote check.
- A deterministic holdings-to-candidates step, so `index_construct` can take a step's output instead of a candidates
  file.
- Plan steps for Signals and Value Chain Explorer.
- A stewardship decision as a plan gate (Steward · Selection).

## Defaults decided without the owner

- Tool limits: `holdings` 500 rows by default (at most 2000), `vote_summary` 200 issuer rows by default (at most 2000),
  so results stay under the sandbox's 256 KB.
- Weights are rounded to 4 decimals and rates to 1, like the cockpit's percentages.
- `triggered_by: "research_plan"` for runs a plan starts, as `document_discovery` already passes.
- The deck uses the default house template; choosing a template is left to Presentations & Reports.
- Deck tables show 8 rows per slide, the house table limit.
- The deck's output rows (AC-47 to AC-52, AC-56, AC-57) are `unit`: rendering a PDF needs a browser the e2e stack is
  not known to give the backend. AC-58 checks a real deck in the running app.
