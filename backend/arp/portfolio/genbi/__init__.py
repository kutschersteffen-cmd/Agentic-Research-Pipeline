"""Generative BI for portfolio risk monitoring.

A plain-language brief ("show me where the climate risk sits in the
sustainable fund") becomes a whole dashboard rather than a single answer:

    brief -> planner (LLM: which queries) -> executor (deterministic: the
    numbers) -> observations (deterministic: the facts worth stating) ->
    narrator (LLM: prose, then checked back against those facts)

The split is the point. A model chooses what to look at and how to phrase
what was found; it never produces a figure. Every number on the dashboard
comes from `portfolio/aggregation.py` via `portfolio/analytics.py` -- the
same engine the Explore and Pivot tabs use -- and every number in the prose
is mechanically checked against the computed facts before it is shown
(`narrator.check_grounding`), the numeric counterpart of the citation
grounding used everywhere else in this codebase.

What persists is the `DashboardSpec`, not the narrative: a generated
dashboard is a re-runnable report definition (`service.run_dashboard`
executes it with no LLM at all), not a one-off prompt.
"""
