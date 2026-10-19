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
2. **Reference files ship with the code**, in `backend/arp/research/indirect_exposure/reference/`:
   `icio2025_industries.csv` (`code,label,isic_divisions`, Appendix A) and
   `exiobase_ixi_to_icio2025.csv` (`exiobase_sector,icio_code`, Appendix B, 163 rows in Appendix B
   order). Sector names are exact `unit.txt` strings, bracketed codes included.
3. **Regions are summed away**, as `ICIOData` already documents. ICIO's China and Mexico split
   regions (`CN1`, `CN2`, `MX1`, `MX2`) are regions like any other, so they are summed too. "N
   regions" in the import message is the number of distinct region prefixes among industry *row*
   labels (ICIO) or among `Z.txt` data rows (EXIOBASE).
4. **ICIO input layout** (from the 2025 edition note and pymrio's `parse_oecd`): a comma-separated
   file whose first row is the header and whose first column holds row labels; the header's first
   cell can be anything. A row or column label is an *industry label* when the part after its
   first `_` is one of the 50 codes (`AUS_C26`, `ROW_J62_63`, `CN1_D`). Only two kinds of cell are
   read: cells whose row and column labels are both industry labels, and the `OUT` column's cell in
   each industry row (that industry row's total output). Every other row (`TLS`, `VA`, `OUT`, …)
   and column (`AUS_HFCE`, …) is never parsed. An empty cell that is read counts as 0.
5. **Missing industries (ICIO)**: an Appendix A code is missing when no industry row label, or no
   industry column label, in any region has that code. A code present in only some regions is not
   missing. The error lists missing codes in Appendix A order, joined with `, `.
6. **EXIOBASE input layout** (read from the real `IOT_2022_ixi.zip`, release 3.11.2): `Z.txt` and
   `x.txt` at the archive root, tab-separated. `Z.txt` line 1 is `region`, an empty cell, then one
   region per column; line 2 is `sector`, an empty cell, then one sector name per column; line 3 is
   `region`, `sector`, then one empty cell per column. Every later line is one row: region, sector
   name, then one value per column. Columns are identified by header lines 1 and 2, never by
   position. `x.txt` has the header `region\tsector\tindout`, then one line per (region, sector).
   The importer reads `Z.txt` one line at a time. A sector name in the archive that is not in the
   crosswalk is an error; a crosswalk sector absent from the archive is not. "N sectors" in the
   import message is the number of distinct sector names among `Z.txt` data rows.
7. **Total output** comes from ICIO's `OUT` column and EXIOBASE's `indout`, summed over regions
   and, for EXIOBASE, over the sectors that map to the same industry. An industry no EXIOBASE
   sector maps to (B09, C21, C301, H53, J58T60; see Appendix B) gets total output 0 and no flows.
8. **`industries.csv` gains a fourth column, `isic_divisions`**: the ISIC Rev.4 divisions an
   industry covers, two digits each, joined with `;` (`C10T12` → `10;11;12`; `C24A` → `24`). The
   existing loaders ignore extra columns, so hand-prepared files without it keep working.
9. **Division lookup**: a company `isic_code` that is not one of the model's codes but equals,
   as an exact string, one two-digit entry in exactly one industry's `isic_divisions` resolves to
   that industry, with no LLM call. No normalisation: `2610`, `6` or `26.1` are not divisions. A
   division in two industries (`24`: C24A and C24B; `30`: C301 and C302T309) and any non-division
   code fall back to the LLM classification, as an unknown code does today.
10. **`ARP_IO_SOURCE`**: `auto` keeps today's rule (ICIO if its two paths are set, else EXIOBASE
    if its two are set, else the tier is off). `icio` or `exiobase` uses only that table, and
    raises a `ValueError` when either of its two paths is unset, which today's CLI commands report on stderr
    with exit 1 and the API returns as 400. The sample flags (`use_sample_icio`,
    `use_sample_exiobase`) still win over the setting. Values are case-sensitive; any other value
    fails the settings load.
11. **Importer output**: `--out` is created with its parents if missing. Paths printed are
    `Path(<dir>).resolve()`. Output files that already exist are overwritten on success. On any
    error: exit 1, exactly one line on stderr, and no output file written.
12. **Default labels**: `icio-<file stem>` and `exiobase-<archive stem>` (`icio-2022_SML`,
    `exiobase-IOT_2022_ixi`). `arp io status` prints the active source's `ARP_*_EDITION_LABEL`
    setting; unset, it keeps today's defaults, `sample` (ICIO) and `exiobase-sample` (EXIOBASE).

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
  Tests set only the variables a row or these notes name; every other `ARP_` variable is unset.
- `<D>` is `Path(<dir>).resolve()`. Import rows pass `--out` as a relative path.
- In every import error row (AC-6, AC-7, AC-8, AC-14, AC-15, AC-48), `<dir>` starts empty, stderr
  is exactly one line, and afterwards `<dir>` holds none of `industries.csv`, `icio_matrix.csv`,
  `exiobase_flows.csv`. Other exit-1 rows check only that stderr contains the given text.
- `industries.csv` columns: `isic_code,label,total_output,isic_divisions`, one row per Appendix A
  code, in Appendix A order.
- `icio_matrix.csv`: header `isic_code,<code 1>,…,<code 50>`; then one row per code, first cell the
  code; cell (i, j) is the flow from industry i to industry j.
- `exiobase_flows.csv`: header `supplier_isic_code,user_isic_code,value`; one row per supplier/user
  pair with a non-zero value, ordered by supplier then user in Appendix A order.
- Numbers are compared as floats with a relative tolerance of 1e-9.
- **Fixture I** (ICIO): file `icio_fixture.csv`. Header: `V1`, then columns for every Appendix A
  code in region `AAA` then region `BBB` (`AAA_A01` … `AAA_T`, `BBB_A01` … `BBB_T`), then
  `AAA_HFCE`, `BBB_GFCF` and `OUT`. Rows: the same 100 industry labels in the same order, then
  `TLS`, `VA` and `OUT`. All industry×industry cells are 0 except `AAA_C26→BBB_C27` = 10,
  `BBB_C26→AAA_C27` = 5 and `AAA_D→AAA_C26` = 2 (row label → column label). `OUT` is 100 for
  `AAA_C26`, 50 for `BBB_C26`, 40 for `AAA_C27`, 60 for `BBB_C27`, 30 for `AAA_D` and 1 for every
  other industry row. Every cell of `AAA_HFCE`, `BBB_GFCF` and of the `TLS`, `VA`, `OUT` rows is 7.
- **Fixture E** (EXIOBASE): file `IOT_fixture_ixi.zip`, holding `Z.txt` and `x.txt` at its root in
  the layout of call 6, with regions `AT` then `WA` and, within each, the 163 Appendix B names in
  Appendix B order, for both rows and columns. B#n is Appendix B row n. All `Z` values are 0
  except (AT, B#87)→(WA, B#88) = 10, (WA, B#89)→(AT, B#88) = 5, (AT, B#108)→(AT, B#87) = 2 and
  (AT, B#100)→(AT, B#87) = 3 (row → column). `indout` is 100 for (AT, B#87), 50 for (WA, B#89), 40
  for (AT, B#88), 60 for (WA, B#88), 30 for (AT, B#108), 20 for (AT, B#100) and 0 otherwise.
- **"ICIO configured"** means the three variables printed on stdout lines 3 to 5 by importing
  fixture I (AC-4) are set; **"EXIOBASE configured"** means the three from importing fixture E
  (AC-13) are set.
- **Theme T** (file `theme_t.json`, `arp.schemas.thematic.ThemeDefinition`):
  `{"name": "Grid equipment", "description": "Makers of electrical equipment for power grids.",
  "activities": [{"name": "Electrical equipment", "in_scope_description": "Transformers, switchgear
  and cables for power grids.", "out_of_scope_description": "Consumer electronics.",
  "seed_keywords": ["transformer", "switchgear"], "core_isic_codes": ["C27"]}]}`.
  **Universe U** (file `universe_u.csv`): header `company_id,name,isic_code`, one row
  `acme,Acme,27`. `--theme` and `--universe` take these file paths.
- AC-22 and AC-23 set `ARP_ANTHROPIC_API_KEY` to a dummy value and `ARP_POSTGRES_DSN` and
  `ARP_RUNS_DIR` as in other holdout tests; the source check fails before any model call. API rows run the app with `ARP_AUTH_MODE=local` and `ARP_USERS_FILE` pointing at a
  file in the format of `config/users.example.json` holding one user with role `analyst`, send
  `Authorization: Bearer <that token>`, and post
  `{"theme": <T>, "companies": [{"company_id": "acme", "name": "Acme", "isic_code": "27"}]}` to
  `POST /api/themes/runs`.
- Model rows call `resolve_indirect_exposure_model(Settings(), …)` from
  `arp.research.indirect_exposure.factory` (`Settings` from `arp.config`) and read the returned
  `LeontiefModel`'s `codes` (list of str) and `edition_label` (str).
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
| AC-34 | AC-1's output | Read `<D>/industries.csv` | Every row's `label` and `isic_divisions` equal its Appendix A row | holdout |
| AC-3 | AC-1's output | Read `<D>/icio_matrix.csv` | (C26, C27) = 15, (D, C26) = 2, every other cell 0 | holdout |
| AC-4 | AC-1 | stdout lines 2 to 5 | Exactly `ARP_IO_SOURCE=icio`, `ARP_ICIO_MATRIX_PATH=<D>/icio_matrix.csv`, `ARP_ICIO_INDUSTRIES_PATH=<D>/industries.csv`, `ARP_ICIO_EDITION_LABEL=icio-icio_fixture`, in that order | holdout |
| AC-5 | Fixture I | `arp io import-icio icio_fixture.csv --out <dir> --label ICIO2025-2022` | stdout line 5 is `ARP_ICIO_EDITION_LABEL=ICIO2025-2022` | holdout |
| AC-6 | Fixture I without its `OUT` column | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `no OUT column` | holdout |
| AC-7 | Fixture I with every `_C24A` and `_C24B` row and column label relabelled `_C24` | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `missing ICIO industries: C24A, C24B` | holdout |
| AC-48 | Fixture I with only the column labels `AAA_C24A` and `BBB_C24A` relabelled `AAA_C24` and `BBB_C24` (row labels unchanged) | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `missing ICIO industries: C24A` | holdout |
| AC-8 | Fixture I with cell `AAA_C26→BBB_C27` = `x` | `arp io import-icio <file> --out <dir>` | Exit 1; stderr contains `row AAA_C26, column BBB_C27: not a number: 'x'` | holdout |
| AC-35 | Fixture I with cell `TLS→AAA_C26` = `x` and cell `AAA_C26→AAA_HFCE` = `x` | `arp io import-icio <file> --out <dir>` | Exit 0; `icio_matrix.csv` as in AC-3 | holdout |
| AC-36 | Fixture I with cell `AAA_D→AAA_C26` empty | `arp io import-icio <file> --out <dir>` | Exit 0; (D, C26) = 0 | holdout |
| AC-47 | Fixture I with `AAA_A01`'s `OUT` cell empty | `arp io import-icio <file> --out <dir>` | Exit 0; `A01` total_output 1 | holdout |
| AC-37 | Fixture I without row `BBB_T` and column `BBB_T` | `arp io import-icio <file> --out <dir>` | Exit 0; stdout line 1 `50 industries, 2 regions -> <D>`; `T` total_output 1 | holdout |
| AC-9 | Fixture I with region `AAA` renamed `CN1` and `BBB` renamed `CN2` in every label | `arp io import-icio <file> --out <dir>` | Exit 0; stdout line 1 `50 industries, 2 regions -> <D>`; `icio_matrix.csv` as in AC-3 | holdout |
| AC-53 | Fixture I plus one extra column `CCC_A01` (every cell 0) | `arp io import-icio <file> --out <dir>` | Exit 0; stdout line 1 `50 industries, 2 regions -> <D>` | holdout |
| AC-38 | Fixture I; `<dir>` is `a/b`, which does not exist | `arp io import-icio icio_fixture.csv --out a/b` | Exit 0; `a/b/industries.csv` and `a/b/icio_matrix.csv` exist | holdout |
| AC-39 | `<dir>/industries.csv` exists with content `old` | `arp io import-icio icio_fixture.csv --out <dir>` | Exit 0; `<D>/industries.csv` as in AC-2 | holdout |
| AC-10 | Fixture E | `arp io import-exiobase IOT_fixture_ixi.zip --out <dir>` | Exit 0; stdout line 1 is `163 sectors -> 50 industries, 2 regions -> <D>` | holdout |
| AC-11 | AC-10's output | Read `<D>/industries.csv` | 50 rows in Appendix A order; total_output `C26` 150, `C27` 100, `D` 50, `C21` 0; `label` and `isic_divisions` as in AC-34 | holdout |
| AC-12 | AC-10's output | Read `<D>/exiobase_flows.csv` | Exactly two data rows, compared as (supplier, user, float value): (C26, C27, 15) then (D, C26, 5) | holdout |
| AC-13 | AC-10 | stdout lines 2 to 5 | Exactly `ARP_IO_SOURCE=exiobase`, `ARP_EXIOBASE_FLOWS_PATH=<D>/exiobase_flows.csv`, `ARP_EXIOBASE_INDUSTRIES_PATH=<D>/industries.csv`, `ARP_EXIOBASE_EDITION_LABEL=exiobase-IOT_fixture_ixi`, in that order | holdout |
| AC-40 | Fixture E | `arp io import-exiobase IOT_fixture_ixi.zip --out <dir> --label X3` | stdout line 5 is `ARP_EXIOBASE_EDITION_LABEL=X3` | holdout |
| AC-49 | Fixture E with the `Z.txt` columns in reverse order: header lines 1 to 3 and the value cells of every data row are reversed together, so each value stays under its own (region, sector) header; the data rows' order and first two cells are unchanged | `arp io import-exiobase <zip> --out <dir>` | Exit 0; `exiobase_flows.csv` as in AC-12 | holdout |
| AC-14 | Fixture E with B#87's name replaced by `Made-up sector` everywhere: `Z.txt` header line 2 (both regions), the sector cell of both its `Z.txt` rows, and both its `x.txt` rows | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `EXIOBASE sector not in crosswalk: Made-up sector` | holdout |
| AC-15 | A zip with fixture E's `x.txt` but no `Z.txt` | `arp io import-exiobase <zip> --out <dir>` | Exit 1; stderr contains `no Z.txt at the archive root` | holdout |
| AC-51 | `reference/icio2025_industries.csv` | Read the whole file | Header `code,label,isic_divisions`; 50 data rows equal, in order, to Appendix A's (Code, Label, isic_divisions) | holdout |
| AC-16 | `reference/exiobase_ixi_to_icio2025.csv` | Read the `icio_code` of Appendix B rows 87, 88, 89, 100, 108, 133, 55, 163 | `C26`, `C27`, `C26`, `D`, `D`, `J62_63`, `C17_18`, `O` | holdout |
| AC-41 | `reference/exiobase_ixi_to_icio2025.csv` | Read the whole file | Header `exiobase_sector,icio_code`; 163 data rows equal, in order, to Appendix B's (sector, ICIO) pairs | holdout |
| AC-17 | ICIO configured, EXIOBASE not, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout is exactly `source: icio`, `edition: icio-icio_fixture`, `industries: 50`, one per line | holdout |
| AC-18 | ICIO and EXIOBASE configured, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout line 1 is `source: icio` | holdout |
| AC-42 | EXIOBASE configured, ICIO not, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout line 1 is `source: exiobase` | holdout |
| AC-19 | ICIO and EXIOBASE configured, `ARP_IO_SOURCE=exiobase` | `arp io status` | Exit 0; stdout is exactly `source: exiobase`, `edition: exiobase-IOT_fixture_ixi`, `industries: 50` | holdout |
| AC-20 | Neither configured, `ARP_IO_SOURCE` unset | `arp io status` | Exit 0; stdout is exactly `source: none` | holdout |
| AC-21 | EXIOBASE configured, ICIO not, `ARP_IO_SOURCE=icio` | `arp io status` | Exit 1; stderr contains `io source icio is not configured: set ARP_ICIO_MATRIX_PATH and ARP_ICIO_INDUSTRIES_PATH` | holdout |
| AC-50 | Only `ARP_ICIO_MATRIX_PATH` set (to fixture I's import output), `ARP_IO_SOURCE=icio` | `arp io status` | Exit 1; stderr contains `io source icio is not configured: set ARP_ICIO_MATRIX_PATH and ARP_ICIO_INDUSTRIES_PATH` | holdout |
| AC-43 | `ARP_IO_SOURCE=figaro` | `arp io status` | Exit 1; stderr contains `Input should be 'auto', 'icio' or 'exiobase'` | holdout |
| AC-44 | `ARP_IO_SOURCE=ICIO` | `arp io status` | Exit 1; stderr contains `Input should be 'auto', 'icio' or 'exiobase'` | holdout |
| AC-22 | ICIO configured, EXIOBASE not, `ARP_IO_SOURCE=exiobase` | `arp theme run --theme <T> --universe <U>` | Exit 1; stderr contains `io source exiobase is not configured: set ARP_EXIOBASE_FLOWS_PATH and ARP_EXIOBASE_INDUSTRIES_PATH` | holdout |
| AC-23 | As AC-22 | `POST /api/themes/runs` with T and Acme | Status 400; `detail` equals `io source exiobase is not configured: set ARP_EXIOBASE_FLOWS_PATH and ARP_EXIOBASE_INDUSTRIES_PATH` | holdout |
| AC-24 | ICIO configured, `ARP_IO_SOURCE=icio` | Division lookup, `isic_code` `26` | Returns `C26`; stub not called | holdout |
| AC-25 | As AC-24 | `isic_code` `62` | Returns `J62_63`; stub not called | holdout |
| AC-26 | As AC-24 | `isic_code` `24` | Returns `None`; stub called once | holdout |
| AC-45 | As AC-24 | `isic_code` `2610` | Returns `None`; stub called once | holdout |
| AC-27 | As AC-24 | `isic_code` `C27` | Returns `C27`; stub not called | holdout |
| AC-28 | `ARP_IO_SOURCE=exiobase`, nothing configured | `resolve_indirect_exposure_model(Settings(), use_sample_icio=True)` | `edition_label` `sample`; `len(codes)` 10; `codes[0]` `07` | holdout |
| AC-46 | `ARP_IO_SOURCE=icio`, nothing configured | `resolve_indirect_exposure_model(Settings(), use_sample_exiobase=True)` | `edition_label` `exiobase-sample`; `len(codes)` 10; `codes[0]` `07` | holdout |
| AC-29 | Nothing configured, `ARP_IO_SOURCE` unset | `resolve_indirect_exposure_model(Settings())` | Returns `None` | holdout |
| AC-30 | Model from `resolve_indirect_exposure_model(Settings(), use_sample_icio=True)` | Division lookup, `isic_code` `27` | Returns `27`; stub not called | holdout |
| AC-31 | `ARP_ICIO_MATRIX_PATH` and `ARP_ICIO_INDUSTRIES_PATH` set to the bundled sample files; nothing else | `arp io status` | Exit 0; stdout is exactly `source: icio`, `edition: sample`, `industries: 10` | holdout |
| AC-52 | Only `ARP_EXIOBASE_FLOWS_PATH` and `ARP_EXIOBASE_INDUSTRIES_PATH` set (fixture E's import output) | `arp io status` | Exit 0; stdout is exactly `source: exiobase`, `edition: exiobase-sample`, `industries: 50` | holdout |
| AC-32 | The real `IOT_2022_ixi.zip` from Zenodo record 23039074 | `arp io import-exiobase IOT_2022_ixi.zip --out <dir>`, then `arp io status` with the printed variables set | Import exits 0 within 15 minutes with peak resident memory at most 1 GB, measured with `/usr/bin/time -v`; stdout line 1 `163 sectors -> 50 industries, 49 regions -> <D>`; status prints `industries: 50`; `D`'s total_output in `industries.csv` is greater than 0 | evaluator |
| AC-33 | AC-32's printed variables set | Division lookup (setup notes) with `isic_code` `27` against the real imported model | Returns `C27`; stub not called | evaluator |
| AC-54 | The real ICIO 2025 regular file `2022_SML.csv` from the OECD ICIO page (the owner supplies it if the OECD site blocks the download) | `arp io import-icio 2022_SML.csv --out <dir>`, then `arp io status` with the printed variables set | Import exits 0; stdout line 1 `50 industries, 81 regions -> <D>`; status prints `industries: 50`; `D`'s and `C26`'s total_output in `industries.csv` are greater than 0 | evaluator |

Must not change: the bundled samples (AC-28, AC-30, AC-46), the `auto` order (AC-18, AC-29,
AC-42), hand-prepared files without `isic_divisions` (AC-31), the default edition labels (AC-31, AC-52), and codes already in the model,
which are used directly (AC-27).

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

The 163 sector names exactly as in `unit.txt` of `IOT_2022_ixi.zip` (3.11.2), in file order,
including EXIOBASE's spelling (`accessoiries`, `preciuos`, `slugde`) and its bracketed ISIC
Rev.3-style codes, which are part of the name. "Re-processing of secondary X" sectors map to the
industry that makes primary X. No sector maps to B09 (mining support services sit inside the extraction sectors), C21
(pharma sits inside "Chemicals nec"), C301 (ships sit inside "other transport equipment"), H53
(post sits inside "Post and telecommunications") or J58T60 (publishing sits inside "Publishing,
printing"). Row 163 has no
ICIO counterpart (ISIC U) and goes to O.

| # | EXIOBASE sector (exact `unit.txt` string) | ICIO |
|---|---|---|
| 1 | Cultivation of paddy rice | A01 |
| 2 | Cultivation of wheat | A01 |
| 3 | Cultivation of cereal grains nec | A01 |
| 4 | Cultivation of vegetables, fruit, nuts | A01 |
| 5 | Cultivation of oil seeds | A01 |
| 6 | Cultivation of sugar cane, sugar beet | A01 |
| 7 | Cultivation of plant-based fibers | A01 |
| 8 | Cultivation of crops nec | A01 |
| 9 | Cattle farming | A01 |
| 10 | Pigs farming | A01 |
| 11 | Poultry farming | A01 |
| 12 | Meat animals nec | A01 |
| 13 | Animal products nec | A01 |
| 14 | Raw milk | A01 |
| 15 | Wool, silk-worm cocoons | A01 |
| 16 | Manure treatment (conventional), storage and land application | A01 |
| 17 | Manure treatment (biogas), storage and land application | A01 |
| 18 | Forestry, logging and related service activities (02) | A02 |
| 19 | Fishing, operating of fish hatcheries and fish farms; service activities incidental to fishing (05) | A03 |
| 20 | Mining of coal and lignite; extraction of peat (10) | B05 |
| 21 | Extraction of crude petroleum and services related to crude oil extraction, excluding surveying | B06 |
| 22 | Extraction of natural gas and services related to natural gas extraction, excluding surveying | B06 |
| 23 | Extraction, liquefaction, and regasification of other petroleum and gaseous materials | B06 |
| 24 | Mining of uranium and thorium ores (12) | B07 |
| 25 | Mining of iron ores | B07 |
| 26 | Mining of copper ores and concentrates | B07 |
| 27 | Mining of nickel ores and concentrates | B07 |
| 28 | Mining of aluminium ores and concentrates | B07 |
| 29 | Mining of precious metal ores and concentrates | B07 |
| 30 | Mining of lead, zinc and tin ores and concentrates | B07 |
| 31 | Mining of other non-ferrous metal ores and concentrates | B07 |
| 32 | Quarrying of stone | B08 |
| 33 | Quarrying of sand and clay | B08 |
| 34 | Mining of chemical and fertilizer minerals, production of salt, other mining and quarrying n.e.c. | B08 |
| 35 | Processing of meat cattle | C10T12 |
| 36 | Processing of meat pigs | C10T12 |
| 37 | Processing of meat poultry | C10T12 |
| 38 | Production of meat products nec | C10T12 |
| 39 | Processing vegetable oils and fats | C10T12 |
| 40 | Processing of dairy products | C10T12 |
| 41 | Processed rice | C10T12 |
| 42 | Sugar refining | C10T12 |
| 43 | Processing of Food products nec | C10T12 |
| 44 | Manufacture of beverages | C10T12 |
| 45 | Manufacture of fish products | C10T12 |
| 46 | Manufacture of tobacco products (16) | C10T12 |
| 47 | Manufacture of textiles (17) | C13T15 |
| 48 | Manufacture of wearing apparel; dressing and dyeing of fur (18) | C13T15 |
| 49 | Tanning and dressing of leather; manufacture of luggage, handbags, saddlery, harness and footwear (19) | C13T15 |
| 50 | Manufacture of wood and of products of wood and cork, except furniture; manufacture of articles of straw and plaiting materials (20) | C16 |
| 51 | Re-processing of secondary wood material into new wood material | C16 |
| 52 | Pulp | C17_18 |
| 53 | Re-processing of secondary paper into new pulp | C17_18 |
| 54 | Paper | C17_18 |
| 55 | Publishing, printing and reproduction of recorded media (22) | C17_18 |
| 56 | Manufacture of coke oven products | C19 |
| 57 | Petroleum Refinery | C19 |
| 58 | Processing of nuclear fuel | C20 |
| 59 | Plastics, basic | C20 |
| 60 | Re-processing of secondary plastic into new plastic | C20 |
| 61 | N-fertiliser | C20 |
| 62 | P- and other fertiliser | C20 |
| 63 | Chemicals nec | C20 |
| 64 | Manufacture of rubber and plastic products (25) | C22 |
| 65 | Manufacture of glass and glass products | C23 |
| 66 | Re-processing of secondary glass into new glass | C23 |
| 67 | Manufacture of ceramic goods | C23 |
| 68 | Manufacture of bricks, tiles and construction products, in baked clay | C23 |
| 69 | Manufacture of cement, lime and plaster | C23 |
| 70 | Re-processing of ash into clinker | C23 |
| 71 | Manufacture of other non-metallic mineral products n.e.c. | C23 |
| 72 | Manufacture of basic iron and steel and of ferro-alloys and first products thereof | C24A |
| 73 | Re-processing of secondary steel into new steel | C24A |
| 74 | Precious metals production | C24B |
| 75 | Re-processing of secondary preciuos metals into new preciuos metals | C24B |
| 76 | Aluminium production | C24B |
| 77 | Re-processing of secondary aluminium into new aluminium | C24B |
| 78 | Lead, zinc and tin production | C24B |
| 79 | Re-processing of secondary lead into new lead, zinc and tin | C24B |
| 80 | Copper production | C24B |
| 81 | Re-processing of secondary copper into new copper | C24B |
| 82 | Other non-ferrous metal production | C24B |
| 83 | Re-processing of secondary other non-ferrous metals into new other non-ferrous metals | C24B |
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
| 94 | Recycling of waste and scrap | E |
| 95 | Recycling of bottles by direct reuse | E |
| 96 | Production of electricity by coal | D |
| 97 | Production of electricity by gas | D |
| 98 | Production of electricity by nuclear | D |
| 99 | Production of electricity by hydro | D |
| 100 | Production of electricity by wind | D |
| 101 | Production of electricity by petroleum and other oil derivatives | D |
| 102 | Production of electricity by biomass and waste | D |
| 103 | Production of electricity by solar photovoltaic | D |
| 104 | Production of electricity by solar thermal | D |
| 105 | Production of electricity by tide, wave, ocean | D |
| 106 | Production of electricity by Geothermal | D |
| 107 | Production of electricity nec | D |
| 108 | Transmission of electricity | D |
| 109 | Distribution and trade of electricity | D |
| 110 | Manufacture of gas; distribution of gaseous fuels through mains | D |
| 111 | Steam and hot water supply | D |
| 112 | Collection, purification and distribution of water (41) | E |
| 113 | Construction (45) | F |
| 114 | Re-processing of secondary construction material into aggregates | B08 |
| 115 | Sale, maintenance, repair of motor vehicles, motor vehicles parts, motorcycles, motor cycles parts and accessoiries | G |
| 116 | Retail sale of automotive fuel | G |
| 117 | Wholesale trade and commission trade, except of motor vehicles and motorcycles (51) | G |
| 118 | Retail trade, except of motor vehicles and motorcycles; repair of personal and household goods (52) | G |
| 119 | Hotels and restaurants (55) | I |
| 120 | Transport via railways | H49 |
| 121 | Other land transport | H49 |
| 122 | Transport via pipelines | H49 |
| 123 | Sea and coastal water transport | H50 |
| 124 | Inland water transport | H50 |
| 125 | Air transport (62) | H51 |
| 126 | Supporting and auxiliary transport activities; activities of travel agencies (63) | H52 |
| 127 | Post and telecommunications (64) | J61 |
| 128 | Financial intermediation, except insurance and pension funding (65) | K |
| 129 | Insurance and pension funding, except compulsory social security (66) | K |
| 130 | Activities auxiliary to financial intermediation (67) | K |
| 131 | Real estate activities (70) | L |
| 132 | Renting of machinery and equipment without operator and of personal and household goods (71) | N |
| 133 | Computer and related activities (72) | J62_63 |
| 134 | Research and development (73) | M |
| 135 | Other business activities (74) | M |
| 136 | Public administration and defence; compulsory social security (75) | O |
| 137 | Education (80) | P |
| 138 | Health and social work (85) | Q |
| 139 | Incineration of waste: Food | E |
| 140 | Incineration of waste: Paper | E |
| 141 | Incineration of waste: Plastic | E |
| 142 | Incineration of waste: Metals and Inert materials | E |
| 143 | Incineration of waste: Textiles | E |
| 144 | Incineration of waste: Wood | E |
| 145 | Incineration of waste: Oil/Hazardous waste | E |
| 146 | Biogasification of food waste, incl. land application | E |
| 147 | Biogasification of paper, incl. land application | E |
| 148 | Biogasification of sewage slugde, incl. land application | E |
| 149 | Composting of food waste, incl. land application | E |
| 150 | Composting of paper and wood, incl. land application | E |
| 151 | Waste water treatment, food | E |
| 152 | Waste water treatment, other | E |
| 153 | Landfill of waste: Food | E |
| 154 | Landfill of waste: Paper | E |
| 155 | Landfill of waste: Plastic | E |
| 156 | Landfill of waste: Inert/metal/hazardous | E |
| 157 | Landfill of waste: Textiles | E |
| 158 | Landfill of waste: Wood | E |
| 159 | Activities of membership organisation n.e.c. (91) | S |
| 160 | Recreational, cultural and sporting activities (92) | R |
| 161 | Other service activities (93) | S |
| 162 | Private households with employed persons (95) | T |
| 163 | Extra-territorial organizations and bodies | O |
