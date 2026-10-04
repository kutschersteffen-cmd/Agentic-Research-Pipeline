# Step 5: Publishing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Only reviewed values leave ARP, and each one traces back to its stored original. A value in a final review state, or one the system auto-accepted, is released per document as a versioned published fact. The release passes a lineage gate that re-reads the original's hash first. A changed value creates a new version; the same value only re-confirms the current one. A restated comparative becomes a marked version of the earlier period, and the original stays visible. A release can be withdrawn with a reason, which restores the previous version. Readers see only what was published by their as-of date, and every change goes to an outbox. Holdings enter through one intake (a monthly API pull, or a CSV or Excel file). Once a month ARP freezes a snapshot of index holdings, portfolio holdings and ESG signals, which other ARP applications pull over a read-only API.

**Architecture:**
- **Two layers (decided).** Extraction records stay what they are: `runs/<id>/results.jsonl`, the decision log and the optional `company_facts` projection, which keep every candidate value, check and decision per run. Published facts are a new, authoritative Postgres layer of three tables in `arp/storage/postgres_models.py`: `published_facts`, `releases` and the outbox `fact_events`. Each published fact links back to its extraction record through `source_run_id` and `item_key`, and to its source through `citation` and `release_id`.
- A new package `arp/publish/`:
  - `facts.py`: the `Fact` model, the pure versioning rule `plan_version`, and `PublishStore` (Postgres writes; `sqlalchemy` and `postgres_models` are imported inside the methods).
  - `candidates.py`: picks what may be published from one run.
  - `gate.py`: the lineage gate and re-grounding.
  - `release.py`: releases, `publish_run` and withdrawal.
  - `reader.py`: as-of reads and the outbox.
  - `scheduler.py`: the daily in-process job that runs the nightly re-ground sample, the holdings pull, the monthly snapshot build and the corrections.
- The decision logic is pure and runs without Postgres: what may be published, versioning, gate grouping, release and withdrawal plans, as-of filtering and snapshot building. `PublishStore` is a thin I/O layer, tested against real Postgres in CI.
- **E17 write path.** `publish_run` reuses the projection's decision resolution. The correction merge moves into `merge_correction`, which both call. It also follows the projection's insert-only versioning: insert the next row, then close the current one (the `superseded_by` FK needs the new row first). The `company_facts` table and `arp db reindex company-facts` stay as they are, so old rows keep working. Old runs are published once with `arp publish backfill`.
- Holdings: the `Holding` model in `arp/schemas/portfolio.py` becomes the one canonical row (`kind`, `holder_id` with the `portfolio_id` alias, `issuer_key`/`issuer_scheme`, `isin`, `source`, `source_ref`). `PortfolioStore` and `PostgresPortfolioStore` gain `kind`. A new package `arp/holdings/` holds validation, the file source and its JSON mappings, the intake (identity, precedence, audit, revisions) and the API source.
- Snapshots: a new package `arp/snapshots/` holds the versioned schemas, the build (frozen files with a manifest, plus correction revisions) and the pull client. It is served by `arp/api/routers/snapshots.py` under `/api/v1/snapshots`.
- Frontend: a "Holdings Intake" sub-tab on the Risk Monitoring page shows the status of each holder (age, last pull, last error) and has an upload form. The workbench learns the new `security` review kind.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 (already the Postgres extra), stdlib `csv`/`hashlib`/`json`/`random`/`datetime`/`uuid`, `openpyxl` (installed), `httpx` (installed), APScheduler through `IntervalScheduler` (installed); pytest; React + TypeScript (Vite), node test runner.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4`, section B5 (E72 to E76), E17 (platform) and section F (E77). Only the local defaults in the Cloud switch-on table are built (`object_store_backend=file`, `scheduler_backend=local`, local Postgres); no cloud adapter and no switch setting is added. Paths are relative to `backend/` unless they start with `frontend/`, `config/` or `docs/`, which live at the repo root. It builds on steps 1 to 4 (`docs/superpowers/plans/2026-10-03-step1-identity-review-keys.md`, `2026-10-04-step2-capture-and-typing.md`, `2026-10-04-step3-checks-and-routing.md`, `2026-10-04-step4-review.md`).

**Deviations from the spec text, decided here:**
- The key is `issuer_key` plus `issuer_scheme` (user decision), not `issuer_id`. `basis` is `""` when the field has none.
- `Fact.valid_from` is the moment a version became the published value. The reader filters on it, and it is the `published_at` that readers and `esg_signals` show. A version restored by a withdrawal keeps its original `release_id` (lineage), but its `valid_from` is the withdrawal time.
- One release per document per publish call (`release_id` is new per call). A re-publish that changes no value creates no release; it only re-confirms.
- Publication is explicit (`POST /api/publish/runs/{run_id}` by an approver, `arp publish run`) or by backfill (`arp publish backfill`). The run-completion projection hook does not publish, because a release needs a named publisher and the gate's original check. Legacy rows with no `route` that were never queued were implicitly trusted. They are not step 3 auto-accepts, so they are never published. They stay visible in `company_facts`.
- Holdings mappings are JSON (`arp/holdings/mappings/*.json`), not YAML: PyYAML is not a declared dependency.
- Number locale: E48's `normalise/locale.py` does not exist yet, so each mapping declares its decimal separator (`"decimal": "." | ","`).
- Identity: an unresolved ISIN becomes a review item of a new kind `security` (key `isin:{ISIN}`) in a `holdings` run, decided in the step 4 workbench. A final `correct` supplies the LEI. `entity_resolution.resolve_security` is not called, because its security master maps to `company_id`, not to an LEI. The intake does reuse `SecurityResolution` in `PortfolioStore` (`needs_review=True`), so the existing "securities needing review" list shows the item too.
- Holdings snapshots stay immutable through a revision archive: each intake writes `revision` n+1 as a write-once file, and the store's working snapshot for that date is the latest revision. The stores' snapshot methods only gain `kind`.
- Snapshot files live in a path-keyed local directory (`snapshot_store_dir/snapshots/{month}/r{n}/`), written atomically and hash re-read like `upload_or_fail`. `LocalBlobStore` (E26) is content-addressed and cannot hold a month/revision path.
- `index_holdings` comes from the intake only. Indices built by the index engine are left out, because their constituents carry `company_id` and neither ISIN nor LEI. `calibration_version` is therefore always null.
- A correction revision is built for the newest frozen month only; later months already include the change through their own as-of read.
- The outbox has one consumer, the snapshot correction build. Subscribers for the index engine and for reports are not wired, because neither has a defined reaction yet; they can poll `GET /api/publish/events`.
- The snapshot roles are grants on top of the rank role: `Principal.roles: list[str]` (`snapshot_reader`, `holdings_reader`).
- `holdings.load(store, kind, holder_id, as_of)` takes the store. The existing portfolio analytics keep `load_holdings_as_of`, which reads the same working snapshots.
- "Business day" means Monday to Friday (no holiday calendar).
- The publishing schedule defaults to off (`publishing_schedule_enabled=False`), like every other in-process schedule.
- There is no publishing UI in this step (API and CLI only).

## Global Constraints

- **Voting is frozen.** Do not change `arp/api/routers/voting.py`, `arp/voting/`, `arp/cli/voting.py`, `arp/stewardship/voting_feed.py`, `frontend/src/components/BallotReview.tsx`, `ReviewerField.tsx`, `ConfirmDecision.tsx`, the voting pages, or any voting test. `useReviewer` stays unchanged. The voting router stays unauthenticated.
- No new dependencies, backend or frontend. `pyproject.toml` changes only in `[tool.setuptools.package-data]`, which adds `"arp.holdings" = ["mappings/*.json"]`.
- **The grounding gate is never weakened.** Only grounded citations with a `content_key` pass the lineage gate. Re-grounding uses `ground_citations` against the stored text and changes no stored fact.
- **Never invent FX rates.** A holding's `fx_rate_to_eur` comes from the file or API row, or is `1.0` only when `currency == "EUR"`. A non-EUR portfolio row without a rate is a validation error. `market_value_eur` is null when either factor is missing.
- **Publication rules:**
  - Only an item in `FINAL_STATES` (through `effective_decisions(..., cosign_required={"edit"})`) or a field with `route == "auto_accept"` that is not in human review is published.
  - Trial runs are never published.
  - A held field, a rejected value, a value still in review, `first_done`, `disagreed` and escalated items are not published.
  - A restatement is published only from a final `restatement_candidate` item. Step 4 always asks for a second review there (`published_change`). A value item whose key has a restatement candidate in the same run is never published on the plain path.
  - A candidate from a run older than the current version's run never supersedes it.
  - A document whose release in that run was withdrawn is not published again from that run.
- **Old data loads:**
  - Old `company_facts` rows and the `company_facts` projection are untouched.
  - Old holdings JSONL rows (key `portfolio_id`, no `kind`) load through the alias as `kind="portfolio"`.
  - Old Postgres `holdings` rows get `kind='portfolio'` from schema step `0003_holdings_intake`.
  - Old runs are published by `arp publish backfill`. Their legacy unrouted rows are reported as skipped (`not_auto_accepted`), never published.
  - Old results rows without `issuer_key` are skipped (`no_issuer_key`).
  - Old `Principal` rows in the users file have no `roles` and load with `[]`.
- **Clients never see `user_id`.** `Release.published_by` and `withdrawn_by` (internal, user ids or `"system"`) are dropped by `public_release`. Responses carry `published_by_role` only. `Fact` holds no user. The holdings audit log (`user_id`, reason) is never served.
- Dev auth mode stays the default. The dev principal also gets both grants. Tests use the `conftest.py` principal override and build other principals explicitly.
- **Postgres tests.**
  - Postgres-backed tests live in files ending `_pg.py`, or are parametrized like `tests/test_portfolio_store_parity.py`. They skip without `ARP_TEST_POSTGRES_DSN`, use an autouse fixture with `ensure_schema(DSN)` and `reset_postgres_tables(DSN)` before and after, and import `arp.storage.postgres_models` only inside fixtures and functions (`pgvector` is not installed locally). They run in CI's Postgres service.
  - Every pure unit has its own non-Postgres test, and no non-`_pg` test imports `arp.storage.postgres_models` at module level.
  - New `arp/` modules import `postgres_models` lazily, as the existing projections do.
- **Timestamps.** Every timestamp the publish layer writes comes from `ts_now()` (`datetime.now(UTC).isoformat(timespec="microseconds")`), a fixed-width UTC string, so string comparison in Python and in Postgres orders it correctly. `as_of_bound` normalises every as-of input to the same form.
- **Exact strings:**
  - Fact states: `approved`, `edited`, `auto_accepted`.
  - Version plan kinds: `insert`, `reconfirm`, `older`.
  - Event types: `published`, `restated`, `withdrawn`, `restored`.
  - Skip reasons (`Skip.reason`): `trial_run`, `no_issuer_key`, `no_value`, `no_period`, `rejected`, `not_final`, `held`, `not_auto_accepted`, `restatement_pending`, `older_than_published`.
  - Gate reasons: `no_grounded_citation`, `original_missing`, `hash_mismatch`. A publish can also be blocked with `release_withdrawn`.
  - Re-ground results: `ok`, the three gate reasons, `text_unavailable`, `not_grounded`, `offset_moved`.
  - `SYSTEM = "system"` (publisher id and role of the backfill).
  - Holding kinds: `index`, `portfolio`. Holding sources: `api`, `file`. Issuer schemes: `LEI`, `ARP_PROVISIONAL`. Provisional key: `ARP:<uuid5(ARP_NAMESPACE, "isin:" + ISIN)>`.
  - Review kind `security`, item key `isin:{ISIN}`, run type `holdings`.
  - Grants: `snapshot_reader`, `holdings_reader`.
  - Datasets: `index_holdings`, `portfolio_holdings`, `esg_signals`. Snapshot id: `f"{month}.r{revision}"`. Files: `{dataset}.v{major}.{csv|jsonl}` plus `manifest.json`.
- **HTTP status codes:**
  - Publish: 503 when `postgres_dsn` is unset; 403 for publishing or withdrawing below approver; 404 for an unknown run, release or fact; 409 for a concurrent publish or a release already withdrawn; 422 for a blank withdrawal reason; 400 for a bad `as_of`.
  - Holdings: 413 for an upload over `max_upload_bytes`; 422 for a rejected or unreadable file, with `{"message", "errors": [{"row", "column", "message"}]}`; 409 for a file over an API month without an override reason, or an API pull for a file holder; 503 for a pull when `holdings_api_url` is unset.
  - Snapshots: 403 without the grant; 404 for an unknown month, revision or dataset; 400 for a malformed month.
- Backend checks: `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest -q && ruff check arp tests`. The baseline is 45 failures that already exist (Chromium, pdftoppm, Postgres factories, the nltk hardlink sandbox, botocore). There must be no new failures. The new `_pg` tests skip locally and must pass in CI.
- Frontend checks: `cd frontend && npm run lint && npm test && npm run build`. The baseline is 0 errors and 13 warnings; add no new errors or warnings.

## Review Focus

1. **Something non-final leaves ARP.** A `first_done` correction, an escalated item, a trial run, a legacy unrouted row, a value item that bypasses its restatement candidate, or a re-publish of an older run over a newer value. Tests: Task 3 (`test_first_done_correction_not_published`, `test_legacy_unrouted_field_not_published`, `test_restatement_published_only_after_second_approval`, `test_value_item_with_candidate_never_published_plainly`), Task 1 (`test_older_run_never_supersedes_newer`).
2. **Withdrawal rewriting history.** Withdrawal closes the withdrawn version and inserts a restored copy; it never reopens the old row. A read as of a time before the withdrawal still shows what was visible then. Tests: Task 5 (`test_withdrawal_restores_previous_fact`), Task 6 (`test_withdrawn_version_still_visible_before_withdrawal`).
3. **Timestamp comparison.** Offsets and date-only inputs normalise to fixed-width UTC, so `2026-10-31` covers the whole day and `+02:00` inputs compare correctly, in Python and in SQL. Tests: Task 6 (`test_as_of_bound_normalises_offset`, `test_as_of_date_covers_whole_day`, `test_facts_as_of_sql_matches_visible_pg`).
4. **The `Holding` change breaking portfolio analytics.** Old snapshots load through the alias, index rows never reach portfolio aggregation (file and Postgres), a portfolio row always has `market_value_eur`, and no FX rate is invented. Tests: Task 8 (`test_old_snapshot_loads_through_alias`, `test_index_holdings_beside_portfolio_holdings`), Task 9 (`test_non_eur_portfolio_row_needs_fx_rate`).
5. **Snapshot immutability and hashes.** A frozen month refuses a rewrite, r1 stays byte-identical after r2, and the client refuses a file whose hash differs from the manifest. Tests: Task 11 (`test_frozen_snapshot_refuses_rewrite`, `test_r1_stays_readable_after_r2`), Task 12 (`test_pull_refuses_hash_mismatch`).

---

### Task 1: Fact model, tables and the versioning rule (E72, E17 schema)

**Files:**
- Create: `arp/publish/__init__.py` (empty), `arp/publish/facts.py`
- Modify: `arp/storage/postgres_models.py` (`ReleaseModel`, `PublishedFactModel`, `FactEventModel`)
- Modify: `tests/postgres_helpers.py` (`_DELETE_ORDER` starts with `"FactEventModel", "PublishedFactModel", "ReleaseModel"`)
- Test: `tests/test_publish_facts.py` (new)

**Interfaces:**
- Produces, in `arp/publish/facts.py` (no `sqlalchemy` import at module level):
  - `def ts_now() -> str`: `datetime.now(UTC).isoformat(timespec="microseconds")`
  - `FactKey = tuple[str, str, str, str]`, meaning `(issuer_key, field_id, period_end, basis)`
  - `FactState = Literal["approved", "edited", "auto_accepted"]`
  - `class FactCandidate(BaseModel)`: `issuer_key: str`, `issuer_scheme: str`, `field_id: str`, `period_end: str`, `basis: str = ""`, `value: str | float | bool | None`, `unit: str | None = None`, `canonical_value: float | None = None`, `canonical_unit: str | None = None`, `state: FactState`, `citation: Citation | None`, `source_run_id: str`, `observed_at: str` (the source run's `created_at`), `item_key: str`, `restated: bool = False`, `restated_by_doc_id: str | None = None`
  - `class Fact(BaseModel)`: `fact_id: str = Field(default_factory=lambda: new_id("fact"))`, the candidate's fields (with `citation: Citation`, not optional), plus `version: int = Field(ge=1)`, `valid_from: str`, `valid_to: str | None = None`, `superseded_by: str | None = None`, `reconfirmed_at: str | None = None`, `release_id: str`, `restored_from: str | None = None`
  - `def fact_key(x: Fact | FactCandidate) -> FactKey`
  - `def same_fact_value(a, b) -> bool`: `same_value(a.value, b.value)` (from `arp/orchestration/review_queue.py`) and equal `unit` and `canonical_unit`
  - `@dataclass(frozen=True) class VersionPlan`: `kind: Literal["insert", "reconfirm", "older"]`, `fact: Fact | None` (the new version, the re-confirmed current, or None for `older`), `closes: Fact | None = None` (the current version with `valid_to` and `superseded_by` set)
  - `def plan_version(current: Fact | None, cand: FactCandidate, *, release_id: str, now: str) -> VersionPlan`:
    - `current is None` → `insert`, version 1, `valid_from=now`
    - `same_fact_value(current, cand)` → `reconfirm`: `current` with `reconfirmed_at=now` (same `fact_id`, `version` and `release_id`)
    - `cand.observed_at < current.observed_at` → `older`, nothing written
    - otherwise → `insert` version `current.version + 1`, `valid_from=now`, with the candidate's `restated`/`restated_by_doc_id`; `closes = current` with `valid_to=now`, `superseded_by=<new fact_id>`
  - `class Release(BaseModel)`: `release_id: str = Field(default_factory=lambda: new_id("rel"))`, `doc_id: str`, `content_key: str`, `storage_uri: str`, `issuer_key: str`, `issuer_scheme: str`, `run_id: str`, `published_at: str`, `published_by: str` (internal), `published_by_role: str`, `withdrawn_at: str | None = None`, `withdrawal_reason: str | None = None`, `withdrawn_by: str | None = None` (internal)
  - `def public_release(r: Release) -> dict`: `r.model_dump(mode="json", exclude={"published_by", "withdrawn_by"})`
  - `EventType = Literal["published", "restated", "withdrawn", "restored"]`
  - `class FactEvent(BaseModel)`: `event_id: int | None = None` (set by the table), `event_type: EventType`, `fact_id: str`, `issuer_key: str`, `field_id: str`, `period_end: str`, `basis: str`, `release_id: str`, `at: str`
- Produces, in `arp/storage/postgres_models.py` (plain `String` timestamps, like the existing models):
  - `ReleaseModel`, `__tablename__ = "releases"`: `release_id` (PK) and the other `Release` fields as columns; `Index("ix_releases_doc", "doc_id")`, `Index("ix_releases_run", "run_id")`.
  - `PublishedFactModel`, `__tablename__ = "published_facts"`:
    - `fact_id` (PK); `value: JSONB`; `canonical_value: Float`; `citation: JSONB`; `superseded_by` (FK `published_facts.fact_id`, nullable); `release_id` (FK `releases.release_id`); `restated: bool = False`; the other `Fact` fields as `String` columns (`valid_to`, `reconfirmed_at`, `restated_by_doc_id`, `restored_from` nullable).
    - `UniqueConstraint("issuer_key", "field_id", "period_end", "basis", "version", name="uq_published_facts_key_version")`
    - `Index("ix_published_facts_current", "issuer_key", "field_id", "period_end", "basis", "valid_to")`
    - `Index("ix_published_facts_valid_from", "valid_from")`
  - `FactEventModel`, `__tablename__ = "fact_events"`: `event_id` (int PK, autoincrement) and the `FactEvent` fields; `Index("ix_fact_events_at", "at")`.
  - `create_all` creates the three tables, so no `SCHEMA_STEPS` entry is needed for them.

- [ ] **Step 1: Write the failing tests** in `tests/test_publish_facts.py` (pure; `T1 = "2026-10-01T09:00:00.000000+00:00"`, `T2` a day later):
  - `test_first_value_is_version_1`: `plan_version(None, cand, release_id="rel_1", now=T1)` has `kind == "insert"`, `fact.version == 1`, `fact.valid_from == T1`, `fact.valid_to is None`, `fact.release_id == "rel_1"`, `closes is None`.
  - `test_same_value_only_reconfirms`: current v1 with `value=1050.0`; a candidate with `value="1050"` gives `kind == "reconfirm"`, the same `fact_id`, `version == 1`, `reconfirmed_at == T2`, the original `release_id`, and `closes is None`.
  - `test_changed_value_new_version_closes_old`: value 1100 gives `insert`, `version == 2`, `valid_from == T2`, `closes.valid_to == T2`, `closes.superseded_by == fact.fact_id`.
  - `test_unit_change_is_new_version`: the same number with unit `tCO2e` → `ktCO2e` gives `insert`.
  - `test_older_run_never_supersedes_newer`: a candidate with an earlier `observed_at` and a different value gives `kind == "older"` and `fact is None`; with the same value it gives `reconfirm`.
  - `test_restated_candidate_marks_new_version_only`: `restated=True`, `restated_by_doc_id="d9"` gives `fact.restated is True`, while `closes.restated is False`.
  - `test_fact_key_uses_empty_basis`: `fact_key(cand) == ("5493001KJTIIGC8Y1R12", "f1", "2024-12-31", "")`.
  - `test_public_release_has_no_user_ids`: `public_release(r)` has no `published_by` and no `withdrawn_by`, and keeps `published_by_role`.
  - `test_published_facts_unique_key_version`: `pytest.importorskip("pgvector")`; `PublishedFactModel.__table__` has a unique constraint over exactly the five key-plus-version columns.

- [ ] **Step 2: Run** `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publish_facts.py -v`. Expect FAIL (`ModuleNotFoundError: arp.publish`).

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(publish): published fact, release and outbox models; versioning rule (E72, E17)`.

---

### Task 2: Postgres publish store (E17 lineage, E72 storage)

**Files:**
- Modify: `arp/publish/facts.py` (`ConcurrentPublish`, `PublishStore`)
- Test: `tests/test_publish_store_pg.py` (new, Postgres-gated)

**Interfaces:**
- Consumes: `Fact`, `Release`, `FactEvent`, `VersionPlan`, `fact_key` (Task 1); `get_engine` (`arp/storage/postgres.py`).
- Produces, in `arp/publish/facts.py`:
  - `class ConcurrentPublish(RuntimeError)`: another publish changed a fact first.
  - `class PublishStore`:
    - `__init__(self, dsn: str)`: keeps `get_engine(dsn)`.
    - `session(self) -> Session` (public; `reader.py` uses it).
    - `current(self, keys: Iterable[FactKey]) -> dict[FactKey, Fact]`: rows with `valid_to IS NULL`.
    - `versions(self, key: FactKey) -> list[Fact]`: oldest first.
    - `get_fact(self, fact_id) -> Fact | None`; `previous_version(self, fact_id) -> Fact | None`, the row whose `superseded_by == fact_id`.
    - `save_release(self, release: Release | None, plans: list[VersionPlan], events: list[FactEvent]) -> None`, in one transaction:
      - insert the release when given;
      - for each `insert` plan: insert the new fact and flush; then, when the plan has `closes`, `UPDATE published_facts SET valid_to, superseded_by WHERE fact_id = :id AND valid_to IS NULL`, where a rowcount other than 1 raises `ConcurrentPublish`. The new row comes first because `superseded_by` is a self-FK checked at statement end;
      - `reconfirm` updates `reconfirmed_at` only; `older` writes nothing;
      - insert the events;
      - an `IntegrityError` (a duplicate key and version) raises `ConcurrentPublish`.
    - `get_release(self, release_id) -> Release | None`; `list_releases(self, *, doc_id: str | None = None, run_id: str | None = None) -> list[Release]`, ordered by `published_at`; `release_facts(self, release_id) -> list[Fact]`.
    - `save_withdrawal(self, release: Release, closes: list[Fact], restores: list[Fact], events: list[FactEvent]) -> None`, in one transaction: update the release `WHERE withdrawn_at IS NULL` (rowcount 1, else `ConcurrentPublish`); insert the restored facts and flush; then close each fact `WHERE valid_to IS NULL` (rowcount 1, else `ConcurrentPublish`), setting `superseded_by` to its restored copy's id; insert the events.
    - `lineage(self, fact_id) -> dict | None`: one `SELECT` of `published_facts` joined to `releases` on `release_id`. Returns `{"fact": <Fact json>, "citation", "release_id", "doc_id", "content_key", "storage_uri", "source_run_id", "item_key"}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_publish_store_pg.py` (skipped without `ARP_TEST_POSTGRES_DSN`; autouse schema and reset fixture):
  - `test_insert_and_current_pg`
  - `test_new_version_closes_old_pg`: after two releases, `versions(key)` holds v1 (with `valid_to` set and `superseded_by == v2.fact_id`) and v2; `current([key])[key]` is v2.
  - `test_reconfirm_updates_only_reconfirmed_at_pg`: the row count is unchanged and `reconfirmed_at` is set.
  - `test_duplicate_key_version_raises_concurrent_pg`
  - `test_stale_close_raises_concurrent_pg`: a plan whose `closes` row is already closed raises `ConcurrentPublish`, and nothing is inserted.
  - `test_lineage_one_join_pg`: `lineage(fact_id)` returns the release's `storage_uri` and the fact's citation. A SQLAlchemy `before_cursor_execute` listener counts exactly 1 statement during the call.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publish_store_pg.py -v`. Locally expect SKIPPED. With a scratch database (`ARP_TEST_POSTGRES_DSN=...`) expect FAIL (`ImportError: PublishStore`).

- [ ] **Step 3: Implement as in Interfaces.** Import `postgres_models` and `sqlalchemy` inside the methods.

- [ ] **Step 4: Run** the full backend check. Expect no new failures (the `_pg` file skips locally).

- [ ] **Step 5: Commit** with `feat(publish): Postgres store with supersession, re-confirmation and one-join lineage (E17, E72)`.

---

### Task 3: What a run may publish (publication rules, E73 selection)

**Files:**
- Modify: `arp/storage/postgres_company_facts_projection.py` (extract `merge_correction`; `resolve_extraction_fact` calls it, with no behaviour change)
- Create: `arp/publish/candidates.py`
- Test: `tests/test_publish_candidates.py` (new); `tests/test_postgres_company_facts_projection.py` runs unchanged

**Interfaces:**
- Consumes: `FactCandidate` (Task 1); `effective_decisions`, `latest_decisions` (`arp/orchestration/review_queue.py`); `field_item_key`, `period_key` (`arp/schemas/review.py`); `RestatementCandidate` rows (`restatements_path`).
- Produces, in `arp/storage/postgres_company_facts_projection.py`:
  - `def merge_correction(f: dict, decision: dict) -> dict`: today's merge block in `resolve_extraction_fact` (the edited keys over the field, the correction citation with `grounded=True`, the `value_state` inference, and clearing the stale canonical, FX and scale keys), moved verbatim.
- Produces, in `arp/publish/candidates.py`:
  - `@dataclass(frozen=True) class Skip`: `item_key: str`, `reason: str`
  - `def run_candidates(run_store, run_id: str) -> tuple[list[FactCandidate], list[Skip]]`:
    - No manifest, or `run_type != "extraction"` → `([], [])`. `params["trial"]` → `([], [Skip("*", "trial_run")])`.
    - `decisions = effective_decisions(run_store, run_id, cosign_required={"edit"})`; `in_review = set(latest_decisions(...)) - set(decisions)`; `rst` = the run's restatement candidates by `item_key` (the last row per key).
    - A results row without `issuer_key` → `Skip(company_id, "no_issuer_key")` for the whole row.
    - For each field, with `key = field_item_key(issuer_key, field_id, period_key(f))`:
      - `key in rst` → handled only by the restatement branch below;
      - `d = decisions.get(key)`;
      - `d is None`: `key in in_review` → `not_final`; `route == "hold"` → `held`; `route == "auto_accept"` → state `auto_accepted` with the field as is; anything else → `not_auto_accepted`;
      - `reject` → `rejected`; `approve` → `approved`; `correct` or `edit` → `edited`, with `merge_correction(f, d)`;
      - after this, `value is None` → `no_value`; no `period_end` → `no_period`.
    - Citation: for a `correct` with a `correction_citation`, that citation; otherwise, for an `approve` or an auto-accept, the first of the field's citations with `grounded` and `content_key`; otherwise `None` (the gate blocks it). A `correct` or `edit` without a `correction_citation` gets `None` too, never the field's original citation, which supports the old value.
    - Restatement branch, for each candidate `c` with `d = decisions.get(c["candidate_id"])`:
      - `d is None` → `Skip(c["item_key"], "restatement_pending")`; `reject` → `rejected`;
      - `approve` → `value = c["new_value"]` with the unit and canonical fields of the run's field row for `c["item_key"]`; `correct` → `merge_correction(field_row, d)`;
      - in both cases `restated=True` and `restated_by_doc_id = citation.doc_id` (or `c["doc_ids"][0]` when there is no citation), state `approved` or `edited`.
    - Every candidate carries `source_run_id=run_id`, `observed_at=manifest.created_at`, `issuer_scheme=row["issuer_scheme"]`, `basis=f.get("basis") or ""`, and `item_key=key` (for a restatement, `c["item_key"]`).

- [ ] **Step 1: Write the failing tests** in `tests/test_publish_candidates.py` (file-based `RunStore` on `tmp_path`; decisions written with `append_decision`, or with `record_review_decision` and `record_cosign` for legacy rows):
  - `test_trial_run_never_published`: `([], [Skip("*", "trial_run")])`.
  - `test_auto_accepted_field_published_as_system`: `state == "auto_accepted"`.
  - `test_legacy_unrouted_field_not_published`: no `route`, never queued → `Skip(key, "not_auto_accepted")`.
  - `test_first_done_correction_not_published`: a `first` `correct` with `second_required=True` → `not_final`.
  - `test_agreed_correction_published_with_its_citation`: after an agreeing `second` → `state == "edited"`, `value == 1050`, `citation.doc_id` is the correction citation's, `canonical_value is None`.
  - `test_edit_without_correction_citation_has_no_citation`: a final `correct` or legacy co-signed `edit` with no `correction_citation` gives `citation is None` (the gate then blocks it).
  - `test_rejected_and_held_not_published`
  - `test_legacy_cosigned_edit_published`: a legacy `edit` plus a co-sign → `edited`; without the co-sign → `not_final`.
  - `test_restatement_published_only_after_second_approval`: a `first` approve on `rst_1` (`second_required=True`) gives `Skip("ISS:f1:2023-12-31", "restatement_pending")`; after an agreeing `second`, exactly one candidate with `restated is True`, `restated_by_doc_id == "d2"` and `value == 8`.
  - `test_value_item_with_candidate_never_published_plainly`: a final `approve` on the value item `ISS:f1:2023-12-31` while `rst_1` is pending yields no candidate for that key.
  - `test_no_value_and_no_period_skipped`
  - `test_row_without_issuer_key_skipped`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publish_candidates.py tests/test_postgres_company_facts_projection.py -v`. Expect FAIL in the new file only.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(publish): select publishable values: final reviews, system auto-accepts, approved restatements`.

---

### Task 4: Lineage gate and re-grounding (E74)

**Files:**
- Create: `arp/publish/gate.py`
- Test: `tests/test_publish_gate.py` (new)

**Interfaces:**
- Consumes: `Fact` (Task 1); `LocalBlobStore`/`DocumentBlobStore` (`exists`, `get`) from `arp/storage/document_blob_store.py`; `DocumentContentStore.lookup`; `ground_citations` (`arp/grounding.py`); `SourceDocument`, `Citation`.
- Produces, in `arp/publish/gate.py`:
  - `def lineage_error(citation: Citation | None, blob_store) -> str | None`:
    - `citation is None`, not `grounded`, or no `content_key` → `"no_grounded_citation"`
    - `not blob_store.exists(content_key)`, or `get` raises → `"original_missing"`
    - `sha256(blob_store.get(content_key)).hexdigest() != content_key` → `"hash_mismatch"`
    - otherwise None
  - `def reground(fact: Fact, *, blob_store, content_store: DocumentContentStore | None, fuzzy_threshold: float) -> str`:
    - `lineage_error(...)` if set;
    - `"text_unavailable"` when there is no content store, or `lookup(content_key, citation.parser_version)` is None;
    - otherwise grounds `Citation(doc_id, doc_type, quote)` against a `SourceDocument` built from the stored text: `"not_grounded"` when it fails, `"offset_moved"` when `char_start` differs from the stored one, else `"ok"`.
  - `def sample(facts: list[Fact], n: int, *, seed: str) -> list[Fact]`: `random.Random(seed).sample(sorted(facts, key=lambda f: f.fact_id), min(n, len(facts)))`.

- [ ] **Step 1: Write the failing tests** in `tests/test_publish_gate.py` (`LocalBlobStore(tmp_path / "blobs")`; the text store set up as in `tests/test_review_context.py`):
  - `test_missing_original_blocks`: `"original_missing"`.
  - `test_hash_mismatch_blocks`: bytes whose sha256 is not the key.
  - `test_ungrounded_citation_blocks`: `"no_grounded_citation"`, also for `None`.
  - `test_stored_original_passes`: `None`.
  - `test_reground_ok`
  - `test_reground_quote_gone_not_grounded`
  - `test_reground_offset_moved`
  - `test_reground_text_unavailable`: a disabled content store.
  - `test_sample_deterministic_per_seed`: the same seed gives the same ids, a different seed gives a different ordering of 20 facts, and `n > len` returns all.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publish_gate.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(publish): lineage gate re-reads the stored original's hash; re-grounding check (E74)`.

---

### Task 5: Releases, publishing a run, withdrawal (E75, E73 apply)

**Files:**
- Create: `arp/publish/release.py`
- Test: `tests/test_publish_release.py` (new, pure), `tests/test_publish_release_pg.py` (new, Postgres-gated)

**Interfaces:**
- Consumes: `plan_version`, `fact_key`, `Release`, `FactEvent`, `ts_now`, `PublishStore`, `ConcurrentPublish` (Tasks 1, 2); `run_candidates`, `Skip` (Task 3); `lineage_error` (Task 4); `Principal`.
- Produces, in `arp/publish/release.py`:
  - `SYSTEM = "system"`
  - `@dataclass class PublishResult`: `releases: list[Release]`, `reconfirmed: int`, `blocked: list[dict]` (each `{"doc_id": str | None, "reason": str, "item_keys": list[str]}`), `skipped: list[Skip]`
  - `class WithdrawalError(ValueError)`
  - `def split_by_gate(cands, blob_store, *, withdrawn_docs: set[str]) -> tuple[dict[str, list[FactCandidate]], list[dict]]`:
    - a candidate without a citation is blocked alone (`doc_id=None`, `no_grounded_citation`);
    - the others are grouped by `(issuer_key, citation.doc_id)`, so a document cited by two issuers gives two groups; the dict is keyed by that pair;
    - a group whose `doc_id` is in `withdrawn_docs` is blocked with `release_withdrawn`;
    - otherwise the first `lineage_error` among the group's citations blocks the whole group. A missing original blocks the release for that document.
  - `def plan_release(group: list[FactCandidate], current: dict[FactKey, Fact], *, run_id, published_by, published_by_role, storage_uri: str, now: str) -> tuple[Release | None, list[VersionPlan], list[FactEvent]]`:
    - `release_id = new_id("rel")`; one `plan_version` per candidate; the release takes `issuer_key`/`issuer_scheme` from the group, `doc_id` and `content_key` from its citations;
    - a `Release` only when at least one plan is an `insert`;
    - one event per `insert` (`"restated"` when `fact.restated`, else `"published"`).
  - `def publish_run(store: PublishStore, run_store, run_id: str, *, principal: Principal | None, blob_store, now: str | None = None) -> PublishResult`:
    - candidates from `run_candidates`; `withdrawn_docs` = the `doc_id`s of `store.list_releases(run_id=run_id)` whose `withdrawn_at` is set;
    - `split_by_gate`, then `store.current(...)` and `plan_release` per `(issuer_key, doc_id)` group, with `storage_uri = blob_store.uri(content_key)`;
    - `older` plans become `Skip(item_key, "older_than_published")`;
    - `store.save_release` per document;
    - `published_by = principal.user_id if principal else SYSTEM`, and `published_by_role = principal.role if principal else SYSTEM`.
  - `def plan_withdrawal(release: Release, versions: list[Fact], previous: dict[str, Fact], *, reason: str, withdrawn_by: str, now: str) -> tuple[Release, list[Fact], list[Fact], list[FactEvent]]`:
    - a blank `reason` raises `WithdrawalError("a withdrawal needs a reason")`; a set `withdrawn_at` raises `WithdrawalError("release already withdrawn")`.
    - For each version of the release with `valid_to is None`: close it at `now`. When `previous.get(fact_id)` exists, insert a restored copy of it: a new `fact_id`, `version = closed.version + 1`, `valid_from = now`, `valid_to = superseded_by = reconfirmed_at = None`, `restored_from = previous.fact_id`, keeping its value, `release_id`, `restated` and citation. The closed version's `superseded_by` becomes the restored id.
    - Events `withdrawn` (closed) and `restored` (copy).
    - A version already superseded is left as it is.
    - Returns the updated release (`withdrawn_at`, `withdrawal_reason`, `withdrawn_by`), the closed and restored facts, and the events.
  - `def withdraw(store, release_id: str, *, reason: str, principal: Principal, now: str | None = None) -> list[Fact]`: `LookupError` for an unknown release; reads `release_facts` and finds each fact's `previous` as follows: start from `previous_version(fact_id)`, or from `previous_version(restored_from)` when the fact is a restored copy; then walk back with `previous_version` past any version whose release has `withdrawn_at` set, stopping at none. Then `store.save_withdrawal`; returns the restored facts.

- [ ] **Step 1: Write the failing tests.** Pure, in `tests/test_publish_release.py`:
  - `test_one_release_per_document`: three candidates of one issuer (two citing `d1`, one `d2`) give two `plan_release` releases, with `doc_id`s `{"d1", "d2"}`, and every plan's `fact.release_id` is its release's id.
  - `test_republish_unchanged_creates_no_release`: all `reconfirm`, release None, no events.
  - `test_restated_insert_emits_restated_event`
  - `test_missing_original_blocks_whole_document`: `split_by_gate` with `d1`'s blob missing gives one blocked entry `{"doc_id": "d1", "reason": "original_missing", "item_keys": [k1, k2]}`, and `d2` passes.
  - `test_withdrawn_document_not_republished`: `d1` in `withdrawn_docs` gives `release_withdrawn`.
  - `test_document_cited_by_two_issuers_gets_two_releases`: two candidates citing `d1` with different `issuer_key`s give two groups and two releases, each with its own `issuer_key`.
  - `test_withdrawal_restores_previous_fact` (spec): v1 (`rel_a`, 1000) superseded by v2 (`rel_b`, 1100); `plan_withdrawal(rel_b, [v2], {v2.fact_id: v1}, ...)` closes v2 at `now` and restores a copy with `value == 1000`, `version == 3`, `restored_from == v1.fact_id`, `release_id == "rel_a"`, `valid_from == now`. Events `["withdrawn", "restored"]`, and the release has `withdrawn_at == now` and the reason.
  - `test_withdrawal_without_reason_refused`: `"  "` raises `WithdrawalError`.
  - `test_withdrawn_twice_refused`
  - `test_withdraw_first_version_leaves_no_current`: no previous → `restores == []`.
  - `test_superseded_version_not_reopened`

  Postgres, in `tests/test_publish_release_pg.py` (an extraction run on `tmp_path` and a `LocalBlobStore` holding the original):
  - `test_publish_run_end_to_end_pg`: one release and one v1 fact; a second `publish_run` creates no release and sets `reconfirmed_at`.
  - `test_missing_original_blocks_release_pg`: `blocked[0]["reason"] == "original_missing"`, and no rows are written.
  - `test_withdrawal_restores_previous_fact_pg`: runs with 1000, then 1100; withdrawing the second release makes the current value 1000, and `versions(key)` has 3 rows.
  - `test_withdraw_after_restore_skips_withdrawn_release_pg`: releases A (1000), B (1100), C (1200); withdrawing C restores B's value, then withdrawing B leaves 1000 current, not 1100 and not B's restored copy; `release_facts`-based `previous` never points into a withdrawn release.
  - `test_restated_period_shows_both_versions_pg` (spec E73): run 1 publishes `2023-12-31 = 9`; run 2's final restatement gives `versions(key)` with `[0].restated is False` and `value == 9`, and `[1].restated is True`, `value == 8`, `restated_by_doc_id == "d2"`.
  - `test_older_run_republished_is_skipped_pg`: re-publishing run 1 after run 2 gives `Skip(key, "older_than_published")` and leaves the current version unchanged.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publish_release.py tests/test_publish_release_pg.py -v`. Expect FAIL (pure file); the `_pg` file skips locally.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(publish): one release per document, restated versions, withdrawal restores the previous fact (E73, E75)`.

---

### Task 6: As-of reader and the outbox (E76)

**Files:**
- Create: `arp/publish/reader.py`
- Test: `tests/test_publish_reader.py` (new, pure), `tests/test_publish_reader_pg.py` (new, Postgres-gated)

**Interfaces:**
- Consumes: `Fact`, `FactEvent`, `fact_key`, `PublishStore.session` (Tasks 1, 2).
- Produces, in `arp/publish/reader.py`:
  - `def as_of_bound(as_of: str) -> str`: `YYYY-MM-DD` → that day's `23:59:59.999999+00:00`. A timestamp is parsed with `datetime.fromisoformat` (naive means UTC), converted to UTC and formatted with `timespec="microseconds"`. Anything else raises `ValueError(f"bad as_of: {as_of!r}")`.
  - `def visible(facts: Iterable[Fact], as_of: str) -> list[Fact]`: with `b = as_of_bound(as_of)`, keeps `valid_from <= b` and (`valid_to is None` or `valid_to > b`); one per `fact_key` (the highest `version`); sorted by key.
  - `def facts_as_of(store: PublishStore, as_of: str, *, issuer_key: str | None = None, field_id: str | None = None) -> list[Fact]`: the same filter in SQL.
  - `def events_since(store: PublishStore, after: str) -> list[FactEvent]`: `at > after`, ordered by `event_id`.
  - `def read_events(store: PublishStore, *, after_id: int = 0, limit: int = 500) -> list[FactEvent]`: `event_id > after_id`, ordered, at most `limit`.

- [ ] **Step 1: Write the failing tests.** Pure, in `tests/test_publish_reader.py`:
  - `test_fact_published_after_as_of_is_invisible` (spec): `valid_from` `2026-11-02...` gives `visible(..., "2026-10-31") == []`.
  - `test_as_of_date_covers_whole_day`: `valid_from` `2026-10-31T23:00:00.000000+00:00` is visible as of `"2026-10-31"`.
  - `test_superseded_value_shown_before_supersession`: v1 as of a date before v2's `valid_from`, v2 after it.
  - `test_withdrawn_version_still_visible_before_withdrawal`
  - `test_as_of_bound_normalises_offset`: `"2026-10-31T10:00:00+02:00"` → `"2026-10-31T08:00:00.000000+00:00"`.
  - `test_bad_as_of_is_value_error`

  Postgres, in `tests/test_publish_reader_pg.py`:
  - `test_facts_as_of_sql_matches_visible_pg`: the facts saved through `PublishStore` give `facts_as_of` equal to `visible` over `versions`, for three as-of points.
  - `test_events_written_with_release_and_withdrawal_pg`: `read_events` returns `published`, then `withdrawn` and `restored`, in `event_id` order; `events_since(t)` returns only the later ones.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publish_reader.py tests/test_publish_reader_pg.py -v`. Expect FAIL (pure file).

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(publish): as-of reads filter on publication time; change events in an outbox (E76)`.

---

### Task 7: Publish API, CLI and backfill (E17 migration path)

**Files:**
- Modify: `arp/api/deps.py` (`publish_store_dep`, `blob_store_dep`)
- Create: `arp/api/routers/publish.py`; Modify: `arp/api/main.py` (mount it with `dependencies=[Depends(authorize)]`)
- Create: `arp/cli/publish.py`; Modify: `arp/cli/__init__.py` (`app.add_typer(publish_app, name="publish")`)
- Test: `tests/test_publish_api.py` (new)

**Interfaces:**
- Consumes: `publish_run`, `withdraw`, `WithdrawalError`, `SYSTEM` (Task 5); `facts_as_of`, `read_events`, `as_of_bound` (Task 6); `PublishStore`, `ConcurrentPublish`, `public_release` (Tasks 1, 2); `require_role`, `cli_principal`, `ROLE_RANK`; `get_checkpoint`/`set_checkpoint` (`arp/storage/postgres_checkpoints.py`); `blob_store_for`, `IndexingConfig.from_settings`.
- Produces, in `arp/api/deps.py`:
  - `def publish_store_dep(settings: Settings = Depends(settings_dep)) -> PublishStore`: raises `HTTPException(503, "the published-fact store needs ARP_POSTGRES_DSN")` when `postgres_dsn` is unset.
  - `def blob_store_dep(settings = Depends(settings_dep))`: `blob_store_for(IndexingConfig.from_settings(settings))`.
- Routes, in `arp/api/routers/publish.py` (`prefix="/api/publish"`, `tags=["publish"]`; on each route the principal dependency comes first):
  - `POST /runs/{run_id}` (approver) → `{"releases": [public_release], "reconfirmed", "blocked", "skipped": [{"item_key", "reason"}]}`; 404 when there is no manifest; `ConcurrentPublish` → 409.
  - `GET /releases?doc_id=&run_id=` → `{"releases": [public_release]}`.
  - `POST /releases/{release_id}/withdraw` (approver), body `WithdrawRequest{reason: str = Field(min_length=1)}` → `{"restored": [Fact json]}`. `LookupError` → 404; `WithdrawalError("release already withdrawn")` → 409; a blank reason, including whitespace-only, → 422 (`WithdrawalError("a withdrawal needs a reason")` is mapped to 422).
  - `GET /facts?as_of=&issuer_key=&field_id=` → `{"as_of": as_of_bound(as_of or ts_now()), "facts": [...]}`; a `ValueError` → 400.
  - `GET /facts/{fact_id}/lineage` → `store.lineage`; 404.
  - `GET /versions?issuer_key=&field_id=&period_end=&basis=` → `{"versions": [...]}`.
  - `GET /events?after_id=0&limit=500` → `{"events": [...]}`.
- CLI, in `arp/cli/publish.py` (`publish_app`):
  - `arp publish run --run-id ID`: `cli_principal`; below approver → exit 1 with `"publishing needs an approver"`; prints the result as JSON (releases through `public_release`).
  - `arp publish withdraw --release-id ID --reason TEXT` (approver).
  - `arp publish backfill [--full]`: `principal=None` (`SYSTEM`); every non-trial extraction run, ordered by `created_at` ascending; incremental through the checkpoint `"published_facts"` unless `--full`; prints `releases=, reconfirmed=, blocked=, skipped=`. Unset `postgres_dsn` → exit 1.
- Migration: `arp db init-postgres` creates the three tables (create_all). `arp publish backfill` publishes old runs. `company_facts` and its reindex stay unchanged.

- [ ] **Step 1: Write the failing tests** in `tests/test_publish_api.py` (`publish_store_dep` and `blob_store_dep` overridden with a small stub class in the test file):
  - `test_publish_store_missing_dsn_503`: no override, `postgres_dsn` unset → 503 on `GET /api/publish/releases`.
  - `test_publish_requires_approver`: an analyst principal → 403 on `POST /api/publish/runs/r1`.
  - `test_unknown_run_404`
  - `test_withdraw_blank_reason_422`: `""` and `"  "` both give 422, not 500.
  - `test_release_response_has_no_user_id`: the stub's release has `published_by="u_secret"`; the response text has no `u_secret` and no `published_by"`.
  - `test_bad_as_of_400`
  - `test_cli_publish_run_needs_approver`: an analyst `ARP_CLI_TOKEN` → exit code 1.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publish_api.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(publish): publish, withdraw, as-of facts, lineage and events API; CLI and backfill of old runs (E17)`.

---

### Task 8: One holding row; index holdings beside portfolio holdings (E77 canonical row, storage)

**Files:**
- Modify: `arp/schemas/portfolio.py` (`Holding`, `HolderConfig`)
- Modify: `arp/storage/portfolio_store.py` (`kind` on the snapshot methods; revision archive; holder registry; holdings audit)
- Modify: `arp/storage/postgres_models.py` (`HoldingModel`), `arp/storage/postgres_schema.py` (`0003_holdings_intake`), `arp/storage/postgres_portfolio_store.py`, `arp/bi/views.py` (`_HOLDINGS_SELECT`)
- Test: `tests/test_portfolio_store.py`, `tests/test_portfolio_store_parity.py` (extend)

**Interfaces:**
- Produces, in `arp/schemas/portfolio.py`:
  - `Holding`, with `model_config = ConfigDict(populate_by_name=True)`:
    - `holder_id: str = Field(validation_alias=AliasChoices("holder_id", "portfolio_id"))`
    - `kind: Literal["index", "portfolio"] = "portfolio"`
    - `security_id: str`, `as_of_date: str`
    - `isin: str | None = None`, `issuer_key: str | None = None`, `issuer_scheme: str | None = None`
    - `source: Literal["api", "file"] | None = None` (None means written before the intake), `source_ref: str | None = None`
    - `quantity`, `price`, `market_value`, `market_value_eur`, `shares`, `free_float`, `weight_pct: float | None = None`; `currency: str | None = None`; `fx_rate_to_eur: float | None = 1.0`
    - `@property portfolio_id -> str` returns `holder_id`
    - `model_validator(mode="after")`: `kind == "portfolio"` requires `market_value_eur` not None (`"a portfolio holding needs market_value_eur"`)
    - Existing callers (`mock_data.py`, `constituent_import.py`, `postgres_portfolio_store.py`) keep passing `portfolio_id=`.
  - `class HolderConfig(BaseModel)`: `holder_id: str`, `kind: Literal["index", "portfolio"]`, `name: str = ""`, `source: Literal["api", "file"] = "file"`, `as_of: str | None = None` (the newest date with data), `last_pull_at: str | None = None`, `last_error: str | None = None`
- Produces, in `arp/storage/portfolio_store.py` (`kind` defaults to `"portfolio"`, so every existing call is unchanged):
  - `snapshot_path(holder_id, as_of_date, *, kind="portfolio")` (`holder_id` and `as_of_date` go through `safe_id`, here and in `revision_path`): portfolio → today's path. Index → `portfolios_dir / "holdings" / "index" / <holder_id> / "snapshots" / "<date>.jsonl"`.
  - `save_snapshot`, `load_snapshot`, `list_snapshot_dates` and `latest_snapshot_date` take `*, kind="portfolio"`. `all_snapshot_dates` and `load_holdings_as_of` stay portfolio-only.
  - `revision_path(kind, holder_id, as_of_date, revision) -> Path`: `portfolios_dir / "holdings" / "revisions" / kind / <holder_id> / f"{as_of_date}.r{revision}.jsonl"`.
  - `save_revision(kind, holder_id, as_of_date, revision, holdings)`: write-once; an existing file raises `FileExistsError`.
  - `load_revision(kind, holder_id, as_of_date, revision) -> list[Holding]`; `list_revisions(kind, holder_id, as_of_date) -> list[int]`, ascending.
  - `holders_path()` (`portfolios_dir / "holdings" / "holders.json"`); `save_holder(cfg)` (key `f"{kind}:{holder_id}"`, through `_put_json_entry`); `get_holder(kind, holder_id) -> HolderConfig | None`; `list_holders() -> list[HolderConfig]`.
  - `holdings_audit_path()` (`portfolios_dir / "holdings" / "audit.jsonl"`); `append_holdings_audit(row: dict)`.
- Produces, in Postgres:
  - `HoldingModel` gains `kind` (default `"portfolio"`), `isin`, `issuer_key`, `issuer_scheme`, `source`, `source_ref`, `currency`, `shares`, `free_float` (nullable). `quantity`, `price`, `market_value`, `market_value_eur` and `fx_rate_to_eur` become `Mapped[float | None]`. `portfolio_id` keeps its column name, holds `holder_id`, and loses its FK to `portfolios`. The unique constraint becomes `UniqueConstraint("kind", "portfolio_id", "security_id", "as_of_date", name="uq_holdings_kind_holder_security_date")`.
  - `SCHEMA_STEPS` appends `SchemaStep("0003_holdings_intake", ...)`, idempotent:
    - drop any FK from `holdings` to `portfolios` (catalog lookup, as in step 0001);
    - `ALTER TABLE holdings DROP CONSTRAINT IF EXISTS uq_holdings_portfolio_security_date`;
    - `DROP NOT NULL` on the five money columns (`quantity`, `price`, `market_value`, `market_value_eur`, `fx_rate_to_eur`);
    - `UPDATE holdings SET kind = 'portfolio' WHERE kind IS NULL`;
    - add `uq_holdings_kind_holder_security_date` unless `pg_constraint` already has it;
    - call `create_bi_views` again (step 0002 never re-runs), after `arp/bi/views.py` adds `h.kind = 'portfolio'` to `_HOLDINGS_SELECT` and to its latest-date subquery, so `bi.holdings` and `bi.holdings_history` stay portfolio-only.
  - `PostgresPortfolioStore`: the snapshot methods take `kind` and filter `HoldingModel.kind == kind` (`save_snapshot` also deletes by kind). Every query without a kind filter (`all_snapshot_dates`, `_latest_snapshot_per_portfolio`, `_holdings_as_of_join`, `aggregate_holdings_by`, `aggregate_market_value_eur`) gains `HoldingModel.kind == "portfolio"`. `_holding_from_row` maps the new columns. The revision, holder and audit methods and their paths delegate to the file store.

- [ ] **Step 1: Write the failing tests:**
  - `test_old_snapshot_loads_through_alias` (spec, `test_portfolio_store.py`): a raw JSONL line with `"portfolio_id": "P1"` and no `kind` loads with `holder_id == "P1"`, `portfolio_id == "P1"` and `kind == "portfolio"`.
  - `test_unsafe_holder_id_or_date_refused`: `snapshot_path("../x", ...)` and `revision_path(..., "../x", ...)` raise.
  - `test_new_snapshot_writes_holder_id`: the written JSON line has `"holder_id"`.
  - `test_index_path_layout`: the path equals `portfolios_dir/"holdings"/"index"/"IDX1"/"snapshots"/"2026-10-31.jsonl"`.
  - `test_portfolio_holding_requires_market_value_eur`: a `ValidationError`; an `index` holding without it is valid.
  - `test_index_holdings_beside_portfolio_holdings` (parity, both stores): an index holder `"X1"` and a portfolio `"X1"` on the same date load apart by kind, and `load_holdings_as_of` returns only the portfolio rows.
  - `test_revision_archive_is_write_once` (parity): `save_revision` r1 twice raises `FileExistsError`; `list_revisions == [1, 2]` after r2; `load_revision(..., 1)` is unchanged.
  - `test_holders_registry_roundtrip` (parity)
  - `test_public_surfaces_match` (existing) still passes: the new public methods exist on both stores.
  - `test_schema_step_0003_idempotent_pg` (in `tests/test_postgres_schema.py`, gated): `ensure_schema` twice applies `0003_holdings_intake` once; an index row with no `fx_rate_to_eur` whose holder is no portfolio inserts; `bi.holdings` still lists only the portfolio row when an index holder shares a portfolio's id.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_portfolio_store.py tests/test_portfolio_store_parity.py tests/test_postgres_schema.py -v`. Expect FAIL in the file half.

- [ ] **Step 3: Implement as in Interfaces.** Check with `grep -rn "Holding(" arp` that every construction still validates (portfolio rows always set `market_value_eur`).

- [ ] **Step 4: Run** the full backend check. Expect no new failures (the portfolio, aggregation, climate and parity suites pass unchanged).

- [ ] **Step 5: Commit** with `feat(holdings): one canonical holding row with kind and issuer key; index holdings beside portfolio holdings (E77)`.

---

### Task 9: Validation and the CSV/Excel file source (E77)

**Files:**
- Create: `arp/holdings/__init__.py` (empty for now), `arp/holdings/validate.py`, `arp/holdings/file_source.py`, `arp/holdings/mappings/default.json`
- Modify: `pyproject.toml` (`[tool.setuptools.package-data]` `"arp.holdings" = ["mappings/*.json"]`)
- Test: `tests/test_holdings_file_source.py` (new)

**Interfaces:**
- Consumes: `lei_is_valid`, `normalise_lei` (`arp/schemas/issuer.py`); `sniff_delimiter` (`arp/decision/parsing.py`); `openpyxl`.
- Produces, in `arp/holdings/validate.py`:
  - `REQUIRED = {"index": ("isin", "weight"), "portfolio": ("isin", "weight", "market_value", "currency")}`
  - `TEMPLATE_COLUMNS = {"index": ("isin", "lei", "name", "weight", "shares", "free_float", "price", "currency"), "portfolio": ("isin", "lei", "name", "weight", "quantity", "price", "market_value", "currency", "fx_rate_to_eur")}`
  - `NUMERIC = ("weight", "shares", "free_float", "price", "quantity", "market_value", "fx_rate_to_eur")`; `WEIGHT_TOLERANCE = 0.5`
  - `def isin_is_valid(isin: str) -> bool`: ISO 6166. Two letters, nine alphanumerics and a check digit; letters map to 10–35, and the Luhn check runs over the resulting digit string.
  - `def parse_decimal(value, decimal: str) -> float | None`: numbers pass through (not bool). For text, drop spaces, `'` and the other separator, then read `decimal` as the point.
  - `@dataclass(frozen=True) class RowError`: `row: int | None` (the file row number; None for file-level), `column: str | None`, `message: str`
  - `@dataclass class Validated`: `rows: list[dict]` (typed, empty when there is any error), `errors: list[RowError]`
  - `def validate(raw: list[dict], *, kind: str, as_of: str, decimal: str = ".", weight_unit: str = "percent", today: date | None = None) -> Validated`. Each raw row carries `_row`. Errors, all collected:
    - a required column absent from every row → `RowError(None, col, "missing required column")`
    - an empty required cell → `"required"`
    - `isin_is_valid` fails → `RowError(r, "isin", "ISIN check digit fails")`
    - a non-empty `lei` failing `lei_is_valid(normalise_lei(...))` → `RowError(r, "lei", "LEI check digits fail (ISO 17442, mod 97)")`
    - an unparseable number → `"not a number"`
    - a repeated ISIN → `RowError(r, "isin", "duplicate position")`
    - a portfolio row with `currency != "EUR"` and no `fx_rate_to_eur` → `RowError(r, "fx_rate_to_eur", "required for a non-EUR position; ARP never invents FX rates")`
    - the weight sum (after `fraction` × 100) outside `100 ± 0.5` → `RowError(None, "weight", f"weights sum to {s:g}%, not 100% ± 0.5")`
    - `as_of > today` → `RowError(None, None, "as-of date is in the future")`
  - Typed rows have `isin` (upper case), `lei` (normalised or None), `name` and the numeric keys as floats or None; `weight` is in percent.
- Produces, in `arp/holdings/file_source.py`:
  - `class Mapping(BaseModel)`: `provider: str`, `columns: dict[str, str]` (canonical name → file header), `decimal: Literal[".", ","] = "."`, `weight_unit: Literal["percent", "fraction"] = "percent"`, `sheet: str | None = None`
  - `MAPPINGS_DIR = Path(__file__).parent / "mappings"`; `def load_mapping(provider: str) -> Mapping` (an unknown provider or an unsafe name → `ValueError`)
  - `def read_rows(data: bytes, filename: str, mapping: Mapping) -> list[dict]`: `.csv` is decoded `utf-8-sig`, with `sniff_delimiter` and `csv.DictReader`; `.xlsx` is read by `openpyxl` (`read_only`, `data_only`) from `mapping.sheet` or the first sheet, with the header in row 1. Rows are keyed by canonical name, plus `_row` (the file row; the header is row 1). Blank rows are dropped. Any other suffix → `ValueError`.
  - `def template(kind: str, fmt: Literal["csv", "xlsx"]) -> bytes`: the default mapping's headers for `TEMPLATE_COLUMNS[kind]`, as one header row.
  - `def file_ref(data: bytes) -> str`: `"sha256:" + hexdigest`
- `mappings/default.json`: `{"provider": "default", "columns": {"isin": "ISIN", "lei": "LEI", "name": "Name", "weight": "Weight (%)", "shares": "Shares", "free_float": "Free float", "price": "Price", "quantity": "Quantity", "market_value": "Market value", "currency": "Currency", "fx_rate_to_eur": "FX rate to EUR"}, "decimal": ".", "weight_unit": "percent"}`

- [ ] **Step 1: Write the failing tests** in `tests/test_holdings_file_source.py`:
  - `test_csv_and_xlsx_give_identical_rows` (spec): three positions (weights 50, 30, 20) written as CSV text and as an XLSX built with `openpyxl` give equal `validate(read_rows(...)).rows`.
  - `test_one_bad_lei_rejects_file_and_names_row` (spec): data row 2 (file row 3) has a bad LEI. `errors == [RowError(3, "lei", "LEI check digits fail (ISO 17442, mod 97)")]` and `rows == []`.
  - `test_isin_check_digit`: `"US0378331005"` is valid, `"US0378331006"` is not.
  - `test_weights_must_sum_to_100`: 99.0 → error; 99.6 → no error; `fraction` weights 0.5/0.3/0.2 → no error.
  - `test_duplicate_position_rejected`
  - `test_future_as_of_rejected`: `today=date(2026, 10, 4)`, `as_of="2026-10-31"`.
  - `test_non_eur_portfolio_row_needs_fx_rate`
  - `test_decimal_comma_mapping`: `;`-delimited CSV with `"12,5"` and `decimal=","` gives 12.5.
  - `test_missing_required_column_rejected`
  - `test_template_has_mapped_headers`: the CSV template's first line for `index` is `"ISIN,LEI,Name,Weight (%),Shares,Free float,Price,Currency"`; the XLSX template opens with `openpyxl` and has the same header row.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_holdings_file_source.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(holdings): CSV and Excel source with provider mappings; whole-file validation with a row-level report (E77)`.

---

### Task 10: Holdings intake: identity, precedence, audit, revisions, staleness (E77)

**Files:**
- Create: `arp/holdings/intake.py`; Modify: `arp/holdings/__init__.py` (`load`)
- Modify: `arp/schemas/review.py` (`ReviewItemKind.SECURITY = "security"`)
- Modify: `arp/review/items.py` (`"holdings"` in `REVIEWABLE_RUN_TYPES`; `_queue_kind` returns `SECURITY` for a holdings run)
- Modify: `arp/review/decide.py` (`ALLOWED`, `CORRECTED_KEYS`, `_REQUIRED_KEY` and `_check_kind` for `security`)
- Test: `tests/test_holdings_intake.py` (new)

**Interfaces:**
- Consumes: `Holding`, `HolderConfig`, `Portfolio`, the store methods (Task 8); `Validated`, `RowError` (Task 9); `IdentifierMapStore.resolve`; `ARP_NAMESPACE`, `lei_is_valid`, `normalise_lei`; `queue_for_review`, `effective_decisions`; `RunStore`, `RunManifest`; `SecurityRef`, `SecurityResolution`; `Principal`.
- Produces, in `arp/holdings/intake.py`:
  - `class IntakeError(ValueError)`: `status: int`, `message: str`, `errors: list[RowError] = []`
  - `@dataclass class IntakeResult`: `status: Literal["written", "unchanged"]`, `revision: int`, `rows: int`, `unresolved: list[str]`, `review_run_id: str | None`
  - `def provisional_issuer_key(isin: str) -> str`: `f"ARP:{uuid.uuid5(ARP_NAMESPACE, 'isin:' + isin)}"`
  - `def isin_decisions(run_store) -> dict[str, str]`: for every `holdings` run (oldest first), the `effective_decisions(..., cosign_required=set())` rows on `isin:` keys with `decision == "correct"` → `{isin: normalise_lei(corrected_value["value"])}`.
  - `def resolve_issuer(isin: str, lei: str | None, *, idmap, decided: dict[str, str], on: str) -> tuple[str, str, bool]`, as `(issuer_key, issuer_scheme, unresolved)`, in this order:
    - a valid row LEI → `(lei, "LEI", False)`
    - `idmap.resolve("ISIN", isin, on=on)` with exactly one key → `(key, "LEI" if lei_is_valid(key) else "ARP_PROVISIONAL", False)`
    - `decided[isin]` → `(lei, "LEI", False)`
    - otherwise → `(provisional_issuer_key(isin), "ARP_PROVISIONAL", True)`
  - `def ingest(store, validated: Validated, *, kind, holder_id, as_of, source, source_ref, principal: Principal | None, override_reason: str | None, run_store, idmap) -> IntakeResult`:
    1. `validated.errors` → `IntakeError(422, "file rejected", errors)`; an `as_of` that is not an ISO date (`date.fromisoformat`) → `IntakeError(422, "as_of must be YYYY-MM-DD")`.
    2. `holder = store.get_holder(kind, holder_id) or HolderConfig(holder_id=holder_id, kind=kind, source=source)`.
    3. Precedence:
       - `source == "api"` and `holder.source == "file"` → `IntakeError(409, "holder is configured for file intake")`.
       - `source == "file"`, `holder.source == "api"`, any date of the same month (`as_of[:7]`, over `list_snapshot_dates`) already has a revision and `override_reason` is blank → `IntakeError(409, "this month already has API data; an override needs a reason")`.
    4. Rows → `Holding(holder_id, kind, security_id=isin, as_of_date=as_of, isin, issuer_key, issuer_scheme, source, source_ref, weight_pct=weight, ...)`, with `fx_rate_to_eur` = the row's rate, or `1.0` only for EUR, else None; `market_value_eur = market_value * fx` when both are set.
       - `store.save_security(SecurityRef(security_id=isin, isin=isin, name=name or isin, asset_class="other", currency=currency or ""))` only when `get_security(isin)` is None.
       - For an unresolved ISIN with no resolution yet: `store.save_resolution(SecurityResolution(security_id=isin, company_id=None, confidence=0.0, method="isin_exact", needs_review=True))`.
       - For an ISIN that resolves while its stored resolution has `needs_review=True`: save it again with `needs_review=False`.
    5. The latest revision with identical `model_dump` rows → `IntakeResult("unchanged", revision=<latest>, ...)`, and nothing is written.
    6. `revision = len(list_revisions) + 1`; `save_revision(...)`, then `save_snapshot(holder_id, as_of, rows, kind=kind)` (the working copy is the latest revision).
    7. When ISINs are unresolved: `run_id = new_id("hold")`; `run_store.save_manifest(RunManifest(run_id=run_id, run_type="holdings", status=JobStatus.COMPLETED, params={"kind", "holder_id", "as_of", "revision"}))`; then one `queue_for_review(run_store, run_id, f"isin:{isin}", {"kind": "security", "isin", "name", "holder_id", "holder_kind": kind, "as_of", "provisional_issuer_key"})` per ISIN.
    8. `store.append_holdings_audit({"at", "kind", "holder_id", "as_of", "revision", "source", "source_ref", "rows", "user_id": principal.user_id if principal else "system", "role", "override_reason"})`.
    9. For `kind == "portfolio"`, `store.save_portfolio(Portfolio(portfolio_id=holder_id, name=holder.name or holder_id))` when `get_portfolio(holder_id)` is None, so file-store analytics (`load_holdings_as_of`) see it. Then `store.save_holder(holder)` with `as_of = max(holder.as_of or "", as_of)` and `last_error = None`.
  - `def previous_month_end(today: date) -> str`: the last calendar day of the previous month, as `YYYY-MM-DD`. Tasks 13 and 14 import it.
  - `def holder_status(store, today: date) -> list[dict]`: for each holder, `{"holder_id", "kind", "name", "source", "as_of", "last_pull_at", "last_error", "expected_as_of", "stale", "age_days"}`. `expected_as_of = previous_month_end(today)`; `stale = as_of is None or as_of < expected_as_of`; `age_days = (today - as_of).days`, or None.
- Produces, in `arp/holdings/__init__.py`: `def load(store, kind: str, holder_id: str, as_of: str) -> list[Holding]`: the working snapshot of the newest date on or before `as_of` (`list_snapshot_dates(holder_id, kind=kind)`), or `[]`.
- Produces, in the workbench:
  - `ReviewItemKind.SECURITY`; `_queue_kind(run_type="holdings", ...)` → `SECURITY`.
  - `ALLOWED["security"] = _ALL`; `CORRECTED_KEYS["security"] = {"value"}`; `_REQUIRED_KEY["security"] = "value"`.
  - `_check_kind`: a `security` correction needs `lei_is_valid(normalise_lei(value))` (else 422 `"a security correction needs a valid LEI"`) and a comment, like identity.

- [ ] **Step 1: Write the failing tests** in `tests/test_holdings_intake.py` (`PortfolioStore`, `RunStore` and `IdentifierMapStore` on `tmp_path`):
  - `test_isin_resolves_to_lei_through_identifier_map`: an `IdentifierMap(issuer_key=<valid LEI>, scheme="ISIN", value=isin)` gives `issuer_key == LEI` and `issuer_scheme == "LEI"`.
  - `test_unresolved_isin_appears_in_review_workbench` (spec): `result.unresolved == [isin]`; the holding has `issuer_scheme == "ARP_PROVISIONAL"` and `issuer_key.startswith("ARP:")`; `GET /api/review/items` (run store overridden) holds an item with `kind == "security"` and `item_key == f"isin:{isin}"`; `list_resolutions_needing_review()` holds the ISIN.
  - `test_resolved_isin_clears_needs_review`: after the decision resolves the ISIN, the next intake leaves it out of `list_resolutions_needing_review()`.
  - `test_security_correction_needs_valid_lei`: `decide` with `correct` and value `"BAD"` → 422. A valid LEI with a comment → `first_done` (`correction`). After an agreeing `second`, `isin_decisions(run_store) == {isin: LEI}`, and the next intake resolves it.
  - `test_override_without_reason_refused` (spec): an `api` holder with revision 1; a file intake without a reason → `IntakeError` with status 409. With a reason → revision 2; the audit row has `user_id == "u_test"` and the reason; `load_revision(..., 1)` is unchanged.
  - `test_override_needed_for_other_date_in_api_month`: an `api` holder with a revision on 2026-10-31; a file dated 2026-10-30 without a reason → 409.
  - `test_same_rows_twice_unchanged`: `status == "unchanged"` and `list_revisions == [1]`.
  - `test_missing_month_reads_previous`: `load(store, "portfolio", "P1", "2026-11-30")` returns October's rows.
  - `test_intake_portfolio_visible_to_analytics`: after intake, `load_holdings_as_of` returns the portfolio's rows in the file store.
  - `test_holder_status_flags_stale`: holder `as_of="2026-09-30"`, `today=date(2026, 11, 5)` → `stale is True`, `age_days == 36`, `expected_as_of == "2026-10-31"`.
  - `test_non_iso_as_of_refused`: `as_of="../x"` → `IntakeError` 422, nothing written.
  - `test_rejected_file_writes_nothing`: errors give 422, and no revision, snapshot or audit row is written.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_holdings_intake.py tests/test_review_items.py tests/test_review_decide.py -v`. Expect FAIL in the new file only.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(holdings): one intake with ISIN-to-LEI identity, review of unresolved ISINs, precedence, audit and revisions (E77)`.

---

### Task 11: Monthly snapshot: schemas, build, storage, corrections (E77)

**Files:**
- Modify: `arp/config.py` (`snapshot_store_dir: Path = REPO_ROOT / "data" / "snapshot_store"`)
- Create: `arp/snapshots/__init__.py` (empty), `arp/snapshots/schema.py`, `arp/snapshots/build.py`
- Test: `tests/test_snapshots_build.py` (new)

**Interfaces:**
- Consumes: `Fact`, `FactEvent`, `fact_key`, `ts_now` (Task 1); `holdings.load`, `PortfolioStore.list_holders` (Tasks 8, 10); `atomic_write_bytes`.
- Produces, in `arp/snapshots/schema.py`:
  - `CURRENT_MAJOR = 1`
  - `SCHEMAS: dict[int, dict] = {1: {"version": "1.0", "retire_after": None, "datasets": {...}}}`, with keys and columns exactly:
    - `index_holdings`: key `["index_id", "issuer_key", "isin", "as_of"]`; columns `["issuer_scheme", "weight", "shares", "free_float", "price", "currency", "calibration_version"]`
    - `portfolio_holdings`: key `["portfolio_id", "issuer_key", "isin", "as_of"]`; columns `["issuer_scheme", "weight", "market_value", "currency", "fx_rate_to_eur", "source_file"]`
    - `esg_signals`: key `["issuer_key", "field_id", "period_end", "basis"]`; columns `["issuer_scheme", "value", "canonical_unit", "state", "fact_id", "fact_version", "release_id", "published_at", "restated"]`
  - `DATASETS = ("index_holdings", "portfolio_holdings", "esg_signals")`
  - `def header(dataset: str, major: int = CURRENT_MAJOR) -> list[str]`: key plus columns
  - `def live_majors(month: str) -> list[int]`: the majors whose `retire_after` is None or `>= month`, ascending. A breaking change adds major N+1 and sets `retire_after` of major N to the month after it ships, so both run side by side for one month.
  - `class DatasetEntry(BaseModel)`: `name: str`, `major: int`, `schema_version: str`, `rows: int`, `files: dict[str, str]` (`{"csv": sha256, "jsonl": sha256}`)
  - `class SnapshotManifest(BaseModel)`: `snapshot_id: str`, `month: str`, `revision: int`, `as_of: str`, `frozen_at: str`, `schema_version: str` (the current major's), `datasets: list[DatasetEntry]`, `supersedes: str | None = None`, `changes: list[dict] = []`
- Produces, in `arp/snapshots/build.py`:
  - `class SnapshotFrozen(RuntimeError)`
  - `def month_of(as_of: str) -> str` (`"2026-10"`); `def month_end(month: str) -> str` (`"2026-10-31"`)
  - `def snapshot_dir(root: Path, month: str, revision: int) -> Path`: `root / "snapshots" / month / f"r{revision}"`
  - `def dataset_rows(as_of: str, *, portfolio_store, facts: list[Fact]) -> dict[str, list[dict]]`:
    - `index_holdings` and `portfolio_holdings` come from `holdings.load(store, kind, h.holder_id, as_of)` for every registered holder of that kind. `index_id`/`portfolio_id` is the holder id, `as_of` the holding's `as_of_date` and `weight` its `weight_pct`. `fx_rate_to_eur` is the holding's rate. `source_file` is `source_ref` when `source == "file"`, else None. `calibration_version` is None.
    - `esg_signals` has one row per fact: `fact_version = version` and `published_at = valid_from`.
    - Rows are sorted by their key columns.
  - `def render(dataset: str, rows: list[dict], major: int) -> tuple[bytes, bytes]`: CSV (`csv.writer`, `lineterminator="\n"`, the header, None as `""`) and JSONL (`json.dumps({c: row.get(c) for c in header}, sort_keys=True, separators=(",", ":"))` per line).
  - `def build_snapshot(as_of: str, *, root: Path, portfolio_store, facts_as_of: Callable[[str], list[Fact]], revision: int = 1, supersedes: str | None = None, changes: list[dict] = ()) -> SnapshotManifest`:
    - an existing `manifest.json` in `snapshot_dir` → `SnapshotFrozen(f"{snapshot_id} is frozen")`;
    - for each live major and dataset, write `{dataset}.v{major}.csv` and `.jsonl` with `atomic_write_bytes`, then re-read and compare sha256 (a mismatch raises `RuntimeError`);
    - write `manifest.json` last; that write freezes the snapshot. `frozen_at = ts_now()`, and `as_of` is the date passed in.
    - The data files hold no build-time value, so the same inputs give the same hashes.
  - `def read_manifest(root, month, revision: int | None = None) -> SnapshotManifest | None`: the latest revision when None.
  - `def list_months(root) -> list[dict]`: `[{"month", "latest_revision", "snapshot_id", "status"}]`, ascending. `status` is `"frozen"` when the latest revision has a manifest, else `"incomplete"`.
  - `def dataset_path(root, month, revision, dataset, fmt, major) -> Path`
  - `def build_correction(month: str, *, root, portfolio_store, facts_as_of, events_since: Callable[[str], list[FactEvent]], now: str | None = None) -> SnapshotManifest | None`:
    - `latest = read_manifest(root, month)`; None → None.
    - `new` = `events_since(latest.frozen_at)` of type `restated`, `withdrawn` or `restored`; none → None.
    - `events` = the same event types since r1's `frozen_at` (`read_manifest(root, month, 1)`), so a later revision keeps every earlier revision's corrections.
    - The corrected ESG facts are `facts_as_of(month_end(month))`, with each key of `events` replaced by its entry in `facts_as_of(now)`, or dropped when it has none.
    - The result is `build_snapshot(month_end(month), revision=latest.revision + 1, supersedes=latest.snapshot_id, changes=[{"event_type", "fact_id", "issuer_key", "field_id", "period_end", "basis", "at"} for each event in `new`], facts_as_of=lambda _: corrected)`.
    - Holdings are not rebuilt: the correction copies the latest revision's holdings data files byte-for-byte (same hashes), so a later intake revision never changes holdings without a `changes` entry.

- [ ] **Step 1: Write the failing tests** in `tests/test_snapshots_build.py` (holders ingested through Task 10 on `tmp_path`; facts from lambdas):
  - `test_same_inputs_same_hashes` (spec): builds into two roots give equal `files` hashes per dataset, while `frozen_at` may differ.
  - `test_frozen_snapshot_refuses_rewrite` (spec): a second `build_snapshot` for the same month and revision raises `SnapshotFrozen`.
  - `test_manifest_hashes_match_stored_files` (spec): sha256 of every file on disk equals the manifest.
  - `test_r1_stays_readable_after_r2` (spec): build r1; `events_since` returns one `withdrawn` event after `frozen_at`; `build_correction` returns r2 with `supersedes == "2026-10.r1"` and `len(changes) == 1`. `read_manifest(root, "2026-10", 1)` still returns r1, and its files' hashes are unchanged.
  - `test_r3_keeps_r2_corrections`: after r2 (one withdrawn key), a second event on another key gives r3 whose ESG rows still reflect the first correction, with `supersedes == "2026-10.r2"` and `changes` listing only the new event.
  - `test_correction_copies_holdings_files`: an intake revision made after r1 does not change the holdings files of r2 (hashes equal r1's).
  - `test_no_events_no_revision`: `build_correction` returns None.
  - `test_esg_signals_rows_keep_fact_id`
  - `test_csv_and_jsonl_hold_the_same_rows`
  - `test_old_major_built_alongside`: with `SCHEMAS` monkeypatched to add major 2 (one extra column) and `retire_after="2026-11"` on major 1, an October build writes `*.v1.*` and `*.v2.*`, and the manifest lists both majors.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_snapshots_build.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(snapshots): frozen monthly snapshot of holdings and ESG signals with hashes, schema majors and correction revisions (E77)`.

---

### Task 12: Snapshot API, access roles, pull client and CLI (E77)

**Files:**
- Modify: `arp/api/auth.py` (`Principal.roles`, `GRANTS`, `require_grant`, dev principal grants); `config/users.example.json` (one service user with `"roles": ["snapshot_reader"]`)
- Modify: `arp/config.py` (`holdings_api_url: str | None = None`, `holdings_api_token: str | None = None`, `snapshot_pull_dir: Path = REPO_ROOT / "data" / "snapshots"`)
- Create: `arp/api/routers/snapshots.py`; Modify: `arp/api/main.py` (mount it with `dependencies=[Depends(authorize)]`)
- Create: `arp/snapshots/client.py`, `arp/cli/snapshots.py`; Modify: `arp/cli/__init__.py` (`app.add_typer(snapshots_app, name="snapshots")`)
- Test: `tests/test_snapshots_api.py` (new), `tests/test_auth.py` (extend)

**Interfaces:**
- Consumes: `read_manifest`, `list_months`, `dataset_path`, `build_snapshot` (Task 11); `SnapshotManifest`, `CURRENT_MAJOR`, `DATASETS` (Task 11); `facts_as_of` (Task 6).
- Produces, in `arp/api/auth.py`:
  - `Principal.roles: list[str] = Field(default_factory=list)`
  - `GRANTS = ("snapshot_reader", "holdings_reader")`
  - `def require_grant(*names: str) -> Callable`: 403 `f"Requires role '{name}'"` for the first missing name
  - The dev principal gets `roles=list(GRANTS)`. Users-file rows may carry `roles`.
- Routes, in `arp/api/routers/snapshots.py` (`prefix="/api/v1/snapshots"`, `tags=["snapshots"]`; every route requires `snapshot_reader`; `month` must match `^\d{4}-\d{2}$`, else 400):
  - `GET ""` → `{"months": list_months(root)}`
  - `GET /latest` → the newest frozen manifest; 404 when there is none
  - `GET /{month}/manifest?revision=` → `SnapshotManifest`; 404
  - `GET /{month}/{dataset}?format=csv|jsonl&revision=&major=` → the file bytes, `media_type` `text/csv` or `application/x-ndjson`, header `ETag: "<sha256>"`. An unknown dataset, major or revision → 404. `portfolio_holdings` also requires `holdings_reader` (403).
- Produces, in `arp/snapshots/client.py`:
  - `class SnapshotHashMismatch(RuntimeError)`
  - `class SnapshotClient`:
    - `__init__(self, base_url: str, token: str | None, *, http: httpx.Client | None = None)` (tests pass a `TestClient`)
    - `manifest(self, month: str | None = None) -> SnapshotManifest` (`/latest` when None)
    - `pull(self, month: str, datasets: list[str] | Literal["all"], dest: Path, *, fmt: str = "csv", major: int = CURRENT_MAJOR) -> list[Path]`: for each matching entry, it fetches the file with `revision=manifest.revision`. A sha256 that differs from `entry.files[fmt]` raises `SnapshotHashMismatch(f"{name}: hash differs from the manifest")`, and that file is not written. Files land in `dest / month / f"{name}.v{major}.{fmt}"`, plus `manifest.json`.
    - `rows(self, month: str, dataset: str, *, major: int = CURRENT_MAJOR) -> tuple[SnapshotManifest, list[dict]]`: the verified JSONL, parsed.
- CLI, in `arp/cli/snapshots.py` (`snapshots_app`):
  - `arp snapshots build --as-of 2026-10-31`: the portfolio store, plus `facts_as_of` over `PublishStore(dsn)` when `postgres_dsn` is set, else no facts; prints the manifest.
  - `arp snapshots pull --month 2026-10 --dataset all [--base-url URL] [--dest DIR]`: defaults `settings.holdings_api_url`, `settings.holdings_api_token` and `settings.snapshot_pull_dir`; exit 1 on `SnapshotHashMismatch`.

- [ ] **Step 1: Write the failing tests** in `tests/test_snapshots_api.py` (a snapshot built on `tmp_path`; `settings_dep` overridden so `snapshot_store_dir` points there; principals `READER` (`role="viewer"`, `roles=["snapshot_reader"]`) and `FULL` (both grants)):
  - `test_manifest_contract` (spec): `GET /api/v1/snapshots/2026-10/manifest` as `FULL` has keys equal to `SnapshotManifest.model_fields`, validates with `SnapshotManifest`, and has `snapshot_id == "2026-10.r1"`.
  - `test_list_and_latest`
  - `test_dataset_etag_is_hash`: the `ETag` equals the manifest's sha256 for that file.
  - `test_reader_without_holdings_reader_gets_403` (spec): `READER` gets 200 on `esg_signals` and 403 on `portfolio_holdings`.
  - `test_no_snapshot_reader_403`: the conftest approver without grants → 403.
  - `test_bad_month_400`: `/api/v1/snapshots/..%2F/manifest` or `"2026-1"` → 400 or 404, never a file.
  - `test_pull_writes_verified_files`: `SnapshotClient("", None, http=TestClient(app)).pull("2026-10", "all", dest)` writes three CSVs and `manifest.json`.
  - `test_pull_refuses_hash_mismatch` (spec): after one stored file is overwritten on disk, `pull` raises `SnapshotHashMismatch` and that file is absent from `dest`.
  - `test_consumer_on_old_major_still_pulls` (spec): with `SCHEMAS` monkeypatched to make major 2 current and major 1 still live, `pull(..., major=1)` succeeds.
  - `test_dev_principal_has_snapshot_grants` (in `tests/test_auth.py`): the loopback dev principal's `roles == ["snapshot_reader", "holdings_reader"]`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_snapshots_api.py tests/test_auth.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures (`test_auth.py`'s existing assertions on `/api/me` allow the extra `roles` key; update any exact-dict assertion to include `"roles": []`).

- [ ] **Step 5: Commit** with `feat(snapshots): read-only snapshot API with reader roles; pull client that verifies hashes (E77)`.

---

### Task 13: Holdings API source, upload endpoint and CLI (E77)

**Files:**
- Modify: `arp/config.py` (`holdings_pull_day: int = Field(default=2, ge=1, le=28)`)
- Create: `arp/holdings/api_source.py`
- Create: `arp/api/routers/holdings.py`; Modify: `arp/api/main.py` (mount it with `dependencies=[Depends(authorize)]`)
- Create: `arp/cli/holdings.py`; Modify: `arp/cli/__init__.py` (`app.add_typer(holdings_app, name="holdings")`)
- Test: `tests/test_holdings_api.py` (new)

**Interfaces:**
- Consumes: `SnapshotClient.rows` (Task 12); `validate` (Task 9); `ingest`, `IntakeError`, `holder_status`, `previous_month_end` (Task 10); `load_mapping`, `read_rows`, `template`, `file_ref` (Task 9); `get_portfolio_store`, `get_run_store`; `cli_principal`.
- Produces, in `arp/holdings/api_source.py`:
  - `def pull_holder(holder: HolderConfig, as_of: str, *, client: SnapshotClient, base_url: str, store, run_store, idmap, today: date | None = None) -> IntakeResult`:
    - `manifest, rows = client.rows(as_of[:7], "index_holdings" if holder.kind == "index" else "portfolio_holdings")`, keeping the rows whose `index_id`/`portfolio_id` equals `holder.holder_id`;
    - raw rows are `{"_row": n, "isin", "lei": issuer_key if issuer_scheme == "LEI" else None, "weight", ...}` (the dataset columns under their canonical names, `fx_rate_to_eur` included, so a non-EUR portfolio row passes Task 9's FX rule);
    - `validate(raw, kind=holder.kind, as_of=as_of)`, then `ingest(..., source="api", source_ref=f"{base_url}/api/v1/snapshots/{month}/{dataset}?revision={manifest.revision}", principal=None, override_reason=None)`.
    - Success: `holder.last_pull_at = now_iso()` and `last_error = None`. Any exception: `last_pull_at` and `last_error = str(exc)[:500]`, then `save_holder` and re-raise. The previous month stays readable.
  - `def pull_due(store, *, settings, client, today: date, run_store, idmap) -> list[dict]`: for every `api` holder whose `as_of` is earlier than `previous_month_end(today)`, `pull_holder`. Errors are caught and listed as `{"holder_id", "kind", "status": "failed", "error"}`; successes as `{"holder_id", "kind", "status", "revision"}`.
- Routes, in `arp/api/routers/holdings.py` (`prefix="/api/holdings"`, `tags=["holdings"]`):
  - `POST /upload`, multipart: `file: UploadFile`, `holder_id`, `kind`, `as_of`, `provider="default"`, `override_reason: str | None`. The body is read with `file.read(settings.max_upload_bytes + 1)`; more than `max_upload_bytes` → 413 (as `documents.py`). It runs `read_rows`, then `validate` (with the mapping's `decimal` and `weight_unit`), then `ingest(source="file", source_ref=file_ref(data), principal=current_user)`, and returns the `IntakeResult` as a dict. `IntakeError` → `HTTPException(status, {"message", "errors": [asdict(e)]})`. A `ValueError`, `BadZipFile` or `InvalidFileException` from `load_mapping`/`read_rows` → 422 `{"message", "errors": []}`.
  - `GET /template?kind=portfolio&format=csv|xlsx` → bytes with `Content-Disposition: attachment; filename="holdings-template-{kind}.{format}"`
  - `GET /holders` → `{"holders": holder_status(store, date.today())}`
  - `PUT /holders/{kind}/{holder_id}` (approver), body `{"name": str = "", "source": "api" | "file"}`: keeps the status fields, appends a holdings audit row (`user_id`, role, old and new `source`), and returns the holder
  - `POST /holders/{kind}/{holder_id}/pull?as_of=`: 503 `"holdings_api_url is not set"` when unset; otherwise `pull_holder` for `as_of` (default `previous_month_end(today)`)
- CLI, in `arp/cli/holdings.py` (`holdings_app`):
  - `arp holdings import --file positions.xlsx --holder P1 --as-of 2026-10-31 [--kind portfolio] [--provider default] [--override-reason TEXT]` (`cli_principal`); a rejected file prints one line per `RowError` and exits 1.
  - `arp holdings pull [--holder ID --kind K] [--as-of DATE]`
  - `arp holdings template --kind K --format csv|xlsx --out PATH`

- [ ] **Step 1: Write the failing tests** in `tests/test_holdings_api.py` (a fake upstream through `httpx.MockTransport` that serves a manifest and a `portfolio_holdings` JSONL whose hashes match):
  - `test_fake_api_month_lands_once_when_pulled_twice` (spec): two `pull_holder` calls give `list_revisions == [1]`, and the second result has `status == "unchanged"`.
  - `test_failed_pull_keeps_last_month_and_flags` (spec): October pulls fine; November's transport returns 500. The holder has `last_error` set; `load(store, "portfolio", "P1", "2026-11-30")` returns October's rows; `holder_status(...)[0]["stale"] is True`.
  - `test_non_eur_api_month_lands_with_fx_rate`: a `portfolio_holdings` row in USD with `fx_rate_to_eur` pulls without a validation error, and the holding keeps the rate.
  - `test_pull_for_file_holder_refused`: `IntakeError` with status 409.
  - `test_upload_bad_lei_422_names_row`: the JSON detail has `errors[0] == {"row": 3, "column": "lei", ...}`.
  - `test_upload_over_size_limit_413`: a body over `max_upload_bytes` is refused.
  - `test_upload_unreadable_file_422`: a `.xlsx` that is not a zip, and an unknown provider, give 422 with `"errors": []`.
  - `test_upload_over_api_month_without_reason_409`
  - `test_template_download_xlsx_opens`
  - `test_put_holder_needs_approver_and_is_audited`: an analyst gets 403; an approver switching `api` to `file` writes an audit row.
  - `test_holders_response_has_no_user_id`
  - `test_pull_endpoint_503_without_api_url`
  - `test_cli_import_xlsx`: with an approver `ARP_CLI_TOKEN`, `arp holdings import --file positions.xlsx --holder P1 --as-of 2026-10-31` exits 0 and writes revision 1.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_holdings_api.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(holdings): monthly API pull, file upload, template download and holder status; holdings CLI (E77)`.

---

### Task 14: Daily in-process job: re-ground sample, pull, snapshot build, corrections (E74, E77)

**Files:**
- Modify: `arp/config.py` (`publishing_schedule_enabled: bool = Field(default=False)`, `publish_state_dir: Path = REPO_ROOT / "data" / "publish"`, `reground_sample_size: int = Field(default=20, ge=0)`, `snapshot_day: int = Field(default=1, ge=1, le=10)`)
- Create: `arp/publish/scheduler.py`
- Modify: `arp/api/deps.py` (`get_publishing_scheduler`), `arp/api/main.py` (start it and shut it down in `lifespan` beside the other schedulers)
- Test: `tests/test_publishing_scheduler.py` (new)

**Interfaces:**
- Consumes: `IntervalScheduler` (`arp/orchestration/interval_scheduler.py`); `reground`, `sample` (Task 4); `facts_as_of`, `events_since` (Task 6); `PublishStore` (Task 2); `build_snapshot`, `build_correction`, `list_months`, `month_of` (Task 11); `pull_due` (Task 13); `previous_month_end` (Task 10); `SnapshotClient` (Task 12).
- Produces, in `arp/publish/scheduler.py`:
  - `class PublishingScheduleConfig(BaseModel)`: `enabled: bool = False`, `interval_hours: int = 24`, `last_run_at: str | None = None`, `last_reground_day: str | None = None`, `last_results: dict = {}`
  - `def first_business_day_after(month_end: date, n: int = 1) -> date`: the n-th Monday-to-Friday day after `month_end`. Mark `# ponytail: weekdays only, no holiday calendar; add one when a missed holiday matters`.
  - `def due_jobs(today: date, config, *, settings, latest_frozen_month: str | None, holders: list[HolderConfig]) -> list[str]`, in this order:
    - `"reground"` when `settings.postgres_dsn` is set and `config.last_reground_day != today.isoformat()`
    - `"pull"` when `settings.holdings_api_url` is set, `today.day >= settings.holdings_pull_day`, and an `api` holder has `as_of < previous_month_end(today)`
    - `"snapshot"` when `today >= first_business_day_after(<previous month end>, settings.snapshot_day)` and `latest_frozen_month != month_of(<previous month end>)`, and not while `settings.holdings_api_url` is set and either `today.day < settings.holdings_pull_day` or `"pull"` is due (the snapshot waits for the pull)
    - `"corrections"` when `settings.postgres_dsn` is set and `latest_frozen_month` is not None
  - `def reground_sample(facts: list[Fact], *, n: int, day: str, blob_store, content_store, fuzzy_threshold: float, log_path: Path) -> list[dict]`: `sample(facts, n, seed=day)`, then `reground` on each. Each result row `{"day", "fact_id", "result"}` is appended to `log_path`. A result other than `ok` logs a warning naming the fact and the result. Published facts are never changed.
  - `class PublishingScheduler(IntervalScheduler)`: `config_cls = PublishingScheduleConfig`, `job_id = "publishing-schedule"`; `__init__(self, settings, portfolio_store, run_store)` (state in `settings.publish_state_dir`); `_default_config` reads `publishing_schedule_enabled`. `_run` runs each due job in its own `try`/`except`, records `{"status", "detail"}` in `config.last_results[job]` and sets `last_run_at` (and `last_reground_day` after `reground`). The facts come from `facts_as_of(PublishStore(dsn), ...)`, or `[]` without a DSN.

- [ ] **Step 1: Write the failing tests** in `tests/test_publishing_scheduler.py`:
  - `test_first_business_day_after_month_end`: `date(2026, 10, 31)` (a Saturday) gives `date(2026, 11, 2)`; with `n=2`, `date(2026, 11, 3)`.
  - `test_snapshot_due_once_per_month`: due on 2026-11-02 when the latest frozen month is `"2026-09"`; not due once it is `"2026-10"`, and not due on 2026-11-01.
  - `test_snapshot_waits_for_pull`: `holdings_api_url` set, `holdings_pull_day=2`, an `api` holder at `"2026-09-30"`: on 2026-11-02 (pull due) "snapshot" is not due; with the holder at `"2026-10-31"` it is. On 2026-11-01 (before the pull day) it is not due.
  - `test_pull_due_after_pull_day_until_success`: not due on day 1; due on day 3 while a holder's `as_of` is `"2026-09-30"`; not due once it is `"2026-10-31"`.
  - `test_reground_once_per_day_and_needs_dsn`
  - `test_reground_sample_records_results`: two facts, one with a missing original; the log has two rows and one is `original_missing`.
  - `test_scheduler_run_builds_snapshot`: a file holder ingested on `tmp_path`, no DSN, and `today` patched to 2026-11-02; `asyncio.run(scheduler._run(config))` writes the `2026-10` r1 manifest and records `last_results["snapshot"]["status"] == "ok"`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_publishing_scheduler.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** `_run` takes `today` from a module-level `def _today() -> date` so the test can patch it.

- [ ] **Step 4: Run** the full backend check. Expect no new failures (the schedule is off by default, so no test starts it).

- [ ] **Step 5: Commit** with `feat(publish): daily in-process job for the re-ground sample, holdings pull, monthly snapshot and corrections (E74, E77)`.

---

### Task 15: Frontend: holdings intake tab; the `security` review kind

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api/client.ts`
- Create: `frontend/src/lib/holdings.ts`, `frontend/src/pages/portfolio-monitoring/HoldingsIntake.tsx`
- Modify: `frontend/src/pages/PortfolioRiskMonitoringTool.tsx` (add `{ id: "holdings", label: "Holdings Intake" }` to `SUB_TABS` and render `HoldingsIntake`)
- Modify: `frontend/src/lib/reviewKeys.ts`, `frontend/src/components/ReviewControls.tsx` (a `security` correction input)
- Test: `frontend/tests/holdings.test.ts` (new), `frontend/tests/reviewKeys.test.ts` (extend)

**Interfaces:**
- Produces, in `types.ts`:
  - `ReviewItemKind` gains `"security"`
  - `interface HolderStatus { holder_id: string; kind: "index" | "portfolio"; name: string; source: "api" | "file"; as_of: string | null; last_pull_at: string | null; last_error: string | null; expected_as_of: string; stale: boolean; age_days: number | null }`
  - `interface RowError { row: number | null; column: string | null; message: string }`
  - `interface IntakeResult { status: "written" | "unchanged"; revision: number; rows: number; unresolved: string[]; review_run_id: string | null }`
- Produces, in `api/client.ts`:
  - `listHolders()` → `{ holders: HolderStatus[] }`
  - `uploadHoldings(form: { file: File; holder_id: string; kind: string; as_of: string; provider?: string; override_reason?: string })` → `IntakeResult` (FormData)
  - `saveHolder(kind, holderId, body: { name: string; source: "api" | "file" })`
  - `pullHolder(kind, holderId)`
  - `holdingsTemplateUrl(kind, format)`, downloaded through the existing token-aware file helper (`fetchFile`)
- Produces, in `lib/holdings.ts`:
  - `ageLabel(days: number | null): string`: null → `"No data"`, 0 → `"today"`, 1 → `"1 day"`, n → `` `${n} days` ``
  - `rowErrorText(e: RowError): string`: `row === null` → `message`; otherwise `` `Row ${row}${column ? ` (${column})` : ""}: ${message}` ``
  - `parseIntakeError(err: Error): { message: string; errors: RowError[] }`: strips the `"NNN: "` prefix `errorFor` adds and parses the JSON detail; falls back to `{ message: err.message, errors: [] }`
- Produces, in `lib/reviewKeys.ts`: `ITEM_KIND_LABEL.security = "Security"`; `decisionChoices("security")` returns all four; `needsCitation("security") === false`.
- `ReviewControls`: for `kind === "security"`, `Correct…` shows one input `"LEI"` (`corrected_value = { value }`) and requires a comment, like identity.
- `HoldingsIntake`:
  - a holders table (Holder, Kind, Source, As of, Age through `ageLabel`, Last pull, a Status badge: `badge badge-high` "Stale" or plain `badge` "Current", and `last_error` in a `title`), with a "Pull now" button for `api` holders;
  - template download links for both kinds and both formats;
  - an upload form: kind `<select>`, holder id, `<input type="date">` for as-of, `<input type="file" accept=".csv,.xlsx">`, provider (default `"default"`) and an optional override reason. A 422 lists `rowErrorText` lines; a 409 shows the message and focuses the reason field; success announces `"Revision {n} written ({rows} rows)"` or `"No change"`, plus `"{k} ISINs sent to review"` when some are unresolved.

- [ ] **Step 1: Write the failing tests:**
  - `holdings.test.ts`: the `ageLabel` cases; `rowErrorText({ row: 3, column: "lei", message: "bad" }) === "Row 3 (lei): bad"`, and a file-level error returns its message; `parseIntakeError(new Error('422: {"message":"file rejected","errors":[{"row":3,"column":"lei","message":"x"}]}'))` gives the message and one error, and a non-JSON message falls back.
  - `reviewKeys.test.ts`: `ITEM_KIND_LABEL.security === "Security"`; `decisionChoices("security")` has `"correct"`; `needsCitation("security") === false`.

- [ ] **Step 2: Run** `cd frontend && npm test`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** `cd frontend && npm run lint && npm test && npm run build`. Expect 0 errors and 13 warnings.

- [ ] **Step 5: Commit** with `feat(frontend): holdings intake tab with holder staleness and file upload; security review kind (E77)`.

---

### Task 16: Documentation

**Files:**
- Modify: `docs/TECHNICAL_REFERENCE.md`: §2 module map (`publish/`, `holdings/`, `snapshots/`, `api/routers/publish.py`, `holdings.py`, `snapshots.py`); §3.10 (holdings intake, holder status); §3.18 (publication rules, gate, releases, withdrawal, as-of reads, outbox, the daily job); §7 data layout (`published_facts`, `releases`, `fact_events`, `portfolios/holdings/...`, `data/snapshot_store/snapshots/{month}/r{n}/`, `data/snapshots/{month}/`, `data/publish/reground.jsonl`); §8 CLI (`arp publish`, `arp holdings`, `arp snapshots`)

**Interfaces:** none.

- [ ] **Step 1: Write** the sections from this plan's Architecture, Deviations, Global Constraints and Interfaces. They cover:
  - the two layers, and that `company_facts` stays the extraction-record read model
  - what may be published, the skip and block reasons, and that legacy unrouted rows are never published
  - the gate (hash re-read of the stored original) and the nightly re-ground sample
  - one release per document per publish, withdrawal restoring the previous version without reopening history, and restated versions
  - as-of semantics (fixed-width UTC, `valid_from` as the publication time) and the outbox event types
  - `arp db init-postgres` followed by `arp publish backfill` for old runs
  - holdings intake: the mapping format (JSON), validation rules, ISIN-to-LEI identity, the `security` review kind, precedence and override, revisions, staleness, and that FX is never invented
  - the snapshot datasets, files, manifest, schema majors, correction revisions, the two reader roles, and the pull client
  - that index-engine indices are not in `index_holdings` yet, and that cloud adapters wait for the switch-on

- [ ] **Step 2: Run** the backend and frontend checks once more. Expect no new failures.

- [ ] **Step 3: Commit** with `docs: published facts, releases, holdings intake and monthly snapshots (step 5)`.
