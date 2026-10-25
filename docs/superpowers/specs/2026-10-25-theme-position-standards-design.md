# Theme position and standards (step 5 of the theme process)

Status: draft, 2026-10-25 (revised after builder check and spec-critic).

## Where this sits

This is step 5 of the five-step theme process in `2026-10-25-theme-dossier-design.md`. That spec shows step 5
as `not_built`. This spec builds step 5 and replaces only step 5's derivation. **Build it after the dossier
and step 3 are on `main`**: every endpoint here lives under `/api/dossiers/{id}`.

Inputs:

- **The theme's research note (step 3).** That step has its own spec. This feature uses only three things
  from it. First, the note's approved versions: a version number, plus who approved it and when. Second,
  each version's items, `{item_id, kind: "risk" | "opportunity", title, summary}`. Third, the rule that
  step 3 is `done` when the note has an approved version. "The approved note" means the note's newest
  approved version. If step 3 names these fields differently, map them; add no others.
- **The exposed companies (step 4).** When the dossier's step 4 is `done`, these are the companies with at
  least one entry in `company_matches`, taken from the newest counted theme run of the dossier's taxonomy.
  Each company's `company_id`, `entity_id`, `name` and `sector` come from the run.

## Owner decisions (2026-10-25)

1. **Position.** The position is a comprehensive house position and narrative on the theme. The model drafts
   it from the research note's risks and opportunities.
2. **Standards.** Standards are the stewardship expectations for exposed companies, derived from the approved
   position. A standard is admissible only if it has **a clear definition and criteria that are easy to
   identify in company reports**.
3. **Data is the main job.** Each standard is matched to an existing data point. Where none exists, a
   data-point schema is drafted for it. Once the standards are approved, step 5 **runs the extraction** of
   the new data points on the exposed companies.
4. **Flags.** Companies that fail a standard are **flagged in StewardIQ**.
5. **One approver, the owner.**
6. **Approach A plus direct edits.** There are two paths, and the owner picks one per draft:
   - **Redraft.** The owner sends instructions and the model redrafts. The model stays the author, so the
     unchanged four-eyes check passes when the owner activates.
   - **Edit.** The owner edits the draft and saves it as their own version, then activates it alone. This
     single-approver exception applies to `theme_standards` only. The activation record says which path was
     used.

   Four-eyes stays as it is for every other policy.

## Intent

Today the theme process ends at a reviewed company list. Nothing says what the house thinks about the theme,
or what it expects of those companies. Step 5 turns the research into a stated position. It then turns the
position into expectations that a machine can check against reported data, and creates that data where it is
missing. The result is a traceable chain:
research item → position paragraph → standard → data point → company flag.

## Goals

- The model drafts a position from the approved note. Every paragraph cites the note items it rests on, and
  every note item is cited. The owner approves it, asks for a redraft, or edits it.
- The model drafts standards from the approved position. Each standard has a definition, where it is
  reported, one criterion on one data point, a severity, and the position paragraphs it rests on.
- Each standard is matched to a **released field** of the field registry. Where no field fits, it is matched
  to a field of the theme's data-point schema, which is drafted together with the standards.
- On activation the schema is released, and an extraction run starts on the exposed companies.
- A check evaluates each exposed company against each active standard, using reviewed company facts. Each
  failure becomes a StewardIQ trigger, from which an engagement can be opened.
- The dossier's step 5 shows where all of this stands.

## Non-goals

- Changing steps 1–4, the research note, matching, extraction or review.
- Changing the monitoring rules.
- Re-checking automatically. A person runs the check.
- Changing a flag's status automatically. Only people acknowledge or resolve flags; re-checks never change
  the status.
- Standards for companies outside the exposed set.
- A golden set for the drafts. The owner's approval is the quality gate.

## Anti-goals

- **A standard a person has to judge** ("has a credible plan"). A criterion that is not a comparison on a
  numeric, boolean or enum data point is rejected.
- **Weakening four-eyes for any policy other than `theme_standards`**, or a single-approver activation that
  the audit trail does not show.
- **A flag on missing or unreviewed data.** No value, or a value still in review, means `no_data`.
- **A standards check that changes how monitoring triggers or the monthly scheduler behave.**

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **A `theme_standards` StewardIQ policy per theme**: the model saves it and the owner activates it. Failures become stored StewardIQ triggers. | The version log and activation audit come for free. | **Chosen by the owner**, with direct edits as a second path |
| B | Standards as rows in the house `monitoring_rules` table. | That table can't see extracted facts or exposure, and every change needs a second person. | Rejected |
| C | Standards stored in the dossier, with the check writing triggers directly. | Simplest, but leaves no StewardIQ version or activation history. | Rejected |

## Model calls (stand-in contract)

Each draft makes **exactly one** call to `LLMClient.complete_structured`, using the client from the
`get_llm_client` dependency in `arp/api/deps.py`. The `output_model` is:

- **`PositionDraft`**: `{summary: str, paragraphs: [{text: str, cites: [str]}]}`.
- **`StandardsDraft`**: `{standards: [<standard, as stored below>], new_fields: [FieldDefinition]}`.
  `FieldDefinition` is the existing class in `arp/schemas/datapoints.py`.

Tests replace the client through the dependency and script these two shapes.

## Position

Positions are stored under `runs_dir/_positions/<dossier_id>/`: one immutable `v<n>.json` per version, plus
an append-only `approvals.jsonl`. A version looks like this:

```
{version, dossier_id, note_version, created_by, created_at, path: "model_draft" | "owner_edit",
 instructions: str | null, summary: str, paragraphs: [{text: str, cites: [item_id, ...]}]}
```

The same validation applies on every path. It stops at the first failure, with these messages:

- `no paragraphs`
- `paragraph <n> is blank`
- `paragraph <n> cites nothing`
- `unknown item '<id>'`
- `item '<id>' not cited`

Endpoints:

- **Draft.** `POST /api/dossiers/{id}/position/draft` `{instructions?}`, analyst role.
  - Needs an approved note, otherwise 409 `research note not approved`.
  - The model gets:
    - the note's items;
    - when a version exists, the latest version and the instructions.
  - Saved with `created_by` `model` and `path` `model_draft`.
  - If validation fails: 502 `position draft invalid: <message>`, and nothing is saved.
- **Edit.** `POST /api/dossiers/{id}/position/versions` `{summary, paragraphs}`, approver role.
  - Saved with `created_by` set to the caller and `path` `owner_edit`.
  - `note_version` is the approved note.
  - If validation fails: 422 `<message>`.
- **Approve.** `POST /api/dossiers/{id}/position/approve` `{version}`, approver role.
  - Only the latest version can be approved, otherwise 409 `only the latest version can be approved (v<n>)`.
  - Its `note_version` must be the approved note, otherwise 409
    `position v<n> rests on note v<a>; v<b> is approved`.
  - Approving appends `{version, approved_by, approved_at}` to the log. The approved position is the version
    in the log's last row.
- **Read.** `GET /api/dossiers/{id}/position`, viewer role. Returns
  `{versions: [...], approvals: [...], approved_version: int | null}`.

## Standards

Standards are a new `theme_standards` policy in `arp/stewardship/policies.py`. Each dossier has its own
`PolicyStore`, under `stewardship_streams_dir/themes/<dossier_id>/`. Being a subfolder, it is never read as a
client stream. Version 0 is `{"policy_id": "theme_standards", "standards": [], "schema": null}`.

A saved version's content:

```
{policy_id: "theme_standards", dossier_id, position_version, path: "model_draft" | "owner_edit",
 standards: [{standard_id: "S1", title, expectation, definition, where_reported,
              rests_on: [paragraph number, 1-based], severity: "low" | "medium" | "high",
              field_id, operator: ">=" | "<=" | ">" | "<" | "==", value, data: "existing" | "new"}],
 schema: DataPointSchema | null}
```

### The theme schema

- There is one schema per dossier, with `schema_id` `theme_std_<dossier hex>`.
- A version's `schema` holds:
  - every field of the theme schema that an earlier activation already released, unchanged;
  - plus that version's new fields.
- A version with new fields becomes the next version of that schema when it is activated.
- `schema` is null while the theme has no fields of its own.
- Fields that an earlier activation released are registry fields, so the model sees them among the
  existing fields.
- Criterion values are in the field's canonical unit, as facts store it.
- A theme field that is already released is used with `data: "existing"`. `data: "new"` is only for
  fields not yet released.

### Validation (all paths)

`PolicyStore.save` runs this validator. It stops at the first failure, with these messages:

- **Standard ids.** At least one standard, with ids `S1`…`Sn` in order: `standard ids must be S1..Sn`.
- **Required text.** `title`, `expectation`, `definition` and `where_reported` must not be blank:
  `standard '<id>': <key> is blank`.
- **Position paragraphs.** Each `rests_on` entry must be a paragraph of the approved position:
  `standard '<id>': position has no paragraph <n>`.
- **Existing data.** With `data: "existing"`, `field_id` must be a released registry field, including
  released theme fields: `standard '<id>': unknown or unreleased field '<field_id>'`.
- **New data.** With `data: "new"`, `field_id` must be a field of `schema`:
  `standard '<id>': field '<field_id>' is not in the new schema`.
  It must also not be released yet: `standard '<id>': field '<field_id>' is released, use data "existing"`.
- **Unused fields.** Every field in `schema` that has not yet been released must be used:
  `new field '<name>' is used by no standard`.
- **Criterion fits the data type.**
  - `number`, `percentage` and `currency_amount` accept any operator, with a numeric value.
  - `boolean` accepts only `==` with `true` or `false`.
  - `enum` accepts only `==` with one of the field's allowed values.
  - A wrong operator for the type fails with `standard '<id>': operator '<op>' does not fit <type>`.
  - A wrong value fails with `standard '<id>': value <value> does not fit <type>`.
  - `string` and `date` fields fail with `standard '<id>': field '<field_id>' is <type>, not checkable`.
  - In messages, `<value>` prints as a JSON scalar, as in a trigger's `reason`.

### Endpoints

- **Draft.** `POST /api/dossiers/{id}/standards/draft` `{instructions?}`, analyst role.
  - Needs an approved position, otherwise 409 `position not approved`.
  - The model gets:
    - the approved position;
    - the released registry fields (`field_id`, name, description, data type, unit, allowed values);
    - the latest standards version, when one exists;
    - the instructions;
    - the rule that every standard needs a clear definition and a criterion that is easy to identify in
      company reports.
  - Saved with `created_by` `model` and `path` `model_draft`.
  - If validation fails: 502 `standards draft invalid: <message>`, and nothing is saved.
  - Otherwise: 200 `{version}`.
- **Edit.** `POST /api/dossiers/{id}/standards/versions` `{standards, new_fields}`, approver role. The
  body has the same shape as `StandardsDraft`.
  - The server builds the version the same way as for a model draft: it sets `policy_id`, `dossier_id`,
    `position_version` (the approved position) and `schema`.
  - Saved with `created_by` set to the caller and `path` `owner_edit`.
  - If validation fails: 422 `<message>`.
  - Otherwise: 200 `{version}`.
- **Activate.** `POST /api/dossiers/{id}/standards/activate` `{version}`, approver role. The steps run in
  order and stop at the first failure:
  1. The version must exist and not be 0, otherwise 404 `unknown standards version <n>`.
  2. Its `position_version` must be the approved position, otherwise 409
     `standards v<n> rest on position v<a>; v<b> is approved`.
  3. The dossier's step 4 must be `done`, otherwise 409 `find companies first`.
  4. If `schema` is not null:
     - **Release.** If `schema` has fields that are not yet released, it is saved to the `SchemaRegistry`
       as the next version of `theme_std_<hex>` and released, with `released_by` set to the approver.
     - **Extract.** If no extraction run exists yet on the schema version this standards version uses, a
       run of that whole schema version is created on the exposed companies. Runs are started through
       the callable that a new `get_extraction_starter` dependency in `arp/api/deps.py` returns, called
       as `(schema, companies, settings) -> run_id`. It creates and schedules the run the way
       `POST /api/extraction/runs` does, and tests override it.
     - **Failure.** If the run cannot be created: 502 `extraction could not start: <reason>`, and nothing
       is activated. A released schema version stays released. A retry then finds no run on it and
       starts one.
  5. `PolicyStore.activate` runs with `approved_by` set to the approver.
     - **Model draft:** the unchanged four-eyes check passes, because the author is `model`.
     - **Owner edit:** for `theme_standards` only, `activate` accepts an approver who is also the author.
     - In both cases the activation row also records `path`.
     - No user may have the user_id `model`. Loading a users file that has one raises a `RuntimeError`
       whose message contains `user id 'model' is reserved`, which the API answers with a 503.
  - Response: 200 `{version, approved_by, approved_at, path, extraction_run_id: str | null}`.
- **Read.** `GET /api/dossiers/{id}/standards`, viewer role. Returns
  `{versions, activations, active_version, active, latest_check: {checked_at, results, flagged} | null}`.
- **Generic endpoints.** The generic `/api/stewardship/policies/theme_standards...` endpoints answer 404
  `Unknown policy`.

## Check

`POST /api/dossiers/{id}/standards/check`, analyst role.

- Needs an active version above 0, otherwise 409 `no active standards`.
- Needs step 4 `done`, otherwise 409 `find companies first`.

For each exposed company and each active standard, the value comes from the company's current facts
(`valid_to` null) for `field_id`, looked up by `entity_id`:

- Only facts with status `auto_accepted`, `approved` or `edited` count.
- The fact with the latest `period_end` wins; a null `period_end` counts as the only period.
- If several bases share that period, the most recently recorded fact wins.

Each pair gets one of these results:

- **`no_data`**: there is no `entity_id`, no counting fact, or the fact's state is `not_found` or
  `not_applicable`.
- **`met` / `unmet`**: the criterion applied to the value. A `zero` state counts as the value 0.

The response is `{checked_at, results: [{company_id, name, standard_id, value, period_end, result}],
flagged: int}`. `flagged` is the number of companies with at least one `unmet`. Results are ordered by company
name, then standard id.

When there is at least one `unmet`, the check appends one event to the house `TriggerStore` (the StewardIQ
streams root):

```
{"event": "standards", "dossier_id", "checked_at", "triggers": [
  {issuer_id: <company_id>, company: <name>, sector: <the run company's sector, else "unknown">,
   type: "theme_standard", theme: <dossier name>, severity: <standard severity>,
   rule: "std:<dossier_id>:<standard_id>",
   reason: "<title>: <value>, expected <operator> <value>"}]}
```

How the store treats these events:

- **Trigger lifecycle.** The fold creates an `open` trigger the first time a (company, rule) pair appears.
  Later standards events never change its status, `is_new` or `first_seen_month`; only people do. The
  `first_seen_month` is the month of `checked_at`.
- **Kept apart from monitoring.** Standards events are ignored by everything that reads `run` events:
  month ordering, reopening, `is_new` and `last_run_at`. So monitoring triggers and the monthly scheduler
  behave exactly as before.
- **`reason` format.** Values print as JSON scalars, such as `true`, `20` or `"B"`.

The check's response is also kept as the dossier's latest check, a file next to the positions.

## Dossier step 5 (replaces `not_built`)

The first matching line wins:

1. Step 3 is not `done` → `not_started`, detail `research note not approved`.
2. There is no position version → `not_started`, `draft the position`.
3. The latest position version is not approved → `waiting`, `approve position v<n>`.
4. The approved position's `note_version` is older than the approved note → `waiting`,
   `position rests on note v<a>, v<b> approved`.
5. There is no standards version above 0 → `not_started`, `draft standards`.
6. The latest standards version is newer than the active version → `waiting`, `approve standards v<n>`.
7. The active version's `position_version` is not the approved position → `waiting`,
   `standards rest on position v<a>, v<b> approved`.
8. The active version started an extraction run. Take the newest extraction run on `theme_std_<hex>`:
   - `pending` or `running` → `running`, `extracting <k> data points`, where k is the schema version's
     field count;
   - `failed` or `cancelled` → `failed`, `extraction <status>`;
   - completed with open review items → `waiting`, `<n> to review`.
9. There has been no check since the last activation, or since that run finished → `waiting`,
   `check companies`.
10. Otherwise → `done`, `<s> standards · <f> flagged`, from the latest check.

Step 5's `href` is `#/themes/<id>/position`. Step 5 no longer shows `not_built`.

## Screens

- **`#/themes/<id>/position`, "Position and standards".** Two sections:
  - **Position.** Shows the latest version's summary and paragraphs, each with its cited items
    (`R1 · <title>`), plus the version number and its state: `Draft by model`, `Draft by <name>` or
    `Approved by <name>`. Actions:
    - **Draft position**, when there is no version yet;
    - an **Instructions** box with **Redraft**;
    - **Edit**, for approvers, which saves a new version;
    - **Approve**, for approvers, on an unapproved latest version.
  - **Standards.** A table of the latest version with columns `Standard`, `Definition`, `Where reported`,
    `Criterion` (`<field name> <operator> <value>`), `Data` (`Existing field` or `New field`), `Severity`
    and `Rests on`. Actions:
    - **Draft standards**, **Instructions** with **Redraft**, **Edit** (approvers only) and **Approve**
      (approvers only);
    - once standards are active, **Check companies**, which shows the latest results as a company ×
      standard grid reading `Met`, `Unmet` or `No data`.
- **StewardIQ Monitoring studio.** Gains a **Theme standards** table listing the open stored triggers of
  type `theme_standard`. Columns: company, theme, standard (the last segment of the rule), severity and
  reason. Each row has the existing **Open engagement** action, which already falls back to stored triggers.

## My calls (owner to confirm with the acceptance table)

1. **Only the latest version can be approved or activated.** The screen therefore always shows what is
   approved.
2. **One criterion per standard, on one field.** A two-part expectation becomes two standards.
3. **The latest reviewed `period_end` counts, whatever its age.** Standards don't test staleness, and values
   still in review count as `no_data`.
4. **A failed model draft is not saved and not retried.** The person presses Redraft or edits instead.
5. **Triggers live in the house trigger store**, with the dossier name as their theme, so engagements opened
   from them carry the theme's name.
6. **Exposed means step 4 is `done`.** That means no pending review, and a run on the latest ratified
   taxonomy version.
7. **Activation extracts the whole theme schema version**, not just the newly added fields. This costs
   more, but keeps one run per version, so step 5's state reads from a single run.
8. **A position resting on an older approved note is stale.** Step 5 shows it, and approving it is refused.

## Constraints

- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`. The API contract is regenerated
  and committed.
- Postgres is required for the registry, facts and extraction. Without a DSN, the standards draft, edit,
  activate and check endpoints answer 503
  `ARP_POSTGRES_DSN is required: Postgres is the system of record.` Order of checks: the role check (403) and request-body validation (422) come first, then this 503, then any
  404 or 409.
  The position endpoints are unaffected.

## Left to the builder

- The prompts.
- The file name for the latest check.
- The page's components and layout, within DESIGN.md.
- How the extraction run is scheduled. It should reuse the extraction router's code path.

## Acceptance

Fixture, seeded through the backend's own stores.

- **Users.** `own` (approver), `ana` (analyst), `vic` (viewer).
- **Dossier `D`.** Name `Grid electrification`, taxonomy `tax_a`, with version 1 ratified. Its newest theme
  run on `tax_a` v1 is `completed`, with 0 pending review items. The run's companies:
  - `C1` "Alpha" (`entity_id` `e1`, sector `Utilities`), with matches;
  - `C2` "Beta" (`e2`, `Utilities`), with matches;
  - `C3` "Gamma" (no `entity_id`), with matches;
  - `C4` "Delta" (`e4`), without matches.
- **Research note.** Approved version 1 for `D`, seeded through step 3's store. Its items:
  - `R1` risk "Permitting delays";
  - `R2` risk "Supply-chain bottlenecks";
  - `O1` opportunity "Grid capex boom".
- **Field registry.**
  - released `fld_scope3` (boolean, "Scope 3 emissions disclosed");
  - released `fld_grid_capex` (percentage, "Grid capex share");
  - released `fld_rating` (enum `A`, `B`, `C`);
  - released `fld_name` (string);
  - draft `fld_draft` (number).
- **Current facts.**
  - `e1`: `fld_scope3` true (`approved`), `fld_grid_capex` 25 (`auto_accepted`);
  - `e2`: `fld_scope3` false (`approved`), `fld_grid_capex` with state `not_found`.

The model is replaced through `get_llm_client` by a stand-in that returns scripted `PositionDraft` and
`StandardsDraft` outputs and records the prompts.

**P-ok** is a position with two paragraphs: the first cites `[R1, O1]`, the second `[R2]`.

**S-ok** is three standards, all resting on paragraph 1:

- `S1`: `fld_scope3 == true`, severity `high`, title `Scope 3 emissions disclosed`;
- `S2`: `fld_grid_capex >= 20`, severity `medium`;
- `S3`: a new boolean field "Board-approved transition plan" `== true`, severity `low`.

**S-two** is S-ok without `S3`.

Evaluator rows get their state seeded through the same stores (position files and `PolicyStore.save` with
`created_by` `model`), never through the real model.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `D` with no approved note | `ana` `POST /api/dossiers/D/position/draft` | 409, detail `research note not approved`; the stand-in received no call | holdout |
| AC-2 | fixture; model returns P-ok | `ana` drafts the position | 200; `version` 1, `created_by` `model`, `path` `model_draft`, `note_version` 1, `instructions` null, 2 paragraphs | holdout |
| AC-3 | model returns P-ok with `R1` replaced by `X9` | draft | 502, detail `position draft invalid: unknown item 'X9'`; `GET .../position` `versions` is empty | holdout |
| AC-4 | model returns P-ok with `O1` removed | draft | 502, detail `position draft invalid: item 'O1' not cited` | holdout |
| AC-5 | model returns `paragraphs: []` | draft | 502, detail `position draft invalid: no paragraphs` | holdout |
| AC-6 | model returns P-ok with paragraph 2's `cites` `[]` | draft | 502, detail `position draft invalid: paragraph 2 cites nothing` | holdout |
| AC-7 | AC-2's v1 | draft with `{"instructions": "Stress grid permitting delays"}` | 200, `version` 2, `instructions` equals `Stress grid permitting delays` | holdout |
| AC-8 | AC-7 | read the stand-in's recorded prompt for v2 | it contains `Stress grid permitting delays` and v1's first paragraph text | holdout |
| AC-9 | AC-2's v1 | `ana` approves v1 | 403; `approved_version` null | holdout |
| AC-10 | AC-2's v1 | `own` approves v1 | 200, `approved_by` `own`; `GET .../position` `approved_version` 1 | holdout |
| AC-11 | AC-7's v2 exists | `own` approves v1 | 409, detail `only the latest version can be approved (v2)` | holdout |
| AC-12 | AC-2's v1 | `own` `POST .../position/versions` with P-ok's paragraphs, the first text changed | 200, `version` 2, `created_by` `own`, `path` `owner_edit` | holdout |
| AC-13 | AC-12's v2 | `own` approves v2 | 200, `approved_by` `own` | holdout |
| AC-14 | — | `ana` `POST .../position/versions` | 403 | holdout |
| AC-15 | — | `own` `POST .../position/versions` with P-ok minus `O1` | 422, detail `item 'O1' not cited` | holdout |
| AC-16 | AC-10; then note v2 approved in step 3 | `GET /api/dossiers/D` | step 5 `waiting`, `position rests on note v1, v2 approved` | holdout |
| AC-17 | AC-16 | `own` approves position v1 | 409, detail `position v1 rests on note v1; v2 is approved` | holdout |
| AC-18 | no approved position | `ana` `POST .../standards/draft` | 409, detail `position not approved` | holdout |
| AC-19 | approved position v1; model returns S-ok | `ana` drafts standards | 200 `{version: 1}`; `active_version` 0 | holdout |
| AC-20 | AC-19 | `GET .../standards` | version 1: `created_by` `model`, `path` `model_draft`; `S1`, `S2` `data` `existing`; `S3` `data` `new` with `field_id` equal to the only field of `schema`; `schema.schema_id` starts with `theme_std_` | holdout |
| AC-21 | S-ok with `S1`'s field `fld_draft` | draft | 502, detail `standards draft invalid: standard 'S1': unknown or unreleased field 'fld_draft'` | holdout |
| AC-22 | S-ok with `S1`'s operator `>=` | draft | 502, detail `standards draft invalid: standard 'S1': operator '>=' does not fit boolean` | holdout |
| AC-23 | S-ok with `S2`'s `definition` `" "` | draft | 502, detail `standards draft invalid: standard 'S2': definition is blank` | holdout |
| AC-24 | S-ok with `S1`'s `rests_on` `[9]` | draft | 502, detail `standards draft invalid: standard 'S1': position has no paragraph 9` | holdout |
| AC-25 | S-ok plus an unused new field "Spare" | draft | 502, detail `standards draft invalid: new field 'Spare' is used by no standard` | holdout |
| AC-26 | S-ok with `S1` on `fld_name` `==` `"x"` | draft | 502, detail `standards draft invalid: standard 'S1': field 'fld_name' is string, not checkable` | holdout |
| AC-27 | S-ok with `S2`'s id changed to `S1` | draft | 502, detail `standards draft invalid: standard ids must be S1..Sn` | holdout |
| AC-28 | S-ok with `S3`'s `field_id` `fld_other` | draft | 502, detail `standards draft invalid: standard 'S3': field 'fld_other' is not in the new schema` | holdout |
| AC-29 | S-ok with `S2` as `fld_rating == "D"` | draft | 502, detail `standards draft invalid: standard 'S2': value "D" does not fit enum` | holdout |
| AC-30 | AC-19's v1 | `ana` activates v1 | 403; `active_version` 0 | holdout |
| AC-31 | AC-19's v1 | `own` activates v1 | 200; `approved_by` `own`, `path` `model_draft`; `active_version` 1 | holdout |
| AC-32 | AC-31 | read the response and the run store | `extraction_run_id` non-null; that run's manifest companies are exactly `C1`, `C2`, `C3` | holdout |
| AC-33 | AC-31 | read the schema registry | schema `theme_std_…` version 1 is released, with `released_by` `own` | holdout |
| AC-34 | S-two drafted as v1 | `own` activates | 200, `extraction_run_id` null; the run store holds no extraction run | holdout |
| AC-35 | AC-19's v1; the newest theme run has 2 pending review items | `own` activates | 409, detail `find companies first`; `active_version` 0 | holdout |
| AC-36 | AC-19's v1 rests on position v1; position v2 drafted and approved | `own` activates v1 | 409, detail `standards v1 rest on position v1; v2 is approved` | holdout |
| AC-37 | — | `own` activates version 7 (none) | 404, detail `unknown standards version 7` | holdout |
| AC-38 | AC-19's v1; `get_extraction_starter` overridden to raise `RuntimeError("boom")` | `own` activates v1 | 502, detail `extraction could not start: boom`; `active_version` 0 | holdout |
| AC-38b | AC-38, then the override removed | `own` activates v1 | 200, `extraction_run_id` non-null; `active_version` 1 | holdout |
| AC-39 | approved position v1 | `own` `POST .../standards/versions` with S-two as content | 200 `{version: 1}`; version 1 `created_by` `own`, `path` `owner_edit` | holdout |
| AC-40 | AC-39 | `own` activates v1 | 200, `approved_by` `own`, `path` `owner_edit`; `active_version` 1 | holdout |
| AC-40b | AC-40 | `GET .../standards` | `activations` last row: `version` 1, `approved_by` `own`, `path` `owner_edit` | holdout |
| AC-41 | — | `ana` `POST .../standards/versions` | 403 | holdout |
| AC-41b | AC-31 active, its run `completed`; the model returns S-ok with `S3` changed to `data` `existing` on the released theme field, plus `S4` on a new boolean field "Grid permit filed", resting on paragraph 1 | `ana` drafts v2; `own` activates v2 | 200, `extraction_run_id` non-null and different from AC-31's | holdout |
| AC-41c | AC-41b | read the schema registry | `theme_std_…` version 2 is released with 2 fields | holdout |
| AC-41d | AC-41b | `GET .../standards` | version 2: `S3` `data` `existing`, `S4` `data` `new` | holdout |
| AC-41e | AC-41b, the new run `running` | `GET /api/dossiers/D` | step 5 `running`, `extracting 2 data points` | holdout |
| AC-42 | — | `own` `POST .../standards/versions` with S-two, `S1` on `fld_draft` | 422, detail `standard 'S1': unknown or unreleased field 'fld_draft'` | holdout |
| AC-43 | the API configured with a users file containing a user whose `user_id` is `model` | any request with a valid token | 503, detail contains `user id 'model' is reserved` | holdout |
| AC-44 | S-two active (via AC-34) | `ana` `POST .../standards/check` | 200; `results` as (company, standard, result): Alpha S1 `met`, Alpha S2 `met`, Beta S1 `unmet`, Beta S2 `no_data`, Gamma S1 `no_data`, Gamma S2 `no_data`; no Delta rows; `flagged` 1 | holdout |
| AC-45 | AC-44, with `e1`'s `fld_grid_capex` replaced by a fact in state `zero`, status `approved` | check | Alpha S2 `unmet`, `value` 0; `flagged` 2 | holdout |
| AC-46 | AC-44, with `e1`'s `fld_scope3` fact status `pending_review` | check | Alpha S1 `no_data` | holdout |
| AC-47 | AC-44 | `GET /api/stewardship/triggers` | exactly one trigger with `rule` starting `std:`: `issuer_id` `C2`, `type` `theme_standard`, `theme` `Grid electrification`, `severity` `high`, `rule` `std:D:S1`, `reason` `Scope 3 emissions disclosed: false, expected == true`, `status` `open` | holdout |
| AC-48 | AC-47's trigger resolved by `own` | check again | still exactly one `std:` trigger, same `trigger_id`, `status` `resolved` | holdout |
| AC-49 | AC-47 | `POST /api/stewardship/monitoring/open-engagement {"issuer_id": "C2", "rule": "std:D:S1"}` | 200; the new issue's theme `Grid electrification`, severity `high`, sector `Utilities` | holdout |
| AC-50 | S-two active; `e2` `fld_scope3` true (`approved`), `e2` `fld_grid_capex` 30 (`approved`); no check before | check | 200, `flagged` 0; Gamma's rows `no_data`; `GET /api/stewardship/triggers` has no `std:` trigger | holdout |
| AC-51 | no active standards | check | 409, detail `no active standards` | holdout |
| AC-52 | `GET /api/stewardship/triggers` after monitoring runs for two months | run AC-44's check, then `GET` again | the non-`std:` triggers are identical in both responses (all keys, including `is_new` and `status`) | holdout |
| AC-53 | holdings for a portfolio loaded for the previous month; no monitoring run recorded for it; AC-44's check ran today | the monthly scheduler ticks | a monitoring run for the previous month is recorded (the tick is not skipped) | holdout |
| AC-54 | no `ARP_POSTGRES_DSN`; otherwise AC-10's state (approved position, no standards); caller `own` | `POST` `.../standards/draft` `{}`, `.../standards/versions` with S-two, `.../standards/activate` `{"version": 1}`, `.../standards/check` with no body | 503 for each, detail `ARP_POSTGRES_DSN is required: Postgres is the system of record.` | holdout |
| AC-55 | fixture without an approved note | `GET /api/dossiers/D` | step 5 `not_started`, detail `research note not approved`, `href` `#/themes/D/position` | holdout |
| AC-56 | approved note, no position | `GET` | step 5 `not_started`, `draft the position` | holdout |
| AC-57 | AC-2 | `GET` | step 5 `waiting`, `approve position v1` | holdout |
| AC-58 | AC-10, no standards | `GET` | step 5 `not_started`, `draft standards` | holdout |
| AC-59 | AC-19 | `GET` | step 5 `waiting`, `approve standards v1` | holdout |
| AC-60 | AC-31, its extraction run `running` | `GET` | step 5 `running`, `extracting 1 data points` | holdout |
| AC-61 | AC-31, its extraction run `failed` | `GET` | step 5 `failed`, `extraction failed` | holdout |
| AC-62 | AC-31, its extraction run `cancelled` | `GET` | step 5 `failed`, `extraction cancelled` | holdout |
| AC-63 | AC-31, its extraction run `completed` with 3 open review items | `GET` | step 5 `waiting`, `3 to review` | holdout |
| AC-64 | AC-31, run `completed`, 0 open review items, no check since | `GET` | step 5 `waiting`, `check companies` | holdout |
| AC-65 | AC-44 | `GET` | step 5 `done`, `2 standards · 1 flagged` | holdout |
| AC-66 | AC-44 | `GET /api/dossiers` | `current_step` for `D` is `null` | holdout |
| AC-67 | AC-44, then position v2 drafted and approved | `GET` | step 5 `waiting`, `standards rest on position v1, v2 approved` | holdout |
| AC-68 | caller `vic` | `GET .../position`, `GET .../standards`; every step-5 `POST` | 200, 200; 403 for every `POST` | holdout |
| AC-69 | AC-2's state, signed in as `own` | open `D`'s dossier page, click step 5's link | `#/themes/D/position` opens; Position shows 2 paragraphs, the first citing `R1 · Permitting delays` and `O1 · Grid capex boom`; state `Draft by model`; **Approve** and **Edit** buttons present | evaluator |
| AC-70 | AC-69, signed in as `ana` | open the page | no **Approve** and no **Edit**; **Redraft** with an **Instructions** box present | evaluator |
| AC-71 | AC-69 | **Edit** paragraph 1, save | the page shows version 2, state `Draft by own` | evaluator |
| AC-72 | AC-19's state | open the page | the Standards table has columns `Standard`, `Definition`, `Where reported`, `Criterion`, `Data`, `Severity`, `Rests on`; `S3`'s Data reads `New field` | evaluator |
| AC-73 | S-two active | click **Check companies** | a grid of rows Alpha, Beta, Gamma and columns S1, S2 reading Alpha `Met` `Met`, Beta `Unmet` `No data`, Gamma `No data` `No data` | evaluator |
| AC-74 | AC-47 | open StewardIQ's Monitoring studio | a **Theme standards** table lists Beta, `Grid electrification`, `S1`, `high`, `Scope 3 emissions disclosed: false, expected == true`, with **Open engagement** | evaluator |
| AC-75 | AC-55's dossier page | read step 5 | it reads `Not started` and `research note not approved` | evaluator |

Must not change:
- AC-76: a house `monitoring_rules` version saved by `ana` and activated by `ana` → 422, detail
  `Four-eyes rule: a version must be activated by someone other than the person who saved it`. Checked by:
  holdout.
- AC-77: the AC-76 version activated by `own` → 200. Checked by: holdout.
- AC-78: `GET /api/stewardship/policies/theme_standards` → 404, detail `Unknown policy`. Checked by: holdout.
- AC-79: `GET /api/stewardship/policies/<id>` for `monitoring_rules`, `coverage_rules`, `escalation_rules`,
  `phrase_blocklist` and `house_voting` → 200 each. Checked by: holdout.
- AC-80: a monitoring run already recorded for the previous month, with no newer loads → the scheduler tick
  records no second run. Checked by: holdout.
- AC-81: dossier steps 1–4 derive exactly as in the dossier spec, whose AC-2 to AC-31 still pass. The only
  exceptions are step 5's `state`, `detail` and `href`, and `current_step` where step 5 is no longer skipped,
  which follow this spec. Checked by: holdout.
