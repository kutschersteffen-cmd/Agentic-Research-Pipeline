# Research Desk, wave 1: chat with stored reports, saved data and uploads

Status: Approved by the owner on 2026-11-25 (spec thread, Approve on head 22f7a8a)
Slug: `research-desk-wave1`
Risk: slices 1 to 3 `risk:normal`; slice 4 `risk:high` (file uploads and deletion; the owner merges it)
Size: `L`, four slices, one PR each, built in order 1, 2, 3, 4 (Argus and Research Desk plan, PRs 1 to 4)

## Summary

Research Desk is a chat where an analyst asks a question about chosen companies and gets an answer whose every
sentence is checked against its sources. Wave 1 builds it in four PRs: the backend chat over stored reports
(slice 1), its screens under `#/argus/desk` (slice 2), reviewed values and XBRL facts as sources (slice 3) and
reports uploaded into a chat (slice 4).

## Decisions for the owner

Approved with the plan on 2026-11-25 (22:57 Berlin) and kept here:

1. Uploads that were never saved to a company are deleted 30 days after they were uploaded (AC-73).
2. The analyst role may upload in Research Desk, the same as Argus uploads today (AC-62).

Approved by the owner later the same evening, in the plan thread:

3. Every answer runs the sentence check. There is no setting, flag or request field that skips it (AC-24).
4. Thorough never uses a language-model reranker: the server's cross-encoder or ColBERT reranker when
   `rerank_enabled` is true, otherwise none (AC-16, AC-17).

Every other choice is under "Defaults taken"; approving the spec approves them.

## Why

Plan: https://claude.ai/artifact/HEt7XAniY3yB5Gnj5JyMRM (sections "Research Desk chat", "Frontend plan", "Slices
and order", "Testing and acceptance"). Screens: https://claude.ai/artifact/EBSKMGCZTVZuwYZ2PLjrQu, boards 11 to 14
(the companies there are made up).

ARP can extract fields from reports (Argus) and answer questions with read-only tools (`arp/ask.py`), but nothing
answers a free question from the reports themselves. An analyst who wants "how much of their 2025 capex went to
low-carbon assets?" has to start a full extraction.

## What the user can do afterwards that they cannot do today

- Open Research Desk (`#/argus/desk`), pick companies, ask a question in Quick or Thorough mode and watch the steps.
- Read an answer where each sentence is marked "found word for word", "calculated" or "to check", open each source
  and see the formula of each calculated figure.
- See how the answer was found: time per step and the passages with their scores.
- Have reviewed values from Argus runs and XBRL facts used as sources, each labelled with its kind.
- Upload reports into a chat, see which company ARP found, ask about them, and save them to the company.

## What exists today (main `7e2e955`)

- Refine chat (`arp/api/routers/refine.py`, `arp/refine/turns.py`): `POST .../turns` answers `202 {"turn_id"}`,
  the turn runs in the background through `schedule_llm_run` (`arp/api/run_scheduling.py`), the page polls
  `GET /api/refine/turns/{id}`. One `running` turn per document via a partial unique index; `reap_stale_turns`
  fails turns with no progress for 10 minutes and all `running` turns at API start.
- Retrieval: `select_relevant_chunks` in `backend/arp/retrieval/select_evidence.py` (BM25, plus vectors fused by
  RRF k=60 when `hybrid_retrieval_enabled`, default `true`; local reranker when `rerank_candidates` is passed;
  `explain=` fills per-chunk `scores` with `bm25`, `vector_rank`, `rrf`, `rerank`).
- Checking: `backend/arp/grounding.py` `is_grounded(quote, source_text)` (exact, normalised, then fuzzy ≥ 0.92;
  short numeric quotes need a label word; digits outside a fuzzy match fail).
- Chunking: `chunk_document` (`arp/ingestion/parsing.py`), deterministic `chunk_id`. Parsing:
  `parse_file_to_text_with_pages` (`arp/ingestion/local_files.py`) for `.pdf .docx .xlsx .xlsm .html .htm .txt
  .md`; `DocumentContentStore.get_or_parse` caches parses.
- Stored reports: files at `$ARP_DOCUMENTS_DIR/<company key>/<doc_type>/<file>`, written by
  `arp/argus/documents.py` `store_upload` (never overwrites, returns the duplicate when the bytes are already
  stored).
- A company's **key** (used by Argus and the documents folder): its active `UNIVERSE` identifier in
  `company_identifiers`, else `str(companies.id)` (`arp/argus/companies.py` `_key`).
- Argus uploads (`POST /api/argus/flows/{id}/documents/upload`, `require_role("analyst")`): `413` "File is larger
  than the {N} MB upload limit." above `max_upload_bytes` (100 000 000); `400` "File names cannot start with a
  dot."; no type check.
- Review decisions: `review_items` (`payload` JSONB has `company_id`, `name`, `field_id`, `period_end`, `field`) and
  insert-only `review_decisions` (`decision` approve, edit, correct, reject, escalate, hold; `edited_value`).
- XBRL: `XbrlStore` (`settings.xbrl_dir`), `read_facts(cik)` gives `FactRow`; `company_ids(cik)` lists the company
  keys that fetched a CIK; `views.query_facts(..., annual_only=True)`.
- Retention: `arp retention cleanup [--apply]` (`arp/cli/retention.py`, `arp/retention.py`) prints `deleted: <x>`
  (or `would delete: <x>`) lines and a summary.
- Roles: `ROLE_RANK = {"viewer": 0, "analyst": 1, "approver": 2}`; `require_role("analyst")` answers `403`
  "Requires role 'analyst' or higher".
- Test double for the model: with `ARP_STANDINS_DIR` set, `build_llm_client` returns `StandInLLMClient`
  (`arp/standins.py`), which answers `complete_structured(output_model=X)` from `$ARP_STANDINS_DIR/model/X.json`
  (`{"output": {...}}`, a list for successive calls, or `{"error": "..."}` to raise) and logs every call with its
  `prompt` to `calls.jsonl`.
- Frontend: hash routes; `#/argus` is `ArgusStart`, `#/argus/<flow>/<step>` is `ArgusFlow` (`App.tsx:301-302`);
  `Orb.tsx` exists.

## Goals

1. G1 (slice 1): chats with a scope (companies, universes, runs), owned by one user, under `/api/desk`.
2. G2 (slice 1): a turn answers a question from the scope's stored reports, Quick or Thorough, 202 then poll.
3. G3 (slice 1): every answer sentence gets one of three statuses by a check in code, never by the model; a
   calculated figure stores its formula.
4. G4 (slice 2): the Research Desk screens: start, working, answer, how it was found.
5. G5 (slice 3): approved reviewed values and XBRL facts are sources, each labelled with its kind.
6. G6 (slice 4): uploads in a chat, with company detection, a chat-only index, save to company, 30-day cleanup.
7. G7 (all): limits that stop abuse: question length, scope size, running turns, upload size, type and count.

## Non-goals

- Argus tab row, Overview card, Company ledger, step chats, "Send to full extraction" and `POST
  /api/desk/turns/{id}/extraction` (later waves). The answer screen shows no "Send to full extraction", "Copy with
  sources", "Add to a report" or "Stop" button in this wave.
- `DocumentChunk.page_start`/`page_end` (wave 4) are not added. `page` here is computed from the parse's page
  breaks (`null` for a file without page breaks, such as `.txt`).
- The parser track, the LLM reranker option, per-run settings profiles.
- Deleting or renaming a chat.
- Model output quality (no `golden` rows: the golden set is not a merge gate and model credit is out).

## Anti-goals (must stay true)

- The model never decides a sentence's status; the check in code does, on every answer (AC-21 to AC-24).
- No user reads, lists or streams another user's chat, turn or upload, whatever their role (AC-6, AC-7, AC-35).
- An unsaved upload never appears outside its chat (AC-70).
- A saved upload is never deleted by the cleanup (AC-74).
- `backend/arp/retrieval/select_evidence.py` and `backend/arp/ingestion/local_files.py` are only called, not
  changed (another factory item edits them).

## Design

### Slice 1: document chat on stored reports (backend)

New package `backend/arp/research_desk/`, router `backend/arp/api/routers/desk.py` (prefix `/api/desk`), tables in
`backend/arp/db/models.py` next to `RefineTurn` (created by `ensure_schema` like the others).

**Tables**

| Table | Columns |
|---|---|
| `desk_chats` | `id` int identity PK, `owner_id` text, `title` text, `created_at`, `updated_at` timestamptz |
| `desk_scope` | `id` int identity PK, `chat_id` FK `desk_chats.id`, `kind` text (`company` \| `universe` \| `run` \| `upload`), `ref` text, `label` text; unique (`chat_id`, `kind`, `ref`) |
| `desk_turns` | `id` int identity PK, `chat_id` FK, `user_id` text, `question` text, `mode` text (`quick` \| `thorough`), `status` text (`running` \| `done` \| `failed`), `stages` JSONB, `sources` JSONB, `answer` JSONB null, `error` text null, `created_at`, `updated_at`, `finished_at` null; partial unique index `uq_desk_turns_running` on (`chat_id`) where `status = 'running'` |
| `desk_uploads` (slice 4) | `id` int identity PK, `chat_id` FK, `owner_id`, `filename`, `stored_path`, `size_bytes`, `sha256`, `status` (`reading` \| `ready` \| `failed`), `error` null, `full_text` null, `page_breaks` JSONB, `detected_company_id` null, `detection` (`lei` \| `isin` \| `name` \| `none`), `saved_company_id` null, `saved_doc_type` null, `saved_at` null, `created_at` |

**Access.** Every `/api/desk` endpoint uses `require_role("analyst")` (a viewer gets `403` "Requires role 'analyst'
or higher"). A chat, its turns and uploads belong to `desk_chats.owner_id`; for anyone else (approvers too) every
endpoint that names them answers `404` with detail `Chat not found` (chat ids), `Turn not found` (turn ids) or
`Upload not found` (upload ids).

**Endpoints**

| Method, path | Body | Answer |
|---|---|---|
| `POST /api/desk/chats` | `{"title"?: str}` | `201 {"id", "title", "created_at"}`; title defaults to `New chat` |
| `GET /api/desk/chats` | | `200 [{"id", "title", "updated_at", "turns"}]`: the caller's chats, `updated_at` newest first, at most 20 |
| `GET /api/desk/chats/{id}` | | `200 {"id", "title", "created_at", "scope": [Scope], "turns": [{"id", "question", "mode", "status", "created_at"}]}`, turns oldest first |
| `PUT /api/desk/chats/{id}/scope` | `{"items": [{"kind", "ref"}]}` | `200 {"scope": [Scope]}`; replaces the whole scope |
| `GET /api/desk/companies?q=&limit=` | | `200 {"total", "items": [Company]}` |
| `POST /api/desk/chats/{id}/turns` | `{"question": str, "mode"?: "quick" \| "thorough"}` | `202 {"turn_id"}` |
| `GET /api/desk/turns/{id}` | | `200 Turn` |

`Scope` is `{"kind", "ref", "label"}`. Label: a company's name (`companies.name`, else the key), a universe's file
name, a run's id, an upload's file name.

`Company` is `{"company_id", "name", "reports"}` (slice 3 adds fields). The list holds every company key that has at
least one report file (slice 3: or a reviewed value or an XBRL fact), sorted by name, filtered by `q` as a
case-insensitive substring of name or key; `limit` default 20, 1 to 100.

**Scope rules.** `kind` must be `company`, `universe` or `run` (`upload` from slice 4), else `422`. A `company` ref
must be a known company key (a folder under `$ARP_DOCUMENTS_DIR`, or a key of a `companies` row), else `422`
`Unknown company: <ref>`. A `universe` ref is a saved universe path, read with `load_saved_universe` (its own errors
apply). A `run` ref must be a run that `RunStore(settings.runs_dir).load_manifest(ref)` finds, else `422` `Unknown run:
<ref>`. The scope expands to the companies it names: a universe's companies and a run's `load_companies(ref)`, each
by its `company_id`; more than 50 distinct companies, or more than 50
items, is `422` `Scope is limited to 50 companies.` Putting a scope bumps `updated_at`.

**Turn limits.** `question` is stripped and must be 1 to 2000 characters (`422` otherwise); `mode` defaults to
`quick`, any other value is `422`. Extra body fields are ignored. Refusals, checked in this order:

1. The chat's scope is empty: `409` `Add a company, universe, run or upload to this chat first.`
2. The chat has a `running` turn: `409` `A question is already running in this chat.`
3. The caller has 3 `running` turns across chats: `429` `You have 3 questions running. Wait for one to finish.`

Stale turns are reaped like Refine's (no progress for 10 minutes, and every `running` turn at API start): `status`
`failed`, `error` `interrupted`. The first turn of a chat titled `New chat` sets the title to the question's first 60
characters.

**Stages.** `Turn.stages` always holds these six records, in this order: `pick_sources`, `split`, `search`, `rank`,
`write`, `check`. Each is `{"name", "status", "ms", "detail"}` with `status` `pending`, `running`, `done`, `failed`
or `skipped`, `ms` an integer once done (else `null`), and `detail`:

| Stage | `detail` once done |
|---|---|
| `pick_sources` | `{"companies": n, "documents": n}` (slice 3 adds `"saved_rows": n`) |
| `split` | `{"questions": [str]}` |
| `search` | `{"matched": n, "kept": n}` |
| `rank` | `{"passages": n, "reranked": bool}` |
| `write` | `{"calculations": n}` |
| `check` | `{"found": n, "calculated": n, "to_check": n}` |

**One turn.**

1. `pick_sources`: every file under `$ARP_DOCUMENTS_DIR/<key>/<doc_type>/` for each scope company whose suffix the
   parser reads, dot files skipped, newest 100 by modification time across the scope. Parsed through the existing
   parse cache, chunked with `chunk_document`.
2. `split`: Quick: `skipped`. Thorough: one model call with output model `DeskSubQuestions` (`{"questions":
   [str]}`); the first 4 are kept; none means the question itself.
3. `search`: `select_relevant_chunks(chunks, <question words>, max_chunks=K, require_hit=True,
   fallback_to_all=True, hybrid_retrieval_enabled=settings.hybrid_retrieval_enabled, content_store=..., explain=...)`
   once per (sub-)question. Quick: K = 8, no `rerank_candidates`. Thorough: K = 12, `rerank_candidates =
   settings.rerank_candidates` with `rerank_model = settings.rerank_model` when `settings.rerank_enabled`, else none.
   No language-model reranker in either mode. `matched` = candidate chunks, `kept` = distinct chunks returned.
4. `rank`: Quick: `skipped`. Thorough: the per-sub-question lists merged round-robin, duplicates dropped, first 12
   kept. `reranked` says whether the reranker scored them.
5. The kept passages become `Turn.sources`, numbered from 1 in rank order.
6. `write`: one model call with output model `DeskAnswer`. Its prompt holds the question, the last 5 `done` turns'
   questions and answer text of the same chat, and each source as a line starting `[<n>] ` followed by its text.
7. `check`: the sentence check below, in code, on every answer.

If the scope yields no source, the turn ends `done` without any model call, with one sentence `I found no reports or
saved data in this chat's scope.` (status `to_check`): `pick_sources` `done`, `split`, `search`, `rank` and `write`
`skipped`, `check` `done` with `{"found": 0, "calculated": 0, "to_check": 1}`. A failed turn keeps the stage
records and `sources` it had reached. A model error (stand-in `{"error": "boom"}`) ends the turn
`failed` with `error` `The model call failed: boom` and the running stage `failed`.

**`DeskAnswer` (the model's output)**

```json
{"sentences": [{"text": "…", "citations": [{"source": 1, "quote": "…"}], "calculation": "c1"}],
 "calculations": [{"id": "c1", "label": "Halden low-carbon share", "expression": "1900 / 3100 * 100",
                   "decimals": 1, "unit": "%"}]}
```

`citations` defaults to `[]`, `calculation` to `null`, `decimals` to `1` (0 to 6), `unit` to `""`. Calculations
after the first 10 are dropped.

**Calculator.** An expression may hold only numbers (digits with an optional `.`), `+ - * / ( )`, unary minus and
spaces, at most 200 characters. It is evaluated in code (never `eval`). Stored per calculation:

`{"id", "label", "expression", "result", "display", "unit", "formula", "error"}`, where `result` is the full float,
`display` is `f"{result:.{decimals}f}"`, and `formula` is exactly `"<label> = <expression> = <display><unit>"`
(e.g. `Halden low-carbon share = 1900 / 3100 * 100 = 61.3%`). On failure `result`, `display` and `formula` are
`null` and `error` is `Only numbers and + - * / ( ) are allowed.`, `Division by zero.` or `The formula is longer
than 200 characters.`

**Sentence check.** A citation **grounds** when its `source` is a number in `Turn.sources` and
`grounding.is_grounded(quote, <that source's text>)` is true. Each sentence gets exactly one status:

1. `calculated`: it names a calculation that has no `error`, its text contains that calculation's `display`, and
   every number in the expression other than 100, 1000 and 1000000 equals a number in a grounding quote of this
   answer (numbers read from quotes with `,` thousands separators removed).
2. else `found`: it has at least one citation and every citation grounds.
3. else `to_check`.

A sentence that names a calculation and fails rule 1 is `to_check`. `check` counts the three statuses; they sum to
the number of sentences. Nothing in the request, the settings or the environment turns the check off.

**`Turn` (`GET /api/desk/turns/{id}`)**

```
{"id", "chat_id", "question", "mode", "status", "error", "created_at", "finished_at",
 "stages": [Stage × 6],
 "sources": [Source],
 "answer": null | {"sentences": [{"n", "text", "status", "citations": [{"source", "quote", "grounded", "page"}],
                                   "calculation"}],
                   "calculations": [Calculation], "check": {"found", "calculated", "to_check"}}}
```

`n` counts sentences from 1. `page` is the 1-based page of the quote's match in the parsed document (from its page
breaks), else `null`. A report `Source` is `{"n", "kind": "report", "company_id", "company_name", "filename",
"doc_type", "chunk_id", "text", "page", "scores", "used"}`: `scores` copies the `explain` scores (`bm25`,
`vector_rank`, `rrf`, `rerank`, each only when computed), `page` is the page of the passage's start, `used` is true
when a sentence cites it.

### Slice 2: Research Desk screens (frontend, plus the event stream)

**Event stream.** `GET /api/desk/turns/{id}/events` answers `text/event-stream`. Each time a stage record changes it
sends `event: stage` with `data:` the stage record as JSON; when the turn is no longer `running` it sends `event: end`
with `data: {"status": "<done|failed>"}` and closes. For a finished turn it sends the six stage records in order,
then `end`. On connect to a running turn it first sends all six current records, then each change; it polls the turn
every 0.5 s. Owner rule as above (`404` `Turn not found`).

**Routes.** `#/argus/desk` is `pages/desk/DeskStart.tsx`, `#/argus/desk/<chatId>` is `pages/desk/DeskChat.tsx`
(`desk` is checked before a flow id). Components in `frontend/src/components/argus/`: `OrbChat` (the Orb, a phase
label, an ask box; props `context` and `onAction` kept generic so later Argus PRs only add a prop), `ScopeChips`,
`StageList`, `FigureCheck`, `CitationPanel`; slice 4 adds `DropZone` there.

**DeskStart.** Heading `Research Desk`. Ask box with placeholder `Ask anything about the companies you pick`, an
`Ask` button, a two-button toggle `Quick` / `Thorough` (Quick pressed by default, `aria-pressed`). `ScopeChips` shows
`Asking about` and one chip per scope item with a remove `×`, plus `+ Saved company`, which opens a search box
that at once lists `GET /api/desk/companies?q=` (empty `q`) results and re-queries as the user types; picking one
adds a chip. `Ask` is disabled while the question is empty
or no chip is chosen. Asking does `POST /api/desk/chats`, `PUT .../scope`, `POST .../turns`, then opens
`#/argus/desk/<chatId>`. Below: `Recent chats`, one line per `GET /api/desk/chats` entry (its title), each opening
its chat.

**DeskChat, working.** While the latest turn is `running`: `Your question` and the question, the Orb with phase label
`WORKING`, and `StageList` fed by the event stream: the header `Working on it · step <k> of <n>` (n = stages not
`skipped`, k = position of the `running` one), then one row per stage not `skipped`, labelled:

| Stage | Label |
|---|---|
| `pick_sources` | `Picked the sources` |
| `split` | `Split the question` |
| `search` | `Searched the reports` |
| `rank` | `Picked the best passages` |
| `write` | `Wrote the answer` |
| `check` | `Checked every figure` |

A `done` row shows its `ms` as seconds with one decimal (`0.4 s`). After `end` the page reads `GET
/api/desk/turns/{id}` once.

**DeskChat, answer.** Phase label `DONE`. The first sentence as the lead (a heading). `FigureCheck`: `Every figure
checked.` when `to_check` is 0, else `<n> to check.`, then three chips `<found> in source`, `<calculated>
calculated`, `<to_check> to check`. Then every sentence in order (sentence 1 again too): its text, directly followed by its marker (`(calculated)` for a
`calculated` sentence, `to check` for a `to_check` one, none for `found`), then one chip per citation showing its
source number. One block per calculation without
error, summary `How the <display><unit> was worked out`, body its `formula`. A link `How was this found?`. Below,
the ask box (placeholder `Ask a follow-up or a new question`), the scope chips and the toggle; asking posts a turn in
the same chat and then re-reads `GET /api/desk/chats/{id}`. Earlier turns of the chat are listed under `Earlier`. A failed turn shows `This question failed:
<error>`.

**CitationPanel.** Clicking a citation chip opens a side panel: the source's company name and file name, `Page <p>`
when the citation has a page, the quote, and `found word for word` when the citation grounds, else `not found in
the source`. Arrows `Source <n>` move to the previous and next cited source. Closing it with `×` or `Esc`.

**How it was found.** `How was this found?` shows `How this answer was found`, the question, `Where the time went`
with one entry per stage not `skipped` (its label and `ms` as seconds), and a table `The <k> passages the answer
used` (k = sources with `used`), columns `#`, `Passage`, `Same words`, `Same meaning`, `Rank`: the passage text
(first 200 characters), company name and file name; `Same words` from `bm25`, `Same meaning` from `vector_rank`,
`Rank` the ordinal of `n` (`1st`, `2nd`, …). `Back to the answer` returns.

A chat id the API answers `404` for shows `Chat not found.`

### Slice 3: saved company data in the chat

**Saved rows.** For each scope company, before the model call, `pick_sources` also reads:

- **Reviewed values**: for every `review_items` row whose `payload.company_id` is the company key (a `run` scope
  item: only that run's items), the latest `review_decisions` row (highest `id`) for that item. Kept only when that
  decision is `approve` (value `payload.field.value`), `edit` or `correct` (value `edited_value`). Unit:
  `payload.field.unit` when present.
- **XBRL facts**: for every CIK whose `XbrlStore.company_ids(cik)` holds the key, its annual facts (`is_annual`).

Each saved row becomes one text line:

- reviewed value: `<company name> · <field_id> · <period_end> · <value> <unit> · reviewed value, run <run_id>`
- XBRL fact: `<label or concept> · FY<fiscal_year> <fiscal_period> · <value> <unit> · XBRL fact, <form> filed <filed>`

(`<value>` is written without `.0` when whole; an absent unit or part leaves its space out.) The lines are ranked
with `select_relevant_chunks(..., require_hit=True, fallback_to_all=False)` against the question, best 20 kept, and
added to `Turn.sources` after the passages. `pick_sources.detail.saved_rows` counts them.

Sources gain:

- `{"n", "kind": "review_value", "company_id", "company_name", "run_id", "item_key", "field_id", "period_end",
  "value", "unit", "decision", "text", "used"}`
- `{"n", "kind": "xbrl_fact", "company_id", "cik", "concept", "label", "fiscal_year", "fiscal_period", "period_end",
  "value", "unit", "form", "filed", "text", "used"}`

Each answer citation gains `"source_kind"`, the cited source's `kind` (`null` for a number outside the sources).
The check is unchanged: a saved-row citation grounds when its quote is found in that row's `text`.

`Company` gains `"reviewed_values"` (count, by the rule above), `"xbrl_first_year"` and `"xbrl_last_year"` (min and
max `fiscal_year` of the company's annual facts, `null` without facts).

**Source-kind labels (UI).** `report` → `Report`, `upload` → `Uploaded report`, `review_value` → `Reviewed value`,
`xbrl_fact` → `XBRL fact`. Each citation chip shows its label after the number; `CitationPanel` shows the label
above the quote, and for a saved row the run id (`Run <run_id>`) or the filing (`<form> filed <filed>`) in place of a
file name and page.

**Saved data panel (DeskStart).** Heading `Saved company data`, a search box (placeholder `Find a company`), one row
per `GET /api/desk/companies` item with a checkbox, its name, and `<reports> reports · <reviewed_values> reviewed
values · XBRL facts <first>–<last>` (the XBRL part left out when there are none). Ticking a row adds it to the scope
chips; unticking removes it.

### Slice 4: uploads in a chat

**Upload.** `POST /api/desk/chats/{id}/uploads`, multipart `file`, `require_role("analyst")`, owner rule. Checked in
this order:

| Case | Answer |
|---|---|
| file name starts with `.` | `400` `File names cannot start with a dot.` |
| suffix (case-insensitive) not `.pdf`, `.docx` or `.xlsx` | `415` `Only PDF, Word (.docx) or Excel (.xlsx) files can be uploaded.` |
| more than `max_upload_bytes` bytes | `413` `File is larger than the <N> MB upload limit.` (as Argus) |
| empty | `400` `The file is empty.` |
| `.pdf` not starting with `%PDF-`, or `.docx`/`.xlsx` not a zip | `415` `The file content does not match its type.` |
| the chat already has 20 uploads | `409` `A chat holds at most 20 uploads.` |

Accepted: `202` with the `Upload` record `{"id", "filename", "size_bytes", "status": "reading", "error",
"detected_company_id", "detected_company_name", "detection", "saved_company_id", "saved_company_name", "saved_at",
"created_at"}`. The file
is stored at `<desk_uploads_dir>/<chat_id>/<upload_id>/<safe file name>`, a new setting `desk_uploads_dir`
(`ARP_DESK_UPLOADS_DIR`, default `data/desk_uploads` under the repo root). The upload is added to the chat's scope as
`{"kind": "upload", "ref": "<upload id>"}`. In the background it is checked with `check_intake` (a quarantined or
OCR-needing file ends `failed` with `error` the intake reason), parsed with `parse_file_to_text_with_pages`, its text
and page breaks stored on the row, then company detection runs and the status becomes `ready`.

`GET /api/desk/chats/{id}/uploads` lists the chat's uploads, oldest first. A scope item `upload` must name an upload
of this chat, else `422` `Unknown upload: <ref>`.

**Company detection** reads the first 3 pages (the first 6000 characters when there are no page breaks): an LEI
(`[A-Z0-9]{18}[0-9]{2}`) or an ISIN (`[A-Z]{2}[A-Z0-9]{9}[0-9]`) that is an active identifier of a `companies` row
gives that company (`detection` `lei` or `isin`, LEI first); else a `companies.name` of at least 4 characters found
as whole words, case-insensitively (`name`; when several match, the longest name; a tie means none); else `none`.
`detected_company_id` is that company's key.

**Chat-only index.** In a turn, a `ready` upload in scope is chunked with `chunk_document` from its stored text and
searched with the reports. Its sources are `{"kind": "upload", "upload_id", "filename", "company_id",
"company_name", …}` with the report source's other fields (`company_*` from the detected or saved company, else
`null`). Unsaved uploads are not registered in `documents`, the document store or `$ARP_DOCUMENTS_DIR`, so they
appear in no other chat and no other search.

**Save.** `POST /api/desk/chats/{id}/uploads/{upload_id}/save` with `{"company_id"?: str, "doc_type"?: DocType}`
(`doc_type` default `other`). The company is the given key, else the detected one. Refusals: upload not `ready`:
`409` `The upload is still being read.` (also for `failed`); already saved: `409` `Already saved.`; no company:
`422` `Pick the company to save this report under.`; unknown key: `422` `Unknown company: <ref>`. Saving calls
`store_upload(documents_dir, key, doc_type, filename, data)` and sets `saved_company_id`, `saved_doc_type`,
`saved_at`; it answers `200` with the `Upload` record. The chat copy stays.

**Retention.** `arp retention cleanup` also covers desk uploads: an upload with `saved_at` null and `created_at` at
least `retention_desk_uploads_days` days before now (new setting, default 30) is expired. Dry run prints `would
delete: desk upload <id>`; `--apply` prints `deleted: desk upload <id>` and deletes its folder
`<desk_uploads_dir>/<chat_id>/<id>/`, its `desk_uploads` row and its `desk_scope` row. Saved uploads are never
expired. The summary line counts them with the other deletions.

**DropZone (DeskStart and DeskChat).** Heading `Upload documents`, a drop area `Drop reports here, from any
companies` with `PDF, Word or Excel · or browse` (`browse` opens the file picker). Dropping on DeskStart creates a
chat, uploads each file and opens the chat. One row per upload: the file name; status `Reading`, `Ready` or `Failed:
<error>`; `Company found: <name>` or `Company not found`; a `Save to the company` button while unsaved and ready,
`Saved to <name>` once saved. Every dropped file is sent to the API (no type filter in the browser); a refused file shows the API's `detail`. Under the list: `Uploads stay with this chat
for 30 days. Save them to the company to keep them.` Upload chips in `ScopeChips` are blue, saved-data chips green.

## Defaults taken

1. Chats are private to their owner for every role, approvers included; a stranger's id answers `404`, not `403`,
   so ids reveal nothing.
2. A viewer cannot use Research Desk at all (it spends model calls), like Refine.
3. No routing model call: every source in scope goes through the same search; the answer model picks.
4. "Tools" for saved data are deterministic reads added as numbered sources, not model tool calls (the app's model
   client has no tool loop).
5. Six fixed stages, with `split` and `rank` `skipped` in Quick, so the UI has one list shape.
6. At most 100 report files read per turn (newest first), 20 saved rows, 8 (Quick) or 12 (Thorough) passages, 4
   sub-questions, 10 calculations, 3 running turns per user, 50 companies per scope, 2000 characters per question,
   20 uploads per chat.
7. Upload types: PDF, Word (.docx), Excel (.xlsx), as the screen says; no HTML (it can carry script). Same size
   limit and message as Argus.
8. Company detection is deterministic (identifiers, then names in the registry), no model or web call. The "identity
   matcher" of the plan (identity runs) needs web search and a model; it stays in Argus step 1.
9. "Unsaved" means `saved_at` is null; the 30 days count from `created_at` (the upload time), not from the last
   question.
10. A saved upload's chat copy is kept with the chat (never expired); the stored report under the company follows
    the documents folder's own rules.
11. The constants 100, 1000 and 1000000 need no source in a calculation (percent and unit scaling).
12. Approved reviewed value = the latest decision is approve, edit or correct; a later reject, escalate or hold
    removes it.

## Notes for the builder

- Smallest possible diff with the lowest complexity: no refactors, no new abstractions, no unrelated cleanup.
- Do not change `select_evidence.py` or `local_files.py`; call them. If the design seems to need a change there,
  set `factory:blocked` and ask.
- Each slice that adds or changes an endpoint runs `scripts/export_openapi.py` and `npm run gen:api`, commits both
  generated files, and adds a line per new `request<T>()` in `frontend/src/api/contract.ts`.
- The event stream must not hold a database connection between polls; the E2E stack proxies `/api/` with buffering
  off already.
- Slices touching `arp/grounding.py` would run the golden set; this spec does not change it.
- Slices 2 to 4 change UI: Playwright screenshot plus `/impeccable:impeccable audit`, as `.claude/CLAUDE.md` asks.
- Never use the word "product" in UI text; the app is "Agentic Research Platform".

## Acceptance

**API rows** use FastAPI's `TestClient` on `arp.api.main:app` with Postgres (the holdout job's), `ARP_AUTH_MODE=local`
and a users file with `alice` (analyst), `bob` (analyst), `ada` (approver) and `vic` (viewer), each sending their
token; "Alice's chat" is one Alice created. `ARP_STANDINS_DIR` is a temp folder (**the fake model**: answers come
from `model/DeskAnswer.json` and `model/DeskSubQuestions.json`, calls are logged in `calls.jsonl`),
`ARP_HYBRID_RETRIEVAL_ENABLED=false` and `ARP_RERANK_ENABLED=false` unless a row says otherwise,
`ARP_DOCUMENTS_DIR`, `ARP_XBRL_DIR`, `ARP_RUNS_DIR`, `ARP_BLOB_STORE_DIR` and `ARP_DESK_UPLOADS_DIR` temp folders. **Report "acme-2025"**
is `$ARP_DOCUMENTS_DIR/acme/other/acme-2025.txt`, 120 paragraphs of about 600 characters (at least 20 chunks under
`chunk_document`'s defaults), each holding the word
`capex`. Report acme-2025 exists in every row unless the row says otherwise. Neither `acme` nor `beta` has a `companies` row unless a row says so (name = key). **Report "beta-2025"** is `$ARP_DOCUMENTS_DIR/beta/other/beta-2025.txt`, three lines only (one passage, so
always a source whatever the ranking): `Capital expenditure in 2025 amounted to EUR 6,400 million.`, `Investments in
renewables and grids: EUR 1,900 million.`, `Group capex: EUR 3,100 million.` No row depends on the order
`select_relevant_chunks` ranks chunks in (other items change its internals); rows find "the source holding X" by
searching `Turn.sources` texts. "A valid `DeskAnswer`" is one sentence citing source 1 with
`Group capex: EUR 3,100 million.`; every turn row has one unless it names another. Runs are created through
`RunStore(settings.runs_dir)` (which also writes the `runs` row). "Waits for the turn" means
polling `GET /api/desk/turns/{id}` until `status` is not `running` (at most 30 s). **CLI rows** run `arp retention
cleanup` in-process (Typer `CliRunner`) with the same env. **UI rows** run in headless Chromium against
`e2e_stack.sh up` (Vite dev server) with every `/api/desk/**` request answered by `page.route` from fixtures; an
event stream fixture is one `text/event-stream` body. **Evaluator rows** run on `e2e_stack.sh up` with
`ARP_STANDINS_DIR` set to a folder holding `model/DeskAnswer.json` (and `DeskSubQuestions.json`) whose quotes are
copied from the seeded reports, so the running app answers with no real model.

### Slice 1: document chat (backend)

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Alice | `POST /api/desk/chats` `{}` | `201`; body has an integer `id`, `title` `New chat` | holdout |
| AC-2 | Vic (viewer) | `POST /api/desk/chats` `{}` | `403`, detail `Requires role 'analyst' or higher` | holdout |
| AC-3 | Alice has 2 chats, Bob has 1 | Alice `GET /api/desk/chats` | `200`, exactly Alice's 2 chat ids, the one with the later `updated_at` first | holdout |
| AC-4 | Alice's chat, report acme-2025 | Alice `PUT .../scope` `{"items": [{"kind": "company", "ref": "acme"}]}` | `200`, `scope` is `[{"kind": "company", "ref": "acme", "label": <string>}]` | holdout |
| AC-5 | Alice's chat | `PUT .../scope` with ref `nosuch` | `422`, detail `Unknown company: nosuch` | holdout |
| AC-6 | Alice's chat C with a `done` turn T | Bob, then Ada, request `GET /api/desk/chats/{C}` and `GET /api/desk/turns/{T}` | each `404`; details `Chat not found` and `Turn not found` | holdout |
| AC-7 | Alice's chat C | Bob `PUT /api/desk/chats/{C}/scope` and `POST /api/desk/chats/{C}/turns` | each `404` `Chat not found`; C's scope and turns unchanged | holdout |
| AC-8 | 51 company folders `c01`…`c51` | `PUT .../scope` with all 51 | `422`, detail `Scope is limited to 50 companies.` | holdout |
| AC-9 | scope acme | `POST .../turns` with a question of 2001 characters; then with `"   "` | both `422`; no turn row written | holdout |
| AC-10 | scope acme | `POST .../turns` `{"question": "q", "mode": "fast"}` | `422` | holdout |
| AC-11 | a chat with empty scope | `POST .../turns` `{"question": "q"}` | `409`, detail `Add a company, universe, run or upload to this chat first.` | holdout |
| AC-12 | scope acme; `DeskAnswer.json` with `"delay_seconds": 5` | two `POST .../turns` in a row | first `202` `{"turn_id": <int>}`; second `409` `A question is already running in this chat.` | holdout |
| AC-13 | Alice has 3 chats, each with a running turn (delay 5 s) | `POST` a turn in a 4th chat | `429`, detail `You have 3 questions running. Wait for one to finish.` | holdout |
| AC-14 | scope acme, a valid `DeskAnswer` | a Quick turn; wait for it | `status` `done`; `stages[*].name` is exactly `["pick_sources", "split", "search", "rank", "write", "check"]`; `split` and `rank` `skipped`, the other four `done` with integer `ms` | holdout |
| AC-15 | scope acme | a Quick turn | `sources` has exactly 8 entries, `n` 1 to 8, each `kind` `report`, `filename` `acme-2025.txt`, `company_id` `acme`; `search.detail.kept` is 8 | holdout |
| AC-16 | scope acme, `DeskSubQuestions` `{"questions": ["capex 2025", "renewables"]}` | a Thorough turn | `sources` has exactly 12 entries; `split.detail.questions` is `["capex 2025", "renewables"]`; `rank.detail.reranked` false; `calls.jsonl` has exactly one `DeskSubQuestions` and one `DeskAnswer` call | holdout |
| AC-17 | `ARP_RERANK_ENABLED=true` | a Quick turn | `rank` is `skipped`; no source's `scores` has a `rerank` key | unit |
| AC-18 | scope acme | a Quick turn | the `DeskAnswer` call's `prompt` in `calls.jsonl` contains the question and, for each source n, `[n] ` followed by the first 40 characters of that source's `text` | holdout |
| AC-19 | scope beta; `DeskAnswer` cites source 1 with a quote copied from source 1's `text` (at least 30 characters) | wait for the turn | that sentence `status` `found`, its citation `grounded` true; `check.found` 1 | holdout |
| AC-20 | as AC-19, but the quote is `EUR 9,999 million was spent on capex` (in no source) | wait for the turn | that sentence `status` `to_check`, citation `grounded` false | holdout |
| AC-21 | scope beta; `DeskAnswer` with 4 sentences: one citing source 1 with `Group capex: EUR 3,100 million.`, one with no citation, one citing source 99 with that same quote, one with two citations of source 1, `Group capex: EUR 3,100 million.` and `Group capex: EUR 3,300 million.` | wait for the turn | statuses in order `found`, `to_check`, `to_check`, `to_check`; `check` is `{"found": 1, "calculated": 0, "to_check": 3}` | holdout |
| AC-22 | scope beta; 6 sentences: 2 citing source 1 with lines of beta-2025, the 3 sentences of AC-23 (in that order after them), 1 with no citation | wait for the turn | statuses in order `found`, `found`, `found`, `found`, `calculated`, `to_check`; `check.found + check.calculated + check.to_check` is 6 | holdout |
| AC-23 | scope beta; sentence 1 quotes `Investments in renewables and grids: EUR 1,900 million.` (source holding it), sentence 2 quotes `Group capex: EUR 3,100 million.`, sentence 3 `That is a low-carbon share of 61.3%.` with `"calculation": "c1"`; `c1` = label `Low-carbon share`, expression `1900 / 3100 * 100`, decimals 1, unit `%` | wait for the turn | sentence 3 `calculated`; `answer.calculations[0]` has `expression` `1900 / 3100 * 100`, `display` `61.3`, `formula` `Low-carbon share = 1900 / 3100 * 100 = 61.3%`, `error` null, `result` within 0.0001 of 61.2903 | holdout |
| AC-24 | as AC-20, and the turn body also holds `"check": false, "skip_check": true, "grounding": false` | wait for the turn | the sentence is still `to_check`; `check` stage `done` | holdout |
| AC-25 | as AC-23 but expression `2000 / 3100 * 100` and sentence text `… 64.5%.` | wait for the turn | sentence 3 `to_check` (2000 is in no grounding quote); `formula` `Low-carbon share = 2000 / 3100 * 100 = 64.5%` | holdout |
| AC-26 | scope beta; calculations `c1` `__import__('os')`, `c2` `1 / 0`, `c3` 201 characters of `1+`; 3 sentences naming c1, c2, c3 in turn | wait for the turn | `error`s are `Only numbers and + - * / ( ) are allowed.`, `Division by zero.`, `The formula is longer than 200 characters.`; each `formula` null; the 3 sentences `to_check` | holdout |
| AC-27 | scope company `empty` (a folder with no files) | a Quick turn | `done`; `answer.sentences` is one sentence with `text` `I found no reports or saved data in this chat's scope.` and `status` `to_check`; `calls.jsonl` has no `DeskAnswer` call | holdout |
| AC-28 | scope beta; `DeskAnswer.json` is `{"error": "boom"}` | wait for the turn | `status` `failed`, `error` `The model call failed: boom`, stage `write` `failed` | holdout |
| AC-29 | a chat titled `New chat` | first turn with a 70-character question | `GET` the chat: `title` is the question's first 60 characters | unit |
| AC-30 | a `running` turn whose `updated_at` is 11 minutes old | another `POST .../turns` in that chat | the old turn is `failed` with `error` `interrupted`; the new one `202` | unit |
| AC-31 | two `done` turns in the chat | a third turn | its `DeskAnswer` prompt contains both earlier questions | unit |
| AC-81 | `$ARP_RUNS_DIR/_universes/utilities.csv`, in the format `load_company_universe` reads, with `company_id` `acme` and `beta` | `PUT .../scope` with `{"kind": "universe", "ref": "_universes/utilities.csv"}` (the path form `load_saved_universe` accepts) | `200`; the item's `label` is `utilities.csv`; a Quick turn then has `pick_sources.detail` `{"companies": 2, "documents": 2}` | holdout |
| AC-82 | Alice's chat | `PUT .../scope` with `{"kind": "run", "ref": "nosuch"}` | `422`, detail `Unknown run: nosuch` | holdout |
| AC-83 | Alice's chat with scope acme and 2 finished turns | Alice `GET /api/desk/chats/{id}` | `scope` as put; `turns` has the 2 turn ids, oldest first | holdout |
| AC-84 | report folders `acme`, `beta` | `GET /api/desk/companies?q=AC`; then `?limit=0` | first `200` with `total` 1 and the one item `company_id` `acme`, `reports` 1; second `422` | holdout |
| AC-85 | Alice has 21 chats | `GET /api/desk/chats` | 20 entries | unit |

### Slice 2: screens and event stream

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-32 | a `done` Quick turn T (API) | `GET /api/desk/turns/{T}/events` | `Content-Type` starts `text/event-stream`; body is 6 `event: stage` messages whose `data` `name`s are the six stages in order, then `event: end` with `data` `{"status": "done"}` | holdout |
| AC-33 | a running turn (`DeskAnswer` `delay_seconds` 5) (API) | read its event stream to the end | at least one `stage` message has `"status": "running"`; the last message is `end` `{"status": "done"}`; the stream closes | holdout |
| AC-34 | a `failed` turn (API) | its event stream | last message `end` with `data` `{"status": "failed"}` | holdout |
| AC-35 | Alice's turn (API) | Bob `GET .../events` | `404` `Turn not found` | holdout |
| AC-36 | routed `GET /api/desk/chats` with 2 chats titled `Capex A` and `Capex B` | open `#/argus/desk` | heading `Research Desk`; `Recent chats` lists `Capex A` and `Capex B`; `Quick` has `aria-pressed="true"`; `Ask` disabled | holdout |
| AC-37 | routed companies `[{"company_id": "acme", "name": "Acme Power", "reports": 1}]`; routed `POST /api/desk/chats` → `201 {"id": 7, …}` | type `capex?`, click `+ Saved company`, pick `Acme Power`, click `Thorough`, click `Ask` | requests in order: `POST /api/desk/chats`, `PUT /api/desk/chats/7/scope` with `items` `[{"kind": "company", "ref": "acme"}]`, `POST /api/desk/chats/7/turns` with `{"question": "capex?", "mode": "thorough"}`; URL ends `#/argus/desk/7` | holdout |
| AC-38 | routed running Thorough turn; event stream fixture: `pick_sources` done (ms 100), `split` done, `search` running | open the chat | `Working on it · step 3 of 6`; rows `Picked the sources` with `0.1 s`, `Split the question`, `Searched the reports` | holdout |
| AC-39 | routed running Quick turn (`split`, `rank` `skipped`, `pick_sources` running) | open the chat | `Working on it · step 1 of 4`; no row `Split the question` or `Picked the best passages` | holdout |
| AC-40 | routed `done` turn with 3 sentences: `found` citing 1, `calculated` (c1, display `61.3`, unit `%`, formula `Low-carbon share = 1900 / 3100 * 100 = 61.3%`), `to_check`; `check` `{1,1,1}` | open the chat | lead heading is sentence 1's text; `1 to check.`; chips `1 in source`, `1 calculated`, `1 to check`; sentence 2's text is directly followed by `(calculated)`, sentence 3's by `to check`; a block `How the 61.3% was worked out` showing the formula | holdout |
| AC-41 | as AC-40 with `check` `{2,1,0}` (no `to_check`) | open the chat | `Every figure checked.` and chip `0 to check` | holdout |
| AC-42 | as AC-40; source 1 `filename` `acme-2025.txt`, `company_name` `Acme Power`; the citation `page` 4, `grounded` true | click citation chip `1` | a panel shows `Acme Power`, `acme-2025.txt`, `Page 4`, the quote, `found word for word`; `Esc` closes it | holdout |
| AC-43 | a citation with `grounded` false | click its chip | the panel shows `not found in the source` | holdout |
| AC-44 | routed `done` turn, sources `n` 1 to 3 `used` true, `n` 4 false | click `How was this found?` | `How this answer was found`; `The 3 passages the answer used`; 3 table rows with `Rank` `1st`, `2nd`, `3rd`; `Back to the answer` returns to the answer | holdout |
| AC-45 | routed `failed` turn, `error` `The model call failed: boom` | open the chat | `This question failed: The model call failed: boom`; the follow-up box is enabled | holdout |
| AC-46 | routed `GET /api/desk/chats/9` answers `404` | open `#/argus/desk/9` | `Chat not found.` | holdout |
| AC-47 | routed `done` turn; after the POST, routed `GET /api/desk/chats/<id>` answers both turns | type a follow-up and click `Ask` | `POST /api/desk/chats/<same id>/turns` with that question; the earlier question is listed under `Earlier` | holdout |
| AC-48 | an existing Argus flow with the default schema | open `#/argus`; open `#/argus/<flowId>/1` | the first shows `h1` `Argus`; the second shows `h1` `New extraction` (the Research Desk route does not catch them) | holdout |
| AC-49 | the running app, stand-in `DeskSubQuestions` and `DeskAnswer` each with `delay_seconds` 3, the answer quoting a seeded report of company `acme` | the evaluator picks Acme in `+ Saved company`, asks in Thorough, watches the steps, opens a citation, opens `How was this found?` | the steps advance live to `Checked every figure`; the answer shows its FigureCheck; the citation panel quotes the report text; the passages table lists the cited passages | evaluator |

### Slice 3: saved company data

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-51 | run `r1` (company `acme`) with a review item for `acme`, field `capex_total`, period `2025-12-31`, value 6400, unit `EUR m`; decision `approve` | a Quick turn on scope acme asking `capex_total` | `sources` holds one `review_value` with `run_id` `r1`, `value` 6400, `decision` `approve`, `text` `acme · capex_total · 2025-12-31 · 6400 EUR m · reviewed value, run r1` | holdout |
| AC-52 | as AC-51, then a later `reject` decision on the same item | a turn | no `review_value` source for that item | holdout |
| AC-53 | decisions `approve`, then `edit` with `edited_value` 6500 | a turn | the source's `value` is 6500 and `decision` `edit` | holdout |
| AC-54 | scope acme; XBRL store: CIK `0000000001` fetched by `acme`, fact `CapitalExpenditure` (no catalog label), period 2025-01-01 to 2025-12-31, fiscal year 2025, fiscal period `FY`, value 6400000000, unit `USD`, form `10-K`, filed `2026-02-01` | a turn asking `CapitalExpenditure` | one `xbrl_fact` source with `cik` `0000000001`, `value` 6400000000, `form` `10-K`, `text` `CapitalExpenditure · FY2025 FY · 6400000000 USD · XBRL fact, 10-K filed 2026-02-01` | holdout |
| AC-55 | scope acme; 30 approved review values for acme, all matching the question | a turn | at most 20 sources are `review_value` or `xbrl_fact`; `pick_sources.detail.saved_rows` equals their count | holdout |
| AC-56 | a sentence citing the AC-51 source with quote `6400 EUR m` | wait for the turn | citation `source_kind` `review_value`, `grounded` true, sentence `found` | holdout |
| AC-57 | runs `r1` and `r2`, both with company `acme` and an approved `capex_total` value each; scope `{"kind": "run", "ref": "r1"}` | a turn asking `capex_total` | every `review_value` source has `run_id` `r1` | holdout |
| AC-58 | as AC-51 and AC-54, plus report acme-2025 | `GET /api/desk/companies?q=acm` | the `acme` item has `reports` 1, `reviewed_values` 1, `xbrl_first_year` 2025, `xbrl_last_year` 2025 | holdout |
| AC-59 | routed answer citing a `review_value` source (run `r1`) and an `xbrl_fact` source (form `10-K`, filed `2026-02-01`) | open the chat; click each chip | chips read `Reviewed value` and `XBRL fact` after their numbers; the panels show `Run r1` and `10-K filed 2026-02-01` | holdout |
| AC-60 | routed companies: `Acme Power` reports 2, reviewed 36, XBRL 2019–2025; `Beta Grid` reports 1, reviewed 0, no XBRL | open `#/argus/desk` | `Saved company data` rows: `2 reports · 36 reviewed values · XBRL facts 2019–2025` and `1 reports · 0 reviewed values`; ticking `Acme Power` adds an `Acme Power` chip | holdout |

### Slice 4: uploads

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-61 | Alice's chat; a valid 2-page text PDF | `POST .../uploads` | `202`, `status` `reading`; within 30 s `GET .../uploads` shows it `ready`; the chat's scope holds `{"kind": "upload", "ref": "<id>"}` | holdout |
| AC-62 | Alice (analyst) and Vic (viewer) | each uploads a valid PDF | Alice `202`; Vic `403` | holdout |
| AC-63 | files `a.html`, `a.exe`, `a.txt` | upload each | each `415`, detail `Only PDF, Word (.docx) or Excel (.xlsx) files can be uploaded.` | holdout |
| AC-64 | `ARP_MAX_UPLOAD_BYTES=1000000`, a 1 000 001-byte `.pdf` | upload | `413`, detail `File is larger than the 1 MB upload limit.`; nothing under `$ARP_DESK_UPLOADS_DIR` | holdout |
| AC-65 | `x.pdf` holding `hello`; `x.docx` holding `hello` | upload each | each `415`, detail `The file content does not match its type.` | holdout |
| AC-66 | `.hidden.pdf`; an empty `e.pdf` | upload each | `400` `File names cannot start with a dot.`; `400` `The file is empty.` | holdout |
| AC-67 | a chat with 20 uploads | a 21st | `409`, detail `A chat holds at most 20 uploads.` | holdout |
| AC-68 | Alice's chat C, upload U | Bob `GET /api/desk/chats/{C}/uploads` and `POST .../uploads/{U}/save` | each `404` | holdout |
| AC-69 | company `Acme Power` (key `acme`) with active LEI `5299000ACMEPOWER0012`; a PDF whose page 1 holds that LEI | upload; wait for `ready` | `detection` `lei`, `detected_company_id` `acme`, `detected_company_name` `Acme Power` | holdout |
| AC-70 | as AC-69, upload U in chat A (unsaved); chat B owned by Alice with scope company `acme` and no report files | a Quick turn in B; then a turn in A | B's turn: no source has `kind` `upload` and its answer is the AC-27 sentence; A's turn: sources include `kind` `upload` with `upload_id` U; `$ARP_DOCUMENTS_DIR/acme` does not exist | holdout |
| AC-71 | AC-69's `ready` upload | `POST .../uploads/{U}/save` `{}` | `200`, `saved_company_id` `acme`, `saved_at` set; `$ARP_DOCUMENTS_DIR/acme/other/<file name>` exists with the same bytes | holdout |
| AC-72 | a `ready` upload with `detection` `none` | save with `{}`; then with `{"company_id": "acme"}`; then again | `422` `Pick the company to save this report under.`; `200`; `409` `Already saved.` | holdout |
| AC-73 | unsaved upload U1 with `created_at` 31 days ago; unsaved U2 created 29 days ago | `arp retention cleanup --apply` | output has `deleted: desk upload <U1>` and no line naming U2; U1's folder, `desk_uploads` row and scope row are gone; U2's remain | holdout |
| AC-74 | upload U3 saved, `created_at` 40 days ago | `arp retention cleanup --apply` | no line names U3; its folder and row remain; the saved report under `$ARP_DOCUMENTS_DIR` remains | holdout |
| AC-75 | as AC-73 | `arp retention cleanup` (no `--apply`) | output has `would delete: desk upload <U1>`; U1's folder and row remain | holdout |
| AC-76 | an encrypted PDF with a password | upload; wait | `status` `failed`, `error` `password protected` | unit |
| AC-77 | routed: drop 2 PDFs on `#/argus/desk`; `POST /api/desk/chats` → 7; uploads answer `reading`, then the list answers `ready`, one with `detected_company_name` `Acme Power`, one with `detection` `none` | drop the files | URL ends `#/argus/desk/7`; rows show `Ready`, `Company found: Acme Power` and `Company not found`; each has `Save to the company`; the line `Uploads stay with this chat for 30 days. Save them to the company to keep them.` | holdout |
| AC-78 | on `#/argus/desk/7`, routed upload answering `415` with the type detail | drop `a.txt` | the row shows `Only PDF, Word (.docx) or Excel (.xlsx) files can be uploaded.` | holdout |
| AC-79 | on `#/argus/desk/7`, routed save answering `200` with `saved_company_id` `acme`, `saved_company_name` `Acme Power` | click `Save to the company` | `POST /api/desk/chats/7/uploads/<id>/save`; the row shows `Saved to Acme Power` | holdout |
| AC-80 | the running app, two seeded PDFs of two registry companies, a stand-in answer quoting both | the evaluator drops both on Research Desk and asks | both rows show the found company; the answer cites both uploads with `Uploaded report` chips and FigureCheck shows `Every figure checked.` | evaluator |
| AC-86 | `$ARP_RUNS_DIR/r9/manifest.json` `{"status": "done"}` and `r9/out.json`, both aged 3651 days; one original in `blob_store_dir` aged 3651 days; unsaved upload U1 31 days old (default retention settings) | `arp retention cleanup` | output has `would delete:` lines for both r9 files, `would delete: <path of the original>` and `would delete: desk upload <U1>`; the summary line starts `would delete <n>, held 0,` where n is the number of `would delete:` lines | holdout |

Must not change: Argus routes and pages (AC-48); Refine endpoints and `select_evidence.py`, `local_files.py` (code
review: unchanged files); `arp retention cleanup` output for run files and originals (AC-86).

## Slices

Four PRs, each with `Spec: research-desk-wave1` and its `Rows:` line, every test change listed, release notes.
Built in order; each later slice merges `origin/main` first.

| Slice | Risk | Size | PR contents | Rows |
|---|---|---|---|---|
| 1 | `risk:normal` | M | `arp/research_desk/` (chats, scope, turns, check, calculator), `api/routers/desk.py`, tables, OpenAPI + generated types, tests | AC-1 to AC-31, AC-81 to AC-85 |
| 2 | `risk:normal` | M | turn event stream; `pages/desk/DeskStart.tsx`, `DeskChat.tsx`; `components/argus/` OrbChat, ScopeChips, StageList, FigureCheck, CitationPanel; route in `App.tsx`; `contract.ts`. Needs `UI review (factory)`; evaluator | AC-32 to AC-49 |
| 3 | `risk:normal` | S | reviewed values and XBRL facts as sources, `source_kind`, company counts; source labels, saved data panel | AC-51 to AC-60 |
| 4 | `risk:high` (owner merges) | M | uploads, detection, save, retention, settings `desk_uploads_dir` and `retention_desk_uploads_days`; DropZone. Needs `UI review (factory)`; evaluator | AC-61 to AC-80, AC-86 |
