# Schema rules: agent-suggested, owner-approved checks on extracted values

Date: 2026-10-17
Status: draft for approval
Mockups: https://claude.ai/artifact/VJz7ui2A7U2887qnaWSUCB (private to the owner)

## Intent

An AI answer can contradict its own numbers or another field. The transition plan is where the
owner sees this: the question asks "50% by 2030", the AI says YES, and the report actually says
42%. The script reviewed on 2026-10-17 (`create_all_files.py`) catches such cases with hand-written
Python per question. ARP should catch them **for any schema**, without new Python per schema:

- A schema carries **rules**: small, typed conditions on its extracted values.
- For a schema the user drafts, **an agent suggests rules**; the user accepts, edits or drops each
  one, and can add their own.
- **Presets ship with rules written once**, in the preset's Python file, by us. No agent runs on
  presets.
- A rule that fails **only flags the value for review**. It never changes the AI's answer. The
  reviewer sees which rule fired, what was found and where.

This is the first of two projects. The second writes the transition-plan preset's rules (the
50%/2030, 5-year and intensity-decline rules) on top of this one; it is out of scope here.

## Goals

1. A field can carry rules of five kinds (below). Rules are part of the field definition, saved and
   versioned with it.
2. During an extraction run, every rule is evaluated after the existing checks. A failed rule adds a
   failing check result to the value, which sends the value to review.
3. A rule never changes a value, its state, its confidence or its citations.
4. Missing inputs (a helper number not found) also flag the value for review, with a message that
   says which number was not found.
5. An agent suggests rules for a drafted or hand-built schema. Each suggestion may add **helper
   fields**: the numbers the rule needs, extracted like any other field.
6. On the Schema screen, one **Rules list** is the only place to accept, edit, drop or add rules. Each
   field shows a read-only marker with its rule count that jumps to its rules in the list.
7. "Confirm schema" stays disabled while any suggestion is still waiting for a decision.
8. The reviewer sees a failed rule in the existing review screen: the rule's sentence as it was at run
   time, the values found, and the page they came from.

## Non-goals

- Rules that change a value (forced NO). The owner decided: flag only.
- Rules for the transition-plan preset, or any other preset (project 2).
- An agent that suggests rules for presets.
- Editing or switching off a rule from the review screen.
- Statistics on how often a rule flags values that reviewers then approve.
- Changing the dedicated `transition_plan/` pipeline or its `REQUIRES_YES` rules (#147).
- Rules over derived fields (`derived_rule`): those rows are computed after checks run.
- Decision Studio's rule graph (`decision/rules.py`). It is not reused here.

## Anti-goals (a failure even if it works)

- A rule silently changes what the AI extracted.
- A rule passes because the AI invented a number: helper numbers get the same grounding check as every
  extracted value, and an ungrounded helper value counts as not found for the rule.
- The reviewer sees a rule sentence that no longer matches the numbers the rule checked.
- A suggestion takes effect without the user accepting it.

## Current state (what this builds on)

- `FieldDefinition.check_config` (`schemas/datapoints.py`) already holds numeric checks: min/max,
  non-negative, part of, sum of, at most (`le_of`), sum to target, year-over-year jump. They only flag,
  never change a value.
- `checks/runner.py` `check_record` runs check layers 1–5 per value. `CheckContext.record_fields` holds
  every value of the company's record, so a check can read other fields. A failing WARN or BLOCK result
  adds `ReasonCode.CHECK_FAILED`; `extraction/routing.py` `route()` then adds `check:<check_id>` and
  routes to REVIEW.
- Multi-period extraction: one field yields a row per period, up to the current year plus
  `planning/periods.py` `MAX_COMPARATIVES` = 4 comparatives.
- `review/context.py` already sends every failing check to the reviewer as
  `failed_checks[].plain` (from `CHECK_WORDS`, falling back to the check's `detail`), and
  `ReviewTiles.tsx` `CheckResults` shows it. A rule result with its sentence in `detail` needs no new
  review UI.
- `db/fields.py` `SchemaRegistry.save` refuses to change a released field's content without a version
  bump, so a rule change on a released field forces a new field version.
- `extraction/schema_builder.py` `draft_schema` drafts fields only. `SchemaPanel.tsx` +
  `SchemaFieldsEditor.tsx` let the user edit drafted fields.

## Design

### The five rule kinds

A rule lives on the field it checks (`FieldDefinition.rules`, a list). Every rule has:

- `rule_id`: stable, unique within the schema.
- `kind`: one of the five below.
- `when`: the value of **this** field that makes the rule apply, or empty for "whenever a value was
  found". Example: `true` for "only when the answer is YES". When this field's value doesn't match,
  the rule is not applicable and has no effect.
- `text`: the plain sentence shown to the user and the reviewer. It is generated from the rule's
  parameters (see "Sentence") and stored with the rule.

| Kind | Parameters | Fails when |
|---|---|---|
| `requires` | `field`, `equals` | the other field's value is not `equals`, or it was not found |
| `threshold` | `conditions`: a list of `{field, op, value}`, with `op` one of `>=`, `<=`, `>`, `<`, `=` | any condition is false, or any named field was not found |
| `series` | `field` (numeric), `years` (1–5), `trend` (`none`, `down`, `up`) | the field has fewer than `years` found values for the consecutive fiscal years ending at the current reporting year; or, with a trend, the last year's value is not below (`down`) or above (`up`) the first year's; or the values' canonical units differ |
| `label` | `field` (enum), `not_in` (list of allowed values of that field) | the other field's value is in `not_in`, or it was not found |
| `computed` | `formula` (`ratio_pct` or `sum`), `inputs` (field ids), `tolerance` (absolute) | this field differs from the formula's result by more than `tolerance`, or any input was not found. `ratio_pct` = inputs[0] ÷ inputs[1] × 100; `sum` = sum of inputs |

"Not found" means: no row for that field, a row that is not `found`/`zero`, or a row that is not
grounded.

For a multi-period field, a rule compares rows of the same period. `series` reads all periods of its
`field`. The "current reporting year" is the latest period-end year in the run's period plan for the
company.

### Validation (trust boundary)

`DataPointSchema` validation rejects a rule whose:

- named fields don't exist in the schema, or name the rule's own field (except `computed` inputs,
  which never include it);
- `threshold`, `series` or `computed` fields are not numeric (`number`, `currency_amount`,
  `percentage`);
- `label` field is not an `enum`, or whose `not_in` contains a value outside that field's
  `allowed_values`;
- `series.years` is outside 1–5 (5 = current year + `MAX_COMPARATIVES`);
- named fields are derived fields;
- `rule_id` repeats within the schema.

The suggestion endpoint and the save endpoint both run this validation. An invalid suggestion is
dropped and never shown.

### Running rules

A new check, registered after the layer-3 plausibility checks, evaluates every rule of a field
against `CheckContext.record_fields`. Each rule produces one `CheckResult`:

- `check_id` = `rule.<rule_id>`
- `severity` = WARN
- `outcome` = PASS, FAIL, or NOT_APPLICABLE (when `when` doesn't match)
- `detail` = the rule's `text`, then what was found, for example:
  `Target ≥ 50% by 2030: failed. Found Target reduction % = 42 (p. 31), Target year = 2030 (p. 31).`
  When an input is missing: `… : Target reduction % not found.`
- `threshold_ref` = `<field_id>:v<version>:rules.<rule_id>`

Because the sentence is copied into `detail` at run time, the reviewer always sees the rule as it was
when the run happened.

Rules add to the field's content, so changing a rule changes the run's reuse key the same way any
field edit does (`planning/doc_routing.py` keys on field id and version).

### Suggesting rules

A new agent call, `suggest_rules(schema, llm)` in `extraction/schema_builder.py`, reads each field's
name, description and extraction instructions and returns:

- rules, each with its target field id, kind and parameters;
- helper fields, each a full field draft (name, description, data type, unit, instructions, seed
  keywords), referenced by the rules that need them.

The prompt tells the model to suggest a rule only for a dependency or threshold the field's own text
states (for example "50% by 2030", "past 5 years", "if no target …"), and never to invent
thresholds. Existing `check_config` checks (range, at most, sum) may be suggested too; they are
stored in `check_config` as today.

API: `POST /api/extraction/schemas/suggest-rules` takes a `DataPointSchema` and returns
`{rules: [{field_id, rule}], helper_fields: [FieldDefinition], check_config: [{field_id, patch}]}`,
after validation against the schema plus its helper fields. Same role as the existing draft
endpoint.

### Schema screen

Mockup screen 1 (B) and screen 2.

- After "Draft extraction schema" fills the fields, the app calls suggest-rules automatically and
  shows the **Rules list** under the fields editor. A hand-built schema gets a "Suggest rules" button
  on the empty list.
- Each suggestion shows its sentence, its kind, the helper fields it would add, and Accept / Edit /
  Drop. Waiting suggestions use the app's "waiting on a person" orange (`--await`, `--await-edge`).
- **Accept** moves the rule into its field's `rules`, or its patch into `check_config`, and adds its
  helper fields to the schema. A helper field already added by another accepted rule is not added twice.
- **Drop** removes the suggestion. Helper fields that no accepted rule uses are not added.
- **Edit** turns the rule's parameters into inputs. The sentence updates as they change.
- **+ Add a rule** opens the same editor, empty, for any field.
- **Suggest again** re-runs the agent on the current fields. Accepted rules stay. New suggestions
  identical to an accepted rule are not shown.
- **Confirm schema** is disabled while any suggestion is waiting. Its label says how many, for example
  `2 rule suggestions waiting`.
- Under each field in the fields editor: a read-only marker `N rules · M waiting` that scrolls the list
  to that field's rules. A helper field shows `helper for a rule`.
- Editing a field still clears "confirmed", as today.

### Sentence

The sentence is generated from the rule's kind and parameters using field names, never written by
hand, so it can't drift from the numbers. One template per kind:

- requires: `Needs <field> to be <equals>.`
- threshold: `Needs <field> <op> <value>[ and <field> <op> <value>…].`
- series: `Needs <field> for <years> years up to the report year[, falling | rising].`
- label: `<field> must not be <v1>[ or <v2>…].`
- computed: `Should equal <formula over input names>, within <tolerance>.`

Each is prefixed with the `when` condition where there is one: `When <this field> is YES: …`.

The frontend renders the template for live editing and stores the result in `text`. The backend
re-renders it on save and on suggest, and its result is the one stored, so both always agree.

### Presets

Presets keep their Python files. A preset may declare `rules=[...]` on its fields like any schema,
using the same models and validation. No preset gets rules in this project.

## Constraints

- No new dependency.
- The API contract check (`scripts/export_openapi.py --check`) must pass: regenerate
  `frontend/src/api/openapi.json` and `schema.gen.ts`.
- Rules run without a model call. The only model call added is suggest-rules.
- Existing schemas with no `rules` behave exactly as before.

## Left to the builder

- Pydantic model layout for the five kinds (a discriminated union is the natural fit).
- File placement of the rule check (`checks/rules.py` fits the existing layout).
- The exact prompt wording for suggest-rules, within the rule above.
- Layout and styling of the Rules list and editor, within the mockups and the app's design system.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A schema whose boolean field `ambition` has a `threshold` rule `when: true`, conditions `pct >= 50` and `year <= 2030`; extraction returns `ambition`=true, `pct`=42 (grounded), `year`=2030 (grounded) | the run's checks and routing finish | the `ambition` row's `checks` include `check_id` `rule.<rule_id>` with `outcome` `fail` and `severity` `warn`; its `route` is `review` and `route_reasons` include `check:rule.<rule_id>` | unit |
| AC-2 | Same as AC-1 | the run finishes | the `ambition` row's `value` is `true`, and its `value_state`, `confidence` and `citations` equal what extraction returned | unit |
| AC-3 | Same as AC-1 but `pct`=55 | the run finishes | the rule's check result has `outcome` `pass`, and `route_reasons` contain no `check:rule.` entry | unit |
| AC-4 | Same as AC-1 but `ambition`=false | the run finishes | the rule's check result has `outcome` `not_applicable` | unit |
| AC-5 | Same as AC-1 but `pct` has no found row | the run finishes | the rule's check result has `outcome` `fail` and its `detail` contains `<pct field name> not found` | unit |
| AC-6 | Same as AC-1 but the `pct` row is found with `grounded` false | the run finishes | the rule's check result has `outcome` `fail` and its `detail` contains `<pct field name> not found` | unit |
| AC-7 | A `requires` rule on `b` (`when: true`) naming `a` `equals: true`; extraction returns `b`=true, `a`=false | the run finishes | `b`'s rule result has `outcome` `fail` | unit |
| AC-8 | A `series` rule on field `s` naming numeric `e`, `years` 5, `trend` `down`; current reporting year 2024; `e` found for 2020–2024 with 2024 < 2020 | the run finishes | the rule result has `outcome` `pass` | unit |
| AC-9 | Same as AC-8 but `e` found for 2020, 2021, 2022, 2024 only | the run finishes | the rule result has `outcome` `fail` | unit |
| AC-10 | Same as AC-8 but the 2024 value is above the 2020 value | the run finishes | the rule result has `outcome` `fail` | unit |
| AC-11 | A `label` rule on `t` naming enum `kind` with `not_in: ["combined"]`; extraction returns `kind`=`combined` | the run finishes | the rule result has `outcome` `fail` | unit |
| AC-12 | A `computed` rule on percentage field `share`, `ratio_pct` of `[green, total]`, tolerance 1; extraction returns green=30, total=200, share=20 | the run finishes | the rule result has `outcome` `fail` | unit |
| AC-13 | Same as AC-12 but share=15.4 | the run finishes | the rule result has `outcome` `pass` | unit |
| AC-14 | A schema whose rule names a field id not in the schema | it is POSTed to `/api/extraction/schemas` | the response status is 422 | unit |
| AC-15 | A schema whose `series` rule has `years` 6 | it is POSTed to `/api/extraction/schemas` | the response status is 422 | unit |
| AC-16 | A schema whose `threshold` rule names a `string` field | it is POSTed to `/api/extraction/schemas` | the response status is 422 | unit |
| AC-17 | A released schema version whose field gains a rule without a version bump | it is saved through `SchemaRegistry.save` | the save is refused with the existing field-version error | unit |
| AC-18 | An LLM stand-in that returns one valid rule with one helper field, plus one rule naming an unknown field | `POST /api/extraction/schemas/suggest-rules` is called | the response has exactly 1 rule and 1 helper field | unit |
| AC-19 | A rule of each kind | its sentence is rendered by the backend and by the frontend | both produce identical text, equal to the template under "Sentence" | unit |
| AC-20 | A failed rule result on a review item | the reviewer opens the item | the review screen lists the rule's sentence and the found values with their page, under the item's failed checks | evaluator |
| AC-21 | A rule edited after a run | the reviewer opens an item from that earlier run | the review screen shows the sentence as it was at run time | unit |
| AC-22 | A drafted schema | the draft finishes on the Schema screen | the Rules list appears below the fields with the agent's suggestions, each with Accept, Edit and Drop | evaluator |
| AC-23 | Two waiting suggestions | the user looks at the Confirm button | it is disabled and reads `2 rule suggestions waiting` | evaluator |
| AC-24 | A suggestion that adds helper field "Total capex" | the user clicks Accept | "Total capex" appears in the fields list marked `helper for a rule`, and the suggestion shows as accepted | evaluator |
| AC-25 | A suggestion that adds a helper field | the user clicks Drop | the suggestion disappears and no helper field is added | evaluator |
| AC-26 | A threshold rule being edited | the user changes 50 to 40 | the sentence reads `… >= 40 …` before saving | evaluator |
| AC-27 | A field with 2 rules, 1 waiting | the user looks at that field in the fields editor | it shows `2 rules · 1 waiting`; clicking it scrolls the Rules list to those rules | evaluator |
| AC-28 | A hand-built schema with no rules | the user opens the Rules list | it shows a "Suggest rules" button | evaluator |
| AC-29 | One accepted rule | the user clicks Suggest again and the agent returns the same rule plus a new one | the list shows the accepted rule once and one new waiting suggestion | evaluator |
| AC-30 | Must not change: a schema with no `rules` | it runs through extraction | every row's `checks`, `route` and `route_reasons` are identical to `main` | unit |
| AC-31 | Must not change: the existing `check_config` checks | their tests run | they pass unchanged | unit |

Must not change: schemas without rules (AC-30), the existing checks (AC-31), the dedicated
`transition_plan/` pipeline (no row: no file under `transition_plan/` changes).

`unit` rows are listed as owed for `holdout` until the `HOLDOUT_TOKEN` secret is confirmed set.
