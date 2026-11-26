# Extraction trace and parse report: keep the ranking, step times and parse facts the pipeline already computes

Status: Draft, for owner approval
Slug: `extraction-trace-parse-report`
Risk: slice A `risk:normal`, slice B `risk:high` (see "Risk and storage")
Size: `M`, two slices (A retrieval trace, B parse report), independent of each other

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them. The one
choice with a cost is storage for slice B: a new nullable column on the parsed-text cache, which makes slice B
`risk:high` (you merge it). The alternative, a JSON file beside each document, avoids the label but adds a second
store nothing else uses.

## Why

Approved by Steffen on 2026-11-25 22:00 UTC as the first item of the extraction-precision review
(`/mnt/project-files/extraction-precision/review-and-ideas.md`, ideas 8 to 11, Docling items 1 to 5, Addendum 2
"Suggested order" step 1). The planned Walkthrough, Run review, Documents step and telemetry screens need facts the
pipeline computes and throws away, and later parser and retrieval changes need a baseline to be measured against:

1. `select_relevant_chunks` (`backend/arp/retrieval/select_evidence.py`) ranks every candidate, but `explain` keeps
   scores only for the returned chunks and 3 near misses. A passage ranked 9th cannot be told from one ranked 90th.
2. With small-to-big on, a returned parent's rank comes from one of its pieces; which piece is not kept.
3. The trace already has per-node `seconds` (`try_tagged`, `gather_evidence`, `extract`, `verify`, `adjudicate`,
   `aggregate`, `finalize_no_evidence`). The evidence gate's LLM call is hidden inside `gather_evidence` and the
   page-image check's LLM call inside `aggregate`, so neither can be seen on its own.
4. A parse (`backend/arp/ingestion/local_files.py`) records nothing about itself: not how long it took, which pages
   came out nearly empty, whether OCR ran, or how many Docling tables `table_spans_from_docling` could not place in
   the text (it skips them silently).

## What exists today (main `7e2e955`)

- `select_relevant_chunks(..., explain=None, parents=None, ...)` fills `explain` with `method`, `reranked`,
  `candidates`, `scores` (per returned chunk and near miss: `bm25`, `vector_rank`, `rrf`, `rerank`, each when
  computed), `near_misses`, `embed_model`, `rerank_model`. `field_evidence` (`arp/extraction/field_graph.py`) adds
  `small_to_big` and `near_miss_chunks`. It may call `select_relevant_chunks` twice with the same `explain` (a
  high-risk field whose small-to-big call found nothing falls back to plain chunks).
- `trace.field_entry` (`arp/walkthrough/trace.py`) builds a field's walkthrough entry with exactly the keys
  `field_id, grouped, skipped, passages, extractor, verifier, adjudicator, vision, retrieval, near_misses,
  not_found_reason, seconds, gate, gate_dropped`. `tests/test_walkthrough_trace.py::test_field_entry_has_every_key`
  and `tests/test_walkthrough_field_graph.py::test_entry_records_retrieval` assert exact key sets (of the entry and
  of `retrieval`). The walkthrough API (`arp/walkthrough/view.py`) copies named keys only, and the frontend sums every
  value of `seconds` for the step total (`frontend/src/lib/walkthrough.ts:287`), so a sub-step put in `seconds`
  would be counted twice.
- `LocalFileDocumentSource._parse_and_identify` parses through `DocumentContentStore.get_or_parse(path,
  parser_version=..., parse=parse_file_to_text_with_pages)`. `ParsedContentCache.get_or_compute` already accepts a
  parse result of any length (`text, page_breaks, *rest = compute()`), stores `rest[0]` as table spans, and keys rows
  on `(content_key, parser_version)`. `parsed_content` is SQLite (`<store_dir>/content.db`); `ensure_columns` already
  adds a missing `table_spans` column at startup.
- PDFs go to the compute service first (`compute_client.parse_pdf(path, parser_version)` returns
  `(text, page_breaks, table_spans)` or None), else to Docling locally (`_extract_pdf_text_local`). Existing tests
  replace `parse_pdf`, `_extract_pdf_text_local`, `_docling_converter` and `local_files.parse_file_to_text_with_pages`
  with stand-ins that keep today's call shapes (some return 2-tuples).

## Goals

- A. For every field ranked for the walkthrough: each ranked candidate's rank in every ranking that ran (words,
  meaning, fused, rerank), up to a cap of 100, the uncapped count, whether it capped, and with small-to-big the
  piece that ranked each returned parent. The time of the evidence gate's call and of the page-image check, apart
  from the node they run in.
- B. For every document `LocalFileDocumentSource` parses into the content store: a parse report (parser, version,
  page count, short pages, OCR, tables found vs kept, parse seconds), stored with the parsed text and returned on
  every cache hit.

## Non-goals

No UI, no API or CLI change, no OpenAPI change. Per-page OCR, a garbage text-layer test, a parser interface or
EdgeParse, a parse timeout or worker process, the pdfium lock fix, reranking or matcher changes, calibration, xlsx
table spans, per-table cell counts (Docling item "cells found vs dropped" left out to keep the diff small), splitting
grounding from the checks inside `aggregate`, and a parse report from the compute service itself.

## Anti-goals (must stay true)

- The same chunks are picked in the same order; prompts, settings and defaults are unchanged; parsed text, page
  breaks and table spans are byte-identical; `parser_version()` is unchanged, so no parse cache is invalidated.
- `select_relevant_chunks` keeps its signature and return value, and every `explain` key it sets today keeps its
  name and meaning. The Research Desk wave 1 item calls it.
- `parse_file_to_text_with_pages`, `compute_client.parse_pdf`, `_extract_pdf_text_local`, `_docling_converter`,
  `_has_text_layer` and the compute server's `/parse` response keep their call shapes and return values.
- Existing tests are not changed, except `test_field_entry_has_every_key`, whose exact key set and equality dict gain
  `ranking` and `sub_seconds` (AC-24). The PR description lists that change.

## Design

### Slice A: retrieval trace and sub-step times

**New `explain` keys** (set by `select_relevant_chunks` whenever `explain` is given and it returns after building
its candidates; the existing early `return []` for no candidates still leaves `explain` untouched):

| Key | Type | Meaning |
|---|---|---|
| `ranks` | `dict[str, dict[str, int]]` | chunk id → its 1-based rank in each ranking that ran and held it. Rank keys: `bm25` (the BM25 or OpenSearch ranking after the `require_hit` filter and the small-to-big collapse to parents, the order `scores[...]["bm25"]` falls in), `vector` (the vector ranking after the collapse; equal to today's `scores[id]["vector_rank"]`), `fused` (the RRF ranking; hybrid only), `rerank` (the reranker pool sorted by rerank score, highest first, ties in pool order; only when the reranker scored, i.e. `explain["reranked"]` is True). A chunk with no rank key has no entry. |
| `ranked_count` | `int` | How many distinct chunk ids hold at least one rank, before the cap. |
| `ranks_capped` | `bool` | `len(ranks) < ranked_count`. |
| `pieces` | `dict[str, dict[str, str]]` | Only when this call had `parents` (small-to-big); absent otherwise, also when an earlier call on the same `explain` had set it. Returned parent id → `{"bm25": piece id, "vector": piece id}`: the piece that gave the parent its place in that ranking (the first of its pieces in that ranking), each key present only when that ranking ran and ranked a piece of that parent. |

**Cap.** `ranks` holds the first `TRACE_RANK_CAP = 100` chunks (a module constant in `select_evidence.py`) of the
order the cut was made from (the fused ranking for hybrid, the BM25 ranking for BM25 only, document order for
`unranked`) that hold a rank, plus every returned chunk not already among them. For method `none` (no query terms)
and `unranked` without a reranker: `ranks == {}`, `ranked_count == 0`, `ranks_capped` False.

**Trace entry.** `trace.field_entry` gains two keys:

- `ranking`: `None`, or `{"ranks", "ranked_count", "ranks_capped"}` copied from `explain`, plus `"pieces"` when
  `explain` has it. It is None when `retrieval` is None (nothing ranked, e.g. a tagged field) and for a grouped field
  (its passages come from several fields' rankings). Default None.
- `sub_seconds`: `dict[str, float]`, default `{}`. Time of a step that runs inside a graph node, already counted in
  that node's `seconds`, rounded to 2 decimals like `seconds`. `gate`: wall time of `gate.apply(...)` in
  `_gather_evidence`, present when a gate applied (a gate is open and the field is not grouped). `vision`: summed
  wall time of the `check_on_page` calls in `_aggregate`, present when at least one ran. Absent otherwise.

`seconds` is unchanged (still node names only). The walkthrough API keeps copying its named keys, so neither new key
reaches the API or the UI.

### Slice B: parse report

**New function** `arp.ingestion.local_files.parse_file_with_report(path) -> tuple[str, list[int], list, dict]`: calls
`parse_file_to_text_with_pages` through the module attribute (so stand-ins patched there still run), times it, and
returns `(text, page_breaks, table_spans, report)`; a 2-tuple result gives `table_spans == []`. `text`,
`page_breaks` and `table_spans` are exactly what `parse_file_to_text_with_pages(path)` returns.

**Report** (exactly these 8 keys):

| Key | Type | Value |
|---|---|---|
| `parser` | `str` | `"docling"` (PDF parsed locally, DOCX), `"compute"` (PDF parsed by the compute service), `"html"`, `"esef"`, `"text"` (.txt, .md), `"xlsx"` |
| `parser_version` | `str` | `parser_version()` |
| `page_count` | `int \| None` | `len(page_breaks)` for a PDF; None for every other format |
| `short_pages` | `list[int]` | 1-based page numbers, ascending, whose page text has fewer than 50 characters after `.strip()`. Page i's text is `text[page_breaks[i-1] : page_breaks[i] - 2]`, the last page's `text[page_breaks[-1]:]` (pages are joined with `"\n\n"`). `[]` with no page breaks |
| `ocr` | `bool \| None` | Local Docling PDF: True when OCR ran (`_has_text_layer` was False), else False. DOCX: False. Compute and other formats: None |
| `tables_found` | `int \| None` | `len(doc.tables)` of the Docling document (local PDF, DOCX). Compute and other formats: None |
| `tables_kept` | `int` | `len(table_spans)` |
| `parse_seconds` | `float` | Wall time of the parse call, ≥ 0, rounded to 2 decimals |

The compute path records what the client can see: `parser "compute"`, `ocr` and `tables_found` None, the rest from
the returned text, page breaks and spans, and `parse_seconds` the client's wall time for the call. Adding the
service-side facts needs a `/parse` response change and is left out.

**Storage.** `parsed_content` gains a nullable `parse_report TEXT` column (JSON), added to the `CREATE TABLE` and, for
an existing file, by `ensure_columns` (the `table_spans` precedent). `ParsedContent` gains `parse_report: dict | None =
None`. `get_or_compute` stores a 4th element of the parse result as the report; `store(...)` takes an optional
`parse_report`; `lookup` and `get_or_parse` return it. Rows written before this change, by EDGAR, or by a parse
callable that returns no report read back with `parse_report` None; they are not re-parsed. `get_full_text`,
`list_cached` and the `/documents/cache` endpoints are unchanged.

**Use.** `LocalFileDocumentSource._parse_and_identify` passes `parse=parse_file_with_report` when it has a content
store; without one it parses as today and records no report. Other callers of `parse_file_to_text_with_pages`
(reground, RFP, golden retrieval, page index, compute server, compute check) are unchanged.

### Risk and storage

Slice B changes a database schema (a column on `parsed_content`), which the steward table puts in `risk:high`: the
owner merges it. Storing without a schema change would mean a second store (a JSON file per content key) that nothing
else reads and that the cache's prune would not clean, so the column is the smaller and safer change. Slice A changes
no stored schema (the trace is a JSON file per run and company, and its readers ignore unknown keys): `risk:normal`.

OpenAPI export and `gen:api`: not touched. No response model changes (the compute server's `ParseResponse` and the
walkthrough view are unchanged).

## Defaults taken

1. Cap 100 per field, by the order the cut was made from, plus returned chunks; `ranks_capped` says when it capped.
2. Rank key names `bm25`, `vector`, `fused`, `rerank` (the brief's words, meaning, fused, rerank); `vector` rather
   than reusing `vector_rank` because the dict is already about ranks.
3. New data in two new top-level trace keys, not inside `retrieval` (an existing test asserts `retrieval`'s exact keys,
   and the API returns `retrieval` as is) and not in `seconds` (the UI sums it).
4. Only two sub-step times: `gate` and `vision`. Grounding and the code checks stay inside `aggregate`; splitting them
   means editing `build_extracted_fields`.
5. Grouped fields record no `ranking`.
6. Parse report stored in a new nullable column; slices split so A can auto-merge while B waits for the owner.
7. Report only for parses by `LocalFileDocumentSource` with a content store; no backfill of cached rows.
8. Short page threshold 50 characters (the same number `_has_text_layer` uses), measured on the parsed markdown.

## Notes for the builder

- Smallest possible diff, lowest complexity: no refactors, no new abstractions beyond `parse_file_with_report`, no
  unrelated cleanup. Additive fields only.
- `ocr` and `tables_found` are known only inside `_convert` / `_extract_pdf_text_local` / `_extract_docx_text`, which
  must keep their call shapes and return values. One way: a module-level `threading.local()` those functions fill and
  `parse_file_with_report` reads and clears (parses run in worker threads, one at a time under `_DOCLING_LOCK`).
- `field_evidence` may call `select_relevant_chunks` twice on one `explain`; the second call must leave `ranks`,
  `ranked_count`, `ranks_capped` and `pieces` as that call defines them (AC-11).
- Do not bump `_PARSER_LOGIC_VERSION`.

## Fixtures (for the acceptance rows)

All rows run without an LLM or network: stub models, small in-memory chunks or fake Docling documents.

- **F1**: as in `tests/test_select_evidence_explain.py`. 20 `DocumentChunk`s (doc_id `d1`, company `c1`, doc type
  `ANNUAL_REPORT_10K`); chunk i for i = 0..9 has text `" ".join(["capex"] * (11 - i)) + f" filler {i}"`, chunks 10..19
  `f"unrelated text {i}"`. Query `["capex"]`, `max_chunks=5`.
- **F150**: 160 chunks built the same way: chunk i for i = 0..149 `" ".join(["capex"] * (151 - i)) + f" filler {i}"`,
  chunks 150..159 `f"unrelated text {i}"`. Query `["capex"]`, `max_chunks=12`.
- **VS** (vectors): `select_evidence._vector_ranking` monkeypatched to `lambda candidates, q, store: [c.chunk_id for c
  in reversed(candidates)]`, called with `hybrid_retrieval_enabled=True` and any non-None `content_store`.
- **RR** (reranker): as the `scorer` fixture there: `rerank._unavailable = False`,
  `rerank.compute_client.models_configured` → False, `rerank._score` → `[float(i) for i in range(len(texts))]`
  (reverses the pool).
- **STB** (small-to-big): parents `P1`, `P2`, `P3` (any chunks). Pieces, in this candidate order: `a1` = `"capex
  filler filler filler filler filler"` (parent P1), `a2` = `"capex capex capex filler"` (P1), `b1` = `"capex filler
  filler filler"` (P2), `c1`..`c6` = `f"unrelated words {k}"` (P3). Called with `parents={piece id: parent}` for all
  9 pieces, query `["capex"]`, `max_chunks=5`.
- **DOCS**: one `SourceDocument` that `chunk_document(doc, keywords=["emissions"])` splits into at least 15 chunks,
  at least 14 of them holding "emissions" (as `_LONG_DOC` in `tests/test_walkthrough_field_graph.py`), a field with
  `seed_keywords=["emissions"]`, `extract_one_field` with the `fake_llm` fixture agreeing (extract + verify), a
  `trace_sink`, `settings=None` (BM25 only, no gate, no rerank) unless a row says otherwise.
- **GATE**: an `EvidenceGate` over a stub client set through `evidence_gate._current`, as
  `tests/test_evidence_gate.py::test_extractor_sees_only_kept_passages_and_trace_records_the_gate` does.
- **PDF3**: a fake Docling converter (as in `tests/test_local_files_pdf_pages.py`) monkeypatched over
  `local_files._docling_converter`, `local_files._has_text_layer` monkeypatched to return True unless a row says
  otherwise, `compute_client.parse_pdf` left unconfigured (returns None). Pages: `p1 = "A" * 80`, `p2 = "  short page  "`
  (14 characters: two spaces, `short page`, two spaces), `p3 = T1 + "\n\n" + "B" * 60` with `T1 = "| a | b |\n|---|---|\n| 1 | 2 |"`. `doc.tables` holds two fake tables
  (`export_to_markdown(doc)` → their markdown, `caption_text(doc)` → `""`, `data.table_cells` → `[]`): one exporting
  `T1`, one exporting `"| zz | yy |\n|---|---|\n| 9 | 9 |"`, which is not in the text. The file is any `*.pdf` (a
  reportlab PDF where intake must accept it).
- **PDF3-ok**: PDF3 with only the `T1` table.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | F1, BM25 only, `explain={}` | `select_relevant_chunks` returns | `explain["ranked_count"] == 10`, `explain["ranks_capped"] is False`, and `explain["ranks"] == {F1[i].chunk_id: {"bm25": i + 1} for i in range(10)}` (so the ids ranked 9 and 10, beyond the 3 near misses, are kept) | holdout |
| AC-2 | F1 + VS | Returns | `ranked_count == 20`, every one of the 20 ids is a key of `ranks`, each entry has int `vector` and `fused`, exactly the 10 "capex" chunks also have `bm25`; for each returned chunk `ranks[id]["vector"] == explain["scores"][id]["vector_rank"]`; the returned chunks' `fused` values are `[1, 2, 3, 4, 5]` in return order | holdout |
| AC-3 | F1 + RR, `rerank_candidates=10` | Returns | Exactly `F1[0..9]` have a `rerank` key; their `rerank` values are the set `{1, …, 10}`; the returned chunks' `rerank` values are `[1, 2, 3, 4, 5]` in return order | holdout |
| AC-4 | F150, BM25 only | Returns | `ranked_count == 150`, `ranks_capped is True`, `len(ranks) == 100`, `set(ranks) == {F150[i].chunk_id for i in range(100)}` | holdout |
| AC-5 | F150 + VS + RR, `rerank_candidates=120` | Returns | `ranked_count == 160`, `ranks_capped is True`, every returned chunk id is a key of `ranks`, `len(ranks) == 112` (the first 100 of the fused order plus the 12 returned, which RR takes from fused ranks 109 to 120) | holdout |
| AC-6 | F1 with `query_terms=[]` | Returns | `ranks == {}`, `ranked_count == 0`, `ranks_capped is False`, `"pieces" not in explain` | holdout |
| AC-7 | The 10 non-"capex" chunks of F1, `fallback_to_all=True`, BM25 only, no reranker | Returns | `explain["method"] == "unranked"`, `ranks == {}`, `ranked_count == 0` | holdout |
| AC-8 | STB, BM25 only | Returns | Returns `[P1, P2]`; `ranks == {P1.chunk_id: {"bm25": 1}, P2.chunk_id: {"bm25": 2}}`; `explain["pieces"] == {P1.chunk_id: {"bm25": a2.chunk_id}, P2.chunk_id: {"bm25": b1.chunk_id}}` | holdout |
| AC-9 | STB + VS | Returns | Returns `[P1, P2, P3]`; `explain["pieces"] == {P1.chunk_id: {"bm25": a2.chunk_id, "vector": a2.chunk_id}, P2.chunk_id: {"bm25": b1.chunk_id, "vector": b1.chunk_id}, P3.chunk_id: {"vector": c6.chunk_id}}` | holdout |
| AC-10 | F1, BM25 only | Returns | `"pieces" not in explain` | holdout |
| AC-11 | One `explain` dict used first for the STB call, then for an F1 call without `parents` | Second call returns | `"pieces" not in explain`, and `ranks`, `ranked_count`, `ranks_capped` equal those of the F1 call on a fresh dict (AC-1) | holdout |
| AC-12 | Each of F1, F1 + VS, F1 + RR (`rerank_candidates=10`), F150 + VS + RR (`rerank_candidates=120`), STB, STB + VS | Called with `explain={}` and again with `explain` omitted | The two calls return the same chunk ids in the same order | holdout |
| AC-13 | DOCS | Field extracted | `entry["ranking"]` has exactly the keys `ranks`, `ranked_count`, `ranks_capped`; `ranks_capped is False`; `ranked_count == len(ranks) >= len(passages) + 4`; for each passage at 1-based position i, `ranks[f"chk_{doc_id}_{char_start}_{char_end}"] == {"bm25": i}` | holdout |
| AC-14 | DOCS with `Settings(small_to_big_enabled=True, hybrid_retrieval_enabled=False)` | Field extracted | `entry["ranking"]` also has `pieces`; `set(pieces)` equals the passage ids (`chk_{doc_id}_{char_start}_{char_end}`); each value is `{"bm25": <id starting with f"chk_{doc_id}_">}` | holdout |
| AC-15 | A field extracted in a group (`extraction_group_size=2`, as `tests/test_walkthrough_pipeline.py::_grouped` does), and separately a field taken from tagged XBRL facts (`skipped == "tagged"`) | Fields extracted | Both entries have `ranking is None` | holdout |
| AC-16 | A field entry with `ranking` and `sub_seconds` written by `write_trace`, and the same entry with those two keys deleted | `GET` the walkthrough for each | The two response bodies are equal (neither key reaches the API) | holdout |
| AC-17 | DOCS + GATE | Field extracted | `entry["sub_seconds"]` has exactly the key `gate`, a float ≥ 0 with at most 2 decimals and `<= entry["seconds"]["gather_evidence"]`; `entry["seconds"]` keys are exactly `try_tagged`, `gather_evidence`, `extract`, `verify`, `aggregate` | holdout |
| AC-18 | DOCS, no gate, vision fallback off | Field extracted | `entry["sub_seconds"] == {}` | holdout |
| AC-19 | `Settings(hybrid_retrieval_enabled=False, vision_fallback_enabled=True)`, a value that does not ground and a stub `PageReading`, as `tests/test_walkthrough_field_graph.py::test_vision_answer_recorded` | Field extracted | `entry["sub_seconds"]` has `vision`, a float ≥ 0 with at most 2 decimals and `<= entry["seconds"]["aggregate"]`; no `gate` key | holdout |
| AC-20 | DOCS, and DOCS + GATE | Field extracted with a `trace_sink` and again without | The fake LLM receives the same prompts in the same order, and the extracted fields' `value`, `value_state`, `citations` and `review_reasons` are equal | holdout |
| AC-21 | `trace.field_entry("f1")` | Built | Its keys are exactly the 14 of main plus `ranking` and `sub_seconds`; `ranking is None`, `sub_seconds == {}`; the other 14 values are main's defaults | holdout |
| AC-31 | PDF3 | `parse_file_with_report(path)` | Returns 4 items; `report` has exactly the 8 keys; `report` without `parse_seconds` equals `{"parser": "docling", "parser_version": parser_version(), "page_count": 3, "short_pages": [2], "ocr": False, "tables_found": 2, "tables_kept": 1}`; `parse_seconds` is a float ≥ 0 with at most 2 decimals | holdout |
| AC-32 | PDF3-ok | Same | `report["tables_found"] == report["tables_kept"] == 1` | holdout |
| AC-33 | PDF3 with `_has_text_layer` returning False | Same | `report["ocr"] is True` | holdout |
| AC-34 | PDF3 | `parse_file_with_report(path)[:3]` and `parse_file_to_text_with_pages(path)` | Equal; `text == "\n\n".join([p1, p2, p3])`, `page_breaks == [0, 82, 98]`, and the one span covers `T1` (`text[span.char_start:span.char_end] == T1`) | holdout |
| AC-35 | `compute_client.parse_pdf` monkeypatched to `lambda p, v: ("A" * 80 + "\n\ntiny", [0, 82], [TableSpan(table_id="table_0", char_start=0, char_end=10)])`, any `*.pdf` path | `parse_file_with_report(path)` | First 3 items equal the stand-in's tuple; `report` without `parse_seconds` equals `{"parser": "compute", "parser_version": parser_version(), "page_count": 2, "short_pages": [2], "ocr": None, "tables_found": None, "tables_kept": 1}` | holdout |
| AC-36 | A `.txt` file and an `.html` file | `parse_file_with_report(path)` | `report` without `parse_seconds` equals `{"parser": "text" / "html", "parser_version": parser_version(), "page_count": None, "short_pages": [], "ocr": None, "tables_found": None, "tables_kept": 0}` | holdout |
| AC-37 | `DocumentContentStore(tmp, dsn=pg_dsn())`, PDF3 | `store.get_or_parse(path, parser_version=parser_version(), parse=parse_file_with_report)` | The returned `ParsedContent.parse_report` is a dict with AC-31's values; `store.lookup(store.content_key_for_file(path), parser_version()).parse_report` equals it exactly (same `parse_seconds`) | holdout |
| AC-38 | As AC-37, then a second `get_or_parse` with a `parse` callable that raises if called | Second call | The callable is not called; `parse_report` equals the first call's exactly | holdout |
| AC-39 | A store; PDF3 parsed with `parse=parse_file_to_text_with_pages`, and a row written by `store.store(...)` without a report | Read back with `lookup` | `parse_report is None` for both; text, page breaks and spans equal what was parsed or stored | holdout |
| AC-40 | `<store_dir>/content.db` created with the legacy DDL below, holding one row for a file's `content_key` (sha256 of its bytes) and the current `parser_version()` | `DocumentContentStore(store_dir, dsn=pg_dsn())`, then `get_or_parse` of that file with a `parse` callable that raises if called | The store opens; the callable is not called; `full_text`, `page_breaks`, `table_spans` equal the inserted values; `parse_report is None` | holdout |
| AC-41 | PDF3's fake converter, and a reportlab PDF (so intake accepts it) at `docs/acme/<DocType.ANNUAL_REPORT_10K.value>/report.pdf`, `LocalFileDocumentSource(docs, content_store=store)` | `fetch(CompanyRef(company_id="acme", name="Acme"))` | The returned document's `full_text == "\n\n".join([p1, p2, p3])`; `store.lookup(store.content_key_for_file(path), parser_version()).parse_report["tables_found"] == 2` | holdout |
| AC-42 | This branch | `parser_version()` | Starts with `"logic=3|"` (no cache invalidated) | holdout |
| AC-44 | Any `*.docx` path; PDF3's fake Docling converter monkeypatched over `local_files._docling_converter`, its document's `export_to_markdown()` (called with no `page_no`) returning `"Intro\n\n" + T1` and `doc.tables` holding PDF3's two tables | `parse_file_with_report(path)` | `report` without `parse_seconds` equals `{"parser": "docling", "parser_version": parser_version(), "page_count": None, "short_pages": [], "ocr": False, "tables_found": 2, "tables_kept": 1}` | holdout |
| AC-43 | This branch | From `backend/`, `pytest tests/test_select_evidence_explain.py tests/test_walkthrough_field_graph.py tests/test_walkthrough_api.py tests/test_evidence_gate.py tests/test_walkthrough_pipeline.py tests/test_local_files_pdf_pages.py tests/test_local_files_cached.py tests/test_local_files_docx.py tests/test_compute_parse_hook.py tests/test_compute_client.py tests/test_compute_cli.py tests/test_document_content_store.py tests/test_doc_identity.py tests/test_capture.py` | Exits 0 | holdout |
| AC-45 | The PR | Its diff against `main` | Under `backend/tests/`, no existing file changes except `tests/test_walkthrough_trace.py`, and there only `test_field_entry_has_every_key` (its key set and equality dict gain `ranking` and `sub_seconds`); the PR description lists it | unit |

Must not change: picked chunks and their order (AC-12), prompts and extracted results (AC-20), parsed text, page
breaks and spans (AC-34, AC-35, AC-41), `parser_version()` (AC-42), existing `explain` keys and every existing test
except `test_field_entry_has_every_key` (AC-21, AC-43, AC-45), the walkthrough API response (AC-16). Superseded rows of
earlier specs: none. The rows of earlier specs that assert `field_entry`'s full key set (why-this-evidence AC-14,
step-timing AC-1, evidence-gate AC-35) are `unit` rows; the unit test `test_field_entry_has_every_key` is the only
one extended.

Legacy DDL for AC-40 (the `parsed_content` table as on main `7e2e955`):

```sql
CREATE TABLE parsed_content (
    id INTEGER PRIMARY KEY, content_key TEXT NOT NULL, key_kind TEXT NOT NULL, parser_version TEXT NOT NULL,
    source_suffix TEXT NOT NULL, full_text TEXT NOT NULL, page_breaks TEXT NOT NULL DEFAULT '[]',
    table_spans TEXT NOT NULL DEFAULT '[]', text_sha256 TEXT NOT NULL, char_len INTEGER NOT NULL,
    byte_size INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX ix_parsed_content_key ON parsed_content (content_key, parser_version);
```

## Slices

Two PRs, each with `Spec: extraction-trace-parse-report` and its `Rows:` line, every test change listed. They touch
different files and can merge in either order.

| Slice | Risk | Size | PR contents | Rows |
|---|---|---|---|---|
| A | `risk:normal` | S | `arp/retrieval/select_evidence.py` (ranks, cap, pieces), `arp/walkthrough/trace.py` (`ranking`, `sub_seconds`), `arp/extraction/field_graph.py` (gate and vision times, pass `ranking`), `tests/test_walkthrough_trace.py` key set, new tests | AC-1 to AC-21, AC-43, AC-45 |
| B | `risk:high` | S | `arp/ingestion/local_files.py` (`parse_file_with_report`, Docling facts, use in `_parse_and_identify`), `arp/storage/parsed_content_cache.py` (column, `ensure_columns`, `ParsedContent.parse_report`, store/lookup), new tests | AC-31 to AC-45 |
