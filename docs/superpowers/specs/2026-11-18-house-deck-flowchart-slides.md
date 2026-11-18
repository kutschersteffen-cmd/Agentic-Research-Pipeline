# Editable flowchart slides in the house deck

Slug: house-deck-flowchart-slides

Risk: `risk:normal` for the build. Size M, delivered as 5 PRs of size S (see `## Slices`). This spec PR is `risk:low`.

Status: **approved by the owner on 18 Nov 2026** (button in the spec session, after two spec-critic rounds; decisions D1–D4 as recommended).
Source: house-deck builder plan, PR 5 (https://claude.ai/artifact/HrvD3WdtCD3e15cMGPjesm); prototype and findings in the
project folder `deck-tools-samples/` (`source/lay.js`, `source/draw.py`, `flow-factory.png`). Checked against `origin/main`
`99267cb`.

## Decisions for the owner

Approving this spec accepts all four as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | The new `flow` visual replaces the planned, never-built `swimlane_flow` of `slide-components-design` (its PR 2). Fixed swimlanes are out (the prototype showed ELK tangles arrows when rows are forced); actors are box fill plus a legend. | Yes: rows AC-37, AC-38 and AC-39 of `slide-components-design` are retired, and AC-50 no longer expects `swimlane_flow` in the prompt (see "Superseded rows"). | Both visuals exist and the storyline offers two flow types. |
| D2 | In the PowerPoint each step is a group (box, label, tag) and left-to-right arrows that are straight (2 route points) or horizontal-vertical-horizontal (4 route points) are connectors glued to the boxes, so moving a box in PowerPoint drags its arrows along. Other arrows are freeform lines. | Yes (AC-27 to AC-30, AC-34b) | All arrows are freeform lines; moving a box leaves its arrows behind. |
| D3 | A left-to-right flow too wide for the slide first wraps into rows (ELK's graph wrapping), at full text size, before text steps down to 24 px. Text never goes below 24 px and the diagram is never scaled. | Yes (AC-17, AC-18) | A 10-step chain gets a `flow_too_big` finding instead of a two-row layout. |
| D4 | A new command `arp report flow <file.mmd> --out <dir>` turns any Mermaid flowchart into one house slide (PPTX, PDF, PNG), without a report, database or model. | Yes (AC-31 to AC-33, AC-34a) | Flows only appear inside a generated deck; the evaluator needs a scripted deck. |

## Why

Today the house deck has no diagram. The 24 diagrams of the engineering deck were hand-written SVG in the Flow
Atlas, pasted in as pictures, so nobody can fix a label or move a box in PowerPoint. The owner chose on 18 Nov 2026:
ELK (`elkjs`) lays flowcharts out, ARP draws them as native shapes, and the model writes Mermaid flowchart text
that ARP parses into a typed visual.

**What the user can do afterwards that they cannot do today:**

1. Ask for a deck and get process slides as diagrams in house style, with up to 12 steps, up to 4 actors and
   labelled arrows, drawn the same in the PDF and the PowerPoint.
2. Edit those diagrams in PowerPoint: every box, label and arrow is a native shape; a step moves as one group and
   its left-to-right arrows follow it.
3. Turn any Mermaid flowchart file into one editable house slide with one command.
4. Trust the size: a diagram either fits the slide at 24 px text or more, or the slide is flagged with the exact
   size it needed. It is never shrunk into unreadable text.

## Versions considered

- **Safe:** typed `flow`, Mermaid parser, ELK layout at one fixed text size, freeform arrows, fixed box sizes, a
  finding when the layout is too big. Long chains (8+ steps in a row) almost always get the finding.
- **Strong (specified here):** the safe version plus label widths measured in Chromium with the deck's fonts,
  explicit line breaks so PowerPoint cannot re-wrap a label, a fit ladder that wraps long chains into rows and then
  steps text down to 24 px, decision/data/stored/emphasis marks, a legend, grouped steps with glued connectors, the
  Mermaid source in the speaker notes, and the `arp report flow` command.
- **Most ambitious:** the strong version plus a model call that merges steps when a flow is too big, and a
  round trip from an edited PowerPoint back to Mermaid.

**Next step up** would need: a fit-ladder step that asks the model to rewrite the Mermaid with fewer steps (one
call, re-parse, re-layout, then the finding), and a PPTX reader that maps named groups and glued connectors back to
Mermaid. Both are left for a later spec.

## What exists today

- `backend/arp/schemas/visuals.py`: typed visuals `cover`, `section`, `kpi_row`, `chart`, `comparison_table`,
  `two_column`, `points`, `next_steps` in the `Visual` union, with `FRIENDLY_NAMES`.
- `backend/arp/reporting/render_model.py`: `render_slide` turns a slide into `Rect`, `Text`, `Line`, `ChartPrim`,
  `TablePrim` primitives in canvas px (1920×1080); `VISUALS` maps `visual.type` to a renderer; `BODY` is
  x 96, y 328, w 1728, h 592 (a template frame may set another body box, `body_box(tokens)`).
- `html_writer.py` and `pptx_writer.py` draw the same primitive list; a `Line` becomes an SVG polyline and a PPTX
  freeform with an optional `a:tailEnd` arrowhead. A `Text` with `\n` is drawn as separate lines in both.
- `browser.py` launches Chromium (`ARP_CHROMIUM_PATH`) for measuring, PDF and PNG.
- `house_pipeline.build_house_deck`: fill (`slide_fill.fill_slide`, one retry with errors, then a `points`
  fallback with a `bad_reference` finding) → lint → `fit_deck` → `fit_ladder` → visual QA → outputs.
- `storyline.CONTENT_VISUALS` lists the visuals the storyline may pick; `style/design.md` says which visual fits
  which claim.
- `design_checks.py`: `underfill`, `small_text` (< 18 px), `low_contrast`, `emphasis_count`.
- Palette `graphite` (light): ground `f4f6f9`, panel `ffffff`, line `d8dee7`, well `eaeef3`, ink `121722`, muted
  `4f5a6b`, highlight `2a78d6`, series_2 `c4ccd7`, inverse_muted `aab4c3`; `graphite_dark` has the same keys.
- No flow visual, no Mermaid parser and no ELK in the repo. `slide-components-design` planned `linear_flow` and
  `swimlane_flow` for its PR 2, which was never built.

## Goals

- G1: a typed `flow` visual with the limits below, accepted by `SlideContent.visual`.
- G2: a parser for a Mermaid flowchart subset into `flow`, rejecting everything else with an exact, line-numbered error.
- G3: ELK layout in the Chromium ARP already launches, from a pinned, vendored `elkjs` with its licence.
- G4: one renderer whose primitives both writers draw; in the PPTX every part is a native, editable shape.
- G5: a fit ladder for flows that never scales the diagram and never sets text below 24 px, ending in a
  `flow_too_big` finding.
- G6: the storyline and slide fill offer `flow`; the model writes Mermaid; one retry with the parse error, then a finding.
- G7: `arp report flow` renders one Mermaid file as a house slide.

## Non-goals

- Mermaid diagram types other than flowcharts (plan PR 7), image slides (plan PR 4), fixed swimlanes, subgraphs.
- Frontend changes. The report page shows flow slides through the existing preview PNGs.
- Mermaid's own renderer, and any Mermaid styling (`style`, `linkStyle`, colours in `classDef` are ignored).
- A model call to merge steps when a flow is too big (next step up).
- `linear_flow` from `slide-components-design` stays as planned there; this spec does not touch it.

## Anti-goals

- The diagram is never scaled down to fit, and no flow text is below 20 px (tags and arrow labels) or 24 px (step
  labels).
- No new colour: every fill and line comes from `graphite` / `graphite_dark`.
- No Node.js on the server: ELK runs in the page Chromium already loads.
- Existing visuals and their PPTX output do not change.

## Design

### The `flow` visual (`backend/arp/schemas/visuals.py`)

```python
class FlowStep(BaseModel):
    id: str            # ^[A-Za-z][A-Za-z0-9_]{0,31}$
    label: Words(5)    # 1 to 5 words, not blank
    tag: Chars(24) = ""   # optional tech tag, e.g. "Postgres"
    kind: Literal["step", "decision", "data"] = "step"
    actor: str | None = None
    stored: bool = False  # "stored result" marker

class FlowArrow(BaseModel):
    source: str
    target: str
    label: Words(3) = ""

class Flow(BaseModel):
    type: Literal["flow"] = "flow"
    mermaid: str = ""                      # what the model writes; parsed on validation
    direction: Literal["LR", "TB"] = "LR"
    steps: list[FlowStep]                  # 2 to 12
    actors: list[str] = []                 # 0 to 4, in first-appearance order
    arrows: list[FlowArrow] = []           # 0 to 20
    emphasis: str | None = None            # a step id
    layout: FlowLayout | None = None       # filled by code (layout_flows), never by the model
```

- `Flow` joins the `Visual` union; `FRIENDLY_NAMES["flow"] = "Flowchart"`.
- **Validation** (pydantic, so a slide-fill answer that breaks it is sent back with the message):
  - When `mermaid` is not blank, it is parsed (below) and the parsed `direction`, `steps`, `actors`, `arrows` and
    `emphasis` replace whatever the input held; a parse error is a validation error whose message contains the
    parser's message unchanged.
  - Steps 2–12, actors 0–4, arrows 0–20; step ids unique; each arrow's `source` and `target` are step ids; no arrow
    from a step to itself; no two arrows with the same source and target; each `actor` is in `actors`; when
    `actors` is not empty every step has an actor; `emphasis` is a step id or none.
- `FlowLayout` (filled by code) holds `type_step` (0 or 1), `wrapped` (bool), `too_big` (bool), `width` and `height`
  of the laid-out diagram, and per step its box and label lines, per arrow its route points and label box, all in
  canvas px.

### Mermaid subset (`backend/arp/reporting/mermaid_flow.py`)

`parse_mermaid(text: str) -> Flow` (with `layout` none), raising `MermaidError` whose `str()` is the message below.
Line numbers count every line of the text, from 1.

Accepted:

- **Header** (first line that is not blank and not a comment): `flowchart` or `graph`, then `LR`, `TB` or `TD`
  (`TD` is `TB`).
- **Comments:** lines starting with `%%` (after spaces), including `%%{init: …}%%`. Blank lines. A trailing `;`.
- **Nodes:** `id`, `id[Text]`, `id(Text)`, `id([Text])` → kind `step`; `id{Text}` → `decision`; `id[(Text)]` → `data`.
  Text may be quoted (`id["Text"]`); quotes are stripped. A node's text comes from the one place that gives it text,
  wherever that is (`a --> b` then `b[Later]` labels `b` "Later"); a node never given text is labelled with its id.
  `defined twice` applies only when two places give the same id text.
- **Label and tag:** text before the first `<br>` (also `<br/>`, `<br />`) is the label, text after it the tag.
- **Arrows:** `a --> b`, `a -->|text| b`, `a -- text --> b`, and chains `a --> b --> c`. Nodes may be defined inside
  arrow lines (`a[Start] --> b{Ok?}`).
- **Actors:** `classDef name …` (anything after the name is ignored), `class a,b name`, and `a:::name`. Every class
  name other than `stored` and `emphasis` is an actor, in order of first appearance anywhere in the text.
- **Reserved classes:** `stored` sets `stored` true; `emphasis` sets the flow's `emphasis` (one step only).
- Step order is order of first appearance.

Rejected, each with exactly this message (`<n>` the line number, `<x>` the offending token as written):

| Input | Message |
|---|---|
| the header line's first word is `sequenceDiagram`, `classDiagram`, `stateDiagram`, `stateDiagram-v2`, `erDiagram`, `gantt`, `pie`, `journey`, `gitGraph`, `mindmap`, `timeline`, `quadrantChart`, `sankey-beta`, `xychart-beta` or `block-beta` (`<x>` that word) | `line <n>: only flowcharts are supported, not <x>` |
| any other header line that is not `flowchart`/`graph` plus a direction, including `flowchart` alone (`<n>` is the header line's number) | `line <n>: start with "flowchart LR" or "flowchart TB"` |
| direction `RL` or `BT` | `line <n>: direction <x> is not supported; use LR or TB` |
| `subgraph` | `line <n>: subgraph is not supported` |
| `style` | `line <n>: style is not supported` |
| `linkStyle` | `line <n>: linkStyle is not supported` |
| `click` | `line <n>: click links are not supported` |
| `---` as the header line (front matter) | `line <n>: front matter is not supported` |
| a node shape other than the accepted ones; `<x>` is the opener: `((`, `>`, `{{`, `[/`, `[\`, `[[` or `@{` | `line <n>: shape <x> is not supported; use [ ], { } or [( )]` |
| an arrow other than `-->`; `<x>` the arrow token as written: `---`, `==>`, `-.->`, `<-->`, `--o`, `--x`, `~~~` | `line <n>: arrow <x> is not supported; use -->` |
| `&` in an arrow line | `line <n>: & is not supported; write one arrow per pair` |
| a node id defined twice with text | `line <n>: step <x> is defined twice` |
| a second `<br>` in one node | `line <n>: step <x> has more than one <br>; write the label, then one tech tag` |
| any other line that matches nothing | `line <n>: cannot read "<the line, trimmed>"` |

After the lines are read, the limits give (no line number):

| Case | Message |
|---|---|
| more than 12 steps | `flow has <k> steps; at most 12` |
| fewer than 2 | `flow has <k> step(s); at least 2` (`step` for 1, `steps` for 0) |
| more than 4 actors | `flow has <k> actors; at most 4` |
| more than 20 arrows | `flow has <k> arrows; at most 20` |
| label over 5 words | `step <id>: label has <k> words; at most 5` |
| tag over 24 characters | `step <id>: tag has <k> characters; at most 24` |
| arrow label over 3 words | `arrow <a>→<b>: label has <k> words; at most 3` |
| arrow from a step to itself | `arrow <a>→<a>: a step cannot point to itself` |
| same arrow twice | `arrow <a>→<b> appears twice` |
| a step in two actors | `step <id> is in 2 actors; at most 1` |
| actors present, a step without one | `step <id> has no actor; give every step an actor or none` |
| two `emphasis` steps | `only one step can have class emphasis` |
| `class` naming an unknown step | `class names unknown step <id>` |

Within one limits row, the message names the first offending step or arrow in step or arrow order. Labels and tags
are trimmed of surrounding whitespace before counting. When several errors apply, the parser reports the first line error by line number, else the first limit error in the
table's order.

### Layout (`backend/arp/reporting/flow_layout.py`, vendored ELK)

- **Vendored ELK:** `backend/arp/reporting/vendor/elkjs/elk.bundled.js` is `elkjs` 0.12.1's `lib/elk.bundled.js`,
  unchanged (sha256 `b1032b7cfd2a57c54c6f0e8369d7665e19a579954f7cd20a6dae28f1912ea0d7`). Next to it: `LICENSE.md`
  (the package's EPL-2.0 text) and `README.md` naming the package, version 0.12.1, the npm URL, the sha256 and the
  licence. It ships in the wheel (`package-data` for `arp.reporting`: `vendor/elkjs/*`). If gitleaks flags the bundle, it is allowed by path in
  `.gitleaksignore`.
- **API:** `async def layout_flows(deck: Deck, tokens: Tokens, mode: Mode = "light") -> tuple[Deck, list[Finding]]`
  lays out every `flow` slide whose `layout` is none, in one Chromium launch (`browser._page`), and returns the deck
  with each such flow's `layout` set. A deck with no flow slide to lay out is returned unchanged with no findings and
  Chromium is not launched.
- **Text measuring** in the same page, with the fonts `render_deck_html` uses for these tokens:
  - Step label: weight 600, body family, 28 px (type step 0) or 24 px (type step 1), line height 1.2. One line when
    its width is at most 320 px; else two lines, broken at the word boundary that makes the longer line shortest.
  - Tag: mono family, 20 px, one line. Arrow label: mono, 20 px, one line.
- **Step box:** width = max(160, widest label line, tag width) + 48; height = 24 + label lines × size × 1.2
  + (tag ? 8 + 24 : 0) + 24 + (stored ? 8 : 0).
- **ELK options:** `elk.algorithm` `layered`, `elk.direction` `RIGHT` (LR) or `DOWN` (TB), `elk.edgeRouting`
  `ORTHOGONAL`, `elk.padding` `[top=0,left=0,bottom=0,right=0]`, `elk.layered.spacing.nodeNodeBetweenLayers` 48, `elk.spacing.nodeNode` 40, `elk.spacing.edgeNode` 24,
  `elk.spacing.edgeEdge` 16, `elk.layered.considerModelOrder.strategy` `NODES_AND_EDGES`, arrow labels with their
  measured size + 8 px padding each side. When wrapping: `elk.layered.wrapping.strategy` `MULTI_EDGE` and
  `elk.aspectRatio` = area width / area height.
- **Area:** the body box (`body_box(tokens)`), less a 40 px band at the bottom for the legend when the flow has
  actors or a stored step.
- **Fit ladder** (first that fits wins; the layout's `width` and `height` are those of the bounding box of all step boxes, arrow route
  points and arrow-label boxes; "fits" = `width` ≤ area width and `height` ≤ area height):
  1. 28 px, the flow's direction, no wrapping;
  2. LR only: 28 px, wrapped;
  3. 24 px, the flow's direction, no wrapping;
  4. LR only: 24 px, wrapped.
  If none fits, the last one tried is kept with `too_big` true, the slide gets `needs_review` true and one finding
  `stage="fit"`, `rule="flow_too_big"`, `message="laid out <W>×<H> px at 24 px text; the body has <AW>×<AH> px; merge
  steps"` (integers, rounded; AW×AH is the area, so the body less the legend band when there is one). The flow keeps 24 px text; it is not scaled.
- **Placement:** the laid-out diagram is centred in the area (both axes); `FlowLayout` stores absolute canvas
  coordinates. ELK's results are deterministic: the same flow and tokens give the same layout.
- **Later stages:** `lint_deck` reads only a flow's step labels, tags and arrow labels as text (`mermaid`, ids,
  `actor`, `actors`, `source`, `target`, `emphasis`, `direction` and `layout` are not text). `lint_and_rewrite`,
  `fit_deck`, `fit_ladder` and `visual_qa` never change a flow slide's `visual`; a flow with a lint finding keeps the
  finding. A `too_big` flow keeps its `needs_review` from `layout_flows`.
- **Who calls it:** `build_house_deck` right after fill, before lint and fit; `arp report flow`. A caller that edits
  a laid-out flow sets `layout` to none so the next `layout_flows` lays it out again.

### Renderer (`backend/arp/reporting/visuals/flow.py`)

Registered as `VISUALS["flow"]`. A flow without a layout raises `VisualDataError("flow has no layout")`; slide fill
does not render flows (it has no dataset to check). Primitives, all from the layout (light mode colours shown; dark
mode uses the same keys of `graphite_dark`):

| Primitive | What | Style |
|---|---|---|
| `step:<id>` (Rect) | the step box | fill by actor (below); outline `ink` 2 px for `step`, `ink` 4 px for `decision`, `muted` 2 px for `data`; the emphasis step `highlight` 4 px with `emphasis` true |
| `step:<id>:label` (Text) | the label, lines joined by `\n` | 28 or 24 px, weight 600, body family, `ink`, centred, anchor middle, `fill_under` the step fill |
| `step:<id>:tag` (Text) | the tag, when set | mono 20 px, `ink`, centred, `fill_under` the step fill |
| `step:<id>:stored` (Rect) | stored marker | 8 px tall band across the bottom inside the box, fill `ink` |
| `arrow:<n>` (Line) | arrow n (1-based, in `arrows` order) along its route | `ink`, 2 px, `arrow` true |
| `arrow:<n>:label` (Text) | arrow label, when set | mono 20 px, `muted`, `fill_under` `panel` |
| `legend:<k>` (Rect), `legend:<k>:text` (Text) | actor k (1-based) | 24×24 swatch, actor fill, `ink` 2 px outline; text the actor name with `_` as spaces, upper-cased, mono 20 px `muted` |
| `legend:stored` (Rect), `legend:stored:text` (Text) | when any step is stored | 24×8 `ink` swatch; text `STORED RESULT` |

- **Actor fills**, by actor index: 1 `panel`, 2 `series_2`, 3 `well`, 4 `inverse_muted`. No actors: every step `panel`.
- **Legend:** one row, left-aligned at the body box's x, its 24 px swatches with their bottom on the body box's
  bottom edge; 12 px from swatch to text, 32 px from one item's text to the next swatch.
- `design_checks` reports no `underfill` for a flow slide (a short process is not an underfilled slide).
- The flow slide's PPTX notes end with `Mermaid source:\n` followed by the flow's `mermaid` text with trailing
  whitespace stripped, when `mermaid` is set.

### PowerPoint editability (`pptx_writer.py`)

- Each step is one group shape named `group:<id>` holding `step:<id>`, its label, tag and stored band, with child
  coordinates equal to slide coordinates (`chOff` = `off`, `chExt` = `ext`).
- `Line` gains two optional fields, `start` and `end` (primitive names). The flow renderer sets them to `step:<source>`
  and `step:<target>`; every other visual leaves them none, so their output is unchanged.
- In an LR flow, an arrow whose route has 2 points becomes a `straightConnector1` connector, and one whose route is
  horizontal, vertical, horizontal (4 points) a `bentConnector3` connector (`flipV` when it runs upwards; `adj1` puts
  the vertical segment at the route's x). Both are `p:cxnSp` named `arrow:<n>`, glued with `a:stCxn` to `step:<source>`
  and `a:endCxn` to `step:<target>`; `idx` is the side the route touches: 0 top, 1 left, 2 bottom, 3 right.
- Every other arrow (TB flows, routes with more bends) stays a freeform `arrow:<n>` with no glue.
- Arrow labels stay separate text boxes.

### `arp report flow`

`arp report flow FILE --out DIR [--headline TEXT] [--kicker TEXT] [--theme light|dark]`:

- Reads FILE as Mermaid, builds one content slide (headline default: FILE's stem; kicker default empty) with the
  house tokens, lays it out and writes `DIR/flow.pptx`, `DIR/flow.pdf` and `DIR/flow.png` (1920×1080).
- Needs no database, settings or model (skipped in `cli/__init__.py` like `report sheet`); needs Chromium.
- Exit 0 and prints `Wrote flow.pptx, flow.pdf, flow.png to <DIR>`, DIR exactly as given. DIR is created if missing,
  and only after a successful parse.
- A parse error: exit 1, nothing written, stderr is exactly the parser's message.
- Too big: exit 0, the files are written, stderr has one line `flow_too_big: <the finding's message>`.

### Model part

- `CONTENT_VISUALS` gains `flow`; `style/design.md` gains the line
  `- flow: a process or decision path of 2 to 12 steps, written as Mermaid flowchart text.`
- Slide fill for `flow` asks the model (`complete_structured`'s `output_model`) for a slide whose visual is a
  `FlowAnswer` (`type` "flow", `mermaid: str`), a model that does not parse, so a client's own validation retries
  never see a Mermaid error. Slide fill then validates the answer into `Flow` in `_check_visual`; a parse or limit
  error there goes into slide fill's one retry.
- The system prompt's schema is `FlowAnswer`'s (not `Flow`'s parsed fields or `layout`), plus a
  syntax guide that names `flowchart LR`, `flowchart TB`, `-->|label|`, `{Question?}`, `[(Data)]`, `<br>` for a tech
  tag, `classDef` / `:::` for actors, and the classes `stored` and `emphasis`, with the limits (12 steps, 4 actors,
  5-word labels, 3-word arrow labels).
- That error goes back once in the existing retry ("Your previous answer had these errors"), with the
  parser's message. A second failure gives the existing `points` fallback with a `bad_reference` finding whose
  message contains the parser's message.

### Superseded rows

Per D1, this spec supersedes these rows of `slide-components-design`. The test-writer retires their hidden tests
when it writes this spec's; `slide-components-design` itself is not edited (its PR 2 builder reads this list):

- AC-37 (`solve_swimlane` columns and routes), AC-38 (`lane:n` / `node:<id>` / `edge:n` shapes), AC-39 (swimlane over
  8 columns gets `needs_review`).
- AC-50: no longer expects `swimlane_flow` in the storyline prompt; `linear_flow`, `matrix_2x2` and `timeline` stay.

### Left to the builder

- The parser's internals (regex or tokenizer); the error table is the contract.
- How the page loads the vendored file (`add_script_tag` with its path or content).
- The PPTX XML for groups and connectors; python-pptx's `add_connector` and `begin_connect` may be used.
- `FlowLayout` field names beyond those named above.

## Fixtures

**F1** (6 steps, 2 actors, LR):

```
flowchart LR
  %% sample review flow
  q2["Q2 results<br>ESEF filings"]:::team
  screen["Screen debt"]:::team
  engage["Engage boards"]:::steward
  plan{"Plan credible?"}:::steward
  add["Add position"]:::team
  log[("Decision log")]:::steward
  q2 --> screen
  screen -->|over 5.5x| engage
  engage --> plan
  plan -->|yes| add
  plan -- no --> log
  classDef team fill:#fff
  classDef steward fill:#eee
  class log stored
  class plan emphasis
```

Parsed: steps `q2`, `screen`, `engage`, `plan` (decision), `add`, `log` (data, stored); actors `team`, `steward`;
arrows 1 q2→screen, 2 screen→engage "over 5.5x", 3 engage→plan, 4 plan→add "yes", 5 plan→log "no"; emphasis `plan`;
`q2` has label `Q2 results` and tag `ESEF filings`.

**F2** (10-step chain, LR): `flowchart LR` then `s1[Step 1] --> s2[Step 2]`, `s2 --> s3[Step 3]`, … `s9 --> s10[Step 10]`,
one arrow per line.

**F3** (4-step chain, TB): `flowchart TB`, `a[Collect filings] --> b[Extract figures]`, `b --> c[Check citations]`,
`c --> d[Store results]`.

**F4** (too big): `flowchart LR`, `hub[Hub]`, then `hub --> t1[One]` … `hub --> t11[Eleven]` (11 arrows, labels the
English number words One to Eleven).

The **F-deck** is `Deck(title="Flows", slides=[...])` with one content slide per fixture (headline `"Flow F<k>"`,
`visual=Flow(mermaid=<Fk>)`), house tokens, no template, light mode unless a row says otherwise; laid out with
`layout_flows` before rendering. Positions are in canvas px; PPTX at 9525 EMU/px. Colours on primitives are written as in `tokens.json` (`#rrggbb`);
in PPTX XML they are compared without `#`, case-insensitively. "Inside" allows ±1 px.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | F1 | `parse_mermaid` | `direction` `LR`; step ids in order `q2, screen, engage, plan, add, log`; kinds step, step, step, decision, step, data; `actors` `["team", "steward"]`; `log.stored` true; `emphasis` `plan`; `q2.label` `Q2 results`, `q2.tag` `ESEF filings` | holdout |
| AC-2 | F1 | `parse_mermaid` | 5 arrows in this order and with these labels: q2→screen "", screen→engage "over 5.5x", engage→plan "", plan→add "yes", plan→log "no" | holdout |
| AC-3 | `flowchart TD` + `a --> b --> c` | `parse_mermaid` | `direction` `TB`; steps a, b, c with labels `a`, `b`, `c`; arrows a→b, b→c | holdout |
| AC-4 | these texts (`\n` separates lines): `sequenceDiagram\n  a->>b: hi`; `hello\n  a --> b`; `flowchart RL\n  a --> b`; `---\ntitle: x\n---\nflowchart LR`; and `flowchart LR\n  a --> b\n` followed by each of these as line 3: `subgraph s`, `style a fill:#fff`, `linkStyle 0 stroke:#000`, `click a "https://x.y"`, `c((Round))`, `c>Flag]`, `c{{Hex}}`, `c[/Lean/]`, `c[\Lean\]`, `c[[Sub]]`, `c@{ shape: rect }`, `a --- c`, `a ==> c`, `a -.-> c`, `a <--> c`, `a --o c`, `a --x c`, `a ~~~ c`, `a & c --> d`, `a[Again]` after line 2 `a[First] --> b`, `c["One<br>Two<br>Three"]`, `?? what` | `parse_mermaid` | raises `MermaidError` whose `str()` is, in order: `line 1: only flowcharts are supported, not sequenceDiagram`; `line 1: start with "flowchart LR" or "flowchart TB"`; `line 1: direction RL is not supported; use LR or TB`; `line 1: front matter is not supported`; then for line 3: `subgraph is not supported`, `style is not supported`, `linkStyle is not supported`, `click links are not supported`, `shape (( is not supported; use [ ], { } or [( )]` and likewise `>`, `{{`, `[/`, `[\`, `[[`, `@{`, `arrow --- is not supported; use -->` and likewise `==>`, `-.->`, `<-->`, `--o`, `--x`, `~~~`, `& is not supported; write one arrow per pair`, `step a is defined twice`, `step c has more than one <br>; write the label, then one tech tag`, `cannot read "?? what"`, each prefixed `line 3: ` | holdout |
| AC-4b | `flowchart LR\n  a --> b\n  b[Later]` | `parse_mermaid` | step `b` has label `Later`; no error | holdout |
| AC-5 | each limit case (13 steps; 1 step; 5 actors; 21 arrows; a 6-word label; a 25-character tag; a 4-word arrow label; `a --> a`; `a --> b` twice; a step in 2 actors; a step without an actor next to steps with one; 2 emphasis steps; `class zz team` for an unknown `zz`) | `parse_mermaid` | raises `MermaidError` with exactly that case's message from the limits table | holdout |
| AC-6 | `{"type": "flow", "mermaid": F1}` | `SlideContent(headline="x", visual=...)` | validates; `visual.steps` has 6 steps and `visual.layout` is none | holdout |
| AC-7 | `{"type": "flow", "mermaid": "flowchart LR\n  a --> b\n  subgraph s"}` | `SlideContent.model_validate` | raises `ValidationError` whose text contains `line 3: subgraph is not supported` | holdout |
| AC-8 | a `Flow` built from fields (no `mermaid`) with an arrow to an unknown step id | `Flow.model_validate` | raises `ValidationError` | holdout |
| AC-9 | the repo | read `backend/arp/reporting/vendor/elkjs/` | `elk.bundled.js` has sha256 `b1032b7cfd2a57c54c6f0e8369d7665e19a579954f7cd20a6dae28f1912ea0d7`; `LICENSE.md` starts with `# Eclipse Public License - v 2.0`; `README.md` contains `0.12.1` and `EPL-2.0` | holdout |
| AC-10 | the F-deck | `layout_flows` | every flow has a layout; no `flow_too_big` finding for F1, F2, F3 | holdout |
| AC-11 | the F-deck | `layout_flows` twice on fresh copies | the two results' layouts are equal field by field | holdout |
| AC-12 | a deck with no flow slide, `ARP_CHROMIUM_PATH` pointing at a file that does not exist | `layout_flows` | returns a deck equal (`==`) to the input and `[]`, no exception | holdout |
| AC-13 | F1 laid out | read its layout | `type_step` 0; `wrapped` false; no two step boxes overlap; every step box lies inside the body box less the bottom 40 px | holdout |
| AC-14 | F1 laid out | read its layout | for each arrow, every segment is horizontal or vertical (±0.5 px); the first point lies on the source box's border and the last on the target box's border (±1 px); no segment crosses the inside of a step box | holdout |
| AC-15 | F1 laid out | read its layout | each step's left edge is right of the right edge of every step it has an arrow from | holdout |
| AC-16 | F1 laid out | read its layout | the union of all step, arrow and arrow-label boxes is centred in the body box less the bottom 40 px (±1 px on both axes) | holdout |
| AC-17 | F2 laid out | read its layout | `type_step` 0; `wrapped` true; step boxes sit at 2 or more distinct y positions; all inside the body box | holdout |
| AC-18 | F2 with `direction` changed to `TB` by its header (`flowchart TB`) | `layout_flows` | `wrapped` false and one `flow_too_big` finding (TB never wraps; 10 steps do not fit 592 px) | holdout |
| AC-19 | F3 laid out | read its layout | `type_step` 0; each step's top edge is below the bottom edge of the step before it | holdout |
| AC-20b | F4 with `class hub,t1,t2,t3,t4,t5,t6,t7,t8,t9,t10,t11 team` added | `layout_flows` | one `flow_too_big` finding whose message ends `the body has 1728×552 px; merge steps` | holdout |
| AC-20 | F4 in the F-deck | `layout_flows` | the slide has `needs_review` true; exactly one finding with `rule` `flow_too_big`, `stage` `fit`, message matching `^laid out \d+×\d+ px at 24 px text; the body has 1728×592 px; merge steps$`; `layout.too_big` true and `layout.type_step` 1 | holdout |
| AC-21 | the laid-out F-deck | `render_deck_html` in Chromium and `build_house_pptx` | for every primitive name on the flow slides, the HTML `[data-name]` box relative to its slide equals the PPTX shape box of that name (±1 px) | holdout |
| AC-22 | laid-out F1 | `render_slide` | `step:plan` (the emphasis, a decision) outline `#2a78d6` width 4 with `emphasis` true, and it is the only primitive with `emphasis` true; `step:log` outline `#4f5a6b` width 2; `step:q2` outline `#121722` width 2 | holdout |
| AC-23 | laid-out F1 | `render_slide` | fills: `step:q2`, `step:screen`, `step:add` `#ffffff`; `step:engage`, `step:plan`, `step:log` `#c4ccd7`; `step:log:stored` exists, fill `#121722`, height 8, its bottom on `step:log`'s bottom (±1) | holdout |
| AC-24 | laid-out F1 | `render_slide` | `legend:1:text` `TEAM`, `legend:2:text` `STEWARD`, `legend:stored:text` `STORED RESULT`; `legend:1` fill `#ffffff`, `legend:2` fill `#c4ccd7`; every legend swatch's bottom at y 920 (±1) | holdout |
| AC-25 | laid-out F1, light and dark | `render_slide` | every `step:<id>:label` has size 28, weight 600 and at most one `\n`; every `step:<id>:tag` and `arrow:<n>:label` has size 20 | holdout |
| AC-25b | the F-deck laid out in light, and again in dark | `design_checks` in that mode | no `small_text`, `low_contrast`, `underfill` or `emphasis_count` finding on the F1, F2 or F3 slide | holdout |
| AC-25c | F1 laid out in dark mode | `render_slide(..., mode="dark")` | every `fill`, `line` and `color` on the flow's primitives (names starting `step:`, `arrow:`, `legend:`) is a value of `graphite_dark` | holdout |
| AC-26 | a `Flow` with `layout` none | `render_slide` | raises `VisualDataError` with message `flow has no layout` | holdout |
| AC-27 | laid-out F1 | `build_house_pptx` | for each step id, a group shape `group:<id>` whose children are named `step:<id>`, `step:<id>:label` and (where present) `step:<id>:tag`, `step:<id>:stored` | holdout |
| AC-28 | laid-out F1 | `build_house_pptx` | each `arrow:<n>` whose layout route has 2 points is a `p:cxnSp` with preset `straightConnector1`, and each with 4 points (horizontal, vertical, horizontal) a `p:cxnSp` with preset `bentConnector3`; each has `a:tailEnd` | holdout |
| AC-29 | laid-out F1 | `build_house_pptx` | every `p:cxnSp` `arrow:<n>` has `a:stCxn` whose `id` is the shape id of `step:<source>` and `a:endCxn` whose `id` is the shape id of `step:<target>`; `stCxn idx` 3 and `endCxn idx` 1 | holdout |
| AC-30 | laid-out F3 (TB) | `build_house_pptx` | each `arrow:<n>` is a freeform `p:sp` (no `p:cxnSp` on the slide) | holdout |
| AC-31 | F1 saved as `f1.mmd`, no database settings in the environment | `arp report flow f1.mmd --out d` | exit 0; stdout `Wrote flow.pptx, flow.pdf, flow.png to d`; `d/flow.png` is 1920×1080; `d/flow.pptx` has 1 slide containing `group:q2` | holdout |
| AC-32 | `bad.mmd` = `flowchart LR\n  a --> b\n  subgraph s\n` | `arp report flow bad.mmd --out d` | exit 1; stderr exactly `line 3: subgraph is not supported\n`; `d` has no `flow.pptx`, `flow.pdf` or `flow.png` | holdout |
| AC-33 | F4 saved as a file | `arp report flow` | exit 0; the three files exist; stderr has one line starting `flow_too_big: laid out ` | holdout |
| AC-34a | `d/flow.png` from AC-31 | look at it at 100% | the two actor fills are different colours; every legend text is legible; no arrow line passes through an arrow label or a step label; `Plan credible?` has a blue 4 px outline and is the only blue-outlined step; the decision outline is thicker than the plain step outlines and the data step's outline is grey | evaluator |
| AC-34b | `d/flow.pptx` from AC-31, opened in LibreOffice Impress | move the group `group:screen` down by 5.29 cm (200 canvas px); if Impress does not keep connectors glued on import, record that and rely on AC-29 | arrows 1 and 2 still end and start on `screen`'s box edges | evaluator |
| AC-35 | laid-out F1 with `mermaid` set | `build_house_pptx` | the slide's notes text ends with `Mermaid source:\n` + F1 with trailing whitespace stripped | holdout |
| AC-36 | a request without `deck` settings and a recording stand-in LLM | draft the storyline | the prompt contains `flow` in the list of visuals and the line `- flow: a process or decision path of 2 to 12 steps, written as Mermaid flowchart text.` | holdout |
| AC-37 | a storyline slide with `visual="flow"` and a recording stand-in that returns `{"type": "flow", "mermaid": F1}` | `fill_slide` | one LLM call; its system prompt contains `flowchart LR`, `classDef` and `<br>`; the slide's visual is a `flow` with 6 steps and no findings | holdout |
| AC-38 | as AC-37, but the stand-in first returns `flowchart LR` / `a --> b` / `subgraph s` as `mermaid`, then F1 | `fill_slide` | two calls; the second prompt contains `line 3: subgraph is not supported`; the visual is a `flow` with 6 steps; no findings | holdout |
| AC-39 | as AC-38, but both answers have the subgraph | `fill_slide` | two calls; the visual is `points`; one finding `rule` `bad_reference` whose message contains `subgraph is not supported` | holdout |
| AC-40 | a storyline with one `flow` slide; a stand-in that returns `{"type": "flow", "mermaid": F1}` for the fill call and, for every other call, an answer that changes nothing (the same text back; an empty QA list) | `build_house_deck` | the saved deck's flow slide has a `layout`; its `visual.mermaid` equals F1 and its 6 step labels equal F1's; `output.pptx` contains `group:plan` | holdout |
| AC-40b | a deck whose only content slide is laid-out F1; a request with notes `"Review flow."` | `lint_deck` | no finding whose `slot` starts with `visual.mermaid`, `visual.layout`, `visual.actors`, `visual.emphasis` or `visual.direction`, or matches `visual.steps.<n>.id`, `visual.steps.<n>.actor`, `visual.arrows.<n>.source` or `visual.arrows.<n>.target` | holdout |
| AC-40c | as AC-40, but the stand-in answers every rewrite or shorten call with the text `REWRITTEN` | `build_house_deck` | the saved flow slide's step labels and arrow labels equal F1's (none is `REWRITTEN`) | holdout |
| AC-40d | as AC-40, with F4 instead of F1 | `build_house_deck` | the saved slide has `needs_review` true; the findings hold exactly one `flow_too_big` | holdout |
| AC-37b | as AC-37 | `fill_slide` | the system prompt contains none of `"layout"`, `"steps"`, `"arrows"`, `FlowLayout` | holdout |
| AC-41 | the sheet deck of `slide-components-design` (`arp/reporting/sheet.py`) | `build_house_pptx` | the PPTX has no `p:cxnSp` and no shape whose name starts with `group:` | holdout |
| AC-42 | `arp report sheet --out d` | run | exits 0 and writes 9 slide PNGs plus `sheet.png`, as on `main` before this change | holdout |
| AC-43 | the sheet deck | `build_house_pptx` | every shape's name, position, size and fill equal a snapshot the test-writer records from `main` `99267cb` and commits to holdout (±1 px) | holdout |
| AC-44 | `PATH` with no `node` binary | `layout_flows` on the F-deck | succeeds; `backend/pyproject.toml` lists no npm or Node package | holdout |
| AC-45 | the backend | build a wheel (`python -m build --wheel`) | the wheel contains `arp/reporting/vendor/elkjs/elk.bundled.js`, `LICENSE.md` and `README.md` | holdout |

Must not change: existing visuals' PPTX (AC-41, AC-42, AC-43); decks without a flow never launch an extra
Chromium for layout (AC-12).

## Slices

Each PR puts `Spec: house-deck-flowchart-slides` and its `Rows:` line in its description. Size S each, `risk:normal`.

| Slice | PR contents | Rows |
|---|---|---|
| 1 | `Flow` schema and validation; `mermaid_flow.parse_mermaid` with every error | AC-1, AC-2, AC-3, AC-4, AC-4b, AC-5, AC-6, AC-7, AC-8 |
| 2 | Vendored elkjs 0.12.1 with licence; `layout_flows` with measuring, the fit ladder and `flow_too_big` | AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-20b, AC-44, AC-45 |
| 3 | `visuals/flow.py` renderer, legend, both writers (freeform arrows), notes, no underfill for flows | AC-21, AC-22, AC-23, AC-24, AC-25, AC-25b, AC-25c, AC-26, AC-35, AC-41, AC-42, AC-43 |
| 4 | PPTX groups and glued connectors (`Line.start`/`end`); `arp report flow` | AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34a, AC-34b |
| 5 | Storyline and slide fill offer `flow`; syntax guide; retry then fallback; `layout_flows` in `build_house_deck`; later stages leave flows alone | AC-36, AC-37, AC-37b, AC-38, AC-39, AC-40, AC-40b, AC-40c, AC-40d |

Slices go in this order; each builds on the one before. Slice 3's AC-41 and AC-43 keep holding after slice 4 (groups and
connectors only appear on flow slides).

## Defaults decided without the owner

- `elkjs` 0.12.1 (released 28 Oct 2026, the newest patch more than two weeks old on the 0.12 line).
- Text sizes: labels 28 px, then 24 px; tags and arrow labels 20 px mono; legend 20 px mono.
- Label wrap at 320 px, two lines at most; box padding 24 px; minimum box width 160 px.
- Actor fills from the existing palette in the order panel, series_2, well, inverse_muted; decision = 4 px outline,
  data = `muted` outline, stored = 8 px `ink` band, emphasis = 4 px `highlight` outline.
- Mermaid `TD` read as `TB`; `graph` accepted like `flowchart`; style text inside `classDef` ignored.
- A node referenced only in an arrow becomes a step labelled with its id (Mermaid's own behaviour).
- A flow slide's Mermaid source goes into the PPTX notes.
- Flows are exempt from `underfill`.

## Watch

- PR #473 (refine chat) edits deck slides: a flow it edits must have `layout` set to none, so the next build lays it
  out again.
- The Vega-Lite spec (plan PR 6) changes chart drawing in `html_writer.py`; this spec touches `Line` in both writers.
  Whichever merges second merges `origin/main` first.
