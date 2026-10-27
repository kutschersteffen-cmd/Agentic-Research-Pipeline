# Sample input-output model

This directory is one `arp io build-full` output, edition `sample`: the same
files the indirect-exposure tier and the Value Chain Explorer read from
`ARP_VALUE_CHAIN_DIR` (`manifest.json`, `nodes.csv`, `A.npy`, `L.npy`,
`G.npy`, `Y.npy`, `y_columns.csv`). **Every value is illustrative**, not an
EXIOBASE figure. It exists so the tier is runnable and testable out of the box
(`--use-sample-io`, or `use_sample_io` in the API) without the ~800 MB EXIOBASE
download.

It has 4 regions (`DE`, `CN`, `US`, `WA`) and 8 EXIOBASE sectors: copper ore
mining, copper production, wind and coal electricity, electrical machinery,
motor vehicles, construction and retail trade -- 32 nodes, every one with
output, plus final demand. The flows follow a plausible electrification value
chain (mining -> copper -> electrical machinery -> vehicles and construction,
with power feeding every sector) and some imports from `CN` and `WA`.

`backend/scripts/make_io_sample.py` writes the archive it was built from:

```
python scripts/make_io_sample.py /tmp/IOT_sample_ixi.zip
arp io build-full /tmp/IOT_sample_ixi.zip --out arp/research/indirect_exposure/sample_data --label sample
```

(`build-full` replaces the directory, so copy this README back afterwards.)

For a real run, build the real table instead and point the tier at it:
`arp io build-full IOT_2022_ixi.zip --out <dir>`, then `ARP_VALUE_CHAIN_DIR=<dir>`.
See `docs/METHODOLOGY.md` for how the tier reads the build.

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
