# Superset Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An LLM turns a plain-language brief or question into draft Superset charts and dashboards over governed Postgres views, with every number computed by Superset SQL.

**Architecture:** A new `arp/bi/` package: planner (LLM, closed `ChartPlan`) → validator → compiler (pure) → `SupersetClient` (REST) → draft dashboard. Superset reads a `bi` schema of views through a `bi_reader` role that can see nothing else. The existing Generative BI under `arp/portfolio/genbi/` is not touched.

**Tech Stack:** Python 3.11, FastAPI, Typer, Pydantic, SQLAlchemy (existing Postgres layer), `httpx` (already a dependency), Apache Superset 5.x (Docker), React/TypeScript. No new Python dependencies.

**Spec:** `docs/superpowers/specs/2026-10-03-superset-integration-design.md`

## Global Constraints

- The LLM never writes SQL or raw Superset `form_data`; it emits a `ChartPlan` only.
- Nothing is written to Superset before the plan passes validation.
- Every dashboard is created with `published=false`; no code path sets it true.
- `bi_reader` has `SELECT` on schema `bi` only; no base table is readable.
- `bi.company_facts` holds only current facts with status `approved`, `edited` or `auto_approved`; `bi.company_facts_pending` holds `pending_review`; `rejected` appears in no view.
- viz_type allowlist (≈8): `big_number_total`, `echarts_timeseries_bar`, `echarts_timeseries_line`, `pie`, `table`, `pivot_table_v2`, `heatmap_v2`, `treemap_v2` (names confirmed against the pinned Superset in Task 4).
- Superset image is pinned to an exact 5.x tag; `SUPERSET_SECRET_KEY` and the `bi_reader` password come from `backend/.env`, no defaults.
- Superset binds to `127.0.0.1:8088`; embedding `frame-ancestors` is limited to the ARP UI origin.
- Postgres is required for BI. Tests needing it use `ARP_TEST_POSTGRES_DSN` and skip without it, like `tests/test_analytics_sql_parity.py`.
- Branch off and PR against `main` (`.claude/CLAUDE.md`). Review with `/ponytail:ponytail-review` and `/code-review`.

## Review Focus

1. A fact whose JSONB `value` has no numeric `value` key: `value_num` must be NULL, the view must not error.
2. An empty or malformed date string (`as_of_date`, `as_of`, `generated_at`): the view must return NULL, not raise.
3. A plan that names a column or metric not on the dataset: rejected before any Superset call, nothing created.
4. Superset fails on the 3rd of 4 chart creations: the 2 charts already created are deleted and the error names the failing chart.
5. A retry of the same brief: no duplicate dashboard (plan-hash slug).

---

## File Structure

| Path | Responsibility |
|---|---|
| `backend/arp/bi/__init__.py` | package marker |
| `backend/arp/bi/catalog.py` | `DatasetDef`, `MetricDef`, `VIEW_DATASETS`, `VIZ_ALLOWLIST` (single source of truth) |
| `backend/arp/bi/views.py` | `bi` schema DDL, `bi_reader` grants; used by a schema step and by bootstrap |
| `backend/arp/bi/plan.py` | `ChartSpec`, `ChartPlan`, `DatasetMeta` Pydantic models |
| `backend/arp/bi/validator.py` | `validate_plan` |
| `backend/arp/bi/compiler.py` | `compile_chart`, `compile_dashboard` (pure) |
| `backend/arp/bi/superset_client.py` | `SupersetClient` |
| `backend/arp/bi/planner.py` | `plan_from_brief` (LLM + one repair round) |
| `backend/arp/bi/service.py` | `design_dashboard`, `ask_chart`, `embed_token` |
| `backend/arp/bi/eval.py` + `backend/arp/golden_set/data/bi_cases.json` | planner eval set |
| `backend/arp/api/routers/bi.py` | HTTP surface |
| `backend/arp/cli/bi.py` | `arp bi bootstrap` |
| `superset/superset_config.py`, `docker-compose.yml` | deployment |
| `frontend/src/pages/portfolio-monitoring/SupersetBI.tsx` | UI sub-tab |

Tests: `backend/tests/test_bi_*.py`; one per module.

---

### Task 1: Settings and catalog

**Files:**
- Modify: `backend/arp/config.py` (add fields to `Settings`, near `postgres_dsn`)
- Create: `backend/arp/bi/__init__.py`, `backend/arp/bi/catalog.py`
- Test: `backend/tests/test_bi_catalog.py`

**Interfaces:**
- Produces: `Settings.superset_url: str = "http://127.0.0.1:8088"`, `Settings.superset_user: str = "arp_designer"`, `Settings.superset_password: str | None = None`, `Settings.bi_reader_password: str | None = None` (env `ARP_SUPERSET_URL` etc.).
- Produces (`catalog.py`):
  - `class MetricDef(BaseModel): name: str; expression: str; description: str`
  - `class DatasetDef(BaseModel): table: str; description: str; columns: dict[str, str]  # column -> description; metrics: list[MetricDef]`
  - `VIEW_DATASETS: dict[str, DatasetDef]` keyed `holdings`, `company_facts`, `company_facts_pending`, `run_records`, `documents` (schema is always `bi`)
  - `VIZ_ALLOWLIST: tuple[str, ...]`

- [ ] **Step 1: Write failing tests** in `test_bi_catalog.py`: `test_every_dataset_has_metrics_and_descriptions` (each dataset has ≥1 metric; every column and metric has non-empty description); `test_company_facts_pending_shares_columns_with_company_facts`; `test_viz_allowlist_has_eight_known_types`; `test_metric_names_unique_per_dataset`.
- [ ] **Step 2: Run** `cd backend && pytest tests/test_bi_catalog.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `catalog.py`. Column sets: `holdings` = portfolio_id, portfolio_name, as_of_date, security_id, security_name, isin, asset_class, currency, company_id, company_name, sector, country, quantity, market_value_eur, weight_pct; `company_facts`/`company_facts_pending` = company_id, fact_key, fact_type, as_of, value_num, value_text, status, confidence, reviewer, valid_from; `run_records` = run_id, run_type, company_id, needs_review, overall_confidence, generated_at; `documents` = doc_id, company_id, doc_type, title, source_url, first_seen_at, last_seen_at. Metrics: holdings → `Exposure (EUR)` `SUM(market_value_eur)`, `Holdings` `COUNT(*)`, `Avg weight (%)` `AVG(weight_pct)`; facts → `Facts` `COUNT(*)`, `Avg confidence` `AVG(confidence)`, `Total value` `SUM(value_num)` (description warns: only meaningful filtered to one `fact_key`); run_records → `Records` `COUNT(*)`, `% needing review` `100.0 * AVG(CASE WHEN needs_review THEN 1 ELSE 0 END)`, `Avg confidence` `AVG(overall_confidence)`; documents → `Documents` `COUNT(*)`, `Companies with documents` `COUNT(DISTINCT company_id)`.
- [ ] **Step 4: Run** the tests → PASS; also `ruff check arp/bi`.
- [ ] **Step 5: Commit** `feat(bi): settings and dataset/metric catalog`.

---

### Task 2: `bi` views and read-only role

**Files:**
- Create: `backend/arp/bi/views.py`
- Modify: `backend/arp/storage/postgres_schema.py` (append `SchemaStep` `0002_create_bi_views` to `SCHEMA_STEPS`; never edit step 0001)
- Test: `backend/tests/test_bi_views.py` (gated on `ARP_TEST_POSTGRES_DSN`)

**Interfaces:**
- Produces: `views.create_bi_views(conn: Connection) -> None` (idempotent: `CREATE SCHEMA IF NOT EXISTS bi`; `CREATE OR REPLACE VIEW` for the five views, columns exactly as in `catalog.VIEW_DATASETS`); `views.ensure_reader_role(conn: Connection, password: str) -> None` (creates or alters role `bi_reader` `LOGIN`, `REVOKE ALL` on `public` schema objects, grants `USAGE` on `bi` and `SELECT` on all `bi` views).
- Consumes: `catalog.VIEW_DATASETS`.

- [ ] **Step 1: Inspect the fact value shape.** Read `fact_candidates` / `fact_confidence` in `arp/storage/postgres_company_facts_projection.py` and decide where a numeric lives in `value` (expected `value->>'value'` when `jsonb_typeof(value->'value') = 'number'`). Record the choice in a comment in `views.py`.
- [ ] **Step 2: Write failing tests**, seeding with the helpers in `tests/postgres_helpers.py` and `PostgresPortfolioStore`: `test_holdings_view_matches_base_tables_total` (sum of `market_value_eur` equals the base `holdings` sum); `test_as_of_date_is_a_date` (`pg_typeof`); `test_facts_view_excludes_pending_and_rejected` and `test_pending_view_holds_only_pending`; `test_value_num_null_when_no_numeric` (Review Focus 1); `test_malformed_date_returns_null_not_error` (Review Focus 2: insert `as_of=''`); `test_bi_reader_cannot_select_base_tables` (connect as `bi_reader`, expect `InsufficientPrivilege` on `holdings`, success on `bi.holdings`); `test_run_records_excludes_payload`.
- [ ] **Step 3: Run** `ARP_TEST_POSTGRES_DSN=... pytest tests/test_bi_views.py -v` → FAIL.
- [ ] **Step 4: Implement** `views.py` and the schema step. Date casts use `NULLIF(col,'')` plus a regex guard (`col ~ '^\d{4}-\d{2}-\d{2}'`) so malformed strings give NULL. Facts views filter `is_current AND status IN (...)`.
- [ ] **Step 5: Run** the tests → PASS; run `arp db check-postgres` and confirm it reports no pending step.
- [ ] **Step 6: Commit** `feat(bi): bi schema views and read-only role`.

---

### Task 3: SupersetClient

**Files:**
- Create: `backend/arp/bi/superset_client.py`, `backend/arp/bi/plan.py` (`DatasetMeta` only)
- Test: `backend/tests/test_bi_superset_client.py` (uses `httpx.MockTransport`, no network)

**Interfaces:**
- Produces: `class SupersetClient` with `__init__(self, base_url: str, user: str, password: str, *, transport: httpx.BaseTransport | None = None)` and methods
  - `ensure_database(name: str, sqlalchemy_uri: str) -> int`
  - `ensure_dataset(database_id: int, schema: str, table: str) -> int`
  - `dataset_meta(dataset_id: int) -> DatasetMeta` (columns + metric names, from the dataset API)
  - `sync_metrics(dataset_id: int, metrics: list[MetricDef]) -> None`
  - `create_chart(name: str, dataset_id: int, viz_type: str, params: dict) -> int`
  - `create_dashboard(title: str, slug: str, position_json: dict, chart_ids: list[int]) -> int` (always `published=False`)
  - `find_dashboard(slug: str) -> int | None`
  - `delete_chart(id: int) -> None`, `delete_dashboard(id: int) -> None`
  - `guest_token(dashboard_id: str, rls: list[dict]) -> str`
  - `class SupersetError(Exception)` carrying status code and response body
- Also creates `backend/arp/bi/plan.py` containing only `class DatasetMeta(BaseModel): columns: set[str]; metrics: set[str]`; Task 5 adds the rest of that file.

- [ ] **Step 1: Write failing tests** with `MockTransport`: `test_login_then_csrf_header_sent_on_writes`; `test_create_dashboard_sends_published_false`; `test_error_response_raises_superset_error_with_body`; `test_ensure_dataset_is_idempotent` (second call finds existing, makes no POST); `test_token_refreshed_on_401_once`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Login at `/api/v1/security/login` (provider `db`), CSRF at `/api/v1/security/csrf_token/`, then `Authorization: Bearer` + `X-CSRFToken`. Re-login once on 401. Endpoints: `/api/v1/database/`, `/dataset/`, `/chart/`, `/dashboard/`, `/security/guest_token/`. Exact payload keys are confirmed in Task 4; mark any not yet confirmed with `# unverified` until then.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(bi): Superset REST client`.

---

### Task 4: Deployment, bootstrap CLI, live contract test

**Files:**
- Modify: `docker-compose.yml` (add `superset` service, `superset` DB init), `backend/.env.example`
- Create: `superset/superset_config.py`, `backend/arp/cli/bi.py`, `backend/tests/test_bi_live_superset.py`, `backend/tests/fixtures/bi/` (recorded chart params)
- Modify: `backend/arp/cli/__init__.py` (`app.add_typer(bi_app, name="bi")`)

**Interfaces:**
- Produces: CLI `arp bi bootstrap` → idempotent; returns exit code 0 and prints JSON `{"database_id", "datasets": {table: id}, "reader_role": "bi_reader"}`.
- Consumes: `SupersetClient` (Task 3), `views.create_bi_views`/`ensure_reader_role` (Task 2), `catalog.VIEW_DATASETS` (Task 1), `Settings.*`.

- [ ] **Step 1: Compose.** `superset` service on the pinned 5.x tag, `127.0.0.1:8088:8088`, metadata DB `superset` in the existing `postgres` container, config from `./superset/superset_config.py` mounted at `/app/pythonpath/`. `superset_config.py` sets `SECRET_KEY` from `SUPERSET_SECRET_KEY` (fail if unset), `FEATURE_FLAGS={"EMBEDDED_SUPERSET": True}`, `GUEST_TOKEN_JWT_SECRET`, `TALISMAN_CONFIG` frame-ancestors `http://localhost:5173`, no cache backend.
- [ ] **Step 2: Write failing live test** `test_live_superset_roundtrip` (marker `@pytest.mark.live_superset`, skipped unless `ARP_TEST_SUPERSET_URL` is set): bootstrap, create one chart of **each** allowlisted viz_type from the hand-written params in `fixtures/bi/*.json`, create a dashboard, read it back, assert `published is False`, delete everything. Register the marker in `pyproject.toml`.
- [ ] **Step 3: Implement `arp bi bootstrap`**: apply views and reader role, `ensure_database("arp_bi", <bi_reader URI>)`, `ensure_dataset` per `VIEW_DATASETS`, `sync_metrics`, ensure the `arp_designer` user exists (via Superset's CLI `superset fab create-user` documented in the command's help if not creatable over REST).
- [ ] **Step 4: Bring up and verify live.** `docker compose up -d postgres superset`, `arp db init-postgres`, `arp portfolio seed-demo` into Postgres, `arp bi bootstrap`, then `ARP_TEST_SUPERSET_URL=http://127.0.0.1:8088 pytest -m live_superset -v` → PASS. If Docker is unavailable in the executing environment, stop and report; Tasks 5–9 may proceed but the compiler stays flagged unverified (see Task 6).
- [ ] **Step 5: Record fixtures.** For each viz_type, save the `params` Superset accepted and renders (confirm by opening the chart's data endpoint `/api/v1/chart/<id>/data/` returns rows) into `fixtures/bi/<viz_type>.json`; correct any `# unverified` payload keys in Task 3.
- [ ] **Step 6: Commit** `feat(bi): superset deployment, bootstrap, live contract test`.

---

### Task 5: ChartPlan and validator

**Files:**
- Modify: `backend/arp/bi/plan.py` (add `ChartSpec`, `ChartPlan`, `MAX_CHARTS`)
- Create: `backend/arp/bi/validator.py`
- Test: `backend/tests/test_bi_validator.py`

**Interfaces:**
- Produces (`plan.py`):
  - `class ChartSpec(BaseModel): title: str; question: str = ""; viz_type: str; dataset: str; metrics: list[str]; groupby: list[str] = []; filters: dict[str, str] = {}; time_range: str | None = None`
  - `class ChartPlan(BaseModel): title: str; goal: str = ""; charts: list[ChartSpec]  # 1..6`
  - `MAX_CHARTS = 6`
  - `DatasetMeta` already exists in this file from Task 3; leave it unchanged
- Produces (`validator.py`): `validate_plan(plan: ChartPlan, metas: dict[str, DatasetMeta]) -> list[str]` — returns rejection reasons, empty list means valid. `metas` is keyed by dataset table name.

- [ ] **Step 1: Write failing tests:** `test_valid_plan_has_no_errors`; `test_unknown_dataset_rejected`; `test_unknown_metric_rejected_names_chart_title`; `test_unknown_groupby_column_rejected`; `test_filter_column_must_exist`; `test_viz_type_outside_allowlist_rejected`; `test_more_than_max_charts_rejected`; `test_empty_metrics_rejected`; `test_pivot_requires_two_groupby`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** both modules; reasons are human-readable strings naming the chart title and the offending value (they are fed back to the planner in Task 8).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(bi): ChartPlan schema and validator`.

---

### Task 6: Compiler

**Files:**
- Create: `backend/arp/bi/compiler.py`
- Test: `backend/tests/test_bi_compiler.py`

**Interfaces:**
- Produces: `compile_chart(spec: ChartSpec, dataset_id: int) -> dict` (Superset chart `params`); `compile_dashboard(chart_ids: list[int], titles: list[str]) -> dict` (`position_json`: a grid, two charts per row, each chart `width=6, height=50`); `plan_hash(plan: ChartPlan) -> str` (first 12 hex of sha256 of the canonical JSON).
- Consumes: `ChartSpec` (Task 5); fixtures in `tests/fixtures/bi/` (Task 4).

- [ ] **Step 1: Write failing golden tests:** one `test_compile_<viz_type>_matches_verified_fixture` per allowlisted type, comparing `compile_chart` output for a canonical spec to `fixtures/bi/<viz_type>.json`; `test_plan_hash_stable_and_order_independent_for_filters`; `test_dashboard_layout_two_per_row`; `test_odd_chart_count_last_row_single`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**, mapping `metrics` to saved-metric names, `groupby` to dimension columns, `filters` to adhoc `==` filters, `time_range` to Superset's string form (`"Last quarter"`, `"No filter"` default).
- [ ] **Step 4: Run** → PASS. If Task 4 Step 4 could not run, add `# unverified against live Superset` to the module docstring and say so in the final report.
- [ ] **Step 5: Commit** `feat(bi): plan to Superset compiler`.

---

### Task 7: Service (design, ask, embed token)

**Files:**
- Create: `backend/arp/bi/service.py`
- Test: `backend/tests/test_bi_service.py` (fake in-memory client)

**Interfaces:**
- Produces: `async def design_dashboard(brief: str, llm: LLMClient, client: SupersetClient) -> DesignResult`; `async def ask_chart(question: str, llm, client) -> DesignResult`; `def embed_token(client, dashboard_id: str) -> tuple[str, str]` (guest token, embedded uuid); `class DesignResult(BaseModel): dashboard_id: int | None; slug: str | None; url: str | None; plan: ChartPlan | None; rejected: list[str]; clarification_needed: str | None`.
- Consumes: `plan_from_brief` (Task 8; code against its signature `async def plan_from_brief(brief: str, metas, llm) -> tuple[ChartPlan | None, list[str]]`, returning `(None, reasons)` on refusal), `validate_plan`, `compile_*`, `SupersetClient`.

- [ ] **Step 1: Write failing tests** with a fake client recording calls: `test_rejected_plan_makes_no_superset_writes` (Review Focus 3); `test_failure_on_third_chart_deletes_first_two` (Review Focus 4); `test_dashboard_created_unpublished`; `test_same_plan_reuses_dashboard_by_slug` (Review Focus 5); `test_ask_lands_on_scratch_dashboard`; `test_no_code_path_publishes` (assert every `create_dashboard` call has `published` false in the fake).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Order: read `dataset_meta` for each dataset → plan → validate → create charts → create dashboard (slug `arp-<plan_hash>`; Scratch slug `arp-scratch`) → on any `SupersetError` delete created charts then re-raise as `BIError`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(bi): design/ask service with cleanup`.

---

### Task 8: Planner and eval set

> Execution order: Task 8 ran before Task 7 (the service imports the planner).

**Files:**
- Create: `backend/arp/bi/planner.py`, `backend/arp/bi/eval.py`, `backend/arp/golden_set/data/bi_cases.json`
- Modify: `backend/arp/cli/golden_set.py` (add `bi` command next to `planner`)
- Test: `backend/tests/test_bi_planner.py`

**Interfaces:**
- Produces: `async def plan_from_brief(brief: str, metas: dict[str, DatasetMeta], llm: LLMClient) -> tuple[ChartPlan | None, list[str]]`; `class PlannerRefusal(BaseModel)` internal output model with `clarification_needed: str`.
- Consumes: `catalog.VIEW_DATASETS` descriptions (prompt is built from them), `VIZ_ALLOWLIST`, `validate_plan`.

- [ ] **Step 1: Write failing tests** with a scripted fake `LLMClient`: `test_prompt_contains_metric_descriptions_but_no_row_data`; `test_invalid_plan_gets_exactly_one_repair_round_with_reasons`; `test_second_failure_returns_none_and_reasons`; `test_refusal_returned_as_clarification`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `complete_structured(output_model=ChartPlan | refusal wrapper)`. System prompt states: choose from the datasets, metrics and viz types listed; never invent columns; facts datasets are reviewed-only, use `company_facts_pending` only when the brief asks about review backlog.
- [ ] **Step 4: Eval set.** `bi_cases.json`: ≥6 cases `{brief, must_include: {datasets, viz_types, metrics}, must_refuse: bool}` incl. one pending-backlog brief (must use `company_facts_pending`) and two that must be refused. `arp golden-set bi` scores shape only, mirroring `planner_runner.py`; it needs an API key and is not run in CI.
- [ ] **Step 5: Run** unit tests → PASS. Commit `feat(bi): planner and eval set`.

---

### Task 9: HTTP API

**Files:**
- Create: `backend/arp/api/routers/bi.py`
- Modify: `backend/arp/api/main.py` (import and `include_router`), `backend/arp/api/deps.py` (`get_superset_client`)
- Test: `backend/tests/test_api_bi.py`

**Interfaces:**
- Produces: `POST /api/bi/design` `{brief}` → `DesignResult`; `POST /api/bi/ask` `{question}` → `DesignResult`; `POST /api/bi/embed-token` `{dashboard_id}` → `{token: str, embedded_id: str}`; `deps.get_superset_client() -> SupersetClient` (raises 503 with a clear message if `superset_password` unset).

- [ ] **Step 1: Write failing tests** via FastAPI `TestClient` and dependency overrides: `test_design_returns_result`; `test_superset_down_returns_502_with_message` (nothing created); `test_missing_superset_config_returns_503`; `test_embed_token_requires_dashboard_id`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; map `BIError`/`SupersetError` to 502. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(bi): HTTP API`.

---

### Task 10: Frontend sub-tab

**Files:**
- Create: `frontend/src/pages/portfolio-monitoring/SupersetBI.tsx`, `frontend/tests/biEmbed.test.ts`
- Modify: `frontend/src/pages/PortfolioRiskMonitoringTool.tsx` (add `{ id: "superset", label: "Superset BI" }` to `SUB_TABS` and the render line), `frontend/package.json` (`@superset-ui/embedded-sdk`)
- Test: `frontend/tests/biEmbed.test.ts` (node:test, pure helper only)

**Interfaces:**
- Produces: component `SupersetBI()`; pure helper `designRequestBody(brief: string): { brief: string }` and `embedUrlFor(result: DesignResult, embeddedId: string, domain: string): string | null` exported for the test.
- Consumes: Task 9 endpoints, existing API base helper used by `GenerativeBI.tsx`.

- [ ] **Step 1: Write failing test** `embedUrlFor returns null when dashboard_id is null` and `designRequestBody trims the brief`. **Step 2: Run** `cd frontend && npm test` → FAIL.
- [ ] **Step 3: Implement** the component: brief textarea, "Design in Superset" button, rejection reasons list, link to the draft dashboard, and the embedded dashboard via the SDK using `/api/bi/embed-token`. Follow `GenerativeBI.tsx` styling and DESIGN.md tokens. Add a visible note: "Draft — unpublished. Publish it in Superset."
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build` → PASS.
- [ ] **Step 5: Run** the app, open the tab and screenshot it (needs Superset up from Task 4).
- [ ] **Step 6: Commit** `feat(bi): Superset BI tab`.

---

### Task 11: Docs and full verification

**Files:**
- Modify: `README.md` (add function entry and setup), `docs/GENBI_LANDSCAPE_REVIEW.md` (note §5.4 alias layer now covered by the Superset metric catalogue)
- Modify: `.github/workflows/ci.yml` (optional job running `-m live_superset`; leave off by default)

- [ ] **Step 1:** Document `docker compose up -d postgres superset`, `arp db init-postgres`, `arp bi bootstrap`, the env vars from Global Constraints, and the "drafts only" rule.
- [ ] **Step 2: Run** `cd backend && ruff check . && pytest -q` and `cd frontend && npm run lint && npm run build && npm test` → all pass.
- [ ] **Step 3: Run** `/ponytail:ponytail-review` then `/code-review`; fix findings.
- [ ] **Step 4: Commit** `docs(bi): setup and README`. Open a PR against `main` only when asked.

---

## Self-Review notes

- Spec coverage: views and role (T2), semantic layer (T1, T4), ChartPlan (T5), compile/publish/cleanup/idempotency (T6, T7), ask the data (T7), deployment and bootstrap (T4), API and embed token (T9), UI (T10), eval set and tests (T8, T11). RLS and narration are out of scope per the spec.
- Spec deviation: the UI is a sub-tab of Risk Monitoring (one file, one line) rather than a new top-level tab. Company facts are not portfolio data, so promote it to its own tab if you want.
- `DatasetMeta` is defined once, in `plan.py`, created by Task 3 and extended by Task 5.
