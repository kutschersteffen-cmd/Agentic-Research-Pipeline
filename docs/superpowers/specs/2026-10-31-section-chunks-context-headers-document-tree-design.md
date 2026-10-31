# Section chunks, context headers and the document tree

Spec slug: `section-chunks-context-headers-document-tree`. Items 2a, 5b and 5c of the RAG improvement plan
(https://claude.ai/artifact/RnMhVmhQNmJPwY8UCaY38t). Research: `docs/RAG_SYSTEMS_LANDSCAPE_RESEARCH.md`
(§3.15 and Appendix A on PageIndex; the Contextual Retrieval rows).

**Depends on:** table-aware extraction (#282, for `ingestion/outline.py`, `heading_path`, `DocumentChunk.page`
and `section_tags`) and the retrieval gold set (spec `retrieval-gold-set-and-question-queries`, for the
`Retrieval recall` gate). Implementation starts after both are on `main`.

## Why

1. **Chunks cross sections.** `ingestion/parsing.py` cuts the whole text into ~3,500-character windows; a
   chunk's `section` is only the last heading before it, so one chunk often holds the end of one section and the
   start of the next. BM25 statistics and embeddings then mix two topics, and section-tag routing is inexact.
2. **Chunks are indexed without context.** A passage that says "we cut it by 12% against 2019" is indexed
   without the company, year or section it belongs to. Anthropic's Contextual Retrieval measured 35% fewer
   retrieval misses from contextual embeddings and 49% with contextual BM25 added (vendor measurement).
3. **There is no reusable map of a document.** Section picking (#6) and LLM-written context (2b) both need,
   for each section: title, page range, a short summary and key terms. Building that per field or per run
   would repeat the same LLM work hundreds of times; it belongs at ingest, once per document version.

## What changes

All three parts sit behind settings that default to **off**. Each is switched on by a separate one-line PR
once the `Retrieval recall` gate shows recall@12 on the PR ≥ `main`.

### Part A (5b): section-bounded chunking — `section_chunking_enabled: bool = False`

1. When on, `_compute_spans` first splits `full_text` at the outline's heading offsets (`outline(doc)`), then
   applies today's sentence-aware split (`chunk_chars`, `overlap_chars`) inside each section. Overlap never
   reaches across a heading.
2. **Merging short sections:** a section shorter than `section_min_chars` (default 800) is joined with the
   section(s) that follow it, one at a time, while the joined span is still < `section_min_chars` and the next
   heading is at the same or a deeper level. Joining stops before a shallower heading. A joined chunk's
   `section` is its first heading.
3. **Unchanged:** whole-table passages; the coverage guarantee (`_fill_coverage_gaps`: every character is in at
   least one chunk); documents with fewer than 2 headings (they chunk exactly as today); `chunk_id` format.
4. `_SPAN_ALGO_VERSION` goes up by one, so cached spans from the old algorithm are not reused. No re-parse.

### Part B (2a): deterministic context headers — `context_headers_enabled: bool = False`

1. New public function `arp.retrieval.index_text.index_text(chunk, doc, settings) -> str`. When the setting is
   on it returns the chunk's **index text**; when off it returns `chunk.text`. When on, each chunk's index text is: a one-line header, a newline, then the chunk text. The header is
   `" · ".join` of the non-empty values of: document `title`, `fiscal_period`, and the chunk's heading path
   joined with `" › "`. Example: `Siemens Annual Report 2025 · FY2025 · Sustainability › Climate › Scope 3`.
2. **Table passages** (`table_id` set) get a second header line before the chunk text:
   `"Table: " + " · ".join` of the non-empty values of the table's `caption`, `unit`, and its `column_headers`
   joined with `" | "`. Example: `Table: GHG emissions · tCO2e · Scope 1 | Scope 2 | Scope 3 | 2024 | 2025`.
   This lets BM25 and embeddings find a table by what it measures, not by its numbers.
3. BM25 (in-memory and OpenSearch) and the embedding ranking index the **index text**. Everything else uses
   `chunk.text` unchanged: the extractor's evidence block, `grounding.py`, citations, offsets, the UI.
4. Embedding cache entries are keyed by chunk id **and** a hash of the exact text embedded, so switching headers on
   or off never reuses a vector computed for the other text.
5. A quote that matches only header text is not grounded (it never appears in `full_text`, so this holds by
   construction; a row checks it).

### Part C (5c): the document tree — `doc_tree_enabled: bool = False`

1. **Built once per document version**, keyed by `(content_key, parser_version, TREE_VERSION)`, stored in a new
   `doc_tree` table next to `parsed_content` in the parsed-content cache. `TREE_VERSION` is a module constant in
   new `arp/ingestion/doc_tree.py`, starting at 1. The tree is built when a document is fetched
   (`DocumentSourceRegistry.fetch_all`, so also `arp documents warm`) with `doc_tree_enabled` on; a later fetch,
   run, field or schema reads the stored tree. Public seam for tests: `build_doc_tree(doc, settings) -> DocTree`,
   which reads or builds and stores the tree.
2. **Structure (no LLM):** an unnamed root (`node_id` `"root"`, never printed, no summary, never sent to the model) whose children are the top-level
   nodes. One node per outline heading, nested by heading level, plus one leaf per whole table
   (child of the section it sits in). Each node: `node_id`, `title`, `heading_path`, `level`, `page_start`,
   `page_end`, `char_start`, `char_end`, `table_id` (tables only), `summary`, `key_terms`, `children`.
   A document with fewer than 3 headings gets page-window nodes of 5 pages each instead (titles `Pages 1–5`, …).
3. **Summaries and key terms (LLM):** `summary` is 2–3 sentences; `key_terms` are 5–10 terms (metric names,
   years, scope words, named programmes; German documents get German terms plus their English forms).
   Built bottom-up: leaves from their text (first `tree_leaf_chars`, default 6,000 characters), parents from
   their children's summaries. Up to 20 nodes per model call, on `tree_summary_model` (default the configured
   Haiku model). The call's output model is `TreeSummaries` = `{"nodes": [{"node_id", "summary", "key_terms"}]}`,
   so in tests the answer is the stand-in file `model/TreeSummaries.json` (`{"output": {...}}`; every call gets the
   same file, and a call takes the entries whose `node_id` it asked for).
4. **Failure:** a node whose call fails, or whose `node_id` is missing from the answer, keeps `summary: null, key_terms: []`; the
   tree is still stored and marked `incomplete: true`; the next build of the same key retries only those nodes.
5. **Never evidence:** nothing in the tree is passed to grounding or shown as a citation.
6. **CLI:** `arp documents tree <doc_id>` prints the stored tree (exit 1 with `No tree stored for <doc_id>.` if
   there is none), the tree, one node per line:
   `<indent><title> (p.<start>–<end>) [<n> terms]`, and `--json` prints the stored JSON.
7. **Cost record:** each model call is logged like other model calls (with stand-ins: one `calls.jsonl` line with
   `"name": "TreeSummaries"`).

### Out of scope

- Using the tree for context (plan item 2b) or for section picking (#6): separate specs, once this is measured.
- Turning any of the three settings on by default (separate PRs, gated on recall).
- OCR or parser changes.

## Acceptance

Conventions:
- Test documents are `SourceDocument`s built in the test: markdown `full_text` with `#`/`##`/`###` heading lines,
  `page_breaks` set explicitly (offsets where pages 2, 3, … start), `table_spans` where a row says so.
- Seams named in this spec and nothing else: `chunk_document`, `index_text`, `build_doc_tree`, `TREE_VERSION`
  (monkeypatched to raise it), the `embed_texts` stand-in from the first retrieval spec, `ARP_STANDINS_DIR`.
- A section's length counts from its heading line's first character to the next heading's.
- `chunk_chars`/`overlap_chars` are 3,500/300 and `section_min_chars` 800 unless a row says otherwise.
- "Snapshot from `main`": span lists or texts recorded by the test-writer from `main` for the fixture documents
  `chunking_a` (no headings), `chunking_b` (12 headings, 3 levels) and `chunking_c` (headings and 2 tables), and
  committed in holdout.

| ID     | Given | When | Then (observable, exact) | Checked by |
|--------|-------|------|--------------------------|------------|
| AC-1   | `## A` (2,000 chars of body) then `## B` (2,000 chars), `section_chunking_enabled` on | `chunk_document` | No chunk contains the `## B` line's offset unless it starts exactly there | holdout |
| AC-2   | Same | Same | Chunks starting before `## B` have `section == "A"`; chunks starting at or after it have `section == "B"` | holdout |
| AC-3   | `## A` with 9,000 chars of body, then `## B`, setting on | `chunk_document` | Section A yields ≥ 3 chunks, each ≤ 3,500 chars, all inside `[offset of ## A, offset of ## B)` | holdout |
| AC-4   | `## A` (200 chars), `## B` (300 chars), `# C` (2,000 chars), setting on | `chunk_document` | One chunk is exactly `[0, offset of # C)` with `section == "A"` | holdout |
| AC-4b  | `## A` (200), `### A.1` (700), `## B` (2,000), setting on | `chunk_document` | One chunk is exactly `[0, offset of ## B)` with `section == "A"` | holdout |
| AC-4c  | `## A` (200), `## B` (2,000), setting on | `chunk_document` | One chunk is exactly `[0, len(full_text))` with `section == "A"` (A joined with B, and A+B fits one chunk) | holdout |
| AC-5   | `## A` (200 chars) then `# Z` (2,000 chars), setting on | `chunk_document` | A's chunk is exactly `[0, offset of # Z)` | holdout |
| AC-6   | Fixtures `chunking_a`, `_b`, `_c`, setting on | `chunk_document` | Every offset 0…len−1 lies in at least one chunk | holdout |
| AC-7   | `chunking_a` (no headings) | `chunk_document` with the setting on | Spans equal the `main` snapshot | holdout |
| AC-8   | `chunking_a`, `_b`, `_c`, setting off | `chunk_document` | Spans equal the `main` snapshots | holdout |
| AC-9   | `chunking_c`, setting on | `chunk_document` | Whole-table passages (`table_id` set) equal those with the setting off | holdout |
| AC-9b  | `chunking_b`, setting on | `chunk_document` | Every `chunk_id` matches `^chk_<doc_id>_\d+_\d+$` (today's format, `ingestion/parsing.py` on `main`) | holdout |
| AC-9c  | Spans for `chunking_b` computed by `chunk_document` with the setting off, still in the in-process span cache | setting switched on, `chunk_document` again | Spans equal those `chunk_document` returns with the setting on after `get_span_cache().clear()` | holdout |
| AC-10  | `title="Siemens Annual Report 2025"`, `fiscal_period="FY2025"`, chunk under `# Sustainability` › `## Scope 3`, `context_headers_enabled` on | `index_text` | Returns `Siemens Annual Report 2025 · FY2025 · Sustainability › Scope 3\n` + `chunk.text` | holdout |
| AC-11  | Same, `fiscal_period=None` | `index_text` | Returns `Siemens Annual Report 2025 · Sustainability › Scope 3\n` + `chunk.text` | holdout |
| AC-11b | Setting off | `index_text` | Returns `chunk.text` | holdout |
| AC-11c | Headers on, a table passage under `## Emissions` whose table has `caption="GHG emissions"`, `unit="tCO2e"`, `column_headers=["Scope 1","Scope 2"]`, doc title `R` and no `fiscal_period` | `index_text` | Returns `R · Emissions\nTable: GHG emissions · tCO2e · Scope 1 | Scope 2\n` + `chunk.text` | holdout |
| AC-11d | Same table with `caption=None`, `unit=None` | `index_text` | The second line is `Table: Scope 1 | Scope 2` | holdout |
| AC-11e | Headers on, BM25 only, 5 passages; the table passage's text holds only numbers, and the query terms are `["GHG emissions"]` | evidence selected | The table passage is returned at rank 0 | holdout |
| AC-12  | 5 chunks, only one under heading `## Scope 3` and none containing "Scope 3" in its text, hybrid off (`ARP_HYBRID_RETRIEVAL_ENABLED=false`), in-memory BM25, query terms `["Scope 3"]`, `require_hit` on | evidence selected with headers on | That chunk is returned at rank 0 | holdout |
| AC-12b | Same, headers off | evidence selected | That chunk is not returned | holdout |
| AC-12c | Headers on, `retrieval_backend=opensearch` (test container) | chunks indexed | The indexed document's `text` field equals `index_text(chunk)` | holdout |
| AC-13  | Headers on | evidence handed to the extractor | Each passage's text equals `chunk.text`; no header line appears in the prompt | holdout |
| AC-14  | Headers on, a citation whose quote is `Sustainability › Scope 3` (header-only text) | grounding | `grounded` is `false` | holdout |
| AC-15  | Hybrid and headers on, recording `embed_texts` stand-in | evidence selected twice for the same field | No chunk's index text is passed to `embed_texts` in the second selection | holdout |
| AC-15b | Same chunks embedded once with headers off | headers switched on, evidence selected | Each chunk's index text is embedded once | holdout |
| AC-16  | `chunking_b`, headers off, hybrid on | evidence selected | Chunk texts passed to `embed_texts` equal the `main` snapshot | holdout |
| AC-17  | `# A` (p.1), `## A1` (p.2) containing one table, `## A2` (p.3), `# B` (p.4–5); stand-in answers for every node | `build_doc_tree` | Root children `[A, B]`; A's children `[A1, A2]`; A1 has one child with `table_id` set | holdout |
| AC-18  | Same | Same | A: `page_start` 1, `page_end` 3; A1: 2–2; B: 4–5; each child's char range lies inside its parent's | holdout |
| AC-19  | Same | Same | Each node's `summary` and `key_terms` equal the stand-in entry with its `node_id` | holdout |
| AC-20  | That tree already stored | `build_doc_tree` again | No `TreeSummaries` line is added to `calls.jsonl` | holdout |
| AC-21  | Same, `TREE_VERSION` monkeypatched to 2 | `build_doc_tree` | `TreeSummaries` calls are logged again; the stored tree's `tree_version` is 2 | holdout |
| AC-22  | Stand-in answer without an entry for A2 | `build_doc_tree` | A2 has `summary: null`, `key_terms: []`; `incomplete: true`; every other node has its answer | holdout |
| AC-23  | The stored tree from AC-22, stand-in now including A2 | `build_doc_tree` | One `TreeSummaries` call is logged and its prompt names only A2's `node_id`; `incomplete` is `false` | holdout |
| AC-24  | 2 headings, `page_breaks` giving 12 pages | `build_doc_tree` | Root children are 3 nodes titled `Pages 1–5`, `Pages 6–10`, `Pages 11–12` | holdout |
| AC-25  | 45 leaf sections under one `#` heading | `build_doc_tree` | Exactly 3 `TreeSummaries` calls carry leaves (20, 20, 5 node_ids), then 1 call for the parent | holdout |
| AC-26  | The tree from AC-17 and an extraction run on that document with stand-in answers | run finishes | No `summary` or `key_terms` text appears in any citation `quote` or evidence passage of the run's results | holdout |
| AC-27  | The stored tree from AC-17 | `arp documents tree <doc_id>` | Line 1 is `A (p.1–3) [<n> terms]`; line 2 is `  A1 (p.2–2) [<m> terms]` | holdout |
| AC-27b | No stored tree | `arp documents tree <doc_id>` | Exit 1; stderr `No tree stored for <doc_id>.` | holdout |
| AC-28  | `doc_tree_enabled` off | a document is fetched through the registry | No `doc_tree` row is written and no `TreeSummaries` call is logged | holdout |
| AC-28b | `doc_tree_enabled` on, local documents dir with one document | `arp documents warm --universe <file>` | `arp documents tree <doc_id>` then exits 0 | holdout |
| AC-31  | The bundled extraction golden set, all three settings off | `arp golden-set run` | Every case passes, as on `main` | golden |

Must not change: chunking with the setting off (AC-8), retrieval inputs with headers off (AC-11b, AC-16), evidence
text and grounding (AC-13, AC-14), ingest without the tree (AC-28), chunk ids (AC-9b), the extraction golden set (AC-31).

PR checklist (not ACs): the PR description lists `main`'s and the PR's recall@5 and recall@12 on the retrieval gold
set for each of `section_chunking_enabled` and `context_headers_enabled` switched on alone, and the tree build's
model calls and tokens for one real report of about 300 pages.
