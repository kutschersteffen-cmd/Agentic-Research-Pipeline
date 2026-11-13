# Showcase demo pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native, one session, no subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `demo/showcase/` pack, one loader script that fills an empty ARP in the right order, and a run sheet the presenter reads from on 17 Nov.

**Architecture:** Data files plus `backend/scripts/load_showcase_pack.py`. The loader is a list of seven step functions run in order; each prints one `ok|skip|FAIL <step>: <reason>` line plus indented detail lines. Local steps call the app's own functions (`load_company_universe`, `resolve_company`, `save_universe`); `portfolios` runs the app's `arp showcase load` as a subprocess; run steps call the running API with `httpx` (already a dependency). No file under `backend/arp/` or `frontend/src/` changes.

**Tech Stack:** Python 3, httpx, SQLAlchemy session from `arp.db.session.transaction`, pytest (Postgres tests use the `pg` fixture), `httpx.MockTransport` for the stubbed API.

**Spec:** `docs/superpowers/specs/2026-11-12-showcase-demo-pack-design.md` (revised 13 Nov). Active rows: AC-1 to AC-6, AC-8 to AC-19, AC-21 to AC-27, AC-38, AC-41 to AC-54. Retired: AC-7, AC-20, AC-28 to AC-37, AC-39, AC-40.

## Global Constraints

- No path under `backend/arp/` or `frontend/src/` changes; no new dependency.
- Identifiers only from api.gleif.org, data.sec.gov, www.sec.gov (looked up 12 Nov, saved; all 10 confirmed).
- Holdings shown come from `data/holdings/`; ESG, controversial revenue, grades and history from `data/simulated/esg_simulated.csv` and are labelled `Simulated`; the trigger-scan rows are labelled `Invented`.
- Loader line format `ok|skip|FAIL <step>: <reason>`, detail lines indented two spaces; exit 1 if any `FAIL`; step order `companies, universe, portfolios, documents, argus-capex, argus-plan, voting`.
- API step skip reasons in this order: `no document present`, `API not reachable at <url>`, `already exists`. Default `--base-url http://127.0.0.1:8000`; `ARP_SHOWCASE_TOKEN` → `Authorization: Bearer <token>`.
- The run sheet never names a holding whose ISIN starts with `RU` (AC-44).

## Review Focus

1. A PDF present but failing Argus's year/name check: no file kept, start returns 400 → `FAIL argus-capex: 400 <detail>`, not a traceback. Test in Task 4.
2. Loader run twice: `companies` and `universe` add no second registry company and no second universe file. Test in Task 3.
3. API up but token missing or role too low (401/403): `FAIL` line with status and detail. Test in Task 4.
4. `arp showcase load` missing (before #434 merges) or failing: `skip` or `FAIL` with its exit code; later steps still run. Test in Task 3.
5. `documents_dir` missing: the copy creates folders. Covered by AC-19 with a fresh tmp dir.

---

### Task 1: Companies and identifiers

**Files:** Create `demo/showcase/companies.csv`, `demo/showcase/identifiers_source.json`. Test `backend/tests/test_showcase_pack.py` (`PACK = Path(__file__).parents[2] / "demo/showcase"`).

**Interfaces:** `companies.csv` header `company_id,name,ticker,website,cik,lei,isin,country,sector,isic_code,fiscal_year_end`, 10 rows in the spec's order; `website` blank (SEC has none), `fiscal_year_end` `12-31` for the US four (SEC), blank for EU. `identifiers_source.json` as built on 12 Nov (`looked_up`, `how`, per company `lei`, `cik`, `isin`, `ticker` with sources), with the EU ISINs added per the spec (holdings file plus GLEIF list).

- [ ] **Step 1: Failing tests:** `test_companies_csv_loads` (AC-1), `test_identifier_check_digits` (AC-2: ISO 6166 Luhn, ISO 17442 mod 97 == 1, CIK `^\d{1,10}$`), `test_isic_maps_to_transition_sector` (AC-3: `sector_for_isic(load_benchmarks(), code)` equals the spec's sector per company), `test_argus_parser_reads_all` (AC-4 via `arp.argus.companies.parse_rows` and `_SHAPE`), `test_identifiers_match_source` (AC-21).
- [ ] **Step 2:** `cd backend && python3 -m pytest tests/test_showcase_pack.py -q` → FAIL. **Step 3:** write both files from the saved lookups. **Step 4:** → PASS. **Step 5: Commit** `feat(demo): showcase companies with looked-up identifiers`

### Task 2: Static pack files

**Files:** Create `demo/showcase/documents.csv`, `demo/showcase/documents/.gitkeep`, `demo/showcase/etf_dax.csv`, `demo/showcase/etf_euro_stoxx_50.csv`, `demo/showcase/etf_ai_big_data.csv`, `demo/showcase/README.md`. Modify `.gitignore` (`demo/showcase/documents/*.pdf`). Test `backend/tests/test_showcase_pack.py`.

**Interfaces:** `documents.csv`: 10 `10-K` rows (`<company_id>_annual_report_2025.pdf`), then 4 `DEF-14A` rows (`<company_id>_proxy_statement_2026.pdf`) for NEE, DUK, NUE, DOW. ETF csvs: line 1 `Source: <file>, public ETF holdings as of <sheet date>`, then `Name,ISIN,Sector,Weight` with the xlsx fraction as written, `Aktien`/`Equities` rows only (throwaway conversion script, not committed). README: purpose, load command, three `Source:` lines, one `Simulated:` line.

- [ ] **Step 1: Failing tests:** `test_documents_csv` (AC-5, only year = `re.findall(r"20\d\d", name) == ["2025"]`), `test_etf_files_match_xlsx` (AC-6: 40/52/100, name, ISIN, weight per xlsx row), `test_etf_overlap_counts_isins` (AC-25 via `compute_holdings_overlap`: `len(core_tickers)` = ISINs in both, ≥ 5), `test_etf_line_one` (AC-26), `test_readme_lines` (AC-27), `test_documents_pdf_ignored` (AC-13), `test_gitkeep_tracked` (AC-53).
- [ ] **Step 2:** → FAIL. **Step 3:** write the files. **Step 4:** → PASS. **Step 5: Commit** `feat(demo): showcase documents list and public ETF holdings`

### Task 3: Loader, local steps

**Files:** Create `backend/scripts/load_showcase_pack.py`. Test `backend/tests/test_load_showcase_pack.py` (imports via `sys.path.insert(0, scripts)` as `test_answer_check_export.py` does).

**Interfaces:**
- `main(argv: list[str] | None = None, *, client: httpx.Client | None = None) -> int`; `STEPS: dict[str, Callable[[Ctx], tuple[str, str]]]` returning `("ok"|"skip", reason)`, any exception → `FAIL <step>: <message>`; `Ctx` dataclass `settings, pack, client, base_url, again, lines` (`lines`: detail lines printed indented after the step line). Options `--only`, `--again`, `--base-url`, `--pack` (default `<repo>/demo/showcase`).
- `companies`: `transaction(require_dsn(settings))`, `resolve_company` per row, then the universe id per company the way `arp.argus.companies` records it → `ok companies: 10 registered`.
- `universe`: `save_universe(settings, companies, "Showcase companies")` → `ok universe: Showcase companies (10 companies)`.
- `portfolios`: module constant `SHOWCASE_LOAD = [sys.executable, "-m", "arp", "showcase", "load"]`; if `importlib.util.find_spec("arp.showcase.load")` is None → `skip portfolios: arp showcase load not available`; else run it, relay its stdout lines as detail lines; non-zero exit → `FAIL portfolios: arp showcase load exited <n>`; ok → `ok portfolios: arp showcase load`.
- `documents`: copy to `settings.documents_dir/<company_id>/<doc_type>/<file_name>` → `ok documents: <k> of 14 present` plus `  missing: <file_name>` in csv order.

- [ ] **Step 1: Failing tests:** `test_companies_twice` (AC-8, `pg`), `test_universe_twice` (AC-45: one catalogue entry via `arp.catalog.universes`), `test_portfolios_relays_showcase_load` (AC-9, `SHOWCASE_LOAD` pointed at a stub script), `test_portfolios_fail_exit_code` (AC-52), `test_portfolios_skip_when_missing` (Review Focus 4, `find_spec` patched), `test_documents_copy` (AC-19), `test_documents_twice` (AC-49), `test_failing_step_continues` (AC-12).
- [ ] **Step 2:** → FAIL. **Step 3:** implement. **Step 4:** → PASS. **Step 5: Commit** `feat(demo): showcase loader, local steps`

### Task 4: Loader, run steps

**Files:** Modify `backend/scripts/load_showcase_pack.py`; test `backend/tests/test_load_showcase_pack.py`.

**Interfaces:**
- First re-read `api/routers/argus.py` and `arp/argus/` on `main` (Argus fixes PR 1 changed step 1) and use the routes as they are then. Expected sequence: `POST /api/extraction/presets/{id}/install`; `GET /api/extraction/schemas/{id}/versions/{v}`, `POST .../release` when `release_flag` is false (per open decision 3); `POST /api/argus/flows`; `POST /api/argus/flows/{f}/companies/upload` (CSV of the `companies.csv` rows with a present annual report; RWE only for plan); `PATCH /api/argus/flows/{f}` (`reporting_year` 2025, `source` `upload`, `schema_choice` schema + version, `step` 3); `POST .../files {all_that_pass: true}`; `POST .../start`. Line `ok argus-capex: started for <n> companies (flow <f>)`.
- Existence: `GET /api/argus/flows`, a flow with that `schema_choice.schema_id` and `reporting_year` 2025 (plan: companies == RWE only). `voting`: `GET /api/runs?run_type=proxy_voting`, then `POST /api/voting/runs {companies}` → `ok voting: started for <n> companies (run <r>)`.
- `httpx.ConnectError`/`ConnectTimeout` on the first call → `skip <step>: API not reachable at <base_url>`; 4xx/5xx → `FAIL <step>: <status> <detail>`.

- [ ] **Step 1: Failing tests:** `test_all_steps_no_documents` (AC-10), `test_api_unreachable` (AC-11), `test_already_exists` (AC-22: 0 POSTs to `/api/argus/flows`), `test_again_creates` (AC-23), `test_plan_already_exists` (AC-46), `test_voting_already_exists` (AC-47), `test_voting_starts_us_four` (AC-48), `test_forbidden_is_fail` (Review Focus 3), `test_start_rejected_is_fail` (Review Focus 1).
- [ ] **Step 2:** → FAIL. **Step 3:** implement. **Step 4:** → PASS. **Step 5: Commit** `feat(demo): showcase loader starts the prepared runs`

### Task 5: Run sheet

**Files:** Create `demo/showcase/RUN_SHEET.md`; test `backend/tests/test_showcase_pack.py`.

**Interfaces:** five blocks `## 0 to 12 · Argus`, `## 12 to 24 · Transition Intelligence`, `## 24 to 36 · R&D Lab`, `## 36 to 48 · StewardIQ`, `## 48 to 60 · Argus, questions`; one `Fallback <scene>:` line per scene (9); `## Depends on` table (7 rows: #434, Themes fixes #429, Themes fixes PR 2, `index-starting-universe` PR 2, Argus fixes PR 2, Argus fixes PR 3, `showcase-portfolio-data` PR 3; scenes; what to do without it); `## Day before` (load command, taxonomy clicks, T1 rule plus October run for the fallback alert, "wait until finished" per run with its screen); `## Start from an empty database`; one `Invented:` and one `Simulated:` line. Click paths read from `frontend/src` on `main`; values (T1 rule, R3 settings, trigger rows) from Task 6.

- [ ] **Step 1: Failing tests:** `test_run_sheet_blocks_and_fallbacks` (AC-17), `test_run_sheet_day_before` (AC-24), `test_run_sheet_labels` (AC-38), `test_run_sheet_depends_on` (AC-41), `test_run_sheet_no_written_off_names` (AC-44).
- [ ] **Step 2:** → FAIL. **Step 3:** write it. **Step 4:** → PASS. **Step 5: Commit** `docs(demo): showcase run sheet`

### Task 6: Verify and hand over

- [ ] Repo checks: `cd backend && ruff check scripts/load_showcase_pack.py tests/test_showcase_pack.py tests/test_load_showcase_pack.py && python3 -m pytest tests/test_showcase_pack.py tests/test_load_showcase_pack.py` (Postgres via `ensure-deps.sh postgres`).
- [ ] AC-18: `git diff --name-only origin/main...HEAD` → no `backend/arp/`, `frontend/src/` path; output saved for the PR.
- [ ] Evaluator rows on the e2e stack: AC-14, AC-15, AC-16, AC-54 on this branch. AC-42, AC-43, AC-50, AC-51 need #434 and `index-starting-universe` PR 2: run them on a throwaway worktree of this branch merged with those PR heads (never pushed), pick the T1 rule and R3 settings there, and say which rows waited for an unmerged PR. Screenshot each; if the stack does not start, say so.
- [ ] Pick the three trigger-scan rows on the stack so they raise at least one trigger.
- [ ] Push `claude/showcase-demo-pack`; send branch, head SHA and test summary to the coordinating session. No PR (steward limit; the owner decides).
