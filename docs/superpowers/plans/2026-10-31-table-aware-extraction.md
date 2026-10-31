# Table-Aware Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Table metadata, a document outline with tags, whole tables as evidence, routing by tags (PR 1), and one table read for grouped fields (PR 2).

**Architecture:** Metadata is computed at Docling parse time and stored in the existing `table_spans` JSON (parser version 4). The outline is derived from `full_text` + `page_breaks` at chunking time and cached with the chunk spans. Evidence selection swaps text passages for whole-table passages after ranking. Routing extends `section_filter`. Grouping by `table_group` extends the existing group-call path.

**Tech Stack:** Python 3.13, Docling, pydantic v2, LangGraph, pytest; reportlab (already a dev dependency? check `pyproject.toml`; else build the fixture PDF once and commit it).

**Spec:** `docs/superpowers/specs/2026-10-31-table-aware-extraction-design.md` (approved 2026-10-31). AC-n refer to its table.

## Global Constraints

- Branch `table-aware-extraction`; PR 1 = Tasks 1–6, PR 2 = Task 7, both against `main` (merge `origin/main` first).
- `_PARSER_LOGIC_VERSION` 3 → 4 (one re-parse per document).
- Preset fields whose `document_routing` changes go up one version; nothing else does.
- `evidence_table_max_chars` default 12,000; swap never refills.
- Never delete or weaken an existing test; list every changed test in the PR.
- After any request/response model change: `scripts/export_openapi.py`, `npm run gen:api`, `tsc -b`, commit both.

## Review Focus

1. A table spanning two pages: `page` is the first page; `heading_path` is from the first page (Task 1 test).
2. A heading inside a table's markdown (`## ` in a cell): must not start a new outline entry inside a table span (Task 2 test).
3. A document with no markdown headings (html/txt): outline is one entry or empty; routing falls back (Task 4 test, covered by AC-16).
4. Empty table (no data cells): metadata built, `kind` from caption only, no crash (Task 1 test).
5. A field with both `sections` (old substring) and `section_tags`: a chunk matching either is kept (Task 4 test).

---

### Task 1: Table metadata at parse time
**Files:** `arp/schemas/common.py` (TableSpan, TableRef, TableCell), `arp/ingestion/local_files.py` (`table_spans_from_docling`, version), new `arp/ingestion/table_kinds.py`, `arp/grounding.py` (`_table_ref_for_offset` sets page/kind), fixture `tests/fixtures/tables/capex_two_header_rows.pdf`, tests `tests/test_table_metadata.py`.
**Produces:** `TableSpan.page/heading_path/column_headers/row_labels/scale/unit/kind`; `table_kind(caption, heading_path, column_headers) -> str | None`; `TableRef.page/kind`.
- [ ] Build the fixture PDF (2 pages, AC-1 layout) and commit it.
- [ ] Tests AC-1, 1b, 1c, 2, 2b, 3, 3b, 3c, 3d, 4, 5, 6, 23, plus Review Focus 1 and 4. Run → fail.
- [ ] Implement: header path per column from every header row top-down joined " – "; page from the table item's provenance (`table.prov[0].page_no`); heading path from the markdown headings before the table's offset (shared helper with Task 2); scale/unit in order caption → header cells → "Unit"/"Einheit" column (reuse `lookup_scale`); kind via ordered rules.
- [ ] Run → pass; `ruff check .`; commit `feat(parsing): table metadata`.

### Task 2: Document outline and chunk tags
**Files:** new `arp/ingestion/outline.py`, new `arp/ingestion/section_tags.py`, `arp/ingestion/chunk_spans.py` (cache entry carries outline), `arp/ingestion/parsing.py` (`ChunkSpan`/`DocumentChunk` page, section_tags, table_id, caption; table chunk section = heading), `arp/schemas/common.py` (DocumentChunk fields), tests `tests/test_outline.py`.
**Produces:** `outline(doc) -> list[OutlineEntry]`; `section_tags_for(title) -> list[str]`; `DocumentChunk.page/section_tags/table_id/caption`.
- [ ] Tests AC-7, 8, 8b, 8c, 9, 9b, 9c, 9d, 9e, Review Focus 2. Run → fail.
- [ ] Implement; keep `section` for text chunks unchanged.
- [ ] Run → pass, plus `tests/test_parsing*.py tests/test_extraction_pipeline.py`; commit `feat(parsing): document outline and section tags`.

### Task 3: Whole tables as evidence and richer passage headers
**Files:** `arp/extraction/field_graph.py` (`field_evidence`), `arp/config.py` (`evidence_table_max_chars`), `arp/extraction/extractor_agent.py` (`format_evidence`), tests `tests/test_table_evidence.py`.
**Produces:** `swap_tables(selected, all_chunks, max_chars) -> list[DocumentChunk]` in `field_graph.py`.
- [ ] Tests AC-10, 11, 12, 13, 14, 23b. Run → fail.
- [ ] Implement swap after `select_relevant_chunks`, keep rank, dedupe, cap; extend `format_evidence` header (only set fields; existing callers that pass a custom `header` keep their output).
- [ ] Run → pass, plus `tests/test_extraction_prompts.py tests/test_grounding.py tests/test_table_grounding.py`; commit `feat(extraction): whole tables as evidence`.

### Task 4: Routing by tags and table kinds, with trace
**Files:** `arp/schemas/datapoints.py` (`DocumentRouting.section_tags/table_kinds`), `arp/planning/doc_routing.py` (`section_filter` returns kept + matched), `arp/extraction/field_graph.py` (state + trace `routing`), `arp/walkthrough/trace.py` (field_entry routing key), tests `tests/test_tag_routing.py`.
- [ ] Tests AC-15, 16, 17, 18, Review Focus 5. Run → fail.
- [ ] Implement; `section_filter` signature stays for existing callers (add `section_filter_with_report` returning `(chunks, report)`).
- [ ] Run → pass, plus `tests/test_doc_routing.py tests/test_walkthrough_*.py`; regenerate API contract if the walkthrough response model changed; commit `feat(retrieval): route by section tags and table kinds`.

### Task 5: Preset routing
**Files:** `arp/presets/green.py`, `arp/presets/transition_capex.py`, `arp/presets/transition_plan.py`, `tests/test_presets_green.py` etc., snapshot allowances in `tests/test_presets_transition_capex.py`, `tests/test_presets_transition_plan*.py` (versions only, listed in PR).
- [ ] Tests AC-19, 19c, 19d, 19e, 19f, 19g. Run → fail.
- [ ] Implement tags/kinds and version bumps.
- [ ] Run → pass, plus all `tests/test_presets_*.py tests/test_rules_*.py`; commit `feat(presets): route capex and transition-plan fields`.

### Task 6: Scoring script, full suite, PR 1
**Files:** new `backend/scripts/answer_check_score.py`, tests `tests/test_answer_check_score.py` (AC-28…28e), `tests/golden/answer_check/` (export once the owner has approved cards; until then the Claude-proposed export, marked as such).
- [ ] Tests AC-28, 28b, 28c, 28d, 28e → implement → pass.
- [ ] Regression: AC-23c (existing check/routing tests unchanged). Full backend suite alone (no parallel DB use). `ruff check .`.
- [ ] Re-parse RWE, Siemens, BASF; run green capex and transition plan with Haiku + Sonnet; score AC-26/27/27b (reported, not gating until cards approved).
- [ ] Merge `origin/main`, push, open PR 1 (`risk:normal`, `Spec: table-aware-extraction`), subscribe.

### Task 7 (PR 2): One table read
**Files:** `arp/schemas/datapoints.py` (`FieldDefinition.table_group`), `arp/extraction/pipeline.py` (grouping), `arp/presets/green.py` (`table_group`), tests `tests/test_table_group.py`.
- [ ] Tests AC-20, 20b, 20c, 20d, 21, 22, 22b, 22c. Run → fail.
- [ ] Implement: group by `table_group` regardless of `high_risk`/`extraction_group_size`; evidence = `merge_evidence` of the group's routed evidence; fallback per field as today.
- [ ] Full suite; rerun the capex scoring; PR 2 against `main` after PR 1.
