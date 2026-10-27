# Value-chain links and portfolio overlays

Status: draft for owner approval, 2026-10-27. Owner decisions on 2026-10-27:

- A company's link may be spec 1's default (ICIO code + country), a revenue split over several ICIO codes,
  or an explicit node override.
- The LLM may only pick a missing ICIO code, as it does today. Every node, weight and overlay number is
  arithmetic.
- Footprint per € invested is EVIC-attributed.
- The feature ships as an API plus a fifth "Portfolio" view in the Value Chain Explorer.
- Links are stored as rules and resolved on every request (approach A).
- Revenue splits are entered by an analyst or imported from a CSV.
- Overlays connect to shocks as a portfolio lens on spec 2's results.
- Links drive the overlay and the shocks lens only. The indirect-exposure tier keeps spec 1's numbers.
- Activity links can be viewed and overridden.

Third of four value-chain specs: (1) indirect-exposure tier on the full build
(`2026-10-26-io-full-resolution-tier-design.md`, "spec 1"), (2) shocks
(`2026-10-26-value-chain-shocks-design.md`, "spec 2"), (3) this, (4) Neo4j summary graph and path finder.
Builds on the explorer spec (`2026-10-24-value-chain-explorer-design.md`): its build, definitions
(`A`, `L`, intensities, node ids, labels, ties, caveat line) and anti-goals hold here unchanged. Needs spec 1
merged: it reuses spec 1's code list, sector map, country → region file and company node set.

## Intent

The explorer shows how a node connects to the world economy. Analysts want the same view of what they
own: which nodes a portfolio's companies sit on, how much of the portfolio's supply chain runs through
each region and sector, and what one euro invested carries in carbon, energy and jobs along the whole
chain. That needs two things. First, a link from each company (and each taxonomy activity) to nodes, one
an analyst can correct and that survives a new EXIOBASE edition. Second, a portfolio overlay that
weights those nodes by holdings.

## Goals

- Every company and taxonomy activity resolves to a weighted set of nodes, with the source of that
  link stated (`nodes`, `split`, `code`, `llm`, `none`).
- An analyst can replace a company's link with a revenue split over ICIO codes or with explicit nodes,
  and an activity's with explicit nodes, through the API, a CSV import (splits) and the screen. Rules
  are stored as region codes, EXIOBASE sector names and ICIO codes, never node ids, so they survive a
  new edition.
- For a portfolio on a date: holdings as weighted nodes, the share of NAV linked, the direct region mix,
  the upstream exposure by region, sector and node, the EVIC-attributed footprint per M EUR invested,
  and optionally its weight in one taxonomy activity's nodes.
- Spec 2's shock endpoints take an optional portfolio and report its holding-weighted output or
  price change.

## Non-goals

- Changing the indirect-exposure tier: theme runs, taxonomy research and the standards mapper keep
  computing on spec 1's code + country mapping and ignore stored rules.
- Sovereign, fund look-through, cash or derivative holdings: a holding without a `company_id` is unlinked.
- A list of the companies linked to a node, or a graph of links (spec 4).
- Deriving revenue splits from the revenue catalogue or from theme-run revenue exposure.
- Shocking "the portfolio's nodes" as a shock target. Selections stay node, region and sector, as in
  spec 2.
- Storing overlay results, or comparing portfolios or dates.

## Anti-goals

- An LLM anywhere but choosing a missing ICIO code from the closed list. That runs only as an explicit
  command (Scope 6), never inside a GET, and its result is labelled `llm`.
- A node id in stored data. A rule that no longer resolves in a new edition is reported as `unresolved`
  and is never silently dropped.
- An overlay figure without its coverage. Every response states the share of NAV linked and the share
  attributed, and lists every holding with its link source.
- Rewriting a company's own `isic_code` or `country` from a link rule.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Rules, resolved live.** Store per subject one rule (split over ICIO codes, explicit region + sector parts, or an LLM-chosen code) and resolve it against the current build on each request, falling back to spec 1's code + country mapping. | Edition-proof by construction, nothing to rebuild after a new build; resolution is a few dictionary lookups per holding. | **Chosen** |
| B | Materialise company → node weights per edition with a job after each `build-full`. | Fast reads; a second stored artefact that goes stale and must be rebuilt per edition. | Rejected |
| C | Store node ids directly. | Simplest; breaks on the next edition, which the dispatcher ruled out. | Rejected |

## Definitions

Arithmetic, node ids, labels, ties and live nodes (`x > 0`) as in the explorer spec. `codes`, the
sector map (ICIO code → EXIOBASE sectors) and the region of a country (`country_exiobase_region.csv`,
"region `R`, or none") as in spec 1.

- **Code node set** of ICIO code `c` in region `R`: the live nodes whose sector `c` covers, in `R` (in every
  region when `R` is none), each weighted by `x / Σ x` over the set. This is spec 1's company set `K`
  with weights `w`.
- **Rules** (one per subject at most; saving replaces the previous one):
  - `split`: parts `[{icio_code, share}]`.
  - `nodes`: parts `[{region, sector, share}]`; `sector` is the sector name as the explorer API shows it.
  - `llm`: one `icio_code`, written by Scope 6 only.
- **Company resolution**, first match wins:
  1. A `nodes` rule. Each part resolves to the live node with that region code and sector name. If no
     such node exists, the part is `unresolved`.
  2. A `split` rule, in the company's region `R`. Each part contributes `share × w` over its code node
     set. If that set is empty, the part is `unresolved`.
  3. The company's own `isic_code`, mapped to a code without an LLM by spec 1's deterministic lookup (in
     `codes`, else one exact ISIC-division or NACE-class match). Its code node set in `R`, share 1.
     Source `code`.
  4. An `llm` rule. The same as 3 on the rule's code. Source `llm`.
  5. Otherwise source `none`, with no nodes.

  When parts are unresolved, the resolved parts' weights are scaled to sum to 1. When every part is
  unresolved, the company has no nodes and keeps its source.
- **Activity resolution**: a `nodes` rule as in company step 1. Otherwise source `code`: the live nodes
  whose sector any of the activity's `core_isic_codes` covers, in every region, weighted by `x / Σ x`
  over that set. Codes not in `codes` are ignored. With no node, source `none`.
- **Linked node weights** `w_h` of holding `h`: its company's resolved weights (each node appears once,
  weights of duplicates summed). A holding is **linked** when `w_h` is not empty.
- **Weights**: NAV = `Σ market_value_eur` over all holdings of the snapshot; `weight_h = mv_h / NAV`.
  Portfolio node weights `W = Σ_h weight_h · w_h` over linked holdings. `linked_weight = Σ W`.
- **Direct region mix**: `W` summed by region label.
- **Upstream**: `w̄ = W / linked_weight`; `u = L · w̄ − w̄`, in € from each node per € of the linked
  holdings' output mix. `upstream_total = Σ u`; grouped by region label and by sector name.
- **Attribution**: holding `h` is attributed when it is linked and its company has numeric values
  `evic` (`climate_evic_eur_m`) and `revenue` (`climate_revenue_eur_m`, new, Scope 7) resolved as of the
  snapshot date, with `evic > 0`. Then its owned output is `o_h = (mv_h / 10⁶) / evic × revenue` (M EUR).
  `attributed_weight = Σ weight_h` over attributed holdings.
- **Footprint**, indicator `s` (`ghg`, `energy`, `jobs`, intensities as in the explorer, null counts 0):
  the contribution of node `i` is `Σ_h s_i · (L · w_h)_i · o_h` over attributed holdings. `total` is
  the sum of the contributions. `per_meur_invested = total / Σ_h (mv_h / 10⁶)` over attributed holdings,
  null when none is attributed. `by_region` sums the contributions by region label.
- **Activity overlay** of activity `a` with node set `N_a`: `direct_weight = Σ_{n∈N_a} W_n` (share of
  NAV); `upstream_share = Σ_{i∈N_a} u_i / upstream_total` (null when `upstream_total` is 0).
- **Shock lens** (spec 2's results `Δx` or `dp_pct` per node):
  - quantity models: `change_pct = 100 · Σ_n W_n · Δx_n / x_n / linked_weight`;
  - price model: `dp_pct = Σ_n W_n · dp_pct_n / linked_weight`.

  Both are null when `linked_weight` is 0.
- **Lists**: groups whose value is 0 are left out. Lists are ordered by value descending, with ties by
  name (groups) or node id (nodes) ascending, and cut to `top` entries. Holdings are ordered by
  `weight` descending, ties by `security_id`, and are never cut.

## Scope

1. **Rule store.** Rules live next to companies, in both portfolio-store backends (JSON files and
   Postgres). Subjects are `company:<company_id>` and `activity:<taxonomy_id>/<activity_id>`. Each
   rule records its parts, `set_by` (principal name, or `llm`) and `set_at`. Deleting a rule
   returns the subject to its default.
2. **Validation on save** (API and CSV), against the current build and the spec 1 model:
   - 1 to 20 parts, with no part named twice;
   - every share > 0, and the shares sum to 1 within 1e-6;
   - every `icio_code` is in `codes`;
   - every `nodes` part names a live node of the current build.
   A `split` is for companies only.
3. **API** under `/api/value-chain` (Appendix B). GET is open to viewers. PUT and DELETE need the analyst
   role, as every write in this app does.
4. **CSV import.** `arp io links import <csv>` takes header `company_id,icio_code,share`, with one
   split per company built from its rows. Each company is validated as in 2 and saved as a `split`
   rule. stdout: `<n> companies linked, <m> rejected`. For each rejected company, stderr gets one line
   `<company_id>: <detail>`, with the detail exactly as the API's 422. Exit 0 when none is rejected,
   else 1; valid companies are saved either way. A `company_id` not in the store is rejected with
   `unknown company '<id>'`.
5. **Overlay** `GET /api/value-chain/portfolio/{portfolio_id}` (Appendix B) on the snapshot as of `as_of`
   (default: the portfolio's latest snapshot date).
6. **LLM classification.** `arp io links classify --portfolio <id> [--as-of <date>]` runs
   `resolve_company_isic` (spec 1) on every company held at that date whose resolution is `none`. It
   stores each code it gets as an `llm` rule. stdout: `<n> classified, <m> left unlinked`. Its function
   form is `await classify_unlinked(store, portfolio_id, as_of, model, llm) -> (classified, unlinked)`
   in `arp.research.value_chain.links`.
7. **Revenue field.** `climate_revenue_eur_m` ("Total revenue", NUMBER, unit `EUR M`, `required=False`)
   joins the fields of `sch_climate_core_v1`, next to `climate_evic_eur_m`. It resolves through the same
   data-point cascade.
8. **Shocks lens.** Spec 2's `shock/quantity` and `shock/price` take optional `portfolio` and `as_of`
   (Appendix B). Without `portfolio`, the response's `portfolio` field is null and nothing else changes.
9. **Screen** (Appendix C): a fifth view, "Portfolio", with the link editor; a portfolio picker on the
   Shocks view.

## My calls (owner to confirm with the acceptance table)

1. **Precedence: analyst rules, then the company's own code, then the LLM.** An analyst override always
   wins. The company's stored `isic_code` beats an earlier LLM guess, so fixing the code on the company
   needs no rule cleanup.
2. **Unresolved parts renormalise and are listed.** A split part whose code has no output in the
   company's region, or a node part missing in a new edition, drops out. The rest are scaled to sum to 1
   and the dropped part is returned in `unresolved`. So the overlay keeps working across editions, and
   the gap is visible.
3. **Weights are shares of NAV.** `W` sums to `linked_weight`, not 1, so unlinked holdings (cash, bonds,
   unknown companies) show as a gap rather than being spread over the rest. Upstream and footprint are
   then computed on the linked part only, as their definitions say.
4. **Footprint is supply-chain** (`s · L`, which includes the node's own direct intensity), so it is the
   EXIOBASE estimate of scope 1 + 2 + upstream scope 3. It is computed only for attributed holdings. The
   reported company scope 1 and 2 used by `compute_financed_emissions` are not mixed in.
5. **A new revenue field** rather than reusing carbon intensity, which is per revenue but does not give
   revenue. Adding it as an optional field adds a `climate_revenue_eur_m` column to `GET
   /api/portfolio/esg/template`.
6. **Activities are identified by taxonomy and activity id** on the latest taxonomy version. A rule
   keyed by them survives new taxonomy versions as long as the activity id stays.
7. **Display**: weights and shares as percent with one decimal (`55.0%`); upstream in cents per euro with
   one decimal (`15.4¢`), as in the explorer; footprint per M EUR with one decimal and unit (`2.2 t CO₂e
   per M EUR invested`); the lens as percent with two decimals (`−8.23%`). The API returns unrounded
   values.

## Constraints

- float64, nothing rounded before display.
- Real build (7,987 nodes), a portfolio of 500 holdings: overlay ≤ 2 s and shock with `portfolio` ≤ 1.5 s
  on a warm process.
- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`; API contract regenerated
  (`scripts/export_openapi.py`, `npm run gen:api`), each new `request<T>()` in `frontend/src/api/contract.ts`.
- The Postgres rule table is a schema migration, so the implementation PR is `risk:high`.

## Left to the builder

Rule storage layout and the Postgres table, module layout (beyond Scope 6's function), how `L · w`
is computed (one product per holding or batched), and the screen's component structure, as long as the
URLs in Appendix C work.

## How this connects to specs 2 and 4

- **Spec 2:** the lens reads spec 2's per-node results unchanged and adds one field. A later spec can
  make "the portfolio's nodes" a shock selection from the same `W`.
- **Spec 4:** resolved links are what a summary graph would draw as `HOLDS` or `LINKED_TO` edges, derived
  on load and never stored as node ids.

## Appendix B: API

Not built: 503 as in the explorer. Every 200 carries `edition` and `caveat`.

- `GET /links/company/{company_id}` → `{subject, source, region, nodes: [{node_id, region_label,
  sector, weight}], unresolved: [part], rule: {kind, parts, set_by, set_at} | null}`. `region` is the
  company's region `R` or null. `nodes` is ordered by weight descending, ties by node id. Unknown
  company: 404 `unknown company '<id>'`.
- `PUT /links/company/{company_id}` body `{kind: "split" | "nodes", parts: [...]}` → 200 with the GET
  body after saving. 422 `detail`, checked in this order:
  - `1 to 20 parts`
  - `duplicate part`
  - `share must be > 0`
  - `shares must sum to 1`
  - `unknown code '<c>'`
  - `unknown node '<region> · <sector>'`
- `DELETE /links/company/{company_id}` → 204. Deleting when no rule exists is also 204.
- `GET|PUT|DELETE /links/activity/{taxonomy_id}/{activity_id}`: the same, with `kind` `nodes` only
  (`split` → 422 `split is for companies only`) and `region` always null. Unknown taxonomy or
  activity: 404 `unknown activity '<taxonomy_id>/<activity_id>'`.
- `GET /portfolio/{portfolio_id}?as_of=&indicator=ghg&top=6&taxonomy=&activity=` returns:
  - `portfolio_id`, `as_of`, `nav_eur`, `linked_weight`, `attributed_weight`;
  - `holdings: [{security_id, company_id, name, market_value_eur, weight, link_source, top_node:
    {node_id, region_label, sector, weight} | null, owned_output_meur | null}]`;
  - `nodes: [{node_id, region_label, sector, weight}]`, `direct_by_region: [[region_label, weight]]`;
  - `upstream_total`, `upstream_by_region`, `upstream_by_sector`, `upstream_nodes`;
  - `footprint: {indicator, unit, total, per_meur_invested, by_region}`;
  - `activity: {taxonomy_id, activity_id, name, direct_weight, upstream_share} | null`.

  Field meanings:
  - `link_source` is the resolution source, or `none` for a holding without `company_id`.
  - `top_node` is the holding's largest node weight.
  - `name` is the security name.
  - `top` (1–20) cuts `nodes`, `upstream_nodes` and the `by_*` lists; holdings are never cut.
  - `indicator` and `unit` work as in the explorer footprint.
  - `taxonomy` and `activity` are given together or not at all; only one of them → 422.

  Errors:
  - unknown portfolio: 404 `unknown portfolio '<id>'`;
  - no snapshot on `as_of`: 404 `no holdings for '<id>' on <as_of>`;
  - unknown activity: 404 as above.
- Spec 2's `GET /shock/quantity` and `GET /shock/price` take `portfolio` and `as_of` (same defaults and
  404s as the overlay). They add `portfolio: {portfolio_id, as_of, linked_weight, change_pct}` (quantity)
  or `{portfolio_id, as_of, linked_weight, dp_pct}` (price), and `portfolio: null` without the
  parameter. `as_of` without `portfolio` → 422.

## Appendix C: screen

- `#/valueChain/portfolio`: a portfolio picker (from `GET /api/portfolio/portfolios`) and a snapshot
  date (default latest), with the text `Pick a portfolio.` until one is chosen. The explorer's other
  views link to it as `Portfolio`.
- `#/valueChain/portfolio/<portfolio_id>`:
  - a coverage line, exactly `Linked <linked>% of NAV · footprint covers <attributed>%`;
  - a footprint tile `<per> <unit> per M EUR invested` with the CO₂e/Energy/Jobs switch (CO₂e first),
    or `—` when null;
  - bars, 6 each: direct region mix, upstream by region, upstream by sector;
  - the holdings table: name, weight, link source, top node, `Edit link`;
  - an `Activity` picker (taxonomy, then activity), which adds the line `<activity name>: <direct>% of
    NAV directly · <upstream>% of upstream` and its own `Edit link`.
- **Link editor** (panel opened by `Edit link`):
  - modes `Default`, `Revenue split` (companies only) and `Nodes`;
  - split rows: an ICIO code picker (the 50 codes plus the five split codes) and a share in %;
  - node rows: the explorer's search picker and a share in %;
  - `Save` sends PUT and `Reset to default` sends DELETE; a 422 `detail` shows under the rows;
  - after saving, the overlay reloads;
  - the editor shows the current source and any `unresolved` parts as `Not in this edition: <part>`.
- **Shocks view**: a `Portfolio` picker (default none). When one is chosen, the results add `Portfolio
  output change <change>%` (quantity models) or `Portfolio price change <dp>%` (price).
- The caveat line at the foot, as on every explorer view.

## Acceptance

**Fixture V** and "V built" as in spec 1's Acceptance. Sector names as the explorer shows them:
`Copper` = `Mining of copper ores and concentrates`, `Nickel` = `Mining of nickel ores and concentrates`,
`Wind` = `Production of electricity by wind`, `Machinery` = `Manufacture of electrical machinery and
apparatus n.e.c.`. Region labels: `DE`, `CN`, `RoW Asia-Pacific` (WA). GHG intensities in V (t/M EUR):
CN.1 1, CN.4 5, DE.4 2, WA.1 0.45, others 0.

**Fixture V′**: V with sectors 1 and 2 swapped in the archive (Nickel first, Copper second), with every
flow, output and satellite value moved with its sector. So V's `WA.1` is V′'s `WA.2`.

**Fixture V−WA**: V without region `WA` (its outputs, flows, final demand and satellite values removed).

**Store S** (portfolio store, either backend):
- companies, as `CompanyRef`:
  - `cm`: country `CN`, `isic_code` `C27`;
  - `sx`: country `CN`, `isic_code` `C27`;
  - `nx`: country `DE`, no code;
  - `us`: country `US`, `isic_code` `C27`;
  - `dz`: country `DE`, no code;
- securities `s_cm`, `s_sx`, `s_nx` with the company of the same suffix, and `s_cash` with no company;
- portfolio `P`, one snapshot on `2026-09-30` with `market_value_eur`: `s_cm` 400,000, `s_sx` 300,000,
  `s_nx` 200,000, `s_cash` 100,000;
- observations dated `2026-09-01`, source `internal_api`: `cm` evic 100 and revenue 50; `sx` evic 60
  and revenue 30; none for `nx`;
- taxonomy `T` with activity `a1` (name `Copper and nickel mining`, `core_isic_codes` `["B07"]`).

"S linked" means S plus:
- `PUT …/links/company/sx` `{"kind": "split", "parts": [{"icio_code": "C27", "share": 0.5},
  {"icio_code": "B07", "share": 0.5}]}`;
- `PUT …/links/company/nx` `{"kind": "nodes", "parts": [{"region": "WA", "sector": "<Copper>",
  "share": 1}]}`.

`O` is `GET /api/value-chain/portfolio/P`. Numbers are compared rounded to 4 decimals. Requests are made
as an analyst unless a row says otherwise.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | V built, S | `GET /api/value-chain/links/company/cm` | 200; `source` `code`; `region` `CN`; `nodes` exactly `[{CN.4, weight 1}]`; `unresolved` `[]`; `rule` null | holdout |
| AC-2 | V built, S linked | `GET …/links/company/sx` | `source` `split`; `nodes` node ids and weights in order: CN.4 0.5, CN.1 0.3571, CN.2 0.1429; `rule.kind` `split` | holdout |
| AC-3 | V built, S linked | `GET …/links/company/nx` | `source` `nodes`; `region` `DE`; `nodes` exactly `[{WA.1, 1}]` with `sector` `<Copper>`, `region_label` `RoW Asia-Pacific` | holdout |
| AC-4 | V built, S | `GET …/links/company/us` (no `US` nodes in V) | `source` `code`; `region` null; `nodes` in order: CN.4 0.6154, DE.4 0.3077, WA.4 0.0769 | holdout |
| AC-5 | V built, S | `GET …/links/company/dz` | 200; `source` `none`; `nodes` `[]` | holdout |
| AC-6 | V built, S | `PUT …/links/company/dz` `{"kind":"split","parts":[{"icio_code":"A01","share":0.4},{"icio_code":"C27","share":0.6}]}` | 200; `nodes` exactly `[{DE.4, 1}]`; `unresolved` `[{"icio_code":"A01","share":0.4}]` | holdout |
| AC-7 | V built, S | `PUT …/links/company/dz` with split parts B07 0.5 and `D_GEN_REN` 0.5 | `nodes` in order: DE.1 0.5, DE.3 0.5 (DE.2 has no output) | holdout |
| AC-8 | V built, S | `PUT …/links/company/dz`, in turn, with: 0 parts; parts C27 0.5 twice; C27 share 0 and B07 share 1; C27 0.5 and B07 0.4; `ZZ` 1; kind `nodes` with region `DE`, sector `<Nickel>` (DE.2 has no output), share 1 | 422 each, `detail` in turn: `1 to 20 parts`, `duplicate part`, `share must be > 0`, `shares must sum to 1`, `unknown code 'ZZ'`, `unknown node 'DE · Mining of nickel ores and concentrates'` | holdout |
| AC-9 | V built, S linked, as a viewer | `PUT …/links/company/cm` with a valid split; then `GET …/links/company/cm` | PUT 403; GET 200 | holdout |
| AC-10 | V built, S linked | `DELETE …/links/company/sx`; then GET it | 204; then `source` `code`, `nodes` exactly `[{CN.4, 1}]`, `rule` null | holdout |
| AC-11 | V built, S linked | `GET …/links/company/zz` | 404 `unknown company 'zz'` | holdout |
| AC-12 | S linked, then V′ built in place of V | `GET …/links/company/nx` | `nodes` exactly `[{WA.2, 1}]` with `sector` `<Copper>` | holdout |
| AC-13 | S linked, then Fixture V−WA built in place of V | `GET …/links/company/nx` | 200; `nodes` `[]`; `unresolved` `[{"region":"WA","sector":"<Copper>","share":1}]`; `source` `nodes` | holdout |
| AC-14 | V built, S | `GET …/links/activity/T/a1` | `source` `code`; `region` null; `nodes` in order: CN.1 0.3704, WA.1 0.2222, DE.1 0.1852, CN.2 0.1481, WA.2 0.0741 | holdout |
| AC-15 | V built, S | `PUT …/links/activity/T/a1` `{"kind":"nodes","parts":[{"region":"CN","sector":"<Copper>","share":1}]}`; then `PUT` with kind `split` | first 200 with `nodes` exactly `[{CN.1, 1}]`, `source` `nodes`; second 422 `split is for companies only` | holdout |
| AC-16 | V built, S | `GET …/links/activity/T/zz` | 404 `unknown activity 'T/zz'` | holdout |
| AC-17 | V built, S linked | `O` | `as_of` `2026-09-30`; `nav_eur` 1000000; `linked_weight` 0.9; `attributed_weight` 0.7 | holdout |
| AC-18 | as AC-17 | `O` | `holdings` in order: s_cm (`weight` 0.4, `link_source` `code`, `top_node` CN.4 weight 1, `owned_output_meur` 0.2), s_sx (0.3, `split`, CN.4 0.5, 0.15), s_nx (0.2, `nodes`, WA.1 1, null), s_cash (0.1, `none`, null, null) | holdout |
| AC-19 | as AC-17 | `O` | `nodes` in order: CN.4 0.55, WA.1 0.2, CN.1 0.1071, CN.2 0.0429; `direct_by_region` `[["CN",0.7],["RoW Asia-Pacific",0.2]]` | holdout |
| AC-20 | as AC-17 | `O` | `upstream_total` 0.2504; `upstream_by_region` `[["CN",0.1543],["RoW Asia-Pacific",0.0592],["DE",0.0368]]` | holdout |
| AC-21 | as AC-17 | `O` | `upstream_by_sector` `[["<Copper>",0.099],["<Machinery>",0.0678],["<Wind>",0.0525],["<Nickel>",0.0311]]`; `upstream_nodes` ids in order `CN.1, CN.3, WA.1, DE.4, CN.2, WA.4` with values 0.0637, 0.0493, 0.0336, 0.032, 0.0311, 0.0256 | holdout |
| AC-22 | as AC-17 | `O` (indicator default) | `footprint` `indicator` `ghg`, `unit` `t CO₂e`, `total` 1.5154, `per_meur_invested` 2.1648, `by_region` `[["CN",1.4802],["DE",0.0288],["RoW Asia-Pacific",0.0064]]` | holdout |
| AC-23 | as AC-17 | `O?indicator=jobs` | `footprint.total` 0; `footprint.by_region` `[]` | holdout |
| AC-24 | as AC-17 | `O?taxonomy=T&activity=a1` | `activity` `{taxonomy_id T, activity_id a1, name "Copper and nickel mining", direct_weight 0.35, upstream_share 0.5193}`; without the parameters `activity` null | holdout |
| AC-25 | as AC-17 | `O?taxonomy=T`; `O?as_of=2026-01-01`; `GET …/portfolio/ZZ` | 422; 404 `no holdings for 'P' on 2026-01-01`; 404 `unknown portfolio 'ZZ'` | holdout |
| AC-26 | V built, S (no rules) | `O` | `linked_weight` 0.7 (`s_nx` and `s_cash` unlinked); holdings row s_nx `link_source` `none` | holdout |
| AC-27 | V built, S linked, observations for `cm` dated `2026-10-15` instead | `O` | `attributed_weight` 0.3; s_cm `owned_output_meur` null | holdout |
| AC-28 | V built, S linked | spec 2 `GET /api/value-chain/shock/quantity?model=demand&region=CN&change=-10&portfolio=P` | `portfolio` `{portfolio_id P, as_of 2026-09-30, linked_weight 0.9, change_pct -8.2277}`; `total_meur` -64.2658 | holdout |
| AC-29 | as AC-28 | `…/shock/quantity?model=supply&region=CN&change=-10&portfolio=P` | `portfolio.change_pct` -7.1757 | holdout |
| AC-30 | as AC-28 | `…/shock/price?carbon_eur_per_t=100&portfolio=P` | `portfolio.dp_pct` 0.0347 | holdout |
| AC-31 | as AC-28 | the AC-28 request without `portfolio`; then with `as_of=2026-09-30` and no `portfolio` | first: `portfolio` null and every other field equal to the AC-28 response's; second: 422 | holdout |
| AC-32 | V built, S; CSV `company_id,icio_code,share` with rows `sx,C27,0.5` `sx,B07,0.5` `dz,C27,0.7` `zz,C27,1` | `arp io links import <csv>` | exit 1; stdout `2 companies linked, 2 rejected`; stderr lines `dz: shares must sum to 1` and `zz: unknown company 'zz'`; then `GET …/links/company/sx` `source` `split` | holdout |
| AC-33 | V built, S; stub `llm` as in spec 1's lookup rows but returning `isic_code` `C27` | `await classify_unlinked(store, "P", "2026-09-30", model, llm)` | returns `(1, 0)`; the stub recorded exactly 1 call, for `nx`; then `GET …/links/company/nx` `source` `llm`, `nodes` exactly `[{DE.4, 1}]`, `rule.set_by` `llm` | holdout |
| AC-34 | as AC-33, then `PUT` `nx` back to S linked's `nodes` rule, and `cm` keeps its `isic_code` | `classify_unlinked` again | returns `(0, 0)`; 0 stub calls | holdout |
| AC-35 | V built, S; an `llm` rule `B07` stored for `cm` | `GET …/links/company/cm` | `source` `code` (company `isic_code` `C27` beats `llm`); `nodes` `[{CN.4, 1}]` | holdout |
| AC-36 | — | `GET /api/portfolio/esg/template` | the template includes column `climate_revenue_eur_m` | holdout |
| AC-37 | — | `GET /openapi.json` | paths `/api/value-chain/links/company/{company_id}` (get, put, delete), `/api/value-chain/links/activity/{taxonomy_id}/{activity_id}` (get, put, delete), `/api/value-chain/portfolio/{portfolio_id}` (get) exist; `shock/quantity` and `shock/price` have query parameters `portfolio` and `as_of` | holdout |
| AC-38 | V built, S linked, app running | open `#/valueChain/portfolio`, pick `P` | the URL becomes `#/valueChain/portfolio/P`; the coverage line reads `Linked 90.0% of NAV · footprint covers 70.0%`; the footprint tile reads `2.2 t CO₂e per M EUR invested` | evaluator |
| AC-39 | as AC-38 | read the holdings table | 4 rows in AC-18's order, with weights `40.0%`, `30.0%`, `20.0%`, `10.0%` and the link sources shown | evaluator |
| AC-40 | as AC-38 | `Edit link` on `s_sx`, `Revenue split`, change the shares to 60/40 and `Save` | the PUT body carries shares 0.6 and 0.4; the overlay reloads; the s_sx top node weight changes to `60.0%` | evaluator |
| AC-41 | as AC-38 | `Edit link` on `s_sx`, shares 60/30, `Save` | the text `shares must sum to 1` shows under the rows; nothing saved | evaluator |
| AC-42 | as AC-38 | `Edit link` on `s_sx`, `Reset to default` | DELETE sent; the row's link source reads `code` | evaluator |
| AC-43 | as AC-38 | pick activity `T` / `Copper and nickel mining` | the line reads `Copper and nickel mining: 35.0% of NAV directly · 51.9% of upstream` | evaluator |
| AC-44 | as AC-38 | Shocks view of any CN node, Demand, `All of CN`, −10%, `Portfolio` `P` | the results show `Portfolio output change −8.23%` | evaluator |
| AC-45 | Real build, a portfolio of 500 linked holdings | time `O` and a demand shock with `portfolio` on a warm process | `O` ≤ 2.0 s; shock ≤ 1.5 s | evaluator |

Must not change:

- AC-46: spec 1's holdout rows AC-9 to AC-21 pass unchanged with S linked present in the store (the tier
  ignores rules). Checked by: holdout.
- AC-47: spec 2's holdout rows pass unchanged (no `portfolio` parameter). Checked by: holdout.
- AC-48: the explorer spec's holdout rows AC-1 to AC-25b still pass. Checked by: holdout.
- AC-49: after S linked, `GET /api/portfolio/companies` returns `sx` and `nx` with `isic_code` and
  `country` as in S. Checked by: holdout.
