# Value Chain Explorer on full-resolution EXIOBASE

Status: draft, 2026-10-24. Owner decisions on 2026-10-24: base the value-chain work on EXIOBASE;
approach A (matrix core, graph on top; see Approaches); build a screen and functions to explore it;
keep all three mocked-up views (node page, upstream tree, footprint breakdown). Mockups with real
EXIOBASE 2022 figures: https://claude.ai/artifact/CaSz62Xaz1jfzhBANf7TE5

## Intent

Analysts want to see how any sector in any region connects to the rest of the world economy: who it
buys from, who it sells to, what flows through its supply chain, and what one euro of its output
takes in carbon, energy and jobs. This is the base for later value-chain work (activity mapping,
company overlays, shock propagation), so it has to be generic, not tied to one theme.

Today `arp io import-exiobase` (spec `2026-10-19-io-tables-import-design.md`) collapses EXIOBASE's
163 sectors × 49 regions into 50 ICIO industries and keeps only some extensions. That is right for
the indirect-exposure tier and stays as it is. This spec adds a second, full-resolution build of the
same archive and an explorer screen on top of it.

## Goals

- Every sector-region node with output (of EXIOBASE's 7,987) can be found and opened.
- For a node: direct and total suppliers, direct and total customers, its own intensities.
- An upstream tree for any node, filterable by depth, width, cut-off and goods only.
- A footprint for any amount of final demand for a node, split by region and by sector, for CO₂e,
  energy and jobs.
- Numbers are exact input-output results, never sampled or estimated by a model.

## Non-goals (this spec)

- Neo4j summary graph and a path finder between two nodes (next slice).
- Linking taxonomy activities or companies to nodes; portfolio overlays.
- Shock simulation (demand, supply-side Ghosh, price model).
- Capital endogenisation, Comtrade/BACI, GEM facilities.
- Changing the existing 50-industry import or the indirect-exposure tier.

## Anti-goals

- An LLM anywhere in this feature. Everything is arithmetic on the published table.
- A number on screen without its basis: every view states version, year, units and the caveats below.
- Listing or ranking nodes with zero output as if they had data.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Matrix core, graph on top.** Full tables as matrix files; all calculations in numpy; Neo4j later holds a derived summary graph and the links to activities and companies. | Exact numbers, reuses the Leontief code and importer; two representations, the graph only for exploration. | **Chosen** |
| B | Graph only: all nodes and links above a cut-off in Neo4j, propagation in Cypher or GDS. | Dropping small links breaks totals; GDS at scale needs Enterprise, the owner chose Community. | Rejected |
| C | Stay at 50 industries and add features there. | Smallest change; never gets past 50 industries. | Rejected |

## Scope

1. **Build command.** `arp io build-full <zip> --out <dir> [--label <label>]` reads one EXIOBASE 3
   ixi archive (`IOT_<year>_ixi.zip`, release 3.11.2 layout) and writes the files in Appendix A.
   It prints, line 1, `<n_nodes> nodes (<n_sectors> sectors × <n_regions> regions) -> <dir>`, where
   `n_nodes` counts every node including zero-output ones, then line 2 `ARP_VALUE_CHAIN_DIR=<dir>`.
   It does not touch `arp io import-exiobase` or its outputs.
2. **Setting.** `ARP_VALUE_CHAIN_DIR` (default unset). Unset, or the directory lacks
   `manifest.json`: the explorer is "not configured".
3. **API**, router prefix `/api/value-chain`, viewer role, read-only (Appendix B).
4. **Screen** "Value Chain Explorer" at `#/valueChain`, listed in the R&D Lab workspace screens
   (`frontend/src/lib/processes.ts`), with three views matching the mockups (Appendix C).

## Definitions

Indices `i, j, k` run over nodes in archive order. `Z` is `Z.txt` (M EUR), `x` is `x.txt`. All
arithmetic, stored matrices and cut-off comparisons are float64.

- `A = Z · diag(x)⁻¹`, with column `j` all zero where `x_j = 0`. `L = (I − A)⁻¹` (Leontief).
- `B = diag(x)⁻¹ · Z`, with row `i` all zero where `x_i = 0`. `G = (I − B)⁻¹` (Ghosh).
- **Upstream of k**: direct `A[i,k]`; total `L[i,k] − δ_ik`. Unit: € from `i` per € of `k`'s output.
- **Downstream of k**: direct `B[k,j]`; total `G[k,j] − δ_kj`. Unit: € of `j`'s output resting on
  €1 of `k`'s output, counting intermediaries; totals can sum to more than 1.
- **Intensities** (direct, per M EUR of output; null where `x_k = 0`):
  - `ghg_t_per_meur`: Σ over `air_emissions` stressors of (row × GWP100 factor from the bundled
    `ghg_gwp100.csv`), kg → t, ÷ `x`.
  - `energy_tj_per_meur`: `energy` row `Energy use - Net` ÷ `x`.
  - `jobs_per_meur`: Σ `employment` rows starting `Employment people` (1000 p) × 1000 ÷ `x`.
  - `va_share`: Σ `factor_inputs` rows except `Taxes less subsidies on products purchased: Total`, ÷ `x`.
- **Footprint** of `y` M EUR of final demand for `k`, indicator `s`: contribution of node `i` is
  `s_i · L[i,k] · y`; total is the sum; "by region" and "by sector" sum those contributions per
  region and per sector name; groups whose sum is 0 are left out.
- **Goods node**: a node whose sector maps, in the bundled `exiobase_ixi_to_icio2025.csv`, to an ICIO
  code starting `A`, `B`, `C`, `D` or `E`. Every other node is a services node.
- **Node id**: `<region code>.<sector number>`, sector number 1–163 in the order sectors appear for
  that region in `x.txt` (`CN.95`). Stable within an edition only.
- **Version and year** come from the archive's `metadata.json`: `version`, and the year in `name`
  (`EXIO_IOT_<year>_ixi`).
- **Ties** in any ranked list break by node id ascending (string order).
- Nodes with `x = 0` never appear in lists, trees or search results; opening one returns 404.

## My calls (owner to confirm with the acceptance table)

1. **No Neo4j in this slice.** All three views are served from the matrices. The summary graph comes
   with the path finder and the activity/company links, where it earns its place.
2. **Precompute `L` and `G` at build time** and store them (float64), so every request is a column
   or row read. The builder picks the on-disk layout (for example `L` stored transposed so a column
   is contiguous) within the performance rows below.
3. **Labels**: EXIOBASE sector names with a trailing ` (NN)` code removed; region codes as in the
   archive, the five rest-of-world codes shown as `RoW Asia-Pacific` (WA), `RoW Europe` (WE),
   `RoW Africa` (WF), `RoW Americas` (WL), `RoW Middle East` (WM).
4. **Display**: flows in cents per euro with one decimal (`7.4¢`); a tree's `chain` with two
   decimals (`0.80¢`); intensity tiles with one decimal, value added as a whole percent; the API
   returns unrounded fractions.
5. **"Hide this node"** on the node page drops the node itself from its suppliers and customers
   (purchases from and sales to its own sector in its own region), nothing else.
6. **Derived files are not committed** (size and the EXIOBASE 3.9+ licence); building them belongs
   in the environment setup script. The owner recorded on 2026-10-19 that the licence is no obstacle.
7. **Search** ranks exact region matches first, so `WA` or `DE` finds that region's nodes ahead of
   sector names that merely contain the letters ("waste", "trade").
8. **Direct mode re-sorts**: switching to Direct shows the top 10 direct suppliers and customers,
   not the Total list's rows with direct values.
9. **Caveat line**, on every view and in every API response: `EXIOBASE <version> · <year> · basic
   prices, M EUR · now-cast years are estimates · capital goods not included in flows`.

## Constraints

- Precision first: float64 arithmetic on the table; nothing rounded before display.
- Build: at most 20 minutes and 8 GB peak resident memory for one real archive.
- Node, tree (depth 4, width 5) and footprint requests: at most 1 s each on a warm process.
- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`; API contract regenerated
  (`scripts/export_openapi.py`, `npm run gen:api`) and each new `request<T>()` listed in
  `frontend/src/api/contract.ts`.

## Left to the builder

File layout, how the build streams `Z.txt`, component structure, and whether the three views are
tabs or sub-routes, as long as the URLs in Appendix C work. `ARP_VALUE_CHAIN_DIR` is read per request
(not cached at start-up), so tests can switch it.

## Appendix A: build output (`<dir>`)

- `manifest.json`: `{"edition": "<label>", "exiobase_version": "<metadata version>", "year":
  <int>, "source_sha256": "<archive hash>", "n_regions": <int>, "n_sectors": <int>, "n_nodes":
  <int>, "built_at": "<RFC 3339>"}`. `--label` defaults to `exiobase-<archive stem>`.
- `nodes.csv`: `node_id,region,sector,sector_no,output_meur,goods,ghg_t_per_meur,energy_tj_per_meur,jobs_per_meur,va_share`.
- The matrices `A`, `L`, `G` (and anything else the builder needs), in a layout of the builder's choice.

## Appendix B: API

Every 200 response carries `edition` and `caveat` (My call 9). Not configured: every endpoint
answers 503 with `detail` `value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR`.
Unknown or zero-output node: 404 `detail` `unknown node '<id>'`. Parameters out of range: 422.

- `GET /status` → `{edition, version, year, n_nodes, n_regions, n_sectors, built_at}`.
- `GET /nodes?q=<text>&limit=20` → `{items: [{node_id, region, region_label, sector}]}`, at most
  `limit` (1–100) items. A node matches when `q` (case-insensitive) equals its region code or region
  label, or is a substring of its sector name or region label. Nodes whose region code or label
  equals `q` come first; then the rest; each group ordered by node id.
- `GET /nodes/{id}?limit=10&exclude_own=false&order=total` → `{node_id, region, region_label,
  sector, output_meur, ghg_t_per_meur, energy_tj_per_meur, jobs_per_meur, va_share, suppliers,
  customers}`; `suppliers` and `customers` are each up to `limit` (1–50) items `{node_id, region,
  region_label, sector, direct, total}`, ordered by `order` (`total` or `direct`) descending.
  A list holds only nodes with output whose value in the `order` measure is greater than 0.
  `exclude_own=true` drops the node itself from both lists.
- `GET /nodes/{id}/tree?depth=2&width=3&cutoff=0.01&goods_only=false` → nested
  `{node_id, region_label, sector, coef, chain, children}`; the root has `coef` and `chain` 1. A
  node's children are its `width` largest direct suppliers: nodes with output, `i ≠` that node (only
  that node; an ancestor may reappear further down), with `A[i,node] > 0` and `A[i,node] ≥ cutoff` (goods nodes only when
  `goods_only`), by `A` descending; `chain` = parent's `chain` × `coef`. Nodes at the last level
  have `children: []`. `depth` 1–4, `width` 1–5, `cutoff` 0–1.
- `GET /nodes/{id}/footprint?indicator=ghg&amount_meur=1&top=6` → `{indicator, unit, total,
  in_home_region, by_region: [[region_label, value]], by_sector: [[sector, value]]}`; `indicator`
  `ghg` (unit `t CO₂e`), `energy` (`TJ`) or `jobs` (`people`); `amount_meur` > 0; `in_home_region`
  is the share of `total` arising in the node's own region (null when `total` is 0); both lists
  ordered descending and cut to the first `top` (1–20) entries, with no remainder entry.

## Appendix C: screen

- `#/valueChain`: a search picker (sector or region) and, until a node is picked, the text
  `Pick a sector and region.` Not configured: the 503 `detail` as the page message.
- `#/valueChain/<id>`: **node page** as mockup 1: four intensity tiles; suppliers and customers as
  bar lists (10 each); a Total/Direct switch, Total selected first, each mode showing the top 10 by
  that measure (`order=total` or `order=direct`); `Hide this node`, off by default; in Total mode each
  row reads `<total>¢ (direct <direct>¢)`, in Direct mode `<direct>¢` (so Direct mode can show fewer
  than 10 rows); clicking a row opens that node's page, whose heading reads `<sector> · <region label>`.
- `#/valueChain/<id>/tree`: **upstream tree** as mockup 2, suppliers to the left of what they supply;
  the screen requests width 3; controls Levels (2–4, default 2), cut-off (0–10¢, default 1¢),
  `Goods only` (off). Each box shows `<coef>¢ per €` and, from level 2, `chain <chain>¢`; clicking
  a box opens that node's tree.
- `#/valueChain/<id>/footprint`: **footprint** as mockup 3: amount (M EUR, default 1), indicator
  CO₂e/Energy/Jobs (default CO₂e), the total, `<n>% in <home region label>`, by-region and
  by-sector bars (6 each).
- The caveat line at the foot of every view.

## Acceptance

Fixture F: an archive named `IOT_2022_ixi.zip` with the real file layout and a `metadata.json` with
`version` `3.11.2` and `name` `EXIO_IOT_2022_ixi`. Regions `DE`, `CN`; sectors, in this order,
`Cultivation of paddy rice`, `Mining of copper ores and concentrates`, `Other business activities
(74)`. Paddy rice has `x = 0` and zero rows and columns. For the other four nodes, in the order
DE.2, DE.3, CN.2, CN.3: `x = [100, 200, 100, 100]`; `Z` rows `[10,20,0,10]`, `[10,20,10,0]`,
`[0,0,20,10]`, `[0,20,10,10]`; `air_emissions` row `CO2 - combustion - air` `[500000, 0, 100000, 0]`
kg; `energy` row `Energy use - Net` `[10, 0, 0, 0]` TJ; `employment` row `Employment people:
High-skilled male` `[1, 2, 0, 0]`; `factor_inputs` rows `Compensation of employees; wages, salaries,
& employers' social contributions: High-skilled` `[30, 100, 50, 50]` and `Taxes less subsidies on
products purchased: Total` `[5, 5, 5, 5]`; every other satellite row zero. "F built" means
`arp io build-full IOT_2022_ixi.zip --out <d>` ran and `ARP_VALUE_CHAIN_DIR=<d>`. Numbers are
compared rounded to 4 decimals. The caveat for F is `EXIOBASE 3.11.2 · 2022 · basic prices, M EUR ·
now-cast years are estimates · capital goods not included in flows` (C below).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture F | `arp io build-full IOT_2022_ixi.zip --out <d>` | exit 0; stdout line 1 `6 nodes (3 sectors × 2 regions) -> <d>`, line 2 `ARP_VALUE_CHAIN_DIR=<d>` | holdout |
| AC-1b | as AC-1 | read `<d>/manifest.json` | `edition` `exiobase-IOT_2022_ixi`, `exiobase_version` `3.11.2`, `year` 2022, `n_regions` 2, `n_sectors` 3, `n_nodes` 6 | holdout |
| AC-2 | F built | `GET /api/value-chain/status` | 200 with `edition` `exiobase-IOT_2022_ixi`, `version` `3.11.2`, `year` 2022, `n_nodes` 6, `n_regions` 2, `n_sectors` 3, `caveat` C | holdout |
| AC-3 | F built | `GET …/nodes/CN.2` | `suppliers` is exactly these 4 items, in order: CN.2 (direct 0.2, total 0.2696), CN.3 (0.1, 0.1572), DE.3 (0.1, 0.1448), DE.2 (0, 0.0336); `caveat` C | holdout |
| AC-4 | F built | `GET …/nodes/CN.2?exclude_own=true` | `suppliers` node ids exactly `["CN.3","DE.3","DE.2"]` | holdout |
| AC-5 | F built | `GET …/nodes/DE.2` | `customers` is exactly these 4 items, in order: DE.3 (direct 0.2, total 0.279), CN.3 (0.1, 0.1289), DE.2 (0.1, 0.1266), CN.2 (0, 0.0336) | holdout |
| AC-6 | F built | `GET …/nodes/DE.2?exclude_own=true` | `customers` node ids exactly `["DE.3","CN.3","CN.2"]` | holdout |
| AC-7 | F built | `GET …/nodes/DE.3` | `sector` `Other business activities`; `ghg_t_per_meur` 0, `energy_tj_per_meur` 0, `jobs_per_meur` 10, `va_share` 0.5 | holdout |
| AC-8 | F built | `GET …/nodes/DE.2` | `ghg_t_per_meur` 5, `energy_tj_per_meur` 0.1, `jobs_per_meur` 10, `va_share` 0.3 | holdout |
| AC-9 | F built | `GET …/nodes/DE.3/tree?depth=2&width=3&cutoff=0.01` | exactly: root → [CN.3 (coef 0.1, chain 0.1), DE.2 (0.1, 0.1)]; CN.3 → [CN.2 (0.1, 0.01), DE.2 (0.1, 0.01)]; DE.2 → [DE.3 (0.1, 0.01)]; every level-2 node has `children: []` | holdout |
| AC-10 | F built | `…/nodes/DE.3/tree?depth=1&width=1` | root children ids exactly `["CN.3"]` | holdout |
| AC-11 | F built | `…/nodes/DE.3/tree?depth=1&cutoff=0.1` | root children ids exactly `["CN.3","DE.2"]` | holdout |
| AC-12 | F built | `…/nodes/DE.3/tree?depth=1&cutoff=0.11` | root `children` is `[]` | holdout |
| AC-13 | F built | `…/nodes/DE.3/tree?depth=1&goods_only=true` | root children ids exactly `["DE.2"]` | holdout |
| AC-13b | F built | `…/nodes/DE.3/tree?depth=1&cutoff=0` | root children ids exactly `["CN.3","DE.2"]` | holdout |
| AC-14 | F built | `…/nodes/DE.2/tree?depth=5` | 422 | holdout |
| AC-15 | F built | `…/nodes/DE.3/footprint?indicator=ghg&amount_meur=2` | `unit` `t CO₂e`; `total` 1.4268; `by_region` `[["DE",1.395],["CN",0.0318]]`; `in_home_region` 0.9777 | holdout |
| AC-16 | F built | same request | `by_sector` `[["Mining of copper ores and concentrates",1.4268]]` | holdout |
| AC-17 | F built | `GET …/nodes/DE.3/footprint?indicator=ghg&amount_meur=2&top=1` | `by_region` `[["DE",1.395]]` | holdout |
| AC-18 | F built | `…/nodes/DE.3/footprint?indicator=energy&amount_meur=2` | `unit` `TJ`; `total` 0.0279; `in_home_region` 1 | holdout |
| AC-19 | F built | `…/nodes/DE.3/footprint?indicator=jobs&amount_meur=2` | `unit` `people`; `total` 25.3576 | holdout |
| AC-20 | F built | `GET …/nodes/DE.1` | 404, `detail` `unknown node 'DE.1'` | holdout |
| AC-21 | F built | `GET …/nodes?q=paddy` | 200, `items` `[]` | holdout |
| AC-22 | F built | `GET …/nodes?q=copper` | `items` node ids exactly `["CN.2","DE.2"]` | holdout |
| AC-22b | F built | `GET …/nodes?q=de` | `items` node ids exactly `["DE.2","DE.3"]` | holdout |
| AC-22c | F built | `GET …/nodes/DE.3?order=direct` | `suppliers` node ids exactly `["CN.3","DE.2","DE.3"]`, each `direct` 0.1 | holdout |
| AC-22d | F built | `GET …/nodes/DE.3` | `suppliers` node ids exactly `["DE.2","DE.3","CN.3","CN.2"]` | holdout |
| AC-22e | F built | a 200 from each of `/nodes?q=copper`, `/nodes/DE.3/tree`, `/nodes/DE.3/footprint` | each has `edition` `exiobase-IOT_2022_ixi` and `caveat` C | holdout |
| AC-23 | `ARP_VALUE_CHAIN_DIR` unset | `GET …/status` | 503, `detail` `value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR` | holdout |
| AC-24 | `ARP_VALUE_CHAIN_DIR` = an empty directory | `GET …/nodes?q=x` | 503 with the same `detail` | holdout |
| AC-25 | `ARP_ANTHROPIC_API_KEY` unset | AC-1 to AC-24 | all pass | holdout |
| AC-26 | Real `IOT_2022_ixi.zip`, Zenodo record 23039074 | `arp io build-full` | exit 0; line 1 `7987 nodes (163 sectors × 49 regions) -> <d>` | evaluator |
| AC-27 | as AC-26 | the same run under `/usr/bin/time -v` (or `ru_maxrss` of the child) | elapsed ≤ 20:00 | evaluator |
| AC-27b | as AC-27 | read maximum resident set size | ≤ 8,388,608 KB | evaluator |
| AC-28 | AC-26 built | open the node page of `Manufacture of electrical machinery and apparatus n.e.c. · CN` | the supplier row `Copper production · CN` reads `7.4¢ (direct 4.3¢)` (whitespace collapsed) | evaluator |
| AC-29 | as AC-28 | read the CO₂e tile | `14.3` | evaluator |
| AC-30 | as AC-28 | click the supplier row `Copper production · CN` | the URL becomes `#/valueChain/<id of Copper production · CN>`; the page heading reads `Copper production · CN` | evaluator |
| AC-31 | as AC-28 | open its tree view with defaults | a box `Copper production · CN` shows `4.3¢ per €`; the box `Mining of copper ores and concentrates · CN` drawn as its supplier shows `18.4¢ per €` and `chain 0.80¢` | evaluator |
| AC-32 | as AC-28 | open its footprint view with defaults | total `973.9 t CO₂e`; `85% in CN` | evaluator |
| AC-33 | AC-26 built, API process warmed by one request | for 10 seeded random nodes with `output_meur` > 0: `GET /nodes/{id}`, `/tree?depth=4&width=5&cutoff=0`, `/footprint?indicator=ghg`, from a client on localhost | each answers in ≤ 1.0 s wall-clock | evaluator |
| AC-34 | AC-26 built | open `#/valueChain` | the page shows `Pick a sector and region.` | evaluator |
| AC-35 | AC-26 built | search `WA` in the picker | every result shown has region `RoW Asia-Pacific` | evaluator |
| AC-35b | AC-26 built | for every `nodes.csv` row, `GET /nodes/{id}` | 200 where `output_meur` > 0; 404 where it is 0 | evaluator |
| AC-35c | as AC-28 | turn on `Hide this node` | no supplier or customer row reads `Manufacture of electrical machinery and apparatus n.e.c. · CN`; with it off, the first supplier row does | evaluator |
| AC-35d | as AC-28 | click Direct | the `Copper production · CN` row reads `4.3¢` with no `(direct`; rows are in descending order of their value | evaluator |
| AC-36 | AC-26 built | open each of `#/valueChain/<id>`, `/tree`, `/footprint` for one node | each page foot shows exactly `EXIOBASE 3.11.2 · 2022 · basic prices, M EUR · now-cast years are estimates · capital goods not included in flows` | evaluator |
| AC-37 | `ARP_VALUE_CHAIN_DIR` unset | open `#/valueChain` | the page shows `value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR` | evaluator |
| AC-38 | the R&D Lab page `#/rdLab` | read the Screens list | it holds `Value Chain Explorer` linking to `#/valueChain` | evaluator |

Must not change:
- AC-39: on the real `IOT_2022_ixi.zip`, the sha256 of every file `arp io import-exiobase --out <d>`
  writes equals that of the same command run from the PR's merge-base with `main`. Checked by: evaluator.
- AC-40: `git diff <merge-base> -- backend/tests/test_io_import.py backend/tests/test_leontief.py backend/tests/test_icio_loader.py backend/tests/test_exiobase_loader.py backend/tests/test_factory.py backend/tests/test_exposure.py backend/tests/test_criticality.py`
  is empty. Checked by: evaluator.
- AC-41: `pytest tests/test_io_import.py tests/test_leontief.py tests/test_icio_loader.py tests/test_exiobase_loader.py tests/test_factory.py tests/test_exposure.py tests/test_criticality.py` (from `backend/`) exits 0. Checked by: unit.
