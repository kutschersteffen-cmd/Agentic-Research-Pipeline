# Showcase demo pack and run of show

## Intent

The owner shows ARP live next week to senior management and analysts: about 60 minutes, four workspaces
(Argus, Transition Intelligence, R&D Lab, StewardIQ), in the bank JupyterLab (Gemini through Vertex AI,
one uvicorn process, Postgres). ARP starts empty there. This spec adds the data that fills it, one command
that loads it the day before, and a run sheet that says what to click in which minute.

Why one pack and not loose files: three loading-order traps were found on 11 Nov (a company needs its
ISIC code before Argus first touches it; ESG rows only for known company ids; security master before
holdings). A script keeps the order; a person under time pressure does not.

## Goals

1. One storyline on the same 10 real listed companies in Argus, R&D Lab, StewardIQ and the company-page
   Transition section. The one exception is scene T1 (portfolio monitoring), which runs on portfolios, not
   on the ten; the run sheet says so.
5. Wherever the demo shows fund or index holdings, they come from public ETF holdings files (owner,
   12 Nov), not from invented funds. The repo holds seven in `data/holdings/`: six index files (DAX, EURO STOXX 50,
   MSCI EM, MSCI Europe, MSCI World, S&P 500, as of 2 Nov 2026) and one thematic file (goal 6). Invented data stays only where no public
   file can serve, and each such place is named in the run sheet.
6. One thematic portfolio is in the mix (owner, 12 Nov): `data/holdings/AI_Big_Data.xlsx`, the public
   holdings of an AI & Big Data index ETF (fund ISIN IE00BGV5VN51, as of 12 Nov 2026, 100 equities). It is
   imported as a portfolio like the six index files and offered to the R&D Lab as a holdings file. No
   taxonomy is derived from thematic ETFs: the owner dropped that scene on 12 Nov (rows AC-28 to AC-37).

## Non-goals

- No change to product code under `backend/arp/` or `frontend/src/`. If the pack exposes a defect, it goes
  to the factory as its own item.
- No client data and no positions of the bank. Holdings come from public ETF holdings files. Two things
  stay invented and say so: the trigger-scan rows and the app's seeded demo portfolios.
- No Data Hub, Decision Studio, Reports or RFP scenes.
- No automatic reset of the database (see "Left to the builder").

## Anti-goals

- A number on screen that looks like a real holding of the bank.
- A scene that only works when the internet does.
- An identifier typed from memory that points at the wrong company.

## Constraints

- Annual reports and proxy statements are copyrighted and large, so they are not committed. The pack lists
  them; the owner saves them into `demo/showcase/documents/` under the given file names.
- Argus checks each file: the file name must carry the reporting year, and a PDF must have a text layer
  with the company name on its first pages.
- A company's Transition section needs `isic_code` on the registry company, set only when the company is
  first created. PR A of `showcase-stewardship-fixes` will make the Argus list upload keep it; until that
  is merged the loader must register the companies first.
- The seeded demo portfolios already contain Enel, Iberdrola and Orsted under their own ids, so the pack
  does not use those three (no company may appear twice in the registry).
- Nothing here has run in the bank Jupyter. The pack is verified in the cloud sandbox with the stand-in
  model; the first real proof is the owner's rehearsal.

## Approaches

1. **Pack plus loader script (chosen by the owner, 12 Nov).** Files in `demo/showcase/`, one script that
   loads them in order and starts the runs to be finished, a run sheet. Costs one script and its test.
2. Pack only, loaded by hand from the run sheet. Nothing to build, but about an hour of clicking before
   each rehearsal and the order is the presenter's to keep. Rejected by the owner.
3. Extend `arp portfolio seed-demo` to seed everything. Rejected: it would put showcase data into product
   code and could not carry the documents.

## The companies

Ten companies in the sectors the Transition section covers. US companies bring SEC filings and proxy
statements; EU companies bring ESEF reports.

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

Identifiers (ISIN, LEI, CIK, ticker) are looked up at build time from GLEIF and SEC EDGAR, never typed
from memory. The lookups are saved in `identifiers_source.json` (per company: the LEI record's legal name,
the SEC record's name for a CIK, the lookup date). All 10 companies must be confirmed. If one cannot be,
the builder stops and asks the owner; no company is dropped silently.

## Files in `demo/showcase/`

| File | Format | Used in |
|---|---|---|
| `companies.csv` | Universe format: `company_id,name,ticker,website,cik,lei,isin,country,sector,isic_code,fiscal_year_end`. No `regimes` column. | Argus step 1, every universe picker, loader |
| `identifiers_source.json` | The saved GLEIF and SEC lookups behind `companies.csv`. | Proof for the identifiers |
| `documents.csv` | `company_id,doc_type,reporting_year,file_name,title,source`. 14 document rows: one annual report per company (`doc_type` `10-K`, the app's "Annual report", `reporting_year` 2025, file name contains `2025`) and one proxy statement per US company (`DEF-14A`, `reporting_year` 2026, file name contains `2026`). `source` names where to get it (company investor-relations site or SEC EDGAR), no deep links. | Owner's download list, loader |
| `documents/` | Empty in git (`.gitkeep`, PDFs git-ignored). The owner saves the 14 files here. | Loader, live upload |
| `etf_dax.csv`, `etf_euro_stoxx_50.csv`, `etf_ai_big_data.csv` | The repo's `data/holdings/DAX.xlsx`, `EURO_STOXX_50.xlsx` and `AI_Big_Data.xlsx` converted to the ETF holdings CSV format the R&D Lab reads: only rows whose `Type of Security` is `Aktien` or `Equities` (cash, fund and future lines are left out), with names, ISINs and weights unchanged. Line 1 is `Source: <file name>, public ETF holdings as of <the xlsx sheet's date>`. | R&D Lab: build universe, overlap |
| `RUN_SHEET.md` | The run of show below, with every click, a fallback per scene, and the day-before checklist. | Presenter |
| `README.md` | What the pack is, the load command, and one `Source:` line per committed holdings file with its public source and as-of date. | Anyone |

## Loader

`backend/scripts/load_showcase_pack.py`, run from `backend/` with the app's environment, after
`scripts/launch_jupyter.sh up`. It prints one line per step in the preflight style,
`ok|skip|FAIL <step>: <reason>`, and exits 1 if any step is `FAIL`.

API steps call `--base-url` (default `http://127.0.0.1:8000`). When the environment variable
`ARP_SHOWCASE_TOKEN` is set they send it as `Authorization: Bearer <token>`; the user needs role `analyst`
or higher (the two approvers written by `launch_jupyter.sh users` qualify). In dev sign-in mode no token
is needed.

| Step | Does |
|---|---|
| `companies` | Registers the 10 companies in the registry with their ISIC code (`resolve_company`). |
| `universe` | Saves `companies.csv` as the saved universe "Showcase companies". |
| `portfolios` | Seeds the demo portfolios (`generate_demo_dataset`, dates relative to today), then imports the seven public files in `data/holdings/` as portfolios through the app's own constituent import, bytes unchanged: the six index files under placeholder ids (owner's choice, 12 Nov), `AI_Big_Data.xlsx` under its real fund ISIN `IE00BGV5VN51`; EUR 100 million assumed per fund. |
| `documents` | Copies every file of `documents.csv` that is present in `demo/showcase/documents/` to `<documents_dir>/<company_id>/<doc_type>/<file_name>` (setting `documents_dir`, default `data/documents`), so runs find it without the internet. Lists the missing ones. |
| `argus-capex` | Through the API: creates the extraction "Showcase: transition capex" for every company whose annual report is present, template `sch_transition_capex`, reporting year 2025, and starts it. |
| `argus-plan` | Same for "Showcase: RWE transition plan": RWE only, its annual report (which holds the sustainability statement), template `transition_plan_indicators`. |
| `voting` | Through the API: starts a proxy voting run for the US companies whose proxy statement is present. |

The three API run steps print `skip` instead of starting anything, checked in this order: `no document
present`, then `API not reachable at <url>`, then `already exists`. `--again` starts a second copy even
when one exists. `--only <step>` runs one step. Steps `companies`, `universe`, `portfolios` and `documents`
are repeatable and never skip. Step order: `companies, universe, portfolios, documents, argus-capex,
argus-plan, voting`.

The R&D Lab taxonomy is not loaded by the script: a taxonomy is drafted by the model and released by a
person, and that review is part of what the lab shows. The run sheet's day-before checklist has the
clicks (theme "Energy transition", accept, release, then a thematic universe run on "Showcase companies").

## Run of show (60 minutes)

| Minute | Workspace | Scene | Live or prepared |
|---|---|---|---|
| 0 to 12 | Argus | A1: new extraction, upload `companies.csv`, attach the RWE and NextEra reports, template "Transition capex", start. A2: open "Showcase: transition capex": values per company, click a value to see its source passage, correct one value, approve, download CSV. | A1 live, A2 prepared |
| 12 to 24 | Transition Intelligence | T1: the imported public portfolios (DAX, MSCI World, AI & Big Data) next to the seeded ones, add one monitoring rule, run last month, open the alerts. T2: RWE company page, Transition section, then one cell of the barrier matrix. | T1 live, T2 prepared (`argus-plan`) |
| 24 to 36 | R&D Lab | R1: Taxonomy Library, upload `etf_dax.csv` and `etf_euro_stoxx_50.csv` for overlap, then build a universe from the thematic `etf_ai_big_data.csv`. R2: Thematic Universe, the released "Energy transition" taxonomy on "Showcase companies": verdict and evidence per company. | R1 live, R2 prepared by hand |
| 36 to 48 | StewardIQ | S1: the proxy voting run for the four US companies: recommendation and reason per resolution. S2: trigger scan with three rows typed from the run sheet, then a client stream with the bundled example policy. | S1 prepared, S2 live |
| 48 to 60 | Argus, questions | The extraction from minute 2 is finished: show it. Off-script: an analyst names a company (single-company form, upload its report) or types what to extract. | live |

Each scene's fallback in the run sheet is the prepared run of the same kind, so a slow model call never
leaves the screen empty.

## Left to the builder

- Exact API calls for `argus-capex`, `argus-plan` and `voting` (read `api/routers/argus.py`, `voting.py`).
- How "Showcase companies" is saved so the pickers list it (`runs/_universes`).
- The three trigger-scan rows and the monitoring rule values in the run sheet; they must produce at least
  one trigger and one alert on the seeded data.
- Public ETF files, three things to prove and report rather than work around: (a) the constituent import
  takes the `data/holdings/` files unchanged; (b) the monitoring rule and monthly run of scene T1 work on
  an imported index portfolio, and if they need climate values the imported companies do not have, T1's
  alert stays on the seeded portfolios and the run sheet says so; (c) the R&D Lab overlap matches the two
  converted files (they carry ISINs and names, no tickers). If (c) fails, the builder stops and reports;
  the fallback is two public issuer CSVs with tickers that the owner downloads.
- A full reset is not built. The run sheet says how to start from an empty database with the existing
  commands.

## Acceptance

Rows are `unit` or `evaluator`: this is demo tooling outside product code, and there is no product
behaviour for a hidden test to pin.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `demo/showcase/companies.csv` | `load_company_universe` reads it | 10 companies; every one has `company_id`, `name`, `country`, `isic_code` and at least one of `isin`, `lei`, `cik`; the header has no `regimes` column | unit |
| AC-2 | `companies.csv` | each identifier is checked | every ISIN passes the ISO 6166 check digit, every LEI passes the ISO 17442 mod-97 check, every CIK is 1 to 10 digits | unit |
| AC-3 | `companies.csv` | `isic_code` is compared with the Transition section's sector prefixes | all 10 codes start with one of `351`, `201`, `241`, `2394` | unit |
| AC-4 | `companies.csv` | it is parsed by the Argus list upload parser | 10 rows returned, none without a valid-shaped ISIN, LEI or CIK | unit |
| AC-5 | `documents.csv` | it is read | 14 rows; every `company_id` is in `companies.csv`; 10 rows have `doc_type` `10-K`, `reporting_year` 2025 and a `file_name` whose only year is `2025`; 4 rows (NEE, DUK, NUE, DOW) have `doc_type` `DEF-14A`, `reporting_year` 2026 and a `file_name` whose only year is `2026`; every `file_name` ends in `.pdf` | unit |
| AC-6 | `etf_dax.csv`, `etf_euro_stoxx_50.csv` and `etf_ai_big_data.csv` | the ETF holdings parser reads each | 40 holdings for DAX, 52 for EURO STOXX 50 and 100 for AI & Big Data (the xlsx rows whose `Type of Security` is `Aktien` or `Equities`), each with the name, ISIN and weight of its xlsx row | unit |
| ~~AC-7~~ | ~~`benchmark_holdings.csv` read by the loader~~ | | Retired 12 Nov before any build: the owner dropped the StewardIQ benchmark file, no scene uses that screen | |
| AC-8 | An empty test database | the loader runs with `--only companies` twice | both runs print `ok companies: 10 registered`; the registry holds 10 companies, each with its `isic_code` | unit |
| AC-9 | An empty test database | the loader runs with `--only portfolios` twice | both runs print a line starting `ok portfolios:`; the portfolio store lists 11 portfolios (4 seeded, 7 imported from `data/holdings/`), not 18 | unit |
| AC-10 | `documents/` holds no PDF, the API is stubbed | the loader runs all steps | `documents` prints `ok documents: 0 of 14 present`, then 14 lines `  missing: <file_name>` in `documents.csv` order; `argus-capex`, `argus-plan` and `voting` each print `skip <step>: no document present`; exit code 0 | unit |
| AC-11 | One annual report present, the API not reachable | the loader runs `--only argus-capex` | prints `skip argus-capex: API not reachable at http://127.0.0.1:8000`; exit code 0 | unit |
| AC-12 | A step raises | the loader runs all steps | that step prints `FAIL <step>: <message>`, the later steps still print their lines, exit code 1 | unit |
| AC-13 | `demo/showcase/documents/` | `git check-ignore demo/showcase/documents/x.pdf` | exit code 0 (the PDF is ignored), and `.gitkeep` in that folder is tracked | unit |
| AC-14 | The e2e stack after `load_showcase_pack.py --only companies` and `--only universe` | a user opens Argus, starts a new extraction and uploads `companies.csv` | step 1 lists 10 companies, none marked "No identifier" | evaluator |
| AC-15 | Same | a user opens Taxonomy Library and uploads `etf_dax.csv` as "DAX" and `etf_euro_stoxx_50.csv` as "EURO STOXX 50" for overlap | the overlap result shows both display names and the number of shared holdings that AC-25 computes | evaluator |
| AC-16 | Same | a user opens the RWE company page | the Transition section names the sector "Power & Utilities" | evaluator |
| AC-17 | `RUN_SHEET.md` | it is read | it has the five time blocks above and 8 lines starting `Fallback A1:`, `Fallback A2:`, `Fallback T1:`, `Fallback T2:`, `Fallback R1:`, `Fallback R2:`, `Fallback S1:`, `Fallback S2:` | unit |
| AC-18 | The PR branch | `git diff --name-only origin/main...HEAD` | lists no path under `backend/arp/` or `frontend/src/` | unit |
| AC-19 | 4 proxy PDFs present in `demo/showcase/documents/`, a temporary `documents_dir` | the loader runs `--only documents` | prints `ok documents: 4 of 14 present`; each of the 4 files exists at `<documents_dir>/<company_id>/DEF-14A/<file_name>` | unit |
| AC-20 | The loader ran `--only companies` and `--only portfolios` on an empty test database | the registry's company names and the portfolio store's company names are put in one list | no name appears twice in that list | unit |
| AC-21 | `identifiers_source.json` and `companies.csv` | each LEI and CIK in `companies.csv` is looked up in the JSON | an entry exists, and its legal name equals the company's `name` once case, punctuation and the legal form (AG, Aktiengesellschaft, SE, SA, S.A., Inc, Incorporated, Corp, Corporation) are ignored | unit |
| AC-22 | One annual report present, the stubbed API reports an extraction named "Showcase: transition capex" | the loader runs `--only argus-capex` | prints `skip argus-capex: already exists` and makes 0 create calls | unit |
| AC-23 | Same as AC-22 | the loader runs `--only argus-capex --again` | makes 1 create call and prints a line starting `ok argus-capex:` | unit |
| AC-24 | `RUN_SHEET.md` | its day-before checklist is read | it contains the load command, the taxonomy steps (theme "Energy transition", accept, release, thematic run on "Showcase companies"), and a line telling the presenter to wait until `argus-capex`, `argus-plan` and `voting` show as finished, naming the screen for each | unit |
| AC-25 | `etf_dax.csv` and `etf_euro_stoxx_50.csv` | the app's overlap function compares them | the shared-holdings count equals the number of ISINs present in both files, and is at least 5 | unit |
| AC-26 | `etf_dax.csv`, `etf_euro_stoxx_50.csv`, `etf_ai_big_data.csv` | line 1 of each is read | it starts with `Source:` and contains the date of its xlsx sheet (`2026-11-02`, `2026-11-02`, `2026-11-12`) | unit |
| AC-27 | `demo/showcase/` | every file is searched | `README.md` has one line starting `Source:` for each `*.csv` holdings file in `demo/showcase/`, naming that file, and does not contain the words `invented weights` | unit |
| ~~AC-28 to AC-37~~ | ~~thematic ETF folders, loader steps `thematic` and `infer`~~ | | Retired 12 Nov before any build: the owner dropped the thematic-ETF taxonomy scene | |
| AC-38 | `RUN_SHEET.md` | it is read | it has two lines starting `Invented:`, one naming the trigger-scan rows and one naming the seeded demo portfolios | unit |
| ~~AC-39~~ | ~~`benchmark_holdings.csv` git-ignored~~ | | Retired 12 Nov with AC-7 | |
| AC-40 | An empty test database | the loader runs `--only portfolios` | one portfolio has the fund ISIN `IE00BGV5VN51`, a name starting `AI & Big Data (public ETF holdings, 2026-11-12)` and a source tag naming `AI_Big_Data.xlsx` | unit |

Must not change: product code stays untouched (AC-18).
