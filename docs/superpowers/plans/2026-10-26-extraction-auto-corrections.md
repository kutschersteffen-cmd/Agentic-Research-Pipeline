# Extraction auto-corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four deterministic rules (label, year, unit scale, planned figure) that correct an extracted value, keep the model's original on the record, and send every corrected value to review.

**Architecture:** A new pure module `backend/arp/extraction/corrections.py` runs once per company in `_extract_company`, after all field rows are gathered and before `check_record`, behind a `corrections` keyword that only custom-schema runs switch on. Each rule returns rows with a `Correction` entry and the `auto_corrected` review reason; routing needs no change. The review context and two frontend views show one line per correction.

**Tech Stack:** Python 3.11, Pydantic, pytest (backend); React + TypeScript, vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-10-26-extraction-auto-corrections-design.md` (approved). The spec's R1–R4 text and its Acceptance table are the source of truth for every exact value below.

## Global Constraints

- No model call anywhere in the corrections code.
- Rules run in the order R1, R2, R3, R4.
- `Correction.rule` ∈ `label_map`, `period_fill`, `unit_scale`, `planned_move`; `Correction.attribute` ∈ `value`, `period_end`, `unit`, `field_id`.
- New `ReasonCode` values: `auto_corrected`, `period_missing` (exact strings).
- New `FieldDefinition.planned_field_id: str | None = None`; preset links exactly: `tc_capex_total` → `tc_capex_total_planned`, `tc_lowcarbon_capex` → `tc_lowcarbon_capex_planned`, `tc_lowcarbon_capex_share_pct` → `tc_lowcarbon_capex_share_pct_planned`.
- Corrections on only when `execute_extraction_run` runs a schema other than `transition_plan_indicators` and `sch_transition_plan_actions`. Every other caller of `_extract_company` keeps the default `False`.
- Reason texts and the reviewer line format are copied verbatim from the spec (R1, R2, R3, R4 "Reason text" lines; "Reviewer view").
- After the model change: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, fix `tsc -b`, commit both generated files.
- Checks before each commit: `cd backend && ruff check . && python3 -m pytest <touched test files>`; frontend tasks also `npm run lint && npx tsc -b && npm test`.
- Never delete or weaken an existing test; list every test change in the PR description. PR body carries `Spec: extraction-auto-corrections` on its own line.

## Review Focus

1. **A row whose citations exist but none is grounded.** R2 and R3 must see no grounded quotes and make no correction. (Test in Task 3 and Task 4.)
2. **Printed numbers with separators.** R3 must find `2,479` in the quote for value 2479, and `2.794` for value 2.794, but not match `2,794` for value 2.794. (Test in Task 4.)
3. **A unit that is only a currency symbol** (`$`) with a "billion" quote: R3 appends `billion` → `$ billion`; the canonical value stays empty (known gap) and nothing raises. (Test in Task 4.)
4. **`planned_field_id` pointing at a field the schema doesn't have:** R4 makes no correction and nothing raises. (Test in Task 5.)
5. **An enum row whose value is not a string** (`None`, a bool): R1 makes no correction and nothing raises. (Test in Task 2.)

---

### Task 1: Record, reason codes, field link and API types

**Files:**
- Modify: `backend/arp/schemas/datapoints.py` (add `Correction`; `ExtractedField.corrections`; `FieldDefinition.planned_field_id`)
- Modify: `backend/arp/schemas/review.py` (`ReasonCode.AUTO_CORRECTED`, `ReasonCode.PERIOD_MISSING`)
- Modify: `backend/arp/presets/transition_capex.py` (set the three `planned_field_id` links)
- Regenerate: `backend/openapi.json` (or wherever `export_openapi.py` writes), `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/test_corrections_model.py`

**Interfaces:**
- Produces: `Correction(rule: Literal["label_map","period_fill","unit_scale","planned_move"], attribute: Literal["value","period_end","unit","field_id"], original: str | float | bool | None, corrected: str | float | bool | None, reason: str)`; `ExtractedField.corrections: list[Correction] = []`; `FieldDefinition.planned_field_id: str | None = None`; `ReasonCode.AUTO_CORRECTED == "auto_corrected"`, `ReasonCode.PERIOD_MISSING == "period_missing"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_row_stored_before_corrections_loads_with_an_empty_list():  # AC-14
    row = ExtractedField.model_validate({"field_id": "f", "field_name": "F", "value": 1.0, "confidence": 0.5})
    assert row.corrections == []

def test_correction_round_trips():
    c = Correction(rule="label_map", attribute="value", original="Cash flow", corrected="cash_flow", reason="x")
    assert Correction.model_validate(c.model_dump(mode="json")) == c

def test_transition_capex_links_actual_fields_to_planned_siblings():
    links = {f.field_id: f.planned_field_id for f in build_transition_capex_schema().fields if f.planned_field_id}
    assert links == {"tc_capex_total": "tc_capex_total_planned", "tc_lowcarbon_capex": "tc_lowcarbon_capex_planned",
                     "tc_lowcarbon_capex_share_pct": "tc_lowcarbon_capex_share_pct_planned"}

def test_new_reason_codes():
    assert ReasonCode.AUTO_CORRECTED == "auto_corrected" and ReasonCode.PERIOD_MISSING == "period_missing"
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_corrections_model.py -q`. Expected: FAIL (import errors).
- [ ] **Step 3: Add the models, codes and preset links** listed under Interfaces. The preset tuple list gains no new column if a keyword on the built `FieldDefinition` is simpler; the three links must hold either way.
- [ ] **Step 4: Run** the tests. Expected: PASS. Also run `python3 -m pytest tests/test_aggregator.py tests/test_routing.py -q`. Expected: PASS (defaults change nothing).
- [ ] **Step 5: Regenerate API types** (Global Constraints command), then `cd frontend && npx tsc -b`. Expected: exit 0.
- [ ] **Step 6: Commit** `feat: correction record, reason codes and planned-field link`.

### Task 2: Corrections module and R1 label_map

**Files:**
- Create: `backend/arp/extraction/corrections.py`
- Test: `backend/tests/test_corrections.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces:
  - `apply_corrections(schema: DataPointSchema, fields: list[ExtractedField], *, documents_by_id: dict[str, SourceDocument], fiscal_year_end: str | None, input_hashes: dict[str, str | None]) -> list[ExtractedField]`. Pure; returns new rows; runs R1–R4 in order; adds `ReasonCode.AUTO_CORRECTED` to `review_reasons` (once) on every row with at least one correction. `input_hashes` maps `field_id` to that field's current input hash (used by R4).
  - Helpers used by later tasks: `grounded_quotes(row) -> list[str]`; `report_period_end(row, documents_by_id) -> str | None` (first cited document with `period_plan.current`); `planned_field_ids(schema) -> set[str]`; `NUMERIC = {number, currency_amount, percentage}`.
  - `_label_map(row, spec) -> ExtractedField` (R1).

- [ ] **Step 1: Write the failing tests**, a parametrised test over the spec's R1 table (allowed `["eu_taxonomy","cash_flow","other"]`):

```python
@pytest.mark.parametrize("value,expected", [
    ("Cash flow", "cash_flow"), ("cash-flow capex", "cash_flow"), ("other $ (millions)", "other"),
    ("cash flow or EU taxonomy", None), ("operating cash", None)])
def test_label_map(value, expected): ...
    # expected None: value unchanged and corrections == []
    # otherwise: value == expected; corrections == [Correction(rule="label_map", attribute="value",
    #   original=value, corrected=expected, reason=f'"{value}" maps to the allowed value "{expected}".')]
    # and ReasonCode.AUTO_CORRECTED in review_reasons

def test_label_map_leaves_non_string_values_alone(): ...  # value None and value True -> no correction (Review Focus 5)
def test_allowed_value_is_not_corrected(): ...           # "cash_flow" -> no correction
def test_apply_twice_adds_no_second_correction(): ...    # apply_corrections(apply_corrections(rows)) == apply_corrections(rows)
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_corrections.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the module with `apply_corrections` (R2–R4 as no-op stubs for now) and `_label_map` per spec R1 (`norm`, exact match first, then the unique allowed value whose tokens are all in the value's tokens).
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: corrections step with label mapping`.

### Task 3: R2 period_fill

**Files:**
- Modify: `backend/arp/extraction/corrections.py` (`_period_fill(rows_for_field, spec, *, documents_by_id, fiscal_year_end, planned_ids) -> list[ExtractedField]`)
- Test: `backend/tests/test_corrections.py`

**Interfaces:**
- Consumes: Task 2 helpers. `period_start` is computed the same way `arp.normalise.period.resolve_period` does for a fiscal year (one year earlier plus a day).
- Produces: rows with `period_end`/`period_start` filled, or `ReasonCode.PERIOD_MISSING` added.

- [ ] **Step 1: Write the failing tests**, one per spec case, with the spec's exact values:
  - `test_single_year_in_quote` (AC-4): quote "capital expenditures were $2,479 million in 2025", no FYE → `period_end` `2025-12-31`, `period_start` `2025-01-01`, one correction `period_fill`/`period_end`/`None`→`2025-12-31`, reason `The quote names only 2025.`
  - `test_fiscal_year_end_march` (AC-29): FYE `03-31` → `2025-03-31`, `period_start` `2024-04-01`.
  - `test_no_year_takes_report_period_end` (AC-5): cited doc `period_plan.current="2025-12-31"` → `2025-12-31`, reason `No year in the quote; taken from the report's period end 2025-12-31.`
  - `test_two_years_flags_period_missing` (AC-6): no correction, `PERIOD_MISSING` in `review_reasons`.
  - `test_no_year_no_report_period_flags` (AC-31).
  - `test_planned_field_never_takes_report_period_end` (AC-18): field `tc_capex_total_planned`, no year → `PERIOD_MISSING`, no correction.
  - `test_fill_that_would_duplicate_a_period_flags_instead` (AC-19): existing 2025 row plus a period-less row naming 2025 → still one 2025 row; period-less row gets `PERIOD_MISSING`.
  - `test_ungrounded_quotes_do_not_fill` (Review Focus 1): citation with `grounded=False` naming 2025 and no report period end → `PERIOD_MISSING`.
  - `test_enum_and_boolean_rows_are_not_filled`: only numeric fields are touched.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `_period_fill` per spec R2 (year regex `\b(19|20)\d{2}\b` over grounded quotes; clash check across the field's rows) and wire it into `apply_corrections`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: fill missing fiscal years from the quote or report period`.

### Task 4: R3 unit_scale

**Files:**
- Modify: `backend/arp/extraction/corrections.py` (`_unit_scale(row, spec, *, fiscal_year_end) -> ExtractedField`)
- Test: `backend/tests/test_corrections.py`

**Interfaces:**
- Consumes: `arp.normalise.units.split_unit(text) -> (scale, ambiguous, base)`; `arp.normalise.value.typed_value(field, pv, *, fiscal_year_end, planned=None, decimal=None) -> TypedValue`; `arp.extraction.extractor_agent.PeriodValue`.
- Produces: rows with the rewritten `unit` and recomputed `canonical_value`, `canonical_unit`, `scale_applied`. The recompute builds a `PeriodValue` from the row (`value`, `state=value_state`, `raw_value_text`, `unit_text=<new unit>`, `period_text`, `basis_text=basis`) and calls `typed_value`. It then replaces the old typing reasons with the new ones: it removes `ReasonCode.CHECK_FAILED` and the sentence `scale stated twice and differs` from `verifier_notes` only when the old typing produced them and the new typing doesn't.

- [ ] **Step 1: Write the failing tests:**
  - `test_billion_quote_rewrites_millions_unit` (AC-7): value 2.794, unit `USD millions`, quote "Capital expenditures were $2.794 billion during 2025" → `unit` `USD billions`; one correction `unit_scale`/`unit`/`USD millions`→`USD billions`, reason `The quote says "billion" next to 2.794.`; `canonical_value == 2794000000.0`; `canonical_unit == "USD"`; `scale_applied == 1e9`.
  - `test_case_is_kept` : unit `Millions of dollars` → `Billions of dollars`.
  - `test_no_scale_word_no_correction` (AC-8): quote "Capital expenditures were 2.794 during 2025".
  - `test_already_converted_scale_is_left_alone` (AC-20): unit `USD`, raw text "$2.794 billion" → no correction; `canonical_value == 2794000000.0`.
  - `test_two_scale_words_no_correction` (AC-27).
  - `test_stale_scale_conflict_is_cleared` (AC-28): unit `USD millions`, raw "$2.794 billion" → unit `USD billions`; no `check_failed` in `review_reasons`; `scale stated twice and differs` not in `verifier_notes`; `auto_corrected` present.
  - `test_separators_in_printed_value` (Review Focus 2): 2479 matches "$2,479 million"; 2.794 does not match "2,794 billion".
  - `test_currency_symbol_unit_gets_word_appended` (Review Focus 3): unit `$`, quote "$2.8 billion", value 2.8 → unit `$ billion`; no exception.
  - `test_percentage_rows_untouched`; `test_ungrounded_quote_no_correction` (Review Focus 1).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `_unit_scale` per spec R3 (effective scale = `scale_applied` when set, else `split_unit(unit)[0]`; quote scale = scale word within 3 characters after the printed value) and wire it in.
- [ ] **Step 4: Run.** Expected: PASS. Also `python3 -m pytest tests/test_aggregator.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: correct a unit whose scale contradicts the grounded quote`.

### Task 5: R4 planned_move

**Files:**
- Modify: `backend/arp/extraction/corrections.py` (`_planned_move(rows, schema, *, documents_by_id, input_hashes) -> list[ExtractedField]`)
- Test: `backend/tests/test_corrections.py`

**Interfaces:**
- Consumes: Task 2 helpers; `input_hashes` from `apply_corrections`.
- Produces: moved rows with `field_id`/`field_name` of the planned field, `input_hash = input_hashes[planned_id]`, `provenance.field_version` = the planned field's `version`. Cleared rows have `value=None`, `value_state=not_found`.

- [ ] **Step 1: Write the failing tests:**
  - `test_future_actual_moves_to_planned_field` (AC-9): report period end `2025-12-31`, `tc_capex_total` 2.5 for `2026-12-31`, no planned row → no `tc_capex_total` row with a value for 2026; exactly one `tc_capex_total_planned` row for `2026-12-31` with value 2.5, one correction `planned_move`/`field_id`/`tc_capex_total`→`tc_capex_total_planned`, reason `Period 2026-12-31 is after the report's period end 2025-12-31, so it is a planned figure.`, `input_hash` equal to the planned field's hash.
  - `test_existing_planned_row_clears_actual_and_keeps_alternative` (AC-25): planned 2.5, actual 3.0 → actual `value` None, `value_state` `not_found`, one correction with `original` 3.0; planned row `alternatives` include value 3.0 with `source` `planned_move`.
  - `test_close_values_add_no_alternative` (AC-26): actual 2.51 → no `planned_move` alternative.
  - `test_field_without_link_is_untouched` (AC-10).
  - `test_link_to_missing_field_is_ignored` (Review Focus 4).
  - `test_not_after_report_period_is_untouched`: period `2025-12-31` → no correction.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `_planned_move` per spec R4 and wire it in. `Alternative.source` gains the literal `"planned_move"` if it is a closed set.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: move planned figures out of actual fields`.

### Task 6: Wire into the pipeline

**Files:**
- Modify: `backend/arp/extraction/pipeline.py` (`_extract_company(..., corrections: bool = False)`; call `apply_corrections` after `fields.extend(...)` and before `check_record`; collect each field's `h` into `input_hashes`; `execute_extraction_run` passes `corrections=schema.schema_id not in {TRANSITION_PLAN_SCHEMA_ID, plan_preset.SCHEMA_ID}`)
- Test: `backend/tests/test_extraction_corrections_pipeline.py` (uses the `fake_llm`, `pg` fixtures and helpers like `_released_run` / `_run_trial` from `tests/test_extraction_pipeline.py`)

**Interfaces:**
- Consumes: `apply_corrections` (Task 2).
- Produces: corrected, routed rows in run results and review items.

- [ ] **Step 1: Write the failing tests:**
  - `test_corrected_rows_route_to_review` (AC-11): trial run where the fake extractor returns `cash-flow capex` → row has `auto_corrected` in `review_reasons`, `route` `review`.
  - `test_rows_needing_no_correction_are_unchanged` (AC-12): the spec's AC-12 answers → `corrections` empty, `route` `review` with `unreleased_version` in `route_reasons`, no `auto_corrected`/`period_missing`.
  - `test_reused_row_keeps_one_correction` (AC-13) and `test_moved_row_is_reused_under_planned_field` (AC-17): two runs with unchanged inputs; second run's row has `reused_from_run` set and exactly one correction.
  - `test_released_schema_auto_accepts_uncorrected_twin_only` (AC-32): released, audited custom enum field; company A `cash_flow` → `route` `auto_accept`; company B `Cash flow` → `value` `cash_flow`, `route` `review`, `auto_corrected` in `review_reasons`.
  - `test_transition_plan_schemas_get_no_corrections` (AC-21, AC-22) and `test_research_callers_get_no_corrections` (AC-23, AC-24): call `_extract_company` without the keyword with one answer per rule → no `corrections`, `auto_corrected` or `period_missing`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the wiring listed under Files.
- [ ] **Step 4: Run** the new file, then `tests/test_extraction_pipeline.py tests/test_financials_extraction_pipeline.py tests/test_tnfd_extraction_pipeline.py` and the transition-plan and replication test files (AC-30). Expected: all PASS, no existing test changed.
- [ ] **Step 5: Commit** `feat: run corrections in custom-schema extraction runs`.

### Task 7: Reviewer view

**Files:**
- Modify: `backend/arp/review/context.py` (bundle gains `"corrections": v.get("corrections", [])` and `"field_names": {field_id: name}` for the schema, so the UI can show names for `planned_move`)
- Create: `frontend/src/lib/corrections.ts` (`correctionLine(c: Correction, fieldName: (id: string) => string): string`)
- Modify: `frontend/src/components/ExtractionResults.tsx` (field detail: one `<p>` per correction above the verifier notes)
- Modify: `frontend/src/components/ReviewControls.tsx` (same lines under the value)
- Test: `frontend/tests/corrections.test.ts`, `backend/tests/test_review_context.py` (new test only)

**Interfaces:**
- Consumes: `Correction` from the generated API types.
- Produces: `correctionLine`, which returns exactly `Auto-corrected (<label>): <original> → <corrected>. <reason>`, with labels `label_map` "Label", `period_fill` "Year", `unit_scale` "Unit scale", `planned_move` "Planned figure"; null shown as `—`; for `planned_move`, original and corrected are passed through `fieldName`.

- [ ] **Step 1: Write the failing tests:** the four AC-15 lines as exact strings in `corrections.test.ts`, one per rule. Also `test_context_includes_corrections` in `test_review_context.py`: an item whose row has one correction returns it under `corrections`.
- [ ] **Step 2: Run** `npm test -- corrections` and `python3 -m pytest tests/test_review_context.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the helper, the bundle keys and the two render sites.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` and the backend test. Expected: PASS. Then screenshot the extraction results with a corrected row using Playwright, and run `/impeccable:impeccable audit` on it (repo rule for UI changes).
- [ ] **Step 5: Commit** `feat: show auto-corrections to reviewers`.

### Task 8: Final checks and PR

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest tests/test_corrections*.py tests/test_extraction*.py tests/test_review_context.py tests/test_aggregator.py tests/test_routing.py -q`. Expected: PASS.
- [ ] **Step 2:** Re-read the diff against the spec's R1–R4 and the Acceptance table. Every `holdout` row has a matching unit test here; list rows still owed to the holdout repo in the PR.
- [ ] **Step 3:** Open the PR against `main`: label `risk:normal`, `Spec: extraction-auto-corrections` on its own line, all test changes listed, and the note that `openwiki/` (extraction page) needs a refresh for the new step. CI runs the golden set (AC-16).
