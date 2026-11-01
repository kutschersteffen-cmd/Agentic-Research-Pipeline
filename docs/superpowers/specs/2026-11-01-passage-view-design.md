# Passage view (how a document was cut into passages)

Status: draft, awaiting owner approval.

## Goal

Show a reviewer the passages retrieval searches, next to the original, so a bad parse is visible before it becomes a
wrong or missing value: text run together, a table split mid-row, a page with no text, a section heading not picked
up. Today Data Library → Parsed documents shows only the raw cached text (`ParsedDocumentsView` in
`frontend/src/pages/DataLibrary.tsx`); passages exist only in memory (`chunk_document`, `ingestion/parsing.py`).

Idea taken from RAGFlow's chunk view (`web/src/pages/chunk/parsed-result`): chunk list beside the original pages.
Not copied: RAGFlow's per-chunk on/off switch (excluding evidence would need review, a reason and the audit log;
its own spec if wanted).

## Design

1. **API.** `GET /api/documents/cache/{row_id}/passages` returns, for the cached text of that row, the passages
   `chunk_document` produces with default settings (`DEFAULT_CHUNK_CHARS`, `DEFAULT_OVERLAP_CHARS`) and the row's
   registered `doc_type` (`annual_report_10k` when the row has no registered document):
   ```
   { "chunk_chars": 3500, "overlap_chars": 300, "page_count": n | null,
     "passages": [ { "index": 1, "char_start": 0, "char_end": 3412, "chars": 3412,
                     "page_start": 1 | null, "page_end": 2 | null, "section": "..." | null, "speaker": "..." | null } ],
     "summary": { "passages": 48, "short": 2, "no_section": 5, "empty_pages": [7, 8] } }
   ```
   - `page_start` / `page_end`: 1-based PDF pages from `page_breaks` (`bisect_right(page_breaks, offset) + 1`, with
     `char_end - 1` for the end); null when the text has no `page_breaks`. `page_count` = `len(page_breaks) + 1`, or null.
   - `short`: passages under 200 characters. `no_section`: passages whose `section` is null (always 0 for
     transcripts, which use `speaker`). `empty_pages`: pages whose text, stripped, is empty.
   - 404 `Cached document not found` when the row does not exist (same as `/cache/{row_id}`).
   Response model added, so the OpenAPI export and `frontend/src/api/schema.gen.ts` are regenerated and the call gets
   a line in `frontend/src/api/contract.ts`.
2. **UI.** In the expanded row of Parsed documents, a two-option switch above the text: `Text` (today's view, the
   default) and `Passages (n)`. Passages shows:
   - one summary line: `48 passages · 2 under 200 characters · 5 without a section · pages 7, 8 have no text`,
     dropping each part that is zero or empty (`48 passages` alone when all are);
   - a list, one row per passage: `#{index} · p. {page_start}–{page_end} · {section or "no section"} · {chars} chars`
     (`p. 3` when start = end; page part absent without pages; speaker in place of section for transcripts);
     a row under 200 characters carries a `short` chip;
   - clicking a row opens its text below it (whitespace kept, scrollable, max 16rem), and for a registered PDF a
     link `Open page {page_start}` to the original at that page (`documentRawUrl(...)#page=N`, as citations do).
     One row open at a time.
   Signal Room rules: mono for numbers and labels, ink only; the `short` chip is a neutral outlined chip (it is a
   hint, not a person-must-act signal and not a run status).
3. **No storage.** Passages are computed on request from the cached text; nothing new is stored.

## Out of scope

Turning passages on or off, editing passages, page images with drawn boxes, table detection markers, other chunkers
(table-aware extraction's own splitter), changing how documents are chunked.

## Acceptance

Fixtures: **T1** = a cached text of 3 PDF pages (`page_breaks` given), 9,000 characters, a markdown heading `# Risk`
at offset 0 and page 3 empty after stripping. **T2** = the same text without `page_breaks`. **T3** = an
`earnings_transcript` cached text of alternating short `Jane Doe:` / `John Roe:` turns. A passage's speaker is what
`chunk_document` reports: the last speaker line within 400 characters before its `char_start` (`detect_speaker`), so
the first passage has none. (Amended during implementation: the spec first said "in effect at `char_start`", which
the unchanged chunker does not do.)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | T1 cached | `GET /api/documents/cache/{id}/passages` | 200; `passages` has the same count and `char_start`/`char_end` as `chunk_document` on the same text and doc type | unit |
| AC-2 | T1 | Same | `index` runs 1..n in order and `chars == char_end - char_start` for every passage | unit |
| AC-3 | T1 | Same | `chunk_chars == 3500`, `overlap_chars == 300` | unit |
| AC-4 | T1 | Same | Every passage's `page_start`/`page_end` equal `bisect_right(page_breaks, char_start)+1` / `bisect_right(page_breaks, char_end-1)+1`; `page_count == 3` | unit |
| AC-5 | T1 | Same | `summary.empty_pages == [3]` | unit |
| AC-6 | T1 | Same | The first passage's `section == "Risk"` | unit |
| AC-7 | T1 | Same | `summary.short` equals the number of passages with `chars < 200`; `summary.no_section` equals the number with `section` null | unit |
| AC-8 | T2 | Same | Every passage has `page_start` and `page_end` null; `page_count` is null; `summary.empty_pages == []` | unit |
| AC-9 | T3 (registered as `earnings_transcript`) | Same | Every passage's `speaker` equals `detect_speaker(text, char_start)`; passage 2's is `Jane Doe` or `John Roe` | unit |
| AC-26 | As AC-9 | Same | Every passage has `section` null | unit |
| AC-27 | As AC-9 | Same | `summary.no_section == 0` | unit |
| AC-10 | Cached row with no registered document | Same | 200; `char_start`/`char_end` equal `chunk_document` on that text with `doc_type=annual_report_10k` and default settings | unit |
| AC-11 | Row id that does not exist | Same | 404 with detail `Cached document not found` | unit |
| AC-12 | API contract | `scripts/export_openapi.py`, `npm run gen:api` | Generated files are committed and up to date (CI's existing contract check passes) | unit |
| AC-13 | e2e stack with a parsed document (the evaluator uploads one PDF of ≥ 3 pages through Data Hub if none is cached) | Reviewer opens Data Library → Parsed documents and expands that row | A switch shows `Text` (selected) and `Passages (n)` with n = the API's `summary.passages` | evaluator |
| AC-14 | As AC-13 | Reviewer clicks `Passages (n)` | A summary line starting `{n} passages` appears, with only the non-zero parts listed in the order in Design 2 | evaluator |
| AC-15 | As AC-14 | Same | One row per passage reads `#{index} · p. {pages} · {section or "no section"} · {chars} chars`, matching the API | evaluator |
| AC-16 | As AC-14, the API response has at least one passage with `chars < 200` (the evaluator's upload ends with a page of under 200 characters) | Same | Exactly the passages with `chars < 200` show a `short` chip, and the chip has no fill and no `--hi` colour | evaluator |
| AC-17 | As AC-14 | Reviewer clicks passage #2 | Its text appears under it and equals the cached text from `char_start` to `char_end` | evaluator |
| AC-18 | As AC-17, registered PDF | Same | A link reads `Open page {page_start}` and its href equals the document's raw URL (`api.documentRawUrl(...)`) followed by `#page={page_start}` | evaluator |
| AC-19 | As AC-17 | Reviewer clicks passage #3 | #3's text opens and #2's closes | evaluator |
| AC-20 | Frontend helper, summary counts `{passages: 48, short: 0, no_section: 5, empty_pages: [7, 8]}` | Summary text is built | `48 passages · 5 without a section · pages 7, 8 have no text` | unit |
| AC-21 | Frontend helper, all counts zero/empty, 12 passages | Summary text is built | `12 passages` | unit |
| AC-22 | Frontend helper, passage with page_start 3, page_end 3 / page_start 3, page_end 4 / no pages | Row label is built | `p. 3` / `p. 3–4` / no page part | unit |
| AC-23 | As AC-14, Graphite and Night | Same | Row and summary text ≥ 13px, ≥ 4.5:1 contrast, no signal colour (`--hi`) | evaluator |
| AC-24 | Viewport 390px | As AC-14 | `document.documentElement.scrollWidth` ≤ 390 | evaluator |
| AC-25 | Existing backend and frontend suites | CI | All existing tests pass unchanged | unit |
| AC-28 | As AC-13 | `Text` selected | The text pane shows exactly the `/cache/{row_id}` `full_text`, in the same `pre` box with the same max height (400px) as on `main` | evaluator |
| AC-29 | As AC-17 | Same | The open passage's text box has `white-space: pre-wrap`, `max-height: 16rem` and `overflow-y: auto` | evaluator |
| AC-30 | Frontend helper, a transcript passage with speaker `Jane Doe` and no section | Row label is built | It contains `Jane Doe` and not `no section` | unit |
| AC-31 | T1 cached | `GET /passages` twice | Row counts of `parsed_content` and the documents registry are the same before and after | unit |
| AC-32 | T1 cached | `GET /api/documents/cache` and `/cache/{row_id}` | Bodies have exactly the keys they have on `main` (`total`, `documents`; and `content_key`, `company_id`, `doc_type`, `title`, `filename`, `full_text`, `page_breaks`, `text_sha256`) | unit |
| AC-33 | The PR diff | Review | No change in `backend/arp/ingestion/parsing.py` or `backend/arp/ingestion/chunk_spans.py` | evaluator |

Must not change: the `Text` view of Parsed documents (AC-28), `/api/documents/cache` and `/cache/{row_id}`
responses (AC-32), how documents are chunked for extraction (AC-33).
