# Showcase fixes for the portfolio screens (rehearsal of 11 Nov 2026)

## Decisions assumed, the owner can change any at approval

The owner was asked these three questions and had not answered when the spec was written. The spec is
built on the recommended option of each. Changing one changes only the rows named.

1. **Demo portfolios on Holdings Intake: listed read-only.** The holder table also shows every portfolio
   that has no holder record; nothing is stored. Alternative: the demo seed stores a holder record per
   portfolio, which turns every demo ISIN into a Blocking "unmatched" issue on a fresh seed with no security
   master. (Rows AC-105 to AC-109.)
2. **Concentration alerts: wording only.** The alert names the portfolios its rule covers and shows percent;
   no figure and no alert logic changes. Alternative: one alert per portfolio, which changes figures and
   duplicate handling and needs its own PR after the showcase. (Rows AC-63, AC-64.)
3. **Monitoring rules: delete and disable.** A rule can be switched off, edited and deleted. Alternative:
   disable and edit only, no delete. (Rows AC-39, AC-45 to AC-48, AC-55, AC-56.)

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
  **slice 1, Risk Monitoring** (defects 1, 5, 9, 10, 11): `Rows: AC-1 to AC-75`; **slice 2, the rest**: no
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
- Names instead of ids in the rows of an Ask answer (`bmw`), and in company-scoped alert cells.
- Three finds from the triage, to be raised as follow-ups: uploaded issuers are dropped from the hand-over to
  Argus (`holdings_universe` keeps only registry companies); a repeat Decision Studio upload overwrites the
  earlier file in `_uploads/`; a report left in `planning` after a crash.

## Anti-goals

- No stored alert event, governance event, holding or snapshot is edited or deleted by this change.
- A completed report can never be discarded through the new route.
- No money figure changes for a request that names no date and no scale.
- No existing test is edited.

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

Refused with 422 before any model call and without an audit row (as request validation is today):

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

`QAAnswer` gains three fields (existing fields keep their meaning):

| Field | Value |
|-------|-------|
| `trend` | null for a point-in-time answer. For a trend: the engine's `TrendPoint` list, ascending by `as_of`; `result` is then null. |
| `scale` | `"units"` or `"millions"`, see section 11. |
| `unit` | `"EUR"` for `market_value_sum`; the data point's unit from the climate schema for `weighted_avg_datapoint` (`""` for a field the schema does not know); `""` for `count`. |

Trend answer: `vintage` = `{"snapshot_dates": [...]}` (the points' dates). `answer_text` for
`market_value_sum`: first line `Trend from <start> to <end>, <n> snapshots (<scope>, <filter>, grouped by <group_by>):`
with `<scope>` and `<filter>` built as in today's point-in-time text, then one line per point
`  <as_of>: EUR <total_market_value_eur:,.0f>` (or the millions form of section 11). For the other metrics:
the same first line, then one line per point starting with two spaces and the date.

`qa_agent.answer_question` takes the three values as keyword arguments with defaults, so its other callers
(`routers/ask.py:81`, `cli/portfolio.py:157`) are unchanged.

Frontend: the three date inputs in `DateSelector.tsx` are `type="date"`; the as-of input has `max` = today.
With a trend whose end is before its start, the pane shows `The end date is before the start date.` under the
boxes and the selection counts as "latest". `AskThePortfolio` sends the typed question plus
`portfolio_ids`, `as_of`, `date_range` from the pane; the "Scoped to:" line stays. A trend answer is shown as a
table: header `As of`, one column per group value (order of first appearance), and `Total` for
`market_value_sum`; one row per point, ascending; a group absent on a date shows `—`.

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
  `elapsedLabel(seconds)` in the frontend gives `m:ss` (`0:42`, `3:16`).
- `DELETE /api/reports/{report_id}`: 204 and the report's folder is removed, when its status is
  `plan_ready`, `storyline_ready` or `failed`. Any other status: 409
  `Only an unfinished report can be discarded (status: <status>).` Unknown id: 404. The folder is resolved
  through `ReportingStore.report_dir`.
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
  `last_pull_at` and `last_error` null. Configured holders come first. Nothing is stored;
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
  `Weights are` (`Percent (5 = 5%)`, `Fraction (0.05 = 5%)`), defaulting to Point and Percent. The existing
  weight-sum check (100% ± 0.5) still rejects a wrong choice.

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

  The step line reads `Done · <day month>` of that load or run (`stepStatusLine`), `Last run failed`, or
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
model key; calls are made as a user who may write (analyst), the RFP rows as an approver. "Seeded" is an
empty portfolio store after `POST /api/portfolio/demo/seed`: four portfolios (`core_equity_europe` "Core
Equity Europe", `sustainable_leaders`, `multi_asset_balanced`, `corporate_bond_income`) with snapshot dates
`S1 < S2 < S3 < S4` = `arp.portfolio.mock_data.snapshot_dates(date.today())`; `S4` is the last day of the
previous month. "Parse P" means `model/_ParsedQuestion.json` = `{"output": P}` in the stand-in folder.
`BMW` = `{"resolvable": true, "spec_name": "", "portfolio_filter": [], "security_filter": {"company_id": "bmw"}, "group_by": "portfolio_id", "metric": "market_value_sum"}`;
`BMW_M` = `BMW` plus `"scale": "millions"`; `WACI` = `{"resolvable": true, "spec_name": "", "portfolio_filter": [], "security_filter": {}, "group_by": "portfolio_id", "metric": "weighted_avg_datapoint", "data_point_field_id": "climate_carbon_intensity"}`.
`ask(B)` is `POST /api/portfolio/ask` with body `B`; `Q` is the string `How much BMW do we hold?`.
"Engine total for date d" is `analytics.execute` on `AnalyticSpec(name=Q, security_filter={"company_id": "bmw"}, group_by="portfolio_id", metric="market_value_sum", as_of=d)`, its `total_market_value_eur`.
`H` is the portfolio template (`GET /api/holdings/template`) with one data row: a valid ISIN `X`, weight
100, market value 1000, currency EUR. "Upload H for h as of d" is `POST /api/holdings/upload` with
`holder_id` h, `kind` portfolio, `as_of` d. `N` is the day after `S4`. "Rule C" is
`POST /api/portfolio/monitoring/rules` with `{"name": "Any weight", "rule_type": "concentration_threshold", "comparator": "gt", "threshold_value": 0, "portfolio_ids": ["core_equity_europe"]}`;
"C evaluated" adds `POST /api/portfolio/monitoring/evaluate-now`, after which `n ≥ 1` open alerts carry C's
`rule_id`. "Rule A" is `{"name": "Carbon cap", "rule_type": "portfolio_aggregate_threshold", "field_id": "climate_carbon_intensity", "comparator": "gt", "threshold_value": 50, "portfolio_ids": ["core_equity_europe"]}`.
A report "with status s" is a manifest saved through `ReportingStore` with that status. Browser rows run at
1400×900; table headers are compared without regard to case (the stylesheet upper-cases them).

### Slice 1: Risk Monitoring (defects 1, 11, 5, 10, 9)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "as_of": S2})` | status 200, `result.as_of` == `S2` | holdout |
| AC-2 | the AC-1 response | `vintage` is read | `vintage.holdings_as_of` == `S2` | holdout |
| AC-3 | the AC-1 response | `result.total_market_value_eur` is read | equals the engine total for date `S2` | holdout |
| AC-4 | Stack, Seeded, Parse `BMW` | `ask({"question": Q})` | `result.as_of` == `S4` and the total equals the engine total for `S4` (must not change) | holdout |
| AC-5 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "as_of": "31/12/2099"})` | status 422, `detail` contains `as_of must be YYYY-MM-DD` | holdout |
| AC-6 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "as_of": "2099-12-31"})` | status 422, `detail` contains `as_of is in the future` | holdout |
| AC-7 | Stack, Seeded, Parse `BMW`; `d` = the day before `S1` | `ask({"question": Q, "as_of": d})` | status 200, `resolvable` false, `result` null | holdout |
| AC-8 | the AC-7 response | `clarification_needed` is read | == `No holdings on or before <d>. The first snapshot is <S1>.` | holdout |
| AC-9 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "date_range": [S2, S4]})` | status 200, `resolvable` true, `result` null, `[p.as_of for p in trend]` == `[S2, S3, S4]` | holdout |
| AC-10 | the AC-9 response | each point's `result.total_market_value_eur` is read | equals the engine total for that point's date | holdout |
| AC-11 | the AC-9 response | `answer_text` is split into lines | 4 lines; line 1 == `Trend from <S2> to <S4>, 3 snapshots (all portfolios, company_id=bmw, grouped by portfolio_id):` | holdout |
| AC-12 | the AC-9 response | lines 2 to 4 of `answer_text` are read | line i+1 == two spaces + `<date i>: EUR ` + that point's total formatted `{:,.0f}` | holdout |
| AC-13 | the AC-9 response | `vintage` is read | == `{"snapshot_dates": [S2, S3, S4]}` | holdout |
| AC-14 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "date_range": [S4, S2]})` | status 422, `detail` contains `date_range start is after its end` | holdout |
| AC-15 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "date_range": ["2026-13-01", S4]})` | status 422, `detail` contains `date_range must be two YYYY-MM-DD dates` | holdout |
| AC-16 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "as_of": S2, "date_range": [S2, S4]})` | status 422, `detail` contains `send as_of or date_range, not both` | holdout |
| AC-17 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "date_range": ["2001-01-01", "2001-12-31"]})` | status 200, `resolvable` false, `clarification_needed` == `No snapshots between 2001-01-01 and 2001-12-31. Snapshots run from <S1> to <S4>.` | holdout |
| AC-18 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "portfolio_ids": ["core_equity_europe"]})` | `spec.portfolio_filter` == `["core_equity_europe"]` | holdout |
| AC-19 | the AC-18 response | `result.rows` is read | every `group_value` is `core_equity_europe` | holdout |
| AC-20 | Stack, Seeded, Parse `BMW` with `"portfolio_filter": ["sustainable_leaders"]` | `ask({"question": Q, "portfolio_ids": ["core_equity_europe"]})` | `spec.portfolio_filter` == `["sustainable_leaders"]` | holdout |
| AC-21 | Stack, Seeded, Parse `BMW` | `ask({"question": Q, "portfolio_ids": ["nope"]})` | status 422, `detail` contains `unknown portfolio_id 'nope'` | holdout |
| AC-22 | Stack, Seeded, Parse `BMW`; the number of rows of `GET /api/portfolio/qa-audit` (as an approver) is noted | the AC-5, AC-6, AC-14, AC-15, AC-16 and AC-21 requests are sent | the number of audit rows is unchanged | holdout |
| AC-23 | Stack, Seeded, Parse `BMW` | after `ask({"question": Q, "as_of": S2})`, the newest audit row is read | its `question` == `Q` and its `vintage.holdings_as_of` == `S2` | holdout |
| AC-24 | the repo at the PR head | `pytest tests/test_api_ask.py tests/test_qa_agent.py tests/test_qa_audit.py` with those files unchanged from `main` | exit code 0 | unit |
| AC-25 | Stack, Seeded, Risk Monitoring open | the date mode is switched to "As of date" and then "Trend range" | the as-of input and both trend inputs have `type="date"` | evaluator |
| AC-26 | Stack, Seeded, Parse `BMW`, Ask the Portfolio tab, As of date set to `S2` | `Q` is typed and Ask is clicked | the request body sent to `/api/portfolio/ask` has `question` == `Q` exactly and `as_of` == `S2` | evaluator |
| AC-27 | the AC-26 answer on the page | the caption under the table is read | it ends `as of <S2>` | evaluator |
| AC-28 | Stack, Seeded, Parse `BMW`, Trend range `S2` to `S4` | `Q` is asked | a table whose header starts `As of` and whose 3 body rows start with `S2`, `S3`, `S4` in that order | evaluator |
| AC-29 | Stack, Seeded, Trend range with From `S4` and To `S2` | the pane is read | it shows `The end date is before the start date.` and the "Scoped to:" line ends `latest` | evaluator |
| AC-30 | Stack, Seeded, Parse `BMW` | `ask({"question": "How many EUR million is our exposure to BMW?"})` | `result.spec_name` == that question exactly | holdout |
| AC-31 | Stack, Seeded, Parse `BMW_M` | `ask({"question": Q})` | `scale` == `"millions"` and `unit` == `"EUR"` | holdout |
| AC-32 | the AC-31 response, total `t` = `result.total_market_value_eur` | line 1 of `answer_text` is read | starts `Total: EUR ` + `t / 1e6` formatted `{:,.2f}` + ` million (` | holdout |
| AC-33 | the AC-31 response | each further line of `answer_text` is read | == two spaces + `<group_value>: EUR ` + that row's `market_value_eur / 1e6` formatted `{:,.2f}` + ` million` | holdout |
| AC-34 | Stack, Seeded | `ask({"question": Q})` once with Parse `BMW`, once with Parse `BMW_M` | `result.total_market_value_eur` is the same number in both | holdout |
| AC-35 | Stack, Seeded, Parse `BMW` | `ask({"question": Q})` | `scale` == `"units"`, `unit` == `"EUR"`, line 1 of `answer_text` starts `Total: EUR ` + the total formatted `{:,.0f}` + ` (` (must not change) | holdout |
| AC-36 | Stack, Seeded, Parse `WACI` | `ask({"question": "What is our WACI?"})` | `unit` == `tCO2e / EUR M revenue` and `scale` == `"units"` | holdout |
| AC-37 | Stack, Seeded, Parse `BMW` with `"metric": "count"` | `ask({"question": Q})` | `unit` == `""` | holdout |
| AC-38 | Stack, Seeded, Parse `BMW` | after `ask({"question": Q})`, the last `_ParsedQuestion` line of `calls.jsonl` is read | its `system` contains `millions` | holdout |
| AC-39 | Stack, Seeded, C evaluated | `DELETE /api/portfolio/monitoring/rules/<C>` | status 409 and `detail` == `Rule has <n> live alerts: clear them first.` | holdout |
| AC-40 | Stack, Seeded, Parse `BMW`, Ask the Portfolio tab, date mode Latest | `Q` is asked | the caption reads `<Q> — grouped by Portfolio, as of <S4>` and the page contains neither `Regarding` nor `override this scope` | evaluator |
| AC-41 | the AC-40 answer | the table's header cells are read | the first is `Portfolio`; none contains `_` | evaluator |
| AC-42 | Stack, Seeded, Parse `BMW_M`, Ask the Portfolio tab | `Q` is asked | a header cell reads `Market value (EUR million)` and the line under the table starts `Total: EUR ` and ends ` million`, with two decimals | evaluator |
| AC-43 | Stack, Seeded, Parse `WACI`, Ask the Portfolio tab | `What is our WACI?` is asked | a header cell reads `Weighted avg (tCO2e / EUR M revenue)` | evaluator |
| AC-44 | the frontend's `dimensionLabel` | called with each id of section 11 and with `my_dim` | the labels of section 11; `my_dim` → `My dim` | unit |
| AC-45 | Stack, Seeded, C evaluated, then `clear-alerts` with `{"status": "false_positive", "reason": "wrong threshold"}` | `DELETE /api/portfolio/monitoring/rules/<C>` | status 204 | holdout |
| AC-46 | after AC-45 | `GET /api/portfolio/monitoring/rules` | no rule has C's `rule_id` | holdout |
| AC-47 | after AC-45 | `GET /api/portfolio/monitoring/alerts` | `n` alerts still carry C's `rule_id`, all with status `false_positive` | holdout |
| AC-48 | Stack, Seeded | `DELETE /api/portfolio/monitoring/rules/rule_nope` | status 404, `detail` == `Unknown rule rule_nope` | holdout |
| AC-49 | Stack, Seeded, C evaluated | `POST .../rules/<C>/clear-alerts` with `{"status": "false_positive", "reason": "wrong threshold"}` | status 200, body == `{"cleared": n}` | holdout |
| AC-50 | after AC-49 | `GET /api/portfolio/monitoring/alerts?status=open` | no alert carries C's `rule_id` | holdout |
| AC-51 | after AC-49, for one of C's alerts | `store.list_alert_events(<its scope_id>)` is read | its `alert_raised` event is unchanged, and exactly one `status_changed` event for it was appended, with `status` `false_positive`, `reason` `wrong threshold` and `decided_by` the caller's name | holdout |
| AC-52 | after AC-49 | the same `clear-alerts` call again | body == `{"cleared": 0}` | holdout |
| AC-53 | Stack, Seeded, C evaluated | `clear-alerts` with `{"status": "acknowledged"}` | status 422; C's alerts are still `open` | holdout |
| AC-54 | Stack, Seeded, C evaluated, one of C's alerts moved to `acknowledged` and one to `escalated` | `clear-alerts` with `{"status": "resolved"}` | body == `{"cleared": n}` | holdout |
| AC-55 | Stack, Seeded, C evaluated, Monitoring & Alerts tab | `Delete` on C's row is clicked and the dialog accepted | the page shows `Rule has <n> live alerts: clear them first.` and C's row is still listed | evaluator |
| AC-56 | the AC-55 page; `Clear alerts` → `False positive` done | `Delete` is clicked and accepted, then the status filter `all` is chosen | C's row is gone and the `Rule` cell of each of its `n` alerts reads `Deleted rule` | evaluator |
| AC-57 | Stack, Seeded, C evaluated, and a second rule C2 (C's body, name `Other`) evaluated | `clear-alerts` for C | the number of open alerts carrying C2's `rule_id` is unchanged | holdout |
| AC-58 | Stack, Seeded, rule C stored | `POST /api/portfolio/monitoring/rules` with C's full body, the same `rule_id` and `created_at`, `"enabled": false` | `GET .../rules` has exactly one rule with that `rule_id`, `enabled` false (must not change) | holdout |
| AC-59 | after AC-58, no alert stored | `POST /api/portfolio/monitoring/evaluate-now` | `threshold_alerts_raised` == 0 (must not change) | holdout |
| AC-60 | the test client of `backend/tests/test_api_ask.py` signed in as a viewer; one rule and one `plan_ready` report stored | `DELETE` the rule, `clear-alerts` on it, `DELETE /api/reports/<id>` | each answers 403; the rule and the report are still stored | unit |
| AC-61 | Stack, Seeded, C stored, Monitoring & Alerts tab | `Disable` on C's row is clicked, then the page is reloaded | C's `Enabled` cell reads `no` and its button reads `Enable` | evaluator |
| AC-62 | Stack, Seeded, C stored (threshold 0) | `Edit` on C's row, `Threshold (%)` set to 10, `Save rule` clicked | the rules table still has one row for C, its condition reads `Weight of one company > 10%`, and `GET .../rules` shows `threshold_value` 0.1 with C's `rule_id` | evaluator |
| AC-63 | Stack, Seeded, C evaluated | the alerts table is read | the `Scope` cell of each of C's alerts reads `<company id> · across Core Equity Europe` | evaluator |
| AC-64 | the AC-63 table | `Observed` and `Threshold` of one of C's alerts are read | both end with `%`; `Threshold` reads `0%`; `Observed` equals the alert's `observed_value` × 100 with at most 2 decimals | evaluator |
| AC-65 | Stack, Seeded, C evaluated, Monitoring & Alerts tab | `Clear alerts` → `False positive` on C's row | under the filter `open` none of C's alerts is listed; under `false positive` all `n` are | evaluator |
| AC-66 | Stack, Seeded, rule A stored | the rules table is read | A's row reads Type `Portfolio aggregate (WACI-style)`, Condition `Carbon intensity > 50 tCO2e / EUR M revenue`, Scope `Core Equity Europe` | evaluator |
| AC-67 | the AC-66 row | its text is searched | it contains none of `portfolio_aggregate_threshold`, `climate_carbon_intensity`, ` gt ` | evaluator |
| AC-68 | Stack, Seeded, rule A with `"portfolio_ids": []` stored | the rules table is read | its Scope reads `All portfolios` | evaluator |
| AC-69 | Stack, Seeded, rule A with `"threshold_value": 0` stored and evaluated (it raises an alert for `core_equity_europe`) | the alerts table is read | that alert's `Scope` reads `Core Equity Europe`, its `Rule` reads `Carbon cap`, its `Breach type` reads `No earlier breach to compare`, its `Threshold` reads `0` | evaluator |
| AC-70 | the AC-69 page | the page text is searched | it contains neither `portfolio__` nor `Unknown` | evaluator |
| AC-71 | the frontend's percent function of section 10 | called with 0.05, 0.0712, 0.125, 0.07, 1 | `5%`, `7.12%`, `12.5%`, `7%`, `100%` | unit |
| AC-72 | the frontend's breach-type label of section 10 | called for `unknown` on a `news_controversy` alert; for `holdings_caused`, `data_caused`, `mixed` | `—`; `Holdings-caused`, `Data-caused`, `Mixed` (the last three must not change) | unit |
| AC-73 | Stack, Seeded | `#/portfolio-monitoring` is opened | the `Monitoring & Alerts` tab has `aria-pressed="true"` and the selection pane is shown | evaluator |
| AC-74 | Stack, Seeded | `#/portfolio-monitoring/dashboards`, `#/portfolio-monitoring/pivot` and `#/portfolio-monitoring/ask` are opened in turn | the pressed tab is `Dashboards (Superset)`, `Dashboards (Superset)`, `Ask the Portfolio` (must not change) | evaluator |
| AC-75 | Stack with `ARP_SUPERSET_PASSWORD` unset (`GET /api/bi/dashboards` answers 503), Company Profiles tab | the "Profile dashboard" card is read | it shows `Dashboards are not set up on this server. Ask your administrator.`, has no element with `role="alert"`, and does not contain `could not be loaded` | evaluator |

### Slice 2: the rest (defects 2, 3, 4, 7, 8, 6, 12)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-76 | Stack; `model/ReportPlan.json` holds a valid plan with `"delay_seconds": 5`; a report request filled in on Presentations & Reports | `Draft content plan` is clicked | within 2 s a `role="status"` line reads `Drafting the content plan… 0:0<s> elapsed. This can take a few minutes; keep this page open.` and the button reads `Drafting…` and is disabled | evaluator |
| AC-77 | the AC-76 page | the line is read again 2 s later, and once the plan is shown | the elapsed time is larger; after the plan is shown the line is gone | evaluator |
| AC-78 | the frontend's `elapsedLabel` | called with 0, 42, 196, 3600 | `0:00`, `0:42`, `3:16`, `60:00` | unit |
| AC-79 | Stack; a report R with status `plan_ready` | `DELETE /api/reports/R` | status 204 | holdout |
| AC-80 | after AC-79 | `GET /api/reports/R`, `GET /api/reports`, and the folder `ReportingStore.report_dir("R")` are checked | 404; R is not listed; the folder does not exist | holdout |
| AC-81 | Stack; reports with status `storyline_ready` and `failed` | `DELETE` each | both 204 | holdout |
| AC-82 | Stack; a report R with status `completed` | `DELETE /api/reports/R` | status 409, `detail` == `Only an unfinished report can be discarded (status: completed).` | holdout |
| AC-83 | after AC-82 | `GET /api/reports` | R is still listed with status `completed` and its folder still holds `manifest.json` | holdout |
| AC-84 | Stack; reports with status `planning` and `rendering` | `DELETE` each | both 409 with their status in the `detail`; both still listed | holdout |
| AC-85 | Stack | `DELETE /api/reports/rpt_000000000000` (not stored) | status 404 and no folder of that name exists afterwards | holdout |
| AC-86 | Stack; three reports saved with `created_at` `2026-11-01T10:00:00`, `2026-11-03T10:00:00`, `2026-11-02T10:00:00` and ids `rpt_c…`, `rpt_a…`, `rpt_b…` | `GET /api/reports` | their order is 3 Nov, 2 Nov, 1 Nov | holdout |
| AC-87 | Stack; a `plan_ready` report on Presentations & Reports | its row in "Previous reports" is read, then `Open` is clicked | the row shows `Open` and `Discard`; after the click the "Review & render" section shows its plan | evaluator |
| AC-88 | the AC-87 page with the report open | `Discard` is clicked and the dialog accepted | the row is gone, the "Review & render" section is gone, and `GET /api/reports` no longer lists it | evaluator |
| AC-89 | Stack, an approver, `model/QuotedPairs.json` holds a valid answer with `"delay_seconds": 5` | one `.docx` is chosen under "Answer library" and `Import past responses` clicked | within 2 s a `role="status"` line reads `Importing 1 file… 0:0<s> elapsed. This can take a few minutes; keep this page open.` | evaluator |
| AC-90 | the AC-89 import has finished with response `{"imported": i, "dropped": []}` | the page is read | a visible `role="status"` line (not inside `#announcer`) reads `Imported <i> entries, dropped 0`; it is still there 10 s later | evaluator |
| AC-91 | the frontend's import-progress text of section 3 | called for 1 file at 5 s and 2 files at 65 s | `Importing 1 file… 0:05 elapsed. This can take a few minutes; keep this page open.` and `Importing 2 files… 1:05 elapsed. This can take a few minutes; keep this page open.` | unit |
| AC-92 | Stack, Seeded; `H` without its `Currency` column | upload it for `typo_fund` as of `S4` | status 422 with `message` `file rejected` | holdout |
| AC-93 | after AC-92 | `GET /api/feeds` | no row has `source_id` `typo_fund` | holdout |
| AC-94 | after AC-92 | `GET /api/issues` | no issue has `subject` `typo_fund` | holdout |
| AC-95 | after AC-92 | `store.list_governance_events()` is read | no `load_recorded` event has `source_id` `typo_fund` | holdout |
| AC-96 | Stack, Seeded; a `load_recorded` event `{kind: "holdings", source_id: "ghost_fund", month: <S4's month>, status: "failed", content_hash: "", detail: "4 row errors"}` appended to the governance log | `GET /api/feeds` and `GET /api/issues` | neither has a row or issue for `ghost_fund` | holdout |
| AC-97 | Stack, Seeded; `H` uploaded for `acme_fund` as of `S4` (ok), then `H` without `Currency` uploaded for `acme_fund` | `GET /api/feeds` and `GET /api/issues` | the `acme_fund` row has `last_load.status` `failed`; an issue titled `Portfolio holdings · acme_fund: last load failed` with severity `block` exists (must not change) | holdout |
| AC-98 | Stack, Seeded; `H` without `Currency` uploaded for `core_equity_europe` (a portfolio with no holder config) | `GET /api/feeds` | the `core_equity_europe` row has `last_load.status` `failed` (must not change) | holdout |
| AC-99 | Stack, Seeded | `GET /api/feeds` | one `holdings` row per demo portfolio, each with `stale` false (must not change) | holdout |
| AC-100 | Stack; a security master (the template of `GET /api/security-master/template`, one row: issuer `iss_acme`, ISIN `X`) uploaded; `H` uploaded for `acme_fund` as of `S4` | `POST /api/portfolio/esg/upload`, month of `S4`, the ESG template (`GET /api/portfolio/esg/template`) with one valid row for `company_id` `iss_acme` | status 200, `status` `written`, `rows` 1 | holdout |
| AC-101 | the AC-100 Given | the same upload with `company_id` `nope` | status 422 and an error with message `unknown company_id 'nope'` (must not change) | holdout |
| AC-102 | Stack, Seeded | the ESG upload with one valid row for `company_id` `bmw` | status 200, `status` `written` (must not change) | holdout |
| AC-103 | Stack, Seeded; `H` with decimal commas (market value `1000,50`, weight `100,0`, as a semicolon-separated CSV) | upload for `acme_fund` as of `S4` with form field `decimal` = `,` | status 200, `status` `written`, and the stored snapshot's one holding has `market_value` 1000.5 | holdout |
| AC-104 | the AC-103 file | the same upload without the `decimal` field | status 422 (must not change) | holdout |
| AC-105 | Stack, Seeded | `GET /api/holdings/holders` | 4 rows, one per demo portfolio, each with `holder_id` = the portfolio id, `kind` `portfolio`, `name` = the portfolio's name, `source` null, `as_of` == `S4`, `stale` false, `last_pull_at` null, `last_error` null | holdout |
| AC-106 | after AC-105 | `store.list_holders()` is read | empty | holdout |
| AC-107 | Stack, Seeded; `H` uploaded for `core_equity_europe` as of `N` | `GET /api/holdings/holders` | exactly one row has `holder_id` `core_equity_europe`; its `source` is `file`; it comes before the three rows whose `source` is null | holdout |
| AC-108 | Stack, Seeded, no security master | `GET /api/security-master/unmatched` and `GET /api/issues` | no unmatched security; no issue with `source` `security_master` (must not change) | holdout |
| AC-109 | Stack, Seeded, Holdings Intake tab | the holder table is read | 4 rows named after the demo portfolios, each with Source `—`, As of `S4` and no `Pull now` button | evaluator |
| AC-110 | Stack, Seeded, Holdings Intake tab | `H` is uploaded for `acme_fund` as of `S4` through the form, without reloading | the selection pane lists `acme_fund` | evaluator |
| AC-111 | the AC-110 page, monthly-run month = month of `S4` | the "Monthly run" table is read, without reloading | it has a row `Holdings acme_fund` | evaluator |
| AC-112 | Stack, Seeded, Holdings Intake tab, monthly-run month `M` whose ESG row does not read `ok` | a valid ESG file for month `M` is uploaded through the form, without reloading | the ESG row of the "Monthly run" table reads `ok` | evaluator |
| AC-113 | Stack, Seeded; `H` without its `Weight (%)` and `Currency` columns | upload for `acme_fund` as of `S4` | status 422; the errors with `row` null are exactly `{"row": null, "column": "Weight (%)", "message": "missing required column"}` and `{"row": null, "column": "Currency", "message": "missing required column"}` | holdout |
| AC-114 | the AC-113 upload made through the Holdings Intake form | the error list is read | it has the lines `missing required column: Weight (%)` and `missing required column: Currency` | evaluator |
| AC-115 | the frontend's `rowErrorText` | called with `{row: null, column: "Weight (%)", message: "missing required column"}`, `{row: null, column: "weight", message: "weights sum to 1%, not 100% ± 0.5"}`, `{row: null, column: null, message: "missing header"}` | `missing required column: Weight (%)`; `weights sum to 1%, not 100% ± 0.5`; `missing header` | unit |
| AC-116 | Stack, Seeded; `H` with weight `1` | upload for `acme_fund` as of `S4` with form field `weight_unit` = `fraction` | status 200 and the stored holding has `weight_pct` 100 | holdout |
| AC-117 | the AC-116 file | the same upload without `weight_unit` | status 422 with an error whose message starts `weights sum to 1%` (must not change) | holdout |
| AC-118 | Stack, Seeded | upload `H` with `decimal` = `;`, and again with `weight_unit` = `bps` | both 422; no snapshot is stored for the holder | holdout |
| AC-119 | Stack, Holdings Intake tab | the upload form is read | selects `Decimal separator` (options `Point (1,234.56)`, `Comma (1.234,56)`) and `Weights are` (options `Percent (5 = 5%)`, `Fraction (0.05 = 5%)`), with Point and Percent chosen | evaluator |
| AC-120 | Stack, Seeded; `H` uploaded for `acme_fund` as of `N` | `POST /api/decision/datasets/from-source` with `{"source": "portfolio_snapshot", "portfolio_ids": ["core_equity_europe"]}` | `name` == `Portfolio holdings as of <S4>` and `as_of` == `S4` | holdout |
| AC-121 | the AC-120 Given | the same call without `portfolio_ids` | `name` == `Portfolio holdings as of <S4> to <N>` and `as_of` == `N` | holdout |
| AC-122 | Stack, Seeded | the same call without `portfolio_ids`; and with `"as_of": S2` | `name` == `Portfolio holdings as of <S4>`, `as_of` == `S4`; and `Portfolio holdings as of <S2>`, `as_of` == `S2` (must not change) | holdout |
| AC-123 | Stack, Seeded; the AC-120 call made once before and once after `H` is uploaded for `acme_fund` as of `N` | `row_count` and `preview` of the two answers are compared | equal | holdout |
| AC-124 | the AC-120 Given | `POST /api/portfolio/universe` with `{"portfolio_ids": ["core_equity_europe"]}` | `as_of` == `S4` and the saved file's name starts `holdings_core_equity_europe_<S4>_` | holdout |
| AC-125 | the AC-120 Given | `POST /api/portfolio/universe` with `{}` | `as_of` == `N` and the saved file's name starts `holdings_all_<S4>_to_<N>_` | holdout |
| AC-126 | Stack, Seeded, no security master, Security Master page | the page is read | it shows `No holdings have been loaded through Holdings Intake yet.` and does not contain `Every held security is matched.` | evaluator |
| AC-127 | the AC-100 Given (master and matching holding loaded), Security Master page | the unmatched table is read | its empty row reads `Every held security is matched.` (must not change) | evaluator |
| AC-128 | Stack, Seeded, no monthly run yet | `GET /api/portfolio/monthly-run/last` | status 200, body `null` | holdout |
| AC-129 | Stack, Seeded; a month `M` for which `GET /api/portfolio/monthly-run/status` has no `blocked_reasons` (an ESG upload for `M` first, if needed) | `POST /api/portfolio/monthly-run` with `{"month": M}` answers `{"status": "ran", "alerts": a, "triggers": t}`, then `GET .../monthly-run/last` | `month` == `M`, `alerts` == `a`, `triggers` == `t`, `at` is an ISO date-time of the run | holdout |
| AC-130 | Stack, Seeded; a month for which `monthly-run/status` has `blocked_reasons` | `POST /api/portfolio/monthly-run` for it, then `GET .../monthly-run/last` | the run answers `status` `blocked`; `last` is still `null` | holdout |
| AC-131 | after AC-129, the Home hub's "Monthly monitoring" process | its steps are read | `Monitoring & Alerts` reads `Done · <day month of the run>` | evaluator |
| AC-132 | Stack, Seeded, the Home hub | the steps `Holdings Intake` (Monthly monitoring) and `Map holdings` (Map securities to issuers) are read | both start `Done · ` | evaluator |
| AC-133 | Stack, Seeded; the AC-100 security master uploaded | the step `Load security master` is read; then a master file that is rejected is uploaded and the hub reloaded | first `Done · <day month>`; then `Last run failed` | evaluator |
| AC-134 | Stack, empty portfolio store, the Home hub | the four steps of AC-131 to AC-133 are read | each reads `No runs yet` (must not change) | evaluator |
| AC-135 | the repo at the PR head | `npm test` in `frontend` with `tests/subTabs.test.ts`, `tests/holdings.test.ts`, `tests/workspaceCard.test.ts` and `tests/processes.test.ts` unchanged from `main` | exit code 0 | unit |
| AC-136 | Stack; the same file `companies.csv` uploaded twice to `POST /api/decision/datasets`, 2 s apart | `GET /api/decision/datasets` | two entries named `companies.csv`, each with an ISO date-time `created_at`, and the two differ | holdout |
| AC-137 | the AC-136 Given, Decision Studio's Data table | the table is read | it has a column `Added`, and the two `companies.csv` rows show different values in it | evaluator |
| AC-138 | the AC-136 Given, the Movement dropdown | its options are read | the two uploads read `companies.csv · added <their Added text>` and differ | evaluator |
| AC-139 | Stack, empty portfolio store, Risk Monitoring | `Seed demo dataset` is clicked and the portfolio list appears | the pane shows `Seeded <N> companies, 4 portfolios, <K> holding rows.` with the numbers of the seed response, still shown 10 s later, and not after a reload | evaluator |
| AC-140 | the frontend's `findingText` | called with `{stage: "qa", rule: "invalid_edit", slot: "number_1", message: "edit changes nothing"}` | null (not listed) | unit |
| AC-141 | the frontend's `findingText` | called with `{stage: "qa", rule: "applied", message: "Shortened the headline"}`; `{stage: "fit", rule: "slot_dropped", slot: "number_1", message: "Slot 'number_1' does not exist in a/b; its content was dropped."}`; `{stage: "lint", rule: "exclamation", slot: "headline", message: "Remove the exclamation mark."}`; `{stage: "new", rule: "x", message: "m"}` | `Visual check: adjusted. Shortened the headline`; `Layout: some content did not fit this slide and was left out.`; `Wording: Remove the exclamation mark.`; `Check: m` | unit |
| AC-142 | a house deck result page built in a browser test from findings `[invalid_edit on slide 2, exclamation on slide 3]` (the `/findings` call answered by the test) | the Findings list is read | it lists slide 3 only, with `Wording: Remove the exclamation mark.`, and the page contains neither `qa/invalid_edit` nor `[headline]` | unit |
| AC-143 | Stack | `#/valueChain/exposure`, `#/valueChain/shock`, `#/valueChain/tree` and `#/valueChain/footprint` are opened in turn | each shows the heading `Value Chain Explorer` and the search box; none shows a heading `exposure`, `shock`, `tree` or `footprint` | evaluator |
| AC-144 | Stack | `#/valueChain/portfolio` is opened | the heading reads `Portfolio` (must not change) | evaluator |
| AC-145 | the repo at the PR head | `cd backend && python scripts/export_openapi.py --check`, then `cd frontend && npm run gen:api && git diff --exit-code src/api` | both exit 0 | unit |

Must not change: a request with only `question` (AC-4, AC-24, AC-35); `spec_name` from the typed question
(AC-30); replacing a rule by `rule_id` and skipping disabled rules (AC-58, AC-59); the known breach-type
labels (AC-72); named and legacy sub-tabs (AC-74); completed and in-flight reports (AC-82 to AC-84); failed
loads for holders and portfolios that exist, and the demo feed rows (AC-97 to AC-99); ESG id checks
(AC-101, AC-102); the default decimal and weight unit (AC-104, AC-117); Security Master and Issues for the
demo seed (AC-108, AC-127); holdings tables with one date (AC-122, AC-123); idle hub steps (AC-134); the
tests named above (AC-135); the Portfolio value-chain heading (AC-144).
