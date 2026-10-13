# Precision-First Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the generic field pipeline the single precision-first engine for any metric or
criteria schema, faster per run, with a harness that measures auto-accept precision.

**Architecture:** All work lands in the existing generic field pipeline:
`extraction/pipeline.py` → `field_graph.py` → `aggregator.py` → `checks/` → `routing.py`.
- Criteria are `boolean` fields.
- The 64 indicators become a preset.
- A company-level answer is a `derived_rule` field, computed without an LLM.
- Precision comes from blind verification, stricter grounding and a reranker.
- Speed comes from extracting fields concurrently under one shared LLM-call semaphore.

**Tech Stack:** Python 3, Pydantic, LangGraph, fastembed (local ONNX), pytest, Typer CLI.

**Spec:** `docs/superpowers/specs/2026-10-12-precision-extraction-design.md`

## Global Constraints

- All paths below are relative to `backend/`. Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`.
- Before running tests by hand: `bash .claude/hooks/ensure-deps.sh backend`.
- Criteria have three outcomes: YES = `value=True, value_state=found` (quote required);
  NO = `value=False, value_state=found` (topic addressed, criterion not met; quote required);
  NOT DISCLOSED = `value_state=not_found`. "No evidence" is never `False`.
- Do not change the meaning of any existing green or EU-taxonomy field. `presets/green.py:88-90`
  ("subtract them when quantified") stays as it is.
- Do not modify `transition_plan/`, the financials path (`extraction/financials_*`), or their
  consumers.
- Retrieval stays local, offline-capable and deterministic. No LLM call for reranking.
- Extractor model `claude-sonnet-5-5` and verifier model `claude-opus-5-5` are unchanged.
- Never delete or weaken an existing test. List every test change in the PR description.

## Review Focus

1. **A long quote with a word typo but correct digits** must still ground through the fuzzy
   path. Only digit differences are rejected. → Task 1.
2. **A boolean `False` with no citation** must go to review (`not_grounded`). A silent
   ungrounded NO must never be auto-accepted. → Task 3.
3. **Reranker model unavailable** (offline, download failure, old fastembed): retrieval falls
   back to the RRF order with one warning, and must not crash. → Task 5.
4. **Concurrent fields:** the output order of `fields` stays the schema order, and one
   field's exception still fails the company exactly as it does today. → Task 9.
5. **A `derived_rule` naming an unknown field_id** must fail when the schema is built, not
   silently give `not_found` at run time. → Task 7.

---

### Task 1: Digit-strict fuzzy grounding

**Files:**
- Modify: `arp/grounding.py` (`_find_in_span`, fuzzy branch ~lines 141-148)
- Test: `tests/test_grounding.py`

**Interfaces:**
- Produces: no signature change. `_find_in_span` returns `None` from the fuzzy path when any
  digit of the normalised quote lies outside the longest matching block.

- [ ] **Step 1: Write the failing tests**

```python
def test_fuzzy_rejects_changed_digit_outside_block():
    src = "Taxonomy-aligned capital expenditure amounted to EUR 1,234 million in the reporting year 2025."
    quote = "Taxonomy-aligned capital expenditure amounted to EUR 1,234 million in the reporting year 2026."
    assert _find_match(quote, src, 0.92) is None

def test_fuzzy_accepts_word_typo_when_digits_inside_block():
    src = "In 2025 taxonomy-aligned capital expenditure amounted to EUR 1,234 million across the group."
    quote = "In 2025 taxonomy-aligned capital expenditure amounted to EUR 1,234 million across the gruop."
    assert _find_match(quote, src, 0.92) is not None
```

- [ ] **Step 2:** Run `python3 -m pytest tests/test_grounding.py -k fuzzy -v`. Expected: the first test FAILS.
- [ ] **Step 3:** In the fuzzy branch, after computing `m`, return `None` when
  `re.search(r"\d", norm_quote[:m.b] + norm_quote[m.b + m.size:])` matches.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_grounding.py tests/test_table_grounding.py tests/test_segment_grounding.py -v`. Expected: all PASS.
- [ ] **Step 5:** Commit: `git commit -m "grounding: reject fuzzy matches whose digits fall outside the matched block"`

### Task 2: Show table unit notes in evidence

**Files:**
- Modify: `arp/extraction/extractor_agent.py` (`format_evidence`)
- Test: `tests/test_extraction_pipeline.py` (or a new `tests/test_format_evidence.py`)

**Interfaces:**
- Produces: `format_evidence(chunks, header=("doc_id","passage_id","doc_type","section","unit_note"))`.
  `unit_note` is printed only when set, like `section` and `speaker`.

- [ ] **Step 1: Write the failing test**

```python
def test_format_evidence_shows_unit_note():
    c = DocumentChunk(chunk_id="p1", doc_id="d1", doc_type=DocType.SUSTAINABILITY_REPORT, text="CapEx | 1,234", unit_note="in EUR millions")
    assert "unit_note=in EUR millions" in format_evidence([c])
    assert "unit_note" not in format_evidence([c.model_copy(update={"unit_note": None})])
```

- [ ] **Step 2:** Run the test. Expected: FAIL.
- [ ] **Step 3:** Add `"unit_note": c.unit_note` to `values`. Treat it as optional the way
  `section` and `speaker` already are, and append it to the default `header`.
- [ ] **Step 4:** Run `python3 -m pytest tests/ -k "evidence or extraction" -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "extraction: show table unit notes in evidence headers"`

### Task 3: Three-outcome rule for boolean fields

**Files:**
- Modify: `arp/extraction/extractor_agent.py` (`extract_field` prompt)
- Test: `tests/test_extraction_pipeline.py`

**Interfaces:**
- Produces: `BOOLEAN_RULE: str` in `extractor_agent.py`, appended to the prompt when
  `field.data_type == FieldDataType.BOOLEAN`. `blind_verify` reuses `extract_field`, so it
  inherits the rule.

- [ ] **Step 1: Write the failing tests**

Test A: a fake `LLMClient` records `prompt`. Extract a boolean field and assert
`BOOLEAN_RULE in prompt`. Extract a currency field and assert `BOOLEAN_RULE not in prompt`.

Test B (Review Focus 2) runs `build_extracted_fields` on these inputs:
- a boolean field;
- a draft with `values=[PeriodValue(value=False, citations=[])]`;
- an agreeing verifier.

Assert `ReasonCode.NOT_GROUNDED in out[0].review_reasons`.

- [ ] **Step 2:** Run the tests. Expected: Test A fails; Test B may already pass (if so, it stays as a guard).
- [ ] **Step 3:** Add the constant with this exact copy:

```python
BOOLEAN_RULE = (
    "This is a yes/no criterion. value=true: the evidence shows the criterion is met (quote it). "
    "value=false: the evidence addresses this topic but shows the criterion is NOT met (quote what it says instead, "
    "e.g. only an intensity target where an absolute target is asked for). If nothing in the evidence addresses "
    "the topic, return an empty `values` list (not disclosed): never return false for missing evidence. "
    "Where the extraction instructions say 'NO otherwise', apply NO only when the topic is addressed."
)
```

- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "extraction: three-outcome rule for boolean criteria"`

### Task 4: High-risk not-found needs both passes

**Files:**
- Modify: `arp/extraction/field_graph.py` (`_gather_evidence`)
- Modify: `arp/extraction/routing.py:46`
- Test: `tests/test_routing.py`, `tests/test_extraction_pipeline.py`

**Interfaces:**
- Produces:
  - `_gather_evidence` passes `fallback_to_all=field.high_risk` to `select_relevant_chunks`.
  - `route` adds `high_risk_not_found` only when
    `value_state == NOT_FOUND and spec.high_risk and field.verifier_confidence is None`, i.e.
    when no verifier pass ran. A not-found the verifier disagrees with is already in review
    via `verifier_disagrees`.

- [ ] **Step 1: Write the failing tests**

```python
def test_high_risk_not_found_agreed_by_verifier_auto_accepts():
    f = ExtractedField(field_id="x", field_name="x", value=None, value_state=ValueState.NOT_FOUND,
                       confidence=0.95, verifier_confidence=0.9)
    spec = make_spec(high_risk=True, status=FieldStatus.RELEASED)
    assert route(f, FieldQuality(field_id="x", version=1, first_audit_passed=True), spec).kind == RouteKind.AUTO_ACCEPT

def test_high_risk_not_found_without_verifier_goes_to_review():
    f = ExtractedField(field_id="x", field_name="x", value=None, value_state=ValueState.NOT_FOUND, confidence=0.0)
    spec = make_spec(high_risk=True, status=FieldStatus.RELEASED)
    assert "high_risk_not_found" in route(f, FieldQuality(field_id="x", version=1, first_audit_passed=True), spec).reasons
```

Also add a `field_graph` test: run with BM25-only settings and a high-risk field whose keywords
hit no chunk. Assert the fake extractor was called. In other words, the run does not go to
`finalize_no_evidence` when chunks exist.

(`make_spec` is a local helper building a `FieldDefinition`. Reuse the one in
`tests/test_routing.py` if it exists.)

- [ ] **Step 2:** Run the tests. Expected: the auto-accept and field_graph tests FAIL.
- [ ] **Step 3:** Implement the two one-line changes from Interfaces.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_routing.py tests/test_extraction_pipeline.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "routing: accept a high-risk not-found only when both passes agree"`

### Task 5: Local cross-encoder reranker

**Files:**
- Create: `arp/retrieval/rerank.py`
- Modify: `arp/retrieval/select_evidence.py` (`select_relevant_chunks`)
- Modify: `arp/config.py`
- Modify: `arp/extraction/field_graph.py` (`_gather_evidence`)
- Test: `tests/test_rerank.py`, `tests/test_select_evidence.py`

**Interfaces:**
- Produces:
  - `rerank(query: str, chunks: list[DocumentChunk], top_n: int) -> list[DocumentChunk]` in
    `rerank.py`. It returns at most `top_n` chunks, best first. If the model can't load, it
    returns `chunks[:top_n]` and logs one warning per process.
  - `RERANK_MODEL_NAME: str` in `rerank.py`.
  - `select_relevant_chunks(..., rerank_candidates: int | None = None)`. When it is set,
    the function takes the top `rerank_candidates` of the final ranking (fused or BM25),
    reranks them, and keeps `max_chunks`.
  - Settings: `rerank_enabled: bool = True`, `rerank_candidates: int = 40`,
    `evidence_max_chunks: int = 12`.
  - `_gather_evidence` passes `max_chunks=settings.evidence_max_chunks` and
    `rerank_candidates=settings.rerank_candidates if settings.rerank_enabled else None`
    (both only when `settings` is not None).

- [ ] **Step 1: Check the dependency.** Run
  `python3 -c "from fastembed.rerank.cross_encoder import TextCrossEncoder; print([m['model'] for m in TextCrossEncoder.list_supported_models()])"`.
  Pick a multilingual (EN/DE) model small enough for CPU and set `RERANK_MODEL_NAME`. If the
  installed fastembed lacks `TextCrossEncoder`, raise the `fastembed` floor in
  `pyproject.toml` to the first version that has it and note that in the commit.
- [ ] **Step 2: Write the failing tests.** Monkeypatch the scorer (`rerank._score`) so these
  run with no model.

```python
def test_rerank_orders_by_score(monkeypatch):
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [0.1, 0.9, 0.5])
    out = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
    assert [c.chunk_id for c in out] == ["b", "c"]

def test_rerank_falls_back_when_model_unavailable(monkeypatch, caplog):
    monkeypatch.setattr(rerank, "_score", raising(RuntimeError("no model")))
    out = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
    assert [c.chunk_id for c in out] == ["a", "b"]
```

  Add a `test_select_evidence.py` case: with `rerank_candidates=3, max_chunks=2` and a patched
  scorer, the returned ids follow the scorer, not the BM25 order.
- [ ] **Step 3:** Implement. `_score(query, texts) -> list[float]` lazily loads
  `TextCrossEncoder(model_name=RERANK_MODEL_NAME)` once, the way
  `retrieval/embeddings._get_model` does. `rerank` catches any exception from `_score`.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_rerank.py tests/test_select_evidence.py tests/test_extraction_pipeline.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "retrieval: local cross-encoder rerank of top candidates"`

### Task 6: Blind verification on green and EU-taxonomy presets

**Files:**
- Modify: `arp/presets/green.py`, `arp/presets/eu_taxonomy.py`
- Test: `tests/test_presets_green.py`, `tests/test_presets_eu_taxonomy.py`

**Interfaces:**
- Produces: every `FieldDefinition` in `build_green_schema()` and in the EU-taxonomy builder
  has `high_risk=True`.

- [ ] **Step 1:** Write the failing test. For each schema, assert `all(f.high_risk for f in schema.fields)`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Set `high_risk=True` in the field factories: `_money` and the inline
  `FieldDefinition`s in `green.py`, and the equivalents in `eu_taxonomy.py`. Change no
  description or instruction text.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_presets_green.py tests/test_presets_eu_taxonomy.py tests/test_presets_infra.py -q`. Expected: PASS. If `presets_infra` expects a version bump when a released field changes, let `registry.save` bump it. Don't hand-edit versions.
- [ ] **Step 5:** Commit: `git commit -m "presets: blind-verify all green and EU-taxonomy fields"`

### Task 7: Derived criterion fields (`derived_rule`)

**Files:**
- Modify: `arp/schemas/datapoints.py` (add `DerivedRule`, `FieldDefinition.derived_rule`, and a `DataPointSchema` validator)
- Create: `arp/extraction/derived.py`
- Modify: `arp/extraction/pipeline.py` (`_extract_company`: skip derived fields in extraction, evaluate them before `check_record`)
- Test: `tests/test_derived.py`

**Interfaces:**
- Produces:
  - `class DerivedRule(BaseModel)` with `all_of: list[str] = []`, `any_of: list[str] = []`,
    `min_true: int | None = None`.
  - `FieldDefinition.derived_rule: DerivedRule | None = None`. Only valid on `boolean` fields.
  - The `DataPointSchema` model validator raises `ValueError` if a rule names a field_id that
    is not in the schema.
  - `evaluate_derived(spec: FieldDefinition, by_id: dict[str, ExtractedField]) -> ExtractedField`
    in `derived.py`, with:
    - `method="extracted"`, `confidence=1.0`, `grounded=True` when the result is found;
    - `citations` = the union of the true inputs' citations (all inputs' citations for `False`);
    - `review_reasons=[ReasonCode.CHECK_FAILED]` if any input has `review_reasons` or failing checks.
  - `min_true` counts across `all_of + any_of`.

- [ ] **Step 1: Write the failing tests**

| Test | Inputs | Expected |
|---|---|---|
| `test_all_of_true` | all_of = [a,b], both True | `True` |
| `test_all_of_one_false` | all_of = [a,b], one False, one not_found | `False` (decided) |
| `test_all_of_not_found_never_false` | all_of = [a,b], one True, one not_found | `not_found` |
| `test_any_of_one_true` | any_of = [a,b], a True, b not_found | `True` |
| `test_any_of_all_false` | any_of = [a,b], both False | `False` |
| `test_min_true` | min_true=2 over all_of+any_of [a,b,c], two True, one not_found | `True` |
| `test_min_true_unreachable` | min_true=2 over all_of+any_of [a,b,c], one True, two False | `False` |
| `test_input_in_review_routes_derived` | an input with review_reasons | derived has `ReasonCode.CHECK_FAILED` |
| `test_unknown_field_id_rejected` | rule names a missing field_id | building the `DataPointSchema` raises `ValidationError` (Review Focus 5) |

- [ ] **Step 2:** Run `python3 -m pytest tests/test_derived.py -v`. Expected: FAIL (import error).
- [ ] **Step 3:** Implement `evaluate_derived` with three-valued logic. Each part is
  satisfied, violated or undecided:
  - **`all_of`:** violated if any input is False; satisfied if all are True.
  - **`any_of`:** satisfied if any input is True; violated if all are False.
  - **`min_true`:** satisfied if count(True) ≥ n; violated if count(True) + count(not_found) < n.

  Combine the parts: any violated → `False`; all satisfied → `True`; otherwise `not_found`.
  In `_extract_company`, drop fields with a `derived_rule` from `to_extract` and append
  `evaluate_derived(...)` results to `fields` before `check_record`.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_derived.py tests/test_extraction_pipeline.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "extraction: derived criterion fields with three-valued rules"`

### Task 8: Transition-plan criteria preset

**Files:**
- Create: `arp/presets/transition_plan.py`
- Create: `arp/presets/data/transition_plan_keywords.json`
- Modify: `arp/presets/registry.py` (register it in `PRESETS`)
- Test: `tests/test_presets_transition_plan.py`

**Interfaces:**
- Consumes: `transition_plan.indicators.load_indicators()` (read-only; `transition_plan/` is
  not modified).
- Produces:
  - `SCHEMA_ID = "transition_plan_indicators"`.
  - `build_transition_plan_schema() -> DataPointSchema`, with 64 `boolean` fields:
    - `field_id=f"tp_{identifier.lower()}"`
    - `name=identifier`
    - `description=question`
    - `extraction_instructions=guideline` (verbatim)
    - `seed_keywords` taken from the JSON file
    - `high_risk=True`, `required=False`
  - The JSON maps each indicator `identifier` to 3–8 keyword phrases, written from the
    question and guideline (for example, A_headline_1 →
    `["absolute emission reduction target", "net zero", "carbon neutral", "reduce absolute emissions", "scope 1 and 2 target"]`).
  - No `derived_rule` ships. The owner defines it later.

- [ ] **Step 1:** Write the failing tests:
  - 64 fields;
  - every field is boolean and `high_risk`;
  - every indicator identifier has ≥3 keywords;
  - `"transition_plan_indicators" in PRESETS`;
  - `extraction_instructions` equals the source guideline for A_headline_1.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement the builder and write the keywords file.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_presets_transition_plan.py tests/test_presets_infra.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "presets: transition-plan indicators as a criteria schema"`

### Task 9: Concurrent fields under one LLM-call cap

**Files:**
- Create: `arp/llm/bounded.py`
- Modify: `arp/config.py`
- Modify: `arp/extraction/pipeline.py` (`execute_extraction_run`, and the field loop in `_extract_company`)
- Test: `tests/test_bounded_llm.py`, `tests/test_extraction_pipeline.py`

**Interfaces:**
- Produces:
  - `class BoundedLLMClient` in `bounded.py`, with `__init__(self, inner: LLMClient, sem: asyncio.Semaphore)`.
    `complete_structured(**kwargs)` acquires `sem` and delegates to `inner`. Any other
    attribute goes to `inner` via `__getattr__`.
  - Setting `llm_call_concurrency: int = 32`. This is the run-wide cap on in-flight LLM
    calls. Company concurrency stays `max_concurrent_llm_calls`.
  - `execute_extraction_run` creates one `asyncio.Semaphore(settings.llm_call_concurrency)`
    and wraps both `llm` and `verifier_llm` (when given).
  - `_extract_company` keeps the reuse check per field, serial and cheap. It then runs the
    remaining `extract_one_field` calls with `asyncio.gather`, and extends `fields` and
    `usages` in schema order.

- [ ] **Step 1: Write the failing tests**
  - A fake inner client counts the peak number of concurrent calls. 10 concurrent calls
    through `BoundedLLMClient` with `Semaphore(3)` give `peak == 3`.
  - A pipeline test where the fake LLM sleeps per call, with 5 fields:
    - output `field_id` order equals schema order (Review Focus 4);
    - peak concurrency is > 1.
  - A second pipeline test: one field's fake raises, and `_extract_company` raises (the
    same as today).
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_bounded_llm.py tests/test_extraction_pipeline.py tests/test_pipeline_results.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "extraction: run a company's fields concurrently under a run-wide LLM-call cap"`

### Task 10: Precision harness

**Files:**
- Modify: `arp/golden_set/schema.py` (add `RecordGoldenCase`, `ExpectedValue`, `PrecisionReport`)
- Create: `arp/golden_set/precision.py`
- Modify: `arp/cli/golden_set.py` (add the `golden-set precision` command)
- Test: `tests/test_golden_precision.py`

**Interfaces:**
- Consumes: `extraction.pipeline._extract_company(..., documents=..., qualities=..., trial=False)`;
  `ingestion.local_files.LocalFileDocumentSource`, constructed as in `arp/cli/_shared.py`.
- Produces:
  - `ExpectedValue`: `field_id: str`, `period_end: str | None = None`,
    `value: str | float | bool | None = None`, `value_state: ValueState`.
  - `RecordGoldenCase`: `case_id: str`, `company: CompanyRef`, `expected: list[ExpectedValue]`.
    Documents live in `<documents_dir>/<company_id>/`.
  - `PrecisionReport`: `schema_id`, `total: int`, `auto_accepted: int`, `auto_accepted_correct: int`,
    `precision: float | None`, `review_rate: float`, `coverage: float`,
    `wrong_auto_accepted: list[dict]` (case_id, field_id, expected, actual, citations).
  - `async run_precision(cases, *, schema, documents_dir: Path, llm, verifier_llm, settings) -> PrecisionReport`.
    It routes as if released and audited: it copies the schema with every field
    `status=FieldStatus.RELEASED` and passes `qualities` with `first_audit_passed=True` for
    every field.
  - Value matching: reuse `runner._values_match`, with a relative tolerance of 0.005 on
    `canonical_value` for numbers. Expected `not_found` matches an actual `value_state == NOT_FOUND`.
  - CLI: `arp golden-set precision --schema <preset_id> --cases <file> --documents-dir <dir> [--min-precision 0.97]`
    prints the report and exits non-zero if `precision < min_precision`.

- [ ] **Step 1: Write the failing tests.** Patch `_extract_company` to return a fixed record:
  - 3 rows auto-accepted: 2 correct, 1 wrong;
  - 1 row routed to review.

  Assert:
  - `precision == 2/3`;
  - `review_rate == 1/4`;
  - `coverage == 3/4`;
  - `len(wrong_auto_accepted) == 1`;
  - expected not_found vs actual not_found counts as correct;
  - the schema passed to `_extract_company` has every field `RELEASED`.
- [ ] **Step 2:** Run `python3 -m pytest tests/test_golden_precision.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_golden_precision.py tests/test_golden_set.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "golden-set: precision harness for whole-record extraction"`

### Task 11: Export reviewer decisions as golden cases

**Files:**
- Create: `arp/golden_set/export.py`
- Modify: `arp/cli/golden_set.py` (add the `golden-set export-labels` command)
- Test: `tests/test_golden_export.py`

**Interfaces:**
- Consumes:
  - `review_decisions.jsonl` rows (`schemas/review.ReviewDecision`); the item key is
    `issuer_key:field_id:period`, see `schemas/review.field_item_key`;
  - the run's result rows from `RunStore`.
- Produces:
  - `export_cases(run_store: RunStore, run_id: str, decisions: list[ReviewDecision]) -> list[RecordGoldenCase]`.
    It groups by company and uses the last decision per item_key. The mapping:

    | Decision | Expected value |
    |---|---|
    | `APPROVE` | the row's `value` and `value_state` |
    | `CORRECT` | the value in `corrected_value` (read its shape from the review API that writes it) |
    | `REJECT` with `reason_code=NOT_DISCLOSED` | `value_state=not_found` |

    Other decisions and `ESCALATE` are skipped.
  - CLI: `arp golden-set export-labels --run-id <id> --out <file>` writes the JSON array.

- [ ] **Step 1: Write the failing tests:**
  - one approve;
  - one correct (with the `corrected_value` shape the review API writes);
  - one reject/not_disclosed;
  - one escalate.

  Assert there are 3 expected values with the right states, and the escalate is absent.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `python3 -m pytest tests/test_golden_export.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "golden-set: export trial-run review decisions as labelled cases"`

### Task 12: Whole-branch verification

- [ ] **Step 1:** Run `cd backend && ruff check . && python3 -m pytest -q`. Expected: all pass; nothing skipped that passed before.
- [ ] **Step 2:** Do a smoke run against one real local report if one exists under the
  configured documents dir. Run `arp golden-set precision` for the green preset on a
  one-case file, and record its wall time and LLM call count in the PR description. If no
  report is available, say so in the PR. Don't invent numbers.
