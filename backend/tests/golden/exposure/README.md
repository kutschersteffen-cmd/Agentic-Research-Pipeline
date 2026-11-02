# Exposure golden sets

Company-level labels for theme and risk exposure, one directory per set with a `cases.json`
(format: `docs/superpowers/specs/2026-11-01-exposure-golden-sets-design.md`). Check a set with
`arp golden-set exposure validate --set <dir>`, assign the tune/holdout split with `split`, and count it with `stats`.

## Labelling procedure

1. A research pass proposes label, rationale and sources per company (web, filings).
2. A person checks every label against at least one primary source (filing or company report) and sets
   `checked_on`.
3. Hard cases are kept on purpose: suppliers, buyers and operators, licensors, exited or insolvent makers,
   conglomerates with a small unit.

Tune thresholds on `split: tune` cases only; gate on `split: holdout`.
