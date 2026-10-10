# Postgres Company Foundation (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Postgres + pgvector the required, authoritative store for companies, fields, runs, review and facts, keyed on one stable company UUID, and ship a one-company view.

**Architecture:** First move every caller off run-file paths onto `RunStore` methods (still file-backed), then add the new tables, then swap the implementations behind the same methods to `arp/db/*`. Every per-field value becomes an insert-only observation with citations; one function (`arp/db/observations.record`) maintains the current-fact layer. Legacy projections and the file run store are deleted last, after an idempotent import and a verify command.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync sessions), psycopg 3, pgvector, Postgres 16, pytest (asyncio_mode=auto), React/TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-10-10-postgres-company-foundation-design.md`

## Global Constraints

- Dates are `date`, timestamps `timestamptz`. No date-as-string columns in any new table.
- Status/kind columns are Postgres enums (SQLAlchemy `Enum(StrEnum, name=...)`).
- Every company reference in a new or re-keyed table is `company_id uuid` with FK to `companies.id`.
- Insert-only tables (`field_observations`, `value_citations`, `review_decisions`, `review_cosigns`) are never `UPDATE`d. `company_facts` is only updated to close a row (`valid_to`, `superseded_by`).
- Field ids match `^(fld_[a-z0-9]+|prov:[a-z0-9_]+:[a-z0-9_]+)$` (DB CHECK). Ids are never reused or deleted.
- Provider rows never create companies. Provider metrics are never mapped onto extracted fields.
- `company_facts` is written only by `arp/db/observations.py`.
- New tables live in `backend/arp/db/models.py` on the existing `Base` from `arp/storage/postgres_models.py`; DDL that `create_all` cannot express goes into `SCHEMA_STEPS` in `arp/storage/postgres_schema.py`.
- Pydantic models in `arp/schemas/` stay the API contract; existing API response shapes do not change.
- Tests needing a database use `ARP_TEST_POSTGRES_DSN`. From Task 5 on, the suite **fails** (not skips) without it, with the message `ARP_TEST_POSTGRES_DSN is required: docker compose up -d postgres`.
- Commits end with the session attribution lines; branch `ccr-c6d8f65a-wk7g7d`; PRs target `main`.

## Decisions this plan adds to the spec

- **`CompanyRef.entity_id: UUID | None`** carries the company UUID through pipelines. `CompanyRef.company_id` stays the universe id because document directories, prompts and logs use it; every database write uses `entity_id`. (The spec's "pipeline passes only `company_id`" is met at the database boundary.)
- **`review_items.item_key`** is kept as the API-facing key (`UNIQUE (run_id, item_key)`): the review endpoints and frontend address items by it. Collisions no longer matter because facts key on `(company_id, field_id, period_end, basis)` via `observation_id`, not on `item_key`.
- **Parsed-text cache** (`content.db` text/file-identity tables) stays SQLite: it is derived and costs only re-parsing. The document registry and embeddings move to Postgres.

## Review Focus

1. A universe row whose `company_id` changed between two universe files but has the same LEI must attach to the same company and gain the new UNIVERSE alias, not create a second company. → Task 3 test `test_renamed_universe_id_same_lei_attaches`.
2. The same value in two representations (`1000` vs `1000.0`, `"1,000"` normalised) must be a no-op, not a new fact version. → Task 7 test `test_equal_numeric_values_do_not_supersede` (reuse `orchestration/review_queue.same_value`).
3. Re-sending an identical provider payload must record the load as unchanged and write zero observations. → Task 8 test `test_identical_payload_is_unchanged`.
4. `arp db import` interrupted halfway and re-run must finish with no duplicate rows. → Task 11 test `test_import_resumes_after_interruption`.
5. Company alias in a URL with different case/whitespace (`lei: 7ltw…`) must resolve to the same company. → Task 9 test `test_alias_lookup_is_normalised`.

---

## File Structure

```
backend/arp/db/__init__.py
backend/arp/db/session.py         engine(), transaction(), require_dsn()
backend/arp/db/models.py          all new ORM tables + enums
backend/arp/db/companies.py       resolve / register / merge
backend/arp/db/fields.py          field registry + table-backed SchemaRegistry
backend/arp/db/runs.py            table-backed RunStore
backend/arp/db/documents.py       table-backed DocumentRegistry
backend/arp/db/observations.py    ObservationIn/CitationIn, record(), apply_decision(), fact rules
backend/arp/db/to_observations.py per-run-type result → observations (pure)
backend/arp/db/providers.py       data sources, loads, provider ingest
backend/arp/db/company_view.py    queries behind the company API
backend/arp/db/importer.py        arp db import / verify
backend/arp/api/routers/companies.py
frontend/src/pages/Company.tsx (+ components under frontend/src/pages/company/)
backend/tests/db/conftest.py      pg fixtures (moved to tests/conftest.py in Task 5)
```

---

### Task 1: RunStore row methods (file-backed) and path guard

**Files:**
- Modify: `backend/arp/storage/run_store.py`
- Modify: every caller of `run_store.*_path(` / `store.results_path(` (≈100 sites, 59 files; find with `grep -rnE "(run_)?store\.\w+_path\(" backend/arp`)
- Modify: `backend/arp/orchestration/batch_runner.py` (`read_done_keys`), `backend/arp/orchestration/jobs.py:171`
- Test: `backend/tests/test_run_store_rows.py`, `backend/tests/test_no_run_paths.py`

**Interfaces:**
- Produces on `RunStore` (all `run_id: str`, rows are `dict`):
  - `read_results(run_id) -> list[dict]`, `append_result(run_id, row) -> None`
  - `read_errors(run_id) -> list[dict]`, `append_error(run_id, row) -> None`
  - `read_review_queue(run_id) -> list[dict]`, `append_review_item(run_id, row) -> None`
  - `read_decisions(run_id) -> list[dict]`, `append_decision_row(run_id, row) -> None`
  - `read_cosigns(run_id) -> list[dict]`, `append_cosign(run_id, row) -> None`
  - `read_restatements(run_id) -> list[dict]`, `append_restatement(run_id, row) -> None`
  - `read_events(run_id) -> list[dict]`, `append_event(run_id, row) -> None`
  - `read_snapshot(run_id, snapshot_id) -> dict | None`, `save_snapshot(run_id, snapshot_id, data: dict) -> None`
  - `save_companies(run_id, companies: list[CompanyRef]) -> None` (pair of existing `load_companies`)
  - `done_keys(run_id, *, include_errors: bool = False) -> set[str]` (replaces `read_done_keys(path, path)`)
- `*_path` methods become private (`_results_path`, …).

- [ ] **Step 1: Write failing tests** in `test_run_store_rows.py`: for each read/append pair, `append` two rows then `read` returns them in order; `read_*` on an unknown run returns `[]`; `done_keys` returns the `_key` of results (plus errors when `include_errors=True`); `read_snapshot` of a missing snapshot is `None`.
- [ ] **Step 2: Run** `pytest tests/test_run_store_rows.py -v` — Expected: FAIL (`AttributeError: 'RunStore' object has no attribute 'read_results'`).
- [ ] **Step 3: Implement** the methods in `run_store.py` as thin wrappers over the existing paths + `read_jsonl`/`append_jsonl`.
- [ ] **Step 4: Run** `pytest tests/test_run_store_rows.py -v` — Expected: PASS.
- [ ] **Step 5: Write the guard test** `test_no_run_paths.py::test_no_path_access_outside_run_store`: walks `backend/arp/**/*.py` except `arp/storage/run_store.py` and `arp/db/runs.py`, asserts no line matches `r"\b\w*store\.\w+_path\("` (excluding `overrides_path`, `output_path`, `file_path`, `template_source_path`, which belong to other stores — list them explicitly in the test).
- [ ] **Step 6: Run** it — Expected: FAIL listing the call sites.
- [ ] **Step 7: Migrate every listed call site** onto the Task 1 methods; rename `*_path` to `_*_path`; make `read_done_keys` call `run_store.done_keys`.
- [ ] **Step 8: Run** `pytest -q` (whole suite) — Expected: same pass count as before the task, guard test PASS.
- [ ] **Step 9: Commit** `refactor(storage): route run file access through RunStore methods`

---

### Task 2: New tables and the Postgres test harness

**Files:**
- Create: `backend/arp/db/__init__.py`, `backend/arp/db/session.py`, `backend/arp/db/models.py`
- Modify: `backend/arp/storage/postgres_schema.py` (import `arp.db.models` so `create_all` sees it; add steps)
- Create: `backend/tests/db/conftest.py`, `backend/tests/db/test_schema.py`
- Modify: `backend/tests/postgres_helpers.py` (`reset_postgres_tables` → one `TRUNCATE … RESTART IDENTITY CASCADE` over all tables in `Base.metadata` except `schema_migrations`)

**Interfaces:**
- Produces `arp.db.session`:
  - `engine(dsn: str | None = None) -> Engine` (defaults to `get_settings().postgres_dsn`; wraps `arp.storage.postgres.get_engine`)
  - `transaction(dsn: str | None = None) -> ContextManager[Session]` (commit on exit, rollback on exception)
  - `require_dsn(settings) -> str` raises `RuntimeError("ARP_POSTGRES_DSN is required …")` when unset
- Produces `arp.db.models` ORM classes and enums, columns exactly as spec §2:
  `Company, CompanyIdentifier, Field, FieldDefinition, DataSchema, DataSchemaField, ProviderMetricCode, Run, RunCompany, RunResult, RunError, RunHeldDocument, Document, DataSource, SourceLoad, FieldObservation, ValueCitation, ReviewItem, ReviewDecision, ReviewCosign, CompanyFact`.
  Enums: `IdScheme, FieldKind, SourceKind, ValueState, Route, CitationRole, ItemState, DecisionKind, FactStatus, SourceKindDS (api|file), Licence, LoadStatus, RunStatus`.
  `ReviewItem` adds `item_key text`, `UNIQUE (run_id, item_key)`.
  `Document` is a new `documents` table (the old `document_registry` table is dropped in Task 12).
- Partial indexes via `Index(..., unique=True, postgresql_where=...)`:
  `uq_company_identifiers_active (scheme, value) WHERE valid_to IS NULL`,
  `uq_company_facts_current (company_id, field_id, period_end, basis) WHERE valid_to IS NULL`.
- `SCHEMA_STEPS` gains `SchemaStep("fields_id_check", …)` adding the CHECK constraint on `fields.field_id`.
- Test fixture `pg` (in `tests/db/conftest.py`): reads `ARP_TEST_POSTGRES_DSN`, runs `ensure_schema` once per session, truncates before each test, yields the DSN.

- [ ] **Step 1: Write failing tests** in `tests/db/test_schema.py`:
  - `test_tables_exist`: after `ensure_schema`, `inspect(engine).get_table_names()` ⊇ the 21 table names above.
  - `test_second_current_fact_is_rejected`: insert two `CompanyFact` rows same key, both `valid_to=None` → `IntegrityError`.
  - `test_closed_fact_allows_new_current`: first row `valid_to` set → second insert succeeds.
  - `test_bad_field_id_rejected`: `Field(field_id="Scope 1")` → `IntegrityError`; `"fld_ab12"` and `"prov:msci:carbon_emissions_scope_1"` succeed.
  - `test_active_alias_unique`: two active `CompanyIdentifier(LEI, X)` → `IntegrityError`; second with `valid_to` set is allowed.
  - `test_unknown_decision_rejected`: inserting `ReviewDecision(decision="maybe")` raises (`DataError`/`StatementError`).
- [ ] **Step 2: Run** `ARP_TEST_POSTGRES_DSN=… pytest tests/db/test_schema.py -v` — Expected: FAIL (`ModuleNotFoundError: arp.db`).
- [ ] **Step 3: Implement** `session.py`, `models.py`, the schema step, the truncate helper.
- [ ] **Step 4: Run** the same command — Expected: PASS. Run `pytest tests/test_postgres_schema.py -v` — Expected: PASS (existing schema tests unaffected).
- [ ] **Step 5: Commit** `feat(db): add company-foundation tables and Postgres test harness`

---

### Task 3: Company registry

**Files:**
- Create: `backend/arp/db/companies.py`, `backend/tests/db/test_companies.py`
- Modify: `backend/arp/schemas/common.py` (`CompanyRef.entity_id: UUID | None = None`)
- Modify: `backend/arp/universe.py` (new `resolve_universe(companies, session) -> list[CompanyRef]`)
- Modify: `backend/arp/schemas/issuer.py` (`issuer_key` → lookup), callers `arp/extraction/pipeline.py:177`, `arp/review/quality.py:147`
- Modify: `backend/arp/cli/db.py` (`arp db companies merge KEEP DROP`)

**Interfaces:**
- Produces in `arp.db.companies`:
  - `@dataclass Resolution: company_id: UUID | None; created: bool; conflict: list[UUID]` (non-empty `conflict` ⇒ `company_id is None`)
  - `normalise_identifier(scheme: IdScheme, value: str) -> str` (move from `storage/identifier_map.py`; CIK strips leading zeros, all upper-case, whitespace removed)
  - `identifiers_of(company: CompanyRef) -> list[tuple[IdScheme, str]]` in order LEI, ISIN, CIK, UNIVERSE, TICKER
  - `resolve(session, ids: list[tuple[IdScheme, str]], *, name: str, allow_create: bool, attrs: dict | None = None) -> Resolution`
  - `resolve_company(session, company: CompanyRef) -> Resolution` (= `resolve(..., allow_create=True)`)
  - `lookup(session, scheme: IdScheme, value: str) -> UUID | None`
  - `merge(session, keep: UUID, drop: UUID) -> None` (moves identifiers and every FK row; records `IdScheme.MERGED_INTO`)
- `issuer_key(company, session) -> tuple[str, str]` returns `(str(entity_id), "INTERNAL")`; signature change propagated to its 2 callers.
- `resolve_universe` sets `entity_id` on each `CompanyRef`; identity conflicts are returned in a second list for the run to record as `identity_conflict` errors.

- [ ] **Step 1: Write failing tests** in `tests/db/test_companies.py`:
  - `test_new_universe_row_creates_company_with_all_identifiers`
  - `test_renamed_universe_id_same_lei_attaches` (Review Focus 1): second row `company_id="SIE2"`, same LEI → same UUID, `created is False`, UNIVERSE aliases `{"SIE","SIE2"}` both active.
  - `test_conflicting_identifiers_return_conflict`: LEI → A, ISIN → B ⇒ `company_id is None`, `set(conflict) == {A, B}`, no rows written.
  - `test_provider_row_never_creates`: `allow_create=False`, unknown ids ⇒ `Resolution(None, False, [])`, company count unchanged.
  - `test_resolution_order_lei_first`: LEI matches A, UNIVERSE id unknown ⇒ A.
  - `test_merge_moves_identifiers_and_rows`: after `merge(keep, drop)`, `lookup` of drop's LEI returns `keep`; a `RunCompany` row for `drop` now points at `keep`.
  - `test_issuer_key_is_stable_across_security_master_upload`: key before and after adding an ISIN alias is equal.
- [ ] **Step 2: Run** `pytest tests/db/test_companies.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `companies.py`, `CompanyRef.entity_id`, `resolve_universe`, new `issuer_key`, CLI merge.
- [ ] **Step 4: Run** `pytest tests/db/test_companies.py -v` — Expected: PASS. Run `pytest -q` — Expected: no new failures.
- [ ] **Step 5: Commit** `feat(db): company registry with identifier aliases`

---

### Task 4: Field registry and table-backed SchemaRegistry

**Files:**
- Create: `backend/arp/db/fields.py`, `backend/tests/db/test_fields.py`
- Modify: `backend/arp/api/deps.py` (schema registry dependency), callers constructing `SchemaRegistry(` (grep)
- Delete (end of task): `backend/arp/storage/schema_registry.py` after callers moved; port `tests/test_schema_registry.py` to the new class

**Interfaces:**
- Produces in `arp.db.fields`:
  - `normalise_metric_code(code: str) -> str` (lowercase, `[^a-z0-9]+` → `_`, strip `_`)
  - `provider_field_id(source_slug: str, code: str) -> str` → `f"prov:{slug}:{normalise_metric_code(code)}"`
  - `class FieldIdCollision(ValueError)`
  - `register_provider_field(session, source_id: int, provider_code: str, *, name: str, unit: str | None, data_type: str) -> str` — existing code → its field_id; new code → new `Field(kind=provider)` + `FieldDefinition(version=1)` + `ProviderMetricCode`; normalised id already owned by a *different* code → raises `FieldIdCollision`
  - `alias_provider_code(session, source_id: int, new_code: str, field_id: str) -> None`
  - `ensure_extracted_field(session, field_id: str, definition: FieldDefinition) -> None` (inserts `Field` + definition version if missing)
  - `retire_field(session, field_id: str) -> None`
  - `class SchemaRegistry` with today's public methods and signatures: `get(schema_id, version=None)`, `list_index()`, `save(schema)`, `release(schema_id, version, released_by=None)`, `quality(field_id, version)`, `record_first_audit(field_id, version, audited_by)`; raises the same `UnreleasedFieldError` / `FieldVersionError` (moved here).

- [ ] **Step 1: Write failing tests** `tests/db/test_fields.py`:
  - `test_normalise_metric_code`: `"CARBON-Emissions Scope 1"` → `"carbon_emissions_scope_1"`.
  - `test_register_provider_field_is_idempotent`: same code twice → same id, one `fields` row.
  - `test_code_collision_raises`: `"Scope-1"` then `"scope_1"` from same source → `FieldIdCollision`.
  - `test_renamed_code_keeps_field`: `alias_provider_code(new_code="S1")` then `register_provider_field("S1")` returns the original id.
  - `test_retired_field_id_not_reissued`: retire then register same code → returns the retired id unchanged (no new row), and `ensure_extracted_field` on a retired `fld_` id raises.
  - `test_schema_registry_*`: port each test in `tests/test_schema_registry.py` to the new class with the `pg` fixture.
- [ ] **Step 2: Run** `pytest tests/db/test_fields.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `fields.py`; switch `deps.py` and callers; delete the old module and old test file.
- [ ] **Step 4: Run** `pytest tests/db/test_fields.py -v && pytest -q` — Expected: PASS, no new failures.
- [ ] **Step 5: Commit** `feat(db): stable field registry and Postgres schema registry`

---

### Task 5: Table-backed RunStore and review; Postgres required

**Files:**
- Create: `backend/arp/db/runs.py`, `backend/tests/db/test_runs.py`
- Modify: `backend/arp/api/deps.py:get_run_store`, every `RunStore(` construction in `backend/arp` (17 sites), `backend/arp/orchestration/review_queue.py` (only where it touched files directly)
- Modify: `backend/arp/config.py` (`postgres_dsn` description: required), `backend/arp/api/main.py` and CLI entry (call `require_dsn` at startup), `backend/pyproject.toml` (move `postgres` extra into `dependencies`)
- Modify: `backend/tests/conftest.py` (move `pg` fixture here; add `run_store` fixture), all 88 test files constructing `RunStore(tmp_path…)` → use the fixture
- Modify: `backend/arp/orchestration/batch_runner.py` (`run_company_batch` calls `resolve_universe` before work; records identity conflicts via `append_error` with `{"kind": "identity_conflict", "company_id": …, "conflict": [...]}`)

**Interfaces:**
- Consumes: Task 1 method set, Task 2 models, Task 3 `resolve_universe`.
- Produces `arp.db.runs.RunStore(dsn: str)` with **exactly** the Task 1 public methods plus `save_manifest`, `load_manifest`, `load_companies`, `list_runs(run_type=None)` (newest first by `created_at`), `extraction_runs()`, and `lock(run_id)` implemented as a transaction holding `SELECT … FOR UPDATE` on the `runs` row.
  - `append_result(run_id, row)` requires `row["_key"]`; resolves `company_id` uuid from `run_companies` via the UNIVERSE alias; `UNIQUE (run_id, company_id)` makes a re-append a no-op.
  - `append_review_item(run_id, row)` requires `row["item_key"]` and `row["company_id"]` (uuid as str); optional `row["observation_id"]`. `queue_for_review` gains a required keyword `company: CompanyRef` and sets `company_id` from `company.entity_id` — update its 5 call sites (`batch_runner.py:147,160`, `reground.py:132`, `transition_barrier/refresh/pipeline.py:70`, and the pipeline `review_items` callback). Item keys cannot supply the company: extraction keys lead with `issuer_key`, theme keys with the universe id.
- `arp.storage.run_store.RunStore` stays importable as an alias of `arp.db.runs.RunStore` until Task 12.

- [ ] **Step 1: Write failing tests** `tests/db/test_runs.py`: run every assertion of `tests/test_run_store_rows.py` against the table-backed store (parametrise that file over both stores); plus
  - `test_list_runs_newest_first`
  - `test_lock_serialises_manifest_updates`: two threads each `with store.lock(r): load→increment completed_count→save` 50 times → final count 100.
  - `test_reappending_same_company_result_is_noop`
  - `test_app_refuses_to_start_without_dsn`: `require_dsn(Settings(postgres_dsn=None))` raises `RuntimeError` mentioning `ARP_POSTGRES_DSN`.
- [ ] **Step 2: Run** `pytest tests/db/test_runs.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `arp/db/runs.py`; wire `deps`, startup check, dependency move.
- [ ] **Step 4: Switch tests**: `run_store` fixture returns `arp.db.runs.RunStore(pg)`; replace the 88 test constructions; the `pg` fixture fails with the Global Constraints message when the env var is missing.
- [ ] **Step 5: Run** `pytest -q` with `ARP_TEST_POSTGRES_DSN` set — Expected: all pass. Without it — Expected: errors with the required message.
- [ ] **Step 6: Commit** `feat(db): Postgres-backed RunStore and review queue; Postgres required`

---

### Task 6: Documents and embeddings in Postgres

**Files:**
- Create: `backend/arp/db/documents.py`, `backend/tests/db/test_documents.py`
- Modify: `backend/arp/storage/document_store.py` (registry collaborator → `arp.db.documents.DocumentRegistry`; embeddings collaborator → `PgVectorEmbeddingsStore` only)
- Modify: `backend/arp/storage/postgres_embeddings.py` (unchanged API; becomes the only implementation)
- Delete: `backend/arp/storage/postgres_document_registry.py` (superseded), SQLite embeddings code in `backend/arp/storage/embeddings_cache.py`

**Interfaces:**
- Produces `arp.db.documents.DocumentRegistry(dsn: str)` with the public methods of today's `arp/storage/document_registry.DocumentRegistry` (same names/signatures — copy the list from that class), writing the `documents` table. `company_id` uuid is resolved from the universe id passed by callers via `companies.lookup(IdScheme.UNIVERSE, …)`; `derive_doc_id` unchanged.
- Produces `get_document(session, doc_id: str) -> Document | None` used by Task 7 citations.

- [ ] **Step 1: Write failing tests**: parametrise the existing `tests/test_document_registry*.py` assertions over the new class; plus `test_document_has_company_fk` (unknown company → `IntegrityError`) and `test_embeddings_roundtrip_pgvector`.
- [ ] **Step 2: Run** them — Expected: FAIL.
- [ ] **Step 3: Implement** and rewire `DocumentContentStore`; parsed-text and file-identity stay in `content.db`.
- [ ] **Step 4: Run** `pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(db): authoritative document registry and pgvector-only embeddings`

---

### Task 7: Observations, citations and the fact layer

**Files:**
- Create: `backend/arp/db/observations.py`, `backend/arp/db/to_observations.py`, `backend/tests/db/test_observations.py`, `backend/tests/test_to_observations.py`, `backend/tests/test_fact_rules.py`
- Modify: `backend/arp/orchestration/batch_runner.py` (`_on_success` writes result + observations + review items in one `transaction()` via `asyncio.to_thread`, 3 retries with backoff on `OperationalError`)
- Modify: `backend/arp/orchestration/review_queue.py:record_review_decision` and `record_cosign` (call `apply_decision` in the same transaction)

**Interfaces:**
- Consumes: Task 2 models, Task 3 `entity_id`, Task 4 `ensure_extracted_field`, Task 6 `get_document`.
- Produces in `arp.db.observations`:
  - `@dataclass CitationIn` — fields of `arp.schemas.common.Citation` relevant to `value_citations` + `role: CitationRole`
  - `@dataclass ObservationIn: company_id: UUID; field_id: str; field_version: int; source_kind: SourceKind; period_end: date | None; basis: str = ""; value: Any; value_state: ValueState; unit, canonical_value, canonical_unit, scale_applied, fx_rate, confidence, checks, route, method; period_start: date | None = None; run_id: str | None = None; source_id: int | None = None; load_id: int | None = None; citations: list[CitationIn] = []; trial: bool = False; held: bool = False`
  - `FactAction = Literal["insert", "supersede", "noop", "keep"]`
  - `decide(current: CompanyFact | None, value, status: FactStatus, value_state: ValueState) -> FactAction` — pure; encodes spec §2.7 table
  - `record(session, observations: list[ObservationIn]) -> list[int]` — inserts observations + citations, then for each non-trial observation applies `decide` under `SELECT … FOR UPDATE`; on `IntegrityError` from `uq_company_facts_current` rolls back to a savepoint and retries once
  - `apply_decision(session, review_item_id: int, decision: DecisionKind, edited_value: Any | None, decision_id: int) -> None`
  - Status mapping: route `auto_accept` → `auto_accepted`; queued → `pending_review`; decision approve → `approved`, edit/correct → `edited`, reject → fact unchanged (current stays), hold → `held`
- Produces in `arp.db.to_observations`: `to_observations(run_type: str, company_id: UUID, run_id: str, result: dict, *, trial: bool) -> list[ObservationIn]` for `extraction`, `financials`, `theme` (`field_id = f"theme:{activity_id}"`), `proxy_voting` (`field_id = f"vote:{meeting_id}:{proposal_number}"`); unknown run types → `[]`. Extraction: one observation per `ExtractedField`; `period_end` from `ExtractedField.period_end` (ISO → `date`; invalid → observation rejected to `run_errors` with `{"kind": "invalid_value", "field_id", "raw"}`); each `Citation` → `CitationIn(role=primary)` for the first, `corroborating` for the rest, `alternatives[*].citations` → `alternative`. `held_documents` → `RunHeldDocument` rows and `held=True`.

- [ ] **Step 1: Write failing pure tests** `tests/test_fact_rules.py`, one per spec §2.7 row:
  - `test_new_key_inserts` → `"insert"`
  - `test_same_value_same_status_noop` → `"noop"`
  - `test_equal_numeric_values_do_not_supersede` (Review Focus 2): current `1000`, incoming `1000.0` → `"noop"`
  - `test_different_accepted_value_supersedes` → `"supersede"`
  - `test_pending_value_keeps_current` → `"keep"`
  - `test_not_found_keeps_current` → `"keep"`; with no current → `"noop"`
  - `test_held_supersedes_with_held_status` → `"supersede"`
- [ ] **Step 2: Write failing tests** `tests/test_to_observations.py`: an `ExtractionRecord` fixture with two fields (FY2024, FY2023) → two observations with the right `period_end`; two citations → roles `primary`, `corroborating`; theme row → `field_id == "theme:A1"`; voting row → `"vote:M1:3"`; trial → every observation `trial=True`; invalid `period_end="31/12/2024"` → excluded and reported.
- [ ] **Step 3: Write failing DB tests** `tests/db/test_observations.py`:
  - `test_new_period_adds_fact_and_keeps_old_period`
  - `test_restated_value_supersedes_and_history_is_queryable` (as-of before/after returns old/new)
  - `test_two_concurrent_writers_leave_one_current_fact` (two threads, same key, different values → exactly one row with `valid_to IS NULL`)
  - `test_trial_run_writes_no_facts`
  - `test_review_approve_turns_pending_into_approved` via `record_review_decision`
  - `test_citation_links_to_document_and_chunk`
  - `test_run_type_facts_do_not_overwrite_each_other`: extraction and financials results for one company → facts under different `field_id`s both current
- [ ] **Step 4: Run** `pytest tests/test_fact_rules.py tests/test_to_observations.py tests/db/test_observations.py -v` — Expected: FAIL.
- [ ] **Step 5: Implement** `observations.py`, `to_observations.py`, the batch-runner and review-queue wiring.
- [ ] **Step 6: Run** the three files, then `pytest -q` — Expected: PASS.
- [ ] **Step 7: Commit** `feat(db): observations, citations and current-fact layer`

---

### Task 8: Provider data sources

**Files:**
- Create: `backend/arp/db/providers.py`, `backend/tests/db/test_providers.py`
- Modify: `backend/arp/portfolio/climate/esg_intake.py` (persist via `record_load` + `ingest_rows`; keep its file validation and mappings)
- Modify: `backend/arp/publish/facts.py` and `backend/arp/bi/published.py` (refuse/skip facts whose observation's source has `licence = internal_only`)
- Modify: `backend/arp/storage/object_store_client.py` usage for payload storage (existing client)

**Interfaces:**
- Consumes: Task 3 `resolve(..., allow_create=False)`, Task 4 `register_provider_field`, Task 7 `record`.
- Produces in `arp.db.providers`:
  - `ensure_source(session, slug: str, *, name: str, kind: str, licence: Licence, id_scheme: IdScheme) -> int` (slug immutable: existing slug returns its id, never renames)
  - `@dataclass LoadResult: load_id: int; unchanged: bool`
  - `record_load(session, source_id: int, payload: bytes, *, request: dict, as_of: date) -> LoadResult` — stores payload in object storage under `provider-loads/<slug>/<sha256>` before inserting; same `payload_sha` → `unchanged=True`, no new row
  - `@dataclass ProviderRow: issuer_ids: list[tuple[IdScheme, str]]; metric_code: str; metric_name: str; unit: str | None; data_type: str; period_end: date | None; value: Any`
  - `@dataclass IngestReport: observations: int; unmatched_issuers: list[list[tuple[str, str]]]; collisions: list[str]`
  - `ingest_rows(session, load_id: int, rows: list[ProviderRow]) -> IngestReport` — sets load `status=ingested` (or `failed` with the exception text, re-raised)
  - `reingest(session, load_id: int, parse: Callable[[bytes], list[ProviderRow]]) -> IngestReport` (reads stored payload; no fetch)
  - First-time match by LEI/ISIN stores the provider issuer id as a new alias (`IdScheme` value = source's `id_scheme`).

- [ ] **Step 1: Write failing tests** `tests/db/test_providers.py`:
  - `test_identical_payload_is_unchanged` (Review Focus 3): second `record_load` same bytes → `unchanged=True`; `ingest_rows` not called → 0 new observations.
  - `test_unknown_issuer_is_reported_not_created`
  - `test_first_match_by_lei_stores_provider_alias`: second pull matches by provider id alone.
  - `test_new_metric_registers_own_field`: observation `field_id == "prov:msci:carbon_emissions_scope_1"`, never an `fld_` id.
  - `test_colliding_codes_reported`: both rows skipped, `collisions` names them.
  - `test_failed_ingest_reingests_from_stored_payload`: first parse raises → load `failed`; `reingest` succeeds without the fetch callable being called.
  - `test_internal_only_fact_refused_by_publish`
  - `test_slug_is_immutable`
- [ ] **Step 2: Run** `pytest tests/db/test_providers.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `providers.py`, ESG intake wiring, licence check in publish/BI.
- [ ] **Step 4: Run** the file, `pytest tests -k "esg or publish or bi" -q`, then `pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(db): provider data sources with stable provider fields`

---

### Task 9: Company API

**Files:**
- Create: `backend/arp/db/company_view.py`, `backend/arp/api/routers/companies.py`, `backend/tests/db/test_company_api.py`
- Modify: `backend/arp/api/main.py` (include router), `backend/arp/api/routers/extraction.py:413`, `backend/arp/api/routers/financials.py:91`, `backend/arp/api/routers/runs.py:69` (use `company_view`)
- Delete: `backend/arp/api/company_results.py`
- Modify: `frontend/src/types.ts` (`CompanySummary`, `CompanyFactRow`, `FactTrail`)

**Interfaces:**
- Produces in `arp.db.company_view` (Pydantic response models in the same module):
  - `resolve_ref(session, ref: str) -> UUID | None` — UUID string, or `"<SCHEME>:<value>"` (scheme case-insensitive, value via `normalise_identifier`)
  - `search(session, q: str, limit: int = 20) -> list[CompanySearchHit]`
  - `summary(session, company_id: UUID, *, today: date) -> CompanySummary` (identity, identifiers, fact counts by status, open review items, documents, runs, holders as of `today`)
  - `facts(session, company_id: UUID, *, as_of: datetime | None, kind: FieldKind | None, field_id: str | None, period_end: date | None, limit: int = 100, offset: int = 0) -> list[CompanyFactRow]` (`source_label` = `"<doc title> p.<page>"` or `"<source name> · <fetched_at date>"`; `licence`)
  - `trail(session, fact_id: int) -> FactTrail` (versions → observations → citations, load, decisions)
  - `results_by_company(session, run_type: str, ref: str) -> list[dict]` and `known_companies(session, run_type: str) -> list[dict]` — same shapes as the deleted `company_results.py` functions
- Routes: `GET /api/companies`, `GET /api/companies/{ref}`, `GET /api/companies/{ref}/facts`, `GET /api/facts/{fact_id}/trail`; unknown ref → 404.

- [ ] **Step 1: Write failing tests** `tests/db/test_company_api.py` (FastAPI `TestClient`, seeded via Task 7 `record`):
  - `test_alias_lookup_is_normalised` (Review Focus 5): `GET /api/companies/lei: 7ltw…` (lower-case, space) → 200, same id as the UUID route.
  - `test_facts_as_of_returns_historical_value`
  - `test_facts_filters_by_kind_and_period`
  - `test_trail_contains_citation_page_and_decision`
  - `test_provider_fact_shows_source_and_licence`
  - `test_unknown_company_404`
  - `test_existing_extraction_company_results_shape_unchanged`: response keys equal the pre-change fixture.
- [ ] **Step 2: Run** `pytest tests/db/test_company_api.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** module, router, endpoint rewrites, TS types; delete `company_results.py`.
- [ ] **Step 4: Run** the file and `pytest -q`; `cd frontend && npx tsc -b` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): one-company view endpoints`

---

### Task 10: Company page

**Files:**
- Create: `frontend/src/pages/Company.tsx`, `frontend/src/pages/company/FactsTable.tsx`, `frontend/src/pages/company/FactTrailPanel.tsx`, `frontend/src/pages/company/companyQuery.ts` (pure helpers), test `frontend/tests/company.test.ts` (the repo's `node --test` runner tests pure modules, not React components)
- Modify: frontend router (route `/companies/:ref`), components rendering company names (link to the page)

**Interfaces:**
- Consumes: Task 9 routes and TS types.
- Page: header (name, country, sector, identifiers), facts table (filters kind/field/period, as-of `<input type="date">`), side panel with the trail; citation links open the existing document viewer at the page; provider rows show source + load date.

- [ ] **Step 1:** Invoke `impeccable:impeccable` (shape) with `DESIGN.md`, then `ui-ux-pro-max:ui-ux-pro-max` for table/panel guidance; record the chosen layout in the PR description.
- [ ] **Step 2: Write failing tests** `frontend/tests/company.test.ts` for `companyQuery.ts`: `factsUrl(ref, {asOf, kind, fieldId, periodEnd})` builds `/api/companies/<encoded ref>/facts?as_of=…` omitting empty filters; `sourceLabel(row)` returns `"Annual Report 2024 p.12"` for a document source and `"MSCI ESG · 2026-09-30"` for a provider source; `encodeRef("LEI:7LTW…")` URL-encodes the colon. UI behaviour (as-of refetch, trail panel, 404 state) is checked by the screenshots in Step 5.
- [ ] **Step 3: Run** `cd frontend && npm test` — Expected: FAIL (`companyQuery.ts` missing).
- [ ] **Step 4: Implement** the page and links.
- [ ] **Step 5: Run** `npm test && npx tsc -b && npm run lint` — Expected: PASS. Screenshot desktop and 390px widths via the `run` skill.
- [ ] **Step 6: Commit** `feat(frontend): company page`

---

### Task 11: Import and verify

**Files:**
- Create: `backend/arp/db/importer.py`, `backend/tests/db/test_importer.py`
- Modify: `backend/arp/cli/db.py` (`arp db import [--dry-run]`, `arp db verify`)

**Interfaces:**
- Consumes: Tasks 3–8. Reads legacy data with the pre-Task-5 file readers (keep `arp/storage/run_store.py` file implementation importable as `LegacyRunStore` until Task 12).
- Produces:
  - `@dataclass ImportReport: counts: dict[str, int]; identity_conflicts: list[dict]; fact_conflicts: list[dict]`
  - `import_all(dsn: str, settings: Settings, *, dry_run: bool) -> ImportReport` — order: universe files → identifier map → schema registry → documents (`content.db`) → runs **oldest first by `created_at`** (manifest, companies, results via `to_observations`, review queue, decisions, cosigns, restatements) → ESG loads. Idempotent: natural keys (`run_id`, `(run_id, company_id)`, `(run_id, item_key)`, decision `(review_item_id, decided_at, reviewer)`, `doc_id`, `payload_sha`) skip existing rows. Each run imports in one transaction. `dry_run` uses a transaction that is rolled back.
  - `@dataclass VerifyReport: differences: list[dict]` ; `verify(dsn: str, settings: Settings) -> VerifyReport` — per run: result/error/review/decision row counts file vs DB; per company and field: current fact value from replaying files oldest-first vs `company_facts`.
  - CLI exits non-zero when `verify` finds differences.

- [ ] **Step 1: Write failing tests** `tests/db/test_importer.py` on a fixture `runs/` tree with three runs (two extraction, one theme) spanning two dates:
  - `test_import_is_idempotent`: second import → all counts 0.
  - `test_import_replays_oldest_first`: older run value 10, newer 12 → current fact 12.
  - `test_import_resumes_after_interruption` (Review Focus 4): patch to raise on the 2nd run, re-run without patch → complete, no duplicates.
  - `test_dry_run_writes_nothing`
  - `test_verify_reports_zero_differences_after_import`, and `test_verify_detects_missing_row` after deleting one `run_results` row.
- [ ] **Step 2: Run** `pytest tests/db/test_importer.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** importer and CLI.
- [ ] **Step 4: Run** the file and `pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(cli): arp db import and verify`

---

### Task 12: Delete the file path and legacy projections; docs

**Files:**
- Delete: `backend/arp/storage/postgres_company_records_projection.py`, `postgres_company_facts_projection.py`, `postgres_document_projection.py`, `postgres_projection_config.py`, `postgres_checkpoints.py`, `document_registry.py` (SQLite registry), `identifier_map.py` (after importer uses its own reader), and their tests
- Modify: `backend/arp/storage/postgres_models.py` (remove `CompanyModel`, `CompanyRecordModel`, `CompanyFactModel`, `DocumentRegistryModel`, `IndexCheckpointModel`; re-key `HoldingModel`, `SecurityModel`, `SecurityResolutionModel`, `ReleaseModel`, `PublishedFactModel`, `FactEventModel` to `company_id uuid FK`)
- Modify: `backend/arp/storage/postgres_schema.py` (step `phase1_rekey`: add `company_id` columns, backfill via UNIVERSE/LEI aliases, drop `issuer_key`/`issuer_scheme`, drop old tables)
- Modify: `backend/arp/config.py` (remove `portfolio_backend`, `embeddings_backend`, `*_projection_enabled`), `backend/arp/storage/run_store.py` (remove `LegacyRunStore` file code, keep re-export or delete module and update imports), `backend/arp/storage/portfolio_store_factory.py` (Postgres only)
- Modify: `docs/METHODOLOGY.md` (storage section), `docs/INSTALLATION.md` (Postgres required; `docker compose up -d postgres`; `arp db init-postgres`; import/verify cut-over steps), `backend/.env.example`, `docker-compose.yml` comments
- Test: `backend/tests/db/test_rekey.py`

**Interfaces:**
- Consumes: everything above. Produces no new API.

- [ ] **Step 1: Write failing tests** `tests/db/test_rekey.py`: after `ensure_schema` on a database seeded with legacy `holdings`/`published_facts` rows keyed by `issuer_key` LEI, rows carry the matching `company_id`; a legacy row whose key matches no company is reported by `schema_report` and left with `company_id NULL` (not deleted); `published_facts` key is `(company_id, field_id, period_end, basis, version)`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** deletions, re-key step, settings removal, docs.
- [ ] **Step 4: Run** `pytest -q`, `ruff check backend`, `cd frontend && npx tsc -b` — Expected: all PASS; `grep -rn "projection_enabled\|portfolio_backend\|embeddings_backend" backend/arp` — Expected: no output.
- [ ] **Step 5: Commit** `refactor(storage): remove file run store and legacy projections; Postgres is the foundation`

---

## Self-review notes

- Spec §2.1–2.8 → Tasks 2–8, 12. §3 → Tasks 1, 5, 7. §4 → Tasks 9–10. §5 error table → Task 3 (conflict), 5 (startup), 7 (retries, invalid value, concurrency), 8 (ingest). §6 order → task order. §7 cut-over → Task 11 + docs in Task 12. §8 findings → Tasks 3, 7, 11, 12. §9 tests → per task.
- Not in this plan (spec §10): ESG provider API client, later phases, `field_links`, merging fact tables, async engine, company embeddings.
