# Sample standards-mapping reference data

These four files exist so `arp taxonomy map-standards --use-sample-standards`
is runnable out of the box, without any external download -- **they are not
authoritative correspondence tables**, and cover only the 10 ISIC Rev.4
divisions in the bundled sample ICIO dataset
(`arp/research/indirect_exposure/sample_data/industries.csv`).

## `isic_nace_sample.csv` (ISIC Rev.4 -> NACE Rev.2)

At the 2-digit division level, NACE Rev.2 was designed to align exactly
with ISIC Rev.4 -- same codes, essentially the same titles -- so this file
is a near-exact (not illustrative-only) correspondence at division level.
NACE diverges from ISIC below the division level (group/class); for
production use with finer-grained activities, replace this with the full
official [Eurostat RAMON correspondence table](https://ec.europa.eu/eurostat/ramon/).

## `isic_naics_sample.csv` / `isic_sic_sample.csv` (ISIC Rev.4 -> NAICS / SIC)

High-level, illustrative correspondences only -- NAICS and SIC don't align
numerically with ISIC at all, so these are hand-picked single best-match
codes per division, not an exhaustive crosswalk. For production use,
replace with the official
[US Census Bureau ISIC/NAICS correspondence tables](https://www.census.gov/naics/)
and a published ISIC-SIC crosswalk.

## `gics_reference_sample.csv` (GICS reference list)

Sector level only (the 11 GICS sectors, stable since the 2018 revision) --
GICS Industry Group/Industry/Sub-Industry codes are part of the licensed
MSCI/S&P GICS structure and aren't redistributed here. Activities are
LLM-classified against whatever reference list is loaded
(`gics.py::classify_gics`), so with only this sample loaded, GICS mapping
tops out at sector-level granularity. Supply your own licensed
`code,label,level` GICS file via `ARP_GICS_REFERENCE_PATH` for
industry/sub-industry-level classification.

## Format

All three crosswalk files: `isic_code,target_code,target_label` -- one row
per correspondence (an ISIC code may map to more than one target code and
vice versa; join is done via `CrosswalkTable.lookup`, which also matches by
digit-prefix so a coarser or finer taxonomy ISIC code still resolves).

`gics_reference_sample.csv`: `code,label,level` -- `level` is one of
`sector`, `industry_group`, `industry`, `sub_industry`.
