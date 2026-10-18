# Transition-plan number rules (first set)

Date: 2026-10-18
Status: approved by the owner 2026-10-18 (description and acceptance table)
Builds on: `docs/superpowers/specs/2026-10-17-schema-rules-design.md` (merged in #169)

## Intent

The transition-plan preset (`backend/arp/presets/transition_plan.py`) turns the 64 indicator questions
into boolean fields. The AI says YES too easily on questions with a number in them. Using the schema
rules from #169, the preset gets fixed rules (written once, in code) that flag a YES for review when
the numbers the AI found contradict it. The owner chose the strongest rules only:

- **A_ambition_5:** "cut absolute GHG emissions by 50% until 2030 at the latest"
- **A_progress_67/68/69:** "absolute scope 1/2/3 emissions for the past 5 years"
- **A_progress_70/71/72:** "decline in scope 1/2/3 emission intensity for the past 5 years"

## Goals

1. The preset gains 8 helper fields that extract the numbers the rules need.
2. Seven question fields gain one rule each. A failed rule flags the value for review and never
   changes it (the #169 behaviour).
3. The seven changed question fields move to version 2, so a released version 1 is never overwritten.

## Non-goals

- Rules for the other questions (net zero by 2050, past-year emissions, combined-scope targets, the
  #147 dependency links, A_progress_66). The owner deferred them.
- Any change to the dedicated pipeline under `backend/arp/transition_plan/`, other than reading its
  unchanged indicator data.
- Any change to the rule engine itself.

## Design

### Helper fields

Added after the 64 question fields. All have `required=False`, `high_risk=False` (so they can be
grouped into shared calls), version 1 and `seed_keywords` as listed. "none" in the unit column means
`unit=None`. Extraction quality of the helpers is not an acceptance criterion: model output varies,
and every flag goes to a reviewer.

| field_id | name | data_type | unit | extraction_instructions (summary; builder writes the full text) | seed_keywords |
|---|---|---|---|---|---|
| `tp_h_target_pct` | Absolute target reduction | percentage | `%` | The percentage cut of the company's absolute GHG reduction target whose target year is nearest to and not after 2030; if there is none, the absolute target with the nearest year. Intensity targets never count. Copy the number as printed. | absolute target, reduction target, GHG reduction, emissions reduction, % reduction, 2030 target |
| `tp_h_target_year` | Absolute target year | number | none | The target year of that same target, as a four-digit year. | target year, by 2030, 2030, reduction target, baseline |
| `tp_h_scope1_emissions` | Scope 1 emissions | number | `tCO2e` | Absolute scope 1 GHG emissions, one value per reported fiscal year. | scope 1, direct emissions, GHG emissions, tCO2e, emissions table |
| `tp_h_scope2_emissions` | Scope 2 emissions | number | `tCO2e` | Absolute scope 2 GHG emissions, one value per reported fiscal year; market-based where both are given. | scope 2, indirect emissions, market-based, location-based, tCO2e |
| `tp_h_scope3_emissions` | Scope 3 emissions | number | `tCO2e` | Absolute scope 3 GHG emissions (total), one value per reported fiscal year. | scope 3, value chain emissions, indirect emissions, tCO2e |
| `tp_h_scope1_intensity` | Scope 1 intensity | number | none | Scope 1 GHG emission intensity, one value per reported fiscal year, in the company's own intensity unit (copied as printed). | emission intensity, scope 1 intensity, tCO2e per, intensity |
| `tp_h_scope2_intensity` | Scope 2 intensity | number | none | The same for scope 2. | emission intensity, scope 2 intensity, tCO2e per, intensity |
| `tp_h_scope3_intensity` | Scope 3 intensity | number | none | The same for scope 3. | emission intensity, scope 3 intensity, tCO2e per, intensity |

### Rules

All seven have `when: true`.

| Field (question) | rule_id | Rule |
|---|---|---|
| `tp_a_ambition_5` | `tp_r_ambition_5` | threshold: `tp_h_target_pct >= 50` and `tp_h_target_year <= 2030` |
| `tp_a_progress_67` | `tp_r_progress_67` | series: `tp_h_scope1_emissions`, years 5, trend none |
| `tp_a_progress_68` | `tp_r_progress_68` | series: `tp_h_scope2_emissions`, years 5, trend none |
| `tp_a_progress_69` | `tp_r_progress_69` | series: `tp_h_scope3_emissions`, years 5, trend none |
| `tp_a_progress_70` | `tp_r_progress_70` | series: `tp_h_scope1_intensity`, years 5, trend down |
| `tp_a_progress_71` | `tp_r_progress_71` | series: `tp_h_scope2_intensity`, years 5, trend down |
| `tp_a_progress_72` | `tp_r_progress_72` | series: `tp_h_scope3_intensity`, years 5, trend down |

### Versions

The seven fields above move to version 2 through the preset's existing `_VERSIONS` map, which already
holds `A_coverage_6: 2`. All other fields keep their current version.

### Known limits (stated, not fixed)

- A 5-year series is found only when the report states those years: the period plan looks back at
  most 4 years before the report year (`planning/periods.py` `MAX_COMPARATIVES`).
- A YES whose numbers are not found is flagged too, so review work may rise at first.

## Acceptance

Rows build the preset with `build_transition_plan_schema()`. Evaluation rows run the preset's fields
through `check_record` and `route()` (as in `backend/tests/test_rules_evaluation.py`), with every
extracted row found and grounded and a current reporting year of 2024. Single-period rows (the
question fields, `tp_h_target_pct`, `tp_h_target_year`) have no `period_end`. Series rows have
`period_end` 31 December of their year and share one `canonical_unit` unless the row says otherwise.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The preset | it is built | it has 72 fields: the 64 question fields, then the 8 helper fields in the table's order, with exactly the field_id, name, data_type, unit (`None` where the table says none) and seed_keywords listed | unit |
| AC-2 | The preset | it is built | every helper field has `required` false and `high_risk` false | unit |
| AC-3 | The preset | it is built | each of the seven fields in the Rules table has exactly one rule, with that rule_id, kind, `when` true and parameters | unit |
| AC-16 | The preset | it is built | every field other than those seven has an empty `rules` list | unit |
| AC-4 | The preset | it is built | the seven rule-carrying fields have version 2; the 57 other question fields have the version they have on `main` (`tp_a_coverage_6` 2, all others 1); the 8 helper fields have version 1 | unit |
| AC-5 | The preset as JSON | it is POSTed to `/api/extraction/schemas` | status 200 | unit |
| AC-6 | `tp_a_ambition_5`=true, `tp_h_target_pct`=42, `tp_h_target_year`=2030 | checks and routing finish | `tp_a_ambition_5` has `rule.tp_r_ambition_5` with `outcome` `fail` | unit |
| AC-17 | As AC-6 | checks and routing finish | `tp_a_ambition_5`'s `route` is `review` and its `route_reasons` include `check:rule.tp_r_ambition_5` | unit |
| AC-7 | As AC-6 but `tp_h_target_pct`=55 | checks and routing finish | `rule.tp_r_ambition_5` has `outcome` `pass` | unit |
| AC-8 | As AC-6 but `tp_h_target_year`=2035 and `tp_h_target_pct`=55 | checks and routing finish | `rule.tp_r_ambition_5` has `outcome` `fail` | unit |
| AC-9 | `tp_a_progress_67`=true, `tp_h_scope1_emissions` found for each year 2020–2024, all rows `canonical_unit` `tCO2e` | checks and routing finish | `rule.tp_r_progress_67` has `outcome` `pass` | unit |
| AC-10 | As AC-9 but no 2022 row | checks and routing finish | `rule.tp_r_progress_67` has `outcome` `fail` | unit |
| AC-11 | `tp_a_progress_70`=true, `tp_h_scope1_intensity` found for 2020–2024, 2024 value below 2020 value, all rows with the same `canonical_unit` | checks and routing finish | `rule.tp_r_progress_70` has `outcome` `pass` | unit |
| AC-12 | As AC-11 but the 2024 value is above the 2020 value | checks and routing finish | `rule.tp_r_progress_70` has `outcome` `fail` | unit |
| AC-13 | `tp_a_progress_70`=false | checks and routing finish | `rule.tp_r_progress_70` has `outcome` `not_applicable` | unit |
| AC-14 | Must not change: a snapshot of the 64 question fields captured on `main` (85b6985) and committed as a fixture | the preset is built on this branch | the first 64 fields' field_id, order, name, description, data_type, unit, allowed_values, extraction_instructions, seed_keywords, required, high_risk, check_config and derived_rule equal the snapshot | unit |
| AC-18 | `main`'s preset (all question fields at their `main` versions) saved and released through the schema registry | this branch's preset is POSTed to `/api/extraction/schemas` | status 200 | unit |
| AC-19 | As AC-18, but this branch's preset with `tp_a_progress_67` left at version 1 | it is POSTed to `/api/extraction/schemas` | status 400, and the body contains `changing it needs` | unit |
| AC-15 | Must not change: the PR's diff | `git diff --name-only origin/main...HEAD` runs | it lists no path under `backend/arp/transition_plan/` | evaluator |

`unit` rows are owed as `holdout` until `HOLDOUT_TOKEN` is confirmed set.
