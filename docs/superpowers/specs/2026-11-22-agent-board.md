# Agent board: a whiteboard on the Agent screen

Slug: agent-board

Risk: this spec PR is `risk:low`. The build is size M, delivered as 4 PRs (see `## Slices`); each slice names its own
risk label.

Status: **approved by the owner on 22 Nov 2026** (button in the spec session, after three spec-critic rounds; decisions D1–D5 as recommended).
Amendment 1 (22 Nov 2026, Phase 2 below: diagrams in Mermaid, number tiles, checklists, live blocks; D6–D9, AC-33 to AC-64,
slice 2b): **approved by the owner on 22 Nov 2026** (button in the spec session, head 8272df6).
Amendment 1b (22 Nov 2026, from the slice 2b security review on PR #648: diagram link statements after `;`, `//` URLs,
`link` statements, anchors stripped in the browser; a live chart that does not render is refused on write and not
re-rendered on read; long table cells cut; AC-36e to AC-36j, AC-49b, AC-58b to AC-58d): **approved by the owner on 22 Nov 2026** (button in the spec session, head 3eda0d8).
Amendment 1c (22 Nov 2026, from the round 2 security review on PR #648: `properties` and `details` statements in sequence diagrams and any
backslash refused in diagrams; `flow` sources get the diagram checks, keeping the house-deck subset; AC-36k to AC-36q): **approved by the owner on 22 Nov 2026**
(button in the spec session, head ab5d266).
Amendment 1d (22 Nov 2026, from the round 3 security review on PR #648, the third round of check bypasses, so it closes
the class: the checks read lines and words the way Mermaid does and refuse hidden characters and entity codes; in the
browser every diagram is drawn and shown inside a sandboxed frame whose Content-Security-Policy blocks every outside load,
with links stripped as before, so a diagram that slips past the checks still cannot reach outside; AC-36r to AC-36z, AC-49c, AC-49d, AC-55b): **approved by the owner on 22 Nov 2026**
(button in the spec session, head 6e1dbf0).
Amendment 1e (22 Nov 2026, from the reviews of PR #660; the owner chose "fix once, frame is the wall"): a statement
also starts after `}`, Mermaid's own entity placeholders are refused, and the slice 3 frame is named the security
boundary for diagrams; AC-65 to AC-67, AC-66b, AC-67b: **awaiting the owner's approval**. The owner asked for it after seeing prototypes: "use Mermaid", diagrams must
"work for anything the user tells the AI", and "let's do all" for tiles, checklists and live blocks.

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
| D6 | **A `diagram` block is any of five Mermaid types** (flowchart, mindmap, timeline, sequenceDiagram, quadrantChart), drawn in the browser by Mermaid 11 with ELK layout and the house colours. The agent draws diagrams instead of `flow` blocks; `flow` blocks stay valid and are drawn by the same renderer. | Yes (AC-33 to AC-36d, AC-47 to AC-49) | Keep only the flowchart subset; ideas, timelines and comparisons cannot be drawn. |
| D7 | **The agent names its own colour groups.** A flowchart ends each node with `:::GroupName` (1 to 4 groups, any names that help the reader: who acts, phase, theme) and may mark one key step `class <id> emphasis`. ARP assigns the colours and shows a legend; a diagram sets no colours itself. | Yes (AC-36c, AC-47) | Fixed ARP roles (platform, model, person); does not fit topics outside ARP. |
| D8 | **Two more block kinds: `tiles` (1 to 4 number tiles) and `checklist`** (items a person ticks; each tick is a version, so undo works). Tile values are JSON numbers, so the D4 check covers them. | Yes (AC-37 to AC-40, AC-50, AC-51) | Numbers and to-dos stay in notes. |
| D9 | **Live blocks.** A `chart`, `table` or tile can point at the thread's data with a JSON Pointer instead of copying numbers; every read fills it from the current data, and the Board reloads when a step changes. The agent uses a pointer whenever the numbers come straight from one list or number in the thread data. | Yes (AC-41 to AC-46, AC-52, AC-53, AC-57 to AC-61) | Every block is a snapshot; a re-run plan leaves old numbers on the board. |

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
| `flow` | same | then these Phase 2 `diagram` checks, in this order (Amendment 1c: slice 3 draws flows with Mermaid too): the hidden character check (Amendment 1d); the `%%{` check; the refused statement words except `classDef`; the HTML check, run on the source with every match of `<br\s*/?>`, compared without case (the pattern `parse_mermaid` uses for tags), removed; the `@{` check; the outside check; the entity code check (Amendment 1d). The `class`-for-emphasis check and the colour-group count do not apply to `flow`, so the house-deck subset (`<br>` tags, `classDef`, `class` actors, `stored`) stays valid | that check's message unchanged |

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
the `Flow` from `parse_mermaid` as JSON. Charts are rendered on every write and stored nowhere; a read renders again, except for the failure memory of Phase 2
live charts (Amendment 1b).

On screen:
- `note`: Markdown with headings, bold, italics, lists, inline code and links whose target starts `https://` or
  `http://`. Raw HTML is shown as text. Other links show as text.
- `table`: a plain table; numbers right-aligned. When a person saves a table as CSV (Board tab `Edit`), the first row
  is `columns`; a cell that Python's `float()` parses to a finite value is a number (an `int` when it has no `.`, `e`
  or `E`), an empty cell is `null`, anything else a string.
- `chart`: `<img src="data:image/svg+xml;base64,…">` of the SVG for the current colour scheme (D1, G6).
- `flow`: a new read-only `BoardFlow` component on React Flow, using `flowCanvas.tsx`'s `FlowHandle`, `LinkedHandles`
  and `DotGrid`. Each step's rank is its longest path from a step with no incoming arrow; ranks run along the source's
  direction (`LR` left to right, `TB` top to bottom), and steps of the same rank sit side by side in source order.

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

### Phase 2 (Amendment 1): diagrams, tiles, checklists, live blocks

Phase 2 adds three kinds to the four, so `KINDS` is `note`, `table`, `chart`, `flow`, `diagram`, `tiles`, `checklist`,
and lets `chart`, `table` and tiles read the thread's data live. Everything in Phase 1 stays as written unless this
section says otherwise. No table changes: the new sources and pointers live in `source` (jsonb).

**`diagram` (D6, D7).** `source` is a string of Mermaid text. Checks, in this order, the first failing one answering
422 with its message:

| Check | Message |
|---|---|
| a string of at most 8 000 characters | `diagram exceeds 8000 characters` |
| no hidden character: no character of Unicode category `Cc` other than tab, line feed and carriage return, and no U+2028, U+2029 or U+FEFF (Amendment 1d) | `diagram may not contain hidden characters` |
| the first word of the first line that is not empty and does not start with `%%` equals `flowchart`, `mindmap`, `timeline`, `sequenceDiagram` or `quadrantChart` (that word `<w>`) | `unsupported diagram type: <w>; use flowchart, mindmap, timeline, sequenceDiagram or quadrantChart` |
| no `%%{` anywhere | `diagram may not set its own config` |
| no statement whose first word, compared without case, is `click`, `style`, `classDef`, `linkStyle`, `link`, `links` or `href`, and for a `sequenceDiagram` also `properties` or `details` (`<w>` the first such word as written); a statement is a line, or a part of a line split at `;` (Amendment 1b; `properties` and `details`, whose JSON can name images, Amendment 1c) | `diagram may not use <w> lines` |
| every statement (as defined in the row above) whose first word is `class` ends with the word `emphasis` | `diagram may only use class lines for emphasis` |
| no `<` followed by a letter, `/` or `!` | `diagram may not contain HTML` |
| no `@{` anywhere (Mermaid shape options, which can load images) (Amendment 1b) | `diagram may not use shape options` |
| no `javascript:`, `http:`, `https:`, `//` or `\` (any backslash, which closes escapes such as `\/`), compared without case (Amendment 1b widens this from `javascript:`, `http://` and `https://`; Amendment 1c widens `\\` and `:\` to any backslash) | `diagram may not load from outside` |
| at most 4 distinct group names, a group name being each match of `:::([A-Za-z][A-Za-z0-9_]*)` other than `emphasis` (`<n>` their count) | `diagram has <n> colour groups; at most 4` |
| no match of `#[A-Za-z0-9_]+;` (Mermaid entity codes such as `#47;`, which Mermaid turns back into `/` when it draws; so a `classDef` colour such as `fill:#fff;` must be written without the trailing `;`) (Amendment 1d), and neither `ﬂ°` (U+FB02 U+00B0) nor `¶ß` (U+00B6 U+00DF) anywhere, each on its own, the placeholders Mermaid writes for entity codes and decodes the same way (Amendment 1e) | `diagram may not use entity codes` |

A `source` that is not a string answers `422 {"detail": "invalid block"}` before these checks; a source with no line
that is non-empty and not a `%%` line answers `unsupported diagram type: ; use flowchart, mindmap, timeline,
sequenceDiagram or quadrantChart` (empty `<w>`).

Security boundary (Amendment 1e). The frame that draws diagrams in the browser (slice 3, AC-49c, AC-49d, AC-55b) is
the security boundary for `diagram` and `flow` blocks; the server checks are a first filter that keeps most unsafe
sources out of storage and gives the agent a clear refusal. A review finding that a source passes the server checks
but is contained by the frame (its loads blocked by the frame's policy, its links stripped) is `optional`, not
blocking. Before slice 3 ships no screen draws these blocks, so this already applies to slice 2b reviews; slice 3
itself must pass AC-49c, AC-49d and AC-55b. A source that makes Mermaid run a script, or touch the parent page, is
never contained and stays blocking. This covers only drawing in the Board tab's frame; any other place that draws or
exports a `diagram` or `flow` source is reviewed on its own.

Lines and words (Amendment 1d). Every check reads the source the way Mermaid does: a line is a part of the source split
at `\r\n`, `\r` or `\n` (Mermaid turns each into a line feed before it reads); a word is a part of a line or statement
split at spaces, tabs and every Unicode space separator (category `Zs`, which JavaScript's `\s` matches); and the
first word of a statement is its first word that is not `end`, compared without case (Mermaid lets a statement follow
a block's `end` on the same line). A new statement also starts after every `}` (Amendment 1e:
Mermaid runs a statement that follows an `accDescr { … }` block on the same line). This split is on purpose
everywhere, so text such as `A->>B: send {x} details` is refused too; the agent rewrites it. These rules bring the checks close to Mermaid's reading; where they still differ, the frame
above is the boundary.

`rendered` is `null`: the browser draws it. Download saves `<title>.mmd` with the source.

**Shape checks for `tiles` and `checklist`.** Before their listed checks: a `source` that is not an object, `tiles` or
`items` missing or not a list, a tile or item that is not an object, a `label` or `text` that is missing or not a string,
or any key not named below, answers `422 {"detail": "invalid block"}`. `label` and `text` lengths count after
stripping.

**`tiles` (D8).** `source` is `{"tiles": [tile]}`, 1 to 4 tiles. A tile is `{"label": str, "value": number | {"live":
pointer}, "format"?: "number" | "percent", "change"?: number, "note"?: str}`. Checks: `tiles must have 1 to 4 tiles`;
`tile <i>: label must be 1 to 40 characters`; `tile <i>: value must be a number` (a JSON number, not a boolean or a
string, or a `{"live": …}` object); `tile <i>: change must be a number`; `tile <i>: note exceeds 80 characters`;
`tile <i>: format must be number or percent` (`i` from 1). The D4 check collects every `value` and `change` that is a
JSON number; it runs on a draw and on a person's `source` PATCH, as for `chart` and `table`. `unverified` is always
`[]` for `diagram` and `checklist`, as for `note` and `flow`, also when `POST /blocks` passes one. `rendered` is `{"values": [number | null]}`, one entry per tile: the number, or the live value.

On screen a tile shows `label`, then the value large: `format: "number"` (the default) with at most 2 decimals and `,`
between thousands (`1,234.5`); `"percent"` as value × 100 with one decimal and `%` (`0.31` → `31.0%`). `change` shows
under it with `+` when above 0, `-` (U+002D) when below 0 and no sign at 0: a number the same way as the value; for `"percent"` as change × 100 with one decimal and ` pts`
(`0.04` → `+4.0 pts`). `note` shows small under that. A `null` value shows `—`. Download saves `<title>.csv` with header
`label,value,change,note` and one row per tile: the raw numbers as JSON writes them (`0.31`, not `31.0%`; a live tile's
resolved value, empty when `null`), empty cells for a missing `change` or `note`.

**`checklist` (D8).** `source` is `{"items": [{"text": str, "done": bool}]}`. Checks: `checklist must have 1 to 50
items`; `item <i>: text must be 1 to 200 characters`; `item <i>: done must be true or false`. `rendered` is `null`.
On screen each item is a checkbox with its text; ticking or unticking sends `PATCH` with the whole new `source`, which is a
new version with `origin: "person"`, so `Undo last change` unticks. Download saves `<title>.md`, one line per item:
`- [x] text` or `- [ ] text`.

**Live pointers (D9).** Live checks run in this order: shape (`invalid block` for a chart with `live` and `data`, a table with both or neither
of `rows` and `live`), then the pointer's form, then the chart's outside check or the table's columns check.
A pointer is a JSON Pointer (RFC 6901) into the thread data (the same JSON the draw prompt gets,
before truncation), a string of 1 to 200 characters starting with `/`; otherwise
`422 {"detail": "live must be a JSON Pointer starting with /"}`.

- `chart`: a top-level `"live": pointer`, and no top-level `data` (both: `422 {"detail": "invalid block"}`). The
  `url`/`href`/`loader`/image check runs on the source as written, at write time. On every read and write, the `live`
  key is removed and `data` becomes `{"values": <the pointer's value>}`; the 5 000-row check and rendering run on that.
  Keys inside the resolved rows (a source list's `url` field, say) are data and are not checked. If the 5 000-row check
  fails or the chart does not render, the block answers `rendered: null` and `live_error` = that check's message
  (`chart exceeds 5000 data rows`, `chart does not render: <first line>`); a write still stores it, except that a write
  whose render fails (crash, out of memory, timeout or a Vega error, not a data problem: not found, not rows, over 5 000
  rows) answers `422 {"detail": "chart does not render: <first line>"}` and stores nothing (Amendment 1b). On a read,
  the API process remembers each (block id, version, SHA-256 of the resolved data as compact JSON) whose render failed
  and answers the same `live_error` for it without rendering again. The memory holds at most 1 000 entries, oldest
  dropped first.
- `table`: `{"live": pointer, "columns": [str]}`. A table has `rows` or `live`, never both and never neither; otherwise
  `422 {"detail": "invalid block"}`. The 1 to 20 columns check applies to a live table too. Each element of the pointer's list becomes a row:
  for each column, the element's key of that name; a missing key is `null`; a value that is not a string, number or
  `null` is its compact JSON text. A cell's text (a string value, or the compact JSON text of a value that is not a string, number or `null`)
  longer than 1 000 characters is cut to its first 1 000 characters followed by `…` (Amendment 1b). At most 200 rows are shown; more set `live_error` to `live data exceeds 200 rows`.
- tile: `"value": {"live": pointer}`; the pointer's value must be a JSON number.

A write checks only the pointer's form; a pointer that does not resolve is stored. Every read (and the write's own
answer) resolves it against the current thread data. When it does not resolve, or its value has the wrong shape, the
block answers with `live_error`: `live data not found: <pointer>`, `live data is not a list of rows: <pointer>` (chart,
table: not a list of objects) or `live data is not a number: <pointer>` (tile), and uses no data: a chart with
`values: []`, a table with no rows, a tile with `null`. Numbers read through a pointer are thread data, so the D4 check
never lists them.

A block in a response gains three fields: `live` (`true` when its source holds a pointer), `live_error` (`null` or the
first message above) and `live_step` (for a pointer whose first two tokens are `steps` and an index `n` that exists,
the `seq` of thread data `steps[n]`; else `null`). For tiles, `live_step` comes from the first tile, in order, that holds a
pointer, and `live_error` is the message of the first tile, in order, whose pointer fails. `rendered` for a live `table` is `{"rows": [[…]]}`; for a non-live table it stays `null`.

**Drawing.** `BoardBlockDraft.kind` takes the seven kinds. The system prompt offers `note`, `table`, `chart`,
`diagram`, `tiles` and `checklist` (not `flow`), with their source formats and the diagram checks above, and says: pick
the diagram type that makes the request clearest; group flowchart nodes with `:::GroupName` (1 to 4 short CamelCase
names that help the reader) and mark at most one key step with `class <id> emphasis`; set no colours or config; labels
at most 5 words; when the numbers come straight from one list or one number in the thread data, use a live pointer
instead of copying them. The retry, refusal and number check work as in Phase 1. A draft with a `live_error` counts as
refused with that message (one retry, then 422); a person's `POST /blocks` or `PATCH` stores it with its `live_error`.

**On screen (slice 3).**

- `diagram` and `flow` blocks are drawn by Mermaid 11 (`mermaid@11.4.1`) with `@mermaid-js/layout-elk@0.1.7` as the
  flowchart layout, `securityLevel: "strict"`, theme `base` with the house fonts and colours, and no `classDef` or config
  from the source. Both packages load with a dynamic `import()` the first time a diagram or flow is on screen, so the
  first page load does not carry them (AC-55). A `flow` block's source is Mermaid already and is drawn the same way; the
  `BoardFlow` component of Phase 1 is not built.
- Flowchart groups take, in the order they first appear in the source, the existing chart slots `--cat-1` (blue),
  `--cat-4` (violet), `--cat-2` (magenta) and then `--muted` (slate), from `frontend/src/index.css` in both themes. Each
  group's box has a fill of `color-mix(in oklch, <hue> 14%, var(--panel))`, a 1.5 px border of the hue, and text of
  `color-mix(in oklch, <hue> 65%, var(--text))`; the text keeps at least 4.5:1 contrast on its fill in light and dark.
  `--cat-3` (gold) and amber are never group colours (DESIGN.md keeps amber for "a person must act"). The builder adds
  one sentence on this to DESIGN.md's Chart Colours paragraph. The `emphasis` step has a 3 px border and semibold text. Under a grouped flowchart one legend line
  lists the groups in that order, each name with its CamelCase split into words (`DataTeam` → `Data Team`), and, when a
  step has `emphasis`, `Bold outline: key step` at the right.
- Mermaid runs, and the diagram is shown, inside its own frame (Amendment 1d): an `iframe` with
  `sandbox="allow-scripts allow-same-origin"` (no `allow-popups` or `allow-top-navigation`)
  whose document is a second Vite page, `board-diagram.html`, served from the app's own origin like `index.html`. That
  page's first element in `<head>` is `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src
  'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com;
  img-src data:">`, and it links the same font stylesheet as `index.html`. The policy applies to the frame's document
  whatever Mermaid draws into it, so even a diagram that gets past the server checks cannot load anything from outside.
  `board-diagram.html`'s entry is a plain `.ts` module with no JSX that imports no React; under `npm run dev` the frame
  needs no live reload. The CSP blocks every outside load; the sandbox blocks popups and top-level navigation; links
  themselves are removed by the `<a>`/`href` stripping below, which stays required.
  The frame is same-origin on purpose: its only scripts are the app's own and Mermaid's (strict), and same-origin keeps
  the existing `Cross-Origin-Embedder-Policy` and font loading working unchanged. The page loads Mermaid and ELK with a
  dynamic `import()` (AC-55 still holds). The Board posts the source, theme and colours to the frame with
  `postMessage(…, location.origin)`; the frame acts only on messages whose `source` is `window.parent` and whose
  `origin` is its own, and answers with its drawn height or Mermaid's error; the Board accepts only messages whose
  `source` is that frame's `contentWindow`. Rows that read a diagram's `svg` read it inside its frame.
- Before the SVG Mermaid returns goes into the frame's page, every `<a>` element in it is replaced by its children and every
  `href` and `xlink:href` attribute is removed (Amendment 1b), so no diagram holds a link.
- A diagram Mermaid cannot draw shows `This diagram could not be drawn: <first line of Mermaid's error>` and its
  source in a code box; the `⋯` menu works as for any block.
- A live block shows `Live · step <live_step>` beside its title, or `Live` when `live_step` is `null`. A block with
  `live_error` shows it as one line under the content, in the same style as `Not in ARP data`.
- While the Board tab is open on a plan it sends `GET /api/plans/<id>` every 10 s, and also `GET B` (redrawing the
  blocks) each time that status is `running`, and once more on the first poll whose status is not `running` after one
  that was. Both stop when the tab closes.
- `Edit` shows a `diagram` as text, and `tiles`, `checklist` and any live `chart` or `table` as formatted JSON of the
  source (a live table is never turned into CSV, so its pointer stays). `Download` of a live table writes `columns`, then
  `rendered.rows`; of a live chart, the light SVG with the current data.
- The empty board reads `Nothing on the board yet. Ask for a chart, diagram, table or checklist.`; the field's
  placeholder is `Ask the agent to draw something…`.

## Defaults decided here

- Block limits (50 per board, 200 rows, 20 columns, 5 000 chart rows, 20 000 note characters) are fixed, not settings.
- The draw call uses the configured model (`ARP_LLM_MODEL`), as explorations do.
- Versions are kept for as long as the block; there is no version browser, only undo.
- The board reloads when the thread is opened and after each change; from Phase 2 also every 10 s while the thread's
  status is `running` (D9).
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
- **Mind map M** (Phase 2): `"mindmap\n  root((Grow newsletter))\n    Topics\n    LinkedIn"`.
- **Grouped flow G** (Phase 2): `"flowchart LR\n  a[Find flat]:::Housing --> b[Give notice]:::Berlin\n  b --> c[Register]:::Munich\n  class b emphasis"`.
- **Live pointer W** (Phase 2): `/steps/0/result/weights`, which in Done plan D is the list of two `{sector, weight}` objects.

## Acceptance

A Phase 2 row (AC-33 on) whose `POST B/blocks` names no title sends `title: "X"`.
Superseded: AC-21 by AC-54 (new empty-board text), AC-32 by AC-56 (golden set with the new kinds). In rows, `B` is `/api/agent/boards/plan/<id>` for the plan named in "Given", and a source in a row is a JSON string
literal, decoded as JSON: `\n`, `\r`, `\\`, `\"` and each `\uXXXX` are one character, and a surrogate pair such as
`\ud83e\uddd1` is one character.

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
| ~~AC-21~~ | ~~Demo plan~~ | ~~open `#/agent/<id>`~~ | ~~the stage tabs read `Board`, `Script`, `Diff`, `Audit` in that order, then `Mini-app` if that tab has shipped, and `Board` is selected; the board shows `Nothing on the board yet. Ask for a chart, flowchart, table or note.`~~ | superseded by AC-54 |
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
| ~~AC-32~~ | ~~Golden file of 10 board requests over Done plan D's thread data, each with the expected `kind`~~ | ~~`cd backend && arp agent board-golden --cases tests/golden/board.jsonl --min-pass 8` (one `{id, prompt, expected_kind}` per line; a case passes if the draft passes every check on the first call, has the expected kind and `unverified: []`; the slice 2 builder writes the 10 cases)~~ | ~~exit 0~~ | superseded by AC-56 |
| AC-33 | Demo plan, empty board | `POST B/blocks` kind `diagram`, title `M`, source Mind map M | HTTP 201; `rendered: null`, `live: false`, `live_error: null` | holdout |
| AC-34 | Same | `POST B/blocks` kind `diagram`, title `P`, source `"pie\n  \"a\": 1"` | HTTP 422, `{"detail": "unsupported diagram type: pie; use flowchart, mindmap, timeline, sequenceDiagram or quadrantChart"}` | holdout |
| AC-35 | Same | `POST B/blocks` kind `diagram`, source `"%%{init: {\"theme\": \"dark\"}}%%\nflowchart LR\n  a --> b"` | HTTP 422, `{"detail": "diagram may not set its own config"}` | holdout |
| AC-36 | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a --> b\n  click a call f()"` | HTTP 422, `{"detail": "diagram may not use click lines"}` | holdout |
| AC-36b | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[<img src=x onerror=f()>] --> b"` | HTTP 422, `{"detail": "diagram may not contain HTML"}` | holdout |
| AC-36c | Same | `POST B/blocks` kind `diagram`, source a flowchart of 5 nodes `a` … `e`, each with its own group `:::G1` … `:::G5` | HTTP 422, `{"detail": "diagram has 5 colour groups; at most 4"}` | holdout |
| AC-36d | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[x] --> b[https://evil.test]"` | HTTP 422, `{"detail": "diagram may not load from outside"}` | holdout |
| AC-37 | Done plan D; stand-in draft `{"kind": "tiles", "title": "Key", "source": {"tiles": [{"label": "Utilities", "value": 0.31, "format": "percent"}, {"label": "Other", "value": 0.5}]}}` | `POST B/draw` `{"prompt": "key numbers"}` | HTTP 200; `kind: "tiles"`, `unverified: [0.5]`, `rendered: {"values": [0.31, 0.5]}` | holdout |
| AC-38 | Demo plan, empty board | `POST B/blocks` kind `tiles`, source `{"tiles": [{"label": "a", "value": "31%"}]}` | HTTP 422, `{"detail": "tile 1: value must be a number"}` | holdout |
| AC-38b | Same | `POST B/blocks` kind `tiles`, source with 5 tiles `{"label": "a", "value": 1}` | HTTP 422, `{"detail": "tiles must have 1 to 4 tiles"}` | holdout |
| AC-39 | Demo plan; checklist `C` with source `{"items": [{"text": "Call vendor", "done": false}]}` at version 1 | `PATCH B/blocks/<C>` `{"source": {"items": [{"text": "Call vendor", "done": true}]}}`, then `POST B/blocks/<C>/undo` | the PATCH answers `version: 2`, `origin: "person"`, item 1 `done: true`; the undo answers `version: 3`, item 1 `done: false` | holdout |
| AC-40 | Demo plan, empty board | `POST B/blocks` kind `checklist`, source `{"items": []}` | HTTP 422, `{"detail": "checklist must have 1 to 50 items"}` | holdout |
| AC-41 | Done plan D, empty board | `POST B/blocks` kind `table`, title `W`, source `{"live": "/steps/0/result/weights", "columns": ["sector", "weight"]}` | HTTP 201; `live: true`, `live_error: null`, `unverified: []`, `rendered: {"rows": [["Energy", 0.125], ["Utilities", 0.31]]}`; `source` is returned as sent | holdout |
| AC-42 | The block from AC-41; the test then sets the stored result's Utilities weight to `0.4` | `GET B` | that block's `rendered.rows` is `[["Energy", 0.125], ["Utilities", 0.4]]`; its `version` is still 1 | holdout |
| AC-43 | Done plan D, empty board | `POST B/blocks` kind `table`, source `{"live": "/steps/5/result", "columns": ["a"]}` | HTTP 201; `live_error: "live data not found: /steps/5/result"`, `rendered: {"rows": []}` | holdout |
| AC-43b | Same | `POST B/blocks` kind `table`, source `{"live": "steps/0", "columns": ["a"]}` | HTTP 422, `{"detail": "live must be a JSON Pointer starting with /"}` | holdout |
| AC-44 | Same | `POST B/blocks` kind `chart`, title `C`, source `{"live": "/steps/0/result/weights", "mark": "bar", "encoding": {"x": {"field": "sector", "type": "nominal"}, "y": {"field": "weight", "type": "quantitative"}}}` | HTTP 201; `live: true`, `live_error: null`, `unverified: []`; `rendered.light` contains `#2a78d6` and the text `Utilities` | holdout |
| AC-45 | Same | `POST B/blocks` kind `chart`, source `{"live": "/steps/0/result/weights", "mark": "image", "encoding": {"url": {"field": "sector"}}}` | HTTP 422, `{"detail": "chart may not load from outside: mark"}` | holdout |
| AC-46 | Same | `POST B/blocks` kind `tiles`, source `{"tiles": [{"label": "Utilities", "value": {"live": "/steps/0/result/weights/1/weight"}}, {"label": "Bad", "value": {"live": "/steps/0/result/weights/1/sector"}}]}` | HTTP 201; `rendered: {"values": [0.31, null]}`, `live_error: "live data is not a number: /steps/0/result/weights/1/sector"` | holdout |
| AC-47 | Demo plan with Mind map M and Grouped flow G on its board | open its Board tab | M shows an `svg` holding the text `Grow newsletter`, `Topics` and `LinkedIn`; G shows boxes `Find flat`, `Give notice`, `Register` whose three fill colours differ; under G one line reads `Housing`, `Berlin`, `Munich` and `Bold outline: key step`; `Give notice`'s border is 3 px wide | evaluator |
| AC-48 | A `diagram` block whose source is `"flowchart LR\n  a -->"` (stored straight in the table by the test, since it passes the server checks) | open the Board tab | the block shows `This diagram could not be drawn:` and its source; its `⋯` menu opens | evaluator |
| AC-49 | Board with M and G | open the Board tab with the browser's network log on | every request goes to the app's own origin, `fonts.googleapis.com` or `fonts.gstatic.com`; no request made after the Board tab opens goes to any other host | evaluator |
| AC-50 | Done plan D; tiles `T` with source `{"tiles": [{"label": "Utilities", "value": 0.31, "format": "percent", "change": 0.04, "note": "vs Q2"}, {"label": "Issuers", "value": 1234.5, "change": -12}]}` | open the Board tab | the tiles read `Utilities` `31.0%` `+4.0 pts` `vs Q2` and `Issuers` `1,234.5` `-12` | evaluator |
| AC-51 | Checklist `C` from AC-39 at version 1 | tick `Call vendor`, reload, then `⋯`, `Undo last change` | after the reload the box is ticked; after the undo it is not | evaluator |
| AC-52 | The live table from AC-41 | open the Board tab; the test then sets Utilities to `0.4` and reloads the page | beside the title `Live · step 1`; before the change the table shows `0.31`, after it `0.4` | evaluator |
| AC-53 | The block from AC-43 | open the Board tab | under the table one line reads `live data not found: /steps/5/result` | evaluator |
| AC-54 | Demo plan, empty board | open `#/agent/<id>` | the stage tabs read `Board`, `Script`, `Diff`, `Audit` in that order, then `Mini-app` if that tab has shipped, and `Board` is selected; the board shows `Nothing on the board yet. Ask for a chart, diagram, table or checklist.` and the field's placeholder is `Ask the agent to draw something…` | evaluator |
| AC-55 | — | `cd frontend && npx vite build --manifest`, then read `dist/.vite/manifest.json` | the manifest has an entry whose `src` is `node_modules/mermaid/dist/mermaid.core.mjs` with `isDynamicEntry: true`; the `file` of the `index.html` entry and of every chunk reached from it through `imports` (recursively) contains neither the text `gitGraph` nor `org.eclipse.elk` | unit |
| AC-56 | Golden file of 14 board requests over Done plan D's thread data: the 10 of AC-32 (an `expected_kind` of `flow` there becomes `diagram`) plus one each expecting `diagram` for a mind map, `diagram` for a sequence, `tiles` and `checklist`; two of the 14 (a table and a chart of the sector weights) also carry `"expected_live": true` | `cd backend && arp agent board-golden --cases tests/golden/board.jsonl --min-pass 11` (a case passes as in AC-32, with `live_error: null`, and, when `expected_live` is true, with `live: true`) | exit 0 | golden |
| AC-57 | A plan with status `running` whose step 1 result is Done plan D's; the live table from AC-41 on its board; the Board tab open | the test sets Utilities to `0.4` | within 15 s, with no page reload, the table shows `0.4` | evaluator |
| AC-58 | A plan whose step 1 result is `{"rows": [{"v": 1}, …]}` with 5 001 rows | `POST B/blocks` kind `chart`, source `{"live": "/steps/0/result/rows", "mark": "point", "encoding": {"y": {"field": "v", "type": "quantitative"}}}` | HTTP 201; `rendered: null`, `live_error: "chart exceeds 5000 data rows"` | holdout |
| AC-59 | Done plan D; a person's tiles block `T` with `{"tiles": [{"label": "a", "value": 0.31}]}` | `PATCH B/blocks/<T>` `{"source": {"tiles": [{"label": "a", "value": 9.99}]}}` | `unverified: [9.99]` | holdout |
| AC-60 | Done plan D, empty board | `POST B/blocks` kind `table`, source `{"live": "/steps/0/result/weights", "columns": ["sector"], "rows": []}` | HTTP 422, `{"detail": "invalid block"}` | holdout |
| AC-61 | The live table from AC-41 | `⋯`, `Download` | `W.csv` reads `sector,weight`, `Energy,0.125`, `Utilities,0.31` on three lines | evaluator |
| AC-62 | Demo plan, empty board | `POST B/blocks` kind `checklist`, title `X`, source `{"items": [{"text": "a", "done": false}]}`, `"unverified": [1]`; then the same with kind `diagram`, source Mind map M | both HTTP 201 with `unverified: []` | holdout |
| AC-63 | Tiles `T` from AC-50; checklist `C` with items `a` done and `b` not done; diagram `M` with source Mind map M | `Download` on each; `⋯`, `Edit` on `T` | `T.csv` reads `label,value,change,note`, `Utilities,0.31,0.04,vs Q2`, `Issuers,1234.5,-12,` on three lines; `C.md` reads `- [x] a` and `- [ ] b` on two lines; `M.mmd` holds exactly Mind map M; `Edit` on `T` shows its source as formatted JSON | evaluator |
| AC-64 | The plan of AC-57 with the Board tab open | the test sets Utilities to `0.4` and the plan's status to `done` in one write | within 15 s, with no page reload, the table shows `0.4` | evaluator |
| AC-36e | Demo plan, empty board | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[Start] --> b[End]; click a href \"x\" _blank"` | HTTP 422, `{"detail": "diagram may not use click lines"}` | holdout |
| AC-36f | Same | `POST B/blocks` kind `diagram`, source `"sequenceDiagram\n  participant A as Analyst\n  link A: Report @ x\n  A->>A: Review"` | HTTP 422, `{"detail": "diagram may not use link lines"}` | holdout |
| AC-36g | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[see //evil.example] --> b"` | HTTP 422, `{"detail": "diagram may not load from outside"}` | holdout |
| AC-36h | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[x:\\\\evil] --> b"` (a colon then two backslashes) | HTTP 422, `{"detail": "diagram may not load from outside"}` | holdout |
| AC-49b | A `diagram` block stored straight in the table by the test with source `"flowchart LR\n  a --> b\n  click a href \"https://example.com\""` | open the Board tab | the diagram shows boxes `a` and `b`; its `svg` holds no `a` element and no `href` or `xlink:href` attribute | evaluator |
| AC-58b | Done plan D, empty board | `POST B/blocks` kind `chart`, source `{"live": "/steps/0/result/weights", "mark": "line", "transform": [{"density": "weight", "steps": 50000000}], "encoding": {"x": {"field": "value", "type": "quantitative"}, "y": {"field": "density", "type": "quantitative"}}}` | HTTP 422 whose `detail` starts `chart does not render: `; the board is still empty | holdout |
| AC-58c | A plan whose step 1 result is `{"rows": [{"note": <a string of 2 000 `x`>}]}`; on its board a live table with columns `["note"]` and pointer `/steps/0/result/rows` | `GET B` | that block's `rendered.rows` is one row whose one cell is 1 001 characters: 1 000 `x` then `…` | holdout |
| AC-36i | Demo plan, empty board | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a@{ img: \"x.png\" } --> b"` | HTTP 422, `{"detail": "diagram may not use shape options"}` | holdout |
| AC-36j | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[http:evil.example] --> b"` | HTTP 422, `{"detail": "diagram may not load from outside"}` | holdout |
| AC-36k | Demo plan, empty board | `POST B/blocks` kind `diagram`, source `"sequenceDiagram\n  participant A as Analyst\n  properties A: {\"icon\": \"x.png\"}\n  A->>A: Review"` | HTTP 422, `{"detail": "diagram may not use properties lines"}` | holdout |
| AC-36l | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[x\\/y] --> b"` (one backslash then a slash in the label) | HTTP 422, `{"detail": "diagram may not load from outside"}` | holdout |
| AC-36m | Same | `POST B/blocks` kind `flow`, source `"flowchart LR\n  a[<img src=x>] --> b"` | HTTP 422, `{"detail": "diagram may not contain HTML"}` | holdout |
| AC-36n | Same | `POST B/blocks` kind `flow`, source `"%%{init: {}}%%\nflowchart LR\n  a --> b"` | HTTP 422, `{"detail": "diagram may not set its own config"}` | holdout |
| AC-36o | Same | `POST B/blocks` kind `diagram`, source `"sequenceDiagram\n  participant A as Analyst\n  details A: {\"x\": 1}\n  A->>A: Review"` | HTTP 422, `{"detail": "diagram may not use details lines"}` | holdout |
| AC-36p | Same | `POST B/blocks` kind `flow`, source `"flowchart LR\n  classDef Ops fill:#fff\n  a[Extract<br>Claude]:::Ops --> b:::Ops\n  class b stored"` | HTTP 201; `rendered.steps[0].label` is `Extract` | holdout |
| AC-36q | Same | `POST B/blocks` kind `diagram`, source `"mindmap\n  root((Move))\n    Details\n    Properties"` | HTTP 201 | holdout |
| AC-36r | Demo plan, empty board | `POST B/blocks` kind `diagram`, source `"sequenceDiagram\n  participant A as Analyst\n\ufeffproperties A: {\"icon\": \"x.png\"}\n  A->>A: Review"` | HTTP 422, `{"detail": "diagram may not contain hidden characters"}` | holdout |
| AC-36s | Same | `POST B/blocks` kind `diagram`, source `"%%\u001cflowchart LR\nsequenceDiagram\n  A->>A: Review"` | HTTP 422, `{"detail": "diagram may not contain hidden characters"}` | holdout |
| AC-36t | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[see #47;#47;evil.example] --> b"` | HTTP 422, `{"detail": "diagram may not use entity codes"}` | holdout |
| AC-36u | Same | `POST B/blocks` kind `flow`, source `"flowchart LR\n  a[Build universe] --> b[Extract]\r\n  b --> c[Report]"` | HTTP 201; `rendered.steps` has 3 entries | holdout |
| AC-36v | Demo plan, empty board | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a --> b\r  click a href \"x\""` | HTTP 422, `{"detail": "diagram may not use click lines"}` | holdout |
| AC-36w | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a --> b\n  click\u00a0a href \"x\""` | HTTP 422, `{"detail": "diagram may not use click lines"}` | holdout |
| AC-36x | Same | `POST B/blocks` kind `diagram`, source `"mindmap\r\n  root((Move))\r\n    Topics"` | HTTP 201 | holdout |
| AC-36z | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  subgraph s\n    a\n  end click a href \"x\""` | HTTP 422, `{"detail": "diagram may not use click lines"}` | holdout |
| AC-36y | Same | `POST B/blocks` kind `diagram`, source `"mindmap\n  root((Team \ud83e\uddd1\u200d\ud83d\udcbb))\n    B\u00fcro"` (an emoji joined with U+200D, and `Büro`) | HTTP 201 | holdout |
| AC-49c | A `diagram` block stored straight in the table by the test with source `"sequenceDiagram\n  participant A as Analyst\n  properties A: {\"icon\": \"https://example.com/i.png\"}\n  A->>A: Review"` | open the Board tab with the browser's network log on | the diagram shows `Analyst`; the network log shows no completed response from `example.com` (an entry blocked by the Content-Security-Policy counts as blocked) | evaluator |
| AC-49d | Board with M and G | open the Board tab | each of the two diagrams is inside an `iframe` whose `sandbox` attribute is exactly `allow-scripts allow-same-origin` and whose document URL's path ends `board-diagram.html` | evaluator |
| AC-55b | — | `cd frontend && npx vite build`, then read `dist/board-diagram.html` | the first child element of its `<head>` is a `<meta http-equiv="Content-Security-Policy">` whose `content` is exactly `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src data:` | unit |
| AC-65 | Demo plan, empty board | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a --> b\n  accDescr { x } click a href \"x\""` | HTTP 422, `{"detail": "diagram may not use click lines"}` | holdout |
| AC-66 | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[see \ufb02\u00b0\u00b047\u00b6\u00df] --> b"` | HTTP 422, `{"detail": "diagram may not use entity codes"}` | holdout |
| AC-66b | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a[see \ufb02\u00b0\u00b047;] --> b"` | HTTP 422, `{"detail": "diagram may not use entity codes"}` | holdout |
| AC-67b | Same | `POST B/blocks` kind `flow`, source `"flowchart LR\n  a --> b{Ready?}\n  b --> c[Stra\u00dfe]"` | HTTP 201; `rendered.steps[1].kind` is `decision` | holdout |
| AC-67 | Same | `POST B/blocks` kind `diagram`, source `"flowchart LR\n  a --> b{Ready?}\n  b --> c[Stra\u00dfe]"` | HTTP 201 | holdout |
| AC-58d | A live chart block whose stored source renders on write but whose resolved data later makes the render fail (the test swaps `render_chart` for one that raises `RenderFailed` and counts calls) | `GET B` twice | both answers carry the same `live_error`, and `render_chart` was called once | unit |

## Slices

| Slice | PR contents | Risk | Needs | Rows |
|---|---|---|---|---|
| 1 | Tables, block checks, chart and flow rendering, `GET`, `POST /blocks`, `PATCH`, `undo`, `DELETE` for plans | `risk:high` (schema) | — | AC-1 to AC-13e, AC-30 |
| 2 | `POST /draw`: prompt, retry, number check (also on a person's `PATCH`), stand-in lists, golden set; in `.github/workflows/golden-set.yml` adds `backend/arp/agent_board/**` and `tests/golden/board.jsonl` to the `paths` filter, `arp/agent_board tests/golden/board.jsonl` to the `other=` git-diff list of the `scope` step, and the `arp agent board-golden …` line to the run step | `risk:high` (workflow file) | slice 1 | AC-14 to AC-17d, AC-19, AC-19b, AC-20, AC-20b, AC-30, AC-32 |
| 3 | Board tab on the Agent screen, with Phase 2's diagram renderer, tiles, checklists and live labels | `risk:normal` | slice 2b, and slices 6 and 8 of `agent-panel-code-mode` | AC-18, AC-18b, AC-22 to AC-26 (with AC-25b to AC-25h), AC-29, AC-31, AC-47 to AC-55, AC-57, AC-61, AC-63, AC-64, AC-49b, AC-49c, AC-49d, AC-55b |
| 2b | Phase 2 backend: `diagram`, `tiles` and `checklist` checks, the diagram checks on `flow` sources (Amendment 1c), live pointers on reads, the draw prompt and `BoardBlockDraft` kinds, 4 more golden cases; in `.github/workflows/golden-set.yml` the run step's `--min-pass 8` becomes `--min-pass 11` | `risk:high` (workflow file) | slice 2 | AC-30, AC-33 to AC-46, AC-56, AC-58 to AC-60, AC-62, AC-36e to AC-36z, AC-58b to AC-58d, AC-65 to AC-67 (with AC-66b, AC-67b) |
| 4 | Boards on explorations | `risk:normal` | slice 3, and slice 10 of `agent-panel-code-mode` | AC-27, AC-28, AC-30, AC-31 |

Slices 1 and 2 are merged. Slice 2b can start once Amendment 1 is approved and its hidden tests are written; slice 3
waits for slice 2b and the Agent screen's stage tabs.

## Later

- **Next step up: board to deck.** A `Send to deck` action that turns the board into house-deck slides (a `diagram` flowchart that `parse_mermaid` accepts goes in as a native flow; other diagrams as pictures). Charts are
  already Vega-Lite and flowcharts already the deck's Mermaid subset, so it needs a block-to-slide mapping and an
  export route, not new drawing.
- Mini-app blocks: when slice 11 of `agent-panel-code-mode` ships, a mini-app becomes a fifth block kind instead of its
  own tab.
- The agent adding a block per finished step (D3's alternative), if the owner wants it after using the board.
- Draw calls counted against the plan budget.
