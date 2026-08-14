# Transition Barrier Assessment — Automation Pipeline

Start here: **`CLAUDE.md`** has the full context for Claude Code (data
schemas, source access patterns, build order, non-negotiable rules). This
README is just a map.

## Layout

```
data/
  criteria_schema.json     35 criteria (9 sectors x Technology/Regulation/Demand)
  assessment_scores.json   105 current ratings (35 criteria x 3 regions)
  source_registry.json     86 sources, deduplicated, with url/locator/access_pattern

docs/
  Transition_Barrier_Assessment.xlsx    the working research tool (Excel)
  Transition_Barrier_Assessment.docx    criteria + ratings, prose version
  Automation_Pipeline_Design.docx       the architecture this code implements

scripts/
  investigate_structured_sources.py     step 1: what can actually be automated
                                         without an LLM, for the 7 sources
                                         tagged structured_api_or_dashboard
```

## First thing to run

```bash
python3 scripts/investigate_structured_sources.py --selftest
```

This checks whether your environment has real outbound internet access
before trusting anything else. If it fails, read the script's docstring —
this happened during initial drafting (sandboxed environment, every request
including to example.com returned 403) and produced misleading results until
the self-test was added. Don't skip this step in a new environment.

If the self-test passes:

```bash
python3 scripts/investigate_structured_sources.py
```

This probes all 7 structured/dashboard sources and reports which ones have
a real machine-readable endpoint vs. which ones just look structured but
actually need an LLM-assisted read. That result should drive what gets built
next — see CLAUDE.md's build order.

## What's already true, so you don't re-derive it

- All 105 assessment cells are complete and cross-validated against the
  35-criteria schema (no gaps, no orphans).
- 88 of 95 source entries across the schema carry a verified `url` +
  `locator` (checked by hand against each primary publisher, Aug 2026).
- Two ratings changed during that verification because US federal policy
  reversed in 2025 (see `assessment_scores.json` → `source_verification`
  → `material_corrections_note`). That's the strongest argument in this
  whole project for why automation matters: a policy reversal like that
  won't be caught by re-fetching the same government page — it needs a
  distinct "did the underlying policy change" search step, not just a
  refresh.
