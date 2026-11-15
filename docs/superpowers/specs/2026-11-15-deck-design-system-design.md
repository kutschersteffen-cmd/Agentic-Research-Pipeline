# Deck design system: shared palette, shapes, visuals and design guidance

## Why

The example house decks read as plain. The owner named four problems, all of them: no identity, weak
emphasis (nothing tells the eye what matters), unbalanced empty space (short content sits top-left),
and basic visuals (charts and tables carry no highlight). Decks are presented in committees and client
meetings next to the ARP app, so they should look like the same product.

## What exists today

- The deck's look comes from `backend/arp/reporting/style/tokens.json` and `layouts.json`, rendered
  twice: `html_render.py` + `style/templates/*.j2` (PDF, PNG previews) and `house_pptx.py` (editable
  PPTX). Both must place the same shapes in the same positions.
- Deck colours today: ink `#141414`, an orange accent `#ea4c14` that no slide shows, and four chart
  colours. The only shapes are the short ink rule above the headline, the timeline dots and table rules.
- The live app (`frontend/src/index.css`) uses the "Graphite" palette: text and accent `#121722`,
  ground `#f4f6f9`, panel `#ffffff`, border `#d8dee7`, well `#eaeef3`, muted `#4f5a6b`, chart slots
  `#2a78d6 #c2407f #a87400 #6250d6`, each with a dark-mode value. `frontend/tests/nightDeskTokens.test.ts`
  reads these literals out of `index.css`.
- `DESIGN.md` still describes an older deep-blue palette and Source Serif titles. It is out of date.
- A company template frame (spec `2026-11-14-template-frame-design.md`) may replace fonts and the
  headline/subheading/body boxes. Everything in this spec applies inside that frame.

## Decisions taken with the owner

1. **Palette:** the live Graphite palette, for both app and deck.
2. **One shared token file** that app and deck both read (approach 2).
3. **Shapes:** a mix of the two mockups shown (direction A "square blocks" and B "soft cards"):
   - from A: a five-square strip as the signature mark, a solid graphite block for the one key item,
     numbered squares for steps, mono uppercase labels;
   - from B: full-width rows for lists, and a soft ground panel behind a row of big numbers.

## Goals

1. One file, `design/tokens.json`, holds the colours (light and dark) both the app and the deck use.
2. Every house slide carries the signature mark and gives one item visible emphasis.
3. Short content fills the slide in a balanced way instead of sitting top-left.
4. Charts and tables can single out one category or row.
5. A written design guide tells the AI (and people) which layout and emphasis to use when.

## Non-goals

- Changing how the app looks. The app's computed colours stay exactly as they are today.
- The app's signal colour (`#ea4c14`, "a person must act") and status colours on slides: decks never
  use them.
- New layouts. Existing layouts and variants get the new shapes; none are added or removed.
- Icons, images or illustrations.
- Company templates: they keep overriding fonts and the three boxes only.

## Anti-goals

- PDF and PPTX disagreeing about any shape's position or colour.
- More than one emphasised item on a slide, or emphasis used as decoration.
- A token change that silently leaves the app or the deck on old values.

## Approaches

| | How | Trade-off |
|---|---|---|
| 1 | Deck keeps its own palette copied from the app, plus a test that the copies match. | Two copies; the test catches drift. |
| **2 (picked)** | One shared `design/tokens.json`; the app's CSS values and the deck's colours both come from it. | Couples app and deck; a generator keeps `index.css` literal so existing app tests still read it. |
| 3 | Shapes in a PowerPoint master. | PDF and previews would not show them. Ruled out. |

## Design

### Shared tokens

- **File:** `design/tokens.json` at the repo root:
  `{ "light": { "<name>": "#rrggbb", ... }, "dark": { ... } }`.
  Names: `ground, panel, line, well, ink, muted, cat-1, cat-2, cat-3, cat-4`. Values are today's
  `index.css` values for `--bg, --panel, --panel-border, --well, --text, --muted, --cat-1..4` (light
  from `:root`, dark from `:root[data-theme="dark"]`).
- **App:** `frontend/scripts/gen_tokens.mjs` (`npm run gen:tokens`) rewrites the lines between
  `/* tokens:begin */` and `/* tokens:end */` markers inside each of the three theme blocks of
  `src/index.css` with the shared values, as literal hex. `index.css` keeps literal values, so
  `nightDeskTokens.test.ts` keeps working unchanged. A frontend test fails when running the generator
  would change `index.css`.
- **Deck:** `house_style.load_tokens()` takes the deck colours from `design/tokens.json`:
  `background = panel`, `ink = ink`, `ink_muted = muted`, `neutral = line`, `categorical = cat-1..4`,
  plus two new roles, `ground` and `well`. `accent` becomes `ink` (graphite). The colour keys leave
  `style/tokens.json`; sizes, grid and type stay there.
- **DESIGN.md** gets its colour section rewritten to the Graphite values. It is reference text, not read
  by code.

### Emphasis

- `SlideContent` gains `emphasis: str | None = None`: the name of one slot on the slide to emphasise.
  It must be a slot of the slide's variant, or `None`.
- Defaults when `None`: `big_number` emphasises `number_1`; every other layout emphasises nothing.
- The slide-fill prompt asks for at most one emphasis, chosen as the item the headline is about. A value
  that names no slot of the variant is dropped (set to `None`) and logged as a `bad_reference` finding,
  like other bad references today.
- `ChartSpec` gains `highlight: str | None = None`: one category value. When set, that category's bars,
  columns or points are drawn in `cat-1` and all others in `well`; a highlighted category that is not
  in the data is ignored and gives a `bad_reference` finding.
- `TableSpec` gains `highlight_row: int | None = None` (0-based within the visible rows): that row gets
  a `well` fill and semibold text.

### Shapes (drawn identically in HTML and PPTX; shape names in brackets)

All corners are square (radius 0), following the app's square-marker language.

| Element | Where | Spec |
|---|---|---|
| Signature strip `[mark:strip]` | every slide, above the headline, replacing the current accent rule | five 12×12 px squares, 4 px gaps, left edge at `margin_x`, bottom edge 24 px above the headline box top. Squares 1, 2, 4, 5 `ink`; square 3 `cat-1`. Under a template frame: 24 px above the frame's headline box. |
| Key block `[emphasis:block]` | `big_number` emphasised number; `matrix` emphasised quadrant | solid `ink` fill behind the slot box with 40 px inner padding; text inside turns `panel` (white); its label turns `#c9d2de` light / `muted` dark. |
| Soft panel `[panel:numbers]` | `big_number` | `ground` fill spanning the row of numbers + labels, 40 px padding around them. The key block sits on top of it. |
| Quadrant panels `[panel:<slot>]` | `matrix` | each quadrant filled `ground`, 36 px padding; the emphasised one is the key block instead. |
| List rows `[row:<n>]` | `bullets`, `summary` | each item a full-width row: `ground` fill, 1 px `line` border, 32 px vertical / 40 px horizontal padding, 24 px gap between rows. Rows stack from the top of the body area; the stack is vertically centred in the body area when it fills less than 60% of it. |
| Number squares `[step:<n>]` | `bullets` rows, `timeline`, `summary` | 56×56 px `ink` square at the left of a row (or on the timeline rule), the 1-based index centred in mono 26 px `panel` colour. Timeline keeps its rule, now 2 px `line`. |
| Labels | `big_number` labels, matrix quadrant titles, table headers | mono, uppercase, 0.08em tracking, `muted` (already true for table headers). |

The emphasised list item (if `emphasis` names a list slot and the slide has one list) is not supported:
a list slot as emphasis is treated as no emphasis. Rows are uniform.

### Design guide

- New file `backend/arp/reporting/style/design.md`, read by `slide_fill.py` together with
  `writing.md`, so the fill prompt includes it. Content (one line each):
  - pick the layout from the claim: one number → `big_number/one`; a comparison of 2–3 numbers →
    `big_number`; a ranking or trend → `chart_takeaway` with `highlight` on the subject; a 2×2 trade-off →
    `matrix`; ordered steps → `timeline`; parallel points → `bullets`; the closing slide → `summary`;
  - at most one emphasis per slide, on the thing the headline names; never emphasise for decoration;
  - highlight in a chart the category the headline names; leave the rest neutral;
  - prefer fewer, larger items: three bullets over five when the points allow it;
  - colour carries meaning only: graphite for emphasis, `cat-1` for the highlighted series, chart
    colours only inside charts.
- `DESIGN.md` gains a short "Decks" section pointing at `design/tokens.json` and `style/design.md`.

### Left to the builder

- How `load_tokens()` merges the shared colours (the JSON shapes above are fixed; the code is not).
- The exact marker comment placement in `index.css`, within the three theme blocks.
- Wording of `design.md` within the lines above.

## Acceptance

Example deck used by several rows ("the example deck"): the eight slides of the utilities example
(title/key_figure, big_number/three, chart_takeaway/chart_left with `highlight="Utilities"`,
table/highlight with `highlight_row=2`, bullets/three, timeline/three, matrix/default with
`emphasis="top_left"`, summary/default), built without a template in light mode. PPTX positions are px
at 9525 EMU/px.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | the repo | read `design/tokens.json` | `light` has exactly the keys `ground, panel, line, well, ink, muted, cat-1, cat-2, cat-3, cat-4` with values `#f4f6f9, #ffffff, #d8dee7, #eaeef3, #121722, #4f5a6b, #2a78d6, #c2407f, #a87400, #6250d6`; `dark` has the same keys with `#0d1015, #141921, #2c3644, #1b222d, #e8ebf0, #a3acbb, #3987e5, #d55181, #c98500, #9085e9` | holdout |
| AC-2 | the repo | `cd frontend && npm run gen:tokens` | exits 0 and `git diff --exit-code frontend/src/index.css` exits 0 | holdout |
| AC-3 | `design/tokens.json` with `light.ink` changed to `#000000` | `npm run gen:tokens` | the `:root` block of `index.css` has `--text: #000000;`; no other line of `index.css` changes | holdout |
| AC-4 | `index.css` edited so `--well` in `:root` differs from `design/tokens.json` | `cd frontend && npm test` | the run fails, and the failing test's name contains `tokens` | holdout |
| AC-5 | the repo | `load_tokens()` (light) | `color.background == "#ffffff"`, `color.ink == "#121722"`, `color.ink_muted == "#4f5a6b"`, `color.neutral == "#d8dee7"`, `color.categorical == ["#2a78d6","#c2407f","#a87400","#6250d6"]` | holdout |
| AC-6 | `design/tokens.json` with `light.cat-1` changed to `#111111` | build the example deck | the PPTX chart on slide 2 fills the highlighted bar `111111` | holdout |
| AC-7 | the example deck | build PPTX | every slide has a group or five shapes named `mark:strip` (5 squares 12×12 px, 4 px gaps); square 3 fill `2a78d6`, the others `121722`; the strip's left edge is 96 px; there is no `accent_rule` shape | holdout |
| AC-8 | the example deck | render HTML in Chromium | on every slide the strip's five squares are at the same boxes (±1 px) as the PPTX `mark:strip` squares | holdout |
| AC-9 | the example deck | slide 1 (big_number/three) | a `panel:numbers` shape with fill `f4f6f9` encloses all six number/label slots; an `emphasis:block` shape with fill `121722` encloses `slot:number_1`; `slot:number_1` runs are colour `ffffff`; `slot:number_2` runs are `121722` | holdout |
| AC-10 | the example deck | slide 6 (matrix, emphasis top_left) | shapes `panel:top_right`, `panel:bottom_left`, `panel:bottom_right` with fill `f4f6f9`; `emphasis:block` with fill `121722` encloses `slot:top_left`; there is no `panel:top_left` | holdout |
| AC-11 | the example deck | slide 4 (bullets/three) | shapes `row:1..3`, each fill `f4f6f9`, border `d8dee7`, full body width (±1 px), 24 px apart (±1); shapes `step:1..3`, each 56×56 px fill `121722` with text `1`,`2`,`3` | holdout |
| AC-12 | bullets/three with three one-line items | build | the vertical centre of the row stack is the vertical centre of the body area (±2 px) | holdout |
| AC-13 | the example deck | slide 2 (chart, highlight "Utilities") | in the PPTX chart, the "Utilities" point fill is `2a78d6` and every other point fill is `eaeef3`; in the HTML SVG, the "Utilities" bar fill is `#2a78d6` and the others `#eaeef3` | holdout |
| AC-14 | the example deck | slide 3 (table, highlight_row 2) | visible row index 2 has cell fill `eaeef3` and bold runs; other body rows have fill `ffffff` and non-bold runs | holdout |
| AC-15 | a slide with `emphasis="nope"` (not a slot of its variant) | fill the slide with a stand-in LLM returning it | the built slide has `emphasis` = None, and findings contain one `bad_reference` for that slide | holdout |
| AC-16 | a chart with `highlight="Mars"` not in the data | build | all bars are drawn in `cat-1..4` as today (no `well` fill) and findings contain one `bad_reference` for that slide | holdout |
| AC-17 | any request | the slide-fill system prompt | contains the full text of `style/design.md` | holdout |
| AC-18 | the example deck in dark mode | build PPTX | slide background `141921`, `mark:strip` squares 1,2,4,5 `e8ebf0` and square 3 `3987e5`, `emphasis:block` fill `e8ebf0` with number runs `141921` | holdout |
| AC-19 | the example deck with the template frame fixture from the template-frame spec | build | `mark:strip` bottom edge is 24 px above the frame headline box top (±1 px), left edge at the headline box's left (±1 px) | holdout |
| AC-20 | the example deck | open the rendered PDF pages | each slide shows exactly one dark emphasis item at most, list rows span the width, the strip sits above every headline, nothing overlaps or is clipped | evaluator |

Must not change:

| ID | Given | When | Then | Checked by |
|----|-------|------|------|------------|
| AC-21 | the app | `cd frontend && npm test` | `nightDeskTokens.test.ts` passes without edits | holdout |
| AC-22 | a template profile, the frame fixture | build the example deck | headline/subheading/body boxes and fonts equal those in template-frame AC-8/AC-9 (±1 px) | holdout |
| AC-23 | any slide | build | no shape or run uses `ea4c14`, `13804f`, `c8323f` (signal and status colours) | holdout |
