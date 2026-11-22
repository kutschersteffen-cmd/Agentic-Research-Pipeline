# Refine chat (stage 1): edit an RFP response or a deck by chatting, in the Agent screen

Date: 2026-11-14, amended 2026-11-22
Slug: refine-chat-design
Risk: this spec PR is `risk:low`. The build is three PRs (see `## Slices`); each names its own risk label.

Status: backend design and rows **approved by the owner on 2026-11-14**. The 2026-11-22 amendment (`## Amendment
2026-11-22: Refine in the Agent screen`, D1 to D3, AC-60 to AC-74c, retired AC-36 to AC-44 and AC-50) **approved by the
owner on 2026-11-22** (button, after three spec-critic rounds).

Owner decisions on 2026-11-14:

- AC-35 changed after approval: the waterfall uses 3 series so negative running totals draw correctly.
- 2026-11-18, after `main` added a second-model fact-check to every RFP draft (`FactCheck`): RFP rows also stand in
  `FactCheck` returning `{}` (nothing unsupported, nothing unanswered).
- ~~2026-11-18: Refine is reached from the command palette and from links on RFP Answers and Report Builder, not
  from the top bar or a workspace row.~~ Superseded 2026-11-22 by the amendment: Refine lives in the Agent screen.

- ~~One chat page, not the Plans page and not a drawer in the existing pages.~~ Superseded 2026-11-22: the owner
  said of PR #473 "use the agent screen/functionality for that". Refine is a thread kind in the Agent screen
  (`2026-11-21-agent-panel-code-mode.md`), with the document in its stage. No separate Refine page is built.
- Split view with an instant in-browser slide preview (now the Agent screen's stream and stage).
- Chat edits to RFP answers count as AI drafts, so the person who asked may approve them.
- During a bulk RFP edit, answers appear one by one as each finishes.
- ~~The exported deck is fully editable in PowerPoint.~~ Superseded 2026-11-19: the owner chose
  `2026-11-18-house-deck-vega-lite-charts` (its AC-23: layout-slide waterfall and heatmap are pictures). Some
  charts are therefore not editable.
- PowerPoint round-trip (upload an edited deck and keep refining) is stage 2, a separate spec, using the
  "read edits back into the app's deck" approach.

History: this spec first came with PR #473 (one Refine page, never merged). That PR is closed; its backend code on
branch `ccr-f2172c39-ocof06` (head `69f9fe0`) may be reused by the builders, merged onto today's `main`.

## Intent

Refining an RFP response or a presentation today means clicking through forms one answer or section at a
time, waiting for a render to see a slide, and having no way to tell the AI "more formal", "shorter",
"use a bar chart". The owner named all three as the problem.

This adds **Refine threads** to the Agent screen: the chat in the stream, the document in the stage. The owner
picks one document (an RFP project or a house-style deck), types an instruction, and sees the change in the stage: deck edits within 1 s of the agent's reply, RFP answers one by one as each is rewritten. Bulk
instructions ("shorten every ESG answer") work in one turn. The exported deck opens in PowerPoint; text
and native charts stay editable, and charts follow `2026-11-18-house-deck-vega-lite-charts`.

The rule that holds elsewhere holds here: **the model proposes edits as typed operations; code applies them,
checks grounding and stores them.** The model never writes to the database directly.

## Goals

1. ~~One page, `Refine`, reachable from the command palette and from links on RFP Answers and Report Builder.~~
   Amended 2026-11-22: a Refine thread in the Agent screen, one per document, reachable from the Agent screen's
   threads column, the command palette and links on RFP Answers and Report Builder, that edits an RFP project's
   answers or a house deck's slides through chat.
2. Bulk edits: one instruction may change many answers or slides in one turn.
3. Style instructions ("more formal", "shorter", "lead with the number", "make slide 3 a bar chart").
4. Live view: a deck change shows within 1 s of the agent's reply; during an RFP turn each rewritten answer
   shows within 2 s of being saved, with a progress line `<done> of <total>`.
5. The slide preview is drawn from the same HTML renderer and slot geometry the export uses
   (`render_deck_html`, `backend/arp/reporting/html_render.py:85`; `house_style.slot_rect`).
6. Undo of the newest turn, repeatable back to the first turn.
7. Every turn is logged: who asked, what they typed, which operations ran, the state before and after.
8. ~~The exported `.pptx` is fully editable: no chart is a picture.~~ Retired 2026-11-19 (owner): charts follow
   `2026-11-18-house-deck-vega-lite-charts`; layout-slide waterfall and heatmap are Vega-Lite pictures.

## Non-goals

- ~~The Plans page and the Ask ARP panel are not touched.~~ Amended 2026-11-22: the Agent screen gains the Refine
  thread kind; its Ask, Plan and Explore modes are not changed.
- Approving RFP answers, exporting the RFP file, managing the library, Auto-fill: they stay on RFP Answers.
- Decks built by the legacy `ReportPlan` path. Only house decks (`deck.json`).
- Editing the storyline. Deck chat starts once a deck exists.
- Uploading a `.pptx` edited in PowerPoint (stage 2).
- Typing directly into the preview. Chat only.
- Streaming the agent's text word by word, WebSockets, server push. The page polls.
- ~~Saving the conversation on the server. History lives in the browser tab, like Ask ARP.~~ Amended 2026-11-22
  (D1): the conversation is the document's stored turns in `refine_turns`, read back by a new list route.

## Anti-goals (a failure even if it works)

- The chat puts a figure or claim into an RFP answer that no library entry backs.
- The preview shows different text or a different chart type from the exported pptx.
- A chat edit overwrites an approved RFP answer.
- An edit cannot be undone.

## Approaches considered

| Approach | Trade-off | Picked |
|----------|-----------|--------|
| A. Split-view page, slide images re-rendered by Chromium after each change | Preview equals export exactly; each change waits seconds | no |
| B. Chat drawer inside RFP Answers and Report Builder | Cheapest; not one page, Report Builder already crowded | no |
| C. Split-view page, slides drawn in the browser from the export's HTML renderer | Instant; preview and export share `render_deck_html` / `slot_rect` | ~~yes (owner)~~ superseded by D |
| D. (2026-11-22) A Refine thread in the Agent screen: chat in the stream, document in the stage, drawn as in C | One place for all agent work; reuses the screen's threads, composer and stage | **yes (owner)** |

Bulk RFP edits: run in the background with answers appearing one by one (**owner**), not one blocking
request.

## Design

### Page (superseded 2026-11-22)

The owner replaced this page with the Agent screen (see the amendment below). The rules in this section about
what the live view shows (RFP view, deck view, overflow outline, `changed` labels, polling, the export notice)
still hold, in the Agent screen's stage; the page itself, its route `#/refine` and its picker are not built.

```
┌ Refine ─ [ RFP: Pension Fund X ▾ ]  [Undo last turn] ─────────────────────┐
│ Chat                        │ Live view           Rewriting… 12 of 40      │
│ you: make all ESG answers   │ Q12 ESG policy   drafted  ● changed          │
│      shorter                │ Q13 Exclusions   drafted  ● changed          │
│ agent: Shortening Q12–Q51.  │ Q14 Voting       approved                    │
│   Not changed: Q14          │                                              │
│   (approved).               │ (deck: slide thumbnails + one large slide,   │
│ [ type an instruction… ]    │  [Export .pptx]  "Preview changed since …")  │
└─────────────────────────────┴──────────────────────────────────────────────┘
```

- Command palette entry `Refine`; an RFP project on RFP Answers links to `#/refine?rfp=<id>` and a report with a
  deck on Report Builder links to `#/refine?report=<id>`. The picker lists RFP projects and reports whose manifest has `has_deck: true`
  (new manifest field, true once `deck.json` exists). The URL
  carries the choice: `/refine?rfp=<project_id>` or `/refine?report=<report_id>`.
- The agent's reply text comes from the model. Under it the page lists, from the turn's result:
  `Changed: <ids>`, `Not changed: <id> (<reason>)` for each, and `Check figures: <ids>`.
- Items changed by the newest turn carry the label `changed` until the next turn starts.
- RFP view: question, answer, status badge, flags, sources (same badges as RFP Answers). Read-only.
- Deck view: thumbnails and the selected slide large, both from `GET /api/reports/{id}/deck/html` in sandboxed
  iframes. A slot whose text overflows its box (`scrollHeight > clientHeight` on its `data-slot` element)
  gets a red outline and the label `Text doesn't fit`.
- Polling: while a turn runs, the page fetches the turn and the document every 1 s; otherwise the document
  every 3 s for as long as the page is open (RFP Answers polls only while running; this page always polls,
  so other people's edits show).
- Deck only: after any chat edit the page shows `Preview changed since last export` and an `Export .pptx`
  button until the next export.

### Turn API (new)

- `POST /api/refine/{kind}/{doc_id}/turns`, `kind` ∈ `rfp`, `deck`. Body `{message, history}`. `history` is a
  list of `{message, reply}` of any length; the server keeps the last 5 (no 422 for longer lists).
  Every turn: insert the `running` row, return 202 `{turn_id}`, then call the model and apply the ops in the
  background. Requires role analyst or approver; viewer gets 403
  `Viewers cannot change documents.`
- `GET /api/refine/turns/{turn_id}` returns `{status, reply, done, total, changed, not_changed:
  [{id, reason}], check_figures, error}`; `status` ∈ `running`, `done`, `failed`, `undone`.
- One running turn per document, enforced in Postgres (a partial unique index on `(kind, doc_id)` where
  `status = 'running'`), so it holds across API workers. A second turn returns 409
  `A change is already running on this document.`
- Ids in results: RFP question ids as integers; deck slides as 1-based positions in `deck.slides`.
- The model call: one `complete_structured` call with output model `RefineOps`:

```json
{"reply": "Shortening Q12 and Q13.",
 "ops": [{"op": "rewrite", "question_ids": [12, 13], "instruction": "shorter"},
         {"op": "set_chart_type", "slide": 3, "chart_type": "column"}]}
```

  Op fields: `op`, plus `question_ids`, `instruction`, `slide`, `slot`, `text` (string or list of strings),
  `variant`, `chart_type`, `to` as each op needs.
- Prompt contents: the last 5 history turns, the message, and the document. For RFP: per question its id,
  status, question text and the first 300 characters of the answer, at most 400 questions (constant
  `REFINE_MAX_QUESTIONS`); a larger project gets the reply
  `This RFP has more than 400 questions. Name a section or question numbers.` and no ops. For a deck: per
  slide its position, layout, variant, headline, slots, chart type, and the variants and slot names its
  layout allows.
- A turn whose model call fails ends `failed` with `error` = the exception text and changes nothing.
- A turn still `running` when the API starts, or `running` for more than 10 minutes (constant
  `REFINE_TURN_TIMEOUT_MIN`), is set to `failed` with `error` `interrupted`, so a dead worker cannot lock a
  document for good. Items it already saved stay and are listed in its `changed`.

### RFP operations

| Op | Effect |
|----|--------|
| `rewrite(question_ids, instruction)` | Re-drafts each answer through the grounded drafting (`draft_answer`, `backend/arp/rfp/draft.py:85`), extended with an optional style instruction and the current answer as a starting point |
| `leave_blank(question_ids)` | Same effect as the existing leave-blank action |

- Questions are processed one at a time in id order; each result is saved and `done` incremented before
  the next starts. This is what makes answers appear one by one.
- `approved` questions are never changed: `not_changed` reason `approved`.
- `no source` questions are not rewritten: reason `no source; use Auto-fill on RFP Answers`. (This also
  keeps chat out of Auto-fill's way: Auto-fill only touches `no source` questions.)
- A re-draft that returns `NO_SOURCE` (no entry selected, no citation, a quote not found, or a number found
  in neither the question nor a cited entry, `draft.py:106`) counts as a grounding failure: the previous
  answer, status, sources and flags stay; reason `not backed by the library`.
- A successful re-draft sets the new answer, status `drafted`, `sources`, `flags`, and `last_editor` to null.
  So the person who asked may approve it (owner decision; an untouched AI draft is treated this way today,
  `docs/superpowers/specs/2026-10-21-rfp-answers-design.md:161`). Who asked is in the turn log.
- A question id not in the project: reason `no such question`.
- A re-draft that raises (model error, timeout) records reason `draft failed` for that question; the turn
  continues with the next one and still ends `done`, so everything it saved can be undone.

### Deck operations

| Op | Effect |
|----|--------|
| `set_text(slide, slot, text)` | Replaces one slot's text or bullet list |
| `set_headline(slide, text)` | Replaces the headline |
| `set_variant(slide, variant)` | Switches to another variant of the slide's layout in `style/layouts.json` |
| `set_chart_type(slide, chart_type)` | Changes `ChartSpec.chart_type`; dataset and columns stay |
| `move_slide(slide, to)` / `delete_slide(slide)` | Reorders or removes a slide |

- A deck turn applies all its ops in one step after the model call (no per-item drafting).
- All slide numbers in one turn's ops refer to positions at the start of the turn. Code resolves each to its
  slide first, applies content ops, then moves and deletes in the order given. In `move_slide(slide, to)`, `to` is
  the 1-based position in the list as it stands when that move is applied (after earlier moves and deletes
  of the same turn). Results use positions after the turn.
- An op naming a slot or variant the slide's layout does not have is skipped with reason `no such slot` /
  `no such variant`; a slide number out of range with `no such slide`. Other ops still apply.
- `set_chart_type` to a type the chart's dataset and columns cannot draw (building the chart data or the SVG
  raises) is skipped with reason `chart type does not fit the data`.
- Numbers in text the chat writes must appear in the report's findings, its datasets, or the slide's text
  before the turn; otherwise the slide is listed in `check_figures`. The edit still applies.
- The deck is written through `ReportingStore`; this turn endpoint is the only new writer of `deck.json`.
- New `GET /api/reports/{id}/deck` returns the deck JSON. New `GET /api/reports/{id}/deck/html` returns
  `render_deck_html(deck, request.datasets, mode=request.layout.theme)` with the datasets of the report's
  stored request. Both, and any deck turn, return 409
  `This report has no deck yet. Approve its storyline in Report Builder first.` when there is no `deck.json`.
- The manifest gets `deck_edited_since_render: bool`, set to true by a deck turn that changed anything and
  false by a render.
- Export is the existing `POST /api/reports/{id}/render`: for a house deck it re-renders the stored
  `deck.json` (`ReportingService._rerender`, `backend/arp/reporting/service.py:189`) with no model call.
  The file is fetched with `GET /api/reports/{id}/download?file=output.pptx`.

### Editable export (retired 2026-11-19)

The owner chose `2026-11-18-house-deck-vega-lite-charts` over this section: chart drawing in the preview and the
`.pptx` follows that spec, so layout-slide waterfall and heatmap are pictures. Text slots stay text boxes, native
charts stay native (AC-33, AC-34, AC-48 still hold).

### Turn log and undo

- New table `refine_turns`: `id, kind, doc_id, user_id, message, ops (JSONB), before (JSONB),
  after (JSONB), status, done, total, result (JSONB), created_at, undone_at`.
  `before` / `after` hold every touched question row (answer, status, sources, flags, last_editor) or the
  whole deck.
- Undo requires role analyst or approver; viewer gets 403 `Viewers cannot change documents.`
- `POST /api/refine/{kind}/{doc_id}/undo` takes the newest turn on the document that is `done` and not
  undone, whoever made it, restores its `before`, sets `status = undone` and `undone_at`, and returns 200
  with the turn. Calling it again goes one turn further back.
- Undo is refused with 409 and changes nothing when any touched item's current value differs from the
  turn's `after`, whoever changed it:
  `Q12 changed after this turn; undo would overwrite it.` / `Slide 2 changed after this turn; undo would
  overwrite it.` For an RFP, the first differing question by id. For a deck, the current `deck.json` is
  compared with `after` as a whole; the message names the first position in the current deck whose slide
  differs from `after` (or the first position past the shorter of the two).
- Undoing a deck turn sets `deck_edited_since_render` to true. With no turn to undo: 409 `Nothing to undo.` While a turn is
  running: 409 `A change is already running on this document.`

## Amendment 2026-11-22: Refine in the Agent screen

The owner, on PR #473: "use the agent screen/functionality for that". The Turn API, the RFP and deck operations, the
turn log and undo above stay as approved, with their rows. What changes is where the chat lives: a **Refine thread**
in the Agent screen (`#/agent`, `frontend/src/pages/Agent.tsx`, spec `2026-11-21-agent-panel-code-mode.md`), one per
document, with the chat in the stream and the live view in the stage. It builds on that spec's slice 13 (ask threads)
and on the Agent screen chat layout follow-up (the factory PR titled `agent-panel chat layout: …`, risk:normal:
composer pinned to the bottom, only the stream scrolls).

### Decisions for the owner

Approving this amendment accepts all three as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | **The conversation is stored**: a Refine thread's stream is the document's turns read back from `refine_turns`, by anyone, oldest first, so a reload or another device shows it. The screen sends the newest 5 turns with status `done` as `history`. | Yes (AC-60, AC-69, AC-72) | History lives in the browser tab as the 2026-11-14 design said; a reload shows an empty stream. |
| D2 | **One thread per document**, shared by everyone who refines it; a second person opening it sees the first one's turns. | Yes (AC-61, AC-62c, AC-69) | One thread per person and document; two people refining the same deck see different streams of the same edits. |
| D3 | **Viewers may read** a Refine thread and its live view, with no composer and no Undo. | Yes (AC-71) | Viewers do not see Refine threads at all. |

### API additions

- `GET /api/refine/{kind}/{doc_id}/turns`: the document's turns, oldest first by `created_at`, every status, as
  `RefineTurn {turn_id, user_id, message, reply, status, done, total, changed, not_changed, check_figures, error,
  created_at}`; `reply` is `null` until the model call returns. A document with no turns answers `[]`. Any signed-in
  role may read it.
- `GET /api/refine/threads`: one row per document that has at least one turn, newest first by its newest turn's
  `created_at`: `{kind, doc_id, title, status, last_turn_at, turns}`. `title` is `RFP: <project investor>` or
  `Deck: <report title>`, cut to its first 60 characters; `status` is the newest turn's `status`; `turns` is the
  number of turns. Any signed-in role may read it.
- `GET /api/refine/documents`: what can be refined, for the picker: every RFP project as `{kind: "rfp", doc_id,
  title}` (title as above), then every report whose manifest has `has_deck: true` as `{kind: "deck", doc_id, title}`,
  each group newest first. A report with no deck is not listed.
- Every `title` above is the whole string (`RFP: <investor>` or `Deck: <report title>`, prefix included) cut to its
  first 60 characters. "Newest first" means by the project's `created_at` and by the report manifest's
  `created_at`. A report's `has_deck` is true exactly when its `deck.json` exists (read, not stored), so a deck written
  by any path counts.
- Reads allow any signed-in role, viewers included: the two list routes above, `GET /api/refine/documents`,
  `GET /api/refine/turns/{turn_id}`, `GET /api/reports/{id}/deck` and `/deck/html`.
- `kind` other than `rfp` and `deck` in any `/api/refine/{kind}/...` route answers 404
  `{"detail": "Unknown document kind."}`. Until slice 2 merges, `deck` answers the same.
- RFP progress: a turn's `total` is the number of question ids in its ops (approved, `no source` and unknown ids
  included); `done` goes up by one per id as each is drafted or skipped.
- Nothing in `POST .../turns`, `GET /api/refine/turns/{id}` or `POST .../undo` changes. `history` stays in the turn's
  body (the screen fills it, D1).

### Screen

- *Threads column*: Refine threads join ask threads, plans and explorations, newest first by `last_turn_at`, each
  with its `title` and a chip from its `status` (`running`, `done`, `failed`, `undone`). Selecting one opens
  `#/agent/refine/<kind>/<doc_id>`. The screen re-reads `GET /api/refine/threads` every 3 s. Above the list, a
  button `Refine a document` opens `#/agent/refine`; viewers see the button and the picker too.
- *Picker* (`#/agent/refine`): the stream shows the heading `Refine a document` and the list from
  `GET /api/refine/documents`, in two groups headed `RFP responses` and `Decks`; choosing one opens its thread. A
  document with no turns yet opens with an empty stream and the line `No changes yet. Type an instruction below.`
  (for a viewer: `No changes yet.`).
- *Stream of a Refine thread*: one turn per stored turn, oldest first: the person's `message` with their `user_id`;
  then the `reply`, or `error`, or `Working…` while `running`; under a finished turn the lines `Changed: <ids>`,
  `Not changed: <id> (<reason>)` for each, and `Check figures: <ids>` (each line only when its list is not empty;
  RFP ids as `Q<n>`, slides as `Slide <n>`). A turn with status `undone` carries the label `undone`.
- *Composer on a Refine thread*: no `Mode` group. Label "Instruction", submit button "Refine" ("Refining…"), help
  line "Enter sends the instruction; Shift+Enter adds a line.". It posts `{message, history}` to
  `POST /api/refine/<kind>/<doc_id>/turns`, where `history` is the thread's newest 5 turns with status `done`, oldest
  first, as `{message, reply}`. While a turn on the document is `running` (anyone's), the text box and button are
  disabled. Any response other than 202 shows its `detail` under the composer, or `Request failed (<status>)` when
  it has none (also for a network error, with status `network`). For a viewer (`canAsk` false) the composer is not
  shown. Leaving the Refine thread brings back the `Mode` group in the mode it had before. The pure functions live
  in `lib/agent.ts` (`refineHistory(turns)`, `refineResultLines(kind, turn)`, `refineControls(canAsk)` which
  returns `{composer, undo, picker, emptyLine}`), and the `unit` rows test those.
- *Stage of a Refine thread*: one tab, `Document`, holding the live view the superseded Page section describes, with the RFP progress line
  `Rewriting… <done> of <total>` while an RFP turn runs (RFP
  view or deck thumbnails plus the selected slide, `changed` labels, the overflow outline and `Text doesn't fit`,
  `Preview changed since last export` and `Export .pptx` for a deck). Above it, `Undo last turn` (hidden for a
  viewer); a refusal shows its `detail` under the button. Polling as the Page section says: the turn and the
  document every 1 s while a turn runs, otherwise the document and the turn list every 3 s.
- *Entry points*: the command palette lists `Refine a document`, opening `#/agent/refine`. RFP Answers, on an open
  project, shows a link `Refine in Agent` to `#/agent/refine/rfp/<id>`. Report Builder, on a report whose manifest
  has `has_deck: true`, shows a link `Refine in Agent` to `#/agent/refine/deck/<id>`.

### Rows superseded

AC-36 to AC-44 and AC-50 (the separate page) are retired; AC-62 to AC-70b check the same behaviour in the Agent
screen. They are all `evaluator` rows, so no hidden test is retired. The hidden tests in the holdout repo under
`specs/refine-chat-design/` (backend rows) apply unchanged.

## Constraints

- LLM client from `build_llm_client` (`backend/arp/llm/factory.py:23`). Tests use the stand-in client
  (`backend/arp/standins.py`), keyed by output model name: `RefineOps` for the turn, `DraftOut` for each RFP
  re-draft. Calls are logged to the stand-ins folder's `calls.jsonl`.
- API contract: new models through `scripts/export_openapi.py` and `npm run gen:api`.
- No new frontend dependency.
- `.github/workflows/golden-set.yml`: add `backend/arp/refine/**` and `backend/tests/golden/refine/**` to its
  paths and a step running `arp golden-set refine --cases backend/tests/golden/refine/cases.json
  --min-accuracy 0.9`. Each case is `{doc_fixture, history, message, expected_ops}`; `doc_fixture` names a
  JSON file in `backend/tests/golden/refine/fixtures/` holding an RFP project or a deck.

## Left to the builder

- Prompt wording; module layout under `backend/arp/refine/`; migration file name.
- ~~Where `Refine` sits in the navigation~~ (amended: the Agent screen); thumbnail size.
- How the stage lays out the deck thumbnails and the large slide at each width, keeping the Agent screen's drawers
  below 900 px.

## Acceptance

Holdout and unit rows use the stand-in client: `RefineOps` returns the ops given in "When"; RFP rows also
stand in `DraftOut`, and `FactCheck` returning `{}` (the second-model fact-check `main` added; owner amendment
2026-11-18). Fixture: RFP project P with Q1, Q2 status `drafted` (answers `A1`, `A2`), Q3 `approved`,
Q4 `no source`; library entry E1 whose answer contains `We screen all holdings quarterly.`. A grounded draft
is `DraftOut {answer: "We screen holdings quarterly.", citations: [{entry_id: E1, quote: "We screen all
holdings quarterly."}]}`. Report R has a deck whose slide 2 uses a layout with slots `text` and `chart` (e.g. `two_column`/`text_chart` in `style/layouts.json`),
no slot `sidebar`, and whose findings, datasets and slide 2 text contain no `73`. Report N (amendment rows) has a
storyline and no `deck.json`. Evaluator rows run on the e2e stack (`backend/scripts/e2e_stack.sh up`), signed in as
its dev user `dev`, with the same stand-ins. Slice 3 adds `backend/scripts/seed_refine_e2e.py`, which the evaluator
runs once against that stack: it creates P with E1, R (4 slides headlined S1 to S4; slide 2 as above with a `line`
chart; slide 4 a layout with a `text` slot holding 400 words; R's title `Climate review`), N, and one ask thread T
through the ask stand-in.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | P; grounded draft | `alice` (analyst) posts a turn; ops `rewrite([Q1,Q2], "shorter")` | `POST` 202; the turn ends `done` with `changed` = [Q1, Q2] | holdout |
| AC-2 | after AC-1 | read Q1 and Q2 | each: answer `We screen holdings quarterly.`, status `drafted`, sources = [E1], `last_editor` null | holdout |
| AC-3 | P; stand-in `DraftOut` cites no entry | ops `rewrite([Q1])` | Q1 answer `A1`, status, sources, flags unchanged; `not_changed` = [{Q1, `not backed by the library`}] | holdout |
| AC-4 | P; stand-in draft cites E1 with the correct quote but its answer says `42 funds` | ops `rewrite([Q1])` | Q1 unchanged; `not_changed` = [{Q1, `not backed by the library`}] | holdout |
| AC-5 | P | ops `rewrite([Q3])` | Q3 unchanged; `not_changed` = [{Q3, `approved`}] | holdout |
| AC-6 | P | ops `rewrite([Q4])` | Q4 unchanged; `not_changed` = [{Q4, `no source; use Auto-fill on RFP Answers`}] | holdout |
| AC-7 | P | ops `leave_blank([Q1])` | Q1 status `left blank` | holdout |
| AC-8 | Q1 status `edited`, `last_editor` `bob` (approver); grounded draft | bob's turn `rewrite([Q1])` ends, then bob approves Q1 with all flags confirmed | approve returns 200 | holdout |
| AC-9 | after AC-1 | read `refine_turns` | one row: `user_id` `alice`, `kind` `rfp`, `message` as typed, `ops` = the stand-in ops, `before` = Q1, Q2 as before the turn | holdout |
| AC-10 | P; stand-in `DraftOut` has `delay_seconds: 2`; ops `rewrite([Q1,Q2])` | `GET` the turn 1 s after posting | `status` `running`, `done` 0 or 1, `total` 2 | holdout |
| AC-11 | a turn on P is running (`RefineOps` `delay_seconds: 2`) | a second turn on P | 409, detail `A change is already running on this document.` | holdout |
| AC-12 | a user with role `viewer` | posts a turn on P | 403, detail `Viewers cannot change documents.` | holdout |
| AC-13 | 7 entries in `history` | a turn | the prompt in `calls.jsonl` contains the 5 newest history messages and neither of the 2 oldest | unit |
| AC-14 | after AC-1 | undo on P | 200; Q1, Q2 answer, status, sources, flags, `last_editor` equal their values before AC-1 | holdout |
| AC-15 | two turns on P (`rewrite([Q1])`, then `rewrite([Q2])`) | undo twice | Q1 and Q2 equal their values before the first turn | holdout |
| AC-16 | no done turn on P | undo | 409, detail `Nothing to undo.` | holdout |
| AC-17 | after AC-1, Q1 edited by hand on RFP Answers | undo | 409, detail `Q1 changed after this turn; undo would overwrite it.` | holdout |
| AC-18 | as AC-17 | read Q1, Q2 and the turn | Q1 keeps the hand edit, Q2 keeps the AC-1 answer, the turn's `status` is `done` | holdout |
| AC-19 | R | ops `set_text(2, "text", "Net zero by 2040")` | `GET /api/reports/R/deck`: slide 2 `slots.text` = `Net zero by 2040` | holdout |
| AC-20 | after AC-19 | `GET /api/reports/R/deck/html` | body contains `Net zero by 2040` | holdout |
| AC-21 | R | ops `set_text(2, "sidebar", "x")`, `set_headline(2, "New")` | slide 2 headline `New` | holdout |
| AC-22 | as AC-21 | read the turn | `not_changed` = [{2, `no such slot`}] | holdout |
| AC-23 | R | ops `set_variant(2, "nonexistent")` | slide 2 unchanged; `not_changed` = [{2, `no such variant`}] | holdout |
| AC-24 | R, slide 2 chart type `line` | ops `set_chart_type(2, "column")` | slide 2 `chart.chart_type` = `column`; `dataset_id` and columns unchanged | holdout |
| AC-25 | R with 4 slides headlined S1–S4 | ops `move_slide(4, 1)`, `delete_slide(3)` | headlines in order: S4, S1, S2 | holdout |
| AC-26 | R | ops `set_text(2, "text", "Emissions fell 73%")` | slide 2 `slots.text` = `Emissions fell 73%` | holdout |
| AC-27 | as AC-26 | read the turn | `check_figures` = [2] | holdout |
| AC-28 | after AC-19 | read `refine_turns` | one row, `kind` `deck`, `before` = the whole prior `deck.json` | holdout |
| AC-29 | after AC-19 | undo on R | `GET .../deck` equals the deck before AC-19 | holdout |
| AC-30 | report with no `deck.json` (storyline unapproved, or deck build failed) | a deck turn, or `GET .../deck/html` | 409, detail `This report has no deck yet. Approve its storyline in Report Builder first.` | holdout |
| AC-31 | after AC-19 | read the manifest | `deck_edited_since_render` = true | holdout |
| AC-32 | after AC-19 | `POST /api/reports/R/render` | `calls.jsonl` gains no `kind: model` line; manifest `deck_edited_since_render` = false | holdout |
| AC-33 | after AC-32 | download `output.pptx`, open with python-pptx | slide 2 has a text frame containing `Net zero by 2040` | holdout |
| AC-34 | after AC-24 and a render | open `output.pptx` slide 2 | its chart slot is a native chart of type column; `deck/html` slide 2 chart slot holds an SVG | holdout |
| ~~AC-35~~ | retired 2026-11-19: the owner chose `2026-11-18-house-deck-vega-lite-charts` (its AC-23) | — | — | — |
| ~~AC-36~~ | ~~the app with stand-ins~~ | ~~open the command palette~~ | ~~it lists `Refine`; `/refine?report=R` opens with R selected; the picker lists no report without a deck~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-62 and AC-73 replace it |
| ~~AC-37~~ | ~~Refine on R; `RefineOps` returns `set_chart_type(3, "column")`~~ | ~~owner types `make slide 3 a column chart`~~ | ~~slide 3 in the right pane shows a column chart within 1 s of the reply appearing~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-63 replaces it |
| ~~AC-38~~ | ~~as AC-37~~ | — | ~~slide 3's thumbnail carries the label `changed`~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-63 replaces it |
| ~~AC-39~~ | ~~Refine on a deck whose slide 2 `text` holds 400 words~~ | — | ~~that slot has a red outline~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-64 replaces it |
| ~~AC-40~~ | ~~as AC-39~~ | — | ~~that slot shows the label `Text doesn't fit`~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-64 replaces it |
| ~~AC-41~~ | ~~Refine on P; ops `rewrite([Q1,Q2,Q3])` with grounded drafts, `DraftOut` `delay_seconds: 2`~~ | ~~owner sends an instruction~~ | ~~Q1 shows its new answer and `changed` before Q2 does; a line `1 of 3` then `2 of 3` shows while it runs~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-65 replaces it |
| ~~AC-42~~ | ~~as AC-41, done~~ | — | ~~under the reply: `Changed: Q1, Q2` and `Not changed: Q3 (approved)`~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-66 replaces it |
| ~~AC-43~~ | ~~Refine open on P; another user edits Q2 on RFP Answers~~ | ~~wait 3 s~~ | ~~the Refine view shows the new Q2 answer~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-67 replaces it |
| ~~AC-44~~ | ~~Refine on R after a chat edit~~ | — | ~~`Preview changed since last export` and `Export .pptx` show; after clicking Export they are gone~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-68 replaces it |
| AC-45 | golden cases file `backend/tests/golden/refine/cases.json`, ≥ 15 instructions with expected ops; a case passes when op names and targets (question ids, slide, slot, variant, chart type) equal the expected, instruction text ignored | `arp golden-set refine --min-accuracy 0.9` with the real model | exits 0 | golden |
| ~~AC-50~~ | ~~as AC-41~~ | — | ~~each answer shows in the right pane within 2 s of the progress line's count going up~~ | ~~evaluator~~ retired 2026-11-22: the separate Refine page; AC-65 replaces it |
| ~~AC-51~~ | retired 2026-11-19: the owner chose `2026-11-18-house-deck-vega-lite-charts` (its AC-23) | — | — | — |
| AC-52 | P; the `DraftOut` stand-in returns an error for Q1 and a grounded draft for Q2 | ops `rewrite([Q1,Q2])` | turn `done`; `changed` = [Q2]; `not_changed` = [{Q1, `draft failed`}] | holdout |
| AC-53 | a `refine_turns` row `running` on P from before an API restart | restart the API, then read the turn | `status` `failed`, `error` `interrupted`; a new turn on P returns 202 | unit |
| AC-54 | after AC-1 | a user with role `viewer` posts undo on P | 403, detail `Viewers cannot change documents.` | holdout |
| AC-55 | after AC-32 (deck rendered, flag false) | undo the AC-19 turn on R | manifest `deck_edited_since_render` = true | holdout |
| AC-56 | R with 4 slides headlined S1–S4 | ops `move_slide(1, 4)`, `delete_slide(2)` | headlines in order: S3, S4, S1 | holdout |
| AC-57 | R, slide 2 a `line` chart with one category and one value column, no `value_column` | ops `set_chart_type(2, "heatmap")` | slide 2 chart type stays `line`; `not_changed` = [{2, `chart type does not fit the data`}] | holdout |
| AC-58 | P; grounded draft | ops `rewrite([Q1], "shorter")` | the `DraftOut` prompt in `calls.jsonl` contains `shorter` and `A1` | unit |
| AC-59 | R, after `POST .../render` of its deck | `GET /api/reports` | R's manifest has `has_deck` = true; a report with no deck has `has_deck` = false | holdout |
| AC-60 | after AC-1 | `GET /api/refine/rfp/P/turns` | 200; one item: `user_id` `alice`, `message` as posted, `reply` the `RefineOps` stand-in's `reply`, `status` `done`, `changed` [1, 2], `not_changed` [] | holdout |
| AC-60b | P with no turns | `GET /api/refine/rfp/P/turns` | 200, `[]` | holdout |
| AC-60c | P | `POST /api/refine/memo/P/turns` | 404, detail `Unknown document kind.` | holdout |
| AC-61 | one done turn on P, then one done turn on R | `GET /api/refine/threads` | 200; exactly two rows, in order: `{kind: "deck", doc_id: R, title: "Deck: <R's title>", status: "done", turns: 1}`, then `{kind: "rfp", doc_id: P, title: "RFP: <P's investor>", status: "done", turns: 1}` (plus `last_turn_at`) | holdout |
| AC-61b | as AC-61 | a `viewer` calls `GET /api/refine/threads`, `GET /api/refine/deck/R/turns`, `GET /api/refine/documents`, `GET /api/refine/turns/<R's turn id>`, `GET /api/reports/R/deck` and `GET /api/reports/R/deck/html` | each 200 | holdout |
| AC-61c | P, R and N | `GET /api/refine/documents` | 200; contains `{kind: "rfp", doc_id: P, title: "RFP: <P's investor>"}` and `{kind: "deck", doc_id: R, title: "Deck: <R's title>"}`; no item has `doc_id` N | holdout |
| AC-61d | P; reports R1 then R2 (both with a deck, R2 created later) | `GET /api/refine/documents` | every `rfp` item comes before every `deck` item; R2 comes before R1 | holdout |
| AC-61e | a report with a deck and a 70-character title, one done turn on it | `GET /api/refine/threads` | its `title` is `Deck: ` followed by the title's first 54 characters (60 in all) | holdout |
| AC-62 | the Agent screen, seeded stack | click `Refine a document` | the address is `#/agent/refine` | evaluator |
| AC-62b | as AC-62 | — | group `RFP responses` lists `RFP: <P's investor>`; group `Decks` lists `Deck: Climate review` and nothing for N | evaluator |
| AC-62c | as AC-62 | choose `Deck: Climate review` | the address is `#/agent/refine/deck/R`; the stream shows `No changes yet. Type an instruction below.` | evaluator |
| AC-62d | as AC-62c | — | the stage has exactly one tab, `Document`, with 4 slide thumbnails | evaluator |
| AC-63 | R's thread; `RefineOps` returns `set_chart_type(2, "column")` | type `make slide 2 a column chart`, press Enter | slide 2 in the stage shows a column chart within 1 s of the reply appearing | evaluator |
| AC-63b | as AC-63 | — | slide 2's thumbnail carries `changed` | evaluator |
| AC-63c | as AC-63 | wait 3 s | the threads column's first row is `Deck: Climate review` with chip `done` | evaluator |
| AC-64 | R's thread | open slide 4 in the stage | its `text` slot has a red outline and the label `Text doesn't fit` | evaluator |
| AC-65 | P's thread; ops `rewrite([Q1,Q2,Q3])`, grounded drafts, `DraftOut` `delay_seconds: 2` | send an instruction | Q1 shows its new answer and `changed` before Q2 shows its new answer | evaluator |
| AC-65b | as AC-65 | — | while it runs the stage shows `Rewriting… 1 of 3`, then `Rewriting… 2 of 3` | evaluator |
| AC-65c | as AC-65 | — | each new answer shows within 2 s of the count going up | evaluator |
| AC-66 | as AC-65 | the turn ends `done` | under the reply: `Changed: Q1, Q2` and `Not changed: Q3 (approved)` | evaluator |
| AC-67 | P's thread open | Q2's answer is changed through the RFP API (as RFP Answers does) | within 5 s the stage shows the new Q2 answer | evaluator |
| AC-68 | R's thread after AC-63 | — | `Preview changed since last export` and `Export .pptx` show | evaluator |
| AC-68b | as AC-68 | click `Export .pptx` and wait for it to finish | neither `Preview changed since last export` nor `Export .pptx` shows | evaluator |
| AC-69 | after AC-63 | reload the page | the stream shows `dev`, `make slide 2 a column chart`, the reply and `Changed: Slide 2` | evaluator |
| AC-70 | after AC-63 | click `Undo last turn` | slide 2 shows a line chart; the turn carries `undone` | evaluator |
| AC-70b | after AC-70 | click `Undo last turn` again | `Nothing to undo.` shows under the button | evaluator |
| AC-71 | — | `refineControls(false)`; `refineControls(true)` | `{composer: false, undo: false, picker: true, emptyLine: "No changes yet."}`; `{composer: true, undo: true, picker: true, emptyLine: "No changes yet. Type an instruction below."}` | unit |
| AC-72 | 7 turns: 6 `done` (m1 to m6, oldest first) and the newest `failed` | `refineHistory(turns)` | `[{message: m2, reply: r2}, …, {message: m6, reply: r6}]`, 5 items, oldest first | unit |
| AC-72b | an RFP turn with `changed` [1, 2], `not_changed` [{3, `approved`}], `check_figures` [] | `refineResultLines("rfp", turn)` | `["Changed: Q1, Q2", "Not changed: Q3 (approved)"]` | unit |
| AC-72c | a deck turn with `changed` [3], `not_changed` [], `check_figures` [2] | `refineResultLines("deck", turn)` | `["Changed: Slide 3", "Check figures: Slide 2"]` | unit |
| AC-73 | seeded stack | open the command palette, type `Refine`, choose `Refine a document` | the address is `#/agent/refine` | evaluator |
| AC-73b | seeded stack | open P on RFP Answers | a link `Refine in Agent` points to `#/agent/refine/rfp/P` | evaluator |
| AC-73c | seeded stack | open R on Report Builder | a link `Refine in Agent` points to `#/agent/refine/deck/R` | evaluator |
| AC-73d | seeded stack | open N on Report Builder | no `Refine in Agent` link shows | evaluator |
| AC-74 | the Agent screen in `Ask` mode | open R's thread | the composer has no `Mode` group, label `Instruction`, button `Refine` | evaluator |
| AC-74b | after AC-74 | open ask thread T | the `Mode` group shows with `Ask` pressed | evaluator |
| AC-74c | R's thread; `RefineOps` `delay_seconds: 2` | send an instruction | until the reply shows, the text box and the button are disabled and the button reads `Refining…` | evaluator |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-46 | Q1 edited by hand on RFP Answers by `bob` | bob approves Q1 with all flags confirmed | 403, detail `You edited this answer last; another approver must approve it.` | holdout |
| AC-47 | approved storyline | `PUT /api/reports/{id}/storyline` | 409, detail `Storyline already approved` | holdout |
| AC-48 | a deck with a `column` chart slide, rendered | open `output.pptx` | the chart slot is a native column chart, as before this change | holdout |
| AC-49 | — | run `backend/tests/test_ask_tools.py` and `backend/tests/test_ask_transition_plan.py` | all pass, files unchanged | unit |

## Slices

Each PR puts `Spec: refine-chat-design` and its `Rows:` line in its description. Builders may start from the code of
closed PR #473 (branch `ccr-f2172c39-ocof06`), merged onto today's `main`.

| Slice | PR contents | Risk | Rows |
|---|---|---|---|
| 1 | `refine_turns` table, Turn API, `RefineOps` (every op), RFP operations, undo, `GET /api/refine/{kind}/{doc_id}/turns`, golden set and its workflow step | `risk:high` (schema, `.github/workflows/**`) | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-45, AC-46, AC-49, AC-52, AC-53, AC-54, AC-58, AC-60, AC-60b, AC-60c |
| 2 | Deck operations, `GET /api/reports/{id}/deck` and `/deck/html`, manifest `has_deck` and `deck_edited_since_render`, `GET /api/refine/threads`, `GET /api/refine/documents` | `risk:normal` | AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-47, AC-48, AC-55, AC-56, AC-57, AC-59, AC-61, AC-61b, AC-61c, AC-61d, AC-61e |
| 3 | `seed_refine_e2e.py`; Agent screen: Refine threads, picker, stream, composer, `Document` stage tab, Undo, palette entry and the two `Refine in Agent` links | `risk:normal` | AC-62, AC-62b, AC-62c, AC-62d, AC-63, AC-63b, AC-63c, AC-64, AC-65, AC-65b, AC-65c, AC-66, AC-67, AC-68, AC-68b, AC-69, AC-70, AC-70b, AC-71, AC-72, AC-72b, AC-72c, AC-73, AC-73b, AC-73c, AC-73d, AC-74, AC-74b, AC-74c |

Slices go in this order. Slice 1 starts once `agent-panel-code-mode` slice 13 has merged; slice 2 needs slice 1;
slice 3 needs slice 2 and the Agent screen chat layout follow-up (composer pinned to the bottom).
