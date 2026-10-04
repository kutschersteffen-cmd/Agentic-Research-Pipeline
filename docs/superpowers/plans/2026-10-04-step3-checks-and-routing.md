# Step 3: Checks and Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every extracted value passes a layered set of stored checks, every document is confirmed against the issuer before extraction, fields are planned (applicability, periods, documents) before any model call, and every value is routed to exactly one of auto-accept, review or hold, with auto-accepted values recorded as decided by the system.

**Architecture:**
- Planning (new `arp/planning/`) runs inside `_extract_company` before the field loop, using rules only: entity confirmation holds mismatched documents; applicability skips fields by rule; period planning lists the periods each document reports; document routing picks the documents per field and skips a field whose inputs are unchanged since the last run.
- Checks (new `arp/checks/`) run once per company record, after all fields are aggregated and before routing. Five layers, cheapest first; a `block` result stops the later layers for that field. Results are stored on `ExtractedField.checks`.
- Routing (`arp/extraction/routing.py`) turns review reasons, check results, field quality and the field definition into `auto_accept | review | hold`. Only `review` rows enter the review queue. `auto_accept` lives on the result row the pipeline writes, never in the human decision log, so no API caller can forge a system decision.
- Identity: `discovery/identity_graph.py` gains a rules step (exact LEI, then `IdentifierMap` for CIK/ISIN) ahead of `_adjudicate`. A name-only or multi-candidate match always becomes a review item.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, stdlib `re`/`math`/`hashlib`/`json`, LangGraph (already used), pytest with `FakeLLMClient` (`tests/conftest.py`); React + TypeScript (Vite), node test runner.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4`. This step covers E34, E35, E36, E37, E42, E62, E63, E64, E65, E66, E67 and E68. Paths are relative to `backend/` unless they start with `frontend/`. It builds on step 1 (`docs/superpowers/plans/2026-10-03-step1-identity-review-keys.md`) and step 2 (`docs/superpowers/plans/2026-10-04-step2-capture-and-typing.md`).

## Global Constraints

- No new dependencies, backend or frontend.
- **Voting is frozen.** Do not change `arp/api/routers/voting.py`, `arp/voting/`, `arp/cli/voting.py`, `arp/stewardship/voting_feed.py`, `frontend/src/components/BallotReview.tsx`, `ReviewerField.tsx`, `ConfirmDecision.tsx`, the voting pages, or any voting test.
- Old run directories and data must still load: old `results.jsonl` rows (no `checks`, `route`, `route_reasons`, `input_hash`), old `schema.json` snapshots and registry files (no `check_config`, `applicability_rules`, `document_routing`, `auto_accept_min`, `high_risk`), old identity results (no `match_rule`). Every new model field has a default.
- A row with `route` absent (`None`) is a legacy row: it is queued, projected and displayed exactly as in step 2 (queued iff `review_reasons`).
- The grounding gate is never weakened. Checks only add failures; no check turns an ungrounded value into a grounded one.
- Identity stays LEI-keyed through `issuer_key()` in `arp/schemas/issuer.py`. Review `item_key` stays `"{issuer_key}:{field_id}:{period_end|unspecified}"`.
- Rules before models: E62 match rules, E63 entity confirmation, E64 applicability, E65 period planning and E66 routing make **no** model call. A model is used only when rules leave an identity ambiguous (the existing `_adjudicate`), and its result always goes to review.
- Check outcomes (exact strings): `pass`, `fail`, `not_applicable`. Severities: `info`, `warn`, `block`. Layers: `1` format, `2` numeric, `3` plausibility, `4` cross-source, `5` model.
- A field "passes all checks" when no result has `outcome == "fail"` with severity `warn` or `block`.
- Routes (exact strings): `auto_accept`, `review`, `hold`. Document match status: `confirmed`, `ambiguous`, `mismatch`. Match rules: `exact_lei`, `identifier_map`, `supplied`, `name_only`, `ambiguous`.
- Route reasons (exact strings): every `ReasonCode` value, plus `check:<check_id>`, `first_audit_pending`, `below_auto_accept_min`, `high_risk_not_found`, `entity_mismatch`, `unreleased_version` (a review reason, not a hold).
- No new review reason codes. A failed check adds the existing `check_failed`; an ambiguous identity uses `match_ambiguous`; a rule skip uses `not_applicable_by_rule` (as a route reason, not a review reason).
- System decisions are never written to `review_decisions.jsonl`. That file stays human-only, written through `record_review_decision` with a `Principal`.
- Backend checks: `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest -q && ruff check arp tests`. The baseline is 45 failures that already exist (Chromium, pdftoppm, postgres factories, the nltk hardlink sandbox, botocore). There must be no new failures.
- Frontend checks: `cd frontend && npm run lint && npm test && npm run build`. The baseline is 0 errors.

## Review Focus

1. **An old run opened after this change.** Rows without `route`/`checks` are still queued by `review_reasons`, still project as `auto_approved` or by decision, and the frontend shows no route badge. Tests in Task 12 (`test_legacy_rows_without_route_unchanged`) and Task 13.
2. **Numbers printed in other formats.** `"4.210,5"`, `"4 210,5"` (NBSP or thin space), `"(1,234)"`, `"−1,234"` and `"1'234"` parse to the right value, so `numeric.in_span` never blocks a correct European-format value. Test in Task 2 (`test_parse_number_formats`).
3. **Same documents, new field version.** A bumped field version, or a changed `extraction_instructions` saved as a new version, must re-extract even though the document hashes are unchanged. Test in Task 10 (`test_field_version_change_reextracts`).
4. **A company with missing attributes.** No ISIC code, no country, no regimes, no LEI: applicability never skips, and the LEI rule never declares a mismatch. Tests in Task 7 (`test_unknown_company_attributes_never_skip`) and Task 6 (`test_provisional_issuer_with_lei_in_text_not_mismatch`).
5. **Parts and total in different units.** Scope 1 in `tCO2e`, total in `ktCO2e`: identities compare `canonical_value`; when canonical units still differ the check is `not_applicable`, never a false fail. Test in Task 3 (`test_identity_mismatched_units_not_applicable`).

---

### Task 1: Layered check framework (E34)

**Files:**
- Modify: `arp/schemas/datapoints.py`: add `CheckOutcome`, `Severity`, `CheckResult`, `CheckConfig`; `FieldDefinition.check_config`; `ExtractedField.checks`.
- Create: `arp/checks/__init__.py` (empty), `arp/checks/runner.py`
- Modify: `arp/extraction/pipeline.py` (`_extract_company`: run `check_record` after the field loop)
- Test: `tests/test_checks_runner.py`

**Interfaces:**
- Produces, in `arp/schemas/datapoints.py`:
  - `class CheckOutcome(StrEnum)`: `PASS="pass"`, `FAIL="fail"`, `NOT_APPLICABLE="not_applicable"`
  - `class Severity(StrEnum)`: `INFO="info"`, `WARN="warn"`, `BLOCK="block"`
  - `class CheckResult(BaseModel)`: `check_id: str`, `layer: int = Field(ge=1, le=5)`, `outcome: CheckOutcome`, `severity: Severity = Severity.INFO`, `detail: str = ""`, `threshold_ref: str | None = None`
  - `class CheckConfig(BaseModel)`: `min_value: float | None = None`, `max_value: float | None = None`, `non_negative: bool = False`, `part_of: str | None = None` (field_id of the whole), `sum_of: list[str] = []` (this field equals the sum of these field_ids), `sum_tolerance: float = 0.01` (relative), `prior_change_max: float | None = 0.5` (relative jump that warns)
  - `FieldDefinition.check_config: CheckConfig = Field(default_factory=CheckConfig)`
  - `ExtractedField.checks: list[CheckResult] = []`
  - `def is_blocking(r: CheckResult) -> bool` (`fail` and `block`) and `def is_failing(r: CheckResult) -> bool` (`fail` and `warn|block`)
- Produces, in `arp/checks/runner.py`:
  - `@dataclass class CheckContext`: `company: CompanyRef`, `issuer_key: str`, `schema: DataPointSchema`, `documents_by_id: dict[str, SourceDocument]`, `record_fields: list[ExtractedField]`, `history: RunHistory | None = None` (Task 4 defines `RunHistory`; type it as a string annotation until then)
  - `Check = Callable[[FieldDefinition, ExtractedField, CheckContext], list[CheckResult]]`
  - `ModelCheck = Callable[[FieldDefinition, ExtractedField, CheckContext], Awaitable[list[CheckResult]]]`
  - `LAYERS: dict[int, list[Check]] = {1: [check_format], 2: [], 3: [], 4: []}`. Later tasks append their checks here.
  - `def threshold_ref(spec: FieldDefinition, name: str) -> str` returns `f"{spec.field_id}:v{spec.version}:check_config.{name}"`.
  - `def check_format(spec, field, ctx) -> list[CheckResult]`: check ids `format.data_type` and `format.allowed_values`, layer 1, severity `block`. `not_applicable` when `value_state` is not `found`/`zero`. `format.data_type` fails when a numeric data type holds a non-numeric value, `boolean` a non-bool, or `date` text that `date.fromisoformat` rejects. `format.allowed_values` fails for an `enum` value outside `allowed_values`; `not_applicable` for other types.
  - `async def run_checks(spec, field, ctx, *, model_check: ModelCheck | None = None) -> list[CheckResult]`: runs `LAYERS[1..4]` in order, then `model_check` as layer 5 when given. After each layer, if any result `is_blocking`, return what was collected (later layers not run, not recorded).
  - `async def check_record(schema, fields, ctx, *, model_check=None) -> list[ExtractedField]`: for each field, `checks = await run_checks(...)`. When any result `is_failing`, append `ReasonCode.CHECK_FAILED` to `review_reasons` (once) and add `"<check_id>: <detail>"` to `verifier_notes`. A field whose `field_id` is not in `schema.fields` is returned unchanged.
- In `_extract_company`: after the loop, `fields = await check_record(schema, fields, CheckContext(...))` with `record_fields=fields`. `history` comes from a new kwarg `history: RunHistory | None = None` (wired in Task 4). `needs_review` becomes `any(f.review_reasons for f in fields)` after checks.
- Layer 5 has no registered check in this step (the verifier redesign is E38, later). The hook exists so the short-circuit is real and tested.

- [ ] **Step 1: Write the failing tests** in `tests/test_checks_runner.py`:
  - `test_layer5_not_called_when_earlier_layer_blocks`: monkeypatch `LAYERS[3] = [lambda s, f, c: [CheckResult(check_id="t.block", layer=3, outcome="fail", severity="block")]]`; a spy `model_check` that records calls. `run_checks` returns results whose last `check_id == "t.block"`, no result has `layer == 4`, and the spy was called 0 times.
  - `test_layer5_called_when_nothing_blocks`: same with a `warn` failure; spy called once, its result is last.
  - `test_enum_outside_allowed_values_blocks`: `format.allowed_values` outcome `fail`, severity `block`.
  - `test_not_found_format_not_applicable`
  - `test_failed_check_adds_check_failed_once`: two failing `warn` results give `review_reasons.count("check_failed") == 1`, and both check ids appear in `verifier_notes`.
  - `test_checks_stored_on_results_row`: `execute_extraction_run` with `FakeLLMClient`; the `results.jsonl` field has a `checks` list containing `format.data_type`.
  - `test_old_field_definition_and_row_load`: a `FieldDefinition` dict without `check_config` gives `check_config == CheckConfig()`; an `ExtractedField` dict without `checks` gives `[]`.

- [ ] **Step 2: Run** `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_checks_runner.py -v`. Expect FAIL (`ModuleNotFoundError: arp.checks`).

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(checks): layered check framework, results stored per field (E34)`.

---

### Task 2: Numeric and table-aware checks (E35)

**Files:**
- Create: `arp/checks/numeric.py`
- Modify: `arp/checks/runner.py` (`LAYERS[2] = [check_number_in_span, check_caption_scale, check_row_label]`)
- Test: `tests/test_checks_numeric.py`

**Interfaces:**
- Consumes: `CheckContext`, `CheckResult`, `LAYERS` (Task 1); `lookup_scale` (`arp/normalise/units.py`).
- Produces:
  - `def parse_number(text: str) -> float | None`. Rules: strip currency symbols, `%` and spaces (incl. U+00A0, U+202F, U+2009) and `'` used as thousands separators; `(x)` and a leading `-`/`−` give a negative; when both `,` and `.` occur the rightmost is the decimal separator; a single `,` followed by exactly 3 digits is a thousands separator, otherwise a decimal; a single `.` is a decimal unless it repeats (`1.234.567`).
  - `def numbers_in(text: str) -> list[float]`: every `parse_number` hit of `re.finditer(r"[(\-−]?\d(?:[\d.,'    ]*\d)?\)?", text)`.
  - `def caption_scale(doc_text: str, char_start: int, window: int = 600) -> tuple[float, str] | None`: the last line in `doc_text[char_start - window : char_start]` that reads as a caption (contains `in <scale word>`, or a scale word in parentheses, e.g. `(USD m)`, `(in thousands)`, `('000)`), with the factor from `lookup_scale`; ambiguous scales (`m`) count only inside a currency caption.
  - `check_number_in_span` → id `numeric.in_span`, layer 2, severity `block`. Applies to numeric data types with `value_state == "found"` and at least one grounded citation with `span_text`. Expected number = `parse_number(raw_value_text)`, else `float(value)`. Pass when `abs(expected)` equals (`math.isclose(rel_tol=1e-9)`) the absolute value of some number in some grounded citation's `span_text`, regardless of `match_method`. Otherwise fail, detail `"value <x> not in grounded span"`.
  - `check_caption_scale` → id `numeric.caption_scale`, layer 2, severity `warn`. `not_applicable` without a caption or for `percentage`. Fail when the caption factor differs from `field.scale_applied or 1.0`; detail names the caption text and both factors.
  - `check_row_label` → id `numeric.row_label`, layer 2, severity `warn`. Takes the source line holding the first grounded citation (`char_start`..`char_end` widened to newlines). `not_applicable` unless that line holds 2 or more numbers (a table row). Pass when a `seed_keyword` or a word of 4+ letters from `spec.name` occurs in the line (case-insensitive); else fail.
- Deferred (state it in the module docstring): column-label checks and table-caption lookup through `Citation.table_ref`. The parser gives no table structure (`table_ref` is always None), so captions are read from the text before the span.

- [ ] **Step 1: Write the failing tests:**
  - `test_fuzzy_quote_with_changed_digit_fails`: a field `value=4210.0`, `raw_value_text="4,210"`, one citation `grounded=True`, `match_method="fuzzy"`, `span_text="Scope 1 emissions of 4,270 tCO2e"`. `numeric.in_span` outcome `fail`, severity `block`.
  - `test_exact_number_in_span_passes`
  - `test_parse_number_formats`: parametrized — `"1,234.5"→1234.5`, `"4.210,5"→4210.5`, `"4 210,5"→4210.5`, `"(1,234)"→-1234.0`, `"−1,234"→-1234.0`, `"1'234"→1234.0`, `"1,5"→1.5`, `"12.5%"→12.5`, `"1.234.567"→1234567.0`.
  - `test_caption_in_thousands_without_scale_warns`: doc text `"Emissions (in thousands of tonnes)\nScope 1  1,234  1,100\n"`, citation span on `"Scope 1  1,234"`, `scale_applied=None`. Outcome `fail`, severity `warn`.
  - `test_caption_scale_applied_passes`: same with `scale_applied=1000.0`.
  - `test_row_label_mismatch_warns`: table line `"Water withdrawal  1,234  1,100"` for a field named `"Scope 1 emissions"` with `seed_keywords=["scope 1"]` gives `fail`; a prose line gives `not_applicable`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_checks_numeric.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures. If an existing pipeline fixture now fails `numeric.in_span`, fix the fixture's quote so it holds the value; do not loosen the check.

- [ ] **Step 5: Commit** with `feat(checks): number-in-span, caption scale and row label checks (E35)`.

---

### Task 3: Plausibility and identity checks (E36)

**Files:**
- Create: `arp/checks/plausibility.py`
- Modify: `arp/checks/runner.py` (`LAYERS[3] = [check_range, check_sign, check_percentage, check_part_of_whole, check_sum_identity]`)
- Test: `tests/test_checks_plausibility.py`

**Interfaces:**
- Consumes: `CheckConfig`, `threshold_ref`, `CheckContext.record_fields` (Task 1).
- Produces:
  - `def numeric_of(f: ExtractedField) -> float | None`: `canonical_value` when set, else `value` when it is a non-bool number, else None. Every check is `not_applicable` when this is None.
  - `check_range` → `plausibility.range`, `block`; uses `min_value`/`max_value`; `threshold_ref(spec, "min_value")` or `"max_value"` on the failing bound; `not_applicable` when both are None.
  - `check_sign` → `plausibility.sign`, `block`; only when `non_negative`.
  - `check_percentage` → `plausibility.percentage`, `block`; only for `data_type == percentage`; bounds `0 <= v <= 100`; `threshold_ref="builtin:percentage_0_100"`.
  - `check_part_of_whole` → `plausibility.part_of_whole`, `warn`; when `part_of` is set, find the record row with `field_id == part_of` and the same `period_end`; fail when part > whole.
  - `check_sum_identity` → `plausibility.sum_identity`, `warn`; when `sum_of` is set, find each part's row with the same `period_end`; `not_applicable` when any part is missing or any `canonical_unit` differs from this field's; fail when `abs(total - sum) > sum_tolerance * max(abs(total), 1e-9)`; detail `"total <t> vs parts <p1>+<p2>=<s>"`; `threshold_ref(spec, "sum_tolerance")`.
- Part/sum failures are `warn`: the check cannot tell which of several fields is wrong, so it must not stop the later layers of this field.

- [ ] **Step 1: Write the failing tests** (a three-field schema `s1`, `s2`, `total` with `total.check_config.sum_of=["s1","s2"]` and `s1.check_config.part_of="total"`, all `canonical_unit="tCO2e"`, `period_end="2024-12-31"`):
  - `test_total_below_parts_fails`: `s1=100`, `s2=50`, `total=120` gives `plausibility.sum_identity` `fail` on `total`.
  - `test_total_equal_parts_passes`: `total=150.5` with tolerance 0.01 passes.
  - `test_part_above_whole_fails`: `s1=200`, `total=150` gives `plausibility.part_of_whole` `fail` on `s1`.
  - `test_percentage_above_100_blocks`
  - `test_negative_when_non_negative_blocks`
  - `test_range_uses_registry_threshold`: `max_value=1e9`, value `2e9`, `threshold_ref == f"{fid}:v1:check_config.max_value"`.
  - `test_identity_mismatched_units_not_applicable`: `s1.canonical_unit="tCO2e"`, `total.canonical_unit="MWh"` gives `not_applicable`.
  - `test_other_period_not_compared`: parts with `period_end="2023-12-31"` give `not_applicable` for the 2024 total.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_checks_plausibility.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(checks): range, sign, percentage, part-of-whole and sum identity checks (E36)`.

---

### Task 4: Run history, prior-period check and restatement candidates (E37)

**Files:**
- Create: `arp/extraction/history.py`, `arp/checks/prior_period.py`
- Modify: `arp/storage/run_store.py` (`restatements_path`)
- Modify: `arp/checks/runner.py` (`LAYERS[4] = [check_comparative_jump, check_last_decided]`)
- Modify: `arp/extraction/pipeline.py`: `execute_extraction_run` loads `RunHistory` once and passes `history=` to `_extract_company`; the worker calls `open_restatement_candidates` after each company.
- Test: `tests/test_checks_prior_period.py`

**Interfaces:**
- Consumes: `effective_decisions` (`arp/orchestration/review_queue.py`), `field_item_key`, `period_key` (`arp/schemas/review.py`), `numeric_of` (Task 3).
- Produces, in `arp/extraction/history.py`:
  - `@dataclass(frozen=True) class PriorValue: value: str | float | bool | None; canonical_value: float | None; run_id: str; decided_by: Literal["human", "system"]`
  - `class RunHistory`:
    - `@classmethod load(cls, run_store: RunStore, *, exclude_run_id: str | None = None) -> RunHistory`: every non-trial extraction run except `exclude_run_id`, oldest `created_at` first, so later runs win. Mark `# ponytail: full scan of past extraction runs per run; index by item_key if run count makes this slow`.
    - `last_decided(item_key: str) -> PriorValue | None`. A field row counts as decided when: its effective decision (co-sign required for `edit`) is `approve` (the row's value, `human`) or `edit` (the edited `value`, `human`); or it has no decision and `route == "auto_accept"` (`system`); or it is a legacy row (`route` absent) that was never queued (`system`, matching the projection's `auto_approved`). `reject` and pending rows do not count.
    - `last_rows(company_id: str, field_id: str) -> list[dict]`: that field's rows from the most recent run that has this company (used by Task 10).
    - `recorded_periods(issuer_key: str) -> set[str]`: period parts of every decided key of the issuer (used by Task 8).
- Produces, in `arp/storage/run_store.py`: `restatements_path(run_id) -> Path` = `run_dir / "restatement_candidates.jsonl"`.
- Produces, in `arp/checks/prior_period.py`:
  - `check_comparative_jump` → `prior.comparative_jump`, layer 4, `warn`. The record rows of the same `field_id` sorted by `period_end` descending; compare this row with the next older row; fail when `abs(new - old) / max(abs(old), 1e-9) > check_config.prior_change_max`; `not_applicable` when no older row, a non-numeric value, or `prior_change_max is None`. `threshold_ref(spec, "prior_change_max")`.
  - `check_last_decided` → `prior.last_decided`, layer 4, `warn`. Looks up `ctx.history.last_decided(field_item_key(ctx.issuer_key, field_id, period_key(field)))`; `not_applicable` without history, without a prior value, or for an `unspecified` period. Fail when the values differ: both numeric and not `math.isclose(rel_tol=1e-6)`, else `str(a) != str(b)`. Detail `"was <old> in run <run_id>, now <new>"`.
  - `class RestatementCandidate(BaseModel)`: `candidate_id: str = Field(default_factory=lambda: new_id("rst"))`, `item_key`, `issuer_key`, `field_id`, `period_end: str`, `previous_value`, `previous_run_id: str`, `new_value`, `run_id: str`, `doc_ids: list[str]`, `status: Literal["open"] = "open"`, `opened_at: str = Field(default_factory=now_iso)`.
  - `def open_restatement_candidates(run_store: RunStore, run_id: str, record: ExtractionRecord, history: RunHistory) -> int`: for each field row that is a **comparative** (not the latest `period_end` of its `field_id` in the record) and whose `prior.last_decided` result is `fail`, append one candidate; return the count. Publishing the restatement is step 5.

- [ ] **Step 1: Write the failing tests.** Build history by writing a prior non-trial run's manifest, `results.jsonl` and an `approve` decision with `RunStore` directly:
  - `test_differing_comparative_opens_one_candidate`: prior run decided FY2023 = 1000; the new record has FY2024 = 1100 and FY2023 = 1050. `open_restatement_candidates` returns 1; `restatement_candidates.jsonl` has one row with `period_end == "2023-12-31"`, `previous_value == 1000`, `new_value == 1050`.
  - `test_equal_comparative_opens_none`: FY2023 = 1000 again gives 0 and no file rows.
  - `test_current_period_difference_warns_but_no_candidate`: FY2024 differs from a prior decided FY2024: `prior.last_decided` `fail`/`warn`, 0 candidates.
  - `test_jump_past_tolerance_warns`: FY2024 = 2000, FY2023 = 1000, `prior_change_max=0.5` gives `prior.comparative_jump` `fail`, `warn`.
  - `test_rejected_and_trial_values_not_prior`: a rejected decision and a trial run's row give `last_decided is None`.
  - `test_auto_accepted_row_is_system_decided`: a prior row with `route="auto_accept"` gives `decided_by == "system"`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_checks_prior_period.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** The worker in `execute_extraction_run` calls `open_restatement_candidates(run_store, run_id, result.record, history)` after setting `result.record.run_id`.

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(checks): prior-period jump check, restatement candidates (E37)`.

---

### Task 5: IdentifierMap and trusted match rules (E62)

**Files:**
- Modify: `arp/schemas/issuer.py` (`IdentifierMap`), `arp/schemas/common.py` (`CompanyRef.isin`), `arp/schemas/discovery.py` (`IdentityResolutionResult` fields)
- Create: `arp/storage/identifier_map.py`, `arp/discovery/match_rules.py`
- Modify: `arp/config.py` (`identifier_map_path: Path = REPO_ROOT / "data" / "identifier_map.jsonl"`)
- Modify: `arp/discovery/identity_graph.py` (rules step ahead of `_adjudicate`), `arp/discovery/identity_pipeline.py` (pass the map; reuse unchanged matches)
- Modify: `tests/test_identity_graph.py`, `tests/test_identity_pipeline.py` (tests that assumed an unflagged clean EDGAR match)
- Test: `tests/test_match_rules.py` (new), plus the two files above

**Interfaces:**
- Produces:
  - `class IdentifierMap(BaseModel)` in `arp/schemas/issuer.py`: `issuer_key: str`, `scheme: Literal["LEI", "CIK", "ISIN"]`, `value: str`, `valid_from: str | None = None`, `valid_to: str | None = None` (ISO dates; `valid_to` exclusive).
  - `CompanyRef.isin: str | None = None`.
  - `class IdentifierMapStore` in `arp/storage/identifier_map.py`, JSONL through `append_jsonl`/`read_jsonl`:
    - `__init__(self, path: Path)`
    - `add(row: IdentifierMap) -> None`
    - `resolve(scheme: str, value: str, *, on: str | None = None) -> list[str]`: distinct `issuer_key`s valid on `on` (today when None). Values compare normalised: CIK without leading zeros, ISIN and LEI upper-case without spaces.
    - `rows_for(issuer_key: str) -> list[IdentifierMap]`
  - In `arp/discovery/match_rules.py`:
    - `class MatchRule(StrEnum)`: `EXACT_LEI="exact_lei"`, `IDENTIFIER_MAP="identifier_map"`, `SUPPLIED="supplied"`, `NAME_ONLY="name_only"`, `AMBIGUOUS="ambiguous"`
    - `@dataclass(frozen=True) class RuleOutcome: rule: MatchRule; resolved: bool; issuer_key: str | None; candidates: list[str]`
    - `def identifiers_of(company: CompanyRef) -> dict[str, str]`: the non-empty, normalised `lei`, `cik`, `isin`.
    - `def apply_identifier_rules(company, idmap: IdentifierMapStore | None) -> RuleOutcome | None`, in order:
      1. `lei_is_valid(normalise_lei(company.lei))` → `EXACT_LEI`, resolved, `issuer_key` = the LEI.
      2. `cik`, then `isin`, through `idmap.resolve`: one key → `IDENTIFIER_MAP`, resolved; two or more → `AMBIGUOUS`, not resolved, `candidates` = the keys.
      3. `website` or `cik` supplied but not mapped → `SUPPLIED`, resolved, `issuer_key=None` (today's "already known" path).
      4. Otherwise None.
    - `def apply_name_rules(company, signals: IdentitySignals) -> RuleOutcome | None`: exactly one EDGAR match with an exact title (`_clean_edgar_match`, moved here) → `NAME_ONLY`, **not resolved**, `candidates=[cik]`; otherwise None (goes to `_adjudicate`).
    - `def needs_recheck(result: IdentityResolutionResult, company: CompanyRef, idmap) -> bool`: True when `identifiers_of(company) != result.identifiers`, or when `apply_identifier_rules(company, idmap)` now gives a different `issuer_key` or rule than the result recorded.
  - New `IdentityResolutionResult` fields: `match_rule: str = ""`, `resolved_issuer_key: str | None = None`, `identifiers: dict[str, str] = {}`, `reason_codes: list[ReasonCode] = []`.
  - Graph shape: `check_known` → `apply_rules` (identifier rules): outcome → `finalize_rules`; None → `gather_signals` → name rules: `NAME_ONLY` → `finalize_rules`; None → `adjudicate` → `finalize`.
    - `finalize_rules`: resolved outcomes give `verdict=RESOLVED`, `flagged_for_review=False`; `NAME_ONLY`/`AMBIGUOUS` give `verdict=UNCERTAIN`, `flagged_for_review=True`, `reason_codes=[MATCH_AMBIGUOUS]`, `resolved_cik` = the single candidate CIK for `NAME_ONLY`. Zero LLM calls.
    - `finalize` (after `_adjudicate`): `match_rule="ambiguous"`, `flagged_for_review=True` always, `reason_codes=[MATCH_AMBIGUOUS]`. The model's answer is a suggestion for the reviewer.
    - Every result records `identifiers=identifiers_of(company)`.
  - `resolve_company_identity(..., identifier_map: IdentifierMapStore | None = None)`.
  - `execute_identity_run(..., previous_run_id: str | None = None)`: when a previous result exists for the company and `not needs_recheck(...)`, reuse it (zero calls); otherwise resolve again. Passes `IdentifierMapStore(settings.identifier_map_path)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_name_only_match_always_creates_review_item` (in `test_identity_pipeline.py`): a single exact EDGAR title match; result `flagged_for_review is True`, `match_rule == "name_only"`, `reason_codes == ["match_ambiguous"]`; the run's review queue has one row for the company; LLM calls 0.
  - `test_exact_lei_resolves_without_lookup`: valid LEI, no website/cik; `match_rule == "exact_lei"`, `resolved_issuer_key == lei`, not flagged; the fake EDGAR and search are never called.
  - `test_cik_resolves_through_identifier_map`: map row `(LEI_X, "CIK", "0000320193")`, company `cik="320193"`; `match_rule == "identifier_map"`, `resolved_issuer_key == LEI_X`.
  - `test_cik_mapping_to_two_issuers_is_ambiguous`: flagged, `match_rule == "ambiguous"`.
  - `test_expired_mapping_ignored`: `valid_to` in the past gives no map hit.
  - `test_adjudicated_result_always_flagged`: an LLM verdict `RESOLVED` with confidence 0.99 is still `flagged_for_review is True`.
  - `test_changed_identifier_triggers_recheck`: `needs_recheck` is False for the same company, True after `cik` changes, and True after a new map row sends its CIK to another issuer. `execute_identity_run(previous_run_id=...)` makes 0 LLM calls for an unchanged company.
  - `test_old_identity_result_loads`: a row without `match_rule` validates with `match_rule == ""`.
  - Update `test_clean_single_exact_edgar_match_resolves_with_zero_llm_calls` to expect flagged/`name_only` (still 0 calls), and the `enriched_universe` "clean resolved" test to need an `approve` decision.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_match_rules.py tests/test_identity_graph.py tests/test_identity_pipeline.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(identity): exact-LEI and identifier-map match rules; name-only matches go to review (E62)`.

---

### Task 6: Entity confirmation at match (E63)

**Files:**
- Modify: `arp/schemas/common.py`: `MatchStatus`; `SourceDocument.covered_entity`, `SourceDocument.match_status`
- Modify: `arp/schemas/datapoints.py`: `ExtractionRecord.held_documents`
- Create: `arp/planning/__init__.py` (empty), `arp/planning/entity_check.py`
- Modify: `arp/extraction/pipeline.py` (`_extract_company`: confirm every fetched document, extract only from non-held ones; new kwarg `identifier_map: IdentifierMapStore | None = None`)
- Test: `tests/test_entity_check.py`

**Interfaces:**
- Consumes: `normalise_lei`, `lei_is_valid` (`arp/schemas/issuer.py`); `IdentifierMapStore` (Task 5).
- Produces:
  - `class MatchStatus(StrEnum)`: `CONFIRMED="confirmed"`, `AMBIGUOUS="ambiguous"`, `MISMATCH="mismatch"`
  - `SourceDocument.covered_entity: str | None = None`, `SourceDocument.match_status: MatchStatus | None = None` (None = not checked, i.e. legacy).
  - `ExtractionRecord.held_documents: list[dict] = []`, each `{"doc_id", "title", "covered_entity", "match_status"}`.
  - In `arp/planning/entity_check.py`:
    - `LEGAL_SUFFIXES = ("plc", "inc", "ltd", "limited", "llc", "gmbh", "ag", "se", "sa", "nv", "bv", "corp", "corporation", "spa", "ab", "asa", "oyj")` and `NOISE_WORDS = ("group", "holdings", "holding", "the", "company", "co")`
    - `def normalise_entity_name(name: str) -> str`: lower-case, punctuation to spaces, drop trailing legal suffixes and noise words, collapse spaces (`"Acme Group plc"` → `"acme"`, `"Acme Energy GmbH"` → `"acme energy"`).
    - `def find_leis(text: str) -> list[str]`: valid LEIs in `text[:5000]`.
    - `def legal_name(text: str) -> str | None`: first run of up to 6 capitalised words ending in a legal suffix.
    - `def confirm_entity(doc: SourceDocument, company: CompanyRef, idmap: IdentifierMapStore | None = None) -> SourceDocument` (returns a copy with `covered_entity` and `match_status`). Rules, in order:
      1. `company.cik` and `f"/data/{int(cik)}/"` in `doc.source_url` (an EDGAR filing fetched by CIK) → `confirmed`.
      2. The issuer has a valid LEI: it is in `find_leis(text)` → `confirmed`; other LEIs only → `mismatch`, `covered_entity` = the first.
      3. `legal_name(doc.title)`: same normalised name as `company.name` → `confirmed`; different → `mismatch`.
      4. `legal_name(doc.full_text[:2000])`: same → `confirmed`; different → `ambiguous` (text below the title can name an auditor or subsidiary, so it never holds a document on its own).
      5. Otherwise `ambiguous`.
- `execute_extraction_run` passes `identifier_map=IdentifierMapStore(settings.identifier_map_path)`.
- In `_extract_company`: `docs = [confirm_entity(d, company, identifier_map) for d in documents]`; `kept = [d for d in docs if d.match_status != MatchStatus.MISMATCH]`; extraction, evidence and planning use `kept`; held docs go to `record.held_documents`; `documents_by_id` keeps all docs. No model call. Persisting the status to `content.db` is deferred (it is recomputed per run).

- [ ] **Step 1: Write the failing tests:**
  - `test_subsidiary_report_holds_parent_passes`: company `"Acme Group plc"`; doc titled `"Acme Energy GmbH Sustainability Report 2023"` gives `mismatch`, `covered_entity == "Acme Energy GmbH"`; doc titled `"Acme Group plc Annual Report 2023"` gives `confirmed`.
  - `test_held_document_not_extracted`: `_extract_company` with the subsidiary doc and the parent doc and `FakeLLMClient`; no evidence block sent to the model has the subsidiary's `doc_id`; `record.held_documents[0]["doc_id"]` is the subsidiary's.
  - `test_issuer_lei_in_text_confirms`
  - `test_foreign_lei_in_text_mismatches`
  - `test_provisional_issuer_with_lei_in_text_not_mismatch`: company without LEI, doc text with some valid LEI and no legal name gives `ambiguous`.
  - `test_auditor_name_in_body_is_ambiguous_not_mismatch`: title without a legal name, body starting `"KPMG AG"` gives `ambiguous`.
  - `test_edgar_doc_by_cik_confirmed`
  - `test_old_source_document_loads_with_no_status`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_entity_check.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures; check `test_rd_exposure_resolver`, `test_revenue_resolver` and `test_golden_set` (their fixture documents must not be held — fix a fixture title only if it names another legal entity by mistake).

- [ ] **Step 5: Commit** with `feat(planning): confirm the covered entity before extraction; mismatches are held (E63)`.

---

### Task 7: Applicability rules per field (E64)

**Files:**
- Modify: `arp/schemas/datapoints.py`: `ApplicabilityRules`; `FieldDefinition.applicability_rules`
- Modify: `arp/schemas/common.py`: `CompanyRef.regimes`
- Create: `arp/planning/applicability.py`
- Modify: `arp/extraction/pipeline.py` (`_extract_company`: skip non-applicable fields before the loop)
- Test: `tests/test_applicability.py`

**Interfaces:**
- Produces:
  - `class ApplicabilityRules(BaseModel)`: `sector_codes: list[str] = []` (ISIC Rev.4 code prefixes, e.g. `"10"`…`"33"` for manufacturing), `countries: list[str] = []` (ISO 3166-1 alpha-2), `regimes: list[str] = []` (e.g. `"CSRD"`, `"SEC"`)
  - `FieldDefinition.applicability_rules: ApplicabilityRules | None = None`
  - `CompanyRef.regimes: list[str] = []`
  - `def not_applicable_reason(field: FieldDefinition, company: CompanyRef) -> str | None`: for each non-empty rule list, when the company's attribute is known and does not match, return a reason (`"isic 6419 not in sector_codes [10..33]"`). Matching: `isic_code.startswith(prefix)`; country case-insensitive equality; regimes non-empty intersection. An unknown attribute (`isic_code`/`country` None, `regimes == []`) never excludes.
  - `def plan_fields(schema: DataPointSchema, company: CompanyRef) -> tuple[list[FieldDefinition], list[ExtractedField]]` returns `(to_extract, skipped)`. A skipped row: `value=None`, `value_state="not_applicable"`, `confidence=0.0`, `grounded=True`, `route_reasons=["not_applicable_by_rule"]`, `verifier_notes=<reason>`, `review_reasons=[]`.
- This task adds `ExtractedField.route_reasons: list[str] = []` (Task 12 adds `route`).
- In `_extract_company`: only `to_extract` enters the loop; `skipped` rows are added to `fields`. No model call for skipped fields.

- [ ] **Step 1: Write the failing tests:**
  - `test_bank_skips_manufacturing_only_field`: company `isic_code="6419"`, field `applicability_rules=ApplicabilityRules(sector_codes=[str(n) for n in range(10, 34)])`. `_extract_company` with `FakeLLMClient`: LLM call count for that field is 0; its row has `value_state == "not_applicable"` and `route_reasons == ["not_applicable_by_rule"]`; it is not in the run's review queue (through `execute_extraction_run`).
  - `test_manufacturer_keeps_field`: `isic_code="2410"` keeps it.
  - `test_country_and_regime_rules`
  - `test_unknown_company_attributes_never_skip`: `isic_code=None`, `country=None`, `regimes=[]` keeps a field with all three rule lists set.
  - `test_old_field_without_rules_loads`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_applicability.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(planning): per-field applicability rules skip fields without a model call (E64)`.

---

### Task 8: Period planning (E65)

**Files:**
- Modify: `arp/schemas/common.py`: `PeriodPlan`; `SourceDocument.period_plan`
- Create: `arp/planning/periods.py`
- Modify: `arp/extraction/extractor_agent.py`: `PeriodValue.planned_period_end`; `extract_field(..., planned_periods=None)` and a prompt rule
- Modify: `arp/extraction/field_graph.py`: `planned_periods` in `FieldState`, `extract_one_field(..., planned_periods: list[str] | None = None)`, passed to `extract_field` and to `build_extracted_fields`
- Modify: `arp/normalise/value.py` (`typed_value(..., planned: set[str] | None = None)`), `arp/extraction/aggregator.py` (`build_extracted_fields(..., planned_periods=None)`)
- Modify: `arp/extraction/pipeline.py` (`_extract_company`: plan every kept document, pass the union)
- Test: `tests/test_period_planning.py`, `tests/test_aggregator.py` (extend)

**Interfaces:**
- Consumes: `reporting_year` (`arp/ingestion/doc_identity.py`), `resolve_period` (`arp/normalise/period.py`), `RunHistory.recorded_periods` (Task 4).
- Produces:
  - `class PeriodPlan(BaseModel)`: `current: str | None = None`, `comparatives: list[str] = []` (latest first), `missing: list[str] = []`; property `planned -> list[str]` = `[current, *comparatives]` without None. All ISO period-end dates.
  - `SourceDocument.period_plan: PeriodPlan | None = None`
  - `MAX_COMPARATIVES = 4`
  - `def plan_periods(doc: SourceDocument, *, fiscal_year_end: str | None, recorded: set[str]) -> PeriodPlan`:
    - `Y = reporting_year(doc.title, doc.full_text)`; None gives an empty plan.
    - `current = resolve_period(f"FY{Y}", fiscal_year_end=fiscal_year_end).end`.
    - Year `y` in `Y-1 … Y-MAX_COMPARATIVES` is a comparative when the text has `FY ?y`, `year ended … y` (within one line), or a line holding both `Y` and `y` as standalone tokens (a table header like `"2024 2023 2022"`). Its period end comes from `resolve_period(f"FY{y}", ...)`.
    - `missing` = planned periods not in `recorded`.
    - Mark `# ponytail: year-token heuristic, use parsed table headers once the parser exposes tables`.
  - `def union_planned(docs: list[SourceDocument]) -> list[str]`: distinct planned periods of all docs, latest first.
  - `PeriodValue.planned_period_end: str | None = None` with description `"The planned period (ISO date from the list given) this value belongs to, if any."`
  - Prompt addition when `planned_periods`: `"Report a value for each of these periods where disclosed (period end): <dates>. Set planned_period_end to the one each value belongs to; leave it empty if none fits."`
  - `typed_value(..., planned=None)`: when `resolve_period` gives no end and `pv.planned_period_end in planned`, use it as `period_end` (start None). A planned date outside the plan is ignored. A resolved end always wins over the planned one.
- In `_extract_company`: `doc.period_plan = plan_periods(...)` for every kept doc (`recorded = history.recorded_periods(issuer_key)` or `set()`), then `planned_periods=union_planned(kept)` to each `extract_one_field`.
- Effect on the step-2 residual: two unresolved-period rows of one field get distinct `period_end`s, so distinct item keys, when the plan supplies them. With no plan they still share `…:unspecified` and keep the existing `check_failed` "period not resolved" note (unchanged).

- [ ] **Step 1: Write the failing tests:**
  - `test_document_with_two_comparatives_plans_three_periods`: title `"Annual Report 2024"`, text holding `"Scope 1 emissions   2024   2023   2022"`, `fiscal_year_end=None`. `plan.planned == ["2024-12-31", "2023-12-31", "2022-12-31"]`.
  - `test_missing_excludes_recorded`: `recorded={"2023-12-31"}` gives `missing == ["2024-12-31", "2022-12-31"]`.
  - `test_no_year_gives_empty_plan`
  - `test_april_fye_plan`: `fiscal_year_end="04-30"` gives `current == "2024-04-30"`.
  - `test_planned_period_makes_unresolved_keys_unique` (in `test_aggregator.py`): two `PeriodValue`s with `period_text` `"current year"` and `"prior year"` and `planned_period_end` `"2024-12-31"` / `"2023-12-31"`, `planned_periods` holding both. The rows have distinct `period_end`, and no row carries the `"period not resolved"` note.
  - `test_planned_period_outside_plan_ignored`
  - `test_prompt_lists_planned_periods`: the `FakeLLMClient` prompt contains `"2023-12-31"`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_period_planning.py tests/test_aggregator.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(planning): per-document period plan drives extraction periods (E65)`.

---

### Task 9: Entity and period consistency checks (E42)

**Files:**
- Create: `arp/checks/consistency.py`
- Modify: `arp/checks/runner.py` (append `check_entity`, `check_period` to `LAYERS[4]`)
- Test: `tests/test_checks_consistency.py`

**Interfaces:**
- Consumes: `SourceDocument.match_status`, `covered_entity` (Task 6); `SourceDocument.period_plan` (Task 8); `CheckContext.documents_by_id` (Task 1).
- Produces:
  - `check_entity` → `consistency.entity`, layer 4. The docs of the field's grounded citations: any `mismatch` → `fail`/`block` (detail names `covered_entity`); else any `ambiguous` → `fail`/`warn`; all `confirmed` → `pass`; no grounded citation, or every doc has `match_status is None` → `not_applicable`.
  - `check_period` → `consistency.period`, layer 4, `block`. `not_applicable` when `period_end` is None or no cited doc has a `period_plan` with planned periods. Fail when `period_end` is in none of the cited docs' `period_plan.planned`; detail `"period <d> not reported by <doc_id>"`.
- An ambiguous entity is `warn`: it keeps the value out of auto-accept and sends it to review, but does not stop the remaining checks.

- [ ] **Step 1: Write the failing tests:**
  - `test_subsidiary_report_for_wrong_entity_fails`: a field citing a doc with `match_status="mismatch"`, `covered_entity="Acme Energy GmbH"` gives `consistency.entity` `fail`, `block`.
  - `test_confirmed_doc_passes`
  - `test_ambiguous_doc_warns`
  - `test_period_not_in_plan_fails`: doc plan `["2024-12-31","2023-12-31"]`, field `period_end="2019-12-31"` gives `fail`.
  - `test_period_in_plan_passes`
  - `test_legacy_doc_without_status_not_applicable`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_checks_consistency.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(checks): entity and period consistency against the cited document (E42)`.

---

### Task 10: Field-to-document routing and unchanged-input skip (E66)

**Files:**
- Modify: `arp/schemas/datapoints.py`: `DocumentRouting`; `FieldDefinition.document_routing`; `ExtractedField.input_hash`, `ExtractedField.reused_from_run`
- Create: `arp/planning/doc_routing.py`
- Modify: `arp/extraction/field_graph.py` (`_gather_evidence` uses `route_documents` and `section_filter` instead of its inline `source_doc_types` filter)
- Modify: `arp/extraction/pipeline.py` (`_extract_company`: compute `input_hash`, reuse prior rows when unchanged)
- Test: `tests/test_doc_routing.py`

**Interfaces:**
- Consumes: `RunHistory.last_rows` (Task 4).
- Produces:
  - `class DocumentRouting(BaseModel)`: `doc_types: list[DocType] = []` (in preference order), `sections: list[str] = []` (section-heading substrings, case-insensitive), `fallback: bool = True`
  - `FieldDefinition.document_routing: DocumentRouting | None = None`
  - `ExtractedField.input_hash: str | None = None`, `ExtractedField.reused_from_run: str | None = None`
  - `def route_documents(field: FieldDefinition, documents: list[SourceDocument]) -> list[SourceDocument]`:
    - No `document_routing`: today's rule (filter by `source_doc_types` when non-empty).
    - Otherwise the documents of the first type in `doc_types` that has any; none present → all documents when `fallback`, else `[]`.
  - `def section_filter(field: FieldDefinition, chunks: list[DocumentChunk]) -> list[DocumentChunk]`: with `sections`, keep chunks whose `section` contains one; none kept → all chunks when `fallback`, else `[]`.
  - `def input_hash(field: FieldDefinition, documents: list[SourceDocument], planned_periods: list[str]) -> str | None`: `sha256(json.dumps([field.field_id, field.version, sorted(d.content_key or d.sha256 for d in documents), planned_periods]))`; None when there are no documents or any document has neither key.
- In `_extract_company`, per field: `h = input_hash(field, route_documents(field, kept), planned)`. When `h` is not None and `history.last_rows(company_id, field_id)` is non-empty and every row has `input_hash == h` and `provenance.field_version == field.version`, reuse those rows (`reused_from_run` = that run id; `checks` cleared so Task 1 recomputes them; Task 12 also clears `route` and `route_reasons` on reuse). Otherwise extract and set `input_hash=h` on every new row. Zero model calls on reuse.

- [ ] **Step 1: Write the failing tests:**
  - `test_unchanged_hash_makes_zero_model_calls`: a released one-field schema; run 1 through `execute_extraction_run` (non-trial) with `FakeLLMClient`; run 2 with the same documents. Run 2 adds 0 LLM calls; its row has `reused_from_run == run1_id` and the same `value`.
  - `test_changed_document_reextracts`: run 2 with one document's text changed (new `content_key`) makes calls.
  - `test_field_version_change_reextracts`: run 2 with the field saved as `version=2` makes calls.
  - `test_routing_prefers_first_doc_type_with_documents`: `doc_types=["sustainability_report", "10-K"]` with only a 10-K present gives the 10-K; with both, only the sustainability report.
  - `test_no_routed_type_and_no_fallback_gives_nothing`
  - `test_section_filter_with_fallback`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_doc_routing.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(planning): field-to-document routing; unchanged inputs skip extraction (E66)`.

---

### Task 11: Field quality and first audit (E67)

**Files:**
- Modify: `arp/schemas/datapoints.py` (`FieldQuality`)
- Modify: `arp/storage/schema_registry.py` (`quality`, `record_first_audit`)
- Modify: `arp/api/routers/extraction.py` (first-audit route)
- Test: `tests/test_schema_registry.py` (extend)

**Interfaces:**
- Produces:
  - `class FieldQuality(BaseModel)`: `field_id: str`, `version: int`, `first_audit_passed: bool = False`, `audited_by: str | None = None`, `audited_at: str | None = None`
  - `SchemaRegistry.quality(field_id: str, version: int) -> FieldQuality`: reads `<root>/field_quality.json` (`{"<field_id>:v<version>": {...}}`); a missing entry is `FieldQuality(field_id, version)`.
  - `SchemaRegistry.record_first_audit(field_id: str, version: int, audited_by: str) -> FieldQuality`: sets `first_audit_passed=True`, `audited_by`, `audited_at=now_iso()`; written with `atomic_write_text` under the registry's `KeyedLock`.
  - `POST /api/extraction/fields/{field_id}/versions/{version}/first-audit`, behind `require_role("approver")`, `audited_by=principal.user_id`, returns the `FieldQuality`.
- The weekly sampler (E10) that decides when an audit has passed comes later; in this step an approver records it. A new version of a field starts unaudited, because the key includes the version.

- [ ] **Step 1: Write the failing tests:**
  - `test_new_field_quality_not_audited`
  - `test_record_first_audit_persists`: a new `SchemaRegistry` on the same root reads `first_audit_passed is True` and `audited_by == "u1"`.
  - `test_new_version_starts_unaudited`: auditing v1 leaves v2 unaudited.
  - `test_first_audit_route_requires_approver`: an analyst token gets 403; the dev approver gets 200.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_schema_registry.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(registry): field quality record with first audit (E67)`.

---

### Task 12: Three-way routing, review queue and projection (E68)

**Files:**
- Modify: `arp/schemas/datapoints.py`: `RouteKind`; `ExtractedField.route`; `FieldDefinition.auto_accept_min`, `FieldDefinition.high_risk`
- Create: `arp/extraction/routing.py`
- Modify: `arp/extraction/pipeline.py`:
  - `_extract_company`: route every field after `check_record`; `needs_review = any(f.route == "review" ...)`; new kwarg `qualities: dict[tuple[str, int], FieldQuality] | None = None`; when all fetched documents were held, every field becomes a held `no_evidence_field` row.
  - `execute_extraction_run`: load `qualities` once from `SchemaRegistry(settings.schema_registry_dir)`.
  - `_review_items`: queue a row when `f.route == "review"`, or `f.route is None and f.review_reasons` (legacy); add `"route_reasons"` to the row.
- Modify: `arp/storage/postgres_company_facts_projection.py` (`resolve_extraction_fact`)
- Modify: `arp/bi/views.py:87` (add `'auto_accepted'` to the `company_facts` statuses), `arp/storage/postgres_models.py` (status docstring)
- Test: `tests/test_routing.py` (new), `tests/test_extraction_pipeline.py`, `tests/test_postgres_company_facts_projection.py` (extend)

**Interfaces:**
- Consumes: `CheckResult`, `is_failing` (Task 1); `FieldQuality` (Task 11); `route_reasons` (Task 7); `held_documents` (Task 6).
- Produces:
  - `class RouteKind(StrEnum)`: `AUTO_ACCEPT="auto_accept"`, `REVIEW="review"`, `HOLD="hold"`
  - `ExtractedField.route: RouteKind | None = None`
  - `FieldDefinition.auto_accept_min: float = Field(default=0.9, ge=0.0, le=1.0)`, `FieldDefinition.high_risk: bool = False`
  - `@dataclass(frozen=True) class Route: kind: RouteKind; reasons: list[str]`
  - `def route(field: ExtractedField, quality: FieldQuality, spec: FieldDefinition, *, held: str | None = None) -> Route`, rules in order:
    1. `held` → `HOLD [held]` (`"entity_mismatch"` from the pipeline).
    2. (removed: an unreleased field version no longer holds — see rule 4.)
    3. `"not_applicable_by_rule" in field.route_reasons` → `AUTO_ACCEPT ["not_applicable_by_rule"]`.
    4. Collect reasons, in this order: `"unreleased_version"` first when `spec.status != "released"` (controller ruling: trial runs must stay reviewable, never auto-accept); each `review_reasons` value; `f"check:{r.check_id}"` for each `is_failing` check; `"first_audit_pending"` when not `quality.first_audit_passed`; `"below_auto_accept_min"` when `value_state` is `found`/`zero`/`not_applicable` and `confidence < spec.auto_accept_min`; `"high_risk_not_found"` when `value_state == "not_found"` and `spec.high_risk`.
    5. Any reason → `REVIEW reasons`; none → `AUTO_ACCEPT []`.
  - A `not_found` value in a field that is not high-risk skips the confidence test (its confidence is 0 by construction), so audited low-risk fields do not flood the queue with "not disclosed".
  - `resolve_extraction_fact` per-field outcome when the field has no decision: `route == "hold"` → `"held"`; `route == "auto_accept"` → `"auto_accepted"`; queued → `"pending_review"`; legacy unqueued → no outcome (as today). Record status = first present of `("pending_review", "held", "rejected", "edited", "approved", "auto_accepted")`; nothing present → `"auto_approved"` (legacy). The reviewer for `held`/`auto_accepted` is None. A human decision on any key still wins over the route.
- How "decided by the system" appears, with no actor to spoof:
  - The system decision is the `route` on the result row, which only the pipeline writes (`results.jsonl`). It is never a row in `review_decisions.jsonl`, so `latest_decisions`, `effective_decisions` and the decision APIs stay human-only, and every decision there carries a `Principal`.
  - The projection reports it as status `auto_accepted` with `reviewer=None`, distinct from a human `approved`. A human named `"system"` produces `approved` with that name, never `auto_accepted`.
  - `RunHistory` (Task 4) reads it as `decided_by="system"`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_routing.py`, a released spec with `auto_accept_min=0.9`, an audited quality, and a found, grounded field with confidence 0.95 and only passing checks:
  - `test_auto_accept_when_all_pass`: `AUTO_ACCEPT`, reasons `[]`.
  - `test_new_field_never_auto_accepts`: unaudited quality gives `REVIEW` with `"first_audit_pending"`.
  - `test_failed_check_reviews`: a `warn` failure gives `REVIEW` with `"check:plausibility.sum_identity"`; an `info` failure still gives `AUTO_ACCEPT`.
  - `test_below_auto_accept_min_reviews`: confidence 0.85 gives `"below_auto_accept_min"`.
  - `test_review_reason_reviews`: `review_reasons=["not_grounded"]` gives `REVIEW` with `"not_grounded"`.
  - `test_not_found_high_risk_reviews`: `"high_risk_not_found"`; the same field with `high_risk=False` gives `AUTO_ACCEPT`.
  - `test_entity_mismatch_holds`: `held="entity_mismatch"` gives `HOLD`.
  - `test_unreleased_version_reviews_never_auto_accepts`: `status="draft"` with everything else passing gives `REVIEW` with reasons starting `["unreleased_version"]`.
  - `test_rule_skip_auto_accepts_even_unaudited`

  In `tests/test_extraction_pipeline.py`:
  - `test_auto_accepted_not_queued_and_marked_system`: a released, audited schema; the fixture document is titled with the company's legal name (so `confirmed`) and reports the value's period (so `consistency.period` passes); the row has `route == "auto_accept"`; the review queue is empty; `review_decisions.jsonl` does not exist.
  - `test_all_documents_held_fields_hold`: the only document is a subsidiary report; every row has `route == "hold"` and `route_reasons == ["entity_mismatch"]`; nothing queued.
  - `test_queue_row_carries_route_reasons`

  In `tests/test_postgres_company_facts_projection.py` (pure `resolve_extraction_fact`):
  - `test_auto_accepted_field_projects_as_auto_accepted`: status `"auto_accepted"`, reviewer None.
  - `test_human_named_system_is_not_auto_accepted`: an `approve` decision with `reviewer="system"` on that key gives `"approved"`.
  - `test_held_field_projects_as_held`
  - `test_legacy_rows_without_route_unchanged`: a step-2 row (no `route`) and its queue/decision give the same `(value, status, reviewer)` as before.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_routing.py tests/test_extraction_pipeline.py tests/test_postgres_company_facts_projection.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** Trial runs use draft fields, so their rows route to `review` with `"unreleased_version"` and are queued as before (never auto-accepted, never held for that reason). Existing trial-run tests that assert queue rows keep working; add `test_trial_run_rows_are_reviewable` asserting a trial row is queued with `"unreleased_version"` in its route reasons.

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(extraction): three-way routing; auto-accepted values recorded as system-decided (E68)`.

---

### Task 13: Frontend: route, checks, held documents

**Files:**
- Modify: `frontend/src/types.ts`: `CheckResult`; `ExtractedField.checks?`, `route?`, `route_reasons?`; `ExtractionRecord.held_documents?`
- Modify: `frontend/src/lib/fieldValue.ts`, `frontend/tests/fieldValue.test.ts`
- Modify: `frontend/src/components/ExtractionResults.tsx`:
  - `FieldDetail`: a route badge (`routeLabel`) and a list of `failedChecks` as `"{check_id}: {detail}"`, with `badge-high` for `block` and `badge-mid` for `warn`.
  - `ExtractionResultsTable`: hide `ReviewControls` for `route === "hold"`; in the expanded row, list `held_documents` as `"Held: {title} (covers {covered_entity})"`.

**Interfaces:**
- Produces:
  - `interface CheckResult { check_id: string; layer: number; outcome: "pass" | "fail" | "not_applicable"; severity: "info" | "warn" | "block"; detail: string; threshold_ref?: string | null }`
  - `routeLabel(f: Pick<ExtractedField, "route" | "route_reasons">): string | null`: `auto_accept` → `"auto-accepted (system)"`; `review` → `"in review"`; `hold` → `"held: " + route_reasons.join(", ")`; missing → `null` (legacy rows show nothing).
  - `failedChecks(f: Pick<ExtractedField, "checks">): CheckResult[]`: `outcome === "fail"` and severity `warn` or `block`; `[]` when `checks` is missing.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/fieldValue.test.ts`:
  - `routeLabel` returns `"auto-accepted (system)"`, `"in review"`, `"held: entity_mismatch"`, and `null` for a legacy field.
  - `failedChecks` keeps a `warn` and a `block` failure, drops `info` failures and passes, and returns `[]` for a legacy field.

- [ ] **Step 2: Run** `cd frontend && npm test`. Expect FAIL.

- [ ] **Step 3: Implement as in Files.**

- [ ] **Step 4: Run** `cd frontend && npm run lint && npm test && npm run build`. Expect 0 errors.

- [ ] **Step 5: Commit** with `feat(frontend): route badge, failed checks and held documents in extraction results`.
