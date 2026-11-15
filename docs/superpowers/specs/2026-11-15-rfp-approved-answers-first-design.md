# RFP answers: approved answers first, then documents in priority order

Status: draft for owner approval, 2026-11-15. Builds on the approved
[RFP agent, part 1](2026-10-21-rfp-answers-design.md) ("part 1" below) and changes none of its rules except
where "Supersedes" says so.

Owner decisions on 2026-11-15:

- The approved answers are the anchor for every new answer. A derived answer should answer the question
  with the least possible change to approved answers, and is checked against them.
- Where the approved answers do not answer a question sufficiently, additional documents are used, in a
  priority order.
- Text taken from a document may be reworded as long as everything is checked.

Two further specs follow this one and are not part of it: updating approved answers from new files, and
statistics from the app's engagement and voting data.

A word on names. The owner calls the approved answers the "golden set". In this repository "golden set"
already means the labelled cases that test the real model (`arp golden-set`, `arp rfp golden`). To keep the
two apart, this spec says **approved answers** or **the library** for the first and **golden check** for
the second.

## Intent

Today auto-fill shows the model the best-matching approved answers and lets it combine, shorten and reword
them freely. The reviewer then has to read every drafted answer in full, because nothing says how far it
moved from text the firm has already approved. And auto-fill can use nothing but the library, so a question
the library does not cover stays blank even when the firm's stewardship statement answers it.

This spec changes both. An approved answer that fits is used unchanged. One that nearly fits is changed as
little as possible, and the reviewer sees exactly which words changed. Only where approved answers do not
cover the question does auto-fill turn to reference documents, in the order the firm ranks them, and only
for the part that is missing.

## Goals

1. An approved answer that answers the new question is used character for character.
2. A drafted answer that departs from an approved answer shows which approved answer it started from, how
   much of it is unchanged, and which words changed.
3. Auto-fill uses documents only when the approved answers do not answer the question, and tries documents
   of priority 1 before priority 2, and so on.
4. An approver can register a reference document (`.pdf` or `.docx`) with a priority.
5. Every figure in a drafted answer is a number of the question, of a cited approved answer, or of a quoted
   document span.
6. A second model checks every draft before a reviewer sees it: that its sources state every fact, and that
   it answers the whole question.

## Anti-goals (a failure even if it technically works)

- An approved answer that fits, reworded anyway.
- A change to approved wording that the reviewer is not shown.
- A document used although the approved answers already answer the question.
- A lower-priority document used although a higher-priority one answers the question.
- A figure in a drafted answer that no source states.
- A retired or replaced document feeding a new draft, or an answer drafted from it being approved without
  the approver being told.
- A scanned PDF read by OCR, with misread digits, used as a source.

## Not in this spec

- Updating approved answers from new files (next spec). That spec also deals with the library filling up
  with repeated answers: as in part 1, every approved answer becomes a library entry, also when it is an
  unchanged copy of one.
- Statistics from engagement and voting data (the spec after that).
- A limit on how much an approved answer may be changed. The change is shown, not capped.
- Reference documents in other formats (`.xlsx`, `.html`, `.pptx`). Excel question-and-answer files still go
  through the part 1 library import.
- A command-line command for registering documents, and a page control for changing a document's title,
  priority or review-by date (the API can).
- Detecting that two sources contradict each other.
- Showing a reviewer why a draft was discarded.

## Constraints

- State lives in Postgres, tables created by `backend/arp/storage/postgres_schema.py` like the part 1 tables.
- Reused as they are: PDF and Word parsing (`ingestion/local_files.py`), passage splitting
  (`ingestion/parsing.py` `chunk_document`), ranking (`retrieval/select_evidence.py`
  `select_relevant_chunks`), quote checking (`grounding.py` `ground_claim` with `passages=`), the verifier
  model (`llm/factory.py` `build_verifier_llm_client`; `schedule_llm_run` already hands it to the RFP run).

## Approaches

**Keeping to approved answers.** Considered: (a) the model may name one approved answer to be used as it
is, and the code copies it; otherwise it adapts one, and the code marks every changed word; (b) the model
always writes the answer and the code rejects drafts that differ too much from approved text; (c) no
drafting at all, the best-matching approved answer is pasted in. Chosen: (a). (b) needs a threshold that is
either too strict for a nearly-fitting answer or too loose to mean anything. (c) leaves every question
whose wording differs from a past one to be fixed by hand.

**Using documents.** Considered: (a) a chain: approved answers alone first, then documents added one
priority at a time, stopping as soon as the question is answered; (b) approved answers and all documents
shown together, with the model told what to prefer. Chosen: (a), as the owner asked. In (b) the order is
only a request to the model; in (a) the code enforces it, because a document that was not shown cannot be
quoted.

**Text from documents.** The owner chose **reword, all checked** over **quote only** (answers built only
from copied sentences read stiff and leave many questions blank).

## How it works

Part 1's shared definitions (location, normalised text, has figures, numbers) apply unchanged. "The model"
is the drafting model; "the second model" is the verifier model. "Today" is the server's date. "Entry"
means an active library entry, that is an approved answer with its question.

### 1. The chain

For each question auto-fill goes through steps and stops at the first one that gives a draft that passes.

- **Step 0, approved answers alone.** The model is shown the top 8 entries for the question (ranked as
  today). Skipped when there is no entry.
- **Step p, for each priority p that an active reference document has, lowest number first.** The model is
  shown the same top 8 entries and the top 8 passages of the active documents with priority p or a lower
  number, ranked together. A passage is a `chunk_document` chunk.

If no step gives a draft that passes, the question stays `no source` with an empty answer, as today.

At every step the model is told: answer from the approved answers; if one answers the question as it is,
name it; otherwise start from the closest one and change as little as possible; use document passages only
for what the approved answers do not cover; say what is still missing rather than guess.

### 2. What the model returns, and when a step passes

`DraftOut` (the model's structured output; names and fields are fixed so tests can supply stand-in answers;
every new field has a default, so part 1's stand-in answers stay valid):

- `use_entry`: the id of an entry that answers the question as it is, or null (default);
- `answer`: the drafted text, when `use_entry` is null;
- `base_entry_id`: the entry the draft started from, or null (default);
- `citations`: each `{entry_id or document_id, quote}`, the quote copied character for character;
- `missing`: the parts of the question the sources shown do not answer (default empty).

A step passes when all of these hold:

1. `missing` is empty.
2. With `use_entry`: it is one of the entries shown. The answer is then that entry's answer, copied by the
   code character for character; `answer` and `citations` are ignored; the one source is that entry with its
   whole answer as the quote.
3. Without `use_entry`: the answer is not empty and has at least one citation. Every quote grounds by
   `ground_claim`'s rules: an entry quote in that entry's answer (as today); a document quote inside the
   passages of that document that were shown at this step.
4. Without `use_entry`: every number in the answer is a number of the question, of a cited entry's answer
   (as today), or of the span a document quote matched in the document. A number elsewhere in the document
   does not count.
5. The second model's check finds nothing (section 3).

A draft that passes is stored with its `priority_step` (0, or the priority p of the step), and its base
entry: with `use_entry`, that entry; otherwise `base_entry_id` when it names a cited entry, else the first
cited entry, else none.

### 3. The second model's check

Once conditions 1 to 4 hold, the second model is given the question, the draft and what supports it: the
whole answer of each cited entry and the matched span of each cited document. It returns `FactCheck`:

- `unsupported`: every fact, figure, date or name in the draft that these do not state (default empty).
  Rewording, shortening and combining are fine.
- `unanswered`: every part of the question the draft does not answer (default empty).

The step passes only when both lists are empty. This runs for every draft, an unchanged approved answer
included (there only `unanswered` can find anything). It costs one more model call per draft checked.
`arp rfp golden drafts` keeps its own check after drafting (part 1 AC-44).

### 4. What the reviewer is shown

`GET /api/rfp/projects/{id}` returns for each question, next to today's fields:

- `priority_step`: 0 when the draft uses approved answers alone, p when it was drafted at document priority
  p, null when nothing was drafted;
- `base_entry_id`: the base entry, or null;
- `kept_share`: the share of the answer's words kept from the base entry's answer, as a whole percentage
  rounded half up; null without a base entry;
- `segments`: the answer cut into runs, each `{text, kept}`, in order; empty without a base entry.

Kept words are worked out by the code, never by a model: the base entry's answer and the question's answer
are each split into words at whitespace and compared with Python's `difflib.SequenceMatcher` (autojunk
off). A word of the answer is kept when it lies in a matching block. A run is a maximal sequence of words
that are all kept or all not kept, joined by single spaces.

(my call) These three are computed when the project is read, from the answer as it stands and the base
entry's answer as it stands. So they follow a colleague's edit, and they follow a later change to the entry.

Each source carries a `kind`. An entry source is returned as today plus `kind` `entry`; a source stored
before this change has no kind and is returned as `entry`. A document source has `kind` `document`, the
document's `document_id`, `title`, `file` and `priority`, the `quote` as it stands in the document (the
matched span), and the `page` the span starts on (`null` for Word).

`stale source` is set when any cited entry or document has `review_by` before today, or a cited document is
retired.

### 5. Reference documents

A reference document holds: title, file name, the original file (blob store), its parsed text and page
starts, a document date, a `review_by` date, a priority (a whole number, 1 or more; 1 is used first), a
status (`active` or `retired`) and who uploaded it. Several documents may share a priority; they are then
used at the same step.

| Endpoint | Who | Does |
|---|---|---|
| `GET /api/rfp/documents` | any signed-in user | Lists all documents by priority, then oldest first: `id` (a whole number), `title`, `filename`, `document_date`, `review_by`, `priority`, `status`, `uploaded_by`, `pages` (page count for a PDF, `null` for Word). |
| `POST /api/rfp/documents` | approver | Multipart: `file`, `title`, `document_date`, `priority` (default 1), `replaces` (optional document id). Parses and stores the document as `active` and returns it as the list does. |
| `PUT /api/rfp/documents/{id}` | approver | JSON body with any of `title`, `review_by` (`YYYY-MM-DD`), `priority`; a field left out stays as it is. |
| `POST /api/rfp/documents/{id}/retire` | approver | Sets status `retired`. |

- An empty `title`, a missing `document_date` or a `priority` below 1 gives 422. `PUT` and `retire` on an
  unknown id give 404 `Reference document not found`.
- The file name must end in `.pdf` or `.docx` (any letter case), else 400
  `<name> is not a .pdf or .docx file.`
- A PDF is refused when `_has_text_layer` is false, that is when fewer than half of its first five pages
  hold 50 characters of text or it cannot be opened: 400
  `<name> has no text layer; upload the original document.` Nothing is stored. (my call) OCR is never used:
  a misread digit would pass every later check.
- `review_by` starts as the document date plus 12 months, by part 1's rule (`plus_12_months`).
- With `replaces`, that document is retired in the same transaction. An unknown `replaces` id gives 404
  `Reference document not found` and nothing is stored.
- (my call) The document date is typed by the approver, never read from the file: PDF dates are often the
  export date.
- (my call) Parsing runs inside the request, like the library import. A long PDF can take a minute.
- Retired documents are never shown to the model. Retiring a document (directly or through `replaces`) adds
  the flag `stale source` to every `drafted` or `edited` question that cites it.

### 6. The page

- On a project, a drafted or edited answer with a base entry shows a line naming the base entry's question
  and how much is unchanged: `Approved answer, unchanged` at 100%, else `<n>% unchanged from the approved
  answer`. Below it the answer is shown read-only with the words that are not kept marked.
- A drafted answer shows where it comes from: `From approved answers only` at `priority_step` 0, else
  `Uses documents (priority <p>)`.
- Each source shows its kind. A document source shows the title, `p. <n>` for a PDF, and the quote.
- RFP Answers gains a section "Reference documents" below "Answer library": a table of priority, title,
  file, document date, review-by date and status. Approvers also see an upload form (file, title, document
  date, priority, optional "Replaces") and a Retire button per active document.

### 7. Golden checks (real model, CI)

`arp rfp golden drafts` cases may hold `documents` (title, text, priority), and each question may carry
`expect`: `unchanged` (an entry answers it as it is), `library` (the entries answer it after a change),
`documents` (only a document answers it) or `none`. The command gains two thresholds:

- `--min-unchanged`: among questions labelled `unchanged`, the share whose answer equals an entry's answer
  character for character;
- `--min-library-first`: among questions labelled `unchanged` or `library` that were drafted, the share with
  no document source.

Two new case files, both fictitious: `backend/arp/golden_set/data/rfp_unchanged_drafts.json` holds a library
and questions labelled `unchanged`, `library` or `none`; `backend/arp/golden_set/data/rfp_chain_drafts.json`
holds a library, two documents of priority 1 and 2, and questions of all four kinds. A threshold is checked
only when the file has a question it applies to, so a case file without `expect` labels (part 1's) is
scored as today. `.github/workflows/golden-set.yml` runs both new files in its RFP step.

### Slices

Two pull requests, each with `Spec: rfp-approved-answers-first-design` and a `Rows:` line.

1. Approved answers first: `use_entry`, the base entry and kept words, the second model's check, the page's
   marks. No documents. AC-1 to AC-14, AC-36, AC-38, AC-39.
2. Reference documents and the chain: AC-15 to AC-35, AC-37, AC-40 to AC-44, and AC-38 and AC-39 again.

Both change the database schema or a workflow file, so both are `risk:high`.

### Left to the builder

Table and column names; passage size; the wording of the model's instructions; the page's layout within
section 6.

## Supersedes

- Part 1 section 3 told the model to "combine and shorten entries and fit the wording to the question". It
  is now told to change as little as possible (section 1). Part 1 AC-14 to AC-18 still hold.
- Part 1 section 3 "every number comes from a cited entry or the question" is widened by condition 4.
- Part 1 AC-44 stays. The same check now also runs inside drafting (AC-10).

## Acceptance

Checked by.

- `holdout`: a hidden test against the app started by `backend/scripts/e2e_stack.sh up` with
  `ARP_STANDINS_DIR` set. The test writes the stand-in answers as `model/DetectedQuestions.json`,
  `model/QuotedPairs.json`, `model/DraftOut.json` and `model/FactCheck.json`; a stand-in gives the same
  answer at every step of the chain. That app signs every request in as one approver, so `bob` in a
  `holdout` row is that user. The hidden tests share one app and database, so a `holdout` row first retires
  every active library entry and every active reference document the two lists show. Whether
  `HOLDOUT_TOKEN` is set is not known to the author; if it is not, the pull request lists its `holdout` rows
  as owed and covers them with its own tests.
- `unit`: the implementer's test, with both models replaced by stand-ins. Used where the hidden test's app
  cannot be in the Given: a second user or role, a fixed "today", a PDF parse, stand-in answers that differ
  from step to step, or data written before this change. A unit row may replace the Docling PDF parse with a
  stand-in that returns the fixture text and its page start, as
  `backend/tests/test_local_files_pdf_pages.py` does; the text-layer check runs for real.
- "unit (browser)": a Playwright test in `backend/tests/e2e` with the RFP API routes stubbed, as
  `test_rfp_page.py` does.
- `evaluator`: the app started by `backend/scripts/e2e_stack.sh up`, used through the browser, no model call.
- `golden`: the real models.

In every row "the stand-in" is the drafting model's and "the second stand-in" the verifier's. Unless a row
says otherwise the second stand-in returns two empty lists. An existing test file may be changed only to
give the second model a stand-in; the pull request lists each such change.

Fixtures:

- Users in unit rows as in part 1: `alice` (analyst), `bob` and `carol` (approvers), `vic` (viewer).
- "Today" in unit rows is 2026-11-15.
- `LIB`: part 1's `lib_past.xlsx` imported, the import stand-in returning its three pairs. `FIRM` is the
  entry with the question `Describe your firm.` and the answer `Example AM is an independent manager founded
  in 2004.`; its id is read from `GET /api/rfp/library`.
- `ref_stmt.docx`: `P0` `Stewardship Statement 2025` (`Heading 1`); `P1` `We engage with investee companies
  on climate, governance and human rights.`; `P2` `In 2025 we held 512 engagement meetings with 340
  companies.`; `P3` `We vote at all meetings where we hold shares.`
- `ref_stmt.pdf`: the same text drawn with reportlab, `P0` and `P1` on page 1, `P2` and `P3` on page 2.
- `ref_policy.docx`: `P0` `Voting Policy 2025` (`Heading 1`); `P1` `We vote against the re-election of
  directors where board independence falls below one half.`
- `ref_scan.pdf`: one page holding only an image, no text.
- "Uploads X" means with title `Stewardship Statement 2025`, document date 2025-12-31 and no priority
  unless the row says otherwise.
- `DOC`: `bob` uploads `ref_stmt.docx`, then sets its `review_by` to 2099-12-31 with `PUT`. `DOC-PDF`: the
  same with `ref_stmt.pdf`. `DOC-OLD`: `bob` uploads `ref_stmt.docx` with document date 2024-12-31 (so its
  `review_by` is 2025-12-31). `DOC-2`: `bob` uploads `ref_policy.docx` with title `Voting Policy 2025` and
  priority 2, then sets its `review_by` to 2099-12-31.
- A "question" is the one question of a project made from `rfp_one.xlsx`: one sheet `RFP`, `A1` the
  question's text, `B1` empty; the detection stand-in reports it at `RFP!A1` with answer location `RFP!B1`.
  The library is empty and there are no reference documents unless the row says otherwise.
- `Q-FIRM`: `Please describe your firm.` `Q-TOPICS`: `Which topics do you engage on?` `Q-MEET`: `How many
  engagement meetings did you hold in 2025?` `Q-BOARD`: `When do you vote against directors?`
- `D-ASSET`: the stand-in drafts `Example AM is an independent asset manager founded in 2004.` citing `FIRM`
  with quote `founded in 2004`.
- `T-QUOTE`: the stand-in drafts `We engage on climate, governance and human rights.` citing the document
  with quote `climate, governance and human rights`.
- `B-QUOTE`: the stand-in drafts `We vote against directors where board independence falls below one half.`
  citing `DOC-2` with quote `board independence falls below one half`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | `LIB`; the stand-in returns `use_entry` = the id of `FIRM` | auto-fill `Q-FIRM` | status `drafted`; answer `Example AM is an independent manager founded in 2004.` | holdout |
| AC-2  | as AC-1 | read the question | `base_entry_id` is the id of `FIRM`; `kept_share` 100; `priority_step` 0; `segments` is one run with `kept` true | holdout |
| AC-3  | as AC-1 | read the question's sources | exactly one, with `kind` `entry`, the id of `FIRM` and the quote `Example AM is an independent manager founded in 2004.` | holdout |
| AC-4  | `LIB`; the stand-in returns `use_entry` = an id no entry has | auto-fill `Q-FIRM` | status `no source`, answer empty | holdout |
| AC-5  | `LIB`; `D-ASSET` | auto-fill `Q-FIRM` | status `drafted`; `base_entry_id` is the id of `FIRM`; `kept_share` 90 | holdout |
| AC-6  | as AC-5 | read the question's `segments` | exactly three: `Example AM is an independent` kept, `asset` not kept, `manager founded in 2004.` kept | holdout |
| AC-7  | the answer of AC-1 | `bob` `PUT`s the answer `Example AM is an independent asset manager founded in 2004.` | status `edited`; `base_entry_id` is still the id of `FIRM`; `kept_share` 90 | holdout |
| AC-8  | `LIB`; a question with status `no source` | `bob` `PUT`s the answer `We do not lend securities.` | `base_entry_id` null; `kept_share` null; `segments` empty; `priority_step` null | holdout |
| AC-9  | `LIB`; `D-ASSET`, but `missing` is [`the firm's size`] | auto-fill `Q-FIRM` | status `no source`, answer empty | holdout |
| AC-10 | `LIB`; `D-ASSET`; the second stand-in returns `unsupported` [`asset manager`] | auto-fill `Q-FIRM` | status `no source`, answer empty | holdout |
| AC-11 | `LIB`; the stand-in returns `use_entry` = the id of `FIRM`; the second stand-in returns `unanswered` [`the firm's size`] | auto-fill `Q-FIRM` | status `no source`, answer empty | holdout |
| AC-12 | RFP routes stubbed: a drafted answer `Example AM is an independent asset manager founded in 2004.` with `kept_share` 90, the segments of AC-6, a base entry whose question is `Describe your firm.` and `priority_step` 0 | open the project page | the answer's card shows `90% unchanged from the approved answer`, `Describe your firm.`, `From approved answers only`, and the word `asset` marked while `Example` is not | unit (browser) |
| AC-13 | RFP routes stubbed: a drafted answer with `kept_share` 100 and `priority_step` 0 | open the project page | the answer's card shows `Approved answer, unchanged` | unit (browser) |
| AC-14 | a question whose stored source is `{"entry_id", "quote"}` with no kind, as part 1 wrote it | `GET /api/rfp/projects/{id}` | 200; that source has `kind` `entry` | unit |
| AC-15 | no reference documents | `bob` uploads `ref_stmt.docx` | 200; `GET /api/rfp/documents` lists exactly one document: `title` `Stewardship Statement 2025`, `filename` `ref_stmt.docx`, `document_date` 2025-12-31, `review_by` 2026-12-31, `priority` 1, `status` `active`, `uploaded_by` `bob`, `pages` null | unit |
| AC-16 | no reference documents | `alice` uploads `ref_stmt.docx` | 403; `GET /api/rfp/documents` lists nothing | unit |
| AC-17 | any reference documents | `bob` uploads `notes.txt` | 400 with detail `notes.txt is not a .pdf or .docx file.`; `GET /api/rfp/documents` returns the same documents as before | holdout |
| AC-18 | any reference documents | `bob` uploads `ref_scan.pdf` | 400 with detail `ref_scan.pdf has no text layer; upload the original document.`; `GET /api/rfp/documents` returns the same documents as before | holdout |
| AC-19 | `DOC-PDF` | `GET /api/rfp/documents` | its `pages` is 2 | unit |
| AC-20 | `DOC-OLD` | `bob` uploads `ref_stmt.docx` with `replaces` = the id of `DOC-OLD` | 200; in the list `DOC-OLD` has `status` `retired` and the new document `status` `active` | holdout |
| AC-21 | `DOC` | `bob` uploads `ref_stmt.docx` with `replaces` = an id no document has | 404 with detail `Reference document not found`; `GET /api/rfp/documents` returns the same documents as before | holdout |
| AC-22 | `DOC` | `alice` calls `POST /api/rfp/documents/{id}/retire` | 403; its `status` is `active` | unit |
| AC-23 | `DOC`, then retired by `bob`; `T-QUOTE` citing it | auto-fill `Q-TOPICS` | status `no source`, answer empty | holdout |
| AC-24 | `DOC`; `T-QUOTE` citing it | auto-fill `Q-TOPICS` | status `drafted`; `priority_step` 1; exactly one source, with `kind` `document`, `title` `Stewardship Statement 2025`, `file` `ref_stmt.docx`, `priority` 1, `quote` `climate, governance and human rights`, `page` null; flags empty; `base_entry_id` null | holdout |
| AC-25 | `DOC-PDF`; the stand-in drafts `We held 512 engagement meetings in 2025.` citing it with quote `512 engagement meetings` | auto-fill `Q-MEET` | status `drafted`; the source's `page` is 2; flags exactly `check figure` | unit |
| AC-26 | `DOC`; the stand-in drafts `We held 600 engagement meetings in 2025.` citing `DOC` with quote `600 engagement meetings` | auto-fill `Q-MEET` | status `no source`, answer empty | holdout |
| AC-27 | `DOC`; the stand-in drafts `We held 512 engagement meetings with 340 companies.` citing `DOC` with quote `512 engagement meetings` | auto-fill `Q-MEET` | status `no source`, answer empty (340 is in the document but not in the quote) | holdout |
| AC-28 | `DOC-OLD`; `T-QUOTE` citing it | auto-fill `Q-TOPICS` | status `drafted`; flags exactly `stale source` | holdout |
| AC-29 | `DOC` and `DOC-2`; `B-QUOTE` | auto-fill `Q-BOARD` | status `drafted`; `priority_step` 2; the one source has `priority` 2 | holdout |
| AC-30 | `DOC` and `DOC-2`; `T-QUOTE` citing `DOC` | auto-fill `Q-TOPICS` | status `drafted`; `priority_step` 1 | holdout |
| AC-31 | `LIB` and `DOC`; the stand-in returns `use_entry` = the id of `FIRM` | auto-fill `Q-FIRM` | status `drafted`; `priority_step` 0; no source has `kind` `document` | holdout |
| AC-32 | `LIB` and `DOC`; at step 0 the stand-in returns `D-ASSET` with `missing` [`engagement topics`]; at step 1 it drafts `Example AM is an independent manager founded in 2004. We engage on climate, governance and human rights.` citing `FIRM` with quote `an independent manager founded in 2004` and `DOC` with the quote of `T-QUOTE` | auto-fill the question `Describe your firm and the topics you engage on.` | status `drafted`; `priority_step` 1; exactly two sources, the first with `kind` `entry`, the second with `kind` `document`; `base_entry_id` is the id of `FIRM`; `kept_share` 53 | unit |
| AC-33 | the answer of AC-24 | `bob` retires `DOC` | the question's flags are exactly `stale source` | holdout |
| AC-34 | the answer of AC-24 | `bob` uploads `ref_stmt.docx` with `replaces` = the id of `DOC` | the question's flags are exactly `stale source` | holdout |
| AC-35 | `DOC` | `bob` calls `PUT /api/rfp/documents/{id}` with only `priority` 3 | 200; `GET /api/rfp/documents` shows its `priority` 3 and its `title` `Stewardship Statement 2025` | holdout |
| AC-36 | `backend/arp/golden_set/data/rfp_unchanged_drafts.json` | `arp rfp golden drafts --cases <file> --min-drafted 0.90 --min-blank 0.95 --min-unchanged 0.90` | exits 0: at least 90% of answerable questions `drafted`, at least 95% of `none` questions `no source`, at least 90% of the questions labelled `unchanged` come back equal to an entry's answer character for character, and 0 drafts state a fact their sources do not | golden |
| AC-37 | `backend/arp/golden_set/data/rfp_chain_drafts.json` | `arp rfp golden drafts --cases <file> --min-drafted 0.90 --min-blank 0.95 --min-unchanged 0.90 --min-library-first 0.95` | exits 0: at least 90% of answerable questions `drafted`, at least 95% of `none` questions `no source`, at least 95% of drafted `unchanged` and `library` questions have no document source, and 0 drafts state a fact their sources do not | golden |
| AC-38 | this change | `arp rfp golden questions` and `arp rfp golden drafts` on the part 1 case files with the part 1 thresholds | both exit 0 | golden |
| AC-39 | this change | run the existing backend and frontend suites | all pass | unit |
| AC-40 | RFP routes stubbed: a drafted answer with one document source (`title` `Stewardship Statement 2025`, `page` 2, quote `512 engagement meetings`) and `priority_step` 2 | open the project page | the answer's card shows `Uses documents (priority 2)`, `Stewardship Statement 2025`, `p. 2` and `512 engagement meetings` | unit (browser) |
| AC-41 | the app, signed in as an approver | open RFP Answers, upload a `.docx` under "Reference documents" with a title, a document date and priority 2 | the table under "Reference documents" shows a row with priority 2, that title, the file name, the document date, a review-by date 12 months later and status `active` | evaluator |
| AC-42 | as AC-41, the document uploaded | press Retire on its row | the row's status reads `retired` and it has no Retire button | evaluator |
| AC-43 | any reference documents | `bob` calls `PUT /api/rfp/documents/{id}` with an id no document has | 404 with detail `Reference document not found` | holdout |
| AC-44 | any reference documents | `bob` uploads `ref_stmt.docx` with a title and no document date | 422; `GET /api/rfp/documents` returns the same documents as before | holdout |

Must not change: part 1's library import, question detection, editing, four-eyes approval and export behave
as today (AC-39); part 1's golden thresholds still hold (AC-38); projects drafted before this change still
load (AC-14).
