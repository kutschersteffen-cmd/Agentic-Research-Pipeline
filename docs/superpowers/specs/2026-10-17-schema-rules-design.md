# Schema rules: agent-suggested, owner-approved checks on extracted values

Date: 2026-10-17
Status: draft for approval
Mockups: https://claude.ai/artifact/VJz7ui2A7U2887qnaWSUCB (private to the owner; screen 1 shows the
existing "at most" and "jump" checks in the Rules list, which this spec leaves out)

## Intent

An AI answer can contradict its own numbers or another field. The transition plan is where the
owner sees this: the question asks "50% by 2030", the AI says YES, and the report actually says
42%. The script reviewed on 2026-10-17 (`create_all_files.py`) catches such cases with hand-written
Python per question. ARP should catch them **for any schema**, without new Python per schema:

- A schema carries **rules**: small, typed conditions on its extracted values.
- For a schema the user drafts, **an agent suggests rules**. The user accepts, edits or drops each
  one, and can add their own.
- **Presets ship with rules written once**, in the preset's Python file, by us. No agent runs on
  presets.
- A rule that fails **only flags the value for review**. It never changes the AI's answer. The
  reviewer sees which rule fired, what was found and where.

This is the first of two projects. The second writes the transition-plan preset's rules (the
50%/2030, 5-year and intensity-decline rules) on top of this one. It is out of scope here.

## Goals

1. A field can carry rules of five kinds (below). Rules are part of the field definition, saved and
   versioned with it.
2. During an extraction run, every rule is evaluated after the existing check layers 1–5. A failed
   rule adds a failing check result to the value, which sends the value to review.
3. A rule never changes a value, its state, its confidence or its citations.
4. Missing inputs (a number the rule needs that was not found) also flag the value for review, with a
   message naming what was not found.
5. An agent suggests rules for a drafted schema. A suggestion may add **helper fields**: the numbers
   or labels the rule needs, extracted like any other field.
6. On the Schema screen, one **Rules list** is the only place to accept, edit, drop or add rules. Each
   field shows a read-only marker with its rule count that scrolls the list to its rules.
7. "Confirm schema" stays disabled while any suggestion is still waiting for a decision.
8. The reviewer sees a failed rule in the existing review screen: the rule's sentence as it was at run
   time, the values found, and their page.

## Non-goals

- Rules that change a value (forced NO). The owner decided: flag only.
- Suggesting or editing the existing `check_config` checks (range, at most, sum, jump) in the Rules
  list. They keep working as today. The owner decided to leave them out.
- Rules for the transition-plan preset, or any other preset (project 2).
- An agent that suggests rules for presets.
- Editing or switching off a rule from the review screen.
- Statistics on how often a rule flags values that reviewers then approve.
- Changing the dedicated `transition_plan/` pipeline or its `REQUIRES_YES` rules (#147).
- Rules over derived fields (`derived_rule`): those rows are computed after checks run.
- Adding or deleting fields by hand on the Schema screen (it can't today), and loading a saved schema
  into it.
- Decision Studio's rule graph (`decision/rules.py`). It is not reused here.

## Anti-goals (a failure even if it works)

- A rule silently changes what the AI extracted.
- A rule passes because the AI invented a number. An input that is not grounded counts as not found.
- The reviewer sees a rule sentence that doesn't match the numbers the rule checked.
- A suggestion takes effect without the user accepting it.

## Current state (what this builds on)

- `FieldDefinition.check_config` (`schemas/datapoints.py`) holds numeric checks that only flag.
- `checks/runner.py` `check_record` runs check layers 1–5 per row. `CheckContext.record_fields` holds
  every row of the company's record. A failing WARN or BLOCK result adds `ReasonCode.CHECK_FAILED`, and
  `extraction/routing.py` `route()` adds `check:<check_id>` and routes to REVIEW.
- Reused rows (`extraction/pipeline.py`) get `checks: []` and go through `check_record` again, so
  rules re-run on reused rows. Today a prior row is reused only if none of its checks failed.
- Multi-period extraction: one field yields a row per period, up to the current year plus
  `planning/periods.py` `MAX_COMPARATIVES` = 4 comparatives.
- `review/context.py` sends each failing check to the reviewer as `failed_checks[].plain`
  (`CHECK_WORDS`, falling back to the check's `detail`). `ReviewTiles.tsx` `CheckResults` shows it.
- `db/fields.py` `SchemaRegistry` refuses to change a released field's content without a version
  bump (`FieldVersionError`, HTTP 400). Keys added to `FieldDefinition` after a release take their
  default when compared, so a new `rules` list that defaults to empty leaves released fields as they
  are.
- `extraction/schema_builder.py` `draft_schema` drafts fields only. `SchemaPanel.tsx` +
  `SchemaFieldsEditor.tsx` edit a drafted schema's fields.
- Percentage values are stored in percent points (20 means 20%).

## Design

### The five rule kinds

A rule lives on the field it checks (`FieldDefinition.rules`, a list, empty by default). Every rule
has:

- `rule_id`: unique within the schema.
- `kind`: one of the five below.
- `when`: the value of **this** field that makes the rule apply (for example `true`), or empty for
  "whenever this field was found". When this field has no found row, or its value doesn't equal
  `when`, the rule is not applicable.

No sentence is stored. It is rendered from the parameters (see "Sentence").

| Kind | Parameters | Fails when |
|---|---|---|
| `requires` | `field`, `equals` | the other field's value is not `equals`, or it is not found |
| `threshold` | `conditions`: a list of `{field, op, value}`, `op` one of `>=`, `<=`, `>`, `<`, `=` | any condition is false, or any named field is not found |
| `series` | `field` (numeric), `years` (1–5), `trend` (`none`, `down`, `up`) | the field lacks a found value for any of the `years` consecutive fiscal years ending at the current reporting year; or, with a trend, the last year's value is not below (`down`) or above (`up`) the first year's |
| `label` | `field` (enum), `not_in` (values of that field's `allowed_values`) | the other field's value is in `not_in`, or it is not found |
| `computed` | `formula` (`ratio_pct` or `sum`), `inputs` (field ids), `tolerance` (absolute, ≥ 0) | this field differs from the formula's result by more than `tolerance`, or any input is not found. `ratio_pct` = inputs[0] ÷ inputs[1] × 100, `sum` = the sum of inputs |

Shared definitions:

- **Not found**: no row for that field and period, or a row that is not `found`/`zero`, or a row that
  is not grounded.
- **Numbers** are compared as `canonical_value`. If the values a rule compares have different
  `canonical_unit`s, the rule fails with "Units differ". A `threshold` value is in the field's `unit`.
- **Periods** *(builder-check call)*: a rule gives one result per row of the field it checks. For each
  other field it reads, it takes that field's row with the same `period_end`. If none matches and the
  other field has exactly one row, it takes that row. If the checked row has no `period_end`, it takes
  the other field's row with the latest `period_end`. `series` ignores this and reads every row of its
  `field`.
- **Current reporting year**: the latest period-end year in the company's period plan for the run. With
  no period plan, a `series` rule fails with "Report year unknown".

### Validation (trust boundary)

`DataPointSchema` validation (HTTP 422 on `POST /api/extraction/schemas`) rejects a rule whose:

1. named fields (including `computed` inputs) don't exist in the schema;
2. named fields (including `computed` inputs) include the rule's own field;
3. `threshold`, `series` or `computed` fields are not `number`, `currency_amount` or `percentage`;
4. `threshold` names a `currency_amount` field whose `unit` is empty;
5. `label` field is not an `enum`;
6. `not_in` holds a value outside the `label` field's `allowed_values`;
7. `series.years` is outside 1–5;
8. named fields are derived fields;
9. `rule_id` repeats within the schema.

The suggestion endpoint runs the same validation and drops invalid suggestions.

### Running rules

`check_record` evaluates a field's rules after its layer 1–5 checks, also when a layer stopped early.
Each rule adds one `CheckResult` per row of the field, after the layer results:

- `check_id` = `rule.<rule_id>`, `layer` = 3, `severity` = WARN
- `outcome` = PASS, FAIL or NOT_APPLICABLE
- `detail` (FAIL only; empty otherwise) = `<sentence> Failed. <found part>`, where the found part is,
  in this order and each only when non-empty:
  - `Found <name> = <value> (p. <page>), <name> = <value> (p. <page>).`: every input the rule read
    that was found, in the order the rule names them. `(p. <page>)` comes from the row's first
    citation and is left out when it has no page. For `computed`, the checked field comes last,
    followed by ` Expected <result>.`
  - for `series`: `Found <name> <year> = <value>, <year> = <value>.` for the years found in the window,
    oldest first;
  - `Not found: <name>, <name>.` (for `series`: `Not found: <name> <year>, <year>.`);
  - `Units differ.` or `Report year unknown.`
- `threshold_ref` = `<field_id>:v<version>:rules.<rule_id>`

Value formatting in sentences and details: booleans as `YES`/`NO`, whole numbers without a decimal
point (`42`, not `42.0`), other numbers as stored, `Expected` rounded to 2 decimals with trailing
zeros dropped, enum values as stored.

The detail is written at run time, so the reviewer sees the rule as it was then.

**Reuse** *(builder-check call)*: a prior row whose only failing checks are `rule.*` results is
reused like a row with no failing checks. Rules re-run on it anyway.

### Sentence

Rendered from kind, parameters and current field names, never typed by hand:

- requires: `needs <field> to be <equals>.`
- threshold: `needs <field> <op> <value>[ and <field> <op> <value>…].`
- series: `needs <field> for <years> years up to the report year[, falling | , rising].`
- label: `<field> must not be <v1>[ or <v2>…].`
- computed `ratio_pct`: `<this field> should equal <in0> ÷ <in1> × 100, within <tolerance>.`
- computed `sum`: `<this field> should equal <in0> + <in1>[ + …], within <tolerance>.`

With a `when`, the sentence is `When <this field> is <when>: <rule part>`. Without one, the rule part's
first letter is capitalized.

The backend renders it for check details. The frontend renders it for the Rules list and live
editing. Both are tested against the same fixture file of expected sentences (AC-31).

### Suggesting rules

A new agent call, `suggest_rules(schema, llm)` in `extraction/schema_builder.py`, reads each field's
name, description and extraction instructions and returns rules plus the helper fields they need. The
prompt tells the model to suggest a rule only for a dependency or threshold the field's own text
states (for example "50% by 2030", "past 5 years", "if no target …"), and never to invent a
threshold. It suggests only the five rule kinds.

`POST /api/extraction/schemas/suggest-rules` takes a `DataPointSchema` and returns
`{rules: [{field_id, rule}], helper_fields: [FieldDefinition]}`:

- A helper field whose name (case-insensitive) matches a schema field or another helper field is
  merged into it, and its rules point to that field's id.
- Every returned rule is validated against the schema plus the returned helper fields, and invalid
  ones are dropped. Helper fields no kept rule names are dropped too.
- It saves nothing. Same role as the existing draft endpoint.

Suggestion quality is not an acceptance criterion, because model output varies. The guard is that
nothing applies until the user accepts it.

### Schema screen

Mockup screen 1 (B) and screen 2, without the "at most" and "jump" items.

- After "Draft extraction schema" fills the fields, the app calls suggest-rules and shows the **Rules
  list** under the fields editor.
- A **waiting** suggestion shows its sentence, the helper fields it would add, and Accept / Edit /
  Drop, in the app's "waiting on a person" orange (`--await`, `--await-edge`).
- **Accept** adds the rule to its field's `rules` and its helper fields to the schema. A helper field
  with the same field id as one already in the schema is not added again. The item then shows an
  `Accepted` label with Edit and Drop, without the orange.
- **Drop** on a waiting suggestion removes it and adds nothing. Drop on an accepted rule removes the
  rule and keeps its helper fields *(builder-check call)*.
- **Edit** turns the parameters into inputs. The sentence re-renders as they change. Save keeps the
  item's state (waiting or accepted).
- **+ Add a rule** opens the editor for any field, using only fields already in the schema. Saving it
  adds an accepted rule.
- **Suggest again** re-runs the agent on the current fields. Waiting suggestions are replaced by the new
  ones. A new suggestion that matches an accepted rule, or one dropped in this session, is not shown.
  "Matches" means same checked field, kind, `when` and parameters.
- **Confirm schema** is disabled while any suggestion is waiting. It then reads
  `1 rule suggestion waiting` or `N rule suggestions waiting`. With none waiting it reads as today:
  `Confirm schema (N fields)`.
- Each field in the fields editor shows a read-only marker when it has rules: `N rules · M waiting`,
  where N counts its accepted and waiting rules and M its waiting ones. It shows `1 rule` / `N rules`
  when M is 0, and nothing when N is 0. Clicking the marker scrolls the Rules list to that field's first
  rule. A field that another accepted rule reads shows `used by a rule`.
- The fields editor gets no rule inputs and no Accept / Edit / Drop.
- Editing a field still clears "confirmed", as today.

### Presets

Presets keep their Python files. A preset may declare `rules=[...]` on its fields, with the same
models and validation. No preset gets rules in this project.

## Constraints

- No new dependency.
- The API contract check (`scripts/export_openapi.py --check`) passes: regenerate
  `frontend/src/api/openapi.json` and `schema.gen.ts`.
- Rules run without a model call. The only model call added is suggest-rules.
- Schemas with no rules behave exactly as before.

## Left to the builder

- Pydantic model layout for the five kinds (a discriminated union fits).
- File placement of the rule evaluation (`checks/rules.py` fits the layout).
- The exact prompt wording for suggest-rules, within the rule above.
- Layout and styling of the Rules list and editor, within the mockups and the app's design system.

## Acceptance

**Fixture schema F** (used by the rows below; ids in code font, names in quotes):

| id | name | type |
|---|---|---|
| `ambition` | "Halving target" | boolean |
| `pct` | "Target reduction" | percentage |
| `year` | "Target year" | number |
| `nz` | "Net-zero target" | boolean |
| `nz2050` | "Net zero by 2050" | boolean |
| `int1` | "Scope 1 intensity" | number, unit `tCO2e/EURm` |
| `declined` | "Intensity declined" | boolean |
| `kind` | "Target type" | enum `standalone`, `combined` |
| `s1` | "Scope 1 target" | boolean |
| `green` | "Green capex" | currency_amount, unit `EUR millions` |
| `total` | "Total capex" | currency_amount, unit `EUR millions` |
| `other` | "Other capex" | currency_amount, unit `EUR millions` |
| `share` | "Green capex share" | percentage |

**Rules R:**

- R1 on `ambition`: threshold, `when` true, `pct >= 50`, `year <= 2030`
- R2 on `nz2050`: requires, `when` true, `nz` equals true
- R3 on `declined`: series, `when` true, `int1`, years 5, trend down
- R4 on `s1`: label, `when` true, `kind` not_in `combined`
- R5 on `share`: computed `ratio_pct`, inputs `green`, `total`, tolerance 1
- R6 on `total`: computed `sum`, inputs `green`, `other`, tolerance 0.5

Every extracted row below is found and grounded with a citation on page 31, unless the row says
otherwise. Single-period rows have no `period_end` unless stated. The current reporting year is 2024.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | F with R1; `ambition`=true, `pct`=42, `year`=2030 | the company's checks and routing finish | `ambition`'s `checks` include `rule.R1` with `outcome` `fail`, `severity` `warn` | unit |
| AC-2 | Same as AC-1 | the company's checks and routing finish | `ambition`'s `route` is `review` and its `route_reasons` include `check:rule.R1` | unit |
| AC-3 | Same as AC-1 | the company's checks and routing finish | the `rule.R1` `detail` is exactly `When Halving target is YES: needs Target reduction >= 50 and Target year <= 2030. Failed. Found Target reduction = 42 (p. 31), Target year = 2030 (p. 31).` | unit |
| AC-4 | Same as AC-1 | the company's checks and routing finish | `ambition`'s `value`, `value_state`, `confidence` and `citations` equal the extracted row's | unit |
| AC-5 | Same as AC-1 but `pct`=55 | the company's checks and routing finish | `rule.R1` has `outcome` `pass` | unit |
| AC-6 | Same as AC-5 | the company's checks and routing finish | `ambition`'s `route_reasons` contain no entry starting `check:rule.` | unit |
| AC-7 | Same as AC-1 but `ambition`=false | the company's checks and routing finish | `rule.R1` has `outcome` `not_applicable` | unit |
| AC-8 | Same as AC-1 but the `ambition` row has `value_state` `not_found` | the company's checks and routing finish | `rule.R1` has `outcome` `not_applicable` | unit |
| AC-9 | Same as AC-1 but `pct` has no row | the company's checks and routing finish | the `rule.R1` `detail` is exactly `When Halving target is YES: needs Target reduction >= 50 and Target year <= 2030. Failed. Found Target year = 2030 (p. 31). Not found: Target reduction.` | unit |
| AC-10 | Same as AC-1 but the `pct` row has `grounded` false | the company's checks and routing finish | `rule.R1` has `outcome` `fail` and its `detail` ends with `Not found: Target reduction.` | unit |
| AC-11 | F with R1; `ambition`=true with no `period_end`; `pct` rows 30 (period end 2023-12-31) and 55 (2024-12-31); `year`=2030 | the company's checks and routing finish | `rule.R1` has `outcome` `pass` (the latest `pct` row was used) | unit |
| AC-12 | F with R2; `nz2050`=true, `nz`=false | the company's checks and routing finish | `rule.R2` has `outcome` `fail` | unit |
| AC-13 | F with R3; `declined`=true; `int1` found for each year 2020–2024, 2024 value 8 and 2020 value 10 | the company's checks and routing finish | `rule.R3` has `outcome` `pass` | unit |
| AC-14 | Same as AC-13 but `int1` has no 2023 row | the company's checks and routing finish | `rule.R3` has `outcome` `fail` and its `detail` contains `Not found: Scope 1 intensity 2023.` | unit |
| AC-15 | Same as AC-13 but the 2024 value is 11 | the company's checks and routing finish | `rule.R3` has `outcome` `fail` | unit |
| AC-16 | Same as AC-13 but the 2022 row's `canonical_unit` is `tCO2e/USDm` | the company's checks and routing finish | `rule.R3` has `outcome` `fail` and its `detail` ends with `Units differ.` | unit |
| AC-17 | F with R4; `s1`=true, `kind`=`combined` | the company's checks and routing finish | `rule.R4` has `outcome` `fail` | unit |
| AC-18 | F with R5; `green`=30, `total`=200, `share`=20 | the company's checks and routing finish | `rule.R5` has `outcome` `fail` and its `detail` ends with `Expected 15.` | unit |
| AC-19 | Same as AC-18 but `share`=15.4 | the company's checks and routing finish | `rule.R5` has `outcome` `pass` | unit |
| AC-20 | F with R6; `green`=30, `other`=170, `total`=200.4 | the company's checks and routing finish | `rule.R6` has `outcome` `pass` | unit |
| AC-21 | A prior run's `ambition` row whose only failing check is `rule.R1`, reuse allowed | the next run processes the company | the new `ambition` row has `reused_from_run` set to the prior run's id | unit |
| AC-22 | F with R1 where `pct` is replaced by `ghost` (not in F) | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-23 | F with R5 whose inputs are `share`, `total` | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-24 | F with a threshold rule on `ambition` naming field `kind` | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-25 | F with `green`'s unit empty and a threshold rule on `ambition` naming `green` | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-26 | F with R4 naming `pct` instead of `kind` | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-27 | F with R4 whose `not_in` is `partial` | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-28 | F with R3 whose `years` is 0, and separately 6 | each is POSTed to `/api/extraction/schemas` | status 422 for both | unit |
| AC-29 | F with `nz` given a `derived_rule` (any_of `ambition`) and R2 | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-30 | F with R1 and a second rule also named `R1` on `nz2050` | it is POSTed to `/api/extraction/schemas` | status 422 | unit |
| AC-31 | `rule_sentences.json` holding R1–R6 and R1 without `when`, each with its expected sentence: R1 `When Halving target is YES: needs Target reduction >= 50 and Target year <= 2030.`; R2 `When Net zero by 2050 is YES: needs Net-zero target to be YES.`; R3 `When Intensity declined is YES: needs Scope 1 intensity for 5 years up to the report year, falling.`; R4 `When Scope 1 target is YES: Target type must not be combined.`; R5 `Green capex share should equal Green capex ÷ Total capex × 100, within 1.`; R6 `Total capex should equal Green capex + Other capex, within 0.5.`; R1 without `when` `Needs Target reduction >= 50 and Target year <= 2030.` | the backend and frontend sentence renderers run on the file | both produce every expected sentence exactly | unit |
| AC-32 | F with R1–R6 | it is POSTed to `/api/extraction/schemas`, then fetched with GET | the fetched fields' `rules` equal the posted ones | unit |
| AC-33 | A released schema version; a field gains R1 without a version bump | the schema is POSTed to `/api/extraction/schemas` | status 400, body contains `changing it needs` | unit |
| AC-34 | Must not change: a schema saved and released on `main` (no `rules` key in its stored body) | it is fetched and POSTed again unchanged | the response has the same schema version and the same field versions | unit |
| AC-35 | An LLM stand-in returning 2 rules: one valid with helper field "Total capex", one naming field id `ghost` | `POST /api/extraction/schemas/suggest-rules` with F minus `total` | the response has exactly 1 rule and exactly 1 helper field, named "Total capex" | unit |
| AC-36 | An LLM stand-in returning 2 valid rules that each add a helper field named "total capex" and "Total Capex" | suggest-rules with F minus `total` | the response has exactly 1 helper field, and both rules name its id | unit |
| AC-37 | Any schema list | `POST /api/extraction/schemas/suggest-rules` is called | `GET /api/extraction/schemas` lists the same schemas as before | unit |
| AC-38 | A run with R1 failing (AC-1); R1's threshold then edited from 50 to 40 and the schema saved | the review context for that run's `ambition` item is fetched | its `failed_checks` include an entry whose `plain` is the AC-3 string | unit |
| AC-39 | Browser test; draft and suggest-rules stubbed to return F's fields and R1 (helper `pct`) waiting | drafting finishes | the Rules list shows R1's sentence with buttons Accept, Edit and Drop | unit |
| AC-40 | Browser test; stub returns 2 waiting suggestions | the user looks at the confirm button | it is disabled and reads `2 rule suggestions waiting` | unit |
| AC-41 | As AC-40; the user accepts one | the user looks at the confirm button | it is disabled and reads `1 rule suggestion waiting` | unit |
| AC-42 | As AC-41; the user drops the other | the user looks at the confirm button | it is enabled and reads `Confirm schema (N fields)` with N the schema's field count | unit |
| AC-43 | Browser test; a waiting suggestion adds helper field "Total capex" | the user clicks Accept | the fields list contains "Total capex" | unit |
| AC-44 | As AC-43 | the user clicks Accept | the item shows `Accepted`, Edit and Drop, and no Accept button | unit |
| AC-45 | Browser test; two waiting suggestions name the same helper field id | the user accepts both | the fields list contains that field once | unit |
| AC-46 | Browser test; a waiting suggestion adds a helper field | the user clicks Drop | the suggestion is gone and the fields list is unchanged | unit |
| AC-47 | Browser test; an accepted rule with a helper field | the user clicks Drop | the rule is gone and the helper field stays in the fields list | unit |
| AC-48 | Browser test; R1 open in Edit | the user changes 50 to 40 | the sentence reads `When Halving target is YES: needs Target reduction >= 40 and Target year <= 2030.` before saving | unit |
| AC-49 | Browser test; `ambition` has 1 accepted and 1 waiting rule | the user looks at `ambition` in the fields editor | its marker reads `2 rules · 1 waiting` | unit |
| AC-50 | As AC-49 | the user clicks the marker | `ambition`'s first rule is inside the viewport | unit |
| AC-51 | Browser test; a field with no rules that no rule reads | the user looks at it in the fields editor | it shows no marker | unit |
| AC-52 | Browser test; R1 accepted | the user looks at `pct` in the fields editor | it shows `used by a rule` | unit |
| AC-53 | Browser test; the fields editor with rules present | the user looks at the fields editor | it has no Accept, Edit or Drop buttons and no rule inputs | unit |
| AC-54 | Browser test; + Add a rule, field `ambition`, kind threshold, `pct >= 50`, saved | the user looks at the Rules list | it shows the rule as `Accepted` with sentence `When Halving target is YES: needs Target reduction >= 50.` | unit |
| AC-55 | Browser test; R1 accepted, R2 dropped; Suggest again stubbed to return R1, R2 and R4 | the new suggestions arrive | the list shows R1 once (accepted) and R4 waiting, and no R2 | unit |
| AC-56 | Browser test; every suggestion dropped, schema confirmed, run started | the run request is sent | its `datapoint_schema` has no `rules` on any field and only the drafted fields | unit |
| AC-57 | Must not change: browser test; a confirmed schema | the user edits a field name | the confirm button is enabled again and reads `Confirm schema (N fields)` | unit |
| AC-58 | The real app with a real model, default green capex request, light and dark theme, 390 px and 1280 px wide | the evaluator drafts the schema and accepts, edits and drops a suggestion | the Rules list and editor show no horizontal page scroll and no overlapping text, and wording matches this spec | evaluator |
| AC-59 | Must not change: a fixed record and schema with no rules; expected `checks`, `route` and `route_reasons` captured on `main` and committed as a snapshot | the record goes through checks and routing | the output equals the snapshot | unit |
| AC-60 | Must not change: the existing `check_config` tests | they run | they pass unchanged | unit |
| AC-61 | Must not change: the PR's diff | `git diff --name-only origin/main...HEAD` runs | it lists no path under `backend/arp/transition_plan/` | evaluator |

"Browser test" rows run in the E2E job (`backend/tests/e2e`) and stub the draft and suggest-rules
calls with Playwright request routing, so the suggestions are fixed.

`unit` rows are owed as `holdout` until the `HOLDOUT_TOKEN` secret is confirmed set.
