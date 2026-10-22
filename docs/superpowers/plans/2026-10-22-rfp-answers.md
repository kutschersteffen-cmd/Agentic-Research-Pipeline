# RFP answers (part 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An answer library, RFP import with question detection, grounded auto-fill, assign/edit/four-eyes approval, and export back into the investor's own `.xlsx`/`.docx`.

**Architecture:** Pure functions in `backend/arp/rfp/` (file locations, fill, detection, drafting, library import) with no DB; three SQLAlchemy tables in `arp/db/models.py` (created by `ensure_schema`'s `create_all`); one router and one CLI sub-app call them. One frontend page `#/rfp`.

**Tech Stack:** FastAPI, SQLAlchemy/Postgres, python-docx, openpyxl, Typer, React.

**Spec:** `docs/superpowers/specs/2026-10-21-rfp-answers-design.md`

## Global Constraints

- No new dependencies (python-docx, openpyxl already installed).
- Golden cases are fictitious; no client data committed.
- `_extract_xlsx_text` and `ingestion/local_files.py` unchanged; no existing test file changed.
- Roles: viewer reads; analyst edits, writes, assigns, leaves blank, creates projects; approver approves and manages the library.
- Regexes verbatim: placeholder `^\[[^\[\]]*\]$`, figures `\d`, numbers `\d+(?:[.,'’]\d+)*` with `,` `'` `’` deleted.
- `review_by` = date + 12 months (29 Feb → 28 Feb).

## Review Focus

1. An answer starting with `=` written into Excel would become a formula → write it as a string (test in Task 2).
2. Several `P<n>` answers in one Word file: inserting after `P1` must not shift `P5` → resolve all paragraphs before mutating (test in Task 2).
3. A citation naming an entry the model was not shown → ungrounded → `no source` (test in Task 4).
4. A garbled location string (`RFP!`, `T0R9C9`, `X1`) → refused/not located, never a crash (tests in Tasks 2, 3).
5. A Word question paragraph with its answer location equal to its own `P<n>` is kept (the "after" case); a cell answer location equal to the question location is not (test in Task 3).

---

### Task 1: Text rules and file locations — `arp/rfp/text.py`, `arp/rfp/locations.py`

**Produces:**
- `normalise(s) -> str`, `is_placeholder(s) -> bool` (empty or placeholder), `has_figures(s) -> bool`, `numbers(s) -> set[str]`, `plus_12_months(d: date) -> date`.
- `items(data: bytes, suffix: str) -> list[tuple[str, str]]` — `(location, text)` in file order. xlsx: non-empty cells per sheet, row-major. docx: body order, `P<n>` for every top-level paragraph, `T<t>R<r>C<c>` for every top-level table cell (empty ones included).
- `document_date(data: bytes) -> date | None` — `docProps/core.xml` `dcterms:modified`, else `dcterms:created`.

Tests (`tests/test_rfp_text.py`): AC-3, AC-4; `numbers("EUR 1,200 and 12.4bn on 31 Dec 2025") == {"1200", "12.4", "31", "2025"}`; `is_placeholder("[Response]")`, `not is_placeholder("[a] [b]")`; `normalise("  What are   your AUM? ") == "what are your aum"`; xlsx/docx `items` order.

### Task 2: Fill — `arp/rfp/fill.py`, CLI `arp rfp fill`

**Produces:** `fill(data: bytes, suffix: str, answers: list[tuple[str, str]]) -> bytes`; raises `FillRefused(msg)` (one line naming the sheet or location). Validates every answer before any change.

Rules exactly as spec §5. xlsx refusal: walk `xl/workbook.xml` → sheet rels → a `/drawing` relationship; name the first such sheet in workbook order.

CLI: `arp rfp fill <original> <answers.json> --out <path>`; exit 0 silent; on `FillRefused` stderr one line, exit 1, no file written.

Tests (`tests/test_rfp_fill.py`), fixtures built in-test per the spec's setup notes: AC-30..37, AC-49 (CLI via `CliRunner`), plus Review Focus 1, 2, 4.

### Task 3: Detection — `arp/rfp/detect.py`

**Produces:** `async detect_questions(items, llm) -> tuple[list[Detected], int]` — `Detected(location, answer_location, question)` in file order of the question location; second value is `not_located`. LLM output model `DetectedQuestions{questions: [{location, question, answer_location}]}`.

Keep iff: normalised text at `location` == normalised reported question; `answer_location` exists (xlsx: valid cell in an existing sheet; docx: index in range); and either (answer is `P<n>`, which may equal the question's own `P<n>`) or (answer is a cell ≠ question location and `is_placeholder`).

Tests: AC-10..13 (pure, with `FakeLLMClient`), Review Focus 4, 5.

### Task 4: Drafting and library import — `arp/rfp/draft.py`, `arp/rfp/library.py`

**Produces:**
- `Entry` (id, question, answer, review_by) and `async draft_answer(question, entries, llm, *, today, settings) -> Draft(status, answer, sources[{entry_id, quote}], flags)`. Retrieval: entries wrapped as `DocumentChunk` (`chunk_id=f"rfp-{id}-{sha256(text)[:12]}"`), `select_relevant_chunks(max_chunks=8, require_hit=True, fallback_to_all=True, hybrid from settings)`. No entries → no LLM call. `ground_claim` over the shown entries only; then the numbers rule.
- `flags(answer, source_review_bys, today) -> list[str]` — `check figure`, `stale source` (`review_by < today`).
- `async extract_pairs(data, suffix, filename, llm, *, today) -> (pairs, dropped)` — each pair's question and answer must ground (`is_grounded`, 0.92) in the joined item text; stored answer is the matched span (verbatim); location = item where the answer span starts; `review_by` from `document_date` or today.

Tests: AC-14..18 at the function level, AC-9 (no entries → `llm.calls == []`), Review Focus 3.

### Task 5: Tables, router, CLI library import — `arp/db/models.py`, `arp/rfp/store.py`, `arp/api/routers/rfp.py`, `arp/cli/rfp.py`

Tables: `rfp_library_entries`, `rfp_projects`, `rfp_questions` (sources as JSONB `[{entry_id, quote}]`, flags JSONB).

Endpoints as spec §1–5 plus `GET /api/rfp/library`, `PUT /api/rfp/library/{id}` (approver), `POST /api/rfp/library/{id}/retire` (approver), `GET /api/rfp/projects`. Router registered with `Depends(authorize)`; approver routes add `require_role("approver")`. `X-RFP-Unapproved` added to CORS `expose_headers`. Project run: `schedule_llm_run`, run_status `detecting → drafting → done | failed`.

CLI `arp rfp library import <file>...` prints `imported N entries, dropped M` then `dropped: <question>` lines.

Tests (`tests/test_rfp_api.py`, `pg` fixture): AC-1, 2, 5, 6, 7, 8, 9, 19..29, 38, 47, 48, 50, 51.

### Task 6: Golden — `arp/rfp/golden.py`, `arp rfp golden questions|drafts`, cases, CI step

Cases describe files as JSON (sheets as row lists; docx as blocks) and are built in memory. `questions`: recall over labelled `(location, answer_location)`. `drafts`: drafted share of answerable, `no source` share of unanswerable, and the verifier model must find 0 drafts with a fact absent from their cited entries. CI: `golden-set.yml` path + scope gain `arp/rfp`, new step runs both commands.

### Task 7: Frontend page — `frontend/src/pages/Rfp.tsx`, `App.tsx`, `api/client.ts`

Library list/import/retire; project upload; project view: counts, run status, "assigned to me" filter, each question with answer, status, flags, assignee, sources (entry question, quote, file + location or `written by`), edit/assign/leave blank/approve (with flag checkboxes), export showing "N questions not approved" before download. Regenerate `openapi.json` and `schema.gen.ts`.
