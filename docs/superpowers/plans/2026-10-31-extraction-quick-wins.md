# Extraction Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Typed model answers per field type, a failed answer that no longer fails the company, two format-check gaps, a share/ratio check, and a row-label check that skips non-numeric fields.

**Architecture:** A helper builds a per-field draft model (same class name `ExtractionDraft`, so `FakeLLMClient` scripts keep working) that `extract_field` and `blind_verify` pass to `complete_structured`. The field graph catches the final `pydantic.ValidationError` per field. The checks change in place in `arp/checks/`.

**Tech Stack:** Python 3.13, pydantic v2 (`create_model`), LangGraph, pytest (asyncio auto mode).

**Spec:** `docs/superpowers/specs/2026-10-31-extraction-quick-wins-design.md` (approved 2026-10-31). Every AC-n below refers to its Acceptance table.

## Global Constraints

- Group calls (`extract_group`), `extract_plan`, Financials and TNFD keep today's loose `PeriodValue`.
- Only `green_revenue_share_pct`, `green_capex_share_pct`, `green_opex_share_pct` change version (2 → 3).
- Detail texts are copied verbatim from the spec (AC-6, 8, 8b, 9, 9b, 12).
- Never delete or weaken an existing test; list every changed test in the PR description.
- After the `ReasonCode` change: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, fix `tsc -b`, commit both generated files.

## Review Focus

1. A numeric field answered `"1,234"` (thousands separator as text): pydantic rejects it, retry asks again. Expect a retry, not a crash. Pin in Task 1 (`test_number_text_with_comma_retries`).
2. A boolean field answered `"true"` (string): pydantic lax mode coerces to `True`. Expected and acceptable; pin it so a later strict-mode switch is a visible change (Task 1, `test_boolean_string_true_coerces`).
3. An enum field whose `allowed_values` is empty or None: the helper must fall back to `str`, not build `Literal[()]`. Pin in Task 1.
4. A share row whose denominator is negative: `ratio` is computed, check may fail; must not raise. Pin in Task 4 (`test_ratio_negative_denominator_no_crash`).
5. A blind verifier that fails validation on a non-high-risk field never happens (non-high-risk uses `verify_extraction`, untouched); Task 2 only wraps `blind_verify`.

---

### Task 1: Typed draft model for extractor and blind verifier

**Files:**
- Modify: `backend/arp/extraction/extractor_agent.py` (add helper; `extract_field` uses it)
- Modify: `backend/arp/extraction/verifier_agent.py` (`blind_verify` uses it)
- Test: `backend/tests/test_typed_draft.py` (new)

**Interfaces:**
- Produces: `draft_model_for(field: FieldDefinition) -> type[ExtractionDraft]` in `extractor_agent.py`. Returns a subclass named `"ExtractionDraft"` whose `values` items are a `PeriodValue` subclass with `value` typed per the spec table (boolean → `bool | None`; number/currency_amount/percentage → `float | None`; enum with allowed_values → `Literal[*allowed_values] | None`, else `str | None`; string/date → `str | None` with a `field_validator(mode="before")` turning an int/float into `str` without a trailing `.0` for integers, e.g. `11115 → "11115"`). Cache with `functools.lru_cache` keyed on `(data_type, tuple(allowed_values or ()))`.
- `extract_field` and `blind_verify` return the instance as `ExtractionDraft` (the subclass is one).

- [ ] **Step 1: Write failing tests** (pattern: `tests/test_langchain_client_retry.py` `_FakeMessages` / `_message` drive the real `LangChainAnthropicClient`, so the validation retry is real)

```python
async def test_ac1_boolean_number_then_true():      # AC-1, AC-1b
    draft = await _extract(BOOL_FIELD, [{"values": [{"value": 220221}], "confidence": .9},
                                        {"values": [{"value": True}], "confidence": .9}])
    assert draft.values[0].value is True and messages.calls == 2
async def test_ac2_boolean_text_every_call_raises(): # AC-2: pytest.raises(pydantic.ValidationError), calls == 3
async def test_ac3_enum_label_then_code():           # AC-3: value == "eu_taxonomy"
async def test_ac3b_enum_null_not_found():           # AC-3b, AC-3c: value is None, calls == 1
async def test_ac5_currency_int():                   # AC-5, AC-5b: value == 11887.0, calls == 1
async def test_ac5c_percentage_text_then_number():   # AC-5c: value == 39.6
async def test_ac5d_string_number_kept_as_text():    # AC-5d: value == "11115"
async def test_ac5e_date_text():                     # AC-5e: value == "2025-12-31"
async def test_ac4_blind_verify_yes_then_false():    # AC-4, AC-4b: agrees is True, calls == 2
def test_number_text_with_comma_retries():           # Review Focus 1
def test_boolean_string_true_coerces():              # Review Focus 2
def test_enum_without_allowed_values_is_str():       # Review Focus 3
```

- [ ] **Step 2:** `cd backend && python3 -m pytest tests/test_typed_draft.py -q` → FAIL (`draft_model_for` not defined).
- [ ] **Step 3:** Implement `draft_model_for` and pass it as `output_model` in `extract_field` and `blind_verify` (the blind draft's `complete_structured` call). Do not touch `extract_group`, `extract_plan`, `verify_extraction`.
- [ ] **Step 4:** `python3 -m pytest tests/test_typed_draft.py tests/test_field_graph_high_risk.py tests/test_verifier_redesign.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(extraction): typed answer format per field type`.

### Task 2: One failed answer fails one field, not the company

**Files:**
- Modify: `backend/arp/schemas/review.py` (`ReasonCode.EXTRACTION_FAILED = "extraction_failed"`)
- Modify: `backend/arp/extraction/field_graph.py` (`_extract`, aggregate step)
- Modify: `backend/arp/extraction/verifier_agent.py` (`blind_verify`)
- Generated: `backend/openapi.json` (or wherever `export_openapi.py` writes), `frontend/src/api/` generated types
- Test: `backend/tests/test_typed_draft_failures.py` (new)

**Interfaces:**
- Consumes: `draft_model_for` (Task 1).
- `_extract`: on `pydantic.ValidationError` from `extract_field`, return `{"draft": ExtractionDraft(confidence=0.0), "extract_failed": True, ...}` (add `extract_failed: bool` to `FieldState`, default False). The aggregate step adds `ReasonCode.EXTRACTION_FAILED` to every row built from such a state and routes it to review.
- `blind_verify`: on `pydantic.ValidationError` from its call, return `(VerifierOutput(agrees=False, confidence=0.0, disagreement_type=DisagreementType.NOT_DISCLOSED, notes="blind re-extraction failed: the answer did not fit the field type"), LLMUsage())`.

- [ ] **Step 1: Write failing tests**

```python
async def test_ac19_run_completes_with_one_failed_field():   # AC-19: status completed, 1/1 companies
async def test_ac19c_other_field_kept():                     # AC-19c: currency row value 11887.0
async def test_ac19d_failed_field_row():                     # AC-19d: value_state not_found, route review, "extraction_failed" in review_reasons
async def test_ac19b_blind_failure_routes_review():          # AC-19b: route review
async def test_ac19e_blind_failure_is_not_disclosed():       # AC-19e: disagreement_type == "not_disclosed"
```
Use `execute_extraction_run` with a 2-field schema and a stand-in client whose `complete_structured` raises `pydantic.ValidationError` for the boolean field's prompt and returns `11887` for the currency field.

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement as in Interfaces.
- [ ] **Step 4:** `python3 -m pytest tests/test_typed_draft_failures.py -q` → PASS. Then `python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b` → no errors.
- [ ] **Step 5:** Commit `feat(extraction): a failed answer fails only its field`.

### Task 3: Format-check gaps

**Files:**
- Modify: `backend/arp/checks/runner.py` (`check_format`)
- Test: `backend/tests/test_checks_runner.py` (add tests)

**Interfaces:**
- Bare-number regex `^[+-]?\d[\d,.' ]*$` on the stripped text (spec Design 2). Currency unit detection: an ISO 4217-looking 3-letter upper-case token, or `€`, `$`, `£`, in `unit` or `canonical_unit`.

- [ ] **Step 1:** Add tests `test_ac6_*` … `test_ac10_*`, `test_ac17_boolean_number_still_blocks` with the spec's exact values, outcomes and detail texts (AC-6, 6b, 6c, 6d, 7, 8, 8b, 8c, 9, 9b, 10, 17).
- [ ] **Step 2:** `python3 -m pytest tests/test_checks_runner.py -q` → new tests FAIL.
- [ ] **Step 3:** Extend `check_format` (block severity, as the existing branch).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(checks): flag numbers in text fields and percent/currency unit mix-ups`.

### Task 4: Share check and green preset

**Files:**
- Modify: `backend/arp/schemas/datapoints.py` (`CheckConfig.ratio_of: list[str] = []`)
- Modify: `backend/arp/checks/plausibility.py` (add `check_ratio`), `backend/arp/checks/__init__.py` (register in layer 3)
- Modify: `backend/arp/presets/green.py` (share fields: `ratio_of`, `version=3`)
- Test: `backend/tests/test_checks_plausibility.py`, `backend/tests/test_presets_green.py`

**Interfaces:**
- `check_ratio(spec, field, ctx) -> list[CheckResult]`, id `plausibility.ratio`, severity warn, uses `_same_period` and `numeric_of`. `ratio = round(100 * num / den, 1)`; fail when `abs(share - ratio) > 1 + 1e-9`; detail `f"share {share:g} vs {num:g}/{den:g} = {ratio:g} %"`.

- [ ] **Step 1:** Tests for AC-11, 12, 12b, 12c, 13, 13b, 13c, 13d, 14, 14b, plus `test_ratio_negative_denominator_no_crash` (Review Focus 4).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; in `green.py` pass `ratio_of=[gtotal, total]` into the share field's `CheckConfig` and set its `version=3`.
- [ ] **Step 4:** `python3 -m pytest tests/test_checks_plausibility.py tests/test_presets_green.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(checks): share must fit numerator/denominator`.

### Task 5: Row-label check skips non-numeric fields

**Files:**
- Modify: `backend/arp/checks/numeric.py` (`check_row_label`)
- Test: `backend/tests/test_checks_numeric.py`

- [ ] **Step 1:** Tests for AC-15 (boolean), AC-15b (enum, string, date), AC-16 (currency still fails; the existing `test_row_label_mismatch_warns` already covers it, keep it).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** First line of `check_row_label`: return not applicable when `spec.data_type in (BOOLEAN, ENUM, STRING, DATE)`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `fix(checks): row-label check only for numeric fields`.

### Task 6: Must-not-change guards and full suite

**Files:**
- Test: `backend/tests/test_quick_wins_unchanged.py` (new), snapshots under `backend/tests/fixtures/quick_wins/`

- [ ] **Step 1:** Before any Task 1–5 code is on the branch (`git stash` or a `main` worktree), record AC-22/22b/22c snapshots: run `extract_plan` (`sch_transition_plan_actions`, `ta_action_text`), `extract_financials` (`capex`) and `extract_tnfd` (`general_requirements`) with a `FakeLLMClient` script that includes `value: "Not disclosed"` for a numeric or yes/no item; save the stored result and the call count as JSON.
- [ ] **Step 2:** Tests: `test_ac22_*`, `test_ac22b_*`, `test_ac22c_*` and their `_calls` variants compare against the snapshots; `test_ac18_group_call_keeps_loose_format` and `test_ac18b_group_call_one_call` (non-high-risk boolean via `extract_group`, scripted `"yes"`).
- [ ] **Step 3:** `cd backend && ruff check . && python3 -m pytest -q` → all pass (AC-20). List every changed existing test in the PR description.
- [ ] **Step 4:** Commit `test: guards for unchanged extraction paths`.
- [ ] **Step 5:** Open the PR against `main` with `Spec: extraction-quick-wins`, `risk:normal`; AC-21 (golden set) is checked by CI; a missing `ARP_ANTHROPIC_API_KEY` counts as fail.
