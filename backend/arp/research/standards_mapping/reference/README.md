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

## Licences

UN Statistics Division tables: free to reuse (UN terms of use). Eurostat: reuse allowed with attribution
(Commission Decision 2011/833/EU). US Census Bureau: US public domain.
