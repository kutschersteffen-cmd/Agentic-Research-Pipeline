# Sample input-output data

`icio_matrix.csv` and `industries.csv` are a small, **illustrative** 10-industry
intermediate-flows table over real ISIC Rev.4 division codes, hand-constructed
to have a plausible electrification-relevant value-chain structure (mining ->
chemicals/basic metals -> electrical equipment -> motor vehicles / electricity
supply, with civil engineering, trade, and IT services layered in). The flow
values are illustrative, not real OECD figures.

This exists so the indirect-exposure tier is runnable and testable out of the
box, without a multi-hundred-megabyte download. For production use, replace
these two files with a real extract from the
[OECD Inter-Country Input-Output Tables](https://www.oecd.org/en/data/datasets/inter-country-input-output-tables.html),
aggregated across countries down to industry x industry (see
`docs/METHODOLOGY.md` for the exact format and the aggregation this loader
expects), and point `ARP_ICIO_MATRIX_PATH` / `ARP_ICIO_INDUSTRIES_PATH` at
them.

## Format

`industries.csv`: `isic_code,label,total_output` — one row per industry,
`total_output` is that industry's gross total output (used as the
denominator for technical coefficients).

`icio_matrix.csv`: a square matrix, header row and first column both equal
the industry codes in `industries.csv`, in the same order. Cell `[i, j]` is
the value of intermediate goods/services flowing **from** industry `i` (the
supplier, the row) **to** industry `j` (the user, the column) as an input to
its production.

## EXIOBASE (`exiobase_flows.csv`)

`exiobase_flows.csv` is the **same illustrative economy** as `icio_matrix.csv`,
re-expressed in EXIOBASE's realistic long format: one row per
(supplier industry, user industry, region) flow, rather than a pre-squared
matrix. Concretely, every nonzero cell of `icio_matrix.csv` was split across
two illustrative regions (`EU`, `ROW`) into two rows whose values sum back to
the original cell exactly. This is deliberate: it lets
`load_sample_exiobase()`'s aggregation reproduce `load_sample_icio()`'s matrix
exactly, which proves the group-and-sum aggregation arithmetic in
`exiobase_loader.py` is correct. **It is not a claim about what a real
EXIOBASE extract's region/sector granularity, units, or classification
quality would actually look like** — treat it purely as a correctness-test
fixture, the same way `icio_matrix.csv`'s values are illustrative rather than
real OECD figures.

For production use, point `ARP_EXIOBASE_FLOWS_PATH`/`ARP_EXIOBASE_INDUSTRIES_PATH`
at a real long-format extract from [EXIOBASE](https://www.exiobase.eu/)
(registration required) with columns `supplier_isic_code,user_isic_code,value`
(extra columns, e.g. region, are permitted and summed/collapsed over). **You
must map EXIOBASE's native product/sector classification to ISIC Rev.4
division codes yourself first** — this loader does not attempt that
crosswalk, since EXIOBASE's categories are NACE/CPA-based, not ISIC-based.
`industries.csv`'s `total_output` must likewise already be aggregated across
regions.

## Criticality overlay

`arp/research/indirect_exposure/criticality.py` bundles a small, hand-curated
subset of commodities from the current **USGS 2025 List of Critical Minerals**
(Federal Register 2025-19813, published 2025-11-07 — 60 commodities,
superseding the 2022 list), corroborated for clean-energy relevance by IEA's
*Critical Minerals in Clean Energy Transitions*. Each entry's ISIC-code
association is **this implementation's own categorization of where that
commodity's mining/refining typically falls** — USGS and IEA publish
commodity lists, not an ISIC crosswalk, so that mapping is not itself
sourced from either body. The result (`ActivityDefinition.criticality_flag`,
`IndirectExposureResult.critical_input`) is a coarse, industry-division-level
"plausibly touches a critical-mineral supply chain" signal, not a
per-commodity certification — e.g. ISIC 07 ("Mining of metal ores") also
contains plenty of non-critical ore mining.
