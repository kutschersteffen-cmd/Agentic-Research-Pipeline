# Agent board: a whiteboard on the Agent screen

Slug: agent-board

Risk: this spec PR is `risk:low`. The build is size M, delivered as 4 PRs (see `## Slices`); each slice names its own
risk label.

Status: draft, waiting for the owner's approval.

Source: thread "Add a whiteboard to ARP" (22 Nov 2026). The owner asked for "the same whiteboard functionality as
Claude" and picked option 1 of three: a **Board** tab on the Agent screen's stage with typed blocks (chart, flowchart,
table, note), over a mini-app-only board or a free drawing canvas. Checked against `origin/main` `ab3b197`. Builds on
the approved spec `2026-11-21-agent-panel-code-mode` (the Agent screen and its stage).

## Decisions for the owner

Approving this spec accepts all five as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | **Charts are drawn on the server**: Vega-Lite rendered to SVG by `vl-convert-python` with the house chart theme (`arp/reporting/vega.py`), shown in the browser as an image. | Yes (AC-6, AC-7, AC-8) | Vega in the browser (`vega-embed`): hover tooltips, about 1 MB more frontend, a second chart look. |
| D2 | **Flowcharts use the Mermaid subset the house deck already reads** (`arp/reporting/mermaid_flow.py`), so a board flowchart can go into a deck unchanged. | Yes (AC-9, AC-10) | Free nodes and edges as JSON; a second flowchart format to keep. |
| D3 | **The agent draws when asked**, from one input at the bottom of the Board tab. It never adds blocks on its own while a plan runs. | Yes (AC-14 to AC-20, AC-25) | It adds a block per finished step; more to read, and the board fills without anyone asking. |
| D4 | **Numbers are checked, not blocked.** A chart or table the agent draws keeps its numbers, and every number not found in the thread's data is listed on the block as `Not in ARP data: …`. | Yes (AC-17, AC-18) | Such a block is refused with 422; the agent then cannot show a share or a total it worked out. |
| D5 | **One column of blocks**, reordered by Move up and Move down (and drag), not a free 2D canvas. Works the same in the phone drawer. | Yes (AC-23, AC-26) | A free canvas with x/y positions; more to build and harder on a phone. |

## Why

The Agent screen (spec `agent-panel-code-mode`) shows what a plan did as a stream of cards and a stage of read-only
tabs: Script, Diff, Audit and, later, Mini-app. Nothing on it lets the owner or the agent **put a picture next to the
work and keep it**: a chart of what a step found, a flowchart of how the plan hangs together, a table to compare, a
note to remember why. Claude does this with artifacts. Today the owner has to leave ARP for that.

After this spec the owner can, on any plan (and, from slice 4, any exploration):

- ask the agent "chart the sector weights from step 2" or "draw the plan as a flowchart" and get a block on the board;
- ask it to change a block ("make it a bar chart, sorted"), or edit the block's source himself;
- add his own notes and tables, reorder, undo the last change, download, delete;
- come back later and find the board as he left it.

## What exists today

| Piece | Where | Used by this spec |
|---|---|---|
| Agent screen, stage tabs | spec `agent-panel-code-mode` Phase 3 (slices 6 to 8, not built yet) | The Board tab joins the stage |
| Plans and stored calls | `orchestration/plan_models.py` (`research_plans`, `research_plan_calls.result`) | The board's thread and its data |
| Explorations | spec `agent-panel-code-mode` Phase 4 (`agent_explorations`, slices 9 and 10) | Boards on explorations (slice 4) |
| Vega-Lite to SVG with the house theme | `reporting/vega.py` (`theme_config`, `to_svg`), `reporting/style/chart_theme.json` | Chart blocks |
| Mermaid subset parser | `reporting/mermaid_flow.py` (`parse_mermaid`, `MermaidError`), `schemas/visuals.py` (`Flow`) | Flowchart blocks |
| Flow drawing in the app | `frontend/src/components/flowCanvas.tsx` (React Flow) | Flowchart blocks on screen |
| Model calls and stand-ins | `LLMClient.complete_structured`, `arp/standins.py` (`model/<Name>.json`) | The draw route |

## Goals

- G1. Every plan, and every exploration, has one board: an ordered list of blocks, stored in Postgres and kept.
- G2. Four block kinds, each with a text source a person can edit: `note` (Markdown), `table` (columns and rows),
  `chart` (Vega-Lite), `flow` (Mermaid subset).
- G3. The agent adds or changes a block from a sentence, using only the thread's own data, and marks numbers it could not
  find there.
- G4. Every change makes a new version; the last change can be undone.
- G5. A block can be downloaded: chart as SVG, table as CSV, note as Markdown, flow as Mermaid text.
- G6. Nothing on the board can load from outside: no URLs in chart specs, no HTML in notes, charts shown as images.
- G7. The Board adds one tab to the stage and nothing else to the screen.

## Non-goals

- Free drawing, sticky notes at x/y positions, shapes, pens (option 3).
- Several people editing at once, comments, sharing a board outside ARP.
- The agent drawing without being asked (D3).
- Interactive charts (hover, zoom) (D1).
- Editing a flowchart by dragging nodes.
- Counting draw calls against a plan's budget.

## Anti-goals

- A block never changes a plan, a run or a stored result. The board only reads thread data.
- The board never fetches a URL, on the server or in the browser.
- A number the agent made up is never shown without the `Not in ARP data` line (D4).

## Design

### Data

Two tables (slice 1):

- `agent_board_blocks(id text pk, thread_kind text, thread_id text, position int, kind text, title text, source jsonb,
  version int, origin text, unverified jsonb, created_at timestamptz, updated_at timestamptz)`.
  `thread_kind` is `plan` or `exploration`; `origin` is `person` or `agent` (who made the current version);
  `unverified` is the list of numbers D4 found missing: always empty for `note` and `flow`; empty for a block a person
  creates with `POST /blocks` unless the body passes it; a person's `source` edit of a `chart` or `table` re-runs the check.
  Index on `(thread_kind, thread_id, position)`. No foreign key (two parent tables); a route checks the thread exists.
- `agent_board_versions(block_id text, version int, kind text, title text, source jsonb, origin text, unverified jsonb,
  created_at timestamptz, pk (block_id, version))`, one row per version, written in the same transaction as the block.
  Deleting a block deletes its versions.

The board code lives in `backend/arp/agent_board/` (store, checks, rendering, draw) and its router in
`backend/arp/api/routers/agent_board.py`.

`id` is a new UUID4 string. Positions of a board are always `0 … n-1` with no gaps.

### Block sources and validation

`source` per kind, checked on every create, edit and draw. The first failing check answers
`422 {"detail": "<message>"}` with the message below, and nothing is stored. A body that is not a JSON object, or whose
`kind` or `title` is missing or not a string, answers `422 {"detail": "invalid block"}` before any other check.

| Kind | `source` | Check | Message |
|---|---|---|---|
| any | — | `title` 1 to 120 characters after stripping | `title must be 1 to 120 characters` |
| any | — | `kind` one of the four | `unknown block kind: <kind>` |
| `note` | string, Markdown | at most 20 000 characters | `note exceeds 20000 characters` |
| `table` | `{"columns": [str], "rows": [[str \| number \| null]]}` | 1 to 20 columns; 0 to 200 rows; every row as long as `columns` | `table must have 1 to 20 columns`, `table exceeds 200 rows`, `row <i> has <m> cells, expected <n>` (`i` from 1) |
| `chart` | Vega-Lite object | no key `url`, `href` or `loader` at any depth, and no mark of type `image` (`"mark": "image"` or `"mark": {"type": "image"}`) at any depth | `chart may not load from outside: <path>` (`<path>` the JSON path of the first offending key or mark in document order, e.g. `data.url`, `layer[0].mark`) |
| `chart` | same | every `data.values` at any depth holds at most 5 000 rows | `chart exceeds 5000 data rows` |
| `chart` | same | `vl-convert` renders it | `chart does not render: <first line of the error>` |
| `flow` | string, Mermaid | `parse_mermaid` accepts it | the `MermaidError` message unchanged |

A board holds at most 50 blocks; a create or draw beyond that answers `409 {"detail": "board is full (50 blocks)"}`.

### Rendering

A block in a response is:

```
{id, kind, title, source, position, version, origin, unverified: [number], rendered, created_at, updated_at}
```

`rendered` is `null` for `note` and `table`; for `chart`, `{"light": "<svg…>", "dark": "<svg…>"}`: the source with
`config` replaced by `theme_config(load_tokens(), mode)` for `light` and `dark`, plus, from `palette(load_tokens(), mode)`:
`background` = `panel`; `axis` and `legend` `labelColor` and `titleColor` = `ink`; `axis` `domainColor` and `tickColor` =
`line`; `title.color` = `ink`; `mark.color` = `highlight`. Then through `vega.to_svg` (D1). The theme file is not changed. For `flow`,
the `Flow` from `parse_mermaid` as JSON. Charts are rendered on every write and stored nowhere; a read renders again.

On screen:
- `note`: Markdown with headings, bold, italics, lists, inline code and links whose target starts `https://` or
  `http://`. Raw HTML is shown as text. Other links show as text.
- `table`: a plain table; numbers right-aligned. When a person saves a table as CSV (Board tab `Edit`), the first row
  is `columns`; a cell that Python's `float()` parses to a finite value is a number (an `int` when it has no `.`, `e`
  or `E`), an empty cell is `null`, anything else a string.
- `chart`: `<img src="data:image/svg+xml;base64,…">` of the SVG for the current colour scheme (D1, G6).
- `flow`: `flowCanvas.tsx` with the `Flow`'s steps and arrows, read-only, laid out top to bottom or left to right as
  the source says.

### API

All routes under `/api/agent/boards/{thread_kind}/{thread_id}`. An unknown `thread_kind` answers
`404 {"detail": "unknown thread kind"}`; a thread that does not exist answers `404 {"detail": "thread not found"}`.

| Route | Body | Does | Answers |
|---|---|---|---|
| `GET` | — | the board | `200 {thread_kind, thread_id, blocks: [block]}` sorted by `position` |
| `POST /blocks` | `{kind, title, source, origin?, unverified?, position?}` | adds a block, `version: 1`. `origin` defaults to `person` and `unverified` to `[]`; `position`, when given, inserts the block there (clamped) instead of at the end. The three optional fields exist so the Board tab's delete-undo can restore a block as it was | `201` block |
| `PATCH /blocks/{id}` | `{title?, source?, position?}` | a change to `title` or `source` makes version + 1. A change to `title` only keeps `origin` and `unverified`. A change to `source` sets `origin: "person"` and, for `chart` and `table`, re-runs the number check (D4) against the thread data, so a person's edit keeps the line for numbers still missing. `position` moves the block to that index (clamped to `0 … n-1`) and shifts the others, without a new version | `200` block |
| `POST /blocks/{id}/undo` | — | with current version `v`, copies version `v − 1`'s `kind`, `title`, `source`, `origin` and `unverified` into a new version `v + 1` (so a second undo brings back the change the first one removed) | `200` block; at version 1 `409 {"detail": "nothing to undo"}` |
| `DELETE /blocks/{id}` | — | removes the block and its versions; positions close up | `204` |
| `POST /draw` | `{prompt, block_id?}` | the agent draws (below) | `200` block |

A block id that is not on this board answers `404 {"detail": "block not found"}`. `prompt` must be 1 to 2 000
characters after stripping, else `422 {"detail": "prompt must be 1 to 2000 characters"}`.

Until slice 4 ships, `thread_kind` `exploration` answers `404 {"detail": "unknown thread kind"}`.

### Drawing (D3, D4)

`POST /draw` makes one `LLMClient.complete_structured` call with output model
`BoardBlockDraft(kind: Literal["note", "table", "chart", "flow"], title: str, source: Any)`.

The prompt holds, in order, each part separated by a blank line:
1. `Request: <prompt>`;
2. with `block_id`, `Current block: ` followed by the block's `{kind, title, source}` as compact JSON;
3. `Thread data:` and, on the next line, the thread data as compact JSON (`json.dumps(…, ensure_ascii=False,
   separators=(",", ":"))`), cut like slice 12 of `agent-panel-code-mode`: over 20 000 bytes as UTF-8, the longest
   prefix of whole characters that fits, followed by `\n(thread data truncated at 20000 bytes)`.

Thread data for a plan: `{"brief", "status", "steps": [{"seq", "kind", "params", "status", "run_id", "result"}]}` from
`research_plans` and `research_plan_calls` sorted by `seq`. For an exploration: `{"question", "status", "result"}`.

The system prompt names the four kinds and their source formats, the Mermaid subset's limits, and says: use only
numbers from the thread data; never put a URL in a chart; reply in the language of the request.

The draft is checked like a person's block. If a check fails, the route makes one more call whose prompt adds, after
part 3, a blank line and `Your last answer was refused: <message>`. If the second draft also fails, the route answers
`422 {"detail": "the agent could not draw this: <message>"}` and stores nothing. If a model call raises, the route
answers `502 {"detail": "the agent could not draw this: model call failed"}` and stores nothing. The thread, block,
prompt and board-full checks run before any model call, so a request they refuse writes no `calls.jsonl` line.

Without `block_id`, a valid draft becomes a new block at the end, `origin: "agent"`. With `block_id`, it becomes the
block's next version (its `kind` may change), `origin: "agent"`; position unchanged.

**Number check (D4).** For `chart` and `table` sources, collect every number in the source (for a chart, every JSON
number inside every `data.values` and every `datasets` entry at any depth of the spec; for a table, every numeric cell)
and every JSON number value at any depth of the thread data. Only JSON numbers count: booleans and digits inside
strings (a brief's `top 10`, a run id) do not. A source number `n` is found when some thread number `c` has `round(n, 2) == round(c, 2)`. The block's
`unverified` is the sorted list of distinct numbers not found. On screen, a non-empty list shows one line under the
block: `Not in ARP data: ` and the numbers joined by `, `, the first 10, then ` and <k> more` when longer.

Each draw call is logged in `calls.jsonl` with stand-ins, like every model call; with `ARP_STANDINS_DIR` the draft comes
from `model/BoardBlockDraft.json`.

### Board tab (slice 3)

- The stage's tabs become `Board`, `Script`, `Diff`, `Audit` (and `Mini-app` once slice 11 of `agent-panel-code-mode`
  ships). `Board` is first and is the tab shown when a thread is opened. No other control is added to the header, the
  threads column or the stream (G7).
- The tab shows the blocks top to bottom. Each block: its title, its content, and a `⋯` menu with `Edit`, `Change
  with agent…`, `Move up`, `Move down`, `Undo last change`, `Download`, `Delete`. `Move up` is absent on the first block,
  `Move down` on the last, `Undo last change` at version 1. A block can also be dragged by its title to a new place.
- An agent-made block shows a small `Agent` label beside the title.
- `Edit` turns the content into a text field holding the source (`note` and `flow` as text, `table` as CSV with a
  header row, `chart` as formatted JSON), with `Save` and `Cancel`. `Save` sends `PATCH`; a 422 keeps the field open with
  the `detail` under it.
- `Change with agent…` opens a one-line field under the block; Enter sends `POST /draw` with `block_id`.
- `Download` saves `<title>.svg` (chart, the light SVG), `<title>.csv` (table), `<title>.md` (note) or `<title>.mmd`
  (flow), where `<title>` has every character outside `A-Za-z0-9-_` replaced by `_`.
- `Delete` removes the block at once, and a 5 s `Block deleted · Undo` bar recreates it if clicked: `POST /blocks` with
  the same kind, title, source, origin, unverified and position (a new id, version 1).
- At the bottom, one field with placeholder `Ask for a chart, flowchart, table or note…`. Enter sends `POST /draw`; while
  it runs, a placeholder block `Drawing…` sits at the end and the field is disabled; on 422 the field keeps the text and
  shows the `detail` under it.
- An empty board shows `Nothing on the board yet. Ask for a chart, flowchart, table or note.` above the field.
- Below 900 px the stage is a drawer (spec `agent-panel-code-mode`); the Board fills its width with no horizontal
  scroll; tables scroll inside their own box.

## Defaults decided here

- Block limits (50 per board, 200 rows, 20 columns, 5 000 chart rows, 20 000 note characters) are fixed, not settings.
- The draw call uses the configured model (`ARP_LLM_MODEL`), as explorations do.
- Versions are kept for as long as the block; there is no version browser, only undo.
- The board does not refresh by itself; it reloads when the thread is opened and after each change.
- A cancelled or failed plan keeps its board and can still be drawn on.

## Fixtures

- **Demo plan**: `arp plan seed-demo` (exists).
- **Done plan D**: a plan with status `done` and one stored call, `seq` 1, `kind` `index_construct`, `result`
  `{"weights": [{"sector": "Energy", "weight": 0.125}, {"sector": "Utilities", "weight": 0.31}]}`, written straight to the
  tables by the test.
- **Stand-ins**: `$ARP_STANDINS_DIR/model/BoardBlockDraft.json`, `{"output": {...}}` as today, or (new in slice 2) a
  JSON list of such objects. With a list, call `i` for that output model (counted from 0 per model name, since the file
  was last written) answers with entry `i`, and calls past the end answer with the last entry. `arp/standins.py` gets
  this rule in slice 2; a single object still answers every call. `calls.jsonl` lines have `name: "BoardBlockDraft"`.
- **Invalid Flow X**: `"flowchart RL\n  a --> b"`; `parse_mermaid` raises `line 1: direction RL is not supported; use LR
  or TB`.
- **Bar chart C**: `{"mark": "bar", "data": {"values": [{"s": "Energy", "w": 0.125}, {"s": "Utilities", "w": 0.31}]},
  "encoding": {"x": {"field": "s", "type": "nominal"}, "y": {"field": "w", "type": "quantitative"}}}`.
- **Flow F**: `"flowchart LR\n  a[Build universe] --> b[Extract]\n  b --> c[Report]"`.

## Acceptance

Superseded: none. In rows, `B` is `/api/agent/boards/plan/<id>` for the plan named in "Given", and `\n` inside a string
means one newline character.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Demo plan, empty board | `GET B` | HTTP 200, `{"thread_kind": "plan", "thread_id": "<id>", "blocks": []}` | holdout |
| AC-2 | No plan `nope` | `GET /api/agent/boards/plan/nope` | HTTP 404, `{"detail": "thread not found"}` | holdout |
| AC-2b | — | `GET /api/agent/boards/folder/x` | HTTP 404, `{"detail": "unknown thread kind"}` | holdout |
| AC-3 | Demo plan, empty board | `POST B/blocks` `{"kind": "note", "title": "Why", "source": "Because **x**"}` | HTTP 201; `position: 0`, `version: 1`, `origin: "person"`, `unverified: []`, `rendered: null`; a following `GET B` returns that one block | holdout |
| AC-4 | Same | `POST B/blocks` `{"kind": "table", "title": "T", "source": {"columns": ["a", "b"], "rows": [[1, 2], [3]]}}` | HTTP 422, `{"detail": "row 2 has 1 cells, expected 2"}`; the board is still empty | holdout |
| AC-4b | Same | `POST B/blocks` `{"kind": 3, "title": "x", "source": ""}` | HTTP 422, `{"detail": "invalid block"}` | holdout |
| AC-5 | Same | `POST B/blocks` with kind `note`, title of 121 `x` characters | HTTP 422, `{"detail": "title must be 1 to 120 characters"}` | holdout |
| AC-6 | Same | `POST B/blocks` kind `chart`, title `C`, source Bar chart C | HTTP 201; `rendered.light` and `rendered.dark` each start with `<svg`; `rendered.light` contains `#2a78d6` and `rendered.dark` contains `#3987e5` and `#e8ebf0` (the house palette's light `highlight`, dark `highlight` and dark `ink`) | holdout |
| AC-7 | Demo plan, empty board; a TCP listener on `127.0.0.1:<p>` | `POST B/blocks` kind `chart`, title `C`, source `{"mark": "bar", "data": {"url": "http://127.0.0.1:<p>/x.csv"}}` | HTTP 422, `{"detail": "chart may not load from outside: data.url"}`; the listener received no connection within 2 s | holdout |
| AC-8 | Same | `POST B/blocks` kind `chart`, title `C`, source `{"layer": [{"mark": {"type": "image"}, "encoding": {"url": {"value": "https://example.com/a.png"}}}]}` | HTTP 422, `{"detail": "chart may not load from outside: layer[0].mark"}` | holdout |
| AC-8b | Demo plan, empty board; a TCP listener on `127.0.0.1:<p>` | `POST B/blocks` kind `chart`, title `C`, source `{"mark": "image", "data": {"values": [{"u": "http://127.0.0.1:<p>/a.png"}]}, "encoding": {"url": {"field": "u"}}}` | HTTP 422, `{"detail": "chart may not load from outside: mark"}`; the listener received no connection within 2 s | holdout |
| AC-9 | Same | `POST B/blocks` kind `flow`, title `F`, source Flow F | HTTP 201; `rendered.steps` has 3 entries with labels `Build universe`, `Extract`, `Report`; `rendered.direction: "LR"` | holdout |
| AC-10 | Same | `POST B/blocks` kind `flow`, title `F`, source Invalid Flow X | HTTP 422, `{"detail": "line 1: direction RL is not supported; use LR or TB"}` | holdout |
| AC-11 | Board with 50 blocks | `POST B/blocks` a valid note | HTTP 409, `{"detail": "board is full (50 blocks)"}` | holdout |
| AC-12 | Board with notes N0, N1, N2 at positions 0, 1, 2 | `PATCH B/blocks/<N2>` `{"position": 0}` | HTTP 200; `GET B` lists N2, N0, N1 with positions 0, 1, 2; each `version` unchanged | holdout |
| AC-12b | Board with notes N0, N1 | `PATCH B/blocks/<N0>` `{"position": 99}` | `GET B` lists N1, N0 with positions 0, 1 | holdout |
| AC-13 | Note N with source `a` at version 1 | `PATCH` `{"source": "b"}`, then `POST B/blocks/<N>/undo` | the PATCH answers `version: 2`, `source: "b"`; the undo answers `version: 3`, `source: "a"` | holdout |
| AC-13b | Note N at version 1 | `POST B/blocks/<N>/undo` | HTTP 409, `{"detail": "nothing to undo"}` | holdout |
| AC-13c | Notes N0, N1, N2 | `DELETE B/blocks/<N1>` | HTTP 204; `GET B` lists N0, N2 with positions 0, 1; `agent_board_versions` has no row with `block_id` N1 | holdout |
| AC-13d | Demo plan board; a note on another plan's board with id X | `PATCH B/blocks/<X>` `{"title": "y"}` | HTTP 404, `{"detail": "block not found"}`; X unchanged | holdout |
| AC-13e | The note N after AC-13 (version 3, source `a`) | `POST B/blocks/<N>/undo` | `version: 4`, `source: "b"` | holdout |
| AC-14 | Done plan D, empty board; stand-in draft `{"kind": "chart", "title": "Weights", "source": <Bar chart C>}` | `POST B/draw` `{"prompt": "chart the weights"}` | HTTP 200; `origin: "agent"`, `kind: "chart"`, `position: 0`, `unverified: []`; `calls.jsonl` has 1 new line with `name: "BoardBlockDraft"` | holdout |
| AC-14b | Done plan D | record `GET /api/plans/<D>`; then on its board a create, a PATCH, an undo, a DELETE and a draw (stand-in note draft) | `GET /api/plans/<D>` returns a body byte-identical to the recorded one | holdout |
| AC-15 | Same | same | that `calls.jsonl` line's `prompt` starts with `Request: chart the weights\n\nThread data:\n{"brief":` and contains `"weight":0.125` | holdout |
| AC-16 | Done plan D; stand-in list: first a flow with source Invalid Flow X, then Flow F | `POST B/draw` `{"prompt": "draw the plan"}` | HTTP 200, `kind: "flow"`; `calls.jsonl` has 2 new `BoardBlockDraft` lines; the second line's `prompt` contains `Your last answer was refused: ` | holdout |
| AC-16b | Done plan D; a stand-in list of two drafts, both charts titled `W` with source `{"data": {"url": "x"}}` | `POST B/draw` `{"prompt": "x"}` | HTTP 422, `{"detail": "the agent could not draw this: chart may not load from outside: data.url"}`; the board is still empty | holdout |
| AC-16c | Done plan D; stand-in `{"error": "boom"}` | `POST B/draw` `{"prompt": "x"}` | HTTP 502, `{"detail": "the agent could not draw this: model call failed"}`; the board is still empty | holdout |
| AC-16d | Done plan D with 50 blocks on its board | `POST B/draw` `{"prompt": "x"}` | HTTP 409, `{"detail": "board is full (50 blocks)"}`; no new `calls.jsonl` line | holdout |
| AC-17 | Done plan D; stand-in draft is a table, columns `["sector", "weight"]`, rows `[["Energy", 0.125], ["Utilities", 0.31], ["Total", 0.435]]` | `POST B/draw` `{"prompt": "table"}` | `unverified: [0.435]` | holdout |
| AC-17b | The block from AC-17 | `PATCH B/blocks/<id>` `{"title": "Weights table"}` | `version: 2`, `origin: "agent"`, `unverified: [0.435]` | holdout |
| AC-17c | Done plan D; stand-in chart draft `{"layer": [{"mark": "bar", "data": {"values": [{"w": 0.31}, {"w": 0.77}]}, "encoding": {"y": {"field": "w", "type": "quantitative"}}}]}`, title `L` | `POST B/draw` `{"prompt": "x"}` | `unverified: [0.77]` | holdout |
| AC-17d | Done plan D; a person's table `T` with rows `[["x", 0.125]]` | `PATCH B/blocks/<T>` `{"source": {"columns": ["a", "b"], "rows": [["x", 9.99]]}}` | `origin: "person"`, `unverified: [9.99]` | holdout |
| AC-18 | The block from AC-17 | open the Board tab | under the table one line reads `Not in ARP data: 0.435` | evaluator |
| AC-18b | Done plan D; stand-in table with one row of 12 numbers 101 … 112 | `POST B/draw` then open the Board tab | the line reads `Not in ARP data: 101, 102, 103, 104, 105, 106, 107, 108, 109, 110 and 2 more` | evaluator |
| AC-19 | Done plan D; agent chart A at version 1 with source Bar chart C (made by `POST B/draw` with stand-in `{"kind": "chart", "title": "Weights", "source": <Bar chart C>}`); then stand-in draft a table `{"columns": ["s"], "rows": [["Energy"]]}` | `POST B/draw` `{"prompt": "as a table", "block_id": "<A>"}` | HTTP 200; same `id` and `position`; `kind: "table"`, `version: 2`; the `calls.jsonl` prompt contains `Current block: {"kind":"chart"` | holdout |
| AC-19b | The block from AC-19 | `POST B/blocks/<A>/undo` | HTTP 200; `kind: "chart"`, `version: 3`, `source` equals Bar chart C | holdout |
| AC-20 | Done plan D | `POST B/draw` `{"prompt": "   "}` | HTTP 422, `{"detail": "prompt must be 1 to 2000 characters"}`; no new `calls.jsonl` line | holdout |
| AC-20b | A plan whose calls' results together exceed 20 000 bytes of compact JSON; any valid stand-in draft | `POST B/draw` `{"prompt": "x"}` | the `calls.jsonl` prompt ends with `\n(thread data truncated at 20000 bytes)`, and the thread data part before it is at most 20 000 bytes as UTF-8 | unit |
| AC-21 | Demo plan | open `#/agent/<id>` | the stage tabs read `Board`, `Script`, `Diff`, `Audit` in that order, then `Mini-app` if that tab has shipped, and `Board` is selected; the board shows `Nothing on the board yet. Ask for a chart, flowchart, table or note.` | evaluator |
| AC-22 | Done plan D with chart C and flow F on its board | open its Board tab | the chart shows as an `img` whose `src` starts `data:image/svg+xml`; the flowchart shows 3 boxes `Build universe`, `Extract`, `Report` joined by 2 arrows | evaluator |
| AC-23 | Board with notes `One`, `Two` | `⋯` on `Two`, `Move up` | the board shows `Two` above `One`, also after a reload | evaluator |
| AC-24 | A note whose source is `<img src=x onerror="document.title='hit'">` and `[a](javascript:alert(1))` | open the Board tab | the `<img …>` text is shown as text; `document.title` is not `hit`; `a` is not a link | evaluator |
| AC-25 | Done plan D; stand-in chart draft | type `chart the weights` in the board's field, press Enter | a `Drawing…` block shows, then the chart with an `Agent` label at the end of the board | evaluator |
| AC-25b | Note `Why` with source `a` at version 1 | `⋯`, `Edit`, change the text to `b`, `Save`, then `⋯`, `Undo last change` | after `Save` the note shows `b`; after the undo it shows `a`; a new note's `⋯` menu has no `Undo last change` | evaluator |
| AC-25c | A table block `T` | `⋯`, `Download` | a file `T.csv` downloads whose first line is the columns joined by `,` | evaluator |
| AC-25d | A note `N` | `⋯`, `Delete`, then click `Undo` in the bar within 5 s | the note is back at its old place | evaluator |
| AC-25e | The table from AC-17 | `⋯`, `Delete`, then `Undo` in the bar within 5 s | the table is back at its old place with the `Agent` label and the line `Not in ARP data: 0.435` | evaluator |
| AC-25f | A chart titled `Sector weights 2026` | `⋯`, `Download` | a file `Sector_weights_2026.svg` downloads whose text starts `<svg` | evaluator |
| AC-25g | Note `N` with source `Because **x**`; flow `F` with source Flow F | `Download` on each | `N.md` holds exactly `Because **x**`; `F.mmd` holds exactly Flow F | evaluator |
| AC-25h | Done plan D; a table `T` | `⋯`, `Edit`, replace the text with `a,b\n1,\nx,2.5`, `Save` | `GET B` shows `T`'s source `{"columns": ["a", "b"], "rows": [[1, null], ["x", 2.5]]}` | evaluator |
| AC-26 | Viewport 390 px wide; Done plan D with a 20-column table on its board | open the stage drawer | the Board tab fills the drawer; no horizontal page scroll; the table scrolls sideways inside its own box | evaluator |
| AC-27 | An exploration E with `status: "done"` and result `{"n": 3}`; stand-in note draft | `POST /api/agent/boards/exploration/<E>/draw` `{"prompt": "summarise"}` | HTTP 200, `origin: "agent"`; the `calls.jsonl` prompt contains `"question":` and `"result":{"n":3}` | holdout |
| AC-28 | Exploration E selected on the Agent screen | look at the stage | the tabs start with `Board` | evaluator |
| AC-29 | Must not change: the `evaluator` rows of `agent-panel-code-mode` AC-27 to AC-38 that are merged when slice 3 opens (its PR lists them) | their checks | pass, with `Board` first among the tabs | evaluator |
| AC-30 | Must not change: the backend suite | `python3 -m pytest` | passes, with no edited test | unit |
| AC-31 | Must not change: the frontend suite | `npm test` | passes, with no edited test except those slice 3 lists in its PR | unit |
| AC-32 | Golden file of 10 board requests over Done plan D's thread data, each with the expected `kind` | `cd backend && arp agent board-golden --cases tests/golden/board.jsonl --min-pass 8` (one `{id, prompt, expected_kind}` per line; a case passes if the draft passes every check on the first call, has the expected kind and `unverified: []`; the slice 2 builder writes the 10 cases) | exit 0 | golden |

## Slices

| Slice | PR contents | Risk | Needs | Rows |
|---|---|---|---|---|
| 1 | Tables, block checks, chart and flow rendering, `GET`, `POST /blocks`, `PATCH`, `undo`, `DELETE` for plans | `risk:high` (schema) | — | AC-1 to AC-13e, AC-30 |
| 2 | `POST /draw`: prompt, retry, number check (also on a person's `PATCH`), stand-in lists, golden set; adds `backend/arp/agent_board/**` and `tests/golden/board.jsonl` to the path filter and run step of `.github/workflows/golden-set.yml` | `risk:high` (workflow file) | slice 1 | AC-14 to AC-17d, AC-19, AC-19b, AC-20, AC-20b, AC-30, AC-32 |
| 3 | Board tab on the Agent screen | `risk:normal` | slice 2, and slice 6 of `agent-panel-code-mode` | AC-18, AC-18b, AC-21 to AC-26 (with AC-25b to AC-25h), AC-29, AC-31 |
| 4 | Boards on explorations | `risk:normal` | slice 3, and slice 10 of `agent-panel-code-mode` | AC-27, AC-28, AC-30, AC-31 |

Slices 1 and 2 can start now; slice 3 waits for the Agent screen shell.

## Later

- **Next step up: board to deck.** A `Send to deck` action that turns the board into house-deck slides. Charts are
  already Vega-Lite and flowcharts already the deck's Mermaid subset, so it needs a block-to-slide mapping and an
  export route, not new drawing.
- Mini-app blocks: when slice 11 of `agent-panel-code-mode` ships, a mini-app becomes a fifth block kind instead of its
  own tab.
- The agent adding a block per finished step (D3's alternative), if the owner wants it after using the board.
- Draw calls counted against the plan budget.
