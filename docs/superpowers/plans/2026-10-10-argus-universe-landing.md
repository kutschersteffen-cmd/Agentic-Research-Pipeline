# Argus universe landing page, shared mapping and XBRL Auto routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Argus "Universe" landing page (upload, security-master mapping, what is already stored per company, hand-over to Extraction or XBRL) and an Auto market for the XBRL pipeline, keeping the manual US/EU switch.

**Architecture:** A read-only backend package `arp/universe_workbench/` (mapping, routing, availability) behind `POST /api/universe/workbench`. The XBRL run gets `market="auto"`: routing is computed once at run creation, stored as `routing.json` in the run directory, and used per company. The Extraction page is not rewritten; both pipelines receive the chosen companies as a saved universe through the existing hand-over.

**Tech Stack:** Python 3.12, pydantic, FastAPI, typer, pytest; React + TypeScript (Vite), vitest.

**Spec:** `docs/superpowers/specs/2026-10-10-argus-universe-landing-design.md` (builds on the two 2026-10-09 XBRL specs).

## Global Constraints

- Branch off `main`; PR base is `main` (CLAUDE.md). Never merge locally.
- Read-only services: the workbench creates and changes nothing. The landing page never starts a run itself.
- Extraction and XBRL stay independent: `arp/xbrl_pipeline` may import `arp/universe_workbench`; `arp/universe_workbench` imports neither pipeline's run code.
- Exact identifiers only (LEI, ISIN, CIK). No name or ticker matching against the security master. Enrichment fills only empty `lei`, `cik`, `isin`, never overwrites, never fills `country`.
- Routing precedence: country (only when in the US / EU27 / EEA / UK table), then ISIN prefix, then CIK (`lei` decides only without a `cik`), then security master, then ticker fallback to SEC, else `unrouted`.
- `universe_path` on `POST /api/universe/workbench` must resolve inside `runs_dir/_universes`, else 400.
- No test calls the network. `market` defaults to `"sec"` on old stored models; the CLI and API default to `"auto"`.
- Commit trailers on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01X1rMyyKSucPp6a66NAAp7f`.
- Checks before each commit: `cd backend && ruff check arp tests && python -m pytest -p no:cacheprovider <task's tests> -q`; frontend: `cd frontend && npm run lint && npm test && npm run build`.

## Review Focus

1. An empty or missing identifier-map file: every company is `unmapped` or `no_identifier`, routing still works from rules 1 to 3 and 5, nothing raises. (Task 1)
2. CIK with leading zeros, LEI in lower case or with spaces, ISIN in lower case: matched and routed as their normalised forms. (Tasks 1, 2)
3. Expired master rows (`valid_to` in the past) and an identifier pointing at two issuers: ignored for mapping / `ambiguous`, never enriched. (Task 1)
4. A 5,000-company universe reads the identifier-map file once, not once per company. (Task 1)
5. `universe_path` with `..`, an absolute path elsewhere, or a symlink out of `_universes`: 400, nothing read. (Task 4)
6. A resumed or retried `auto` XBRL run keeps its original routing even if the master changed since. (Task 5)
7. Duplicate `company_id` rows in one universe: one availability entry, both rows returned. (Tasks 3, 4)

---

### Task 1: Security-master mapping

**Files:**
- Create: `backend/arp/universe_workbench/__init__.py` (empty), `backend/arp/universe_workbench/mapping.py`
- Test: `backend/tests/test_workbench_mapping.py`

**Interfaces:**
- Consumes: `IdentifierMapStore.rows()` and `normalise_identifier(scheme, value)` (`arp/storage/identifier_map.py`); `IdentifierMap` (`arp/schemas/issuer.py`); `schemas.issuer.issuer_key`, `normalise_lei`.
- Produces:
  - `@dataclass(frozen=True) class Mapping: status: Literal["mapped","ambiguous","unmapped","no_identifier"]; issuer_key: str | None; key_scheme: str | None; identifiers: dict[str, list[str]]; candidates: list[str]`. `identifiers` holds the master's LEI, CIK, ISIN values for the mapped issuer; `key_scheme` is `"INTERNAL"` when mapped.
  - `class MasterIndex` with `@classmethod build(cls, idmap: IdentifierMapStore, *, on: str | None = None) -> MasterIndex` (reads the file once, honours `valid_from`/`valid_to`, `on` defaults to today), `resolve(self, scheme: str, value: str) -> list[str]`, `identifiers(self, issuer_key: str) -> dict[str, list[str]]`.
  - `map_company(company: CompanyRef, index: MasterIndex | None) -> Mapping`; `enrich(company: CompanyRef, mapping: Mapping) -> CompanyRef`.

Semantics of `map_company`: try LEI, then ISIN, then CIK (as `issuer_key` does); a scheme with exactly one issuer gives `mapped`; none mapped but some scheme with two or more issuers gives `ambiguous` (`candidates` lists them); none matching but the company has any of the three identifiers gives `unmapped`; no identifier at all gives `no_identifier`. `index=None` behaves like an empty index. `enrich` fills an empty `lei`, `cik`, `isin` only when `mapping.status == "mapped"` and the issuer has exactly one value for that scheme.

- [ ] **Step 1: Write failing tests** in `test_workbench_mapping.py` using a `tmp_path` identifier map built with `IdentifierMapStore.add`: `test_mapped_by_lei_isin_cik` (one issuer, each of the three finds it; `key_scheme == "INTERNAL"`); `test_cik_leading_zeros_and_lower_case_lei` (`cik="0000320193"` vs master `320193`; `lei=" 5299 00abc..."` normalised); `test_ambiguous_when_identifier_points_at_two_issuers`; `test_unmapped_and_no_identifier`; `test_expired_rows_are_ignored` (`valid_to` in the past gives unmapped); `test_missing_map_file_is_empty` (`IdentifierMapStore(tmp_path/"none.jsonl")` and `index=None` both give `unmapped`/`no_identifier`, no raise); `test_parity_with_issuer_key` (for five fixture companies, `issuer_key(company, idmap)` is `(k, "INTERNAL")` exactly when `map_company(...).status == "mapped"` and `issuer_key == k`); `test_enrich_fills_only_empty_fields` (an existing `lei` is kept; a missing `isin` filled; `country` untouched; an issuer with two ISINs does not fill `isin`); `test_index_reads_the_file_once` (monkeypatch `IdentifierMapStore.rows` with a counter; 5,000 `map_company` calls after one `build` give one `rows()` call).
- [ ] **Step 2: Run** `python -m pytest tests/test_workbench_mapping.py -q`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** `mapping.py` as specified.
- [ ] **Step 4: Run** the tests and `ruff check arp tests`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(workbench): security-master mapping with a one-pass index`.

### Task 2: Market routing

**Files:**
- Create: `backend/arp/universe_workbench/routing.py`
- Test: `backend/tests/test_workbench_routing.py`

**Interfaces:**
- Consumes: Task 1 `MasterIndex`, `map_company`, `enrich`.
- Produces:
  - `Market = Literal["sec","esef"]`; `@dataclass(frozen=True) class Route: market: Market | None; status: Literal["routed","no_source","unrouted"]; basis: str | None; detail: str; company: CompanyRef` (`company` is the enriched row; equal to the input when nothing was filled). `basis` is one of `country`, `isin_prefix`, `cik`, `lei`, `master`, `ticker_fallback`, or `None` when unrouted.
  - `country_market(value: str | None) -> Market | None`, `route_company(company: CompanyRef, index: MasterIndex | None = None) -> Route`, `route_universe(companies: list[CompanyRef], index: MasterIndex | None = None) -> list[Route]`.
- Pinned strings: unrouted detail `"no country or identifier: add an ISIN, LEI or CIK, or load it into the security master"`; no-source detail `f"no XBRL source for {prefix} yet"`; an unrecognised `country` that does not decide appends `f"; country '{value}' not recognised"` to `detail`.
- Country table: US; EU27 (AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE); EEA (IS LI NO); UK (GB); each by ISO alpha-2, alpha-3 and English name, case-insensitive, including "UK", "Great Britain", "United Kingdom", "USA", "United States of America". ISIN prefixes `XS` and `EU` carry no country and are ignored; any other two-letter prefix outside the table gives `no_source`.

- [ ] **Step 1: Write failing tests** (table-driven, `pytest.mark.parametrize`): `test_country_decides` (`"Germany"`, `"DE"`, `"DEU"`, `"de"` give esef/`country`; `"United States"`, `"us"` give sec; `"United Kingdom"`, `"GB"` give esef); `test_home_country_beats_cik` (country `DE` + cik gives esef); `test_isin_prefix` (`US0378331005` sec, `DE000BASF111` esef, `JP3633400001` gives `no_source` with the pinned detail, `XS1234567890` ignored); `test_country_beats_isin_prefix`; `test_cik_beats_lei_without_country` (cik + lei, no country, gives sec/`cik`); `test_lei_alone_gives_esef`; `test_lowercase_and_spaced_identifiers`; `test_unrecognised_country_is_ignored_and_noted` (country `"Atlantis"` + cik gives sec and `detail` contains `country 'Atlantis' not recognised`); `test_master_enrichment_then_reroute` (row with only an ISIN unknown to the prefix table, master maps it to an issuer with a CIK, gives sec/`master` and `company.cik` filled); `test_ticker_fallback` (only ticker gives sec/`ticker_fallback`); `test_unrouted` (name only gives `unrouted` with the pinned detail, `market is None`); `test_route_universe_keeps_order_and_duplicates`.
- [ ] **Step 2: Run** `python -m pytest tests/test_workbench_routing.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `routing.py` following the precedence in Global Constraints; rule 4 calls `map_company` then `enrich`, then re-runs rules 1 to 3 once.
- [ ] **Step 4: Run** the tests and ruff. Expected: PASS.
- [ ] **Step 5: Commit** `feat(workbench): country, ISIN and identifier market routing`.

### Task 3: Availability

**Files:**
- Create: `backend/arp/universe_workbench/availability.py`
- Modify: `backend/arp/storage/document_store.py` (add `files_on_disk(documents_dir: Path, company_id: str) -> int`, the body of `routers/documents._files_on_disk`), `backend/arp/api/routers/documents.py` (import and use it; behaviour unchanged)
- Test: `backend/tests/test_workbench_availability.py`

**Interfaces:**
- Consumes: `RunStore.list_runs(run_type)`, `results_path`, `read_jsonl`; `DocumentContentStore.readiness_by_company(ids)`; `XbrlStore.ciks()`, `meta`, `company_ids`, `report_meta`.
- Produces: pydantic models `IdentityAvail(run_id: str, verdict: str, resolved_cik: str | None, resolved_website: str | None)`, `DocumentsAvail(registered: int, parsed: int, on_disk: int, doc_types: list[str], last_seen_at: str | None)`, `ExtractionAvail(runs: int, run_types: list[str], last_run_id: str | None, last_run_at: str | None)`, `XbrlAvail(key: str, market: str, fact_count: int, fetched_at: str, report: bool)`, `Availability(identity: IdentityAvail | None, documents: DocumentsAvail, extraction: ExtractionAvail, xbrl: XbrlAvail | None)`; and `availability(companies: list[CompanyRef], *, run_store: RunStore, content_store: DocumentContentStore, xbrl_store: XbrlStore, documents_dir: Path) -> dict[str, Availability]` (keyed by `company_id`, one entry per distinct id).

Indexing: one pass over `identity` runs (newest first, first hit per company wins); one pass over runs of types `extraction`, `financials`, `tnfd`, `transition_plan` reading each `results.jsonl` once (companies keyed by each row's `company_id`; `last_run_*` from the newest run, `runs` counts distinct runs); one pass over `xbrl_store.ciks()` mapping every id in `company_ids(key)`. Mark the scans with `# ponytail:` naming the upgrade (an index) if the stores grow.

- [ ] **Step 1: Write failing tests** with a `tmp_path` `RunStore` (create runs via `JobManager(run_store).create_run(...)` and write `results.jsonl` rows), a real `DocumentContentStore` over a temp registry (follow `tests/test_document_store*.py` fixtures), and an `XbrlStore` seeded with `set_meta`: `test_company_with_nothing_stored` (all empty, `identity is None`, `xbrl is None`); `test_documents_registered_and_on_disk`; `test_extraction_runs_counted_and_latest_reported` (two runs, newest wins for `last_run_id`); `test_identity_latest_run_wins`; `test_xbrl_found_by_any_company_id` (`company_ids` has two ids, both found; `market` read from meta, default `"sec"`); `test_duplicate_company_ids_give_one_entry`; `test_each_results_file_read_once` (patch `RunStore.read_jsonl` with a counter: 3 runs, 100 companies give 3 reads).
- [ ] **Step 2: Run** `python -m pytest tests/test_workbench_availability.py tests/test_api_documents*.py -q`. Expected: new tests FAIL, document tests PASS.
- [ ] **Step 3: Implement** the models, the three indexes and the `files_on_disk` move.
- [ ] **Step 4: Run** the tests and ruff. Expected: PASS.
- [ ] **Step 5: Commit** `feat(workbench): per-company availability from stored runs, documents and XBRL files`.

### Task 4: Workbench API

**Files:**
- Create: `backend/arp/api/routers/universe_workbench.py`
- Modify: `backend/arp/api/main.py` (include the router with `dependencies=[Depends(authorize)]`, next to `universe.router`)
- Test: `backend/tests/test_api_universe_workbench.py`

**Interfaces:**
- Consumes: Tasks 1 to 3; `settings_dep`, `get_document_content_store` (`arp/api/deps.py`); `load_company_universe`.
- Produces: `POST /api/universe/workbench`, body `WorkbenchRequest{companies: list[CompanyRef] | None, universe_path: str | None}`; response `{rows: [{company, mapping, route, availability}], counts: {routes: {sec, esef, no_source, unrouted}, mapping: {mapped, ambiguous, unmapped, no_identifier}}}`. `company` is the enriched row (`route.company`); `route` is `{market, status, basis, detail}`. `universe_path` must satisfy `Path(p).resolve().is_relative_to((settings.runs_dir / "_universes").resolve())` else 400 `"Universe file must be a saved universe."`; neither field gives 400 `"Provide either `companies` or `universe_path`."`; more than 10,000 companies gives 400. The identifier map is read once per request.

- [ ] **Step 1: Write failing tests** with `TestClient` and the app fixtures other `test_api_*.py` files use: `test_workbench_with_companies` (one mapped US, one EU by country, one unrouted; counts and per-row routes asserted); `test_workbench_with_saved_universe_path`; `test_path_outside_universes_is_400` (parametrize: `"../etc/passwd"`, an absolute `tmp_path/"x.csv"` outside, a symlink inside `_universes` pointing outside; assert 400 and that `load_company_universe` was not called); `test_requires_companies_or_path`; `test_too_many_companies`; `test_duplicate_company_ids_both_rows_returned`; `test_requires_authorization` (same pattern as the other routers' auth tests).
- [ ] **Step 2: Run** `python -m pytest tests/test_api_universe_workbench.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the router and include it in `main.py`.
- [ ] **Step 4: Run** the tests, `tests/test_api_xbrl.py`, and ruff. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): universe workbench endpoint (mapping, routing, availability)`.

### Task 5: XBRL Auto market, routing store, CLI screen

**Files:**
- Modify: `backend/arp/xbrl_pipeline/models.py`, `backend/arp/xbrl_pipeline/fetch.py`, `backend/arp/api/routers/xbrl.py`, `backend/arp/cli/xbrl.py`
- Test: `backend/tests/test_xbrl_auto.py` (new), `backend/tests/test_cli_xbrl.py`, `backend/tests/test_api_xbrl.py`

**Interfaces:**
- Consumes: Tasks 1, 2; `create_xbrl_run`, `execute_xbrl_run`, `fetch_company`, `fetch_company_esef` (existing).
- Produces:
  - `models.CompanyStatus`: `status` gains `"unrouted"` and `"no_source"`; new `note: str | None = None`; `market: Market | None = "sec"`.
  - `fetch.py`: `Market` stays `Literal["sec","esef"]`; new `RunMarket = Literal["auto","sec","esef"]`; `create_xbrl_run(companies, tags, refresh, run_store, market: RunMarket = "sec", index: MasterIndex | None = None) -> str` (for `auto`: routes the universe, writes `routing.json` in the run directory as a list of `{company_id, market, status, basis, detail, company}`, and stores the enriched companies as the run's companies); `load_routing(run_store, run_id) -> dict[str, dict]` (company id to routing entry); `execute_xbrl_run(..., market: RunMarket = "sec", source=None, esef_source=None)`; for `auto` each company is fetched by its stored route (SEC and ESEF sources built lazily, only when a company needs them); a `no_source` or `unrouted` company returns `CompanyStatus(status=<that>, cik=None, fact_count=0, report="none", market=None, note=<detail>)` without any fetch and counts as completed. A missing `routing.json` on an `auto` run is created from the stored companies, so older callers still work.
  - API: `XbrlRunRequest.market: Literal["auto","sec","esef"] = "auto"`; `start_run` builds the `MasterIndex` from `settings.identifier_map_path` and passes it; retry and resume read `manifest.params.get("market", "sec")` and reuse `routing.json`.
  - CLI: `arp xbrl fetch --market auto|sec|esef` default `auto` (other value exits 2; for `auto` it builds the `MasterIndex` from `settings.identifier_map_path`, like the API); new `arp xbrl screen --universe f` prints one line per company `company_id  market-or-status  basis  detail` and a summary `sec=N  esef=N  no_source=N  unrouted=N`; read-only.

- [ ] **Step 1: Write failing tests** in `test_xbrl_auto.py` with fake sources (reuse `FakeSource` / `EsefFake` patterns from `test_xbrl_fetch.py` and `test_xbrl_esef_fetch.py`): `test_auto_run_fetches_each_company_by_its_route` (4 companies: CIK, EU country with LEI, Japanese ISIN, name only; result rows are `ok`/`ok`/`no_source`/`unrouted`, the last two with `note` and `market is None`, run status `completed`); `test_routing_json_written_and_enriched_companies_stored`; `test_resume_and_retry_keep_the_original_routing` (change the identifier map between create and execute; the stored route is used); `test_forced_markets_ignore_routing` (`market="sec"` and `"esef"` behave as before; existing tests unchanged); `test_unrouted_rows_count_as_completed`; `test_sources_built_lazily` (a universe with no ESEF company never constructs the ESEF source). In `test_api_xbrl.py`: `test_start_run_market_defaults_to_auto` and `test_retry_of_an_auto_run_keeps_routing`. In `test_cli_xbrl.py`: `test_fetch_default_market_is_auto`, `test_screen_prints_routes_and_summary`, `test_screen_does_not_write_runs`.
- [ ] **Step 2: Run** `python -m pytest tests/test_xbrl_auto.py tests/test_api_xbrl.py tests/test_cli_xbrl.py -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** as specified; keep SEC and ESEF code paths unchanged.
- [ ] **Step 4: Run** `python -m pytest tests/test_xbrl*.py tests/test_esef*.py tests/test_api_xbrl.py tests/test_cli_xbrl.py -q` and ruff. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(xbrl): Auto market with stored per-company routing and a screen command`.

### Task 6: Landing page

**Files:**
- Create: `frontend/src/pages/ArgusUniverse.tsx`, `frontend/src/lib/workbench.ts`, `frontend/tests/workbench.test.ts`
- Modify: `frontend/src/types.ts` (workbench types), `frontend/src/api/client.ts` (`universeWorkbench`), `frontend/src/App.tsx` (TABS entry `{ id: "argusUniverse", label: "Universe" }`, lazy import, render line, "Workspaces" nav neighbours as the Argus screens, hand-over wiring)

**Interfaces:**
- Consumes: the Task 4 response; `UniversePicker` (`onResolved(path, count)`), `api.universeFromCompanies(companies, name)`, `sendUniverse(from)(to, path, count)` and `pendingFor` in `App.tsx`.
- Produces: types `WorkbenchRow`, `WorkbenchResponse`, `WorkbenchRoute`, `WorkbenchMapping`, `WorkbenchAvailability` mirroring the API; `api.universeWorkbench(body: {companies?: unknown[]; universe_path?: string}) => Promise<WorkbenchResponse>`; helpers in `workbench.ts`: `routeText(route): string` ("US (SEC)", "EU (ESEF)", "No XBRL source yet", "Not routed"), `mappingText(m): string`, `selectedCompanies(rows: WorkbenchRow[], selected: Set<string>): CompanyRef[]` (enriched companies, in table order, duplicates kept), `handoverName(target: "extraction" | "xbrl"): string`.

Page behaviour: universe via `UniversePicker`; on resolve call the workbench and show one table (selection box, company, mapping and issuer id, master LEI/CIK/ISIN, suggested route with its reason, availability cells for identity, documents, extraction, XBRL); a count line for routes and mapping; a select-all box; two buttons "Extraction" and "XBRL facts" and a scope switch "Whole universe" / "Selected (n)"; a button saves `selectedCompanies` with `api.universeFromCompanies` and calls `onSendUniverse(target, path, count)`. The page never starts a run.

- [ ] **Step 1: Write failing tests** in `workbench.test.ts`: `routeText` for sec, esef, no_source, unrouted; `mappingText` for the four statuses; `selectedCompanies` keeps table order and duplicate rows and returns the enriched company; `handoverName`.
- [ ] **Step 2: Run** `cd frontend && npm test -- workbench`. Expected: FAIL.
- [ ] **Step 3: Implement** types, client call, helpers, the page and the `App.tsx` wiring (receiver for `extraction` already exists; Task 7 adds the `xbrl` one).
- [ ] **Step 4: Run** `npm run lint && npm test && npm run build`; then start the dev server and the backend against a seeded store (as in the earlier XBRL screenshot run), load `#/argusUniverse`, and save a screenshot to the scratchpad directory (kill the servers by PID).
- [ ] **Step 5: Commit** `feat(frontend): Argus universe landing page`.

### Task 7: XBRL page Auto and hand-over receiver

**Files:**
- Modify: `frontend/src/pages/XbrlFacts.tsx`, `frontend/src/components/XbrlFetchArea.tsx`, `frontend/src/lib/xbrlTags.ts`, `frontend/src/types.ts`, `frontend/src/api/client.ts` (`startXbrlRun` market type), `frontend/src/App.tsx` (pass `pendingUniverse={pendingFor("xbrl")}`)
- Test: `frontend/tests/xbrlTags.test.ts`

**Interfaces:**
- Consumes: Task 5 API (`market` `auto|sec|esef`, statuses `unrouted`, `no_source`, `note`); Task 6 `api.universeWorkbench`.
- Produces: `XbrlRunMarket = "auto" | "sec" | "esef"` type; `XbrlCompanyStatus` gains `"unrouted" | "no_source"` statuses, `note: string | null`, `market: XbrlMarket | null`; `statusText` handles the two new statuses (`"Not routed"`, `"No XBRL source yet"`); `XbrlFacts` takes `pendingUniverse?: UniverseHandoff | null`.

Behaviour: the Fetch area's market control becomes Auto (default) / US (SEC) / EU (ESEF). A handed-over universe (`pendingUniverse`) is used like a picked one ("Using N companies sent from X"); a different pick replaces it. With Auto and a universe chosen, the area calls `api.universeWorkbench({universe_path})` and shows the route counts ("SEC n · ESEF n · no source n · not routed n") before "Start fetch"; with US or EU no preview is requested. The results table shows `note` for `unrouted` and `no_source` rows; the key column stays blank for them.

- [ ] **Step 1: Write failing tests**: `statusText("unrouted")`, `statusText("no_source")`, and that existing `statusText("not_found", "esef")` is unchanged.
- [ ] **Step 2: Run** `cd frontend && npm test -- xbrlTags`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the control, receiver, preview and status text.
- [ ] **Step 4: Run** `npm run lint && npm test && npm run build`; screenshot `#/xbrl` with Auto selected and a handed-over universe against the seeded backend (scratchpad directory).
- [ ] **Step 5: Commit** `feat(frontend): XBRL Auto market, hand-over receiver and routing preview`.

### Task 8: Argus process view

**Files:**
- Modify: `frontend/src/lib/processes.ts`, `frontend/src/pages/ProcessHub.tsx` (only if run-type mapping needs `xbrl_fetch`)
- Test: `frontend/tests/processes.test.ts`

**Interfaces:**
- Produces: in the Argus workspace: `screens` gains `["#/argusUniverse", "Universe"]` and `["#/xbrl", "XBRL Facts"]`; `runTypes` gains `"xbrl_fetch"`; the process `extract` gets a first step `{ tab: "argusUniverse", label: "Universe", does: "Bring or pick the universe, map it through the security master, see what is already stored, and hand the chosen companies to Extraction.", handsOn: "Mapped universe", carried: true }`; a new process `{ id: "xbrl", title: "XBRL facts", cadence: "Per universe, refreshed when filings change", outcome: "Every company routed to its filing market, its tagged facts stored with the original filing, revenue and capex resolved, and an extraction run verified against them.", steps: Universe, Fetch, Facts, Verify }` with `tab: "xbrl"` for the last three and `runTypes: ["xbrl_fetch"]` on Fetch. `WORKSPACE_OF_RUN_TYPE` must map `xbrl_fetch` to Argus.

- [ ] **Step 1: Write failing tests** in `processes.test.ts`: the Argus workspace has two processes (`extract`, `xbrl`) and `workspaceOfProcess("xbrl")?.id === "argus"`; the five workspace ids are unchanged; `stepHref` of the Universe step is `"#/argusUniverse"`; the workspace for run type `xbrl_fetch` is Argus; the Argus screens include both new links.
- [ ] **Step 2: Run** `cd frontend && npm test -- processes`. Expected: FAIL.
- [ ] **Step 3: Implement** the data changes (and the run-type mapping if it is not derived from `runTypes`).
- [ ] **Step 4: Run** `npm run lint && npm test && npm run build`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): Argus process view with the universe step and the XBRL process`.

### Task 9: Docs and final checks

**Files:**
- Modify: `docs/superpowers/specs/2026-10-10-argus-universe-landing-design.md` (status "implemented"; fix anything that differs from the build), `docs/PROCESS_VIEW.md` (workspace and process tables, a paragraph on the landing page, the security-master paragraph's mention of routing), `README.md` (function table row for the Universe screen / XBRL Auto), `docs/TECHNICAL_REFERENCE.md` (module map: `universe_workbench/`; a section for the workbench endpoint; XBRL section: Auto, `routing.json`, new statuses, `arp xbrl screen`)

- [ ] **Step 1: Update the docs** from the built code (read `routing.py`, `mapping.py`, `availability.py`, `fetch.py`, `routers/universe_workbench.py`), concise and in the surrounding style; do not rewrite unrelated text.
- [ ] **Step 2: Run** `cd backend && ruff check arp tests && python -m pytest -p no:cacheprovider tests/test_workbench*.py tests/test_api_universe_workbench.py tests/test_xbrl*.py tests/test_esef*.py tests/test_api_xbrl.py tests/test_cli_xbrl.py tests/test_api_documents*.py -q`. Expected: all PASS.
- [ ] **Step 3: Full suite and comparison.** Run `python -m pytest -p no:cacheprovider -q 2>&1 | grep -E "^(FAILED|ERROR)" | sed 's/ - .*//' | sort > branch.txt` on the branch, and the same on a clean `origin/main` worktree (`git worktree add` in the scratchpad directory, removed afterwards); `diff` the two lists. Expected: identical (main has 44 known browser/botocore failures).
- [ ] **Step 4: Frontend** `cd frontend && npm run lint && npm test && npm run build`. Expected: pass.
- [ ] **Step 5: Commit** `docs: Argus universe landing page, Auto routing and the XBRL process`. Open the PR against `main` only when the user asks.
