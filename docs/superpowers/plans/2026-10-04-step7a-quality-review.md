# Step 7a: Extraction quality and review refinements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Values are taken from structured filings before any model call. Numbers are read in the right locale, converted, and then checked by converting them back. Table values cite the cell they came from. Corrections need a grounded citation, and disagreements are typed; only those disagreements reach a third, adjudicating call. Checks are measured, and cross-source differences are flagged. A parser upgrade re-grounds stored citations. Reviewers get known-answer items, similar past decisions, a pre-filled verifier correction, keyboard shortcuts, error analytics and a guarded bulk accept.

**Architecture:** Every item extends an existing seam. Nothing is rebuilt.
- **Extraction.**
  - `extraction/field_graph.py` gains an entry node `try_tagged` (E29). The graph shape is shared with `financials_graph.py` through `graph_shape.build_extract_verify_graph`.
  - `extraction/verifier_agent.py` and `aggregator.py` take E38.
  - A new `extraction/adjudicator.py` (E40) is a graph node that runs after `verify`.
- **Checks.** These follow the `checks/runner.py` layer pattern:
  - `checks/round_trip.py` (E49) on layer 3;
  - `checks/cross_source.py` (E39) on a new layer 5;
  - `checks/effectiveness.py` (E41) is a read-only report, not a check.
- **Normalisation.** `normalise/locale.py` (E48) becomes the one number parser that `decision/parsing.to_number` and `checks/numeric.parse_number` delegate to. A JSON manifest guards the versioned tables (E50).
- **Ingestion.** Docling table structure becomes `SourceDocument.table_spans` and table chunks. Grounding sets `Citation.table_ref`, which becomes a `TableRef` (E45).
- **Re-grounding.** `orchestration/reground.py` (E51) reuses `publish/gate.py`'s re-grounding through a new citation-level `reground_citation`.
- **Review.** New `review/quality.py` (E56) and `review/analytics.py` (E59). The similar-decisions and bulk-accept endpoints go in `api/routers/extraction.py` (E57, E61), using `review/decide.py`'s locked append path. The frontend gets the pre-fill and keyboard shortcuts (E57).

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, LangGraph (already used), stdlib `csv`, `hashlib`, `json`, `re`, `datetime`; Docling (installed) for table structure; pytest. React + TypeScript (Vite), `node --test`, oxlint.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4`. This plan covers these rows:
- E29, E38, E39, E40, E41
- E45, E48, E49, E50, E51
- E56, E57, E59, E61

Step 7b (E16, E19, E20, E22–E25) is a separate plan. Paths are relative to `backend/` unless they start with `frontend/` or `docs/`. This plan builds on steps 1 to 6 (`docs/superpowers/plans/2026-10-0*-step*.md`).

**Deviations from the spec text, decided here:**
- **E50: tables stay CSV.** The normalisation tables stay CSV and are versioned by file name (`units_v1.csv` and so on), with their existing per-row tests. The guard is a new `normalise/tables/manifest.json` mapping `{table: {"version": int, "sha256": str}}`. A test recomputes each table's hash and fails when the content changed but the version and hash in the manifest did not. Converting to JSON would churn every loader for no gain.
- **E48: number locale.**
  - Language comes from a small stop-word table, `normalise/tables/locale_v1.csv` (columns `word,language,decimal`), counted over the document text. The result is stored as `SourceDocument.language` and `SourceDocument.decimal`, with decimal being `"point"`, `"comma"` or `None`.
  - Table context means: the other numbers in the same table span decide first, then the document, then the language.
  - An ambiguous value (for example `1,234` with no context) is parsed under the `point` convention and gets the review reason `number_locale_ambiguous`.
- **E29: tagged values.**
  - Fields carry a tag list, `FieldDefinition.xbrl_tags: list[str] = []`, with tags written like `us-gaap:Revenues`.
  - A tagged value gets `ExtractedField.method = "tagged"`. The other method values are `extracted` (the default, so old rows still read) and `adjudicated`.
  - Facts come from the existing `XbrlFactSource` (annual 10-K/10-K/A, USD, SEC companyfacts). There is one fetch per company, and only when `settings.xbrl_facts_enabled` is on, the company has a CIK, and some field has `xbrl_tags`. ESEF facts come later in 7b (E16), through the same interface.
- **E38: verifier redesign.**
  - `DisagreementType` takes the values `none`, `value`, `unit_or_scale`, `period`, `entity` and `not_disclosed`.
  - For a high-risk field, the verifier model re-extracts blind with `extract_field`, and code compares the two values: `same_value` for value, then unit, then period. Other fields keep the review prompt.
  - A correction whose citations do not ground through `ground_citations` is rejected. The extractor's value stays, the corrected value goes into `alternatives` with `source="verifier"`, and the field gets the review reason `verifier_correction_uncited`.
- **E40: adjudicator.**
  - It runs only when `disagreement_type` is something other than `none`.
  - It uses the verifier client. There is no new model setting, and `ProvenanceInfo.adjudicator_model` records the model.
  - When it settles a value, it gives the value with a grounded citation, and the field gets `method="adjudicated"`.
  - When it cannot settle the value, the field gets the review reason `adjudicator_unresolved`, and both candidates go into `alternatives`.
- **E39: cross-source references.** `CheckContext.references: dict[str, list[Reference]]` is keyed by item key. `Reference` has `source: Literal["tagged", "text", "published"]`, `value: float` and `unit: str | None`. It is filled by the pipeline from:
  - XBRL facts, for fields whose value was not tagged;
  - the last run's text value for the same item, for tagged fields (from `RunHistory`);
  - the current published fact, when `postgres_dsn` is set.

  There is no licensed reference data, because ARP has none. The tolerance is `CheckConfig.cross_source_tolerance = 0.01`, relative. A difference above it gives severity `warn`, which sends the value to review.
- **E45: table references.**
  - `Citation.table_ref` changes from `str | None` to `TableRef | None`, with fields `table_id`, `row_label`, `col_label`, `caption` and `unit_note`. It has never been set, so no stored row breaks.
  - Docling's `doc.tables` gives `SourceDocument.table_spans`, a list of `TableSpan{table_id, char_start, char_end, caption, unit_note, cells: [{row_label, col_label, char_start, char_end}]}`.
  - The span offsets are in the markdown text that `_extract_pdf_text` already returns. Each table is located by searching for its exported markdown. Where that fails, the table has no span, and no error is raised.
  - The parser bump to `_PARSER_LOGIC_VERSION = 3` is made in this task, and E51 is what handles it.
- **E51: re-grounding on a parser upgrade.**
  - The re-ground job never rewrites `results.jsonl`, which is append-only. It appends a row to `runs/<id>/regrounds.jsonl` for each citation it checks. For each span that moved or no longer grounds, it queues a review item of kind `value` with `review_reasons` including `span_moved`.
  - It runs from `arp documents reground` and from the daily publishing job.
  - The current parser version is recorded in `publish_state_dir/parser_version.txt`. The job does nothing while that file matches `parser_version()`.
- **E56: known-answer items.**
  - Known answers live in a real run of type `extraction`, created by `review/quality.py` with `params.trial = True`, so the run is never published. Its rows are built from gold cases. So `get_item`, `build_context` and `decide` work unchanged, and the API cannot tell these items apart.
  - The mapping from item key to case id lives only on the server, in `review_quality_dir/known.jsonl`.
  - Per-reviewer rates are shown only to approvers, with the reviewer's name and never their `user_id`.
  - A correction confirmed by a second review appends a `GoldenSetCase` to `review_quality_dir/extraction_cases.json`. That is the deployment's own gold file; the bundled file is never written.
- **E57: speed aids.**
  - Keyboard shortcuts open and focus a decision form: `a` for approve, `c` for correct, `r` for reject. Submitting stays a click or Enter, which keeps the existing safety stance ("deciding stays a click").
  - `useCardKeys(selector)` stays backward-compatible, because the frozen `BallotReview.tsx` imports it. The new handlers are an optional second argument.
- **E59: error analytics.** The "table" is one JSON file per month, `review_analytics_dir/YYYY-MM.json`, written by a monthly job on the existing `IntervalScheduler`. The job is off by default, behind `review_analytics_schedule_enabled`.
- **E61: bulk accept.**
  - The endpoint only; there is no UI.
  - The sample rate is `bulk_accept_sample_rate = 0.2`, and at least one item per call is always sampled.
  - Sampled items get a first decision with `second_required=True` and `second_reasons=["bulk_sample"]`. The rest go to `final`.
  - The analyst role is required.

## Global Constraints

- VOTING IS FROZEN. Do not change any of these:
  - `arp/api/routers/voting.py`, `arp/voting/`, `arp/cli/voting.py`, `arp/stewardship/voting_feed.py`
  - `BallotReview.tsx`, `ReviewerField.tsx`, `ConfirmDecision.tsx`
  - the voting pages, the voting tests, `useReviewer`

  The voting router stays unauthenticated.
- No new dependencies.
- Never invent FX rates.
- The grounding gate must never be weakened. Every value that is not tagged still needs a grounded citation. Tagged values cite their XBRL fact.
- Dev auth mode stays the default.
- Clients never see `user_id`.
- No model identifiers in code, commits or docs.
- Old `results.jsonl` rows stay readable. Every new model field has a default.
- New schedulers are off by default.
- Backend checks: `cd backend && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python -m pytest -q && ruff check arp tests`. The failures must equal the 42-failure Postgres baseline.
- Frontend checks: `cd frontend && npm run lint && npm test && npm run build`. Expected: 0 lint errors and all tests passing.

## Review Focus

1. A document whose numbers mix conventions, for example a German report quoting a US figure (`1,234.5`): the table and document context win, and anything still ambiguous goes to review, never silently to the wrong number. *(Task 1 test.)*
2. An XBRL fact for a different fiscal year from the field's planned period: no tagged value is taken, and the field falls through to normal extraction. *(Task 4 test.)*
3. A verifier "correction" that cites text not present in the document: it is rejected, the extractor value stands, and the field goes to review. *(Task 5 test.)*
4. A bulk-accept batch where a single item turned high-risk or picked up a failing check after the client loaded it: the whole call is refused, and no decision row is written. *(Task 12 test.)*
5. A known-answer item seen through every review API (list, context, source, decision response): no field, key pattern or run parameter visible to a non-approver reveals it, apart from the run-level `trial` flag in the runs API, which is accepted. *(Task 10 test.)*

---

### Task 1: Number locale and versioned tables (E48, E50)

**Files:**
- Create: `arp/normalise/locale.py`, `arp/normalise/tables/locale_v1.csv`, `arp/normalise/tables/manifest.json`
- Modify:
  - `arp/decision/parsing.py`: `to_number` delegates to the new parser
  - `arp/checks/numeric.py`: `parse_number` delegates to the new parser
  - `arp/normalise/value.py`: `typed_value` takes `decimal`
  - `arp/schemas/common.py`: `SourceDocument.language` and `SourceDocument.decimal`, both `str | None = None`
  - `arp/ingestion/local_files.py`: sets both fields at parse time
- Test: `tests/test_normalise_locale.py`, `tests/test_normalise_tables_manifest.py`

**Interfaces:**
- Produces:
  - `parse_number(text: str, decimal: Literal["point", "comma"] | None = None) -> tuple[float | None, bool]`. The bool means "ambiguous". It handles everything the current `checks/numeric.parse_number` handles (parentheses negatives, unicode minus, thin space and apostrophe separators, mixed `,` and `.`).
  - `detect_language(text: str) -> str | None`, using `locale_v1.csv` stop-word counts with a minimum of 5 hits.
  - `decimal_for(language: str | None) -> Literal["point", "comma"] | None`
  - `context_decimal(numbers: list[str]) -> Literal["point", "comma"] | None`, which decides from unambiguous neighbours such as `1.234,56` or `12,5`.
  - `typed_value(field, pv, *, fiscal_year_end, planned, decimal=None)`. When the value is ambiguous, it adds the review reason `number_locale_ambiguous` to the field.
  - Tests: `table_versions() -> dict[str, dict]` reads `manifest.json`, which lists `units_v1`, `scale_v1`, `fx_v1`, `basis_v1` and `locale_v1`.

- [ ] **Step 1: Write the failing tests.**
  - `test_point_and_comma_resolve_by_context` (the spec's test):
    - `parse_number("1.234", "comma") == (1234.0, False)`
    - `parse_number("1.234", "point") == (1.234, False)`
    - `parse_number("1,234", "comma") == (1.234, False)`
    - `parse_number("1,234", None) == (1234.0, True)`
  - `test_context_decimal_from_neighbours`: `context_decimal(["1.234,56", "7"]) == "comma"`, `context_decimal(["12.5"]) == "point"` and `context_decimal(["1,234"]) is None`.
  - `test_detect_language_german`: a German paragraph gives `"de"`, and `decimal_for("de") == "comma"`.
  - `test_mixed_document_table_context_wins` (Review Focus 1): in a document whose language is `de`, a table with `context_decimal == "point"` parses `1,234.5` as 1234.5, not ambiguous.
  - `test_ambiguous_value_flags_review`: `typed_value` on raw text `1,234` with `decimal=None` adds `number_locale_ambiguous`.
  - `test_existing_parse_number_behaviour_kept`: the cases in `tests/test_checks_numeric.py` still pass through the delegated path. Run that file unchanged.
  - Manifest tests:
    - `test_manifest_hash_matches_table` (parametrized per table): the sha256 of the file bytes equals `manifest[table]["sha256"]`;
    - `test_manifest_version_matches_filename`: `units_v1` has version 1;
    - `test_changed_table_without_bump_fails`: write a modified copy into `tmp_path`, run the same checker function, `check_manifest(tables_dir, manifest)`, and assert it reports that table.
- [ ] **Step 2:** Run `pytest tests/test_normalise_locale.py tests/test_normalise_tables_manifest.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the interfaces above.**
  - `check_manifest(tables_dir: Path, manifest: dict) -> list[str]` lives in `locale.py`'s sibling module `normalise/tables_manifest.py`.
  - `locale_v1.csv` holds about 15 stop words each for `en` (point), `de`, `fr`, `es`, `it` and `nl` (all comma).
  - `local_files` sets `language` and `decimal` from the parsed text.
- [ ] **Step 4:** Run those tests plus `tests/test_checks_numeric.py tests/test_normalise_value.py tests/test_decision*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(normalise): locale-aware number parsing and table version manifest (E48, E50)`

### Task 2: Round-trip check (E49)

**Files:**
- Create: `arp/checks/round_trip.py`
- Modify: `arp/checks/__init__.py` (register it on layer 3)
- Test: `tests/test_checks_round_trip.py`

**Interfaces:**
- Consumes: Task 1's `parse_number`.
- Produces: `check_round_trip(spec, field, ctx) -> list[CheckResult]`, with `check_id="round_trip"` and layer 3.
  - It reverses the conversion: `canonical_value / fx_rate / unit factor / scale_applied`, using `normalise.units.lookup_unit` and `lookup_scale` and the stored `fx_rate`.
  - It compares the result with `parse_number(raw_value_text)` within a relative `1e-6`.
  - It gives `not_applicable` when there is no canonical value or no raw text.
  - A failure has severity `block` and a detail naming both numbers.

- [ ] **Step 1: Write the failing tests.**
  - `test_round_trip_passes_for_correct_conversion`: raw `"EUR 1.5 million"`, canonical 1,500,000 EUR, scale 1e6.
  - `test_altered_conversion_fails` (the spec's test): the same field with `canonical_value` 1,600,000 gives outcome `fail` with severity `block`.
  - `test_round_trip_with_fx`: a USD canonical with a stored `fx_rate` reverses to the raw EUR value.
  - `test_not_applicable_without_canonical`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_checks_round_trip.py tests/test_checks_*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(checks): round-trip conversion check (E49)`

### Task 3: Table grounding (E45)

**Files:**
- Modify:
  - `arp/schemas/common.py`: `TableRef`, `TableCell` and `TableSpan` models; `SourceDocument.table_spans: list[TableSpan] = []`; `Citation.table_ref: TableRef | None`
  - `arp/ingestion/local_files.py`: `_extract_pdf_text` also returns table spans, and `_PARSER_LOGIC_VERSION = 3`
  - `arp/ingestion/parsing.py`: `chunk_document` emits one chunk per table, with `section` = the caption
  - `arp/grounding.py`: `ground_citations` sets `table_ref` when the match lies inside a cell
  - `arp/checks/numeric.py`: `check_caption_scale` and `check_row_label` use `table_ref` when present, and update the "table_ref is always None" docstring
- Test: `tests/test_table_grounding.py`

**Interfaces:**
- Produces:
  - `TableRef(table_id: str, row_label: str | None, col_label: str | None, caption: str | None, unit_note: str | None)`
  - `TableSpan(table_id, char_start, char_end, caption, unit_note, cells: list[TableCell])` and `TableCell(row_label, col_label, char_start, char_end)`
  - `table_spans_from_docling(doc, text: str) -> list[TableSpan]`, pure. It locates each table's exported markdown in `text`, maps each cell's text to its offset inside that block, and skips any table it cannot locate.
  - `_table_ref_for_offset(doc: SourceDocument, char_start: int) -> TableRef | None` in `grounding.py`.

- [ ] **Step 1: Write the failing tests.** Use a fake Docling-like object with `tables[i].export_to_markdown()` and cells with `text`, `row_header` and `column_header`, or whatever minimal attribute shape the implementation reads, documented in the test.
  - `test_value_in_table_cell_cites_the_cell` (the spec's test): a document whose text contains a markdown table with a "Revenue" row and an "FY2024" column. Grounding a quote of that cell's number gives `table_ref.row_label == "Revenue"`, `col_label == "FY2024"`, and a caption and unit note taken from the text before the table (`"in EUR million"`).
  - `test_value_outside_table_has_no_table_ref`
  - `test_unlocatable_table_is_skipped`: a table whose markdown is not in the text gives no span and no exception.
  - `test_chunk_document_emits_table_chunk`
  - `test_old_citation_without_table_ref_still_loads`: an old-row dict with `"table_ref": null` validates.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_table_grounding.py tests/test_grounding*.py tests/test_checks_numeric.py tests/test_ingestion*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(grounding): table cell references from Docling table structure (E45)`

### Task 4: Structured data first (E29)

**Files:**
- Modify:
  - `arp/schemas/datapoints.py`: `FieldDefinition.xbrl_tags`, `ExtractedField.method`
  - `arp/schemas/common.py`: `ProvenanceInfo.adjudicator_model: str | None = None`, used by Task 6
  - `arp/ingestion/xbrl.py`: a public `fact_for_tags`
  - `arp/extraction/graph_shape.py`: an optional `try_tagged` entry
  - `arp/extraction/field_graph.py`: the `try_tagged` node, plus `extract_one_field(..., xbrl_facts=None, cik=None)`
  - `arp/extraction/pipeline.py`: one facts fetch per company, passed to every field
  - `arp/extraction/steps.py`: a step label
- Test: `tests/test_tagged_first.py`

**Interfaces:**
- Produces:
  - `FieldDefinition.xbrl_tags: list[str] = []`
  - `ExtractedField.method: Literal["extracted", "tagged", "adjudicated"] = "extracted"`
  - `XbrlFactSource.fact_for_tags(facts_json: dict, tags: list[str], *, fiscal_year: int) -> XbrlFact | None`. It accepts annual 10-K and 10-K/A facts only, for exactly that fiscal year, and takes the first tag in list order that has a fact.
  - `try_tagged` builds an `ExtractedField`:
    - `method="tagged"`;
    - `value` and `raw_value_text` from the fact;
    - `unit` from the fact unit;
    - `citations=[fact.as_citation(cik)]`, whose quote names the tag;
    - `grounded=True` and `confidence=1.0`;
    - the canonical value from the existing `normalise.value` path.

    It then routes to END. With no fact, it routes to `gather_evidence`.
  - The financials graph keeps working: the new graph-shape kwarg is optional.

- [ ] **Step 1: Write the failing tests.** Use a fake `XbrlFactSource` that returns a fixed companyfacts JSON, and an LLM fake that counts `complete_structured` calls.
  - `test_tagged_field_makes_zero_model_calls` (the spec's test): a field with `xbrl_tags=["us-gaap:Revenues"]` and a matching FY fact gives `method == "tagged"`, the citation quote contains `Revenues`, and the call count is 0 for both the extractor and the verifier fakes.
  - `test_fact_for_other_year_falls_through` (Review Focus 2): the fact is only for FY2022 and the plan is FY2024. The field is extracted normally, the call count is above 0, and `method == "extracted"`.
  - `test_untagged_field_unchanged`
  - `test_tagged_value_auto_accepts_when_checks_pass`: `route()` gives `auto_accept` for a released field that has passed first audit.
  - `test_old_row_without_method_reads_as_extracted`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_tagged_first.py tests/test_field_graph*.py tests/test_financials*.py tests/test_extraction*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(extraction): tagged XBRL values before any model call (E29)`

### Task 5: Verifier redesign (E38)

**Files:**
- Modify:
  - `arp/extraction/verifier_agent.py`
  - `arp/extraction/field_graph.py`: `_verify`
  - `arp/extraction/aggregator.py`: the disagree branch
  - `arp/schemas/datapoints.py`: `Alternative.source` gains `"verifier"`, `"adjudicator"` and `"tagged"`
  - `arp/schemas/review.py`: `ReasonCode` gains `verifier_correction_uncited` and `adjudicator_unresolved`
- Test: `tests/test_verifier_redesign.py`

**Interfaces:**
- Produces:
  - `class DisagreementType(StrEnum)`: `none`, `value`, `unit_or_scale`, `period`, `entity`, `not_disclosed`.
  - `VerifierOutput` gains `disagreement_type: DisagreementType = none` and `citations: list[Citation] = []`.
  - `async blind_verify(company_name, field, evidence, verifier_llm, planned_periods) -> tuple[VerifierOutput, LLMUsage]`. It calls `extract_field` with the verifier client, never seeing the draft, then `compare(draft, blind) -> DisagreementType` in code. `agrees` means `disagreement_type == none`, and the blind extraction's value and citations become `corrected_value` and `citations` when they differ.
  - `_verify` uses `blind_verify` when `field.high_risk`, and `verify_extraction` (the review prompt, now asking for `disagreement_type` and citations) otherwise.
  - Aggregator: a correction grounds `verifier.citations` with `ground_citations(...)`.
    - With at least one grounded citation, the correction replaces the value (as today) and its citations are kept.
    - With none, the extractor value stays, `Alternative(source="verifier", value=corrected)` is appended, and `verifier_correction_uncited` goes into `review_reasons`.

- [ ] **Step 1: Write the failing tests.** Use LLM fakes returning fixed outputs.
  - `test_correction_without_citation_is_rejected` (the spec's test and Review Focus 3): the verifier corrects with `citations=[]`, or with a quote not in the text. The final value equals the extractor's, `verifier_correction_uncited` is in `review_reasons`, and the alternative with source `verifier` holds the corrected value.
  - `test_grounded_correction_replaces_value`
  - `test_high_risk_field_verifies_blind`: the verifier fake records its prompt, which never contains the draft value, and `disagreement_type` comes from code (a value differing beyond tolerance gives `value`, a scale difference gives `unit_or_scale`).
  - `test_low_risk_field_uses_review_prompt`
  - `test_verifier_agreement_has_type_none`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_verifier_redesign.py tests/test_aggregator*.py tests/test_field_graph*.py tests/test_golden_set.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(extraction): blind high-risk verification, typed disagreement, cited corrections (E38)`

### Task 6: Adjudication (E40)

**Files:**
- Create: `arp/extraction/adjudicator.py`
- Modify: `arp/extraction/field_graph.py` (an `adjudicate` node between `verify` and `aggregate`), `arp/extraction/aggregator.py`
- Test: `tests/test_adjudicator.py`

**Interfaces:**
- Consumes: Task 5's `VerifierOutput.disagreement_type` and `citations`, and Task 4's `ExtractedField.method` and `ProvenanceInfo.adjudicator_model`.
- Produces:
  - `AdjudicatorOutput(settled: bool, value: str | float | bool | None, citations: list[Citation], notes: str)`
  - `async adjudicate(company_name, field, chunks, draft, verifier: VerifierOutput, llm) -> tuple[AdjudicatorOutput, LLMUsage]`, using `llm.complete_structured(system=..., prompt=..., output_model=AdjudicatorOutput)`.
  - The node runs only when `verifier.disagreement_type != none`, using the verifier client. It records `provenance.adjudicator_model`.
  - Aggregator:
    - When the result is settled and at least one of its citations grounds, the field gets the value, `method="adjudicated"`, and those citations.
    - Otherwise the field gets `adjudicator_unresolved` in `review_reasons`, with both the extractor and verifier candidates in `alternatives`.

- [ ] **Step 1: Write the failing tests.**
  - `test_adjudicator_not_called_when_verifier_agrees` (the spec's test): the adjudicator fake's call count is 0.
  - `test_typed_disagreement_calls_adjudicator_once`
  - `test_settled_with_grounded_citation_sets_value`: `method == "adjudicated"`.
  - `test_unsettled_or_uncited_goes_to_review`: `adjudicator_unresolved` is set and both alternatives are present.
  - `test_adjudicator_usage_counted_in_cost`: the usages list includes the third call.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_adjudicator.py tests/test_verifier_redesign.py tests/test_field_graph*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(extraction): adjudicator call only on typed disagreement (E40)`

### Task 7: Cross-source check (E39)

**Files:**
- Create: `arp/checks/cross_source.py`
- Modify:
  - `arp/checks/runner.py`: `CheckContext.references`, and layer 5 in the run loop
  - `arp/checks/__init__.py`: register the check
  - `arp/schemas/datapoints.py`: `CheckConfig.cross_source_tolerance: float = 0.01`
  - `arp/extraction/pipeline.py`: build the references
- Test: `tests/test_checks_cross_source.py`

**Interfaces:**
- Consumes: Task 4's XBRL facts per company and `ExtractedField.method`; `RunHistory` (`ctx.history`); `publish.reader.facts_as_of` when `postgres_dsn` is set.
- Produces:
  - `Reference(source: Literal["tagged", "text", "published"], value: float, unit: str | None)`
  - `CheckContext.references: dict[str, list[Reference]] = {}`, keyed by item key.
  - `check_cross_source(spec, field, ctx) -> list[CheckResult]`, with `check_id="cross_source"` and layer 5.
    - For each reference whose unit matches the field's canonical unit, or where either unit is `None`: `|a - b| / max(|b|, 1e-9) > tolerance` gives `fail` with severity `warn`, and a detail naming the source and both values.
    - It gives `not_applicable` without references or without a canonical value.
  - `build_references(fields, *, xbrl_facts, cik, history, published) -> dict[str, list[Reference]]` in `pipeline.py`, pure and following the rules in the deviations.

- [ ] **Step 1: Write the failing tests.**
  - `test_tagged_and_text_differ_beyond_tolerance_fails` (the spec's test): a text value of 100 against a tagged reference of 103 fails. Against 100.5 it passes.
  - `test_published_reference_compared`
  - `test_unit_mismatch_ignored`
  - `test_build_references_rules`:
    - a tagged field gets the prior text value from the history fake;
    - an extracted field with a tag fact gets a `tagged` reference;
    - with no DSN there is no `published` reference.
  - `test_layer5_runs`: `run_checks` includes `cross_source` results.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_checks_cross_source.py tests/test_checks_*.py tests/test_extraction*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(checks): cross-source reference check (E39)`

### Task 8: Check effectiveness report (E41)

**Files:**
- Create: `arp/checks/effectiveness.py`
- Modify:
  - `arp/api/routers/review.py`: `GET /api/review/check-effectiveness`, approver only
  - `arp/cli/extraction.py`: `extract check-effectiveness`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_checks_effectiveness.py`, with the fixture `tests/fixtures/effectiveness/`

**Interfaces:**
- Produces:
  - `CheckStat(check_id, field_id, field_version: int | None, fired: int, decided: int, hits: int, overturns: int, hit_rate: float, overturn_rate: float)`
  - `effectiveness(run_store, *, run_ids: list[str] | None = None) -> list[CheckStat]`
    - It covers non-trial extraction runs.
    - A check has fired on a field when it is in that field's `checks` with outcome `fail`.
    - A field counts as decided when its item has an effective decision (`effective_decisions`).
    - A hit is a decided fired item whose effective decision is `correct` or `reject`.
    - An overturn is a decided fired item whose effective decision is `approve`.
    - Rates are hits or overturns divided by `decided`, and 0.0 when nothing was decided.
  - The output is sorted by `(check_id, field_id, field_version)`.

- [ ] **Step 1: Write the failing test.** `test_report_matches_hand_count`:
  - The fixture is two runs: 6 fields with 3 checks firing in a known pattern, and 5 decisions (2 correct, 1 reject, 2 approve), one of them on a trial run that must be ignored.
  - The expected `CheckStat` list is hand-counted inline in the test, for example `CheckStat("sum", "rev", 1, fired=3, decided=3, hits=2, overturns=1, ...)`.

  Also:
  - `test_endpoint_requires_approver`
  - `test_endpoint_has_no_user_ids`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_checks_effectiveness.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(checks): check effectiveness report per check and field version (E41)`

### Task 9: Re-grounding on parser upgrade (E51)

**Files:**
- Create: `arp/orchestration/reground.py`
- Modify:
  - `arp/publish/gate.py`: extract `reground_citation(c: Citation, *, blob_store, content_store, fuzzy_threshold) -> str`, which `reground(fact, ...)` delegates to
  - `arp/publish/scheduler.py`: the daily job calls `reground_if_parser_changed`
  - `arp/cli/documents.py`: `documents reground [--force]`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_reground_parser.py`

**Interfaces:**
- Consumes: `parser_version()` (`ingestion/local_files.py`); `content_store.get_or_parse` or `get_or_compute` for re-parsing the original from the blob; `ground_citations`; `queue_for_review`.
- Produces:
  - `RegroundReport(checked: int, unchanged: int, moved: int, lost: int, queued: int)`
  - `reground_runs(run_store, *, settings, blob_store, content_store, run_ids=None) -> RegroundReport`
    - It covers every extraction run's `results.jsonl` field citation whose `parser_version` differs from the current one.
    - It re-parses the original with the current parser and re-grounds the stored quote, giving `ok`, `offset_moved` or `not_grounded`.
    - It appends `{item_key, doc_id, old: {char_start, char_end, page, parser_version}, new: {...}, outcome}` to `runs/<id>/regrounds.jsonl`.
    - For `offset_moved` and `not_grounded` it queues a review item (`queue_for_review(run_store, run_id, item_key, {**field_row, "review_reasons": [..., "span_moved"]})`), at most once per `(item_key, parser_version)`.
    - It never rewrites `results.jsonl`.
  - `reground_if_parser_changed(...) -> RegroundReport | None` reads and writes `publish_state_dir/parser_version.txt`. On the first run, when the file is absent, it only records the version.

- [ ] **Step 1: Write the failing tests.**
  - `test_parser_bump_moves_span_and_flags_it` (the spec's test):
    1. Store a document parsed under a fake old parser version, with a citation at offset 10.
    2. The "new parser" (monkeypatched `parser_version` plus parse output) inserts text before it.
    3. Assert outcome `offset_moved`, a `regrounds.jsonl` row with the new offsets, one review-queue row with `span_moved`, and `results.jsonl` unchanged byte for byte.
  - `test_unchanged_span_not_queued`
  - `test_lost_quote_flagged_not_grounded`
  - `test_second_run_same_version_does_nothing` (idempotent)
  - `test_reground_if_parser_changed_first_run_records_only`
  - `test_gate_reground_still_works`: the existing gate tests pass through `reground_citation`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_reground_parser.py tests/test_publish*.py -q` (with the DSN). Expected: PASS.
- [ ] **Step 5:** Commit: `feat(grounding): re-ground stored citations when the parser version changes (E51)`

### Task 10: Reviewer quality loop (E56)

**Files:**
- Create: `arp/review/quality.py`
- Modify:
  - `arp/config.py`: `review_quality_dir`, `known_answer_rate: float = 0.05`
  - `arp/review/decide.py`: after a second-step `second_done` on a `correct` first decision, call `quality.record_confirmed_correction`
  - `arp/api/routers/review.py`: `GET /api/review/quality`, approver only
  - `arp/cli/golden_set.py`: `golden-set seed-known-answers --count N`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_review_quality.py`

**Interfaces:**
- Produces:
  - `seed_known_answers(run_store, settings, *, count: int, seed: int | None = None) -> str`. It creates one extraction run (`params.trial = True`, `schema.json` built from the cases' field definitions) whose `results.jsonl` rows have `route == "review"`, with values deliberately taken from the gold `expected_value` or a perturbed copy (half of each). It appends `{item_key, run_id, case_id, expected_value, perturbed}` to `review_quality_dir/known.jsonl` and returns the run id.
  - `ReviewerStat(name: str, decisions: int, agreement_rate: float, overturn_rate: float, known_answer_items: int, known_answer_accuracy: float)`
  - `reviewer_stats(run_store, settings) -> list[ReviewerStat]`, grouped internally by `user_id` and output by name.
    - Agreement is a reviewer's first decision agreeing (`agrees`) with the effective final decision.
    - An overturn is a first decision that differs from a later second or resolution decision.
    - Known-answer accuracy: approve on an unperturbed case or correct-to-expected on a perturbed one is right; anything else is wrong.
  - `record_confirmed_correction(bundle: dict, corrected_value: dict, settings) -> None` appends a `GoldenSetCase` (from `field_definition`, the evidence text and `expected_value = corrected_value["value"]`) to `review_quality_dir/extraction_cases.json`, which is created if missing. `golden_set.runner.load_cases(path)` must load the file.

- [ ] **Step 1: Write the failing tests.**
  - `test_known_answer_item_indistinguishable_in_api` (the spec's test and Review Focus 5):
    1. Seed known answers, then build one real extraction run with the same field.
    2. For both items, `GET /api/review/items`, `GET .../context` and `GET .../source` (where applicable) as an analyst.
    3. Assert the item dicts have identical key sets, and the context bundles have identical key sets recursively.
    4. Assert no string in either response contains `known`, `gold`, `case_` or `perturb`.
  - `test_reviewer_stats_agreement_and_overturn`: with hand-built decision rows for two users, the rates equal the hand count and the output has no `user_id`.
  - `test_known_answer_accuracy`
  - `test_second_approved_correction_appends_gold_case`: after `decide` (first correct, then second approve by another user), the deployment gold file holds 1 case that `load_cases` reads. The bundled file is unchanged.
  - `test_quality_endpoint_requires_approver`
  - `test_known_answer_run_never_published`: `run_candidates` gives `[]`, because the run is a trial.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_review_quality.py tests/test_review_*.py tests/test_golden_set.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(review): known-answer items, reviewer agreement and overturn rates, gold-set growth (E56)`

### Task 11: Speed aids (E57)

**Files:**
- Modify:
  - `arp/api/routers/extraction.py`: `GET /api/extraction/items/{item_key}/similar`
  - `arp/review/context.py`: the bundle gains `suggested_correction`
  - frontend:
    - `frontend/src/lib/cardKeys.ts`: optional handlers
    - `frontend/src/components/ReviewControls.tsx`: pre-fill from `suggested_correction`, and `a`/`c`/`r` open and focus the decision form
    - `frontend/src/pages/ReviewQueue.tsx`: pass the handlers
    - `frontend/src/api/client.ts`, `frontend/src/types.ts`
- Test: `tests/test_similar_decisions.py`, `frontend/tests/cardKeys.test.ts`

**Interfaces:**
- Produces:
  - `similar_decisions(run_store, *, run_id: str, item_key: str, limit: int = 10) -> list[dict]`
    - It covers other extraction runs, not trial runs.
    - It returns items whose `field_id` and `issuer_key` match (parsed from the item key with `field_item_key`'s inverse), and whose cited document's `doc_type` equals the current item's first citation's `doc_type`.
    - Each entry is `{run_id, item_key, period, value, decision: public_decision(...)}`, newest first, and never contains `user_id`.
  - The endpoint `GET /api/extraction/items/{item_key}/similar?run_id=...` gives `{"items": [...]}`, or 404 for an unknown run or item.
  - `bundle["suggested_correction"]`: `{value, citations}` from the first alternative with `source == "verifier"` or `"adjudicator"`, or `None`.
  - `useCardKeys(selector: string, handlers?: Partial<Record<"a" | "c" | "r", (card: HTMLElement) => void>>)`, with the same ignore rules as today (inputs, modifiers, dialogs). Calls with one argument are unchanged.

- [ ] **Step 1: Write the failing tests.**
  - `test_similar_matches_field_issuer_doc_type` (the spec's test): of three earlier runs, one matches on all three, one has a different doc type and one a different issuer. Only the first is returned, and it has no `user_id`.
  - `test_similar_excludes_current_run_and_trials`
  - `test_context_suggested_correction_from_verifier_alternative`
  - Frontend `cardKeys.test.ts`:
    - a handler for `a` is called with the focused card;
    - keys typed inside an `input` are ignored;
    - a one-argument call registers only `j`/`k`.

    Use the existing DOM-less style of `frontend/tests/*.test.ts`, extracting a pure key-dispatch function `dispatchCardKey(event, handlers) -> boolean` if needed.
- [ ] **Step 2:** Run `pytest tests/test_similar_decisions.py -q` and `cd frontend && npm test`. Expected: FAIL.
- [ ] **Step 3: Implement.** The frontend pre-fills `corrected` with `setCorrected` when the correct form opens and a suggestion exists. The shortcuts never submit.
- [ ] **Step 4:** Run the backend tests, then `cd frontend && npm run lint && npm test && npm run build`. Expected: PASS, with 0 lint errors.
- [ ] **Step 5:** Commit: `feat(review): similar decisions, prefilled verifier correction, decision shortcuts (E57)`

### Task 12: Guarded bulk accept (E61)

**Files:**
- Modify:
  - `arp/review/decide.py`: extract the per-item locked work into `_decide_locked(...)` and add `bulk_accept(...)`
  - `arp/api/routers/extraction.py`: `POST /api/extraction/items/bulk-accept`, analyst role
  - `arp/config.py`: `bulk_accept_sample_rate: float = 0.2`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_bulk_accept.py`

**Interfaces:**
- Produces:
  - `BulkAcceptRequest(run_id: str, items: list[BulkItem])` with `BulkItem(item_key: str, context_etag: str)`, at most 200 items.
  - `bulk_accept(run_store, req, principal, *, settings, content_store) -> {"accepted": int, "second_review": list[str]}`.
    - The whole call runs under `run_store.lock(run_id)`.
    - It first validates every item and raises `DecisionError(409, ...)` naming the first offending item if any of these fails:
      - the item kind is `value`;
      - the state is `pending`;
      - it is not `high_risk`;
      - no check is failing;
      - the etag matches the current bundle.
    - Only then does it write first decisions (`approve`, reason `confirmed`) with snapshots, through the same path as `decide`.
    - Sampled items (`sampled(item_key, rate)`, plus the item with the smallest hash when none is sampled) get `second_required=True` and `second_reasons=["bulk_sample"]`.
  - The endpoint returns that dict. `DecisionError` maps to its status.

- [ ] **Step 1: Write the failing tests.**
  - `test_high_risk_item_rejects_whole_call` (the spec's test and Review Focus 4): of 3 items, 1 is high-risk. The call returns 409 and the decision log is unchanged (byte compare).
  - `test_failing_check_rejects_whole_call`
  - `test_stale_etag_rejects_whole_call`
  - `test_all_low_risk_accepted_with_sample`: of 10 items, all are approved. At least 1 is in `second_review`, and its state is `first_done`. The others are `final`.
  - `test_bulk_requires_analyst`: a viewer gets 403.
  - `test_bulk_decisions_have_no_user_id_in_response`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.** The single-item `decide` behaviour must not change; the existing `tests/test_review_decide.py` still passes.
- [ ] **Step 4:** Run `pytest tests/test_bulk_accept.py tests/test_review_*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(review): guarded bulk accept with forced sample re-check (E61)`

### Task 13: Error analytics (E59)

**Files:**
- Create: `arp/review/analytics.py`
- Modify:
  - `arp/config.py`: `review_analytics_dir`, `review_analytics_schedule_enabled: bool = False`, and the state dir in the ensure-dirs list
  - `arp/api/deps.py` and `arp/api/main.py`: the scheduler getter and lifespan start/stop
  - `arp/api/routers/review.py`: `GET /api/review/analytics?month=YYYY-MM`, approver only
  - `arp/cli/extraction.py`: `extract review-analytics --month`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_review_analytics.py`

**Interfaces:**
- Produces:
  - `ReasonTotal(field_id, model: str | None, doc_type: str | None, reason: str, count: int)`
  - `monthly_totals(run_store, month: str) -> list[ReasonTotal]`
    - It covers decision rows with `decided_at` in that month, across non-trial extraction runs.
    - Each row is joined to its run's results field: `model = provenance.extractor_model`, `doc_type` = the first citation's doc type.
    - It groups by `(field_id, model, doc_type, reason_code)` and sorts.
  - `write_month(run_store, settings, month) -> Path`, written atomically to `review_analytics_dir/{month}.json`.
  - `ReviewAnalyticsScheduler(IntervalScheduler)` runs daily. On the first day it runs after a month ends, it writes the previous month once, tracked by `last_month` in its config.

- [ ] **Step 1: Write the failing tests.**
  - `test_totals_match_hand_count` (the spec's test): with fixture runs holding 7 decisions over 2 fields, 2 models and 2 doc types, and one decision in another month, the totals equal the inline hand count.
  - `test_write_month_file`
  - `test_scheduler_writes_previous_month_once`: drive its due logic with fixed dates.
  - `test_analytics_endpoint_requires_approver`
  - `test_scheduler_off_by_default`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_review_analytics.py -q`, then the full backend check. Expected: PASS, and the failures equal the baseline.
- [ ] **Step 5:** Commit: `feat(review): monthly error analytics by field, model and document type (E59)`
