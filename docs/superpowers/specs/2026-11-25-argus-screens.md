# Argus screens: tab row, Overview, Company ledger, step chats, Review a value

Status: Approved by the owner on 2026-11-26 (spec thread, Approve on head 4fd69d6)
Slug: `argus-screens`
Risk: `risk:normal` for every slice (5 slices = Argus plan PRs 5 to 9)
Plan: https://claude.ai/artifact/HEt7XAniY3yB5Gnj5JyMRM (approved 2026-11-25), sections "Argus additions",
"Frontend plan", "Slices and order", "Testing and acceptance". Screens: https://claude.ai/artifact/EBSKMGCZTVZuwYZ2PLjrQu
(screens 1, 2, 3, 4, 6, 7, 8, 15; the companies there are made up).

## Summary

Argus gets one tab row and a reworked Overview with a Research Desk card (slice 5), a Company ledger that shows
the approved value of every field per company across runs (slice 6), an assistant ("Ask ARP") on step 1 that
explains company issues (slice 7), the same assistant on step 3 plus the hand-off from a Research Desk answer to a
new extraction (slice 8), and a Review a value page with notes, keyboard review and the source PDF in place
(slice 9). The assistant only ever proposes: every change it suggests is a button the person clicks.

## What the user can do afterwards that they cannot do today

- Move between Overview, New extraction, Research Desk, Company ledger, Walkthrough and XBRL Facts from one tab row.
- Drop reports or type a question on the Argus Overview and land in a Research Desk chat.
- See one table of approved values per field and company, across every extraction run, and download it as CSV.
- Ask why a company has two issuers and pick one with a click; see which companies have no documents.
- Describe new fields on step 3 and add the drafted ones with a click.
- Send a Research Desk answer to a full extraction that opens at step 3 with its fields filled.
- Review one value at a time with a note, J/K/A/E/R keys, and the cited PDF page with the quote boxed.

## What exists today (main `7137b77`)

- `#/argus` is `ArgusStart.tsx`: it reads `/api/runs` (paged, `listAllRuns`), `GET /api/argus/flows` and
  `GET /api/review/items`, three calls on two polls. `lib/argusStart.ts` `STEPS` is
  `["Companies", "Documents", "Schema", "Extract", "Results"]`, used by the step bar (`StepBar.tsx`), the start
  page tiles and `filterLine`.
- `App.tsx` routes `#/argus/new` to `ArgusNew` and any other `#/argus/<param>` to `ArgusFlow` (`flowId = params[0]`,
  `step = params[1]`). `#/argusWalkthrough/...` and `#/xbrl` are separate route ids.
- `arp/api/routers/argus.py`: flows are JSON files (`arp/argus/flows.py`, `ArgusFlow`, field `started_by` = user id).
  `GET /flows/{id}` is open to any signed-in user; writes need `analyst`.
- Step 1 rows (`arp/argus/rows.py` `FlowRow`) carry `identifiers` and `master_identifiers` (`{"LEI": [...], ...}`),
  `problem`, `documents` (count on file) and `document_types`. A row with `problem` already gets class
  `argus-row-await` (amber).
- Review: `GET /api/review/items?run_id=`, `GET /api/review/runs/{run}/items/{key}/context` (has `field_definition`,
  `value`, `evidence[]` with `page` computed from char offsets, `quote`, `company_id`, `doc_type`, `source_filename`,
  `documents[]` with `pages` = page count, `suggested_correction`, `failed_checks`, `etag`) and
  `POST .../decision` (`ItemDecisionRequest`: `decision` approve|correct|reject|escalate, `reason_code`, `comment`,
  `corrected_value`, `correction_citation`, `context_etag`). `comment` is already stored on every decision row.
- `ReviewControls.tsx` / `ItemDecision`: a decision button selects the decision, `Submit` sends it;
  `CommentField` is a folded "Add a comment" toggle. `SourcePanel.tsx` `PageView` draws
  `/api/documents/{company}/{doc_type}/{file}/pages/{page}` with `/boxes?q=` as `.source-page-box` elements.
- Model calls: `arp.api.deps.get_llm_client()`; unit tests swap it with `FakeLLMClient` (`tests/conftest.py`
  `fake_llm`, scripted per output model name) via `app.dependency_overrides[deps.get_llm_client]` or
  `monkeypatch.setattr("arp.api.deps.get_llm_client", ...)`. The running app answers model calls from
  `ARP_STANDINS_DIR/model/<OutputModelName>.json` (`arp/standins.py`). `draft_schema` uses output model
  `_SchemaDraft`, `suggest_rules` uses `RuleSuggestions` (`arp/extraction/schema_builder.py`).
- Review decisions per run: `arp/orchestration/review_queue.py` `item_states()` gives each decided item's state
  (`pending`, `first_done`, `disagreed`, `second_done`, `final`; final = `second_done` or `final`) and its
  effective decision row. A run's schema: `arp/extraction/pipeline.py` `load_run_schema()`.

## Built on wave 1 (`research-desk-wave1`, `docs/superpowers/specs/2026-11-25-research-desk-wave1.md`, merged in #732)

Wave 1 (plan PRs 1 to 4) builds `/api/desk`, `DeskStart`/`DeskChat` at `#/argus/desk` and `#/argus/desk/<chatId>`,
and `OrbChat`, `ScopeChips`, `CitationPanel`, `FigureCheck`, `StageList`, `DropZone` in
`frontend/src/components/argus/`. This spec does not specify them again. It uses these wave 1 contracts as that
spec defines them:

- tables `desk_chats` (`id` int, `owner_id`, `title`, `created_at`, `updated_at`), `desk_scope` (`kind` `company` |
  `universe` | `run` | `upload`, `ref`, `label`), `desk_turns` (`question`, `mode`, `status` `running` | `done` |
  `failed`), `desk_uploads` (`saved_company_id`);
- `POST /api/desk/chats` `{"title"?}` → `201 {"id", ...}`; `PUT /api/desk/chats/{id}/scope` `{"items": [{"kind",
  "ref"}]}` (replaces the scope); `POST /api/desk/chats/{id}/turns`; the owner rule (`404` `Chat not found` /
  `Turn not found` for anyone else, approvers too); viewers cannot use Research Desk (`403`);
- the scope's company expansion (a universe's companies, a run's `load_companies(ref)`);
- `Turn.answer.sentences[].citations[]` `{"source", "quote", "grounded", "page"}` and report `Source`
  `{"n", "kind": "report", "company_id", "company_name", "filename", "doc_type", ...}`;
- `OrbChat` props `context` and `onAction`; `DropZone` as on `DeskStart` (creates a chat, uploads each file, opens
  the chat); `DeskStart`'s ask box (placeholder `Ask anything about the companies you pick`).

If wave 1's spec is amended, its contracts win for these names; every contract this spec defines
itself (paths, fields, status codes, labels below) stays as written.

## Goals

- G1 One tab row on every Argus page, current tab marked (slice 5).
- G2 One `GET /api/argus/overview` replaces the start page's three reads (slice 5).
- G3 Overview Research Desk card: drop files or ask, land in the chat; recent chats (slice 5).
- G4 Step labels: step 3 "Fields and settings", step 5 "Review" (slice 5; slice 9 renames what is left).
- G5 Company ledger API, CSV and page; the latest decision per value wins (slice 6).
- G6 Assist endpoint with exact actions; step 1 context and amber issue rows (slice 7).
- G7 Step 3 assist, "Ask these documents first", hand-off from a Desk answer (slice 8).
- G8 Step 5 assist, notes, Review a value with queue keys, Source PDF in place (slice 9).

## Non-goals

Plan PRs 1 to 4 and 10 to 14: page numbers on chunks (Research Desk citations already carry a page from wave 1), the walkthrough roll-up and its `#/argus/walkthrough` route,
settings profiles, the profile picker, the Extraction settings page and tab, the run review page and its button.
The parser track. Any language-model reranker. An EUR column in the ledger (Steffen chose "Not now", 2026-11-25): values stay in their own currency. A chat on the step 5 table itself
(it needs run-wide context, which is the run review).

## Anti-goals (must stay true)

- A1 The assistant never changes anything by itself: no assist or hand-off response applies an action; actions are
  buttons the client runs only on a click.
- A2 Another user's draft flow or chat is not readable through assist (steps 1 and 3) or the hand-off.
- A3 No new global key handler: J/K/A/E/R act only while focus is inside the queue.
- A4 Existing routes keep working: `#/argus/<flow>/<1-5>`, `#/argus/new`, `#/argusWalkthrough/...`, `#/xbrl`.
- A5 Never the word "product" in UI text; the app is "Agentic Research Platform".

## Design

### Roles

| Call | viewer | analyst | approver | Other limits |
|---|---|---|---|---|
| `GET /api/argus/overview` | yes | yes | yes | `recent_chats` are the caller's own only |
| `GET /api/argus/ledger`, `/ledger.csv` | yes | yes | yes | all runs of the team, as review items are today |
| `POST /api/argus/flows/{id}/assist` step 1, 3 | 403 | own flow | own flow | another user's flow answers 404 |
| `POST /api/argus/flows/{id}/assist` step 5 | 403 | yes | yes | any flow with a run: review is two-person |
| `POST /api/desk/turns/{id}/extraction` | 403 | own chat | own chat | another user's turn answers 404 |

"Own flow" is `flow.started_by == principal.user_id`; "own chat" is the turn's chat `owner == principal.user_id`.

### Slice 5: tab row and Overview

**`GET /api/argus/overview`** (any signed-in user) returns `200`:

```json
{"runs": [RunManifest], "flows": [ArgusFlow], "items": [ReviewItem],
 "recent_chats": [{"chat_id": 0, "title": "str", "updated_at": "ISO"}], "profile": "Standard"}
```

- `runs`: every run whose `run_type` is `extraction`, `financials`, `tnfd` or `transition_plan`, newest
  `created_at` first, the same objects `/api/runs` returns.
- `flows`: exactly what `GET /api/argus/flows` returns in `flows`.
- `items`: exactly what `GET /api/review/items` (no `run_id`) returns in `items` for the caller.
- `recent_chats`: the caller's own Research Desk chats (`desk_chats.owner_id`), newest `updated_at` first, at
  most 5; `chat_id` is the chat's integer `id`; never another user's. Empty for a viewer with no chats.
- `profile`: the string `"Standard"` until settings profiles exist (plan PR 12).

`ArgusStart.tsx` reads this one endpoint instead of `listAllRuns`, `listArgusFlows` and `listReviewItems`, polled
every 3 s while a listed run is `pending` or `running`, else every 15 s. What the page shows from runs, flows and
items does not change.

**`ArgusTabs`** (`frontend/src/components/argus/ArgusTabs.tsx`): a `nav` with `aria-label="Argus"` holding links,
in this order:

| Label | href | Current when the hash is |
|---|---|---|
| Overview | `#/argus` | exactly `#/argus` (or `#/argus/`) |
| New extraction | `#/argus/new` | `#/argus/new...` or `#/argus/<flowId>...` (any first param but `desk`, `ledger`) |
| Research Desk | `#/argus/desk` | `#/argus/desk...` |
| Company ledger (from slice 6) | `#/argus/ledger` | `#/argus/ledger...` |
| Walkthrough | `#/argusWalkthrough` | `#/argusWalkthrough...` |
| XBRL Facts | `#/xbrl` | `#/xbrl...` |

The current link has `aria-current="page"` and an underline; no other link has `aria-current`. A tab for a page
that does not exist yet is left out: slice 5 shows 5 links, slice 6 adds Company ledger (6 links). Extraction
settings is not shown (plan PR 13). The tab row renders at the top of every page under `#/argus`,
`#/argusWalkthrough` and `#/xbrl`.

**Overview Research Desk card**: a region `aria-label="Research Desk"` on the start page, with heading
`Research Desk`, the line `Chat with reports or saved company data`, the Orb, wave 1's `DropZone`, a text input
`aria-label="Ask Research Desk"` with an `Ask` button, a `Recent:` line, and a link `Open Research Desk` to
`#/argus/desk`.

- `Recent:` lists the first 3 of `recent_chats` as links with the chat's `title`, each to `#/argus/desk/<chat_id>`.
  With no recent chats the `Recent:` line is not shown.
- Asking: a Research Desk question needs at least one company in scope (wave 1), so the card does not post a turn.
  On `Ask` or Enter with non-blank text, it stores the text in `sessionStorage` key `arp.desk.question` and sets
  the hash to `#/argus/desk`; `DeskStart` (one-line change) puts a stored question into its ask box on open and
  removes the key. Blank text does nothing.
- Dropping or browsing files: the card holds wave 1's `DropZone`, which behaves as on `DeskStart` (creates a chat,
  uploads each file, opens `#/argus/desk/<id>`).
- The `section[aria-label="Process"]` shows the line `Settings: Standard` (from `profile`).

**Step labels**: `STEPS` becomes `["Companies", "Documents", "Fields and settings", "Extract", "Review"]`. The step
bar reads `1 Companies`, `2 Documents`, `3 Fields and settings`, `4 Extract`, `5 Review`; the tile filter line reads
`Showing step 3 Fields and settings only.` This supersedes earlier rows that expect `Schema` or `Results` as step
labels: `2026-10-24-argus-simplified-pipeline-design.md` AC-1, AC-2, AC-7, AC-17 and
`2026-11-12-showcase-argus-fixes.md` AC-76, AC-107 (their label text only; the rest of each row stands). The test
writer updates their hidden tests in the same change; the builder updates the visible e2e tests that assert the
old labels (`tests/e2e/test_argus_step1.py`, `test_argus_showcase_pr3.py`, `test_argus_showcase_fixes.py`) and
lists them in the PR.

**Routing**: `App.tsx` sends `#/argus/ledger` (slice 6) to the ledger and keeps `#/argus/desk...` to wave 1's
pages before the flow route; a flow id is 32 hex characters, so no flow is named `desk` or `ledger`.

### Slice 6: Company ledger

**`GET /api/argus/ledger?fields=&year=&companies=`** (any signed-in user). `fields` and `companies` are
comma-separated field ids and company keys (absent or empty = all); `year` is an integer (non-integer = 422).

Cells come from every run with `run_type == "extraction"` and status `completed` or `partially_completed`. Each
results record `r` and field `f` gives one candidate for the cell `(company_key, field_id, year)`:

- `company_key` = `r.issuer_key`, or `r.company_id` when the record has no `issuer_key`.
- `year` = the first 4 digits of `f.period_end`; when `f.period_end` is empty, the run's reporting year: the
  `reporting_year` of the flow whose `run_id` is this run when that flow exists and the value is set; otherwise
  (no flow, or `null`) the year of the run's `created_at` minus 1.
- `item_key` = `results_field_key(r, f)` (`arp/schemas/review.py`), the key its review decisions use.
- List-item fields (`f.basis` set) are left out of the ledger. Within one run, a cell takes the candidate with the
  latest `period_end`, then the first in results order.
- A stored field without `value_state` is read through `ExtractedField`, which infers it.

**The latest decision wins.** For each cell:

1. Among the cell's candidate runs that have at least one decision row for its `item_key`, the deciding run is the
   one whose newest decision row (by `decided_at`) is newest. If there is one, the cell's status comes from that
   run's item state (`item_states()`):
   - final (`second_done` or `final`) with effective decision `approve`: `approved`, value = that run's `f.value`;
   - final with effective `correct`: `approved`, value = `corrected_value["value"]`, unit =
     `corrected_value["unit"]` when present;
   - final with effective `reject` and `reason_code == "not_disclosed"`: `not_disclosed`, value `null`;
   - any other state or effective decision (pending, escalated, first_done, disagreed, reject for another
     reason): `needs_you`, value = that run's `f.value`.
2. With no decision row in any candidate run, the newest candidate run (by `created_at`) decides from its field:
   `f.route` in (`review`, `hold`): `needs_you`; otherwise `f.value_state` in (`found`, `zero`): `approved`;
   otherwise (`not_found`, `not_applicable`): `not_disclosed` with value `null`.
3. A cell whose status would be `approved` becomes `calculated` when the deciding (or newest) run's schema
   (`load_run_schema`) defines that field with a `derived_rule`. Only boolean fields can have one today, so only
   boolean cells are ever `calculated`.

Except for a final `correct`, a cell's `unit` is `f.unit` of the deciding (rule 1) or newest (rule 2) run. Values
keep their stored JSON type (number, string, boolean).

Response `200`:

```json
{"year": 2025, "years": [2025, 2024],
 "companies": [{"company_key": "str", "name": "str"}],
 "fields": [{"field_id": "str", "name": "str"}],
 "cells": [{"company_key": "str", "field_id": "str", "year": 2025, "value": "str|number|bool|null",
            "unit": "str|null", "status": "approved|needs_you|calculated|not_disclosed",
            "run_id": "str", "item_key": "str", "flow_id": "str|null"}]}
```

- `years`: every year that has a cell after the `fields`/`companies` filters, newest first. `year`: the `year`
  parameter, or the first of `years` when absent (`null` when there are none). `cells` hold only that year.
- `companies` and `fields`: those with at least one cell in `cells`, sorted by `name` (case-insensitive);
  a company's `name` is `r.name` from the newest run (by `created_at`) holding that company, a field's `name` is
  `f.field_name` from the newest run holding that field.
- `run_id`/`item_key`: the deciding run (rule 1) or the newest run (rule 2); `flow_id`: the flow whose `run_id`
  is that run, else `null`.
- Values are as stored, in their own currency and unit (no conversion).

**`GET /api/argus/ledger.csv`** takes the same parameters and returns the same cells as `text/csv` with
`Content-Disposition: attachment; filename="company-ledger-<year>.csv"`, header line
`company,company_key,field,field_id,year,value,unit,status,run_id,item_key`, one line per cell sorted by company
name, then field name, both case-insensitive, empty for `null`.

**Page `#/argus/ledger`** (`ArgusLedger.tsx`): heading `Company ledger`; filters `What` (select: `All fields`, then
one option per entry of `GET /api/extraction/schemas`, newest version of each schema, released or not, by `name`;
choosing one reads that version with `GET /api/extraction/schemas/<id>?version=<v>` and sends `fields=` with its
field ids, comma-separated in schema order), `Year` (select of `years`, showing `year`), and a checkbox
`Only what needs me`; a legend `Approved`, `Needs you`, `Calculated`, `Not disclosed`; a link `Download CSV` whose
`href` is `/api/argus/ledger.csv?year=<year>` with `All fields`, or `/api/argus/ledger.csv?fields=<ids>&year=<year>`
with a schema chosen.

`Only what needs me` (client-side) leaves rows and columns as they are and shows every cell that is not
`needs_you` empty (no value, no status, no `—`).

The table has a header cell `Field`, then one column per company (`name`), and one row per field (`name`). A
cell shows the value as stored followed by a space and the unit when it has one, or `not disclosed` for
`not_disclosed`, or `not found` for a `needs_you` cell whose value is `null`, and under it a dot and the status
label (`Approved`, `Needs you`, `Calculated`, `Not disclosed`). A field/company pair with no cell shows `—`. Under
the table: `— means this field was not extracted for that company yet.`

Clicking a cell opens a side panel (`aside`, `aria-label="Source"`) with `<company> · <field>`, the year, the
value, and, from `GET /api/review/runs/<run_id>/items/<item_key>/context`, the first evidence `quote` and
`<title, else source_filename>, page <page>`; plus a link `Open in Review` to `#/argus/<flow_id>/5` when `flow_id` is
set. When the context call fails the panel shows `The source could not be loaded.`

### Slice 7: assist endpoint, step 1 chat and issue rows

**`POST /api/argus/flows/{flow_id}/assist`**, body `{"step": 1|3|5, "message": "str" (0..2000, default ""),
"item_key": "str|null"}`. Needs `analyst`. Checks in this order:

| Case | Status | `detail` |
|---|---|---|
| viewer | 403 | (existing role message) |
| `step` not 1, 3 or 5, or `message` over 2000 characters | 422 | (validation) |
| no such flow | 404 | `Extraction not found` |
| step 1 or 3 and `flow.started_by != principal.user_id` | 404 | `Extraction not found` |
| step 5 and no `item_key` | 400 | `Pick a value first.` |
| step 5 and `flow.run_id` is null | 409 | `This extraction has not finished.` |
| step 5 and `item_key` not an item of `flow.run_id` | 404 | `Review item not found` |
| a model call fails | 502 | `The assistant could not answer. Try again.` |

Answer `200`: `{"say": "str", "actions": [Action]}`. `Action` has `id`, `kind`, `label` and, per kind:

| kind | Extra fields | id | label | The client on click |
|---|---|---|---|---|
| `pick_issuer` | `company_id`, `lei` | `pick:<company_id>:<lei>` | `Use LEI <lei> for <name>` | `PUT /api/argus/flows/{id}/companies/{company_id}` with the company's current values and `lei` set to the pick |
| `fetch_document` | `company_id` | `fetch:<company_id>` | `Find documents for <name>` | sets the hash to `#/argus/<flow>/2` |
| `add_companies` | `companies` (list of `{name, ticker, isin, lei}`) | `add:companies` | `Add 1 company` / `Add <n> companies` | one `POST /api/argus/flows/{id}/companies` `{company: ...}` per company, in order |
| `add_field` | `field` (a `FieldDefinition`) | `field:<n>` | `+ Add <field name>` | adds the field to step 3's unsaved fields |
| `propose_edit` | `value`, `unit` | `edit:<n>` | `Use <value>` | selects `Edit value` with `Corrected value` filled; sends nothing |
| `ask` | `message` | `ask:<n>` | the message | sends the message as the next assist question |

Fields a kind does not use are `null`. Nothing is sent to any endpoint until the person clicks. A click whose
request fails shows `Could not apply: <detail>` under the action buttons; the rest of the chat stays.

**Empty message: no model call.** The server answers from the flow alone:

- Step 1, no companies: say `Add companies first.`, no actions.
- Step 1 with companies: an *ambiguous* row is one whose flow company has no own `lei` and whose row has 2 or more
  distinct LEIs across `identifiers["LEI"]` and `master_identifiers["LEI"]` (so a pick, which sets the own `lei`,
  ends it); a *no-documents* row has `documents == 0` (the registered count `FlowRow.documents`). With k such rows (a row counted once) of
  n: say `<k> of <n> companies need a look.`, or `Every company has one issuer and documents on file.` when k = 0.
  Actions: one `pick_issuer` per LEI of each ambiguous row (rows in step 1 order, LEIs ascending), then one
  `fetch_document` per no-documents row.
- Step 3: say `Describe what you need and I'll draft fields.`, actions: one `ask` with message `Why Standard?`.
- Step 5: when the item context has `suggested_correction`: say `The verifier read <value>. Use it?` and one
  `propose_edit` `edit:0` with that `value` and `unit` `null`; else say `Ask me about this value.` and no actions.

**Non-empty message: model calls.** The candidates are the empty-message actions of that step, except `ask`;
step 3 first drafts (slice 8). Then one call with output model **`AssistReply`**:

```python
class AssistReply(BaseModel):
    say: str                       # 1..1200 characters
    action_ids: list[str] = []     # ids of candidates, in the order to show
    add_companies: list[CompanyInput] = []  # step 1 only, at most 20
    edits: list[ProposedEdit] = []          # step 5 only, at most 2; ProposedEdit = {value: str (1..100), unit: str|None}
    ask: list[str] = []            # at most 3, each 1..120 characters
```

`actions` = the candidates named in `action_ids`, in that order (unknown or repeated ids dropped), then one
`add_companies` action when `add_companies` is non-empty (step 1 only), then one `propose_edit` per `edits` entry
(step 5 only, ids `edit:1`, `edit:2`), then one `ask` per `ask` entry (ids `ask:0`, ...). Fields the step does not
use are ignored. The prompt sent to the model holds the person's message, every candidate as a line
`<id>: <label>`, and the step's context: step 1 the name of
each ambiguous row with its LEIs, the name of each no-documents row, each row's `problem`, and the identity run's
status; step 3 the flow's companies, settings (`mode`, `evidence_passages`) and the profile name `Standard`;
step 5 the field definition's `name` and `description`, the value, every evidence `quote` and the failed checks'
`plain` text.

The model client comes from `arp.api.deps.get_llm_client` as a FastAPI dependency, so tests swap it with
`app.dependency_overrides[deps.get_llm_client]` (`FakeLLMClient`, scripted for `AssistReply`, `_SchemaDraft`,
`RuleSuggestions`), and the running app answers from `ARP_STANDINS_DIR/model/AssistReply.json` (and
`_SchemaDraft.json`, `RuleSuggestions.json`). Assist never writes the flow file, a decision row or a schema.

What each slice's assist does with a non-empty message: slice 7 makes only the `AssistReply` call on every step
(step 3 with no candidates; `edits` ignored on step 5); slice 8 adds step 3's drafting; slice 9 adds step 5's
`edits`.

**Step 1 UI**: wave 1's `OrbChat` above `Add companies` with context `{flowId, step: 1}`. Its only change: with
`context.flowId` set it sends questions to `POST /api/argus/flows/{flowId}/assist` (`step`, `message`, `item_key`
from context) and shows `say` and one button per action. On step 1 open, when the flow has at least one company,
it sends one assist call with an empty message. The input placeholder is
`Ask about these companies, e.g. "was this company renamed?"`. A 502 shows its `detail` in the chat; the table
still works.

Issue rows: an ambiguous row gets class `argus-row-await` and, in its Identifiers cell, an `await-text` line
`<k> possible` (k = its distinct LEIs). A no-documents row gets class `argus-row-await` and its Documents on file
cell (`None`) gets class `await-text`. When any row has an issue, a line under the table reads
`You can go on with issues open.`; the Continue button stays enabled as today. A flow with no companies sends no
assist call on open. After a `pick_issuer` or `add_companies` click's requests succeed, the page re-reads
`GET /api/argus/flows/{id}` and sends one new empty-message assist.

### Slice 8: step 3 chat, "Ask these documents first", hand-off

**Step 3 assist (non-empty message)**: before `AssistReply`, the server calls `draft_schema(message, llm)` and then
`suggest_rules(<drafted schema>, llm)`. Candidates: one `add_field` per drafted field, then one per
`helper_fields` entry, skipping a field whose `name` (case-insensitive) is already in the flow's chosen schema (when
`schema_choice.kind == "schema"`) or already a candidate. Drafted fields get generated ids, so a candidate's id is
`field:<n>`, n counting candidates from 0 in that order. Nothing is saved. Any of the three model calls failing gives the 502 above.

**Step 3 UI**: `OrbChat` (context `{flowId, step: 3}`) at the top of step 3, placeholder
`Describe what you need, e.g. "add R&D spend and say which part is low-carbon"`; on open it sends one empty-message
call. An `add_field` click adds the field to the fields being edited (unsaved, as a drafted field is today) and the
chip disappears; a chip whose field `name` (case-insensitive) is already among the edited fields is not shown. When the flow has
`desk_origin`, a line under the chat reads `Started from Research Desk · “<question>” · open the answer`, where
`open the answer` links to `#/argus/desk/<chat_id>`.

**Step 2 "Ask these documents first"**: a button on step 2, shown when the flow has at least one company. On
click: `POST /api/desk/chats`, then `PUT /api/desk/chats/<id>/scope` adding each of the flow's companies (by
`company_id`, in flow order), then the hash becomes `#/argus/desk/<id>`. An error shows
`Could not open Research Desk: <error>` next to the button.

**`POST /api/desk/turns/{turn_id}/extraction`** (no body; in wave 1's `/api/desk` router). Needs `analyst`.

| Case | Status | `detail` |
|---|---|---|
| viewer | 403 | (existing role message) |
| no such turn, or its chat's `owner_id` is not the caller | 404 | `Turn not found` |
| the turn's `status` is `running` | 409 | `Wait for the answer to finish.` |
| the turn's `status` is `failed` | 409 | `This answer failed. Ask again first.` |
| the chat's scope gives no company | 400 | `Add a company to the chat first.` |
| `draft_schema` fails | 502 | `Could not draft the fields. Try again.` |

Order: checks, then `draft_schema(turn.question, llm)`, then the writes, so a 4xx or 502 leaves no flow and no
schema. On success `201 {"flow_id": "<id>"}` and a new flow with:

- `started_by`/`started_by_name` = the caller; `companies` = the chat scope's companies expanded as wave 1 expands
  them (scope order; a universe's and a run's companies in their own order), then each saved upload's
  `saved_company_id`, without repeats (first one wins), each registered with
  `register(session, {"company_id": <key>, "name": <companies.name, else the key>})` so its key stays the
  documents folder key;
- the drafted schema saved unreleased (`SchemaRegistry.save`) and `schema_choice = {"kind": "schema",
  "schema_id": <its id>, "version": <its version>}`;
- `source = "upload"`; every flow file whose check passes marked `kept` (as `POST /files` with
  `all_that_pass: true`); `step = 3`;
- new field `desk_origin = {"chat_id", "turn_id", "question"}` on `ArgusFlow` (default `null`).

Each call makes a new flow. Unsaved uploads are not carried over.

**"Send to full extraction"**: a button under each answer whose turn `status` is `done` in `DeskChat` (not under a
running or failed one). On click it calls the hand-off and
sets the hash to `#/argus/<flow_id>/3`; an error shows `Could not start the extraction: <error>` under the answer.

### Slice 9: Review, Review a value, Source PDF

**Step 5 assist**: as in slice 7, with `item_key`; the item and its context are read with the caller's view
(`get_item`, `build_context`), so a blind second reviewer's prompt holds no first decision.

**Rename**: step 5's section `aria-label` becomes `Review`; no visible `Results` text is left on step 5.

**Opening a value**: on step 5, each row with an open review item gets its Value cell as a link to
`#/argus/<flow>/5/<encodeURIComponent(item_key)>`. `ArgusFlow` sends step 5 with a third param to
`ArgusReviewValue.tsx`.

**Review a value** (`#/argus/<flow>/5/<itemKey>`): a link `← 5 Review` to `#/argus/<flow>/5`, heading
`Review a value`, the line `<i> of <n> need you`.

- Queue: a region `aria-label="Queue"` with one button per open item of the run (`GET /api/review/items?run_id=`,
  in that order): company name, field name, value, and the status `Needs you`, or `Awaiting a second review` for an
  item in state `first_done`. The open item's button has `aria-current="true"`. A
  click opens that item (the hash changes to its key).
- Detail: heading `<company> · <field> · <year of period_end>` (without `period_end` it ends at the field name), the value and unit, the first evidence quote, `Why
  it needs you` (the failed checks' `plain` text), `Field definition` (`field_definition.description`), and the
  decision controls of `ItemDecision` with choices `approve`, `correct`, `reject` only (no Escalate), labelled
  `Approve`, `Edit value`, `Reject`.
- Note: a text field labelled `Note for the run review (optional)`, always visible, which replaces `CommentField`
  on this page; its trimmed text is sent as `comment` with the decision (`null` when blank). The decision history
  shows each decision's note.
- After a decision answers, the page re-reads `GET /api/review/items?run_id=` and opens the first item that came
  after the decided one in the old list and is in the new list; if there is none, the last item of the new list
  that came before it; if the new list holds only the decided item, that item; if the new list is empty, the text
  `Nothing needs you in this run.` and the `← 5 Review` link.
- Ask ARP: `OrbChat` with context `{flowId, step: 5, itemKey}`, placeholder `Ask about this value`, one
  empty-message call on open. `propose_edit` selects `Edit value` and fills `Corrected value`; sending still needs
  the citation and `Submit`, as today.

Keys, only while focus is inside the Queue region, and only without Ctrl, Meta or Alt: `J` opens the next item
and `K` the previous (focus moves to that item's button; no wrap at the ends); `A`, `E`, `R` do what clicking
`Approve`, `Edit value`, `Reject` does (select the decision; nothing is sent until `Submit`). Typing these letters
anywhere else (the note, the chat, `Corrected value`) does nothing but type. No `keydown` listener is added to
`window` or `document`.

**Source PDF in place**: a link `Open the page in the PDF`, shown when the first evidence has `company_id`,
`doc_type`, `source_filename` and `page`. A click replaces the detail and chat with the Source PDF view (the hash
does not change):

- heading `<source_filename>`, a button `← Review a value`, the text `Page <p> / <pages>` (`pages` from the
  context's `documents` entry for that `doc_id`), buttons `Previous page` and `Next page` (disabled at 1 and at
  `pages`), `Zoom out` and `Zoom in` with the zoom shown as `<z>%` (100 at open, steps of 25, from 50 to 200),
  and a `Close the PDF` button;
- `PdfPageView` (`frontend/src/components/argus/PdfPageView.tsx`, built from `SourcePanel`'s `PageView`): the page
  image from `/pages/<p>` and, on the cited page only, one `.source-page-box` per box from
  `/pages/<p>/boxes?q=<quote>`; no boxes request on other pages;
- a nav `aria-label="Pages"` of thumbnails for the evidence's cited pages of that document plus the current page,
  ascending, each a button `Page <n>` that opens it;
- focus moves to `Close the PDF` on open. Escape while focus is inside the view, `Close the PDF` or
  `← Review a value` closes it, and focus returns to `Open the page in the PDF`.

The page used is the one the context's `evidence[].page` gives today (from character offsets); pages on chunks
are plan PR 10.

**Research Desk citations**: wave 1's `CitationPanel` gets a button `Open page in PDF`, shown when the citation's
`page` is set and its source is a report (`kind` `report`). A click shows `PdfPageView` in the panel for that
source's `company_id`, `doc_type`, `filename` at that page, with boxes for the citation's `quote`, and a
`Back to the citation` button.

## Defaults taken (no owner question needed)

- Step 5 assist is open to any analyst or approver on any flow with a run (second reviewers are other people by
  rule); steps 1 and 3 and the hand-off are owner-only and answer 404 to others.
- An empty assist message never calls the model; its say lines and actions are fixed text above.
- "Missing documents" is `documents == 0` (`None`); per-type expectations ("1 stored, 1 missing") need data we do
  not keep. A `fetch_document` click opens step 2, where finding documents already exists.
- `pick_issuer` labels name the LEI, since a row holds LEIs, not issuer names.
- Ledger: extraction runs only; values in their own currency; its "approved" follows the review states (second
  review included), stricter than wave 1's saved-data default 12; a final reject for a reason other than
  `not_disclosed` shows `needs_you`; deciding a value from the ledger panel is not in scope (`Open in Review`).
- Ledger `What` lists saved schemas; there is no company filter on the page (the API has `companies=`).
- Review a value's queue lists open items only (no Done list); A/E/R select, `Submit` sends.
- The step 5 table gets no chat; the Overview keeps its Runs table and Waiting for you as they are.

## Notes for the builder

- Smallest possible diff, lowest complexity: no helpers, layers or options this spec does not name.
- Each slice that adds or changes an endpoint runs `python scripts/export_openapi.py`, `npm run gen:api`, fixes
  `tsc -b`, commits both generated files and adds a line per new `request<T>()` in `frontend/src/api/contract.ts`.
- After UI changes: a Playwright screenshot of the changed page and `/impeccable:impeccable audit`.
- Builders never attach the holdout repo. LLM credits are empty: every test uses `FakeLLMClient` or stand-ins.
- Ledger shortcut: it reads every extraction run's results and decisions per call; leave a `shortcut:` comment.

## Acceptance

**How the rows run.** API rows run against the app (`TestClient` or `e2e_stack.sh up`) with the model swapped as
above; users A (analyst), B (analyst), V (viewer), P (approver). Browser rows (`holdout` E2E) load the built app
from `e2e_stack.sh up` at 1440 px wide; every API route a row names is answered by the test with `page.route`, and
the test waits for each routed response before reading the page. `evaluator` rows run on `e2e_stack.sh up` with
`ARP_STANDINS_DIR` set and its `model/*.json` files written by the evaluator; finished runs are seeded straight
into the store as `tests/e2e/test_argus_steps45.py` does, with a PDF from `tests/pdf_fixtures.make_pdf`. A row with
"each of" passes only when every listed case holds.

**Flow F** (API rows): a draft flow started by A with three companies, in this order: `cX` (name `X`) linked to a
registry company (`entity_id`) that holds two LEI identifiers `LEI1` and `LEI2` in Postgres, with no own `lei`, and
2 PDFs for `cX`; `cY` (name `Y`) with own `lei` `LEI3` and no documents; `cZ` (name `Z`) with own `lei` `LEI4` and 1
PDF. "PDFs for" a company means stored under `<documents_dir>/<company_id>/10-K/` and registered in the documents
table, as the upload path (`store_upload`) does, since step 1's `documents` counts registered documents. Browser rows route `GET /api/argus/flows/F` with rows
that give the same `identifiers`, `documents` and companies. **Flow G**: a flow of A with finished run R and open
item I1 (used where a row needs steps 3 and 5 on one flow).

### Slice 5: tab row and Overview

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | runs of types `extraction`, `tnfd`, `theme`; one draft flow; one open review item | `GET /api/argus/overview` as V | `200`; `runs` holds the extraction and tnfd runs only, newest `created_at` first; `flows` equals `GET /api/argus/flows` `flows`; `items` equals `GET /api/review/items` `items`; `profile` is `"Standard"` | holdout |
| AC-2 | A has 7 desk chats with `updated_at` 1 minute apart, B has 1 | `GET /api/argus/overview` as A | `recent_chats` holds 5 entries, A's 5 newest by `updated_at`, newest first, each with exactly the keys `chat_id` (the chat's integer id), `title`, `updated_at`; B's chat is not among them | holdout |
| AC-3 | the start page | it loads and the first poll answers | the page requested `GET /api/argus/overview` and made no request to `/api/runs`, `/api/argus/flows` or `/api/review/items` | holdout |
| AC-4 | overview routed with one finished extraction run (schema `Capex` v1, 3 companies, started by A) and 2 open value items of it | `#/argus` opens | the Runs table's row reads `Capex v1`, `3 companies`, step `5 Review`, status `Needs you`; `Waiting for you` reads `2` | holdout |
| AC-5 | any page | each of `#/argus`, `#/argus/new` (create routed), `#/argus/F/2`, `#/argus/desk`, `#/argusWalkthrough`, `#/xbrl` opens | `nav[aria-label="Argus"]` holds links `Overview`, `New extraction`, `Research Desk`, `Walkthrough`, `XBRL Facts` in this relative order; exactly one link has `aria-current="page"`: `Overview`, `New extraction`, `New extraction`, `Research Desk`, `Walkthrough`, `XBRL Facts` respectively | holdout |
| AC-6 | the tab row on `#/argus` | the links' `href`s are read | the five links of AC-5 point to `#/argus`, `#/argus/new`, `#/argus/desk`, `#/argusWalkthrough`, `#/xbrl`; no link reads `Extraction settings` | holdout |
| AC-7 | a flow at step 5 | it opens | the step bar's items read `1 Companies`, `2 Documents`, `3 Fields and settings`, `4 Extract`, `5 Review` | holdout |
| AC-8 | the start page | the step-3 tile is clicked | the line above the table reads `Showing step 3 Fields and settings only.` | holdout |
| AC-9 | overview routed with `recent_chats` ids 1 to 4 titled `Alpha chat`, `Bravo chat`, `Charlie chat`, `Delta chat` | `#/argus` opens | the `Research Desk` region shows `Recent:` with exactly 3 links `Alpha chat`, `Bravo chat`, `Charlie chat` to `#/argus/desk/1`, `#/argus/desk/2`, `#/argus/desk/3`, and a link `Open Research Desk` to `#/argus/desk` | holdout |
| AC-10 | overview routed with `recent_chats: []` | `#/argus` opens | the `Research Desk` region has no `Recent:` text | holdout |
| AC-11 | the start page; `GET /api/desk/chats` and `/api/desk/companies` routed | `How big is capex?` is typed in `Ask Research Desk` and Enter pressed | the hash is `#/argus/desk`; DeskStart's ask box holds `How big is capex?`; no `POST` to `/api/desk/...` was made | holdout |
| AC-12 | the start page | `Ask` is clicked with `Ask Research Desk` empty | no request to `/api/desk/...` is made and the hash stays `#/argus` | holdout |
| AC-13 | chat create routed to `201 {"id": 9, ...}`, uploads routed | two PDFs are dropped on the card's drop zone | `POST /api/desk/chats`, then two `POST /api/desk/chats/9/uploads`; the hash ends `#/argus/desk/9` | holdout |
| AC-14 | the state after AC-11 | the page is reloaded | DeskStart's ask box is empty | holdout |
| AC-15 | the start page | it loads | `section[aria-label="Process"]` contains the text `Settings: Standard` | holdout |
| AC-16 | the running app, two text PDFs of one company, a `DeskAnswer` stand-in citing one of them | the evaluator drops both on the Overview card; once both read `Ready` in the chat, asks a question | the chat opens at `#/argus/desk/<id>` and its answer shows a citation chip whose panel names one of the two files | evaluator |
| AC-17 | the routed pages of AC-5 and AC-9 | each opens | no visible text matches `/product/i` | holdout |

### Slice 6: Company ledger

Runs below are completed extraction runs; values are JSON numbers unless a row quotes them; every seeded field has
`value_state` `found` and route `auto_accept` unless the row says otherwise; decisions are written straight to the
runs' decision files. A "final" decision is a row with `step` `first` and `second_required` false; a decision that
"needs a second review" is a row with `step` `first` and `second_required` true.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-21 | run R1 (older) and R2 (newer) both hold company K, field `capex`, period 2025-12-31, values `10` and `12`, unit `EUR m`; R1's item has a final `approve` decided at T2; R2's item has a final `approve` decided at T1 < T2 | `GET /api/argus/ledger?year=2025` | one cell for (K, `capex`, 2025): `status` `approved`, `value` `10`, `unit` `EUR m`, `run_id` R1 | holdout |
| AC-22 | as AC-21 but R2's item gets a final `correct` to `{"value": "15", "unit": "EUR bn"}` decided at T3 > T2 | `GET /api/argus/ledger?year=2025` | the cell: `status` `approved`, `value` `"15"`, `unit` `EUR bn`, `run_id` R2 | holdout |
| AC-23 | as AC-21 but R2's item gets a first decision at T3 > T2 that needs a second review (state `first_done`) | `GET /api/argus/ledger?year=2025` | the cell's `status` is `needs_you` and `run_id` is R2 | holdout |
| AC-24 | one run, item with a final `reject`, `reason_code` `not_disclosed` | `GET /api/argus/ledger` | the cell: `status` `not_disclosed`, `value` `null` | holdout |
| AC-25 | one run, item with a final `reject`, `reason_code` `wrong_value` | `GET /api/argus/ledger` | the cell's `status` is `needs_you` | holdout |
| AC-26 | no decisions; four fields with (route `auto_accept`, `found`), (`auto_accept`, `not_found`), (`review`, `found`), (`hold`, `found`) | `GET /api/argus/ledger` | statuses `approved`, `not_disclosed` (value `null`), `needs_you`, `needs_you` | holdout |
| AC-27 | no decisions; R1 older value `10` route `review`, R2 newer value `12` route `auto_accept`, same cell | `GET /api/argus/ledger` | the cell: `approved`, `value` `12`, `run_id` R2 | holdout |
| AC-28 | no decisions; the run's schema gives boolean field `low_carbon_ok` a `derived_rule`; the field is `auto_accept`, `found`, value `true` | `GET /api/argus/ledger` | the cell: `status` `calculated`, `value` `true` | holdout |
| AC-29 | a field with no `period_end` in a run whose flow has `reporting_year` 2023 | `GET /api/argus/ledger` | the cell's `year` is 2023 | holdout |
| AC-30 | a field with no `period_end` in a run with no flow, created 2026-03-01 | `GET /api/argus/ledger` | the cell's `year` is 2025 | holdout |
| AC-31 | cells in 2025 and 2024 | `GET /api/argus/ledger` (no `year`) | `years` is `[2025, 2024]`, `year` is 2025, and every cell has `year` 2025 | holdout |
| AC-32 | cells for fields `a`, `b` and companies K1, K2 | `GET /api/argus/ledger?fields=a&companies=K1` | only the (K1, `a`) cell; `fields` holds only `a` and `companies` only K1 | holdout |
| AC-33 | a failed extraction run and a completed `tnfd` run, both with values | `GET /api/argus/ledger` | neither run gives a cell | holdout |
| AC-34 | — | `GET /api/argus/ledger?year=abc` | `422` | holdout |
| AC-35 | a run started from flow F2 and a run with no flow | `GET /api/argus/ledger` | the first run's cells have `flow_id` F2; the second's `null` | holdout |
| AC-36 | as AC-22, company K named `Kay`, plus a (K, `opex` "Opex", value `3`, unit `EUR m`, route `auto_accept`) cell in R2 | `GET /api/argus/ledger.csv?year=2025` | the body is exactly 3 lines: `company,company_key,field,field_id,year,value,unit,status,run_id,item_key`, then `Kay,K,capex,capex,2025,15,EUR bn,approved,<R2>,<R2 capex item_key>`, then `Kay,K,Opex,opex,2025,3,EUR m,approved,<R2>,<R2 opex item_key>` (field names as stored; quoted only where CSV needs it) | holdout |
| AC-37 | as AC-36 | the same request | `Content-Type` starts `text/csv`; `Content-Disposition` is `attachment; filename="company-ledger-2025.csv"` | holdout |
| AC-38 | ledger routed: year 2025, companies K1 `Kay`, K2 `Lee`, fields `capex` `Capex` and `ok` `Low-carbon ok`, cells (K1, capex, `"10"`, `EUR m`, `approved`, run `r1`, item `k1`, flow `f1`), (K2, capex, `null`, `needs_you`, run `r2`, item `k2`, flow `null`), (K1, ok, `true`, unit `null`, `calculated`, run `r1`, item `k3`, flow `f1`) | `#/argus/ledger` opens | header cells `Field`, `Kay`, `Lee`; row `Capex` shows `10 EUR m` with `Approved` and `not found` with `Needs you`; row `Low-carbon ok` shows `true` with `Calculated` and `—` | holdout |
| AC-39 | the routed ledger of AC-38 | `Only what needs me` is checked | the header still reads `Field`, `Kay`, `Lee` and both rows are shown; the only cell with any text is `not found` with `Needs you` | holdout |
| AC-40 | the routed ledger of AC-38, `What` = `All fields` | `Download CSV`'s `href` is read | `/api/argus/ledger.csv?year=2025` | holdout |
| AC-41 | the routed ledger of AC-38; schemas routed with `Capex set` (fields `capex`, `ok`) | `Capex set` is chosen in `What`, then `Download CSV`'s `href` is read | the ledger was requested with `fields=capex,ok`; the `href` is `/api/argus/ledger.csv?fields=capex,ok&year=2025` | holdout |
| AC-42 | the ledger of AC-38; context of `r1`/`k1` routed with first evidence `quote` `Capex was 10`, `title` `null`, `source_filename` `ar.pdf`, `page` 4 | the `10 EUR m` cell is clicked | `aside[aria-label="Source"]` shows `Kay · Capex`, `Capex was 10`, `ar.pdf, page 4` and a link `Open in Review` to `#/argus/f1/5` | holdout |
| AC-43 | the ledger of AC-38; context routed to `500` | the `10 EUR m` cell is clicked | the Source panel shows `The source could not be loaded.` | holdout |
| AC-44 | slice 6 merged | the tab row on `#/argus/ledger` is read | 6 links; `Company ledger` (href `#/argus/ledger`) comes right after `Research Desk` and is the only one with `aria-current="page"` | holdout |
| AC-46 | the routed ledger of AC-38 | it opens | no visible text matches `/product/i` | holdout |
| AC-45 | V signed in | `GET /api/argus/ledger` and `GET /api/argus/ledger.csv` | each `200` | holdout |

### Slice 7: assist and step 1

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-51 | flow F; no model scripted | `POST /api/argus/flows/F/assist` `{"step": 1, "message": ""}` as A | `200`; `say` `2 of 3 companies need a look.`; action ids in order `pick:cX:LEI1`, `pick:cX:LEI2`, `fetch:cY`; labels `Use LEI LEI1 for X`, `Use LEI LEI2 for X`, `Find documents for Y`; no model call made | holdout |
| AC-52 | a flow of A whose companies each have an own `lei` and at least 1 document | step 1 empty-message assist | `say` `Every company has one issuer and documents on file.`, `actions` `[]` | holdout |
| AC-53 | a flow of A with no companies | step 1 empty-message assist | `say` `Add companies first.`, `actions` `[]` | holdout |
| AC-54 | flow F; `AssistReply` scripted `{say: "Pick one.", action_ids: ["fetch:cY", "nope", "pick:cX:LEI2", "fetch:cY"], add_companies: [{name: "Nor"}], ask: ["Why two?"]}` | step 1 assist with message `which issuer?` | `say` `Pick one.`; action ids `fetch:cY`, `pick:cX:LEI2`, `add:companies`, `ask:0`; the `add_companies` action's label is `Add 1 company` and `companies[0].name` `Nor`; the `ask` action's `message` and label are `Why two?` | holdout |
| AC-55 | flow F; `AssistReply` scripted | step 1 assist with message `which issuer?` | the one prompt sent to the model contains `which issuer?`, `X`, `LEI1`, `LEI2`, `Y` and the lines `pick:cX:LEI1: Use LEI LEI1 for X` and `fetch:cY: Find documents for Y` | holdout |
| AC-56 | flow F (A's) | each of: step 1 assist as B, step 3 assist as B | `404` `Extraction not found`; no model call made | holdout |
| AC-57 | flow F | assist as V | `403` | holdout |
| AC-58 | flow F | each of: `step` 2; a message of 2001 characters | `422` | holdout |
| AC-59 | flow F; the model client raises | step 1 assist with a message | `502` `The assistant could not answer. Try again.` | holdout |
| AC-60 | flow G; `AssistReply`, `_SchemaDraft`, `RuleSuggestions` scripted (every candidate id, `add_companies`, `edits`) | six assist calls as A: steps 1, 3 and 5 (on I1), each with an empty and a non-empty message | G's flow JSON file, R's decision file and the schema list are byte-for-byte unchanged | holdout |
| AC-61 | flow F routed; the empty-message assist routed with the AC-51 answer | `#/argus/F/1` opens | one assist request with `{"step": 1, "message": ""}` was sent; the page shows `2 of 3 companies need a look.` and buttons `Use LEI LEI1 for X`, `Use LEI LEI2 for X`, `Find documents for Y`; no `PUT` or `POST` to `/companies` was made | holdout |
| AC-62 | the page of AC-61 | `Use LEI LEI2 for X` is clicked | one `PUT /api/argus/flows/F/companies/cX` whose body has `lei` `LEI2` and `name` `X` | holdout |
| AC-62b | as AC-62, the `PUT` routed `200` | the `PUT` answers | one `GET /api/argus/flows/F` and one more assist request with `{"step": 1, "message": ""}` follow | holdout |
| AC-63 | the page of AC-61 | `Find documents for Y` is clicked | the hash becomes `#/argus/F/2` | holdout |
| AC-64 | the page of AC-61 with an answer holding `add_companies` `[{name: "Nor"}, {name: "Sve"}]` | `Add 2 companies` is clicked | two `POST /api/argus/flows/F/companies`, the first with `company.name` `Nor`, the second `Sve` | holdout |
| AC-65 | the page of AC-61 | the rows are read | X's and Y's rows have class `argus-row-await`, Z's does not; X's Identifiers cell has text `2 possible`; Y's Documents on file cell has class `await-text`; the text `You can go on with issues open.` is shown | holdout |
| AC-66 | the page of AC-61 | the continue button to step 2 is clicked | one `PATCH /api/argus/flows/F` with `step` 2 is sent and the hash becomes `#/argus/F/2` | holdout |
| AC-67 | assist routed to `502` `The assistant could not answer. Try again.` | a question is asked on step 1 | the chat shows `The assistant could not answer. Try again.` and the company table is still shown | holdout |
| AC-68 | the page of AC-61; the `PUT` routed to `409` `Companies cannot be changed once the extraction has started.` | `Use LEI LEI1 for X` is clicked | the chat shows `Could not apply: Companies cannot be changed once the extraction has started.`; the other buttons are still shown | holdout |
| AC-69 | flow F | `PUT /api/argus/flows/F/companies/cX` with X's values and `lei` `LEI1`, then step 1 empty-message assist | no action id starts with `pick:cX:` | holdout |
| AC-70 | a flow with no companies routed | `#/argus/<flow>/1` opens | no assist request is made | holdout |
| AC-70b | the routed step 1 of AC-61 and the routed step 3 of AC-75 | each opens | no visible text matches `/product/i` | holdout |
| AC-71 | the running app, a flow with a company holding two LEIs (as `cX`), `AssistReply` stand-in choosing `pick:<company_id>:<first LEI>` | the evaluator asks the step 1 chat which issuer to use and clicks the offered button | the row then has no `possible` text and the empty-message chat no longer offers an issuer for it | evaluator |

### Slice 8: step 3, step 2 link, hand-off

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-72 | A's flow whose chosen schema holds a field named `Capex`; `_SchemaDraft` scripted to draft fields named `Capex` and `Low capex`; `RuleSuggestions` scripted with a valid rule on `Low capex` that reads helper field `Grid capex`; `AssistReply` scripted with `action_ids` `["field:0", "field:1", "field:7"]` | step 3 assist with message `low-carbon capex` | `actions` ids `field:0`, `field:1`; labels `+ Add Low capex`, `+ Add Grid capex`; each has a `field` with that `name`; no action is labelled `+ Add Capex` | holdout |
| AC-73 | as AC-72 | the assist call answers | the schema list (`GET /api/extraction/schemas`) is unchanged | holdout |
| AC-74 | A's flow | step 3 empty-message assist | `say` `Describe what you need and I'll draft fields.`; one action `ask:0`, label and message `Why Standard?`; no model call made | holdout |
| AC-75 | step 3 routed with an assist answer holding `field:0` for field `Low capex` | `+ Add Low capex` is clicked | `Low capex` appears among the fields being edited, the chip is gone, and no `POST /api/extraction/schemas` was made | holdout |
| AC-76 | a flow routed with `desk_origin` `{chat_id: 7, turn_id: 70, question: "How much capex?"}` | `#/argus/<flow>/3` opens | the text `Started from Research Desk · “How much capex?” · open the answer` is shown and `open the answer` links to `#/argus/desk/7` | holdout |
| AC-77 | a flow with companies `k1`, `k2` routed on step 2; chat create routed to `201 {"id": 8, ...}` | `Ask these documents first` is clicked | `POST /api/desk/chats`, then `PUT /api/desk/chats/8/scope` with `items` `[{"kind": "company", "ref": "k1"}, {"kind": "company", "ref": "k2"}]`; then the hash is `#/argus/desk/8` | holdout |
| AC-78 | a flow with no companies routed on step 2 | it opens | no `Ask these documents first` button | holdout |
| AC-79 | as AC-77 with chat create routed to `500` `boom` | the button is clicked | text `Could not open Research Desk: ` followed by text containing `boom` is shown; the hash is unchanged | holdout |
| AC-80 | A's chat with companies K1, K2 in scope and a `done` turn `How much capex?`; `_SchemaDraft` scripted with 2 fields | `POST /api/desk/turns/<turn>/extraction` as A | `201` with `flow_id`; `GET /api/argus/flows/<flow_id>` shows `step` 3, company keys K1 then K2, `source` `upload`, `started_by` A, `desk_origin.question` `How much capex?`, and `schema_choice.kind` `schema` pointing at a saved schema with those 2 fields and `release_flag` false | holdout |
| AC-81 | A's chat with company K1 and a universe holding K1 and K2 in scope, a `done` turn | the hand-off as A | the new flow's company keys are K1, K2 (K1 once) | holdout |
| AC-82 | as AC-80, K1 with 2 files of which 1 passes step 2's check | the hand-off as A | in the new flow's view the passing file is `kept` and the other has no decision | holdout |
| AC-83 | as AC-80 | the hand-off twice | two different `flow_id`s | holdout |
| AC-84 | the chat of AC-80 (A's) | the hand-off as B | `404` `Turn not found`; flow list and schema list unchanged | holdout |
| AC-85 | each of: a `running` turn; a `failed` turn | the hand-off as A | `409` `Wait for the answer to finish.`; `409` `This answer failed. Ask again first.` | holdout |
| AC-86 | a chat whose scope is one unsaved upload, with a `done` turn | the hand-off | `400` `Add a company to the chat first.` | holdout |
| AC-87 | as AC-80, `_SchemaDraft` raises | the hand-off | `502` `Could not draft the fields. Try again.`; flow list and schema list unchanged | holdout |
| AC-88 | V | the hand-off | `403` | holdout |
| AC-89 | a `done` answer routed in `#/argus/desk/<chat>`; hand-off routed to `201 {"flow_id": "f1"}` | `Send to full extraction` is clicked | one `POST /api/desk/turns/<turn>/extraction`; the hash becomes `#/argus/f1/3` | holdout |
| AC-90 | the chat of AC-89 with a `failed` turn; then the hand-off routed to `500` `boom` on the done one | the page is read; then `Send to full extraction` is clicked | no `Send to full extraction` under the failed turn; then text `Could not start the extraction: ` with `boom` under the answer | holdout |
| AC-91 | the running app, a chat with two seeded companies, a `DeskAnswer` stand-in and a `_SchemaDraft` stand-in with 2 fields | the evaluator clicks `Send to full extraction` | step 3 opens listing the 2 stand-in field names and the `Started from Research Desk` line | evaluator |

### Slice 9: Review, Review a value, Source PDF

"Run R" is a finished run of flow G (started by A) with open items I1 (`Kay`, `Capex`, period 2025-12-31), I2
(`Lee`, `Capex`), I3 (`Moe`, `Opex`), in that order. I1's context: first evidence `quote` `Capex was 10`,
`company_id` `cK`, `doc_type` `10-K`, `source_filename` `ar.pdf`, `page` 4; a second evidence on page 7 of the same
document; the `documents` entry for it has `pages` 9; `field_definition.description` `Capex on low-carbon assets`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-101 | I1 with `suggested_correction` value `1,180` | step 5 empty-message assist on G as B (not G's starter) | `200`; `say` `The verifier read 1,180. Use it?`; one action `edit:0`, kind `propose_edit`, `value` `1,180`, `unit` `null`, label `Use 1,180` | holdout |
| AC-102 | an item without `suggested_correction` | step 5 empty-message assist | `say` `Ask me about this value.`, `actions` `[]` | holdout |
| AC-103 | I1 as in AC-101; `AssistReply` scripted with `edits` `[{value: "1,200"}]` and `action_ids` `["edit:0"]` | step 5 assist with a message on I1 | action ids `edit:0`, `edit:1`; `edit:1` has `value` `1,200` | holdout |
| AC-104 | `AssistReply` scripted | step 5 assist with message `grids?` on I1 | the prompt contains `grids?`, `Capex on low-carbon assets` and `Capex was 10` | holdout |
| AC-105 | flow G | step 5 assist with no `item_key` | `400` `Pick a value first.` | holdout |
| AC-106 | a flow of A with no run | step 5 assist with an `item_key` | `409` `This extraction has not finished.` | holdout |
| AC-107 | flow G | step 5 assist with `item_key` `nope` | `404` `Review item not found` | holdout |
| AC-108 | step 5 of G routed | it opens | the section has `aria-label="Review"`; I1's Value cell is a link to `#/argus/G/5/<encodeURIComponent(I1 key)>` | holdout |
| AC-109 | Review a value of I1 routed | it opens | link `← 5 Review` to `#/argus/G/5`; heading `Review a value`; text `1 of 3 need you`; the Queue lists 3 buttons in order `Kay`, `Lee`, `Moe`, each with `Needs you`, the first with `aria-current="true"`; the detail heading is `Kay · Capex · 2025`; the buttons `Approve`, `Edit value`, `Reject` are shown and no `Escalate` | holdout |
| AC-110 | as AC-109 | the note `grids included` is typed, `Approve` then `Submit` clicked | one decision `POST` for I1 with `decision` `approve` and `comment` `grids included` | holdout |
| AC-111 | as AC-109 | `Approve` then `Submit` with the note blank | the decision body's `comment` is `null` | holdout |
| AC-112 | as AC-110, decision routed `200`, then items routed without I1 | the decision answers | `GET /api/review/items?run_id=R` is requested again; I2 opens (hash ends in I2's encoded key) and the Queue holds 2 buttons | holdout |
| AC-113 | focus on Kay's queue button | `J`, `J`, `J`, `K` are pressed in turn | after each, the open item is Lee, Moe, Moe, Lee and focus is on that item's queue button | holdout |
| AC-114 | focus in the Queue | `A` is pressed | `Approve` has `aria-pressed="true"`; no decision `POST` was made | holdout |
| AC-115 | focus in the Queue | `E` is pressed, then `R` | after `E`: `Edit value` has `aria-pressed="true"` and `Corrected value` is shown; after `R`: `Reject` has `aria-pressed="true"`; no decision `POST` | holdout |
| AC-116 | focus in the note field | `J`, `A`, `R` are typed | the note reads `JAR`; the open item is still Kay; no decision button has `aria-pressed="true"` | holdout |
| AC-117 | focus on the `← 5 Review` link | `J` is pressed | the open item is still Kay | holdout |
| AC-118 | focus in the Queue | `Ctrl+J` is pressed | the open item is still Kay | holdout |
| AC-119 | step-5 assist routed with `edit:0` `Use 1,180` | `Use 1,180` is clicked | `Edit value` has `aria-pressed="true"` and `Corrected value` holds `1,180`; no decision `POST` was made | holdout |
| AC-120 | Review a value of I1, boxes routed with 2 boxes | `Open the page in the PDF` is clicked | the hash is unchanged; heading `ar.pdf`; text `Page 4 / 9`; an image from `/api/documents/cK/10-K/ar.pdf/pages/4`; one request to `/api/documents/cK/10-K/ar.pdf/pages/4/boxes` with `q=Capex was 10`; 2 `.source-page-box` elements; focus on `Close the PDF` | holdout |
| AC-121 | the PDF open at page 4 | `Next page` is clicked | text `Page 5 / 9`; an image request for page 5 and no boxes request for page 5 | holdout |
| AC-122 | the PDF open at page 4 | the `Pages` nav is read | exactly the buttons `Page 4`, `Page 7`, in that order | holdout |
| AC-123 | the PDF open at page 4 | `Previous page` is clicked 3 times; then `Next page` 8 times | at page 1 `Previous page` is disabled; at page 9 `Next page` is disabled | holdout |
| AC-124 | the PDF open | `Zoom in`, `Zoom in`, `Zoom out` | the zoom text reads `125%`, `150%`, `125%` | holdout |
| AC-125 | the PDF open | `Zoom out` until it stops; `Zoom in` until it stops | `Zoom out` is disabled at `50%`; `Zoom in` is disabled at `200%` | holdout |
| AC-126 | the PDF open, focus inside it | Escape is pressed | the detail is back and focus is on `Open the page in the PDF` | holdout |
| AC-127 | I1's first evidence routed with `page` `null` | Review a value opens | no `Open the page in the PDF` link | holdout |
| AC-128 | a `done` desk turn routed whose citation 1 has `page` 3, source `kind` `report`, `company_id` `cK`, `doc_type` `10-K`, `filename` `ar.pdf`, `quote` `Capex was 10` | citation chip 1, then `Open page in PDF` are clicked | an image from `/api/documents/cK/10-K/ar.pdf/pages/3` and a boxes request for page 3 with `q=Capex was 10` | holdout |
| AC-129 | a citation routed with `page` `null` | its panel opens | no `Open page in PDF` button | holdout |
| AC-130 | the running app, a seeded run with a value needing review | the evaluator opens it from step 5, types a note, approves and submits | the item leaves the queue and its decision history shows the note | evaluator |
| AC-131 | the running app, the seeded run's cited PDF (text layer) | the evaluator opens `Open the page in the PDF` | the cited page number shows with at least one `.source-page-box` over the quote | evaluator |
| AC-133 | the routed Review a value of AC-109, then its Source PDF (AC-120) | each is shown | no visible text matches `/product/i` | holdout |
| AC-132 | the running app, a Research Desk answer (stand-in) citing a seeded PDF on a known page | the evaluator opens the citation and `Open page in PDF` | that page shows with at least one `.source-page-box` over the quote | evaluator |

Must not change (each also a row): AC-4 (start page content), AC-66 (issues never block step 2), AC-60 (assist
writes nothing), AC-116 to AC-118 (no global keys), AC-17, AC-46, AC-70b, AC-133 (no "product").

## Slices

Five PRs, each `risk:normal`, each with `Spec: argus-screens` and its `Rows:` line, every changed test listed.
Order: 5, then 6 and 7 in parallel, then 8, then 9. All start after wave 1 is merged.

| Slice | Plan PR | PR contents | Rows |
|---|---|---|---|
| 5 | 5 | `GET /api/argus/overview`; `ArgusTabs`; `App.tsx` tab row; `ArgusStart` reads the overview; Research Desk card; `DeskStart` reads `arp.desk.question`; `STEPS` renames and the e2e tests asserting old labels | AC-1 to AC-17 |
| 6 | 6 | `GET /api/argus/ledger`, `/ledger.csv`; `ArgusLedger.tsx` at `#/argus/ledger`; `Company ledger` tab | AC-21 to AC-46 |
| 7 | 7 | `POST /api/argus/flows/{id}/assist` with steps 1, 3 (empty message) and 5 (empty message) answers, `AssistReply`; `OrbChat` assist prop; step 1 chat and issue rows | AC-51 to AC-71, AC-70b |
| 8 | 8 | step 3 drafting in assist; step 3 chat and origin line; `desk_origin`; step 2 button; `POST /api/desk/turns/{id}/extraction`; `Send to full extraction` | AC-72 to AC-91 |
| 9 | 9 | step 5 model edits in assist; step 5 rename; `ArgusReviewValue.tsx`; note field; queue keys; `PdfPageView`; Source PDF; `Open page in PDF` in `CitationPanel` | AC-101 to AC-133 |

Slice 7 builds the whole assist contract (all three steps' empty-message answers and the model call); slices 8
and 9 add step 3 drafting and step 5 `edits` to it. AC-60 runs from slice 7 on: all six calls exist from slice 7
(with slice 7's non-empty answers as described under the assist design).
