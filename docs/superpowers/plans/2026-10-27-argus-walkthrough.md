# Argus Walkthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record what each field's models saw and said during a run, serve it per row through one endpoint, and show it as a ten-step walkthrough screen in Argus, reachable from every result row and review item.

**Architecture:** A small `arp/walkthrough/` package owns the trace format (`trace.py`: build entries, write/read `traces/<company_id>.json` best effort) and the read side (`view.py`: pick the row, follow reuse and moves, cut passage text). Pipelines collect entries through optional side-channel arguments (`trace_sink` dicts and `on_*` callbacks), so existing signatures, return types and callers stay as they are; only the run workers (`execute_*_run`, seeding) pass a sink and write the file. The frontend adds one lazy page, one pure helper module, and a link on each result and review surface.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, pydantic, Postgres-backed `RunStore` (run folder files via `run_dir`); React + TypeScript (Vite), `node --test` for frontend unit tests.

**Spec:** `docs/superpowers/specs/2026-10-27-argus-walkthrough-design.md` (approved 2026-10-27). Read its Design section and the AC rows each task names.

## Global Constraints

- No extra model call anywhere (AC-28–30, AC-65–67, AC-73). Traces are built from values the graphs already hold.
- Stored result rows and every results endpoint body stay exactly as on `main` (AC-25, AC-26, AC-63). Never put trace data into result rows.
- Only `execute_extraction_run`, `execute_financials_extraction_run`, `execute_tnfd_extraction_run` and `seed_known_answers` write traces. `_extract_company` callers in `research/` and `golden_set/` and `extract_one_field` callers in `golden_set/`, `transition_barrier/` pass no sink and write nothing (AC-23, AC-24).
- Trace file: `run_store.run_dir(run_id) / "traces" / f"{company_id}.json"`, top-level keys only `fields`, `plans`, `record`, each present only when filled. Field entries always carry every key: `field_id, grouped, skipped, passages, extractor, verifier, adjudicator, vision`; `verifier` has `model, prompt_version, blind, answer, verdict`; other calls `model, prompt_version, answer`. Passage keys exactly `doc_id, char_start, char_end, section`.
- `skipped` values exactly `tagged`, `no_evidence`, `derived`, `documents_held`; `tagged`/`derived` win over `documents_held`.
- Writing a trace never raises: on any exception log a warning and `run_store.append_event(run_id, {"type": "trace_write_failed", "company_id": ..., "at": <iso>})`.
- `model`/`prompt_version` come from the call's `LLMUsage` (the value the row provenance records).
- Endpoint: `GET /api/walkthrough/runs/{run_id}/companies/{company_id}?item=&period_end=&basis=`, mounted with `dependencies=[Depends(authorize)]`; 404 checks (run, company, item) before 422 checks before the row check; response keys and status rules exactly as the spec's "The endpoint" section.
- `not_recorded_reason` order: `write_failed`, `expired` (`trace_run_id` manifest `created_at` older than `settings.retention_runs_days`), `before_traces`; checked against the `trace_run_id` run.
- Screen copy verbatim from the spec: step names and labels in its two step tables, the three "not recorded" notes, `Reused from run <id>; the steps show that run.`, `Show the other N passages`, `Text not available`, link text `How was this found?`.
- Route `#/argusWalkthrough/<run_id>/<company_id>/<item>[/<period_end>]`, `unspecified` for a missing period, plan list rows append `?basis=<basis>` to the last segment.
- Checks before each commit: `cd backend && ruff check . && python3 -m pytest <touched test files>` with `ARP_TEST_POSTGRES_DSN` set to a private database; frontend tasks also `cd frontend && npm run lint && npx tsc -b && npm test`. Never run the whole backend suite locally (40 min, shared DB).
- Never delete or weaken an existing test; list every test change in the PR. PR body carries `Spec: argus-walkthrough` on its own line, label `risk:normal`.

## Review Focus

1. A company with many fields and documents: one trace write per company, not per field; a 30-field company must not rewrite the file 30 times.
2. Document text missing from the content store (pruned cache, upload deleted): passages show position and `Text not available`, the endpoint still returns 200 (test in Task 6).
3. A run id or company id with path characters (`../x`): `run_dir` already validates run ids with `safe_id`; the company id in the trace path must go through `safe_id` too (test in Task 1).
4. A trace file that is corrupt JSON (half-written after a crash): `read_trace` returns `None`, the walkthrough reads `before_traces`, never a 500 (test in Task 1).
5. A field whose row exists but whose `period_end` changed between runs on reuse: the reuse chain matches on field id and period (and basis); a missing match stops the chain at the last run found and reads `before_traces` (test in Task 6).

---

### Task 1: Trace format and file I/O

**Files:**
- Create: `backend/arp/walkthrough/__init__.py` (empty), `backend/arp/walkthrough/trace.py`
- Test: `backend/tests/test_walkthrough_trace.py`

**Interfaces:**
- Produces:
  - `passage(chunk: DocumentChunk) -> dict` → `{"doc_id", "char_start", "char_end", "section"}`
  - `call(usage: LLMUsage | None, answer: BaseModel | None) -> dict | None` → `{"model", "prompt_version", "answer": answer.model_dump(mode="json")}`, `None` when `answer` is `None`
  - `verifier_call(usage, answer, *, blind: bool, verdict: BaseModel | None) -> dict | None` (adds `blind`, `verdict`)
  - `field_entry(field_id: str, *, grouped: bool = False, skipped: str | None = None, passages: list[dict] = (), extractor: dict | None = None, verifier: dict | None = None, adjudicator: dict | None = None, vision: dict | None = None) -> dict`
  - `trace_path(run_store, run_id: str, company_id: str) -> Path`
  - `write_trace(run_store, run_id: str, company_id: str, trace: dict) -> None` (best effort, never raises; skips writing when `trace` is empty)
  - `read_trace(run_store, run_id: str, company_id: str) -> dict | None` (`None` on missing or unparsable file)

- [ ] **Step 1: Write the failing tests**
  - `test_field_entry_has_every_key`: `field_entry("f1")` keys == `{"field_id","grouped","skipped","passages","extractor","verifier","adjudicator","vision"}`, all empty/None/False.
  - `test_passage_keys_are_exact`: a `DocumentChunk` → dict keys exactly `{"doc_id","char_start","char_end","section"}`.
  - `test_call_records_usage_and_answer`: `call(LLMUsage(model="m", prompt_version="p"), VerifierOutput(agrees=True, confidence=0.9, notes="ok"))["answer"]["agrees"] is True`, `["model"] == "m"`; `call(usage, None) is None`.
  - `test_write_then_read_round_trip` (uses `run_store`): `read_trace(...) == trace`; file at `run_dir/traces/c1.json`.
  - `test_write_failure_records_event_and_does_not_raise`: make `run_dir/traces` a regular file; `write_trace` returns; `run_store.read_events(run_id)` has one `{"type": "trace_write_failed", "company_id": "c1"}` (plus `at`).
  - `test_corrupt_trace_reads_as_none` (Review Focus 4): file content `{not json` → `None`.
  - `test_company_id_with_path_parts_is_refused` (Review Focus 3): `trace_path(rs, run_id, "../x")` raises `ValueError`; `write_trace` with it records `trace_write_failed` and writes nothing outside `traces/`.
- [ ] **Step 2: Run.** `cd backend && python3 -m pytest tests/test_walkthrough_trace.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement `trace.py`.** Use `arp.storage` `safe_id` for the company id; write via a temp file + `os.replace` so a crash never leaves a half file. Log with `logging.getLogger(__name__)`.
- [ ] **Step 4: Run.** → PASS.
- [ ] **Step 5: Commit** `feat: trace format and best-effort trace files`.

### Task 2: Field graph records its trace

**Files:**
- Modify: `backend/arp/extraction/field_graph.py` (`extract_one_field` gains `trace_sink: dict | None = None`; `_verify`, `_aggregate`)
- Modify: `backend/arp/extraction/verifier_agent.py` (`blind_verify(..., on_draft: Callable[[ExtractionDraft], None] | None = None)`)
- Modify: `backend/arp/extraction/vision_check.py` (`check_on_page(..., on_reading: Callable[[PageReading], None] | None = None)`)
- Test: `backend/tests/test_walkthrough_field_graph.py`

**Interfaces:**
- Consumes: Task 1 `passage`, `call`, `verifier_call`, `field_entry`.
- Produces: when `trace_sink` is given, `extract_one_field` sets `trace_sink[field.field_id] = field_entry(...)` before returning; return value unchanged. `skipped` is `"tagged"` when the tagged path ended the graph, `"no_evidence"` when evidence was empty, else `None`. `grouped` is `grouped is not None`; for a grouped field `extractor.answer.values` holds only that field's draft (the `grouped[0]` draft). Blind verifier: `answer` = the draft passed to `on_draft`, `verdict` = the `VerifierOutput`; non-blind: `answer` = `VerifierOutput`, `verdict` = `None`. `vision` = `call(usage, reading)` of the last vision call that ran for the field, else `None`.

- [ ] **Step 1: Write the failing tests** (use `fake_llm`, a one-document setup like `tests/test_field_graph_high_risk.py`):
  - `test_entry_for_agreeing_field` (AC-1 shape): extractor 120, verifier agrees → entry `extractor.answer.values[0].value == 120`, `verifier.blind is False`, `verifier.verdict is None`, `adjudicator is None`, `vision is None`, `skipped is None`, passages keys exact and equal in order to the chunks in the extractor prompt (each chunk text appears in `llm.prompts[0]`, in order).
  - `test_blind_verifier_draft_is_kept` (AC-2): high-risk field, blind draft 2.794, adjudicator `settled=False` → `verifier.blind is True`, `verifier.answer["values"][0]["value"] == 2.794`, `verifier.verdict["agrees"] is False`, `adjudicator.answer.settled is False`.
  - `test_tagged_field_entry` (AC-6): field with `xbrl_tags` and a fact source → `skipped == "tagged"`, `passages == []`, all calls `None`.
  - `test_no_evidence_entry` (AC-33): no keyword match → `skipped == "no_evidence"`.
  - `test_vision_answer_recorded` (AC-39) and `test_no_vision_when_fallback_off` (AC-40): script `PageReading`; with `vision_fallback_enabled` the entry's `vision.answer` equals the scripted reading; off → `vision is None`.
  - `test_no_sink_changes_nothing`: same call without `trace_sink` returns the same 3-tuple as before; `llm.calls` unchanged (AC-28: one `ExtractionDraft`, one `VerifierOutput`).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_walkthrough_field_graph.py -q` → FAIL.
- [ ] **Step 3: Implement.** Add `trace: dict` to `FieldState` only if needed; simplest is to build the entry from `final_state` after `run_graph` (evidence, draft, verifier, adjudicator, usages) plus two locals captured by the `on_draft` / `on_reading` closures passed through state. Keep callbacks optional and default `None`.
- [ ] **Step 4: Run** the new file plus `tests/test_field_graph_high_risk.py tests/test_verifier_redesign.py tests/test_vision_check.py` → PASS, no existing test changed.
- [ ] **Step 5: Commit** `feat: field graph records passages and model answers when asked`.

### Task 3: Data-point runs write traces

**Files:**
- Modify: `backend/arp/extraction/pipeline.py` (`_extract_company(..., traces: dict | None = None)`; `_extract` closure; derived fields; `all_held`; `_extract_plans`; `execute_extraction_run._worker`)
- Modify: `backend/arp/transition_alignment/plan_extraction.py` (`extract_plan(..., on_draft: Callable[[PlanDraft], None] | None = None)`)
- Test: `backend/tests/test_walkthrough_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `write_trace`, `field_entry`, `passage`, `call`; Task 2 `extract_one_field(trace_sink=)`.
- Produces: with `traces` given, `_extract_company` fills `traces.setdefault("fields", {})[field_id]` for every field it processes this run (extracted, `derived`, `documents_held`), and `traces.setdefault("plans", {})[doc_id] = {"passages": [...], "extractor": call(usage, draft)}` per plan document. Reused fields add nothing. `execute_extraction_run._worker` creates `traces = {}`, passes it, and calls `write_trace(run_store, run_id, company.company_id, traces)` after `_extract_company` returns. Research and golden-set callers pass nothing.

- [ ] **Step 1: Write the failing tests** (reuse helpers from `tests/test_extraction_corrections_pipeline.py` / `tests/test_extraction_pipeline.py`):
  - `test_run_writes_one_trace_file_per_company` (AC-1): the file's top level is exactly `{"fields"}` with one key; entry as in Task 2's first test.
  - `test_trace_file_is_small` (AC-31): AC-1 run's file ≤ 8192 bytes.
  - `test_grouped_fields_share_passages` (AC-8): two groupable fields, group answer A=10, B=20 → both `grouped`, equal `passages`, A's `extractor.answer.values` == one value 10, B's one value 20.
  - `test_derived_and_held_entries` (AC-34, AC-35): derived field → `skipped == "derived"`; company with every document held, schema without tagged/derived fields → every entry `documents_held`.
  - `test_plan_documents_recorded` (AC-41): transition-plan actions run, one plan document yielding two bases → `plans.<doc_id>` has `passages` and `extractor`.
  - `test_trace_write_failure_does_not_fail_the_run` (AC-14): `traces` is a regular file → run `completed`, done count 1, row in results, event `trace_write_failed`.
  - `test_research_callers_write_no_trace` (AC-24): call `_extract_company` the way `research/revenue_exposure/resolver.py` and `research/taxonomy_sources/empirical.py` do → no `traces/*.json` under the runs root. `test_golden_set_writes_no_trace` (AC-23): run the golden-set runner on a one-case set → none under runs root or its output dir.
  - `test_model_call_counts_unchanged` (AC-28, AC-29, AC-66, AC-73): AC-1 run 1 `ExtractionDraft` + 1 `VerifierOutput`; AC-2 run adds 1 `AdjudicatorOutput`; plan run 1 `PlanDraft`; grouped run counts equal those of the same run with no sink.
  - `test_results_unchanged_by_traces` (AC-25 stand-in): results endpoint body of a run equals the body of the same run with trace writing patched out.
  - `test_retention_removes_traces` (AC-71): age the run files past `retention_runs_days`, run `cleanup(apply=True)` → no `traces/*.json`; results body unchanged.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_walkthrough_pipeline.py -q` → FAIL.
- [ ] **Step 3: Implement.** Pass `trace_sink=traces["fields"] if traces is not None else None` in `_extract`. In `_extract_plans`, capture the draft with `on_draft` and the chunks already computed by `plan_evidence`. Derived rows: add the entry where `evaluate_derived` runs. `all_held`: add `documents_held` entries for every field that is neither tagged nor derived.
- [ ] **Step 4: Run** the new file plus `tests/test_extraction_pipeline.py tests/test_extraction_corrections_pipeline.py tests/test_transition_alignment_plan_extraction.py tests/test_golden_precision.py` → PASS.
- [ ] **Step 5: Commit** `feat: extraction runs write one trace file per company`.

### Task 4: Financials and TNFD runs write traces

**Files:**
- Modify: `backend/arp/extraction/financials_graph.py` (`extract_company_financials(..., trace_sink: dict | None = None)`), `backend/arp/extraction/tnfd_graph.py` (`extract_company_tnfd(..., trace_sink=None)`), `financials_pipeline.py` and `tnfd_pipeline.py` (`_extract_company_*` pass-through, `_worker` writes)
- Test: `backend/tests/test_walkthrough_financials_tnfd.py`

**Interfaces:**
- Produces: `trace_sink["record"] = {"passages": [passage(c) for c in evidence], "extractor": call(extractor_usage, draft), "verifier": call(verifier_usage, verifier)}` (no `adjudicator` key). Workers create `{}`, pass it, `write_trace` after the call.

- [ ] **Step 1: Write the failing tests:** `test_financials_trace_record` (AC-9: top level exactly `{"record"}`, keys `passages`, `extractor`, `verifier`, no `adjudicator`), `test_tnfd_trace_record`, `test_financials_call_count` (AC-30: 1 + 1), `test_tnfd_call_count` (AC-65: 1 + 1), `test_financials_results_unchanged` (AC-63 stand-in, as in Task 3).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus `tests/test_financials_extraction_pipeline.py tests/test_tnfd_extraction_pipeline.py` → PASS.
- [ ] **Step 5: Commit** `feat: financials and TNFD runs write traces`.

### Task 5: Seeded known-answer items get traces

**Files:**
- Modify: `backend/arp/review/quality.py` (`_record(..., trace_sink: dict | None = None)`; `seed_known_answers._worker` writes)
- Test: `backend/tests/test_walkthrough_seeding.py`

**Interfaces:**
- Consumes: Task 1; `field_evidence` from `arp.extraction.field_graph`.
- Produces: `trace_sink["fields"][spec.field_id] = field_entry(spec.field_id, passages=[passage(c) for c in field_evidence(spec, [doc], settings)], extractor=call(usage_e, draft), verifier=verifier_call(usage_v, answer, blind=spec.high_risk, verdict=...))` where `usage_e`/`usage_v` are `LLMUsage(model=..., prompt_version=...)` carrying exactly the provenance values `_record` already sets; blind: `answer` = the seeded draft, `verdict` = the seeded `VerifierOutput`; non-blind: `answer` = the seeded `VerifierOutput`, `verdict` = `None`.

- [ ] **Step 1: Write the failing tests** (use the `qenv` fixture from `tests/test_review_quality.py`): `test_seeded_trace_written` (file at the seeded run's `traces/<company_id>.json`), `test_seeded_passages_match_real_selection` (AC-21: `(doc_id, char_start, char_end, section)` list equals `field_evidence(spec, [doc], settings)`), `test_seeded_high_risk_is_blind` (AC-22), `test_seeded_items_unchanged` (AC-62 stand-in: seeded review item bodies equal those created with the trace write patched out, ids/run ids/timestamps ignored).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus `tests/test_review_quality.py` → PASS, unchanged.
- [ ] **Step 5: Commit** `feat: seeded known-answer items carry a trace like real ones`.

### Task 6: Walkthrough endpoint

**Files:**
- Create: `backend/arp/walkthrough/view.py`, `backend/arp/api/routers/walkthrough.py`
- Modify: `backend/arp/api/main.py` (include the router with `dependencies=[Depends(authorize)]`, beside `review.router`)
- Test: `backend/tests/test_walkthrough_api.py`

**Interfaces:**
- Consumes: Task 1 `read_trace`; `load_run_schema`; `_moved_from` (pipeline.py; import it, do not copy); `get_run_store`, `get_document_content_store`, `settings_dep` from `arp.api.deps`.
- Produces:
  - `build_walkthrough(run_store, content_store, settings, *, run_id: str, company_id: str, item: str, period_end: str | None, basis: str | None) -> dict` raising `LookupError` (→404) or `ValueError` (→422), in the spec's check order.
  - Route `GET /api/walkthrough/runs/{run_id}/companies/{company_id}` with query `item` (required), `period_end`, `basis`; no `response_model` (so no OpenAPI regen; no `contract.ts` line).
  - Section names: Financials `segments`, `capex`, `rnd`; TNFD `disclosures`, `core_global_metrics`, `sector_metrics`, `general_requirements`, `sector_leap_considerations`. Single-object sections wrap as `[obj]`, `None` → `[]`. Data-point `rows` = that field's rows from the results endpoint for the company (with the `corrections` default the results endpoint applies), in order; plan list `rows` filtered by `basis`.
  - `passages[i]` = trace passage + `rank` (i+1), `doc_title` (from the record's `documents`), `text` (`full_text[char_start:char_end]` via `content_store.lookup(content_key, parser_version)`, `None` when missing).

- [ ] **Step 1: Write the failing tests** (TestClient pattern of `tests/test_review_context.py`; runs made with Task 3/4 code and `fake_llm`):
  - `test_recorded_field` (AC-3), `test_old_run_before_traces` (AC-4, AC-29), `test_reused_row_reads_origin` (AC-5), `test_three_run_chain` (AC-32), `test_tagged_recorded` (AC-7), `test_no_evidence_recorded` (AC-36), `test_moved_row_reads_source_field` (AC-37), `test_expired` (AC-38), `test_reused_from_expired_run` (AC-64), `test_write_failed` (AC-15), `test_financials_capex` (AC-10), `test_tnfd_disclosures` (AC-11), `test_tnfd_general_requirements_object` (AC-12), `test_tnfd_general_requirements_none` (AC-13), `test_financials_old_run` (AC-68), `test_plan_row_by_basis` (AC-42), `test_not_found_cases` (AC-16, AC-70), `test_missing_period_or_basis_is_422` (AC-17), `test_requires_sign_in` (AC-18: remove the `authorize`/`current_user` overrides → 401), `test_no_review_data` (AC-19: decision note `zq-note-7f3a`, reviewer id a fresh UUID), `test_seeded_and_real_look_alike` (AC-20), `test_text_not_available` (Review Focus 2: content store without the document → `text is None`, HTTP 200), `test_chain_stops_on_period_mismatch` (Review Focus 5).
  - Each asserts the spec row's exact values (e.g. AC-3: `passages[i]["rank"] == i + 1` and `passages[i]["text"] == full_text[char_start:char_end]` for every i).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_walkthrough_api.py -q` → FAIL.
- [ ] **Step 3: Implement** `view.py` (pure functions over `run_store` and `content_store`) and the thin router.
- [ ] **Step 4: Run** → PASS; also `tests/test_review_context.py tests/test_review_quality.py`.
- [ ] **Step 5: Commit** `feat: walkthrough endpoint per row`.

### Task 7: Walkthrough screen

**Files:**
- Create: `frontend/src/lib/walkthrough.ts`, `frontend/src/pages/ArgusWalkthrough.tsx`, `frontend/tests/walkthrough.test.ts`
- Modify: `frontend/src/types.ts` (`Walkthrough` and nested types), `frontend/src/api/client.ts` (`getWalkthrough`), `frontend/src/App.tsx` (TABS `{ id: "argusWalkthrough", label: "Walkthrough" }`, lazy import, render with `key={route.params.join("/")}`), `frontend/src/components/NavIcons.tsx` (entry), `frontend/src/lib/processes.ts` (Argus `screens` gains `["#/argusWalkthrough", "Walkthrough"]` after Universe)

**Interfaces:**
- Consumes: Task 6 response shape.
- Produces (in `lib/walkthrough.ts`, pure, no React):
  - `walkthroughHref(runId: string, companyId: string, item: string, periodEnd?: string | null, basis?: string | null): string` — `#/argusWalkthrough/...`, each segment `encodeURIComponent`, `periodEnd ?? "unspecified"` when the caller passes `periodEnd` for a row (`undefined` = no segment), `?basis=` appended raw-encoded.
  - `parseWalkthroughParams(params: string[]): { runId?: string; companyId?: string; item?: string; periodEnd?: string; basis?: string }`.
  - `steps(w: Walkthrough): Step[]` with `Step = { n: number; name: string; kind: "llm" | "code"; model: string | null; label: string; recorded: boolean; answer: unknown }` — ten data-point steps, six Financials, five TNFD, six plan-list, names and labels exactly as the spec's tables and "Skipped fields" bullets.
  - `notRecordedNote(reason: string, retentionDays: number): string | null` — the spec's three notes verbatim.

- [ ] **Step 1: Write the failing tests** (`node:test`): href round-trips through `parseWalkthroughParams` including `unspecified` and a basis with `:`; `steps()` for the AC-2 shaped fixture gives 10 steps, step 4 name `Verify, blind`, step 5 label `unresolved`; non-blind step 4 name `Verify`; `not recorded` labels for steps 2, 3, 5 when `recorded` false; skipped labels (`taken from XBRL tag`, `no passage matched` + `not reached` ×3, `derived by rule`, `documents held`); Financials 6 steps with step 5 `XBRL value used` when `raw_value_text` contains `sec xbrl` (case-insensitive), TNFD 5 steps, none named `Adjudicate`; `notRecordedNote` texts verbatim.
- [ ] **Step 2: Run** `cd frontend && npm test` → FAIL.
- [ ] **Step 3: Implement** the lib, types, client method, page and wiring. Page layout per the spec's "The screen" and the mockup (https://claude.ai/artifact/U1chr5wCfgSQgXnHJ3qjFg): pickers always visible (prefilled from the route), result card (the "Open in review queue" link shows when the row's `route` is `review`, linking to `#/review/<run_type>/<run_id>`-style queue route the app already uses; the page never fetches or shows decisions, AC-74), steps list; Find evidence shows passages ranked 1–2 with quoted words marked and `Show the other N passages`; model steps have Summary / Full answer / JSON tabs (JSON `pre` not wrapped, `overflow-x: auto`, Copy via `navigator.clipboard.writeText` with a select-text fallback). Use existing tokens and Argus page classes only.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` → PASS. Screenshot `#/argusWalkthrough/...` at 1280 px and 390 px with Playwright against mocked API data (as Task 7 of the previous plan did), then run `/impeccable:impeccable audit` on the page; fix findings it rates as real.
- [ ] **Step 5: Commit** `feat: Argus walkthrough screen`.

### Task 8: "How was this found?" links

**Files:**
- Modify: `frontend/src/components/ExtractionResults.tsx` (`FieldDetail` gains `walkthroughHref?: string`; `ExtractionResultsTable` passes it; `FinancialsResultsTable` adds a link per section), `frontend/src/pages/DataLibrary.tsx` (by-company `FieldDetail` and Financials sections), `frontend/src/components/TnfdResults.tsx` (link on Disclosures; record carries `run_id`), `frontend/src/components/ReviewControls.tsx` (field items: link from `ctx.item.payload` company/field/period and `ctx.value.basis`), `frontend/src/components/RunReviewList.tsx` (Financials/TNFD legacy items: link to `segments` / `disclosures` from `payload.company_id`)
- Test: `frontend/tests/walkthrough.test.ts` (extend)

**Interfaces:**
- Consumes: Task 7 `walkthroughHref`.
- Produces: one `<a href={...}>How was this found?</a>` per surface; nothing else changes on those screens.

- [ ] **Step 1: Write the failing tests:** a helper `rowWalkthroughHref(runId, record, field)` in `lib/walkthrough.ts` (uses `company_id`, `field_id`, `period_end ?? "unspecified"`, `basis` when the field is a plan list row) returns the routes of AC-50, AC-51, AC-52, AC-61; `recordWalkthroughHref(runId, companyId, section)` for AC-53, AC-59, AC-60.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the helpers and the links.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` → PASS. Screenshot the extraction results and a review item with the link, run `/impeccable:impeccable audit`.
- [ ] **Step 5: Commit** `feat: link every result row and review item to its walkthrough`.

### Task 9: Final checks and PR

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest tests/test_walkthrough_*.py tests/test_extraction_pipeline.py tests/test_extraction_corrections_pipeline.py tests/test_financials_extraction_pipeline.py tests/test_tnfd_extraction_pipeline.py tests/test_review_quality.py tests/test_review_context.py tests/test_field_graph_high_risk.py tests/test_verifier_redesign.py tests/test_vision_check.py tests/test_transition_alignment_plan_extraction.py -q` on a private DB → PASS. `cd frontend && npm run lint && npx tsc -b && npm test` → PASS.
- [ ] **Step 2:** Re-read the diff against the spec's Design and Acceptance table; list the `holdout` and `evaluator` rows still owed in the PR.
- [ ] **Step 3:** Open the PR against `main`: label `risk:normal`, `Spec: argus-walkthrough` on its own line, every test change listed, note that `openwiki/` (extraction and review pages) needs the walkthrough for the weekly `/context-refresh`.
