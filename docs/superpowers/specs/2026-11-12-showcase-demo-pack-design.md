# Showcase demo pack and run of show

Slug: `showcase-demo-pack`. Revised 13 Nov 2026 against `main` 7440e12 (owner: "fix everything needed").
Status: **approved by the owner on 13 Nov 2026** (buttons in the coordinating session), with the recommended
option on all three decisions below.

## Intent

The owner shows ARP live on 17 Nov to senior management and analysts: about 60 minutes, four workspaces
(Argus, Transition Intelligence, R&D Lab, StewardIQ), in the bank JupyterLab (Gemini through Vertex AI,
one uvicorn process, Postgres, no Superset). ARP starts empty there. This spec adds the data that fills it,
one command that loads it the day before, and a run sheet that says what to click in which minute.

Why one pack and not loose files: three loading-order traps were found on 11 Nov (a company needs its
ISIC code before Argus first touches it; ESG rows only for known company ids; security master before
holdings). A script keeps the order; a person under time pressure does not.

## Goals

1. One storyline on the same 10 real listed companies in Argus, R&D Lab, StewardIQ and the company-page
   Transition section. Scenes T1 (portfolio monitoring) and R3 (Index Construction) run on public
   portfolios and index files instead; the run sheet says so.
2. Everything works with no internet from the Jupyter: every document is a file in the pack. Live document
   search is a bonus when the `fetch` line of `scripts/launch_jupyter.sh check` says `ok`.
3. Runs that take minutes are finished the day before; one extraction is started live in minute 2 and
   shown finished near the end.
4. Loading is one command, safe to run twice.
5. Wherever the demo shows fund or index holdings, they come from the seven public ETF holdings files in
   `data/holdings/` (six index files as of 2 Nov 2026, `AI_Big_Data.xlsx` as of 12 Nov 2026), not from
   invented funds.
6. One thematic portfolio is in the mix: `AI_Big_Data.xlsx` (fund ISIN IE00BGV5VN51, 100 equities),
   imported as a portfolio with the six index files and offered to the R&D Lab as a holdings file.
7. ESG values, controversial revenue shares, A-F transition grades and the June to October holdings history
   come from the simulated dataset (`data/simulated/esg_simulated.csv`, loaded by `arp showcase load`). The
   run sheet labels each of them `Simulated` wherever the presenter shows one.

## Non-goals

- No change to product code under `backend/arp/` or `frontend/src/`. If the pack exposes a defect, it goes
  to the factory as its own item.
- No client data and no positions of the bank. One thing is invented and says so: the trigger-scan rows.
- No Data Hub, Decision Studio, Reports or RFP scenes, and no Superset dashboards or charts (`arp bi ask`
  and `arp bi design` need a Superset; the bank Jupyter has none).
- No seeded demo portfolios (`arp portfolio seed-demo`): T1 runs on a public portfolio (owner decision 1).
- No taxonomy derived from thematic ETFs (dropped 12 Nov, rows AC-28 to AC-37) and no StewardIQ benchmark
  file (dropped 12 Nov, rows AC-7 and AC-39).
- No automatic reset of the database.

## Anti-goals

- A number on screen that looks like a real holding of the bank, or a simulated value presented as real.
- A scene that only works when the internet does.
- An identifier typed from memory that points at the wrong company.
- A scene built on a company the simulated dataset is about to delete: the 19 dataset rows whose ISIN starts
  with `RU` (Gazprom, Sberbank, ...; the 15 written-off positions being removed are among them) never appear
  in the run sheet.

## Constraints

- Annual reports and proxy statements are copyrighted and large, so they are not committed. The pack lists
  them; the owner saves them into `demo/showcase/documents/` under the given file names.
- Argus checks each file: the file name must carry the reporting year, and a PDF must have a text layer
  with the company name on its first pages.
- The Argus list upload keeps `isic_code` since #418/#428. The `companies` step stays anyway: it registers
  the ten companies (with ISIC, under their universe ids `RWE`, ...) before any document, upload or run
  exists, so the RWE company page (T2, AC-16) and the document folders do not depend on which Argus upload
  happens first.
- Argus extractions have no name field; the Argus list labels a run by its template's name and version
  ("Transition capex, R&D and redline facts v1 · 10 companies"). "Showcase: transition capex" and
  "Showcase: RWE transition plan" are the names the loader output and the run sheet use; the run sheet
  says what the Argus list shows instead.
- The two preset templates (`sch_transition_capex`, `transition_plan_indicators`) are saved unreleased, and
  a draft template runs as a trial on one company only. A full run needs the template released, which
  needs role `approver`; the loader releases them (owner decision 3).
- `arp showcase load` (PR #434, `showcase-portfolio-data` PR 2) is not merged on 13 Nov. Until it is, the
  `portfolios` step prints `skip` and T1 has no public portfolio.
- Several screens change in PRs not merged on 13 Nov: Themes fixes (#429 and its PR 2), Index Construction
  screen (`index-starting-universe` PR 2), Argus fixes PR 2 and PR 3, portfolio-data PR 3 (grades on
  screens). The run sheet names the PR next to each click that needs it and says what to do without it.
- The factory is changing the simulated dataset after #434: it deletes 15 written-off positions and scales
  controversial revenue shares above 100 % to 100 %. Nothing in the pack depends on those names or on the
  dataset's row count (2,538 on 13 Nov).
- Nothing here has run in the bank Jupyter. The pack is verified in the cloud sandbox with the stand-in
  model; the first real proof is the owner's rehearsal.

## Approaches

1. **Pack plus loader script (chosen by the owner, 12 Nov).** Files in `demo/showcase/`, one script that
   loads them in order and starts the runs to be finished, a run sheet. Costs one script and its test.
2. Pack only, loaded by hand from the run sheet. Rejected by the owner.
3. Extend `arp portfolio seed-demo` to seed everything. Rejected: showcase data in product code, and it
   could not carry the documents.

## The companies

| company_id | Name | Country | ISIC | Transition sector |
|---|---|---|---|---|
| RWE | RWE AG | DE | 3510 | Power & Utilities |
| EOAN | E.ON SE | DE | 3510 | Power & Utilities |
| ENGI | Engie SA | FR | 3510 | Power & Utilities |
| BAS | BASF SE | DE | 2011 | Chemicals |
| TKA | thyssenkrupp AG | DE | 2410 | Steel |
| HEI | Heidelberg Materials AG | DE | 2394 | Cement |
| NEE | NextEra Energy Inc | US | 3510 | Power & Utilities |
| DUK | Duke Energy Corp | US | 3510 | Power & Utilities |
| NUE | Nucor Corp | US | 2410 | Steel |
| DOW | Dow Inc | US | 2011 | Chemicals |

Identifiers come from GLEIF and SEC EDGAR, never from memory, and are saved in `identifiers_source.json`
(per company: the LEI record's legal name and status, the SEC record's name for a CIK, the source of each
ISIN, the lookup date). Looked up on 12 Nov: all 10 LEIs confirmed by exact legal name; the 4 US CIKs and
tickers from SEC. An ISIN is filled in only where two sources agree it is the ordinary share: US, the CUSIP
the SEC 13(f) list marks `COM`, found in the company's GLEIF ISIN list; EU, the ISIN a file in
`data/holdings/` lists for the company, found in its GLEIF ISIN list (Engie: the line named `ENGIE SA`).
thyssenkrupp is in no holdings file, so its ISIN stays blank (its LEI is enough). EU tickers are the
`company_id` above.

## Files in `demo/showcase/`

| File | Format | Used in |
|---|---|---|
| `companies.csv` | Universe format: `company_id,name,ticker,website,cik,lei,isin,country,sector,isic_code,fiscal_year_end`. No `regimes` column. | Argus step 1, every universe picker, loader |
| `identifiers_source.json` | The saved GLEIF and SEC lookups behind `companies.csv`. | Proof for the identifiers |
| `documents.csv` | `company_id,doc_type,reporting_year,file_name,title,source`. 14 rows: one annual report per company (`doc_type` `10-K`, the app's "Annual report", `reporting_year` 2025, file name contains `2025`) and one proxy statement per US company (`DEF-14A`, `reporting_year` 2026, file name contains `2026`). `source` names where to get it (company investor-relations site or SEC EDGAR), no deep links. | Owner's download list, loader |
| `documents/` | Empty in git (`.gitkeep`, PDFs git-ignored). The owner saves the 14 files here. | Loader, live upload |
| `etf_dax.csv`, `etf_euro_stoxx_50.csv`, `etf_ai_big_data.csv` | `data/holdings/DAX.xlsx`, `EURO_STOXX_50.xlsx` and `AI_Big_Data.xlsx` converted to the ETF holdings CSV the R&D Lab reads: columns `Name,ISIN,Sector,Weight` (`Sector` is the xlsx `Industry Classification`, unchanged; `Weight` is `Weighting`, unchanged), only rows whose `Type of Security` is `Aktien` or `Equities`, names, ISINs and weights unchanged. Line 1 is `Source: <file name>, public ETF holdings as of <the xlsx sheet's date>`. No `Ticker` column: the parser then keys a holding on its name, which matches all shared equities of DAX and EURO STOXX 50 (checked 12 Nov: same name and ISIN in both). | R&D Lab: overlap, build universe |
| `RUN_SHEET.md` | The run of show below, with every click, a fallback per scene, a "Depends on" table and the day-before checklist. | Presenter |
| `README.md` | What the pack is, the load command, one `Source:` line per committed holdings csv with its public source and as-of date, and one line naming the simulated dataset. | Anyone |

## Loader

`backend/scripts/load_showcase_pack.py`, run from `backend/` with the app's environment, after
`scripts/launch_jupyter.sh up`. It prints one line per step, `ok|skip|FAIL <step>: <reason>`, and lines
starting with two spaces under it for details; it exits 1 if any step is `FAIL`.

API steps call `--base-url` (default `http://127.0.0.1:8000`). When `ARP_SHOWCASE_TOKEN` is set they send
it as `Authorization: Bearer <token>`. In dev sign-in mode (the bank Jupyter's setting) no token is needed
and the user is an approver.

| Step | Via | Does |
|---|---|---|
| `companies` | Database | Registers the 10 companies in the registry with their ISIC code (`resolve_company`) and their universe ids. |
| `universe` | Files (`save_universe` into `runs_dir/_universes`) | Saves `companies.csv` as the saved universe "Showcase companies" (the pickers list it as "Showcase companies (10 companies)"); a second run reuses the same file. |
| `portfolios` | `arp showcase load` (subprocess) | Runs `arp showcase load` (seven public portfolios, simulated June to October history, simulated ESG and scores, six monthly runs; about 3 minutes) and prints its lines indented under its own. Prints `skip portfolios: arp showcase load not available` when the installed app has no such command. |
| `documents` | File copy | Copies every file of `documents.csv` that is present in `demo/showcase/documents/` to `<documents_dir>/<company_id>/<doc_type>/<file_name>`, so runs find it without the internet; a file already there is overwritten, never copied under a second name. Lists the missing ones. |
| `argus-capex` | API | Installs and, if needed, releases template `sch_transition_capex`, creates an Argus extraction for every company whose annual report is present, reporting year 2025, keeps the files that pass the year and name check, and starts it. |
| `argus-plan` | API | Same for template `transition_plan_indicators` with RWE only (its annual report holds the sustainability statement). |
| `voting` | API | Starts a proxy voting run for the US companies whose proxy statement is present. |

The three API run steps print `skip` instead of starting anything, checked in this order: `no document
present`, then `API not reachable at <url>`, then `already exists` (an Argus extraction with the same
template and reporting year 2025, and for `argus-plan` RWE as its only company; for `voting` a
`proxy_voting` run). `--again` starts a second copy even when one exists. A refusal by the API (a 4xx or
5xx) prints `FAIL <step>: <status> <the API's detail>`. `--only <step>` runs one step. Steps `companies`,
`universe` and `documents` are repeatable and never skip. Step order: `companies, universe, portfolios,
documents, argus-capex, argus-plan, voting`.

The R&D Lab taxonomy is not loaded by the script: a taxonomy is drafted by the model and released by a
person, and that review is part of what the lab shows. The run sheet's day-before checklist has the clicks
(theme "Energy transition", accept, release, then a thematic universe run on "Showcase companies").

## Run of show (60 minutes)

| Minute | Workspace | Scene | Live or prepared |
|---|---|---|---|
| 0 to 12 | Argus | A1: new extraction, upload `companies.csv`, attach the RWE and NextEra reports, template "Transition capex", start. A2: open the prepared capex extraction: values per company, click a value to see its source passage, correct one value, approve, download CSV. | A1 live, A2 prepared |
| 12 to 24 | Transition Intelligence | T1: the public portfolios (DAX, MSCI World, AI Big Data) with six months of simulated history; on DAX add the run sheet's monitoring rule, "Run now" for October 2026, open the alert, whose text contains `Simulated`. T2: RWE company page, Transition section, then one cell of the barrier matrix. | T1 live, T2 prepared (`argus-plan`) |
| 24 to 36 | R&D Lab | R1 (4 min): Taxonomy Library, upload `etf_dax.csv` and `etf_euro_stoxx_50.csv` for overlap, then build a universe from `etf_ai_big_data.csv`. R2 (4 min): Thematic Universe, the released "Energy transition" taxonomy on "Showcase companies": verdict and evidence per company. R3 (4 min): Index Construction on the starting universe `DAX.xlsx` with the simulated ESG fields: screen out grade F and controversial revenue above a threshold, weight, cap, show the constituents and the notes naming the starting universe and `Simulated ESG data`. | R1 live, R2 prepared by hand, R3 live |
| 36 to 48 | StewardIQ | S1: the proxy voting run for the four US companies: recommendation and reason per resolution. S2: trigger scan with three rows typed from the run sheet, then a client stream with the bundled example policy. | S1 prepared, S2 live |
| 48 to 60 | Argus, questions | The extraction from minute 2 is finished: show it. Off-script: an analyst names a company (single-company form, upload its report) or types what to extract. | live |

Each scene's fallback in the run sheet is the prepared run of the same kind, so a slow model call never
leaves the screen empty. Fallback T1 is the October alert prepared the day before; fallback R3, while
`index-starting-universe` PR 2 is not merged, is the built-in demo universe, which the presenter calls
synthetic.

## Decided by the owner (13 Nov)

1. **Seeded demo portfolios.** Recommended: leave them out (T1 runs on DAX; the seed's own ESG load would
   make "Run now" for October republish it with November's values, #434 builder call 2). Alternative: keep
   them as a second fallback for T1, with an `Invented:` line in the run sheet.
2. **Index Construction without its screen.** If `index-starting-universe` PR 2 is not merged by the
   rehearsal: recommended, show R3 on the built-in demo universe and say the real starting universe is
   coming; alternatives, drop R3 and give its 4 minutes to R1 and R2, or show `POST /api/index/run` with
   `universe` `file:DAX` in a terminal.
3. **Releasing the two preset templates.** Recommended: the loader releases them (needs `approver`; dev
   sign-in is one). Alternatives: the owner releases both in the schema screen the day before, or the
   prepared extractions run as trials on one company each.

The owner chose the recommended option of each; the loader, the run of show and the rows below follow it. Another choice
changes: decision 1, AC-20 comes back and an `Invented:` line for the seeded portfolios is added; decision
2, R3 and AC-43, AC-50, AC-51; decision 3, the `argus-capex` and `argus-plan` steps.

## Left to the builder

- Exact API calls for `argus-capex`, `argus-plan` and `voting`, read on `main` at build time (Argus fixes
  PR 1 changed step 1's keys and endpoints).
- The monitoring rule (type, threshold) and the three trigger-scan rows: the rule must raise at least one
  alert on `portfolio_dax` for 2026-10 (AC-42); the rows at least one trigger.
- R3's screen settings (grade and controversial-revenue filters, weighting, cap), chosen on the stack so
  the result has between 20 and 40 constituents.
- A full reset is not built. The run sheet says how to start from an empty database with the existing
  commands.
- Checked 12 Nov, recorded for the reader: (a) the constituent import did not take the files under their
  own names, which #434 fixes; (c) the overlap of the two converted files matches all shared equities by
  name.

## Acceptance

Rows are `unit` or `evaluator`: this is demo tooling outside product code, and there is no product
behaviour for a hidden test to pin. "The e2e stack" is `backend/scripts/e2e_stack.sh up`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `demo/showcase/companies.csv` | `load_company_universe` reads it | 10 companies; every one has `company_id`, `name`, `country`, `isic_code` and at least one of `isin`, `lei`, `cik`; the header has no `regimes` column | unit |
| AC-2 | `companies.csv` | each identifier is checked | every ISIN passes the ISO 6166 check digit, every LEI passes the ISO 17442 mod-97 check, every CIK is 1 to 10 digits | unit |
| AC-3 | `companies.csv` | each `isic_code` is mapped with `sector_for_isic(load_benchmarks(), isic_code)` | for each company the result equals its "Transition sector" in "The companies" table | unit |
| AC-4 | `companies.csv` | it is parsed by the Argus list upload parser | 10 rows returned, none without a valid-shaped ISIN, LEI or CIK | unit |
| AC-5 | `documents.csv` | it is read | 14 rows; every `company_id` is in `companies.csv`; 10 rows have `doc_type` `10-K`, `reporting_year` 2025 and a `file_name` whose only year is `2025`; 4 rows (NEE, DUK, NUE, DOW) have `doc_type` `DEF-14A`, `reporting_year` 2026 and a `file_name` whose only year is `2026`; every `file_name` ends in `.pdf` | unit |
| AC-6 | `etf_dax.csv`, `etf_euro_stoxx_50.csv` and `etf_ai_big_data.csv` | the ETF holdings parser reads each | 40 holdings for DAX, 52 for EURO STOXX 50 and 100 for AI & Big Data (the xlsx rows whose `Type of Security` is `Aktien` or `Equities`), each with the name, ISIN and weight of its xlsx row | unit |
| ~~AC-7~~ | ~~`benchmark_holdings.csv` read by the loader~~ | | Retired 12 Nov: the owner dropped the StewardIQ benchmark file | |
| AC-8 | An empty test database | the loader runs with `--only companies` twice | both runs print `ok companies: 10 registered`; the registry holds 10 companies, each with its `isic_code` | unit |
| AC-9 | `arp showcase load` replaced by a stub that prints `ok import: 7 portfolios` and exits 0 | the loader runs `--only portfolios` | prints `ok portfolios: arp showcase load`, then `  ok import: 7 portfolios`; exit code 0 | unit |
| AC-10 | `documents/` holds no PDF, `arp showcase load` stubbed to exit 0, the API stubbed | the loader runs all steps | `documents` prints `ok documents: 0 of 14 present`, then 14 lines `  missing: <file_name>` in `documents.csv` order; `argus-capex`, `argus-plan` and `voting` each print `skip <step>: no document present`; exit code 0 | unit |
| AC-11 | One annual report present, the API not reachable | the loader runs `--only argus-capex` | prints `skip argus-capex: API not reachable at http://127.0.0.1:8000`; exit code 0 | unit |
| AC-12 | A step raises | the loader runs all steps | that step prints `FAIL <step>: <message>`, the later steps still print their lines, exit code 1 | unit |
| AC-13 | `demo/showcase/documents/` | `git check-ignore demo/showcase/documents/x.pdf` | exit code 0 | unit |
| AC-14 | The e2e stack after `load_showcase_pack.py --only companies` and `--only universe` | a user opens Argus, starts a new extraction and uploads `companies.csv` | step 1 lists 10 companies, none marked "No identifier" | evaluator |
| AC-15 | Same | a user opens Taxonomy Library and uploads `etf_dax.csv` as "DAX" and `etf_euro_stoxx_50.csv` as "EURO STOXX 50" for overlap | the overlap result shows both display names and the number of shared holdings that AC-25 computes | evaluator |
| AC-16 | Same | a user opens the RWE company page | the Transition section names the sector "Power & Utilities" | evaluator |
| AC-17 | `RUN_SHEET.md` | it is read | it has five headings starting `## 0 to 12`, `## 12 to 24`, `## 24 to 36`, `## 36 to 48`, `## 48 to 60`, and 9 lines starting `Fallback A1:`, `Fallback A2:`, `Fallback T1:`, `Fallback T2:`, `Fallback R1:`, `Fallback R2:`, `Fallback R3:`, `Fallback S1:`, `Fallback S2:` | unit |
| AC-18 | The PR branch | `git diff --name-only origin/main...HEAD`, run once and pasted into the PR description (not a committed test: it would fail every later product PR) | lists no path under `backend/arp/` or `frontend/src/` | unit |
| AC-19 | 4 proxy PDFs present in `demo/showcase/documents/`, a temporary `documents_dir` | the loader runs `--only documents` | prints `ok documents: 4 of 14 present`; each of the 4 files exists at `<documents_dir>/<company_id>/DEF-14A/<file_name>` | unit |
| ~~AC-20~~ | ~~registry and seeded portfolio names~~ | | Retired 13 Nov: no seeded demo portfolios (owner decision 1); public portfolio companies live in the portfolio store under `isin_<ISIN>` ids | |
| AC-21 | `identifiers_source.json` and `companies.csv` | each LEI and CIK in `companies.csv` is looked up in the JSON | an entry exists, and its legal name equals the company's `name` once case, punctuation and the legal form (AG, Aktiengesellschaft, SE, SA, S.A., Inc, Incorporated, Corp, Corporation) are ignored | unit |
| AC-22 | One annual report present, the stubbed API lists an Argus extraction with template `sch_transition_capex` and reporting year 2025 | the loader runs `--only argus-capex` | prints `skip argus-capex: already exists` and sends 0 `POST /api/argus/flows` (template install and release calls are allowed) | unit |
| AC-23 | Same as AC-22 | the loader runs `--only argus-capex --again` | sends 1 `POST /api/argus/flows` and prints a line starting `ok argus-capex:` | unit |
| AC-24 | `RUN_SHEET.md` | its day-before checklist is read | it contains the load command, the taxonomy steps (theme "Energy transition", accept, release, thematic run on "Showcase companies"), and a line telling the presenter to wait until `argus-capex`, `argus-plan` and `voting` show as finished, naming the screen for each | unit |
| AC-25 | `etf_dax.csv` and `etf_euro_stoxx_50.csv` | the app's overlap function compares them | the shared-holdings count equals the number of ISINs present in both files, and is at least 5 | unit |
| AC-26 | `etf_dax.csv`, `etf_euro_stoxx_50.csv`, `etf_ai_big_data.csv` | line 1 of each is read | it starts with `Source:` and contains the date of its xlsx sheet (`2026-11-02`, `2026-11-02`, `2026-11-12`) | unit |
| AC-27 | `demo/showcase/` | `README.md` is read | one line starting `Source:` for each `*.csv` holdings file in `demo/showcase/`, naming that file; one line starting `Simulated:` naming `data/simulated/esg_simulated.csv`; the words `invented weights` do not occur | unit |
| ~~AC-28 to AC-37~~ | ~~thematic ETF folders, loader steps `thematic` and `infer`~~ | | Retired 12 Nov: the owner dropped the thematic-ETF taxonomy scene | |
| AC-38 | `RUN_SHEET.md` | it is read | it has one line starting `Invented:` naming the trigger-scan rows, and one line starting `Simulated:` naming the ESG values, controversial revenue shares, transition grades and June to October holdings history | unit |
| ~~AC-39~~ | ~~`benchmark_holdings.csv` git-ignored~~ | | Retired 12 Nov with AC-7 | |
| ~~AC-40~~ | ~~AI & Big Data portfolio from the pack's own import~~ | | Retired 13 Nov: `arp showcase load` imports it (`showcase-portfolio-data` AC-34) | |
| AC-41 | `RUN_SHEET.md` | its "Depends on" table is read | one row each for #434, Themes fixes #429, Themes fixes PR 2, `index-starting-universe` PR 2, Argus fixes PR 2, Argus fixes PR 3 and `showcase-portfolio-data` PR 3, each naming the scenes that need it and what to do without it | unit |
| AC-42 | The e2e stack with #434 merged, after `load_showcase_pack.py --only portfolios` | a user opens Risk Monitoring → Monitoring & Alerts, adds the run sheet's rule on `DAX (public ETF holdings, 2026-11-02)` and clicks "Run now" for 2026-10 | at least one alert on that portfolio is listed, and its text contains `Simulated` | evaluator |
| AC-43 | The e2e stack with `index-starting-universe` PR 2 merged and #434 merged | a user opens Index Construction, picks the starting universe `DAX.xlsx`, applies the run sheet's R3 settings and runs | the constituents table lists between 20 and 40 companies | evaluator |
| AC-44 | `RUN_SHEET.md` and `data/simulated/esg_simulated.csv` | the run sheet is searched case-insensitively for every dataset name whose ISIN starts with `RU`, and for the words Gazprom, Sberbank, Lukoil, Rosneft, Novatek, Surgutneftegas, Tatneft, Norilsk, Alrosa, Severstal, Novolipetsk, Magnit, Polyus, VTB, Rusal, PhosAgro, Inter RAO, Moscow Exchange | none occurs | unit |
| AC-45 | An empty `runs_dir` | the loader runs `--only universe` twice | both runs print `ok universe: Showcase companies (10 companies)`; the app's universe catalogue lists exactly one universe named `Showcase companies (10 companies)` | unit |
| AC-46 | RWE's annual report present, the stubbed API lists an Argus extraction with template `transition_plan_indicators`, reporting year 2025 and RWE as its only company | the loader runs `--only argus-plan` | prints `skip argus-plan: already exists` and sends 0 `POST /api/argus/flows` | unit |
| AC-47 | The 4 proxy statements present, the stubbed API lists one `proxy_voting` run | the loader runs `--only voting` | prints `skip voting: already exists` and sends 0 `POST /api/voting/runs` | unit |
| AC-48 | The 4 proxy statements present, the stubbed API lists no `proxy_voting` run | the loader runs `--only voting` | sends 1 `POST /api/voting/runs` whose `companies` are NEE, DUK, NUE, DOW, and prints a line starting `ok voting: started for 4 companies` | unit |
| AC-49 | 4 proxy PDFs present, a temporary `documents_dir` | the loader runs `--only documents` twice | each `<documents_dir>/<company_id>/DEF-14A/` folder holds exactly one file | unit |
| AC-50 | Same as AC-43 | same | the notes include `Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies.` | evaluator |
| AC-51 | Same as AC-43 | same | the notes include a line starting `Simulated ESG data: matched` | evaluator |
| AC-52 | `arp showcase load` replaced by a stub that exits 1 | the loader runs `--only portfolios` | prints `FAIL portfolios: arp showcase load exited 1`; exit code 1 | unit |
| AC-53 | `demo/showcase/documents/` | `git ls-files demo/showcase/documents/.gitkeep` | prints that path | unit |
| AC-54 | The e2e stack, the loader ran `--only companies` and `--only documents` with `RWE_annual_report_2025.pdf` present | a user starts a new Argus extraction, uploads `companies.csv` and opens step 2 with source Upload | step 2 lists `RWE_annual_report_2025.pdf` for RWE before any document search is started | evaluator |

Must not change: product code stays untouched (AC-18).
