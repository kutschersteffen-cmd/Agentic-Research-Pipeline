# Themes exposure layers (direct and value chain)

Date: 2026-10-18
Status: draft for owner approval
Parent: `docs/superpowers/plans/2026-10-15-themes-lane-addon-3-layer-exposure.md` (the owner's add-on and its reconciliation). The owner asked for the spec without a question round; every call below marked **my call** is open to change at approval.

## Intent

A theme run already says which companies are exposed to a theme and, where a revenue number exists, how much. It cannot see the companies one step up the value chain: the supplier whose biggest customer is a pure-play. This spec adds that view. For each company in a theme run, plus every supplier that sells to them, it shows three layers and one combined score:

- **Layer 1, direct:** the company's own revenue share in the theme.
- **Layer 2, value chain:** revenue the company earns from customers that have Layer 1 exposure, one or two hops away, decayed per hop.
- **Layer 3, macro and adopters:** shown as "not available". No data source exists yet.
- **Score `S`:** a weighted sum of the layers.

The score orders companies only where the data supports it. A company with no evidence on any layer is listed as `insufficient data`, never ranked.

## Scope

- **Supply edges:** a new Postgres table of supplier-to-customer edges, keyed by issuer key, each with a revenue share, a cited source passage, the date the relationship held (`effective_date`) and the date it became public (`published_at`). Filled by CSV import (`arp theme edges import`).
- **Layers computation:** for a theme run and an `as_of` date, compute Layer 1, Layer 2 and `S` per company. Exposed through `arp theme layers` and `GET /api/themes/runs/{run_id}/layers`.
- **Screen:** a "Layers" table on the existing Thematic Universe page (`#/theme`) for the selected run, with an `As of` date input that defaults to today (UTC).

## My calls (owner to confirm with the acceptance table)

1. **The formula.** The add-on's `S_i` equation did not arrive, and its two weight sets disagree. Until the owner supplies the formula:
   - `S = w1·L1 + w2·L2 + w3·L3`, with a missing layer counted as 0. Defaults: `w1 = 0.45`, `w2 = 0.35`, `w3 = 0.20` (the add-on's text), hop decay `γ = 0.85`, at most 2 hops.
   - These five values are settings: `ARP_THEME_LAYER_W1`, `ARP_THEME_LAYER_W2`, `ARP_THEME_LAYER_W3`, `ARP_THEME_LAYER_DECAY`, `ARP_THEME_LAYER_MAX_HOPS`. Each weight must be 0 or more, the decay greater than 0 and at most 1, and max hops 1 or 2. Any other value is a configuration error: the API does not start and `arp theme layers` exits 1, each with a message naming the setting. Every response states the values it used.
   - The weights are not renormalised when a layer is missing, so `S` stays comparable across companies; with Layer 3 always missing, the highest possible `S` is 0.80.
2. **Layer 1** is the highest revenue share among the company's matches in the run with verdict `include` whose revenue exposure came from the catalogue or from grounded extraction (`revenue_exposure.revenue.source` is `catalogue` or `extracted`). Qualitative or unresolved revenue gives no Layer 1 number.
3. **Pure-play** uses the existing setting `ARP_REVENUE_EXPOSURE_PURE_PLAY_THRESHOLD` (default 0.5), so "pure-play" means the same here as in the theme run's existing results. A company is a pure-play when `L1 ≥` that value.
4. **Edges and their versions.** An edge is one row per `(supplier_key, customer_key, effective_date, published_at)`; re-importing an identical row adds nothing, and a row with the same four values but a different `revenue_share`, `source_doc` or `source_passage` is refused, because a correction must carry a new `published_at`. The import does not check keys against the registry or the run: a supplier needs no row in `companies`. Edges are not merged or overwritten: a correction is a new row with a later `published_at`. For each supplier-customer pair, the version used at `as_of` is the row known at `as_of` (`effective_date ≤ as_of` and `published_at ≤ as_of`) with the latest `effective_date`, and among those the latest `published_at`. A supplier's shares to different customers may add up to more than 1; the import does not check that.
5. **Layer 2** for supplier `s` sums, over every path of 1 to `max_hops` edges from `s` to a company `a` in the run with a Layer 1 number, `(product of the edge revenue shares along the path) × L1(a) × γ^(edges in path)`, capped at 1. A path never visits the same company twice, so a loop cannot feed a company's own exposure back to it. A company with no such path has `L2` null.
6. **Via** is the single path with the highest contribution; on a tie, the path whose list of issuer keys sorts first.
7. **Who is listed:** every company in the run, plus every supplier with a non-null `L2`. Order: `S` descending, then issuer key ascending; companies with all layers null come last with `status = insufficient data` and no rank.
8. **Names:** a run company's name is its name in the run; a supplier outside the run takes `supplier_name` from the edge version used.
9. **Edges come from CSV only** in this release. Extracting major-customer disclosures from filings with the LLM is the next item, and it must cite passages the same way.
10. **Identity** is the issuer key from `arp.schemas.issuer.issuer_key` (registry UUID first). The edge CSV has no ticker column; tickers stay attributes only.
11. **Computed on read**, not stored: the layers are a pure function of the run, the edge table, the settings and `as_of`, so there is no new run type and no recompute step.

## Not in this spec

- Layer 3 data (interconnection queues, capex, adopters): no source identified.
- LLM extraction of supply edges from filings.
- The four research replications (THEME, FinDKG, FundaPod, LLM Black-Litterman), the analyst/skeptic/auditor agents and LangGraph.
- The Thematic Bubble Indicator, the CVXPY optimiser and any portfolio weights.
- Neo4j, Qdrant, Elasticsearch; broker execution, direct indexing.
- Publishing `S` into Decision Studio. The layer columns can be joined into a Decision Studio dataset later; Decision Studio rules cannot walk a graph, so the layers are computed here.

## Acceptance

Setup notes for the test-writer:
- The edge table, the theme run and the API share the Postgres database at `ARP_POSTGRES_DSN` and the runs directory at `ARP_RUNS_DIR`.
- A theme run is created through `RunStore(dsn, runs_dir)`: `save_manifest(RunManifest(run_id=R, run_type="theme"))`, `save_companies(R, [CompanyRef(company_id=..., entity_id=<uuid>, name=...)])`, and one `append_result(R, {"_key": <company_id>, "company_matches": [CompanyMatch.model_dump(mode="json"), ...]})` per company. Each `entity_id` must first exist as a row of the `companies` table (`arp.db.models.Company`). A company's issuer key is `issuer_key(CompanyRef)[0]`, which is the `entity_id` as a string.
- **Fixture F** (used by many rows):
  - Run `R` with companies A, B and C (names `A`, `B`, `C`), each with one match with verdict `include`:
    - A: `revenue_exposure.revenue = {value_pct: 0.60, source: "catalogue"}`
    - B: `revenue_exposure.revenue = {value_pct: 0.25, source: "extracted"}`
    - C: `revenue_exposure.revenue = {value_pct: null, source: "qualitative"}`
  - Edge CSV with two rows: S1 (name `S1`) supplies A with `revenue_share` 0.40; S2 (name `S2`) supplies S1 with `revenue_share` 0.50. Both have `effective_date` 2023-12-31 and `published_at` 2024-03-01, a `source_doc` and a non-empty `source_passage`. S1 and S2 are not in the run.
  - Default settings.
- S1, S2, S3, T1, T2 and X have no row in `companies`; their keys are fresh UUID strings.
- "Dates as F" means `effective_date` 2023-12-31 and `published_at` 2024-03-01.
- Edge CSV columns, in this order: `supplier_key, supplier_name, customer_key, customer_name, revenue_share, source_doc, source_passage, effective_date, published_at`. Dates are `YYYY-MM-DD`. In import messages, `row n` is the n-th data row; the header is not counted.
- `GET /api/themes/runs/{run_id}/layers` returns `{run_id, as_of, weights: {w1, w2, w3}, decay, max_hops, pure_play_threshold, rows}`. Each element of `rows` has the keys `issuer_key, name, in_run, l1, l2, l3, score, pure_play, status, rank, l2_via`. `l2_via` is a list of issuer keys from the supplier to the anchor company, or null when `l2` is null. "X's row" means the element whose `issuer_key` is X's issuer key.
- Every value is computed from unrounded inputs; only numbers in API responses are rounded, to 4 decimal places with Python's `round`. The CLI prints numbers with exactly 4 decimals and a missing value as `-`.
- Roles: the GET endpoint accepts any signed-in user (`viewer` and up). Holdout tests run the app with `ARP_AUTH_MODE=local`.

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | Fixture F's edge CSV | `arp theme edges import --csv <file>` | Exit 0, stdout `2 rows, 2 new` | holdout |
| AC-2 | AC-1 just happened | The same import again | Exit 0, stdout `2 rows, 0 new` | holdout |
| AC-3 | A one-row edge CSV with an empty `source_passage` | `arp theme edges import --csv <file>` | Exit 1, stderr contains `row 1: source_passage is required` | holdout |
| AC-34 | A two-row edge CSV: row 1 valid, row 2 with an empty `source_passage` | `arp theme edges import --csv <file>`, then importing a file with only that valid row | The first import exits 1 with stderr containing `row 2: source_passage is required`; the second prints `1 rows, 1 new` | holdout |
| AC-4 | An edge CSV row with `revenue_share` 1.5 | `arp theme edges import --csv <file>` | Exit 1, stderr contains `row 1: revenue_share must be greater than 0 and at most 1` | holdout |
| AC-5 | An edge CSV row whose `supplier_key` equals its `customer_key` | `arp theme edges import --csv <file>` | Exit 1, stderr contains `row 1: a company cannot supply itself` | holdout |
| AC-6 | An edge CSV whose header lacks `published_at` | `arp theme edges import --csv <file>` | Exit 1, stderr contains `missing column: published_at` | holdout |
| AC-7 | Fixture F imported; signed in as a `viewer` | `GET /api/themes/runs/R/layers?as_of=2024-06-30` | 200. `weights` = `{"w1": 0.45, "w2": 0.35, "w3": 0.2}`, `decay` = 0.85, `max_hops` = 2, `pure_play_threshold` = 0.5, `as_of` = `2024-06-30` | holdout |
| AC-8 | Fixture F imported | `GET .../layers?as_of=2024-06-30` | `[r["issuer_key"] for r in rows]` = [A, B, S1, S2, C] | holdout |
| AC-9 | Fixture F imported | `GET .../layers?as_of=2024-06-30` | A's row: `name` = `A`, `in_run` = true, `l1` = 0.6, `l2` = null, `l3` = null, `score` = 0.27, `pure_play` = true, `status` = `scored`, `rank` = 1, `l2_via` = null | holdout |
| AC-10 | Fixture F imported | `GET .../layers?as_of=2024-06-30` | B's row: `l1` = 0.25, `score` = 0.1125, `pure_play` = false, `rank` = 2 | holdout |
| AC-11 | Fixture F imported | `GET .../layers?as_of=2024-06-30` | S1's row: `name` = `S1`, `in_run` = false, `l1` = null, `l2` = 0.204, `score` = 0.0714, `rank` = 3, `l2_via` = [S1's key, A's key] | holdout |
| AC-12 | Fixture F imported | `GET .../layers?as_of=2024-06-30` | S2's row: `l2` = 0.0867, `score` = 0.0303, `rank` = 4, `l2_via` = [S2's key, S1's key, A's key] | holdout |
| AC-13 | Fixture F imported | `GET .../layers?as_of=2024-06-30` | C's row: `l1` = null, `l2` = null, `l3` = null, `score` = null, `status` = `insufficient data`, `rank` = null | holdout |
| AC-14 | Fixture F imported | `GET .../layers?as_of=2024-02-01` (before `published_at`) | `[r["issuer_key"] for r in rows]` = [A, B, C] | holdout |
| AC-15 | Fixture F, but the S1→A row has `effective_date` 2024-08-31 | `GET .../layers?as_of=2024-06-30` | `[r["issuer_key"] for r in rows]` = [A, B, C] | holdout |
| AC-16 | Fixture F plus edge S3 supplies S2 (`revenue_share` 0.9, dates as F) | `GET .../layers?as_of=2024-06-30` | No row has S3's issuer key (its only path to A has 3 edges) | holdout |
| AC-35 | Fixture F with `ARP_THEME_LAYER_MAX_HOPS=1` | `GET .../layers?as_of=2024-06-30` | `max_hops` = 1, and `[r["issuer_key"] for r in rows]` = [A, B, S1, C] | holdout |
| AC-17 | Fixture F plus edge S1 supplies B (`revenue_share` 0.20, dates as F) | `GET .../layers?as_of=2024-06-30` | S1's row: `l2` = 0.2465, `score` = 0.0863, `l2_via` = [S1's key, A's key] | holdout |
| AC-18 | A run with company D (include, catalogue 1.0) and edges T1→D share 1.0 and T2→T1 share 1.0, dates as F | `GET .../layers?as_of=2024-06-30` | T1's `l2` = 0.85 and T2's `l2` = 0.7225 | holdout |
| AC-19 | AC-18 plus run company E (include, catalogue 1.0) and edge T1→E share 1.0, dates as F | `GET .../layers?as_of=2024-06-30` | T1's `l2` = 1.0 (1.7 capped at 1) | holdout |
| AC-36 | A run with companies A (include, catalogue 0.60) and B (include, extracted 0.25), and edges A→B share 0.40 and B→A share 0.40, dates as F | `GET .../layers?as_of=2024-06-30` | A's `l2` = 0.085 and B's `l2` = 0.204 (the path A→B→A is not counted) | holdout |
| AC-37 | Fixture F plus an older S1→A row: `revenue_share` 0.90, `effective_date` 2022-12-31, `published_at` 2023-03-01 | `GET .../layers?as_of=2024-06-30` | S1's `l2` = 0.204 (the 2023-12-31 version is used) | holdout |
| AC-38 | AC-37's edges | `GET .../layers?as_of=2023-06-30` | S1's `l2` = 0.459, and no row has S2's issuer key | holdout |
| AC-39 | Fixture F plus a correction S1→A row: `revenue_share` 0.30, `effective_date` 2023-12-31, `published_at` 2024-05-01 | Import it, then `GET .../layers?as_of=2024-06-30` | The import prints `1 rows, 1 new`; S1's `l2` = 0.153 | holdout |
| AC-40 | Fixture F plus edge C supplies X (`revenue_share` 0.5, dates as F), X not in the run | `GET .../layers?as_of=2024-06-30` | C's `l2` = null and `status` = `insufficient data`; no row has X's issuer key | holdout |
| AC-41 | A run with company M holding two `include` matches: catalogue 0.20 and extracted 0.50 | `GET .../layers?as_of=2024-06-30` | M's `l1` = 0.5 and `score` = 0.225 | holdout |
| AC-42 | A run with companies P and Q, both include with catalogue 0.40, where P's issuer key sorts before Q's | `GET .../layers?as_of=2024-06-30` | P's `rank` = 1 and Q's `rank` = 2, both with `score` = 0.18 | holdout |
| AC-20 | Fixture F with A's match verdict `exclude` instead of `include` | `GET .../layers?as_of=2024-06-30` | A's `l1` = null and A's `status` = `insufficient data`; no row has S1's or S2's issuer key | holdout |
| AC-21 | Fixture F with `ARP_THEME_LAYER_W1=0.5`, `ARP_THEME_LAYER_W2=0.35`, `ARP_THEME_LAYER_W3=0.15` | `GET .../layers?as_of=2024-06-30` | `weights` = `{"w1": 0.5, "w2": 0.35, "w3": 0.15}` and A's `score` = 0.3 | holdout |
| AC-43 | Fixture F with `ARP_REVENUE_EXPOSURE_PURE_PLAY_THRESHOLD=0.2` | `GET .../layers?as_of=2024-06-30` | B's `pure_play` = true | holdout |
| AC-22 | No run `nope` | `GET /api/themes/runs/nope/layers?as_of=2024-06-30` | 404, `detail` = `unknown theme run 'nope'` | holdout |
| AC-23 | An existing run whose `run_type` is `extraction` | `GET /api/themes/runs/<its id>/layers?as_of=2024-06-30` | 404, `detail` = `unknown theme run '<its id>'` | holdout |
| AC-24 | Fixture F | `GET .../layers?as_of=30.06.2024` | 422, `detail` = `as_of must be a date in YYYY-MM-DD form` | holdout |
| AC-25 | Fixture F | `GET .../layers` with no `as_of` | 200 with `as_of` = today's date (UTC) | holdout |
| AC-26 | No `Authorization` header | `GET .../layers?as_of=2024-06-30` | 401, `detail` = `Missing or invalid bearer token` | holdout |
| AC-27 | Fixture F imported | `arp theme layers --run R --as-of 2024-06-30` | Exit 0. Stdout lines are tab-separated (shown as `\t`). Line 1 is `rank\tissuer_key\tname\tl1\tl2\tl3\tscore\tstatus`; line 2 is `1\t<A's key>\tA\t0.6000\t-\t-\t0.2700\tscored`; the last line is `-\t<C's key>\tC\t-\t-\t-\t-\tinsufficient data` | holdout |
| AC-28 | Fixture F imported; run R selected on `#/theme`; `As of` set to 2024-06-30 | Open the Layers table | Columns, in order: Rank, Company, Layer 1, Layer 2, Layer 3, Score, Via. S1's Via cell reads `S1 → A` | evaluator |
| AC-29 | Same as AC-28 | Look at the Layer 3 column | Every cell reads `not available` | evaluator |
| AC-30 | Same as AC-28 | Look at C's row | It is the last row, its Score cell reads `insufficient data`, and its Rank cell is empty | evaluator |
| AC-31 | Same as AC-28 | Look above the table | It reads `Weights 0.45 / 0.35 / 0.20 · decay 0.85 · as of 2024-06-30` | evaluator |
| AC-44 | Same as AC-28, then `As of` changed to 2024-02-01 | Look at the Layers table | It lists A, B and C only | evaluator |
| AC-46 | Fixture F with `ARP_THEME_LAYER_DECAY=1.5` | `arp theme layers --run R --as-of 2024-06-30` | Exit 1, stderr contains `ARP_THEME_LAYER_DECAY` | holdout |
| AC-47 | Fixture F with `ARP_THEME_LAYER_MAX_HOPS=3` | `arp theme layers --run R --as-of 2024-06-30` | Exit 1, stderr contains `ARP_THEME_LAYER_MAX_HOPS` | holdout |
| AC-48 | Fixture F with `ARP_THEME_LAYER_W1=-0.1` | `arp theme layers --run R --as-of 2024-06-30` | Exit 1, stderr contains `ARP_THEME_LAYER_W1` | holdout |
| AC-49 | A run with P and Q, both include with catalogue 0.40, where P's issuer key sorts before Q's; edges S1→P and S1→Q, each `revenue_share` 0.50, dates as F | `GET .../layers?as_of=2024-06-30` | S1's `l2` = 0.34 and `l2_via` = [S1's key, P's key] | holdout |
| AC-50 | Fixture F imported, then a CSV with the S1→A row changed only in `revenue_share` (0.45) | Import the second CSV | Exit 1, stderr contains `row 1: an edge with this supplier, customer, effective_date and published_at is already stored with different values` | holdout |
| AC-51 | A run selected on `#/theme`, `As of` untouched | Open the Layers table | The `As of` input shows today's UTC date as `YYYY-MM-DD`, and the line above the table ends with `as of <that date>` | evaluator |
| AC-32 | Fixture F's run, once without and once with fixture F's edge CSV imported | `GET /api/runs/R/results`, `GET /api/runs/R/export.csv` and `GET /api/runs/R/export.xlsx` | The results body and the CSV body are identical in both cases; the XLSX has the same cell values in every sheet | holdout |
| AC-45 | An existing theme run selected on `#/theme` | Look at the existing results table | It shows the same columns and rows as on `main` before this change | evaluator |
| AC-33 | The existing tests under `backend/tests/` for theme runs and revenue exposure | The full backend suite runs | They pass with no edits to those test files | unit |

Must not change:
- The theme run's ranked results, CSV and XLSX exports (AC-32).
- The existing results table on `#/theme` (AC-45).
- `CompanyMatch` and every existing theme-run test (AC-33).
