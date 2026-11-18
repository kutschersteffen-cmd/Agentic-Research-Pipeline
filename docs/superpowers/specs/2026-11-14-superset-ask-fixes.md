# Superset "ask for a chart": fixes from the showcase rehearsal

Slug: superset-ask-fixes

Risk: `risk:normal`. Size S, 1 PR.

Status: **approved by the owner on 14 Nov 2026** (buttons in the spec session, after the spec-critic read
"Ready for approval").

## Why

The showcase rehearsal hit four defects in "ask for a chart" (`arp bi ask|design`, `POST /api/bi/ask|design`):

1. When the model asks a question back ("Which portfolio do you mean?"), ARP reports it as a list of validation
   errors. `DesignResult.clarification_needed` exists for this but is never set.
2. A Superset failure that is not one of ARP's own messages reaches the user as "Superset request failed", or as
   a raw `Superset: [Errno 111] Connection refused`. The user cannot tell "not running" from "wrong password"
   from "not bootstrapped".
3. Asking the same question twice adds a second, identical chart to the `arp-scratch` dashboard.
4. Nobody has checked that the four dashboard templates show rows after `arp showcase load`.

**Showcase constraint.** The bank's JupyterLab has no Superset. There only (2) is visible: asking for a chart must
end in a clear message that Superset is not set up here (AC-10 text, or the existing 503 of AC-17 when
`ARP_SUPERSET_PASSWORD` is unset). Everything else matters only where Superset runs.

## Goals

- (1) A clarification is returned as a question: `clarification_needed` set, `rejected` empty. `rejected` holds only
  validation errors. The CLI prints the question and exits 3; the Superset BI page shows it.
- (2) `_bad_gateway` (`backend/arp/api/routers/bi.py`) answers with fixed texts for "unreachable", "login failed"
  (401/403) and "missing" (404). Never the Superset response body: it may hold hosts, DSNs or secrets.
- (3) A repeated question reuses the chart already on `arp-scratch`, matched by chart title and params.
- (4) One test proves the template views return rows after a showcase-style publish. No code change unless it fails.

## Non-goals

Superset bootstrap, new chart types, planner prompt changes, any UI work beyond the one banner line in (1).
The CLI's operator output on Superset errors (`Superset at <url>: ...` plus the response body, exit 1) stays as it is:
it is for operators, not API clients.

## Approaches

- **(1) Where the question goes.** (a) Only `clarification_needed`, plus a three-line change to the BI page so it
  shows the question. (b) Also copy it into `rejected`, so the page works unchanged. **Owner picked (a)** on
  14 Nov 2026: with (b) API clients see the question twice and `rejected` keeps meaning two things.
- **(2) Where to classify.** (a) In `_bad_gateway`, from the root cause (`e.__cause__ or e`). (b) At each `raise
  BIError` in `service.py`. Picked (a), my call: one place, and every BI endpoint gets the same texts for rules 1 to 3.
- **(3) How to match.** (a) Title and params of the charts already on `arp-scratch`. (b) A hash of the question.
  Intake fixed (a). Consequence: if the model words the title differently the second time, a new chart is added.
  That is accepted.

## Design

### (1) Clarification (`arp/bi/planner.py`, `service.py`, `cli/bi.py`, `SupersetBI.tsx`)

- `plan_from_brief` tells a clarification apart from validation errors. The return shape is the builder's call;
  `service.py` and `arp/bi/eval.py` are its only callers. `eval.py` keeps its behaviour: a `must_refuse` case
  passes when there is no plan, whether by clarification or by failed validation.
- A clarification is: the model returned no plan, in the first or the repair round. Its text is the model's
  `clarification_needed`, or `The brief could not be mapped onto the available datasets.` when that is empty.
- `design_dashboard` and `ask_chart` return `DesignResult(clarification_needed=<text>, rejected=[])` for a
  clarification and `DesignResult(rejected=<errors>)` (as today) when the repair round still fails validation.
  Both are HTTP 200. `qa_audit` already records `clarification_needed`.
- `arp bi ask|design`: clarification → stderr `Clarification needed: <text>`, exit 3. Validation errors → as today.
- `SupersetBI.tsx` `ResultView`: when `clarification_needed` is set, the warning banner reads
  `The model needs more detail: <text>` followed by the existing `Nothing was created in Superset. Refine the brief
  and try again.`, with no reasons list. A result with `rejected` renders exactly as today.
- The OpenAPI document does not change (`DesignResult` already has both fields).

### (2) Error texts (`arp/api/routers/bi.py`)

`_bad_gateway` keeps logging the body for operators and picks the 502 `detail` by the first rule that matches.
"Root cause" is `e.__cause__` when it is set, else `e`. Rule 1 also matches when `e` itself is an `httpx.TransportError` (a raw httpx error's cause is httpcore's; owner decision, 15 Nov 2026).

| # | Root cause | `detail` |
|---|------------|----------|
| 1 | `httpx.TransportError` (connection refused, DNS, timeout) | `Superset is not reachable at <ARP_SUPERSET_URL>. It is not set up here or not running.` |
| 2 | `SupersetError` with status 401 or 403 | `Superset login failed (HTTP <status>): check ARP_SUPERSET_USER and ARP_SUPERSET_PASSWORD.` |
| 3 | `SupersetError` with status 404 | ``Superset has no such dataset or dashboard (HTTP 404): run `arp bi bootstrap`.`` |
| 4 | `e` is a `BIError` (any other cause, or none) | `str(e)`, as today |
| 5 | `SupersetError`, any other status | `Superset request failed (HTTP <status>).` |
| 6 | anything else | `Superset request failed.` |

`<ARP_SUPERSET_URL>` is `settings.superset_url` with any trailing `/` removed. Applies to all four BI endpoints,
so rules 1 to 3 give the same text everywhere. Rule 4 comes before rule 5 on purpose: ARP's own `BIError` messages
(`Creating chart 'A' failed: Superset returned HTTP 422`, `Superset: Superset returned HTTP 500`) keep their
wording, and none of them carries the body.
`embed-token`'s own 404 (`DashboardNotFound`) and 403 (`NotAnARPDashboard`) are caught before and do not change.

### (3) Reuse on `arp-scratch` (`arp/bi/service.py`)

Before creating the chart, `_add_to_scratch` looks at the charts on `arp-scratch`: their ids and titles from
`GET /api/v1/dashboard/{id}/charts` (as `dashboard_charts` does today), and for each chart whose title
(`slice_name`) equals the plan's chart title, `result.params` (a JSON string) from `GET /api/v1/chart/{id}`.
If that parsed JSON equals the `params` object `create_chart` would send for the plan's chart
(`{**compile_chart(...), "datasource": "<dataset id>__table", "viz_type": ...}`), nothing is created or attached
and the layout is not rewritten. Not the `form_data` of `/dashboard/{id}/charts`: Superset adds keys such as
`slice_id` there, so it never matches. The result is the same as a fresh add: `dashboard_id`, `slug`
`arp-scratch`, `url`, `plan`. The new client call goes into `superset_client.py`; `tests/test_bi_live_superset.py`
is the contract for it.

### (4) Template rows (test only)

One Postgres test (`ARP_TEST_POSTGRES_DSN`): run `arp.showcase.load.load` with a `PostgresPortfolioStore` on the
`env` fixture of `tests/test_showcase_load.py` (six monthly runs, real `publish_rows`), then query the `bi` view
behind every dataset the four templates in `arp/bi/templates/` use: `holdings`, `holdings_history`,
`portfolio_climate_metrics`, `company_profile`, `alerts`, `triggers` (AC-23, AC-24). If a view is empty when it
should not be, fix the cause in the publish or view code in the same PR; if the fix is not small, label the PR
`factory:blocked` and ask.

## Files

`backend/arp/bi/planner.py`, `service.py`, `eval.py` (caller only), `superset_client.py` (one new read call);
`backend/arp/api/routers/bi.py`; `backend/arp/cli/bi.py`; `frontend/src/pages/portfolio-monitoring/SupersetBI.tsx`;
their tests. No generated OpenAPI files change.

Existing tests superseded by (1), to be changed (not deleted) and listed in the PR:
`tests/test_api_bi.py::test_rejected_plan_is_200_with_reasons` and
`tests/test_bi_service.py::test_rejected_plan_makes_no_superset_writes` (a model refusal now lands in
`clarification_needed`, not `rejected`); `tests/test_bi_planner.py::test_refusal_returned_as_clarification`
(the planner's return shape).

## Left to the builder

The return shape of `plan_from_brief`; test layout and fakes.

## Acceptance

Holdout tests run in-process, not against the e2e stack (which has no Superset and a real model). API rows use a
FastAPI app with `get_llm_client`, `current_user` and `settings_dep` overridden as in `tests/test_api_bi.py`, and
`get_superset_client` returning `SupersetClient("http://127.0.0.1:8088", "arp_designer", <pw>,
transport=httpx.MockTransport(...))` (as in `tests/test_bi_superset_client.py`), or a real unreachable port for
AC-10/AC-11. CLI rows use `CliRunner` with `arp.llm.factory.build_llm_client` and
`arp.bi.superset_client.SupersetClient` monkeypatched as in `tests/test_bi_cli.py`. The model stand-in returns
fixed `PlannerRefusal` objects. "Question Q" is `Which portfolio do you mean?`. `ARP_SUPERSET_URL` is
`http://127.0.0.1:8088` and `ARP_SUPERSET_PASSWORD` is set unless a row says otherwise.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The model returns no plan and `clarification_needed` = Q | `POST /api/bi/ask` | 200; `clarification_needed` = Q; `rejected` = `[]`; `dashboard_id`, `url`, `plan` are `null`; Superset received no POST, PUT or DELETE other than `POST /api/v1/security/login` | holdout |
| AC-2 | As AC-1 | `POST /api/bi/design` | Same as AC-1 | holdout |
| AC-3 | The model returns no plan and `clarification_needed` = `""` | `POST /api/bi/ask` | 200; `clarification_needed` = `The brief could not be mapped onto the available datasets.`; `rejected` = `[]` | holdout |
| AC-4 | The model's first plan fails validation; its repair answer is no plan with `clarification_needed` = Q | `POST /api/bi/ask` | 200; `clarification_needed` = Q; `rejected` = `[]` | holdout |
| AC-5 | The model returns a plan that fails validation in both rounds | `POST /api/bi/ask` | 200; `rejected` = the validator's error strings for the second plan (non-empty); `clarification_needed` = `null` | holdout |
| AC-6 | As AC-1 | `arp bi ask "x"` and `arp bi design "x"` | Each exits 3; stderr is exactly `Clarification needed: Which portfolio do you mean?` plus a newline; stdout is empty | holdout |
| AC-7 | As AC-5 | `arp bi ask "x"` | Exits 3; stderr is the validator's errors, one per line, as on `main` | holdout |
| AC-8 | The BI page receives a result with `clarification_needed` = Q, `rejected` = `[]` | It renders | The warning banner's text is exactly `The model needs more detail: Which portfolio do you mean? Nothing was created in Superset. Refine the brief and try again.`; it has no `No dashboard was drafted.` and no list | unit |
| AC-9 | The BI page receives a result with `rejected` = `["e1", "e2"]`, `clarification_needed` = `null` | It renders | Same as on `main`: `No dashboard was drafted. The plan was refused for these reasons:` with list items `e1` and `e2` | unit |
| AC-10 | Nothing listens on `127.0.0.1:8088` | `POST /api/bi/ask` | 502; `detail` = `Superset is not reachable at http://127.0.0.1:8088. It is not set up here or not running.` | holdout |
| AC-11 | As AC-10 | `GET /api/bi/dashboards` | 502; same `detail` as AC-10 | holdout |
| AC-12 | Superset's login answers 401 with body `{"message": "postgresql://bi_reader:s3cret@db/arp"}` | `POST /api/bi/ask` | 502; `detail` = `Superset login failed (HTTP 401): check ARP_SUPERSET_USER and ARP_SUPERSET_PASSWORD.`; the response body does not contain `s3cret` | holdout |
| AC-13 | Login succeeds; the database lookup `GET /api/v1/database/` answers 403 | `POST /api/bi/ask` | 502; `detail` = `Superset login failed (HTTP 403): check ARP_SUPERSET_USER and ARP_SUPERSET_PASSWORD.` | holdout |
| AC-14 | Login succeeds; `GET /api/v1/dashboard/` answers 404 | `GET /api/bi/dashboards` | 502; ``detail`` = ``Superset has no such dataset or dashboard (HTTP 404): run `arp bi bootstrap`.`` | holdout |
| AC-15 | Login succeeds; `GET /api/v1/dashboard/` answers 500 with body `secret-body` | `GET /api/bi/dashboards` | 502; `detail` = `Superset request failed (HTTP 500).`; the response body does not contain `secret-body` | holdout |
| AC-16 | Superset has no database `arp_bi` (lookup answers 200 with an empty result) | `POST /api/bi/ask` | 502; ``detail`` = ``Superset has no database 'arp_bi' -- run `arp bi bootstrap`.``, as on `main` | holdout |
| AC-17 | `ARP_SUPERSET_PASSWORD` is unset | `POST /api/bi/ask` | 503; `detail` = `Superset is not configured: set ARP_SUPERSET_PASSWORD.`, as on `main` | holdout |
| AC-18 | `GET /api/v1/dashboard/7` answers 404 | `POST /api/bi/embed-token` with `dashboard_id` `7` | 404; `detail` = `Dashboard 7 not found.`, as on `main` | holdout |
| AC-19 | `arp-scratch` does not exist; the model returns a valid one-chart plan | `POST /api/bi/ask` | 200; Superset received one chart POST and one dashboard POST for slug `arp-scratch`; `slug` = `arp-scratch` | holdout |
| AC-20 | After AC-19, the model returns the same plan again | `POST /api/bi/ask` with the same question | 200; Superset received no chart POST and no PUT; `arp-scratch` still has 1 chart; `dashboard_id` and `url` equal those of AC-19 | holdout |
| AC-21 | After AC-19, the model returns a plan with the same chart title but a different metric | `POST /api/bi/ask` | 200; one new chart is created; `arp-scratch` has 2 charts | holdout |
| AC-22 | After AC-19, the model returns a plan with a different chart title and the same params | `POST /api/bi/ask` | 200; one new chart is created; `arp-scratch` has 2 charts | holdout |
| AC-23 | Postgres (`ARP_TEST_POSTGRES_DSN`) with `create_bi_views` applied; `arp.showcase.load.load` run with a `PostgresPortfolioStore` on the `env` fixture of `tests/test_showcase_load.py` | Query each of `bi.holdings`, `bi.holdings_history`, `bi.portfolio_climate_metrics`, `bi.company_profile` | Each returns at least 1 row | unit |
| AC-24 | As AC-23 | Query `bi.alerts` and `bi.triggers` | Each returns at least 1 row when any `ok run <month>: ...` line of the load reports more than 0 alerts (for `bi.alerts`) or more than 0 triggers (for `bi.triggers`) | unit |
| AC-25 | The PR branch | `cd backend && python scripts/export_openapi.py` | `frontend/src/api/openapi.json` is byte-identical to `main` | unit |
| AC-26 | A BI case with `must_refuse: true`; the stand-in model returns no plan with `clarification_needed` = Q | `run_bi_set` (`arp/bi/eval.py`) runs | The case has `passed` = `true`; the same stand-in on a case without `must_refuse` gives `passed` = `false` | unit |
| AC-27 | Superset's login answers 401 with body `B-401` | `arp bi ask "x"` | Exits 1; stderr starts with `Superset at http://127.0.0.1:8088: ` and contains `Response body: B-401`, as on `main` | holdout |
| AC-28 | The model returns a valid one-chart plan titled `A`; the chart POST answers 422 with body `secret-422` | `POST /api/bi/design` | 502; `detail` = `Creating chart 'A' failed: Superset returned HTTP 422`, as on `main`; the response body does not contain `secret-422` | holdout |

Must not change: validation-error results (AC-5, AC-7, AC-9); BIError messages of ARP's own (AC-16, AC-28); the 503
when BI is not configured (AC-17); embed-token's 404 (AC-18); the first ask on an empty scratch dashboard (AC-19);
the OpenAPI document (AC-25); the eval's refusal check (AC-26); the CLI's operator output (AC-27).
