# RFP answers from reference documents and the app's own data

Status: draft for owner approval, 2026-11-15. Builds on the approved
[RFP agent, part 1](2026-10-21-rfp-answers-design.md) ("part 1" below) and changes none of its rules except
where "Supersedes" says so. Owner decisions on 2026-11-15: auto-fill may use two more kinds of source,
reference documents (Word and PDF) and statistics from the app's engagement and voting data; text taken from
a document may be reworded as long as everything is checked; statistics are answered by free questions (the
model writes the query), not from a fixed list.

## Intent

Today auto-fill can only use the answer library: question-and-answer pairs from past RFP responses and from
answers approved in the app. Much of what an investor asks is answered elsewhere: in documents such as the
firm's stewardship statement, and in the engagement and voting records the app already holds. Colleagues
copy those by hand, which is slow and is where wrong figures get in.

This spec lets auto-fill draw on those sources, under one rule: nothing reaches a reviewer unless the code
could check it. Text must be quoted from an approved source. A figure must either sit inside such a quote or
be computed by the code from the app's data. The model never types a statistic's digits.

## Goals

1. An approver can register a reference document (`.pdf` or `.docx`) and auto-fill can draft from it.
2. Every drafted answer shows, for each source, what kind it is and exactly what supports the answer: the
   quote with file and page for a document; the definition, value and time of computation for a statistic.
3. A figure in a drafted answer is always one of: a number in the question, a number in a cited library
   entry, a number inside a quoted document span, a statistic the code computed and wrote in, or the year
   of a statistic's period.
4. A second model checks every draft before a reviewer sees it. A draft with a fact its sources do not state
   is discarded.
5. A question about engagement or voting activity can be answered with a statistic the model asks for and
   the code computes, shown with a plain definition the approver must confirm.
6. A statistic computed from demo data can never be approved by accident, and never enters the library.

## Anti-goals (a failure even if it technically works)

- A figure in a drafted answer that no source states and the code did not compute.
- A statistic whose wording says something other than what was counted (wrong period, wrong filter).
- A demo figure in a file that goes to an investor, or in the answer library.
- A retired or replaced document feeding a new draft, or an answer drafted from it being approved without
  the approver being told.
- A scanned PDF read by OCR, with misread digits, used as a source.

## Not in this spec

- Fixed, named statistics (a catalogue). The owner chose free questions.
- Breakdowns (a value per theme, per year). A statistic is one number. An answer may hold up to six.
- Sums and averages. Statistics are counts, distinct counts and shares.
- Recomputing a statistic after the draft. It is shown with its time of computation.
- Data other than engagement and voting (holdings, extracted company facts, financials).
- Reference documents in other formats (`.xlsx`, `.html`, `.pptx`). Excel question-and-answer files still go
  through the part 1 library import.
- A command-line command for registering documents, and a page control for changing a document's title or
  review-by date (the API can).
- Detecting that two sources contradict each other.
- Showing a reviewer why a draft was discarded.

## Constraints

- State lives in Postgres, tables created by `backend/arp/storage/postgres_schema.py` like the part 1 tables.
- Statistics read the app's tables with `SELECT` only.
- Reused as they are: PDF and Word parsing (`ingestion/local_files.py`), passage splitting
  (`ingestion/parsing.py` `chunk_document`), ranking (`retrieval/select_evidence.py`
  `select_relevant_chunks`), quote checking (`grounding.py` `ground_claim` with `passages=`), the verifier
  model (`llm/factory.py` `build_verifier_llm_client`; `schedule_llm_run` already hands it to the RFP run).

## Approaches

**Text from documents.** Considered: (a) passages of the document are shown to the model next to library
entries, and the model quotes them; (b) on upload, a model turns the document into question-and-answer pairs
for the library. Chosen: (a). In (b) the questions are invented and the page is lost. Within (a) the owner
chose **reword, all checked** over **quote only** (answers built only from copied sentences read stiff and
leave many questions blank).

**Statistics.** Considered: (A) a fixed catalogue of named, tested statistics; (B) free questions, where the
model writes the query; (C) statistics computed nightly and stored as library text. Recommended: A. **The
owner chose B.** B answers far more questions; its risk is a query that looks right and counts the wrong
thing. The guards below reduce that risk. They do not remove it: two models can make the same mistake, so
the approver's check of the definition is the last line.

Guards for B (my calls):

1. The model's query is a small form (dataset, measure, filters, period), not SQL. The code checks every
   name and value against the data before running it.
2. The code computes the value and writes it into the answer. The model writes only a placeholder.
3. The second model writes its own query for the same placeholder without seeing the first. The two values
   must be equal.
4. The code writes a definition sentence from the query. The reviewer sees it and must confirm the flag
   `check statistic`.
5. A statistic that counts nothing is rejected, because zero most often means a wrong filter.

## How it works

Part 1's shared definitions (location, normalised text, has figures, numbers) apply unchanged. "The model"
is the drafting model; "the second model" is the verifier model. "Today" is the server's date.

### 1. Reference documents

A reference document holds: title, file name, the original file (blob store), its parsed text and page
starts, a document date, a `review_by` date, a status (`active` or `retired`) and who uploaded it.

| Endpoint | Who | Does |
|---|---|---|
| `GET /api/rfp/documents` | any signed-in user | Lists all documents, oldest first: `id`, `title`, `filename`, `document_date`, `review_by`, `status`, `uploaded_by`, `pages` (page count for a PDF, `null` for Word). |
| `POST /api/rfp/documents` | approver | Multipart: `file`, `title`, `document_date`, `replaces` (optional document id). Parses and stores the document as `active`. |
| `PUT /api/rfp/documents/{id}` | approver | Changes `title` and `review_by`; a field left out stays as it is. |
| `POST /api/rfp/documents/{id}/retire` | approver | Sets status `retired`. |

- An empty `title` or a missing `document_date` gives 422. `PUT` and `retire` on an unknown id give 404
  `Reference document not found`.
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

### 2. Drafting from documents

For each question auto-fill ranks two lists separately: the top 8 active library entries (as today) and the
top 8 passages of active reference documents. A passage is a `chunk_document` chunk. Both lists go to the
model. (my call) Separate lists, so a long document cannot crowd out approved answers.

The model is called for a question when there is at least one ranked entry, one ranked passage or one
dataset row (section 4). Each citation names one library entry or one reference document, with a quote the
model is told to copy character for character. A draft needs at least one citation or one statistic. It is
kept only if all of these hold; otherwise the question stays `no source` with an empty answer:

1. Every quote grounds by `ground_claim`'s rules: an entry quote in that entry's answer (as today); a
   document quote inside the passages of that document that were shown to the model.
2. Every number in the answer is a number of the question, of a cited entry's answer (as today), or of the
   span a document quote matched in the document. A number elsewhere in the document does not count.
3. The second model finds no unsupported fact (section 3).

A document source is stored and returned with `kind` `document`, the document's `document_id`, `title` and
`file`, the `quote` as it stands in the document (the matched span), and the `page` the span starts on
(`null` for Word). An entry source is returned as today plus `kind` `entry`; a source stored before this
change has no kind and is returned as `entry`.

`stale source` is set when any cited entry or document has `review_by` before today, or a cited document is
retired.

### 3. The second model's check

After checks 1 and 2 pass, the second model is given the draft and what supports it: the whole answer of each
cited entry, the matched span of each cited document, and for each statistic its definition and value
(section 4). It lists every fact, figure, date or name in the draft that these do not state, and every
statistic whose surrounding wording does not match its definition. Rewording, shortening and combining are
fine. If the list is not empty the draft is discarded.

This applies to every draft, library-only ones included. It costs one more model call per drafted question.
`arp rfp golden drafts` keeps its own check after drafting (part 1 AC-44), so a golden draft is checked
twice.

### 4. Statistics

**Datasets.** Four read-only datasets. Each row carries the `source` of the record it comes from.

| Dataset | One row per | Date columns | Other columns |
|---|---|---|---|
| `engagements` | `stw_engagements` row | `started_at` | `engagement_id`, `company_id`, `company_name`, `sector`, `theme`, `status`, `escalation_stage`, `milestone_stage`, `esg_pillars` (list), `source` |
| `objectives` | `stw_objectives` row | `started_at`, `closed_at` | `objective_id`, `engagement_id`, `company_id` and `theme` (its engagement's), `objective_type`, `status`, `outcome`, `influence_level`, `escalated`, `source` |
| `activities` | `stw_activities` row | `occurred_at` | `activity_id`, `engagement_id`, `company_id` and `theme` (its engagement's), `activity_type`, `interaction_type`, `is_initiation`, `source` |
| `votes` | `vote_decisions` row | `meeting_date` | `decision_id`, `meeting_id` (its item's), `company_id`, `issuer_name`, `isin`, `meeting_type`, `proponent`, `management_recommendation`, `categories` (list), `vote`, `against_management`, `source` |

- `company_name` and `sector` come from `stw_companies`; `meeting_date`, `meeting_type`, `issuer_name`,
  `isin` and `company_id` of a vote from its meeting; `proponent`, `management_recommendation` and
  `categories` from its item.
- Values are compared as text; booleans read `true` and `false`. A value that is not set is empty and
  matches no filter.
- A row's date is the UTC date of its timestamp.
- (my call) `engagements`, `objectives` and `activities` can be queried only when the setting
  `engagement_store` is `postgres`. With the file store the `stw_` tables may hold partial rows, so a query
  on them rejects the draft. `votes` can always be queried.

**Structured outputs.** These names and fields are fixed, so tests can supply stand-in answers:

- `DraftOut` (drafting model): `answer`; `citations`, each `{entry_id or document_id, quote}`;
  `statistics`, a list of queries.
- A query: `id`, `dataset`, `measure`, `column`, `filters`, `share_filters`, `date_column`, `date_from`,
  `date_to`.
- `SecondQueries` (second model): `statistics`, a list of queries.
- `FactCheck` (second model): `unsupported`, a list of strings.

**The query.**

- `id`: `S1` to `S6`, matching a placeholder `{S1}` in the answer;
- `dataset`: one of the four;
- `measure`: `count` (rows), `count_distinct` (distinct values of `column`) or `share`;
- `column`: for `count_distinct` only, a column that is neither a date nor a list;
- `filters`: column to list of values; a row matches when its value is one of them (for a list column, when
  the list holds one of them); all filters must match;
- `share_filters`: for `share` only, same form, at least one;
- `date_column`, `date_from`, `date_to`: a date column of the dataset and an inclusive period. All required.
  Rows with no date in that column are never counted. (my call) When the question names no period, the model
  is told to use the last full calendar year before today and to name that year in the answer.

**The code rejects the whole draft** (`no source`, empty answer) when any of these holds:

- a dataset, measure or column is unknown, a filter is on a date column, or `column` is a date or a list;
- a filter value does not occur in that column anywhere in the dataset (exact match);
- a date is missing or not a date, or `date_from` is after `date_to`;
- a placeholder has no query, a query has no placeholder, or there are more than six;
- the statistic counts nothing: no row matches (for `share`, the denominator is zero), or a distinct count
  is zero;
- the second model's value differs (below).

**The value.** `count`: the number of rows that match `filters` in the period. `count_distinct`: the number
of distinct non-empty values of `column` among those rows. `share`: among the rows that match `filters` in
the period and have a value in every `share_filters` column, those that match `share_filters`, divided by
all of them. Rows left out because such a value is empty are counted as `left_out`. The code writes a count
as digits with `,` between thousands (`1,204`) and a share as a percentage rounded half up to one decimal
(`6.25` becomes `6.3%`), and puts it in place of the placeholder.

**The definition.** Written by the code, never by a model:

- `count`: `Number of <dataset><where>; <date_column> from <date_from> to <date_to>.`
- `count_distinct`: `Number of distinct <column> in <dataset><where>; <date_column> from <date_from> to <date_to>.`
- `share`: `Share of <dataset> with <share filters> among <dataset><where>; <date_column> from <date_from> to <date_to>.`

`<where>` is empty without filters, else ` where ` and the filters. Filters are written `<column> = <value>`,
several values as `<column> = <v1> or <v2>`, several filters joined with ` and `, in the order the query
gave them. Dates are `YYYY-MM-DD`.

**The second query.** In a call of its own, the second model gets the question, the answer with its
placeholders and the same dataset description. It never sees the first model's queries, definitions or
values. It writes its own query for each placeholder (`SecondQueries`). The code runs both. Every
placeholder's two written values must be equal, and the second queries must pass the same checks. The fact
check of section 3 is a later, separate call.

**Numbers.** Check 2 of section 2 runs on the answer with the placeholders taken out. It also allows the
year of each statistic's `date_from` and `date_to`.

**What is stored and returned** for a statistic source: `kind` `statistic`, the query, the `definition`, the
written `value`, the `numerator` (for a count, the count itself), the `denominator` and `left_out` (for a
share, else `null`), `computed_at` (ISO 8601, UTC), and `data_sources`: the distinct `source` values of the
rows counted (for a share, of the denominator's rows).

**Flags.** `check statistic` on every answer with a statistic source. `demo data` when any statistic's
`data_sources` holds `mock_voice_seed` or `npx_urth_demo`. Both are kept when a colleague edits the answer.
The approver confirms `check statistic` like every flag. An answer flagged `demo data` cannot be approved:
409 `This answer uses demo data and cannot be approved.` (my call) A new setting
`rfp_allow_demo_statistics` (`ARP_RFP_ALLOW_DEMO_STATISTICS`, default `false`) lifts this for demos; the
flag then must be confirmed like the others, and the approved answer makes no library entry.

Any other approved answer still becomes a library entry, as in part 1. Known limit: an entry made from an
answer with a statistic carries that figure forward; a later draft from it has the flag `check figure`, as
every answer with a digit does.

### 5. The page

- RFP Answers gains a section "Reference documents" below "Answer library": a table of title, file,
  document date, review-by date and status. Approvers also see an upload form (file, title, document date,
  optional "Replaces") and a Retire button per active document.
- On a project, each source of an answer shows its kind. A document source shows the title, `p. <n>` for a
  PDF, and the quote. A statistic source shows the value, the definition, the row counts (`2 of 8` for a
  share, followed by `1 left out` when rows were left out; the count for the others) and the time of
  computation as `15 Nov 2026, 09:30 UTC`.

### 6. Golden checks (real model, CI)

- `arp rfp golden drafts` cases may hold `documents` (title and text). New case file
  `backend/arp/golden_set/data/rfp_document_drafts.json`: a fictitious stewardship statement and questions
  labelled answerable or unanswerable.
- New command `arp rfp golden statistics --cases <file> --min-drafted <x> --min-blank <y>`. The case file
  `backend/arp/golden_set/data/rfp_statistics.json` holds `today`, fictitious rows for the four datasets and
  questions labelled with their expected written values, or as unanswerable. The command uses the file's
  `today`, treats all four datasets as queryable, and reads no application table. It exits 1 below either
  threshold, and when any drafted answer's written values differ from the labelled ones.
- `.github/workflows/golden-set.yml` runs both in its RFP step.

### Slices

Two pull requests, each with `Spec: rfp-reference-sources-design` and a `Rows:` line.

1. Reference documents and the second model's check: AC-1 to AC-21, AC-40, AC-42 to AC-44, AC-46, AC-47,
   AC-56, AC-57.
2. Statistics: AC-22 to AC-39, AC-41, AC-45, AC-48 to AC-55, AC-58, and AC-42 and AC-43 again.

Both change the database schema or a workflow file, so both are `risk:high`.

### Left to the builder

Table and column names; passage size; how the model is told the columns and their values; how the
statistics are computed (SQL or in memory), as long as the golden command needs no application table; the
page's layout within section 5.

## Supersedes

- Part 1 AC-44 stays. The same check now also runs inside drafting (AC-15, AC-16).
- Part 1 section 3 "every number comes from a cited entry or the question" is widened by check 2 above.
  Part 1 AC-16 to AC-18 still hold.

## Acceptance

Checked by.

- `holdout`: a hidden test against the app started by `backend/scripts/e2e_stack.sh up` with
  `ARP_STANDINS_DIR` set. The test writes the stand-in answers as `model/DetectedQuestions.json`,
  `model/DraftOut.json` and `model/FactCheck.json`. That app signs every request in as one approver, so
  `bob` in a `holdout` row is that user. Whether `HOLDOUT_TOKEN` is set is not known to the author; if it is
  not, the pull request lists its `holdout` rows as owed and covers them with its own tests.
- `unit`: the implementer's test, with both models replaced by stand-ins. Used where the hidden test's app
  cannot be in the Given: a second user or role, a fixed "today", a PDF parse, the part 1 library, or
  dataset rows. (my call) The statistics rows are `unit` so that this spec need not pin the stewardship
  intake format; the owner can ask for hidden tests on them later. A unit row may replace the Docling PDF
  parse with a stand-in that returns the fixture text and its page start, as
  `backend/tests/test_local_files_pdf_pages.py` does; the text-layer check runs for real.
- "unit (browser)": a Playwright test in `backend/tests/e2e` with the RFP API routes stubbed, as
  `test_rfp_page.py` does.
- `evaluator`: the app started by `backend/scripts/e2e_stack.sh up`, used through the browser, no model call.
- `golden`: the real models.

In every row "the stand-in" is the drafting model's and "the second stand-in" the verifier's. Unless a row
says otherwise the second stand-in reports nothing unsupported and returns the same queries as the stand-in.
An existing test file may be changed only to give the second model a stand-in; the pull request lists each
such change.

Fixtures:

- Users in unit rows as in part 1: `alice` (analyst), `bob` and `carol` (approvers), `vic` (viewer).
- "Today" in unit rows is 2026-11-15. `rfp_allow_demo_statistics` is `false` and `engagement_store` is
  `postgres` unless a row says otherwise.
- `ref_stmt.docx`: `P0` `Stewardship Statement 2025` (`Heading 1`); `P1` `We engage with investee companies
  on climate, governance and human rights.`; `P2` `In 2025 we held 512 engagement meetings with 340
  companies.`; `P3` `We vote at all meetings where we hold shares.`
- `ref_stmt.pdf`: the same text drawn with reportlab, `P0` and `P1` on page 1, `P2` and `P3` on page 2.
- `ref_scan.pdf`: one page holding only an image, no text.
- "Uploads X" means with title `Stewardship Statement 2025` and document date 2025-12-31 unless the row
  says otherwise.
- `DOC`: `bob` uploads `ref_stmt.docx`, then sets its `review_by` to 2099-12-31 with `PUT`. `DOC-PDF`: the
  same with `ref_stmt.pdf`. `DOC-OLD`: `bob` uploads `ref_stmt.docx` with document date 2024-12-31 (so its
  `review_by` is 2025-12-31).
- A "question" is the one question of a project made from `rfp_one.xlsx`: one sheet `RFP`, `A1` the
  question's text, `B1` empty; the detection stand-in reports it at `RFP!A1` with answer location `RFP!B1`.
  The library is empty unless the row says otherwise.
- `Q-TOPICS`: `Which topics do you engage on?` `Q-MEET`: `How many engagement meetings did you hold in 2025?`
  `Q-VOTE`: `What share of votes did you cast against management in 2025?` `Q-COMP`: `How many companies
  did you engage with in 2025?`
- `ROWS`. `votes`: 9 rows with `meeting_date` in 2025, one of them at 2025-12-31T15:00:00Z; of the 9, 2 have
  `against_management` `true`, 6 `false` and 1 no value; and 2 rows in 2024, 1 of them `true`, 1 `false`.
  `activities`: 5 rows with `occurred_at` in 2025, one of them at 2025-12-31T15:00:00Z, for companies `c1`,
  `c1`, `c2`, `c3`, `c3`; and 1 row in 2024 for `c4`. Each activity belongs to an engagement of its company
  with `theme` `climate`. Vote rows have `source` `ledger_test`, engagement and activity rows `voice_test`.
- `ROWS-DEMO`: `ROWS` with every `source` `npx_urth_demo`. `ROWS-16`: `votes` holds 16 rows in 2025, 1 of
  them `against_management` `true`, 15 `false`. `ROWS-1204`: `activities` holds 1,204 rows in 2025.
- `S-VOTE`: the query `S1`, dataset `votes`, measure `share`, `share_filters` `against_management` = `true`,
  no filters, `date_column` `meeting_date`, 2025-01-01 to 2025-12-31. `S-COMP`: `S1`, dataset `activities`,
  measure `count_distinct`, `column` `company_id`, no filters, `date_column` `occurred_at`, 2025-01-01 to
  2025-12-31.
- `A-VOTE`: the stand-in drafts `In 2025 we voted against management on {S1} of items.` with `S-VOTE` and no
  citation. `A-COMP`: it drafts `We engaged with {S1} companies in 2025.` with `S-COMP` and no citation.
- `T-QUOTE`: the stand-in drafts `We engage on climate, governance and human rights.` citing the document
  with quote `climate, governance and human rights`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | no reference documents | `bob` uploads `ref_stmt.docx` | 200; `GET /api/rfp/documents` lists exactly one document: `title` `Stewardship Statement 2025`, `filename` `ref_stmt.docx`, `document_date` 2025-12-31, `review_by` 2026-12-31, `status` `active`, `uploaded_by` `bob`, `pages` null | unit |
| AC-2  | no reference documents | `alice` uploads `ref_stmt.docx` | 403; `GET /api/rfp/documents` lists nothing | unit |
| AC-3  | no reference documents | `bob` uploads `notes.txt` | 400 with detail `notes.txt is not a .pdf or .docx file.`; the list is empty | holdout |
| AC-4  | no reference documents | `bob` uploads `ref_scan.pdf` | 400 with detail `ref_scan.pdf has no text layer; upload the original document.`; the list is empty | holdout |
| AC-5  | `DOC-PDF` | `GET /api/rfp/documents` | its `pages` is 2 | unit |
| AC-6  | `DOC-OLD` | `bob` uploads `ref_stmt.docx` with `replaces` = the id of `DOC-OLD` | 200; the list holds `DOC-OLD` with `status` `retired` and the new document with `status` `active` | holdout |
| AC-7  | `DOC` | `bob` uploads `ref_stmt.docx` with `replaces` = an id no document has | 404 with detail `Reference document not found`; the list still holds exactly one document | holdout |
| AC-8  | `DOC` | `alice` calls `POST /api/rfp/documents/{id}/retire` | 403; its `status` is `active` | unit |
| AC-9  | `DOC` | `bob` calls `POST /api/rfp/documents/{id}/retire` | 200; its `status` is `retired` | holdout |
| AC-10 | `DOC`, retired; `T-QUOTE` citing it | auto-fill `Q-TOPICS` | status `no source`, answer empty | holdout |
| AC-11 | `DOC`; `T-QUOTE` citing it | auto-fill `Q-TOPICS` | status `drafted`; exactly one source, with `kind` `document`, `title` `Stewardship Statement 2025`, `file` `ref_stmt.docx`, `quote` `climate, governance and human rights`, `page` null; flags empty | holdout |
| AC-12 | `DOC-PDF`; the stand-in drafts `We held 512 engagement meetings in 2025.` citing it with quote `512 engagement meetings` | auto-fill `Q-MEET` | status `drafted`; the source's `page` is 2; flags exactly `check figure` | unit |
| AC-13 | `DOC`; the stand-in drafts `We held 600 engagement meetings in 2025.` citing `DOC` with quote `600 engagement meetings` | auto-fill `Q-MEET` | status `no source`, answer empty | holdout |
| AC-14 | `DOC`; the stand-in drafts `We held 512 engagement meetings with 340 companies.` citing `DOC` with quote `512 engagement meetings` | auto-fill `Q-MEET` | status `no source`, answer empty (340 is in the document but not in the quote) | holdout |
| AC-15 | `DOC`; `T-QUOTE` citing it; the second stand-in reports one unsupported fact | auto-fill `Q-TOPICS` | status `no source`, answer empty | holdout |
| AC-16 | the part 1 library of `lib_past.xlsx`; the stand-in drafts as in part 1 AC-14; the second stand-in reports one unsupported fact | auto-fill part 1's `rfp_in.xlsx` | question `RFP!A2` has status `no source`, answer empty | unit |
| AC-17 | `DOC-OLD`; `T-QUOTE` citing it | auto-fill `Q-TOPICS` | status `drafted`; flags exactly `stale source` | holdout |
| AC-18 | `DOC` and the part 1 library; the stand-in drafts `Example AM is an independent manager founded in 2004. We engage on climate, governance and human rights.` citing the firm entry with quote `an independent manager founded in 2004` and `DOC` with the quote of `T-QUOTE` | auto-fill `Q-TOPICS` | status `drafted`; exactly two sources, the first with `kind` `entry`, the second with `kind` `document` | unit |
| AC-19 | the app, signed in as an approver | open RFP Answers, upload a `.docx` under "Reference documents" with a title and a document date | the table under "Reference documents" shows a row with that title, the file name, the document date, a review-by date 12 months later and status `active` | evaluator |
| AC-20 | as AC-19, the document uploaded | press Retire on its row | the row's status reads `retired` and it has no Retire button | evaluator |
| AC-21 | RFP routes stubbed: a drafted answer with one document source (`title` `Stewardship Statement 2025`, `page` 2, quote `512 engagement meetings`) | open the project page | the answer's source shows `Stewardship Statement 2025`, `p. 2` and `512 engagement meetings` | unit (browser) |
| AC-22 | `ROWS`; `A-VOTE` | auto-fill `Q-VOTE` | status `drafted`; answer `In 2025 we voted against management on 25.0% of items.` | unit |
| AC-23 | as AC-22 | read the answer's sources | exactly one, with `kind` `statistic`, `definition` `Share of votes with against_management = true among votes; meeting_date from 2025-01-01 to 2025-12-31.`, `value` `25.0%`, `numerator` 2, `denominator` 8, `left_out` 1, `data_sources` [`ledger_test`], and a `computed_at` in UTC not before the test began | unit |
| AC-24 | as AC-22 | read the answer's flags | exactly `check figure` and `check statistic` | unit |
| AC-25 | `ROWS`; `A-COMP` | auto-fill `Q-COMP` | status `drafted`; answer `We engaged with 3 companies in 2025.`; the source's `definition` is `Number of distinct company_id in activities; occurred_at from 2025-01-01 to 2025-12-31.` and its `numerator` is 3 | unit |
| AC-26 | `ROWS`; `A-COMP`, but the draft reads `We engaged with {S1} companies in 2025, 7 of them new.` | auto-fill `Q-COMP` | status `no source`, answer empty (the model typed a figure no source states) | unit |
| AC-27 | `ROWS`; `A-COMP`, but `S-COMP` has the filter `region` = `Europe` | auto-fill `Q-COMP` | status `no source`, answer empty | unit |
| AC-28 | `ROWS`; `A-COMP`, but `S-COMP` has the filter `theme` = `biodiversty` | auto-fill `Q-COMP` | status `no source`, answer empty | unit |
| AC-29 | `ROWS`; `A-COMP`, but `S-COMP` has no `date_to` | auto-fill `Q-COMP` | status `no source`, answer empty | unit |
| AC-30 | `ROWS`; the question reads `What share of votes did you cast against management in 2023?`; `A-VOTE`, but the draft reads `In 2023 we voted against management on {S1} of items.` and `S-VOTE` runs from 2023-01-01 to 2023-12-31 | auto-fill it | status `no source`, answer empty (no rows to count) | unit |
| AC-31 | `ROWS`; `A-VOTE`; the second stand-in returns `S-VOTE` with the period 2024-01-01 to 2024-12-31 | auto-fill `Q-VOTE` | status `no source`, answer empty | unit |
| AC-32 | `ROWS`; `A-VOTE`, but the draft reads `In 2024 we voted against management on {S1} of items.` | auto-fill `Q-VOTE` | status `no source`, answer empty (2024 is not in the question or the statistic's period) | unit |
| AC-33 | `ROWS`; `A-COMP`, but `S-COMP` has the filter `theme` = `climate` | auto-fill `Q-COMP` | the source's `definition` is `Number of distinct company_id in activities where theme = climate; occurred_at from 2025-01-01 to 2025-12-31.` | unit |
| AC-34 | `ROWS-1204`; the question reads `How many engagement activities did you log in 2025?`; the stand-in drafts `We logged {S1} activities in 2025.` with a `count` query on `activities`, `occurred_at` 2025-01-01 to 2025-12-31 | auto-fill it | answer `We logged 1,204 activities in 2025.` | unit |
| AC-35 | `ROWS-DEMO`; `A-VOTE` | auto-fill `Q-VOTE` | flags exactly `check figure`, `check statistic` and `demo data` | unit |
| AC-36 | the answer of AC-35 | `bob` approves it with all three flags confirmed | 409 with detail `This answer uses demo data and cannot be approved.`; status `drafted`; the library is unchanged | unit |
| AC-37 | the answer of AC-35; `rfp_allow_demo_statistics` is `true` | `bob` approves it with all three flags confirmed | 200; status `approved` | unit |
| AC-38 | the answer of AC-22 | `bob` approves it with `confirmed_flags: ["check figure"]` | 409; status `drafted` | unit |
| AC-39 | RFP routes stubbed: a drafted answer with one statistic source (`value` `25.0%`, the definition of AC-23, `numerator` 2, `denominator` 8, `left_out` 1, `computed_at` `2026-11-15T09:30:00Z`) | open the project page | the source shows `25.0%`, the definition, `2 of 8`, `1 left out` and `15 Nov 2026, 09:30 UTC` | unit (browser) |
| AC-40 | `backend/arp/golden_set/data/rfp_document_drafts.json` | `arp rfp golden drafts --cases <file> --min-drafted 0.90 --min-blank 0.95` | exits 0: at least 90% of answerable questions `drafted`, at least 95% of unanswerable ones `no source`, and 0 drafts with a fact its sources do not state | golden |
| AC-41 | `backend/arp/golden_set/data/rfp_statistics.json` | `arp rfp golden statistics --cases <file> --min-drafted 0.80 --min-blank 0.95` | exits 0: at least 80% of answerable questions `drafted`, at least 95% of unanswerable ones `no source`, and every drafted answer's written values equal the labelled ones | golden |
| AC-42 | this change | `arp rfp golden questions` and `arp rfp golden drafts` on the part 1 case files with the part 1 thresholds | both exit 0 | golden |
| AC-43 | this change | run the existing backend and frontend suites | all pass | unit |
| AC-44 | `DOC` | `bob` calls `PUT /api/rfp/documents/{id}` with only `review_by` 2027-06-30 | 200; `GET /api/rfp/documents` shows its `review_by` 2027-06-30 and its `title` `Stewardship Statement 2025` | holdout |
| AC-45 | the answer of AC-22 | `alice` `PUT`s the answer `We voted against management on 25.0% of items in 2025.` | status `edited`; its one source is still the statistic; flags exactly `check figure` and `check statistic` | unit |
| AC-46 | the answer of AC-11 | `bob` retires `DOC` | the question's flags are exactly `stale source` | holdout |
| AC-47 | a question whose stored source is `{"entry_id", "quote"}` with no kind, as part 1 wrote it | `GET /api/rfp/projects/{id}` | 200; that source has `kind` `entry` | unit |
| AC-48 | `ROWS`; `A-COMP`, but the query's `id` is `S2` and the draft reads `We engaged with {S2} companies in 2025.` | auto-fill `Q-COMP` | status `drafted`; answer `We engaged with 3 companies in 2025.` | unit |
| AC-49 | `ROWS-16`; `A-VOTE` | auto-fill `Q-VOTE` | answer `In 2025 we voted against management on 6.3% of items.` | unit |
| AC-50 | the answer of AC-35 | `alice` `PUT`s the answer `We voted against management on 25.0% of items.` | flags exactly `check figure`, `check statistic` and `demo data` | unit |
| AC-51 | the answer of AC-50 | `carol` approves it with all three flags confirmed | 409 with detail `This answer uses demo data and cannot be approved.` | unit |
| AC-52 | `ROWS`; `A-COMP`, but the draft reads `We engaged with {S1} companies in {S2} meetings in 2025.` and `S-COMP` is the only query | auto-fill `Q-COMP` | status `no source`, answer empty | unit |
| AC-53 | `ROWS`; `A-COMP`, but `S-COMP` runs from 2025-12-31 to 2025-01-01 | auto-fill `Q-COMP` | status `no source`, answer empty | unit |
| AC-54 | `ROWS`; `A-VOTE`; the second stand-in's fact check reports `S1: the wording does not match the definition` | auto-fill `Q-VOTE` | status `no source`, answer empty | unit |
| AC-55 | `ROWS`; `engagement_store` is `file`; `A-COMP` | auto-fill `Q-COMP` | status `no source`, answer empty | unit |
| AC-56 | no reference documents | `bob` calls `PUT /api/rfp/documents/{id}` with an id no document has | 404 with detail `Reference document not found` | holdout |
| AC-57 | no reference documents | `bob` uploads `ref_stmt.docx` with a title and no document date | 422; `GET /api/rfp/documents` lists nothing | holdout |
| AC-58 | as AC-37, approved | read the library | it holds no entry | unit |

Must not change: part 1's library import, question detection, editing, four-eyes approval and export behave
as today (AC-43); part 1's golden thresholds still hold (AC-42); projects drafted before this change still
load (AC-47).
