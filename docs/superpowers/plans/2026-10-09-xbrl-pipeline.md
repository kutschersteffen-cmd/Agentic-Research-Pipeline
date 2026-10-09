# XBRL Fact Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A separate XBRL function (core + US/SEC) that downloads and stores each company's `companyfacts` JSON and latest 10-K as filed, extracts every tagged fact, always resolves revenue and capex, lets the user pick tags from the full taxonomy, shows files and facts in tables, and verifies an extraction run against the stored facts, through CLI, API and a frontend page.

**Architecture:** One package, `backend/arp/xbrl_pipeline/`, holds all logic. The CLI group, the `/api/xbrl` router and the `XbrlFacts` page are thin layers over it. A fetch is a `RunStore` run executed by the existing `run_batch`. Data lives as files under `data/xbrl/`. The extraction pipeline is not modified.

**Tech Stack:** Python 3 (FastAPI, Typer, pydantic, httpx, pytest with `asyncio_mode = "auto"`), React 19 + TypeScript (Vite), `node --test` for frontend logic tests.

**Spec:** `docs/superpowers/specs/2026-10-09-xbrl-pipeline-design.md`

## Global Constraints

- No database. All state is files under `Settings.xbrl_dir` (default `REPO_ROOT / "data" / "xbrl"`).
- `extraction/*` and `ingestion/esef.py` are untouched. `ingestion/xbrl.py` and `ingestion/edgar.py` get only the additive public surface in Task 1.
- The XBRL function never registers documents in the shared document store, blob store or search index: its SEC source is built without `content_store` or `indexing_config`.
- Tag identifier everywhere: `"<taxonomy>:<Concept>"`, for example `us-gaap:Revenues`.
- Per-company fetch statuses: `ok`, `unchanged`, `no_cik`, `not_found` (result rows) and `error` (a row in the run's `errors.jsonl`). Report outcome per company: `stored`, `unchanged`, `none`, `error`; a report outcome never changes the company's status.
- Fetch pacing: one company at a time, 0.15 s between requests (the EDGAR default; the SEC limit is 10 requests per second). 3 attempts with backoff on 429 and 5xx. 404 is final.
- Table years are the calendar year of the period end, never companyfacts' `fy` (that labels comparatives with the filing's year).
- Verify tolerance default: relative 0.005. Outcomes: `match`, `mismatch`, `missing_in_run`, `missing_in_xbrl`.
- Verify refuses a run whose `step_settings.json` is missing or shows `xbrl_facts_enabled` true. That flag also gates ESEF facts (`extraction/pipeline.py:187`), so one check covers both.
- Stored files are served only as downloads: `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox`. The 10-K is never rendered inside the app.
- All user-supplied names, CIKs and file kinds are validated (`arp.storage.safe_path.safe_id`, a fixed set of kinds).
- The router is included in `api/main.py` with `dependencies=[Depends(authorize)]`.
- Frontend: text errors (not colour alone), labelled inputs, 3:1 field borders, touch-size controls; follow `DESIGN.md` and `PRODUCT.md`.
- Every commit message ends with the attribution trailer the session specifies (Co-Authored-By and Claude-Session lines).

## Review Focus

1. A foreign filer (only `ifrs-full` facts) or a CIK the SEC answers 404 for ends as `not_found` with `required` rows marked `not_found`, never an `error` that blocks the batch. Tasks 3 and 4 tests.
2. The same CIK listed twice, or a universe with duplicate `company_id`: one `companyfacts` original and one report on disk, the second company `unchanged`, no crash. Task 4 test.
3. Unsafe CIKs, selection names and file kinds (`../x`, empty, unknown kind) are rejected with a clear error in the store and as HTTP 400 or 404 in the API; downloads carry the attachment, nosniff and sandbox headers. Tasks 1, 6, 8 and 10 tests.
4. Verify on a run with no `step_settings.json`, or with XBRL on, refuses rather than reporting a circular "match". Task 7 test.
5. A 10-K that is not inline XBRL, a company with no 10-K, or a report download that fails leaves the company's facts saved and its status `ok`. Task 4 tests.

## File Structure

| File | Responsibility |
|---|---|
| `backend/arp/xbrl_pipeline/models.py` | Pydantic row types shared by all modules |
| `backend/arp/xbrl_pipeline/store.py` | `XbrlStore`: the on-disk layout, nothing else |
| `backend/arp/xbrl_pipeline/flatten.py` | companyfacts JSON to fact rows and catalogue |
| `backend/arp/xbrl_pipeline/required.py` | Revenue and capex resolution |
| `backend/arp/xbrl_pipeline/fetch.py` | Source wrapper, per-company fetch, retry, run creation and execution |
| `backend/arp/xbrl_pipeline/registry.py` | Taxonomy snapshots, search, seen counts, extension tags |
| `backend/arp/xbrl_pipeline/selection.py` | Named selections cut from stored originals |
| `backend/arp/xbrl_pipeline/verify.py` | Compare an extraction run with stored revenue and capex |
| `backend/arp/xbrl_pipeline/views.py` | File listing, facts query, by-year pivot, download resolution |
| `backend/arp/cli/xbrl.py` | Typer commands |
| `backend/arp/api/routers/xbrl.py` | `/api/xbrl` endpoints |
| `frontend/src/lib/xbrlTags.ts` | Pure logic for the page (tested) |
| `frontend/src/components/TagCombobox.tsx` | Searchable multi-select |
| `frontend/src/components/XbrlFactsTable.tsx` | Flat and by-year tables |
| `frontend/src/pages/XbrlFacts.tsx` | The page |

Tests live in `backend/tests/test_xbrl_*.py`, `test_api_xbrl.py`, `test_cli_xbrl.py` and `frontend/tests/xbrlTags.test.ts`. Shared fixture: `backend/tests/fixtures/xbrl/companyfacts_small.json`.

---

### Task 1: Settings, models, store, fixture and the additive source surface

**Files:**
- Modify: `backend/arp/config.py` (add `xbrl_dir` beside `documents_dir`; add it to `ensure_dirs`)
- Modify: `backend/arp/ingestion/xbrl.py` and `backend/arp/ingestion/edgar.py` (additive only)
- Create: `backend/arp/xbrl_pipeline/__init__.py`, `models.py`, `store.py`
- Create: `backend/tests/fixtures/xbrl/companyfacts_small.json`
- Test: `backend/tests/test_xbrl_store.py`, `backend/tests/test_edgar_annual_original.py`

**Interfaces:**
- Produces, in `ingestion/xbrl.py`: constants `REVENUE_TAGS = _REVENUE_TAGS`, `CAPEX_TAGS = _CAPEX_TAGS`; method `XbrlFactSource.fetch_company_facts_raw(self, cik: str) -> tuple[dict | None, bytes | None]` returning `await self._company_facts(cik)`.
- Produces, in `ingestion/edgar.py`: `class AnnualOriginal(BaseModel)` with `accession: str, form: str, filing_date: str | None, source_url: str, primary_document: str, content: bytes`; method `EdgarDocumentSource.fetch_latest_annual_original(self, cik: str, *, client: httpx.AsyncClient | None = None) -> AnnualOriginal | None` (the first `10-K` in the submissions' recent filings; downloads the primary document with the SEC headers and `self._delay`; returns `None` when there is no 10-K or the submissions are unavailable; the `client` parameter exists so tests can inject `httpx.MockTransport`).
- Produces, in `models.py` (all `BaseModel`):
  - `FactRow`: `company_id: str, cik: str, taxonomy: str, concept: str, unit: str, value: float, period_start: str | None, period_end: str, fiscal_year: int | None, fiscal_period: str | None, form: str, filed: str | None, accession: str | None, source_sha: str`, plus property `tag_id`
  - `FactView(FactRow)`: adds `label: str | None`
  - `CatalogEntry`: `taxonomy: str, concept: str, label: str | None, fact_count: int, first_year: int | None, last_year: int | None, units: list[str]`
  - `RequiredRow`: `company_id: str, cik: str, metric: Literal["revenue", "capex"], fiscal_year: int | None, status: Literal["found", "not_found"], concept: str | None, value: float | None, unit: str | None, period_start: str | None, period_end: str | None, form: str | None, filed: str | None`
  - `ReportMeta`: `accession: str, form: str, filing_date: str | None, source_url: str, primary_document: str, filename: str, sha256: str, size: int, inline_xbrl: bool`
  - `CompanyStatus`: `company_id: str, cik: str | None, status: Literal["ok", "unchanged", "no_cik", "not_found"], source_sha: str | None, fact_count: int, report: Literal["stored", "unchanged", "none", "error"]`
  - `CompanyFiles`: `cik: str, company_id: str, name: str | None, fetched_at: str, fact_count: int, tags: list[str] | None, original_size: int, report: ReportMeta | None`
  - `TagEntry`: `taxonomy: str, concept: str, label: str | None, data_type: str | None, period_type: str | None, balance: str | None, documentation: str | None, deprecated: bool = False, extension: bool = False, seen_count: int = 0`, plus property `tag_id`
  - `PivotRow`: `tag_id: str, label: str | None, unit: str, values: dict[int, float | None]`; `PivotTable`: `years: list[int]` (newest first), `rows: list[PivotRow]`, `total: int`
  - `VerifyRow`: `company_id: str, metric: str, fiscal_year: int, outcome: Literal["match", "mismatch", "missing_in_run", "missing_in_xbrl"], run_value: float | None, xbrl_value: float | None, unit: str | None, detail: str`
- Produces, in `store.py`: `class XbrlStore(root: Path)` with
  - `company_dir(cik10: str) -> Path` (validates with `safe_id`), `ciks() -> list[str]`, `selections_dir`, `taxonomy_dir`
  - `save_original(cik10: str, raw: bytes) -> str` (writes `companyfacts-<sha16>.json`, idempotent, returns the sha256 hex)
  - `meta(cik10: str) -> dict | None`; `set_meta(cik10: str, *, source_sha: str, tags: list[str] | None, company_id: str, company_name: str | None, fact_count: int) -> None` (`meta.json`, also records `fetched_at`)
  - `original(cik10: str) -> dict | None` (the original whose sha is in `meta`)
  - `save_report(cik10: str, content: bytes, meta: ReportMeta) -> Path` (writes `annual-<accession>.htm` and `report.json`), `report_meta(cik10: str) -> ReportMeta | None`
  - `write_facts(cik10, rows: Iterable[FactRow]) -> int`, `read_facts(cik10) -> Iterator[FactRow]`, `write_catalog(cik10, entries)`, `read_catalog(cik10)`, `write_required(cik10, rows)`, `read_required(cik10)`
  - `file_path(cik10: str, kind: str) -> Path | None` for `kind` in `original`, `report`, `facts`, `required`, `catalog` (`None` when the file does not exist; `KeyError` for any other kind)

- [ ] **Step 1: Create the fixture `companyfacts_small.json`.** Real companyfacts shape (`cik`, `entityName`, `facts` by taxonomy, concept `label`, `units` by unit name, rows with `start`, `end`, `val`, `accn`, `fy`, `fp`, `form`, `filed`). Contents, exactly: `us-gaap:Revenues` (USD) with three rows: FY2023 annual 1000 (2022-10-01 to 2023-09-30, 10-K, filed 2023-11-01), FY2024 annual 1200 (2023-10-01 to 2024-09-28, 10-K, filed 2024-11-01), Q1 FY2024 300 (2023-10-01 to 2023-12-30, fp `Q1`, 10-Q); `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` (USD) with one FY2024 annual row 150; `dei:EntityCommonStockSharesOutstanding` (unit `shares`) with one instant row (`end` 2024-10-18, no `start`, 10-K, fp `FY`) 15000. Total 5 facts, 3 concepts.
- [ ] **Step 2: Write failing tests.** `test_xbrl_store.py`: `test_save_original_is_idempotent_and_returns_sha` (same bytes twice: one file, same 64-character sha); `test_meta_roundtrip_and_original_loads_latest`; `test_facts_catalog_required_roundtrip`; `test_save_report_and_report_meta_roundtrip`; `test_file_path_kinds` (existing kinds resolve, a missing file gives `None`, `"../x"` raises `KeyError`); `test_unsafe_cik_rejected` (`company_dir("../x")` raises `UnsafeIdentifierError`); `test_fetch_company_facts_raw_returns_data_and_bytes` (seed the cache file the way existing tests do; grep `xbrl_companyfacts_` in `backend/tests`). `test_edgar_annual_original.py` (mirror the stubbing in existing EDGAR tests; grep `_get_submissions` in `backend/tests`): returns the first `10-K` with its bytes and accession, returns `None` when the filings list has only `10-Q`, returns `None` when submissions are unavailable.
- [ ] **Step 3: Run `cd backend && pytest tests/test_xbrl_store.py tests/test_edgar_annual_original.py -v`.** Expected: FAIL (import errors).
- [ ] **Step 4: Implement** the settings field, both additive surfaces, `models.py` and `store.py`. JSONL via `arp.storage.jsonl_io`; atomic JSON writes via `arp.storage.atomic_io`.
- [ ] **Step 5: Run the tests again, then `pytest -k "xbrl or edgar" -q`.** Expected: PASS; the existing EDGAR and XBRL tests still pass.
- [ ] **Step 6: Commit** (`feat(xbrl): store, models, settings and additive SEC source surface`).

---

### Task 2: Extract all (flatten and catalogue)

**Files:** Create `backend/arp/xbrl_pipeline/flatten.py`; Test `backend/tests/test_xbrl_flatten.py`

**Interfaces:**
- Consumes: `FactRow`, `CatalogEntry`.
- Produces: `flatten_company_facts(facts: dict, *, company_id: str, cik: str, source_sha: str, concepts: frozenset[str] | None = None) -> Iterator[FactRow]` (one row per fact in file order; `concepts` filters on tag ids, `None` means all, an empty set means none) and `build_catalog(facts: dict) -> list[CatalogEntry]` (always complete).

- [ ] **Step 1: Write failing tests:** `test_flatten_all_yields_every_fact` (fixture gives 5 rows; the Q1 row has `fiscal_period == "Q1"`; the `dei` row has `period_start is None` and `unit == "shares"`); `test_flatten_filters_by_tag_id` (`{"us-gaap:Revenues"}` gives 3 rows); `test_flatten_empty_filter_matches_nothing`; `test_catalog_lists_every_concept` (3 entries; Revenues: `fact_count == 3`, `first_year == 2023`, `last_year == 2024`, `units == ["USD"]`, `label == "Revenues"`).
- [ ] **Step 2: Run `pytest tests/test_xbrl_flatten.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement** both functions. Catalogue years come from the row's `fy`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): flatten companyfacts into fact rows and a catalogue`).

---

### Task 3: Required items (revenue and capex)

**Files:** Create `backend/arp/xbrl_pipeline/required.py`; Test `backend/tests/test_xbrl_required.py`

**Interfaces:**
- Consumes: `REVENUE_TAGS`, `CAPEX_TAGS`, `XbrlFactSource.fact_for_tags(facts_json, tags, *, fiscal_year)` (static; reused, not rewritten, and `fiscal_year` there is the period-end year); `RequiredRow`.
- Produces: `resolve_required(facts: dict, *, company_id: str, cik: str) -> list[RequiredRow]`. Years = distinct period-end years of annual facts under either tag list. Per year and metric: a `found` row when `fact_for_tags` returns a fact (concept `us-gaap:<tag>`), else `not_found`. With no year at all: exactly one `not_found` row per metric with `fiscal_year=None`.

- [ ] **Step 1: Write failing tests:** `test_required_found_for_revenue_and_capex` (revenue 2023 is 1000 and 2024 is 1200, concept `us-gaap:Revenues`; capex 2024 is 150, concept `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`); `test_required_capex_2023_is_not_found_not_guessed` (status `not_found`, value `None`); `test_required_matches_existing_resolver` (revenue 2024 equals `XbrlFactSource.fact_for_tags(fixture, REVENUE_TAGS, fiscal_year=2024).value`); `test_foreign_filer_without_us_gaap_gives_not_found_rows` (only `ifrs-full` facts: two rows, both `not_found`, `fiscal_year is None`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `resolve_required`.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): resolve revenue and capex from stored facts`).

---

### Task 4: Fetch pipeline (facts and report, retry, runs)

**Files:** Create `backend/arp/xbrl_pipeline/fetch.py`; Test `backend/tests/test_xbrl_fetch.py`

**Interfaces:**
- Consumes: `XbrlStore`, `flatten_company_facts`, `build_catalog`, `resolve_required`, `ReportMeta`, `CompanyStatus`; `RunStore`, `JobManager` (`create_run("xbrl_fetch", params, n, companies=companies)`, `record_progress`, `finish_run`), `run_batch`, `hold_run` (same imports as `arp/discovery/pipeline.py`).
- Produces:
  - `FETCH_DELAY_SECONDS = 0.15`
  - `class SecSource(Protocol)`: `async resolve_cik(cik: str | None, ticker: str | None) -> str | None`, `async fetch_company_facts_raw(cik: str) -> tuple[dict | None, bytes | None]`, `async fetch_latest_annual_original(cik: str) -> AnnualOriginal | None`
  - `build_source(settings: Settings, *, refresh: bool = False) -> SecSource` (a small class holding an `EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir)` and an `XbrlFactSource(edgar, settings.cache_dir, ttl_hours=0 if refresh else settings.xbrl_facts_ttl_hours)`; no content or indexing stores)
  - `async def with_retry(call: Callable[[], Awaitable[T]], *, attempts: int = 3, base_delay: float = 1.0, sleep=asyncio.sleep) -> T` (retries `httpx.HTTPStatusError` with status 429 or 5xx and `httpx.TransportError`; re-raises after the last attempt; other errors propagate at once)
  - `async def fetch_company(company: CompanyRef, *, source: SecSource, store: XbrlStore, tags: frozenset[str] | None, sleep=asyncio.sleep) -> CompanyStatus`
  - `create_xbrl_run(companies: list[CompanyRef], tags: list[str] | None, refresh: bool, run_store: RunStore) -> str`
  - `async def execute_xbrl_run(run_id: str, companies: list[CompanyRef], *, settings: Settings, run_store: RunStore, tags: list[str] | None, refresh: bool, source: SecSource | None = None) -> str` (`run_batch` with `concurrency=1`; result rows carry `company_id`, the key `run_batch` resumes on, see `_KEY_FIELD` in `orchestration/batch_runner.py`)

Behaviour of `fetch_company`: resolve the CIK (none gives `no_cik`); `with_retry(fetch_company_facts_raw)`; `None` data gives `not_found`; when raw bytes are `None` (cache file from before step 7b) use `json.dumps(data, sort_keys=True).encode()`; `save_original`; `unchanged` only when the sha equals `meta.source_sha` and the requested tag set equals `meta.tags` (then no facts, catalogue or required are rewritten), otherwise write facts (filtered by `tags`), catalogue and required and `set_meta`. Then the report step, always run for a resolved company: `with_retry(fetch_latest_annual_original)`; an exception gives `report="error"`; `None` gives `"none"`; the same accession already stored gives `"unchanged"`; otherwise `save_report` with `inline_xbrl` true when the bytes contain `http://www.xbrl.org/2013/inlineXBRL`, giving `"stored"`. `await sleep(FETCH_DELAY_SECONDS)` after each network call. CIKs are zero-padded to 10 digits for the store. A report problem never changes the company's status.

- [ ] **Step 1: Write failing tests** with a fake source and an injected no-op `sleep`: `test_fetch_ok_writes_everything` (status `ok`, `fact_count == 5`, 5 fact rows, catalogue 3, required has revenue and capex rows, meta holds the sha, `report == "stored"`); `test_second_fetch_is_unchanged_including_report`; `test_tags_filter_writes_subset_but_keeps_original_and_required` (3 fact rows for `{"us-gaap:Revenues"}`, original on disk, required rows present, report still stored); `test_tags_matching_nothing_is_ok_with_empty_facts`; `test_changed_tag_set_is_not_unchanged`; `test_404_is_not_found`; `test_no_cik`; `test_same_cik_twice_stores_one_original_and_one_report` (Review Focus 2); `test_report_not_inline_is_stored_and_flagged` (`inline_xbrl` false); `test_no_10k_gives_report_none_and_company_ok`; `test_report_download_failure_leaves_company_ok` (Review Focus 5); `test_with_retry_succeeds_after_two_429`; `test_with_retry_gives_up_after_three_and_404_is_not_retried`; `test_run_isolates_a_failing_company_and_resume_retries_it` (three companies, the middle one's fake raises a non-retryable error: the run finishes, `errors.jsonl` has one row, the other two have result rows; re-running `execute_xbrl_run` on the same `run_id` with the fake fixed completes the third).
- [ ] **Step 2: Run `pytest tests/test_xbrl_fetch.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement** `fetch.py`. Follow `arp/discovery/pipeline.py` for run setup, `hold_run`, `record_progress`, `finish_run`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): resumable, paced fetch of companyfacts and the latest 10-K`).

---

### Task 5: Tag registry (taxonomy snapshots, search, seen counts)

**Files:** Create `backend/arp/xbrl_pipeline/registry.py`, `backend/tests/fixtures/xbrl/taxonomy_small.xsd`, `taxonomy_small_lab.xml`; Test `backend/tests/test_xbrl_registry.py`

**Interfaces:**
- Consumes: `XbrlStore`, `TagEntry`, `CatalogEntry`, `REVENUE_TAGS`, `CAPEX_TAGS`.
- Produces:
  - `TAXONOMY_SOURCES: dict[str, TaxonomySource]` for `us-gaap`, `ifrs-full`, `dei` (URLs per taxonomy-year; filled in Step 1)
  - `parse_taxonomy(xsd: bytes, labels: bytes, *, taxonomy: str) -> list[TagEntry]` (pure: element `name`, `type`, `periodType`, `balance`, standard label, documentation label, deprecation)
  - `class TaxonomyRegistry(store: XbrlStore)` with `write_snapshot(taxonomy: str, year: int, entries: list[TagEntry]) -> None` (`taxonomy/<taxonomy>-<year>.jsonl`) and `search(q: str = "", *, taxonomy: str | None = None, seen_only: bool = False, extension_only: bool = False, include_deprecated: bool = True, offset: int = 0, limit: int = 50) -> tuple[list[TagEntry], int]` (items and total before paging)
  - `async def update_taxonomies(store: XbrlStore, *, fetch: Callable[[str], Awaitable[bytes]], taxonomies: list[str] | None = None) -> dict[str, int]` (entries written per taxonomy)

Search rules: latest snapshot year per taxonomy; case-insensitive substring match on concept or label; `seen_count` is the number of CIK catalogues containing the tag id; concepts found in catalogues but in no snapshot are returned as `extension=True`; an empty `q` lists the tags of `REVENUE_TAGS` and `CAPEX_TAGS` first, then the rest sorted by concept.

- [ ] **Step 1: Confirm the official sources.** Using the environment's proxy, find and fetch the current official files for the FASB US-GAAP taxonomy (elements schema and labels), the IFRS Accounting Taxonomy (`ifrs-full`) and `dei`. Record the URLs and the year in `TAXONOMY_SOURCES`. If a source is unreachable, stop and report which one; do not guess a URL or invent data.
- [ ] **Step 2: Create the two small fixtures** (4 elements: `Revenues` and `PaymentsToAcquirePropertyPlantAndEquipment` as monetary duration items, one instant `Assets` with `balance="debit"`, one deprecated element), mirroring the real file shapes seen in Step 1.
- [ ] **Step 3: Write failing tests:** `test_parse_taxonomy_fields` (label, `period_type`, `balance`, `data_type`, deprecated flag, taxonomy set); `test_search_empty_query_pins_revenue_and_capex_first`; `test_search_filters_by_text_taxonomy_and_deprecated`; `test_seen_count_follows_catalogues` (catalogue A holds `us-gaap:Revenues` and `us-gaap:Assets`, catalogue B holds only `us-gaap:Assets`: `Revenues.seen_count == 1`, `Assets.seen_count == 2`); `test_seen_only_hides_unused_tags`; `test_extension_tag_from_catalogue_is_marked` (`xyz:CustomRevenue`); `test_never_used_tag_has_zero_seen_count`; `test_paging_returns_total_and_slice`; `test_update_taxonomies_writes_snapshots_with_stub_fetch`.
- [ ] **Step 4: Run.** Expected: FAIL.
- [ ] **Step 5: Implement** with `xml.etree.ElementTree` on bytes. The files are third-party input: no DTD or entity resolution, no network access while parsing. Add `# ponytail: seen counts scan every catalogue per search, memoise on directory mtime if slow`.
- [ ] **Step 6: Run.** Expected: PASS.
- [ ] **Step 7: Run `update_taxonomies` for real once** and check the snapshot sizes are plausible (tens of thousands for `us-gaap`); report the numbers. Do not commit generated snapshots (`data/` is runtime state; confirm `.gitignore`).
- [ ] **Step 8: Commit** (`feat(xbrl): tag registry over the official taxonomies`).

---

### Task 6: Named selections

**Files:** Create `backend/arp/xbrl_pipeline/selection.py`; Test `backend/tests/test_xbrl_selection.py`

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

**Files:** Create `backend/arp/xbrl_pipeline/verify.py`; Test `backend/tests/test_xbrl_verify.py`

**Interfaces:**
- Consumes: `RunStore` (`run_dir`, `results_path`, `read_jsonl`), `ExtractionRecord` rows from `runs/<id>/results.jsonl` (`company_id`, `fields[]` with `field_id`, `canonical_value`, `canonical_unit`, `period_end`), `XbrlStore.read_required`, `VerifyRow`.
- Produces: `class CircularRunError(ValueError)` and `verify_run(run_id: str, *, run_store: RunStore, store: XbrlStore, mapping: dict[str, str], tolerance: float = 0.005) -> list[VerifyRow]`. `mapping` maps `"revenue"` and `"capex"` to the extraction `field_id`. Writes `runs/<run_id>/xbrl_verify.jsonl` and returns the rows.

Rules: raise `CircularRunError` when `step_settings.json` is missing or has `xbrl_facts_enabled` true. XBRL values come from all `required.jsonl` files keyed by `(company_id, metric, fiscal_year)` (`# ponytail: linear scan, index by company above ~10k companies`). Per run company, per metric, per year (the period-end years of any field in that company's record): both values present gives `match` when `abs(run - xbrl) <= tolerance * abs(xbrl)` else `mismatch`; units differing gives `mismatch` with detail `"unit"`; XBRL `found` but no run value gives `missing_in_run`; run value present but XBRL missing or `not_found` gives `missing_in_xbrl`; both missing gives no row.

- [ ] **Step 1: Write failing tests** (build a run in a tmp `RunStore`): `test_match_within_tolerance` and `test_mismatch_outside_tolerance` (1.004x inside, 1.006x outside); `test_missing_in_run`; `test_missing_in_xbrl`; `test_unit_difference_is_mismatch`; `test_refuses_when_xbrl_was_on`; `test_refuses_when_step_settings_missing` (Review Focus 4); `test_writes_verify_jsonl`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): verify an extraction run against stored XBRL facts`).

---

### Task 8: Company views (files, facts table, by-year table, downloads)

**Files:** Create `backend/arp/xbrl_pipeline/views.py`; Test `backend/tests/test_xbrl_views.py`

**Interfaces:**
- Consumes: `XbrlStore`, `FactView`, `CompanyFiles`, `PivotTable`, `PivotRow`.
- Produces:
  - `is_annual(row: FactRow) -> bool` (form in `10-K`, `10-K/A`; `fiscal_period == "FY"`; and either no `period_start` or a duration of 350 to 380 days)
  - `list_company_files(store: XbrlStore, *, offset: int = 0, limit: int = 50) -> tuple[list[CompanyFiles], int]` (sorted by `fetched_at` descending)
  - `query_facts(store: XbrlStore, cik10: str, *, q: str = "", taxonomy: str | None = None, form: str | None = None, period_year: int | None = None, annual_only: bool = False, sort: str = "period_end", order: Literal["asc", "desc"] = "desc", offset: int = 0, limit: int = 100) -> tuple[list[FactView], int]` (`q` matches label or tag id case-insensitively; `sort` is one of `period_end`, `filed`, `value`, `concept`, `form`; any other key raises `ValueError`; labels come from the catalogue)
  - `pivot_facts(store: XbrlStore, cik10: str, *, q: str = "", taxonomy: str | None = None, offset: int = 0, limit: int = 100) -> PivotTable` (annual facts only; columns are the period-end years, newest first; one row per `(tag_id, unit)`; when a period was reported more than once the latest `filed` wins; `total` is the row count before paging)
  - `download_path(store: XbrlStore, cik10: str, kind: str) -> Path` (raises `KeyError` for an unknown kind, `FileNotFoundError` when the file is missing)

- [ ] **Step 1: Write failing tests** on a store built from the fixture (flatten and write directly): `test_list_company_files_has_sizes_and_report` ; `test_query_facts_filters_by_text_and_returns_label` (`q="revenues"` gives 3 rows with `label == "Revenues"`); `test_query_facts_annual_only` (4 rows: both Revenues years, capex, and the `dei` instant; the Q1 row is excluded); `test_query_facts_sort_and_paging` (`sort="value"`, `order="asc"`, `limit=2` returns the two smallest values and `total == 5`); `test_query_facts_rejects_unknown_sort`; `test_pivot_years_and_values` (years `[2024, 2023]`; Revenues `{2024: 1200.0, 2023: 1000.0}`; capex `{2024: 150.0, 2023: None}`; the `dei` row `{2024: 15000.0, 2023: None}`); `test_pivot_latest_filed_wins` (add a restated duplicate of Revenues 2024 filed later: its value is shown); `test_download_path_kinds_and_errors` (Review Focus 3).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Add `# ponytail: loads the company's facts.jsonl per request, cache by mtime if large filers feel slow`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** (`feat(xbrl): file listing, facts table and by-year pivot views`).

---

### Task 9: CLI

**Files:** Create `backend/arp/cli/xbrl.py`; Modify `backend/arp/cli/__init__.py` (import `xbrl_app`, `app.add_typer(xbrl_app, name="xbrl")`); Test `backend/tests/test_cli_xbrl.py`

**Interfaces:**
- Consumes: Tasks 4 to 8. Pattern: `arp/cli/discovery.py` (`_run_store`, `_and_drain`, `load_company_universe`, `asyncio.run`).
- Produces: `xbrl_app` with `fetch --universe PATH [--tags A,B,C] [--refresh]`, `taxonomy update`, `tags [--search TEXT] [--taxonomy T] [--seen-only] [--limit N]`, `select --name N --tags A,B,C`, `files [--limit N]`, `verify RUN_ID [--map revenue=FIELD] [--map capex=FIELD] [--tolerance X]` (exits 1 and prints the guard message on `CircularRunError`).

- [ ] **Step 1: Write failing tests** with Typer's `CliRunner` and `Settings` pointed at tmp dirs: `test_tags_lists_registry_with_seen_counts`; `test_select_writes_selection_and_prints_count`; `test_files_lists_companies_with_report_info`; `test_verify_prints_summary_and_exits_nonzero_on_circular_run`; `test_fetch_runs_with_patched_source` (patch `build_source` so no network is used; assert `results.jsonl` holds the company status).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the commands as thin calls into the package.
- [ ] **Step 4: Run, then `arp xbrl --help`.** Expected: PASS and six commands listed.
- [ ] **Step 5: Commit** (`feat(xbrl): arp xbrl CLI group`).

---

### Task 10: API router

**Files:** Create `backend/arp/api/routers/xbrl.py`; Modify `backend/arp/api/main.py` (import the router; `app.include_router(xbrl.router, dependencies=[Depends(authorize)])` beside the others); Test `backend/tests/test_api_xbrl.py`

**Interfaces:**
- Consumes: Tasks 4 to 8. Patterns: `arp/api/routers/discovery.py` (`_run_store` dependency, `asyncio.create_task` for the background run), `routers/documents.py` (`FileResponse`, `safe_id` to HTTP 400), `tests/test_api_bi.py` (a `FastAPI()` app with the router, `dependency_overrides` for `deps.settings_dep` and `current_user`, `TestClient`).
- Produces, prefix `/api/xbrl`:
  - `POST /runs` body `{companies?: list[CompanyRef], universe_path?: str, tags?: list[str], refresh?: bool}` returns `{run_id, company_count}` (400 when neither companies nor universe)
  - `GET /runs/{run_id}`, `GET /runs/{run_id}/results?offset&limit`, `POST /runs/{run_id}/retry` (resumes the same run)
  - `GET /tags?q&taxonomy&seen_only&extension_only&offset&limit` returns `{items, total}`; `POST /taxonomy/update`
  - `PUT /selections/{name}` body `{tags: list[str]}`, `GET /selections`, `GET /selections/{name}/facts?offset&limit`
  - `GET /companies?offset&limit` returns `{items: CompanyFiles[], total}`
  - `GET /companies/{cik}/files/{kind}` (download; attachment, nosniff and sandbox headers; unknown kind 404; missing file 404; unsafe CIK 400)
  - `GET /companies/{cik}/facts?q&taxonomy&form&period_year&annual_only&sort&order&offset&limit` returns `{items, total}` (unknown `sort` 400)
  - `GET /companies/{cik}/pivot?q&taxonomy&offset&limit` returns a `PivotTable`
  - `GET /required?run_id` (rows for that run's companies)
  - `POST /verify` body `{run_id, mapping, tolerance?}` (409 with the guard message on `CircularRunError`)

- [ ] **Step 1: Write failing tests:** `test_start_run_requires_companies_or_universe` (400); `test_start_run_returns_run_id` (patch `execute_xbrl_run` with a stub); `test_run_results_paged`; `test_tags_search_and_paging`; `test_selection_roundtrip`; `test_unsafe_selection_name_is_400`; `test_companies_listing`; `test_download_has_attachment_nosniff_and_sandbox_headers`; `test_download_unknown_kind_is_404_and_unsafe_cik_is_400`; `test_facts_filter_sort_paging_and_bad_sort_is_400`; `test_pivot_shape`; `test_required_for_run`; `test_verify_circular_is_409`; `test_verify_returns_rows`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the router.
- [ ] **Step 4: Run `pytest tests/test_api_xbrl.py -v`, then `pytest -q -k "xbrl or api"`.** Expected: PASS; nothing else broke.
- [ ] **Step 5: Commit** (`feat(xbrl): /api/xbrl router`).

---

### Task 11: Frontend logic, API client and types

**Files:** Create `frontend/src/lib/xbrlTags.ts`; Modify `frontend/src/api/client.ts` (a `// XBRL` block after the Discovery block), `frontend/src/types.ts`; Test `frontend/tests/xbrlTags.test.ts`

**Interfaces:**
- Produces, in `xbrlTags.ts` (pure, no DOM):
  - `toggleTag(selected: string[], tagId: string): string[]` (adds if absent, removes if present, keeps order, no duplicates)
  - `tagQuery(p: { q?: string; taxonomy?: string; seenOnly?: boolean; extensionOnly?: boolean; offset?: number; limit?: number }): string` (only set keys, URL-encoded; empty string when none)
  - `statusText(status: string): string` and `reportText(report: string): string` (plain-language labels for `ok`, `unchanged`, `no_cik`, `not_found`, `error` and `stored`, `unchanged`, `none`, `error`)
  - `verifySummary(rows: { outcome: string }[]): Record<string, number>` (all four outcomes always present)
  - `formatFactValue(value: number, unit: string): string` (thousands separators; integers without decimals; other numbers up to 4 decimals with trailing zeros trimmed; the unit is returned separately by the caller, never dropped)
  - `periodLabel(start: string | null, end: string): string` (`"2023-10-01 to 2024-09-28"`, or `"as of 2024-10-18"` when there is no start)
  - `secFilingUrl(cik: string, accession: string): string` (`https://www.sec.gov/Archives/edgar/data/<cik without leading zeros>/<accession without dashes>/`)
  - `nextSort(current: { key: string; order: "asc" | "desc" }, key: string): { key: string; order: "asc" | "desc" }` (same key toggles the order; a new key starts `asc`) and `ariaSort(current: { key: string; order: "asc" | "desc" }, key: string): "ascending" | "descending" | "none"`
- Produces, in `client.ts`: `startXbrlRun`, `getXbrlRun`, `getXbrlResults`, `retryXbrlRun`, `searchXbrlTags`, `updateXbrlTaxonomy`, `saveXbrlSelection`, `listXbrlSelections`, `getXbrlSelectionFacts`, `listXbrlCompanies`, `xbrlDownloadUrl(cik, kind)`, `getXbrlFacts`, `getXbrlPivot`, `getXbrlRequired`, `verifyXbrl`, each a thin `request(...)` call to the Task 10 endpoints. Types in `types.ts`: `XbrlTag`, `XbrlCompanyStatus`, `XbrlCompanyFiles`, `XbrlFact`, `XbrlPivot`, `XbrlRequiredRow`, `XbrlVerifyRow`.

- [ ] **Step 1: Write failing tests** in the style of `tests/cardKeys.test.ts` (`node:test`, `assert/strict`): `toggleTag` adds, removes and never duplicates; `tagQuery({q: "rev enue", seenOnly: true})` encodes the space and includes `seen_only=true`; `tagQuery({})` is `""`; `statusText("no_cik")` and `statusText("not_found")` are non-empty and different; `reportText("none")` is non-empty; `verifySummary([])` gives four zero counts; `formatFactValue(1200000, "USD") === "1,200,000"`, `formatFactValue(0.12345678, "pure") === "0.1235"`, `formatFactValue(-1500, "USD") === "-1,500"`; `periodLabel(null, "2024-10-18") === "as of 2024-10-18"`; `secFilingUrl("0000320193", "0000320193-24-000123") === "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/"`; `nextSort` toggles on the same key and starts `asc` on a new key; `ariaSort` returns `none` for another key.
- [ ] **Step 2: Run `cd frontend && npm test`.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the module, the client block and the types.
- [ ] **Step 4: Run `npm test && npm run lint && npx tsc -b`.** Expected: PASS, no type errors.
- [ ] **Step 5: Commit** (`feat(xbrl): frontend logic, client and types`).

---

### Task 12: Page shell, tag dropdown, Fetch and Tags areas

**Files:** Create `frontend/src/components/TagCombobox.tsx`, `frontend/src/pages/XbrlFacts.tsx`; Modify `frontend/src/App.tsx` (lazy import, a `TABS` entry `{ id: "xbrl", label: "XBRL Facts" }`, the render line beside the other pages, and the sidebar grouping list that must contain every tab id; read the grouping block before editing)

**Interfaces:**
- Consumes: Task 11 module and client; `UniversePicker` (as used in `pages/DocumentDiscovery.tsx`) for choosing companies.
- Produces: `TagCombobox({ selected, onChange }: { selected: string[]; onChange: (next: string[]) => void })`, a multi-select combobox that loads options from `api.searchXbrlTags` as the user types (debounced), shows label, tag id, taxonomy and seen count per option, offers filters for taxonomy, extension and seen-only, shows chosen tags as removable chips, and announces the result count through the existing `lib/announce.ts`. `XbrlFacts` page with the Fetch and Tags areas; later tasks add areas below them.

Fetch area: choose companies, All or Selected tags (using the chosen tags), optional refresh, start; a status table with `statusText` and `reportText` per company, polling the run until finished, and a retry-failed action. Tags area: the combobox, save as a named selection.

- [ ] **Step 1: Load the design skills** (`impeccable:impeccable`, `ui-ux-pro-max:ui-ux-pro-max`) and read `DESIGN.md`, `PRODUCT.md` and `pages/DocumentDiscovery.tsx` for structure and tokens. Reuse existing components and CSS classes before adding new ones.
- [ ] **Step 2: Implement `TagCombobox`** following the ARIA combobox pattern: input `role="combobox"` with `aria-expanded`, `aria-controls`, `aria-activedescendant`; a `role="listbox"` of `role="option"` items; ArrowUp/Down moves, Enter toggles, Escape closes, Backspace on an empty input removes the last chip; every control keyboard-reachable with a visible focus ring; options and chips at touch size.
- [ ] **Step 3: Implement the page shell with the Fetch and Tags areas** and register it in `App.tsx`.
- [ ] **Step 4: Run `npm run lint && npm test && npm run build`.** Expected: all pass.
- [ ] **Step 5: See it work.** Use the `run` skill to start the backend and frontend. Check: the dropdown opens and a search for "revenue" lists matches with seen counts; keyboard selection adds a chip and Backspace removes it; a fetch on a one-company universe shows its text status. If the SEC is unreachable from the environment, say so and verify the Fetch area against stubbed API responses instead.
- [ ] **Step 6: Commit** (`feat(xbrl): XBRL Facts page with Fetch, Tags and the tag dropdown`).

---

### Task 13: Files and Facts areas (the tables)

**Files:** Create `frontend/src/components/XbrlFactsTable.tsx`; Modify `frontend/src/pages/XbrlFacts.tsx`

**Interfaces:**
- Consumes: `api.listXbrlCompanies`, `xbrlDownloadUrl`, `getXbrlFacts`, `getXbrlPivot`; helpers `formatFactValue`, `periodLabel`, `secFilingUrl`, `nextSort`, `ariaSort`.
- Produces: `XbrlFactsTable({ cik }: { cik: string })` with a view toggle (Flat, By year) and the filters from the spec; Files area in the page.

Files area: a table of fetched companies (CIK, name, fetch date, fact count, report form, filing date, "inline XBRL" or "not inline XBRL" in text), download buttons for the `companyfacts` original, the 10-K, facts, required and catalogue (each disabled with a text reason when the file does not exist), and an "Open filing on SEC.gov" link built with `secFilingUrl`. Facts area: choose a company from the fetched list, a caption stating the extracted fact count and whether a tag selection limited it. Flat table: label with tag id beneath, period, fiscal year and period, value right-aligned with tabular figures and the unit beside it, form, filed, accession; sortable headers with `aria-sort`; filters (text, taxonomy, form, period year, annual-only); server-side paging with a visible range and total. By-year table: one row per tag and unit, one column per period-end year (newest first), empty cells shown as a dash with a visually hidden "no value", first column sticky, header row sticky; horizontal scroll stays inside the table container (focusable, labelled), never the page.

- [ ] **Step 1: Implement the Files area and `XbrlFactsTable`** using the design skills' guidance; a proper `<table>` with `<caption>`, `<th scope>`; loading, empty and error states stated in text.
- [ ] **Step 2: Run `npm run lint && npm test && npm run build`.** Expected: all pass.
- [ ] **Step 3: See it work.** Run the app with at least one fetched company (a real fetch, or the Task 1 fixture written into `data/xbrl/` with a small report file). Check and screenshot at desktop and phone width: sorting by clicking and by keyboard, filters, paging, the by-year table with the fixed first column, downloads start (the 10-K downloads and does not render), no horizontal page scroll, values right-aligned with units visible.
- [ ] **Step 4: Commit** (`feat(xbrl): files and facts tables`).

---

### Task 14: Required and Verify areas

**Files:** Modify `frontend/src/pages/XbrlFacts.tsx`

**Interfaces:**
- Consumes: `api.getXbrlRequired`, `api.verifyXbrl`, `verifySummary`, `formatFactValue`.
- Produces: Required area (revenue and capex per company and year, the winning concept shown, `not_found` marked in text) and Verify area (choose an extraction run, map revenue and capex to its field ids, run, show the four outcome counts and the mismatch list; the circular-run message shown as text).

- [ ] **Step 1: Implement both areas.**
- [ ] **Step 2: Run `npm run lint && npm test && npm run build`.** Expected: all pass.
- [ ] **Step 3: See it work.** Required shows rows for a fetched company; Verify on a run that had XBRL on shows the guard message in text. Screenshot at desktop and phone width.
- [ ] **Step 4: Commit** (`feat(xbrl): required and verify areas`).

---

### Task 15: Documentation and final checks

**Files:** Modify `README.md` (add function 18 to the table, after 17: separate from Data-Point Extraction, CLI/API/page, files only), `docs/TECHNICAL_REFERENCE.md` (a section for the XBRL function: layout under `data/xbrl/`, statuses, report download, selection modes, tag registry, tables, verify guard, the two additive changes to `ingestion/`)

- [ ] **Step 1: Make the two edits.**
- [ ] **Step 2: Run all checks:** `cd backend && pytest -q tests/test_xbrl_*.py tests/test_edgar_annual_original.py tests/test_api_xbrl.py tests/test_cli_xbrl.py`, then `pytest -q -k "xbrl or extraction or edgar"` to show the existing pipelines are unaffected; `cd ../frontend && npm test && npm run lint && npm run build`; then the repo's Python linter as configured in `backend/pyproject.toml`. Expected: all pass. Report anything skipped.
- [ ] **Step 3: Commit** (`docs(xbrl): document the XBRL function`), then push `ccr-f2048353-4v08hm`. Do not open a pull request unless asked.
