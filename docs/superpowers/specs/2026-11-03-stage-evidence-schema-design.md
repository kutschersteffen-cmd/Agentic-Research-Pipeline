# Stage evidence in the taxonomy schema

Spec slug: `stage-evidence-schema`. Status: draft, for owner approval.

## Why

The extraction schema generated from a ratified taxonomy version (`research/taxonomy_schema.py`) has four
percentage fields per activity (revenue, CapEx, OpEx, R&D share). Companies at an early stage of an activity rarely
state a percentage; they write "€40m invested in a stack factory", "pilot plant commissioned", "300 MW backlog" or
"partnership with X". Those companies come out with no exposure. The stage cannot be set in the taxonomy in
advance: it differs by company (owner, 2026-11-03), and one company can be at two stages of the same activity at
once (keep both).

## Goals

1. Every activity in the generated schema gets, next to the four existing percentage fields, evidence fields that
   do not need a percentage, and three yes/no stage-evidence fields.
2. The stage is extracted per company and activity from cited evidence, never preset. Two stages can both be true.
3. Each new field has its own description, extraction guidance and keywords; the guidance keeps the existing
   rules (explicitly stated only, never estimated, a verified quote).

## Non-goals

- Patents (owner, 2026-11-03).
- A list or record data type in the extraction engine (option 2, not chosen). Lists are stored as text.
- Scoring or combining the fields into an exposure estimate, and any change to the theme-run output.
- Changing the funnel (the A2 session reads the schema's keywords; PR #331).
- Changing schemas already registered or released.

## Anti-goals

- A stage field set to true without a quote.
- Any field value that is estimated or computed from unrelated totals.
- A change to the field ids, names or texts of the four existing percentage fields.

## Design

### Fields per activity

`build_taxonomy_schema` emits, per activity and in this order, the four existing fields followed by these 12:

| Key | Name suffix | Data type | Unit / allowed values |
|---|---|---|---|
| `revenue_amount` | revenue amount | `currency_amount` | — |
| `capex_amount` | CapEx / investment amount | `currency_amount` | — |
| `rd_amount` | R&D spend amount | `currency_amount` | — |
| `rd_programme` | named R&D programme | `string` | — |
| `milestone` | most advanced development milestone | `enum` | `lab`, `pilot`, `demonstration`, `first_commercial`, `series_production` |
| `capacity` | installed or planned capacity | `number` | unit as stated, kept in `raw_value_text` |
| `backlog` | orders / backlog | `currency_amount` | — |
| `partnerships` | partnerships, grants, offtake agreements | `string` | — |
| `news_momentum` | recent momentum events | `string` | — |
| `stage_ideation` | ideation-stage evidence | `boolean` | — |
| `stage_innovation` | innovation-stage evidence | `boolean` | — |
| `stage_commercial` | commercial-stage evidence | `boolean` | — |

Field id: `{taxonomy_id}_{activity_id}_{key}`. The four existing ids keep their `_pct` suffix
(`{taxonomy_id}_{activity_id}_{metric}_pct`) unchanged. Field name: `{activity.name}: {name suffix}`. All new
fields are `required=False` and carry `version=taxonomy.version`, like the existing ones.

### Guidance

Every new field's `extraction_instructions` starts with the shared rule: "Extract only what the company explicitly
states about this specific activity, with a verbatim quote. Never estimate, infer or compute a value." Then the
field-specific text, fixed in the code as a constant per key:

- **revenue_amount / capex_amount / rd_amount / backlog:** the stated amount for this activity, with currency and
  fiscal year in `raw_value_text`; company-wide totals do not count.
- **rd_programme:** the name and one-line purpose of an R&D programme, project or research focus tied to this
  activity.
- **milestone:** the most advanced stage the company states it has reached: `lab` (research, prototype,
  proof of concept), `pilot` (pilot plant or line), `demonstration` (demonstrator, field test at scale),
  `first_commercial` (first commercial unit, first customer delivery, FID), `series_production` (serial
  manufacturing, ongoing sales).
- **capacity:** installed or planned capacity for this activity, with its unit and whether installed or planned.
- **partnerships:** each stated partnership, grant or offtake agreement for this activity, separated by `; `.
- **news_momentum:** each stated recent event for this activity (launch, partnership, investment, expansion,
  order), with its date, separated by `; `. From the documents given, not from web search.
- **stage_ideation:** true only if a quote shows research, prototype, lab-scale or proof-of-concept work on this
  activity.
- **stage_innovation:** true only if a quote shows a pilot, demonstrator, first commercial unit, pre-series
  production or a first order.
- **stage_commercial:** true only if a quote shows ongoing sales, segment revenue, series production or a market
  position.

Several stage fields can be true for the same company and activity.

### Keywords

Each new field's `seed_keywords` = `activity.seed_keywords` + that field's list, fixed in the code:

| Key | Field keywords |
|---|---|
| revenue_amount | revenue, sales, turnover |
| capex_amount | capital expenditure, capex, investment, invested |
| rd_amount | research and development, R&D, R&D expenses |
| rd_programme | research programme, research project, development programme |
| milestone | prototype, pilot, demonstrator, first commercial, series production |
| capacity | capacity, MW, GW, production line, plant |
| backlog | order backlog, order intake, orders |
| partnerships | partnership, joint venture, grant, offtake, agreement |
| news_momentum | launched, announced, signed, expanded, commissioned |
| stage_ideation | research programme, prototype, lab-scale, proof of concept |
| stage_innovation | pilot plant, demonstrator, first commercial, pre-series, order, FID |
| stage_commercial | segment revenue, series production, capacity, backlog, market share |

### Existing schemas

`build_taxonomy_schema` stays pure: the same taxonomy version gives the same schema. Schemas already registered are
not touched. `GET /taxonomies/{id}/versions/{v}/schema` keeps returning the registered schema. Calling
`POST /taxonomies/{id}/versions/{v}/schema` again after this change registers a new registry version with the new
fields, because the content differs; it must be released before a theme run accepts it (the existing gate in
`released_run_schema`).

### Capacity unit

`capacity` has `unit=None`; the guidance asks for the unit in `raw_value_text`.

## Approaches considered

1. **Flat fields in the existing schema (chosen by the owner):** only `taxonomy_schema.py` changes; lists stored as
   text.
2. A list data type in the extraction engine: real lists, but changes `arp/extraction`, grounding, review and
   storage.
3. A separate evidence schema: two schemas to release per taxonomy version.

## Acceptance

Rows are `unit` until `HOLDOUT_TOKEN` is set; the PR lists them as owed to `holdout`. "The fixture taxonomy" is a
ratified taxonomy `tax_fx` v1 with activities `act_a` ("Electrolyser manufacturing", seed_keywords
["electrolyser"]) and `act_b` ("Fuel cell manufacturing", seed_keywords []), in that order.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The fixture taxonomy | `build_taxonomy_schema` | `len(schema.fields) == 32` | unit |
| AC-2 | As AC-1 | build | Fields 0–15 have ids `tax_fx_act_a_revenue_pct, tax_fx_act_a_capex_pct, tax_fx_act_a_opex_pct, tax_fx_act_a_rd_pct, tax_fx_act_a_revenue_amount, tax_fx_act_a_capex_amount, tax_fx_act_a_rd_amount, tax_fx_act_a_rd_programme, tax_fx_act_a_milestone, tax_fx_act_a_capacity, tax_fx_act_a_backlog, tax_fx_act_a_partnerships, tax_fx_act_a_news_momentum, tax_fx_act_a_stage_ideation, tax_fx_act_a_stage_innovation, tax_fx_act_a_stage_commercial` in this order; fields 16–31 the same for `act_b` | unit |
| AC-3 | As AC-1 | build | The 4 `_pct` fields of each activity equal, in every attribute, `tests/fixtures/stage_evidence/pct_fields_main.json`, which is generated by running `build_taxonomy_schema` from `origin/main` on the fixture taxonomy in the first commit of the PR, before any code change; the file is only added, never edited, in the PR | unit |
| AC-4a | As AC-1 | build | `revenue_amount`, `capex_amount`, `rd_amount`, `backlog` have `data_type == currency_amount` | unit |
| AC-4b | As AC-1 | build | `rd_programme`, `partnerships`, `news_momentum` have `data_type == string` | unit |
| AC-4c | As AC-1 | build | `milestone` has `data_type == enum` | unit |
| AC-4d | As AC-1 | build | `capacity` has `data_type == number` and `unit is None` | unit |
| AC-4e | As AC-1 | build | `stage_ideation`, `stage_innovation`, `stage_commercial` have `data_type == boolean` | unit |
| AC-5 | As AC-1 | build | `milestone.allowed_values == ["lab", "pilot", "demonstration", "first_commercial", "series_production"]` | unit |
| AC-6 | As AC-1 | build | Every new field's `extraction_instructions` starts with "Extract only what the company explicitly states about this specific activity, with a verbatim quote. Never estimate, infer or compute a value." | unit |
| AC-6b | As AC-1 | build | For each of the 12 keys, the instructions after the prefix equal the literal text for that key in this spec's Guidance section, written out in the test (not read from code constants) | unit |
| AC-7 | As AC-1 | build | For each of the 12 keys, `act_a`'s field has `seed_keywords == ["electrolyser"] + <that key's list from this spec's Keywords table>`, written out in the test (not read from code constants) | unit |
| AC-7b | As AC-1 | build | For each new field of `act_a`, `name == "Electrolyser manufacturing: " + <name suffix from the Fields table>` | unit |
| AC-7c | As AC-1 | build | The 12 new fields of `act_a` have 12 distinct, non-empty `description` values | unit |
| AC-8 | As AC-1 | build | Every new field has `required is False` and `version == 1` | unit |
| AC-9 | A draft (unratified) taxonomy | build | Raises `ValueError` (regression) | unit |
| AC-10 | A taxonomy version whose schema was registered on `main` (the fixture taxonomy, 8 fields: 4 per activity) | `GET /taxonomies/{id}/versions/{v}/schema` after this change | Returns the same 8 fields | unit |
| AC-10b | As AC-10 | `POST /taxonomies/{id}/versions/{v}/schema` | The response has 32 fields, and its `version` equals the previously registered version + 1 | unit |
| AC-11 | The AC-1 schema | `field_id_for(schema, "act_a", "rd")` | Returns `tax_fx_act_a_rd_pct` | unit |
| AC-12a | Golden case (a) in `tests/golden/stage_evidence/`: a report stating a pilot plant and a commercial product line for activity `act_a` of the fixture taxonomy; schema = the fixture taxonomy's generated schema `sch_tax_fx_v1` | `arp golden-set precision --schema sch_tax_fx_v1 --cases tests/golden/stage_evidence/cases.json --documents-dir tests/golden/stage_evidence/documents --min-precision 0.9` with the real model | Exits 0; the case expects `stage_innovation=true` and `stage_commercial=true`, each with a grounded quote | golden |
| AC-12b | Golden case (b): a report with only company-wide totals and no stage evidence for `act_a` | same command | Exits 0; the case expects `revenue_amount`, `capex_amount`, `rd_amount`, `backlog`, `stage_ideation`, `stage_innovation`, `stage_commercial` all `not_found` (an expected `not_found` counts as correct only when the extractor returns `not_found`) | golden |
| AC-13 | The existing tests `tests/test_research_pipeline.py` and `tests/test_taxonomy_schema.py::test_schema_text_and_keywords`, `::test_schema_is_deterministic_and_refuses_drafts` | CI on this branch | They pass unmodified. Only `test_schema_has_four_fields_per_activity_in_order` may change (it asserts the old field count) and is listed in the PR | unit |
| AC-14 | As AC-1 | build | No new field has a default value, and `ActivityDefinition` gains no stage attribute (the stage exists only as extracted fields) | unit |

Must not change: the four `_pct` fields (AC-3), `field_id_for` (AC-11), draft refusal (AC-9), registered schemas
(AC-10), the funnel and theme-run output (covered by AC-13).
