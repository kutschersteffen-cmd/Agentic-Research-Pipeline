`pct_fields_main.json`: the 8 fields `build_taxonomy_schema` produced on `main` (commit 24cb044, before the
stage-evidence change) for the fixture taxonomy `tax_fx` v1 (activities `act_a` "Electrolyser manufacturing",
seed_keywords ["electrolyser"], and `act_b` "Fuel cell manufacturing", seed_keywords []; in-scope text
"<name> in scope."). Dumped with `model_dump(mode="json", exclude={"created_at", "effective_from"})`.
Never edit this file; it guards AC-3 of docs/superpowers/specs/2026-11-03-stage-evidence-schema-design.md.
