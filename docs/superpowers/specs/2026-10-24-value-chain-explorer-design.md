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

- Every one of EXIOBASE's 7,987 sector-region nodes can be opened and read.
- For a node: direct and total suppliers, direct and total customers, its own intensities.
- An upstream tree for any node, filterable.
- A footprint for any amount of final demand for a node, split by region and by sector.
- Numbers are exact input-output results, never sampled or estimated by a model.

## Non-goals (this spec)

- Neo4j summary graph and a path finder between two nodes (next slice).
- Linking taxonomy activities or companies to nodes; portfolio overlays.
- Shock simulation (demand, supply-side Ghosh, price model).
- Capital endogenisation, Comtrade/BACI, GEM facilities.
- Changing the existing 50-industry import or the indirect-exposure tier.

## Anti-goals

- An LLM anywhere in this feature. Everything is arithmetic on the published table.
- A number on screen without its basis: every view states edition, year, units and the caveats below.
- Ranking or presenting nodes with zero output as if they had data.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Matrix core, graph on top.** Full tables as matrix files; all calculations in numpy; Neo4j later holds a derived summary graph and the links to activities and companies. | Exact numbers, reuses the Leontief code and importer; two representations, the graph only for exploration. | **Chosen** |
| B | Graph only: all nodes and links above a cut-off in Neo4j, propagation in Cypher or GDS. | Dropping small links breaks totals; GDS at scale needs Enterprise, the owner chose Community. | Rejected |
| C | Stay at 50 industries and add features there. | Smallest change; never gets past 50 industries. | Rejected |

## Scope

1. **Build command.** `arp io build-full <zip> --out <dir> [--label <label>]` reads one EXIOBASE 3
   ixi archive (`IOT_<year>_ixi.zip`, release 3.11.2 layout) and writes the files in Appendix A.
   It prints, line 1, `<n_nodes> nodes (<n_sectors> sectors × <n_regions> regions) -> <dir>`, then
   one line `ARP_VALUE_CHAIN_DIR=<dir>`. It does not touch `arp io import-exiobase` or its outputs.
2. **Setting.** `ARP_VALUE_CHAIN_DIR` (default unset). Unset, or the directory lacks
   `manifest.json`: the explorer is "not configured".
3. **API**, router prefix `/api/value-chain`, viewer role, read-only (Appendix B).
4. **Screen** "Value Chain Explorer" at `#/valueChain`, listed in the R&D Lab workspace screens
   (`frontend/src/lib/processes.ts`), with three views matching the mockups (Appendix C).

## Definitions

Indices `i, j, k` run over nodes in archive order. `Z` is `Z.txt` (M EUR), `x` is `x.txt`.

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
  `s_i · L[i,k] · y`; total is the sum; "by region" and "by sector" group those contributions.
- **Goods node**: a node whose sector maps, in the bundled `exiobase_ixi_to_icio2025.csv`, to an ICIO
  code starting `A`, `B`, `C`, `D` or `E`. Every other node is a services node.
- **Node id**: `<region code>.<sector number>`, sector number 1–163 in the order sectors appear for
  that region in `x.txt` (`CN.95`). Stable within an edition only.
- **Ties** in any ranked list break by node id ascending (string order).
- Nodes with `x = 0` never appear in lists, trees or search results; opening one returns 404.

## My calls (owner to confirm with the acceptance table)

1. **No Neo4j in this slice.** All three views are served from the matrices. The summary graph comes
   with the path finder and the activity/company links, where it earns its place.
2. **Precompute `L` and `G` at build time** and store them, so every request is a column or row read.
   The builder picks the on-disk layout (for example float32, `L` stored transposed so a column is
   contiguous) within the performance rows below.
3. **Labels**: EXIOBASE sector names with a trailing ` (NN)` code removed; region codes as in the
   archive, the five rest-of-world codes shown as `RoW Asia-Pacific` (WA), `RoW Europe` (WE),
   `RoW Africa` (WF), `RoW Americas` (WL), `RoW Middle East` (WM).
4. **Display unit**: cents per euro (`7.4¢`), one decimal; a tree's `chain` two decimals (`0.80¢`);
   the API returns fractions.
5. **Derived files are not committed** (size and the EXIOBASE 3.9+ licence); building them belongs
   in the environment setup script. The owner recorded on 2026-10-19 that the licence is no obstacle.
6. **Caveat line** on every view: `EXIOBASE <version> · <year> · basic prices, M EUR · now-cast years
   are estimates · capital goods not included in flows`.

## Constraints

- Precision first: exact arithmetic on the table; nothing rounded before display.
- Build: at most 20 minutes and 8 GB peak resident memory for one real archive.
- Node, tree (depth 4, width 5) and footprint requests: at most 1 s each on a warm process.
- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`; API contract regenerated
  (`scripts/export_openapi.py`, `npm run gen:api`) and each new `request<T>()` listed in
  `frontend/src/api/contract.ts`.

## Left to the builder

File layout and dtypes, how the build streams `Z.txt`, the search matching rule (case-insensitive
substring on sector name or region code is enough), component structure, and whether the three views
are tabs or sub-routes, as long as the URLs in Appendix C work.

## Appendix A: build output (`<dir>`)

- `manifest.json`: `{"edition": "<label>", "exiobase_version": "<from metadata.json>", "year":
  <int>, "source_sha256": "<archive hash>", "n_regions": 49, "n_sectors": 163, "built_at": "<RFC 3339>"}`.
  `--label` defaults to `exiobase-<archive stem>`.
- `nodes.csv`: `node_id,region,sector,sector_no,output_meur,goods,ghg_t_per_meur,energy_tj_per_meur,jobs_per_meur,va_share`.
- The matrices `A`, `L`, `G` (and anything else the builder needs), in a layout of the builder's choice.

## Appendix B: API

All responses carry `edition` and `caveat` (the line in My call 6). Not configured: every endpoint
answers 503 with `detail` `value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR`.
Unknown or zero-output node: 404 `detail` `unknown node '<id>'`.

- `GET /status` → `{edition, year, n_nodes, n_regions, n_sectors, built_at}`.
- `GET /nodes?q=<text>&limit=20` → `[{node_id, region, region_label, sector}]`, at most `limit` (max 100).
- `GET /nodes/{id}?limit=10&exclude_own=false` → `{node_id, region, region_label, sector,
  output_meur, ghg_t_per_meur, energy_tj_per_meur, jobs_per_meur, va_share, suppliers, customers}`;
  `suppliers` and `customers` are each up to `limit` items `{node_id, region, region_label, sector,
  direct, total}`, ordered by `total` descending. `exclude_own=true` drops the node itself.
- `GET /nodes/{id}/tree?depth=2&width=3&cutoff=0.01&goods_only=false` → nested
  `{node_id, region_label, sector, coef, chain, children}`; root has `coef` and `chain` 1. A node's
  children are its `width` largest direct suppliers `i ≠` that node with `A[i,node] ≥ cutoff`
  (goods nodes only when `goods_only`), by `A` descending; `chain` = parent's `chain` × `coef`.
  `depth` 1–4, `width` 1–5, `cutoff` 0–1; out of range → 422.
- `GET /nodes/{id}/footprint?indicator=ghg&amount_meur=1&top=6` → `{indicator, unit, total,
  in_home_region, by_region: [[label, value]], by_sector: [[sector, value]]}`; `indicator` one of
  `ghg` (t CO₂e), `energy` (TJ), `jobs` (people); `in_home_region` is the share of `total` arising in
  the node's own region (null when `total` is 0); lists ordered descending, `top` 1–20; `by_region`
  labels are region labels (My call 3).

## Appendix C: screen

- `#/valueChain`: picker (search by sector or region) and, until a node is picked, the text
  `Pick a sector and region.` Not configured: the 503 `detail` as the page message.
- `#/valueChain/<id>`: **node page** as mockup 1: four intensity tiles; suppliers and customers as
  bar lists; a Total/Direct switch (Total first); `Hide own sector` (off by default); each row opens
  that node.
- `#/valueChain/<id>/tree`: **upstream tree** as mockup 2, goods flowing left to right into the
  selected node; controls Levels (2–4, default 2), cut-off (0–10¢, default 1¢), `Goods only`
  (off). Each box shows `<coef>¢ per €` and, below level 1, `chain <chain>¢`; clicking a box opens
  its tree.
- `#/valueChain/<id>/footprint`: **footprint** as mockup 3: amount (M EUR, default 1), indicator
  CO₂e/Energy/Jobs (default CO₂e), total with `<n>% in <home region>`, by-region and by-sector bars.
- The caveat line at the foot of every view.

## Acceptance

Fixture F: an archive with the real file layout holding regions `DE`, `CN` and, in this order, the
sectors `Cultivation of paddy rice`, `Mining of copper ores and concentrates` and `Other business
activities (74)`. Paddy rice has `x = 0` and zero rows and columns. For the other four nodes, in the
order DE.2, DE.3, CN.2, CN.3: `x = [100, 200, 100, 100]`; `Z` rows `[10,20,0,10]`, `[10,20,10,0]`,
`[0,0,20,10]`, `[0,20,10,10]`; `air_emissions` row `CO2 - combustion - air` `[500000, 0, 100000, 0]`
kg; `energy` row `Energy use - Net` `[10, 0, 0, 0]` TJ; `employment` row `Employment people:
High-skilled male` `[1, 2, 0, 0]`; `factor_inputs` rows `Compensation of employees; wages, salaries,
& employers' social contributions: High-skilled` `[30, 100, 50, 50]` and `Taxes less subsidies on
products purchased: Total` `[5, 5, 5, 5]`; every other satellite row zero. Values are compared
rounded to 4 decimals.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture F | `arp io build-full F.zip --out <d>` | exits 0; stdout line 1 `6 nodes (3 sectors × 2 regions) -> <d>`; line 2 `ARP_VALUE_CHAIN_DIR=<d>`; `<d>/manifest.json` has `n_regions` 2, `n_sectors` 3 | holdout |
| AC-2 | F built, `ARP_VALUE_CHAIN_DIR` set | `GET /api/value-chain/nodes/CN.2` | `suppliers`, in order: CN.2 (direct 0.2, total 0.2696), CN.3 (0.1, 0.1572), DE.3 (0.1, 0.1448), DE.2 (0, 0.0336); no `CN.1` or `DE.1` | holdout |
| AC-3 | as AC-2 | `GET …/nodes/CN.2?exclude_own=true` | `suppliers` node ids exactly `["CN.3","DE.3","DE.2"]` | holdout |
| AC-4 | as AC-2 | `GET …/nodes/DE.2` | `customers` totals DE.3 0.279, CN.3 0.1289, DE.2 0.1266, CN.2 0.0336, in that order; directs 0.2, 0.1, 0.1, 0 | holdout |
| AC-5 | as AC-2 | `GET …/nodes/DE.3` | `ghg_t_per_meur` 0, `energy_tj_per_meur` 0, `jobs_per_meur` 10, `va_share` 0.5; for DE.2: 5, 0.1, 10, 0.3 | holdout |
| AC-6 | as AC-2 | `GET …/nodes/DE.3/tree?depth=2&width=3&cutoff=0.01` | root children, in order: CN.3 (coef 0.1), DE.2 (coef 0.1); DE.2's children include DE.3 with coef 0.1 and chain 0.01; no child equals its own parent | holdout |
| AC-7 | as AC-2 | same with `goods_only=true` | root children exactly `["DE.2"]` | holdout |
| AC-8 | as AC-2 | `GET …/nodes/DE.3/footprint?indicator=ghg&amount_meur=2` | `total` 1.4268; `by_region` `[["DE",1.395],["CN",0.0318]]`; `in_home_region` 0.9777 | holdout |
| AC-9 | as AC-2 | `GET …/nodes/DE.1` and `GET …/nodes?q=paddy` | 404 `unknown node 'DE.1'`; search returns `[]` | holdout |
| AC-10 | as AC-2 | `GET …/nodes/DE.2/tree?depth=5` | 422 | holdout |
| AC-11 | `ARP_VALUE_CHAIN_DIR` unset | `GET /api/value-chain/status` | 503, `detail` `value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR` | holdout |
| AC-12 | Real `IOT_2022_ixi.zip`, Zenodo record 23039074 | `arp io build-full` measured with peak RSS | exits 0 within 20 min, peak RSS ≤ 8 GB; line 1 `7987 nodes (163 sectors × 49 regions) -> <d>` | evaluator |
| AC-13 | AC-12 built | open `#/valueChain/<id of CN Manufacture of electrical machinery and apparatus n.e.c.>` | supplier row `Copper production · CN` shows `7.4¢  (direct 4.3¢)`; tile CO₂e shows `14.3` | evaluator |
| AC-14 | AC-12 built | its tree view, defaults | `Copper production · CN` box shows `4.3¢ per €`; under it `Mining of copper ores and concentrates · CN` shows `18.4¢ per €` and `chain 0.80¢` | evaluator |
| AC-15 | AC-12 built | its footprint view, defaults | total `973.9 t CO₂e`, `85% in CN` | evaluator |
| AC-16 | AC-12 built, warm API process | node, tree (depth 4, width 5) and footprint requests for 10 random nodes | each answers in ≤ 1 s | evaluator |
| AC-17 | the R&D Lab page `#/rdLab` | read the Screens list | it holds `Value Chain Explorer` linking to `#/valueChain` | evaluator |
| AC-18 | any explorer view | read the foot of the page | the caveat line with edition and year | evaluator |

Must not change:
- AC-19: `arp io import-exiobase IOT_2022_ixi.zip --out <d>` writes byte-identical files to `main`'s. Checked by: holdout.
- AC-20: the existing indirect-exposure tests pass unchanged. Checked by: unit.
