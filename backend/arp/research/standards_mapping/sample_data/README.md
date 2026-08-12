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

**⚠ Unverified, best-effort reconstruction from LLM training knowledge --
not sourced from MSCI/S&P's official published structure.** All four
levels (11 sectors, 25 industry groups, 76 industries, 163 sub-industries)
are included, matching the expected shape of the standard, but:

- it was written from memory, not fetched from an authoritative source
  (this environment's network egress is blocked for general web access,
  so it couldn't be cross-checked against MSCI's live GICS structure page
  at build time);
- GICS has been revised more than once (2016 Real Estate split, 2018
  creation of Communication Services, a 2023 restructuring touching parts
  of Real Estate, Financial Services, and Consumer sectors) -- this file
  most likely reflects a ~2021-2022 vintage and may be missing later
  renames/reclassifications;
- individual codes or labels may simply be wrong at the sub-industry
  level, where MSCI/S&P's licensed structure has ~163 entries to get
  exactly right.

The 11 top-level sector codes/names are stable, public, and high-
confidence; treat anything below sector level here as a **draft
approximation for testing the mapping pipeline, not a citable
classification**. For any real use, verify against MSCI's current
published GICS structure (or your Bloomberg/FactSet/MSCI subscription)
and supply the corrected/current file via `ARP_GICS_REFERENCE_PATH` --
that path always wins over this bundled sample (see `mapper.py::
_resolve_table_path`), and GICS Industry Group/Industry/Sub-Industry
codes are MSCI/S&P-licensed, so redistributing a verified copy here
still isn't appropriate even once corrected.

## Format

All three crosswalk files: `isic_code,target_code,target_label` -- one row
per correspondence (an ISIC code may map to more than one target code and
vice versa; join is done via `CrosswalkTable.lookup`, which also matches by
digit-prefix so a coarser or finer taxonomy ISIC code still resolves).

`gics_reference_sample.csv`: `code,label,level` -- `level` is one of
`sector`, `industry_group`, `industry`, `sub_industry`.
