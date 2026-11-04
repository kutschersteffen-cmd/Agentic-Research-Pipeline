# Official classification correspondence tables

Unmodified official tables, converted to CSV where the source was Excel. Nothing in the code reads them yet;
they are the source data for linking companies' NACE/ISIC codes to EXIOBASE sectors.
Downloaded 2026-11-02.

| File | Maps | Publisher | Source |
|---|---|---|---|
| `un_isic4_nace2.csv` | ISIC Rev.4 → NACE Rev.2 | UN Statistics Division | https://unstats.un.org/unsd/classifications/Econ/tables/ISIC/ISIC4_NACE2/ISIC4_NACE2.txt |
| `un_nace2_isic4.csv` | NACE Rev.2 → ISIC Rev.4 | UN Statistics Division | https://unstats.un.org/unsd/classifications/Econ/tables/ISIC/NACE2_ISIC4/NACE2_ISIC4.txt |
| `un_isic31_isic4.csv` | ISIC Rev.3.1 → ISIC Rev.4 | UN Statistics Division | https://unstats.un.org/unsd/classifications/Econ/tables/ISIC/ISIC31_ISIC4/ISIC31_ISIC4.txt |
| `un_isic31_nace11.csv` | ISIC Rev.3.1 → NACE Rev.1.1 | UN Statistics Division | https://unstats.un.org/unsd/classifications/Econ/tables/ISIC/ISIC31_NACE11/ISIC31-NACE11.txt |
| `census_isic4_naics2017.csv` | ISIC Rev.4 → NAICS 2017 (US) | US Census Bureau, distributed by UNSD | https://unstats.un.org/unsd/classifications/Econ/tables/ISIC/ISIC4-NAICS2017US.zip |
| `eurostat_nace2_nace21.csv` | NACE Rev.2 → NACE Rev.2.1 (v1.05) | Eurostat, copy hosted by CSO Ireland | https://www.cso.ie/en/media/csoie/methods/cars/CorresTab_NACE_Rev.2-NACE_Rev.2.1-TypeCorres_V1.05_(1).xlsx (Eurostat's own copy: ShowVoc, NACE 2.1 dataset) |

## Reading the UN files

`*part` columns: `1` means only part of that code maps to the code on the other side, `0` means all of it.
Codes appear at every level (section letter, 2-digit division, 3-digit group, 4-digit class); filter on code
length for one level. NACE codes keep their dot (`35.11`), ISIC codes don't (`3510`).

## Not included, and why

- ISIC Rev.4 ↔ Rev.5 and NAICS 2022: no official table found on UNSD; census.gov was unreachable.
- GICS, ICB, TRBC, BICS: proprietary, no official correspondence to any statistical classification exists.
- EXIOBASE ↔ NACE Rev.2: no official table; the best available is BONSAI's `exiobase2_to_NACE2008.csv`
  (https://github.com/BONSAMURAIS/correspondence_tables, BSD-3, marked incomplete by its authors).

## EXIOBASE sector table (`indirect_exposure/reference/exiobase_nace.csv`)

Built from BONSAI `exiobase2_to_NACE2008.csv` (BSD-3) for `nace2_code`, matched to the 163 EXIOBASE 3 sectors by code, then
the Eurostat table above for `nace21_code`. One row per (sector, Rev. 2 code, Rev. 2.1 code). Rev. 2.1 targets in another
division than the Rev. 2 code are dropped unless they are the only target. BONSAI codes missing a leading zero (`5`) are padded.
BONSAI's EXIOBASE 2 waste codes `i90.*` are shifted by one against EXIOBASE 3, so those sectors were matched by name.

### Hand-made rows (sector missing or empty in BONSAI)

| Sector | NACE Rev. 2 | Reason |
|---|---|---|
| Manure treatment (conventional), storage and land application | 01.62 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Manure treatment (biogas), storage and land application | 01.62 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary wood material into new wood material | 16 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary paper into new pulp | 17.11 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Plastics, basic | 20.16 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary plastic into new plastic | 20.16 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| N-fertiliser | 20.15 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| P- and other fertiliser | 20.15 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Chemicals nec | 20 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary glass into new glass | 23.1 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of ash into clinker | 23.5 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary steel into new steel | 24.1,24.2,24.3 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary preciuos metals into new preciuos metals | 24.41 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary aluminium into new aluminium | 24.42 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary lead into new lead, zinc and tin | 24.43 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary copper into new copper | 24.44 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary other non-ferrous metals into new other non-ferrous metals | 24.45 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Recycling of waste and scrap | 38.32 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Recycling of bottles by direct reuse | 38.32 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Re-processing of secondary construction material into aggregates | 38.32 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Computer and related activities (72) | 62,63.1 | missing, empty or N/A in BONSAI; filled from the sector and NACE titles |
| Biogasification of food waste, incl. land application | 38.21 | EXIOBASE 3 code absent in BONSAI; taken from the same-named BONSAI row |
| Biogasification of paper, incl. land application | 38.21 | EXIOBASE 3 code absent in BONSAI; taken from the same-named BONSAI row |
| Biogasification of sewage slugde, incl. land application | 38.21 | EXIOBASE 3 code absent in BONSAI; taken from the same-named BONSAI row |
| Landfill of waste: Plastic | 38.21 | EXIOBASE 3 code absent in BONSAI; taken from the same-named BONSAI row |
| Landfill of waste: Inert/metal/hazardous | 38.22 | EXIOBASE 3 code absent in BONSAI; taken from the same-named BONSAI row |
| Landfill of waste: Textiles | 38.21 | EXIOBASE 3 code absent in BONSAI; taken from the same-named BONSAI row |
| Landfill of waste: Wood | 38.21 | EXIOBASE 3 code absent in BONSAI; taken from the same-named BONSAI row |

### Electricity split (BONSAI sends all of `i40.11.*` to 35.11)

| Sector | NACE Rev. 2.1 |
|---|---|
| Production of electricity by coal | 35.11 (non-renewable) |
| Production of electricity by gas | 35.11 (non-renewable) |
| Production of electricity by nuclear | 35.11 (non-renewable) |
| Production of electricity by hydro | 35.12 (renewable) |
| Production of electricity by wind | 35.12 (renewable) |
| Production of electricity by petroleum and other oil derivatives | 35.11 (non-renewable) |
| Production of electricity by biomass and waste | 35.12 (renewable) |
| Production of electricity by solar photovoltaic | 35.12 (renewable) |
| Production of electricity by solar thermal | 35.12 (renewable) |
| Production of electricity by tide, wave, ocean | 35.12 (renewable) |
| Production of electricity by Geothermal | 35.12 (renewable) |
| Production of electricity nec | 35.11 (non-renewable) |

### Dropped cross-division Rev. 2.1 targets

| Sector | NACE Rev. 2 | Dropped Rev. 2.1 |
|---|---|---|
| Fishing, operating of fish hatcheries and fish farms; service activities incidental to fishing (05) | 03 | 01 |
| Processing of Food products nec | 10.89 | 11.07 |
| Manufacture of textiles (17) | 13 | 23 |
| Manufacture of wood and of products of wood and cork, except furniture; manufacture of articles of straw and plaiting materials (20) | 16 | 15 |
| Re-processing of secondary wood material into new wood material | 16 | 15 |
| Publishing, printing and reproduction of recorded media (22) | 18 | 13 |
| Manufacture of rubber and plastic products (25) | 22 | 15, 23 |
| Manufacture of glass and glass products | 23.1 | 29.3 |
| Re-processing of secondary glass into new glass | 23.1 | 29.3 |
| Manufacture of ceramic goods | 23.4 | 31.0 |
| Manufacture of fabricated metal products, except machinery and equipment (28) | 25 | 28 |
| Manufacture of machinery and equipment n.e.c. (29) | 28.1 | 29.3, 30.9 |
| Manufacture of machinery and equipment n.e.c. (29) | 28.11 | 29.32, 30.91 |
| Manufacture of machinery and equipment n.e.c. (29) | 28.2 | 26.2, 29.3 |
| Manufacture of machinery and equipment n.e.c. (29) | 28.25 | 29.32 |
| Manufacture of machinery and equipment n.e.c. (29) | 28.4 | 27.9 |
| Manufacture of machinery and equipment n.e.c. (29) | 28.49 | 27.90 |
| Manufacture of office machinery and computers (30) | 28.23 | 26.20 |
| Manufacture of electrical machinery and apparatus n.e.c. (31) | 27 | 29, 32 |
| Manufacture of medical, precision and optical instruments, watches and clocks (33) | 32.5 | 26.6 |
| Manufacture of other transport equipment (35) | 30 | 33 |
| Recycling of waste and scrap | 38.32 | 20.16 |
| Recycling of bottles by direct reuse | 38.32 | 20.16 |
| Construction (45) | 41 | 43, 68, 91 |
| Re-processing of secondary construction material into aggregates | 38.32 | 20.16 |
| Retail trade, except of motor vehicles and motorcycles; repair of personal and household goods (52) | 47.9 | 60.3 |
| Other land transport | 49.3 | 52.3 |
| Supporting and auxiliary transport activities; activities of travel agencies (63) | 52 | 35, 63 |
| Supporting and auxiliary transport activities; activities of travel agencies (63) | 79 | 52, 55, 56, 77, 82 |
| Real estate activities (70) | 68 | 55 |
| Computer and related activities (72) | 63.1 | 60.2, 60.3 |
| Other business activities (74) | 70 | 73 |
| Other business activities (74) | 74 | 18, 80 |
| Other business activities (74) | 81 | 96 |
| Other business activities (74) | 82 | 18, 43, 46, 47, 95, 53, 61, 77, 85, 86, 87, 93, 96 |
| Education (80) | 85 | 93 |
| Health and social work (85) | 88 | 85 |
| Recreational, cultural and sporting activities (92) | 90 | 91 |
| Recreational, cultural and sporting activities (92) | 93 | 84 |
| Other service activities (93) | 96 | 53 |

## Licences

UN Statistics Division tables: free to reuse (UN terms of use). Eurostat: reuse allowed with attribution
(Commission Decision 2011/833/EU). US Census Bureau: US public domain.
