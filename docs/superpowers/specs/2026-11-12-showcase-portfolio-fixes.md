# Showcase fixes for the portfolio screens (rehearsal of 11 Nov 2026)

## Decisions assumed, the owner can change any at approval

The owner was asked these three questions and had not answered when the spec was written. The spec is
built on the recommended option of each. Changing one changes only the rows named.

1. **Demo portfolios on Holdings Intake: listed read-only.** The holder table also shows every portfolio
   that has no holder record; nothing is stored. Alternative: the demo seed stores a holder record per
   portfolio, which turns every demo ISIN into a Blocking "unmatched" issue on a fresh seed with no security
   master. (Rows AC-113 to AC-117.)
2. **Concentration alerts: wording only.** The alert names the portfolios its rule covers and shows percent;
   no figure and no alert logic changes. Alternative: one alert per portfolio, which changes figures and
   duplicate handling and needs its own PR after the showcase. (Rows AC-71, AC-72.)
3. **Monitoring rules: delete and disable.** A rule can be switched off, edited and deleted. Alternative:
   disable and edit only, no delete. (Rows AC-49, AC-50, AC-59 to AC-62, AC-68, AC-70.)

## Intent

A live rehearsal with real model calls on 11 Nov 2026 found 12 defects in the Data Hub, Risk Monitoring,
Decision Studio, Presentations & Reports and RFP screens. The showcase is next week, in a bank JupyterLab:
Gemini through Vertex AI, one uvicorn process serving the built frontend, Postgres, dev sign-in or two local
users, no Superset, Neo4j or OpenSearch.

This spec fixes all 12 for the person presenting, so that no screen ignores what was picked, shows an
internal id, waits minutes in silence or leaves a row that cannot be removed. Every fix comes with a test
that failed before it. No existing test is changed or weakened.

## Build order and PRs

- One implementing PR, `risk:high`, `Spec: showcase-portfolio-fixes`, one commit per defect (as PR #413),
  built on `main` (PR #413 is merged: `main` 3fff505 contains 463ed94).
- It is `risk:high` because it deletes stored data (a rule from `rules.json`, a report folder), changes which
  snapshot date money figures are computed for (Ask the Portfolio), and adds weight-parsing options on
  upload. No schema migration, no auth change. The owner merges it on GitHub.
- If the diff grows past what one review can hold, slice by screen with a `Rows:` line:
  **slice 1, Risk Monitoring** (defects 1, 5, 9, 10, 11): `Rows: AC-1 to AC-83`; **slice 2, the rest**: no
  `Rows:` line.
- API changes need the OpenAPI files regenerated in the same PR (`backend/scripts/export_openapi.py`, then
  `npm run gen:api`); `frontend/src/types.ts` holds hand-written copies of `QAAnswer`, `HolderStatus` and
  `AlertRule` that need the same fields.

## Causes (verified in code on `fix/showcase` 463ed94; the files are unchanged on `main` 3fff505)

| # | Defect | Cause |
|---|--------|-------|
| 1 | Ask the Portfolio ignores the as-of date and the trend range; the date box takes any text | `AskThePortfolio.tsx:32` puts the selection into the question as prose; `AskRequest` (`routers/portfolio.py:150`) has only `question`; `qa_agent.py:107-114` never sets `AnalyticSpec.as_of`/`date_range` and `:116` refuses a trend. `analytics.execute` already honours both. `DateSelector.tsx` uses `type="text"`. |
| 2 | Report drafting: no feedback, a `plan_ready` row cannot be opened or removed, list not in date order | `ReportBuilder.tsx:444` only disables the button; the actions cell (`:640`) renders only for `completed`; there is no delete route; `reporting_store.py:100` sorts by folder name, a random id. |
| 3 | RFP library import: no feedback | `RfpAnswers.tsx:59-66`: the button is disabled and the result goes only to the screen-reader announcer. |
| 4 | A rejected upload for a mistyped holder leaves a Blocking issue and a Behind feed row | `holdings/intake.py:71-74` records a failed load before any holder exists; `feeds.py:41-50` lists every holdings source that has a load. |
| 5 | Rules cannot be disabled, edited or deleted; 15 alerts stay | No controls in `MonitoringAlerts.tsx`; no delete route; no bulk status change. `POST /monitoring/rules` already replaces a rule with the same `rule_id`, and the evaluator already skips disabled rules. |
| 6 | A newer upload relabels other portfolios | `decision/sources.py:397,441` and `routers/portfolio.py:135-144` label with the newest date over all portfolios, while the rows come from each portfolio's own latest snapshot. |
| 7 | ESG upload rejects uploaded portfolios' companies | `esg_intake.py:180` knows only `store.list_companies()`; an uploaded holding's issuer exists only as its security's resolution (`portfolio_directories`). |
| 8 | Holdings Intake: demo portfolios missing, no refresh, unnamed missing columns, no decimal or weight choice | `holder_status` lists `holders.json` only; `HoldingsIntake.tsx` `submit()` reloads holders only; `lib/holdings.ts:6` drops the column; `upload` takes only `provider`. |
| 9 | Risk Monitoring opens on Dashboards; Company Profiles shows an error line | `PortfolioRiskMonitoringTool.tsx:29` opens `SUB_TABS[0]`; `CompanyProfiles.tsx:31` renders a 503 as an error. |
| 10 | Monitoring shows raw ids, "Unknown", fractions | `MonitoringAlerts.tsx:203-208,254-260` print stored values as they are; the label maps exist in the same file. |
| 11 | Ask wording: prefix in the caption, raw headers, plain EUR | The prefix of defect 1 becomes `spec_name`; `AggregationResultTable.tsx:19` prints `group_by`; nothing carries a scale or unit. |
| 12 | Six smaller items | See "Decided", 12a to 12f. |

## Goals

- Ask the Portfolio answers for the as-of date or trend range picked in the pane, and says which date it used.
- A monitoring rule can be switched off, corrected and deleted, and its alerts cleared in one step.
- Every label on the monitoring and Ask tables is a name a person reads, with the right unit.
- Risk Monitoring opens on a tab that works without Superset.
- Slow actions (plan drafting, RFP import) show that they are running and for how long.
- An unfinished report can be opened or discarded; reports are listed newest first.
- A rejected upload for a holder that does not exist leaves nothing behind.
- Uploaded portfolios work with the ESG upload, the holder table, the pane and the monthly-run table.
- Tables built from holdings are labelled with the dates their rows really have.
- The six smaller items of defect 12 are fixed.

## Non-goals

- Making plan drafting or the RFP import faster, or turning them into background jobs.
- Per-portfolio concentration maths (decision 2).
- A general dismiss feature for Issues.
- Rewriting or deleting lines of the append-only alert and governance logs.
- Anything PR #413 fixed.
- Superset, Neo4j or OpenSearch setup.
- Dates named inside the question text ("in September"): only the pane's date fields set the date.
- Names instead of ids in the rows of an Ask answer (`bmw`), in its `answer_text`
  (`company_id=bmw, grouped by portfolio_id`), in the page's `Query:` line, in company-scoped alert cells and
  in stored alert rationale texts.
- Three finds from the triage, to be raised as follow-ups: uploaded issuers are dropped from the hand-over to
  Argus (`holdings_universe` keeps only registry companies); a repeat Decision Studio upload overwrites the
  earlier file in `_uploads/`; a report left in `planning` after a crash.

## Anti-goals

- No stored alert event or governance event is edited or deleted by this change.
- A completed report can never be discarded through the new route.
- No money figure changes for a request that names no date and no scale.
- No line of an existing test is removed or changed; tests are only added.

## Approaches

1. **One fix per defect at its cause, reusing what exists (chosen).** The engine already supports as-of and
   trend, the rule store already upserts, the evaluator already honours `enabled`, `portfolio_directories`
   already knows uploaded issuers. Most fixes pass an existing value through or render an existing label.
2. Frontend-only patches (keep the prose prefix, hide rows in the UI). Smaller, but the date would still be
   ignored and orphan rows would still be stored. Rejected.
3. Larger redesigns (background jobs with polling for drafting and import, a holder record for every
   portfolio, per-portfolio concentration). Each is a feature of its own and too risky a week before the
   showcase. Rejected; listed under Non-goals.

## Decided

### 1. Ask the Portfolio: scope and dates as request fields

`POST /api/portfolio/ask` body gains three optional fields; `question` is what the user typed, nothing more.

| Field | Type | Meaning |
|-------|------|---------|
| `portfolio_ids` | list of str, default `[]` | The pane's selection. Used as the portfolio filter when the parsed question names no portfolio; a portfolio named in the question wins. |
| `as_of` | `YYYY-MM-DD` or null | Becomes `AnalyticSpec.as_of`. |
| `date_range` | `[start, end]` or null | Becomes `AnalyticSpec.date_range` (trend). |

Refused with 422 by the route itself, before any model call and before the audit `try` block, so no audit
row is written. `detail` is a plain string (`HTTPException(422, "<text>")`):

| Case | `detail` contains |
|------|-------------------|
| `as_of` is not a real `YYYY-MM-DD` date | `as_of must be YYYY-MM-DD` |
| `as_of` is after the server's date (same rule as holdings upload, `validate.py:150`) | `as_of is in the future` |
| a `date_range` entry is not a real `YYYY-MM-DD` date | `date_range must be two YYYY-MM-DD dates` |
| `date_range` start after end | `date_range start is after its end` |
| both `as_of` and `date_range` | `send as_of or date_range, not both` |
| a `portfolio_ids` entry that is no portfolio | `unknown portfolio_id '<id>'` |

A range end in the future is allowed (a range only selects snapshot dates).

Answered with 200 and `resolvable: false`, `result: null`, `trend: null`:

- `as_of` before the first snapshot date: `clarification_needed` =
  `No holdings on or before <as_of>. The first snapshot is <first date>.`
- no snapshot date inside `date_range`: `clarification_needed` =
  `No snapshots between <start> and <end>. Snapshots run from <first date> to <last date>.`
- the scoped portfolios have no snapshot at all: `clarification_needed` = `No holdings snapshots for that selection.`

"First" and "last" date are taken over the portfolios the answer is scoped to (the effective portfolio
filter; all portfolios when it is empty), and the checks run after the parse, when that filter is known.

An `as_of` that is not itself a snapshot date is answered as the engine does today: each scoped portfolio's
newest snapshot on or before it, with `result.as_of` and `vintage.holdings_as_of` = the requested date. So
that the answer says which data it used, `vintage` gains `snapshot_dates`: the sorted distinct `as_of_date`
values of the holdings the answer was computed from (for a trend, the points' dates).

`QAAnswer` gains three fields (existing fields keep their meaning):

| Field | Value |
|-------|-------|
| `trend` | null for a point-in-time answer. For a trend: the engine's `TrendPoint` list, ascending by `as_of`; `result` is then null. |
| `scale` | `"units"` or `"millions"`, see section 11. |
| `unit` | `"EUR"` for `market_value_sum`; the data point's unit from the climate schema for `weighted_avg_datapoint` (`""` for a field the schema does not know); `""` for `count`. |

Trend answer: `vintage` = `{"snapshot_dates": [...]}` only. `answer_text`: first line
`Trend from <start> to <end>, <n> snapshots (<scope>, <filter>, grouped by <group_by>):` with `<scope>` and
`<filter>` built as in today's point-in-time text (`portfolios=['core_equity_europe']` or `all portfolios`;
`k=v` pairs or `no filter`), then one line per point, by metric:

- `market_value_sum`: `  <as_of>: EUR <total_market_value_eur:,.0f>` (or the millions form of section 11);
- `count`: `  <as_of>: <sum of holding_count> holdings`;
- `weighted_avg_datapoint`: `  <as_of>: ` + the rows as `<group_value> <weighted_avg_value:.4f>`
  (`<group_value> no data` when null), joined by `; `.

`qa_agent.answer_question` takes the three values as keyword arguments with defaults, so its other callers
(`routers/ask.py:81`, `cli/portfolio.py:157`) are unchanged.

Frontend: the three date inputs in `DateSelector.tsx` are `type="date"`; the as-of input has `max` = today.
With a trend whose end is before its start, the pane shows `The end date is before the start date.` under the
boxes and the selection counts as "latest". `AskThePortfolio` sends the typed question plus
`portfolio_ids`, `as_of`, `date_range` from the pane; the "Scoped to:" line stays. Under a point-in-time
answer's table the page shows `Snapshot used: <date>` (`Snapshots used: <a>, <b>` for several) from
`vintage.snapshot_dates`. A trend answer is shown as a table: header `As of`, one column per group value
(order of first appearance), and `Total` for `market_value_sum`; one row per point, ascending; a group
absent on a date shows `—`; cells are formatted as in the point-in-time table (the cell formats are the
builder's choice within that and are not tested beyond AC-31).

### 5. Monitoring rules

- **Disable, enable, edit:** the existing `POST /api/portfolio/monitoring/rules` with the rule's `rule_id` and
  `created_at` (it already replaces the stored rule). No new route.
- **Delete:** `DELETE /api/portfolio/monitoring/rules/{rule_id}`: 204; removes the rule's entry from
  `rules.json` (new `delete_rule` on the file store, delegated by the Postgres store like `save_rule`).
  404 `Unknown rule <rule_id>`. 409 `Rule has <n> live alerts: clear them first.` while any alert with that
  `rule_id` is `open`, `acknowledged` or `escalated`.
- **Clear a rule's alerts:** `POST /api/portfolio/monitoring/rules/{rule_id}/clear-alerts`, body
  `{"status": "resolved" | "false_positive", "reason": ""}`: appends one `status_changed` event
  (`decided_by` = the caller's name, as `transition_alert` does) to every live alert carrying that `rule_id`;
  answers `{"cleared": <n>}`. It does not require the rule to exist (alerts of a deleted rule can be cleared).
  Any other `status` is 422. No event is rewritten or removed.
- Both new routes, and the report route of section 2, need an analyst or higher, through the existing
  `authorize` dependency that guards every non-GET route.
- A cleared alert of a rule that is still enabled and still breaching is raised again by the next evaluation
  (existing behaviour); the user disables or corrects the rule first.
- UI, rules table: a column `Alerts` (live count) and per rule the buttons `Disable` or `Enable`, `Edit`,
  `Clear alerts`, `Delete`. `Edit` fills the form above the table; its button then reads `Save rule`, with a
  `Cancel` next to it. `Clear alerts` offers `Resolve` and `False positive`. `Delete` asks
  `window.confirm("Delete rule '<name>'?")` (the pattern of `RecipesView.tsx:131`) and shows the 409 text when
  refused.

### 10. Monitoring wording

Pure functions in a new `frontend/src/lib/monitoringLabels.ts` (tested by `node --test`), used by both tables:

| What | Shown |
|------|-------|
| Rule type | The labels of `RULE_TYPES` (`Company field threshold`, `Single-name concentration`, `Portfolio aggregate (WACI-style)`) |
| Comparator | `>`, `≥`, `<`, `≤` |
| Condition, field or aggregate rule | `<field name> <comparator> <threshold> <unit>`, name and unit from the climate schema (`Carbon intensity > 50 tCO2e / EUR M revenue`); an unknown field id is shown as it is, without unit |
| Condition, concentration rule | `Weight of one company <comparator> <percent>` (`Weight of one company > 5%`) |
| Rule scope | Portfolio names joined by `, `; `All portfolios` when the rule names no portfolio and no company; company ids as today |
| Percent | fraction × 100, at most 2 decimals, trailing zeros dropped: 0.05 → `5%`, 0.0712 → `7.12%`, 0.125 → `12.5%`, 0.07 → `7%` |
| Alert `Rule` (new column) | The rule's name; `Deleted rule` when its `rule_id` matches no rule; `—` when it has none |
| Alert scope `portfolio__<id>` | The portfolio's name (the id when unknown) |
| Concentration alert scope | `<company id> · across <portfolio names of its rule>`, `· across all portfolios` when the rule names none, `<company id>` alone when the rule is deleted |
| Concentration alert Observed and Threshold | Percent |
| Breach type `unknown` | `No earlier breach to compare` on a threshold breach, `—` on a news alert |

A concentration alert is one with a `company_id` and `breach_type` `holdings_caused` (by construction, see
`BreachType`). The rule form shows `Threshold (%)` for a concentration rule and stores the typed percent as a
fraction (5 → 0.05); editing shows the percent again. Stored values and rationale texts are not changed.

### 9. Opening tab and Company Profiles

- A route with no sub-tab (`#/portfolio-monitoring`) opens `Monitoring & Alerts`. A named sub-tab opens as
  today, and legacy or unknown ids still go where `resolveSubTab` sends them. The tab order is unchanged.
  This is a new function next to `resolveSubTab` (for example `openingSubTab`), so
  `frontend/tests/subTabs.test.ts` passes unchanged. Its test named "the default is dashboards" then
  describes the fallback of `resolveSubTab`, no longer the page's opening tab; the owner may ask for a
  rename in a later change.
- `CompanyProfiles`: when the dashboards list answers 503, the "Profile dashboard" card shows
  `Dashboards are not set up on this server. Ask your administrator.` as plain help text, without
  `role="alert"` and without `The profile dashboard could not be loaded:`. Other errors render as today.

### 11. Ask the Portfolio wording

- The caption is `<spec_name> — grouped by <label>, as of <as_of>`; with the prefix gone, `spec_name` is the
  model's name or the typed question.
- Column header for the grouping (`dimensionLabel` in the frontend): `portfolio_id` → `Portfolio`,
  `asset_class` → `Asset class`, `company_id` and `company_name` → `Company`, `sector` → `Sector`,
  `country` → `Country`, `currency` → `Currency`, `gics_sector` → `GICS sector`, `gics_industry_group` →
  `GICS industry group`, `gics_industry` → `GICS industry`, `gics_sub_industry` → `GICS sub-industry`; any
  other id with `_` as spaces and a capital first letter.
- Scale: `_ParsedQuestion` gains `scale` (`"units"` default, `"millions"`); the system prompt says to choose
  `millions` when the question asks for EUR million. The numbers in `result` stay plain EUR. With
  `millions`, `answer_text` writes `EUR <value / 1e6:,.2f> million` wherever it writes `EUR <value:,.0f>`
  today, the table header is `Market value (EUR million)`, cells have two decimals, and the total line is
  `Total: EUR <x.xx> million`. With `units` every text is as today.
- Unit: the weighted-average column header is `Weighted avg (<unit>)` when `unit` is not empty.
- `AggregationView` and `AggregationResultTable` take `scale` and `unit` as optional props; without them
  they render as today (the unified Ask cards are not changed).

### 2. Presentations & Reports

- While a plan or storyline drafts, a line with `role="status"` under the button reads
  `Drafting the content plan… <m:ss> elapsed. This can take a few minutes; keep this page open.`
  (`Drafting the storyline…` for a house deck), counting up every second; the button reads `Drafting…`.
  `elapsedLabel(seconds)` in the frontend gives `m:ss` (`0:42`, `3:16`); one frontend function builds the
  whole line from the output format and the seconds.
- `DELETE /api/reports/{report_id}`: 204 and the report's folder is removed, when its status is
  `plan_ready`, `storyline_ready` or `failed`. Any other status: 409
  `Only an unfinished report can be discarded (status: <status>).` Unknown id: 404. `report_dir()` creates
  the folder it names, so the route checks `reports_dir / safe_id(report_id)` with `exists()` and never calls
  `report_dir()` for an id that is not stored. (A later `GET /api/reports/{id}` for the same id may recreate
  an empty folder, as it does today for any unknown id; such a folder has no manifest and is not listed.)
- Previous reports: a `plan_ready` or `storyline_ready` row shows `Open` (what a click on the row does today)
  and `Discard`; a `failed` row shows `Discard`. `Discard` asks `window.confirm("Discard this draft?")`. If
  the discarded report is the one open under "Review & render", that section closes.
- `GET /api/reports` lists newest first by `created_at`.

### 3. RFP library import

While importing, a `role="status"` line reads
`Importing <n> file… <m:ss> elapsed. This can take a few minutes; keep this page open.` (`files` for n > 1).
Afterwards a visible `role="status"` line shows the text that today goes only to the announcer
(`Imported 4 entries, dropped 0`, with `: <reasons>` when something was dropped); it stays until the next
import starts.

### 4. Rejected upload for a holder that does not exist

- `ingest` records a failed load only when the holder exists: a holder config for `(kind, holder_id)`, or,
  for kind `portfolio`, a portfolio with that id. Otherwise it answers 422 as today and records nothing.
- `feeds.overview` lists a holdings source that has no holder config only when it has at least one ok load.
  Stored orphan events stay in the log and are no longer shown; Issues is built from the same rows.

### 7. ESG upload

The known company ids are the registry companies plus every company id a security resolves to
(`portfolio_directories(store)`). Everything else in `esg_intake` is unchanged.

### 8. Holdings Intake

- **Holders (decision 1):** `GET /api/holdings/holders` also returns one row per portfolio that has no
  holder config: `holder_id` = portfolio id, `kind` `"portfolio"`, `name` = portfolio name, `source` null,
  `as_of` = its latest snapshot date, `stale`, `age_days` and `expected_as_of` computed as for holders,
  `last_pull_at` and `last_error` null. Nothing is stored;
  `holder_status`, Feeds, Issues and Security Master are unchanged. The page shows `—` as Source.
- **Refresh:** after a successful holdings upload the page calls the pane's `refreshPortfolios` and reloads
  the monthly-run table; after a successful ESG upload it reloads the monthly-run table.
- **Missing columns:** in the 422 of `POST /api/holdings/upload`, an error with message
  `missing required column` carries as `column` the file header the provider mapping expects
  (`Weight (%)`, not `weight`); `validate` itself is unchanged. `rowErrorText` shows such an error as
  `missing required column: <column>`; every other error with `row` null shows its message alone, as today.
- **Decimal and weights:** the upload takes two optional form fields, `decimal` (`.` or `,`) and
  `weight_unit` (`percent` or `fraction`); each overrides the provider mapping's value when sent; any other
  value is 422. The form gets two selects: `Decimal separator` (`Point (1,234.56)`, `Comma (1.234,56)`) and
  `Weights are` (`Percent (5 = 5%)`, `Fraction (0.05 = 5%)`), defaulting to Point and Percent. The form
  always sends both fields. The existing weight-sum check (100% ± 0.5) still rejects a wrong choice.

### 6. Dates on holdings tables

- `from_portfolio_snapshot`: `D` = the distinct `as_of_date` values of the holdings it loaded. One date:
  title `Portfolio holdings as of <date>`. Several: `Portfolio holdings as of <oldest> to <newest>`. The
  dataset's `as_of` is the newest. Which holdings are loaded and the date used for observation look-ups do
  not change.
- `POST /api/portfolio/universe`: the name ends `_<date>` or `_<oldest>_to_<newest>` by the same rule, and the
  response's `as_of` is the newest.

### 12. Smaller items

- **a. Security Master:** with no master loaded and no unmatched security, the unmatched table's empty row
  reads `No holdings have been loaded through Holdings Intake yet.` With a master loaded it reads
  `Every held security is matched.` as today.
- **b. Home hub:** a monthly run that ran appends a governance event `monthly_run_recorded`
  (`month`, `alerts`, `triggers`); `GET /api/portfolio/monthly-run/last` returns the newest as
  `{"month", "at", "alerts", "triggers"}`, or `null`. A blocked run records nothing. Steps get their state
  from recorded activity (the hub reads `GET /api/feeds` and the new route):

  | Step (process) | Done when | Failed when |
  |----------------|-----------|-------------|
  | `Load security master` (Map securities to issuers) | the security master feed's `last_load.status` is `ok` | it is `failed` |
  | `Holdings Intake` (Monthly monitoring) and `Map holdings` (Map securities to issuers) | at least one `holdings` or `index` feed row has `last_load.status` `ok` | none is ok and at least one is `failed` |
  | `Monitoring & Alerts` (Monthly monitoring) | `monthly-run/last` is not null | never |

  The step line reads `Done · <day month>` (`stepStatusLine` on the `at` of the newest ok load among those
  rows, or of the run), `Last run failed`, or
  `No runs yet`. Run-based steps are unchanged; `stepState` keeps its present result when no activity is
  passed, so `workspaceCard.test.ts` and `processes.test.ts` pass unchanged.
- **c. Decision Studio uploads:** `DatasetSummary` gains `created_at`. The Data table gets a column `Added`
  (local date and time with seconds). A Movement option without `as_of` reads `<name> · added <that text>`;
  options with `as_of` are unchanged.
- **d. Seed confirmation:** the `Seeded N companies, M portfolios, K holding rows.` line is rendered in the
  pane whether or not portfolios are listed, until the page is reloaded.
- **e. Deck findings:** `findingText(finding)` in the frontend gives the line shown, or null for a finding
  that is not listed:

  | Finding | Line |
  |---------|------|
  | rule `invalid_edit` | not listed |
  | rule `applied` | `Visual check: adjusted. <message>` |
  | rule `slot_dropped` | `Layout: some content did not fit this slide and was left out.` |
  | anything else | `<stage label>: <message>`, stage labels `lint` → `Wording`, `fit` → `Layout`, `data` → `Data`, `qa` → `Visual check`, other → `Check` |

  No `stage/rule` text and no `[slot]` are shown. A slide with no listed finding is not shown; with none at
  all, the `Findings` heading is not shown. `GET /api/reports/{id}/findings` is unchanged.
- **f. Value chain headings:** `#/valueChain/<view>` with `<view>` one of `tree`, `footprint`, `exposure`,
  `shock` and no node id shows the explorer's start (`<h1>Value Chain Explorer</h1>` and the search box),
  as `#/valueChain` does.

## Existing tests that pin behaviour (none may change)

- `frontend/tests/subTabs.test.ts`: fallback and legacy ids of `resolveSubTab`, `SUB_TABS[0]`.
- `frontend/tests/holdings.test.ts`: `rowErrorText` for row errors and for `{row: null, column: null}`.
- `frontend/tests/workspaceCard.test.ts`, `processes.test.ts`: `stepState` and the step lists.
- `backend/tests/test_holdings_file_source.py:117`: `validate` returns
  `RowError(None, "weight", "missing required column")`.
- `backend/tests/test_api_ask.py`, `test_qa_agent.py`, `test_qa_audit.py`: answers and audit rows for a
  request with only `question`; the unified `/api/ask` equals `/api/portfolio/ask`.
- `backend/tests/test_reporting_store.py`, `test_reporting_visual_qa.py` (asserts `invalid_edit` findings
  are produced), `test_portfolio_monitoring_evaluator.py`, `test_holdings_intake.py`, `test_esg_intake.py`,
  `test_issues.py`, `test_security_master.py`, `test_decision_sources.py`, `test_decision_api.py`,
  `test_monthly_run.py`.

## Notes for the builder

- Proof per defect: a test that fails on `main` and passes after, with the failing output in the PR
  description. Backend fixes: pytest. Frontend logic goes into `frontend/src/lib/*.ts` functions with
  `node --test` tests; a fix that is pure markup (the seed line, the status lines) gets a browser test in
  `backend/tests/e2e`.
- The new routes raise `HTTPException` with the codes above themselves; they do not rely on the app-wide
  `ValueError` handler (PR #410 replaces it).
- Gitleaks flags id-like test literals: mark fixtures as `.gitleaksignore` describes.
- Left to the builder: function and file names not given above, layout of the new buttons and selects,
  test names.
- Seen, not part of this spec: the Ask help text names `ARP_ANTHROPIC_API_KEY` although the showcase runs on
  Gemini.
- Say in the PR whether `openwiki/` needs an update (the Ask request, the two new routes).

## Acceptance

**Fixtures.** "Stack" is the app from `backend/scripts/e2e_stack.sh up` with `ARP_STANDINS_DIR` set and no
model key. It seeds the demo data when it starts and all hidden tests share it, with nothing reset in
between. So `holdout` rows never upload to `core_equity_europe` or `sustainable_leaders`, never upload as of a
date after `S4`, and use their own ids: `<x>` stands for a suffix unique to the test (letters and digits, at
most 8). `evaluator` rows run on a freshly started Stack. Calls are made as a user who may write (analyst);
the RFP rows and `qa-audit` reads as an approver.

Demo data: four portfolios, `core_equity_europe` ("Core Equity Europe", `CEE` below), `sustainable_leaders`
("Sustainable Leaders Fund"), `multi_asset_balanced`, `corporate_bond_income`. `S4` is the last day of the
month before the Stack started; `S3`, `S2`, `S1` are the last days of the months 3, 6 and 9 months before
`S4`'s month. Each portfolio has exactly these four snapshot dates. `O` is the day before `S4`.

Ask: "Parse P" means `model/_ParsedQuestion.json` = `{"output": P}` in the stand-in folder.
`SEC` = `{"resolvable": true, "spec_name": "", "portfolio_filter": [], "security_filter": {}, "group_by": "sector", "metric": "market_value_sum"}`;
`SEC_M` = `SEC` plus `"scale": "millions"`; `WACI` = `SEC` with `"group_by": "portfolio_id"`,
`"metric": "weighted_avg_datapoint"`, `"data_point_field_id": "climate_carbon_intensity"`; `ONE(c)` = `SEC`
with `"security_filter": {"company_id": c}`. `Q` is the string `How much do we hold?`. `askc(E)` is
`POST /api/portfolio/ask` with `{"question": Q, "portfolio_ids": ["core_equity_europe"]}` plus the fields
`E`. `TOP(d)` is the first `preview` row of `POST /api/decision/datasets/from-source` with
`{"source": "portfolio_snapshot", "as_of": d, "portfolio_ids": ["core_equity_europe"]}`: its `Company_Id` and
its `Portfolio_Market_Value_EUR`.

Uploads: `H(X)` is the portfolio template (`GET /api/holdings/template`) with one data row: a valid ISIN
`X` no other test uses, weight 100, market value 1000, currency EUR. "Upload F for h as of d" is
`POST /api/holdings/upload` with file F, `holder_id` h, `kind` portfolio, `as_of` d. "Master (i, X)" is the
security master template (`GET /api/security-master/template`) with one row, issuer `i` and ISIN `X`,
uploaded to `POST /api/security-master/upload`. "ESG row for c" is the ESG template
(`GET /api/portfolio/esg/template`) with one valid row for `company_id` c, uploaded to
`POST /api/portfolio/esg/upload`.

Rules: "Rule C" is `POST /api/portfolio/monitoring/rules` with
`{"name": "Any weight <x>", "rule_type": "concentration_threshold", "comparator": "gt", "threshold_value": 0, "portfolio_ids": ["core_equity_europe"]}`.
"C evaluated" adds `POST /api/portfolio/monitoring/evaluate-now`; `n` is then the number of alerts of
`GET /api/portfolio/monitoring/alerts?status=open` that carry C's `rule_id` (one per company held in `CEE`,
`n ≥ 3`). "Rule A" is
`{"name": "Carbon cap", "rule_type": "portfolio_aggregate_threshold", "field_id": "climate_carbon_intensity", "comparator": "gt", "threshold_value": 50, "portfolio_ids": ["core_equity_europe"]}`.

Reports: `model/ReportPlan.json` holds a valid plan. "A draft" is a report made with
`POST /api/reports?render=false` (status `plan_ready`); "a finished report" is one made with
`POST /api/reports` (status `completed`).

`unit` rows that say "browser test" run a page in `backend/tests/e2e` with the named API calls answered by
the test. Browser rows run at 1400×900; table headers are compared without regard to case (the stylesheet
upper-cases them). "`detail` contains" always means `detail` is a string that contains the text.

### Slice 1: Risk Monitoring (defects 1, 11, 5, 10, 9)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Stack; `(c, v)` = `TOP(S2)`; Parse `ONE(c)` | `askc({"as_of": S2})` | status 200, `result.as_of` == `S2` and `vintage.holdings_as_of` == `S2` | holdout |
| AC-2 | the AC-1 response | `result.total_market_value_eur` is read | within 0.01 of `v` | holdout |
| AC-3 | Stack, Parse `SEC` | `askc({"as_of": S2})` | `vintage.snapshot_dates` == `[S2]` | holdout |
| AC-4 | Stack, Parse `SEC`; `d` = the day after `S2` | `askc({"as_of": d})` | `result.as_of` == `d` and `vintage.snapshot_dates` == `[S2]` | holdout |
| AC-5 | Stack, Parse `SEC` | `POST /api/portfolio/ask` with only `{"question": Q}` | status 200, `result.as_of` == `S4` and `vintage.holdings_as_of` == `S4` (must not change) | holdout |
| AC-6 | Stack, Parse `SEC` | `askc({"as_of": "31/12/2099"})` | status 422, `detail` contains `as_of must be YYYY-MM-DD` | holdout |
| AC-7 | Stack, Parse `SEC` | `askc({"as_of": "2099-12-31"})` | status 422, `detail` contains `as_of is in the future` | holdout |
| AC-8 | Stack, Parse `SEC`; `d` = the day before `S1` | `askc({"as_of": d})` | status 200, `resolvable` false, `result` null, `trend` null | holdout |
| AC-9 | the AC-8 response | `clarification_needed` is read | == `No holdings on or before <d>. The first snapshot is <S1>.` | holdout |
| AC-10 | Stack, Parse `SEC` | `askc({"date_range": [S2, S4]})` | status 200, `resolvable` true, `result` null, and the `as_of` values of `trend` are `[S2, S3, S4]` | holdout |
| AC-11 | the AC-10 response | each point's `result.total_market_value_eur` is compared with the total of `askc({"as_of": <that date>})` | equal for all three | holdout |
| AC-12 | the AC-10 response | `answer_text` is split into lines | 4 lines; line 1 == `Trend from <S2> to <S4>, 3 snapshots (portfolios=['core_equity_europe'], no filter, grouped by sector):` | holdout |
| AC-13 | the AC-10 response | lines 2 to 4 of `answer_text` are read | line i+1 == two spaces + `<date i>: EUR ` + that point's total formatted `{:,.0f}` | holdout |
| AC-14 | the AC-10 response | `vintage` is read | == `{"snapshot_dates": [S2, S3, S4]}` | holdout |
| AC-15 | Stack, Parse `SEC` | `askc({"date_range": [S4, S2]})` | status 422, `detail` contains `date_range start is after its end` | holdout |
| AC-16 | Stack, Parse `SEC` | `askc({"date_range": ["2026-13-01", S4]})` | status 422, `detail` contains `date_range must be two YYYY-MM-DD dates` | holdout |
| AC-17 | Stack, Parse `SEC` | `askc({"as_of": S2, "date_range": [S2, S4]})` | status 422, `detail` contains `send as_of or date_range, not both` | holdout |
| AC-18 | Stack, Parse `SEC` | `askc({"date_range": ["2001-01-01", "2001-12-31"]})` | status 200, `resolvable` false, `clarification_needed` == `No snapshots between 2001-01-01 and 2001-12-31. Snapshots run from <S1> to <S4>.` | holdout |
| AC-19 | Stack, Parse `SEC` | `askc({})` | `spec.portfolio_filter` == `["core_equity_europe"]` | holdout |
| AC-20 | Stack, Parse `SEC` with `"group_by": "portfolio_id"` | `askc({})` | `result.rows` has exactly one row, with `group_value` `core_equity_europe` | holdout |
| AC-21 | Stack, Parse `SEC` with `"portfolio_filter": ["sustainable_leaders"]` | `askc({})` | `spec.portfolio_filter` == `["sustainable_leaders"]` (must not change) | holdout |
| AC-22 | Stack, Parse `SEC` | `POST /api/portfolio/ask` with `{"question": Q, "portfolio_ids": ["nope"]}` | status 422, `detail` contains `unknown portfolio_id 'nope'` | holdout |
| AC-23 | Stack, Parse `SEC`; the newest row of `GET /api/portfolio/qa-audit?limit=1` is noted | the AC-6, AC-7, AC-15, AC-16, AC-17 and AC-22 requests are sent | the newest audit row is still the noted one | holdout |
| AC-24 | Stack, Parse `SEC` | after `askc({"as_of": S2})`, the newest audit row is read | its `question` == `Q` and its `vintage.holdings_as_of` == `S2` | holdout |
| AC-25 | the repo at the PR head | `pytest tests/test_api_ask.py tests/test_qa_agent.py tests/test_qa_audit.py` | exit code 0 | unit |
| AC-26 | a store with one portfolio that has no snapshot; a parse scoped to it | `answer_question` is called | `resolvable` false, `clarification_needed` == `No holdings snapshots for that selection.` | unit |
| AC-27 | a seeded store; a trend over three dates with metric `count`, and with `weighted_avg_datapoint` | `answer_text` is read | the per-date lines have the forms of section 1 (`  <date>: <n> holdings`; `  <date>: <group> <value:.4f>` joined by `; `) | unit |
| AC-28 | Stack, Risk Monitoring open | the date mode is switched to "As of date" and then "Trend range" | the as-of input and both trend inputs have `type="date"` | evaluator |
| AC-29 | Stack, Parse `SEC`, Ask the Portfolio tab, no portfolio ticked, As of date set to `S2` | `Q` is typed and Ask is clicked | the request body sent to `/api/portfolio/ask` has `question` == `Q` exactly, `as_of` == `S2` and `portfolio_ids` == `[]` | evaluator |
| AC-30 | the AC-29 answer on the page | the text under the table is read | the caption ends `as of <S2>` and a line reads `Snapshot used: <S2>` | evaluator |
| AC-31 | Stack, Parse `SEC`, Trend range `S2` to `S4` | `Q` is asked | a table whose header starts `As of` and whose 3 body rows start with `S2`, `S3`, `S4` in that order | evaluator |
| AC-32 | Stack, Trend range with From `S4` and To `S2` | the pane is read | it shows `The end date is before the start date.` and the "Scoped to:" line ends `latest` | evaluator |
| AC-33 | Stack, Parse `SEC`, `Core Equity Europe` ticked in the pane, date mode Latest | `Q` is asked | the request body has `portfolio_ids` == `["core_equity_europe"]` and neither `as_of` nor `date_range` set | evaluator |
| AC-34 | Stack, Parse `SEC` | `POST /api/portfolio/ask` with `{"question": "How many EUR million is our exposure to BMW?"}` | `result.spec_name` == that question exactly (must not change) | holdout |
| AC-35 | Stack, Parse `SEC_M` | `askc({})` | `scale` == `"millions"` and `unit` == `"EUR"` | holdout |
| AC-36 | the AC-35 response, `t` = `result.total_market_value_eur` | line 1 of `answer_text` is read | starts `Total: EUR ` + `t / 1e6` formatted `{:,.2f}` + ` million (` | holdout |
| AC-37 | the AC-35 response | each further line of `answer_text` is read | == two spaces + `<group_value>: EUR ` + that row's `market_value_eur / 1e6` formatted `{:,.2f}` + ` million` | holdout |
| AC-38 | Stack | `askc({})` once with Parse `SEC`, once with Parse `SEC_M` | `result.total_market_value_eur` is the same number in both (must not change) | holdout |
| AC-39 | Stack, Parse `SEC` | `askc({})` | line 1 of `answer_text` starts `Total: EUR ` + the total formatted `{:,.0f}` + ` (` (must not change) | holdout |
| AC-40 | Stack, Parse `SEC` | `askc({})` | `scale` == `"units"` and `unit` == `"EUR"` | holdout |
| AC-41 | Stack, Parse `WACI` | `askc({})` | `unit` == `tCO2e / EUR M revenue` and `scale` == `"units"` | holdout |
| AC-42 | Stack, Parse `SEC` with `"metric": "count"` | `askc({})` | `unit` == `""` | holdout |
| AC-43 | Stack, Parse `SEC` | after `askc({})`, the last `_ParsedQuestion` line of `calls.jsonl` is read | its `system` contains `millions` | holdout |
| AC-44 | Stack, Parse `SEC`, Ask the Portfolio tab, date mode Latest | `Q` is asked | the caption reads `<Q> — grouped by Sector, as of <S4>` and the page contains neither `Regarding` nor `override this scope` | evaluator |
| AC-45 | the AC-44 answer | the table's header cells are read | the first is `Sector`; none contains `_` | evaluator |
| AC-46 | Stack, Parse `SEC_M`, Ask the Portfolio tab | `Q` is asked | a header cell reads `Market value (EUR million)`; the line under the table starts `Total: EUR `, has two decimals and ends ` million` | evaluator |
| AC-47 | Stack, Parse `WACI`, Ask the Portfolio tab | `Q` is asked | a header cell reads `Weighted avg (tCO2e / EUR M revenue)` | evaluator |
| AC-48 | the frontend's `dimensionLabel` | called with each id of section 11 and with `my_dim` | the labels of section 11; `my_dim` → `My dim` | unit |
| AC-49 | Stack, C evaluated | `DELETE /api/portfolio/monitoring/rules/<C>` | status 409 and `detail` == `Rule has <n> live alerts: clear them first.` | holdout |
| AC-50 | after AC-49 | `GET /api/portfolio/monitoring/rules` | C is still listed | holdout |
| AC-51 | Stack, C evaluated | `POST /api/portfolio/monitoring/rules/<C>/clear-alerts` with `{"status": "false_positive", "reason": "wrong threshold"}` | status 200, body == `{"cleared": n}` | holdout |
| AC-52 | after AC-51 | `GET /api/portfolio/monitoring/alerts?status=open` | no alert carries C's `rule_id` | holdout |
| AC-53 | after AC-51; C's alerts as they were listed before the call | `GET /api/portfolio/monitoring/alerts?status=false_positive` | `n` alerts carry C's `rule_id`, each with the same `alert_id`, `triggered_at`, `observed_value` and `rationale` as before | holdout |
| AC-54 | a store with a rule and two open alerts of it | `clear-alerts` is called, then `store.list_alert_events(<scope>)` is read for one alert | its `alert_raised` event is unchanged, and exactly one `status_changed` event was appended for it, with the sent `status` and `reason` and `decided_by` = the caller's name | unit |
| AC-55 | after AC-51 | the same `clear-alerts` call again | body == `{"cleared": 0}` | holdout |
| AC-56 | Stack, C evaluated | `clear-alerts` with `{"status": "acknowledged"}` | status 422, and `n` open alerts still carry C's `rule_id` | holdout |
| AC-57 | Stack, C evaluated, one of C's alerts moved to `acknowledged` and one to `escalated` (the existing transition route) | `clear-alerts` with `{"status": "resolved"}` | body == `{"cleared": n}` | holdout |
| AC-58 | Stack, C evaluated, and a second rule C2 (C's body, name `Other <x>`) evaluated | `clear-alerts` for C | the number of open alerts carrying C2's `rule_id` is unchanged | holdout |
| AC-59 | Stack, C evaluated, then cleared as in AC-51 | `DELETE /api/portfolio/monitoring/rules/<C>` | status 204 | holdout |
| AC-60 | after AC-59 | `GET /api/portfolio/monitoring/rules` | no rule has C's `rule_id` | holdout |
| AC-61 | after AC-59 | `GET /api/portfolio/monitoring/alerts` | `n` alerts still carry C's `rule_id`, all with status `false_positive` | holdout |
| AC-62 | Stack | `DELETE /api/portfolio/monitoring/rules/rule_nope<x>` | status 404, `detail` == `Unknown rule rule_nope<x>` | holdout |
| AC-63 | Stack, rule C stored | `POST /api/portfolio/monitoring/rules` with C's full body, the same `rule_id` and `created_at`, `"enabled": false` | `GET .../rules` has exactly one rule with that `rule_id`, with `enabled` false (must not change) | holdout |
| AC-64 | after AC-63, C never evaluated before | `POST /api/portfolio/monitoring/evaluate-now`, then `GET .../alerts` | no alert carries C's `rule_id` (must not change) | holdout |
| AC-65 | the test client of `backend/tests/test_api_ask.py` signed in as a viewer; one rule stored | `DELETE` the rule, and `clear-alerts` on it | both answer 403 and the rule is still stored | unit |
| AC-66 | Stack, C stored, Monitoring & Alerts tab | `Disable` on C's row is clicked, then the page is reloaded | C's `Enabled` cell reads `no` and its button reads `Enable` | evaluator |
| AC-67 | Stack, C stored (threshold 0) | `Edit` on C's row, `Threshold (%)` set to 10, `Save rule` clicked | the rules table still has one row for C, its condition reads `Weight of one company > 10%`, and `GET .../rules` shows `threshold_value` 0.1 under C's `rule_id` | evaluator |
| AC-68 | Stack, C evaluated, Monitoring & Alerts tab | `Delete` on C's row is clicked and the dialog accepted | the page shows `Rule has <n> live alerts: clear them first.` and C's row is still listed | evaluator |
| AC-69 | Stack, C evaluated, Monitoring & Alerts tab | `Clear alerts` → `False positive` on C's row | under the filter `open` none of C's alerts is listed; under `false positive` all `n` are | evaluator |
| AC-70 | the AC-69 page | `Delete` on C's row is clicked and accepted, then the filter `all` is chosen | C's row is gone and the `Rule` cell of each of its `n` alerts reads `Deleted rule` | evaluator |
| AC-71 | Stack, C evaluated | the alerts table is read | the `Scope` cell of each of C's alerts reads `<company id> · across Core Equity Europe` | evaluator |
| AC-72 | the AC-71 table | `Observed` and `Threshold` of one of C's alerts are read | `Threshold` reads `0%`; `Observed` ends with `%` and equals the alert's `observed_value` × 100 with at most 2 decimals | evaluator |
| AC-73 | Stack, rule A stored | the rules table is read | A's row reads Type `Portfolio aggregate (WACI-style)`, Condition `Carbon intensity > 50 tCO2e / EUR M revenue`, Scope `Core Equity Europe` | evaluator |
| AC-74 | the AC-73 row | its text is searched | it contains none of `portfolio_aggregate_threshold`, `climate_carbon_intensity`, ` gt ` | evaluator |
| AC-75 | Stack, rule A with `"portfolio_ids": []` stored | the rules table is read | its Scope reads `All portfolios` | evaluator |
| AC-76 | Stack, rule A with `"threshold_value": 0` stored and evaluated (it raises an alert for `CEE`) | that alert's row in the alerts table is read | `Scope` reads `Core Equity Europe`, `Rule` reads `Carbon cap`, `Breach type` reads `No earlier breach to compare`, `Threshold` reads `0` | evaluator |
| AC-77 | the AC-76 table | its `Scope` and `Breach type` columns are searched | no cell contains `portfolio__` or `Unknown` | evaluator |
| AC-78 | the frontend's percent function of section 10 | called with 0.05, 0.0712, 0.125, 0.07, 1, 0 | `5%`, `7.12%`, `12.5%`, `7%`, `100%`, `0%` | unit |
| AC-79 | the frontend's breach-type label of section 10 | called for `unknown` on a `news_controversy` alert; for `holdings_caused`, `data_caused`, `mixed` | `—`; `Holdings-caused`, `Data-caused`, `Mixed` (the last three must not change) | unit |
| AC-80 | Stack | `#/portfolio-monitoring` is opened | the `Monitoring & Alerts` tab has `aria-pressed="true"` and the selection pane is shown | evaluator |
| AC-81 | Stack | `#/portfolio-monitoring/dashboards`, `#/portfolio-monitoring/pivot` and `#/portfolio-monitoring/ask` are opened in turn | the pressed tab is `Dashboards (Superset)`, `Dashboards (Superset)`, `Ask the Portfolio` (must not change) | evaluator |
| AC-82 | Stack with `ARP_SUPERSET_PASSWORD` unset (`GET /api/bi/dashboards` answers 503), Company Profiles tab | the "Profile dashboard" card is read | it shows `Dashboards are not set up on this server. Ask your administrator.`, has no element with `role="alert"`, and does not contain `could not be loaded` | evaluator |
| AC-83 | a browser test, `GET /api/bi/dashboards` answered with 500 `boom` | the "Profile dashboard" card is read | a `role="alert"` element reads `The profile dashboard could not be loaded: boom` (must not change) | unit |

### Slice 2: the rest (defects 2, 3, 4, 7, 8, 6, 12)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-84 | Stack; `model/ReportPlan.json` also has `"delay_seconds": 5`; a report request filled in on Presentations & Reports | `Draft content plan` is clicked | within 2 s a `role="status"` line reads `Drafting the content plan… 0:0<s> elapsed. This can take a few minutes; keep this page open.`, and the button reads `Drafting…` and is disabled | evaluator |
| AC-85 | the AC-84 page | the line is read again 2 s later, and once the plan is shown | the elapsed time is larger; after the plan is shown the line is gone | evaluator |
| AC-86 | the frontend's `elapsedLabel` | called with 0, 42, 196, 3600 | `0:00`, `0:42`, `3:16`, `60:00` | unit |
| AC-87 | the frontend's drafting-line function of section 2 | called for a house deck at 5 s, and for another format at 65 s | `Drafting the storyline… 0:05 elapsed. This can take a few minutes; keep this page open.` and `Drafting the content plan… 1:05 elapsed. This can take a few minutes; keep this page open.` | unit |
| AC-88 | Stack; a draft R | `DELETE /api/reports/R` | status 204 | holdout |
| AC-89 | after AC-88 | `GET /api/reports`, then `GET /api/reports/R` | R is not listed; the second call answers 404 | holdout |
| AC-90 | a `ReportingStore` on a temp folder with a `plan_ready` report R, behind the API test client | `DELETE /api/reports/R`, then `DELETE /api/reports/rpt_000000000000` | after the first, `reports_dir/R` does not exist; the second answers 404 and `reports_dir/rpt_000000000000` does not exist | unit |
| AC-91 | Stack; a finished report R | `DELETE /api/reports/R` | status 409, `detail` == `Only an unfinished report can be discarded (status: completed).` | holdout |
| AC-92 | Stack; a finished report R, after a `DELETE /api/reports/R` attempt | `GET /api/reports/R` and `GET /api/reports/R/download` | 200 with status `completed`; 200 (must not change) | holdout |
| AC-93 | manifests saved through `ReportingStore` with status `storyline_ready`, `failed`, `planning`, `rendering`, `pending`, behind the API test client | `DELETE` each | 204 for `storyline_ready` and `failed`; 409 with the status in `detail` for the other three, which are still stored | unit |
| AC-94 | Stack | `DELETE /api/reports/rpt_000000000000` | status 404 | holdout |
| AC-95 | Stack; five drafts made one after another, at least 1 s apart | `GET /api/reports` | among these five, the order is the reverse of their creation | holdout |
| AC-96 | manifests saved with `created_at` `2026-11-01T10:00:00`, `2026-11-03T10:00:00`, `2026-11-02T10:00:00` under ids `rpt_c00000000000`, `rpt_a00000000000`, `rpt_b00000000000` | `ReportingStore.list_reports()` | their order is 3 Nov, 2 Nov, 1 Nov | unit |
| AC-97 | the test client of `backend/tests/test_api_ask.py` signed in as a viewer; a `plan_ready` report stored | `DELETE /api/reports/<id>` | 403 and the report is still stored | unit |
| AC-98 | Stack; a draft, Presentations & Reports open | its row in "Previous reports" is read, then `Open` is clicked | the row shows `Open` and `Discard`; after the click the "Review & render" section shows its plan | evaluator |
| AC-99 | the AC-98 page with the draft open | `Discard` is clicked and the dialog accepted | the row is gone, the "Review & render" section is gone, and `GET /api/reports` no longer lists the draft | evaluator |
| AC-100 | a browser test, `GET /api/reports` answered with one `failed` and one `completed` report | the two rows are read | the `failed` row shows `Discard` and no `Open`; the `completed` row shows `Preview` and `Download` and no `Discard` | unit |
| AC-101 | Stack, an approver, `model/QuotedPairs.json` holds a valid answer with `"delay_seconds": 5` | one `.docx` is chosen under "Answer library" and `Import past responses` clicked | within 2 s a `role="status"` line reads `Importing 1 file… 0:0<s> elapsed. This can take a few minutes; keep this page open.` | evaluator |
| AC-102 | the AC-101 import has finished with response `{"imported": i, "dropped": []}` | the page is read | a visible `role="status"` line outside `#announcer` reads `Imported <i> entries, dropped 0`, and is still there 10 s later | evaluator |
| AC-103 | the frontend's import-progress text of section 3 | called for 1 file at 5 s and 2 files at 65 s | `Importing 1 file… 0:05 elapsed. This can take a few minutes; keep this page open.` and `Importing 2 files… 1:05 elapsed. This can take a few minutes; keep this page open.` | unit |
| AC-104 | Stack; `H(X)` without its `Currency` column uploaded for `typo_<x>` as of `S4` (it answers 422 `file rejected`, as today) | `GET /api/feeds` | no row has `source_id` `typo_<x>` | holdout |
| AC-105 | the AC-104 Given | `GET /api/issues` | no issue has `subject` `typo_<x>` | holdout |
| AC-106 | a file store with a `load_recorded` event `{kind: "holdings", source_id: "ghost_fund", month: "2026-10", status: "failed", content_hash: "", detail: "4 row errors"}` and no holder or portfolio of that id | `feeds.overview` and the issues list are built; and a rejected upload for an unknown holder is ingested | neither has an entry for `ghost_fund`; the rejected upload adds no `load_recorded` event | unit |
| AC-107 | Stack; `H(X)` uploaded for `good_<x>` as of `O` (ok), then `H(X)` without `Currency` uploaded for `good_<x>` as of `O` | `GET /api/feeds` and `GET /api/issues` | the `good_<x>` feed row has `last_load.status` `failed`, and an issue titled `Portfolio holdings · good_<x>: last load failed` with severity `block` exists (must not change) | holdout |
| AC-108 | Stack; `H(X)` without `Currency` uploaded for `corporate_bond_income` as of `S4` (a portfolio with no holder config) | `GET /api/feeds` | the `corporate_bond_income` row has `last_load.status` `failed` (must not change) | holdout |
| AC-109 | Stack | `GET /api/feeds` | the rows with `source_id` `core_equity_europe` and `sustainable_leaders` have `feed` `holdings`, `stale` false and `channel` null (must not change) | holdout |
| AC-110 | Stack; Master (`iss_<x>`, `X`) uploaded; `H(X)` uploaded for `esg_<x>` as of `O` | ESG row for `iss_<x>`, month of `S1` | status 200, `status` `written`, `rows` 1 | holdout |
| AC-111 | the AC-110 Given | ESG row for `nope_<x>`, month of `S1` | status 422 and an error with message `unknown company_id 'nope_<x>'` (must not change) | holdout |
| AC-112 | the repo at the PR head | `pytest tests/test_esg_intake.py tests/test_esg_api_source.py` | exit code 0 | unit |
| AC-113 | Stack | `GET /api/holdings/holders` | every portfolio of `GET /api/portfolio/portfolios` appears exactly once, with `kind` `portfolio`; the `sustainable_leaders` row has `name` `Sustainable Leaders Fund`, `source` null, `as_of` == `S4`, `stale` false, `last_pull_at` null, `last_error` null | holdout |
| AC-114 | a seeded file store behind the API test client | `GET /api/holdings/holders`, then `store.list_holders()` | the response has 4 rows; `list_holders()` is empty | unit |
| AC-115 | Stack; `H(X)` uploaded for `multi_asset_balanced` as of `O` | `GET /api/holdings/holders` | exactly one row has `holder_id` `multi_asset_balanced`, and its `source` is `file` (must not change) | holdout |
| AC-116 | a seeded file store with no security master, behind the API test client | `GET /api/holdings/holders`, then `GET /api/security-master/unmatched` and `GET /api/issues` | no unmatched security; no issue with `source` `security_master` (must not change) | unit |
| AC-117 | Stack, Holdings Intake tab | the holder table is read | 4 rows named after the demo portfolios, each with Source `—`, As of `S4` and no `Pull now` button | evaluator |
| AC-118 | Stack, Holdings Intake tab | `H(X)` is uploaded for `acme_fund` as of `S4` through the form, without reloading | the selection pane lists `acme_fund` | evaluator |
| AC-119 | the AC-118 page, monthly-run month = month of `S4` | the "Monthly run" table is read, without reloading | it has a row `Holdings acme_fund` | evaluator |
| AC-120 | Stack, Holdings Intake tab, monthly-run month set to `2020-01` (its ESG row reads `missing`) | an ESG row for `bmw`, month `2020-01`, is uploaded through the form, without reloading | the ESG row of the "Monthly run" table reads `ok` | evaluator |
| AC-121 | Stack; `H(X)` without its `Weight (%)` and `Currency` columns | upload for `cols_<x>` as of `O` | status 422; the errors with `row` null are exactly `{"row": null, "column": "Weight (%)", "message": "missing required column"}` and `{"row": null, "column": "Currency", "message": "missing required column"}` | holdout |
| AC-122 | the AC-121 file uploaded through the Holdings Intake form | the error list is read | it has the lines `missing required column: Weight (%)` and `missing required column: Currency` | evaluator |
| AC-123 | the frontend's `rowErrorText` | called with `{row: null, column: "Weight (%)", message: "missing required column"}`, `{row: null, column: "weight", message: "weights sum to 1%, not 100% ± 0.5"}`, `{row: null, column: null, message: "missing header"}` | `missing required column: Weight (%)`; `weights sum to 1%, not 100% ± 0.5`; `missing header` | unit |
| AC-124 | Stack; `H(X)` with decimal commas (market value `1000,50`, weight `100,0`), saved as a semicolon-separated CSV | upload for `comma_<x>` as of `O` with form field `decimal` = `,` | status 200, `status` `written` | holdout |
| AC-125 | the AC-124 file | upload for `comma2_<x>` as of `O` without the `decimal` field | status 422 (must not change) | holdout |
| AC-126 | a file store behind the API test client; the AC-124 upload | the stored snapshot is read | its one holding has `market_value` 1000.5 and `weight_pct` 100 | unit |
| AC-127 | Stack; `H(X)` with weight `1` | upload for `frac_<x>` as of `O` with form field `weight_unit` = `fraction` | status 200, `status` `written` | holdout |
| AC-128 | the AC-127 file | upload for `frac2_<x>` as of `O` without `weight_unit` | status 422 with an error whose message starts `weights sum to 1%` (must not change) | holdout |
| AC-129 | a file store behind the API test client; the AC-127 upload | the stored snapshot is read | its one holding has `weight_pct` 100 | unit |
| AC-130 | Stack | upload `H(X)` for `opts_<x>` as of `O` with `decimal` = `;`, and again with `weight_unit` = `bps` | both 422, and `GET /api/holdings/holders` has no row for `opts_<x>` | holdout |
| AC-131 | Stack, Holdings Intake tab | the upload form is read | selects `Decimal separator` (options `Point (1,234.56)`, `Comma (1.234,56)`) and `Weights are` (options `Percent (5 = 5%)`, `Fraction (0.05 = 5%)`), with Point and Percent chosen | evaluator |
| AC-132 | Stack; Master (`iss_<x>`, `X`) uploaded; `H(X)` uploaded for `F` = `old_<x>` as of `O` | `POST /api/decision/datasets/from-source` with `{"source": "portfolio_snapshot", "portfolio_ids": [F]}` | `name` == `Portfolio holdings as of <O>` and `as_of` == `O` | holdout |
| AC-133 | the AC-132 Given | the same call with `"portfolio_ids": [F, "core_equity_europe"]` | `name` == `Portfolio holdings as of <O> to <S4>` and `as_of` == `S4` | holdout |
| AC-134 | Stack | the same call with `"portfolio_ids": ["core_equity_europe"]`; and again with `"as_of": S2` added | `name` == `Portfolio holdings as of <S4>`, `as_of` == `S4`; and `Portfolio holdings as of <S2>`, `as_of` == `S2` (must not change) | holdout |
| AC-135 | the AC-132 Given | `POST /api/portfolio/universe` with `{"portfolio_ids": [F, "core_equity_europe"]}` | `as_of` == `S4` and the file name (last part of the returned `path`) starts `holdings_<F>_core_equity_europe_<O>_to_<S4>_` | holdout |
| AC-136 | Stack | `POST /api/portfolio/universe` with `{"portfolio_ids": ["core_equity_europe"]}` | `as_of` == `S4` and the file name starts `holdings_core_equity_europe_<S4>_` (must not change) | holdout |
| AC-137 | Stack (no security master loaded), Security Master page | the page is read | it shows `No holdings have been loaded through Holdings Intake yet.` and does not contain `Every held security is matched.` | evaluator |
| AC-138 | Stack; Master (`iss_a`, `X`) and `H(X)` for `acme_fund` as of `S4` uploaded; Security Master page | the unmatched table is read | its empty row reads `Every held security is matched.` (must not change) | evaluator |
| AC-139 | a seeded file store behind the API test client, no monthly run yet | `GET /api/portfolio/monthly-run/last` | status 200, body `null` | unit |
| AC-140 | Stack; `M` = the month of `S4` | `POST /api/portfolio/monthly-run` with `{"month": M, "portfolio_ids": ["sustainable_leaders"]}` answers `{"status": "ran", "alerts": a, "triggers": t}`; then `GET /api/portfolio/monthly-run/last` | `month` == `M`, `alerts` == `a`, `triggers` == `t`, and `at` is an ISO date-time not earlier than the start of the test | holdout |
| AC-141 | Stack; the answer of `GET /api/portfolio/monthly-run/last` is noted | `POST /api/portfolio/monthly-run` with `{"month": "2001-01", "portfolio_ids": ["sustainable_leaders"]}` answers `status` `blocked`; then `GET .../monthly-run/last` | status 200 with the same body as noted | holdout |
| AC-142 | Stack; the AC-140 run made; the Home hub's "Monthly monitoring" process | its steps are read | `Monitoring & Alerts` reads `Done · <day month of the run>` | evaluator |
| AC-143 | Stack, the Home hub | the steps `Holdings Intake` (Monthly monitoring) and `Map holdings` (Map securities to issuers) are read | both start `Done · ` | evaluator |
| AC-144 | Stack; Master (`iss_a`, `X`) uploaded | the step `Load security master` is read; then a master file that is rejected is uploaded and the hub reloaded | first `Done · <day month>`; then `Last run failed` | evaluator |
| AC-145 | the frontend's `stepState` and `stepStatusLine` | called for the four steps of section 12b with no activity | state `idle` and the line `No runs yet` (must not change) | unit |
| AC-146 | the repo at the PR head | `npm test` in `frontend` | exit code 0, including `tests/subTabs.test.ts`, `tests/holdings.test.ts`, `tests/workspaceCard.test.ts` and `tests/processes.test.ts` | unit |
| AC-147 | Stack; the same file `companies_<x>.csv` uploaded twice to `POST /api/decision/datasets`, 2 s apart | `GET /api/decision/datasets` | two entries named `companies_<x>.csv`, each with an ISO date-time `created_at`, and the two differ | holdout |
| AC-148 | Stack; `companies.csv` uploaded twice in Decision Studio, 2 s apart | the Data table is read | it has a column `Added`, and the two `companies.csv` rows show different values in it | evaluator |
| AC-149 | the AC-148 Given, the Movement dropdown | its options are read | the two uploads read `companies.csv · added <their Added text>` and differ | evaluator |
| AC-150 | a browser test: `GET /api/portfolio/portfolios` answered with `[]`, then, after `POST /api/portfolio/demo/seed` is answered with `{"company_count": 30, "portfolio_count": 4, "holding_rows": 480}`, with four portfolios | `Seed demo dataset` is clicked | the pane lists the portfolios and shows `Seeded 30 companies, 4 portfolios, 480 holding rows.` | unit |
| AC-151 | the frontend's `findingText` | called with `{stage: "qa", rule: "invalid_edit", slot: "number_1", message: "edit changes nothing"}` | null (not listed) | unit |
| AC-152 | the frontend's `findingText` | called with `{stage: "qa", rule: "applied", message: "Shortened the headline"}`; `{stage: "fit", rule: "slot_dropped", slot: "number_1", message: "Slot 'number_1' does not exist in a/b; its content was dropped."}`; `{stage: "lint", rule: "exclamation", slot: "headline", message: "Remove the exclamation mark."}`; `{stage: "new", rule: "x", message: "m"}` | `Visual check: adjusted. Shortened the headline`; `Layout: some content did not fit this slide and was left out.`; `Wording: Remove the exclamation mark.`; `Check: m` | unit |
| AC-153 | a browser test: a house deck result whose `/findings` call is answered with an `invalid_edit` finding on slide 2 and an `exclamation` finding (slot `headline`) on slide 3 | the Findings list is read | it lists slide 3 only, with `Wording: Remove the exclamation mark.`, and the page contains neither `qa/invalid_edit` nor `[headline]` | unit |
| AC-154 | Stack | `#/valueChain/exposure`, `#/valueChain/shock`, `#/valueChain/tree` and `#/valueChain/footprint` are opened in turn | each shows the heading `Value Chain Explorer` and the search box; none shows a heading `exposure`, `shock`, `tree` or `footprint` | evaluator |
| AC-155 | Stack | `#/valueChain/portfolio` is opened | the heading reads `Portfolio` (must not change) | evaluator |
| AC-156 | the repo at the PR head | `cd backend && python scripts/export_openapi.py --check`, then `cd frontend && npm run gen:api && git diff --exit-code src/api` | both exit 0 | unit |
| AC-157 | the repo at the PR head | `git diff origin/main -- backend/tests frontend/tests` | no removed line (no line starting with a single `-`) | unit |
| AC-158 | a file store with governance events and alert events, behind the API test client | a rejected upload, a monthly run, `clear-alerts`, a rule delete and a report discard are made | every governance and alert event line that existed before is still there, byte for byte and in the same order | unit |

Must not change: a request with only `question` (AC-5, AC-25, AC-34, AC-39); a portfolio named in the question
(AC-21); plain-EUR figures (AC-38); replacing a rule by `rule_id` and skipping disabled rules (AC-63, AC-64);
the known breach-type labels (AC-79); named and legacy sub-tabs (AC-81); other dashboard errors (AC-83);
finished reports (AC-92); failed loads for holders and portfolios that exist, and the demo feed rows (AC-107
to AC-109); ESG id checks (AC-111, AC-112); holder rows of configured holders (AC-115); Security Master and
Issues for the demo seed (AC-116, AC-138); the default decimal and weight unit (AC-125, AC-128); holdings
tables with one date (AC-134, AC-136); idle hub steps (AC-145); the existing frontend tests (AC-146); the
Portfolio value-chain heading (AC-155); existing test lines and log lines (AC-157, AC-158).
