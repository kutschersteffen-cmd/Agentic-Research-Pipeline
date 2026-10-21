# RFP agent, part 1: answering the written RFP

Status: draft, 2026-10-21. Part 2 (the pitch deck) gets its own spec after this one is built; it
reads this part's approved answers.

## Intent

The firm answers RFPs from institutional investors. Today the right answer to each question sits
somewhere in past RFP responses and a shared answer library, all Word and Excel files, and
assembling correct answers by hand takes most of the time. This part gives the app what a tool
like Loopio or Responsive does, end to end:

1. an **answer library** of approved question-and-answer pairs, loaded once from the past files,
2. **import** of an incoming RFP (the investor's Word or Excel file) with every question found,
3. **auto-fill**: each question gets a drafted answer built only from library entries, with its
   sources shown,
4. **assign and review**: questions go to colleagues, and an approver signs off every answer,
5. **export**: approved answers are written back into the investor's own file, in its format.

Every answer the firm approves goes back into the library, so the library gets better with each RFP.

## Goals

- A reviewer can check any drafted answer in seconds, because each one names the library entries it
  came from and quotes them.
- An answer with no source in the library is never filled in. It is left blank and flagged.
- Figures that go stale (AUM, performance, fees, headcount, dates) are never copied forward
  silently. Every answer that contains one is flagged for a human to check.
- The exported file is the investor's file, with their formatting, plus the answers.

## Anti-goals (a failure even if it technically works)

- An invented answer or figure reaching an investor.
- An old figure reused without a flag.
- The investor's file coming back with broken formatting, moved cells or lost sheets.

## Not in this spec

- The pitch deck (part 2).
- RFPs that arrive as PDFs or online portals: the app cannot write answers back into them.
- Email or chat notifications on assignment. Assignees see their questions on the RFP page.
- Usage analytics (win rates, time saved).
- Translating answers between languages.

## How it works

### Where it lives (my call)

A new feature area laid out like `transition_alignment`: backend module `backend/arp/rfp/`, router
`backend/arp/api/routers/rfp.py` registered in `api/main.py` with `Depends(authorize)`, CLI sub-app
`backend/arp/cli/rfp.py`, frontend pages under `frontend/src/pages/`. State lives in Postgres,
in tables created by `backend/arp/storage/postgres_schema.py` like the existing ones. Uploaded
files go through the existing blob store (`storage/document_blob_store.py`).

Reused as they are: file parsing (`ingestion/local_files.py`), the LLM client
(`llm/base.py` `complete_structured`), quote checking (`grounding.py` `ground_claim`), ranked
retrieval (`retrieval/select_evidence.py` `select_relevant_chunks`, hybrid mode), roles
(`api/auth.py` `require_role`), and run scheduling (`api/run_scheduling.py` `schedule_llm_run`).

### 1. Answer library

A library entry holds: question text, answer text, topic tags, the source file and its location in
it (sheet and cell, or paragraph), the date it was approved, a `review_by` date, an owner, a
`has_figures` flag, and a status (`active` or `retired`).

**Loading the past files.** `arp rfp library import <file>...` and `POST /api/rfp/library/import`
take `.docx` and `.xlsx` files. Each file is parsed, and Claude lists the question-and-answer pairs
in it, quoting both from the file. (my call) An answer is stored **verbatim** from the file, never
rewritten, because it is what the firm already sent. A pair whose quoted question or answer does
not ground in the file (`is_grounded`, threshold 0.92) is dropped and listed in the import report.
Imported entries are `active` at once: they were already approved when they were first sent.

(my call) `review_by` defaults to 12 months after the source file's last-modified date. Entries past
`review_by` still match, but every answer drafted from them carries a `stale source` flag.

(my call) `has_figures` is set by a fixed rule, not by the model: the answer contains a digit next to
`%`, a currency sign or code (`€ $ £ EUR USD GBP CHF`), `m`, `mn`, `bn`, `million`, `billion`, or a
four-digit year from 1990 to 2099.

Duplicates are kept. When several entries match a question, the most recently approved one ranks
first among equally relevant entries.

An approver can edit an entry, change its tags, owner and `review_by`, or retire it. Retired entries
never match.

### 2. Importing an incoming RFP

`POST /api/rfp/projects` takes the investor's file (`.docx` or `.xlsx`), the investor name and the
due date, and creates an RFP project. The original bytes are stored unchanged for export.

Questions are found by Claude, from a parse that keeps locations: for Excel, each non-empty cell
with its sheet and cell reference (the existing `_extract_xlsx_text` drops cell references, so the
importer needs its own pass with openpyxl); for Word, each paragraph and each table cell with its
index. For every question Claude returns the question's location and **where its answer goes**: an
Excel cell, a Word table cell, or "after this Word paragraph". The app then checks deterministically
that the text at that location is the question Claude reported; a mismatch drops the question and
lists it on the project as `not located`. The project page shows the question count so a person can
compare it with the file.

### 3. Auto-fill

For each question:

1. Retrieval picks the top 8 active library entries (hybrid BM25 plus vectors, as
   `select_relevant_chunks` does for document chunks; library entries are wrapped as chunks).
2. Claude drafts an answer **only from those entries**, citing each entry it used with a quote.
   It may combine and shorten entries, and adapt wording to the question, but adds no facts.
3. `ground_claim` checks every quote against its entry. If any quote fails, or Claude cites
   nothing, the draft is discarded and the question gets status `no source`, answer blank.
4. Every number in the draft must appear in a cited entry. A number that does not discards the draft
   the same way (`no source`). This is the same check as the deck linter's "numbers not found in the
   source".
5. Flags on the draft: `check figure` when any cited entry has `has_figures`; `stale source` when any
   cited entry is past `review_by`.

The draft runs as a background run via `schedule_llm_run`, so a 300-question RFP does not block the
request. The project page shows progress.

### 4. Assign and review

The RFP project page lists every question in file order with its draft, its flags, its sources
(entry question, quoted text, original file and location) and its status:
`no source` · `drafted` · `edited` · `approved` · `left blank`.

- An analyst can edit a draft (status `edited`), assign the question to a user, or mark it
  `left blank`. A filter shows "assigned to me".
- An approver approves an answer (status `approved`). Editing an approved answer sets it back to
  `edited`.
- (my call) On approval, the answer becomes a new active library entry: source is this RFP project,
  `review_by` is 12 months later, `has_figures` by the rule above. The entries it was drafted from
  stay as they are.
- Roles come from `config/users.json` as today: viewer can read, analyst edits and assigns,
  approver approves.

### 5. Export

`GET /api/rfp/projects/{id}/export` returns a copy of the investor's original file with every
`approved` answer written into its answer location. Nothing else in the file changes.

- Excel: the answer is written as the value of its cell, keeping that cell's existing style.
- Word, table cell: the answer replaces the cell's empty paragraph, in that paragraph's style.
- Word, after a paragraph: a new paragraph is inserted after the question, in the style of the
  paragraph that follows the question in the original (or `Normal` when there is none).
- Questions not `approved` are left as they were in the original. The response header
  `X-RFP-Unapproved` gives their count, and the page shows it before download.

Known limit, stated so it is not a surprise: openpyxl does not keep images, charts or shapes inside
an Excel file. (my call) Export refuses an `.xlsx` that contains any of these, with a message naming
the sheet, rather than return a damaged file.

## Constraints

- Real-model checks: this feature touches `arp/llm` callers and adds golden cases, so CI runs the
  golden set on its PRs.
- Golden cases are fictitious RFPs and a fictitious library, written for the purpose; no client data
  is committed.
- No new dependencies: python-docx and openpyxl are already installed.

## Left to the builder

- Table and column names, the API shape beyond the endpoints named here, the frontend layout of the
  project page.
- Prompt wording and the structured-output models.
- How library entries are wrapped as chunks for retrieval.

## Acceptance

Setup notes for the test-writer:
- Fixture files live with the tests. `lib_past.xlsx`: one sheet `Responses`, header row `Question |
  Answer`, then 3 rows: (`Describe your firm.`, `Example AM is an independent manager founded in
  2004.`), (`What is your total AUM?`, `EUR 12.4bn as of 31 Dec 2025.`), (`Do you sign the UN PRI?`,
  `Yes, we have been a PRI signatory since 2010.`). `rfp_in.xlsx`: one sheet `RFP`, header row
  `Question | Response`, then `A2` = `Please describe your firm.`, `A3` = `What are your assets under
  management?`, `A4` = `Do you use derivatives for leverage?`, column B empty; cell `A1` bold.
- Unit rows replace the model with a stand-in that returns fixed structured output.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | empty library | `arp rfp library import lib_past.xlsx` | exit 0; stdout `imported 3 entries, dropped 0`; the library holds 3 active entries whose answers equal the fixture answers character for character | unit |
| AC-2  | stand-in returns a 4th pair whose answer is not in the file | import `lib_past.xlsx` | stdout `imported 3 entries, dropped 1`; the dropped pair's question is printed on the next line, prefixed `dropped: ` | unit |
| AC-3  | the 3 entries from AC-1 | read their `has_figures` | `Describe your firm.` true (year 2004), `What is your total AUM?` true, `Do you sign the UN PRI?` true (year 2010) | unit |
| AC-4  | an answer `We have offices in four countries.` | compute `has_figures` | false | unit |
| AC-5  | `lib_past.xlsx` last modified 2025-06-30 | import it | every entry's `review_by` is 2026-06-30 | unit |
| AC-6  | a user with role `analyst` | `POST /api/rfp/library/{id}/retire` | 403 | unit |
| AC-7  | a retired entry that is the only match | auto-fill a question that matches it | the question's status is `no source` and its answer is empty | unit |
| AC-8  | `rfp_in.xlsx` uploaded, stand-in reports 3 questions with answer cells `B2`, `B3`, `B4` | project created | the project lists 3 questions in order A2, A3, A4 with answer locations `RFP!B2`, `RFP!B3`, `RFP!B4` | unit |
| AC-9  | stand-in reports a question at `RFP!A5`, which is empty | project created | that question is not in the list; the project shows `1 not located` | unit |
| AC-10 | library from AC-1, stand-in drafts A2 from the `Describe your firm.` entry with a quote from it | auto-fill | A2 status `drafted`; its sources list that entry and the quote; flag `check figure` present | unit |
| AC-11 | stand-in drafts A3 with quote `EUR 13.0bn` (not in any entry) | auto-fill | A3 status `no source`, answer empty | unit |
| AC-12 | stand-in drafts A3 as `EUR 12.9bn.` citing the AUM entry with a quote that does ground | auto-fill | A3 status `no source`, answer empty (12.9 is in no cited entry) | unit |
| AC-13 | a cited entry with `review_by` before today | auto-fill | the draft carries flag `stale source` | unit |
| AC-14 | a drafted question, user role `analyst` | `POST .../questions/{qid}/approve` | 403; status unchanged | unit |
| AC-15 | a drafted question, user role `approver` | approve it | status `approved`; the library gains one active entry with that question and answer, source = this project | unit |
| AC-16 | an approved question | an analyst edits its answer | status `edited`; the library entry from AC-15 is unchanged | unit |
| AC-17 | `rfp_in.xlsx` project, A2 and A3 approved, A4 `no source` | export | `B2` and `B3` hold the approved answers; `B4` is empty; `A1` is still bold; the sheet names and every other cell equal the original; header `X-RFP-Unapproved: 1` | holdout |
| AC-18 | a `.docx` RFP whose question sits in a table cell with an empty cell to its right, approved | export | the right-hand cell holds the answer; the document's paragraph and table counts are otherwise unchanged | holdout |
| AC-19 | a `.docx` RFP with a question paragraph followed by another paragraph in style `Body Text`, approved | export | a new paragraph with the answer, style `Body Text`, sits directly after the question; all other paragraphs are unchanged and in order | holdout |
| AC-20 | an `.xlsx` RFP that contains an image | export | 409, message names the sheet holding the image; no file returned | unit |
| AC-21 | user `alice` (analyst) assigned 2 of 3 questions | open the project page, filter "assigned to me" | exactly those 2 questions show | evaluator |
| AC-22 | a drafted answer | open the project page | the answer shows its flags and, for each source, the entry's question, the quoted text and the original file name and location | evaluator |
| AC-23 | the golden RFP cases in `backend/arp/golden_set/data/rfp_questions.json` | run the golden set for question detection | at least 95% of questions found with the right answer location, and no reported question absent from the file | golden |
| AC-24 | the golden drafting cases in `backend/arp/golden_set/data/rfp_drafts.json` | run the golden set for drafting | 0 drafts with a figure absent from their cited entries; at least 90% of questions whose answer is in the library get status `drafted` | golden |

Must not change: existing document upload, review queue and deck routes behave as today. Covered by
the existing suites.
