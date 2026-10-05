# Portfolio Monitoring Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align Risk Monitoring with Stewardship Monitoring: monthly ESG/holdings intake, stored shared-shape triggers, Superset for all analytics, a hybrid Company Profile, and removal of Governance & Audit.

**Architecture:** Keep both rule engines (`AlertRule` evaluator, stewardship ZEN rules). Add a monthly run that ingests, evaluates both, stores triggers and publishes flat rows to Postgres for Superset. Entity resolution stays; its review decisions move out of `governance.py`.

**Tech Stack:** Python 3.11, FastAPI, pytest (asyncio_mode=auto), Pydantic, Postgres + Apache Superset (opt-in), React/TypeScript (Vite), `node --test` for frontend.

**Spec:** `docs/superpowers/specs/2026-10-05-portfolio-monitoring-alignment-design.md`

## Global Constraints

- Ruff line length 130. Backend tests: `tests/test_<area>.py`, portfolio tests build `PortfolioStore(tmp_path)` inline (no store fixture exists).
- Frontend tests are pure TS: `npm test` = `node --test --experimental-strip-types tests/*.test.ts`; lint `npm run lint` (oxlint); build `npm run build`. No new frontend dependencies, no custom grid library.
- No role checks added on any write route. The `AlertRule` evaluator is not replaced or merged into ZEN.
- Superset reads only `bi` views over Postgres. WACI / financed emissions stay computed in Python.
- ESG provider API format is unknown: build a pluggable mapping plus an auth hook (credentials from environment, never in the repo).
- Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_018betDPYivWpvk1u9mvbZ14`. Work on branch `ccr-aa44f76b-aa3l67`; any PR targets `main`.
- **Deviation from spec:** the generic event-log store methods (`append_governance_event`, `list_governance_events`, `governance_events_path`) are kept with their names, because the entity-resolution decision log and the load records need an append-only log. Only the governance module, schemas, routes and tab are deleted.

## Review Focus

- Re-uploading an identical ESG file for the same month must report `unchanged` and add no duplicate observations.
- An ESG file with comma decimals, blank values, or a `company_id` not in the universe must produce row errors and write nothing (no partial load).
- A failed or missing holdings or ESG load for a month blocks the monthly run: no alerts or triggers are evaluated for that month.
- Empty portfolio universe: stewardship returns no triggers plus a note, and does not fall back to the synthetic sample or crash.
- Existing `governance/events.jsonl` files containing `climate_conflict` or policy/owner events must not break the entity-resolution review list.

## File Structure

| File | Responsibility |
|---|---|
| `backend/arp/portfolio/resolution_review.py` (new) | Pending entity-resolution reviews and their decision log |
| `backend/arp/portfolio/climate/esg_intake.py` (new) | ESG template, validation, ingest (mirrors `arp/holdings`) |
| `backend/arp/portfolio/climate/esg_api_source.py` (new) | Monthly API pull with pluggable mapping and auth hook |
| `backend/arp/portfolio/loads.py` (new) | Load records per (kind, source, month); blocking check |
| `backend/arp/schemas/triggers.py` (new) | Shared trigger shape and `from_alert` |
| `backend/arp/stewardship/trigger_store.py` (new) | Stored stewardship triggers with status and `is_new` |
| `backend/arp/portfolio/monthly_run.py` (new) | Orchestrates one monthly run |
| `backend/arp/bi/published.py` (new) | Publishes flat rows for Superset datasets |
| `backend/arp/bi/templates/*.json` (new) | Provisioned dashboards |
| `frontend/src/pages/portfolio-monitoring/ProfileActionStrip.tsx` (new) | Engagements, triggers, alerts strip |

---

### Task 1: Remove governance backend; keep entity-resolution review

**Files:**
- Create: `backend/arp/portfolio/resolution_review.py`, `backend/tests/test_resolution_review.py`
- Modify: `backend/arp/api/routers/portfolio.py` (lines ~42-44, 120-135, 349-427), `backend/arp/cli/portfolio.py:36`, `backend/arp/portfolio/mock_data.py` (~204, 253), `backend/arp/config.py:339`, `backend/arp/schemas/portfolio.py`
- Delete: `backend/arp/portfolio/governance.py`, `backend/arp/schemas/governance.py`, `backend/arp/portfolio/climate/validation.py`, `backend/tests/test_portfolio_governance.py`, `backend/tests/test_climate_validation.py`

**Interfaces:**
- Produces (`resolution_review.py`): `list_pending(store: PortfolioStore) -> list[dict]`; `record_decision(store, item_key: str, decision: str, decided_by: str, reason: str = "", override_value: str | None = None) -> ResolutionDecision`; `latest_decisions(store) -> dict[str, dict]`. `ResolutionDecision` (Pydantic) moves into `schemas/portfolio.py`, same `decision` values `GovernanceDecision` has today.
- Routes: `GET /api/portfolio/resolution-review`, `POST /api/portfolio/resolution-review/decisions`. Review threshold comes from `settings.portfolio_confidence_review_threshold`.

- [ ] **Step 1: Write failing tests** in `test_resolution_review.py`: `test_pending_lists_securities_below_threshold`, `test_record_decision_removes_item_from_pending` (assert the item is absent from `list_pending` after `accept`), `test_latest_decision_wins`, `test_legacy_climate_conflict_events_are_ignored` (pre-append a `decision_recorded` event with `item_type="climate_conflict"` via `store.append_governance_event`; assert `list_pending` and `latest_decisions` do not raise and exclude it).
- [ ] **Step 2: Run** `cd backend && pytest tests/test_resolution_review.py -v`; expected FAIL (module missing).
- [ ] **Step 3: Implement `resolution_review.py`** reusing `store.list_resolutions_needing_review()` and the event log methods; port only the entity-resolution logic from `governance.py` (lines 19-118).
- [ ] **Step 4: Delete** the files listed above; remove the `cross_check_and_store` call and the `climate_validation_tolerance_pct` parameter from `mock_data.generate_demo_dataset`, `config.py`, router and CLI; replace `governance.get_current_policy` uses with the settings value; replace the `/governance/*` routes with the two new routes.
- [ ] **Step 5: Run** `cd backend && ruff check . && pytest tests/test_resolution_review.py tests/test_portfolio_entity_resolution.py tests/test_datapoint_mapping.py tests/test_postgres_portfolio_store.py tests/test_portfolio_store_parity.py -v`; expected PASS. Fix any remaining reference found by `grep -rn "governance\|climate.validation" backend/arp backend/tests`.
- [ ] **Step 6: Commit** `refactor: remove governance backend, keep entity-resolution review`.

### Task 2: Remove Governance tab; move review panel into Holdings Intake

**Files:**
- Create: `frontend/src/pages/portfolio-monitoring/ResolutionReviewPanel.tsx`
- Modify: `frontend/src/pages/PortfolioRiskMonitoringTool.tsx:13-71` (`SUB_TABS`, render switch), `frontend/src/pages/portfolio-monitoring/HoldingsIntake.tsx`, `frontend/src/api/client.ts` (governance functions from ~L679), `frontend/src/types.ts`, `frontend/tests/subTabs.test.ts`
- Delete: `frontend/src/pages/portfolio-monitoring/GovernanceAudit.tsx`

**Interfaces:**
- Consumes: Task 1 routes. Produces: `api.listResolutionReview(): Promise<ResolutionReviewItem[]>`, `api.recordResolutionDecision(body: { item_key: string; decision: string; reason?: string; override_value?: string }): Promise<ResolutionDecision>`.

- [ ] **Step 1: Update `tests/subTabs.test.ts`**: assert `SUB_TABS` ids no longer include `"governance"` and `resolveSubTab("governance")` falls back to the default.
- [ ] **Step 2: Run** `cd frontend && npm test`; expected FAIL on the new assertions.
- [ ] **Step 3: Implement** the removal of the sub-tab and the new panel (accept / override / reject on each pending item), rendered inside `HoldingsIntake.tsx` below the holder table.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`; expected PASS.
- [ ] **Step 5: Commit** `feat: move entity-resolution review into Holdings Intake`.

### Task 3: ESG upload (CSV / Excel) and load records

**Files:**
- Create: `backend/arp/portfolio/climate/esg_intake.py`, `backend/arp/portfolio/loads.py`, `backend/arp/portfolio/climate/mappings/default.json`, `backend/tests/test_esg_intake.py`
- Modify: `backend/arp/api/routers/portfolio.py` (new routes), `frontend/src/pages/portfolio-monitoring/HoldingsIntake.tsx`, `frontend/src/api/client.ts`

**Interfaces:**
- Produces (`esg_intake.py`): `ESG_TEMPLATE_COLUMNS: list[str]` (`company_id` or `isin`, plus one column per field in `climate/schemas.py`: scope1, scope2, scope3, carbon intensity, EVIC, green revenue %); `validate_esg(raw: list[dict], *, month: str, known_company_ids: set[str], decimal: str = ".") -> ValidatedEsg`; `ingest_esg(store, validated: ValidatedEsg, *, provider: str, month: str, source_ref: str | None) -> EsgIntakeResult` (`status: "written" | "unchanged"`, `rows: int`). Reuses `arp.holdings.file_source.read_rows` and `Mapping`.
- Produces (`loads.py`): `LoadRecord(kind: Literal["holdings","esg"], source_id: str, month: str, status: Literal["ok","failed"], content_hash: str, detail: str, at: str)`; `record_load(store, rec: LoadRecord) -> None`; `latest_load(store, kind: str, source_id: str, month: str) -> LoadRecord | None`. Stored through the event log (`event_type="load_recorded"`).
- Routes: `POST /api/portfolio/esg/upload` (form: `file`, `provider`, `month`), `GET /api/portfolio/esg/template?format=csv|xlsx`. Observations written with `DataPointObservation(source="internal_api", period=month, notes="file:<ref>")`.

- [ ] **Step 1: Write failing tests**: `test_valid_file_writes_one_observation_per_company_field`, `test_identical_reupload_is_unchanged_and_adds_no_observations`, `test_changed_reupload_appends_new_values_latest_wins`, `test_comma_decimals_parsed_with_decimal_comma`, `test_unknown_company_id_rejects_whole_file_and_writes_nothing`, `test_blank_value_is_row_error`, `test_failed_validation_records_failed_load`, `test_template_has_all_climate_field_columns`.
- [ ] **Step 2: Run** `pytest tests/test_esg_intake.py -v`; expected FAIL.
- [ ] **Step 3: Implement** both modules and routes; content hash is a SHA-256 of the validated rows, compared with `latest_load` for (`esg`, provider, month).
- [ ] **Step 4: Run** `pytest tests/test_esg_intake.py tests/test_holdings_intake.py -v`; expected PASS. Add the ESG upload form and template links to Holdings Intake; run `npm run build`.
- [ ] **Step 5: Commit** `feat: ESG upload with idempotent monthly loads`.

### Task 4: Monthly API pull with pluggable provider and auth

**Files:**
- Create: `backend/arp/portfolio/climate/esg_api_source.py`, `backend/tests/test_esg_api_source.py`
- Modify: `backend/arp/config.py` (settings), `backend/arp/holdings/api_source.py` (record a load after `pull_holder`)

**Interfaces:**
- Produces: `pull_esg(store, settings: Settings, month: str, provider: str = "default", fetcher: Callable[[str, dict], bytes] | None = None) -> EsgIntakeResult`. Settings: `esg_api_base_url: str | None`, `esg_api_token: str | None` (env `ARP_ESG_API_URL`, `ARP_ESG_API_TOKEN`). The fetcher receives the URL and headers (`Authorization: Bearer <token>`); a missing URL or token raises `ValueError` and records a `failed` load. Output bytes go through `read_rows` + `validate_esg` + `ingest_esg`, so API and file share one path.
- Consumes: Task 3. Also make `holdings.api_source.pull_holder` call `record_load` with `kind="holdings"` on success and failure.

- [ ] **Step 1: Write failing tests** with a fake `fetcher`: `test_pull_uses_same_ingest_as_upload` (asserts identical observations to uploading the same bytes), `test_missing_credentials_records_failed_load`, `test_fetcher_error_records_failed_load_and_raises`, `test_token_sent_as_bearer_and_never_logged` (assert token absent from the failed-load `detail`), `test_pull_twice_same_month_is_unchanged`, `test_holdings_pull_records_load`.
- [ ] **Step 2: Run** `pytest tests/test_esg_api_source.py -v`; expected FAIL.
- [ ] **Step 3: Implement** with `httpx` only if already a dependency (check `pyproject.toml`); otherwise `urllib.request`.
- [ ] **Step 4: Run** `pytest tests/test_esg_api_source.py tests/test_holdings_api.py -v`; expected PASS.
- [ ] **Step 5: Commit** `feat: monthly ESG API pull with auth hook`.

### Task 5: Stewardship uses the real issuer universe by default

**Files:**
- Modify: `backend/arp/stewardship/universe.py` (`HouseUniverseSetting.get` default), `backend/arp/stewardship/process.py:64-103`, `backend/tests/test_stewardship_universe.py`, `backend/tests/test_api_stewardship.py`, `backend/tests/test_portfolio_to_stewardship.py`

**Interfaces:** `HouseUniverseSetting.get()` default becomes `{"source": "portfolio", "set_by": None, "set_at": None}`; `"sample"` stays selectable.

- [ ] **Step 1: Write failing tests**: `test_default_source_is_portfolio`, `test_empty_portfolio_returns_note_and_no_triggers` (assert result has the `"No portfolio holdings loaded."` note, empty issuers, `monitoring.evaluate(...) == []`, and no sample data used).
- [ ] **Step 2: Run** `pytest tests/test_stewardship_universe.py -v`; expected FAIL.
- [ ] **Step 3: Implement** the default change; update stewardship tests that relied on the sample default to set `source="sample"` explicitly through `HouseUniverseSetting.set`.
- [ ] **Step 4: Run** `pytest tests/test_stewardship_universe.py tests/test_api_stewardship.py tests/test_portfolio_to_stewardship.py tests/test_stewardship_monitoring.py -v`; expected PASS.
- [ ] **Step 5: Commit** `feat: stewardship defaults to the real issuer universe`.

### Task 6: Shared trigger shape, stored stewardship triggers, wider alert feed

**Files:**
- Create: `backend/arp/schemas/triggers.py`, `backend/arp/stewardship/trigger_store.py`, `backend/tests/test_trigger_store.py`
- Modify: `backend/arp/stewardship/alerts_feed.py`, `backend/arp/api/routers/stewardship.py` (new routes), `frontend/src/api/client.ts`

**Interfaces:**
- Produces (`triggers.py`): `UnifiedTrigger` (`trigger_id: str`, `source: Literal["risk_alert","stewardship"]`, `issuer_id: str`, `type: str`, `theme: str`, `severity: Literal["low","medium","high"]`, `reason: str`, `status: Literal["open","acknowledged","resolved"]`, `first_seen_month: str`, `is_new: bool`); `from_alert(alert: Alert) -> UnifiedTrigger` (theme = `"climate_data"` for `threshold_breach`, `"controversy"` for `news_controversy`; severity fixed `"medium"`, marked `# ponytail: alerts carry no severity; derive one when rules gain it`).
- Produces (`trigger_store.py`): `TriggerStore(root: Path)`; `record_run(self, month: str, triggers: list[dict]) -> list[UnifiedTrigger]` (id = hash of issuer_id + rule; `is_new` true when absent from the previous month's run); `list_triggers(self, status: str | None = None) -> list[UnifiedTrigger]`; `transition(self, trigger_id: str, status: str, decided_by: str, reason: str = "") -> UnifiedTrigger`. Append-only JSONL under `settings.stewardship_streams_dir/triggers/events.jsonl`.
- Routes: `GET /api/stewardship/triggers?status=`, `POST /api/stewardship/triggers/{trigger_id}/transition`.
- `alerts_feed.issuer_fields(alerts)` additionally returns `alert.open_<category>` for every `AlertCategory` and `alert.open_total`; the two existing keys keep their values.

- [ ] **Step 1: Write failing tests**: `test_record_run_marks_first_run_triggers_new`, `test_second_run_same_trigger_not_new`, `test_trigger_absent_next_month_stays_listed_until_resolved`, `test_transition_changes_status_and_keeps_history`, `test_unknown_trigger_id_raises_keyerror`, `test_from_alert_maps_category_to_type_and_theme`, `test_issuer_fields_keeps_existing_keys_and_adds_total`.
- [ ] **Step 2: Run** `pytest tests/test_trigger_store.py tests/test_stewardship_monitoring.py -v`; expected FAIL.
- [ ] **Step 3: Implement** the modules and routes.
- [ ] **Step 4: Run** the same command; expected PASS.
- [ ] **Step 5: Commit** `feat: stored stewardship triggers with shared shape`.

### Task 7: Monthly run

**Files:**
- Create: `backend/arp/portfolio/monthly_run.py`, `backend/tests/test_monthly_run.py`
- Modify: `backend/arp/api/routers/portfolio.py` (route), `backend/arp/cli/portfolio.py` (command), `backend/arp/portfolio/monitoring/scheduler.py`

**Interfaces:**
- Produces: `run_month(store: PortfolioStore, settings: Settings, month: str, *, portfolio_ids: list[str], esg_provider: str = "default") -> MonthlyRunResult` (`status: "ran" | "blocked"`, `blocked_reasons: list[str]`, `alerts: int`, `triggers: int`). Steps in order: check `latest_load` is `ok` for each portfolio holding load and the ESG load for `month` (else `blocked` with reasons and nothing evaluated); `evaluate_threshold_rules(store, as_of=<month end>)`; `evaluate_news_triggers(store)`; stewardship `monitoring.evaluate` over `universe.from_portfolio(store)` merged with `alerts_feed.issuer_fields`; `TriggerStore.record_run`.
- Routes/CLI: `POST /api/portfolio/monthly-run` body `{month}`; `arp portfolio monthly-run --month YYYY-MM`. The scheduler calls `run_month` for the previous month.

- [ ] **Step 1: Write failing tests**: `test_blocked_when_holdings_load_missing`, `test_blocked_when_esg_load_failed_evaluates_nothing` (assert no alert events written), `test_runs_all_steps_in_order_on_seeded_demo`, `test_rerun_same_month_creates_no_duplicate_alerts_or_new_flags`, `test_empty_universe_runs_with_zero_triggers`.
- [ ] **Step 2: Run** `pytest tests/test_monthly_run.py -v`; expected FAIL.
- [ ] **Step 3: Implement** `run_month` and wire the route, CLI and scheduler.
- [ ] **Step 4: Run** `pytest tests/test_monthly_run.py tests/test_portfolio_monitoring_evaluator.py -v`; expected PASS.
- [ ] **Step 5: Commit** `feat: monthly monitoring run`.

### Task 8: Publish datasets for Superset

**Files:**
- Create: `backend/arp/bi/published.py`, `backend/tests/test_bi_published.py`
- Modify: `backend/arp/storage/postgres_portfolio_store.py`, `backend/arp/storage/portfolio_store.py` (no-op), `backend/arp/bi/views.py` (`_VIEWS`), `backend/arp/bi/catalog.py` (`VIEW_DATASETS`), `backend/arp/portfolio/monthly_run.py`, `backend/tests/test_bi_views.py`, `backend/tests/test_bi_catalog.py`

**Interfaces:**
- Store: `publish_rows(dataset: str, month: str, rows: list[dict]) -> None` on both stores (Postgres: table `bi_published(dataset text, month text, row jsonb)`, replacing that dataset+month; file store: no-op with `# ponytail: Superset needs Postgres`).
- `published.py`: `climate_metric_rows(store, month, portfolio_ids) -> list[dict]` (portfolio_id, as_of_date, waci, financed_emissions_tco2e, coverage_pct, uncovered_market_value_eur) built with `climate/metrics.py` and `aggregation.py`; `alert_rows(store) -> list[dict]`; `trigger_rows(triggers: list[UnifiedTrigger]) -> list[dict]`; `profile_rows(store, month) -> list[dict]` (company_id, company_name, field_id, field_name, value, unit, as_of, source).
- Views/datasets: `portfolio_climate_metrics`, `alerts`, `triggers`, `company_profile`, each cast with `bi.safe_date` where temporal; `VIEW_DATASETS` metrics: WACI avg, coverage avg, open alerts count, open triggers count.

- [ ] **Step 1: Write failing tests**: `test_climate_metric_rows_match_waci_and_pcaf_for_demo_data`, `test_alert_rows_include_status_and_portfolio`, `test_publish_rows_replaces_same_dataset_month_only` (Postgres test, same skip pattern as `test_postgres_portfolio_store.py`), `test_views_and_catalog_columns_match` (extend the existing parity test).
- [ ] **Step 2: Run** `pytest tests/test_bi_published.py tests/test_bi_views.py tests/test_bi_catalog.py -v`; expected FAIL.
- [ ] **Step 3: Implement**; call the four publishers at the end of `run_month`.
- [ ] **Step 4: Run** the same command plus `tests/test_monthly_run.py`; expected PASS.
- [ ] **Step 5: Commit** `feat: publish climate, alert, trigger and profile datasets`.

### Task 9: Provisioned dashboards

**Files:**
- Create: `backend/arp/bi/templates/climate_overview.json`, `alerts_triggers.json`, `company_profile.json`
- Modify: `backend/tests/test_bi_templates.py`

**Interfaces:** each template follows the shape of `backend/arp/bi/templates/exposure.json` (read it first). Slugs: `arp-climate-overview` (WACI and financed emissions by portfolio over months, coverage), `arp-alerts-triggers` (counts by status and by issuer), `arp-company-profile` (emissions, intensity, EVIC, green revenue share, exposure by portfolio; native filter on `company_id`). Only chart types in `VIZ_ALLOWLIST`.

- [ ] **Step 1: Write failing test** `test_all_templates_load_and_validate_against_catalog` (every dataset and column referenced exists in `VIEW_DATASETS`; slugs start with `arp-`) and `test_company_profile_template_has_company_id_filter`.
- [ ] **Step 2: Run** `pytest tests/test_bi_templates.py -v`; expected FAIL.
- [ ] **Step 3: Write the three templates.**
- [ ] **Step 4: Run** the same command; expected PASS. Where a Superset instance is available, run `arp bi bootstrap` and open each dashboard (the `live_superset` marker covers this; it is not run in CI here).
- [ ] **Step 5: Commit** `feat: provision climate, alert and profile dashboards`.

### Task 10: Company Profile (action strip + embedded dashboard)

**Files:**
- Create: `frontend/src/pages/portfolio-monitoring/ProfileActionStrip.tsx`, `frontend/tests/profileEmbed.test.ts`
- Modify: `frontend/src/pages/portfolio-monitoring/CompanyProfiles.tsx`, `frontend/src/lib/biEmbed.ts`, `frontend/src/api/client.ts`, `backend/arp/bi/superset_client.py` (guest-token request)

**Interfaces:**
- `biEmbed.ts`: `profileEmbedParams(companyId: string | null): { rls: { clause: string }[] }`, returning `[]` when `companyId` is null and a clause on `company_id` (value escaped) otherwise.
- Backend guest-token function gains an optional `rls: list[dict]` argument passed through to Superset. **Spike first:** confirm RLS in the guest token works with this repo's embed SDK usage (`SupersetBI.tsx`); if the SDK path cannot carry it, fall back to a native-filter value and record the finding in the spec.
- Strip data: `api.listTriggers(status?)`, `api.listAlerts()` (existing), `api.openEngagementFromTrigger` (existing), `api.transitionTrigger(id, status)`, `api.transitionAlert` (existing).

- [ ] **Step 1: Write failing test** in `profileEmbed.test.ts`: `null` gives `[]`; `"abc"` gives a clause containing `company_id` and `abc`; a company id containing a single quote is escaped (no unescaped quote in the clause).
- [ ] **Step 2: Run** `cd frontend && npm test`; expected FAIL.
- [ ] **Step 3: Implement** the helper, the backend pass-through, the strip (engagements, triggers with acknowledge/resolve/open-engagement, alerts with transition, issuer picker, as-of month) and the page layout (strip above, embedded `arp-company-profile` below; empty-state text when the issuer has no data).
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build` and `cd backend && pytest tests/test_bi_*.py -v`; expected PASS.
- [ ] **Step 5: Commit** `feat: hybrid company profile`.

### Task 11: Remove Standard Analytics tab

**Files:**
- Modify: `frontend/src/pages/PortfolioRiskMonitoringTool.tsx`, `frontend/tests/subTabs.test.ts`, `frontend/src/lib/subTabs.ts` (default tab)
- Delete: `frontend/src/pages/portfolio-monitoring/StandardAnalytics.tsx`

**Interfaces:** `SUB_TABS` loses `"standard"`; the default sub-tab becomes `"dashboards"`. Backend aggregation and climate endpoints stay (Ask the Portfolio and the publishers use them). Do this task last, after Task 9, so no gap exists.

- [ ] **Step 1: Update `subTabs.test.ts`** to assert `"standard"` is gone and the default resolves to `"dashboards"`.
- [ ] **Step 2: Run** `npm test`; expected FAIL.
- [ ] **Step 3: Implement** the removal.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`; expected PASS.
- [ ] **Step 5: Commit** `feat: Superset replaces in-app analytics tab`.

---

## Self-review notes

- Spec coverage: intake (Tasks 3-4), entity resolution move (1-2), Governance removal (1-2), rule alignment (5-7), Superset datasets and dashboards (8-9), Company Profile (10), Standard Analytics removal (11), unverified issuer-to-dashboard link (Task 10 spike). `climate/validation.py` open question resolved: only `mock_data.py` called it, so it is deleted in Task 1.
- Known unknowns for the implementer: the full `AlertStatus` member list (read `schemas/portfolio_monitoring.py`), the exact `GovernanceDecision.decision` values (read `schemas/governance.py` before deleting), the guest-token function name in `bi/superset_client.py`, and the `exposure.json` template shape.
