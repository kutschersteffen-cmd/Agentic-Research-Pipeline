# XBRL Fact Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A separate XBRL function (core + US/SEC) that downloads and stores `companyfacts` originals, extracts every tagged fact, always resolves revenue and capex, lets the user pick tags from the full taxonomy, and verifies an extraction run against the stored facts, through CLI, API and a frontend page.

**Architecture:** One package, `backend/arp/xbrl_pipeline/`, holds all logic. The CLI group, the `/api/xbrl` router and the `XbrlFacts` page are thin layers over it. A fetch is a `RunStore` run executed by the existing `run_batch`. Data lives as files under `data/xbrl/`. The extraction pipeline is not modified.

**Tech Stack:** Python 3 (FastAPI, Typer, pydantic, httpx, pytest with `asyncio_mode = "auto"`), React 19 + TypeScript (Vite), `node --test` for frontend logic tests.

**Spec:** `docs/superpowers/specs/2026-10-09-xbrl-pipeline-design.md`

## Global Constraints

- No database. All state is files under `Settings.xbrl_dir` (default `REPO_ROOT / "data" / "xbrl"`).
- `extraction/*` and `ingestion/esef.py` are untouched. `ingestion/xbrl.py` gets only the additive public surface in Task 1.
- Tag identifier everywhere: `"<taxonomy>:<Concept>"`, for example `us-gaap:Revenues`.
- Per-company fetch statuses: `ok`, `unchanged`, `no_cik`, `not_found` (result rows) and `error` (a row in the run's `errors.jsonl`).
- Fetch pacing: one company at a time, 0.15 s between requests (the EDGAR default; the SEC limit is 10 requests per second). 3 attempts with backoff on 429 and 5xx. 404 is final.
- Verify tolerance default: relative 0.005. Outcomes: `match`, `mismatch`, `missing_in_run`, `missing_in_xbrl`.
- Verify refuses a run whose `step_settings.json` is missing or shows `xbrl_facts_enabled` true. That flag also gates ESEF facts (`extraction/pipeline.py:187`), so one check covers both.
- All user-supplied names (selection names, company ids) go through `arp.storage.safe_path.safe_id`.
- The router is included in `api/main.py` with `dependencies=[Depends(authorize)]`.
- Frontend: text errors (not colour alone), labelled inputs, 3:1 field borders, touch-size controls; follow `DESIGN.md` and `PRODUCT.md`.
- Every commit message ends with the attribution trailer the session specifies (Co-Authored-By and Claude-Session lines).

## Review Focus

1. A foreign filer (only `ifrs-full` facts) or a CIK the SEC answers 404 for must end as `not_found` with `required` rows marked `not_found`, never as an `error` that blocks the batch. Task 3 and Task 4 tests.
2. The same CIK listed twice, or a universe with duplicate `company_id`: one original on disk, the second company `unchanged`, no crash. Task 4 test.
3. Unsafe names (`../x`, empty, very long) for selections and company ids are rejected with a clear error, in the store and in the API (HTTP 400). Tasks 1, 6 and 9 tests.
4. Verify on a run with no `step_settings.json`, or with XBRL on, must refuse rather than report a circular "match". Task 7 test.
5. A fetch with `--tags` that matches nothing: `facts.jsonl` empty, original stored, `required` still resolved, status `ok`; and a later fetch with different tags is not wrongly `unchanged`. Task 4 tests.

## File Structure

| File | Responsibility |
|---|---|
| `backend/arp/xbrl_pipeline/models.py` | Pydantic row types shared by all modules |
| `backend/arp/xbrl_pipeline/store.py` | `XbrlStore`: the on-disk layout, nothing else |
| `backend/arp/xbrl_pipeline/flatten.py` | companyfacts JSON to fact rows and catalogue |
| `backend/arp/xbrl_pipeline/required.py` | Revenue and capex resolution |
| `backend/arp/xbrl_pipeline/fetch.py` | Per-company fetch, retry, run creation and execution |
| `backend/arp/xbrl_pipeline/registry.py` | Taxonomy snapshots, search, seen counts, extension tags |
| `backend/arp/xbrl_pipeline/selection.py` | Named selections cut from stored originals |
| `backend/arp/xbrl_pipeline/verify.py` | Compare an extraction run with stored revenue and capex |
| `backend/arp/cli/xbrl.py` | Typer commands |
| `backend/arp/api/routers/xbrl.py` | `/api/xbrl` endpoints |
| `frontend/src/lib/xbrlTags.ts` | Pure logic for the page (tested) |
| `frontend/src/components/TagCombobox.tsx` | Searchable multi-select |
| `frontend/src/pages/XbrlFacts.tsx` | The page |

Tests live in `backend/tests/test_xbrl_*.py`, `test_api_xbrl.py`, `test_cli_xbrl.py` and `frontend/tests/xbrlTags.test.ts`. Shared fixture: `backend/tests/fixtures/xbrl/companyfacts_small.json`.

---

### Task 1: Settings, models, store, fixture and the additive xbrl.py surface

**Files:**
- Modify: `backend/arp/config.py` (add `xbrl_dir` beside `documents_dir`; add it to `ensure_dirs`)
- Modify: `backend/arp/ingestion/xbrl.py` (additive only)
- Create: `backend/arp/xbrl_pipeline/__init__.py`, `models.py`, `store.py`
- Create: `backend/tests/fixtures/xbrl/companyfacts_small.json`
- Test: `backend/tests/test_xbrl_store.py`

**Interfaces:**
- Produces, in `ingestion/xbrl.py`: module constants `REVENUE_TAGS = _REVENUE_TAGS`, `CAPEX_TAGS = _CAPEX_TAGS`; method `XbrlFactSource.fetch_company_facts_raw(self, cik: str) -> tuple[dict | None, bytes | None]` that returns `await self._company_facts(cik)`.
- Produces, in `models.py` (all `BaseModel`):
  - `FactRow`: `company_id: str, cik: str, taxonomy: str, concept: str, unit: str, value: float, period_start: str | None, period_end: str, fiscal_year: int | None, fiscal_period: str | None, form: str, filed: str | None, accession: str | None, source_sha: str`
  - `CatalogEntry`: `taxonomy: str, concept: str, label: str | None, fact_count: int, first_year: int | None, last_year: int | None, units: list[str]`
  - `RequiredRow`: `company_id: str, cik: str, metric: Literal["revenue", "capex"], fiscal_year: int | None, status: Literal["found", "not_found"], concept: str | None, value: float | None, unit: str | None, period_start: str | None, period_end: str | None, form: str | None, filed: str | None`
  - `CompanyStatus`: `company_id: str, cik: str | None, status: Literal["ok", "unchanged", "no_cik", "not_found"], source_sha: str | None, fact_count: int`
  - `TagEntry`: `taxonomy: str, concept: str, label: str | None, data_type: str | None, period_type: str | None, balance: str | None, documentation: str | None, deprecated: bool = False, extension: bool = False, seen_count: int = 0`, plus property `tag_id -> str` (`f"{taxonomy}:{concept}"`)
  - `VerifyRow`: `company_id: str, metric: str, fiscal_year: int, outcome: Literal["match", "mismatch", "missing_in_run", "missing_in_xbrl"], run_value: float | None, xbrl_value: float | None, unit: str | None, detail: str`
- Produces, in `store.py`: `class XbrlStore(root: Path)` with
  - `company_dir(cik10: str) -> Path` (validates with `safe_id`)
  - `ciks() -> list[str]`
  - `save_original(cik10: str, raw: bytes) -> str` (writes `companyfacts-<sha16>.json`, idempotent, returns the full sha256 hex)
  - `meta(cik10: str) -> dict | None` and `set_meta(cik10: str, *, source_sha: str, tags: list[str] | None) -> None` (`meta.json`)
  - `original(cik10: str) -> dict | None` (the original whose sha is in `meta`)
  - `write_facts(cik10, rows: Iterable[FactRow]) -> int`, `read_facts(cik10) -> Iterator[FactRow]`
  - `write_catalog(cik10, entries: list[CatalogEntry]) -> None`, `read_catalog(cik10) -> list[CatalogEntry]`
  - `write_required(cik10, rows: list[RequiredRow]) -> None`, `read_required(cik10) -> list[RequiredRow]`
  - `selections_dir -> Path`, `taxonomy_dir -> Path` (both under the root)

- [ ] **Step 1: Create the fixture `companyfacts_small.json`.** Real companyfacts shape (`cik`, `entityName`, `facts` by taxonomy, concept `label`, `units` by unit name, rows with `start`, `end`, `val`, `accn`, `fy`, `fp`, `form`, `filed`). Contents, exactly: `us-gaap:Revenues` (USD) with three rows: FY2023 annual 1000 (period 2022-10-01 to 2023-09-30, 10-K), FY2024 annual 1200 (2023-10-01 to 2024-09-28, 10-K), Q1 FY2024 300 (2023-10-01 to 2023-12-30, fp `Q1`, 10-Q); `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` (USD) with one FY2024 annual row 150; `dei:EntityCommonStockSharesOutstanding` (unit `shares`) with one instant row (`end` 2024-10-18, no `start`) 15000. Total 5 facts, 3 concepts.
- [ ] **Step 2: Write failing tests in `test_xbrl_store.py`:** `test_save_original_is_idempotent_and_returns_sha` (same bytes twice: one file, same sha, `len(sha) == 64`); `test_meta_roundtrip_and_original_loads_latest` (`set_meta` then `original()` equals the parsed fixture); `test_facts_catalog_required_roundtrip`; `test_unsafe_cik_rejected` (`company_dir("../x")` raises `UnsafeIdentifierError`); `test_fetch_company_facts_raw_returns_data_and_bytes` (an `XbrlFactSource` built on a stub `edgar` and a pre-seeded cache file returns `(dict, bytes)`; mirror how `tests` already seed `xbrl_companyfacts_<cik10>.json` — grep `xbrl_companyfacts_` in `backend/tests`).
- [ ] **Step 3: Run `cd backend && pytest tests/test_xbrl_store.py -v`.** Expected: FAIL with import errors.
- [ ] **Step 4: Implement** the settings field, the additive `xbrl.py` surface, `models.py` and `store.py`. JSONL via `arp.storage.jsonl_io` (`read_jsonl`, `append_jsonl`). Atomic writes for `meta.json` via `arp.storage.atomic_io`.
- [ ] **Step 5: Run the tests again.** Expected: PASS. Also run `pytest -k xbrl -q` to confirm the existing XBRL tests still pass.
- [ ] **Step 6: Commit** (`feat(xbrl): store, models and settings for the XBRL pipeline`).

---

### Task 2: Extract all (flatten and catalogue)

**Files:**
- Create: `backend/arp/xbrl_pipeline/flatten.py`
- Test: `backend/tests/test_xbrl_flatten.py`

**Interfaces:**
- Consumes: `FactRow`, `CatalogEntry` (Task 1).
- Produces: `flatten_company_facts(facts: dict, *, company_id: str, cik: str, source_sha: str, concepts: frozenset[str] | None = None) -> Iterator[FactRow]` (yields one row per fact, in file order; `concepts` filters on tag ids; `None` means all) and `build_catalog(facts: dict) -> list[CatalogEntry]` (always complete, ignores any filter).

- [ ] **Step 1: Write failing tests:** `test_flatten_all_yields_every_fact` (fixture gives 5 rows; the Q1 row has `fiscal_period == "Q1"`; the `dei` row has `period_start is None` and `unit == "shares"`); `test_flatten_filters_by_tag_id` (`frozenset({"us-gaap:Revenues"})` gives 3 rows); `test_flatten_empty_filter_matches_nothing` (`frozenset()` gives 0 rows, which is different from `None`); `test_catalog_lists_every_concept` (3 entries; Revenues has `fact_count == 3`, `first_year == 2023`, `last_year == 2024`, `units == ["USD"]`, `label == "Revenues"`).
- [ ] **Step 2: Run** `pytest tests/test_xbrl_flatten.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** both functions. Years come from the row's `fy`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): flatten companyfacts into fact rows and a catalogue`).

---

### Task 3: Required items (revenue and capex)

**Files:**
- Create: `backend/arp/xbrl_pipeline/required.py`
- Test: `backend/tests/test_xbrl_required.py`

**Interfaces:**
- Consumes: `REVENUE_TAGS`, `CAPEX_TAGS`, `XbrlFactSource.fact_for_tags(facts_json, tags, *, fiscal_year)` (static; the existing resolver is reused, not rewritten); `RequiredRow`.
- Produces: `resolve_required(facts: dict, *, company_id: str, cik: str) -> list[RequiredRow]`. Years = the distinct period-end years of annual facts under either tag list. For each year and metric: a `found` row when `fact_for_tags` returns a fact (concept written as `us-gaap:<tag>`), else `not_found`. When no year exists at all, return exactly one `not_found` row per metric with `fiscal_year=None`.

- [ ] **Step 1: Write failing tests:** `test_required_found_for_revenue_and_capex` (fixture: revenue 2023 is 1000 and 2024 is 1200 with concept `us-gaap:Revenues`; capex 2024 is 150 with concept `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`); `test_required_capex_2023_is_not_found_not_guessed` (status `not_found`, value `None`); `test_required_matches_existing_resolver` (for revenue 2024 the value equals `XbrlFactSource.fact_for_tags(fixture, REVENUE_TAGS, fiscal_year=2024).value`); `test_foreign_filer_without_us_gaap_gives_not_found_rows` (a dict with only `ifrs-full` facts gives two rows, both `not_found`, `fiscal_year is None`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `resolve_required`** as described.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): resolve revenue and capex from stored facts`).

---

### Task 4: Fetch pipeline (per company, retry, runs)

**Files:**
- Create: `backend/arp/xbrl_pipeline/fetch.py`
- Test: `backend/tests/test_xbrl_fetch.py`

**Interfaces:**
- Consumes: `XbrlStore`, `flatten_company_facts`, `build_catalog`, `resolve_required`, `CompanyStatus`; `RunStore`, `JobManager` (`create_run("xbrl_fetch", params, n, companies=companies)`, `record_progress`, `finish_run`), `run_batch`, `hold_run` (same imports as `arp/discovery/pipeline.py`); `arp.orchestration.jobs._xbrl_source(settings)` for the real source (precedent: `discovery/refresh.py`).
- Produces:
  - `FETCH_DELAY_SECONDS = 0.15`
  - `async def with_retry(call: Callable[[], Awaitable[T]], *, attempts: int = 3, base_delay: float = 1.0, sleep=asyncio.sleep) -> T` (retries `httpx.HTTPStatusError` with status 429 or 5xx, and `httpx.TransportError`; re-raises after the last attempt; any other error propagates at once)
  - `async def fetch_company(company: CompanyRef, *, source, store: XbrlStore, tags: frozenset[str] | None, refresh: bool, sleep=asyncio.sleep) -> CompanyStatus` (`source` needs `resolve_cik(cik, ticker)` and `fetch_company_facts_raw(cik)`)
  - `create_xbrl_run(companies: list[CompanyRef], tags: list[str] | None, refresh: bool, run_store: RunStore) -> str`
  - `async def execute_xbrl_run(run_id: str, companies: list[CompanyRef], *, settings: Settings, run_store: RunStore, tags: list[str] | None, refresh: bool, source=None) -> str` (`run_batch` with `concurrency=1`, result rows carry `company_id`, which is the key `run_batch` resumes on; check `_KEY_FIELD` in `orchestration/batch_runner.py`)

Behaviour of `fetch_company`: resolve the CIK (none gives `no_cik`); call `with_retry(fetch_company_facts_raw)`; `None` data gives `not_found`; when raw bytes are `None` (cache file from before step 7b) use `json.dumps(data, sort_keys=True).encode()`; `save_original`; the company is `unchanged` only when the sha equals `meta.source_sha` and the requested tag set equals `meta.tags`, in which case nothing else is written; otherwise write facts (filtered by `tags`), catalogue and required, then `set_meta`; always `await sleep(FETCH_DELAY_SECONDS)` after the network call. CIK is zero-padded to 10 digits for the store.

- [ ] **Step 1: Write failing tests** using a fake source and an injected no-op `sleep`: `test_fetch_ok_writes_everything` (status `ok`, `fact_count == 5`, facts file has 5 rows, catalogue 3, required has revenue and capex rows, meta holds the sha); `test_second_fetch_is_unchanged` (same inputs, status `unchanged`); `test_tags_filter_writes_subset_but_keeps_original_and_required` (`tags={"us-gaap:Revenues"}` writes 3 fact rows, the original is on disk, required rows exist); `test_tags_matching_nothing_is_ok_with_empty_facts` (Review Focus 5); `test_changed_tag_set_is_not_unchanged` (fetch with tags A, then tags B: second status is `ok`); `test_404_is_not_found`; `test_no_cik`; `test_same_cik_twice_stores_one_original` (Review Focus 2: statuses `ok` then `unchanged`, exactly one `companyfacts-*.json`); `test_with_retry_succeeds_after_two_429` and `test_with_retry_gives_up_after_three_and_404_is_not_retried` (count calls); `test_run_isolates_a_failing_company_and_resume_retries_it` (three companies, the middle one's fake raises a non-retryable error: the run finishes, `errors.jsonl` has one row, the other two have result rows; re-running `execute_xbrl_run` on the same `run_id` with the fake fixed completes the third).
- [ ] **Step 2: Run** `pytest tests/test_xbrl_fetch.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `fetch.py`. Follow `arp/discovery/pipeline.py` for the run setup, `hold_run`, `record_progress` and `finish_run`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): resumable, paced companyfacts fetch run`).

---

### Task 5: Tag registry (taxonomy snapshots, search, seen counts)

**Files:**
- Create: `backend/arp/xbrl_pipeline/registry.py`
- Create: `backend/tests/fixtures/xbrl/taxonomy_small.xsd`, `taxonomy_small_lab.xml`
- Test: `backend/tests/test_xbrl_registry.py`

**Interfaces:**
- Consumes: `XbrlStore`, `TagEntry`, `CatalogEntry`, `REVENUE_TAGS`, `CAPEX_TAGS`.
- Produces:
  - `TAXONOMY_SOURCES: dict[str, TaxonomySource]` for `us-gaap`, `ifrs-full`, `dei` (URLs per taxonomy-year; filled in Step 1)
  - `parse_taxonomy(xsd: bytes, labels: bytes, *, taxonomy: str) -> list[TagEntry]` (pure: element `name`, `type`, `periodType`, `balance`, standard label, documentation label, deprecation)
  - `class TaxonomyRegistry(store: XbrlStore)` with `write_snapshot(taxonomy: str, year: int, entries: list[TagEntry]) -> None` (`taxonomy/<taxonomy>-<year>.jsonl`), `search(q: str = "", *, taxonomy: str | None = None, seen_only: bool = False, extension_only: bool = False, include_deprecated: bool = True, offset: int = 0, limit: int = 50) -> tuple[list[TagEntry], int]` (items and total)
  - `async def update_taxonomies(store: XbrlStore, *, fetch: Callable[[str], Awaitable[bytes]], taxonomies: list[str] | None = None) -> dict[str, int]` (entries written per taxonomy)

Search rules: the latest snapshot year per taxonomy; case-insensitive substring match on concept or label; `seen_count` is the number of CIK catalogues containing the tag id; concepts found in catalogues but in no snapshot are returned as `extension=True`; an empty `q` puts the tags from `REVENUE_TAGS` and `CAPEX_TAGS` first, then the rest sorted by concept; `total` is the count before paging.

- [ ] **Step 1: Confirm the official sources.** Using the environment's proxy, find and fetch the current official files for the FASB US-GAAP taxonomy (elements schema and labels), the IFRS Accounting Taxonomy (`ifrs-full`) and `dei`. Record the URLs and the year in `TAXONOMY_SOURCES`. If a source is unreachable, stop and report which one; do not guess a URL or invent data.
- [ ] **Step 2: Create the two small fixtures** (4 elements: `Revenues` and `PaymentsToAcquirePropertyPlantAndEquipment` as monetary duration items, one instant `Assets` with `balance="debit"`, one element marked deprecated), mirroring the real file shapes seen in Step 1.
- [ ] **Step 3: Write failing tests:** `test_parse_taxonomy_fields` (label, `period_type`, `balance`, `data_type`, deprecated flag, taxonomy set); `test_search_empty_query_pins_revenue_and_capex_first`; `test_search_filters_by_text_taxonomy_and_deprecated`; `test_seen_count_follows_catalogues` (catalogue A holds `us-gaap:Revenues` and `us-gaap:Assets`, catalogue B holds only `us-gaap:Assets`: `Revenues.seen_count == 1`, `Assets.seen_count == 2`); `test_seen_only_hides_unused_tags`; `test_extension_tag_from_catalogue_is_marked` (`xyz:CustomRevenue` in a catalogue, not in any snapshot, appears with `extension=True`); `test_never_used_tag_has_zero_seen_count`; `test_paging_returns_total_and_slice`; `test_update_taxonomies_writes_snapshots_with_stub_fetch`.
- [ ] **Step 4: Run.** Expected: FAIL.
- [ ] **Step 5: Implement** with `xml.etree.ElementTree`; treat input as untrusted XML (no network entity resolution; use `defusedxml` only if it is already a dependency, else the stdlib parser on bytes without DTD processing).
- [ ] **Step 6: Run.** Expected: PASS.
- [ ] **Step 7: Run `update_taxonomies` for real once** with the proxy and check the snapshot counts are plausible (tens of thousands for `us-gaap`); report the numbers. Do not commit the generated snapshots (`data/` is runtime state; confirm `.gitignore`).
- [ ] **Step 8: Commit** (`feat(xbrl): tag registry over the official taxonomies`).

---

### Task 6: Named selections

**Files:**
- Create: `backend/arp/xbrl_pipeline/selection.py`
- Test: `backend/tests/test_xbrl_selection.py`

**Interfaces:**
- Consumes: `XbrlStore`, `flatten_company_facts`, `safe_id`.
- Produces: `cut_selection(store: XbrlStore, name: str, tags: frozenset[str]) -> int` (writes `selections/<name>.json` with `{name, tags, created_at}` and `selections/<name>.jsonl`; reads each stored original, never the network; returns the fact count), `list_selections(store) -> list[dict]`, `read_selection_facts(store, name: str, *, offset: int = 0, limit: int = 100) -> tuple[list[FactRow], int]`.

- [ ] **Step 1: Write failing tests:** `test_cut_from_original_after_a_different_fetch` (fetch stored with tags B only, cut `us-gaap:Revenues`: 3 rows, no source involved); `test_cut_covers_every_stored_company` (two CIKs); `test_cut_with_unused_tag_returns_zero_and_still_saves`; `test_unsafe_name_rejected` (`../x` and the empty string raise `UnsafeIdentifierError`); `test_list_and_read_paging`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Add `# ponytail: re-reads every stored original, add a per-concept index if cuts get slow`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): named tag selections cut from stored originals`).

---

### Task 7: Verify an extraction run against the stored facts

**Files:**
- Create: `backend/arp/xbrl_pipeline/verify.py`
- Test: `backend/tests/test_xbrl_verify.py`

**Interfaces:**
- Consumes: `RunStore` (`run_dir`, `results_path`, `read_jsonl`), `ExtractionRecord` rows from `runs/<id>/results.jsonl` (`company_id`, `fields[]` with `field_id`, `canonical_value`, `canonical_unit`, `period_end`), `XbrlStore.read_required`, `VerifyRow`.
- Produces: `class CircularRunError(ValueError)` and `verify_run(run_id: str, *, run_store: RunStore, store: XbrlStore, mapping: dict[str, str], tolerance: float = 0.005) -> list[VerifyRow]`. `mapping` maps `"revenue"` and `"capex"` to the extraction `field_id`. It writes `runs/<run_id>/xbrl_verify.jsonl` and returns the rows.

Rules: raise `CircularRunError` when `step_settings.json` is missing or has `xbrl_facts_enabled` true. XBRL values come from all `required.jsonl` files, keyed by `(company_id, metric, fiscal_year)` (`# ponytail: linear scan, index by company when above ~10k companies`). Per run company, per metric, per year (years are the period-end years of any field in that company's record): both values present gives `match` when `abs(run - xbrl) <= tolerance * abs(xbrl)` else `mismatch`; units differing (when both present) is `mismatch` with detail `"unit"`; XBRL `found` but run value missing gives `missing_in_run`; run value present but XBRL missing or `not_found` gives `missing_in_xbrl`; both missing gives no row.

- [ ] **Step 1: Write failing tests** (build a run in a tmp `RunStore`): `test_match_within_tolerance` and `test_mismatch_outside_tolerance` (1.004x inside, 1.006x outside, 0.5% default); `test_missing_in_run`; `test_missing_in_xbrl`; `test_unit_difference_is_mismatch`; `test_refuses_when_xbrl_was_on`; `test_refuses_when_step_settings_missing` (Review Focus 4); `test_writes_verify_jsonl`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): verify an extraction run against stored XBRL facts`).

---

### Task 8: CLI

**Files:**
- Create: `backend/arp/cli/xbrl.py`
- Modify: `backend/arp/cli/__init__.py` (import `xbrl_app`, `app.add_typer(xbrl_app, name="xbrl")`)
- Test: `backend/tests/test_cli_xbrl.py`

**Interfaces:**
- Consumes: Tasks 4 to 7. Pattern: `arp/cli/discovery.py` (`_run_store`, `_and_drain`, `load_company_universe`, `asyncio.run`).
- Produces: `xbrl_app` with `fetch --universe PATH [--tags A,B,C] [--refresh]`, `tags [--search TEXT] [--taxonomy T] [--seen-only] [--limit N]`, `select --name N --tags A,B,C`, `verify RUN_ID [--map revenue=FIELD] [--map capex=FIELD] [--tolerance X]` (exits 1 and prints the guard message on `CircularRunError`), `taxonomy update`.

- [ ] **Step 1: Write failing tests** with Typer's `CliRunner` and `Settings` pointed at tmp dirs: `test_tags_lists_registry_with_seen_counts`; `test_select_writes_selection_and_prints_count`; `test_verify_prints_summary_and_exits_nonzero_on_circular_run`; `test_fetch_runs_with_patched_source` (patch the source builder in `fetch.py` so no network is used; assert the run folder has `results.jsonl` with the company status).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the commands as thin calls into the package.
- [ ] **Step 4: Run, then `arp xbrl --help`** to see the group registered. Expected: PASS and the five commands listed.
- [ ] **Step 5: Commit** (`feat(xbrl): arp xbrl CLI group`).

---

### Task 9: API router

**Files:**
- Create: `backend/arp/api/routers/xbrl.py`
- Modify: `backend/arp/api/main.py` (import the router; `app.include_router(xbrl.router, dependencies=[Depends(authorize)])` beside the others)
- Test: `backend/tests/test_api_xbrl.py`

**Interfaces:**
- Consumes: Tasks 4 to 7. Pattern: `arp/api/routers/discovery.py` (`_run_store` dependency, `asyncio.create_task` for the background run) and `tests/test_api_bi.py` (a `FastAPI()` app with the router, `dependency_overrides` for `deps.settings_dep` and `current_user`, `TestClient`).
- Produces, prefix `/api/xbrl`:
  - `POST /runs` body `{companies?: list[CompanyRef], universe_path?: str, tags?: list[str], refresh?: bool}` returns `{run_id, company_count}` (400 when neither companies nor universe)
  - `GET /runs/{run_id}`, `GET /runs/{run_id}/results?offset&limit`, `POST /runs/{run_id}/retry` (resumes the same run)
  - `GET /tags?q&taxonomy&seen_only&extension_only&offset&limit` returns `{items, total}`
  - `POST /taxonomy/update`
  - `PUT /selections/{name}` body `{tags: list[str]}`, `GET /selections`, `GET /selections/{name}/facts?offset&limit`
  - `GET /required?run_id` (rows for that run's companies)
  - `POST /verify` body `{run_id, mapping, tolerance?}` (409 with the guard message on `CircularRunError`)

- [ ] **Step 1: Write failing tests:** `test_start_run_requires_companies_or_universe` (400); `test_start_run_returns_run_id` (patch `execute_xbrl_run` with a stub); `test_run_results_paged`; `test_tags_search_and_paging`; `test_selection_roundtrip`; `test_unsafe_selection_name_is_400` (Review Focus 3); `test_required_for_run`; `test_verify_circular_is_409`; `test_verify_returns_rows`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the router; name and id inputs go through `safe_id` and map `UnsafeIdentifierError` to HTTP 400, as `routers/documents.py` does.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Run `pytest -q -k "xbrl or api"`** to check nothing else broke.
- [ ] **Step 6: Commit** (`feat(xbrl): /api/xbrl router`).

---

### Task 10: Frontend logic, API client and types

**Files:**
- Create: `frontend/src/lib/xbrlTags.ts`
- Modify: `frontend/src/api/client.ts` (a `// XBRL` block after the Discovery block), `frontend/src/types.ts`
- Test: `frontend/tests/xbrlTags.test.ts`

**Interfaces:**
- Produces, in `xbrlTags.ts` (pure, no DOM): `toggleTag(selected: string[], tagId: string): string[]` (add if absent, remove if present, keeps order, no duplicates); `tagQuery(p: { q?: string; taxonomy?: string; seenOnly?: boolean; extensionOnly?: boolean; offset?: number; limit?: number }): string` (a query string with only the set keys, URL-encoded); `statusText(status: string): string` (plain-language label for `ok`, `unchanged`, `no_cik`, `not_found`, `error`); `verifySummary(rows: { outcome: string }[]): Record<string, number>` (all four outcomes always present, zero when absent).
- Produces, in `client.ts`: `startXbrlRun`, `getXbrlRun`, `getXbrlResults`, `retryXbrlRun`, `searchXbrlTags`, `updateXbrlTaxonomy`, `saveXbrlSelection`, `listXbrlSelections`, `getXbrlSelectionFacts`, `getXbrlRequired`, `verifyXbrl`, each a thin `request(...)` call to the endpoints in Task 9. Types in `types.ts`: `XbrlTag`, `XbrlCompanyStatus`, `XbrlRequiredRow`, `XbrlVerifyRow`.

- [ ] **Step 1: Write failing tests** in the style of `tests/cardKeys.test.ts` (`node:test`, `assert/strict`): `toggleTag` adds, removes and never duplicates; `tagQuery({q: "rev enue", seenOnly: true})` encodes the space and includes `seen_only=true`; `tagQuery({})` is the empty string; `statusText("no_cik")` is non-empty and differs from `statusText("not_found")`; `verifySummary([])` returns four zero counts.
- [ ] **Step 2: Run `cd frontend && npm test`.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the module, the client block and the types.
- [ ] **Step 4: Run `npm test && npm run lint && npx tsc -b`.** Expected: PASS, no type errors.
- [ ] **Step 5: Commit** (`feat(xbrl): frontend logic, client and types`).

---

### Task 11: The XbrlFacts page and the tag dropdown

**Files:**
- Create: `frontend/src/components/TagCombobox.tsx`, `frontend/src/pages/XbrlFacts.tsx`
- Modify: `frontend/src/App.tsx` (lazy import, a `TABS` entry `{ id: "xbrl", label: "XBRL Facts" }`, the render line beside the other pages, and the sidebar grouping list that must contain every tab id; read the grouping block before editing)

**Interfaces:**
- Consumes: Task 10 module and client; `UniversePicker` (as used in `pages/DocumentDiscovery.tsx`) for choosing companies.
- Produces: `TagCombobox({ selected, onChange }: { selected: string[]; onChange: (next: string[]) => void })`: a multi-select combobox that loads options from `api.searchXbrlTags` as the user types (debounced), shows label, tag id, taxonomy and seen count per option, offers filters for taxonomy, extension and seen-only, shows chosen tags as removable chips, and announces the result count through the existing `lib/announce.ts`.

Page areas, as in the spec: Fetch (companies, All or Selected tags, refresh, start, status table with text status labels, retry failed), Tags (the combobox, save as a named selection), Required (revenue and capex per company and year, `not_found` in text), Verify (choose an extraction run, field mapping for revenue and capex, outcome counts from `verifySummary`, mismatch list; the circular-run message shown as text).

- [ ] **Step 1: Load the design skills** (`impeccable:impeccable`, `ui-ux-pro-max:ui-ux-pro-max`) and read `DESIGN.md`, `PRODUCT.md` and `pages/DocumentDiscovery.tsx` for the page's structure and tokens. Reuse existing components and CSS classes before adding new ones.
- [ ] **Step 2: Implement `TagCombobox`** following the ARIA combobox pattern: input `role="combobox"` with `aria-expanded`, `aria-controls`, `aria-activedescendant`; listbox of `role="option"` items; ArrowUp/Down moves, Enter toggles, Escape closes, Backspace on an empty input removes the last chip; every control keyboard-reachable with a visible focus ring; options and chips at touch size.
- [ ] **Step 3: Implement the page** and register it in `App.tsx`.
- [ ] **Step 4: Run `npm run lint && npm test && npm run build`.** Expected: all pass.
- [ ] **Step 5: See it work.** Use the `run` skill to start the backend and the frontend. Open the page in a browser and check: the dropdown opens and a search for "revenue" lists matches with seen counts; keyboard selection adds a chip and Backspace removes it; a fetch on a one-company universe shows its text status; the Verify area shows the guard message for a run that had XBRL on. Take a screenshot at desktop and at phone width and check there is no horizontal scroll. If the SEC is unreachable from the environment, say so and verify the Fetch area against the stubbed API instead.
- [ ] **Step 6: Commit** (`feat(xbrl): XBRL Facts page with tag dropdown`).

---

### Task 12: Documentation and spec alignment

**Files:**
- Modify: `README.md` (add function 18 to the table, after 17: separate from Data-Point Extraction, CLI/API/page, files only)
- Modify: `docs/TECHNICAL_REFERENCE.md` (a section for the XBRL function: layout under `data/xbrl/`, statuses, selection modes, tag registry, verify guard, the one additive change to `ingestion/xbrl.py`)

- [ ] **Step 1: Make the two edits.**
- [ ] **Step 2: Run the whole change's checks:** `cd backend && pytest -q tests/test_xbrl_*.py tests/test_api_xbrl.py tests/test_cli_xbrl.py` and `pytest -q -k "xbrl or extraction"` to prove the extraction pipeline is unaffected; `cd ../frontend && npm test && npm run lint && npm run build`; then the repo's Python linter as configured in `backend/pyproject.toml`. Expected: all pass. Report anything skipped.
- [ ] **Step 3: Commit** (`docs(xbrl): document the XBRL function`), then push `ccr-f2048353-4v08hm`. Do not open a pull request unless asked.
