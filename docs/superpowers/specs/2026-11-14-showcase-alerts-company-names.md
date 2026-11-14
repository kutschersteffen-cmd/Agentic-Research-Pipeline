# Alerts show company names, and cash lines never alert

Slug: showcase-alerts-company-names

Risk: `risk:normal` for the implementing PR. Size S, one PR.

Status: **approved by the owner on 14 Nov 2026** (buttons in the spec session, after the spec-critic read `Ready for approval`).

## Why

On the showcase data (seven imported portfolios) a concentration rule such as "single name > 0.5%" raises
36 alerts. Risk Monitoring, Monitoring, Alerts then shows raw ids where a reader expects a company:

- the `Scope` cell reads `isin_DE0005140008 · across all portfolios`
  (`frontend/src/lib/monitoringLabels.ts`, `alertScope`, from `alert.company_id`);
- the `Rationale` cell repeats the id, because `_evaluate_concentration_threshold` builds it as
  `f"{rule.name}: {company_id} = …"` (`backend/arp/portfolio/monitoring/evaluator.py:207`).

The names are in the store (`DEUTSCHE BANK AG` for `isin_DE0005140008`). The owner asked on 14 Nov 2026 for
the table to show the name, with the id kept as secondary text.

The same portfolios hold 2 to 26 currency lines each (`_CURRENCYUSD` and so on; companies such as
`isin__CURRENCYUSD`). `constituent_import.py` loads them as holdings and the concentration check does not skip
them, so a low enough threshold can alert on "US Dollar". None fires at 0.5% today; the owner wants it
impossible. `index_universe.py` already drops asset class `cash` the same way.

## Goals

1. Every alert that names a company shows the company's name in `Scope`, with the id after it in smaller muted
   monospace text (the pattern of `BackgroundAgents.tsx:419`).
2. A concentration alert's `Rationale` names the company, for alerts raised before and after this change.
3. A cash or currency holding never raises a concentration alert.

## Non-goals

- Other screens (company profile, Overview, Ask the Portfolio) and the CLI.
- Portfolio ids in the rationale of a portfolio-aggregate alert, and the raw comparator (`gt`) in rationales.
- Cash lines in field-threshold or portfolio-aggregate rules, and re-importing the showcase data.
- Amendment A of `showcase-portfolio-data` (written-off list, revenue-share cap): different files, no overlap.

## Anti-goals

- Any concentration weight changes. Weight stays "share of all holdings, cash included" (the rationale says
  "of NAV"), so the `Observed` value of every non-cash alert is the same as before.
- The stored event log is rewritten. Alerts already raised stay as they were stored; the name is added on read.

## Approaches considered

1. **`company_name` on the alert, filled by the server on read (chosen).** `GET /api/portfolio/monitoring/alerts`
   looks each alert's `company_id` up in the company directory (`portfolio_directories`) and sets
   `company_name`; the same read swaps the id for the name in the rationale of an alert stored with the old
   text. New alerts store the name in their rationale. Correct for old and new alerts, one lookup per request.
   Costs an API contract regeneration.
2. **Client-side lookup from a companies list.** The Monitoring page loads no company list today; it would need
   one call per company or a new list endpoint, and it cannot fix the stored rationale text. Rejected.
3. **Store `company_name` on the alert when raised.** Wrong for every alert raised before the change, and goes
   stale on a rename. Rejected.

## Design

Backend:

- `Alert` (`backend/arp/schemas/portfolio_monitoring.py`) gains `company_name: str | None = None`. It is never
  written to the event log; the list endpoint fills it.
- `GET /api/portfolio/monitoring/alerts` (in the router, not in `list_alerts`, which also feeds the CLI and the
  duplicate checks) sets `company_name` to the directory name of `company_id` for every
  alert that has one, and leaves it `null` when the company is not in the directory or the alert has no company.
- New concentration alerts store the rationale
  `"{rule.name}: {company name} = {weight:.2%} of NAV {rule.comparator} {rule.threshold_value:.2%}"`, falling back
  to the id when the company has no directory entry.
- On read, a concentration alert (has `company_id`, breach type `holdings_caused`) whose rationale starts with
  `"{rule name}: {company_id} = "` gets that `company_id` replaced by `company_name`. Only that prefix; nothing
  else in any rationale changes, and the stored event is untouched.
- `_evaluate_concentration_threshold` skips every company whose securities, among the holdings the rule
  evaluates, are all cash or currency lines: `asset_class == "cash"`, or `security_id`/`isin` starting with
  `_CURRENCY`. The total the weight is
  divided by stays the sum over all holdings, cash included.
- Regenerate the contract: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`.

Frontend (`MonitoringAlerts.tsx`, `monitoringLabels.ts`):

- A new pure function `alertScopeParts(alert, rules, portfolios)` in `monitoringLabels.ts` returns
  `{ name: string | null, id: string | null, suffix: string }`:
  - portfolio alert: `{ name: null, id: null, suffix: <portfolio name> }` (today's text);
  - company alert without `company_name`: `{ name: null, id: null, suffix: <today's alertScope text> }`;
  - company alert with `company_name`: `{ name: company_name, id: company_id, suffix }`, where `suffix` is
    ` · across <portfolio names>` or ` · across all portfolios` for a concentration alert whose rule exists, and
    `""` otherwise (field-threshold, news, or a deleted rule).
- `alertScope` stays and returns `name + " " + id + suffix` when there is a name, else `suffix`, so its existing
  tests pass unchanged.
- The `Scope` cell renders `name`, a space, `id` in `<span className="mono muted">`, then `suffix`; without a
  name, just `suffix`.
- `Rationale` shows the text the API returns.

Risk label: `risk:normal`. The steward table puts "portfolio weights or index maths" in `risk:high`. This change
computes no weight differently: it drops some company rows from the alert loop and keeps the denominator, which
AC-5 pins. If the builder finds the cash skip cannot be done without changing the denominator, that is a
`risk:high` change outside this spec: stop and raise `factory:blocked`.

## Other specs this changes

`2026-11-12-showcase-portfolio-fixes.md` AC-71 (`Scope` reads `<company id> · across Core Equity Europe`) is
superseded by AC-20 here whenever the company is in the directory; its hidden test is updated in the holdout repo
with this spec's tests. Its AC-71 still holds for a company with no directory entry (AC-16).

## Left to the builder

How cash companies are found, and the exact code of the read-time fill.

## Acceptance

Fixture `F` for the `holdout` rows:

- companies `isin_DE0005140008` named `DEUTSCHE BANK AG`, `isin__CURRENCYUSD` named `US Dollar`, `cash_eur`
  named `Euro Cash`;
- securities (all currency `EUR`): `DE0005140008`, asset class `equity`, company `isin_DE0005140008`;
  `_CURRENCYUSD`, asset class `other`, company `isin__CURRENCYUSD`; `CASHEUR`, asset class `cash`, company
  `cash_eur`;
- one portfolio `p1` named `Core Equity Europe` holding on `2026-11-02` `DE0005140008` 600 000 EUR,
  `_CURRENCYUSD` 300 000 EUR, `CASHEUR` 100 000 EUR;
- rule `R`: concentration, name `Single name > 0.5%`, comparator `gt`, threshold `0.005`, no portfolio ids.

"Evaluated" means `POST /api/portfolio/monitoring/evaluate-now` (it uses the latest snapshot, `2026-11-02`).
"The list" means the response of `GET /api/portfolio/monitoring/alerts`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | F, R evaluated | the list is read | it holds exactly one alert, with `company_id` `isin_DE0005140008` | holdout |
| AC-2 | F, R evaluated | the list is read | that alert's `company_name` is `DEUTSCHE BANK AG` | holdout |
| AC-3 | F, R evaluated | the list is read | that alert's `rationale` is `Single name > 0.5%: DEUTSCHE BANK AG = 60.00% of NAV gt 0.50%` | holdout |
| AC-4 | F, R evaluated | the list is read | no alert has `company_id` `isin__CURRENCYUSD` or `cash_eur` | holdout |
| AC-5 | F, R evaluated | the list is read | the AC-1 alert's `observed_value` is `0.6` (600 000 of 1 000 000: cash stays in the total) | holdout |
| AC-6 | F, R stored, and an `alert_raised` event stored the old way for scope `isin_DE0005140008` under R (open, `holdings_caused`) with rationale `Single name > 0.5%: isin_DE0005140008 = 60.00% of NAV gt 0.50%` | the list is read | that alert's `rationale` is `Single name > 0.5%: DEUTSCHE BANK AG = 60.00% of NAV gt 0.50%` | holdout |
| AC-7 | as AC-6 | the list is read | that alert's `company_name` is `DEUTSCHE BANK AG` | holdout |
| AC-8 | as AC-6, after the list was read | the scope's stored `alert_raised` event is read from the store | its rationale is still `Single name > 0.5%: isin_DE0005140008 = 60.00% of NAV gt 0.50%` | holdout |
| AC-9 | F, plus an open `holdings_caused` alert stored under R for company `isin_XX0000000000`, which has no directory entry, rationale `Single name > 0.5%: isin_XX0000000000 = 7.00% of NAV gt 0.50%` | the list is read | that alert's `company_name` is `null` | holdout |
| AC-10 | as AC-9 | the list is read | that alert's `rationale` is `Single name > 0.5%: isin_XX0000000000 = 7.00% of NAV gt 0.50%` | holdout |
| AC-11 | F, plus an open `data_caused` field-threshold alert stored for `isin_DE0005140008` with rationale `Carbon cap: climate_carbon_intensity = 80 gt 50` | the list is read | that alert's `company_name` is `DEUTSCHE BANK AG` | holdout |
| AC-12 | as AC-11 | the list is read | that alert's `rationale` is `Carbon cap: climate_carbon_intensity = 80 gt 50` | holdout |
| AC-13 | `alertScopeParts`, a concentration alert (`company_id` `bmw`, `company_name` `BMW AG`, `holdings_caused`) whose rule is scoped to `Core Equity Europe` | called | `{ name: "BMW AG", id: "bmw", suffix: " · across Core Equity Europe" }` | unit |
| AC-14 | as AC-13, the rule scoped to no portfolios | called | `{ name: "BMW AG", id: "bmw", suffix: " · across all portfolios" }` | unit |
| AC-15 | as AC-13, the rule deleted (not in the rules list) | called | `{ name: "BMW AG", id: "bmw", suffix: "" }` | unit |
| AC-16 | as AC-13 without `company_name` | called | `{ name: null, id: null, suffix: "bmw · across Core Equity Europe" }` | unit |
| AC-17 | a field-threshold alert (`scope_id` and `company_id` `bmw`, `company_name` `BMW AG`, `data_caused`) | `alertScopeParts` called | `{ name: "BMW AG", id: "bmw", suffix: "" }` | unit |
| AC-18 | a `news_controversy` alert (`scope_id` and `company_id` `bmw`, `company_name` `BMW AG`, breach type `unknown`) | `alertScopeParts` called | `{ name: "BMW AG", id: "bmw", suffix: "" }` | unit |
| AC-19 | a portfolio-aggregate alert, `scope_id` `portfolio__core_equity_europe` | `alertScopeParts` called | `{ name: null, id: null, suffix: "Core Equity Europe" }` | unit |
| AC-20 | the e2e stack, showcase data loaded (`arp showcase load`), a rule `Single name > 0.5%` (Single-name concentration, `>`, 0.5, all portfolios) created on Risk Monitoring, Monitoring, `Evaluate now` clicked, filter `open` | the Deutsche Bank alert's `Scope` cell is read | it reads `DEUTSCHE BANK AG isin_DE0005140008 · across all portfolios`, with `isin_DE0005140008` in smaller grey monospace | evaluator |
| AC-21 | the AC-20 table | that alert's `Rationale` cell is read | it starts with `Single name > 0.5%: DEUTSCHE BANK AG = ` | evaluator |
| AC-22 | the AC-20 table | every `Scope` cell is read | none starts with `isin_` | evaluator |
| AC-23 | the AC-20 table | every `Scope` and `Rationale` cell is read | none contains `_CURRENCY` | evaluator |

Must not change:

- AC-5: the `Observed` weight of a non-cash company (the total keeps cash).
- AC-8: the stored event log.
- AC-9, AC-10, AC-16: an alert whose company has no directory entry reads exactly as today.
- AC-12, AC-19: field-threshold rationales and portfolio-aggregate scopes.
- The existing tests in `frontend/tests/monitoringLabels.test.ts` and
  `backend/tests/test_portfolio_monitoring_evaluator.py` pass unchanged.
