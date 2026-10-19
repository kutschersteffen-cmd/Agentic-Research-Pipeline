# Import real OECD ICIO and EXIOBASE tables

Status: draft, 2026-10-19. Owner decisions: [research note](../../SECTOR_IO_MODELS_RESEARCH.md) §4
(EXIOBASE licence is no obstacle; focus on ICIO and EXIOBASE), scope "importers + source choice",
EXIOBASE "map to ISIC Rev.4".

## Intent

The indirect-exposure tier (`backend/arp/research/indirect_exposure/`) can read an ICIO-shaped
matrix and an EXIOBASE-shaped flows file, but only files someone has already prepared by hand.
Nothing turns the files the publishers actually ship into that shape. This spec adds two import
commands that do, a setting that picks which table backs a run, and a way for companies' own ISIC
codes to find the right industry in the imported tables.

## Scope

1. `arp io import-icio <csv> --out <dir> [--label <label>]` reads one OECD ICIO **2025 edition**
   year file and writes `industries.csv` and `icio_matrix.csv`, the pair `load_icio` already reads.
2. `arp io import-exiobase <zip> --out <dir> [--label <label>]` reads one EXIOBASE 3 **ixi**
   archive (`IOT_<year>_ixi.zip`) and writes `industries.csv` and `exiobase_flows.csv`, the pair
   `build_icio_from_long_format` already reads.
3. Both outputs use the same 50 industries: the ICIO 2025 list (Appendix A), with ICIO's codes.
   EXIOBASE's 163 sectors are mapped onto them by a bundled crosswalk (Appendix B).
4. Setting `ARP_IO_SOURCE` = `auto` (default) | `icio` | `exiobase`.
5. `arp io status` prints which table is active.
6. A company `isic_code` that is an ISIC Rev.4 division (`26`) resolves to the imported industry
   that contains it (`C26`) without an LLM call.

## My calls (owner to confirm with the acceptance table)

1. **Industry codes are ICIO's own codes** (`C26`, `D`, `J62_63`), in Appendix A order, for both
   importers. EXIOBASE maps onto them, so an ICIO-backed and an EXIOBASE-backed run share one code
   list and their numbers can be compared industry by industry.
2. **Regions are summed away**, as `ICIOData` already documents. ICIO's China and Mexico split
   rows (`CN1`, `CN2`, `MX1`, `MX2`) are regions like any other, so they are summed too.
3. **ICIO input layout** (from the 2025 edition note and pymrio's `parse_oecd`): a comma-separated
   file whose first row is the header and whose first column holds row labels; the header's first
   cell can be anything. A row or column label is an *industry label* when the part after its
   first `_` is one of the 50 codes (`AUS_C26`, `ROW_J62_63`, `CN1_D`). Every other row (`TLS`,
   `VA`, `OUT`, …) and every other column (`AUS_HFCE`, …) is ignored, except the column headed
   `OUT`, which gives each industry row's total output. An empty cell counts as 0.
4. **EXIOBASE input layout** (read from the real `IOT_2022_ixi.zip`, release 3.11.2): `Z.txt` and
   `x.txt` at the archive root, tab-separated. `Z.txt` has three header lines (`region\t\t<region>…`,
   `sector\t\t<sector>…`, `region\tsector\t…`), then one line per (region, sector) row: region,
   sector name, then one value per column. `x.txt` has the header `region\tsector\tindout`, then
   one line per (region, sector). The importer reads `Z.txt` one line at a time.
5. **Total output** comes from ICIO's `OUT` column and EXIOBASE's `indout`, summed over regions
   and, for EXIOBASE, over the sectors that map to the same industry. An industry no EXIOBASE
   sector maps to (C21, C301, H53, J58T60; see Appendix B) gets total output 0 and no flows.
6. **`industries.csv` gains a fourth column, `isic_divisions`**: the ISIC Rev.4 divisions an
   industry covers, two digits each, joined with `;` (`C10T12` → `10;11;12`; `C24A` → `24`). The
   existing loaders ignore extra columns, so hand-prepared files without it keep working.
7. **Division lookup**: a company `isic_code` that is not one of the model's codes but appears in
   exactly one industry's `isic_divisions` resolves to that industry, with no LLM call. A division
   in two industries (`24`: C24A and C24B; `30`: C301 and C302T309) falls back to the LLM
   classification, as an unknown code does today.
8. **`ARP_IO_SOURCE`**: `auto` keeps today's rule (ICIO if its two paths are set, else EXIOBASE if
   its two are set, else the tier is off). `icio` or `exiobase` uses only that table, and raises
   an error when its paths are not set. The sample flags (`use_sample_icio`,
   `use_sample_exiobase`) still win over the setting. An unknown value fails the settings load,
   like any malformed `ARP_` setting.
9. **Errors** the importers raise: exit 1, a one-line message on stderr, and no output files
   written. Output files that already exist are overwritten on success.
10. **Default labels**: `icio-<file stem>` and `exiobase-<archive stem>` (`icio-2022_SML`,
    `exiobase-IOT_2022_ixi`).

## Not in this spec

- Other tables (FIGARO, BEA, GLORIA, …), other EXIOBASE systems (`pxp`), other ICIO editions.
- Downloading files: the user downloads them; the commands read local files.
- Per-run source choice in the API or UI, and side-by-side comparison of the two tables.
- Keeping EXIOBASE's native 163 sectors (owner chose mapping to ISIC Rev.4 industries).
- The criticality overlay and standards mapping. Both match ISIC divisions such as `07`, so with
  imported tables they will not match ICIO codes such as `B07` until a later change teaches them
  `isic_divisions`.
- Country-level results: regions stay summed away.

## Acceptance

Setup notes for the test-writer:
- Run commands as `arp io …`. Settings are read from the environment when each command starts.
- `industries.csv` columns: `isic_code,label,total_output,isic_divisions`, one row per Appendix A
  code, in Appendix A order, labels exactly as in Appendix A.
- `icio_matrix.csv`: header `isic_code,<code 1>,…,<code 50>`; then one row per code, first cell the
  code; cell (i, j) is the flow from industry i to industry j.
- `exiobase_flows.csv`: header `supplier_isic_code,user_isic_code,value`; one row per supplier/user
  pair with a non-zero value, ordered by supplier then user in Appendix A order.
- Numbers are compared as floats with a relative tolerance of 1e-9.
- **Fixture I** (ICIO): a CSV with header cell `V1`, then columns for every Appendix A code in regions
  `AAA` and `BBB` (`AAA_A01` … `BBB_T`), then `AAA_HFCE`, `BBB_GFCF` and `OUT`. Rows: the same 100
  industry labels, then `TLS`, `VA` and `OUT`. All intermediate cells are 0 except
  `AAA_C26→BBB_C27` = 10, `BBB_C26→AAA_C27` = 5 and `AAA_D→AAA_C26` = 2. `OUT` is 100 for
  `AAA_C26`, 50 for `BBB_C26`, 40 for `AAA_C27`, 60 for `BBB_C27`, 30 for `AAA_D` and 1 for every
  other industry row. `AAA_HFCE`, `BBB_GFCF` and the `TLS`, `VA`, `OUT` rows hold 7 in every cell.
- **Fixture E** (EXIOBASE): a zip holding `Z.txt` and `x.txt` at its root in the layout of call 4,
  with regions `AT` and `WA` and the 163 Appendix B sector names in Appendix B order. All `Z` values
  are 0 except (AT, B#87)→(WA, B#88) = 10, (WA, B#89)→(AT, B#88) = 5, (AT, B#108)→(AT, B#87) = 2
  and (AT, B#100)→(AT, B#87) = 3, where B#n is Appendix B row n. `indout` is 100 for (AT, B#87),
  50 for (WA, B#89), 40 for (AT, B#88), 60 for (WA, B#88), 30 for (AT, B#108), 20 for (AT, B#100)
  and 0 otherwise.
- "ICIO configured" means `ARP_ICIO_MATRIX_PATH` and `ARP_ICIO_INDUSTRIES_PATH` point at fixture I's
  import output; "EXIOBASE configured" means `ARP_EXIOBASE_FLOWS_PATH` and
  `ARP_EXIOBASE_INDUSTRIES_PATH` point at fixture E's. Unset paths are unset variables.
- **Theme T**: a `ThemeDefinition` JSON with one activity whose `core_isic_codes` is `["C27"]`;
  **universe U**: a CSV with one company (`name` `Acme`, `isic_code` `27`). Theme-run rows set
  `ARP_ANTHROPIC_API_KEY` to a dummy value: the source check fails before any model call. API rows
  run the app with `ARP_AUTH_MODE=local` as an `analyst` and post
  `{"theme": <T>, "companies": [<Acme as CompanyRef>]}` to `POST /api/themes/runs`.
- Division lookup rows call `resolve_company_isic(company, model, llm)` from
  `arp.research.indirect_exposure.company_mapper`, with `model` from
  `resolve_indirect_exposure_model(Settings())` and an `llm` stub whose `complete_structured`
  returns `isic_code` `None` and records that it was called.

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | Fixture I | `arp io import-icio <file> --out <dir>` | Exit 0; stdout line 1 is `50 industries, 2 regions -> <dir>` | holdout |
| AC-2 | AC-1's output | Read `<dir>/industries.csv` | 50 rows in Appendix A order; `C26` total_output 150, `C27` 100, `D` 31, `A01` 2; `C10T12` isic_divisions `10;11;12`; `C24A` `24`; `A01` `01` | holdout |
| AC-3 | AC-1's output | Read `<dir>/icio_matrix.csv` | (C26, C27) = 15, (D, C26) = 2, every other cell 0 | holdout |
| AC-4 | AC-1 | stdout lines 2 to 5 | `ARP_IO_SOURCE=icio`, `ARP_ICIO_MATRIX_PATH=<abs dir>/icio_matrix.csv`, `ARP_ICIO_INDUSTRIES_PATH=<abs dir>/industries.csv`, `ARP_ICIO_EDITION_LABEL=icio-<file stem>`, in that order | holdout |
| AC-5 | Fixture I | `arp io import-icio <file> --out <dir> --label ICIO2025-2022` | stdout line 5 is `ARP_ICIO_EDITION_LABEL=ICIO2025-2022` | holdout |
| AC-6 | Fixture I with the `OUT` column removed | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `no OUT column`; `<dir>/industries.csv` does not exist | holdout |
| AC-7 | Fixture I with every `_C24A` and `_C24B` row and column relabelled `_C24` | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `missing ICIO industries: C24A, C24B` | holdout |
| AC-8 | Fixture I with cell `AAA_C26→BBB_C27` set to `x` | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `row AAA_C26, column BBB_C27: not a number: 'x'` | holdout |
| AC-9 | Fixture I with region `AAA` renamed `CN1` and `BBB` renamed `CN2` | `arp io import-icio <file> --out <dir>` | Exit 0; same `icio_matrix.csv` values as AC-3 | holdout |
| AC-10 | Fixture E | `arp io import-exiobase <zip> --out <dir>` | Exit 0; stdout line 1 is `163 sectors -> 50 industries, 2 regions -> <dir>` | holdout |
| AC-11 | AC-10's output | Read `<dir>/industries.csv` | 50 rows in Appendix A order; `C26` total_output 150, `C27` 100, `D` 50, `C21` 0; isic_divisions as in AC-2 | holdout |
| AC-12 | AC-10's output | Read `<dir>/exiobase_flows.csv` | Exactly two data rows: `C26,C27,15` then `D,C26,5` | holdout |
| AC-13 | AC-10 | stdout lines 2 to 5 | `ARP_IO_SOURCE=exiobase`, `ARP_EXIOBASE_FLOWS_PATH=<abs dir>/exiobase_flows.csv`, `ARP_EXIOBASE_INDUSTRIES_PATH=<abs dir>/industries.csv`, `ARP_EXIOBASE_EDITION_LABEL=exiobase-<zip stem>`, in that order | holdout |
| AC-14 | Fixture E with sector B#87 renamed `Made-up sector` in `Z.txt` and `x.txt` | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `EXIOBASE sector not in crosswalk: Made-up sector` | holdout |
| AC-15 | A zip with `x.txt` but no `Z.txt` | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `no Z.txt at the archive root` | holdout |
| AC-16 | The bundled crosswalk | Look up Appendix B rows 87, 88, 89, 100, 108, 133, 55, 163 | `C26`, `C27`, `C26`, `D`, `D`, `J62_63`, `C17_18`, `O`; all 163 rows map to an Appendix A code | holdout |
| AC-17 | ICIO configured, EXIOBASE not, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout `source: icio`, `edition: icio-<fixture I stem>`, `industries: 50`, one per line | holdout |
| AC-18 | ICIO and EXIOBASE configured, `ARP_IO_SOURCE` unset | `arp io status` | stdout line 1 `source: icio` | holdout |
| AC-19 | ICIO and EXIOBASE configured, `ARP_IO_SOURCE=exiobase` | `arp io status` | stdout `source: exiobase`, `edition: exiobase-<fixture E stem>`, `industries: 50` | holdout |
| AC-20 | Neither configured, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout `source: none` | holdout |
| AC-21 | EXIOBASE configured, ICIO not, `ARP_IO_SOURCE=icio` | `arp io status` | Exit 1; stderr contains `io source icio is not configured: set ARP_ICIO_MATRIX_PATH and ARP_ICIO_INDUSTRIES_PATH` | holdout |
| AC-22 | ICIO configured, EXIOBASE not, `ARP_IO_SOURCE=exiobase` | `arp theme run --theme <T> --universe <U>` | Exit 1; stderr contains `io source exiobase is not configured: set ARP_EXIOBASE_FLOWS_PATH and ARP_EXIOBASE_INDUSTRIES_PATH` | holdout |
| AC-23 | ICIO configured, `ARP_IO_SOURCE=exiobase`, EXIOBASE not | `POST /api/themes/runs` with T and Acme | Status 400; `detail` equals AC-22's message | holdout |
| AC-24 | ICIO configured, `ARP_IO_SOURCE=icio` | `resolve_company_isic` for a company with `isic_code` `26` | Returns `C26`; the LLM stub was not called | holdout |
| AC-25 | As AC-24 | Company `isic_code` `62` | Returns `J62_63`; stub not called | holdout |
| AC-26 | As AC-24 | Company `isic_code` `24` | Returns `None`; stub called once | holdout |
| AC-27 | As AC-24 | Company `isic_code` `C27` | Returns `C27`; stub not called | holdout |
| AC-28 | `ARP_IO_SOURCE=exiobase`, nothing configured | `resolve_indirect_exposure_model(Settings(), use_sample_icio=True)` | Returns the bundled sample model: 10 codes, first `07` | holdout |
| AC-29 | Nothing configured, `ARP_IO_SOURCE` unset | `resolve_indirect_exposure_model(Settings())` | Returns `None` (tier off, as today) | holdout |
| AC-30 | `use_sample_icio=True` | `resolve_company_isic` for a company with `isic_code` `27` | Returns `27`; stub not called (sample codes unchanged) | holdout |
| AC-31 | The hand-prepared sample `industries.csv` (three columns, no `isic_divisions`) set as `ARP_ICIO_INDUSTRIES_PATH` with the sample matrix | `arp io status` | Exit 0; `source: icio`, `industries: 10` | holdout |
| AC-32 | The real `IOT_2022_ixi.zip` from Zenodo record 23039074 | `arp io import-exiobase <zip> --out <dir>`, then `arp io status` with the printed settings | Import exits 0 within 15 minutes, stdout line 1 `163 sectors -> 50 industries, 49 regions -> <dir>`; status prints `industries: 50`; `D`'s total_output in `industries.csv` is greater than 0 | evaluator |
| AC-33 | AC-32's settings and a real `ARP_ANTHROPIC_API_KEY` | `arp theme run --theme <T> --universe <U>` | stdout contains `Indirect exposure tier enabled (exiobase-IOT_2022_ixi).`; exit 0; Acme's match has a non-null `indirect_exposure` | evaluator |

Must not change: the bundled samples (AC-28, AC-30), `auto` order (AC-18, AC-29), hand-prepared
files without `isic_divisions` (AC-31), codes already in the model used directly (AC-27).

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

## Appendix B: EXIOBASE 3 ixi sectors → ICIO 2025

Sector names exactly as in `unit.txt` of `IOT_2022_ixi.zip` (3.11.2), in file order. Codes in
brackets are EXIOBASE's ISIC Rev.3-style codes. Rule for "Re-processing of secondary X" sectors:
they map to the industry that makes primary X. No sector maps to C21 (pharma sits inside
"Chemicals nec"), C301 (ships sit inside "other transport equipment"), H53 (post sits inside
"Post and telecommunications") or J58T60 (publishing sits inside "Publishing, printing").

| # | EXIOBASE sector | ICIO |
|---|---|---|
| 1–17 | Cultivation of paddy rice; Cultivation of wheat; Cultivation of cereal grains nec; Cultivation of vegetables, fruit, nuts; Cultivation of oil seeds; Cultivation of sugar cane, sugar beet; Cultivation of plant-based fibers; Cultivation of crops nec; Cattle farming; Pigs farming; Poultry farming; Meat animals nec; Animal products nec; Raw milk; Wool, silk-worm cocoons; Manure treatment (conventional), storage and land application; Manure treatment (biogas), storage and land application | A01 |
| 18 | Forestry, logging and related service activities (02) | A02 |
| 19 | Fishing, operating of fish hatcheries and fish farms; service activities incidental to fishing (05) | A03 |
| 20 | Mining of coal and lignite; extraction of peat (10) | B05 |
| 21–23 | Extraction of crude petroleum and services related to crude oil extraction, excluding surveying; Extraction of natural gas and services related to natural gas extraction, excluding surveying; Extraction, liquefaction, and regasification of other petroleum and gaseous materials | B06 |
| 24–31 | Mining of uranium and thorium ores (12); Mining of iron ores; Mining of copper ores and concentrates; Mining of nickel ores and concentrates; Mining of aluminium ores and concentrates; Mining of precious metal ores and concentrates; Mining of lead, zinc and tin ores and concentrates; Mining of other non-ferrous metal ores and concentrates | B07 |
| 32–34 | Quarrying of stone; Quarrying of sand and clay; Mining of chemical and fertilizer minerals, production of salt, other mining and quarrying n.e.c. | B08 |
| 35–46 | Processing of meat cattle; Processing of meat pigs; Processing of meat poultry; Production of meat products nec; Processing vegetable oils and fats; Processing of dairy products; Processed rice; Sugar refining; Processing of Food products nec; Manufacture of beverages; Manufacture of fish products; Manufacture of tobacco products (16) | C10T12 |
| 47–49 | Manufacture of textiles (17); Manufacture of wearing apparel; dressing and dyeing of fur (18); Tanning and dressing of leather; manufacture of luggage, handbags, saddlery, harness and footwear (19) | C13T15 |
| 50–51 | Manufacture of wood and of products of wood and cork, except furniture; manufacture of articles of straw and plaiting materials (20); Re-processing of secondary wood material into new wood material | C16 |
| 52–55 | Pulp; Re-processing of secondary paper into new pulp; Paper; Publishing, printing and reproduction of recorded media (22) | C17_18 |
| 56–57 | Manufacture of coke oven products; Petroleum Refinery | C19 |
| 58–63 | Processing of nuclear fuel; Plastics, basic; Re-processing of secondary plastic into new plastic; N-fertiliser; P- and other fertiliser; Chemicals nec | C20 |
| 64 | Manufacture of rubber and plastic products (25) | C22 |
| 65–71 | Manufacture of glass and glass products; Re-processing of secondary glass into new glass; Manufacture of ceramic goods; Manufacture of bricks, tiles and construction products, in baked clay; Manufacture of cement, lime and plaster; Re-processing of ash into clinker; Manufacture of other non-metallic mineral products n.e.c. | C23 |
| 72–73 | Manufacture of basic iron and steel and of ferro-alloys and first products thereof; Re-processing of secondary steel into new steel | C24A |
| 74–83 | Precious metals production; Re-processing of secondary preciuos metals into new preciuos metals; Aluminium production; Re-processing of secondary aluminium into new aluminium; Lead, zinc and tin production; Re-processing of secondary lead into new lead, zinc and tin; Copper production; Re-processing of secondary copper into new copper; Other non-ferrous metal production; Re-processing of secondary other non-ferrous metals into new other non-ferrous metals | C24B |
| 84 | Casting of metals | C24A |
| 85 | Manufacture of fabricated metal products, except machinery and equipment (28) | C25 |
| 86 | Manufacture of machinery and equipment n.e.c. (29) | C28 |
| 87 | Manufacture of office machinery and computers (30) | C26 |
| 88 | Manufacture of electrical machinery and apparatus n.e.c. (31) | C27 |
| 89 | Manufacture of radio, television and communication equipment and apparatus (32) | C26 |
| 90 | Manufacture of medical, precision and optical instruments, watches and clocks (33) | C26 |
| 91 | Manufacture of motor vehicles, trailers and semi-trailers (34) | C29 |
| 92 | Manufacture of other transport equipment (35) | C302T309 |
| 93 | Manufacture of furniture; manufacturing n.e.c. (36) | C31T33 |
| 94–95 | Recycling of waste and scrap; Recycling of bottles by direct reuse | E |
| 96–111 | Production of electricity by coal; … by gas; … by nuclear; … by hydro; … by wind; … by petroleum and other oil derivatives; … by biomass and waste; … by solar photovoltaic; … by solar thermal; … by tide, wave, ocean; … by Geothermal; Production of electricity nec; Transmission of electricity; Distribution and trade of electricity; Manufacture of gas; distribution of gaseous fuels through mains; Steam and hot water supply | D |
| 112 | Collection, purification and distribution of water (41) | E |
| 113 | Construction (45) | F |
| 114 | Re-processing of secondary construction material into aggregates | B08 |
| 115–118 | Sale, maintenance, repair of motor vehicles, motor vehicles parts, motorcycles, motor cycles parts and accessoiries; Retail sale of automotive fuel; Wholesale trade and commission trade, except of motor vehicles and motorcycles (51); Retail trade, except of motor vehicles and motorcycles; repair of personal and household goods (52) | G |
| 119 | Hotels and restaurants (55) | I |
| 120–122 | Transport via railways; Other land transport; Transport via pipelines | H49 |
| 123–124 | Sea and coastal water transport; Inland water transport | H50 |
| 125 | Air transport (62) | H51 |
| 126 | Supporting and auxiliary transport activities; activities of travel agencies (63) | H52 |
| 127 | Post and telecommunications (64) | J61 |
| 128–130 | Financial intermediation, except insurance and pension funding (65); Insurance and pension funding, except compulsory social security (66); Activities auxiliary to financial intermediation (67) | K |
| 131 | Real estate activities (70) | L |
| 132 | Renting of machinery and equipment without operator and of personal and household goods (71) | N |
| 133 | Computer and related activities (72) | J62_63 |
| 134–135 | Research and development (73); Other business activities (74) | M |
| 136 | Public administration and defence; compulsory social security (75) | O |
| 137 | Education (80) | P |
| 138 | Health and social work (85) | Q |
| 139–158 | Incineration of waste: Food; … Paper; … Plastic; … Metals and Inert materials; … Textiles; … Wood; … Oil/Hazardous waste; Biogasification of food waste, incl. land application; Biogasification of paper, incl. land application; Biogasification of sewage slugde, incl. land application; Composting of food waste, incl. land application; Composting of paper and wood, incl. land application; Waste water treatment, food; Waste water treatment, other; Landfill of waste: Food; … Paper; … Plastic; … Inert/metal/hazardous; … Textiles; … Wood | E |
| 159 | Activities of membership organisation n.e.c. (91) | S |
| 160 | Recreational, cultural and sporting activities (92) | R |
| 161 | Other service activities (93) | S |
| 162 | Private households with employed persons (95) | T |
| 163 | Extra-territorial organizations and bodies | O |

In the ranges above, "…" stands for the prefix of the previous name (`Production of electricity
by`, `Incineration of waste:`, `Landfill of waste:`); the bundled crosswalk file spells every name
out in full, exactly as in `unit.txt`.
