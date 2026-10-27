# Revenue routes to a target on the full-resolution value chain

Status: draft for owner approval, 2026-10-27. Owner decisions on 2026-10-27:

- What it is for: an app screen for analysts, and the base for company-level work (a company's revenue
  exposure to an activity, risk assessment).
- Exposure is measured **in revenue terms only**: the share of a seller's sales that ends up with the
  target. Numbers of different kinds are never multiplied or combined.
- Routes run upstream and downstream: from any seller to the target, through any chain of buyers.
- Company-to-company supply links (`SUPPLIES_TO`) are left out: they say what share of a supplier's
  revenue a customer makes up, but not what is supplied, and carry too little information here.
- Matching companies to activities is not part of this spec. The R&D Lab Match step (theme runs) and spec 3's
  links already cover it.
- More detail on top of EXIOBASE comes from **product recipes entered by analysts** as cost shares
  (option 3 of three: not the EXIOBASE product tables, not trade data).
- Approach A: all numbers from the stored matrices (numpy). No Neo4j in this spec.

Fourth of four value-chain specs: (1) indirect-exposure tier on the full build, (2) shocks
(`2026-10-26-value-chain-shocks-design.md`), (3) links and portfolio overlays (PR #256), (4) this. The
dispatcher's working title was "Neo4j summary graph and path finder". The owner turned it into revenue
routes with recipes and no graph (see Approaches). Builds on the explorer spec
(`2026-10-24-value-chain-explorer-design.md`, "the explorer"): its build, definitions (`A`, `B`, `G`, node ids,
labels, live nodes, ties, caveat line) and anti-goals hold here unchanged. It needs nothing from specs 1–3.

## Intent

Analysts want to know who earns money from a given part of the economy, and how. "Which sectors in which
regions sell into battery making, and how much of their revenue ends up there?" The explorer shows a node's
direct and total customers, but not what share of a seller's revenue reaches one chosen target, or through
which chain of buyers it gets there.

This spec adds that measure, the routes behind it, and product recipes. A recipe describes one product (say
an EV battery) much more finely than its EXIOBASE sector does: what it buys, as shares of its cost. A later
spec lets companies inherit these shares through their links to nodes and activities.

## Goals

- For a target (any live node, or a recipe), every live node's **revenue share to the target**: the share of
  its sales that ends up as the target's purchases, directly or through other buyers. Also the same amount
  in M EUR.
- For one seller and the target, the largest **routes** with each route's share. The shown routes and the
  remainder add up exactly to the seller's share.
- Analysts create, change and delete recipes on a screen and through the API.
- Every number states its basis: the explorer caveat line, the model caveat and, for a recipe, its source.

## Non-goals

- Neo4j: no summary graph and no Cypher path search. A later spec adds them when a company-level feature
  needs graph queries; the matrices and recipes here are what it would load.
- Companies: no company list, no company exposure figure. Spec 3's links and the R&D Lab Match step map
  companies to nodes and activities; combining them with this measure is the next spec.
- `SUPPLIES_TO` company links, in any calculation or view.
- Recipes in physical units (kg per unit), licensed LCA databases (ecoinvent), price conversion.
- A recipe's link to a taxonomy activity, recipe versions or history, recipes made of other recipes, a
  recipe made in several regions (an analyst enters one recipe per region).
- Upstream footprint of a recipe (CO₂e, energy, jobs), and recipes in spec 2's shocks.

## Anti-goals

- An LLM anywhere in this feature.
- Combining numbers of different kinds: every share is a share of a seller's revenue, and a route's share is a
  product of such shares only.
- A number without its basis (see Goals).
- Silently using a recipe that no longer fits the current build: it is refused with the reason (409), never
  dropped or adjusted.
- Writing a node id into stored data. A recipe names its nodes by region code and sector name, so it carries
  over to a new edition.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **numpy only.** Revenue shares and routes computed per request from the stored `A`, `x` and `G`; recipes stored by the app and applied per request. | Exact, smallest, no second copy to load and keep in step; later company work reads the same API. | **Chosen** |
| B | A plus a Neo4j summary graph (nodes, sales links above a cut-off, recipes) loaded per edition for the screen and later company work. | Matches the explorer's original "graph on top" plan; every number still from numpy, and nothing in this spec queries the graph. | Rejected for now |
| C | Route search in Cypher on a cut-off graph. | Drops small links, so shares undercount by an unknown amount. Same reason the explorer rejected approach B. | Rejected |

## Definitions

Arithmetic in float64. `Z`, `x`, `B = diag(x)⁻¹ · Z` (row `i` zero where `x_i = 0`) and live nodes as in the
explorer; `B` follows from the stored `A` and `x` as `B[i,j] = A[i,j] · x_j / x_i`. `B[i,j]` is the share of
`i`'s sales that go to `j`.

- **Recipe**: a product made in one live **home** node `h` (region code + sector name), with an annual output
  `q` (M EUR, `0 < q < x_h`), a `source` (text), and 1 to 50 **inputs**, each a live node (region code +
  sector name) with a cost share `s_i > 0`, no node twice, `Σ s_i ≤ 1` (within 1e-9). The **unlisted share**
  `1 − Σ s_i` is value added and inputs the analyst did not list; it is bought from no node. A recipe's
  purchases are `z_i = s_i · q` M EUR.
- **Target** and its two pieces, `d` (direct share of each node's sales going to the target) and `B'` (sales
  between nodes, without those to the target):
  - **Node target** `t`: `d_i = B[i,t]`; `B'` is `B` with column `t` set to 0.
  - **Recipe target** with home `h`: `d_i = z_i / x_i`; `B'` is `B` with `B'[i,h] = (Z[i,h] − z_i) / x_i`
    for each input `i`. The recipe's purchases are taken out of its home node's purchases, so they are not
    counted twice. Its output stays in `x_h`, and the home node's sales keep the table's pattern.
  - A recipe is **consistent** when `z_i ≤ Z[i,h]` for every input (within 1e-9 M EUR).
- **Revenue share** to the target, per node: `r = (I − B')⁻¹ · d`, so `r = d + B' · r`. `r_i` lies in [0, 1].
  It is the share of `i`'s sales that ends up as the target's purchases, assuming every node sells to its
  buyers in the table's proportions. **Revenue to the target** is `r_i · x_i` M EUR. The builder may use
  `G` with a rank-one update instead of a new inverse, as long as results agree to 1e-9.
- **Route** from seller `n`: a sequence `n = m_0, m_1, …, m_k`, then the target, with `k + 1` **hops**
  (1 to `max_hops`). Nodes may repeat (a node selling to itself is a route). Its **share** is
  `B'[m_0,m_1] · … · B'[m_{k−1},m_k] · d_{m_k}`. Every factor must be > 0. Over all routes of any length,
  the shares add up to `r_n` exactly.
- A **route list** for `n` holds the routes of at most `max_hops` hops with share ≥ `min_share`, ordered
  by share descending, then fewer hops first, then the route's node ids joined with `>` in ascending
  string order. Shares count as equal for ordering when they agree to 12 decimals. The list is cut to
  `top`. `shown_share` is the sum of the listed shares; `rest_share = r_n − shown_share`.
- **Model caveat**, in every response and view of this spec: `Revenue shares assume every node sells to its
  buyers in the table's proportions; a recipe replaces its home node's purchases only for the recipe's output.`

## Scope

1. **Recipe store.** Recipes are kept by the app, outside `ARP_VALUE_CHAIN_DIR`, and survive a restart and a
   new build. Each has a server-assigned `recipe_id` (URL-safe, never reused), `name` (1–120 chars),
   `home`, `output_meur`, `inputs`, `source` (1–2000 chars), `set_by` (principal name) and `set_at`
   (RFC 3339). Saving with the same `recipe_id` replaces the recipe.
2. **Validation on save**, against the current build; the first failing check answers 422 with its `detail`:
   - a region + sector that names no node: `unknown node <region> · <sector>`; a zero-output one:
     `no output: <region> · <sector>`;
   - inputs: 1 to 50, no node twice (`input named twice: <region> · <sector>`), each share > 0, sum ≤ 1
     (`input shares add up to more than 1`);
   - `output_meur` > 0 and below the home node's output (`output_meur must be below the home node's
     output (<x_h> M EUR)`, `x_h` with at most 4 decimals and no trailing zeros);
   - not consistent: `the recipe buys more from <sector> · <region label> than <home sector> · <home region
     label> does in total`, for the first such input in input order.
   Not built: 503 as in the explorer.
3. **Use against a later build.** When a stored recipe no longer resolves (a name with no live node) or is
   not consistent with the current build, every exposure or route request on it answers 409 with the same
   `detail` text as on save. `GET /recipes` lists it with `status` `unresolved` or `inconsistent`.
4. **API** under `/api/value-chain` (Appendix A). GET for viewers; POST, PUT and DELETE need the analyst role
   (the router's existing `authorize`).
5. **Screen**: two views in the Value Chain Explorer (Appendix B), and a `Revenue exposure` link on the node
   page.

## My calls (owner to confirm with the acceptance table)

1. **No company figures yet.** The owner's end goal is companies, but company → node weights come from spec 3,
   which is not merged. Company exposure `Σ w_n · r_n` is one line once it is, and goes in the next spec.
2. **Recipe purchases are carved out of the home node** (Definitions) rather than added on top, so no flow is
   counted twice. That is why an inconsistent recipe is refused.
3. **The unlisted share is bought from nobody.** The alternative is to fill it with the home node's average
   inputs. That makes a partly listed recipe look complete, so I left it as an explicit remainder.
4. **Defaults**: exposure list `top` 20 (1–100); routes `max_hops` 4 (1–6), `min_share` 0.001
   (0.0001–1), `top` 10 (1–50). Shares display as percent with one decimal (`24.7%`), revenue as M EUR
   with one decimal; the API returns unrounded values.
5. **Routes may revisit nodes**, so that shown routes plus the remainder add up exactly. Paths that never
   revisit a node would not.
6. **Self-sales count**: a node selling to the target node itself (`B[t,t]`) has a direct share like any
   other seller.

## Constraints

- Exposure and route requests: at most 2 s each on the real build, warm process. Saving a recipe: at most
  2 s.
- Repo checks as in the explorer, including the API contract (`scripts/export_openapi.py`,
  `npm run gen:api`, each new `request<T>()` in `frontend/src/api/contract.ts`).

## Left to the builder

The recipe store's backend (Postgres or the app's file store), recipe id format, how `r` is computed (solve or
rank-one update on `G`), the route search (any search that returns exactly the route list defined above), and
the screen's component structure, as long as the URLs in Appendix B work.

## Appendix A: API

Every 200 carries `edition`, `caveat` (explorer line) and `model_caveat`. Unknown or zero-output node: 404
`unknown node '<id>'`. Unknown recipe: 404 `unknown recipe '<id>'`. Parameters out of range: 422.

- `GET /recipes` → `{items: [{recipe_id, name, home: {region, sector}, output_meur, n_inputs, status}]}`,
  `status` `ok`, `unresolved` or `inconsistent`; ordered by name, then `recipe_id`.
- `GET /recipes/{rid}` → `{recipe_id, name, home, output_meur, inputs: [{region, sector, share}], source,
  unlisted_share, set_by, set_at, status}`.
- `POST /recipes` with `{name, home, output_meur, inputs, source}` → 201 and the recipe as `GET` returns it.
- `PUT /recipes/{rid}` with the same body → 200 and the recipe. `DELETE /recipes/{rid}` → 204.
- `GET /exposure?target=<node id | recipe:<rid>>&top=20` → `{target, target_label, basis: "node" |
  "recipe", recipe_source (null for a node), unlisted_share (null for a node), items: [{node_id,
  region_label, sector, direct, share, revenue_meur}]}`. `direct` is `d_i` and `share` is `r_i`. Items are
  live nodes with `share` > 0, ordered by `share` descending, ties by node id, cut to `top`.
  `target_label` is `<sector> · <region label>` for a node and the recipe's `name` for a recipe.
- `GET /routes?target=…&from=<node id>&max_hops=4&min_share=0.001&top=10` → `{target, from, share,
  routes: [{nodes: [node ids…, target], share}], shown_share, rest_share}`, where `nodes` ends with
  the `target` value exactly as requested.

## Appendix B: screen

- `#/valueChain/<id>/exposure` and `#/valueChain/recipes/<rid>/exposure`: the target's label, then a table of
  sellers (top 20): `<sector> · <region label>`, `<share>%`, `<revenue> M EUR`. Under it, for a recipe, its
  source and `Unlisted share <n>%`. Clicking a row opens `…/exposure/<from id>`, which adds that
  seller's route list (defaults). Each route reads as its labels joined by ` → `, ending with the target
  label, then `<share>%`, and a last line reads `Other routes <rest_share>%`.
- `#/valueChain/recipes`: the recipe list (name, home, output, status) and a `New recipe` button.
  `#/valueChain/recipes/<rid>` and `#/valueChain/recipes/new`: a form with name, home (search picker as on
  the explorer), output M EUR, inputs (picker + share in %), source; `Save` shows a 422 `detail` next
  to the form; `Delete` asks for confirmation. Saving opens the recipe's exposure view. Viewers see the form
  read-only.
- The node page (`#/valueChain/<id>`) gets a `Revenue exposure` link to `#/valueChain/<id>/exposure`.
- The explorer caveat line and the model caveat at the foot of each view.

## Acceptance

Fixture F and "F built" as in the explorer's acceptance section; caveat C as there. Live nodes, in order:
DE.2 (`Mining of copper ores and concentrates`, DE), DE.3 (`Other business activities`, DE), CN.2,
CN.3. M (model caveat): `Revenue shares assume every node sells to its buyers in the table's proportions; a
recipe replaces its home node's purchases only for the recipe's output.` Recipe body R: `{"name": "Test
battery", "home": {"region": "DE", "sector": "Other business activities"}, "output_meur": 50, "inputs":
[{"region": "DE", "sector": "Mining of copper ores and concentrates", "share": 0.2}, {"region": "CN",
"sector": "Other business activities", "share": 0.1}], "source": "test"}`. "R saved" means `POST
/recipes` with R as an analyst returned 201 with `recipe_id` `<rid>`. Fixture F2 is F with the `Z` entry
from CN.3 to DE.3 set to 0 (row CN.3 `[0, 0, 10, 10]`), and "switched to F2" means F2 built into another
directory and `ARP_VALUE_CHAIN_DIR` pointed at it. Numbers are compared rounded to 4 decimals.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | F built | `GET /api/value-chain/exposure?target=DE.3` | 200; `basis` `node`; `target_label` `Other business activities · DE`; items node ids in order `["DE.2","CN.3","DE.3","CN.2"]` with `share` 0.2473, 0.2254, 0.1138, 0.0282, `direct` 0.2, 0.2, 0.1, 0, `revenue_meur` 24.7261, 22.5352, 22.7543, 2.8169; `caveat` C; `model_caveat` M | holdout |
| AC-2 | F built | `…/exposure?target=DE.3&top=2` | items node ids exactly `["DE.2","CN.3"]` | holdout |
| AC-3 | F built | `…/routes?target=DE.3&from=CN.3` | `share` 0.2254; `routes` exactly, in order: `["CN.3","DE.3"]` 0.2, `["CN.3","CN.3","DE.3"]` 0.02, `["CN.3","CN.2","CN.3","DE.3"]` 0.002, `["CN.3","CN.3","CN.3","DE.3"]` 0.002; `shown_share` 0.224; `rest_share` 0.0014 | holdout |
| AC-4 | F built | `…/routes?target=DE.3&from=CN.3&top=3` | 3 routes, the first three of AC-3; `rest_share` 0.0034 | holdout |
| AC-5 | F built | `…/routes?target=DE.3&from=CN.3&max_hops=2&min_share=0.01` | `routes` exactly `["CN.3","DE.3"]` 0.2, `["CN.3","CN.3","DE.3"]` 0.02 | holdout |
| AC-6 | F built | R saved, then `GET …/recipes/<rid>` | `name` `Test battery`; `unlisted_share` 0.7; `status` `ok`; `set_by` the analyst's principal name; `inputs` as sent | holdout |
| AC-7 | R saved | `GET …/exposure?target=recipe:<rid>` | `basis` `recipe`; `target_label` `Test battery`; `recipe_source` `test`; `unlisted_share` 0.7; items node ids `["DE.2","CN.3","CN.2","DE.3"]` with `share` 0.1183, 0.0575, 0.0072, 0.007, `direct` 0.1, 0.05, 0, 0, `revenue_meur` 11.8276, 5.7516, 0.719, 1.3941 | holdout |
| AC-8 | R saved | `…/routes?target=recipe:<rid>&from=DE.2&min_share=0.002` | `share` 0.1183; `routes` exactly `["DE.2","recipe:<rid>"]` 0.1, `["DE.2","DE.2","recipe:<rid>"]` 0.01, `["DE.2","CN.3","recipe:<rid>"]` 0.005; `rest_share` 0.0033 | holdout |
| AC-9 | R saved | `…/routes?target=recipe:<rid>&from=DE.3&min_share=0.002` | `share` 0.007; `routes` exactly `["DE.3","DE.2","recipe:<rid>"]` 0.005 | holdout |
| AC-10 | F built | `POST /recipes` with R, but the input `{"region":"CN","sector":"Mining of copper ores and concentrates","share":0.1}` replacing the CN input | 422; `detail` `the recipe buys more from Mining of copper ores and concentrates · CN than Other business activities · DE does in total` | holdout |
| AC-11 | F built | `POST /recipes` with R and `output_meur` 200 | 422; `detail` `output_meur must be below the home node's output (200 M EUR)` | holdout |
| AC-12 | F built | `POST /recipes` with R and shares 0.6 and 0.5 | 422; `detail` `input shares add up to more than 1` | holdout |
| AC-13 | F built | `POST /recipes` with R and an input `DE` · `Cultivation of paddy rice` | 422; `detail` `no output: DE · Cultivation of paddy rice` | holdout |
| AC-14 | F built | `POST /recipes` with R and home `XX` · `Other business activities` | 422; `detail` `unknown node XX · Other business activities` | holdout |
| AC-15 | F built | `POST /recipes` with R, the DE input named twice (shares 0.2 and 0.1) | 422; `detail` `input named twice: DE · Mining of copper ores and concentrates` | holdout |
| AC-16 | F built | `POST /recipes` with R as a viewer | 403; `GET /recipes` lists no recipe | holdout |
| AC-17 | R saved, switched to F2 | `GET …/exposure?target=recipe:<rid>` | 409; `detail` `the recipe buys more from Other business activities · CN than Other business activities · DE does in total`; `GET /recipes` lists it with `status` `inconsistent` | holdout |
| AC-18 | R saved, then the API process restarted | `GET …/recipes/<rid>` | 200, same body as AC-6 | holdout |
| AC-19 | R saved | `PUT …/recipes/<rid>` with R and `output_meur` 100, then `GET …/exposure?target=recipe:<rid>` | items node ids `["DE.2","CN.3","CN.2","DE.3"]`; `DE.2` `direct` 0.2, `share` 0.2349; `CN.3` `direct` 0.1, `share` 0.1142 | holdout |
| AC-20 | R saved | `DELETE …/recipes/<rid>`, then `GET …/exposure?target=recipe:<rid>` | 204, then 404 `unknown recipe '<rid>'` | holdout |
| AC-21 | F built | each of `/exposure?target=DE.1`, `/routes?target=DE.3&from=DE.1` | 404, `detail` `unknown node 'DE.1'` | holdout |
| AC-22 | F built | each of `/exposure?target=DE.3&top=101`, `/routes?target=DE.3&from=CN.3&max_hops=7`, `…&min_share=0.00001`, `…&top=51`, `/exposure` with no `target` | each answers 422 | holdout |
| AC-23 | `ARP_VALUE_CHAIN_DIR` unset | `GET …/exposure?target=DE.3` and `POST /recipes` with R | 503, explorer `detail` | holdout |
| AC-24 | `ARP_ANTHROPIC_API_KEY` unset, and separately set to an invalid key | AC-1 to AC-23 | all pass | holdout |
| AC-25 | Real `IOT_2022_ixi.zip` built (explorer AC-26) | for 10 seeded random live nodes: `/exposure?target=<id>` and `/routes?target=<id>&from=<the first item's node id>`, warm process, client on localhost | each answers in ≤ 2.0 s | evaluator |
| AC-26 | as AC-25 | for the same 10 targets and sellers: `/routes?…&max_hops=6&min_share=0.0001&top=50` | `shown_share` equals the sum of the listed routes' `share` within 1e-12; `rest_share` ≥ −1e-9; `share` equals that seller's `share` in `/exposure?target=<id>&top=100` when listed there | evaluator |
| AC-27 | as AC-25 | open the node page of `Manufacture of electrical machinery and apparatus n.e.c. · CN`, click `Revenue exposure` | the URL becomes `#/valueChain/<its id>/exposure`; a table of up to 20 sellers with percent and M EUR columns, percent descending | evaluator |
| AC-28 | as AC-27 | click the first seller row | its route list appears; the routes' percents plus `Other routes` add up to the row's percent (± 0.1 for rounding) | evaluator |
| AC-29 | as AC-25, signed in as analyst | on `#/valueChain/recipes` create a recipe with home `Manufacture of electrical machinery and apparatus n.e.c. · CN`, output 1000, inputs `Copper production · CN` 10% and `Manufacture of rubber and plastic products · CN` 5%, source `evaluator test` | the exposure view opens; `Copper production · CN` is listed; the page shows `Unlisted share 85.0%` and the source `evaluator test` | evaluator |
| AC-30 | as AC-29 | edit the recipe and set output to a value ≥ that node's output | the form shows `output_meur must be below the home node's output (…)` and nothing is saved | evaluator |
| AC-31 | as AC-25, signed in as viewer | open the recipe from AC-29 | the form is read-only; no `Save` or `Delete` | evaluator |
| AC-32 | as AC-25 | open each view of this spec | each page foot shows caveat C for the real build and M | evaluator |

Must not change:
- AC-33: the explorer's and spec 2's API responses for the same requests are unchanged:
  `git diff <merge-base> -- backend/tests/test_value_chain*.py` is empty and
  `pytest tests/test_value_chain*.py` (from `backend/`) exits 0. Checked by: unit.
- AC-34: `git diff <merge-base> -- backend/arp/company_graph.py backend/arp/research/exposure_layers.py` is
  empty (no change to the company graph or theme layers). Checked by: evaluator.
