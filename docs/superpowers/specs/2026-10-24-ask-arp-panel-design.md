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

1. One panel, opened from a top-bar button or Ctrl/⌘J on any page, that answers the three questions above.
2. Follow-up questions work for up to 5 previous turns.
3. Every figure in an answer comes from an existing engine or a code sum, with its source and date on the card.
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

### Request and response

`POST /api/ask` with

```json
{ "question": "now only equities",
  "history": [ { "question": "What is the exposure to BMW in our portfolio?", "tool": "portfolio",
                 "standalone_question": "What is the exposure to BMW in our portfolio?" } ] }
```

- `question`: 1 to 1,000 characters.
- `history`: at most 5 turns, oldest first. More than 5 is a 422. Only questions and tool names travel; never
  answers or figures.

The response is one of five card kinds, discriminated by `tool`:

| `tool` | Answers | Body |
|---|---|---|
| `portfolio` | exposures, weights, counts over holdings | the `QAAnswer` that Ask the Portfolio returns for `standalone_question` |
| `smart_search` | open data issues, stored outputs, feeds | the `SearchAnswer` that Smart Search returns for `standalone_question` |
| `transition_plan` | a company's newest transition plan assessment | see §Transition plan |
| `benchmark_sectors` | sector weights of a benchmark, with a data check | see §Benchmark sectors |
| `none` | anything else | `answer_text` saying what the panel can answer |

Every response also carries `standalone_question` (the question rewritten so it reads on its own, for example
"What is the exposure to BMW in equities in our portfolio?") so the browser can send it back as history.

### Routing (the only new model call)

One `complete_structured` call with a closed output model:

- `tool`: one of the five values above.
- `standalone_question`: the question rewritten using the history.
- `company`: the company as the user wrote it (for `transition_plan`), else null.
- `benchmark_id`: one id from the list of uploaded benchmarks given in the prompt, or null (for
  `benchmark_sectors`).

The output model has no number fields. `portfolio` and `smart_search` then call the existing
`qa_agent.answer_question` and `smart_search.smart_search` with `standalone_question`, so those keep their own
prompts and their own model call. Two model calls per portfolio or smart-search question; one for the other two
tools.

### Transition plan

Code, no model:

1. Candidate runs: completed runs of type `transition_plan` (stored, read-only) and completed extraction runs on
   the transition plan preset (`is_transition_plan_preset_run`).
2. Read each with `decision.sources.from_transition_plan_run`, which already gives both kinds the same columns.
3. Match `company` against each row's `Company` name after `_normalised_name` in `decision/sources.py`
   (lowercase, letters and digits only, so "BASF" becomes `basf` and "BASF SE" becomes `basfse`). An exact
   normalised match wins; otherwise every row whose normalised name contains the normalised `company` matches.
4. The newest run (by `created_at`) whose rows match wins.
   - No match in any run: `answer_text` = `No completed transition plan assessment includes <company>.`
   - Matches more than one distinct company in that run: no figures; `answer_text` lists the names and asks
     which one.
5. The card shows: company name, run id (linked to the run's results), run date, `Indicators_Disclosed_Count`,
   `Walk_Disclosed_Count`, `Talk_Disclosed_Count`, `Walk_Share_pct`, `Assessment_Confidence_pct`, and whether
   `Needs_Review_Flag` is set ("Some indicators still wait for review" with a link to the review queue).
6. Also listed, without figures: the next 2 older runs that include the company (run id and date), so "newest
   assessments" (plural) is covered.

### Benchmark sectors

Code, no model, from `stewardship.benchmark.BenchmarkStore`:

1. If any benchmark is uploaded: use `benchmark_id` from routing. If routing returned null, no figures;
   `answer_text` lists the uploaded benchmarks' names and asks which one.
2. If none is uploaded: use the stewardship sample (`stewardship/data/examples/sample_meetings.json`: 12 issuers,
   each with `sector` and `holding.index_weight_pct`; its weights do not sum to 100, and the check shows the real
   sum), and the card says `Synthetic sample: 12 fictional companies
   standing in for MSCI World. Upload the iShares URTH holdings file under Stewardship → Benchmarks for the real
   index.`
3. **Data check**, shown above the chart (this is "review the data"):
   - source: file name and "Fund Holdings as of" date, or "synthetic sample"
   - constituents: count
   - dropped lines: the `dropped` count from the upload (cash, futures and similar)
   - unclassified weight: % of weight whose sector is empty
   - total weight: sum of `weight_pct`, two decimals
4. **Chart**: sum of `weight_pct` per sector, two decimals, sorted largest first, empty sector shown as
   "Unclassified", drawn with the existing `BarChart` component. The table of the same numbers sits under it.

### Audit

Every call appends one `qa_audit` row: `endpoint` = `ask.<tool>` (or `ask.error` if routing itself failed),
`question` = the user's question as typed, plus the existing fields. The `portfolio` and `smart_search` tools
call the agents directly, not through their endpoints, so there is one row per question, not two.

### Panel (frontend)

- An "Ask" button in the top bar and Ctrl/⌘J open a panel on the right; Esc or the close button closes it.
  Focus moves to the input on open and back to the button on close.
- The panel lives in the app shell, so the conversation survives moving between pages. It is also kept in
  `sessionStorage` so a reload keeps it; "Clear" empties it.
- Below 640 px wide the panel takes the full screen.
- Each turn shows the question, then its card. Portfolio cards reuse `AggregationResultTable`; Smart Search cards
  reuse the Smart Search page's row list; every card names its source and date.
- While a question is running the input is disabled and the card reads "Working…". An error shows the API's
  message in the card, and the question can be sent again.

### Access (my call)

The same as Ask the Portfolio: `POST` needs `analyst` or higher (the router-level `authorize` rule). The Ask
button is hidden for viewers, so they never see a 403.

## Constraints

- Postgres, the run store and the benchmark store are read as they are; no new tables, no migration.
- `complete_structured` only; no free-text model output.
- API contract: export OpenAPI and regenerate `schema.gen.ts`; add the endpoint to `frontend/src/api/contract.ts`.
- The route lives in a new module `backend/arp/ask.py` with a new router; it does not touch `arp/llm`,
  `arp/extraction` or grounding, so the golden set does not run.

## Left to the builder

- Prompt wording, provided the output model above is kept.
- Card layout and copy beyond the exact texts in this spec and the Acceptance table.
- Whether the router module is one file or two.

## Acceptance

Unit tests replace the model with a stand-in that returns a fixed routing output. Rows marked `evaluator` use the
real model in the running app.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Holdings that include BMW; stand-in routes to `portfolio` with `standalone_question` "What is the exposure to BMW in our portfolio?" | `POST /api/ask` `{"question": "What is the exposure to BMW in our portfolio?", "history": []}` as an analyst | 200; `tool` = `portfolio`; `answer` equals, field for field, the body `POST /api/portfolio/ask` returns for the same question with the same stand-in parse | unit |
| AC-2 | Stand-in routes to `smart_search` with `standalone_question` "Which feeds are behind?" | `POST /api/ask` with that question | 200; `tool` = `smart_search`; `answer` equals the body `POST /api/smart-search` returns for the same question and stand-in | unit |
| AC-3 | Three runs include "BASF SE": a completed `transition_plan` run created 2026-09-01, a completed transition plan preset extraction run created 2026-10-20, and a preset run created 2026-10-23 still `running`; stand-in routes to `transition_plan`, `company` = "BASF" | `POST /api/ask` | 200; `tool` = `transition_plan`; `run_id` = the 2026-10-20 run; `Indicators_Disclosed_Count`, `Walk_Disclosed_Count`, `Talk_Disclosed_Count`, `Walk_Share_pct`, `Assessment_Confidence_pct` and `Needs_Review_Flag` equal that run's BASF row from `from_transition_plan_run`; `older_runs` = [the 2026-09-01 run id] | unit |
| AC-4 | No completed run includes BASF | `POST /api/ask`, stand-in `company` = "BASF" | 200; `tool` = `transition_plan`; no figures; `answer_text` = `No completed transition plan assessment includes BASF.` | unit |
| AC-5 | The newest completed run has rows "BASF SE" and "BASF Coatings GmbH"; stand-in `company` = "BASF Coat" | `POST /api/ask` | 200; figures are those of "BASF Coatings GmbH" (contains match on one company) | unit |
| AC-6 | The newest completed run has rows "Shell plc" and "Shell Midstream Partners"; stand-in `company` = "Shell" | `POST /api/ask` | 200; no figures; `answer_text` names both companies and ends with a question | unit |
| AC-7 | One uploaded benchmark: name "iShares MSCI World ETF", as of "Oct 20, 2026", dropped 3, constituents A (Information Technology, 30.0), B (Information Technology, 20.004), C (Financials, 40.0), D ("", 9.996); stand-in routes to `benchmark_sectors` with its id | `POST /api/ask` | 200; `tool` = `benchmark_sectors`; `sectors` = [["Information Technology", 50.0], ["Financials", 40.0], ["Unclassified", 10.0]] in that order; check: `constituents` 4, `dropped` 3, `unclassified_pct` 10.0, `total_pct` 100.0, `as_of` "Oct 20, 2026", `is_sample` false | unit |
| AC-8 | No uploaded benchmark; stand-in routes to `benchmark_sectors`, `benchmark_id` null | `POST /api/ask` | 200; `is_sample` true; `constituents` 12; `answer_text` starts `Synthetic sample: 12 fictional companies standing in for MSCI World.` | unit |
| AC-9 | Two uploaded benchmarks; stand-in `benchmark_id` null | `POST /api/ask` | 200; no `sectors`; `answer_text` names both benchmarks and ends with a question | unit |
| AC-10 | Stand-in routes to `none` | `POST /api/ask` `{"question": "What did BMW say about cobalt?"}` | 200; `tool` = `none`; `answer_text` names the four things the panel can answer: portfolio exposure, data issues/outputs/feeds, a company's newest transition plan assessment, a benchmark's sector weights | unit |
| AC-11 | `history` with 6 turns | `POST /api/ask` | 422 | unit |
| AC-12 | Empty question, or one of 1,001 characters | `POST /api/ask` | 422 | unit |
| AC-13 | A viewer | `POST /api/ask` | 403; the top bar shows no Ask button for a viewer | unit |
| AC-14 | Any of AC-1, AC-3, AC-7, AC-10, and a call where the stand-in raises | `POST /api/ask`, then `GET /api/portfolio/qa-audit` as an approver | exactly one new row per call; `endpoint` = `ask.portfolio`, `ask.transition_plan`, `ask.benchmark_sectors`, `ask.none`, `ask.error` respectively; `question` as typed | unit |
| AC-15 | Running app with the real model, holdings incl. BMW, a completed transition plan run incl. BASF, the URTH file uploaded | Ask the owner's three questions in the panel, one after another | Card 1 shows BMW's EUR exposure equal to what the Ask the Portfolio page shows for the same question; card 2 shows BASF's newest run with its date and figures; card 3 shows the data check above a sector bar chart for the uploaded MSCI World file | evaluator |
| AC-16 | After card 1 of AC-15 | Ask "now only equities" | The card's filter shows company BMW and asset class equity, and the figure equals Ask the Portfolio's answer to "What is the exposure to BMW in equities in our portfolio?" | evaluator |
| AC-17 | Any page, signed in as analyst | Press Ctrl/⌘J; type and send; navigate to another page; reload | The panel opens with focus in the input; Esc closes it and focus returns to the Ask button; after navigating and after reload the earlier turns are still shown; "Clear" removes them | evaluator |
| AC-18 | A 390 px wide screen | Open the panel and ask question 3 | The panel fills the screen; no horizontal scrolling; chart and check block are readable | evaluator |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-19 | The existing suites | Run the tests for `POST /api/portfolio/ask` and `POST /api/smart-search` | They pass unchanged, and each endpoint still writes its own audit row (`portfolio.ask`, `datahub.smart_search`) | unit |
| AC-20 | No call to `/api/ask` | Any BI, Superset or stewardship screen | No chart, dashboard or benchmark is created, changed or deleted by the panel; `/api/ask` makes no write except the audit row | unit |
