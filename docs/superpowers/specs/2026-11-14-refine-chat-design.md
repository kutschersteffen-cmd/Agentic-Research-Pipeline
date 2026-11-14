# Refine chat (stage 1): edit an RFP response or a deck by chatting, with a live view

Date: 2026-11-14
Status: draft, waiting for owner approval
Owner decisions on 2026-11-14:

- One chat page, not the Plans page and not a drawer in the existing pages.
- Split view with an instant in-browser slide preview.
- Chat edits to RFP answers count as AI drafts, so the person who asked may approve them.
- During a bulk RFP edit, answers appear one by one as each finishes.
- The exported deck is fully editable in PowerPoint.
- PowerPoint round-trip (upload an edited deck and keep refining) is stage 2, a separate spec, using the
  "read edits back into the app's deck" approach.

## Intent

Refining an RFP response or a presentation today means clicking through forms one answer or section at a
time, waiting for a render to see a slide, and having no way to tell the AI "more formal", "shorter",
"use a bar chart". The owner named all three as the problem.

This adds one page, **Refine**, with a chat on the left and the document on the right. The owner picks one
document (an RFP project or a house-style deck), types an instruction, and sees the change in the right
pane: deck edits within 1 s of the agent's reply, RFP answers one by one as each is rewritten. Bulk
instructions ("shorten every ESG answer") work in one turn. The exported deck opens in PowerPoint with
every text, table and chart editable.

The rule that holds elsewhere holds here: **the model proposes edits as typed operations; code applies them,
checks grounding and stores them.** The model never writes to the database directly.

## Goals

1. One page, `Refine`, in the main navigation, that edits an RFP project's answers or a house deck's slides
   through chat.
2. Bulk edits: one instruction may change many answers or slides in one turn.
3. Style instructions ("more formal", "shorter", "lead with the number", "make slide 3 a bar chart").
4. Live view: a deck change shows within 1 s of the agent's reply; during an RFP turn each rewritten answer
   shows within 2 s of being saved, with a progress line `<done> of <total>`.
5. The slide preview is drawn from the same HTML renderer and slot geometry the export uses
   (`render_deck_html`, `backend/arp/reporting/html_render.py:85`; `house_style.slot_rect`).
6. Undo of the newest turn, repeatable back to the first turn.
7. Every turn is logged: who asked, what they typed, which operations ran, the state before and after.
8. The exported `.pptx` is fully editable: no chart is a picture. Waterfall becomes a native stacked-column
   chart with an invisible base series; heatmap becomes a native table whose cells are filled by value.

## Non-goals

- The Plans page and the Ask ARP panel are not touched.
- Approving RFP answers, exporting the RFP file, managing the library, Auto-fill: they stay on RFP Answers.
- Decks built by the legacy `ReportPlan` path. Only house decks (`deck.json`).
- Editing the storyline. Deck chat starts once a deck exists.
- Uploading a `.pptx` edited in PowerPoint (stage 2).
- Typing directly into the preview. Chat only.
- Streaming the agent's text word by word, WebSockets, server push. The page polls.
- Saving the conversation on the server. History lives in the browser tab, like Ask ARP.

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
| C. Split-view page, slides drawn in the browser from the export's HTML renderer | Instant; preview and export share `render_deck_html` / `slot_rect` | **yes (owner)** |

Bulk RFP edits: run in the background with answers appearing one by one (**owner**), not one blocking
request.

## Design

### Page

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

- Navigation entry `Refine`. The picker lists RFP projects and reports whose manifest has `has_deck: true`
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

### Editable export

- `house_pptx` (`backend/arp/reporting/house_pptx.py:151`) stops inserting chart pictures:
  - `waterfall`: a native stacked-column chart; series 1 is the invisible base (no fill, no line),
    series 2 the step values.
  - `heatmap`: a native table, one cell per value, cell fill from the theme's sequential palette.
- `render_deck_html` changes the same way, so preview and export match: a heatmap slot becomes an HTML
  `<table>` with filled cells; a waterfall slot stays an SVG, drawn as a stacked column with an invisible base.
- Text slots stay text boxes; tables stay native tables. Images placed in `image` slots stay pictures (they
  are images, not charts).

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
- Where `Refine` sits in the navigation; thumbnail size.

## Acceptance

Holdout and unit rows use the stand-in client: `RefineOps` returns the ops given in "When"; RFP rows also
stand in `DraftOut`. Fixture: RFP project P with Q1, Q2 status `drafted` (answers `A1`, `A2`), Q3 `approved`,
Q4 `no source`; library entry E1 whose answer contains `We screen all holdings quarterly.`. A grounded draft
is `DraftOut {answer: "We screen holdings quarterly.", citations: [{entry_id: E1, quote: "We screen all
holdings quarterly."}]}`. Report R has a deck whose slide 2 uses a layout with slots `body` and `chart`,
no slot `sidebar`, and whose findings, datasets and slide 2 text contain no `73`.

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
| AC-19 | R | ops `set_text(2, "body", "Net zero by 2040")` | `GET /api/reports/R/deck`: slide 2 `slots.body` = `Net zero by 2040` | holdout |
| AC-20 | after AC-19 | `GET /api/reports/R/deck/html` | body contains `Net zero by 2040` | holdout |
| AC-21 | R | ops `set_text(2, "sidebar", "x")`, `set_headline(2, "New")` | slide 2 headline `New` | holdout |
| AC-22 | as AC-21 | read the turn | `not_changed` = [{2, `no such slot`}] | holdout |
| AC-23 | R | ops `set_variant(2, "nonexistent")` | slide 2 unchanged; `not_changed` = [{2, `no such variant`}] | holdout |
| AC-24 | R, slide 2 chart type `line` | ops `set_chart_type(2, "column")` | slide 2 `chart.chart_type` = `column`; `dataset_id` and columns unchanged | holdout |
| AC-25 | R with 4 slides headlined S1–S4 | ops `move_slide(4, 1)`, `delete_slide(3)` | headlines in order: S4, S1, S2 | holdout |
| AC-26 | R | ops `set_text(2, "body", "Emissions fell 73%")` | slide 2 `slots.body` = `Emissions fell 73%` | holdout |
| AC-27 | as AC-26 | read the turn | `check_figures` = [2] | holdout |
| AC-28 | after AC-19 | read `refine_turns` | one row, `kind` `deck`, `before` = the whole prior `deck.json` | holdout |
| AC-29 | after AC-19 | undo on R | `GET .../deck` equals the deck before AC-19 | holdout |
| AC-30 | report with no `deck.json` (storyline unapproved, or deck build failed) | a deck turn, or `GET .../deck/html` | 409, detail `This report has no deck yet. Approve its storyline in Report Builder first.` | holdout |
| AC-31 | after AC-19 | read the manifest | `deck_edited_since_render` = true | holdout |
| AC-32 | after AC-19 | `POST /api/reports/R/render` | `calls.jsonl` gains no `kind: model` line; manifest `deck_edited_since_render` = false | holdout |
| AC-33 | after AC-32 | download `output.pptx`, open with python-pptx | slide 2 has a text frame containing `Net zero by 2040` | holdout |
| AC-34 | after AC-24 and a render | open `output.pptx` slide 2 | its chart slot is a native chart of type column; `deck/html` slide 2 chart slot holds an SVG | holdout |
| AC-35 | a deck with one waterfall slide and one heatmap slide, rendered | open `output.pptx` | no picture shape on either chart slot; the waterfall slot is a native stacked-column chart with 2 series; the heatmap slot is a native table | holdout |
| AC-36 | the app with stand-ins | open the navigation | it has `Refine`; `/refine?report=R` opens with R selected; the picker lists no report without a deck | evaluator |
| AC-37 | Refine on R; `RefineOps` returns `set_chart_type(3, "column")` | owner types `make slide 3 a column chart` | slide 3 in the right pane shows a column chart within 1 s of the reply appearing | evaluator |
| AC-38 | as AC-37 | — | slide 3's thumbnail carries the label `changed` | evaluator |
| AC-39 | Refine on a deck whose slide 2 `body` holds 400 words | — | that slot has a red outline | evaluator |
| AC-40 | as AC-39 | — | that slot shows the label `Text doesn't fit` | evaluator |
| AC-41 | Refine on P; ops `rewrite([Q1,Q2,Q3])` with grounded drafts, `DraftOut` `delay_seconds: 2` | owner sends an instruction | Q1 shows its new answer and `changed` before Q2 does; a line `1 of 3` then `2 of 3` shows while it runs | evaluator |
| AC-42 | as AC-41, done | — | under the reply: `Changed: Q1, Q2` and `Not changed: Q3 (approved)` | evaluator |
| AC-43 | Refine open on P; another user edits Q2 on RFP Answers | wait 3 s | the Refine view shows the new Q2 answer | evaluator |
| AC-44 | Refine on R after a chat edit | — | `Preview changed since last export` and `Export .pptx` show; after clicking Export they are gone | evaluator |
| AC-45 | golden cases file `backend/tests/golden/refine/cases.json`, ≥ 15 instructions with expected ops; a case passes when op names and targets (question ids, slide, slot, variant, chart type) equal the expected, instruction text ignored | `arp golden-set refine --min-accuracy 0.9` with the real model | exits 0 | golden |

| AC-50 | as AC-41 | — | each answer shows in the right pane within 2 s of the progress line's count going up | evaluator |
| AC-51 | a deck with one waterfall slide and one heatmap slide | `GET .../deck/html` | the heatmap slot holds a `<table>`; the waterfall slot holds an SVG | holdout |
| AC-52 | P; the `DraftOut` stand-in returns an error for Q1 and a grounded draft for Q2 | ops `rewrite([Q1,Q2])` | turn `done`; `changed` = [Q2]; `not_changed` = [{Q1, `draft failed`}] | holdout |
| AC-53 | a `refine_turns` row `running` on P from before an API restart | restart the API, then read the turn | `status` `failed`, `error` `interrupted`; a new turn on P returns 202 | unit |
| AC-54 | after AC-1 | a user with role `viewer` posts undo on P | 403, detail `Viewers cannot change documents.` | holdout |
| AC-55 | after AC-32 (deck rendered, flag false) | undo the AC-19 turn on R | manifest `deck_edited_since_render` = true | holdout |
| AC-56 | R with 4 slides headlined S1–S4 | ops `move_slide(1, 4)`, `delete_slide(2)` | headlines in order: S3, S4, S1 | holdout |
| AC-57 | R, slide 2 a `line` chart with one category and one value column, no `value_column` | ops `set_chart_type(2, "heatmap")` | slide 2 chart type stays `line`; `not_changed` = [{2, `chart type does not fit the data`}] | holdout |
| AC-58 | P; grounded draft | ops `rewrite([Q1], "shorter")` | the `DraftOut` prompt in `calls.jsonl` contains `shorter` and `A1` | unit |
| AC-59 | R, after `POST .../render` of its deck | `GET /api/reports` | R's manifest has `has_deck` = true; a report with no deck has `has_deck` = false | holdout |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-46 | Q1 edited by hand on RFP Answers by `bob` | bob approves Q1 with all flags confirmed | 403, detail `You edited this answer last; another approver must approve it.` | holdout |
| AC-47 | approved storyline | `PUT /api/reports/{id}/storyline` | 409, detail `Storyline already approved` | holdout |
| AC-48 | a deck with a `column` chart slide, rendered | open `output.pptx` | the chart slot is a native column chart, as before this change | holdout |
| AC-49 | — | run `backend/tests/test_ask_tools.py` and `backend/tests/test_ask_transition_plan.py` | all pass, files unchanged | unit |
