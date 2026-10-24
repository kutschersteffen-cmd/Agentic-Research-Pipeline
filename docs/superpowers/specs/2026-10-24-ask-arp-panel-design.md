# Ask ARP: one chat panel for plain-language questions

Date: 2026-10-24
Status: draft for the owner's approval
Owner decisions on 2026-10-24: approach A (one endpoint that picks a tool, history kept in the browser); the
first three questions it must answer are the owner's own (below); "review the data" means a check block shown
above the chart.

## Intent

Today each plain-language agent lives on its own page and answers one question at a time: Ask the Portfolio
(`backend/arp/portfolio/qa_agent.py`), Smart Search (`backend/arp/smart_search.py`) and BI ask. A person has to
know which page answers which question, and cannot ask a follow-up.

This adds one chat panel, reachable from every page, that takes a question, picks the right tool, and shows the
answer as a card with its source. A follow-up ("now only equities") is understood in the light of the last few
turns. The rule that holds everywhere else holds here: **the model picks the tool and words the question; code
computes every number shown.**

The owner's first three questions, which this spec must answer:

1. "What is the exposure to BMW in our portfolio?"
2. "Show me the newest transition plan assessments of BASF."
3. "Review the data and build a chart on the sector distribution across MSCI World."

## Goals

1. One panel, opened from an Ask button or Ctrl/⌘J on any page, that answers the three questions above.
2. Follow-up questions work for up to 5 previous turns.
3. Every figure in an answer comes from an existing engine or a code sum, with its source and date on the card
   (the synthetic sample has no date and says so).
4. Questions the panel cannot answer get a plain "can't answer that yet" with what it can answer.

## Non-goals

- Saving conversations on the server or reopening them later (approach B; can be added on top of this).
- Streaming replies, multi-step agents, Claude tool calling (approach C).
- BI ask: it saves every chart to the shared Superset scratch dashboard, and the panel must not create things as
  a side effect.
- Questions about what a document says, why a review item was flagged, or how to use the app (suggestions 2, 3
  and 5; separate specs).
- Starting, changing or approving anything from the panel. It only reads.
- Changing Ask the Portfolio, Smart Search or their pages.

## Anti-goals (a failure even if it technically works)

- A number on a card that the model wrote rather than code computed.
- The sample's 12 fictional companies shown as if they were MSCI World.
- A transition plan assessment shown as "newest" when a newer completed one exists, or one shown without its
  run date and review state.
- An answer that leaves no audit row.

## Approaches considered

- **A. One `POST /api/ask` that routes to a tool, history sent by the browser (picked).** Reuses
  `complete_structured` and the existing engines. About 3 days. Trade-off: closing the tab loses the
  conversation.
- B. As A, with threads and turns in Postgres. About 1.5 extra days plus a migration. Deferred: build it once
  people show they come back to old chats; A's request shape does not need to change for it.
- C. A multi-step agent with Claude tool calling. About 1.5 to 2 weeks, a new model-calling style every other
  agent avoids, and provenance gets harder. More than the three questions need.


## How it works

### Request

`POST /api/ask` with

```json
{ "question": "now only equities",
  "history": [ { "question": "What is the exposure to BMW in our portfolio?", "tool": "portfolio",
                 "standalone_question": "What is the exposure to BMW in our portfolio?" } ] }
```

- `question`: 1 to 1,000 characters.
- `history`: optional, default `[]`; 0 to 5 turns, oldest first. Each turn has exactly the three keys above; any other key (an answer, a
  figure) is a 422. More than 5 turns is a 422.
- Access: `POST` needs `analyst` or higher (the router-level `authorize` rule), as for Ask the Portfolio.
- A 422 or 403 never reaches the handler and writes no audit row.

### Response

```text
AskResponse
  tool:                "portfolio" | "smart_search" | "transition_plan" | "benchmark_sectors" | "none"
  question:            str   # as typed
  standalone_question: str   # rewritten to read on its own; the browser sends it back as history
  answer_text:         str   # always set; built by code, see below
  answered_at:         str   # server time in UTC, ISO 8601, when the answer was built
  portfolio:           QAAnswer | null          # set only when tool = portfolio
  smart_search:        SearchAnswer | null      # set only when tool = smart_search
  transition_plan:     TransitionPlanCard | null
  benchmark_sectors:   BenchmarkCard | null

TransitionPlanCard
  company:      str          # the matched row's Company
  company_id:   str          # its Company_Id
  run_id:       str
  run_type:     "transition_plan" | "extraction"
  run_date:     str          # the run manifest's created_at string, unchanged
  figures:      { indicators_disclosed_count, walk_disclosed_count, talk_disclosed_count,
                  walk_share_pct, assessment_confidence_pct }   # numbers, from the run's row
  open_review_items: int     # review items of this run and company not yet in a final state
  older_runs:   [ { run_id, run_date } ]   # at most 2, newest first; run_date as above

BenchmarkCard
  benchmark_id: str | null   # null for the sample
  name:         str          # the benchmark's stored name, or "Synthetic sample"
  is_sample:    bool
  check:        { source, as_of, constituents, dropped, unclassified_pct, total_pct }
  sectors:      [ { sector, weight_pct } ]
```

When a tool cannot give figures (no match, several matches), its card is `null` and `answer_text` says why.

For `portfolio` and `smart_search`, `answer_text` is the agent's own `answer_text` when it is resolvable (both
agents build it from the computed result in code), else the agent's `clarification_needed`. The other tools' texts
are given below.

### Routing (the only new model call)

One `complete_structured` call. Output model, with no number fields:

- `tool`: one of the five values.
- `standalone_question`: the question rewritten using the history.
- `company`: the company as the user wrote it (for `transition_plan`), else null.
- `benchmark_id`: one id from the uploaded benchmarks listed in the prompt, or null.

`portfolio` and `smart_search` then call `qa_agent.answer_question` and `smart_search.smart_search` with
`standalone_question`. Those agents keep their own prompts and their own model call, so a portfolio question
makes two model calls. Smart Search's three input lists are built the way `POST /api/smart-search` builds them;
moving that code into a shared function is fine if the endpoint's behaviour stays the same (AC-27).

### Transition plan

Code, no model:

1. **Candidate runs (my call):** runs of type `transition_plan`, plus extraction runs on the transition plan
   preset (`is_transition_plan_preset_run`), with status `completed` or `partially_completed`. A partial run can
   still hold a valid row for the company. Trial runs (`params.trial`) are left out, as `run_store.extraction_runs()`
   leaves them out.
2. Read each with `decision.sources.from_transition_plan_run`, which gives both kinds the same columns.
3. If `company` is null or normalises to an empty string: `transition_plan` is null and `answer_text` is
   `Which company do you mean?`
4. **Matching:** normalise `company` and each row's `Company` with `_normalised_name` in `decision/sources.py`
   (lowercase, letters and digits only: "BASF SE" becomes `basfse`). A row matches when its normalised name equals
   or contains the normalised `company`.
5. **The run:** the newest candidate (by `created_at`) with at least one matching row. Within that run, rows whose
   normalised name equals `company` win over rows that only contain it.
   - One company left: it is the answer.
   - Several companies left: `transition_plan` is null and `answer_text` is
     `Several companies match "<company>": <names, sorted, comma-separated>. Which one do you mean?`
   - No candidate run has a match: `transition_plan` is null and `answer_text` is
     `No completed transition plan assessment includes <company>.`
6. **Figures:** the row's `Indicators_Disclosed_Count`, `Walk_Disclosed_Count`, `Talk_Disclosed_Count`,
   `Walk_Share_pct`, `Assessment_Confidence_pct`. These are the figures as extracted, the same ones Decision
   Studio scores; reviewer corrections are not applied to them (my call: the same truth as Decision Studio).
7. **Review state (my call):** `open_review_items` counts the items of that run and company that
   `review.items.list_open_items` returns for the caller. This is what the Review Queue shows the same person. The
   stored `Needs_Review_Flag` is not used, because review decisions never clear it.
8. `older_runs`: the next 2 older candidate runs with a row whose normalised `Company` equals the chosen row's
   normalised `Company`, newest first.
9. `answer_text`: `<company>: newest transition plan assessment from <run date YYYY-MM-DD> (run <run_id>).`, then
   ` <n> items still wait for review.` when `open_review_items` > 0.

### Benchmark sectors

Code, no model, from `stewardship.benchmark.BenchmarkStore`:

1. **Uploaded benchmarks exist:** use routing's `benchmark_id`. If it is null or not an uploaded id,
   `benchmark_sectors` is null and `answer_text` is `Which benchmark do you mean: <names, sorted, comma-separated>?`
2. **None uploaded:** use the stewardship sample (`stewardship/data/examples/sample_meetings.json`). It has 12
   issuers, each with `sector` and `holding.index_weight_pct`, and its weights do not sum to 100.
3. **Check** (this is "review the data"):
   - `source`: the benchmark's stored `source` (e.g. "iShares holdings export"), or "synthetic sample"
   - `as_of`: its "Fund Holdings as of" date, or null for the sample
   - `constituents`: count
   - `dropped`: the stored `dropped` count, 0 for the sample
   - `total_pct`: sum of weights, two decimals
   - `unclassified_pct`: weight with an empty sector ÷ total weight × 100, two decimals
4. **Sectors:** sum of weights per sector, two decimals, largest first, ties by sector name. An empty sector is
   reported as "Unclassified".
5. `answer_text`: `Sector weights of <name> as of <as_of>.` For the sample: `Synthetic sample: 12 fictional
   companies standing in for MSCI World. Upload the iShares URTH holdings file under Stewardship → Benchmarks for
   the real index.`

### Nothing to answer

`tool` = `none`: `answer_text` is `I can't answer that yet. I can answer: portfolio exposure; data issues, outputs
and feeds; a company's newest transition plan assessment; a benchmark's sector weights.`

### Errors

Any exception after the request is validated (routing, an agent, a store) returns 502 with
`{"detail": "Ask could not answer this question. Try again."}`.

### Audit

Every handled call (200 or 502) appends one `qa_audit` row:
- `endpoint`: `ask.<tool>`, or `ask.error` when routing itself failed
- `question`: the question as typed, not the standalone one
- `error`: set on a 502

`portfolio` and `smart_search` call the agents directly, not through their endpoints, so each question writes
one row, not two.

### Panel (frontend)

- **Opening (my call):** desktop has no top bar (`.app-topbar` is hidden above 1024 px). So:
  - a button "Ask ARP" with the shortcut shown sits in the sidebar, under "Jump to…";
  - at 1024 px and below, an "Ask" button also sits in the top bar, so phones reach it without opening the menu;
  - Ctrl/⌘J works everywhere;
  - viewers see neither button, and the shortcut does nothing for them.
- **Open and close:** the panel opens on the right with focus in the input. Esc or the close button closes it and
  focus returns to the button that opened it. When opened by shortcut, focus returns to the Ask button visible at
  that width: the sidebar "Ask ARP" button above 1024 px, the top-bar "Ask" button at 1024 px and below.
- **Keeping the conversation:** the panel lives in the app shell, so it survives moving between pages. It is
  also kept in `sessionStorage`, so a reload keeps it. "Clear" empties both.
- **History sent:** the browser sends the newest 5 answered turns as `history`. A turn that ended in an error is
  shown but never sent.
- At 640 px and below, the panel takes the full screen.
- **Turns:** each turn shows the question, then its card. Every card starts with `answer_text`.
  - The portfolio card shows its query's filters (company, asset class and the other `security_filter` values).
  - The transition plan card always shows `open_review_items`, 0 included.
  - Portfolio cards reuse `AggregationResultTable`, Smart Search cards reuse the Smart Search page's row list, and
    the benchmark card draws `sectors` with `BarChart` above a table of the same numbers, under the check block.
  - Each card ends with a source line:
    - portfolio: `Source: holdings engine · holdings as of <vintage.holdings_as_of>`
    - smart_search: `Source: Data Hub lists · <answered_at as YYYY-MM-DD HH:MM> UTC`
    - transition_plan: `Source: run <run_id> · <run date YYYY-MM-DD>`
    - benchmark: `Source: <name> · as of <as_of>` or `Source: synthetic sample`
- **Running and errors:** while a question runs, the input and Send are disabled and the card reads `Working…`. On
  an error, the card shows the response's `detail` text and Send is enabled again.

## Constraints

- Postgres, the run store and the benchmark store are read as they are; no new tables, no migration.
- `complete_structured` only; no free-text model output.
- API contract: export OpenAPI and regenerate `schema.gen.ts`; add the endpoint to `frontend/src/api/contract.ts`.
- The route lives in a new module `backend/arp/ask.py` with a new router. It does not touch `arp/llm`,
  `arp/extraction` or grounding, so the golden set does not run.

## Left to the builder

- Prompt wording, provided the output model above is kept.
- Card layout and copy beyond the exact texts in this spec and the Acceptance table.
- Whether the router module is one file or two.
- How an open review item is tied to a company (its payload's company id), as long as AC-9 holds.

## Calls I made (the owner can override any)

1. Runs that count: `completed` and `partially_completed`, never trial runs.
2. Review state from the open items in the review queue, not the stored flag.
3. Figures as extracted, the same as Decision Studio, without reviewer corrections.
4. The Ask button sits in the sidebar on desktop, and also in the top bar at 1024 px and below.
5. Access: analyst and up, as for Ask the Portfolio.
6. Routing quality is checked by the evaluator with your three questions and follow-ups (AC-29 to AC-32), with no
   scored routing test set. A scored set (for example 30 labelled questions, at least 95% routed right) would need
   a new golden-set kind, which is more than this change needs. Say if you want it.

## Acceptance

Backend rows replace the model with stand-ins: one for routing and, on the portfolio and Smart Search paths, one
for the downstream agent. Each stand-in returns the same fixed output on every call. `evaluator` rows use the
real model in the running app.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture holdings where BMW's lines total EUR 1,234,567.00; routing stand-in → `portfolio`, `standalone_question` "What is the exposure to BMW in our portfolio?"; qa_agent stand-in → spec `{security_filter: {company_id: "bmw"}, group_by: "company_id", metric: "market_value_sum"}` | `POST /api/ask` `{"question": "What is the exposure to BMW in our portfolio?", "history": []}` as an analyst | 200; `tool` = `portfolio`; `portfolio` equals, field for field, the body of `POST /api/portfolio/ask` for the same question with the same stand-in; its result row for `bmw` is 1234567.0; `answer_text` = that body's `answer_text` | holdout |
| AC-2 | A feed that is behind; routing stand-in → `smart_search`, `standalone_question` "Which feeds are behind?"; smart_search stand-in → filter `{target: "feeds", behind: true}` | `POST /api/ask` `{"question": "Which feeds are behind?", "history": []}` | 200; `tool` = `smart_search`; `smart_search` equals, field for field, the body of `POST /api/smart-search` for the same question with the same stand-in; `answer_text` = that body's `answer_text` | holdout |
| AC-3 | Candidate runs incl. "BASF SE": completed `transition_plan` run created 2026-09-01, completed preset extraction run created 2026-10-20; a preset run created 2026-10-23 with status `running` whose rows also include BASF SE; routing stand-in → `transition_plan`, `company` "BASF" | `POST /api/ask` | `transition_plan.run_id` = the 2026-10-20 run; `run_date` = that run manifest's `created_at` string; `company` = "BASF SE" | holdout |
| AC-4 | As AC-3 | `POST /api/ask` | the five `transition_plan.figures` equal the 2026-10-20 run's BASF SE row from `from_transition_plan_run` (`Indicators_Disclosed_Count` … `Assessment_Confidence_pct`) | holdout |
| AC-5 | Four completed runs incl. "BASF SE", created d1 < d2 < d3 < d4 | `POST /api/ask`, `company` "BASF" | `run_id` = d4's run; `older_runs` = [{d3 run, d3}, {d2 run, d2}] | holdout |
| AC-53 | Completed runs d1 < d2 < d3 < d4; d4, d2 and d1 have "BASF SE"; d3 has only "BASF Coatings GmbH" | `POST /api/ask`, `company` "BASF" | `run_id` = d4's run; `older_runs` = [{d2 run, d2}, {d1 run, d1}] | holdout |
| AC-55 | Routing stand-in → `transition_plan`, `company` null | `POST /api/ask` | 200; `transition_plan` null; `answer_text` = `Which company do you mean?` | holdout |
| AC-6 | Newest matching run is `partially_completed` (created 2026-10-22) and has a BASF SE row; an older completed one exists | `POST /api/ask`, `company` "BASF" | `run_id` = the 2026-10-22 run | holdout |
| AC-7 | Newest matching run is a preset run with `params.trial` true; an older non-trial completed run includes BASF SE | `POST /api/ask`, `company` "BASF" | `run_id` = the older non-trial run | holdout |
| AC-8 | No candidate run includes BASF | `POST /api/ask`, `company` "BASF" | 200; `tool` = `transition_plan`; `transition_plan` null; `answer_text` = `No completed transition plan assessment includes BASF.` | holdout |
| AC-9 | As AC-3; the 2026-10-20 run has 3 review items for BASF SE (1 approved, 2 pending) and 1 pending item for another company; the 2026-09-01 run has 1 pending BASF SE item | `POST /api/ask` as the analyst who decided none of them | `open_review_items` = 2; `answer_text` ends ` 2 items still wait for review.` | holdout |
| AC-10 | As AC-9, but all 3 items approved | `POST /api/ask` | `open_review_items` = 0; `answer_text` = `BASF SE: newest transition plan assessment from 2026-10-20 (run <run_id>).` | holdout |
| AC-11 | Newest matching run has rows "BASF" and "BASF SE" | `POST /api/ask`, `company` "BASF" | `transition_plan.company` = "BASF" (the exact match wins) | holdout |
| AC-12 | Newest matching run has rows "BASF SE" and "BASF Coatings GmbH" | `POST /api/ask`, `company` "BASF Coat" | `transition_plan.company` = "BASF Coatings GmbH" | holdout |
| AC-13 | Newest matching run has rows "Shell plc" and "Shell Midstream Partners" | `POST /api/ask`, `company` "Shell" | `transition_plan` null; `answer_text` = `Several companies match "Shell": Shell Midstream Partners, Shell plc. Which one do you mean?` | holdout |
| AC-14 | One uploaded benchmark "iShares MSCI World ETF", source "iShares holdings export", as of "Oct 20, 2026", dropped 3; constituents A (Information Technology, 30.0), B (Information Technology, 20.004), C (Financials, 40.0), D ("", 9.996); routing stand-in → `benchmark_sectors` with its id | `POST /api/ask` | `benchmark_sectors.sectors` = [{Information Technology, 50.0}, {Financials, 40.0}, {Unclassified, 10.0}], in that order | holdout |
| AC-15 | As AC-14 | `POST /api/ask` | `benchmark_sectors.check` = {source "iShares holdings export", as_of "Oct 20, 2026", constituents 4, dropped 3, unclassified_pct 10.0, total_pct 100.0}; `is_sample` false; `name` "iShares MSCI World ETF" | holdout |
| AC-16 | One uploaded benchmark with weights A (Energy, 72.0), B ("", 8.0) | `POST /api/ask` | `check.total_pct` 80.0; `check.unclassified_pct` 10.0 | holdout |
| AC-17 | No uploaded benchmark; routing stand-in → `benchmark_sectors`, `benchmark_id` null | `POST /api/ask` | `is_sample` true; `check.constituents` 12; `check.dropped` 0; `check.total_pct` = the sum of the sample's 12 `index_weight_pct` to two decimals; `name` = `Synthetic sample`; `benchmark_id` null; `check.source` = `synthetic sample`; `check.as_of` null; `answer_text` starts `Synthetic sample: 12 fictional companies standing in for MSCI World.` | holdout |
| AC-18 | Uploaded benchmarks "B Index" and "A Index"; routing stand-in `benchmark_id` null, then (second call) `benchmark_id` "nope" | `POST /api/ask` twice | both: `benchmark_sectors` null; `answer_text` = `Which benchmark do you mean: A Index, B Index?` | holdout |
| AC-19 | Routing stand-in → `none` | `POST /api/ask` `{"question": "What did BMW say about cobalt?"}` (no `history` key) | 200; `answer_text` = `I can't answer that yet. I can answer: portfolio exposure; data issues, outputs and feeds; a company's newest transition plan assessment; a benchmark's sector weights.` | holdout |
| AC-20 | `history` with 5 valid turns / with 6 turns | `POST /api/ask` | 200 / 422 | holdout |
| AC-21 | `question` of 1,000 characters / empty / 1,001 characters | `POST /api/ask` | 200 / 422 / 422 | holdout |
| AC-22 | A history turn with an extra key `answer` | `POST /api/ask` | 422 | holdout |
| AC-23 | A viewer | `POST /api/ask` | 403 | holdout |
| AC-24 | One call each for AC-1, AC-2, AC-3, AC-14, AC-19, and a follow-up `{"question": "now only equities", history: [AC-1's turn]}` | then `GET /api/portfolio/qa-audit` as an approver | exactly 6 new rows; in call order, their `endpoint` values are `ask.portfolio`, `ask.smart_search`, `ask.transition_plan`, `ask.benchmark_sectors`, `ask.none`, `ask.portfolio`; the follow-up call's row has `question` = "now only equities" | holdout |
| AC-25 | Routing stand-in raises | `POST /api/ask` | 502; `detail` = `Ask could not answer this question. Try again.`; one new audit row with `endpoint` `ask.error` and `error` set | holdout |
| AC-50 | Routing stand-in → `transition_plan`; the run store raises when read | `POST /api/ask` | 502; `detail` = `Ask could not answer this question. Try again.`; one new audit row with `endpoint` `ask.transition_plan` and `error` set | holdout |
| AC-26 | A request rejected with 422 (AC-21) and one with 403 (AC-23) | `GET /api/portfolio/qa-audit` | no new audit row for either | holdout |
| AC-29 | Running app, real model, holdings incl. BMW | Ask "What is the exposure to BMW in our portfolio?" | the card's EUR figure equals what the Ask the Portfolio page shows for the same question | evaluator |
| AC-30 | Two completed transition plan runs incl. BASF, on different dates | Ask "Show me the newest transition plan assessments of BASF." | the card shows the newer run's date, its figures and its number of open review items (0 shown as 0), and lists the older run under it | evaluator |
| AC-31 | The URTH file uploaded under Stewardship → Benchmarks | Ask "Review the data and build a chart on the sector distribution across MSCI World." | the card shows the check block (source, as of, constituents, dropped, unclassified, total) above a sector bar chart and a table of the same numbers | evaluator |
| AC-32 | After AC-29 | Ask "now only equities" | the card's filter shows company `bmw` and asset class `equity`, and the figure equals Ask the Portfolio's answer to "What is the exposure to BMW in equities in our portfolio?" | evaluator |
| AC-33 | After AC-29 to AC-32 and one more question (5 earlier turns) | Ask "go back to the BMW question, total across all asset classes" | the figure equals AC-29's | evaluator |
| AC-34 | One card of each kind on screen | Look at each card's last line | it reads as in §Panel (frontend) for its kind, with a date, except the sample's line, which reads exactly `Source: synthetic sample` | evaluator |
| AC-35 | Analyst, desktop width (1280 px) | Click "Ask ARP" in the sidebar | the panel opens with focus in the input | evaluator |
| AC-36 | Analyst, 390 px wide | Tap "Ask" in the top bar | the panel opens with focus in the input | evaluator |
| AC-37 | Analyst, any page | Press Ctrl/⌘J | the panel opens with focus in the input | evaluator |
| AC-38 | Panel opened by Ctrl/⌘J at 1280 px | Press Esc | the panel closes; focus is on the sidebar "Ask ARP" button | evaluator |
| AC-51 | Panel opened by Ctrl/⌘J at 390 px | Click the close button | the panel closes; focus is on the top-bar "Ask" button | evaluator |
| AC-52 | Panel opened by the top-bar "Ask" button at 390 px | Press Esc | focus is on the top-bar "Ask" button | evaluator |
| AC-39 | Two turns in the panel | Navigate to another page | both turns are still shown | evaluator |
| AC-40 | Two turns in the panel | Reload the page | both turns are still shown | evaluator |
| AC-41 | Two turns in the panel | Click "Clear", then reload | 0 turns shown, before and after the reload | evaluator |
| AC-42 | Viewer, desktop and 390 px | Look at the sidebar and top bar; press Ctrl/⌘J | no Ask button anywhere; the shortcut opens nothing | evaluator |
| AC-43 | A question in flight | Look at the panel | input and Send disabled; the card reads `Working…` | evaluator |
| AC-44 | The API returns 502 | Look at the card, then at Send | the card shows `Ask could not answer this question. Try again.`; Send is enabled | evaluator |
| AC-45 | 390 px wide | Open the panel | the panel is 390 px wide, covering the page | evaluator |
| AC-48 | 6 answered turns in the panel | Ask a 7th question | the card shows an answer, not an error; the request's `history` holds the newest 5 turns | evaluator |
| AC-49 | Running app, real model | Ask "What did BMW say about cobalt?" | the card reads `I can't answer that yet. I can answer: portfolio exposure; data issues, outputs and feeds; a company's newest transition plan assessment; a benchmark's sector weights.` and shows no figures | evaluator |
| AC-54 | One answered turn, then a turn that ended in a 502 | Ask another question | the card shows an answer; the request's `history` holds only the answered turn | evaluator |
| AC-46 | 390 px wide, AC-31's card shown | Scroll sideways | `document.documentElement.scrollWidth` ≤ 390; chart labels neither overlap nor are cut off | evaluator |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-27 | The existing backend tests for `POST /api/portfolio/ask` and `POST /api/smart-search` | Run them | they pass with no test file changed, and each endpoint still writes one audit row (`portfolio.ask`, `datahub.smart_search`) | unit |
| AC-28 | Counts of runs, benchmarks, review decisions and published facts | `POST /api/ask` once per tool (AC-1, AC-2, AC-3, AC-14, AC-19) | those counts are unchanged; the `qa_audit` row count grew by exactly 5 | holdout |
| AC-47 | The existing frontend tests for the Ask the Portfolio and Smart Search pages | Run them | they pass with no test file changed | unit |
