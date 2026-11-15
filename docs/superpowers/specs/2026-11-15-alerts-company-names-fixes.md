# Alert company names: deleted or renamed rules, and the status-change answer

Slug: alerts-company-names-fixes

Risk: `risk:normal` for the implementing PR (proposed). Size S, one PR. Backend only.

Status: draft, waiting for owner approval.

Parent: [`2026-11-14-showcase-alerts-company-names.md`](2026-11-14-showcase-alerts-company-names.md). Its hidden
tests stay in the regression suite.

## Why

Two gaps the review of the parent spec found, both reproduced on `main` (`b53ad65`):

1. **Deleted or renamed rule.** `with_company_names` (`backend/arp/portfolio/monitoring/evaluator.py:57-71`) only
   swaps the company id in a rationale that starts with `"{rule.name}: {company_id} = "`. It needs the rule to
   still exist under the same name. For an alert whose rule was deleted (`old_prefix` is `None`) or renamed (the
   prefix no longer matches), `company_name` is filled but the `Rationale` keeps the raw id, e.g.
   `Single name > 0.5%: isin_DE0005140008 = 60.00% of NAV gt 0.50%`.
2. **Status-change answer.** `POST /api/portfolio/monitoring/alerts/{scope_id}/{alert_id}/transition`
   (`backend/arp/api/routers/portfolio.py:269-283`) returns the alert straight from `transition_alert`, never
   through `with_company_names`. Its answer has `company_name` `null` and the raw-id rationale. Nobody sees it today
   because the page reloads the list after a status change, but any other client gets a different alert than the
   list shows.

## Goals

1. A concentration alert's `Rationale` names the company whether its rule still exists, was renamed or was deleted.
2. The status-change answer carries the same `company_name` and `rationale` as the list shows for that alert.
3. One shared helper fills both, so the list and the status-change answer cannot drift apart again.

## Non-goals

- Cash or currency alerts that were already open before the parent fix. **Owner decision, 15 Nov 2026
  (button):** they are left alone and nothing is built for them. The showcase database is rebuilt, and the
  `clear-alerts` action already closes them.
- Other screens (company profile, Overview, Ask the Portfolio) and the CLI.
- Any change to the `Alert` schema or its field descriptions, so the OpenAPI document does not change.

## Anti-goals

- The stored event log is rewritten (an anti-goal of the parent spec too). Names are added on read only.
- A `data_caused` (field-threshold) or portfolio-aggregate rationale changes.

## Approaches considered

1. **Swap `: <company_id> = ` without the rule (chosen).** Every concentration rationale is
   `"<rule name>: <company> = <weight> of NAV <comparator> <threshold>"`. The company id sits between the first
   `": "` that is followed by the id and the `" = "` after it, whatever the rule name is or was. So the swap looks
   for the text `": {company_id} = "` in a `holdings_caused` rationale and needs no rule at all.
2. **Keep the rule-name prefix, and look deleted rules up in the event log.** The rule's old name is not stored
   anywhere once it is deleted or renamed. Rejected.
3. **Store the name in old events (migration).** Rewrites the event log, an anti-goal. Rejected.

For the status-change answer there is one sensible way: run the alert it returns through the same helper the list
uses. The list and the transition route both call one function that loads the company directory and fills the
names, so neither can skip a step the other does.

## Design

- `with_company_names` no longer takes `rules`. For each alert whose `company_id` is in the directory it sets
  `company_name` (as today). When the alert's `breach_type` is `holdings_caused` and its rationale contains
  `": {company_id} = "`, the **first** occurrence of that text becomes `": {company_name} = "`. Nothing else in
  the rationale changes: the rule name stored in it stays as it was stored (a renamed rule keeps its old name in an
  old alert's rationale). Alerts of other breach types, and alerts whose company is not in the directory, are
  returned unchanged (as today).
- One shared helper (name and place are the builder's call; the router or `evaluator.py`) takes the store and a
  list of alerts, loads the company directory once, and returns `with_company_names(...)`. Both
  `GET /api/portfolio/monitoring/alerts` and the transition route return through it. The transition route keeps
  its 404 for an unknown alert.
- `transition_alert` keeps its signature and behaviour; the CLI and `clear_rule_alerts` are untouched.
- Tests: extend `backend/tests/test_alert_company_names.py`. Its existing tests pass unchanged.

## Other specs this changes

Parent design line "On read, a concentration alert ... whose rationale starts with `"{rule name}: {company_id} = "`
gets that `company_id` replaced" is replaced by the rule above. No parent AC row is retired:

- Parent AC-6, AC-7 (old rationale named on read, rule stored) still hold; AC-1 to AC-4 here extend them to a
  deleted and a renamed rule.
- Parent AC-8 (stored event log untouched) still holds; AC-17 and AC-18 here add the same for a status change.
- Parent AC-9, AC-10 (company not in the directory) still hold; AC-10 and AC-11 here pin them for the
  status-change answer.
- Parent AC-11, AC-12 (field-threshold alert: name filled, rationale kept) still hold; AC-13 and AC-14 here add the
  case where such a rationale happens to contain `: <company_id> = `.

## Left to the builder

The helper's name and module, and the exact code of the swap.

## Acceptance

All rows drive the app started by `backend/scripts/e2e_stack.sh up`.

- Fixture `F` is the parent spec's fixture `F` (companies `isin_DE0005140008` `DEUTSCHE BANK AG`,
  `isin__CURRENCYUSD` `US Dollar`, `cash_eur` `Euro Cash`; portfolio `p1` named `Core Equity Europe`; rule `R`
  named `Single name > 0.5%`, concentration, `gt`, `0.005`, no portfolio ids), built the way the parent's holdout
  tests build it. Every row starts from F with no alerts stored.
- "Stored the old way" for scope `S`: one JSON line appended to `<ARP_PORTFOLIOS_DIR>/monitoring/S/events.jsonl` of
  the running stack (the file store the alert endpoints read; `<ARP_PORTFOLIOS_DIR>` is `ARP_PORTFOLIOS_DIR` if the
  stack sets it, else `<repo root>/portfolios`, the `portfolios_dir` default in `arp/config.py:102`):
  `{"event_type": "alert_raised", "at": "2026-11-02T00:00:00+00:00", "alert": {...}}`, where `alert` is an `Alert`
  in JSON without a `company_name` key, `status` `open`, `category` `threshold_breach`, `scope_id` `S`, and the
  `company_id`, `rule_id`, `breach_type` and `rationale` the row names. It always carries an explicit `alert_id`
  `alrt_ac<n>`, where `<n>` is the ID of the row whose Given stores it (AC-1's is `alrt_ac1`; a row "as AC-1" uses
  the same alert), and `triggered_at` `2026-11-02T00:00:00+00:00`. "That alert" is the list entry with that
  `alert_id`. Unless a row says otherwise, `S` and
  `company_id` are `isin_DE0005140008`, `rule_id` is R's and `breach_type` is `holdings_caused`.
- `OLD` is `Single name > 0.5%: isin_DE0005140008 = 60.00% of NAV gt 0.50%`; `NEW` is
  `Single name > 0.5%: DEUTSCHE BANK AG = 60.00% of NAV gt 0.50%`.
- "The list" is the response of `GET /api/portfolio/monitoring/alerts`. "A status change" is
  `POST /api/portfolio/monitoring/alerts/{scope_id}/{alert_id}/transition` with body `{"status": "acknowledged"}`;
  "its answer" is that response.
- "Evaluated" is `POST /api/portfolio/monitoring/evaluate-now`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | F; an alert stored the old way with rationale `OLD` and `rule_id` `rule_gone`, which no stored rule has | the list is read | that alert's `rationale` is `NEW` | holdout |
| AC-2 | as AC-1 | the list is read | that alert's `company_name` is `DEUTSCHE BANK AG` | holdout |
| AC-3 | F, then R posted again to `POST /api/portfolio/monitoring/rules` with the same `rule_id` and name `Top holding cap`; an alert stored the old way with rationale `OLD` | the list is read | that alert's `rationale` is `NEW` (the old rule name stays in it) | holdout |
| AC-4 | F; an alert stored the old way with rationale `isin_DE0005140008 cap: isin_DE0005140008 = 60.00% of NAV gt 0.50%` | the list is read | that alert's `rationale` is `isin_DE0005140008 cap: DEUTSCHE BANK AG = 60.00% of NAV gt 0.50%` | holdout |
| AC-5 | F, R evaluated | a status change on the Deutsche Bank alert | 200; its answer's `status` is `acknowledged` | holdout |
| AC-6 | as AC-5 | a status change on the Deutsche Bank alert | its answer's `company_name` is `DEUTSCHE BANK AG` | holdout |
| AC-7 | as AC-5 | a status change on the Deutsche Bank alert | its answer's `rationale` is `NEW` | holdout |
| AC-8 | as AC-1 | a status change on that alert | its answer's `rationale` is `NEW` | holdout |
| AC-9 | as AC-1 | a status change on that alert | its answer's `company_name` is `DEUTSCHE BANK AG` | holdout |
| AC-10 | F; an alert stored the old way for `S` and `company_id` `isin_XX0000000000` (not in the directory) with rationale `Single name > 0.5%: isin_XX0000000000 = 7.00% of NAV gt 0.50%` | a status change on it | its answer's `company_name` is `null` | holdout |
| AC-11 | as AC-10 | a status change on it | its answer's `rationale` is `Single name > 0.5%: isin_XX0000000000 = 7.00% of NAV gt 0.50%` | holdout |
| AC-12 | F, R evaluated, then a status change on the Deutsche Bank alert | the list is read | the alert with the same `alert_id` has the same `status`, `company_name` and `rationale` as the status change's answer | holdout |
| AC-13 | F; an alert stored the old way with `breach_type` `data_caused` and rationale `Carbon cap: isin_DE0005140008 = 80 gt 50` | the list is read | that alert's `rationale` is `Carbon cap: isin_DE0005140008 = 80 gt 50` | holdout |
| AC-14 | as AC-13 | a status change on that alert | its answer's `rationale` is `Carbon cap: isin_DE0005140008 = 80 gt 50` | holdout |
| AC-15 | F; an alert stored the old way for `S` `portfolio__p1`, `portfolio_id` `p1`, no `company_id`, `breach_type` `holdings_caused`, rationale `Avg carbon: p1 = 80 gt 50` | the list is read | that alert's `rationale` is `Avg carbon: p1 = 80 gt 50` | holdout |
| AC-16 | as AC-15 | a status change on that alert | its answer's `rationale` is `Avg carbon: p1 = 80 gt 50` | holdout |
| AC-17 | as AC-1, after a status change on that alert | the `alert_raised` line of `<ARP_PORTFOLIOS_DIR>/monitoring/isin_DE0005140008/events.jsonl` whose `alert.alert_id` is `alrt_ac1` is read | its `alert.rationale` is still `OLD` | holdout |
| AC-18 | as AC-17 | the same line is read | its `alert` has no `company_name` key | holdout |
| AC-19 | F | a status change with `scope_id` `isin_DE0005140008` and `alert_id` `nope` | 404; `detail` is `No alert 'nope' in scope 'isin_DE0005140008'`, as on `main` | holdout |
| AC-20 | the PR branch | `cd backend && python scripts/export_openapi.py` | `frontend/src/api/openapi.json` is byte-identical to `main` | unit |

No `evaluator` rows: nothing on screen changes except the `Rationale` of an alert whose rule was deleted or renamed,
which AC-1 and AC-3 pin through the API the page renders verbatim.

Must not change:

- AC-10, AC-11: an alert whose company has no directory entry reads exactly as today (parent AC-9, AC-10).
- AC-13, AC-14: field-threshold rationales (parent AC-12).
- AC-15, AC-16: portfolio-aggregate rationales.
- AC-17, AC-18: the stored event log (parent AC-8).
- AC-19: the 404 for an unknown alert.
- AC-20: the OpenAPI document.
- The existing tests in `backend/tests/test_alert_company_names.py` and
  `backend/tests/test_portfolio_monitoring_evaluator.py` pass unchanged.
