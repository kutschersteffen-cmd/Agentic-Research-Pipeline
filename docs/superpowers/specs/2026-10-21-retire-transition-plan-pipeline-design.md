# Retire the dedicated transition-plan pipeline

Date: 2026-10-21
Status: approved by the owner 2026-10-21 (description and acceptance table)
Source: audit finding 8 (two pipelines for the same 64 indicators)
Builds on: `docs/superpowers/specs/2026-10-18-transition-plan-number-rules-design.md` (the preset's number rules)

## Intent

The 64 Colesanti Senni transition-plan indicators run through two pipelines:
- **The dedicated pipeline** under `backend/arp/transition_plan/`: its own graph, agents, aggregator
  and run type `transition_plan`.
- **The generic field pipeline**, through the preset `backend/arp/presets/transition_plan.py`
  (`transition_plan_indicators`).

They already give different answers: only the preset has the number rules. Every indicator fix has to
be made twice, or it drifts.

This change makes the preset the only way to assess transition plans. Runs already stored stay
readable. The owner decided:

- **Contradictions are flagged, not forced.** The dedicated pipeline turns a child YES into NO when
  its parent indicator is NO. The preset keeps the AI's YES and sends it to review, like every other
  preset rule.
- **Decision Studio keeps working unchanged.** An adapter turns a preset run into the same columns,
  with the same values, that a transition-plan run gives today: `Ind_*_Disclosed` plus the counts.
  Sector and region come from the company record. The extra sector/location LLM step is dropped.
- **Old runs are read-only.** Stored `transition_plan` runs keep their results, review queue and
  Decision Studio input. They can't be started, resumed or restarted.
- **No silent fallback to an old version.** A start runs the preset's current version. Until an
  approver releases that version, a non-trial start is refused with the existing "not released"
  error. After the deploy, one release is needed.
- **Financials and TNFD (finding 9) are parked.** They need list fields the generic pipeline doesn't
  have, and the payoff doesn't justify building them now.

## Goals

1. Starting a transition-plan assessment, from the UI or `/api/extraction/start`, runs the preset
   through the generic pipeline.
2. The preset flags the 10 parent/child contradictions the dedicated pipeline handled.
3. Decision Studio frameworks written for transition-plan runs work on preset runs without edits, and
   give the same numbers for the same answers.
4. Stored `transition_plan` runs stay viewable, reviewable and usable as Decision Studio input.
5. The dedicated pipeline's code is deleted.

## Non-goals

- Financials and TNFD (finding 9): parked by the owner on 2026-10-21.
- List or table fields in the generic pipeline.
- A rule kind that changes a value. Rules only flag.
- Changing the rule engine. For example, a missing parent still fails a `requires` rule, as in every
  other preset.
- Changing the number rules or the 64 question texts.
- Migrating stored `transition_plan` runs into extraction runs, or deleting stored rows.
- Paper-exact BM25-only retrieval. The preset uses the generic retrieval, as it does today.
- Running an older released version when a newer one is saved.

## Anti-goals (a failure even if it technically works)

- A stored transition-plan run can no longer be opened, scored or reviewed.
- A Decision Studio framework that scores transition-plan runs today:
  - returns different columns or an error on a preset run, or
  - returns different numbers for the same answers.
- A transition-plan start runs the old pipeline, or an unreleased version, without the user asking for
  a trial.
- A framework written against a preset run's generic extraction columns stops working.

## Design

### 1. Starting a run

`POST /api/extraction/start` with `profile: "transition_plan"` runs in two steps:

1. It installs the preset (`install_preset("transition_plan", registry)`). This is a no-op when the
   content is already saved.
2. It starts a generic extraction run on the preset's schema, through the same code path as
   `profile: "custom"`, with the request's `trial` flag.

The custom path's release gate then decides, unchanged:
- **Released:** the run starts.
- **Not released, `trial` false:** status 400 with the existing `is not released` message.
- **Not released, `trial` true:** the run starts and is marked as a trial.

The response has `run_type: "extraction"`.

After this change is deployed, the preset's new version (with the contradiction rules) is saved on the
first start. An approver releases it once through the existing release endpoint.

The run is an ordinary extraction run, so it gets:
- field-level review
- checks
- history
- observations
- the publish gate

The frontend's "Transition plan" profile (`frontend/src/lib/jobs.ts`) keeps its label and sends the
same profile. Its results open in the generic extraction results view.

`GET /api/extraction/pipeline?profile=transition_plan` returns the same body as `profile=custom`.

Restarting a preset run (`POST /api/extraction/runs/{id}/restart`) works as it does for a custom run.
It re-sends the saved start request, so it runs the version that is current then, under the same gate.

### 2. Contradiction rules

Each child field below gets one `requires` rule:
- rule_id `tp_r_req_<child suffix>`
- `field` = the parent field
- `equals` true
- `when` true

The checks are the existing ones. A failed rule flags the value for review and never changes it (the
#169 behaviour). As for every `requires` rule, a parent that is missing or ungrounded also fails the
rule, so that child YES goes to review too.

Field ids are the preset's own: `tp_` plus the lower-cased identifier.

| Child field | Parent field | rule_id |
|---|---|---|
| `tp_a_headline_2` | `tp_a_headline_1` | `tp_r_req_headline_2` |
| `tp_a_ambition_4` | `tp_a_ambition_3` | `tp_r_req_ambition_4` |
| `tp_a_ambition_5` | `tp_a_headline_1` | `tp_r_req_ambition_5` |
| `tp_a_coverage_6` | `tp_a_headline_1` | `tp_r_req_coverage_6` |
| `tp_a_coverage_7` | `tp_a_headline_1` | `tp_r_req_coverage_7` |
| `tp_a_coverage_8` | `tp_a_headline_1` | `tp_r_req_coverage_8` |
| `tp_a_pathway_12` | `tp_a_pathway_11` | `tp_r_req_pathway_12` |
| `tp_a_progress_67` | `tp_a_emissions_59` | `tp_r_req_progress_67` |
| `tp_a_progress_68` | `tp_a_emissions_60` | `tp_r_req_progress_68` |
| `tp_a_progress_69` | `tp_a_emissions_61` | `tp_r_req_progress_69` |

`tp_a_ambition_5` and `tp_a_progress_67/68/69` already carry a number rule. The requires rule goes
**after** it.

Each of the 10 fields moves up one version through the preset's `_VERSIONS` map. On `main` today:
- `tp_a_ambition_5`, `tp_a_coverage_6` and `tp_a_progress_67/68/69` are at 2, so they move to 3.
- The other five are at 1, so they move to 2.
- `tp_a_progress_70/71/72` stay at 2.
- Every other field stays at 1.

This supersedes these rows of the number-rules spec, which were scoped to their own PR:
- AC-3: four fields now have two rules.
- AC-16: six more fields now carry a rule.
- AC-4: field versions.
- AC-15: "no path under `backend/arp/transition_plan/`".

### 3. Decision Studio

A **transition-plan preset run** is an extraction run whose manifest `params.schema_id` is
`transition_plan_indicators`.

**Columns.** For a preset run, the transition-plan adapter (`from_transition_plan_run`, also
`RUN_ADAPTERS["transition_plan"]`) emits two groups of columns, in this order:
1. Exactly the columns an old transition-plan run gives with `include_indicators=True`: the same
   names, in the same order, with the 4 categories sorted.
2. Then every column the generic extraction adapter gives for the same run that is not already in
   group 1: `Extraction_Confidence_pct` and one column per field name. These carry the generic
   adapter's values.

So a framework written for transition-plan runs and one written for the generic extraction columns
both work on a preset run.

**Where it applies.** Every place that resolves the columns or dataset of a run uses this adapter for
a preset run:
- `template_for_run` at start (`extraction.py`)
- `attach_framework` (`decision.py`)
- re-scoring
- the `transition_plan_run` source
- joined runs, which give it the same prefix an old transition-plan run gets

The `extraction_run` source keeps returning the generic columns for any extraction run, a preset run
included.

**Values in group 1.**
- Group 1 reads each field's value, grounded flag and confidence exactly as the generic extraction
  adapter reads them for the same run.
- "Found" means that value is not null.
- Only the 64 question fields count, never the 8 helper fields.
- The divisors are today's: all indicators of that kind, found or not.
- A dataset built this way has source `transition_plan_run`. That includes a framework attached to a
  preset run and the run's scoring.

| Column | Value (string, as written to the dataset) |
|---|---|
| `Company`, `Company_Id` | as in the generic extraction adapter |
| `Sector` | the run's stored company `sector`, else `""` |
| `Region` | the run's stored company `country`, else `""` |
| `Indicators_Disclosed_Count` | number of question fields with value `true` |
| `Walk_Disclosed_Count` / `Talk_Disclosed_Count` | the same count, over indicators whose `walk_or_talk` in `indicators.json` is walk / talk |
| `Walk_Share_pct` | walk-disclosed ÷ number of walk indicators in `indicators.json` (34) × 100, one decimal |
| `Assessment_Confidence_pct` | mean `confidence` of the found question fields × 100, one decimal (ungrounded counts as 0); `0.0` when none was found |
| `<Category>_Disclosure_pct` | for each of governance, strategy, target and tracking: disclosed in that category ÷ number of indicators in that category in `indicators.json` × 100, one decimal |
| `Needs_Review_Flag` | `Yes` when the stored record's `needs_review` is true, else `No` |
| `Ind_<identifier>_Disclosed` | `Yes` for value `true`, `No` for `false`, `""` when not found |

**Confidence.** Cell confidences follow today's adapter:
- `Ind_*` cells: the field's confidence when grounded, `0` when found but ungrounded, none when not found.
- `Indicators_Disclosed_Count`, `Walk_Disclosed_Count`, `Talk_Disclosed_Count` and `Walk_Share_pct`:
  the `Assessment_Confidence_pct` value ÷ 100.
- Every other group-1 column: none.
- Group-2 columns: as the generic adapter gives them.

**Frontend.**
- The Decision Studio transition-plan run picker also lists preset runs.
- Its "Create a sample run" button is removed, because the seed endpoint goes.
- The process map's Transition Plan step also counts preset runs.

### 4. Old runs

**These stay:**
- `GET /api/transition-plan/indicators`.
- The read routes in `api/routers/transition_plan.py`: results, review-queue, review-decisions and
  review-history.
- `POST /api/transition-plan/runs/{id}/review`, so pending items can still be decided.
- `from_transition_plan_run`'s reading of old runs, and the `transition_plan` entries in
  `REVIEWABLE_RUN_TYPES`, `RUN_TYPE_LABEL` and RunReviewList.
- The frontend's `TransitionPlanResults.tsx`.
- From `schemas/transition_plan.py`: `IndicatorCategory`, `WalkOrTalk` and `TransitionPlanIndicator`.
- `transition_plan/indicators.py` and `data/indicators.json`, which the preset reads.

**These go:**
- `POST /api/transition-plan/runs` and `POST /api/transition-plan/demo/seed`. Both paths have no other
  method, so they answer 404.
- The CLI commands `arp transition-plan run` and `arp transition-plan seed-demo`. `indicators` stays.
- Resume. `POST /api/runs/{id}/resume` on a `transition_plan` run returns 400 with
  `Transition-plan runs can no longer be resumed: start a new transition-plan assessment.`
- Restart. `POST /api/extraction/runs/{id}/restart` on a `transition_plan` run, from any step, returns
  400 with `Transition-plan runs can no longer be restarted: start a new transition-plan assessment.`
- `transition_plan` from the frontend's `RESUMABLE_RUN_TYPES`, so no Resume button is offered.

### 5. Deleted

**Code:**
- From `backend/arp/transition_plan/`: `aggregator.py`, `basic_info_agent.py`, `company_assessment.py`,
  `demo.py`, `indicator_agent.py`, `indicator_graph.py`, `pipeline.py`, `verifier_agent.py`.
- From `schemas/transition_plan.py`: the record models only the pipeline uses (`IndicatorAssessment`,
  `CategoryBreakdown`, `TransitionPlanAssessmentRecord`, `Verdict`).
- The `transition_plan` branches in `orchestration/jobs.py` (the resume dispatch) and
  `extraction/steps.py` (the pipeline shape).
- `frontend/src/api/client.ts`'s demo-seed method.
- No setting is dedicated to this pipeline. The `hybrid_retrieval_enabled` description in `config.py`
  mentions it; that sentence is removed.

**Tests:**
- Deleted, as they test only deleted code: `test_transition_plan_company_assessment.py`,
  `test_transition_plan_consistency.py`, `test_transition_plan_demo.py` and
  `test_transition_plan_indicator_graph.py`.
- Reworked: `test_resume_run.py`. Its generic resume and lease tests use this pipeline as their
  example; they move to another run type with every assert kept.
- Edited: `test_jobs.py`, `test_api_batch_runs.py`, `test_extraction_start.py` and
  `frontend/tests/runs.test.ts`.

**Docs:**
- README, METHODOLOGY, TECHNICAL_REFERENCE and DECISION_MECHANISM describe the preset as the
  transition-plan assessment.
- `docs/decision-studio/indicator-list.md` drops the seed instructions.
- The evaluator skill line that runs `arp transition-plan seed-demo` is removed.

### Left to the builder

- How the adapter reads the run's stored companies (the run store already saves them).
- Which run type hosts the reworked resume tests.
- The order of the work.

### Calls made in this spec (owner: check these)

- Pending review items on old runs can still be decided. Otherwise they would sit in "Needs you"
  forever.
- A child YES whose parent is missing or ungrounded goes to review, because the rule engine treats a
  missing input as a failure. The old pipeline left it alone. This means more review items at first.
- A preset run serves both kinds of framework: transition-plan columns first, then the generic ones.
  This avoids breaking any framework already written against the generic columns.
- The demo seed and its Decision Studio button are removed rather than rebuilt for preset runs.
- Restarting an old run is refused from every step, the rules step included.

## Acceptance

**Preset rows** build the preset with `build_transition_plan_schema()`.

**Evaluation rows** run the preset's fields through `check_record` and `route()`, as in
`backend/tests/test_rules_evaluation.py`, with every extracted row found and grounded unless the row
says otherwise.

**"Released preset"** means this branch's preset installed and released through the schema registry.

**Holdout fixtures**, captured on `main` before the implementation PR merges, and committed in the holdout repo, never in this
repo:
- `F-cols`: the column list `from_source("transition_plan_run", run_id=…, include_indicators=True)`
  gives for an old `transition_plan` run.
- `F-old`: the full dataset (columns and rows) for the stored old run `O` below.
- `F-preset`: the 72 fields of the preset, with every attribute.
- `F-joined`: the column names `from_joined_runs` gives for `O`, joined with the extraction run `E` below.
- `F-ind`: the indicators `GET /api/transition-plan/indicators` returns.

**Facts from `indicators.json`:**

| Category | Indicators | of which walk | of which talk |
|---|---|---|---|
| target | 12 | 0 | 12 |
| governance | 9 | 2 | 7 |
| strategy | 24 | 17 | 7 |
| tracking | 19 | 15 | 4 |
| all | 64 | 34 | 30 |

- `A_headline_1` is target and talk.
- `A_management_32` is strategy and walk.
- `A_emissions_59` is tracking.

**Preset field names:** the field `tp_a_headline_1` is named `A_headline_1`, and `tp_h_scope1_emissions`
is named `Scope 1 emissions`. The generic extraction adapter names its columns after these names.

**Run `R`** is a stored preset run with two companies:
- **X:** stored company `sector` "Utilities", `country` "DE". All 64 question fields are found,
  grounded, with `confidence` 0.8. The 12 target indicators are `true` and the other 52 are `false`.
  No helper field is found. The stored `needs_review` is false.
- **Y:** no sector or country. Found:
  - `tp_a_headline_1`: `true`, grounded, `confidence` 0.6;
  - `tp_a_management_32`: `true`, **ungrounded**, `confidence` 0.9;
  - `tp_h_scope1_emissions`: grounded, `confidence` 1.0.

  Nothing else is found. The stored `needs_review` is true.

**Run `O`** is a stored `transition_plan` run with 2 result rows and 1 pending review item.

**Run `E`** is a stored extraction run of another released schema `S`, with one company.

All dataset values are compared as strings, as written to the dataset.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Released preset, one company | `POST /api/extraction/start` `{profile: "transition_plan", companies: [it]}` | status 200; body `run_type` is `extraction` | holdout |
| AC-2 | As AC-1 | the run's manifest is read | `run_type` is `extraction`, and `params.schema_id` is `transition_plan_indicators` | holdout |
| AC-30 | As AC-1 | the run's manifest is read | `params.trial` is false | holdout |
| AC-3 | `main`'s preset saved and released; this branch deployed | `POST /api/extraction/start` `{profile: "transition_plan", companies: [one]}` | status 400; body contains `is not released` | holdout |
| AC-4 | As AC-3 | the same request with `trial: true` | status 200; the manifest's `params.trial` is true | holdout |
| AC-31 | As AC-3, then the version the start saved is released | the request from AC-3 is sent again | status 200 | holdout |
| AC-32 | As AC-31 | the run's schema is read from the registry at the run's `params` schema version | `tp_a_headline_2` has version 2 and rule `tp_r_req_headline_2` | holdout |
| AC-33 | This branch | `GET /api/extraction/pipeline?profile=transition_plan` | status 200; body equals the body for `profile=custom` | holdout |
| AC-5 | This branch's app | `POST /api/transition-plan/runs` with a valid old-style body | status 404 | holdout |
| AC-34 | This branch's app | `POST /api/transition-plan/demo/seed` | status 404 | holdout |
| AC-6 | This branch | `arp transition-plan --help` runs | the only command listed is `indicators` | holdout |
| AC-35 | This branch | `arp transition-plan indicators` runs | exit code 0; the output names all 64 identifiers in `F-ind` | holdout |
| AC-36 | This branch's app | `GET /api/transition-plan/indicators` | status 200; body equals `F-ind` | holdout |
| AC-7 | The preset | it is built | each child field in the contradiction table has a rule with that rule_id, kind `requires`, `field` = the parent field, `equals` true and `when` true | holdout |
| AC-8 | The preset | it is built | `tp_a_ambition_5`, `tp_a_progress_67`, `tp_a_progress_68` and `tp_a_progress_69` each have exactly 2 rules: their `F-preset` rule first, then the requires rule | holdout |
| AC-9 | The preset | it is built | the fields with at least one rule are exactly: `tp_a_headline_2`, `tp_a_ambition_4`, `tp_a_ambition_5`, `tp_a_coverage_6`, `tp_a_coverage_7`, `tp_a_coverage_8`, `tp_a_pathway_12`, `tp_a_progress_67`, `tp_a_progress_68`, `tp_a_progress_69`, `tp_a_progress_70`, `tp_a_progress_71`, `tp_a_progress_72` | holdout |
| AC-10 | The preset | it is built | each of the 10 child fields has its `F-preset` version + 1; every other field has its `F-preset` version | holdout |
| AC-11 | `tp_a_headline_2`=true, `tp_a_headline_1`=false | checks and routing finish | `tp_a_headline_2` has `rule.tp_r_req_headline_2` with `outcome` `fail` | holdout |
| AC-12 | As AC-11 | checks and routing finish | `tp_a_headline_2`'s `route` is `review` | holdout |
| AC-37 | As AC-11 | checks and routing finish | `tp_a_headline_2`'s `route_reasons` include `check:rule.tp_r_req_headline_2` | holdout |
| AC-38 | As AC-11 | checks and routing finish | `tp_a_headline_2`'s value is still `true` | holdout |
| AC-13 | `tp_a_headline_2`=true, `tp_a_headline_1`=true | checks and routing finish | `rule.tp_r_req_headline_2` has `outcome` `pass` | holdout |
| AC-14 | `tp_a_headline_2`=false, `tp_a_headline_1`=false | checks and routing finish | `rule.tp_r_req_headline_2` has `outcome` `not_applicable` | holdout |
| AC-55 | `tp_a_headline_2`=true; `tp_a_headline_1` not found | checks and routing finish | `rule.tp_r_req_headline_2` has `outcome` `fail` | holdout |
| AC-56 | As AC-55 | checks and routing finish | `tp_a_headline_2`'s `route` is `review` | holdout |
| AC-39 | `tp_a_progress_67`=true; `tp_h_scope1_emissions` grounded, `canonical_unit` `tCO2e`, `period_end` 31 December of each year: 2020: 100, 2021: 95, 2022: 90, 2023: 85, 2024: 80; report year 2024; `tp_a_emissions_59`=false | checks and routing finish | `rule.tp_r_req_progress_67` has `outcome` `fail` | holdout |
| AC-40 | As AC-39 | checks and routing finish | `rule.tp_r_progress_67` has `outcome` `pass` | holdout |
| AC-15 | `main`'s preset saved and released through the schema registry | this branch's preset is POSTed to `/api/extraction/schemas` | status 200 | holdout |
| AC-16 | Run `R` | `from_source("transition_plan_run", run_id=R, include_indicators=True)` | its first columns equal `F-cols`, in order | holdout |
| AC-41 | As AC-16 | its columns after the `F-cols` ones are read | they equal the columns `from_source("extraction_run", run_id=R)` gives, minus every column in `F-cols`, in that adapter's order | holdout |
| AC-17 | As AC-16 | the row for X is read | `Sector` "Utilities", `Region` "DE", `Indicators_Disclosed_Count` "12", `Walk_Disclosed_Count` "0", `Talk_Disclosed_Count` "12", `Walk_Share_pct` "0.0", `Assessment_Confidence_pct` "80.0", `Needs_Review_Flag` "No" | holdout |
| AC-18 | As AC-16 | the row for X is read | `Target_Disclosure_pct` "100.0"; `Governance_Disclosure_pct`, `Strategy_Disclosure_pct` and `Tracking_Disclosure_pct` "0.0"; `Ind_A_headline_1_Disclosed` "Yes"; `Ind_A_emissions_59_Disclosed` "No" | holdout |
| AC-19 | As AC-16 | the row for Y is read | `Sector` "", `Region` "", `Indicators_Disclosed_Count` "2", `Walk_Disclosed_Count` "1", `Talk_Disclosed_Count` "1", `Walk_Share_pct` "2.9", `Assessment_Confidence_pct` "30.0", `Needs_Review_Flag` "Yes" | holdout |
| AC-57 | As AC-16 | the row for Y is read | `Target_Disclosure_pct` "8.3", `Strategy_Disclosure_pct` "4.2", `Governance_Disclosure_pct` "0.0", `Tracking_Disclosure_pct` "0.0"; `Ind_A_headline_1_Disclosed` "Yes", `Ind_A_management_32_Disclosed` "Yes", `Ind_A_headline_2_Disclosed` "" | holdout |
| AC-42 | As AC-16 | the cell confidences for Y are read | `Ind_A_headline_1_Disclosed` 0.6; `Ind_A_management_32_Disclosed` 0; `Ind_A_headline_2_Disclosed` none; `Indicators_Disclosed_Count` and `Walk_Share_pct` 0.3; `Target_Disclosure_pct` none | holdout |
| AC-20 | Run `R`, and a ratified framework that needs `Indicators_Disclosed_Count` | it is attached to `R` (`attach_framework`) | status 200 | holdout |
| AC-43 | As AC-20 | the attached run is scored | the scored dataset's source is `transition_plan_run` | holdout |
| AC-58 | As AC-20 | the attached run is scored | X's `Indicators_Disclosed_Count` in the scored dataset is "12" | holdout |
| AC-44 | Run `R`, and a ratified framework that needs the column `A_headline_1` | it is attached to `R` | status 200 | holdout |
| AC-59 | As AC-44 | the attached run is scored | X's `A_headline_1` in the scored dataset equals X's `A_headline_1` in `from_source("extraction_run", run_id=R)` | holdout |
| AC-45 | Run `R` and run `E` | `from_joined_runs(run_store, [R, E])` | every column `F-joined` gives for `O` appears for `R`, with the same prefix | holdout |
| AC-60 | Must not change: run `O`, and a ratified framework that needs `Indicators_Disclosed_Count` | it is attached to `O` | status 200 | holdout |
| AC-61 | As AC-60 | the attached run is scored | each company's `Indicators_Disclosed_Count` equals its value in `F-old` | holdout |
| AC-46 | Must not change: an extraction run of another released schema `S`, and a ratified framework needing one of `S`'s field names | the framework is attached to it | status 200; scoring it gives the same columns as `from_source("extraction_run", …)` | holdout |
| AC-47 | Must not change: a released custom schema `S`, one company | `POST /api/extraction/start` `{profile: "custom", datapoint_schema: S, companies: [it]}` | status 200; `run_type` `extraction`; manifest `params.schema_id` equals `S`'s id | holdout |
| AC-21 | Must not change: run `O` | `GET /api/transition-plan/runs/{O}/results` | status 200; `total` 2 | holdout |
| AC-22 | Must not change: run `O` | `GET /api/transition-plan/runs/{O}/review-queue` | status 200; exactly 1 item, whose key equals the stored pending item's key | holdout |
| AC-48 | Run `O` | `POST /api/transition-plan/runs/{O}/review` approving that item | status 200 | holdout |
| AC-49 | As AC-48 | `GET /api/transition-plan/runs/{O}/review-queue` | 0 items | holdout |
| AC-50 | As AC-48 | `GET /api/transition-plan/runs/{O}/review-history` | it lists exactly 1 decision, for that item's key | holdout |
| AC-23 | Must not change: run `O` | `from_source("transition_plan_run", run_id=O, include_indicators=True)` | columns and rows equal `F-old` | holdout |
| AC-24 | Run `O` with status `failed` | `POST /api/runs/{O}/resume` | status 400; body contains `Transition-plan runs can no longer be resumed` | holdout |
| AC-25 | Run `O` with a saved `start_request.json` | `POST /api/extraction/runs/{O}/restart` from step `start` | status 400; body contains `Transition-plan runs can no longer be restarted` | holdout |
| AC-51 | As AC-25 | the same request from step `rules` | status 400; body contains `Transition-plan runs can no longer be restarted` | holdout |
| AC-62 | Must not change: a failed extraction run of a released schema | `POST /api/runs/{id}/resume` | status 200 | holdout |
| AC-63 | A preset run started through `/api/extraction/start`, released preset | `POST /api/extraction/runs/{id}/restart` from step `start` | status 200 | holdout |
| AC-64 | As AC-63 | the new run's manifest is read | `params.schema_id` is `transition_plan_indicators` | holdout |
| AC-26 | Must not change: the preset | it is built | every attribute of all 72 fields equals `F-preset`, except the `rules` and `version` of the 10 child fields | holdout |
| AC-27 | The running app, a released preset | an analyst starts a "Transition plan" assessment for one company from the Extraction page | the run appears in Run History | evaluator |
| AC-52 | As AC-27, once the run completes | its results are opened | they open in the extraction results view, which lists the 64 question fields and the 8 helper fields | evaluator |
| AC-28 | The running app, run `O` | it is opened from Run History | its results show in the transition-plan results view | evaluator |
| AC-53 | As AC-28 | Run History shows `O` | no Resume button is offered for it | evaluator |
| AC-54 | The running app, runs `R` and `O` | Decision Studio's transition-plan run picker is opened | both `R` and `O` are listed | evaluator |
| AC-65 | The running app | Decision Studio's transition-plan source is selected | no "Create a sample run" button is shown | evaluator |
| AC-66 | The running app, with `R` and `O` the only transition-plan runs | the start page's process map is opened | the Transition Plan step counts 2 runs | evaluator |
| AC-29 | This branch | `git ls-files backend/arp/transition_plan` | lists exactly `__init__.py`, `indicators.py` and the files under `backend/arp/transition_plan/data/` on `main` | holdout |

IDs are not in numeric order: AC-30 to AC-54 were added after review and kept next to the rows they
belong with.
