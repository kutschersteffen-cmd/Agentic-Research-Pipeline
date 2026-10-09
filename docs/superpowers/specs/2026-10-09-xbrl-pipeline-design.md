# XBRL fact pipeline: design

Date: 2026-10-09. Status: draft for review. Scope: sub-projects 0 (core) and 1 (US / SEC).

## Purpose

1. Download the XBRL-tagged reports of a list of companies and keep the originals.
2. Extract every available tagged fact into one common format.
3. Always resolve revenue and capex.
4. Let a user pick, from all available tags, the subset to pass on.
5. Serve as an independent answer key to prove the LLM extraction pipeline.

## Decisions taken in brainstorming

| Topic | Decision |
|---|---|
| Markets | All markets with XBRL tagging, built as a shared core plus one adapter per regime. Order: core + US, then EU (ESEF), UK, Japan. This spec covers core + US only. |
| Approach | `companyfacts` now. Per-filing iXBRL later (needed for segment/region splits and text blocks). |
| Storage | Files, in the repo's existing file-based layout. No database is required and the README's "no database required" stays as is. |
| Required items | Revenue and capex. |
| Relation to extraction | Separate. The extraction pipeline is not modified. The new store is an answer key and a tag catalogue only. |
| Standing | Its own function in the repo (added to the README function table), not a mode of Data-Point Extraction. |
| User control | The user explicitly chooses what is extracted: everything (default) or a chosen set of tags, at fetch time or afterwards. |
| Surfaces | CLI, API and a frontend page, all sharing one code path. |
| Tag list | The tag dropdown offers every tag that exists in the official taxonomies (`us-gaap`, `ifrs-full`, `dei`), not only tags found in fetched reports. Company-specific extension tags are added as they are seen. Other taxonomies arrive with their market adapters. |

## What already exists and is reused

- `ingestion/xbrl.py`: `XbrlFactSource.fetch_company_facts`, `resolve_cik`, `fact_for_tags`, the `_REVENUE_TAGS` and `_CAPEX_TAGS` fallback lists.
- `ingestion/edgar.py`: User-Agent, request delay, ticker-to-CIK map.
- `schemas.common.CompanyRef`: already carries `cik`, `ticker`, `lei`, `country`.
- `ingestion/esef.py`: iXBRL parser (`parse_ixbrl`). It drops hidden and dimensional facts. Used by the EU adapter later, not here.

Not changed: `extraction/*`, `ingestion/esef.py`. `ingestion/xbrl.py` gains only an additive public surface: the constants `REVENUE_TAGS` and `CAPEX_TAGS` and the method `XbrlFactSource.fetch_company_facts_raw`, which returns the parsed JSON together with the served bytes so the original can be stored as served.

## Flow

```
company list -> 1 FETCH -> 2 EXTRACT ALL -> 3 REQUIRED -> 4 SELECT
 (CompanyRef)   raw JSON    every fact        revenue,      named subset
                + sha256    as a flat row     capex
```

New package: `backend/arp/xbrl_pipeline/` (the only place with logic). The CLI, API and frontend are thin layers over it:

- CLI group `backend/arp/cli/xbrl.py`, registered in `cli/__init__.py`.
- API router `backend/arp/api/routers/xbrl.py`, included in `api/main.py` with the same `authorize` dependency as the other routers.
- Frontend page `frontend/src/pages/XbrlFacts.tsx`, lazy-loaded in `App.tsx`, with calls added to `frontend/src/api/client.ts`.

### Run model

A fetch is a run, recorded in `RunStore` like discovery runs (`create_*_run`, manifest, `results.jsonl`). The per-company status rows (see Batch behaviour) are that run's `results.jsonl`, so run history, progress polling and re-run of failures work the way they do for the other functions.

### Selecting what is extracted

The user chooses one of two modes, in the CLI, API or page:

| Mode | Effect |
|---|---|
| **All** (default) | Every fact is written to `facts.jsonl`. |
| **Selected tags** | Only facts whose concept is in the chosen set are written to `facts.jsonl`. |

In both modes the original document is stored in full and `catalog.json` lists every concept, so the choice is never lossy. Revenue and capex (step 3) are resolved in both modes. Step 4 (select) reads the stored originals, not `facts.jsonl`, so a new selection can be cut at any time, including after a fetch that used a different one, with no new download.

### 1. Fetch

- Resolve each company's CIK (`CompanyRef.cik`, else ticker lookup). No CIK gives status `no_cik`.
- Download the `companyfacts` JSON through `XbrlFactSource.fetch_company_facts`.
- Save the original bytes as `data/xbrl/<cik10>/companyfacts-<sha16>.json`.
- If the sha equals the previous run's, status is `unchanged` and steps 2 and 3 are skipped for that company.

### 2. Extract all

Every fact in the JSON becomes one row in `data/xbrl/<cik10>/facts.jsonl`:

| Field | Source |
|---|---|
| company_id, cik | company list |
| taxonomy, concept | JSON path (e.g. `us-gaap`, `Revenues`) |
| unit, value | row `val`, unit key |
| period_start, period_end | row `start`, `end` |
| fiscal_year, fiscal_period | row `fy`, `fp` |
| form, filed, accession | row `form`, `filed`, `accn` |
| source_sha | sha of the stored original |

`data/xbrl/<cik10>/catalog.json` lists every concept the company uses, with a fact count, the years covered and the label from the JSON.

Nothing is filtered at this step.

### 3. Required: revenue and capex

- Uses the existing fallback lists in `ingestion/xbrl.py`, because filers tag these differently.
- Output: `data/xbrl/<cik10>/required.jsonl`, one row per company, fiscal year and metric, holding the winning concept, value, unit and period.
- If no concept matches, the row has status `not_found`. Nothing is guessed or estimated.

### Tag registry

The list of selectable tags is independent of any fetched report.

- **Source.** The official taxonomies: `us-gaap` (FASB), `ifrs-full` (IFRS Foundation, used by ESEF and by foreign filers on the SEC) and `dei` (cover-page facts). The exact taxonomy files and their URLs are confirmed when the plan is written. Other taxonomies (UK, Japan, ...) are added with their market adapters.
- **Storage.** A snapshot per taxonomy and year in `data/xbrl/taxonomy/<taxonomy>-<year>.jsonl`, one row per tag: concept name, label, data type, period type (instant or duration), balance (debit or credit), documentation text and a deprecated flag. Built by `arp xbrl taxonomy update`, never at page load.
- **Extension tags.** A company's own tags (for example `xyz:CustomRevenue`) are not in any standard taxonomy. They are added to the registry from `catalog.json` as fetches see them, marked as extensions.
- **Seen counts.** Each registry tag carries the number of fetched companies that use it, computed from the `catalog.json` files. A tag nobody has used shows 0, so a selection that will return nothing is visible before you run it.
- **Search.** Server-side, by name or label, with filters for taxonomy, extension, seen-only and deprecated. Revenue and capex tags are pinned at the top of an empty search.

### 4. Select

- `arp xbrl tags` lists tags from the tag registry (see below), with how many fetched companies use each.
- `arp xbrl select --name <n> --tags A,B,C` writes `data/xbrl/selections/<n>.jsonl`: the facts for those concepts across the company list.
- A selection is a named file, so it can be re-run and read by later processing.

## Batch behaviour

`XbrlFactSource._company_facts` has no retry, no pacing, and a 7-day cache. The new pipeline wraps it rather than changing it.

- Companies are fetched one at a time with the existing EDGAR delay (below the SEC limit of 10 requests per second).
- 429 and 5xx responses are retried 3 times with backoff. A 404 is final.
- Per-company status: `ok`, `unchanged`, `no_cik`, `not_found`, `error`. Written as the run's `results.jsonl` rows. One failure never stops the batch.
- A re-run retries only the companies that failed or were not reached.
- `--refresh` builds the source with `ttl_hours=0` to bypass the cache.

## CLI

| Command | Does |
|---|---|
| `arp xbrl fetch --universe <file> [--tags A,B,C] [--refresh]` | Steps 1 to 3. Without `--tags`, mode All. |
| `arp xbrl taxonomy update` | Builds or refreshes the tag registry snapshots |
| `arp xbrl tags [--search <text>] [--taxonomy <t>] [--seen-only]` | Lists registry tags with seen counts |
| `arp xbrl select --name <n> --tags A,B,C` | Step 4 |
| `arp xbrl verify <run_id> [--tolerance 0.005]` | Compares an extraction run with the stored revenue and capex |

## API

Router prefix `/api/xbrl`, authorised like the other routers.

| Endpoint | Does |
|---|---|
| `POST /runs` | Start a fetch. Body: companies (or a universe), optional `tags`, `refresh`. Returns `run_id`. |
| `GET /runs/{id}` and `GET /runs/{id}/results` | Manifest and per-company status rows, paged. |
| `GET /tags?q=&taxonomy=&seen_only=&offset=&limit=` | Registry tags matching the search, paged, each with its seen count. The page never receives the whole list. |
| `POST /taxonomy/update` | Rebuilds the registry snapshots. |
| `PUT /selections/{name}`, `GET /selections`, `GET /selections/{name}/facts` | Save, list and read named selections. |
| `GET /required` | Revenue and capex rows for a run or a universe. |
| `POST /verify` | Body: extraction `run_id`, optional tolerance. Returns the outcomes, or the circular-run error. |

Name and company identifiers are validated with `safe_id`, as in `routers/documents.py`.

## Frontend page

`XbrlFacts`, one page with four areas:

1. **Fetch.** Choose companies (the existing universe), choose All or Selected tags, optional refresh, start. A status table shows `ok`, `unchanged`, `no_cik`, `not_found` and `error` per company, with a retry-failed action.
2. **Tags.** A searchable multi-select dropdown (combobox) over the whole tag registry. Options load from `GET /tags` as the user types, so tens of thousands of tags stay fast. Each option shows label, concept name, taxonomy and seen count. Filters: taxonomy, extension, seen-only. Chosen tags appear as removable chips. The chosen set is saved by name or used for the next fetch. It is keyboard-operable and announces result counts to screen readers.
3. **Required.** Revenue and capex per company and year, with the winning concept shown and `not_found` marked in text.
4. **Verify.** Choose an extraction run and see match, mismatch and missing counts, with the mismatches listed. A circular run shows the guard message in plain text.

The page follows `DESIGN.md` and `PRODUCT.md` and the repo's accessibility conventions (labelled inputs, errors stated in text and not only by colour, 3:1 field borders, touch-sized controls). Design work in the plan uses the impeccable and ui-ux-pro-max skills.

## Verify

Purpose: prove the LLM extraction against the filer's own tagged values.

- **Guard.** Refuses a run whose `step_settings.json` is missing or shows `xbrl_facts_enabled` on. That flag also gates ESEF facts in the extraction pipeline, so one check covers both. Such a run copied XBRL, so a comparison would be circular. The error says to re-run with it off.
- **Inputs.** `runs/<run_id>/results.jsonl` rows of the generic extraction pipeline (`ExtractionRecord`: `company_id` and `fields[]`, each with `field_id`, `canonical_value`, `canonical_unit`, `period_end`). The user maps revenue and capex to the run's `field_id`s (`revenue=<field_id>`, `capex=<field_id>`). Runs of the financials profile (`CompanyFinancialsRecord`) are out of scope for now.
- **Outcomes** per company, year and metric: `match`, `mismatch`, `missing_in_run`, `missing_in_xbrl`. Values match within a relative tolerance, default 0.5%, units normalised first.
- **Output.** `runs/<run_id>/xbrl_verify.jsonl` plus a one-screen summary: counts per outcome and the mismatches listed.

## Known limits

- Taxonomies change each year: tags are added, renamed and deprecated. A snapshot is per year, and facts match tags by concept name. A deprecated tag stays selectable, marked as deprecated, because older filings still use it.
- `companyfacts` has no dimensional facts (segment, region) and no text blocks. These come from the per-filing iXBRL parse in the EU step, which can then be re-run on US filings.
- Non-US filers have no `companyfacts`. They are covered by the later adapters.
- Revenue and capex tagging varies between filers. A filer that uses a concept outside the fallback lists shows `not_found`, never a guess.

## Testing

One small `companyfacts` fixture and tests that cover:

1. extract-all (row count and fields),
2. required resolution (winning concept, `not_found` case),
3. select (subset file),
4. batch handling with a stubbed HTTP layer: 429 then success, 404, unchanged sha,
5. `verify`: match, mismatch, missing, and the circular-run guard,
6. selection modes: a fetch with `--tags` writes only those concepts to `facts.jsonl` but still stores the full original, and a later `select` for other tags works with no download,
7. API: the endpoints above through FastAPI's test client, including `safe_id` rejection,
8. tag registry: a small taxonomy fixture builds a snapshot, search and paging return the expected tags, seen counts follow `catalog.json`, extension tags are added and marked, a never-used tag shows 0,
9. frontend: the page's behaviour tests in the repo's existing frontend test style (to be confirmed in the plan), and the type check and lint the repo already runs.

## Documentation

Add the function to the README function table and to `docs/TECHNICAL_REFERENCE.md`, stating its separation from Data-Point Extraction and the `verify` guard.

## Later sub-projects (not in this spec)

EU (ESEF via `filings.xbrl.org`), UK (Companies House iXBRL), Japan (EDINET, classic XBRL). Each gets its own spec, plan and build.
