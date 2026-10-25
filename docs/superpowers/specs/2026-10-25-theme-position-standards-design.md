# Theme position and standards (step 5 of the theme process)

Status: draft, 2026-10-25.

## Where this sits

Step 5 of the five-step theme process in `2026-10-25-theme-dossier-design.md`. That spec shows step 5 as
`not_built`; this spec builds it and replaces only its step 5 derivation. Inputs:

- the theme's **approved research note** (step 3, its own spec). Step 5 uses only the note's approved version
  number and its list of items, each `{item_id, kind: "risk" | "opportunity", title, summary}`. Build this
  feature after step 3 is on `main`. If step 3's record names these fields differently, map them, but don't add any.
- the **exposed companies** (step 4): the newest counted theme run of the dossier's taxonomy when the dossier's
  step 4 is `done`. Those are the run's companies with at least one entry in `company_matches`.

## Owner decisions (2026-10-25)

1. **Position**: a comprehensive house position and narrative on the theme. The model drafts it from the
   research note's risks and opportunities, and the owner approves it.
2. **Standards**: stewardship expectations for exposed companies, derived from the approved position. A
   standard is admissible only with a **clear definition and criteria that are easy to identify in company
   reports**.
3. **Data is the main job of the standards part**: every standard is matched to an existing data point. Where
   none exists, a data-point schema is drafted for it. Once the standards are approved, step 5 **runs the
   extraction** of the new data points on the exposed companies.
4. Companies that fail a standard are **flagged in StewardIQ**.
5. **One approver, the owner**. The model drafts and the owner approves.
6. **Approach A** (below). Standards are a StewardIQ policy saved with author `model`, so the unchanged
   four-eyes check passes when the owner activates. The owner changes a draft by sending instructions to the
   model for a redraft, never by editing the draft. Four-eyes is not weakened for any policy.

## Intent

Today the theme process ends at a reviewed company list: nothing says what the house thinks about the theme or
what it expects of those companies. Step 5 turns the research into a stated position and the position into
expectations that a machine can check against reported data. Where the data doesn't exist yet, step 5 creates
it. The point is a traceable chain:
research item → position paragraph → standard → data point → company flag.

## Goals

- From an approved research note, the model drafts a position. Every paragraph cites the note items it rests
  on, and every note item is cited. The owner approves it or sends instructions for a redraft.
- From the approved position, the model drafts standards. Each one has a definition, the place it is reported,
  one criterion on one data point, a severity and the position paragraphs it rests on.
- Each standard is matched to a **released field** of the field registry or, where none fits, to a field of
  a new data-point schema drafted with the standards.
- On activation, the new schema is released and an extraction run starts on the exposed companies.
- A check evaluates every exposed company against every active standard from the current company facts.
  It records a StewardIQ trigger for each failure, and the trigger can open an engagement like any other.
- The dossier's step 5 shows where this stands.

## Non-goals

- Changing steps 1–4, the research note, matching, extraction, review or the monitoring rules.
- Re-checking automatically: the check runs when a person presses **Check companies** (or calls the API).
- Closing a flag automatically when a company later meets the standard: flags follow the trigger lifecycle
  people already use (acknowledge, resolve).
- Standards for companies outside the exposed set, and a golden set for the drafts. The owner's approval is
  the quality gate.

## Anti-goals

- A standard that a person has to judge ("has a credible plan"). If a standard's criterion is not a
  comparison on a numeric, boolean or enum data point, the draft is rejected.
- Any path where the owner approves their own edit: four-eyes stays exactly as it is.
- A flag raised on missing data: no value means `no_data`, never a failure.
- A standards check that makes the monthly monitoring scheduler think the month already ran.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **A `theme_standards` StewardIQ policy per theme**, saved by the model, activated by the owner; failures become stored StewardIQ triggers. | Version log and activation audit for free; the owner redrafts by instruction instead of editing. | **Chosen by the owner** |
| B | Standards as rows in the house `monitoring_rules` table. | That table can't see extracted facts or exposure, and every change needs a second person. | Rejected |
| C | Standards stored in the dossier, the check writing triggers directly. | Simplest; no StewardIQ version or activation history. | Rejected |

## Position

Stored under `runs_dir/_positions/<dossier_id>/`: one immutable file per version, `v<n>.json`, plus an
append-only `approvals.jsonl`. A version:

```
{version, dossier_id, note_version, created_by: "model", created_at, instructions: str | null,
 summary: str, paragraphs: [{text: str, cites: [item_id, ...]}]}
```

- **Draft** `POST /api/dossiers/{id}/position/draft` `{instructions?}` (analyst). This needs an approved
  research note, otherwise 409 `research note not approved`. The model gets the note's items and, when a
  version exists, the latest version and the instructions. The result is validated before it is saved:
  at least one paragraph with non-blank text; each paragraph cites at least one item; every cited id is a
  note item (`unknown item '<id>'`); every note item is cited (`item '<id>' not cited`). If the draft fails
  validation, 502 `position draft invalid: <first failure>` and nothing is saved. If it passes, 200 and the
  version.
- **Approve** `POST /api/dossiers/{id}/position/approve` `{version}` (approver). Only the latest version can
  be approved, otherwise 409 `only the latest version can be approved (v<n>)`. Approving appends
  `{version, approved_by, approved_at}`. The approved position is the last row of the log.
- **Read** `GET /api/dossiers/{id}/position` (viewer) → `{versions: [...], approvals: [...], approved_version: int | null}`.

## Standards

A `theme_standards` policy in `arp/stewardship/policies.py`, stored per dossier in its own `PolicyStore`
under `stewardship_streams_dir/themes/<dossier_id>/` (a subfolder, so it is never read as a client stream).
Version 0 is `{"policy_id": "theme_standards", "standards": [], "schema": null}`. Content of a saved version:

```
{policy_id: "theme_standards", dossier_id, position_version,
 standards: [{standard_id: "S1", title, expectation, definition, where_reported,
              rests_on: [paragraph number, 1-based], severity: "low" | "medium" | "high",
              field_id, operator: ">=" | "<=" | ">" | "<" | "==", value, data: "existing" | "new"}],
 schema: DataPointSchema | null}
```

`schema` holds the new fields, with `schema_id` `theme_std_<dossier hex>`, and is null when every
standard uses an existing field.

- **Draft** `POST /api/dossiers/{id}/standards/draft` `{instructions?}` (analyst). This needs an approved
  position, otherwise 409 `position not approved`. The model gets the approved position, the released fields
  of the field registry (`field_id`, name, description, data type, unit, allowed values), the latest standards
  version when one exists, and the instructions. It is told that every standard needs a clear definition and
  a criterion that is easy to identify in company reports. It returns the standards and any new fields.
  The draft is saved through `PolicyStore.save(..., created_by="model")`, whose validator checks the
  following, failing on the first error with the message shown:
  - at least one standard; ids `S1`, `S2`, … unique;
  - `title`, `expectation`, `definition`, `where_reported` non-blank → `standard '<id>': <key> is blank`;
  - each `rests_on` entry is a paragraph of the approved position → `standard '<id>': position has no paragraph <n>`;
  - `data: "existing"`: `field_id` is a released registry field → `standard '<id>': unknown or unreleased field '<field_id>'`;
  - `data: "new"`: `field_id` is a field of `schema` → `standard '<id>': field '<field_id>' is not in the new schema`;
  - every `schema` field is used by a standard → `new field '<name>' is used by no standard`;
  - the criterion fits the field's data type. `number`, `percentage`, `currency_amount`: any operator with a
    numeric value. `boolean`: `==` with `true` or `false`. `enum`: `==` with one of its allowed values.
    `string` or `date`: `standard '<id>': field '<field_id>' is <type>, not checkable`. Otherwise
    `standard '<id>': operator '<op>' does not fit <type>`.

  If validation fails: 502 `standards draft invalid: <message>`, nothing saved. If it passes: 200
  `{version}`. How the new fields are drafted (one call, or reusing `draft_schema`) is the builder's choice.
- **Activate** `POST /api/dossiers/{id}/standards/activate` `{version}` (approver), in this order, stopping at
  the first failure:
  1. The version exists and is not 0, otherwise 404 `unknown standards version <n>`.
  2. Its `position_version` is the approved position, otherwise 409
     `standards v<n> rest on position v<a>; v<b> is approved`.
  3. The dossier's step 4 is `done`, otherwise 409 `find companies first`.
  4. If `schema` is not null: the schema is saved to the `SchemaRegistry` and released with `released_by`
     the approver. Then an extraction run on the exposed companies is created and scheduled the way
     `POST /api/extraction/runs` does it. If the run cannot be created: 502 `extraction could not start: <reason>`,
     and nothing is activated.
  5. `PolicyStore.activate(version, approved_by=<approver user_id>)`. The four-eyes check is unchanged and
     passes because the author is `model`.

  200 `{version, approved_by, approved_at, extraction_run_id: str | null}`.
- **Read** `GET /api/dossiers/{id}/standards` (viewer) →
  `{versions, activations, active_version, active, latest_check: {checked_at, results} | null}`.
- The generic `/api/stewardship/policies/theme_standards...` endpoints answer 404 `Unknown policy`. Theme
  standards are reached only through the dossier.

## Check

`POST /api/dossiers/{id}/standards/check` (analyst). This needs an active version > 0, otherwise 409
`no active standards`, and step 4 `done`, otherwise 409 `find companies first`.

For each exposed company and each active standard, the value is the company's current fact for `field_id`
with the latest `period_end` (a null `period_end` when the field has none). Facts are looked up by the
company's `entity_id`.

- `no_data`: no `entity_id`, no fact, or a fact whose state is `not_found` or `not_applicable`.
- `met` / `unmet`: the criterion applied to the value. A `zero` state means the value 0.

The response is `{checked_at, results: [{company_id, name, standard_id, value, period_end, result}],
flagged: <companies with at least one unmet>}`, ordered by company name, then by standard id.

Every `unmet` is recorded in the house `TriggerStore` (the StewardIQ streams root) as one run event for the
current month (`YYYY-MM`, UTC) with `kind: "theme_standards"` and `dossier_id`. Each trigger:

```
{issuer_id: <company_id>, company: <name>, sector: <the run company's sector, else "unknown">,
 type: "theme_standard", theme: <dossier name>, severity: <standard severity>,
 rule: "std:<dossier_id>:<standard_id>",
 reason: "<title>: <value>, expected <operator> <value>"}
```

Values in `reason` print as JSON scalars (`true`, `20`, `"B"`). The same company and standard keep their
trigger id across checks. `TriggerStore.last_run_at` ignores runs whose `kind` is `theme_standards`, so the
monthly scheduler's "already ran" test sees only monitoring runs. The check's results are kept as the
dossier's latest check (a file next to the positions) for `GET .../standards` and step 5's detail.

## Dossier step 5 (replaces `not_built`)

The first matching line wins:

1. Step 3 is not `done` → `not_started`, detail `research note not approved`.
2. No position version → `not_started`, `draft the position`.
3. The latest position version is not approved → `waiting`, `approve position v<n>`.
4. No standards version > 0 → `not_started`, `draft standards`.
5. The latest standards version > the active version → `waiting`, `approve standards v<n>`.
6. The active version's `position_version` ≠ the approved position → `waiting`,
   `standards rest on position v<a>, v<b> approved`.
7. The active version has a schema; the newest extraction run on that `schema_id` is `pending` or `running`
   → `running`, `extracting <k> data points` (k = the schema's field count); `failed` or `cancelled` →
   `failed`, `extraction <status>`; completed with open review items → `waiting`, `<n> to review`.
8. No check since the last activation (or since that run finished) → `waiting`, `check companies`.
9. Otherwise `done`, `<s> standards · <f> flagged` (from the latest check).

`href` for step 5: `#/themes/<id>/position`. On screen `not_built` no longer appears for step 5.

## Screens

- `#/themes/<id>/position`, **Position and standards**, in two sections:
  - **Position**: the latest version's summary and paragraphs, each with its cited items (`R1 · <title>`),
    the version and its state (`Draft` or `Approved by <name>`). **Draft position** when there is none; an
    **Instructions** box with **Redraft**; **Approve** shown only to approvers on an unapproved latest version.
  - **Standards**: a table of the latest version with columns `Standard`, `Definition`, `Where reported`,
    `Criterion` (`<field name> <operator> <value>`), `Data` (`Existing field` or `New field`), `Severity`,
    `Rests on`. **Draft standards**, **Instructions** + **Redraft**, **Approve** (approvers only), and once
    active **Check companies** with the latest results as a company × standard grid reading `Met`, `Unmet`,
    `No data`.
- StewardIQ's **Monitoring** studio gains a **Theme standards** table: the open stored triggers of type
  `theme_standard`, with columns company, theme, standard (the rule's last segment), severity, reason, and
  the existing **Open engagement** action (which already falls back to stored triggers).

## My calls (owner to confirm with the acceptance table)

1. **The model is the author, the owner is the approver.** Every saved version has `created_by: "model"`;
   approve and activate need the `approver` role. No user may be called `model`.
2. **Only the latest version can be approved or activated after a redraft**, so the screen always shows what
   is approved.
3. **One criterion per standard, on one field.** A two-part expectation becomes two standards.
4. **The latest `period_end` counts**, whatever its age. Standards don't test staleness.
5. **A failed draft is not saved and not retried**: the person presses Redraft.
6. **Triggers live in the house trigger store**, with the dossier name as their theme, so engagements opened
   from them carry the theme's name.
7. **Exposed means step 4 `done`**: no pending review and the run on the latest ratified taxonomy version.

## Constraints

- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`; API contract regenerated and committed.
- The model client comes from the `get_llm_client` dependency in `arp/api/deps.py`, so tests can replace it.
- Postgres is required for the registry, facts and extraction; the endpoints return 503 like the other
  registry endpoints when it is not configured.

## Left to the builder

The prompts; how new fields are drafted; file names for the latest check; the page's components and layout
within DESIGN.md; how the extraction run is scheduled (reusing the extraction router's code path).

## Acceptance

Fixture, seeded through the backend's own stores. Users `own` (approver), `ana` (analyst), `vic` (viewer).
Dossier `D` (name `Grid electrification`) with taxonomy `tax_a`, v1 ratified. Its newest theme run on
`tax_a` v1 is `completed` with 0 pending review items, and its companies are:
- `C1` "Alpha", with `entity_id` `e1`, has matches;
- `C2` "Beta", with `e2`, has matches;
- `C3` "Gamma", with no `entity_id`, has matches;
- `C4` "Delta", with `e4`, has no matches.

Step 3: an approved research note version 1 for `D`, with items `R1` risk, `R2` risk and `O1` opportunity,
seeded through step 3's store. Field registry: released `fld_scope3` (boolean, "Scope 3 emissions
disclosed") and `fld_grid_capex` (percentage, "Grid capex share"), and draft `fld_draft` (number).
Current facts: `e1` `fld_scope3` true, `e1` `fld_grid_capex` 25; `e2` `fld_scope3` false, no
`fld_grid_capex`.

The model is replaced through `get_llm_client` by a stand-in returning scripted outputs and recording the
prompts. **P-ok** is a position with two paragraphs, citing `[R1, O1]` and `[R2]`. **S-ok** is three
standards resting on paragraph 1:
- `S1`: `fld_scope3 == true`, severity `high`, title `Scope 3 emissions disclosed`;
- `S2`: `fld_grid_capex >= 20`, `medium`;
- `S3`: a new boolean field "Board-approved transition plan" `== true`, `low`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `D` with no approved research note | `ana` `POST /api/dossiers/D/position/draft` | 409, detail `research note not approved`; the model was not called | holdout |
| AC-2 | fixture; model returns P-ok | `ana` drafts the position | 200; `version` 1, `created_by` `model`, `note_version` 1, `instructions` null, 2 paragraphs | holdout |
| AC-3 | model returns P-ok with `R1` replaced by `X9` | draft | 502, detail `position draft invalid: unknown item 'X9'`; `GET .../position` has no versions | holdout |
| AC-4 | model returns P-ok without `O1` | draft | 502, detail `position draft invalid: item 'O1' not cited` | holdout |
| AC-5 | AC-2's v1 | draft with `{"instructions": "Stress grid permitting delays"}` | 200, `version` 2, `instructions` stored; the prompt sent to the model contains `Stress grid permitting delays` and v1's first paragraph text | holdout |
| AC-6 | AC-2's v1 | approve v1 as `ana`; then as `own` | 403; then 200 with `version` 1, `approved_by` `own`; `GET .../position` `approved_version` 1 | holdout |
| AC-7 | AC-5's v2 exists | `own` approves v1 | 409, detail `only the latest version can be approved (v2)` | holdout |
| AC-8 | no approved position | `ana` `POST .../standards/draft` | 409, detail `position not approved` | holdout |
| AC-9 | approved position v1; model returns S-ok | `ana` drafts standards | 200 `{version: 1}`; `GET .../standards` version 1 has `created_by` `model`; `S1`, `S2` `data` `existing`; `S3` `data` `new` with `field_id` equal to the only field of `schema`; `schema.schema_id` starts with `theme_std_`; `active_version` 0 | holdout |
| AC-10 | as AC-9, with `S1`'s field changed to `fld_draft` | draft | 502, detail `standards draft invalid: standard 'S1': unknown or unreleased field 'fld_draft'` | holdout |
| AC-11 | as AC-9, with `S1`'s operator changed to `>=` | draft | 502, detail `standards draft invalid: standard 'S1': operator '>=' does not fit boolean` | holdout |
| AC-12 | as AC-9, with `S2`'s `definition` set to `" "` | draft | 502, detail `standards draft invalid: standard 'S2': definition is blank` | holdout |
| AC-13 | as AC-9, with `S1`'s `rests_on` set to `[9]` | draft | 502, detail `standards draft invalid: standard 'S1': position has no paragraph 9` | holdout |
| AC-14 | as AC-9, plus an unused new field "Spare" | draft | 502, detail `standards draft invalid: new field 'Spare' is used by no standard` | holdout |
| AC-15 | as AC-9, with a released string field `fld_name` used by `S1` with `==` | draft | 502, detail `standards draft invalid: standard 'S1': field 'fld_name' is string, not checkable` | holdout |
| AC-16 | AC-9's v1 | `ana` activates v1 | 403; `active_version` stays 0 | holdout |
| AC-17 | AC-9's v1 | `own` activates v1 | 200; `approved_by` `own`; `extraction_run_id` non-null; that run's manifest companies are `C1`, `C2`, `C3` (not `C4`); the schema is released with `released_by` `own`; `active_version` 1 | holdout |
| AC-18 | S-ok without `S3` (no new fields), drafted as v1 | `own` activates | 200, `extraction_run_id` null; no extraction run was created | holdout |
| AC-19 | AC-9's v1; the newest theme run has 2 pending review items | `own` activates | 409, detail `find companies first`; `active_version` 0 | holdout |
| AC-20 | AC-9's v1 rests on position v1; position v2 drafted and approved | `own` activates v1 | 409, detail `standards v1 rest on position v1; v2 is approved` | holdout |
| AC-21 | `own` activates version 7 (none) | — | 404, detail `unknown standards version 7` | holdout |
| AC-22 | AC-18 active | `ana` `POST .../standards/check` | 200; `results` (company, standard, result): Alpha S1 `met`, Alpha S2 `met`, Beta S1 `unmet`, Beta S2 `no_data`, Gamma S1 `no_data`, Gamma S2 `no_data`; Delta absent; `flagged` 1 | holdout |
| AC-23 | AC-22 | `GET /api/stewardship/triggers` | exactly one trigger with `rule` starting `std:`: `issuer_id` `C2`, `type` `theme_standard`, `theme` `Grid electrification`, `severity` `high`, `rule` `std:D:S1`, `reason` `Scope 3 emissions disclosed: false, expected == true`, `status` `open` | holdout |
| AC-24 | AC-22 | check again | still exactly one `std:` trigger, with the same `trigger_id` | holdout |
| AC-25 | AC-23's trigger | `POST /api/stewardship/monitoring/open-engagement {"issuer_id": "C2", "rule": "std:D:S1"}` | 200; the new issue's theme is `Grid electrification` and its severity `high` | holdout |
| AC-26 | no active standards | check | 409, detail `no active standards` | holdout |
| AC-27 | AC-22's check ran in the current month; holdings loaded before it | the monthly monitoring scheduler runs that month | the monitoring run executes (it is not skipped as already run) | holdout |
| AC-28 | fixture without an approved note | `GET /api/dossiers/D` | step 5 `not_started`, detail `research note not approved`, `href` `#/themes/D/position` | holdout |
| AC-29 | approved note, no position | `GET` | step 5 `not_started`, `draft the position` | holdout |
| AC-30 | AC-2 | `GET` | step 5 `waiting`, `approve position v1` | holdout |
| AC-31 | AC-6 (approved), no standards | `GET` | step 5 `not_started`, `draft standards` | holdout |
| AC-32 | AC-9 | `GET` | step 5 `waiting`, `approve standards v1` | holdout |
| AC-33 | AC-17, its extraction run `running` | `GET` | step 5 `running`, `extracting 1 data points` | holdout |
| AC-34 | AC-17, its extraction run `failed` | `GET` | step 5 `failed`, `extraction failed` | holdout |
| AC-35 | AC-18 active, not checked | `GET` | step 5 `waiting`, `check companies` | holdout |
| AC-36 | AC-22 | `GET` | step 5 `done`, `2 standards · 1 flagged`; `GET /api/dossiers` `current_step` for `D` is `null` | holdout |
| AC-37 | AC-22, then position v2 drafted and approved | `GET` | step 5 `waiting`, `standards rest on position v1, v2 approved` | holdout |
| AC-38 | caller `vic` | `GET .../position`, `GET .../standards`; `POST` draft, approve, activate, check | 200, 200; 403 on every `POST` | holdout |
| AC-39 | the running app, AC-2's state, signed in as `own` | open `D`'s dossier page, click step 5's link | `#/themes/D/position` opens; the Position section shows 2 paragraphs, the first citing `R1` and `O1` by title, state `Draft`, and an **Approve** button | evaluator |
| AC-40 | AC-39 signed in as `ana` | open the page | no **Approve** button; **Redraft** with an **Instructions** box is present | evaluator |
| AC-41 | AC-9's state | open the page | the Standards table has columns `Standard`, `Definition`, `Where reported`, `Criterion`, `Data`, `Severity`, `Rests on`; `S3` reads `New field` | evaluator |
| AC-42 | AC-18 active | click **Check companies** | a grid of Alpha, Beta, Gamma × S1, S2 reading `Met`, `Met` / `Unmet`, `No data` / `No data`, `No data` | evaluator |
| AC-43 | AC-23 | open StewardIQ's Monitoring studio | a **Theme standards** table lists Beta, `Grid electrification`, `S1`, `high`, `Scope 3 emissions disclosed: false, expected == true`, with **Open engagement** | evaluator |
| AC-44 | AC-28's dossier page | read step 5 | it reads `Not started` and `research note not approved`, not `Coming later` | evaluator |

Must not change:
- AC-45: a house `monitoring_rules` version saved by `ana` and activated by `ana` → 422 with detail
  `Four-eyes rule: a version must be activated by someone other than the person who saved it`; activated by
  `own` → 200. Checked by: holdout.
- AC-46: `GET /api/stewardship/policies/theme_standards` → 404, detail `Unknown policy`; the other five
  policies still answer 200. Checked by: holdout.
- AC-47: `GET /api/stewardship/triggers` returns the triggers of a monthly monitoring run with the same
  keys and values as before. Checked by: holdout.
- AC-48: dossier steps 1–4 derive exactly as in the dossier spec (its AC-2 through AC-31 still pass, except
  that step 5's `state`, `detail` and `href`, and `current_step` where step 5 is no longer skipped, follow this spec). Checked by: holdout.
