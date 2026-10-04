# Step 6: Platform (local parts of E5, E12, E13, E15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ARP keeps what it must and deletes only what it may. A run survives its worker being killed and finishes without repeating work, and the document registry can live in Postgres. A load script measures cost and time per 1,000 issuers.

**Architecture:**
- **E5.** `arp/retention.py` holds the retention rules and the cleanup job. A single guard, `delete_expired`, refuses to delete anything younger than its retention period, and every delete goes through it. Anything referenced by a published fact is held.
- **E12.**
  - `arp/orchestration/jobs.py` holds three pieces: the `JobLauncher` seam behind `schedule_llm_run`, a per-run worker lease (a non-blocking `flock`), and `resume_run`.
  - `resume_run` rebuilds a run from what its creator stored (`companies.json`, `schema.json`, `manifest.params`) and re-enters the same `execute_*_run`. `run_batch` skips keys that are already done.
  - Callers reach it through `arp extract run --run-id` and `POST /api/runs/{run_id}/resume`.
- **E13.** Setting `embeddings_backend == "postgres"` moves the document registry, as well as the embeddings, into Postgres. This uses a new `PgDocumentRegistry` behind the existing `DocumentContentStore` facade. Parsed text stays in SQLite, because it is a derived cache.
- **E15.** `arp/scale/` has a report built from `RunManifest` and a load driver. The driver has a simulated mode, used to generate the committed local report, and a live mode, which needs an API key and is the user's to run.

**Tech Stack:** Python 3.11, FastAPI, Typer, Pydantic v2, SQLAlchemy 2 + pgvector (installed extra), stdlib `fcntl`, `os`, `shutil`, `asyncio`, `datetime`; pytest.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4`, section "C to E. Platform" (rows E5, E12, E13, E15) and the "Cloud switch-on" table. Only local defaults are built. No cloud adapter is added, and no `ARP_DEPLOYMENT`, `job_backend`, `run_store_backend` or `object_store_backend` setting either. Paths are relative to `backend/` unless they start with `docs/`. This builds on steps 1 to 5 (`docs/superpowers/plans/2026-10-0*-step*.md`).

**Deviations from the spec text, decided here:**
- **Retention periods.** These are three settings, each defaulting to 3,650 days and each with a 365-day floor:
  - `retention_runs_days`
  - `retention_decision_logs_days`
  - `retention_originals_days`

  Counsel has not confirmed the periods yet; the spec defers bucket lock until they do. Age is the file's own mtime (`lstat`, so a symlink is never followed). The cleanup is dry-run unless `--apply` is passed.
- **What counts as a decision log.** Inside a run directory, a decision log is `review_decisions.jsonl`, `review_cosigns.jsonl` or anything under `snapshots/`. Each of these is kept on its own period. Every other file in the run is deleted together with the rest of the run, and only once the run's newest such file is past `retention_runs_days`, so a run is never left half-deleted. Runs in `running` or `pending` status are never touched.
- **Held items.** A run id that appears as `source_run_id` on any `published_facts` row, or a content key cited by any row (current or past versions), is never deleted. Past versions count because withdrawal restores them.
- **Resume coverage.** Resume covers every run type that runs through `run_batch` over companies: `theme`, `extraction`, `financials`, `tnfd`, `transition_plan`, `identity` and `discovery`. These are not resumed, and you start a new run instead:
  - whole-pass jobs (`calibration`, `taxonomy_research`, `emerging_themes`, and the barrier refresh), which are not keyed per item, so re-running them would repeat rows;
  - `voting`, which is frozen, and whose creator stores no inputs.
- **Resume counters.** Resume rebuilds the counters from the run's files:
  - `completed_count` = the number of result keys;
  - `review_count` = the number of review-queue rows;
  - `failed_count` = 0, because failed items are retried;
  - tokens and cost are kept, because that money was really spent.

  A key that stopped with `ReviewRequired` counts as done, so its review item is not queued twice.
- **No auto-resume at API startup.** Resume is explicit, and the worker lease stops a second worker from starting on the same run.
- **Migrating existing documents.** The Postgres registry reuses the `document_registry` table. That table is currently a projection, and now becomes authoritative when it is selected; the identity columns are added additively by reconciliation. Existing SQLite rows are copied once with `arp documents migrate-registry`. Embeddings are not copied, because they are a cache.
- **Concurrency.** The local 200-issuer report comes from the simulated driver, which tells you about orchestration overhead and nothing about API rate limits. `max_concurrent_llm_calls` stays at 8 until a live run says otherwise.

## Global Constraints

- VOTING IS FROZEN. Do not change any of these:
  - `arp/api/routers/voting.py`, `arp/voting/`, `arp/cli/voting.py`, `arp/stewardship/voting_feed.py`
  - `BallotReview.tsx`, `ReviewerField.tsx`, `ConfirmDecision.tsx`
  - the voting pages, the voting tests, `useReviewer`

  The voting router stays unauthenticated.
- No new dependencies.
- Never invent FX rates.
- The grounding gate must never be weakened.
- Dev auth mode stays the default.
- Clients never see `user_id`.
- No model identifiers in code, commits or docs.
- Every new setting defaults to today's behaviour, so nothing is deleted and nothing moves to Postgres unless it is configured.
- Backend checks: `cd backend && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python -m pytest -q && ruff check arp tests`. The failures must equal the 42-failure Postgres baseline.

## Review Focus

1. A symlink inside `runs/` or the blob store that points outside the directory: the cleanup must neither follow it nor delete its target. *(Task 1 test.)*
2. Two workers resuming the same run at the same moment, for example a CLI resume while the API task is still alive: the second worker is refused (`RunBusy`, HTTP 409) and no item runs twice. *(Task 2 test.)*
3. Resuming a run that is completed, or of a type that cannot be resumed (voting, calibration): the request is refused with a clear message and the run is left as it was. *(Task 3 test.)*
4. A pre-step-6 run with no `companies.json`: theme runs fall back to `universe_path`, and every other type is refused with "run has no stored inputs". *(Task 3 test.)*
5. The Postgres registry receiving a doc_id that is already mapped to different bytes: it logs the collision and assigns a fresh id, exactly as SQLite does. *(Task 4 parity test.)*

---

### Task 1: Retention rules and cleanup job (E5)

**Files:**
- Create: `arp/retention.py`, `arp/cli/retention.py`
- Modify:
  - `arp/config.py`: the three settings, beside `blob_store_dir`
  - `arp/publish/facts.py`: `PublishStore.referenced`
  - `arp/cli/__init__.py`: register `retention`
  - `docs/TECHNICAL_REFERENCE.md`: a retention section
- Test: `tests/test_retention.py`, plus `tests/test_retention_pg.py` for `referenced`

**Interfaces:**
- Produces:
  - `RetentionViolation(Exception)`
  - `RetentionPolicy` (frozen dataclass): `runs: timedelta`, `decision_logs: timedelta`, `originals: timedelta`, and `@classmethod from_settings(s)`
  - `DECISION_LOG_NAMES = {"review_decisions.jsonl", "review_cosigns.jsonl"}` and `DECISION_LOG_DIRS = {"snapshots"}`
  - `delete_expired(path: Path, retention: timedelta, *, now: datetime) -> None`. It uses `lstat` and raises `RetentionViolation` when `now - mtime < retention`. It deletes with `unlink` for files and symlinks, and never calls `rmtree` on a link target.
  - `CleanupReport` (dataclass): `deleted: list[str]`, `held: list[str]`, `kept: int`
  - `cleanup(settings, *, apply: bool, now: datetime | None = None, held_runs: set[str] = frozenset(), held_keys: set[str] = frozenset()) -> CleanupReport`. It walks `settings.runs_dir` and `settings.blob_store_dir`. In dry-run it only reports; otherwise it deletes through `delete_expired` and then removes directories left empty.
  - `PublishStore.referenced(self) -> tuple[set[str], set[str]]`: the distinct `source_run_id` values and `citation->>'content_key'` values over every row.
  - CLI `arp retention cleanup [--apply]`. It takes the held sets from `PublishStore` when `postgres_dsn` is set and empty sets otherwise, then prints the deleted and held lists and a count.

- [ ] **Step 1: Write the failing tests.** Age files with `os.utime`, and use `now = datetime.now(UTC)`. Build settings with `tmp_path` dirs and the defaults (3,650 days).
  - `test_delete_expired_refuses_younger_file`: a file 10 days old with a 3,650-day retention raises `RetentionViolation`, and the file still exists.
  - `test_delete_expired_deletes_older_file`: at 3,651 days the file is gone.
  - `test_cleanup_dry_run_deletes_nothing`: an expired run is reported in `deleted` but is still on disk.
  - `test_cleanup_deletes_expired_run_but_keeps_young_decision_log`:
    - The run's files are 3,651 days old, and `review_decisions.jsonl` is 10 days old.
    - With `apply=True`, `results.jsonl` and `manifest.json` are gone and `review_decisions.jsonl` remains.
  - `test_cleanup_keeps_run_with_one_young_file`: one file aged 10 days keeps every run file, so the run is all-or-nothing.
  - `test_cleanup_skips_running_run`: a manifest with status `running`, with every file old, is kept.
  - `test_cleanup_holds_published_run_and_original`: the run id is in `held_runs` and blob `ab/abcd…` is in `held_keys`. Both are kept, both are listed in `held`, and both are old.
  - `test_cleanup_deletes_expired_original`: an old blob not in `held_keys` is deleted, and its now-empty `ab/` directory is removed.
  - `test_cleanup_never_follows_symlink` (Review Focus 1): `runs/r1/link -> outside/secret.txt` and `blobs/ab/link -> outside/x`, all old. After `apply`, the files under `outside/` still exist.
  - `test_policy_floor`: `Settings(retention_runs_days=30)` raises `ValidationError`.
  - `_pg`: `test_referenced_returns_run_and_content_key` publishes one fact through the step 5 test helpers and asserts `referenced()` contains its `source_run_id` and its citation `content_key`.
- [ ] **Step 2:** Run `pytest tests/test_retention.py -q`. Expected: FAIL, because the import fails.
- [ ] **Step 3: Implement.**
  - Settings: `retention_runs_days: int = Field(default=3650, ge=365)`, and the same for `retention_decision_logs_days` and `retention_originals_days`.
  - A path is a decision log when its name is in `DECISION_LOG_NAMES` or any part relative to the run directory is in `DECISION_LOG_DIRS`.
  - Run age is the maximum `lstat().st_mtime` over the run's non-decision-log files, ignoring `.lock`.
  - Walk with `os.walk(followlinks=False)`.
  - Add the CLI and a `docs/TECHNICAL_REFERENCE.md` section that states the rules above.
- [ ] **Step 4:** Run `pytest tests/test_retention.py tests/test_retention_pg.py -q` (with the DSN). Expected: PASS.
- [ ] **Step 5:** Commit: `feat(retention): retention rules and cleanup job that never deletes inside the period (E5)`

### Task 2: Job launcher, worker lease and stored run inputs (E12, part 1)

**Files:**
- Create: `arp/orchestration/jobs.py`
- Modify:
  - `arp/api/run_scheduling.py`: delegate to the launcher
  - `arp/orchestration/job_manager.py`: `create_run(..., companies=None)`
  - `arp/storage/run_store.py`: `companies_path` and `load_companies`
  - `arp/orchestration/batch_runner.py`: review-stopped keys count as done
  - the creators, passing `companies=`: `create_extraction_run`, `create_financials_extraction_run`, `create_tnfd_extraction_run`, `create_transition_plan_run`, `create_identity_run`, `create_discovery_run`, `create_theme_run`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Produces:
  - `RunBusy(RuntimeError)`
  - `@contextmanager run_lease(run_store, run_id) -> Iterator[None]`. It takes a non-blocking `fcntl.flock(LOCK_EX | LOCK_NB)` on `run_dir/.worker` and raises `RunBusy` if the lock is held. The lock is released on exit and freed by the OS if the process dies.
  - `class JobLauncher(Protocol): def launch(self, run_id: str, job: Callable[[], Awaitable[None]]) -> None`
  - `class LocalJobLauncher`. `launch` runs `job` inside `run_lease` in an `asyncio.create_task`. It keeps each task in `self._tasks: set` until done, so a running job is never garbage-collected, and logs any exception.
  - `get_job_launcher() -> JobLauncher`, a module-level singleton marked `# ponytail: a cloud_run launcher plugs in here at Cloud switch-on.`
  - `schedule_llm_run`: same signature and the same order (clients first, then create), then `get_job_launcher().launch(run_id, lambda: run(run_id, llm, verifier_llm))`.
  - `JobManager.create_run(run_type, params, company_count, model=None, verifier_model=None, companies: list[CompanyRef] | None = None)` writes `companies.json` (a list of `model_dump(mode="json")`, written with `atomic_write_text`) when companies are given.
  - `RunStore.companies_path(run_id) -> Path` and `RunStore.load_companies(run_id) -> list[CompanyRef] | None`.
  - `read_done_keys(results_path, errors_path: Path | None = None) -> set[str]` adds the `key` of each errors row with `review: true`. `run_batch` passes its `errors_path`.

- [ ] **Step 1: Write the failing tests.**
  - `test_run_lease_refuses_second_holder` (Review Focus 2): a second `run_lease` on the same run, nested on another thread or opened through a second `RunStore`, raises `RunBusy`. After the first exits, a new lease succeeds.
  - `test_run_lease_released_when_process_killed`:
    - Start a subprocess (`sys.executable -c`) that takes `run_lease` on a `tmp_path` run, prints `ready`, then sleeps.
    - Wait for `ready`, then `kill()` it and wait.
    - A lease in the test process then succeeds.
  - `test_local_launcher_runs_job_under_lease`: a job that tries to take `run_lease` on the same run itself gets `RunBusy`, which proves the launcher holds the lease. Run it with `asyncio.run` and await the launcher's task set.
  - `test_create_run_stores_companies`: `JobManager.create_run("extraction", {}, 2, companies=[CompanyRef(...), CompanyRef(...)])`, then `load_companies` returns the same two. Without `companies`, `load_companies` returns `None`.
  - `test_review_stopped_key_counts_as_done`: an errors row `{"key": "c1", "review": true, ...}` and a plain error row `{"key": "c2", ...}` give `read_done_keys(results, errors) == {"c1"}`.
  - `test_creators_store_companies`: `create_financials_extraction_run`, `create_transition_plan_run`, `create_identity_run` and `create_discovery_run` each give a run where `load_companies` matches the input.
- [ ] **Step 2:** Run `pytest tests/test_jobs.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the interfaces above.** No voting file changes. `create_voting_run` passes no companies, so voting runs stay non-resumable by construction.
- [ ] **Step 4:** Run `pytest tests/test_jobs.py tests -q -k "run or batch or schedul"`. Expected: PASS, with no new failures against the baseline.
- [ ] **Step 5:** Commit: `feat(jobs): JobLauncher seam, per-run worker lease, stored run inputs (E12)`

### Task 3: Resume for every run type (E12, part 2)

**Files:**
- Modify:
  - `arp/orchestration/jobs.py`: `resume_run`
  - `arp/cli/extraction.py`: `extract run --run-id`
  - `arp/api/routers/runs.py`: `POST /{run_id}/resume`
  - `arp/research/pipeline.py`: `resume_theme_run` falls back to `companies.json` when `universe_path` is missing
  - `arp/cli/runs.py`: the cancel docstring points to `arp extract run --run-id`
  - `docs/TECHNICAL_REFERENCE.md`: a durable-jobs section
- Test: `tests/test_resume_run.py`

**Interfaces:**
- Consumes: `run_lease`, `RunBusy` and `RunStore.load_companies` from Task 2; the existing `execute_*_run` functions and `resume_theme_run`.
- Produces:
  - `RESUMABLE = {"theme", "extraction", "financials", "tnfd", "transition_plan", "identity", "discovery"}`
  - `class NotResumable(ValueError)`
  - `async def resume_run(run_id: str, *, settings: Settings, run_store: RunStore, registry: DocumentSourceRegistry, llm: LLMClient | None = None, verifier_llm: LLMClient | None = None) -> str`

  It works in this order:
  1. Load the manifest. Raise `NotResumable` with these messages:
     - an unknown run: `"Unknown run_id"`
     - status `completed`: `"already completed"`
     - a type not in `RESUMABLE`: `f"{run_type} runs are not resumable; start a new run"`
     - a non-theme run with no `companies.json`: `"run has no stored inputs"`
  2. Run settings come from `settings.model_copy(update=...)` with the manifest's `model` and `verifier_model` when they are set. Missing clients are built from those run settings with `build_llm_client` and `build_verifier_llm_client`. Discovery needs neither client.
  3. Enter `run_lease` (`RunBusy` propagates).
  4. Under `run_store.lock`, rebuild the counters (see the deviations), and set `cancel_requested=False`, `status=RUNNING` and `error=None`.
  5. Dispatch:
     - extraction: `load_run_schema`
     - tnfd: `params["as_of"]`
     - financials: an XBRL source exactly as `get_xbrl_source` builds it from settings
     - theme: `resume_theme_run`
     - every other type: `execute_*_run(run_id, companies, ...)`

     The lease is held for the whole run.
  - CLI `arp extract run --run-id ID` calls `asyncio.run(resume_run(...))` with the CLI's settings, store and registry. It exits 1 with the message on `NotResumable` or `RunBusy`.
  - API `POST /api/runs/{run_id}/resume`, with `dependencies=[Depends(require_role("analyst"))]`:
    - an unknown run returns 404;
    - `NotResumable` returns 400;
    - `RunBusy` returns 409, checked up front by trying the lease once;
    - otherwise it calls `get_job_launcher().launch(run_id, lambda: resume_run(...))` and returns `{"run_id": run_id, "status": "resumed"}`. The launcher already holds the lease, so in that path `resume_run` must take `lease=False`. Add the keyword `lease: bool = True`.

- [ ] **Step 1: Write the failing tests.** Use `create_transition_plan_run` with 6 companies, and monkeypatch `arp.transition_plan.pipeline._assess_company` and `prepare_company` with a fake that records calls and returns a minimal `TransitionPlanAssessmentResult`.
  - `test_killed_worker_resumes_without_repeats` (the spec's test):
    1. Start `execute_transition_plan_run` as a task. The fake blocks on an `asyncio.Event` after 3 companies have returned.
    2. Once 3 result rows exist, cancel the task (the kill).
    3. Release the fake and call `resume_run`.
    4. Assert:
       - `results.jsonl` holds each of the 6 company ids exactly once;
       - the fake was called once for each of the 3 companies done before the kill;
       - the manifest has `completed_count == 6` and status `completed`;
       - there are no duplicate `item_key` rows in `review_queue.jsonl`.
  - `test_resume_refuses_completed_run` (Review Focus 3): the error contains "already completed", and the manifest is unchanged.
  - `test_resume_refuses_non_resumable_types`: the types `voting`, `calibration` and `emerging_themes` (made with `JobManager.create_run`) each raise `NotResumable`.
  - `test_resume_refuses_run_without_inputs` (Review Focus 4): a `financials` run created with no companies gives "run has no stored inputs".
  - `test_resume_theme_falls_back_to_companies_json`: a theme run with `universe_path=None` and stored companies reaches `execute_theme_run` with those companies. Monkeypatch `execute_theme_run` to capture them.
  - `test_resume_resets_failed_and_retries`: a run with one prior plain error row and `failed_count=1` that succeeds on resume ends with `failed_count == 0` and status `completed`.
  - `test_resume_busy_run_refused`: while a `run_lease` is held, `resume_run` raises `RunBusy`, and the API returns 409.
  - `test_resume_endpoint_requires_analyst`: in `auth_mode="local"`, a viewer token gets 403.
  - `test_cli_extract_run_resumes`: `CliRunner` with `extract run --run-id`, against the same monkeypatched fake, exits 0 and finishes the run.
- [ ] **Step 2:** Run `pytest tests/test_resume_run.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the interfaces above.**
- [ ] **Step 4:** Run `pytest tests/test_resume_run.py tests/test_jobs.py -q`, then the full backend run. Expected: PASS, and the failures equal the baseline.
- [ ] **Step 5:** Commit: `feat(jobs): arp extract run --run-id resumes every batch run type (E12)`

### Task 4: Document registry in Postgres (E13)

**Files:**
- Create: `arp/storage/postgres_document_registry.py`
- Modify:
  - `arp/storage/postgres_models.py`: add the nullable columns `family_id`, `version`, `supersedes`, `published_at`, `identity_confidence` and `identity_review` to `DocumentRegistryModel`, and update its docstring (authoritative when selected)
  - `arp/storage/parsed_content_cache.py`: `parsed_keys`
  - `arp/storage/document_store.py`: the `postgres_dsn` kwarg
  - `arp/retrieval/content_store_factory.py`: `content_store_for`
  - the constructor sites, which call `content_store_for(settings)`:
    - `arp/api/deps.py:93`
    - `arp/cli/_shared.py:46`
    - `arp/cli/db.py:131,186,231`
    - `arp/storage/document_search_factory.py:21`
    - `arp/emerging_themes/scheduler.py:70`
    - `arp/publish/scheduler.py:124`

    Leave `arp/api/routers/extraction.py:325` (`enabled=False`) as it is.
  - `arp/cli/documents.py`: `migrate-registry`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_postgres_document_registry_pg.py`

**Interfaces:**
- Produces:
  - `class PgDocumentRegistry`, constructed as `PgDocumentRegistry(dsn: str, enabled: bool, parsed_keys: Callable[[list[str]], set[str]])`. It has the same public methods and return types as `DocumentRegistry`:
    - `register_document(**)`, with the collision guard and the same upsert columns, using `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update`
    - `resolve_document`, `set_storage_uri`, `set_identity`, `list_family`, `list_by_content_keys`, `list_all`
    - `readiness_by_company`: registered count, doc types and last seen come from Postgres; `parsed` comes from `parsed_keys`
    - `stats() -> dict`, taking no connection
    - `__init__` calls the same schema-ensure function `PublishStore` uses
  - `ParsedContentCache.parsed_keys(self, content_keys: list[str]) -> set[str]`: the keys that have any `parsed_content` row, batched by 900.
  - `DocumentContentStore(store_dir, enabled=True, *, postgres_dsn: str | None = None)`. With a DSN:
    - `self._registry = PgDocumentRegistry(dsn, enabled, self._parsed_content.parsed_keys)`
    - `self._embeddings = PgVectorEmbeddingsStore(dsn)`
    - `stats()` merges `self._registry.stats()` instead of `stats(conn)`, and adds `"registry_backend": "postgres"`
  - `content_store_for(settings) -> DocumentContentStore` passes `postgres_dsn=settings.postgres_dsn` only when `settings.embeddings_backend == "postgres"`.
  - `copy_sqlite_registry(store_dir: Path, dsn: str) -> int` in `postgres_document_registry.py`. It reads every SQLite row through `DocumentRegistry.list_all` and upserts it keeping the SQLite `first_seen_at`, `last_seen_at`, `storage_uri` and identity columns, then returns the count. It is idempotent.
  - CLI `arp documents migrate-registry` refuses (exit 1) unless `embeddings_backend == "postgres"` and `postgres_dsn` is set.

- [ ] **Step 1: Write the failing tests (`_pg`).** Parametrize over `sqlite` and `postgres` registries built through `DocumentContentStore`, with a truncated table per test. Assert identical results for:
  - register, then resolve;
  - re-register (updates `last_seen_at`, keeps `first_seen_at`);
  - `set_storage_uri`, `set_identity`, then `list_family` ordering by `(version, doc_id)`;
  - `list_documents_by_content_keys`, `list_all_documents`;
  - `readiness_by_company`, with one parsed and one unparsed document.

  Also:
  - `test_collision_assigns_fresh_id` (Review Focus 5): register `doc_x` for company A with content key k1, then register `doc_x` for company B with key k2. The returned id differs from `doc_x`, and `doc_x` still resolves to A/k1. Run it for both backends.
  - `test_content_store_for_selects_backend`: with `embeddings_backend="postgres"` and a DSN, `stats()["registry_backend"] == "postgres"`; with the default, there is no Postgres and no change.
  - `test_copy_sqlite_registry_is_idempotent`: two SQLite rows with identity columns. The first copy returns 2, Postgres rows equal the SQLite rows field by field, and a second copy leaves the table unchanged.
- [ ] **Step 2:** Run `pytest tests/test_postgres_document_registry_pg.py -q` (with the DSN). Expected: FAIL.
- [ ] **Step 3: Implement the interfaces above.**
- [ ] **Step 4:** Run the new tests, then the full backend run. Expected: PASS, and the failures equal the baseline.
- [ ] **Step 5:** Commit: `feat(storage): document registry in Postgres via embeddings_backend (E13)`

### Task 5: Load script and cost/time report (E15)

**Files:**
- Create: `arp/scale/__init__.py`, `arp/scale/report.py`, `arp/scale/load.py`, `arp/cli/scale.py`, and `docs/scale/2026-10-04-local-200-issuers.md` (generated)
- Modify: `arp/cli/__init__.py` (register `scale`), `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_scale.py`

**Interfaces:**
- Produces:
  - `RunReport` (Pydantic): `run_id`, `run_type`, `status`, `concurrency: int | None`, `issuers: int`, `completed: int`, `failed: int`, `review: int`, `duration_s: float`, `input_tokens: int`, `output_tokens: int`, `cost_usd: float`, `cost_per_1000_usd: float`, `minutes_per_1000: float`, `issuers_per_minute: float`.
  - `run_report(m: RunManifest) -> RunReport`:
    - `duration_s = updated_at - created_at`;
    - the per-1,000 figures scale by `issuers = completed + failed`;
    - every rate is 0.0 when `issuers == 0` or `duration_s == 0`;
    - `concurrency = m.params.get("concurrency")`.
  - `render_markdown(reports: list[RunReport], *, title: str, note: str) -> str`: one table row per run, plus the note.
  - `async simulate(n: int, concurrency: int, *, run_store: RunStore, latency_s: float = 0.05, tokens: tuple[int, int] = (6000, 800), cost_per_call_usd: float = 0.03, fail_every: int = 0) -> str`:
    - creates a `JobManager` run of type `"load_test"` with `params={"concurrency": c, "mode": "simulated", "latency_s": latency_s}` and synthetic companies `LOAD{i:04d}`;
    - drives `run_company_batch` with a worker that sleeps `latency_s` and returns an object carrying `usage`;
    - `fail_every > 0` makes every k-th company raise;
    - no network.
  - `async live(universe_path: Path, schema_path: Path, concurrency: int, *, settings, run_store, registry) -> str`: `create_extraction_run` plus `execute_extraction_run`, with `settings.model_copy(update={"max_concurrent_llm_calls": concurrency})` and `params["concurrency"]` recorded.
  - CLI:
    - `arp scale load --issuers 200 --concurrency 4,8,16 [--live --universe P --schema P] [--latency 0.05] [--out docs/scale/x.md]` runs one run per concurrency level, then writes `render_markdown`.
    - `arp scale report RUN_ID... [--out P]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_run_report_math`: a manifest with 200 completed, 0 failed, created at `T`, updated at `T + 100 s`, and cost 6.0 gives `cost_per_1000_usd == 30.0`, `minutes_per_1000 == pytest.approx(8.333, rel=1e-3)` and `issuers_per_minute == 120.0`.
  - `test_run_report_zero_issuers`: every rate is 0.0, with no `ZeroDivisionError`.
  - `test_simulate_records_counts_and_cost`: `simulate(20, 4, latency_s=0, fail_every=5)` gives `completed == 16`, `failed == 4`, `cost_usd == pytest.approx(16 * 0.03)` and status `partially_completed`.
  - `test_render_markdown_has_row_per_run`: two reports give two table rows containing their run ids.
  - `test_cli_scale_load_writes_report`: `CliRunner` with `scale load --issuers 10 --concurrency 2,4 --latency 0 --out tmp/x.md`. The file exists and has 2 rows.
- [ ] **Step 2:** Run `pytest tests/test_scale.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the interfaces above.**
- [ ] **Step 4:** Run `pytest tests/test_scale.py -q`. Expected: PASS.
- [ ] **Step 5: Generate the local report.**
  - Run `arp scale load --issuers 200 --concurrency 4,8,16 --latency 0.5 --out ../docs/scale/2026-10-04-local-200-issuers.md`, with `ARP_RUNS_DIR` set to a scratch directory so no `runs/` are committed.
  - The note states that the run is simulated (0.5 s per company, no API), that it measures orchestration only, that the default stays at 8, and how to run `--live`.
  - Add `TECHNICAL_REFERENCE.md` lines for E15.
- [ ] **Step 6:** Commit: `feat(scale): load script and cost/time report from RunManifest; local 200-issuer report (E15)`
