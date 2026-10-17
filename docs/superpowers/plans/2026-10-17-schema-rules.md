# Schema Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fields carry typed rules that flag contradicting values for review, suggested by an agent and approved by the user on the Schema screen.

**Architecture:** Rules are pydantic models on `FieldDefinition.rules`, validated in `DataPointSchema`. `checks/rules.py` renders each rule's sentence and evaluates it as an extra WARN `CheckResult` inside the existing `check_record`, so routing, review context and the review screen pick it up unchanged. A new suggest-rules endpoint wraps one LLM call. The frontend adds one Rules list under the fields editor plus read-only markers.

**Tech Stack:** Python 3.11, pydantic v2, FastAPI, pytest (+ Postgres test DB), React + TypeScript (Vite), `node --test`, Playwright (E2E job).

**Spec:** `docs/superpowers/specs/2026-10-17-schema-rules-design.md` (approved 2026-10-17). AC-n below refers to its Acceptance table. Its fixture schema F and rules R1–R6 are used throughout.

## Global Constraints

- No new dependency, backend or frontend.
- Rules only add `CheckResult`s. Never change `value`, `value_state`, `confidence` or `citations`.
- Rule results: `check_id` `rule.<rule_id>`, `layer` 3, `severity` WARN, `threshold_ref` `<field_id>:v<version>:rules.<rule_id>`.
- `FieldDefinition.rules` defaults to `[]`, so schemas without rules behave exactly as on `main`.
- After any request/response model change: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, then commit both generated files.
- Checks per task: `cd backend && ruff check . && python3 -m pytest tests/<file>`. Frontend: `cd frontend && npm run lint && npx tsc -b && npm test`.
- Run `bash .claude/hooks/ensure-deps.sh backend` (and `postgres`) before tests. `export ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test`.
- No file under `backend/arp/transition_plan/` changes (AC-61).
- Exact UI copy: `Accepted`, `+ Add a rule`, `Suggest again`, `1 rule suggestion waiting`, `N rule suggestions waiting`, `Confirm schema (N fields)`, `N rules · M waiting`, `1 rule`, `N rules`, `used by a rule`.

## Review Focus

Inputs the spec implies but its rows don't exercise, most likely to bite first. Each has a test in its owning task.

1. A numeric input with `value_state` `zero` counts as found with value 0, never as "not found" (Task 3).
2. `ratio_pct` with a zero denominator fails with `Cannot divide by zero.` as the found part's last sentence. It never raises (Task 3).
3. `series` with two rows for the same year (two documents) counts the year once and uses the first row in record order (Task 3).
4. Suggested rules get fresh `rule_id`s that never collide with ids already in the schema (Task 5).
5. `when` on an enum field matches the stored string exactly (`"combined"`), and on a boolean only a real `true`/`false` (Task 3).

---

### Task 1: Rule models and schema validation

**Files:**
- Create: `backend/arp/schemas/rules.py`
- Modify: `backend/arp/schemas/datapoints.py` (`FieldDefinition` gains `rules`; `DataPointSchema` gains a `_rules_valid` validator next to `_derived_inputs_valid`)
- Test: `backend/tests/test_schema_rules_validation.py`
- Test fixture helper: `backend/tests/rules_fixtures.py` (schema F and R1–R6 as Python builders, shared by Tasks 1–5)

**Interfaces:**
- Produces, in `arp/schemas/rules.py`:
  - `Condition(field: str, op: Literal[">=", "<=", ">", "<", "="], value: float)`
  - `RequiresRule(kind: Literal["requires"], field: str, equals: bool | str | float)`
  - `ThresholdRule(kind: Literal["threshold"], conditions: list[Condition])` (min 1)
  - `SeriesRule(kind: Literal["series"], field: str, years: int, trend: Literal["none", "down", "up"] = "none")`
  - `LabelRule(kind: Literal["label"], field: str, not_in: list[str])` (min 1)
  - `ComputedRule(kind: Literal["computed"], formula: Literal["ratio_pct", "sum"], inputs: list[str], tolerance: float = 0)` (`tolerance >= 0`, `ratio_pct` exactly 2 inputs, `sum` at least 2)
  - each rule also has `rule_id: str` and `when: bool | str | float | None = None`
  - `FieldRule = Annotated[RequiresRule | ThresholdRule | SeriesRule | LabelRule | ComputedRule, Field(discriminator="kind")]`
  - `rule_inputs(rule: FieldRule) -> list[str]`: the field ids the rule reads, in the order it names them
- Produces: `FieldDefinition.rules: list[FieldRule] = []`
- Produces, in `tests/rules_fixtures.py`: `schema_f(**field_overrides) -> DataPointSchema`, `R1()`…`R6()` returning `FieldRule`, and `with_rules(schema, {field_id: [rules]}) -> DataPointSchema`

- [ ] **Step 1: Write the failing tests** in `test_schema_rules_validation.py`, posting through `TestClient` the way `tests/test_extraction_schema_gate.py` does (analyst principal, `settings` + `pg` fixtures):
  - `test_unknown_field_rejected` (AC-22): 422, body contains `R1`
  - `test_computed_input_is_own_field_rejected` (AC-23): 422, `R5`
  - `test_threshold_on_enum_rejected` (AC-24): 422, `R7`
  - `test_threshold_on_unitless_currency_rejected` (AC-25): 422, `R8`, plus control AC-69: 200
  - `test_label_on_non_enum_rejected` (AC-26): 422, `R4`
  - `test_label_value_outside_allowed_rejected` (AC-27): 422, `R4`
  - `test_series_years_out_of_range_rejected` (AC-28): years 0 and 6, both 422, `R3`
  - `test_rule_naming_derived_field_rejected` (AC-29): 422, `R2`; `test_rule_on_derived_field_rejected` (AC-67): 422, `R2`; controls AC-70: both 200
  - `test_duplicate_rule_id_rejected` (AC-30): 422, `R1`
  - `test_computed_on_non_numeric_own_field_rejected` (AC-68): 422, `R9`
  - `test_rules_round_trip` (AC-32): POST F with R1–R6, GET by id, `fields[i].rules` equal
  - `test_released_field_gains_rule_refused` (AC-33): 400, body contains `changing it needs`
  - `test_released_schema_without_rules_resaves_same_versions` (AC-34): body stored without a `rules` key, then fetched and POSTed again → same schema version and field versions

- [ ] **Step 2: Run them, expect failures**

Run: `cd backend && python3 -m pytest tests/test_schema_rules_validation.py -v`
Expected: FAIL (`rules` is an unknown field / no validation)

- [ ] **Step 3: Implement the models in `arp/schemas/rules.py`, add `rules` to `FieldDefinition`, and add `DataPointSchema._rules_valid`** enforcing validation items 1–10 of the spec. Every `ValueError` message starts with `rule <rule_id>:`.

- [ ] **Step 4: Run the tests, expect them to pass.** Also run `python3 -m pytest tests/test_extraction_schema_gate.py tests/test_derived.py` (unchanged, must pass).

- [ ] **Step 5: Commit** `feat(schemas): typed field rules with validation`

### Task 2: Rule sentences

**Files:**
- Create: `backend/arp/checks/rules.py` (sentence part only in this task)
- Create: `backend/tests/fixtures/rule_sentences.json`
- Test: `backend/tests/test_rule_sentences.py`

**Interfaces:**
- Consumes: `FieldRule`, `rule_inputs` (Task 1)
- Produces: `rule_sentence(rule: FieldRule, field_id: str, schema: DataPointSchema) -> str` and `format_value(v: bool | float | str | None) -> str` (`YES`/`NO`, whole numbers without `.0`, others as stored)
- Produces the fixture shape: a JSON list of `{"field_id": str, "rule": <FieldRule as JSON>, "sentence": str}` over schema F. Task 6 reads the same file.

- [ ] **Step 1: Write the fixture** with the 7 entries and exact sentences from AC-31.
- [ ] **Step 2: Write `test_sentences_match_fixture`** (AC-31): for each entry, `rule_sentence(...) == entry["sentence"]`.
- [ ] **Step 3: Run it, expect failure** (`ImportError`).
- [ ] **Step 4: Implement `rule_sentence`** with the spec's six templates, the `When <field> is <when>: ` prefix, and the first letter capitalized when there is no `when`.
- [ ] **Step 5: Run it, expect pass.**
- [ ] **Step 6: Commit** `feat(checks): render rule sentences`

### Task 3: Evaluate rules inside `check_record`

**Files:**
- Modify: `backend/arp/checks/rules.py` (evaluation)
- Modify: `backend/arp/checks/runner.py` (`check_record` appends rule results after `run_checks`)
- Test: `backend/tests/test_rules_evaluation.py`
- Test: `backend/tests/test_rules_no_rules_snapshot.py` + `backend/tests/fixtures/no_rules_snapshot.json`

**Interfaces:**
- Consumes: `rule_sentence`, `format_value` (Task 2); `CheckContext` (`checks/runner.py`)
- Produces: `evaluate_rules(spec: FieldDefinition, row: ExtractedField, ctx: CheckContext) -> list[CheckResult]`, one result per rule of `spec`
- Produces: `report_year(ctx: CheckContext) -> int | None`: the latest year of `d.period_plan.current` over `ctx.documents_by_id.values()`

- [ ] **Step 1: Write the failing tests.** Build rows with the `_field` style of `tests/test_checks_plausibility.py` (found, grounded, citation on page 31). Call `check_record` and then `route()` (`extraction/routing.py`) with a `FieldQuality(first_audit_passed=True)` and a released spec, so only rule reasons appear. One test per row: AC-1 to AC-20, AC-64, AC-72, AC-74, AC-75. Assert the exact `detail` strings for AC-3, AC-9 and AC-18, and the endings for AC-10, AC-14 and AC-16.
  Plus the Review Focus tests:
  - `test_zero_value_counts_as_found`: R1 with `pct` `value_state` `zero` → `fail`, `detail` contains `Found Target reduction = 0 (p. 31)`
  - `test_ratio_with_zero_denominator`: R5 with `total`=0 → `fail`, `detail` ends with `Cannot divide by zero.`
  - `test_series_duplicate_year_counted_once`: R3 with two 2024 rows (8 then 12) → `pass`
  - `test_when_on_enum_matches_string`: a rule `when: "combined"` on `kind` applies for `combined` and is `not_applicable` for `standalone`
- [ ] **Step 2: Write `test_no_rules_output_unchanged`** (AC-59): a fixed record and schema without rules. Generate the snapshot by running this test's body on `main` (`git stash` your branch changes, or check out `origin/main` in a worktree), commit it, and compare `checks`, `route` and `route_reasons` against it.
- [ ] **Step 3: Run the tests, expect failures.**
- [ ] **Step 4: Implement `evaluate_rules` and `report_year`.** Follow the spec exactly for: period row picking (order 1–4), not found (no row, a state other than `found`/`zero`, or not grounded), units groups, `when`, the detail format, and `Expected` rounding. In `check_record`, `checks = [*await run_checks(...), *evaluate_rules(spec, field, ctx)]`. Rules run even when `run_checks` stopped early.
- [ ] **Step 5: Run the tests, expect pass.** Then run `python3 -m pytest tests/test_checks_*.py tests/test_routing.py tests/test_derived.py` (AC-60, unchanged).
- [ ] **Step 6: Commit** `feat(checks): evaluate field rules as WARN checks`

### Task 4: Reuse and review context

**Files:**
- Modify: `backend/arp/extraction/pipeline.py:262` (the reuse condition)
- Test: `backend/tests/test_rules_pipeline.py`

**Interfaces:**
- Consumes: the evaluation in `check_record` (Task 3)
- Produces: no new names

- [ ] **Step 1: Write the failing tests** using the `_run` pattern of `tests/test_doc_routing.py` (`fake_llm`, `RunStore`, `execute_extraction_run`) with schema F + R1:
  - `test_rule_only_failure_is_reused` (AC-21)
  - `test_non_rule_failure_not_reused` (AC-65, must not change)
  - `test_reused_row_reruns_rules` (AC-66: bump `pct`'s version and script 55)
  - `test_review_context_keeps_run_time_sentence` (AC-38): after the run, save R1 with threshold 40 as a new field version, then build the review context as `tests/test_review_context.py` does; `failed_checks` has `plain` == the AC-3 string
- [ ] **Step 2: Run them, expect AC-21 and AC-66 to fail** (AC-65 and AC-38 may already pass).
- [ ] **Step 3: Change the reuse condition** so it ignores failing results whose `check_id` starts with `rule.`.
- [ ] **Step 4: Run them, expect pass.** Also run `python3 -m pytest tests/test_doc_routing.py tests/test_review_context.py`.
- [ ] **Step 5: Commit** `feat(extraction): rule failures don't block reuse`

### Task 5: Suggest-rules agent and endpoint

**Files:**
- Modify: `backend/arp/extraction/schema_builder.py` (add `RuleSuggestions`, `suggest_rules`)
- Modify: `backend/arp/api/routers/extraction.py` (add `POST /schemas/suggest-rules` next to `/schemas/draft`)
- Test: `backend/tests/test_suggest_rules.py`

**Interfaces:**
- Produces: `class RuleSuggestion(BaseModel): field_id: str; rule: FieldRule`
- Produces: `class RuleSuggestions(BaseModel): rules: list[RuleSuggestion] = []; helper_fields: list[FieldDefinition] = []`. This is both the LLM `output_model` and the endpoint's `response_model`.
- Produces: `async def suggest_rules(schema: DataPointSchema, llm: LLMClient) -> tuple[RuleSuggestions, LLMUsage]`
- Endpoint: `async def suggest_rules_endpoint(schema: DataPointSchema) -> RuleSuggestions`, calling `get_llm_client()` like `draft_schema_endpoint`, with role `analyst`. It saves nothing.

- [ ] **Step 1: Write the failing tests.** The stand-in is monkeypatched over `arp.api.routers.extraction.get_llm_client` and returns `RuleSuggestions` from `complete_structured`:
  - `test_invalid_suggestion_and_its_helper_dropped` (AC-35)
  - `test_helpers_merged_by_name` (AC-36)
  - `test_helper_merged_into_existing_field` (AC-63)
  - `test_suggest_saves_nothing` (AC-37)
  - Review Focus: `test_suggested_rule_ids_are_fresh`, where the stand-in returns a rule with `rule_id` `R1` against F already holding R1 → the returned id differs from every id in F and from the others returned
- [ ] **Step 2: Run them, expect failures.**
- [ ] **Step 3: Implement `suggest_rules`.**
  - The prompt follows the spec's rule ("only thresholds or dependencies the field's own text states; never invent one; only the five kinds") and lists every field's id, name, type, unit, allowed values, description and instructions.
  - After the call, the code:
    1. merges helper fields by case-insensitive name into existing or earlier helper fields and rewrites rule references;
    2. assigns fresh `rule_id`s (`new_id("rule")`);
    3. validates each rule alone against schema + kept helpers, using the Task 1 validator, and drops failures;
    4. drops helper fields no kept rule reads.
- [ ] **Step 4: Run them, expect pass.**
- [ ] **Step 5: Regenerate the API contract.** Run `python scripts/export_openapi.py`, then `cd ../frontend && npm run gen:api && npx tsc -b`. Expected: `tsc` exits 0.
- [ ] **Step 6: Commit** the backend files plus `frontend/src/api/openapi.json` and `schema.gen.ts`: `feat(api): suggest rules for a drafted schema`

### Task 6: Frontend types, client and sentence renderer

**Files:**
- Modify: `frontend/src/types.ts` (`FieldDefinition.rules?: FieldRule[]`, plus the `FieldRule` union and `RuleSuggestions`, mirroring Task 1/5 names)
- Modify: `frontend/src/api/client.ts` (`suggestRules(schema: DataPointSchema): Promise<RuleSuggestions>` → `POST /api/extraction/schemas/suggest-rules`)
- Modify: `frontend/src/api/contract.ts` (add `Satisfies<Served<S["RuleSuggestions"]>, RuleSuggestions>`)
- Create: `frontend/src/lib/ruleSentence.ts`
- Test: `frontend/tests/ruleSentence.test.ts`

**Interfaces:**
- Produces: `ruleSentence(rule: FieldRule, fieldId: string, fields: FieldDefinition[]): string`
- Produces: `ruleInputs(rule: FieldRule): string[]`, the same order as the backend
- Produces: `sameRule(a: {fieldId: string; rule: FieldRule}, b: {fieldId: string; rule: FieldRule}): boolean`: same checked field, kind, `when` and parameters, ignoring `rule_id`

- [ ] **Step 1: Write `ruleSentence.test.ts`** (AC-62), reading `../backend/tests/fixtures/rule_sentences.json` with `node:fs` and asserting every sentence. Add a `sameRule` test: same parameters with different ids → true; a different `when` → false.
- [ ] **Step 2: Run `npm test`, expect failure.**
- [ ] **Step 3: Implement `ruleSentence.ts`.** It ports Task 2's templates and number formatting.
- [ ] **Step 4: Run `npm run lint && npx tsc -b && npm test`, expect pass.**
- [ ] **Step 5: Commit** `feat(frontend): rule types, client and sentences`

### Task 7: Rules list, markers and confirm gating

**Files:**
- Create: `frontend/src/components/RulesList.tsx` (list, item, editor, "+ Add a rule", "Suggest again")
- Modify: `frontend/src/components/SchemaFieldsEditor.tsx` (read-only marker per field; new optional props `markers: Record<string, string>`, `onMarkerClick(fieldId)`)
- Modify: `frontend/src/pages/extraction/SchemaPanel.tsx` (call `suggestRules` after a draft; hold waiting suggestions and session-dropped ones per job; gate and relabel the confirm button)
- Modify: `frontend/src/lib/jobs.ts` if `CustomJob` needs a `suggestions` slot
- Modify: `frontend/src/index.css` (`.rules-*` rules using `--await`, `--await-edge` and the existing spacing/type tokens)
- Test: `backend/tests/e2e/test_schema_rules.py`

**Interfaces:**
- Consumes: `api.suggestRules`, `ruleSentence`, `ruleInputs`, `sameRule` (Task 6)
- Produces: `RulesList` props `{ schema: DataPointSchema; waiting: RuleSuggestion[]; onChange(next: { schema: DataPointSchema; waiting: RuleSuggestion[]; dropped: RuleSuggestion[] }): void; onSuggestAgain(): void; busy: boolean }`. List order: by checked field in schema order, then arrival order.

- [ ] **Step 1: Write the browser tests** in `test_schema_rules.py`, using the `page` fixture style of `tests/e2e/test_app_smoke.py`. Each test:
  1. `page.route("**/api/extraction/schemas/draft", …)` and `page.route("**/api/extraction/schemas/suggest-rules", …)` fulfil with JSON built from schema F (via `tests.rules_fixtures`);
  2. opens Extraction from the sidebar, picks the custom profile, and drafts.

  One test per row AC-39 to AC-57 and AC-71. For AC-56/AC-71, intercept `**/api/extraction/runs` and assert on the posted body.
- [ ] **Step 2: Start the stack and run them, expect failures**

Run: `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`, then `cd backend && ARP_E2E_URL=http://localhost:5173 ARP_CHROMIUM_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1) pytest -m e2e tests/e2e/test_schema_rules.py -v`
Expected: FAIL (no Rules list)

- [ ] **Step 3: Implement `RulesList`, the markers and the SchemaPanel wiring.**
  - Accept merges helper fields by `field_id`.
  - Drop on an accepted rule keeps its helper fields.
  - Suggest again replaces waiting items and hides suggestions `sameRule` to accepted or dropped ones.
  - The marker click scrolls the first matching list item into view.
  - Editing a field still sets `confirmed: false`.
  - Keyboard: every button is reachable and has a visible focus state, and inputs have labels.
- [ ] **Step 4: Rebuild the stack (`e2e_stack.sh down && up`) and run the tests, expect pass.** Also run `pytest -m e2e tests/e2e` (the smoke tests must still pass) and `cd frontend && npm run lint && npx tsc -b && npm test`.
- [ ] **Step 5: Screenshot and audit.** Use Playwright to screenshot the Schema screen with the AC-39 stubs in light and dark at 390 px and 1280 px. Run `/impeccable:impeccable audit` on it and fix what it flags. Expected: no horizontal page scroll and no overlapping text (the AC-58 conditions).
- [ ] **Step 6: Commit** `feat(frontend): Rules list on the Schema screen`

### Task 8: Finish and open the PR

**Files:** none new.

- [ ] **Step 1: Run the full checks.** `cd backend && ruff check . && python3 -m pytest` (alone, nothing else using the test DB). Then the frontend checks, `python scripts/export_openapi.py --check`, and `git diff --name-only origin/main...HEAD | grep transition_plan/`. Expected: tests green except failures that also occur on `main` in this container (missing browser, `hdbscan`, `botocore`), the contract check up to date, and no `transition_plan/` path.
- [ ] **Step 2: Review.** Run `/ponytail:ponytail-review` and `/code-review` on the branch. Fix confirmed findings, rerun the checks and commit.
- [ ] **Step 3: Merge `origin/main` into the branch** (a merge commit), rerun the checks and push.
- [ ] **Step 4: Open the PR against `main`.**
  - Title: `Schema rules: agent-suggested checks that flag for review`.
  - Body:
    - `Spec: 2026-10-17-schema-rules-design` on its own line;
    - the risk label `risk:normal`, with a one-line reason;
    - every test file added, and the statement that no existing test changed;
    - the `unit` rows owed as `holdout`;
    - that AC-58, AC-61 and AC-73 are for the evaluator.
