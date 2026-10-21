# RFP agent, part 1: answering the written RFP

Status: draft, 2026-10-21. Part 2 (the pitch deck) gets its own spec after this one is built; it
reads this part's approved answers. Owner decisions on 2026-10-21: the agent does all five jobs of a
tool like Loopio or Responsive; answers come from past RFP responses and a shared answer library,
all Word and Excel; colleagues may write answers by hand; approval is four-eyes; any digit in an
answer counts as a figure to check.

## Intent

The firm answers RFPs from institutional investors. Today the right answer to each question sits
somewhere in past RFP responses and a shared answer library, all Word and Excel files, and
assembling correct answers by hand takes most of the time. This part gives the app what a tool
like Loopio or Responsive does, end to end:

1. an **answer library** of approved question-and-answer pairs, loaded once from the past files,
2. **import** of an incoming RFP (the investor's Word or Excel file) with every question found,
3. **auto-fill**: each question gets a drafted answer built only from library entries, with its
   sources shown,
4. **assign and review**: questions go to colleagues, who can edit drafts or write answers by hand,
   and a second person approves every answer,
5. **export**: approved answers are written back into the investor's own file, in its format.

Every answer the firm approves goes back into the library, so the library gets better with each RFP.

## Goals

- A reviewer can check any drafted answer in seconds, because each one names the library entries it
  came from and quotes them.
- The agent never fills in an answer it has no library source for. It leaves it blank and flagged;
  a colleague may then write one by hand.
- Figures that go stale (AUM, performance, fees, headcount, dates) are never copied forward
  silently. Every answer containing a digit carries a flag the approver must confirm.
- The exported file is the investor's file, with their formatting, plus the answers.

## Anti-goals (a failure even if it technically works)

- An invented answer or figure reaching an investor.
- An old figure reused without a flag.
- The investor's file coming back with broken formatting, moved cells, lost sheets, or any of the
  investor's own text overwritten.

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
`backend/arp/cli/rfp.py`, a frontend page under `frontend/src/pages/`. State lives in Postgres, in
tables created by `backend/arp/storage/postgres_schema.py` like the existing ones. Uploaded files go
through the existing blob store (`storage/document_blob_store.py`).

Reused as they are: file parsing (`ingestion/local_files.py`, unchanged), the LLM client
(`llm/base.py` `complete_structured`, extractor and verifier from `llm/factory.py`), quote checking
(`grounding.py` `is_grounded`, `ground_claim`), ranked retrieval (`retrieval/select_evidence.py`
`select_relevant_chunks`, hybrid mode), roles (`api/auth.py` `require_role`), and run scheduling
(`api/run_scheduling.py` `schedule_llm_run`).

### Shared definitions

- **Location.** Excel: `<sheet>!<cell>`, e.g. `RFP!B2`. Word table cell: `T<t>R<r>C<c>`, the
  0-based indexes of a top-level table in `Document.tables` and of the row and cell in it. Word
  paragraph: `P<n>`, the 0-based index in `Document.paragraphs`.
- **Normalised text.** Casefold, collapse every run of whitespace to one space, strip leading and
  trailing whitespace and the characters `?:.;`. Used to compare a reported question with the file.
- **Empty or placeholder.** A cell or paragraph is *empty or placeholder* when its text, stripped of
  whitespace, is empty or is one bracketed span such as `[Response]` or `[Please answer here]`
  (regex `^\[[^\[\]]*\]$`).
- **Has figures.** An answer has figures when it contains a digit (regex `\d`).
- **Numbers.** The numbers of a text are its matches of `\d+(?:[.,'’]\d+)*`, each normalised by
  deleting `,`, `'` and `’`. So `1,200` and `1200` are the same number, `12.4bn` gives `12.4`, and
  `31 Dec 2025` gives `31` and `2025`. (my call) This is stricter than the deck linter's
  `number_not_in_source`, which skips small integers and years and allows rounding.

### 1. Answer library

A library entry holds: question text, answer text, topic tags, its source (a file name and location
in it, an RFP project, or `written by <user_id>`), the date it was approved, a `review_by` date, an
owner, `has_figures`, and a status (`active` or `retired`).

**Loading the past files.** `arp rfp library import <file>...` and `POST /api/rfp/library/import`
take `.docx` and `.xlsx` files and share one code path. Each file is parsed, and Claude lists the
question-and-answer pairs in it, quoting both. (my call) An answer is stored **verbatim** from the
file, never rewritten, because it is what the firm already sent. A pair whose question or answer
does not ground in the file (`is_grounded`, threshold 0.92) is dropped and listed in the import
report. Imported entries are `active` at once: they were approved when they were first sent.

(my call) `review_by` is 12 months after the file's document date: its core property `modified`,
else `created`, else the import date. Entries past `review_by` still match, but every answer drafted
from them carries the flag `stale source`.

An approver can edit an entry's answer, tags, owner and `review_by`, or retire it. Retired entries
are never shown to the model.

### 2. Importing an incoming RFP

`POST /api/rfp/projects` (analyst or above) takes the investor's file (`.docx` or `.xlsx`), the
investor name and the due date, stores the original bytes unchanged, creates the project and starts
a background run (`schedule_llm_run`) that finds the questions and then auto-fills them. The project
shows `run_status`: `detecting`, `drafting`, `done` or `failed`.

Questions are found by Claude, from a parse that keeps locations: for Excel, every non-empty cell
with its location (the existing `_extract_xlsx_text` drops cell references, so the importer has its
own openpyxl pass); for Word, every paragraph and every top-level table cell with its location. For
each question Claude returns its location and its **answer location**. The app keeps a question only
if all of these hold, and otherwise lists it as not located:

1. the normalised text at the question location equals the normalised reported question,
2. the answer location exists (for "after a paragraph", the answer location is the question's own
   `P<n>`, meaning "after this paragraph"),
3. the answer location is not the question location, and for a cell is *empty or placeholder*.

The project returns its questions in file order and a `not_located` count.

### 3. Auto-fill

For each question in status `no source` or new (never one that is `edited`, `approved` or
`left blank`):

1. Retrieval picks the top 8 active library entries (hybrid BM25 plus vectors, as
   `select_relevant_chunks` does for document chunks; entries are wrapped as chunks).
2. Claude drafts an answer **only from those entries**, citing each entry it used with a quote. It
   may combine and shorten entries and fit the wording to the question, but adds no facts.
3. `ground_claim` checks every quote against its entry's answer text. If any quote fails, or there
   is no citation, the draft is discarded: status `no source`, answer empty.
4. Every number in the draft must be a number of a cited entry's answer or of the question. If one is
   not, the draft is discarded the same way.
5. Otherwise status `drafted`. Flags: `check figure` when the draft has figures; `stale source` when
   any cited entry is past `review_by`.

`POST /api/rfp/projects/{id}/autofill` (analyst or above) runs steps 1 to 5 again in the background,
e.g. after the library has grown.

### 4. Assign and review

The project page lists every question in file order with its answer, status, flags, assignee and
sources (each source: the entry's question, the quoted text, and the entry's original file name and
location, or `written by <user>`). Statuses: `no source` · `drafted` · `edited` · `approved` ·
`left blank`. A filter shows "assigned to me". The page shows the question count, the not-located
count and the run status.

- **Edit or write** (analyst or above): `PUT .../questions/{qid}` with `{"answer": "<text>"}` sets
  the answer, status `edited`, and records the caller as last editor. This works on any status, so a
  colleague can write an answer by hand for a `no source` question. (my call) Editing keeps the
  question's sources as they are: an edited draft still shows the entries it came from, and a
  hand-written answer on a `no source` question has none. Flags are recomputed: `check figure` by the
  has-figures rule; `stale source` while any source is past `review_by`.
- **Assign** (analyst or above): `PUT .../questions/{qid}/assignee` with `{"user_id": "<id>"}`.
- **Leave blank** (analyst or above): `POST .../questions/{qid}/leave-blank`, status `left blank`.
- **Approve** (approver): `POST .../questions/{qid}/approve` with
  `{"confirmed_flags": ["check figure", ...]}`. Refused with 409 when the answer is empty, or when
  `confirmed_flags` does not contain every flag the question has. Refused with 403 when the caller is
  the question's last editor (four-eyes). An unedited agent draft has no last editor, so any approver
  may approve it. On success: status `approved`.
- **Back to library** (my call): on approval the answer becomes one new active library entry with
  the question and answer, source `project <id>` when the question has sources, or
  `written by <last editor>` when it has none,
  `review_by` = approval date + 12 months, `has_figures` by the rule. The entries it was drafted from
  stay as they are. Approving is the approver's confirmation that each flag was checked, which is why
  the new entry may start a fresh `review_by`.
- Editing an approved answer sets it back to `edited`; the library entry already made stays.
- Roles come from `config/users.json` as today: viewer reads, analyst edits, writes, assigns and
  leaves blank, approver also approves and manages the library.

`GET /api/rfp/projects/{id}` returns the project with `run_status`, `not_located` and `questions[]`,
each with `id`, `location`, `answer_location`, `question`, `answer`, `status`, `flags`, `assignee`,
`last_editor` and `sources`.

### 5. Export

Writing answers into a file is one function, with two entry points that share it:

- `GET /api/rfp/projects/{id}/export` (viewer or above) returns a copy of the original file with
  every `approved` answer written into its answer location. The response header
  `X-RFP-Unapproved` gives the count of questions not approved; the page shows it before download.
- `arp rfp fill <original> <answers.json> --out <path>` does the same from a JSON list of
  `{"answer_location": "<location>", "answer": "<text>"}`. Exit 0 and no output on success.

Rules, applied to every answer:

- **Excel cell:** the cell's value becomes the answer; its font, fill, border and number format stay.
- **Word table cell:** the cell's text becomes the answer, in a single paragraph that keeps the
  style of the cell's first paragraph.
- **Word, after paragraph `P<n>`:** if `P<n+1>` exists and is *empty or placeholder*, it receives the
  answer and keeps its style; otherwise a new paragraph with the answer is inserted directly after
  `P<n>`, in the style of `P<n+1>`, or `Normal` when `P<n>` is the last paragraph.
- Nothing else in the file changes.

Refusals (no file is returned or written): an `.xlsx` that contains an image, chart or shape (an
`xl/drawings/drawing*.xml` entry in the archive; cell comments, stored as `vmlDrawing`, do not
count) is refused, because openpyxl would drop it; the message names the first sheet that holds one.
An Excel or table-cell answer location that does not exist or is not *empty or placeholder* in the
original is refused, naming the location; a `P<n>` location is refused only when `P<n>` does not
exist. The API returns 409; the CLI exits 1 with that
message as one line on stderr.

## Constraints

- Golden checks with the real model: `arp rfp golden questions` and `arp rfp golden drafts` (below).
  The golden-set CI workflow gains a step that runs both on PRs touching `backend/arp/rfp/`; like
  the existing step, it warns and passes without `ARP_ANTHROPIC_API_KEY`.
- Golden cases are fictitious RFPs and a fictitious library written for the purpose. No client data
  is committed.
- No new dependencies: python-docx and openpyxl are already installed.

## Left to the builder

- Table and column names, prompt wording, the structured-output models.
- How library entries are wrapped as chunks for retrieval.
- The layout of the project page and of the library page, within the content stated above.
- Endpoints for library browsing and editing beyond retire (AC-7).

## Acceptance

Setup notes for the test-writer:
- Users in `config/users.json`: `alice` (analyst), `bob` (approver), `carol` (approver),
  `vic` (viewer).
- Unit rows replace the model with a stand-in that returns fixed structured output.
- `lib_past.xlsx`: core property `modified` = 2025-06-30T00:00:00Z; one sheet `Responses`, row 1
  `Question | Answer`, then rows (`Describe your firm.`, `Example AM is an independent manager
  founded in 2004.`), (`What is your total AUM?`, `EUR 12.4bn as of 31 Dec 2025.`), (`Do you sign
  the UN PRI?`, `Yes, we have been a PRI signatory since 2010.`).
- `rfp_in.xlsx`: one sheet `RFP`; `A1` `Question` (bold), `B1` `Response`; `A2` `Please describe
  your firm.`, `A3` `What are your assets under management?`, `A4` `Do you use derivatives for
  leverage?`; `B2:B4` empty and filled yellow (`FFFF00`); `A6` `Contact: rfp@investor.example`.
- `rfp_table.docx`: paragraph `Section 1`; a 2x2 table (`Question` | `Response`;
  `What is your total AUM?` | one empty `Normal` paragraph); paragraph `End`.
- `rfp_table_ph.docx`: as `rfp_table.docx`, but the answer cell holds one paragraph `[Response]`.
- `rfp_para.docx`: `P0` `Section A` (`Heading 1`), `P1` `Describe your firm.` (`Normal`),
  `P2` `Next section.` (`Body Text`).
- `rfp_para_empty.docx`: `P0` `Describe your firm.` (`Normal`), `P1` empty (`Body Text`),
  `P2` `Next.` (`Normal`).
- `rfp_image.xlsx` and `rfp_chart.xlsx`: `rfp_in.xlsx` plus, on sheet `RFP`, one PNG image
  (`openpyxl.drawing.image.Image`; Pillow is already a backend dependency) or one `BarChart`, built
  with openpyxl. Each archive contains an `xl/drawings/drawing1.xml` entry.
- "Today" in unit rows is 2026-10-21.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | empty library | `arp rfp library import lib_past.xlsx` | exit 0; stdout `imported 3 entries, dropped 0`; the library holds 3 active entries whose answers equal the fixture answers character for character | unit |
| AC-2  | stand-in also returns the pair (`What are your fees?`, `0.5% p.a. on all mandates.`), absent from the file | import `lib_past.xlsx` | exit 0; stdout line 1 `imported 3 entries, dropped 1`, line 2 `dropped: What are your fees?` | unit |
| AC-3  | the answer `We employ 85 people.` | compute has figures | true | unit |
| AC-4  | the answer `We have offices in four countries.` | compute has figures | false | unit |
| AC-5  | `lib_past.xlsx` | import it | every entry's `review_by` is 2026-06-30 | unit |
| AC-6  | `lib_past.xlsx` saved with no `modified` and no `created` property | import it on 2026-10-21 | every entry's `review_by` is 2027-10-21 | unit |
| AC-7  | an active entry | `alice` calls `POST /api/rfp/library/{id}/retire` | 403; the entry is still active | unit |
| AC-8  | an active entry | `bob` calls `POST /api/rfp/library/{id}/retire` | 200; the entry's status is `retired` | unit |
| AC-9  | the library's only entry is retired; the stand-in would draft from any entry it is shown | auto-fill `rfp_in.xlsx` | every question has status `no source` and an empty answer; the stand-in was shown no entries | unit |
| AC-10 | `rfp_in.xlsx` uploaded; stand-in reports questions at `RFP!A2`, `RFP!A3`, `RFP!A4` with answer locations `RFP!B2`, `RFP!B3`, `RFP!B4` | detection finished | `GET` project lists 3 questions in that order with those locations; `not_located` is 0 | unit |
| AC-11 | as AC-10, but the stand-in reports A3's question as `what are your assets under management` | detection finished | A3 is listed; `not_located` is 0 | unit |
| AC-12 | stand-in also reports question `Any other comments?` at `RFP!A5` (empty) with answer location `RFP!B5` | detection finished | no question at `RFP!A5`; `not_located` is 1 | unit |
| AC-13 | stand-in reports A2 with answer location `RFP!A6` (holds investor text) | detection finished | no question at `RFP!A2`; `not_located` is 1 | unit |
| AC-14 | library from AC-1; stand-in drafts A2 as `Example AM is an independent manager founded in 2004.` citing the firm entry with quote `an independent manager founded in 2004` | auto-fill | A2 status `drafted`; its one source is the firm entry with that quote | unit |
| AC-15 | as AC-14 | read A2's flags | exactly `check figure` and `stale source` (the entry's `review_by` 2026-06-30 is past) | unit |
| AC-16 | stand-in drafts A3 citing the AUM entry with quote `EUR 13.0bn` | auto-fill | A3 status `no source`, answer empty | unit |
| AC-17 | stand-in drafts A3 as `EUR 12.9bn.` citing the AUM entry with quote `EUR 12.4bn as of 31 Dec 2025` | auto-fill | A3 status `no source`, answer empty | unit |
| AC-18 | stand-in drafts A3 as `EUR 12.4bn (31 Dec 2025).` with the quote of AC-17 | auto-fill | A3 status `drafted` | unit |
| AC-19 | A3 `edited` by `alice` | `POST .../autofill`, stand-in drafts A3 differently | A3's answer and status are unchanged | unit |
| AC-20 | A4 `no source` | `alice` `PUT`s answer `No, we do not use derivatives for leverage.` | A4 status `edited`, sources empty, flags empty, `last_editor` `alice` | unit |
| AC-21 | A4 as in AC-20 | `vic` `PUT`s an answer | 403; A4 unchanged | unit |
| AC-22 | A4 as in AC-20 | `alice` (analyst) approves it | 403; status `edited` | unit |
| AC-23 | A4 as in AC-20 | `bob` approves it with `confirmed_flags: []` | 200; status `approved` | unit |
| AC-24 | A4 approved by `bob` as in AC-23 | read the library | exactly one new active entry with A4's question and answer, source `written by alice`, `review_by` 2027-10-21, `has_figures` false | unit |
| AC-25 | A2 `drafted` with flags `check figure`, `stale source`, never edited | `bob` approves with `confirmed_flags: ["check figure"]` | 409; status `drafted`; library unchanged | unit |
| AC-26 | as AC-25 | `bob` approves with both flags confirmed | 200; status `approved`; the library gains one entry whose source is this project and `has_figures` true | unit |
| AC-27 | a question with an empty answer | `bob` approves it | 409; status unchanged; library unchanged | unit |
| AC-28 | `rfp_in.xlsx` project with its 3 questions | `alice` sets assignee `alice` on A2 and A3 | `GET` project shows `assignee` `alice` on A2 and A3, and no assignee on A4 | unit |
| AC-29 | a drafted question | `alice` calls `leave-blank` | status `left blank` | unit |
| AC-30 | `rfp_in.xlsx`, answers for `RFP!B2` `Example AM is independent.` and `RFP!B3` `EUR 12.4bn.` | `arp rfp fill rfp_in.xlsx answers.json --out out.xlsx` | exit 0; `B2` and `B3` hold those values and are still filled `FFFF00`; `B4` empty and filled `FFFF00`; `A1` still bold; sheet names and every other cell's value, font and fill equal the original | holdout |
| AC-31 | `rfp_table.docx`, answer `EUR 12.4bn.` for `T0R1C1` | `arp rfp fill` | exit 0; cell `T0R1C1` has exactly 1 paragraph, text `EUR 12.4bn.`, style `Normal`; paragraph count, table count and every other cell's text equal the original | holdout |
| AC-32 | `rfp_table_ph.docx`, answer `EUR 12.4bn.` for `T0R1C1` | `arp rfp fill` | exit 0; cell `T0R1C1` has exactly 1 paragraph, text `EUR 12.4bn.` | holdout |
| AC-33 | `rfp_para.docx`, answer `Example AM is independent.` for `P1` | `arp rfp fill` | exit 0; 4 paragraphs; `P2` is the answer in style `Body Text`; `P0`, `P1`, `P3` have the text and style of the original `P0`, `P1`, `P2` | holdout |
| AC-34 | `rfp_para_empty.docx`, answer `Example AM is independent.` for `P0` | `arp rfp fill` | exit 0; 3 paragraphs; `P1` is the answer in style `Body Text`; `P0` and `P2` unchanged | holdout |
| AC-35 | `rfp_image.xlsx`, any answer for `RFP!B2` | `arp rfp fill` | exit 1; stderr one line containing `RFP`; no file at `--out` | holdout |
| AC-36 | `rfp_chart.xlsx`, any answer for `RFP!B2` | `arp rfp fill` | exit 1; stderr one line containing `RFP`; no file at `--out` | holdout |
| AC-37 | `rfp_in.xlsx`, an answer for `RFP!A6` | `arp rfp fill` | exit 1; stderr one line containing `RFP!A6`; no file at `--out` | holdout |
| AC-38 | `rfp_in.xlsx` project with A2 and A3 approved, A4 not | `GET .../export` | 200; header `X-RFP-Unapproved: 1` | unit |
| AC-51 | as AC-38 | `GET .../export` | in the returned file `B2` and `B3` hold A2's and A3's approved answers, `B4` is empty, and every other cell's value, font and fill and the sheet names equal the original | unit |
| AC-39 | an assigned and a drafted question | open the project page as `alice`, filter "assigned to me" | exactly the questions assigned to `alice` show | evaluator |
| AC-40 | a drafted answer with two sources | open the project page | the answer shows its flags and, for each source, the entry's question, the quoted text and the original file name and location | evaluator |
| AC-41 | a project with 2 of 3 questions approved | open the project page, start the download | the page states that 1 question is not approved before the file downloads | evaluator |
| AC-42 | golden cases `backend/arp/golden_set/data/rfp_questions.json` (fictitious RFP files with labelled question and answer locations) | `arp rfp golden questions --cases <file> --min-recall 0.95` | exits 0: at least 95% of labelled questions are kept with the labelled location and answer location | golden |
| AC-43 | golden cases `backend/arp/golden_set/data/rfp_drafts.json` (a fictitious library and questions labelled answerable or unanswerable) | `arp rfp golden drafts --cases <file> --min-drafted 0.90 --min-blank 0.95` | exits 0: at least 90% of answerable questions get `drafted`, at least 95% of unanswerable ones get `no source` | golden |
| AC-44 | as AC-43 | the same command | it also fails unless the verifier model finds 0 drafts stating a fact absent from their cited entries | golden |
| AC-45 | this change | run the existing backend and frontend suites | all pass, with no existing test file changed | unit |
| AC-46 | this change | `arp golden-set run` on the existing cases | exits 0 | golden |
| AC-47 | A4 `edited` by `bob` | `bob` approves it with `confirmed_flags: []` | 403; status `edited` | unit |
| AC-48 | as AC-47 | `carol` approves it with `confirmed_flags: []` | 200; status `approved` | unit |
| AC-49 | `rfp_para.docx`, an answer for `P9` | `arp rfp fill` | exit 1; stderr one line containing `P9`; no file at `--out` | holdout |
| AC-50 | A2 `drafted` as in AC-14 | `alice` `PUT`s `Example AM was founded in 2004 and has 85 staff.` | status `edited`; its one source is still the firm entry; flags exactly `check figure` and `stale source` | unit |

Must not change: existing document upload, ingestion (`_extract_xlsx_text` output included), review
queue and deck routes behave as today (AC-45, AC-46).
