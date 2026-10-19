# Import real OECD ICIO and EXIOBASE tables, with end markets, emissions, an electricity split and regions

Status: draft, 2026-10-19. Owner decisions: [research note](../../SECTOR_IO_MODELS_RESEARCH.md) §4
(EXIOBASE licence is no obstacle; focus on ICIO and EXIOBASE), scope "importers + source choice",
EXIOBASE "map to ISIC Rev.4", and on 2026-10-19 "one spec only" for the four extensions, the
electricity split into 5 industries, and 12 region groups.

## Intent

The indirect-exposure tier (`backend/arp/research/indirect_exposure/`) can read an ICIO-shaped
matrix and an EXIOBASE-shaped flows file, but only files someone has already prepared by hand.
Nothing turns the files the publishers actually ship into that shape. This spec adds two import
commands that do, a setting that picks which table backs a run, and a way for companies' own ISIC
codes to find the right industry. It also reads four more parts of the same files, each giving one
new result next to today's upstream and downstream shares: where an industry's output ends up
(final demand), its carbon intensity (EXIOBASE emissions), a split of electricity into generation,
grid and gas (EXIOBASE), and where in the world the exposure sits (12 region groups).

## Scope

1. `arp io import-icio <csv> --out <dir> [--label <label>]` reads one OECD ICIO **2025 edition**
   year file and writes `industries.csv` and `icio_matrix.csv` (the pair `load_icio` already
   reads), plus `final_demand.csv`, `regional_output.csv` and `regional_flows.csv`.
2. `arp io import-exiobase <zip> --out <dir> [--label <label>] [--split-electricity]` reads one
   EXIOBASE 3 **ixi** archive (`IOT_<year>_ixi.zip`) and writes `industries.csv` and
   `exiobase_flows.csv` (the pair `build_icio_from_long_format` already reads), plus
   `final_demand.csv`, `ghg.csv`, `regional_output.csv` and `regional_flows.csv`.
3. Both outputs use the ICIO 2025 industry list (Appendix A), with ICIO's codes. EXIOBASE's 163
   sectors map onto it by a bundled crosswalk (Appendix B). With `--split-electricity`, EXIOBASE's
   electricity, gas and steam sectors map to 5 industries in place of `D` (54 industries).
4. Setting `ARP_IO_SOURCE` = `auto` (default) | `icio` | `exiobase`.
5. `arp io status` prints, one per line: `source: icio|exiobase|none`; then, unless `none`,
   `edition: <label>`, `industries: <n>`, `final demand: yes|no` (`final_demand.csv` present),
   `emissions: yes|no` (`ghg.csv` present) and `regions: <n>|no` (n = number of groups in
   `regional_output.csv`; `no` when that file is absent).
6. A company `isic_code` that is an ISIC Rev.4 division (`26`) or, with the split, a NACE class
   (`35.12`) resolves to the industry that contains it without an LLM call.
7. `IndirectExposureResult` gains five optional fields: `end_market`, `theme_demand_share`,
   `ghg_direct_t_per_meur`, `ghg_supply_chain_t_per_meur`, `regional`. Each is null when its
   extra file is absent, so runs on today's files are unchanged. `end_market` is a
   `dict[str, float]` with keys `households`, `government`, `investment`, `inventories` in that
   order; the two `ghg_*` fields and `theme_demand_share` are `float`; `regional` is a pydantic
   model `RegionalExposure` (in `arp.schemas.exposure`) with fields `region: str`,
   `upstream: float`, `downstream: float`, `upstream_by_region: dict[str, float]` and
   `downstream_by_region: dict[str, float]`.

## My calls (owner to confirm with the acceptance table)

1. **Industry codes are ICIO's own codes** (`C26`, `D`, `J62_63`), in Appendix A order, for both
   importers. An ICIO-backed and an EXIOBASE-backed run share one code list unless the EXIOBASE
   import used `--split-electricity`.
2. **Reference files ship with the code**, in `backend/arp/research/indirect_exposure/reference/`:
   `icio2025_industries.csv` (`code,label,isic_divisions`, Appendix A),
   `exiobase_ixi_to_icio2025.csv` (`exiobase_sector,icio_code,split_code`, Appendix B, 163 rows in
   order), `region_groups.csv` (`code,group`, Appendix C) and `ghg_gwp100.csv`
   (`stressor,factor`, Appendix D). Sector and stressor names are exact archive strings.
3. **Summed model**: the existing matrix files sum all regions, as `ICIOData` already documents.
   "N regions" in the import message is the number of distinct region prefixes among industry
   *row* labels (ICIO) or among `Z.txt` data rows (EXIOBASE).
4. **ICIO input layout** (from the 2025 edition note and pymrio's `parse_oecd`): comma-separated;
   the first row is the header and the first column holds row labels; the header's first cell can
   be anything. A label is an *industry label* when the part after its first `_` is one of the 50
   codes (`AUS_C26`, `ROW_J62_63`, `CN1_D`), and a *final-demand label* when that part is one of
   `HFCE`, `NPISH`, `DPABR`, `GGFC`, `GFCF`, `INVNT`. Only three kinds of cell are read:
   industry×industry cells, industry-row × final-demand-column cells, and the `OUT` column's cell
   in each industry row (that row's total output). Every other row (`TLS`, `VA`, `OUT`, …) and
   column is never parsed. An empty cell that is read counts as 0.
5. **Missing industries (ICIO)**: an Appendix A code is missing when no industry row label, or no
   industry column label, in any region has that code. A code present in only some regions is not
   missing. The error lists missing codes in Appendix A order, joined with `, `.
6. **EXIOBASE input layout** (read from the real `IOT_2022_ixi.zip`, release 3.11.2), all
   tab-separated:
   - `Z.txt` at the root: line 1 `region`, an empty cell, then one region per column; line 2
     `sector`, an empty cell, then one sector name per column; line 3 `region`, `sector`, then one
     empty cell per column. Every later line: region, sector name, then one value per column.
   - `x.txt` at the root: header `region\tsector\tindout`, then one line per (region, sector).
   - `Y.txt` at the root, optional: line 1 `region`, empty, one region per column; line 2
     `category`, empty, one final-demand category per column; line 3 `region`, `sector`, empty
     cells; then rows as in `Z.txt`.
   - `air_emissions/F.txt`, optional: line 1 `region` then one region per column; line 2 `sector`
     then one sector name per column; then lines whose first cell is a stressor name followed by
     one value per column. A line whose first cell is not an Appendix D stressor is skipped.

   Columns are identified by their header lines, never by position. Lines may end in `\r\n` (the
   real `Y.txt` does); a trailing `\r` is stripped from every line. `Z.txt` is read one line at a
   time. A sector name in the archive that is not in the crosswalk is an error; a crosswalk sector
   absent from the archive is not. "N sectors" in the import message is the number of distinct
   sector names among `Z.txt` data rows. When `Y.txt` or `air_emissions/F.txt` is absent, the
   matching output file is not written.
7. **Total output** comes from ICIO's `OUT` column and EXIOBASE's `indout`, summed over regions
   and, for EXIOBASE, over the sectors that map to the same industry. An industry no EXIOBASE
   sector maps to (B09, C21, C301, H53, J58T60; see Appendix B) gets total output 0 and no flows.
8. **`industries.csv` gains two columns, `isic_divisions` and `nace_classes`**: the ISIC Rev.4
   divisions an industry covers (two digits each, joined with `;`; `C10T12` → `10;11;12`), and
   the NACE Rev.2 classes that pin it down where divisions cannot (only the 5 split industries
   have any; empty otherwise). The existing loaders ignore extra columns, so hand-prepared files
   without them keep working.
9. **Code lookup**: a company `isic_code` that is not one of the model's codes but equals, as an
   exact string, one entry in exactly one industry's `isic_divisions` or `nace_classes` resolves
   to that industry, with no LLM call. No normalisation: `2610`, `6` or `26.1` match nothing. A
   division or class found in two or more industries (`24`: C24A and C24B; `30`; with the split,
   `35` and `35.11`) and any other code fall back to the LLM classification, as an unknown code
   does today.
10. **`ARP_IO_SOURCE`**: `auto` keeps today's rule (ICIO if its two paths are set, else EXIOBASE
    if its two are set, else the tier is off). `icio` or `exiobase` uses only that table, and
    raises a `ValueError` when either of its two paths is unset, which today's CLI commands report
    on stderr with exit 1 and the API returns as 400. The sample flags (`use_sample_icio`,
    `use_sample_exiobase`) still win over the setting. Values are case-sensitive; any other value
    fails the settings load.
11. **Importer output**: `--out` is created with its parents if missing. Paths printed are
    `Path(<dir>).resolve()`. Output files that already exist are overwritten on success, and any of `final_demand.csv`,
    `ghg.csv`, `regional_output.csv`, `regional_flows.csv` that this import did not produce is
    deleted from `<dir>`. On any
    error: exit 1, exactly one line on stderr, and no output file written. The extra files
    (`final_demand.csv`, `ghg.csv`, `regional_output.csv`, `regional_flows.csv`) are found by name
    in the directory of the configured industries file; no new settings.
12. **Default labels**: `icio-<file stem>` and `exiobase-<archive stem>` (`icio-2022_SML`,
    `exiobase-IOT_2022_ixi`). `arp io status` prints the active source's `ARP_*_EDITION_LABEL`
    setting; unset, it keeps today's defaults, `sample` (ICIO) and `exiobase-sample` (EXIOBASE).
13. **Final demand** is folded into 4 groups. ICIO: `HFCE`, `NPISH`, `DPABR` → households;
    `GGFC` → government; `GFCF` → investment; `INVNT` → inventories. EXIOBASE, matched as exact
    strings: `Final consumption expenditure by households` and `Final consumption expenditure by
    non-profit organisations serving households (NPISH)` → households; `Final consumption
    expenditure by government` → government; `Gross fixed capital formation` → investment;
    `Changes in inventories` and `Changes in valuables` → inventories; `Exports: Total (fob)` is
    ignored. Any other category is an error: `unknown final-demand category: <name>`. For industry j, with `L` the summed model's Leontief inverse and `y_c` the
    final-demand vector of group c: `end_market[c] = (L·y_c)[j] / (L·y)[j]`, with
    `y = Σ_c y_c`. `theme_demand_share = Σ_{k∈core} L[j,k]·y[k] / (L·y)[j]`, clamped to [0, 1].
    Both are null when `(L·y)[j]` is 0.
14. **Emissions** (EXIOBASE only): each Appendix D stressor is multiplied by its GWP100 factor
    (IPCC AR6; CH₄ from fuels and combustion counted as fossil, CH₄ from agriculture and waste as
    non-fossil; biogenic CO₂ 0; HFC and PFC are already in kg CO₂e) and summed per industry into
    `ghg.csv` as kg CO₂e. With `x` the summed total output (million EUR):
    `ghg_direct_t_per_meur[j] = kg[j] / 1000 / x[j]` (0 when `x[j]` is 0) and
    `ghg_supply_chain_t_per_meur = f·L`, the row vector of direct intensities times the Leontief
    inverse. ICIO-backed models have no `ghg.csv`, so both fields are null.
15. **Electricity split** (`--split-electricity`, EXIOBASE only): `D` is replaced, at its place in
    Appendix A order, by `D_GEN_FOS`, `D_GEN_NUC`, `D_GEN_REN`, `D_TD`, `D_GAS` (Appendix A2),
    following Appendix B's Split column. Without the flag, the output is exactly the 50-industry
    output.
16. **Regions** fold into the 12 groups of Appendix C, in Appendix C order. A table region not in
    Appendix C is an error. `regional_output.csv` and `regional_flows.csv` hold the
    region-resolved model: one industry per (group, code) for every group that has at least one
    industry row or column label in the file. For a company, its `CompanyRef.country` (ISO
    3166-1 alpha-2 or alpha-3, case-insensitive, matched against Appendix C's country rows)
    picks the group; `regional` is null when the country is missing, is not in Appendix C, is one
    of the special codes, or names a group that has no industries in the model.
    `regional` is `{"region", "upstream", "downstream", "upstream_by_region",
    "downstream_by_region"}`: the call 17 formulas on the region-resolved inverse, using the company's (group, code)
    column and row, with core industries counted in every group; `*_by_region` splits that share
    by the group of the core industry, with one key per group in the model, in Appendix C order.
17. **Unchanged results**: `upstream_exposure` and `downstream_exposure` keep being computed from
    the summed model exactly as today. The Leontief inverse, for both the summed and the
    region-resolved model, is `L = (I − A)⁻¹` with `A[i,j] = Z[i,j] / x[j]`, `Z` the flows and `x`
    the `total_output` (`regional_output.csv` for the region-resolved model); column j of `A` is 0
    when `x[j]` is 0. The region-resolved model keeps every (group, code) industry, including
    those with zero output. With `L` the Leontief inverse and j the company's industry,
    upstream is `Σ_{k∈core} L[k,j] / Σ_k L[k,j]` (the core share of column j) and downstream is
    `Σ_{k∈core} L[j,k] / Σ_k L[j,k]` (the core share of row j), each 0 when its sum is 0 and
    clamped to [0, 1].

## Not in this spec

- Other tables (FIGARO, BEA, GLORIA, …), other EXIOBASE systems (`pxp`), other ICIO editions.
- Downloading files: the user downloads them; the commands read local files.
- Per-run source choice in the API or UI, and side-by-side comparison of the two tables.
- Keeping EXIOBASE's native 163 sectors beyond the electricity split.
- Showing the new fields in the UI; they appear in the API and stored results only.
- Non-GHG emissions, water, land, energy, materials and employment accounts.
- The criticality overlay and standards mapping. Both match ISIC divisions such as `07`, so with
  imported tables they will not match ICIO codes such as `B07` until a later change.
- Region groups other than Appendix C, and per-country (ungrouped) results.

## Acceptance

Setup notes for the test-writer:
- Run commands as `arp io …`. Settings are read from the environment when each command starts.
  Tests set only the variables a row or these notes name; every other `ARP_` variable is unset.
- `<D>` is `Path(<dir>).resolve()`. Import rows pass `--out` as a relative path.
- In every import error row (AC-6, AC-7, AC-8, AC-14, AC-15, AC-48, AC-81, AC-94, AC-101), `<dir>` starts empty,
  stderr is exactly one line, and afterwards `<dir>` holds no `.csv` file. Other exit-1 rows check
  only that stderr contains the given text.
- `industries.csv` columns: `isic_code,label,total_output,isic_divisions,nace_classes`, one row per
  industry, in Appendix A order (Appendix A2 order with the split).
- `icio_matrix.csv`: header `isic_code,<code 1>,…,<code n>`; then one row per code, first cell the
  code; cell (i, j) is the flow from industry i to industry j.
- `exiobase_flows.csv`: header `supplier_isic_code,user_isic_code,value`; one row per supplier/user
  pair with a non-zero value, ordered by supplier then user in industry order.
- `final_demand.csv`: header `isic_code,households,government,investment,inventories`, one row per
  industry in industry order. `ghg.csv`: header `isic_code,kg_co2e`, one row per industry.
- `regional_output.csv`: header `region,isic_code,total_output`, one row per (group, industry), groups
  in Appendix C order, industries in industry order. `regional_flows.csv`: header
  `supplier_region,supplier_isic_code,user_region,user_isic_code,value`, non-zero values only, ordered
  by supplier group, supplier code, user group, user code.
- Numbers are compared as floats with a relative tolerance of 1e-6 (absolute 1e-12 near 0). A
  fraction such as `25/192` stands for its exact value.
- **Fixture I** (ICIO): file `icio_fixture.csv`. Header: `V1`, then columns for every Appendix A
  code in region `DEU` then region `CHN` (`DEU_A01` … `DEU_T`, `CHN_A01` … `CHN_T`), then
  `DEU_HFCE`, `CHN_GFCF` and `OUT`. Rows: the same 100 industry labels in the same order, then
  `TLS`, `VA` and `OUT`. All industry×industry cells are 0 except `DEU_C26→CHN_C27` = 10,
  `CHN_C26→DEU_C27` = 5 and `DEU_D→DEU_C26` = 2 (row label → column label). `OUT` is 100 for
  `DEU_C26`, 50 for `CHN_C26`, 40 for `DEU_C27`, 60 for `CHN_C27`, 30 for `DEU_D` and 1 for every
  other industry row. `DEU_HFCE` is 20 for `DEU_C27`, 10 for `CHN_C27`, 5 for `DEU_D`, else 0;
  `CHN_GFCF` is 50 for `DEU_C27`, else 0. Every cell of the `TLS`, `VA` and `OUT` rows is 7.
- **Fixture E** (EXIOBASE): file `IOT_fixture_ixi.zip`, holding `Z.txt`, `x.txt`, `Y.txt` and
  `air_emissions/F.txt` in the layout of call 6, lines ending in `\n`, with regions `AT` then `WA`
  and, within each, the 163 Appendix B names in Appendix B order, for rows and columns. B#n is
  Appendix B row n. `Z` values are 0 except (AT, B#87)→(WA, B#88) = 10, (WA, B#89)→(AT, B#88) = 5,
  (AT, B#108)→(AT, B#87) = 2 and (AT, B#100)→(AT, B#87) = 3 (row → column). `indout` is 100 for
  (AT, B#87), 50 for (WA, B#89), 40 for (AT, B#88), 60 for (WA, B#88), 30 for (AT, B#108), 20 for
  (AT, B#100) and 0 otherwise. `Y.txt` has, for each region, the 7 categories in the order
  households, NPISH, government, gross fixed capital formation, changes in inventories, changes in
  valuables, `Exports: Total (fob)` (exact strings in call 13); values are 0
  except (AT, B#88)×(AT, households) = 30, (AT, B#88)×(WA, gross fixed capital formation) = 50,
  (AT, B#108)×(AT, households) = 5, (WA, B#89)×(AT, changes in valuables) = 4 and
  (AT, B#87)×(AT, Exports) = 999. `air_emissions/F.txt` has 4 stressor lines, values 0 except
  `CO2 - combustion - air` (AT, B#100) = 2000, `CH4 - combustion - air` (AT, B#87) = 10,
  `CO2 - waste - biogenic - air` (AT, B#87) = 500 and `SO2 - combustion - air` (AT, B#87) = 123.
- Each configured setup (ICIO, EXIOBASE, split) and each other import row writes into its own
  fresh, empty `<dir>`; no two imports share a directory unless a row says so (AC-102).
- **"ICIO configured"** means the three variables printed on stdout lines 3 to 5 by importing
  fixture I (AC-4) are set; **"EXIOBASE configured"** the three from importing fixture E (AC-13);
  **"split configured"** the three from importing fixture E with `--split-electricity` (AC-67).
- **Theme T**: file `theme_t.json` (`arp.schemas.thematic.ThemeDefinition`):
  `{"name": "Grid equipment", "description": "Makers of electrical equipment for power grids.",
  "activities": [{"name": "Electrical equipment", "in_scope_description": "Transformers, switchgear
  and cables for power grids.", "out_of_scope_description": "Consumer electronics.",
  "seed_keywords": ["transformer", "switchgear"], "core_isic_codes": ["C27"]}]}`.
  **Universe U**: file `universe_u.csv`, header `company_id,name,isic_code`, one row
  `acme,Acme,27`. `--theme` and `--universe` take these file paths.
- AC-22 and AC-23 set `ARP_ANTHROPIC_API_KEY` to a dummy value and `ARP_POSTGRES_DSN` and
  `ARP_RUNS_DIR` as in other holdout tests; the source check fails before any model call. API rows
  run the app with `ARP_AUTH_MODE=local` and `ARP_USERS_FILE` pointing at a file in the format of
  `config/users.example.json` holding one user with role `analyst`, send
  `Authorization: Bearer <that token>`, and post
  `{"theme": <T>, "companies": [{"company_id": "acme", "name": "Acme", "isic_code": "27"}]}` to
  `POST /api/themes/runs`.
- Model rows call `resolve_indirect_exposure_model(Settings(), …)` from
  `arp.research.indirect_exposure.factory` (`Settings` from `arp.config`) and read the returned
  `LeontiefModel`'s `codes` (list of str) and `edition_label` (str).
- **Exposure rows** call `compute_indirect_exposure(company_id, isic_code, model, core_codes,
  edition, country=<country>)` from `arp.research.indirect_exposure.exposure`, with `model` from
  `resolve_indirect_exposure_model(Settings())`, `company_id` `"x"`, `edition` `"e"`, and read the
  returned `IndirectExposureResult`'s fields. `country` defaults to `None`.
- Division lookup rows call `await resolve_company_isic(company, model, llm)` from
  `arp.research.indirect_exposure.company_mapper`. `company` is
  `arp.schemas.common.CompanyRef(company_id="x", name="X", isic_code=<code>)`; `model` comes from
  `resolve_indirect_exposure_model(Settings())`. `llm` is a stub with
  `async def complete_structured(self, *, system, prompt, output_model)` that records each call and
  returns `(output_model(isic_code=None, rationale="stub"), arp.llm.base.LLMUsage())`. The function
  returns `(code or None, usage)`; rows check the first element.
- The bundled sample files are `backend/arp/research/indirect_exposure/sample_data/industries.csv`
  and `…/sample_data/icio_matrix.csv`.

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | Fixture I | `arp io import-icio icio_fixture.csv --out <dir>` | Exit 0; stdout line 1 is `50 industries, 2 regions -> <D>` | holdout |
| AC-2 | AC-1's output | Read `<D>/industries.csv` | 50 rows, `isic_code` in Appendix A order; total_output `C26` 150, `C27` 100, `D` 31, `A01` 2 | holdout |
| AC-34 | AC-1's output | Read `<D>/industries.csv` | Every row's `label` and `isic_divisions` equal its Appendix A row; every `nace_classes` is empty | holdout |
| AC-3 | AC-1's output | Read `<D>/icio_matrix.csv` | (C26, C27) = 15, (D, C26) = 2, every other cell 0 | holdout |
| AC-4 | AC-1 | stdout lines 2 to 5 | Exactly `ARP_IO_SOURCE=icio`, `ARP_ICIO_MATRIX_PATH=<D>/icio_matrix.csv`, `ARP_ICIO_INDUSTRIES_PATH=<D>/industries.csv`, `ARP_ICIO_EDITION_LABEL=icio-icio_fixture`, in that order | holdout |
| AC-5 | Fixture I | `arp io import-icio icio_fixture.csv --out <dir> --label ICIO2025-2022` | stdout line 5 is `ARP_ICIO_EDITION_LABEL=ICIO2025-2022` | holdout |
| AC-6 | Fixture I without its `OUT` column | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `no OUT column` | holdout |
| AC-7 | Fixture I with every `_C24A` and `_C24B` row and column label relabelled `_C24` | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `missing ICIO industries: C24A, C24B` | holdout |
| AC-48 | Fixture I with only the column labels `DEU_C24A` and `CHN_C24A` relabelled `DEU_C24` and `CHN_C24` (row labels unchanged) | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `missing ICIO industries: C24A` | holdout |
| AC-8 | Fixture I with cell `DEU_C26→CHN_C27` = `x` | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `row DEU_C26, column CHN_C27: not a number: 'x'` | holdout |
| AC-35 | Fixture I with cell `TLS→DEU_C26` = `x` and cell `VA→CHN_GFCF` = `x` | `arp io import-icio <file> --out <dir>` | Exit 0; `icio_matrix.csv` as in AC-3 | holdout |
| AC-36 | Fixture I with cell `DEU_D→DEU_C26` empty | `arp io import-icio <file> --out <dir>` | Exit 0; (D, C26) = 0 | holdout |
| AC-47 | Fixture I with `DEU_A01`'s `OUT` cell empty | `arp io import-icio <file> --out <dir>` | Exit 0; `A01` total_output 1 | holdout |
| AC-37 | Fixture I without row `CHN_T` and column `CHN_T` | `arp io import-icio <file> --out <dir>` | Exit 0; stdout line 1 `50 industries, 2 regions -> <D>`; `T` total_output 1 | holdout |
| AC-9 | Fixture I with region `DEU` renamed `CN1` and `CHN` renamed `CN2` in every label | `arp io import-icio <file> --out <dir>` | Exit 0; stdout line 1 `50 industries, 2 regions -> <D>`; `icio_matrix.csv` as in AC-3 | holdout |
| AC-53 | Fixture I plus one extra column `USA_A01` (every cell 0) | `arp io import-icio <file> --out <dir>` | Exit 0; stdout line 1 `50 industries, 2 regions -> <D>` | holdout |
| AC-81 | Fixture I with region `DEU` renamed `QQQ` in every label | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `region not in region groups: QQQ` | holdout |
| AC-38 | Fixture I; `<dir>` is `a/b`, which does not exist | `arp io import-icio icio_fixture.csv --out a/b` | Exit 0; `a/b/industries.csv` and `a/b/icio_matrix.csv` exist | holdout |
| AC-39 | `<dir>/industries.csv` exists with content `old` | `arp io import-icio icio_fixture.csv --out <dir>` | Exit 0; `<D>/industries.csv` as in AC-2 | holdout |
| AC-56 | AC-1's output | Read `<D>/final_demand.csv` | `C27`: households 30, investment 50, government 0, inventories 0; `D`: households 5, others 0; every other row all 0 | holdout |
| AC-104 | Fixture I with columns `DEU_NPISH`, `DEU_DPABR`, `DEU_GGFC` and `DEU_INVNT` added before `OUT` (0 in every industry row except as stated) and, for row `DEU_A01`: `DEU_HFCE` 1, `DEU_NPISH` 2, `DEU_DPABR` 4, `DEU_GGFC` 8, `CHN_GFCF` 16, `DEU_INVNT` 32 | `arp io import-icio <file> --out <dir>`, then read `<D>/final_demand.csv` | `A01`: households 7, government 8, investment 16, inventories 32 | holdout |
| AC-74 | AC-1's output | Read `<D>/regional_output.csv` | 100 rows: group `CN` then `EU`, each with the 50 codes; (EU, C26) 100, (CN, C26) 50, (EU, C27) 40, (CN, C27) 60, (EU, D) 30; every other row 1 | holdout |
| AC-75 | AC-1's output | Read `<D>/regional_flows.csv` | Exactly three data rows: (CN, C26, EU, C27, 5), (EU, C26, CN, C27, 10), (EU, D, EU, C26, 2), in that order | holdout |
| AC-10 | Fixture E | `arp io import-exiobase IOT_fixture_ixi.zip --out <dir>` | Exit 0; stdout line 1 is `163 sectors -> 50 industries, 2 regions -> <D>` | holdout |
| AC-11 | AC-10's output | Read `<D>/industries.csv` | 50 rows in Appendix A order; total_output `C26` 150, `C27` 100, `D` 50, `C21` 0; `label`, `isic_divisions` and `nace_classes` as in AC-34 | holdout |
| AC-12 | AC-10's output | Read `<D>/exiobase_flows.csv` | Exactly two data rows, compared as (supplier, user, float value): (C26, C27, 15) then (D, C26, 5) | holdout |
| AC-13 | AC-10 | stdout lines 2 to 5 | Exactly `ARP_IO_SOURCE=exiobase`, `ARP_EXIOBASE_FLOWS_PATH=<D>/exiobase_flows.csv`, `ARP_EXIOBASE_INDUSTRIES_PATH=<D>/industries.csv`, `ARP_EXIOBASE_EDITION_LABEL=exiobase-IOT_fixture_ixi`, in that order | holdout |
| AC-40 | Fixture E | `arp io import-exiobase IOT_fixture_ixi.zip --out <dir> --label X3` | stdout line 5 is `ARP_EXIOBASE_EDITION_LABEL=X3` | holdout |
| AC-14 | Fixture E with B#87's name replaced by `Made-up sector` everywhere: `Z.txt` header line 2 (both regions), the sector cell of both its `Z.txt` rows, and both its `x.txt` rows | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `EXIOBASE sector not in crosswalk: Made-up sector` | holdout |
| AC-15 | A zip with fixture E's `x.txt` but no `Z.txt` | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `no Z.txt at the archive root` | holdout |
| AC-49 | Fixture E with the `Z.txt` columns in reverse order: on header lines 1 to 3 and on every data row, the cells after the first two are reversed, so each value stays under its own (region, sector) header; the first two cells of every line and the data rows' order are unchanged | `arp io import-exiobase <zip> --out <dir>` | Exit 0; `exiobase_flows.csv` as in AC-12 | holdout |
| AC-105 | Fixture E with the `Y.txt` columns in reverse order: on header lines 1 to 3 and on every data row, the cells after the first two are reversed; the first two cells of every line and the row order are unchanged | `arp io import-exiobase <zip> --out <dir>` | Exit 0; `final_demand.csv` as in AC-57 | holdout |
| AC-106 | Fixture E with the `air_emissions/F.txt` columns in reverse order: on header lines 1 and 2 and on every stressor line, the cells after the first are reversed; the first cell of every line and the line order are unchanged | `arp io import-exiobase <zip> --out <dir>` | Exit 0; `ghg.csv` as in AC-62 | holdout |
| AC-107 | Fixture E without sector B#1 (`Cultivation of paddy rice`): its rows and columns removed from `Z.txt`, its rows from `Y.txt`, its lines from `x.txt`, its columns from `air_emissions/F.txt`, in both regions | `arp io import-exiobase <zip> --out <dir>` | Exit 0; stdout line 1 is `162 sectors -> 50 industries, 2 regions -> <D>`; `A01` total_output 0 in `industries.csv` | holdout |
| AC-55 | Fixture E with every line of every file ending in `\r\n` | `arp io import-exiobase <zip> --out <dir>` | Exit 0; `exiobase_flows.csv` as in AC-12 | holdout |
| AC-57 | AC-10's output | Read `<D>/final_demand.csv` | `C27`: households 30, investment 50; `D`: households 5; `C26`: inventories 4; every other value 0 (the Exports 999 is not counted) | holdout |
| AC-62 | AC-10's output | Read `<D>/ghg.csv` | `D` 2000, `C26` 298, every other row 0 | holdout |
| AC-91 | AC-10's output | Read `<D>/regional_output.csv` | 100 rows, the 50 `EU` rows then the 50 `ASIA_OTH` rows; (EU, C26) 100, (ASIA_OTH, C26) 50, (EU, C27) 40, (ASIA_OTH, C27) 60, (EU, D) 50; every other row 0 | holdout |
| AC-92 | AC-10's output | Read `<D>/regional_flows.csv` | Exactly 3 data rows, in this order: `EU,C26,ASIA_OTH,C27,10`, `EU,D,EU,C26,5`, `ASIA_OTH,C26,EU,C27,5` (numbers compared as floats) | holdout |
| AC-94 | Fixture E with region `WA` renamed `XX` in every file | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `region not in region groups: XX` | holdout |
| AC-101 | Fixture E with category `Exports: Total (fob)` renamed `Exports` in `Y.txt` | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `unknown final-demand category: Exports` | holdout |
| AC-58 | Fixture E without `Y.txt` | `arp io import-exiobase <zip> --out <dir>` | Exit 0; `<D>` holds no `final_demand.csv`; `ghg.csv` as in AC-62 | holdout |
| AC-100 | Fixture E without `air_emissions/F.txt` | `arp io import-exiobase <zip> --out <dir>` | Exit 0; `<D>` holds no `ghg.csv`; `final_demand.csv` as in AC-57 | holdout |
| AC-102 | `<dir>` holds AC-10's output | Import Fixture E without `air_emissions/F.txt` with `--out <dir>` | Exit 0; `<D>` holds no `ghg.csv` | holdout |
| AC-103 | Fixture E with these values in `Y.txt` for row (AT, B#1), columns region AT: households 1, NPISH 2, government 4, gross fixed capital formation 8, changes in inventories 16, changes in valuables 32, `Exports: Total (fob)` 64 | `arp io import-exiobase <zip> --out <dir>`, then read `<D>/final_demand.csv` | `A01`: households 3, government 4, investment 8, inventories 48 | holdout |
| AC-67 | Fixture E | `arp io import-exiobase IOT_fixture_ixi.zip --out <dir> --split-electricity` | Exit 0; stdout line 1 is `163 sectors -> 54 industries, 2 regions -> <D>` | holdout |
| AC-68 | AC-67's output | Read `<D>/industries.csv` | 54 rows in Appendix A2 order, no `D` row; total_output `D_TD` 30, `D_GEN_REN` 20, `D_GEN_FOS` 0, `D_GEN_NUC` 0, `D_GAS` 0; `label`, `isic_divisions` and `nace_classes` as in Appendix A2 | holdout |
| AC-69 | AC-67's output | Read `<D>/exiobase_flows.csv` | Exactly three data rows: (C26, C27, 15), (D_GEN_REN, C26, 3), (D_TD, C26, 2), in that order | holdout |
| AC-16 | `reference/exiobase_ixi_to_icio2025.csv` | Read the `icio_code` of Appendix B rows 87, 88, 89, 100, 108, 133, 55, 163 | `C26`, `C27`, `C26`, `D`, `D`, `J62_63`, `C17_18`, `O` | holdout |
| AC-41 | `reference/exiobase_ixi_to_icio2025.csv` | Read the whole file | Header `exiobase_sector,icio_code,split_code`; 163 data rows equal, in order, to Appendix B's (sector, ICIO, Split) triples | holdout |
| AC-51 | `reference/icio2025_industries.csv` | Read the whole file | Header `code,label,isic_divisions`; 50 data rows equal, in order, to Appendix A's (Code, Label, isic_divisions) | holdout |
| AC-82 | `reference/region_groups.csv` | Read the whole file | Header `code,group`; its rows equal, as a set, Appendix C's (code, group) pairs | holdout |
| AC-66 | `reference/ghg_gwp100.csv` | Read the whole file | Header `stressor,factor`; 23 data rows equal, in order, to Appendix D's (stressor, factor) pairs | holdout |
| AC-17 | ICIO configured, EXIOBASE not, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout is exactly `source: icio`, `edition: icio-icio_fixture`, `industries: 50`, `final demand: yes`, `emissions: no`, `regions: 2`, one per line | holdout |
| AC-18 | ICIO and EXIOBASE configured, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout line 1 is `source: icio` | holdout |
| AC-42 | EXIOBASE configured, ICIO not, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout line 1 is `source: exiobase` | holdout |
| AC-19 | ICIO and EXIOBASE configured, `ARP_IO_SOURCE=exiobase` | `arp io status` | Exit 0; stdout is exactly `source: exiobase`, `edition: exiobase-IOT_fixture_ixi`, `industries: 50`, `final demand: yes`, `emissions: yes`, `regions: 2` | holdout |
| AC-20 | Neither configured, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout is exactly `source: none` | holdout |
| AC-21 | EXIOBASE configured, ICIO not, `ARP_IO_SOURCE=icio` | `arp io status` | Exit 1; stderr contains `io source icio is not configured: set ARP_ICIO_MATRIX_PATH and ARP_ICIO_INDUSTRIES_PATH` | holdout |
| AC-50 | Only `ARP_ICIO_MATRIX_PATH` set (to fixture I's import output), `ARP_IO_SOURCE=icio` | `arp io status` | Exit 1; stderr contains `io source icio is not configured: set ARP_ICIO_MATRIX_PATH and ARP_ICIO_INDUSTRIES_PATH` | holdout |
| AC-43 | `ARP_IO_SOURCE=figaro` | `arp io status` | Exit 1; stderr contains `Input should be 'auto', 'icio' or 'exiobase'` | holdout |
| AC-44 | `ARP_IO_SOURCE=ICIO` | `arp io status` | Exit 1; stderr contains `Input should be 'auto', 'icio' or 'exiobase'` | holdout |
| AC-31 | `ARP_ICIO_MATRIX_PATH` and `ARP_ICIO_INDUSTRIES_PATH` set to the bundled sample files; nothing else | `arp io status` | Exit 0; stdout is exactly `source: icio`, `edition: sample`, `industries: 10`, `final demand: no`, `emissions: no`, `regions: no` | holdout |
| AC-52 | Only `ARP_EXIOBASE_FLOWS_PATH` and `ARP_EXIOBASE_INDUSTRIES_PATH` set (fixture E's import output) | `arp io status` | Exit 0; stdout line 2 is `edition: exiobase-sample` | holdout |
| AC-22 | ICIO configured, EXIOBASE not, `ARP_IO_SOURCE=exiobase` | `arp theme run --theme <T> --universe <U>` | Exit 1; stderr contains `io source exiobase is not configured: set ARP_EXIOBASE_FLOWS_PATH and ARP_EXIOBASE_INDUSTRIES_PATH` | holdout |
| AC-23 | As AC-22 | `POST /api/themes/runs` with T and Acme | Status 400; `detail` equals `io source exiobase is not configured: set ARP_EXIOBASE_FLOWS_PATH and ARP_EXIOBASE_INDUSTRIES_PATH` | holdout |
| AC-24 | ICIO configured, `ARP_IO_SOURCE=icio` | Code lookup, `isic_code` `26` | Returns `C26`; stub not called | holdout |
| AC-25 | As AC-24 | `isic_code` `62` | Returns `J62_63`; stub not called | holdout |
| AC-26 | As AC-24 | `isic_code` `24` | Returns `None`; stub called once | holdout |
| AC-45 | As AC-24 | `isic_code` `2610` | Returns `None`; stub called once | holdout |
| AC-27 | As AC-24 | `isic_code` `C27` | Returns `C27`; stub not called | holdout |
| AC-71 | Split configured, `ARP_IO_SOURCE=exiobase` | Code lookup, `isic_code` `35.12` | Returns `D_TD`; stub not called | holdout |
| AC-72 | As AC-71 | `isic_code` `35` | Returns `None`; stub called once | holdout |
| AC-28 | `ARP_IO_SOURCE=exiobase`, nothing configured | `resolve_indirect_exposure_model(Settings(), use_sample_icio=True)` | `edition_label` `sample`; `len(codes)` 10; `codes[0]` `07` | holdout |
| AC-46 | `ARP_IO_SOURCE=icio`, nothing configured | `resolve_indirect_exposure_model(Settings(), use_sample_exiobase=True)` | `edition_label` `exiobase-sample`; `len(codes)` 10; `codes[0]` `07` | holdout |
| AC-29 | Nothing configured, `ARP_IO_SOURCE` unset | `resolve_indirect_exposure_model(Settings())` | Returns `None` | holdout |
| AC-30 | Model from `resolve_indirect_exposure_model(Settings(), use_sample_icio=True)` | Code lookup, `isic_code` `27` | Returns `27`; stub not called | holdout |
| AC-83 | ICIO configured | Exposure for `C27`, core `{"C26"}` | `upstream_exposure` `25/192` | holdout |
| AC-90 | ICIO configured | Exposure for `C26`, core `{"C27"}` | `downstream_exposure` `3/23` | holdout |
| AC-59 | ICIO configured | Exposure for `C26`, core `{"C27"}` | `end_market` is `{"households": 0.375, "government": 0, "investment": 0.625, "inventories": 0}` | holdout |
| AC-60 | ICIO configured | Exposure for `D`, core `{"C27"}` | `theme_demand_share` `4/129` | holdout |
| AC-61 | EXIOBASE configured | Exposure for `C26`, core `{"C27"}` | `end_market` is `{"households": 0.28125, "government": 0, "investment": 0.46875, "inventories": 0.25}` | holdout |
| AC-84 | EXIOBASE configured | Exposure for `C26`, core `{"C27"}` | `theme_demand_share` 0.75 | holdout |
| AC-97 | ICIO configured | Exposure for `A01`, core `{"C27"}` | `end_market` is null; `theme_demand_share` is null | holdout |
| AC-99 | Fixture I with `DEU_HFCE` for `DEU_D` set to -0.1, imported, its printed variables set | Exposure for `D`, core `{"C27"}` | `theme_demand_share` 1 | holdout |
| AC-63 | EXIOBASE configured | Exposure for `C27`, core `{"C26"}` | `ghg_direct_t_per_meur` 0; `ghg_supply_chain_t_per_meur` 0.000498 | holdout |
| AC-64 | EXIOBASE configured | Exposure for `C26`, core `{"C27"}` | `ghg_direct_t_per_meur` `149/75000`; `ghg_supply_chain_t_per_meur` 0.00332 | holdout |
| AC-98 | EXIOBASE configured | Exposure for `C21`, core `{"C27"}` | `ghg_direct_t_per_meur` 0; `ghg_supply_chain_t_per_meur` 0 | holdout |
| AC-65 | ICIO configured | Exposure for `C27`, core `{"C26"}` | `ghg_direct_t_per_meur` and `ghg_supply_chain_t_per_meur` are null | holdout |
| AC-85 | Model from `use_sample_icio=True` | Exposure for `27`, core `{"20"}`, `country="DE"` | `end_market`, `theme_demand_share`, `ghg_direct_t_per_meur`, `ghg_supply_chain_t_per_meur` and `regional` are all null | holdout |
| AC-76 | ICIO configured | Exposure for `C27`, core `{"C26"}`, `country="DE"` | `regional.region` `EU`; `regional.upstream` `1/9`; `regional.upstream_by_region` is `{"CN": 1/9, "EU": 0}` with keys in that order | holdout |
| AC-77 | As AC-76 | `country="DEU"` | `regional.region` `EU` | holdout |
| AC-78 | As AC-76 | `country="de"` | `regional.region` `EU` | holdout |
| AC-86 | ICIO configured | Exposure for `C27`, core `{"C26"}`, `country="CN"` | `regional.region` `CN`; `regional.upstream` `50/351`; `regional.upstream_by_region` is `{"CN": 0, "EU": 50/351}` | holdout |
| AC-79 | ICIO configured | Exposure for `C26`, core `{"C27"}`, `country="DE"` | `regional.downstream` `1/7`; `regional.downstream_by_region` is `{"CN": 1/7, "EU": 0}` | holdout |
| AC-80 | ICIO configured | Exposure for `C27`, core `{"C26"}`, `country="XX"` | `regional` is null | holdout |
| AC-87 | ICIO configured | Exposure for `C27`, core `{"C26"}`, no `country` | `regional` is null | holdout |
| AC-95 | ICIO configured | Exposure for `C27`, core `{"C26"}`, `country="US"` | `regional` is null | holdout |
| AC-96 | ICIO configured | Exposure for `C27`, core `{"C26"}`, `country="CN1"` | `regional` is null | holdout |
| AC-93 | EXIOBASE configured | Exposure for `C27`, core `{"C26"}`, `country="AT"` | `regional.region` `EU`; `regional.upstream` `1/9`; `regional.upstream_by_region` is `{"EU": 0, "ASIA_OTH": 1/9}` with keys in that order | holdout |
| AC-32 | The real `IOT_2022_ixi.zip` from Zenodo record 23039074 | `arp io import-exiobase IOT_2022_ixi.zip --out <dir>`, then `arp io status` with the printed variables set | Import exits 0 within 15 minutes with peak resident memory at most 1 GB, measured with `/usr/bin/time -v`; stdout line 1 `163 sectors -> 50 industries, 49 regions -> <D>`; status prints `industries: 50`, `final demand: yes`, `emissions: yes`, `regions: 11`; `D`'s total_output in `industries.csv` is greater than 0 | evaluator |
| AC-88 | As AC-32 | Import again with `--split-electricity` into another `<dir>` | Exit 0; stdout line 1 `163 sectors -> 54 industries, 49 regions -> <D>`; `D_TD` and `D_GEN_REN` total_output both greater than 0 | evaluator |
| AC-89 | AC-32's printed variables set | Exposure for `D` and for `J62_63`, core `{"C27"}` | `D`'s `ghg_direct_t_per_meur` is greater than `J62_63`'s | evaluator |
| AC-33 | AC-32's printed variables set | Code lookup with `isic_code` `27` against the real imported model | Returns `C27`; stub not called | evaluator |
| AC-54 | The real ICIO 2025 regular file `2022_SML.csv` from the OECD ICIO page (the owner supplies it if the OECD site blocks the download) | `arp io import-icio 2022_SML.csv --out <dir>`, then `arp io status` with the printed variables set | Import exits 0; stdout line 1 `50 industries, 81 regions -> <D>`; status prints `industries: 50`, `final demand: yes`, `regions: 12`; `D`'s and `C26`'s total_output in `industries.csv` are greater than 0 | evaluator |

Must not change: the bundled samples (AC-28, AC-30, AC-46, AC-85), the `auto` order (AC-18,
AC-29, AC-42), hand-prepared files without the new columns (AC-31), the default edition labels
(AC-31, AC-52), codes already in the model, which are used directly (AC-27), and today's upstream
and downstream shares (AC-83, AC-90).

## Appendix A: ICIO 2025 industries

From the OECD note *Development of OECD Inter-Country Input-Output Database, 2025 edition*, Table 2.
`isic_divisions` lists the two-digit ISIC Rev.4 divisions; C24A/C24B and C301/C302T309 share one.

| # | Code | Label | isic_divisions |
|---|---|---|---|
| 1 | A01 | Agriculture and hunting | 01 |
| 2 | A02 | Forestry and logging | 02 |
| 3 | A03 | Fishing and aquaculture | 03 |
| 4 | B05 | Mining of coal and lignite | 05 |
| 5 | B06 | Extraction of crude petroleum and natural gas | 06 |
| 6 | B07 | Mining of metal ores | 07 |
| 7 | B08 | Other mining and quarrying | 08 |
| 8 | B09 | Mining support service activities | 09 |
| 9 | C10T12 | Manufacture of food products; beverages and tobacco products | 10;11;12 |
| 10 | C13T15 | Manufacture of textiles, wearing apparel, leather and related products | 13;14;15 |
| 11 | C16 | Manufacture of wood and of products of wood and cork | 16 |
| 12 | C17_18 | Manufacture of paper and paper products; Printing and reproduction of recorded media | 17;18 |
| 13 | C19 | Manufacture of coke and refined petroleum products | 19 |
| 14 | C20 | Manufacture of chemicals and chemical products | 20 |
| 15 | C21 | Manufacture of basic pharmaceutical products and pharmaceutical preparations | 21 |
| 16 | C22 | Manufacture of rubber and plastic products | 22 |
| 17 | C23 | Manufacture of other non-metallic mineral products | 23 |
| 18 | C24A | Manufacture of basic iron and steel | 24 |
| 19 | C24B | Manufacture of basic precious and other non-ferrous metals | 24 |
| 20 | C25 | Manufacture of fabricated metal products | 25 |
| 21 | C26 | Manufacture of computer, electronic and optical products | 26 |
| 22 | C27 | Manufacture of electrical equipment | 27 |
| 23 | C28 | Manufacture of machinery and equipment n.e.c. | 28 |
| 24 | C29 | Manufacture of motor vehicles, trailers and semi-trailers | 29 |
| 25 | C301 | Building of ships and boats | 30 |
| 26 | C302T309 | Manufacture of other transport equipment | 30 |
| 27 | C31T33 | Manufacture of furniture and other manufacturing | 31;32;33 |
| 28 | D | Electricity, gas, steam and air conditioning supply | 35 |
| 29 | E | Water supply; sewerage, waste management and remediation activities | 36;37;38;39 |
| 30 | F | Construction | 41;42;43 |
| 31 | G | Wholesale and retail trade; repair of motor vehicles and motorcycles | 45;46;47 |
| 32 | H49 | Land transport and transport via pipelines | 49 |
| 33 | H50 | Water transport | 50 |
| 34 | H51 | Air transport | 51 |
| 35 | H52 | Warehousing and support activities for transportation | 52 |
| 36 | H53 | Postal and courier activities | 53 |
| 37 | I | Accommodation and food service activities | 55;56 |
| 38 | J58T60 | Publishing, Motion picture, video, television programme production and broadcasting activities | 58;59;60 |
| 39 | J61 | Telecommunications | 61 |
| 40 | J62_63 | Computer programming and information service activities | 62;63 |
| 41 | K | Financial and insurance activities | 64;65;66 |
| 42 | L | Real estate activities | 68 |
| 43 | M | Professional, scientific and technical activities | 69;70;71;72;73;74;75 |
| 44 | N | Administrative and support service activities | 77;78;79;80;81;82 |
| 45 | O | Public administration and defence; compulsory social security | 84 |
| 46 | P | Education | 85 |
| 47 | Q | Human health and social work activities | 86;87;88 |
| 48 | R | Arts, entertainment and recreation activities | 90;91;92;93 |
| 49 | S | Other service activities | 94;95;96 |
| 50 | T | Activities of households as employers; undifferentiated goods- and services-producing activities of households for own use | 97;98 |

## Appendix A2: industries with `--split-electricity`

Appendix A order with row 28 (`D`) replaced by the five rows below; 54 industries. Every other
row keeps its Appendix A code, label and `isic_divisions`, and has an empty `nace_classes`.
`nace_classes` lists NACE Rev.2 classes, which split ISIC Rev.4 classes 3510 and 3520 finer.

| # | Code | Label | isic_divisions | nace_classes |
|---|---|---|---|---|
| 28 | D_GEN_FOS | Electricity generation from fossil fuels | 35 | 35.11 |
| 29 | D_GEN_NUC | Electricity generation from nuclear | 35 | 35.11 |
| 30 | D_GEN_REN | Electricity generation from renewables | 35 | 35.11 |
| 31 | D_TD | Electricity transmission and distribution | 35 | 35.12;35.13;35.14 |
| 32 | D_GAS | Gas distribution and steam supply | 35 | 35.21;35.22;35.23;35.30 |

Rows 33–54 are Appendix A rows 29–50 in order (E … T).

## Appendix B: EXIOBASE 3 ixi sectors → ICIO 2025 industries

The 163 sector names exactly as in `unit.txt` of `IOT_2022_ixi.zip` (3.11.2), in file order,
including EXIOBASE's spelling (`accessoiries`, `preciuos`, `slugde`) and its bracketed ISIC
Rev.3-style codes, which are part of the name. "Re-processing of secondary X" sectors map to the
industry that makes primary X. No sector maps to B09 (mining support services sit inside the extraction sectors), C21
(pharma sits inside "Chemicals nec"), C301 (ships sit inside "other transport equipment"), H53
(post sits inside "Post and telecommunications") or J58T60 (publishing sits inside "Publishing,
printing"). Row 163 has no
ICIO counterpart (ISIC U) and goes to O.

The Split column is the industry with `--split-electricity`; it differs from the ICIO column only
for rows 96–111.

| # | EXIOBASE sector (exact `unit.txt` string) | ICIO | Split |
|---|---|---|---|
| 1 | Cultivation of paddy rice | A01 | A01 |
| 2 | Cultivation of wheat | A01 | A01 |
| 3 | Cultivation of cereal grains nec | A01 | A01 |
| 4 | Cultivation of vegetables, fruit, nuts | A01 | A01 |
| 5 | Cultivation of oil seeds | A01 | A01 |
| 6 | Cultivation of sugar cane, sugar beet | A01 | A01 |
| 7 | Cultivation of plant-based fibers | A01 | A01 |
| 8 | Cultivation of crops nec | A01 | A01 |
| 9 | Cattle farming | A01 | A01 |
| 10 | Pigs farming | A01 | A01 |
| 11 | Poultry farming | A01 | A01 |
| 12 | Meat animals nec | A01 | A01 |
| 13 | Animal products nec | A01 | A01 |
| 14 | Raw milk | A01 | A01 |
| 15 | Wool, silk-worm cocoons | A01 | A01 |
| 16 | Manure treatment (conventional), storage and land application | A01 | A01 |
| 17 | Manure treatment (biogas), storage and land application | A01 | A01 |
| 18 | Forestry, logging and related service activities (02) | A02 | A02 |
| 19 | Fishing, operating of fish hatcheries and fish farms; service activities incidental to fishing (05) | A03 | A03 |
| 20 | Mining of coal and lignite; extraction of peat (10) | B05 | B05 |
| 21 | Extraction of crude petroleum and services related to crude oil extraction, excluding surveying | B06 | B06 |
| 22 | Extraction of natural gas and services related to natural gas extraction, excluding surveying | B06 | B06 |
| 23 | Extraction, liquefaction, and regasification of other petroleum and gaseous materials | B06 | B06 |
| 24 | Mining of uranium and thorium ores (12) | B07 | B07 |
| 25 | Mining of iron ores | B07 | B07 |
| 26 | Mining of copper ores and concentrates | B07 | B07 |
| 27 | Mining of nickel ores and concentrates | B07 | B07 |
| 28 | Mining of aluminium ores and concentrates | B07 | B07 |
| 29 | Mining of precious metal ores and concentrates | B07 | B07 |
| 30 | Mining of lead, zinc and tin ores and concentrates | B07 | B07 |
| 31 | Mining of other non-ferrous metal ores and concentrates | B07 | B07 |
| 32 | Quarrying of stone | B08 | B08 |
| 33 | Quarrying of sand and clay | B08 | B08 |
| 34 | Mining of chemical and fertilizer minerals, production of salt, other mining and quarrying n.e.c. | B08 | B08 |
| 35 | Processing of meat cattle | C10T12 | C10T12 |
| 36 | Processing of meat pigs | C10T12 | C10T12 |
| 37 | Processing of meat poultry | C10T12 | C10T12 |
| 38 | Production of meat products nec | C10T12 | C10T12 |
| 39 | Processing vegetable oils and fats | C10T12 | C10T12 |
| 40 | Processing of dairy products | C10T12 | C10T12 |
| 41 | Processed rice | C10T12 | C10T12 |
| 42 | Sugar refining | C10T12 | C10T12 |
| 43 | Processing of Food products nec | C10T12 | C10T12 |
| 44 | Manufacture of beverages | C10T12 | C10T12 |
| 45 | Manufacture of fish products | C10T12 | C10T12 |
| 46 | Manufacture of tobacco products (16) | C10T12 | C10T12 |
| 47 | Manufacture of textiles (17) | C13T15 | C13T15 |
| 48 | Manufacture of wearing apparel; dressing and dyeing of fur (18) | C13T15 | C13T15 |
| 49 | Tanning and dressing of leather; manufacture of luggage, handbags, saddlery, harness and footwear (19) | C13T15 | C13T15 |
| 50 | Manufacture of wood and of products of wood and cork, except furniture; manufacture of articles of straw and plaiting materials (20) | C16 | C16 |
| 51 | Re-processing of secondary wood material into new wood material | C16 | C16 |
| 52 | Pulp | C17_18 | C17_18 |
| 53 | Re-processing of secondary paper into new pulp | C17_18 | C17_18 |
| 54 | Paper | C17_18 | C17_18 |
| 55 | Publishing, printing and reproduction of recorded media (22) | C17_18 | C17_18 |
| 56 | Manufacture of coke oven products | C19 | C19 |
| 57 | Petroleum Refinery | C19 | C19 |
| 58 | Processing of nuclear fuel | C20 | C20 |
| 59 | Plastics, basic | C20 | C20 |
| 60 | Re-processing of secondary plastic into new plastic | C20 | C20 |
| 61 | N-fertiliser | C20 | C20 |
| 62 | P- and other fertiliser | C20 | C20 |
| 63 | Chemicals nec | C20 | C20 |
| 64 | Manufacture of rubber and plastic products (25) | C22 | C22 |
| 65 | Manufacture of glass and glass products | C23 | C23 |
| 66 | Re-processing of secondary glass into new glass | C23 | C23 |
| 67 | Manufacture of ceramic goods | C23 | C23 |
| 68 | Manufacture of bricks, tiles and construction products, in baked clay | C23 | C23 |
| 69 | Manufacture of cement, lime and plaster | C23 | C23 |
| 70 | Re-processing of ash into clinker | C23 | C23 |
| 71 | Manufacture of other non-metallic mineral products n.e.c. | C23 | C23 |
| 72 | Manufacture of basic iron and steel and of ferro-alloys and first products thereof | C24A | C24A |
| 73 | Re-processing of secondary steel into new steel | C24A | C24A |
| 74 | Precious metals production | C24B | C24B |
| 75 | Re-processing of secondary preciuos metals into new preciuos metals | C24B | C24B |
| 76 | Aluminium production | C24B | C24B |
| 77 | Re-processing of secondary aluminium into new aluminium | C24B | C24B |
| 78 | Lead, zinc and tin production | C24B | C24B |
| 79 | Re-processing of secondary lead into new lead, zinc and tin | C24B | C24B |
| 80 | Copper production | C24B | C24B |
| 81 | Re-processing of secondary copper into new copper | C24B | C24B |
| 82 | Other non-ferrous metal production | C24B | C24B |
| 83 | Re-processing of secondary other non-ferrous metals into new other non-ferrous metals | C24B | C24B |
| 84 | Casting of metals | C24A | C24A |
| 85 | Manufacture of fabricated metal products, except machinery and equipment (28) | C25 | C25 |
| 86 | Manufacture of machinery and equipment n.e.c. (29) | C28 | C28 |
| 87 | Manufacture of office machinery and computers (30) | C26 | C26 |
| 88 | Manufacture of electrical machinery and apparatus n.e.c. (31) | C27 | C27 |
| 89 | Manufacture of radio, television and communication equipment and apparatus (32) | C26 | C26 |
| 90 | Manufacture of medical, precision and optical instruments, watches and clocks (33) | C26 | C26 |
| 91 | Manufacture of motor vehicles, trailers and semi-trailers (34) | C29 | C29 |
| 92 | Manufacture of other transport equipment (35) | C302T309 | C302T309 |
| 93 | Manufacture of furniture; manufacturing n.e.c. (36) | C31T33 | C31T33 |
| 94 | Recycling of waste and scrap | E | E |
| 95 | Recycling of bottles by direct reuse | E | E |
| 96 | Production of electricity by coal | D | D_GEN_FOS |
| 97 | Production of electricity by gas | D | D_GEN_FOS |
| 98 | Production of electricity by nuclear | D | D_GEN_NUC |
| 99 | Production of electricity by hydro | D | D_GEN_REN |
| 100 | Production of electricity by wind | D | D_GEN_REN |
| 101 | Production of electricity by petroleum and other oil derivatives | D | D_GEN_FOS |
| 102 | Production of electricity by biomass and waste | D | D_GEN_REN |
| 103 | Production of electricity by solar photovoltaic | D | D_GEN_REN |
| 104 | Production of electricity by solar thermal | D | D_GEN_REN |
| 105 | Production of electricity by tide, wave, ocean | D | D_GEN_REN |
| 106 | Production of electricity by Geothermal | D | D_GEN_REN |
| 107 | Production of electricity nec | D | D_GEN_FOS |
| 108 | Transmission of electricity | D | D_TD |
| 109 | Distribution and trade of electricity | D | D_TD |
| 110 | Manufacture of gas; distribution of gaseous fuels through mains | D | D_GAS |
| 111 | Steam and hot water supply | D | D_GAS |
| 112 | Collection, purification and distribution of water (41) | E | E |
| 113 | Construction (45) | F | F |
| 114 | Re-processing of secondary construction material into aggregates | B08 | B08 |
| 115 | Sale, maintenance, repair of motor vehicles, motor vehicles parts, motorcycles, motor cycles parts and accessoiries | G | G |
| 116 | Retail sale of automotive fuel | G | G |
| 117 | Wholesale trade and commission trade, except of motor vehicles and motorcycles (51) | G | G |
| 118 | Retail trade, except of motor vehicles and motorcycles; repair of personal and household goods (52) | G | G |
| 119 | Hotels and restaurants (55) | I | I |
| 120 | Transport via railways | H49 | H49 |
| 121 | Other land transport | H49 | H49 |
| 122 | Transport via pipelines | H49 | H49 |
| 123 | Sea and coastal water transport | H50 | H50 |
| 124 | Inland water transport | H50 | H50 |
| 125 | Air transport (62) | H51 | H51 |
| 126 | Supporting and auxiliary transport activities; activities of travel agencies (63) | H52 | H52 |
| 127 | Post and telecommunications (64) | J61 | J61 |
| 128 | Financial intermediation, except insurance and pension funding (65) | K | K |
| 129 | Insurance and pension funding, except compulsory social security (66) | K | K |
| 130 | Activities auxiliary to financial intermediation (67) | K | K |
| 131 | Real estate activities (70) | L | L |
| 132 | Renting of machinery and equipment without operator and of personal and household goods (71) | N | N |
| 133 | Computer and related activities (72) | J62_63 | J62_63 |
| 134 | Research and development (73) | M | M |
| 135 | Other business activities (74) | M | M |
| 136 | Public administration and defence; compulsory social security (75) | O | O |
| 137 | Education (80) | P | P |
| 138 | Health and social work (85) | Q | Q |
| 139 | Incineration of waste: Food | E | E |
| 140 | Incineration of waste: Paper | E | E |
| 141 | Incineration of waste: Plastic | E | E |
| 142 | Incineration of waste: Metals and Inert materials | E | E |
| 143 | Incineration of waste: Textiles | E | E |
| 144 | Incineration of waste: Wood | E | E |
| 145 | Incineration of waste: Oil/Hazardous waste | E | E |
| 146 | Biogasification of food waste, incl. land application | E | E |
| 147 | Biogasification of paper, incl. land application | E | E |
| 148 | Biogasification of sewage slugde, incl. land application | E | E |
| 149 | Composting of food waste, incl. land application | E | E |
| 150 | Composting of paper and wood, incl. land application | E | E |
| 151 | Waste water treatment, food | E | E |
| 152 | Waste water treatment, other | E | E |
| 153 | Landfill of waste: Food | E | E |
| 154 | Landfill of waste: Paper | E | E |
| 155 | Landfill of waste: Plastic | E | E |
| 156 | Landfill of waste: Inert/metal/hazardous | E | E |
| 157 | Landfill of waste: Textiles | E | E |
| 158 | Landfill of waste: Wood | E | E |
| 159 | Activities of membership organisation n.e.c. (91) | S | S |
| 160 | Recreational, cultural and sporting activities (92) | R | R |
| 161 | Other service activities (93) | S | S |
| 162 | Private households with employed persons (95) | T | T |
| 163 | Extra-territorial organizations and bodies | O | O |

## Appendix C: region groups

Group order is the table order. ICIO region codes are ISO3 (ISO2 in brackets, used only to match a
company's `country`); `CN1`, `CN2`, `MX1`, `MX2` and `ROW` are ICIO's own codes. EXIOBASE codes are
ISO2, plus its rest-of-world regions `WA` (Asia and Pacific), `WE` (Europe), `WF` (Africa), `WL`
(America) and `WM` (Middle East). `region_groups.csv` has one row per distinct code listed below
(ISO3, ISO2 and the special codes), each with its group. A company `country` matches a row's
code case-insensitively; the special codes `CN1`, `CN2`, `MX1`, `MX2`, `ROW` and `W*` are table
regions, not countries, and never match a company.

| # | Group | Name | ICIO 2025 regions | EXIOBASE regions |
|---|---|---|---|---|
| 1 | CN | China | CHN (CN), HKG (HK), CN1, CN2 | CN |
| 2 | US | United States | USA (US) | US |
| 3 | EU | European Union (27) | AUT (AT), BEL (BE), BGR (BG), HRV (HR), CYP (CY), CZE (CZ), DNK (DK), EST (EE), FIN (FI), FRA (FR), DEU (DE), GRC (GR), HUN (HU), IRL (IE), ITA (IT), LVA (LV), LTU (LT), LUX (LU), MLT (MT), NLD (NL), POL (PL), PRT (PT), ROU (RO), SVK (SK), SVN (SI), ESP (ES), SWE (SE) | AT, BE, BG, CY, CZ, DE, DK, EE, ES, FI, FR, GR, HR, HU, IE, IT, LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, SK |
| 4 | EUR_OTH | Other Europe and Central Asia | GBR (GB), CHE (CH), NOR (NO), ISL (IS), TUR (TR), RUS (RU), UKR (UA), BLR (BY), KAZ (KZ) | GB, CH, NO, TR, RU, WE |
| 5 | JP | Japan | JPN (JP) | JP |
| 6 | KR | Korea | KOR (KR) | KR |
| 7 | TW | Chinese Taipei | TWN (TW) | TW |
| 8 | IN | India | IND (IN) | IN |
| 9 | ASIA_OTH | Other Asia-Pacific | AUS (AU), NZL (NZ), IDN (ID), MYS (MY), PHL (PH), SGP (SG), THA (TH), VNM (VN), KHM (KH), LAO (LA), MMR (MM), BRN (BN), BGD (BD), PAK (PK) | AU, ID, WA |
| 10 | AMER_OTH | Other Americas | CAN (CA), MEX (MX), MX1, MX2, BRA (BR), ARG (AR), CHL (CL), COL (CO), CRI (CR), PER (PE) | CA, MX, BR, WL |
| 11 | MEA | Middle East and Africa | ARE (AE), SAU (SA), ISR (IL), JOR (JO), EGY (EG), MAR (MA), TUN (TN), ZAF (ZA), NGA (NG), SEN (SN), CIV (CI), CMR (CM), AGO (AO), COD (CD), STP (ST) | ZA, WF, WM |
| 12 | ROW | Rest of the world (ICIO only) | ROW | (none) |

## Appendix D: greenhouse-gas factors (GWP100, IPCC AR6)

The 23 greenhouse-gas stressors of `air_emissions/unit.txt` (3.11.2), in file order, with the factor
that turns the stressor's unit into kg CO₂e. CH₄ fossil 29.8, CH₄ non-fossil 27.0, N₂O 273, SF₆
25,200, NF₃ 17,400 (AR6 WG1 Table 7.15). HFC and PFC are already reported in kg CO₂-eq. Biogenic
CO₂ is 0, as in GHG Protocol inventories. Any other stressor (`SO2 …`, `NOx …`, …) is skipped.

| # | Stressor | Factor |
|---|---|---|
| 1 | CO2 - combustion - air | 1 |
| 2 | CH4 - combustion - air | 29.8 |
| 3 | N2O - combustion - air | 273 |
| 4 | CH4 - non combustion - Extraction/production of (natural) gas - air | 29.8 |
| 5 | CH4 - non combustion - Extraction/production of crude oil - air | 29.8 |
| 6 | CH4 - non combustion - Mining of antracite - air | 29.8 |
| 7 | CH4 - non combustion - Mining of bituminous coal - air | 29.8 |
| 8 | CH4 - non combustion - Mining of coking coal - air | 29.8 |
| 9 | CH4 - non combustion - Mining of lignite (brown coal) - air | 29.8 |
| 10 | CH4 - non combustion - Mining of sub-bituminous coal - air | 29.8 |
| 11 | CH4 - non combustion - Oil refinery - air | 29.8 |
| 12 | CO2 - non combustion - Cement production - air | 1 |
| 13 | CO2 - non combustion - Lime production - air | 1 |
| 14 | SF6 - air | 25200 |
| 15 | HFC - air | 1 |
| 16 | PFC - air | 1 |
| 17 | CH4 - agriculture - air | 27 |
| 18 | CO2 - agriculture - peat decay - air | 1 |
| 19 | N2O - agriculture - air | 273 |
| 20 | CH4 - waste - air | 27 |
| 21 | CO2 - waste - biogenic - air | 0 |
| 22 | CO2 - waste - fossil - air | 1 |
| 23 | NF3 - air | 17400 |
