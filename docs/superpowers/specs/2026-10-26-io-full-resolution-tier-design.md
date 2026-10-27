# Indirect-exposure tier on full-resolution EXIOBASE

Status: approved by the owner, 2026-10-27. Owner decisions on 2026-10-26: retire the 50-industry path entirely (ICIO
source, `arp io import-icio`, `arp io import-exiobase`, the 10-industry samples); keep ICIO codes as
the labels for companies and activities and map them to nodes; replace the samples with a tiny
full-format sample; leave stored run results as they are; approach A (output-weighted node set).
First of four value-chain specs: (1) this, (2) shock simulation, (3) linking activities and
companies to nodes, portfolio overlays, (4) Neo4j summary graph and path finder.

## Intent

The indirect-exposure tier (theme runs, taxonomy research, the standards mapper) computes upstream
and downstream shares on a 50-industry table: `arp io import-exiobase` collapses EXIOBASE's
163 sectors × 49 regions into ICIO industries, so copper ore mining and nickel mining, or wind and
coal power, are one number. `arp io build-full` (spec `2026-10-24-value-chain-explorer-design.md`)
already writes the full 7,987-node Leontief inverse for the Value Chain Explorer. This spec points
the tier at that build and retires the 50-industry path, so there is one input-output model in the
product.

## Goals

- The tier's numbers come from the full-resolution build in `ARP_VALUE_CHAIN_DIR`, the same build the
  explorer reads.
- A company's own region counts: a Chinese machinery maker is computed on Chinese machinery nodes.
- Every field of `IndirectExposureResult` keeps its meaning and type.
- One model, one setting, one sample: the ICIO and 50-industry EXIOBASE code paths are gone.
- `build-full` also stores final demand, which the tier needs for `end_market` and spec 2 needs for
  demand shocks.

## Non-goals

- Classifying companies or activities into EXIOBASE sectors or nodes (spec 3).
- Shocks, Ghosh-based downstream measures, price model (spec 2). `downstream_exposure` keeps its
  current Leontief-row definition.
- Neo4j, path finding (spec 4).
- Migrating, re-running or flagging stored theme-run results.
- Changing the Value Chain Explorer's API or screen.

## Anti-goals

- A silent change of vocabulary: `core_isic_codes`, a company's `isic_code`, the revenue- and
  R&D-exposure relevance gates and the standards mapper (NACE/NAICS/SIC) keep working on ICIO codes.
- An LLM in the arithmetic. LLM calls stay where they are today (company and core-sector
  classification into the closed code list).
- Rewriting stored results: old runs keep the numbers and `icio_edition` they were computed with.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Output-weighted node set.** A company is the set of nodes whose sector maps to its ICIO code, in its country's EXIOBASE region (all regions if unknown), weighted by output; core = every node whose sector maps to a core code, any region. Shares come from the weighted columns and rows of `L`. | Exact; uses the full resolution and the company's region; regional split comes from the same vectors. Needs a country → region file. | **Chosen** |
| B | Largest node only: the biggest-output node of the code in the region. | Simple to explain; arbitrary for broad codes (`B07` = 7 sectors, `C20` many more). | Rejected |
| C | Collapse the full build back to 50 industries at load and keep today's tier code. | Smallest diff; throws the resolution away. | Rejected |

## Scope

1. **Model source.** `resolve_indirect_exposure_model(settings, *, use_sample=False)` in
   `arp.research.indirect_exposure.factory` returns a model read from `settings.value_chain_dir`
   (`ARP_VALUE_CHAIN_DIR`), or from the bundled sample when `use_sample` is true, or None (tier off)
   when the setting is unset. The setting is set but the directory has no `manifest.json`: raises
   `ValueError("value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR")`.
   The returned object keeps the attributes callers use today: `codes`, `labels`, `isic_divisions`,
   `nace_classes`, `edition_label` (the manifest's `edition`), `index_of()`,
   `industry_reference_list()`, `industry_prompt_list()`.
2. **Code list.** `codes` is the 50 ICIO 2025 codes of `reference/icio2025_industries.csv` in file
   order, then the 5 split codes `D_GEN_FOS`, `D_GEN_NUC`, `D_GEN_REN`, `D_TD`, `D_GAS` (55 codes).
   Labels and `isic_divisions` come from that file; the split codes take their labels and NACE
   classes from today's `SPLIT_INDUSTRIES` and have no `isic_divisions`. So `35` still resolves to
   `D`, and `35.12` to `D_TD`, without an LLM call (`35.11` matches three split codes and goes to the
   LLM, as today). `industry_reference_list()` and `industry_prompt_list()` list only the 50 ICIO codes:
   the LLM never picks a split code; split codes count only when supplied (theme files, a company's
   `isic_code`, a NACE class).
3. **Sector map.** An ICIO code `c` covers the EXIOBASE sectors whose `icio_code` is `c` in
   `reference/exiobase_ixi_to_icio2025.csv`; a split code covers those whose `split_code` is `c`.
4. **Country → region.** New `reference/country_exiobase_region.csv` (`code,region`): every ISO 3166-1
   alpha-2 and alpha-3 code, mapped to its EXIOBASE region (the country's own code for the 44
   EXIOBASE countries, otherwise `WA`, `WE`, `WF`, `WL` or `WM` per EXIOBASE 3's rest-of-world
   composition). Lookup is case-insensitive. Region groups for `regional` keep coming from
   `reference/region_groups.csv`.
5. **Exposure** (`compute_indirect_exposure`, same signature and result model): Definitions below.
6. **`build-full` additions**: reads `Y.txt` when present and writes `Y.npy` and `y_columns.csv`
   (Appendix A). Its stdout, `manifest.json`, `nodes.csv` and the `A`/`L`/`G` files are unchanged.
7. **Sample.** `backend/arp/research/indirect_exposure/sample_data/` is replaced by one `build-full`
   output directory, edition `sample`, with a README saying the values are illustrative: regions
   `DE`, `CN`, `US`, `WA`; sectors `Mining of copper ores and concentrates`, `Copper production`,
   `Production of electricity by wind`, `Production of electricity by coal`, `Manufacture of
   electrical machinery and apparatus n.e.c. (31)`, `Manufacture of motor vehicles, trailers and
   semi-trailers (34)`, `Construction (45)`, `Retail trade, except of motor vehicles and motorcycles;
   repair of personal and household goods (52)`; every node with output; with `Y.npy`.
8. **Flags.** `use_sample_icio` and `use_sample_exiobase` become one `use_sample_io` everywhere: theme
   runs (`api/routers/themes.py`, `research/pipeline.py`, `cli/theme.py` `run` and
   `classify-sectors`), taxonomy research and standards mapping (`api/routers/taxonomies.py`,
   `cli/taxonomy.py`, `research/standards_mapping/mapper.py`). CLI option `--use-sample-io`.
   Resuming a run whose stored params have `use_sample_icio` or `use_sample_exiobase` true uses the
   sample.
9. **Retired**: `arp io import-icio`, `arp io import-exiobase`, `--split-electricity`; settings
   `ARP_ICIO_MATRIX_PATH`, `ARP_ICIO_INDUSTRIES_PATH`, `ARP_ICIO_EDITION_LABEL`,
   `ARP_EXIOBASE_FLOWS_PATH`, `ARP_EXIOBASE_INDUSTRIES_PATH`, `ARP_EXIOBASE_EDITION_LABEL`,
   `ARP_IO_SOURCE`; `icio_loader.py`, `exiobase_loader.py`, the importer half of `io_import.py`, the
   Leontief disk cache, the old sample files; their tests (each listed in the PR). Unit tests of
   the tier are rewritten on the new model, not dropped.
10. **`arp io status`** prints `source: exiobase` or `source: none`; then, unless none,
    `edition: <label>`, `nodes: <n_nodes>`, `final demand: yes|no` (`Y.npy` present). When any
    retired setting above is set in the environment it also prints, to stderr, one line
    `ignored (retired): <NAME>` per such setting, in the order listed in 9; exit code stays 0.
11. **Messages.** Tier required but off: CLI `No input-output data available: run arp io build-full
    and set ARP_VALUE_CHAIN_DIR, or pass --use-sample-io.`; API 400 with the same text ending `or
    set use_sample_io.`
12. **Screens.** Theme Builder and Taxonomy Library send `use_sample_io`. Theme Builder's help text
    reads `Structural supply-chain exposure via EXIOBASE input-output propagation — catches companies
    with no direct textual evidence but real economic linkage to the theme's core sectors. The sample
    dataset is illustrative only; for a real run, set ARP_VALUE_CHAIN_DIR on the backend instead and
    leave this off.` Taxonomy Library's two checkbox labels read `sample input-output model (for
    ISIC classification)` and `Anchor against the bundled sample input-output industry list`.
13. **Retired acceptance rows.** The implementation PR strikes through every row of
    `2026-10-19-io-tables-import-design.md` and rows AC-39, AC-40, AC-41 of
    `2026-10-24-value-chain-explorer-design.md`, each with `retired by
    2026-10-26-io-full-resolution-tier-design.md`. The test-writer for this spec removes their
    holdout tests in the same holdout PR as this spec's tests.

## Definitions

Over the build's nodes in archive order; only nodes with `x > 0` take part anywhere below. `L` is
the build's Leontief inverse, `g` its `ghg_t_per_meur` (empty counts 0), `Yg` final demand summed
into the four groups of Appendix A (n × 4, M EUR), `y` its row sums.

- **Region of a company**: `R` = the region `country_exiobase_region.csv` gives its `country`, if
  that region has nodes in the build; else none.
- **Company nodes** `K`: nodes whose sector the company's code covers, in region `R` (every region
  when `R` is none). **Weights** `w_k = x_k / Σ_{K} x`.
- **Core nodes** `C`: nodes whose sector any core code covers, in every region.
- `K` or `C` empty, or the company code not in `codes`: the result is None.
- `c = L[:, K] · w` (composite column), `r = wᵀ · L[K, :]` (composite row).
- `upstream_exposure = Σ_{i∈C} c_i / Σ_i c_i`; `downstream_exposure = Σ_{j∈C} r_j / Σ_j r_j`;
  both clamped to [0, 1].
- `end_market`: `d = r · Yg`; each group's `d / Σ d`, keys in Appendix A order. `theme_demand_share =
  Σ_{j∈C} r_j · y_j / Σ d`, clamped. Both null without `Y.npy` or when `Σ d = 0`.
- `ghg_direct_t_per_meur = Σ_k w_k g_k`; `ghg_supply_chain_t_per_meur = g · c`.
- `regional`: null when `R` is none. Otherwise `region` = the group of `R` in `region_groups.csv`;
  `upstream_by_region[G] = Σ_{i∈C, group(i)=G} c_i / Σ_i c_i` for every group with nodes in the
  build, keys in the order groups first appear in `region_groups.csv`; `downstream_by_region` the
  same with `r`; `upstream` and `downstream` are the sums of their maps, clamped.
- `isic_code`, `isic_label`, `core_sector`, `critical_input` as today (on the ICIO code);
  `icio_edition` is the `edition` argument as today.

## My calls (owner to confirm with the acceptance table)

1. **One setting.** The tier reads `ARP_VALUE_CHAIN_DIR`, the explorer's setting, so one build backs
   both. No separate on/off switch: unset = off, as today.
2. **55 codes, 50 offered** (owner, 2026-10-26): the 5 electricity split codes are accepted so themes
   that carry them keep them and `35.12` resolves without an LLM call, but classification prompts
   offer only the 50, so the gates, the standards mapper and the LLM cache see what they see today.
3. **Region from country, not from group.** The company is computed on its own country's nodes,
   which makes `regional.upstream` equal `upstream_exposure` whenever `regional` is set. Countries
   in EXIOBASE's rest-of-world are computed on their RoW region.
4. **Full `Y`, not grouped.** `build-full` stores `Y` per region of demand and category so spec 2 can
   shock demand by region; the tier groups it on load.
5. **Retired settings are reported, not rejected**, by `arp io status`, so a deployment that upgrades
   sees why its tier went off without the app failing to start.
6. **Tests of retired code are deleted** with the code, and tests that pass the old flags
   (`tests/test_standards_mapper.py` among them) are edited to `use_sample_io`; a test of
   `use_sample_exiobase` becomes one of `use_sample_io`. This is a retirement the owner chose, not
   weakening a test to pass; the PR lists every deleted and rewritten test file.
7. **Docs**: `docs/METHODOLOGY.md`'s indirect-exposure section and the sample README are updated in
   the implementation PR. `openwiki/` is regenerated by the weekly refresh, not by hand.

## Constraints

- float64 throughout; nothing rounded before display.
- Real build (7,987 nodes): `resolve_indirect_exposure_model` ≤ 30 s and ≤ 1.5 GB added resident
  memory (memory-mapping `L` is fine); one `compute_indirect_exposure` ≤ 2 s once loaded.
- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`; API contract regenerated
  (`scripts/export_openapi.py`, `npm run gen:api`).

## Left to the builder

Module layout (whether `leontief.py` keeps the `LeontiefModel` name), how `L` is read (in memory or
memory-mapped), the sample's flow values, and how the sample directory is produced (a committed
fixture archive plus `build-full`, or committed output only).

## What this leaves ready for specs 2–4

- **Spec 2 (shocks):** `A`, `L`, `G`, `x`, `Y` per region and category, value added (`va_share × x`)
  and the GHG, energy and jobs intensities all sit in one build directory; the tier already reads it.
- **Spec 3 (linking):** the ICIO-code → sector and country → region maps are the default link from a
  company or activity to nodes; spec 3 can replace the code-based link with direct node links
  without touching the arithmetic.
- **Spec 4 (graph):** one model, one node id scheme (`<region>.<sector no>`) shared by the tier and
  the explorer.

## Appendix A: `Y.npy` and `y_columns.csv`

- `y_columns.csv`: header `region,category`, one row per `Y.txt` column in archive order.
- `Y.npy`: float64, shape `(n_nodes, rows of y_columns.csv)`, rows in node order, M EUR as in
  `Y.txt`; an empty cell is 0.
- `Y.txt` layout as in `2026-10-19-io-tables-import-design.md` My call 6. Absent: neither file is
  written. A category not in the table below: exit 1, stderr `Y.txt: unknown final-demand category:
  <name>`.
- Groups, in this order (Exports are not final demand of any region's economy here and are left
  out, as today):

| Group | EXIOBASE categories |
|---|---|
| households | `Final consumption expenditure by households`; `Final consumption expenditure by non-profit organisations serving households (NPISH)` |
| government | `Final consumption expenditure by government` |
| investment | `Gross fixed capital formation` |
| inventories | `Changes in inventories`; `Changes in valuables` |
| (none) | `Exports: Total (fob)` |

## Acceptance

**Fixture V**: an archive `IOT_2022_ixi.zip` in the layout of the explorer spec's Fixture F
(`metadata.json` `version` `3.11.2`, `name` `EXIO_IOT_2022_ixi`). Regions, in order, `DE`, `CN`,
`WA`; sectors, in order, `Mining of copper ores and concentrates` (1), `Mining of nickel ores and
concentrates` (2), `Production of electricity by wind` (3), `Manufacture of electrical machinery and
apparatus n.e.c. (31)` (4). Node ids `DE.1` … `WA.4`.

- `x`: DE `[50, 0, 100, 200]`, CN `[100, 40, 80, 400]`, WA `[60, 20, 10, 50]`.
- `Z` (supplier → user, M EUR), 0 except: CN.1→CN.4 40, CN.2→CN.4 20, WA.1→CN.4 20, DE.1→DE.4 10,
  CN.1→DE.4 10, CN.3→CN.4 20, DE.3→DE.4 20, DE.4→DE.3 30, CN.4→CN.3 16, CN.4→DE.3 10,
  CN.3→CN.1 10, WA.4→WA.1 6, WA.1→WA.4 5, DE.4→CN.4 20.
- `Y.txt`: columns region-major (`DE`, `CN`, `WA`), within each region the 7 categories in Appendix A's
  table order, exact strings as there; 0 except (column region, category,
  row node, value): DE GFCF DE.4 100; DE households DE.4 20; CN GFCF CN.4 200; CN households CN.4
  100; DE households CN.4 30; DE households DE.3 50; CN households CN.3 30; CN government CN.3 4;
  CN changes in inventories CN.1 10; WA households WA.4 39; CN exports CN.4 999.
- `air_emissions/F.txt`: `CO2 - combustion - air` CN.1 100000, CN.4 2000000, DE.4 400000 kg;
  `CH4 - agriculture - air` WA.1 1000 kg; 0 elsewhere. `energy`, `employment` and `factor_inputs`
  each one all-zero row as in Fixture F.
- "V built": `arp io build-full IOT_2022_ixi.zip --out <d>` ran and `ARP_VALUE_CHAIN_DIR=<d>`.
- **Exposure rows** call `compute_indirect_exposure("x", <code>, model, <core>, "e", country=<c>)`
  from `arp.research.indirect_exposure.exposure` with `model =
  resolve_indirect_exposure_model(Settings())` (`Settings` from `arp.config`) and read the returned
  `IndirectExposureResult`. Floats compared rounded to 4 decimals.
- **Lookup rows** call `await resolve_company_isic(company, model, llm)` with the stub `llm` of
  `2026-10-19-io-tables-import-design.md` (records calls, returns `isic_code=None`).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture V | `arp io build-full IOT_2022_ixi.zip --out <d>` | exit 0; stdout line 1 `12 nodes (4 sectors × 3 regions) -> <d>` | holdout |
| AC-2 | as AC-1 | read `<d>/y_columns.csv` | 21 data rows: for `DE`, `CN`, `WA` in turn, the 7 categories in Appendix A's table order (households, NPISH, government, GFCF, inventories, valuables, exports) | holdout |
| AC-3 | as AC-1 | `numpy.load(<d>/Y.npy)` | shape `(12, 21)`; row CN.4 column (CN, `Gross fixed capital formation`) 200; row CN.4 column (CN, `Exports: Total (fob)`) 999; row CN.4 column (DE, households) 30 | holdout |
| AC-4 | Fixture V without `Y.txt` | `arp io build-full` | exit 0; `<d>` has no `Y.npy` and no `y_columns.csv` | holdout |
| AC-5 | Fixture V with the `Changes in valuables` cell of region `CN` on `Y.txt` line 2 replaced by `Made-up demand` | `arp io build-full` | exit 1; stderr contains `Y.txt: unknown final-demand category: Made-up demand` | holdout |
| AC-6 | V built | `resolve_indirect_exposure_model(Settings())` | `edition_label` `exiobase-IOT_2022_ixi`; `codes` has 55 entries, the last five `D_GEN_FOS`, `D_GEN_NUC`, `D_GEN_REN`, `D_TD`, `D_GAS` | holdout |
| AC-6b | V built | `model.industry_prompt_list()` | 50 lines, one per code of `icio2025_industries.csv`; none contains `D_GEN` | holdout |
| AC-7 | `ARP_VALUE_CHAIN_DIR` unset | `resolve_indirect_exposure_model(Settings())` | returns None | holdout |
| AC-8 | `ARP_VALUE_CHAIN_DIR` = an empty directory | `resolve_indirect_exposure_model(Settings())` | raises `ValueError` with message `value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR` | holdout |
| AC-9 | V built | exposure `C27`, core `{"B07"}`, country `CN` | `upstream_exposure` 0.1549, `downstream_exposure` 0.015 | holdout |
| AC-9b | as AC-9 | same call | `isic_code` `C27`, `isic_label` `Manufacture of electrical equipment`, `core_sector` false, `icio_edition` `e`, `company_id` `x` | holdout |
| AC-10 | as AC-9 | same call | `end_market` `{"households": 0.4116, "government": 0.0023, "investment": 0.5855, "inventories": 0.0006}` in that key order; `theme_demand_share` 0.0006 | holdout |
| AC-11 | as AC-9 | same call | `ghg_direct_t_per_meur` 5, `ghg_supply_chain_t_per_meur` 5.2949 | holdout |
| AC-12 | as AC-9 | same call | `regional.region` `CN`; `upstream_by_region` `{"CN": 0.1149, "EU": 0.0019, "ASIA_OTH": 0.038}` in that key order; `downstream_by_region` `{"CN": 0.015, "EU": 0, "ASIA_OTH": 0}`; `upstream` 0.1549 | holdout |
| AC-13 | V built | exposure `C27`, core `{"B07"}`, country None | `upstream_exposure` 0.1295, `downstream_exposure` 0.0152, `ghg_direct_t_per_meur` 3.6923, `ghg_supply_chain_t_per_meur` 3.9307; `regional` null | holdout |
| AC-14 | V built | exposure `B07`, core `{"C27"}`, country `CN` | `upstream_exposure` 0.014, `downstream_exposure` 0.1085, `ghg_direct_t_per_meur` 0.7143, `theme_demand_share` 0.7939 | holdout |
| AC-15 | V built | exposure `B07`, core `{"C27"}`, country `DE` (DE.2 has no output) | `upstream_exposure` 0, `downstream_exposure` 0.0506, `regional.region` `EU` | holdout |
| AC-16 | V built | exposure `C27`, core `{"D_GEN_REN"}`, country `CN`; then core `{"D"}` | both: `upstream_exposure` 0.0493, `downstream_exposure` 0.2273, `theme_demand_share` 0.0348 | holdout |
| AC-17 | V built | exposure `C27`, core `{"B07"}`, country `THA`; then country `th` | both: `upstream_exposure` 0.0909, `downstream_exposure` 0.0904, `regional.region` `ASIA_OTH` | holdout |
| AC-18 | V built | exposure `C27`, core `{"B07"}`, country `US` (no `US` nodes in V) | same values as AC-13 | holdout |
| AC-19 | V built | exposure `C27`, core `{"B07", "D"}`, country `DE` | `upstream_exposure` 0.1705, `downstream_exposure` 0.2313, `theme_demand_share` 0.1025, `ghg_direct_t_per_meur` 2 | holdout |
| AC-20 | V built | exposure `B07`, core `{"A01"}`, country `CN`; then code `ZZ`, core `{"B07"}` | both return None | holdout |
| AC-21 | V built without `Y.txt` | exposure as AC-9 | `end_market` null, `theme_demand_share` null; `upstream_exposure` 0.1549 | holdout |
| AC-22 | V built | lookup with `isic_code` `27`; then `35`; then `35.12` | `C27`, `D`, `D_TD`; the stub recorded 0 calls | holdout |
| AC-23 | V built | lookup with `isic_code` `D_GEN_REN` | `D_GEN_REN`; 0 stub calls | holdout |
| AC-24 | — | `resolve_indirect_exposure_model(Settings(), use_sample=True)`, then exposure `C27`, core `{"B07"}`, country `CN` on it | `edition_label` `sample`; result not None; `upstream_exposure` > 0, `downstream_exposure` > 0, `end_market` not null | holdout |
| AC-25 | V built | `arp io status` | exit 0; stdout exactly `source: exiobase`, `edition: exiobase-IOT_2022_ixi`, `nodes: 12`, `final demand: yes` | holdout |
| AC-25b | V built without `Y.txt` | `arp io status` | stdout line 4 `final demand: no` | holdout |
| AC-26 | `ARP_VALUE_CHAIN_DIR` unset, `ARP_IO_SOURCE=icio` and `ARP_ICIO_MATRIX_PATH=/x` in the environment | `arp io status` | exit 0; stdout `source: none`; stderr lines exactly `ignored (retired): ARP_ICIO_MATRIX_PATH`, `ignored (retired): ARP_IO_SOURCE` | holdout |
| AC-27 | — | `arp io import-exiobase x.zip --out d`; then `arp io import-icio x.csv --out d` | each exits 2 with `No such command` on stderr | holdout |
| AC-28 | — | `arp theme classify-sectors --use-sample-icio …` | exit 2, stderr contains `No such option: --use-sample-icio` | holdout |
| AC-28b | — | `arp taxonomy create --use-sample-exiobase …` | exit 2, stderr contains `No such option: --use-sample-exiobase` | holdout |
| AC-29 | `ARP_VALUE_CHAIN_DIR` unset, any valid theme file `<f>` | `arp theme classify-sectors --theme <f> --out <o>` | exit 1; stderr `No input-output data available: run arp io build-full and set ARP_VALUE_CHAIN_DIR, or pass --use-sample-io.` | holdout |
| AC-30 | `ARP_VALUE_CHAIN_DIR` unset; app as in the 2026-10-19 spec's API rows | `POST /api/taxonomies` with `{"name": "t", "derivation_method": "industry_anchored", "use_sample_io": false}` | 400, `detail` `No input-output data available: run arp io build-full and set ARP_VALUE_CHAIN_DIR, or set use_sample_io.` | holdout |
| AC-31 | a stored theme run whose `manifest.json` params have `use_sample_icio: true`, interrupted before its first company; a second such run with `use_sample_exiobase: true` instead | resume each | in both, the first company result has `indirect_exposure.icio_edition` `sample` | holdout |
| AC-32 | — | `GET /openapi.json` | the request schemas of `POST /api/themes/runs` and `POST /api/taxonomies` have property `use_sample_io` and neither `use_sample_icio` nor `use_sample_exiobase` | holdout |
| AC-33 | Real `IOT_2022_ixi.zip` (Zenodo record 23039074) built with `build-full` | read `y_columns.csv` | 343 data rows (49 regions × 7) | evaluator |
| AC-34 | as AC-33 | exposure `C27`, core `{"B07"}`, country `CN` | not None; `regional.region` `CN`; `upstream_by_region` keys exactly `CN, US, EU, EUR_OTH, JP, KR, TW, IN, ASIA_OTH, AMER_OTH, MEA` in that order | evaluator |
| AC-35 | as AC-33 | time `resolve_indirect_exposure_model` and read the process's RSS before and after | ≤ 30.0 s; RSS grows ≤ 1,572,864 KB | evaluator |
| AC-36 | as AC-35, model loaded | time 10 `compute_indirect_exposure` calls (country None, codes `C27`, `B07`, `D`, `C20`, `C29`, `F`, `G`, `K`, `A01`, `C24A`; core `{"B07"}`) | each ≤ 2.0 s | evaluator |
| AC-37 | Thematic Universe screen `#/theme` | tick the sample checkbox and start a run | the request body has `use_sample_io: true` | evaluator |
| AC-37b | Thematic Universe screen `#/theme` | read the help text under the sample checkbox | exactly as Scope 12 | evaluator |
| AC-38 | Taxonomy Library | read the two checkbox labels | exactly as Scope 12 | evaluator |
| AC-38b | Taxonomy Library, new taxonomy, method industry-anchored | tick the sample checkbox and create | the request body has `use_sample_io: true` | evaluator |

Must not change:

- AC-39: the Value Chain Explorer spec's holdout rows AC-1 to AC-25b still pass (its Fixture F has
  no `Y.txt`). Checked by: holdout.
- AC-40: `build-full` on Fixture V writes `manifest.json` and `nodes.csv` byte-identical to those the
  PR's merge-base with `main` writes, apart from `built_at`. Checked by: holdout.
- AC-41: a stored theme run from before this change opens in Run History; its indirect-exposure
  figures equal the values in the run's stored result file, and it reads `Computed from <stored icio_edition>`. Checked by: evaluator.
- AC-42: `pytest tests/test_revenue_resolver.py tests/test_rd_exposure_resolver.py
  tests/test_api_value_chain.py tests/test_value_chain_model.py`
  (from `backend/`) exits 0 with no test removed from those files. Checked by: unit.
