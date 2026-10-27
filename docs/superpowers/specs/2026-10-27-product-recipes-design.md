# Product recipes on the full-resolution value chain

Status: approved by the owner, 2026-10-27 (project 1 and the series outline). Owner decisions on 2026-10-27 (brainstorming session):
recipes start from taxonomy activities linked to EXIOBASE nodes; the input is a physical amount
("10 GW of wind"); coarse nodes get estimated recipe nodes attached at the input they refine, in the
same tree, marked estimated with their source; EXIOBASE and estimate are shown side by side and never
added; every estimated quantity carries low / central / high; recipes live in Postgres, seeded from a
cited JSON library in the repo, with an in-app agent that drafts new recipes and a person who approves
them. Mockup (illustrative numbers): https://claude.ai/artifact/2ywABMASVKuanhXUfyjta7. Source
research: https://claude.ai/artifact/Npdtr6c9H5qmMJaq3fdogL.

Builds on `docs/superpowers/specs/2026-10-24-value-chain-explorer-design.md` (the explorer spec): its
build (`arp io build-full`), definitions (`A`, `L`, node ids, ties, labels, caveat line), API conventions
and anti-goals hold here unchanged.

This document covers four projects. **Project 1 is specified in full and is what the Acceptance table
covers.** Projects 2–4 are outlines; each gets its own spec, written against this document.

## Intent

Analysts want to break any product down into its inputs, all the way to the mine, and see how much of
each raw material a given amount of that product needs. The first use is electrification: "10 GW of
onshore wind needs how much copper, neodymium, dysprosium, and from which mines?" The answer must name
the stages in between (generator, magnets, copper refining, ore mining), not only the total.

Today the criticality registry (`backend/arp/research/indirect_exposure/criticality.py`) flags
industries by two-digit ISIC code and, since industries carry ICIO codes, never fires. This series
replaces that idea with quantities.

Two facts shape the design:

- EXIOBASE gives the whole chain at its own detail, but it is coarse where it matters. Lithium, cobalt,
  graphite and rare earths sit together in "Mining of other non-ferrous ores", and a wind turbine gets
  the average recipe of "Machinery and equipment n.e.c.", which contains almost no magnets.
- Product-level recipes exist (NREL REMPD, JRC, GREET, Babbitt et al., RASMI; see the source research
  page) but each covers one family, often as ranges, under different licences.

So the tree follows EXIOBASE, and where a sourced recipe knows better, an estimated node is attached
beside the EXIOBASE input it refines. Both are shown; neither changes the other.

## Goals (whole series)

- From a taxonomy activity and a physical amount, a tree down to the mines with tonnes per stage.
- EXIOBASE figures and recipe estimates side by side at every stage and in the totals.
- Every estimated number traceable to a source and a verified quote, with low / central / high.
- A recipe library for the first four product families, and an agent that drafts more on request.

## Non-goals (whole series)

- Monte Carlo or statistical intervals. Low and high are outer bounds (Definitions).
- Prices, substitution, recycling loops or time dynamics. The model stays linear and static.
- Changing the 50-industry indirect-exposure tier or `arp io import-exiobase`.
- Fixing or extending `criticality.py`. It is retired by project 3's spec, not patched.

## Anti-goals

- An EXIOBASE figure changed, scaled or replaced by an estimate. Estimates sit beside it.
- An estimate added to an EXIOBASE figure in any total.
- An estimated number without a source, or an agent-drafted recipe used in a tree before a person
  approved it.
- An LLM in the tree or totals arithmetic. The agent only drafts recipes (project 4).

## Approaches

Decided with the owner, in this order:

| Question | Options considered | Chosen | Why |
|---|---|---|---|
| How a physical amount becomes model input | A: € via cost per unit, EXIOBASE recipe only. B: physical recipe for the first step, EXIOBASE for the rest, as two calculations. C: an estimated product node with its own recipe, fed by € via cost per unit | **C** | A misses the minerals that matter (magnets); B double-counts unless the EXIOBASE part is adjusted and hides the product as a stage; C keeps the product visible as a stage |
| How estimated nodes relate to EXIOBASE | Replace the EXIOBASE input; attach beside it | **Attach beside, EXIOBASE untouched** | Full visibility, nothing mixed |
| Totals where both exist | Replace (estimate counts, EXIOBASE greyed); side by side | **Side by side, never summed** | Owner choice |
| Ranges | Central with range on hover; low / central / high carried through | **Low / central / high throughout** | Owner choice |
| Recipe research | Fixed library; in-app agent; both | **Both** | Library for the four families now, agent for the long tail |
| Where recipes live | A: Postgres store seeded from a repo JSON file; B: JSON files in git, agent opens PRs; C: library in git, drafts in Postgres | **A** | Reuses the taxonomy draft → ratify pattern (`storage/taxonomy_store.py`, `agents/taxonomy_researcher.py`); in-app Approve; the seed file keeps the library reviewable in git |

## The series

| # | Project | Delivers | Depends on |
|---|---|---|---|
| 1 | **Ore extraction in the value chain** (this spec) | Tonnes of ore per metal from EXIOBASE's material accounts: in the build, the footprint and the upstream tree | explorer build |
| 2 | Recipe store and recipe nodes | Recipe schema and Postgres store, estimated nodes in the tree, physical input, side-by-side totals, low / central / high, metal content of ore | 1 |
| 3 | Taxonomy activities on nodes | Each taxonomy activity linked to EXIOBASE nodes (and optionally a recipe); start a tree from an activity; retire `criticality.py` | 2 (recipe link), or 1 alone for the node link |
| 4 | Recipe research | Seed library for energy technology, vehicles and batteries, buildings, electronics; `arp recipes import`; in-app agent drafting recipes with grounded quotes; approval screen | 2 |

---

## Project 1: Ore extraction in the value chain

### Intent

Give the explorer a physical indicator for metals before any recipe exists. EXIOBASE's material
accounts record, per node, the ore extracted from the ground. With them, the footprint view can answer
"how much copper ore is dug up for €1 M of this node's output, and where", and every box of the upstream
tree can show how much of that ore flows through it.

### Goals

- `arp io build-full` reads the metal-ore rows of the archive's material accounts.
- The footprint endpoint and view accept one indicator per metal ore.
- The upstream tree endpoint and view can show, per box, the tonnes of one chosen ore embodied in it.
- `/status` lists the ores the build holds.

### Non-goals (project 1)

- Metal content. EXIOBASE reports gross ore; converting to tonnes of metal needs grade factors, which
  are estimates and belong to project 2 (My call 1).
- Non-metal materials (sand, biomass, fossil fuels), and splitting "other non-ferrous ores".
- Ore indicators in the shocks feature (`2026-10-26-value-chain-shocks-design.md`) or on the node page.
- Physical input amounts, recipes, activities.

### Definitions (add to the explorer's Definitions)

- **Ore rows**: the rows of the archive's `material/F.txt` whose name starts with
  `Domestic Extraction Used - Metal Ores - `. The rest of the name is the **ore label**
  (`Copper ores`). Every other row of that file is ignored. Values are kt; the build stores tonnes
  (× 1000).
- **Ore key**: the ore label lower-cased, each run of characters other than `a–z` and `0–9` replaced by
  one `_`, leading and trailing `_` removed (`Copper ores` → `copper_ores`).
- **Direct ore intensity** `m_ore[k]`: the ore row at node `k` in tonnes ÷ `x_k`, in t per M EUR; null
  where `x_k = 0`.
- **Total ore intensity** `M_ore[k] = Σ_i m_ore[i] · L[i,k]` (zero-output `i` count 0): tonnes of that
  ore extracted anywhere per M EUR of `k`'s output.
- **Ore footprint** of `y` M EUR for `k`: as the explorer's footprint, with `s = m_ore`; unit `t ore`.
- **Embodied ore of a tree box**: `y · chain · M_ore[box node]`, where `y` is the tree request's
  `amount_meur` and `chain` the box's chain. The root's value equals the ore footprint total.

### My calls (owner to confirm with the acceptance table)

1. **Gross ore, labelled as ore.** EXIOBASE follows the economy-wide material-flow convention of gross
   (run-of-mine) ore; tonnes of metal need a grade per metal and region. That factor is an estimate, so
   it comes in project 2 with the other estimates, and project 1 shows `t ore` everywhere. Copper ore at
   about 0.6 % grade means 1,000 t ore ≈ 6 t copper; the unit label must make this impossible to miss.
2. **All metal-ore rows the archive has, including all-zero ones**, so the list is the same for every
   build of a release. Expected in 3.11.2 (not yet checked against a real archive; the builder reads
   the real names): bauxite and aluminium, copper, gold, iron, lead, nickel, other non-ferrous, PGM,
   silver, tin, uranium and thorium, zinc.
3. **Precomputed at build time**: `m_ore` and `M_ore` per node and ore, so a footprint or tree request
   stays a read.
4. **Display**: ore tonnes rounded to one decimal first; below 1,000 t shown with that decimal, from
   1,000 t up with no decimals and thousands separators (`143.4 t ore`, `999.9 t ore` for 999.94,
   `1,000 t ore` for 999.96, `1,283 t ore`); the API returns unrounded values.
5. **Caveat line** unchanged; the ore views add one line under it: `Ore: gross ore extracted, not metal
   content`.
6. **A material file without ore rows is an error**, not an empty list: the real 3.11.2 row names are
   unverified, and a silent `ores: []` would hide a mismatch on every deployment.

### API (adds to the explorer's Appendix B)

- `GET /status` gains `ores: [{key, label}]`, in archive row order.
- `GET /nodes/{id}/footprint`: `indicator` also accepts `ore:<key>` for any key in `ores`; unit
  `t ore`; the response gains `ore_note` `Ore: gross ore extracted, not metal content` for ore
  indicators (absent otherwise). An unknown `ore:` key answers 422. As for every indicator, regions
  and sectors whose sum is 0 are left out of `by_region` and `by_sector`.
- `GET /nodes/{id}/tree` gains optional `ore=<key>` and `amount_meur` (> 0, default 1). With `ore`,
  every item gains `ore_t` (embodied ore, Definitions) and the response root gains `ore_note`. Without
  `ore`, the response is unchanged and `amount_meur` is ignored. An unknown key, or `amount_meur` ≤ 0
  with `ore`, answers 422.

### Screen (adds to the explorer's Appendix C)

- Footprint view: the indicator picker lists CO₂e, Energy, Jobs, then one entry per ore as
  `<ore label> (ore)`, in `/status` order.
- Upstream tree view: a `Show ore` picker (default `None`, then the `/status` labels without suffix,
  e.g. `Copper ores`) and the amount (M EUR, default 1). With an
  ore picked, each box gains a line `<value> t ore`.
- Both show `Ore: gross ore extracted, not metal content` under the caveat when an ore is picked.

### Constraints

- The explorer's build limits (20 minutes, 8 GB) and request limits (1 s) hold with ores included.
- An archive without `material/F.txt` builds exactly as before: same files, same bytes apart from
  `built_at`, and `ores: []` (older or trimmed archives). Ore data goes in its own file(s), written only
  when ore rows exist, so the manifest and `nodes.csv` do not change. A build directory from before this
  change also reads as `ores: []`.
- An archive that has `material/F.txt` but no ore row fails the build with
  `material/F.txt: no row starts with 'Domestic Extraction Used - Metal Ores - '`, so a renamed row
  never silently drops the feature (My call 6).
- Repo checks as in the explorer spec; API contract regenerated.

### Left to the builder

Where `m_ore` and `M_ore` are stored in the build directory, and how the pickers look, as long as the
rows below pass.

---

## Project 2 (outline): Recipe store and recipe nodes

- **Recipe**: a named product with a unit (`1 MW installed`), a cost per unit with region and source
  (for the € conversion), the EXIOBASE node(s) it is linked to, and lines. Each line has an input, a
  kind (`exiobase_node`, `recipe`, `raw_material`), low / central / high quantity per unit, the
  EXIOBASE node it attaches at, a source and a verbatim quote. Recipes nest through `recipe` lines.
- **Store**: Postgres, versioned, DRAFT → APPROVED as in the taxonomy store; only APPROVED versions
  are used in trees.
- **Tree**: the input is a recipe and a physical amount (`10 GW`). The tree follows EXIOBASE from the
  linked node; at each attach point the recipe's estimated nodes appear beside the EXIOBASE input,
  marked estimated with their source.
- **Totals**: two columns, EXIOBASE and estimate, never summed; each low / central / high.
- **Low and high**: every recipe line at its low (high) value at once, giving outer bounds.
- **Splits of coarse nodes** (rare earths, lithium, cobalt, graphite out of "other non-ferrous ores")
  and **metal content of ore**: estimated, sourced (USGS Mineral Commodity Summaries), side by side.
- Open for its spec: tonnes mined (demand, default) vs tonnes in product (content) as a toggle.

## Project 3 (outline): Taxonomy activities on nodes

- Link each taxonomy activity to EXIOBASE nodes, starting from its `standards_mapping` NACE codes and
  `core_isic_codes`; a person confirms the link, as for other mappings.
- Optionally link an activity to a recipe.
- Start a tree or footprint from an activity.
- Retire `criticality.py`, `criticality_flag` and `critical_input`, which never fire today; the spec
  decides what replaces them in the API.

## Project 4 (outline): Recipe research

- **Seed library** as a cited JSON file in the repo, imported with `arp recipes import`. First
  families and sources (see the source research page):
  - energy technology: NREL REMPD (CC BY), JRC139701 (wind by drivetrain), JRC143190 (grid);
  - vehicles and batteries: GREET 2025, carculator;
  - buildings: RASMI, Heeren & Fishman;
  - electronics: Babbitt et al. (CC0), EU ecodesign disclosures.
  Values from sources that forbid redistribution (EC3, IBU.data) are cited, not stored.
- **Agent**: drafts a recipe for a named product, each line with a grounded quote checked by
  `arp/grounding.py`; writes DRAFT only.
- **Approval screen**: the recipe card of the mockup, with Approve and Request changes.

## Acceptance (project 1)

The explorer's fixture F has no `material/F.txt`. Here **F0** is exactly the explorer's fixture F, and
the explorer's acceptance rows run on F0 unchanged. **F** is F0 plus a `material/F.txt` in the same
layout as the other satellites, with these rows, in this order (kt, for DE.1, DE.2, DE.3, CN.1, CN.2,
CN.3):

1. `Domestic Extraction Used - Metal Ores - Other non-ferrous metal ores (incl. PGM)` `[0, 0, 0, 0, 0, 0]`
2. `Domestic Extraction Used - Non-Metallic Minerals - Sand and gravel` `[0, 5, 5, 0, 5, 5]`
3. `Domestic Extraction Used - Metal Ores - Nickel ores` `[0, 0, 0, 0, 0, 0]`
4. `Domestic Extraction Used - Metal Ores - Copper ores` `[0, 40, 0, 0, 100, 0]`

"F built" and "F0 built" mean `arp io build-full IOT_2022_ixi.zip --out <d>` ran on that fixture and
`ARP_VALUE_CHAIN_DIR=<d>`. Numbers are compared rounded to 4 decimals. `O` is `Ore: gross ore extracted,
not metal content`. `ORES` is `[{"key":"other_non_ferrous_metal_ores_incl_pgm","label":"Other non-ferrous
metal ores (incl. PGM)"},{"key":"nickel_ores","label":"Nickel ores"},{"key":"copper_ores","label":"Copper
ores"}]`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | F built | `GET /api/value-chain/status` | `ores` is exactly `ORES` | holdout |
| AC-2 | F0 built | `GET /api/value-chain/status` | 200; `ores` is `[]` | holdout |
| AC-3 | F built | `GET …/nodes/DE.3/footprint?indicator=ore:copper_ores&amount_meur=2` | `unit` `t ore`; `total` 143.3869; `by_region` `[["DE",111.6016],["CN",31.7853]]`; `by_sector` `[["Mining of copper ores and concentrates",143.3869]]`; `in_home_region` 0.7783; `ore_note` O | holdout |
| AC-4 | F built | `GET …/nodes/CN.2/footprint?indicator=ore:copper_ores` | `total` 1283.0655 | holdout |
| AC-5 | F built | `GET …/nodes/DE.3/footprint?indicator=ore:nickel_ores` | 200; `unit` `t ore`; `total` 0; `in_home_region` null; `by_region` `[]`; `by_sector` `[]`; `ore_note` O | holdout |
| AC-6 | F built | `GET …/nodes/DE.3/footprint?indicator=ore:sand_and_gravel` and `?indicator=ore:gold_ores` | each answers 422 | holdout |
| AC-7 | F built | `GET …/nodes/DE.3/tree?ore=copper_ores&amount_meur=2` (depth 2, width 3, cutoff 0.01) | root `ore_t` 143.3869 and `ore_note` O; root children in order CN.3 (`ore_t` 38.5661), DE.2 (`ore_t` 90.4821); under CN.3, children CN.2 (`ore_t` 25.6613) then DE.2 (`ore_t` 9.0482); under DE.2, one child DE.3 (`ore_t` 1.4339) | holdout |
| AC-8 | F built | `GET …/nodes/DE.3/tree?ore=gold_ores` | 422 | holdout |
| AC-9 | F built | `GET …/nodes/DE.3/footprint?indicator=ghg&amount_meur=2` | `unit` `t CO₂e`; `total` 1.4955; `by_region` `[["DE",1.395],["CN",0.1004]]`; `by_sector` `[["Mining of copper ores and concentrates",1.4268],["Other business activities",0.0687]]`; `in_home_region` 0.9328; no `ore_note` key | holdout |
| AC-10 | F built | `GET …/nodes/DE.3/tree?depth=2&width=3&cutoff=0.01` | exactly the tree of the explorer's AC-9 (ids, `coef`, `chain`); no item has an `ore_t` key and the response has no `ore_note` key | holdout |
| AC-11 | F0 | `arp io build-full IOT_2022_ixi.zip --out <d>` | exit 0; the same two stdout lines as the explorer spec's AC-1 | holdout |
| AC-12 | F built, screen at `#/valueChain/DE.3/footprint` | open the indicator picker | entries in order `CO₂e`, `Energy`, `Jobs`, `Other non-ferrous metal ores (incl. PGM) (ore)`, `Nickel ores (ore)`, `Copper ores (ore)` | evaluator |
| AC-13 | as AC-12 | pick `Copper ores (ore)`, amount 2 | total reads `143.4 t ore`; `78% in DE`; the line O shows under the caveat | evaluator |
| AC-14 | F built, screen at `#/valueChain/DE.3/tree` | pick `Show ore` `Copper ores`, amount 2 | root box `143.4 t ore`; level-1 CN.3 `38.6 t ore`; level-1 DE.2 `90.5 t ore`; CN.2 under CN.3 `25.7 t ore`; DE.2 under CN.3 `9.0 t ore`; DE.3 under DE.2 `1.4 t ore`; the line O shows under the caveat | evaluator |
| AC-15 | as AC-14 | set `Show ore` back to `None` | no box shows a `t ore` line | evaluator |
| AC-16 | the real `IOT_2022_ixi.zip` the explorer's evaluator rows use (Zenodo 23039074) | `arp io build-full` under `/usr/bin/time -v` | exit 0; elapsed ≤ 20:00 | evaluator |
| AC-16d | AC-16 built | `GET …/status` | `ores` is non-empty and one `label` contains `Copper` | evaluator |
| AC-16b | as AC-16 | read maximum resident set size | ≤ 8,388,608 KB | evaluator |
| AC-16c | AC-16 built, API process warmed by one request; `<k>` is the first key in `/status` `ores` whose label contains `Copper` | for 10 seeded random nodes with `output_meur` > 0: `/footprint?indicator=ore:<k>` and `/tree?depth=4&width=5&cutoff=0&ore=<k>`, from a client on localhost | each answers 200 in ≤ 1.0 s wall-clock | evaluator |
| AC-17 | F with `material/F.txt` holding only the sand row; `<d>` does not exist | `arp io build-full IOT_2022_ixi.zip --out <d>` | exit ≠ 0; the last non-empty line of stderr is exactly `material/F.txt: no row starts with 'Domestic Extraction Used - Metal Ores - '`; `<d>` still does not exist | holdout |
| AC-18 | F0 | in the same CI job, build F0 with `origin/main` and with the PR, each to its own `<d>` | identical file lists; every file except `manifest.json` byte-identical; `manifest.json` equal without `built_at` | holdout |
| AC-19 | as AC-15 | look under the caveat | the line O is not shown | evaluator |
| AC-20 | F built | `GET …/nodes/DE.3/tree?ore=copper_ores` | root `ore_t` 71.6934 | holdout |
| AC-21 | F built | `GET …/nodes/DE.3/tree?ore=copper_ores&amount_meur=0` | 422 | holdout |
| AC-21b | F built | `GET …/nodes/DE.3/tree?amount_meur=0` | 200, the same response as AC-10 | holdout |
| AC-22 | F built, screen at `#/valueChain/CN.2/footprint` | pick `Copper ores (ore)`, amount 1 | total reads `1,283 t ore` | evaluator |
| AC-23 | `ARP_VALUE_CHAIN_DIR` = an F0 build directory made by `main` (fixture in the holdout repo) | `GET …/status` | 200; `ores` `[]` | holdout |
| AC-24 | F built to `<d1>`, F0 built to `<d2>` | compare `nodes.csv`, and `manifest.json` without `built_at` and `source_sha256` | `nodes.csv` byte-identical; the two manifests equal | holdout |
| AC-25 | `ARP_ANTHROPIC_API_KEY` unset | every holdout row of this table except AC-25 and AC-25b (AC-1 to AC-11, AC-17, AC-18, AC-20, AC-21, AC-21b, AC-23, AC-24, AC-27, AC-29) | all pass | holdout |
| AC-25b | `ARP_ANTHROPIC_API_KEY` set to an invalid key (any model call fails) | as AC-25 | all pass | holdout |
| AC-26 | F built | open `#/valueChain/DE.3/tree` | `Show ore` reads `None`; amount reads `1`; no box shows a `t ore` line | evaluator |
| AC-27 | F0 built, and separately the AC-23 directory | `GET …/nodes/DE.3/footprint?indicator=ore:copper_ores` and `GET …/nodes/DE.3/tree?ore=copper_ores` | each answers 422 | holdout |
| AC-28 | as AC-13 | then pick `CO₂e` | total reads `1.5 t CO₂e`; the line O is not shown | evaluator |
| AC-29 | the explorer spec's holdout suite | run it twice: once as is (its fixture is F0), once with its fixture builder adding the `material/F.txt` of F above (its "F built" then means this spec's F) | every explorer holdout row passes both times | holdout |
| AC-29b | AC-16 built with the PR | the evaluator rechecks every `evaluator` row of the explorer spec | each passes | evaluator |
| AC-30 | the shared ore formatter | format 999.94 and 999.96 | `999.9 t ore` and `1,000 t ore` | unit |

Must not change: every explorer acceptance row (AC-29, AC-29b), plus AC-9, AC-10, AC-11, AC-18, AC-21b,
AC-23 and AC-24 for the touched endpoints and the build without ores.
