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
