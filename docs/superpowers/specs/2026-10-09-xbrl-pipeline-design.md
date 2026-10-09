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

## What already exists and is reused

- `ingestion/xbrl.py`: `XbrlFactSource.fetch_company_facts`, `resolve_cik`, `fact_for_tags`, the `_REVENUE_TAGS` and `_CAPEX_TAGS` fallback lists.
- `ingestion/edgar.py`: User-Agent, request delay, ticker-to-CIK map.
- `schemas.common.CompanyRef`: already carries `cik`, `ticker`, `lei`, `country`.
- `ingestion/esef.py`: iXBRL parser (`parse_ixbrl`). It drops hidden and dimensional facts. Used by the EU adapter later, not here.

Not changed: `extraction/*`, `ingestion/xbrl.py`, `ingestion/esef.py`.

## Flow

```
company list -> 1 FETCH -> 2 EXTRACT ALL -> 3 REQUIRED -> 4 SELECT
 (CompanyRef)   raw JSON    every fact        revenue,      named subset
                + sha256    as a flat row     capex
```

New package: `backend/arp/xbrl_pipeline/`. New CLI group: `backend/arp/cli/xbrl.py`, registered in `cli/__init__.py`.

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

### 4. Select

- `arp xbrl tags` lists all available concepts across the company list, with counts.
- `arp xbrl select --name <n> --tags A,B,C` writes `data/xbrl/selections/<n>.jsonl`: the facts for those concepts across the company list.
- A selection is a named file, so it can be re-run and read by later processing.

## Batch behaviour

`XbrlFactSource._company_facts` has no retry, no pacing, and a 7-day cache. The new pipeline wraps it rather than changing it.

- Companies are fetched one at a time with the existing EDGAR delay (below the SEC limit of 10 requests per second).
- 429 and 5xx responses are retried 3 times with backoff. A 404 is final.
- Per-company status: `ok`, `unchanged`, `no_cik`, `not_found`, `error`. Written to `status.jsonl` in the run folder. One failure never stops the batch.
- A re-run retries only the companies that failed or were not reached.
- `--refresh` builds the source with `ttl_hours=0` to bypass the cache.

## CLI

| Command | Does |
|---|---|
| `arp xbrl fetch --universe <file> [--refresh]` | Steps 1 to 3 |
| `arp xbrl tags [--universe <file>]` | Lists available concepts |
| `arp xbrl select --name <n> --tags A,B,C` | Step 4 |
| `arp xbrl verify <run_id> [--tolerance 0.005]` | Compares an extraction run with the stored revenue and capex |

## Verify

Purpose: prove the LLM extraction against the filer's own tagged values.

- **Guard.** Refuses a run whose `step_settings.json` shows `xbrl_facts_enabled` on, or ESEF on. Such a run copied XBRL, so a comparison would be circular. The error says to re-run with both off.
- **Inputs.** `runs/<run_id>/results.jsonl` rows. `ExtractedField` carries `field_id`, `canonical_value`, `canonical_unit` and `period_end`. Mapping a run's revenue and capex fields to the metrics, and the exact row nesting, are confirmed when the plan is written (open item).
- **Outcomes** per company, year and metric: `match`, `mismatch`, `missing_in_run`, `missing_in_xbrl`. Values match within a relative tolerance, default 0.5%, units normalised first.
- **Output.** `runs/<run_id>/xbrl_verify.jsonl` plus a one-screen summary: counts per outcome and the mismatches listed.

## Known limits

- `companyfacts` has no dimensional facts (segment, region) and no text blocks. These come from the per-filing iXBRL parse in the EU step, which can then be re-run on US filings.
- Non-US filers have no `companyfacts`. They are covered by the later adapters.
- Revenue and capex tagging varies between filers. A filer that uses a concept outside the fallback lists shows `not_found`, never a guess.

## Testing

One small `companyfacts` fixture and tests that cover:

1. extract-all (row count and fields),
2. required resolution (winning concept, `not_found` case),
3. select (subset file),
4. batch handling with a stubbed HTTP layer: 429 then success, 404, unchanged sha,
5. `verify`: match, mismatch, missing, and the circular-run guard.

## Later sub-projects (not in this spec)

EU (ESEF via `filings.xbrl.org`), UK (Companies House iXBRL), Japan (EDINET, classic XBRL). Each gets its own spec, plan and build.
