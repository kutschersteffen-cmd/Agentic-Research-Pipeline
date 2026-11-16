# Deck design system: shared palette, shapes, visuals and design guidance

## Why

The example house decks read as plain. The owner named four problems, all of them: no identity, weak
emphasis (nothing tells the eye what matters), unbalanced empty space (short content sits top-left),
and basic visuals (charts and tables carry no highlight). Decks are presented in committees and client
meetings next to the ARP app, so they should look like the same product.

## What exists today

- The deck's look comes from `backend/arp/reporting/style/tokens.json` and `layouts.json`. It is
  rendered twice:
  - `html_render.py` + `style/templates/*.j2` for the PDF and PNG previews;
  - `house_pptx.py` for the editable PPTX.

  Both must place the same shapes in the same positions.
- **Deck colours today:** ink `#141414`, an orange accent `#ea4c14` that no slide shows, and four chart
  colours. The only shapes are the short ink rule above the headline (`accent_rule`), the timeline dots
  and the table rules.
- **The live app** (`frontend/src/index.css`) uses the "Graphite" palette:
  - text and accent `#121722`, ground `#f4f6f9`, panel `#ffffff`, border `#d8dee7`, well `#eaeef3`,
    muted `#4f5a6b`;
  - chart slots `#2a78d6 #c2407f #a87400 #6250d6`;
  - a dark-mode value for each.

  `frontend/tests/nightDeskTokens.test.ts` reads these literals out of `index.css`.
- **Reserved colours in the app:**
  - signal amber `--hi`/`--await-edge`: `#85601a` light, `#d4a650` dark;
  - brand orange `#ea4c14`, used only for the logo;
  - status: `--high` `#13804f`/`#4fd69c`, `--low` `#c8323f`/`#ff6b7a`, `--run` `#2563c9`, and `--mid`
    (an oklch amber).
- **`DESIGN.md` is out of date.** It still describes an older deep-blue palette and Source Serif titles.
- **Company template frames** (spec `2026-11-14-template-frame-design.md`) may replace fonts and the
  headline/subheading/body boxes. Everything in this spec applies inside that frame too.
- **Docker:** the backend image copies only `backend/`.

## Decisions taken with the owner

1. **Palette:** the live Graphite palette, for both app and deck.
2. **One shared token file** that app and deck both read (approach 2).
3. **Shapes:** a mix of the two mockups shown, direction A ("square blocks") and direction B ("soft
   cards").
   - From A: a five-square strip as the signature mark, a solid graphite block for the one key item,
     numbered squares for steps, and mono uppercase labels.
   - From B: full-width rows for lists, and a soft ground panel behind a row of big numbers.

## Goals

1. One file holds the colours (light and dark) that both the app and the deck use.
2. Every house slide carries the signature mark. At most one item per slide is emphasised: by default
   only on `big_number`, otherwise where the slide names one.
3. Short content fills the slide in a balanced way instead of sitting top-left.
4. Single-series bar and column charts can single out one category; tables can single out one row.
5. A written design guide tells the AI (and people) which layout and emphasis to use when.

## Non-goals

- Changing how the app looks. The app's computed colours stay exactly as they are today.
- Reserved colours on slides. Decks never use signal amber, brand orange or status colours.
- New layouts. Existing layouts and variants get the new shapes; none are added or removed.
- Icons, images or illustrations.
- Company templates. They keep overriding fonts and the three boxes only.
- Emphasis inside lists. List rows are uniform.

## Anti-goals

- PDF and PPTX disagreeing about any shape's position or colour.
- More than one emphasised item on a slide, or emphasis used as decoration.
- A token change that silently leaves the app or the deck on old values.
- Shapes overlapping each other or reaching outside the content area.

## Approaches

| | How | Trade-off |
|---|---|---|
| 1 | The deck keeps its own palette copied from the app, plus a test that the two copies match. | Two copies; the test catches drift. |
| **2 (picked)** | One shared token file. The app's CSS values and the deck's colours both come from it. | Couples app and deck. A generator keeps `index.css` literal, so existing app tests still read it. |
| 3 | Shapes in a PowerPoint master. | The PDF and previews would not show them. Ruled out. |

## Design

### Shared tokens

- **File:** `backend/arp/reporting/style/design_tokens.json`. It lives inside the backend package, so it
  ships in the backend image (the Dockerfiles copy only `backend/`). The frontend reads it only at
  generate time.
  - Shape: `{ "light": { "<name>": "#rrggbb", ... }, "dark": { ... } }`.
  - Names: `ground, panel, line, well, ink, muted, cat-1, cat-2, cat-3, cat-4`.
  - Values are today's `index.css` values for `--bg, --panel, --panel-border, --well, --text, --muted,
    --cat-1..4`: light from `:root`, dark from `:root[data-theme="dark"]`.
- **App:** `frontend/scripts/gen_tokens.mjs` (`npm run gen:tokens`) reads that file and rewrites the
  lines between `/* tokens:begin */` and `/* tokens:end */` marker pairs in `src/index.css`. It writes
  the shared values as literal hex.
  - Each of the three theme blocks may hold one or more marker pairs, placed around the existing lines.
    No lines move.
  - `index.css` keeps literal values, so `nightDeskTokens.test.ts` keeps working unchanged.
  - `--accent` and `--sidebar-bg` equal `ink` and `well` today but are app-only choices: they stay
    outside the shared tokens and are not generated.
  - A new frontend test, `index_css_matches_design_tokens`, fails when running the generator would
    change `index.css`.
- **Deck:** `house_style.load_tokens()` takes the deck colours from `design_tokens.json`:
  - `background = panel`, `ink = ink`, `ink_muted = muted`, `neutral = line`, and
    `categorical = cat-1..4`;
  - two new roles, `ground` and `well`;
  - `accent` becomes `ink`.

  The colour keys leave `style/tokens.json`; sizes, grid and type stay there. Tokens are still cached
  per process: `load_tokens.cache_clear()` reloads them.
- **DESIGN.md:** its colour section is rewritten to the Graphite values. It is reference text and no
  code reads it.

### Emphasis

- **`SlideContent.emphasis`** (`str | None = None`): the name of one slot to emphasise.
  - On `big_number` it may name `number_n`; that number and its `label_n` are emphasised together.
  - On `matrix` it may name one quadrant slot.
  - Any other value is invalid.
  - Defaults when `None`: `big_number` emphasises `number_1`; other layouts emphasise nothing.
- **Slide fill:** the prompt asks for at most one emphasis, on the item the headline is about. An invalid
  value never triggers a retry or a placeholder. The slide keeps its layout, variant and slots,
  `emphasis` becomes `None`, and one `bad_reference` finding (stage `data`) is returned by `fill_slide`
  for that slide.
- **`ChartSpec.highlight`** (`str | None = None`): one category value. It applies to bar and column
  charts with exactly one value column. That category's bar is drawn in `cat-1` and every other bar in
  `well`. On any other chart, or when the category is not in the data, it is ignored: colours stay as
  today and `build_house_deck`'s findings hold one `bad_reference` (stage `data`) for that slide.
  In the HTML SVG each bar's group has `id="bar-<category>"` (matplotlib `set_gid`), so a bar can be
  found by its category.
- **`TableSpec.highlight_row`** (`int | None = None`, 0-based index into the visible body rows, header
  excluded): that row's cells
  get a `well` fill, with bold runs in the PPTX and `font-weight` 600 in the HTML.

### Shapes

- Shapes are drawn identically in HTML and PPTX.
- **Naming:** in the PPTX a shape is named as in brackets below. In the HTML it is an element with
  `data-shape="<name>"`; the strip is five elements, each `data-shape="mark:strip"`.
- **No overflow:** every shape fills exactly the slot box (or union of slot boxes) it names. Padding goes
  inward: text inside a shape is inset by the padding given. So shapes never reach past their slots and
  never overlap neighbours.
- **Corners** are all square (radius 0), following the app's square-marker language.

| Element | Where | Spec |
|---|---|---|
| Signature strip `[mark:strip]` | Every slide; replaces `accent_rule`. | Five 12×12 px squares with 4 px gaps. Squares 1, 2, 4, 5 are `ink`; square 3 is `cat-1`. Bottom edge 24 px above the headline box top, left edge at the headline box's left. Without a frame: left 96 px, top 60 px, on every slide including title and section. With a frame: left = frame headline box x, bottom = frame headline box y − 24 (title and section slides too). |
| Key block `[emphasis:block]` | `big_number`: the emphasised `number_n` plus its `label_n`. `matrix`: the emphasised quadrant. | Solid `ink` fill over the union of those slot boxes. Text inset 40 px. Number, label and quadrant text inside use `panel`. |
| Soft panel `[panel:numbers]` | `big_number` | `ground` fill over the union of all number and label slot boxes on the slide; text inset 40 px. The key block is drawn on top. |
| Quadrant panels `[panel:<slot>]` | `matrix`, every quadrant except the emphasised one | `ground` fill over the slot box, text inset 36 px. Where two quadrant slot boxes touch, each panel (and the key block) stops 8 px short of the shared edge, so a 16 px gap shows. |
| List rows `[row:<n>]` | `bullets`, `summary` | One row per item, as wide as the list slot box. `ground` fill, 1 px `line` border, text inset 32 px vertical / 40 px horizontal, 24 px gap between rows. Row height = max(text height, 56) + 64. When the stack fills less than 70% of the slot box height, it is centred vertically in the slot box; otherwise it starts at the top. |
| Number squares `[step:<n>]` | `bullets` and `summary` rows (at the row's left, inside the inset); `timeline` (on the rule) | 56×56 px `ink` square with the 1-based index centred, mono 26 px, in `panel`. The timeline rule becomes 2 px `line`. |
| Labels | `big_number` labels, table headers | Mono, uppercase, 0.08em tracking. `muted`, or `panel` on a key block. The 1 px rule above each `big_number` label (`label_n:rule`) is removed; the soft panel replaces it. Matrix quadrants keep plain body text. |

**Superseded:** template-frame spec AC-22 ("an `accent_rule` shape exists") is superseded by AC-7 here.
Its hidden test is retired in the same change, and all its other clauses stand.

### Design guide

- New file `backend/arp/reporting/style/design.md`. `slide_fill.py` puts its full text into the
  slide-fill system prompt, after `writing.md`. Content, one line each:
  - pick the layout from the claim:
    - one number → `big_number/one`;
    - 2–3 numbers compared → `big_number`;
    - a ranking or trend → `chart_takeaway` with `highlight` on the subject;
    - a 2×2 trade-off → `matrix`;
    - ordered steps → `timeline`;
    - parallel points → `bullets`;
    - the closing slide → `summary`;
  - at most one emphasis per slide, on the thing the headline names; never emphasise for decoration;
  - highlight in a chart the category the headline names, and leave the rest neutral;
  - prefer fewer, larger items: three bullets over five when the points allow it;
  - colour carries meaning only:
    - graphite for emphasis;
    - `cat-1` for the highlighted category;
    - chart colours only inside charts.
- `DESIGN.md` gains a short "Decks" section pointing at `design_tokens.json` and `style/design.md`.

### Left to the builder

- How `load_tokens()` merges the shared colours. The JSON shapes above are fixed; the code is not.
- Marker comment placement in `index.css`, within the rules above.
- The wording of `design.md`, within the lines above.

## Acceptance

**Example deck** (`backend/tests/fixtures/deck_design_example.py`, function `example_deck()` returning
`(Deck, [datasets])`). Eight slides, 0-based: slide 0 is the title slide.

- **Datasets:**
  - `eps`: category column `sector` and one numeric column `growth_pct`. Rows: Tech 18, Financials 12,
    Market 11, Industrials 9, Energy 6, Utilities 4.
  - `names`: columns `Company, Weight %, EPS growth %, Net debt / EBITDA`. Five rows: Northgrid,
    Solvane Power, Eastwater, Kestrel Gas, Brightline.
- **Slides:**
  0. `title/key_figure`
  1. `big_number/three`, emphasis default
  2. `chart_takeaway/chart_left`: bar chart of `eps`, `highlight="Utilities"`
  3. `table/highlight` on `names`, `highlight_row=2`
  4. `bullets/three`, three one-line items
  5. `timeline/three`
  6. `matrix/default`, `emphasis="top_left"`
  7. `summary/default`, four items

Built without a template in light mode unless a row says otherwise. Positions are in px at 9525 EMU/px
unless a row says otherwise. Shape names are as in the Design section.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | the repo | read `backend/arp/reporting/style/design_tokens.json` | `light` has exactly the keys `ground, panel, line, well, ink, muted, cat-1, cat-2, cat-3, cat-4` with values `#f4f6f9, #ffffff, #d8dee7, #eaeef3, #121722, #4f5a6b, #2a78d6, #c2407f, #a87400, #6250d6`; `dark` has the same keys with `#0d1015, #141921, #2c3644, #1b222d, #e8ebf0, #a3acbb, #3987e5, #d55181, #c98500, #9085e9` | holdout |
| AC-2 | the repo | `cd frontend && npm run gen:tokens` | exits 0 and `git diff --exit-code frontend/src/index.css` exits 0 | holdout |
| AC-3 | `design_tokens.json` with `light.ink` changed to `#000000` | `npm run gen:tokens` | the `:root` block of `index.css` has `--text: #000000;`; no other line of `index.css` changes | holdout |
| AC-4 | `index.css` edited so `--cat-3` in `:root` differs from `design_tokens.json` | `cd frontend && npm test` | the test named `index_css_matches_design_tokens` fails | holdout |
| AC-5 | the repo | `load_tokens()` (light) | `color.background == "#ffffff"`, `color.ink == "#121722"`, `color.ink_muted == "#4f5a6b"`, `color.neutral == "#d8dee7"`, `color.categorical == ["#2a78d6","#c2407f","#a87400","#6250d6"]` | holdout |
| AC-6 | `design_tokens.json` with `light.cat-1` changed to `#111111`, then `load_tokens.cache_clear()` | build the example deck | in the PPTX chart on slide 2, the "Utilities" bar fill is `111111` | holdout |
| AC-7 | the example deck | build PPTX | every slide has five shapes named `mark:strip`, each 12×12 px, at left 96, 112, 128, 144, 160 and top 60 (±1 px); the third has fill `2a78d6`, the others `121722`; no slide has an `accent_rule` shape | holdout |
| AC-8 | the example deck | render HTML in Chromium | on every slide the five `[data-shape="mark:strip"]` elements have the same boxes (±1 px) as the PPTX `mark:strip` shapes | holdout |
| AC-9 | the example deck | slide 1 (big_number/three) | `panel:numbers` has fill `f4f6f9` and its box equals the union of the six number/label slot boxes (±1 px); `emphasis:block` has fill `121722` and its box equals the union of `slot:number_1` and `slot:label_1` (±1 px); `slot:number_1` and `slot:label_1` runs are colour `ffffff`; `slot:number_2` runs are `121722` | holdout |
| AC-10 | the example deck | slide 6 (matrix, emphasis top_left) | `panel:top_right`, `panel:bottom_left`, `panel:bottom_right` each have fill `f4f6f9`; `emphasis:block` has fill `121722`; each of the four has the box of its slot shortened 8 px on the edge it shares vertically with another quadrant (±1 px); there is no `panel:top_left`; no two of the four shapes overlap | holdout |
| AC-11 | the example deck | slide 4 (bullets/three) | shapes `row:1`, `row:2`, `row:3` have fill `f4f6f9`, a `d8dee7` line, the left and width of `slot:items` (±1 px), and a 24 px gap between consecutive rows (±1 px); shapes `step:1`..`step:3` are 56×56 px, fill `121722`, with text `1`, `2`, `3` | holdout |
| AC-12 | the example deck | slide 4 | the vertical centre of the `row:1`..`row:3` stack equals the vertical centre of `slot:items` (±2 px) | holdout |
| AC-13 | the example deck | slide 2 (chart, highlight "Utilities") | PPTX: the "Utilities" point fill is `2a78d6` and every other point fill is `eaeef3`. HTML: the shape inside `#bar-Utilities` has fill `#2a78d6` and those inside the other `bar-*` groups `#eaeef3` | holdout |
| AC-14 | the example deck | slide 3 (table, highlight_row 2) | PPTX: visible body row 2 (header excluded) has cell fill `eaeef3` and runs with bold on; other body rows have fill `ffffff` and bold off. HTML: that row's cells have computed `font-weight` ≥ 600, others 400 | holdout |
| AC-15 | a storyline slide; a stand-in LLM that returns a valid `bullets/three` fill with `emphasis="nope"` | `fill_slide` | the result keeps the stand-in's layout, variant and slots; `emphasis` is None; the stand-in was called once; the returned findings hold exactly one `bad_reference`, stage `data` | holdout |
| AC-16 | the example deck with slide 2's `highlight="Mars"`, built through `build_house_deck` with a stand-in LLM | build | the bars use the `cat-1..4` colours as without a highlight (none is `eaeef3`), and `build_house_deck`'s findings hold exactly one `bad_reference`, stage `data`, slide 2 | holdout |
| AC-17 | any request | `fill_slide` with a recording stand-in | the recorded system prompt contains the full text of `style/design.md` | holdout |
| AC-18 | the example deck in dark mode | build PPTX | slide background `141921`; `mark:strip` squares 1, 2, 4, 5 `e8ebf0` and square 3 `3987e5`; `emphasis:block` fill `e8ebf0` with `slot:number_1` runs `141921` | holdout |
| AC-19 | the example deck with the template-frame fixture (`tests/fixtures/frame_template.py`, frame headline box x 144, y 72) | build PPTX (6350 EMU/px) | on every slide the leftmost `mark:strip` square has left 144 px and the strip's bottom edge is at 48 px (±1 px) | holdout |
| AC-20 | the example deck | look at every rendered PDF page | each slide shows at most one dark emphasis block, list rows span the list area, the strip sits above every headline, and nothing overlaps or is clipped | evaluator |

Must not change:

| ID | Given | When | Then | Checked by |
|----|-------|------|------|------------|
| AC-21 | the app | `cd frontend && npm test` | `nightDeskTokens.test.ts` passes without edits to it | holdout |
| AC-22 | the example deck with the template-frame fixture | build PPTX (6350 EMU/px) | on slides 1–7, the `headline` and `subheading` boxes equal the frame boxes of template-frame AC-1 (±1 px) and their runs use the fonts of template-frame AC-9/AC-27; slide 0 matches template-frame AC-14 | holdout |
| AC-23 | the example deck, light and dark | build PPTX and HTML | no shape fill, line or run colour, and no HTML computed colour, is `ea4c14`, `85601a`, `d4a650`, `13804f`, `c8323f`, `4fd69c`, `ff6b7a` or `2563c9` | holdout |
