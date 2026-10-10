# Argus universe landing page, shared mapping and XBRL Auto routing: design

Date: 2026-10-10. Status: implemented. Builds on `2026-10-09-xbrl-pipeline-design.md` and `2026-10-09-xbrl-esef-design.md`.

## Purpose

1. One landing page for Argus where a user brings a company universe, maps it through the security master, sees what the tool already holds for each company, and then chooses a pipeline to run: the current **Extraction** pipeline or the **XBRL** pipeline, for the whole universe or for selected companies.
2. The two pipelines stay large and independent. Neither calls the other. They share only the universe file format and three read-only services: security-master mapping, availability and market routing.
3. XBRL gets an **Auto** market: the universe is screened and each company goes to the SEC or the ESEF index. The manual US/EU choice stays.

## Decisions

| Topic | Decision |
|---|---|
| Placement | A new Argus screen "Universe" (`#/argusUniverse`) is the first step of both Argus processes. Argus gets a second process, "XBRL facts". Extraction and XBRL Facts stay separate screens. |
| Extraction page | Not rewritten. Its Companies step still accepts an upload and still accepts a hand-over, which is how the landing page feeds it. |
| Hand-over | The existing universe hand-over: the chosen companies are saved as a universe file (`save_universe`) and sent with `sendUniverse`. XBRL gets a receiver like Extraction's. |
| Mapping rule | Exact identifiers only (LEI, ISIN, CIK), as the house rule says: nothing is matched by name. A company with no identifier is shown as unmapped with what to add. |
| Enrichment | Identifiers the master knows (LEI, CIK, ISIN) are filled in only where the row has none, for every routed row, and the saved universe (including the whole-universe hand-over) and the run's companies are saved enriched. Nothing is overwritten. The master holds no country, so country is never filled in. |
| Routing precedence | Home country, then ISIN prefix, then identifiers. Home country beats a CIK or LEI. |
| Unroutable | A ticker with nothing else falls back to the SEC (today's behaviour). Anything else is `unrouted` with the reason. |
| Manual switch | `market` is `auto` (default), `sec` or `esef`. `sec` and `esef` force every company, as today. |
| Mixed runs | One XBRL run covers both markets. Routing is computed when the run is created and stored with it. Resume and retry reuse it. |

## Backend: `backend/arp/universe_workbench/` (new, read-only)

- `mapping.py`
  - `MasterIndex.build(idmap: IdentifierMapStore, *, on: str | None = None)`: reads the identifier map once into `(scheme, normalised value) -> issuer keys` and `issuer key -> rows`, honouring `valid_from` / `valid_to`.
  - `map_company(company, index) -> Mapping` with `status` (`mapped`, `ambiguous`, `unmapped`, `no_identifier`), `issuer_key`, `key_scheme`, `identifiers` (the master's LEI, CIK, ISIN for that issuer) and `candidates` for ambiguous. Same semantics as `schemas.issuer.issuer_key` (LEI, then ISIN, then CIK; exactly one issuer wins); a test pins the two together.
  - `enrich(company, mapping) -> CompanyRef`: fills missing `lei`, `cik`, `isin` when the issuer has exactly one value for that scheme.
- `routing.py` (pure, no network)
  - `route_company(company, index) -> Route` with `market` (`sec`, `esef`, `None`), `status` (`routed`, `no_source`, `unrouted`), `basis` (`country`, `isin_prefix`, `cik`, `lei`, `master`, `ticker_fallback`) and `detail`.
  - Rules, first match wins:
    1. `country` in the table below: US gives SEC; EU, EEA and UK give ESEF. A country string outside the table is ignored and noted, never a decision.
    2. ISIN prefix, only when the ISIN matches `^[A-Z]{2}[A-Z0-9]{9}[0-9]$` (after strip and upper-case; a malformed ISIN is ignored and noted): `US` gives SEC; the EU, EEA and `GB` prefixes give ESEF; `XS` and `EU` carry no country and are ignored; any other two-letter prefix gives `no_source` ("no XBRL source for <prefix> yet"), but only when the company has no CIK, on the row or from the master (a CIK means the SEC is a source after all).
    3. `cik` gives SEC. `lei` gives ESEF, but only when there is no `cik`.
    4. Nothing routed: map through the master (`map_company`), enrich, and run rules 1 to 3 once more on the enriched company (basis `master`). A `no_source` from the row's own identifiers yields to a routed result from the master.
    5. Still nothing: a ticker gives SEC (`ticker_fallback`); otherwise `unrouted` with "no country or identifier: add an ISIN, LEI or CIK, or load it into the security master".
  - Country table: US; EU27 (AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE); EEA (IS LI NO); UK (GB). Each matches by ISO alpha-2, alpha-3 and English name, case-insensitively ("United Kingdom", "UK", "Great Britain", "USA", "United States of America" included).
  - `route_universe(companies, index) -> list[Route]`.
- `availability.py`: `availability(companies, *, run_store, content_store, xbrl_store, documents_dir) -> dict[company_id, Availability]`, each part indexed in one pass, not per company:
  - identity: the latest `identity` run result for the company (verdict, resolved CIK/website, run id);
  - documents: `readiness_by_company` plus files on disk (the logic behind `POST /api/documents/readiness`, reused, not copied);
  - extraction: runs of types `extraction`, `financials`, `tnfd`, `transition_plan` that contain the company (count, last run id and date);
  - XBRL: files by company id (market, key, fact count, fetched date, report stored).
- API `POST /api/universe/workbench` (new router, same `authorize` dependency): body `{companies | universe_path, availability: bool = true}`; response rows `{company (enriched), mapping, route, availability}` plus counts per route and per mapping status. With `availability: false` (the XBRL page's routing preview) the store scans are skipped and each row's availability is null. A `universe_path` must resolve inside `runs_dir/_universes` (else 400); an empty saved universe gives 400 "Universe file is empty."; more than 10,000 companies gives 400.

## XBRL changes

- `market` is `auto | sec | esef`, default `auto`, on `arp xbrl fetch` and on `POST /api/xbrl/runs`.
- `create_xbrl_run` for `auto` calls `route_universe`, stores the result as `routing.json` in the run directory (company id, market, status, basis, detail, enriched company) and stores the enriched companies as the run's companies. `routing.json` is created from the stored companies if missing.
- `execute_xbrl_run` for `auto` fetches each company by its stored route, using the stored (enriched) company from `routing.json`. A company missing from `routing.json` gets `unrouted` with "not in stored routing". Companies with status `no_source` or `unrouted` get a result row with that status and a `note`; they count as completed and fetch nothing.
- `CompanyStatus.status` gains `no_source` and `unrouted`; `CompanyStatus` gains `note: str | None`; `CompanyStatus.market` may be `None`.
- New `arp xbrl screen --universe f.csv`: prints the routing table (company, market, basis, detail) and the counts. Read-only.

## Frontend

- New page `frontend/src/pages/ArgusUniverse.tsx` (id `argusUniverse`, label "Universe"), registered in `App.tsx` (`TABS`, lazy import, "Workspaces" group neighbours as the Argus screens do) and in the Argus workspace `screens`.
  - Universe: the existing `UniversePicker` (upload or saved universe).
  - Table, one row per company: mapping status and issuer id; the master's LEI, CIK, ISIN; suggested route with its reason; availability columns (identity, documents with types and last seen, extraction runs, XBRL files). Tick boxes select companies; "all" selects the whole universe.
  - Hand-over: "Extraction" and "XBRL facts" buttons with scope "whole universe" or "selected (n)". The companies are saved enriched (`api.universeFromCompanies`) and sent with `sendUniverse`.
- XBRL Facts page: receives a hand-over like Extraction (`pendingUniverse`); the market control becomes Auto (default), US, EU. With Auto, the Fetch area shows the routing counts from the workbench endpoint before "Start fetch"; US and EU skip them. Status text covers `no_source` and `unrouted` with their note.
- `processes.ts`: the Argus process "Extract and score" gets a first step "Universe" (the landing page); a new process `xbrl`, "XBRL facts" (steps: Universe, Fetch, Facts, Verify), `run: undefined`, run type `xbrl_fetch` (added to the workspace's `runTypes`). `processes.test.ts` is updated for the new process id.
- Docs: `docs/PROCESS_VIEW.md` (workspace and process tables, the landing page, the security-master paragraph), `README.md` function table, `docs/TECHNICAL_REFERENCE.md` (module map and a section for the workbench).

## Errors and limits

- A missing or empty security master maps nothing; every company shows `no_identifier` or `unmapped`, routing falls back to rules 1 to 3 and 5. Not an error.
- An identifier that points at two issuers gives `ambiguous` with the candidates; it is not enriched and not used for routing rule 4.
- Availability reads existing stores only; nothing is created or changed. Its cost grows with the number of stored runs and documents; `# ponytail:` marks the one-pass scans so an index can replace them if the stores grow.
- The landing page never starts a run itself; it only hands a saved universe to the pipeline's own screen.

## Out of scope

- Rewriting the Extraction page or its Identify step.
- Name or ticker matching against the security master; extra identifier columns (CUSIP, SEDOL, FIGI, PermID) on the universe.
- Country enrichment, and regimes beyond SEC and ESEF (UK is routed to the ESEF index only because filings.xbrl.org carries UK filings).
- Changes to the security master or its load process.

## Testing

- Routing: table-driven tests for every rule and conflict (CIK + EU country gives ESEF; CIK + LEI without country gives SEC; LEI only gives ESEF; `XS` ISIN ignored; Japanese ISIN gives `no_source`; unrecognised country ignored with a note; ticker fallback; unrouted reason; master enrichment then re-route; ambiguous master).
- Mapping: parity test between `map_company` and `schemas.issuer.issuer_key` on one fixture; enrichment never overwrites.
- Availability: fixtures for each store; companies with nothing stored.
- XBRL: a mixed `auto` run with fake sources (one SEC, one ESEF, one `no_source`, one `unrouted`), `routing.json` reused on resume and retry, `market="sec"`/`"esef"` still force everything.
- API: the workbench endpoint, including the `universe_path` containment check; CLI `screen`.
- Frontend: lint, build and unit tests for the new helpers and `processes.ts`; a screenshot of the landing page with seeded data.
- No test calls the network.
