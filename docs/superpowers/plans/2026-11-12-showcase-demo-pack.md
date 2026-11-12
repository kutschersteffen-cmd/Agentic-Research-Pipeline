# Showcase demo pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native, one session, no subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `demo/showcase/` pack, one loader script that fills an empty ARP in the right order, and a run sheet the presenter reads from.

**Architecture:** Data files plus `backend/scripts/load_showcase_pack.py`. The loader is a list of seven step functions run in order; each prints one `ok|skip|FAIL <step>: <reason>` line. Local steps call the app's own functions (`load_company_universe`, `resolve_company`, `save_universe`, `generate_demo_dataset`); run steps call the running API with `httpx` (already a dependency). No file under `backend/arp/` or `frontend/src/` changes.

**Tech Stack:** Python 3, httpx, SQLAlchemy session from `arp.db.session.transaction`, pytest (Postgres tests use the `pg` fixture), `httpx.MockTransport` for the stubbed API.

**Spec:** `docs/superpowers/specs/2026-11-12-showcase-demo-pack-design.md` (owner-approved 12 Nov 2026)

## Decisions the spec leaves open (need the owner's yes)

1. **Argus extractions have no name.** `ArgusFlow` has no name field, and the Argus list labels a run by its schema name ("Transition capex, R&D and redline facts v1 · 10 companies"). Adding a name is product code (AC-18). So "already exists" means: an Argus flow whose `schema_choice.schema_id` is the step's template and `reporting_year` is 2025 (`argus-plan`: and its companies are RWE only); for `voting`, a `proxy_voting` run in `GET /api/runs`. "Showcase: transition capex" is the name in the loader output and the run sheet, which also says what the Argus list shows instead. AC-22's stub reports such a flow.
2. **The presets are saved unreleased, and a draft schema runs as a trial on one company only** (`arp/argus/start.py`). The loader installs the preset and releases it when its newest version is not released. Release needs role `approver`, not `analyst` as the spec says: dev sign-in is approver, and the two approvers `launch_jupyter.sh users` writes qualify. A 403 prints `FAIL argus-capex: ...` naming the role.
3. **AC-18 is checked once, not by a committed test.** A test asserting `git diff origin/main...HEAD` has no `backend/arp/` path would fail every later product PR. The command and its output go in the PR description.
4. **ISINs only where two sources agree it is the share.** GLEIF lists every ISIN a company issued (bonds included). US: the CUSIP the SEC 13(f) list marks `COM`, as an ISIN, found in the company's GLEIF list (all 4 confirmed; the S&P 500 file has the same ISIN). EU: the ISIN a public file in `data/holdings/` lists for the company, found in its GLEIF list: RWE, E.ON, BASF, Heidelberg Materials confirmed; Engie has two lines, the one named `ENGIE SA` is taken, not `ENGIE SA PF 2028` (loyalty-dividend shares); thyssenkrupp is in no file, so its ISIN stays blank (its LEI is enough for AC-1). Tickers: US from SEC `company_tickers.json`; EU the spec's `company_id`.
5. **(a) The constituent import does not take the files unchanged.** It accepts only names like `Constituent_<fund ISIN>.xlsx` (`DAX.xlsx: expected a file name like Constituent_<ISIN>.xlsx`) and needs an assumed fund size in EUR. The content is fine: a renamed copy of `DAX.xlsx` imports 43 rows, weights sum 1.000000, one sector word left untranslated (`Grundstoffe`). The files do not carry the ETF's own ISIN. Proposal: the loader copies each file, bytes unchanged, to a temp folder as `Constituent_<12-character id>.xlsx` (`DAX000000000`, `EUROSTOXX500`, `MSCIEM000000`, `MSCIEUROPE00`, `MSCIWORLD000`, `SP5000000000`), imports with an assumed EUR 100 million per fund (the tag says `sizing:assumed-notional-eur-...`), then saves each portfolio's name as `DAX (public ETF holdings, 2026-11-02)` and replaces the made-up `fund_isin:` tag with `source:DAX.xlsx`. Alternatives: a factory item so the import takes any file name (the pack waits for it), or renaming the files with the real fund ISINs (needs a source for them).
6. **(c) The overlap matches the converted files by name, and for equities it is exact.** With no ticker the parser keys a holding on its name. All 17 equities in both files have the same name and ISIN in both. Converting every line gives 20 shared by name but 19 ISINs in both, so AC-25 fails: the cash lines (`EURO CURRENCY`, `US DOLLAR`, pseudo-ISINs `_CURRENCYEUR`, `_CURRENCYUSD`) are in both, and the money-market fund `DEUTSCHE GLOBAL LIQUIDITY SERI` has the same name under two ISINs. Proposal: convert only the `Type of Security = Aktien` rows, reading AC-6's "constituent rows" as those; then 17 shared by name = 17 ISINs in both. Columns `Name,ISIN,Sector,Weight` with the xlsx fraction written as is (no `Ticker` column: an empty one makes the parser drop names containing EURO, DOLLAR and the like, e.g. Euronext).
7. **AC-20 cannot hold once the six files are imported.** 10 names appear under two ISINs in the public files (share classes and dual listings: RIO TINTO, LINDT, EQT, ICBC, ...), and `RWE AG` is both the DAX file's name and the showcase name. Proposal: AC-20 compares the registry with the seeded demo portfolios' companies only (what it was written for: Enel, Iberdrola, Orsted); the imported index companies are keyed by ISIN (`isin_<ISIN>`) and left out.
8. **(b) preview, to confirm on the stack.** The import writes no holdings load record and its only snapshot is 2026-11-02, so a monthly run of October is blocked for the imported portfolios. The loader will not write load records (that would claim a load that did not happen). If the stack confirms it, T1's rule and alert stay on the seeded portfolios and the imported ones are shown next to them; the run sheet says so.

## Global Constraints

- No path under `backend/arp/` or `frontend/src/` changes; no new dependency.
- Identifiers only from api.gleif.org, data.sec.gov, www.sec.gov; all 10 companies confirmed or stop and ask.
- Holdings come from the public files in `data/holdings/` (line 1 of each converted file: `Source: <file name>, public ETF holdings as of 2026-11-02`); invented content (engagement notes, trigger rows) says so in the run sheet.
- Loader line format `ok|skip|FAIL <step>: <reason>`; exit 1 if any `FAIL`; steps in order `companies, universe, portfolios, documents, argus-capex, argus-plan, voting`.
- Skip reasons, checked in this order: `no document present`, `API not reachable at <url>`, `already exists`.
- Default `--base-url http://127.0.0.1:8000`; `ARP_SHOWCASE_TOKEN` → `Authorization: Bearer <token>`.

## Review Focus

1. A PDF present but failing Argus's year/name check: no file is kept, start returns 400 → `FAIL argus-capex: Keep at least one file in step 2.` (the API's message), not a crash. Test in Task 4.
2. Loader run twice: `companies` and `universe` must not add a second registry company or a second universe file. Test in Task 3 (AC-8 runs twice; universe file count stays 1).
3. API up but token missing or wrong role (401/403): a `FAIL` line with the status and the API's `detail`, never a traceback. Test in Task 4.
4. `documents_dir` set to a relative path or missing folder: the copy creates folders and the line counts what was copied. Covered by AC-19 with a fresh tmp dir.
5. A company id the registry already holds under a different name (bank DB not empty): `resolve_company` attaches by LEI/CIK; the line still says `10 registered`. Covered by running AC-8 twice.

---

### Task 1: Companies and identifiers

**Files:**
- Create: `demo/showcase/companies.csv`, `demo/showcase/identifiers_source.json`
- Test: `backend/tests/test_showcase_pack.py`

**Interfaces:**
- Produces: `companies.csv` header `company_id,name,ticker,website,cik,lei,isin,country,sector,isic_code,fiscal_year_end`, 10 rows in the spec's order. `identifiers_source.json`: `{"looked_up": "<date>", "companies": {"<company_id>": {"lei": {"value", "legal_name", "url"}, "cik": {"value", "name", "url"}, "isin": {...}|null, "ticker": {...}}}}`.

- [ ] **Step 1: Write the failing tests** (`PACK = Path(__file__).parents[2] / "demo/showcase"`)
  - `test_companies_csv_loads` (AC-1): `load_company_universe` → 10; each has `company_id, name, country, isic_code` and one of `isin, lei, cik`; header lacks `regimes`.
  - `test_identifier_check_digits` (AC-2): ISO 6166 Luhn on letters-to-digits, ISO 17442 `int(digits) % 97 == 1`, CIK `^\d{1,10}$`.
  - `test_isic_in_transition_sectors` (AC-3): every code starts with one of `351, 201, 241, 2394`, and each such prefix is in `load_benchmarks().sectors[...].isic_prefixes` (so the test breaks if the app's table moves).
  - `test_argus_parser_reads_all` (AC-4): `arp.argus.companies.parse_rows("companies.csv", bytes)` → 10 rows, each with a value matching `_SHAPE` for LEI, ISIN or CIK.
  - `test_identifiers_match_source` (AC-21): each LEI/CIK has a JSON entry whose name equals `name` after dropping case, punctuation and the legal forms the spec lists.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_showcase_pack.py -q` → FAIL (file missing).
- [ ] **Step 3: Look up identifiers** with a throwaway script in the scratchpad (GLEIF `lei-records?filter[entity.legalName]=` and `/lei-records/{lei}/isins`, SEC `company_tickers.json` and `submissions/CIK##########.json`, the 13(f) list). Write both files from the responses. Websites: the company's own domain from the SEC submissions `website` field (US) or left blank (EU) — never from memory.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** `feat(demo): showcase companies with looked-up identifiers`

### Task 2: Static pack files

**Files:**
- Create: `demo/showcase/documents.csv`, `demo/showcase/documents/.gitkeep`, `demo/showcase/etf_dax.csv`, `demo/showcase/etf_euro_stoxx_50.csv`, `demo/showcase/README.md`
- Modify: `.gitignore` (`demo/showcase/documents/*.pdf` and `demo/showcase/benchmark_holdings.csv`)
- Test: `backend/tests/test_showcase_pack.py`

**Interfaces:**
- Produces: `documents.csv` rows: 10 `10-K` (reporting_year 2025, `<company_id>_annual_report_2025.pdf`), then 4 `DEF-14A` (2026, `<company_id>_proxy_statement_2026.pdf`) for NEE, DUK, NUE, DOW. `source` is "Company investor-relations site" or "SEC EDGAR".
- The two ETF CSVs per Decision 6, converted once from the xlsx (throwaway script, not committed). README: the load command, where each holdings file comes from (DWS constituent exports in `data/holdings/`, the iShares MSCI World holdings CSV the owner downloads), and that nothing in the pack is invented holdings.

- [ ] **Step 1: Failing tests**: `test_documents_csv` (AC-5, "only year" = `re.findall(r"20\d\d", file_name) == ["2025"]`), `test_etf_files_match_xlsx` (AC-6 via `load_holdings_with_weights`: count, names, ISINs, weights equal to the xlsx `Aktien` rows), `test_etf_overlap_counts_isins` (AC-25 via `compute_holdings_overlap`: `len(core_tickers)` = ISINs in both, ≥ 5), `test_etf_line_one` (AC-26), `test_no_invented_holdings` (AC-27: no csv/xlsx under `demo/showcase/` besides the two ETF files and `companies.csv`/`documents.csv`; README names `data/holdings/DAX.xlsx`, `EURO_STOXX_50.xlsx` and the iShares source), `test_documents_dir_ignored` (AC-13).
- [ ] **Step 2: Run** → FAIL. **Step 3:** write the files. **Step 4:** Run → PASS. **Step 5: Commit** `feat(demo): showcase documents list and public ETF holdings`

### Task 3: Loader, local steps

**Files:**
- Create: `backend/scripts/load_showcase_pack.py`
- Test: `backend/tests/test_load_showcase_pack.py` (imports via `sys.path.insert(0, scripts)` as `test_answer_check_export.py` does)

**Interfaces:**
- Produces: `main(argv: list[str] | None = None, *, client: httpx.Client | None = None) -> int`; `STEPS: dict[str, Callable[[Ctx], tuple[str, str]]]` returning `("ok"|"skip", reason)`, an exception → `FAIL`; `Ctx` dataclass with `settings`, `pack: Path`, `client`, `base_url`, `again: bool`, `extra: list[str]` (lines printed after the step line, e.g. `  missing: <file>`). Options `--only <step>`, `--again`, `--base-url`, `--pack` (default `<repo>/demo/showcase`).
- `companies`: `transaction(require_dsn(settings))` + `resolve_company` per row → `ok companies: 10 registered`.
- `universe`: `save_universe(settings, companies, "Showcase companies")` → `ok universe: Showcase companies (10 companies)`.
- `portfolios`: `asyncio.run(generate_demo_dataset(store, today=date.today()))` with the store the CLI's `_portfolio_store()` builds, then `import_constituent_files` on the six files per Decision 5 → `ok portfolios: 4 seeded, 6 imported`.
- `documents`: copy present files to `settings.documents_dir/<company_id>/<doc_type>/<file_name>` → `ok documents: <k> of 14 present` plus `  missing: <file_name>` lines in csv order, then `  benchmark: <n> equity rows` (`parse_ishares_holdings`) or `  missing: benchmark_holdings.csv`.

- [ ] **Step 1: Failing tests**: `test_companies_twice` (AC-8, `pg`), `test_portfolios_twice` (AC-9, `pg`, two runs, `len(store.list_portfolios()) == 10`), `test_no_duplicate_names` (AC-20 as Decision 7 reads it), `test_benchmark_line` (AC-7, 3-row iShares file in a tmp pack, then absent), `test_documents_copy` (AC-19, 4 dummy proxy PDFs in a tmp pack copy, tmp `ARP_DOCUMENTS_DIR`), `test_failing_step_continues` (AC-12: monkeypatch `STEPS["universe"]` to raise; later lines still print; exit 1), `test_universe_saved_once` (Review Focus 2).
- [ ] **Step 2: Run** → FAIL (no module). **Step 3:** implement. **Step 4:** Run → PASS. **Step 5: Commit** `feat(demo): showcase loader, local steps`

### Task 4: Loader, run steps

**Files:**
- Modify: `backend/scripts/load_showcase_pack.py`
- Test: `backend/tests/test_load_showcase_pack.py`

**Interfaces:**
- Consumes: `Ctx.client` (an `httpx.Client` with `base_url`; tests pass one on `httpx.MockTransport`).
- `argus-capex` / `argus-plan` call, in order: `POST /api/extraction/presets/{id}/install`; `GET /api/extraction/schemas/{id}/versions/{v}` and, when `release_flag` is false, `POST .../release`; `POST /api/argus/flows`; `POST /api/argus/flows/{f}/companies/upload` (a CSV of the `companies.csv` rows whose annual report is present; RWE only for plan); `PATCH /api/argus/flows/{f}` `{reporting_year: 2025, source: "upload", schema_choice: {kind: "schema", schema_id, version}, step: 3}`; `POST .../files {all_that_pass: true}`; `POST .../start`. Line: `ok argus-capex: started for <n> companies (flow <f>)`. Existence check first: `GET /api/argus/flows` (Decision 1).
- `voting`: `GET /api/runs?run_type=proxy_voting` for existence, then `POST /api/voting/runs {companies: [...]}` with the US rows whose proxy is present → `ok voting: started for <n> companies (run <r>)`.
- Unreachable = `httpx.ConnectError`/`ConnectTimeout` on the first call → `skip <step>: API not reachable at <base_url>`. Any 4xx/5xx → exception with `<status> <detail>` → `FAIL`.

- [ ] **Step 1: Failing tests**: `test_all_steps_no_documents` (AC-10: full output lines and exit 0, `pg` for the local steps), `test_api_unreachable` (AC-11: real client to `http://127.0.0.1:9`, expect exact default-URL line by passing `--base-url` unset and stubbing the transport to raise `ConnectError`), `test_already_exists` (AC-22: 0 POSTs to `/api/argus/flows`), `test_again_creates` (AC-23: 1 create, line starts `ok argus-capex:`), `test_forbidden_is_fail` (Review Focus 3), `test_start_rejected_is_fail` (Review Focus 1).
- [ ] **Step 2: Run** → FAIL. **Step 3:** implement. **Step 4:** Run → PASS. **Step 5: Commit** `feat(demo): showcase loader starts the prepared runs`

### Task 5: Run sheet

**Files:**
- Create: `demo/showcase/RUN_SHEET.md`
- Test: `backend/tests/test_showcase_pack.py`

**Interfaces:**
- Five blocks headed `## 0 to 12 · Argus`, `## 12 to 24 · Transition Intelligence`, `## 24 to 36 · R&D Lab`, `## 36 to 48 · StewardIQ`, `## 48 to 60 · Argus, questions`; one `Fallback <scene>:` line per scene; `## Day before` checklist with the load command, the taxonomy clicks, and "wait until finished" naming the screen per run (Argus list for both extractions, StewardIQ → Proxy voting for `voting`); a `## Start from an empty database` section using existing commands; a note per click that depends on open PRs #418, #419, #421, #410.
- Monitoring rule and three trigger-scan rows are chosen by running them on the seeded data in the e2e stack (Task 6) so they give at least one alert and one trigger.

- [ ] **Step 1: Failing tests**: `test_run_sheet_blocks_and_fallbacks` (AC-17), `test_run_sheet_day_before` (AC-24: contains `python scripts/load_showcase_pack.py`, `Energy transition`, `accept`, `release`, `Showcase companies`, and one line naming `argus-capex`, `argus-plan`, `voting` with "finished").
- [ ] **Step 2: Run** → FAIL. **Step 3:** write it from the app on `main` (click paths read from `frontend/src`). **Step 4:** Run → PASS. **Step 5: Commit** `docs(demo): showcase run sheet`

### Task 6: Verify and hand over

- [ ] Repo checks: `cd backend && ruff check scripts/load_showcase_pack.py tests/test_showcase_pack.py tests/test_load_showcase_pack.py && python3 -m pytest tests/test_showcase_pack.py tests/test_load_showcase_pack.py` (Postgres via `ensure-deps.sh postgres`).
- [ ] AC-18: `git diff --name-only origin/main...HEAD` → no `backend/arp/`, `frontend/src/` path; output saved for the PR.
- [ ] Evaluator rows on the e2e stack (`e2e_stack.sh up`, loader `--only companies` and `--only universe`): AC-14 Argus upload shows 10, none "No identifier"; AC-15 overlap shows both names and 6 shared; AC-16 RWE page says "Power & Utilities". Screenshot each; if the stack does not start, say so.
- [ ] Try the monitoring rule, the monthly run and the trigger rows there, on an imported index portfolio first (check (b)); fix the run sheet values to ones that fire and say where T1's alert comes from.
- [ ] Push `claude/showcase-demo-pack`; send branch, head SHA and test summary to the coordinating session. No PR.
