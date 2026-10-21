# Retire the Dedicated Transition-Plan Pipeline: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transition-plan assessments run only through the `transition_plan_indicators` preset. Stored
`transition_plan` runs stay readable, reviewable and scoreable, and the dedicated pipeline is deleted.

**Architecture:**
- The `/api/extraction/start` profile `transition_plan` becomes a thin alias for the custom path, run on
  the installed preset.
- One helper decides when an extraction run is a "transition-plan preset run". Every Decision Studio
  entry point (start check, attach, scoring, sources, joins) asks that helper and then uses the
  transition-plan adapter. For preset runs, the adapter computes today's columns from field values and
  appends the generic extraction columns.
- Old runs keep their read routes. Their resume and restart are refused.

**Tech Stack:** Python 3.11, FastAPI, Typer, pytest with Postgres (`ARP_TEST_POSTGRES_DSN`), React +
TypeScript (`node --test`).

**Spec:** `docs/superpowers/specs/2026-10-21-retire-transition-plan-pipeline-design.md` (owner approved
2026-10-21). Read it first: every number below comes from it.

## Global Constraints

- **Rules only flag, never change a value.** No new rule kind and no change to `arp/checks/rules.py`.
- **Field ids** are `tp_` + lower-cased identifier. Field *names* are the identifier (`A_headline_1`).
- **Requires rules:** each rule_id is `tp_r_req_<child suffix>`, with `equals` true and `when` true. On
  the four fields that already have a number rule, the requires rule goes after it.
- **Versions:** each of the 10 child fields is bumped +1 from `main` through `_VERSIONS`. No other
  field's version changes.
- **Adapter divisors:**
  - walk: 34;
  - target: 12, governance: 9, strategy: 24, tracking: 19;
  - all values one decimal, as strings.
  - Only the 64 question fields count.
- **Exact messages:**
  - `Transition-plan runs can no longer be resumed: start a new transition-plan assessment.`
  - `Transition-plan runs can no longer be restarted: start a new transition-plan assessment.`
- **No migration** and no deleted rows. Schema steps stay untouched.
- **Repo rules:** every test change goes in the PR description. Never delete or weaken a test except
  one that tests only deleted code. After changing routes, regenerate `openapi.json` and
  `schema.gen.ts`.
- The PR description carries `Spec: retire-transition-plan-pipeline` on its own line, and the label
  `risk:high` (it changes `.claude/skills/evaluator`).

## Review Focus

1. **`False` is a found value.** A question field whose value is `false` counts as found: `Ind_*` is
   `No`, not `""`. A truthiness check (`if value:`) would blank every NO. Tested in Task 3.
2. **The same field on several periods.** A question field can appear on more than one period row. The
   adapter takes the first row per field, as `from_extraction_run` does ("latest period first"). It
   must never count the field twice. Tested in Task 3.
3. **Nothing to read.** A company with no fields at all, or a run with no stored companies: counts are
   `"0"`, `Assessment_Confidence_pct` is `"0.0"`, `Sector`/`Region` are `""`, and nothing raises.
   Tested in Task 3.
4. **Extraction runs without `params.schema_id`.** Runs created before that param existed must keep
   the generic adapter and not crash the helper. Tested in Task 3.
5. **Restarting a preset run from `rules`.** It is an extraction run, so it must still re-score through
   the transition-plan adapter, not be refused like an old run. Tested in Task 4.

---

### Task 1: Contradiction rules on the preset

**Files:**
- Modify: `backend/arp/presets/transition_plan.py` (`_VERSIONS`, the field builder around L89-106)
- Test: `backend/tests/test_presets_transition_plan.py` (extend; create if absent, following
  `backend/tests/test_rules_evaluation.py` for evaluation helpers)
- Fixture: `backend/tests/fixtures/transition_plan_preset_main.json`. Before editing the preset, dump
  `build_transition_plan_schema().model_dump(mode="json")["fields"]` from `origin/main`.

**Interfaces:**
- Produces: `REQUIRES_YES: dict[str, str]` in `arp/presets/transition_plan.py`, mapping child field id
  to parent field id. These are the 10 pairs from spec §2, written as field ids
  (`"tp_a_headline_2": "tp_a_headline_1"`, …).

- [ ] **Step 1: Capture the fixture from main.** Run
  `git show origin/main:backend/arp/presets/transition_plan.py` in a scratch checkout, dump the fields
  to the fixture path and commit it.
- [ ] **Step 2: Write the failing tests.**
  - `test_child_fields_carry_requires_rules`: for every child/parent pair, the child's last rule has
    kind `requires`, rule_id `tp_r_req_<suffix>`, field = parent, `equals is True`, `when is True`.
  - `test_two_rule_fields_keep_number_rule_first`: `tp_a_ambition_5` and `tp_a_progress_67/68/69` have
    2 rules, and `rules[0]` equals the fixture's rule.
  - `test_rule_bearing_fields_are_exactly_13`: the set equals spec AC-9's list.
  - `test_versions`: each child is at its fixture version + 1, and every other field is at its fixture
    version.
  - `test_everything_else_unchanged`: all 72 fields equal the fixture, except `rules` and `version` on
    the 10 children.
  - Evaluation tests, through `check_record` + `route()`:
    - `headline_2` true and `headline_1` false: outcome `fail`, route `review`, `route_reasons`
      contains `check:rule.tp_r_req_headline_2`, value still `True`.
    - Both true: `pass`.
    - `headline_2` false: `not_applicable`.
    - `headline_1` absent: `fail` and `review`.
    - `progress_67` true, scope-1 series 2020–2024 = 100, 95, 90, 85, 80 tCO2e, report year 2024,
      `emissions_59` false: `tp_r_req_progress_67` fails and `tp_r_progress_67` passes.
- [ ] **Step 3: Run them.** `cd backend && python3 -m pytest tests/test_presets_transition_plan.py -v`
  is expected to FAIL (no requires rules yet).
- [ ] **Step 4: Implement.** Add `REQUIRES_YES`. Append
  `RequiresRule(kind="requires", rule_id=..., field=parent, equals=True, when=True)` after any existing
  rule on each child, and add the 10 version bumps to `_VERSIONS`. Update the module docstring to say
  the preset is now the transition-plan assessment.
- [ ] **Step 5: Update the superseded number-rules tests.** In
  `backend/tests/test_presets_transition_plan_rules.py`, the asserts for number-rules AC-3 (exactly one
  rule), AC-16 (only seven fields have rules) and AC-4 (versions) now encode superseded rows. Change
  them to the new expectations, keeping every assert, and list each change in the PR. Then run the same
  command, plus `tests/test_presets_transition_plan_rules.py` and `tests/test_rules_evaluation.py`.
  Expected: PASS.
- [ ] **Step 6: Release compatibility.** Add `test_branch_preset_saves_over_main_release`: save and
  release the fixture schema in the registry, then POST this branch's preset to
  `/api/extraction/schemas` and expect status 200. Run it; expect PASS.
- [ ] **Step 7: Commit.** `feat(transition-plan): flag parent/child contradictions in the preset`

### Task 2: Start transition-plan assessments on the preset

**Files:**
- Modify: `backend/arp/api/routers/extraction.py`:
  - `_dispatch`, the `else` branch (~L262);
  - `start_extraction_run`, the template check (~L162-166).
- Modify: `backend/arp/extraction/steps.py`: `PROFILES["transition_plan"]` and `_graph`.
- Test: `backend/tests/test_extraction_start.py` (edit the transition-plan cases, ~L9, 32, 60-63).

**Interfaces:**
- Consumes: `install_preset(preset_id, registry) -> DataPointSchema` (`arp/presets/registry.py`) and
  `SCHEMA_ID` from `arp/presets/transition_plan.py`.
- Produces: `decision_kind_for_schema(schema_id: str) -> str` in `arp/decision/templates.py`. It returns
  `"transition_plan"` for `SCHEMA_ID` and `"extraction"` otherwise. Task 3 uses it as well.

- [ ] **Step 1: Write the failing tests.**
  - Released preset, start `{profile: "transition_plan", companies: [c]}`: status 200, `run_type`
    `extraction`, and the manifest's `params.schema_id` is `transition_plan_indicators` with
    `params.trial` false.
  - `main`'s preset released, this branch's preset not: status 400, body contains `is not released`.
    With `trial: true`: status 200 and `params.trial` true. After releasing the saved version, a second
    start: 200, and the run's schema has `tp_a_headline_2` at version 2.
  - `GET /api/extraction/pipeline?profile=transition_plan` returns the same body as `profile=custom`.
  - The custom profile is unchanged: a released schema `S` gives 200, `run_type` `extraction` and
    `params.schema_id == S.schema_id`.
  - A ratified framework needing `Indicators_Disclosed_Count`, passed as `decision_framework_id` on a
    transition-plan start, is accepted (no "needs columns" 400).
- [ ] **Step 2: Run them.** `python3 -m pytest tests/test_extraction_start.py -v` should FAIL.
- [ ] **Step 3: Implement.**
  - In `_dispatch`, the transition-plan branch calls `install_preset("transition_plan", registry)` with
    the schema registry `_registry_for` builds. It then calls `start_extraction_run` with
    `datapoint_schema=` that schema and `trial=req.trial`, and returns `run_type "extraction"`.
  - `start_extraction_run`'s template check passes `decision_kind_for_schema(schema.schema_id)`
    instead of `"extraction"`.
  - `PROFILES["transition_plan"]` reuses `PROFILES["custom"]`'s settings and item text, and `_graph`
    maps `transition_plan` to the field graph.
- [ ] **Step 4: Run them again.** Same command; expected PASS.
- [ ] **Step 5: Commit.** `feat(transition-plan): start assessments on the preset`

### Task 3: Decision Studio adapter for preset runs

**Files:**
- Modify: `backend/arp/decision/sources.py`:
  - `from_transition_plan_run` (~L54);
  - `from_joined_runs` (~L664-688);
  - `_JOINABLE`.
- Modify: `backend/arp/decision/templates.py`:
  - `RUN_ADAPTERS["transition_plan"]` columns lambda (~L46-49);
  - `run_dataset` (~L187).
- Modify: `backend/arp/api/routers/decision.py` `attach_framework` (~L521-525).
- Test: `backend/tests/test_decision_sources.py` and `backend/tests/test_decision_templates.py`
  (extend).

**Interfaces:**
- Consumes: `decision_kind_for_schema` (Task 2).
- Produces:
  - `is_transition_plan_preset_run(manifest: RunManifest) -> bool` in `arp/decision/sources.py`. True
    iff `run_type == "extraction"` and `params.get("schema_id") == SCHEMA_ID`. It must tolerate a
    missing `schema_id`.
  - `decision_kind(manifest: RunManifest) -> str` in `arp/decision/templates.py`. It returns
    `"transition_plan"` for a preset run and `manifest.run_type` otherwise.
  - `run_dataset` and `attach_framework` call `decision_kind(manifest)` instead of `manifest.run_type`.

- [ ] **Step 1: Write the fixture helper.** In `backend/tests/test_decision_sources.py`,
  `store_preset_run(run_store, companies, records) -> run_id` writes a manifest with `run_type`
  `extraction` and `params.schema_id`, the companies, and one result row per company, shaped like
  `ExtractionRecord`. Build runs `R` (companies X and Y) and `E` exactly as the spec's Acceptance
  preamble describes them.
- [ ] **Step 2: Write the failing tests.**
  - The columns of `from_transition_plan_run(R, include_indicators=True)` start with
    `expected_transition_plan_columns()`, followed by `from_extraction_run(R)`'s columns minus those.
  - X's and Y's cells, with exactly the values in spec AC-17, AC-18, AC-19 and AC-57.
  - Y's confidences per AC-42.
  - `dataset.source == "transition_plan_run"`.
  - The Review Focus tests:
    - `test_false_value_is_found`.
    - `test_first_period_row_per_field_wins`: two `tp_a_headline_1` rows, first `true` and second
      `false`, give a count of 1 and `Yes`.
    - `test_company_without_fields` and `test_run_without_stored_companies`.
    - `test_extraction_run_without_schema_id_keeps_generic_adapter`.
  - Templates:
    - A framework needing `Indicators_Disclosed_Count` attaches to `R` (200) and scores it with source
      `transition_plan_run`, X = `"12"`.
    - A framework needing `A_headline_1` attaches (200) and scores X's `A_headline_1` equal to
      `from_extraction_run`'s.
    - A framework on `E` (another schema) keeps the generic columns.
  - Joins: `from_joined_runs([R, E])` gives `R`'s columns the `TP_` prefix, for the same columns an old
    run joined with `E` gets.
  - Must not change: an old `transition_plan` run gives byte-identical columns and rows to `main`.
    Compare with a fixture dumped from `origin/main` in Step 1 of this task.
- [ ] **Step 3: Run them.** `python3 -m pytest tests/test_decision_sources.py tests/test_decision_templates.py -v`
  should FAIL.
- [ ] **Step 4: Implement.**
  - `from_transition_plan_run` loads the manifest. For a preset run it builds the old-format column
    values from field rows, using the divisors in Global Constraints and the walk/talk and category
    lookups from `load_indicators()`. It then appends `from_extraction_run`'s columns that are not
    already present, with their values and confidences. Old runs keep today's code path, untouched.
  - The `RUN_ADAPTERS["transition_plan"]` columns lambda returns `expected_transition_plan_columns()`
    when `field_names is None` (old runs). Otherwise it returns that list plus the missing
    `extraction_columns(field_names)` entries.
  - `attach_framework` still computes `field_names` for `run_type == "extraction"`, and passes
    `decision_kind(manifest)`.
  - `from_joined_runs` uses `decision_kind(manifest)` to pick both the source and the `_JOINABLE`
    prefix.
- [ ] **Step 5: Run them again.** Same command, plus `tests/test_decision_api.py tests/test_decision_joined.py`.
  Expected: PASS.
- [ ] **Step 6: Commit.** `feat(decision): score transition-plan preset runs with the transition-plan columns`

### Task 4: Retire the dedicated pipeline (backend)

**Files:**
- Modify: `backend/arp/api/routers/transition_plan.py`: delete `POST /runs` (L49) and
  `POST /demo/seed` (L80). Keep `/indicators`, `/runs/{id}/results`, `/review-queue`,
  `/review-decisions`, `/review-history`, `POST /runs/{id}/review`, and `GET /runs/{id}` if it still
  exists on `main`.
- Modify: `backend/arp/cli/transition_plan.py`: keep only `indicators`.
- Modify: `backend/arp/orchestration/jobs.py`: delete `_resume_transition_plan` and its `RESUMABLE`
  entry. `check_resumable` raises `NotResumable` with the exact resume message for
  `run_type == "transition_plan"`, before the generic not-resumable check.
- Modify: `backend/arp/api/routers/extraction.py` `restart_run`: first thing after loading the
  manifest, an old `transition_plan` run gets a 400 with the exact restart message. This comes before
  the `rules` branch.
- Modify: `backend/arp/schemas/transition_plan.py`: keep only `IndicatorCategory`, `WalkOrTalk` and
  `TransitionPlanIndicator`.
- Delete from `backend/arp/transition_plan/`: `aggregator.py`, `basic_info_agent.py`,
  `company_assessment.py`, `demo.py`, `indicator_agent.py`, `indicator_graph.py`, `pipeline.py`,
  `verifier_agent.py`.
- Delete tests: `test_transition_plan_company_assessment.py`, `test_transition_plan_consistency.py`,
  `test_transition_plan_demo.py`, `test_transition_plan_indicator_graph.py`.
- Rework: `backend/tests/test_resume_run.py`. Move its generic resume and lease tests from the
  transition-plan pipeline to the theme pipeline (`create_theme_run`, already used there), keeping
  every assert. Edit `test_jobs.py` (~L18, 149) and `test_api_batch_runs.py` (~L9, 24).
- Regenerate: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`.

- [ ] **Step 1: Write the failing tests** (in `backend/tests/test_transition_plan_old_runs.py`, new),
  on a stored old run `O` with 2 result rows and 1 pending item:
  - `POST /api/transition-plan/runs` returns 404, and so does `/demo/seed`.
  - `arp transition-plan --help` lists only `indicators`, and `arp transition-plan indicators` exits 0
    naming all 64 identifiers.
  - `GET /api/transition-plan/indicators` returns 64 items.
  - Results return `total` 2. The review queue has 1 item; deciding it gives 200, an empty queue and
    1 history entry.
  - Resume on a failed `O` returns 400 with the exact message. Restart from `start` and from `rules`
    both return 400 with the exact message.
  - A failed extraction run still resumes with 200.
  - A preset run restarts from `start` with 200 and the same `schema_id`. It also restarts from
    `rules` with 200 and `rescored: true`, once a framework is attached.
- [ ] **Step 2: Run them.** `python3 -m pytest tests/test_transition_plan_old_runs.py -v` should FAIL.
- [ ] **Step 3: Implement** the file list above.
- [ ] **Step 4: Run the touched suites.**
  `python3 -m pytest tests/test_transition_plan_old_runs.py tests/test_resume_run.py tests/test_jobs.py tests/test_api_batch_runs.py tests/test_extraction_start.py tests/test_transition_plan_indicators.py -v`
  should PASS. Then run `ruff check .`. `git ls-files backend/arp/transition_plan` must list only
  `__init__.py`, `indicators.py` and `data/` files.
- [ ] **Step 5: Run the full backend suite.** `python3 -m pytest -q --ignore=tests/e2e` with Postgres
  and `ARP_CHROMIUM_PATH` set. Expected: no new failures against `main`.
- [ ] **Step 6: Commit.** `refactor(transition-plan): retire the dedicated pipeline; old runs read-only`,
  including both regenerated API files.

### Task 5: Frontend

**Files:**
- Modify: `frontend/src/lib/runs.ts`:
  - drop `"transition_plan"` from `RESUMABLE_RUN_TYPES` (L15);
  - add `decisionRunType(r: RunManifest): string`.
- Modify: `frontend/src/lib/jobs.ts`: in `PROFILE_META.transition_plan`, `runType` stays
  `"transition_plan"` (scoring kind), and the `about` text now says it runs the 64-indicator preset.
- Modify: `frontend/src/pages/extraction/JobReview.tsx` (~L34, 52-53, 90), `ResultsTable.tsx` (~L61-64)
  and `Overview.tsx` (~L45). A transition-plan job's new results render with the extraction views.
  Pass `fieldNames` from the run's schema to `RunScoringPanel`.
- Modify: `frontend/src/pages/DecisionStudio.tsx`:
  - the picker filter (~L780) uses `decisionRunType(r)`;
  - delete `onSeedDemoRun` (~L253-261) and its paragraph (~L812-820).
- Modify: `frontend/src/api/client.ts`: delete `seedTransitionPlanDemo` (~L822).
- Modify: `frontend/src/pages/ProcessHub.tsx` (L100): `step.runTypes!.includes(decisionRunType(r))`.
- Test: `frontend/tests/runs.test.ts` (edit L6 and add cases).

**Interfaces:**
- Produces: `decisionRunType(r)`. It returns `"transition_plan"` when
  `r.run_type === "extraction" && r.params?.schema_id === "transition_plan_indicators"`, and
  `r.run_type` otherwise.

- [ ] **Step 1: Write the failing tests.**
  - `decisionRunType` maps a preset run to `"transition_plan"`, an extraction run of another schema to
    `"extraction"`, and an extraction run without `params.schema_id` to `"extraction"`.
  - `RESUMABLE_RUN_TYPES` does not contain `"transition_plan"`.
- [ ] **Step 2: Run them.** `cd frontend && npm test` should FAIL.
- [ ] **Step 3: Implement** the file list above.
- [ ] **Step 4: Run the checks.** `npm run lint && npx tsc -b && npm test` should PASS.
- [ ] **Step 5: Check the browser flow.** Run `bash backend/scripts/e2e_stack.sh up`, then screenshot
  with Playwright:
  - the Decision Studio transition-plan picker, listing a preset run and an old run, with no sample
    button;
  - the process map's Transition Plan count;
  - an old run in Run History, with no Resume button.

  Then run `/impeccable:impeccable audit` on the Decision Studio page.
- [ ] **Step 6: Commit.** `feat(frontend): transition-plan assessments use the preset`

### Task 6: Docs and skills

**Files:**
- Modify: `README.md`, `docs/METHODOLOGY.md`, `docs/TECHNICAL_REFERENCE.md` and
  `docs/DECISION_MECHANISM.md`. They now describe the preset as the transition-plan assessment and old
  runs as read-only.
- Modify: `docs/decision-studio/indicator-list.md` (L23): drop the seed instructions.
- Modify: `.claude/skills/evaluator/SKILL.md` (L25): drop `arp transition-plan seed-demo`.
- Modify: `backend/arp/config.py` (L140): drop the sentence about the transition-plan pipeline from
  the `hybrid_retrieval_enabled` description.

- [ ] **Step 1: Search for leftovers.**
  `grep -rn "seed-demo\|demo/seed\|transition_plan/indicator_graph\|execute_transition_plan_run" --include=*.md --include=*.py --include=*.ts* .`
  should return no hits outside `docs/superpowers/` history.
- [ ] **Step 2: Commit.** `docs: the preset is the transition-plan assessment`
- [ ] **Step 3: Merge and open the PR.** Merge `origin/main`, push, and open the PR against `main` with
  `Spec: retire-transition-plan-pipeline`, the label `risk:high` and the full test-change list. The
  owner's `tests-weakened-ok` label is needed for the four deleted test files.
