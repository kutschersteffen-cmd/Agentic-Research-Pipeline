# Refine chat: edit an RFP response or a deck by chatting, with a live view

Date: 2026-11-14
Status: draft, waiting for owner approval
Owner decisions on 2026-11-14: one chat page (not the Plans page, not a drawer in the existing pages);
split view with an instant in-browser slide preview; chat edits to RFP answers count as AI drafts, so the
person who asked may approve them (option "chat counts as drafter").

## Intent

Refining an RFP response or a presentation today means clicking through forms one answer or one section at
a time, waiting for a render to see a slide, and having no way to tell the AI "more formal", "shorter",
"use a bar chart". The owner named all three as the problem.

This adds one page, **Refine**, with a chat on the left and the document on the right. The owner picks one
document (an RFP project or a house-style deck), types an instruction, and the change appears in the right
pane as soon as the agent's reply arrives. Bulk instructions ("shorten every ESG answer") work in one turn.

The rule that holds elsewhere holds here: **the model proposes edits as typed operations; code applies them,
checks grounding and stores them.** The model never writes to the database directly.

## Goals

1. One page, `Refine`, reachable from the main navigation, that edits either an RFP project's answers or a
   house deck's slides through chat.
2. Bulk edits: one instruction may change many answers or slides in one turn.
3. Style instructions ("more formal", "shorter", "lead with the number", "make slide 3 a bar chart").
4. Instant view: the right pane shows the change within 1 s of the agent's reply. Slides are drawn in the
   browser from the same HTML renderer the export uses (`render_deck_html`,
   `backend/arp/reporting/html_render.py:85`), so the preview and the exported pptx use the same slot
   geometry (`house_style.slot_rect`).
5. Undo of the last turn, any number of times back to the first turn of the session.
6. Every turn is logged: who asked, what they typed, which operations ran, the state before.

## Non-goals

- The Plans page and the existing Ask ARP panel stay as they are.
- Approving RFP answers, exporting the RFP file, managing the library: they stay on the RFP Answers page.
- Decks built by the legacy `ReportPlan` path (pptx/docx/pdf from sections). Only house decks (`deck.json`).
- Editing the storyline. Deck chat starts once a deck exists (storyline approved in Report Builder).
- Typing directly into the preview (click-to-edit). Chat only.
- Streaming the agent's reply word by word, WebSockets or server push. The reply arrives whole; other
  people's changes appear by polling.
- Saving the conversation on the server for later. History lives in the browser tab, like Ask ARP.

## Anti-goals (a failure even if it works)

- The chat puts a figure or claim into an RFP answer that no library entry backs.
- The preview shows something different from what the exported pptx contains.
- A chat edit silently overwrites an approved RFP answer.
- An edit cannot be undone.

## Approaches considered

| Approach | Trade-off | Picked |
|----------|-----------|--------|
| A. New split-view page, slide images re-rendered by Chromium after each change | Preview equals export exactly; each change waits seconds for the render | no |
| B. Chat drawer inside RFP Answers and Report Builder | Cheapest, reuses pages as the view; not one page, Report Builder already crowded | no |
| C. New split-view page, slides drawn in the browser from the export's HTML renderer | Instant; preview matches export because both use `render_deck_html` / `slot_rect` | **yes (owner)** |

Agent shape: a single structured LLM call per turn (`LLMClient.complete_structured`, as in
`backend/arp/ask.py:54`) that returns a list of operations. No multi-step tool-calling loop: the client has no
tool-use API today (`backend/arp/llm/base.py:34`) and one call per turn keeps a turn predictable.

## Design

### Page

```
┌ Refine ─ [ RFP: Pension Fund X ▾ ]  [Undo last turn] ─────────────────────┐
│ Chat                        │ Live view                                    │
│ you: make all ESG answers   │ Q12 ESG policy   drafted  ● changed          │
│      shorter                │ Q13 Exclusions   drafted  ● changed          │
│ agent: Shortened Q12, Q13.  │ Q14 Voting       approved                    │
│   Not changed: Q14          │                                              │
│   (approved).               │ (deck: slide thumbnails + one large slide)   │
│ [ type an instruction… ]    │                                              │
└─────────────────────────────┴──────────────────────────────────────────────┘
```

- The picker lists RFP projects and reports that have a deck. The URL carries the choice
  (`/refine?rfp=<id>` or `/refine?report=<id>`) so a link opens the same document.
- After each turn the agent's reply lists what changed, what was not changed and why, and which items need
  a figure checked.
- Changed answers or slides are marked "changed" until the next turn.
- RFP view: question, answer, status badge, flags, sources (same badges as RFP Answers). Read-only.
- Deck view: a column of thumbnails and the selected slide large, both from `deck/html` in sandboxed
  iframes. A slot whose text overflows its box gets a red outline and the label `Text doesn't fit`
  (checked in the browser: the slot element's `scrollHeight > clientHeight`).
- The page polls the document every 3 s while open (like `RfpAnswers.tsx:173`) so edits made elsewhere show.

### Turn endpoint

`POST /api/refine/{kind}/{doc_id}/turns` with `{message, history}`; `kind` is `rfp` or `deck`; `history` is
the last 5 turns `{message, reply}` (older ones dropped by the server). Response: `{reply, changed,
not_changed: [{id, reason}], check_figures: [id], turn_id}` plus the updated document.

- One turn at a time per document: a second turn while one runs returns 409
  `A change is already running on this document.`
- Any signed-in user may run a turn (analyst or approver).

### RFP operations

| Op | Effect |
|----|--------|
| `rewrite(question_ids, instruction)` | Re-drafts each answer with the instruction, through the existing grounded drafting (`draft_answer`, `backend/arp/rfp/draft.py:85`, extended with an optional style instruction and the current answer as a starting point) |
| `leave_blank(question_ids)` | Same as the existing leave-blank action |

Rules:

- Approved answers are never changed. They appear in `not_changed` with reason `approved`.
- If a re-draft fails grounding (no cited entry or a number not found in the question or a cited entry),
  the previous answer, status, sources and flags stay. The question appears in `not_changed` with reason
  `not backed by the library`. The answer is never replaced by "no source" through chat.
- A successful re-draft sets status `drafted`, the new `sources` and `flags`, and `last_editor` to empty.
  So the person who asked may approve it (owner decision; this is how an untouched AI draft is treated
  today, `docs/superpowers/specs/2026-10-21-rfp-answers-design.md:161`). Who asked is in the turn log.

### Deck operations

| Op | Effect |
|----|--------|
| `set_text(slide, slot, text)` | Replaces one slot's text or bullet list |
| `set_headline(slide, text)` | Replaces the headline |
| `set_variant(slide, variant)` | Switches to another variant of the same layout in `style/layouts.json` |
| `set_chart_type(slide, chart_type)` | Changes `ChartSpec.chart_type`; dataset and columns stay |
| `move_slide(slide, to)` / `delete_slide(slide)` | Reorders or removes a slide |

Rules:

- The turn endpoint is the only new deck write path: it writes `deck.json` through `ReportingStore`. A slot or
  variant that does not exist for the slide's layout is rejected per op (`not_changed`, reason
  `no such slot` / `no such variant`), the other ops still apply.
- Numbers in text the chat writes must appear in the report's findings, its datasets or the slide's previous
  text; otherwise the slide id is listed in `check_figures`. The edit still applies (decks are internal drafts
  until exported).
- `GET /api/reports/{id}/deck/html` returns `render_deck_html(deck, datasets, mode=theme)`.
- After a chat edit the report shows `Preview changed since last export`. `POST /api/reports/{id}/export`
  re-runs `render_house_outputs` (`backend/arp/reporting/house_pipeline.py:23`) from the edited deck: no LLM
  calls, no `fit_deck`.
- A report with no `deck.json` returns 409 `This report has no deck yet. Approve its storyline in Report
  Builder first.`

### Turn log and undo

- New table `refine_turns`: `id, kind, doc_id, user, message, ops (JSONB), before (JSONB), created_at`.
  `before` holds the prior state of every question or the whole deck the turn touched.
- `POST /api/refine/{kind}/{doc_id}/undo` restores the newest turn's `before` and marks that turn undone.
  Repeating it walks back further. Undo of a turn whose items were changed since by someone else returns 409
  `Q12 changed after this turn; undo would overwrite it.` and changes nothing.

## Constraints

- The LLM client is built with `build_llm_client` (`backend/arp/llm/factory.py:23`); unit tests use a
  stand-in model.
- API contract: new response models go through `scripts/export_openapi.py` and `npm run gen:api`.
- No new frontend dependency; the preview is the backend's HTML in an iframe.

## Left to the builder

- Prompt wording, the op schema's exact field names, migration file name.
- Where the Refine entry sits in the navigation.
- Thumbnail size.

## Acceptance

Stand-in model in every `holdout` and `unit` row; it returns the ops given in "When".

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | RFP project with Q1, Q2 status `drafted`, library entries that back the new wording | turn whose model output is `rewrite([Q1,Q2], "shorter")` and grounded drafts | 200; `changed` = [Q1, Q2]; both status `drafted`, `sources` non-empty, `last_editor` null | holdout |
| AC-2 | Q1 `drafted` with answer `A` | `rewrite([Q1])` where the draft cites no entry | Q1 answer still `A`, status, sources, flags unchanged; `not_changed` = [{Q1, `not backed by the library`}] | holdout |
| AC-3 | Q3 status `approved` | `rewrite([Q3])` | Q3 unchanged; `not_changed` = [{Q3, `approved`}] | holdout |
| AC-4 | Q1 `edited`, `last_editor` = `bob` (approver) | bob runs a turn with a grounded `rewrite([Q1])`, then `POST .../questions/Q1/approve` as bob with all flags confirmed | approve returns 200 | holdout |
| AC-5 | any successful RFP turn by `alice` | — | one `refine_turns` row: user `alice`, the typed message, the ops, `before` holding Q1 and Q2 as they were | holdout |
| AC-6 | after the AC-1 turn | `POST /api/refine/rfp/{id}/undo` | Q1, Q2 answer, status, sources, flags, `last_editor` equal their values before the turn | holdout |
| AC-7 | report with a deck, slide 2 has slot `body` | `set_text(2, "body", "Net zero by 2040")` | `deck.json` slide 2 `slots.body` = `Net zero by 2040`; `GET .../deck/html` contains `Net zero by 2040` | holdout |
| AC-8 | after the AC-7 turn | `POST /api/refine/deck/{id}/undo` | `deck.json` equals its content before AC-7 | holdout |
| AC-9 | report whose storyline is not approved (no `deck.json`) | any deck turn | 409, detail `This report has no deck yet. Approve its storyline in Report Builder first.` | holdout |
| AC-10 | a turn on document D is running | a second turn on D | 409, detail `A change is already running on this document.` | holdout |
| AC-11 | after the AC-7 turn | `POST /api/reports/{id}/export` | `output.pptx` contains `Net zero by 2040`; stand-in model received 0 calls | holdout |
| AC-12 | deck findings and datasets contain no `73` | `set_text(2, "body", "Emissions fell 73%")` | edit applied; `check_figures` = [2] | holdout |
| AC-13 | slide 2 layout has no slot `sidebar` | ops `set_text(2,"sidebar","x")` and `set_headline(2,"New")` in one turn | headline is `New`; `not_changed` = [{2, `no such slot`}] | holdout |
| AC-14 | 7 earlier turns in `history` | a turn | the prompt sent to the model contains the last 5 turns' messages and not the 2 oldest | unit |
| AC-15 | Q12 changed by another user after turn T | undo of T | 409, detail `Q12 changed after this turn; undo would overwrite it.`; nothing changed | holdout |
| AC-16 | Refine page open on a deck | owner types `make slide 3 a bar chart` | within 1 s of the reply appearing, slide 3 in the right pane shows a bar chart and is marked `changed` | evaluator |
| AC-17 | Refine page on a deck where a slot's text overflows | — | that slot has a red outline and the label `Text doesn't fit` | evaluator |
| AC-18 | Refine page on an RFP project | owner types `make all ESG answers shorter` | the reply lists changed and not-changed questions with reasons; changed rows marked `changed` in the right pane | evaluator |
| AC-19 | golden set of ≥ 15 instructions with expected ops (new cases file) | `arp golden-set refine --min-accuracy 0.9` with the real model | exits 0 | golden |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-20 | Q1 edited by hand on RFP Answers by `bob` | bob approves Q1 with all flags confirmed | 403, detail `You edited this answer last; another approver must approve it.` | holdout |
| AC-21 | approved storyline | `PUT /api/reports/{id}/storyline` | 409 as today | holdout |
