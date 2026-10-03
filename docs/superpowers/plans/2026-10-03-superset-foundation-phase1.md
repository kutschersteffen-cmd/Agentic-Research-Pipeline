# Superset Foundation Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the old Generative BI, give Risk Monitoring one Superset "Dashboards" tab (replacing Generative BI, Pivot Explorer and "Superset BI"), provision a standard `arp-risk-exposure` dashboard with native filters, and sync catalogue descriptions into Superset.

**Architecture:** Everything builds on the shipped `arp/bi` package (catalog -> views -> validator -> compiler -> `SupersetClient`). Dashboard templates are committed JSON compiled by the same compiler and created by `arp bi bootstrap` idempotently; the UI lists `arp-` dashboards from a new endpoint and embeds the chosen one. Phases 2 and 3 are untouched.

**Tech Stack:** Python 3.11, FastAPI, Typer, Pydantic, SQLAlchemy/Postgres 16, Apache Superset 5.0.0 (Docker), React/TypeScript. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-03-superset-foundation-phase1-design.md` (builds on `2026-10-03-superset-integration-design.md`)

## Global Constraints

- Phases 2 and 3 untouched: Standard Analytics, Company Profiles, Monitoring & Alerts, Governance & Audit and Ask the Portfolio keep working unchanged.
- Keep `AnalyticSpec`, `PivotSpec`, `analytics.py`, `aggregation.py`, saved analytics, and the `/api/portfolio/aggregate` and `/pivot` endpoints.
- Every dashboard the code creates is `published=false`, including the provisioned one.
- Templates use only the 8 allowlisted viz types and catalogue datasets, and pass `validate_plan` against live dataset metadata before any write.
- A dashboard is embeddable and listed iff its slug starts with exactly `arp-` (case-sensitive, no stripping).
- Re-running `arp bi bootstrap` changes nothing when `arp-risk-exposure` has at least as many charts as its template; it never deletes charts and never touches `published`.
- No secrets in API responses, logs or errors (Superset bodies stay out of messages).
- Postgres tests use `ARP_TEST_POSTGRES_DSN`; live tests are marked `live_superset` and skipped without `ARP_TEST_SUPERSET_URL`.
- Pre-existing backend test failures (5, recorded by name in the controller's notes) are not yours; do not add new ones.
- PRs go against `main`; do not open one.

## Review Focus

1. A template naming a column or metric that does not exist: bootstrap fails loudly before creating anything (Task 5 test).
2. `arp bi bootstrap` re-run after a person extended or published `arp-risk-exposure`: nothing deleted, `published` untouched (Task 5 test).
3. Dashboard list lookalike slugs (`ARP-x`, `arpx`, ` arp-x`, empty): excluded (Task 6 test).
4. Description sync on re-run: idempotent and does not drop existing columns, metrics or flags (Task 3 test; Superset's dataset PUT replaces lists).
5. `bi.holdings_history` with junk date strings and with an empty `holdings` table: junk rows excluded, no error (Task 2 test).

---

## File Structure

| Path | Responsibility |
|---|---|
| `backend/arp/bi/views.py`, `catalog.py` | add `holdings_history` view and dataset |
| `backend/arp/bi/superset_client.py` | `sync_descriptions`, `list_dashboards`, `json_metadata` on create/update |
| `backend/arp/bi/plan.py` | `NativeFilter`, `DashboardTemplate` models |
| `backend/arp/bi/compiler.py` | `compile_native_filters` |
| `backend/arp/bi/templates.py` + `backend/arp/bi/templates/exposure.json` | load and provision templates |
| `backend/arp/cli/bi.py` | bootstrap: descriptions + template provisioning |
| `backend/arp/api/routers/bi.py` | `GET /api/bi/dashboards` |
| `frontend/src/pages/portfolio-monitoring/SupersetBI.tsx` | picker + embed (becomes the "Dashboards (Superset)" tab) |
| removals | see Task 1 |

Tests: one file per module as in `backend/tests/test_bi_*.py`.

---

### Task 1: Remove the old Generative BI

**Files:**
- Delete: `backend/arp/portfolio/genbi/` (all), `backend/arp/api/routers/genbi.py`, `frontend/src/pages/portfolio-monitoring/GenerativeBI.tsx`, `backend/arp/golden_set/planner_runner.py`, `planner_schema.py`, `backend/arp/golden_set/data/planner_cases.json`, `backend/tests/test_genbi_*.py` (5 files), `docs/GENBI_LANDSCAPE_REVIEW.md`
- Modify: `backend/arp/api/main.py` (drop `genbi` import and `include_router`), `backend/arp/cli/portfolio.py` (drop the `bi` Typer group, its commands and `_echo_dashboard`; keep imports still used), `backend/arp/cli/golden_set.py` (drop the `planner` command and its imports; keep `bi`), `backend/arp/storage/portfolio_store.py` and `postgres_portfolio_store.py` (drop `dashboards_path`, `save_dashboard`, `list_dashboards`, `get_dashboard` together; update the Postgres class docstring), `frontend/src/pages/PortfolioRiskMonitoringTool.tsx` (drop the `genbi` entry and render), `frontend/src/api/client.ts` and `frontend/src/types.ts` (drop the Generative BI block and its types), docs that mention it (`docs/METHODOLOGY.md`, `docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md`, `README.md`, the two Superset specs/plans: reword to "replaced by Superset"), stale comments in `backend/arp/api/routers/bi.py:18` and `backend/arp/bi/eval.py:1`
- Test: existing suites

**Interfaces:**
- Produces: nothing new. Later tasks assume `PortfolioRiskMonitoringTool.tsx` has no `genbi` sub-tab.

- [ ] **Step 1: Baseline.** Run the full backend suite once with `ARP_TEST_POSTGRES_DSN` set and save the failing test names to a file outside the repo; run `cd frontend && npm test && npm run lint && npm run build`. Record both.
- [ ] **Step 2: Delete and edit** exactly the files above. `grep -rn "genbi\|GenerativeBI\|planner_runner\|PlannerCase" backend frontend/src docs README.md --include=* -l` must list only historical docs under `docs/superpowers/` that describe past work (reword the ones that claim Generative BI exists today).
- [ ] **Step 3: Run** the full backend suite: failures must equal the Step 1 set (no new ones; the store parity test `tests/test_portfolio_store_parity.py` must pass). Frontend `npm test && npm run lint && npm run build` must pass.
- [ ] **Step 4: Run** `python -c "from arp.api.main import app; print([r.path for r in app.routes if 'portfolio/bi' in r.path])"` and expect `[]`.
- [ ] **Step 5: Commit** `refactor: remove the old Generative BI (replaced by Superset)`.

---

### Task 2: `bi.holdings_history` view and dataset

**Files:**
- Modify: `backend/arp/bi/views.py`, `backend/arp/bi/catalog.py`, `backend/arp/bi/superset_client.py` only if dataset creation needs nothing new (it should not)
- Test: `backend/tests/test_bi_views.py`, `backend/tests/test_bi_catalog.py`

**Interfaces:**
- Produces: `VIEW_DATASETS["holdings_history"]` (same `columns` and `metrics` as `holdings`, description "Every holdings snapshot, joined to security and company"); `TEMPORAL_COLUMNS["holdings_history"] = frozenset({"as_of_date"})`; Postgres view `bi.holdings_history`; `views.create_bi_views` creates it (existing function, idempotent `CREATE OR REPLACE`).

- [ ] **Step 1: Failing tests:** in `test_bi_views.py` `test_holdings_history_has_every_snapshot` (two snapshot dates for one portfolio -> both present; `bi.holdings` still returns only the later), `test_holdings_history_excludes_junk_dates_and_empty_table_is_ok` (a junk `as_of_date` row is absent; with `holdings` emptied the view returns zero rows and no error), `test_history_columns_match_catalog` (view columns equal `VIEW_DATASETS["holdings_history"].columns` in order); in `test_bi_catalog.py` `test_holdings_history_mirrors_holdings` (columns and metric names equal `holdings`'; temporal column present).
- [ ] **Step 2: Run** `ARP_TEST_POSTGRES_DSN=... pytest tests/test_bi_views.py tests/test_bi_catalog.py -v` -> FAIL.
- [ ] **Step 3: Implement** the catalog entry (build it from the `holdings` entry so the two cannot drift) and the view in `views.py` reusing the same SELECT as `bi.holdings` minus the latest-snapshot join (share the SELECT text via a helper so both stay in step). Grants: `bi_reader` gets SELECT as for the other views (extend the existing grant loop; no new privileges).
- [ ] **Step 4: Run** the same command -> PASS; also `pytest tests/test_bi_planner.py tests/test_bi_validator.py -q` (planner prompt and validator are catalog-driven; fix any count assertions).
- [ ] **Step 5: Commit** `feat(bi): holdings_history view and dataset`.

---

### Task 3: Bootstrap copies catalogue descriptions into Superset

**Files:**
- Modify: `backend/arp/bi/superset_client.py`, `backend/arp/cli/bi.py`
- Test: `backend/tests/test_bi_superset_client.py`, `backend/tests/test_bi_cli.py`, live assertions in `backend/tests/test_bi_live_superset.py`

**Interfaces:**
- Produces: `SupersetClient.sync_descriptions(self, dataset_id: int, description: str, columns: dict[str, str]) -> None` — sets the dataset `description` and each named column's `description`, keeping every existing column (by id and `column_name`) and every metric untouched; idempotent (no PUT when nothing differs).
- Consumes: `catalog.VIEW_DATASETS[...]` (`.description`, `.columns: dict[str, str]`).

- [ ] **Step 1: Failing tests (mock transport):** `test_sync_descriptions_sets_dataset_and_column_descriptions`; `test_sync_descriptions_keeps_existing_columns_and_metrics` (the PUT body lists all existing columns with their ids and all metrics with ids; Review Focus 4); `test_sync_descriptions_is_idempotent` (second call with the same values makes no PUT). In `test_bi_cli.py`: `test_bootstrap_syncs_descriptions_for_every_dataset` with the existing fake client. Live (extend the existing bootstrap live test): after bootstrap, `GET /dataset/<id>` shows `description` and a column description from the catalog for `holdings`.
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** `sync_descriptions` (read via `_dataset`, merge, one PUT) and call it for each dataset in `cli/bi.py` next to `sync_metrics`.
- [ ] **Step 4: Run** the unit tests -> PASS. The live assertion is run in Task 8 with the full live suite.
- [ ] **Step 5: Commit** `feat(bi): bootstrap copies catalogue descriptions into Superset`.

---

### Task 4: Native filters — live spike, compiler support, client plumbing

**Files:**
- Modify: `backend/arp/bi/plan.py`, `backend/arp/bi/compiler.py`, `backend/arp/bi/superset_client.py`
- Create: `backend/tests/fixtures/bi/native_filters.json` (the config Superset accepted and applied)
- Test: `backend/tests/test_bi_compiler.py`, `backend/tests/test_bi_superset_client.py`, `backend/tests/test_bi_live_superset.py`

**Interfaces:**
- Produces (`plan.py`): `class NativeFilter(BaseModel): name: str; dataset: str; column: str` (a select filter on `dataset.column`).
- Produces (`compiler.py`): `compile_native_filters(filters: list[NativeFilter], dataset_ids: dict[str, int], chart_ids: list[int]) -> dict` — the `native_filter_configuration` list (wrapped as `{"native_filter_configuration": [...]}` ready to be `json_metadata`); `chart_ids` is accepted so scopes can name charts if the spike needs it.
- Produces (client): `create_dashboard(..., json_metadata: dict | None = None)` and `update_dashboard(..., json_metadata: dict | None = None)` (additive; `published` stays False and is still not an argument).

- [ ] **Step 1: Live spike (record the result in the report).** Bring up Superset 5.0.0 as in `test_bi_live_superset.py`'s docstring (Docker daemon: `nohup dockerd &`; image `apache/superset:5.0.0`; the Dockerfile build fails in the sandbox on proxy TLS — use the local `arp-superset:dev` image or the wheel workaround documented in the README). With a dashboard of two charts on two different datasets (`holdings` and `holdings_history`) sharing the column `portfolio_name`, try native filters (`filterType: filter_select`, `targets: [{datasetId, column:{name}}]`, scope covering both charts) and decide: does ONE filter scope charts on both datasets? Check by rendering with a filter value set and reading each chart's data (`/api/v1/chart/<id>/data/` with the filter, or screenshot). Write the answer, the accepted config and the Superset behaviour into the report. If one filter cannot cover both datasets, the template (Task 5) uses one filter per dataset.
- [ ] **Step 2: Failing tests:** `test_compile_native_filters_matches_verified_fixture` (golden against `native_filters.json` for a canonical `[NativeFilter(name="Portfolio", dataset="holdings", column="portfolio_name")]`), `test_native_filter_ids_are_stable_and_unique` (ids derived from dataset+column, identical across calls), `test_create_dashboard_sends_json_metadata_and_still_unpublished` (mock transport; body has `json_metadata` as a JSON string and `published: false`).
- [ ] **Step 3: Implement** the model, `compile_native_filters` (pure, deterministic ids), and the two client parameters.
- [ ] **Step 4: Run** `pytest tests/test_bi_compiler.py tests/test_bi_superset_client.py -q` -> PASS; add a live test `test_native_filters_are_stored_and_applied` (creates a dashboard with the compiled filters, reads `json_metadata` back, asserts the filter exists; applies it to the data query if the spike showed how) and run it live once.
- [ ] **Step 5: Commit** `feat(bi): native filter compiler and dashboard json_metadata`.

---

### Task 5: Dashboard templates and bootstrap provisioning

**Files:**
- Create: `backend/arp/bi/templates.py`, `backend/arp/bi/templates/exposure.json`
- Modify: `backend/arp/bi/plan.py` (add `DashboardTemplate`), `backend/arp/cli/bi.py`, `backend/arp/bi/service.py` only if a shared helper is extracted (prefer calling `_create_charts`/`compile_dashboard` as they are)
- Test: `backend/tests/test_bi_templates.py`, `backend/tests/test_bi_cli.py`, live in `backend/tests/test_bi_live_superset.py`

**Interfaces:**
- Produces (`plan.py`): `class DashboardTemplate(BaseModel): slug: str; title: str; goal: str = ""; charts: list[ChartSpec]; native_filters: list[NativeFilter] = []`.
- Produces (`templates.py`): `load_templates() -> list[DashboardTemplate]` (reads `backend/arp/bi/templates/*.json` via `importlib.resources`, validates slug starts with `arp-`); `provision(client: SupersetClient, template: DashboardTemplate) -> str` returning `"created" | "rebuilt" | "unchanged"`.
- `exposure.json`: slug `arp-risk-exposure`, title "Exposure overview", charts per the spec (total exposure big number; exposure by fund bar; sector treemap; country table; currency bar; asset class pie; sector x fund pivot; exposure over time by fund line on `holdings_history`), native filters from the Task 4 decision (portfolio_name, sector, country).
- Consumes: `compile_chart`, `compile_dashboard`, `compile_native_filters`, `validate_plan` (build a `ChartPlan` from the template's charts for validation), `SupersetClient` (`find_dashboard`, `dashboard_charts`, `create_chart`, `create_dashboard(..., json_metadata=)`, `delete_dashboard`, `delete_chart`).

- [ ] **Step 1: Failing tests (fake client, as in `test_bi_service.py`):** `test_provision_creates_dashboard_when_absent` (charts created, dashboard slug `arp-risk-exposure`, unpublished, json_metadata present -> `"created"`), `test_provision_is_unchanged_when_complete` (no writes), `test_provision_rebuilds_only_when_fewer_charts` (deletes only the dashboard, recreates, charts of the old one untouched -> `"rebuilt"`), `test_provision_leaves_extended_dashboard_alone` (more charts than the template -> no writes; Review Focus 2), `test_provision_never_sets_published` (no `published` anywhere in calls), `test_template_with_unknown_column_fails_before_any_write` (Review Focus 1), `test_bundled_templates_validate_against_catalog` (every bundled template passes `validate_plan` with offline metas built from the catalog), `test_template_slug_must_start_with_arp`. CLI: `test_bootstrap_provisions_templates`.
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** `DashboardTemplate`, `templates.py`, `exposure.json`, and the bootstrap call after datasets/metrics/descriptions (print `{"templates": {slug: status}}` in the existing JSON summary). Failure of validation raises before any write and exits non-zero with a clear message.
- [ ] **Step 4: Run** unit tests -> PASS. Live: extend the live bootstrap test: after bootstrap, `arp-risk-exposure` exists, every chart returns rows from the ETF-or-demo data in the DSN, native filters present, `published` is False; a second bootstrap reports `unchanged`.
- [ ] **Step 5: Commit** `feat(bi): provision the standard exposure dashboard from a template`.

---

### Task 6: `GET /api/bi/dashboards`

**Files:**
- Modify: `backend/arp/bi/superset_client.py`, `backend/arp/api/routers/bi.py`
- Test: `backend/tests/test_bi_superset_client.py`, `backend/tests/test_api_bi.py`, live in `backend/tests/test_bi_live_superset.py`

**Interfaces:**
- Produces (client): `list_dashboards(self, slug_prefix: str = "arp-") -> list[dict]` returning `{"id": int, "slug": str, "title": str, "published": bool}` for dashboards whose slug starts with the prefix (use Superset's list filter, then re-check `startswith` in Python so lookalikes never pass).
- Produces (API): `GET /api/bi/dashboards` -> `list[DashboardItem]` (`id, slug, title, published`), 502 on Superset failure (no body), 503 when not configured (existing getters).

- [ ] **Step 1: Failing tests:** client `test_list_dashboards_filters_by_prefix` (mock returns `arp-a`, `ARP-b`, `arpx`, ` arp-c`, `None`, `human` -> only `arp-a`); `test_list_dashboards_pages_through_results` (more than one page); API `test_dashboards_endpoint_returns_items`, `test_dashboards_502_without_body`, `test_dashboards_503_when_unconfigured`; live: a hand-made dashboard with slug `arp-manual-<tag>` is listed and one with a non-`arp-` slug is not (create and delete both in `finally`).
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** both.
- [ ] **Step 4: Run** unit tests -> PASS.
- [ ] **Step 5: Commit** `feat(bi): list embeddable dashboards`.

---

### Task 7: One "Dashboards (Superset)" tab

**Files:**
- Modify: `frontend/src/pages/portfolio-monitoring/SupersetBI.tsx`, `frontend/src/pages/PortfolioRiskMonitoringTool.tsx`, `frontend/src/api/client.ts`, `frontend/src/types.ts`, `frontend/src/lib/biEmbed.ts` (helpers), `frontend/tests/biEmbed.test.ts`
- Delete: `frontend/src/pages/portfolio-monitoring/PivotExplorer.tsx` (and any helper used only by it; check with grep before deleting)

**Interfaces:**
- Consumes: `GET /api/bi/dashboards` (Task 6) and the existing `/api/bi/design`, `/ask`, `/embed-token`.
- Produces: a single sub-tab `{ id: "dashboards", label: "Dashboards (Superset)" }` replacing `pivot` and `superset`; pure helper `pickDefaultDashboard(items: DashboardItem[], preferredSlug = "arp-risk-exposure"): DashboardItem | null` in `biEmbed.ts` (preferred slug if present, else first, else null).

- [ ] **Step 1: Failing tests (`node --test`):** `pickDefaultDashboard prefers arp-risk-exposure`, `falls back to the first item`, `returns null for an empty list`.
- [ ] **Step 2: Run** `cd frontend && npm test` -> FAIL.
- [ ] **Step 3: Implement:** a dashboard picker (select) fed by the new endpoint, defaulting via the helper; selecting a dashboard mounts the embed (reuse the existing embed lifecycle in `SupersetBI.tsx`); keep the "describe a dashboard" box and the draft notice; after a successful design, refresh the list and select the new dashboard; show a clear empty state ("No dashboards yet - run `arp bi bootstrap` or describe one") and an unconfigured state (503). Show a `Draft` badge for unpublished items. Remove the old `pivot` and `superset` entries from `SUB_TABS` and their renders and the Pivot Explorer import; keep types still used elsewhere. Follow DESIGN.md.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build` -> all pass.
- [ ] **Step 5: Commit** `feat(ui): one Dashboards (Superset) tab replaces Pivot Explorer, Generative BI and Superset BI`.

---

### Task 8: Docs and live end-to-end verification

**Files:**
- Modify: `README.md` (Risk Monitoring tab list, Superset BI section: provisioning, `arp-` slug opt-in, descriptions), `docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md` where it describes the tabs, `.env.example` only if a new variable appeared (none expected)

- [ ] **Step 1: Docs:** document that hand-built dashboards opt in by setting the dashboard slug to `arp-<name>` in Superset's Properties; that `arp bi bootstrap` provisions `arp-risk-exposure`; that Pivot Explorer and Generative BI are gone and where their jobs went; the Pivot weighted-average climate pivots now live only in Standard Analytics.
- [ ] **Step 2: Verification:** `ruff check` and `ruff format --check` on touched files; full backend suite (failures equal the Task 1 baseline set); frontend `npm test && npm run lint && npm run build`; the whole live suite once against a real Superset 5.0.0 (`pytest -m live_superset`).
- [ ] **Step 3: End-to-end on real data:** with the four imported DWS funds in Postgres (`arp portfolio import-constituents` with `ARP_PORTFOLIO_BACKEND=postgres`), run `arp bi bootstrap`, start backend and frontend, open the Dashboards tab in Chromium, confirm `arp-risk-exposure` is the default, all charts render with ~EUR 400.6M total, a native filter changes the numbers, and an `arp-` hand-made dashboard shows in the picker; save screenshots to the scratchpad directory. Leave nothing running.
- [ ] **Step 4: Commit** `docs: Superset foundation phase 1`.

---

## Self-Review notes

- Spec coverage: removal (T1), `holdings_history` (T2), descriptions (T3), native filters + templates + provisioning (T4, T5), list endpoint + `arp-` opt-in (T6), one tab replacing three (T7), docs/testing/verification (T8). Phases 2 and 3 are untouched by design.
- Risk carried: the cross-dataset native-filter behaviour is decided by the Task 4 spike; Task 5's template adapts (one filter per dataset if needed).
- Order: 1 removes the `genbi` tab before Task 7 reshapes the tab list; 2 precedes 5 (the time chart needs `holdings_history`); 4 precedes 5; 6 precedes 7.
