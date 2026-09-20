"""Equity index construction: composable screens, selection, weighting,
constraints and the path-dependent decarbonisation layer.

Deliberately zero-LLM and deterministic end to end. Anything model-derived
(thematic relevance, for instance) enters as a frozen, effective-dated
snapshot upstream of this package -- see `docs/EQUITY_INDEX_CONSTRUCTION_PLAN.md`
section 6.4.
"""
