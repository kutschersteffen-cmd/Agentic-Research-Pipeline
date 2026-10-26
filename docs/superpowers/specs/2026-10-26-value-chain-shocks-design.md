# Shock simulation on the full-resolution value chain

Status: draft for owner approval, 2026-10-26. Owner decisions on 2026-10-26: shocks target sets of nodes
(node ids, whole regions, whole sectors), not final-demand categories; the Ghosh result is framed as a
dependency indicator, not a forecast; the carbon price covers chosen regions (or all); the feature ships
with an API and a fourth "Shocks" view in the Value Chain Explorer.

Builds on `docs/superpowers/specs/2026-10-24-value-chain-explorer-design.md` (the explorer spec below):
its build (`arp io build-full`), its definitions (`A`, `L`, `B`, `G`, intensities, node ids, ties, labels,
caveat line) and its anti-goals hold here unchanged.

## Intent

The explorer answers "how is this node connected?". Analysts next ask "what happens if…?": demand for a
sector or region falls by 10%, a supplier region loses a tenth of its primary inputs, a carbon price of
€100/t is levied in the EU. Input-output arithmetic answers each in one matrix-vector product on the
matrices the build already stores. This spec adds three models on that build:

- **Demand shock** (Leontief quantity model): `Δx = L · Δy`.
- **Supply dependency** (Ghosh quantity model): `Δx' = Δv' · G`.
- **Carbon cost-push** (Leontief price model): `Δp' = c' · L`, with `c` the carbon cost per € of output.

## Goals

- Run any of the three models on a set of nodes chosen by node id, region and sector, through the API and
  the screen.
- For the quantity models: output change in M EUR in total, by region, by sector and per node, plus the
  GHG, energy and jobs that go with it.
- For the price model: price change per node, and output-weighted by region and by sector, plus the
  tonnes priced and the carbon cost.
- Every result states its basis (the explorer caveat line) and the model's own linearity caveat.

## Non-goals (this spec)

- Final-demand categories (households, government, investment) as shock targets, and consumer-price
  indices weighted by household baskets. Both need `Y` by category, which the build does not store.
- Exogenous price shocks on a node (e.g. "electricity +20%"), which need a partitioned price model.
- Sector-specific carbon coverage (ETS sector scope), free allocation, border adjustments (CBAM).
- Saving, naming or comparing scenarios; scenarios are a request, nothing is stored.
- Changing the 50-industry tier (spec 1 of the value-chain series), activity/company links and portfolio
  overlays (spec 3), Neo4j and path finding (spec 4).

## Anti-goals

- An LLM anywhere in this feature.
- A result without its basis: every response and view carries the explorer caveat line and the model
  caveat (Definitions).
- Presenting the Ghosh result as lost output. It is labelled a dependency indicator everywhere.
- A shock silently applied to a node whose base is zero or negative: such nodes are listed as skipped.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Compute per request from the stored build.** `y = x − A·x` and `v' = x' − 1'·diag(x)·A` follow exactly from `A` and `x`; each model is one product with the stored `L` or `G`, held in memory by the explorer process already. | No build change, no new files; a request is about 64 M multiply-adds (tens of ms). | **Chosen** |
| B | Extend `build-full` to store `Y` (by category × destination region) and `v`. | Opens final-demand-category shocks; `v` and total `y` are redundant with A, the categories are a non-goal. | Rejected for now; the later spec that needs categories adds `Y` |
| C | POST endpoint with stored, named scenarios. | Saved scenarios nobody asked for; POST needs the analyst role on this router, the explorer is viewer read-only. | Rejected |

**What `build-full` must add: nothing.** EXIOBASE's IOT satisfies `x = Z·1 + Y·1` and `x' = 1'·Z + v'`
(`v` being all `factor_inputs` rows, including taxes less subsidies on products), so both bases derive
from the stored `A` and `nodes.csv`.

**Dependency on the other value-chain specs:** none. This spec reads only the `build-full` output and the
explorer's model code. Spec 1 (full-resolution indirect-exposure tier) neither blocks nor changes it;
spec 3 may later overlay a portfolio on these results.

## Definitions

Notation and float64 arithmetic as in the explorer spec. Only nodes with `x > 0` ("live nodes") are ever
selected, shocked, listed or counted.

- **Final demand** of node `k`: `y_k = x_k − Σ_j A[k,j]·x_j` (M EUR). Can be ≤ 0 (inventory draw-downs).
- **Primary inputs** of node `k`: `v_k = x_k · (1 − Σ_i A[i,k])` (M EUR): value added plus net taxes.
- **Selection**: the union of the live nodes named by `node` (node ids), `region` (region codes: all live
  nodes of that region) and `sector` (sector names as the API shows them: that sector in every region).
  A node named twice counts once.
- **Base** of a selected node: `y_k` for `model=demand`, `v_k` for `model=supply`. Nodes with base ≤ 0
  are **skipped**: not shocked, listed in `skipped`. "Shocked nodes" are the selected nodes not skipped.
- **Shock size**, `unit=pct`: each shocked node gets `change/100 × base_k`. `unit=meur`: the `change`
  (total M EUR) is split over the shocked nodes in proportion to their base, so it equals a uniform
  `pct` of `100 × change / Σ base`, the sum over shocked nodes only. Either way `change_pct` in the response is that uniform percent.
- **Demand**: `Δy_k` as above for shocked nodes, 0 elsewhere; `Δx = L · Δy`.
- **Supply**: `Δv_k` likewise; `Δx_j = Σ_k Δv_k · G[k,j]`.
- **Indicators** of a quantity result: `ghg = Σ_i ghg_t_per_meur_i · Δx_i` (t CO₂e), likewise energy (TJ)
  and jobs (people); a null intensity counts 0.
- **Carbon cost per € of output**: `c_i = τ · ghg_t_per_meur_i / 10⁶` for nodes in covered regions, 0
  elsewhere; `τ` in EUR per t CO₂e; all regions covered when none is given.
- **Price change**: `Δp_j = Σ_i c_i · L[i,j]`, reported as percent `dp_pct_j = 100 · Δp_j`.
- **Priced tonnes**: `Σ_i ghg_t_per_meur_i · x_i` over covered live nodes; **carbon cost** `τ ·` that
  `/ 10⁶` (M EUR).
- **Groups**: quantity results sum `Δx` per region label and per sector name; price results take the
  output-weighted mean `Σ x_j·dp_pct_j / Σ x_j` over the group's live nodes. Groups with value 0 are left
  out; so are node-list entries whose value is 0. Quantity groups and node lists order by absolute value descending; price ones by value
  descending; ties by name (groups) or node id (nodes) ascending. Each list is cut to `top` entries.
- **Model caveats** (exact strings, field `model_caveat`):
  - demand: `Linear Leontief model: fixed input recipes, no substitution, no capacity limits, no price effects.`
  - supply: `Ghosh dependency indicator, not a forecast: downstream output resting on the lost inputs if every buyer keeps its sales shares; no substitution or rerouting.`
  - price: `Leontief cost-push: full pass-through of the carbon cost, no substitution, no demand response; producers' direct emissions only, households' own emissions not priced; basic prices.`

## My calls (owner to confirm with the acceptance table)

1. **GET, not POST**, so the viewer role can run shocks (the router lets viewers use safe methods only).
   Selections are repeated query parameters.
2. **`meur` spreads pro rata to base**, so a set shock in M EUR and in percent are the same mechanism.
3. **All GHG with a GWP100 factor are priced**, CH₄ and N₂O included, as the stored `ghg_t_per_meur` is.
4. **EU-27 preset** on the screen: `AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO
   SE SI SK` (GB excluded). The API takes region codes only.
5. **Change limits**: `pct` from −100 to 100; `meur` any finite non-zero number whose absolute value is at
   most the shocked nodes' total base. `τ` from 0 to 10,000 EUR/t.
6. **Display**: M EUR with one decimal and sign (`−30.2`); indicator tiles with one decimal and unit;
   price changes with two decimals and `%` (`0.06%`); API values unrounded.
7. **Focus node**: both endpoints take an optional `focus` node id and return its own value, so the
   screen can show "this node" next to the totals.

## Constraints

- Each shock request on the real build: at most 1 s on a warm process (the explorer's budget).
- No new files in the build, no change to `build-full` output or to the existing endpoints.
- Repo checks and API contract regeneration as in the explorer spec.

## Left to the builder

Code layout (methods on `ValueChain` or a sibling module), whether `y` and `v` are computed at load or
per request, the screen's component structure, as long as the URLs and rows below hold.

## Appendix B: API (adds to the explorer's Appendix B)

Errors as there (503 not built). Every 200 carries `edition`, `caveat`, `model_caveat`.

- `GET /api/value-chain/shock/quantity?model=demand|supply&node=…&region=…&sector=…&change=-10&unit=pct&top=6&focus=…`
  → `{model, unit, change_pct, total_meur, by_region: [[region_label, Δ]], by_sector: [[sector, Δ]],
  nodes: [{node_id, region_label, sector, delta_meur}], shocked: [{node_id, base_meur, shock_meur}],
  skipped: [node_id], indicators: {ghg, energy, jobs}, focus: {node_id, delta_meur} | null}`.
  `shocked` is ordered by node id. `top` 1–20 cuts `by_region`, `by_sector`, `nodes`. Defaults: `unit`
  `pct`, `top` 6; `model` and `change` are required.
- `GET /api/value-chain/shock/price?carbon_eur_per_t=100&region=…&top=6&focus=…` → `{carbon_eur_per_t,
  covered_regions: [code], priced_t, carbon_cost_meur, by_region: [[region_label, dp_pct]], by_sector:
  [[sector, dp_pct]], nodes: [{node_id, region_label, sector, dp_pct}], focus: {node_id, dp_pct} | null}`.
  `covered_regions` lists every region code covered, in string order. `carbon_eur_per_t` is required,
  `top` defaults to 6.
- `focus` naming an unknown or zero-output node: 422 `unknown node '<id>'`.
- 422 when: no `node`, `region` or `sector` on a quantity request; an unknown or zero-output node id
  (`detail` `unknown node '<id>'`), unknown region code (`unknown region '<code>'`) or unknown sector
  (`unknown sector '<name>'`); `model`, `unit`, `change`, `top` or `carbon_eur_per_t` out of range; every
  selected node skipped (`detail` `no selected node has a positive base`).

## Appendix C: screen

`#/valueChain/<id>/shock`, a fourth view next to node page, tree and footprint, linked from each:

- Model switch `Demand` / `Supply dependency` / `Carbon price`, Demand first.
- Demand and Supply dependency: target `This node` / `All of <region label>` / `<sector> in all regions`
  (default `This node`); change in % (default −10).
- Carbon price: price in EUR per t (default 100); coverage `All regions` / `EU-27` / `<region label> only`
  (default `All regions`).
- Results heading, exactly: `Output change` (Demand), `Dependency indicator: output change` (Supply
  dependency), `Price change` (Carbon price).
- Results: the total (`Δ output <total> M EUR`, or for price `this node <dp>%`), indicator tiles (quantity
  models), by-region and by-sector bars and the top nodes (6 each).
- The model caveat above the results; the explorer caveat line at the foot.

## Acceptance

Fixture F and "F built" as in the explorer spec's Acceptance. For F, live nodes DE.2, DE.3, CN.2, CN.3 have
final demand `y = [60, 160, 70, 60]` and primary inputs `v = [80, 140, 60, 70]`. Numbers are compared
rounded to 4 decimals. `Q` is `GET /api/value-chain/shock/quantity`, `P` is `GET
/api/value-chain/shock/price`. Sector names: `Mining` is `Mining of copper ores and concentrates`, `OBA`
is `Other business activities` (sent URL-encoded in full).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | F built | `Q?model=demand&region=DE&change=-10&unit=pct` | 200; `change_pct` -10; `shocked` `[{DE.2, 60, -6}, {DE.3, 160, -16}]`; `total_meur` -30.1819; `skipped` `[]` | holdout |
| AC-2 | F built | same request | `by_region` `[["DE",-27.798],["CN",-2.3839]]`; `by_sector` `[["Other business activities",-20.9253],["Mining of copper ores and concentrates",-9.2566]]` | holdout |
| AC-3 | F built | same request | `nodes` ids and `delta_meur` exactly, in this order: DE.3 -18.8063, DE.2 -8.9917, CN.3 -2.119, CN.2 -0.2649 | holdout |
| AC-4 | F built | same request | `indicators` `ghg` -45.7955, `energy` -0.8992, `jobs` -299.1701 | holdout |
| AC-5 | F built | `Q?model=demand&region=DE&change=-22&unit=meur` | `change_pct` -10; `total_meur` -30.1819 | holdout |
| AC-6 | F built | `Q?model=demand&node=DE.3&change=-2&unit=meur` | `total_meur` -2.8218; `indicators.ghg` -1.4955 (the negative of explorer AC-15's footprint total); `indicators.jobs` -27.9004 | holdout |
| AC-7 | F built | `Q?model=demand&sector=OBA&change=-10&unit=pct` | `shocked` ids `["CN.3","DE.3"]`; `total_meur` -31.1566; `by_region` `[["DE",-21.2396],["CN",-9.917]]` | holdout |
| AC-8 | F built | `Q?model=demand&node=DE.3&region=DE&change=-10&unit=pct` | `shocked` ids exactly `["DE.2","DE.3"]` (DE.3 counted once); `total_meur` -30.1819 | holdout |
| AC-9 | F built | `Q?model=supply&node=DE.2&change=-10&unit=pct` | `shocked` `[{DE.2, 80, -8}]`; `total_meur` -12.5446; `nodes`, in this order: DE.2 -9.0129, DE.3 -2.232, CN.3 -1.0313, CN.2 -0.2684 | holdout |
| AC-10 | F built | `Q?model=supply&node=CN.2&change=-10&unit=pct` | `by_region` `[["CN",-8.4655],["DE",-0.2013]]`; `indicators.jobs` -10.4891 | holdout |
| AC-11 | F built | AC-1, AC-9 and AC-15 requests | `model_caveat` is exactly the demand, supply and price string of Definitions respectively; each has `edition` `exiobase-IOT_2022_ixi` and the explorer caveat C | holdout |
| AC-12 | F built | `Q?model=demand&node=DE.3&change=-10&unit=pct&focus=CN.3` | `focus` `{"node_id": "CN.3", "delta_meur": -2.0343}` | holdout |
| AC-13 | F built | `Q?model=demand&region=DE&change=-10&unit=pct&top=1` | `by_region`, `by_sector` and `nodes` each have exactly 1 entry: `DE`, `Other business activities`, `DE.3` | holdout |
| AC-14 | F built | each of `Q?model=demand&change=-10&unit=pct` (no selection), `Q?model=demand&node=DE.1&change=-10`, `Q?model=demand&region=FR&change=-10`, `Q?model=demand&sector=Fishing&change=-10`, `Q?model=foo&node=DE.2&change=-10`, `Q?model=demand&node=DE.2&change=-101&unit=pct`, `Q?model=demand&node=DE.2&change=-61&unit=meur`, `Q?model=demand&node=DE.2&change=-10&unit=pct&top=21`, `Q?model=demand&node=DE.2&change=-10&unit=foo`, `Q?model=demand&node=DE.2&change=-10&unit=pct&top=0`, `Q?model=demand&node=DE.2&change=0&unit=meur`, `Q?model=demand&node=DE.2&change=nan&unit=meur`, `Q?model=demand&node=DE.2&unit=pct` (no change), `P?carbon_eur_per_t=100&focus=DE.1`, `P?carbon_eur_per_t=-1`, `P?carbon_eur_per_t=10001`, `P?carbon_eur_per_t=100&region=FR` | each 422; the second's `detail` is `unknown node 'DE.1'`, the third's `unknown region 'FR'`, the fourth's `unknown sector 'Fishing'`; `P?carbon_eur_per_t=100&focus=DE.1` gives `unknown node 'DE.1'` and `P?carbon_eur_per_t=100&region=FR` gives `unknown region 'FR'` | holdout |
| AC-15 | F built | `P?carbon_eur_per_t=100` | `covered_regions` `["CN","DE"]`; `priced_t` 627; `carbon_cost_meur` 0.0627; `nodes` DE.2 0.0564, CN.2 0.0148, CN.3 0.0109, DE.3 0.0075 (`dp_pct`, in that order) | holdout |
| AC-16 | F built | same request | `by_region` `[["DE",0.0238],["CN",0.0129]]`; `by_sector` `[["Mining of copper ores and concentrates",0.0356],["Other business activities",0.0086]]` | holdout |
| AC-17 | F built | `P?carbon_eur_per_t=100&region=DE&focus=CN.2` | `covered_regions` `["DE"]`; `priced_t` 500; `carbon_cost_meur` 0.05; `by_region` `[["DE",0.0234],["CN",0.0041]]`; `focus.dp_pct` 0.0017 | holdout |
| AC-18 | F built | `P?carbon_eur_per_t=0` | 200; `priced_t` 627; `carbon_cost_meur` 0; `nodes`, `by_region`, `by_sector` all `[]` | holdout |
| ~~AC-19~~ | | | retired before approval: duplicate of AC-1's `skipped` check | |
| AC-20 | Fixture F2: F with CN.3's `Z` row `[0,40,10,60]` (`y` of CN.3 = -10; the table is deliberately unbalanced and `arp io build-full` accepts it, as it runs no balance check) | `Q?model=demand&node=DE.2&node=CN.3&change=-10&unit=pct` | `skipped` `["CN.3"]`; `shocked` ids `["DE.2"]` | holdout |
| AC-21 | F2 built | `Q?model=demand&node=CN.3&change=-10&unit=pct` | 422, `detail` `no selected node has a positive base` | holdout |
| AC-22 | `ARP_VALUE_CHAIN_DIR` unset | `Q?model=demand&node=DE.2&change=-10` and `P?carbon_eur_per_t=100` | each 503 with the explorer's not-built `detail` | holdout |
| AC-23 | `ARP_ANTHROPIC_API_KEY` unset | AC-1 to AC-22 | all pass | holdout |
| AC-23b | `ARP_ANTHROPIC_API_KEY` set to an invalid key (any model call fails) | AC-1 to AC-22 | all pass | holdout |
| AC-23c | F built | `Q?model=demand&node=DE.2&change=-10` (no `unit`, no `top`) | 200; `change_pct` -10 | holdout |
| AC-23d | F2 built | `Q?model=demand&node=DE.2&node=CN.3&change=-30&unit=meur` | `change_pct` -50; `shocked` `[{DE.2, 60, -30}]`; `skipped` `["CN.3"]` | holdout |
| AC-24 | Real `IOT_2022_ixi.zip` built (explorer AC-26) | `Q?model=demand&node=<id of Manufacture of electrical machinery and apparatus n.e.c. · CN>&change=-1&unit=meur` | `indicators.ghg` rounds to -973.9 (the explorer's AC-32 footprint, negated) | evaluator |
| AC-25 | as AC-24, warm process | for 10 seeded random live nodes: `Q?model=demand&region=<its region>&change=-10`, `Q?model=supply&sector=<its sector>&change=-10`, `P?carbon_eur_per_t=100` with the EU-27 regions | each answers in ≤ 1.0 s wall-clock from a localhost client | evaluator |
| AC-26 | as AC-24 | open `#/valueChain/<id>/shock` for that node | `Demand` selected, target `This node`, change `-10`; the page shows `Δ output <v> M EUR`, `<v>` being `total_meur` of `Q?model=demand&node=<id>&change=-10&unit=pct` with one decimal and its sign; the demand model caveat; at the foot the explorer caveat line | evaluator |
| AC-27 | as AC-26 | pick `Supply dependency` | the model switch reads `Supply dependency`; the results heading reads `Dependency indicator: output change`; the model caveat reads exactly the supply string of Definitions; no heading or label on the view contains `forecast` other than that caveat | evaluator |
| AC-28 | as AC-26 | pick `Carbon price`, coverage `EU-27`, price 100 | the request sent has 27 `region` parameters, the codes of My call 4 | evaluator |
| AC-29 | as AC-26 | pick target `All of CN` | the total equals that of `Q?model=demand&region=CN&change=-10&unit=pct`, shown with one decimal | evaluator |
| AC-30 | as AC-24 | open the node page, tree and footprint views | each links to the Shocks view of the same node | evaluator |
| AC-30b | as AC-26 | pick target `Manufacture of electrical machinery and apparatus n.e.c. in all regions` | the total equals `total_meur` of `Q?model=demand&sector=Manufacture of electrical machinery and apparatus n.e.c.&change=-10&unit=pct`, one decimal | evaluator |
| AC-30c | as AC-26 | read the GHG tile | it reads `<indicators.ghg of the AC-26 request, one decimal> t CO₂e` | evaluator |
| AC-30d | as AC-26 | pick `Carbon price`, coverage `All regions`, price 100 | the total reads `this node <d>%`, `<d>` being `focus.dp_pct` of `P?carbon_eur_per_t=100&focus=<id>` with two decimals; by-region and by-sector bars show 6 entries each | evaluator |
| AC-30e | as AC-30d | pick coverage `CN only` | the request sent has exactly one `region` parameter, `CN` | evaluator |

Must not change:
- AC-31: every row of the explorer spec's Acceptance (AC-1 to AC-41) still passes. Checked by: holdout
  (its holdout rows) and evaluator (its evaluator rows).
- AC-32: the files `arp io build-full` writes for fixture F are byte-identical to `main`'s, apart from
  `built_at` in `manifest.json`. Checked by: holdout.
