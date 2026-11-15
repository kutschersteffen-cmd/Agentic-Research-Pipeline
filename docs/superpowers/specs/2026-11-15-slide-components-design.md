# Slide components: the foundation for client-ready house decks

## Why

House decks come out correct but not designed. The review on 15 Nov 2026
(https://claude.ai/artifact/S8usSGVTxZbFFitSyhC63d) traced this to the structure:

- slides are fixed text boxes filled from the top;
- nothing measures composition;
- every visual is coded twice, once for HTML/PDF and once for PowerPoint;
- charts use matplotlib defaults;
- layouts are chosen one slide at a time.

The owner reviewed an external slide-agent blueprint and chose to adopt its best ideas: typed slide
components, a fixed slide anatomy, component choice in the outline, data labels and units, and code
(not the AI) computing positions. The owner approved the mockups of 8 components on 15 Nov 2026 (the
review sheet in this spec reproduces them).

## What exists today

- **Build sequence:** storyline (headlines, approved by a person) → `fill_slide` picks one of 21
  `layouts.json` variants per slide and fills text slots → lint → fit (Chromium measures overflow) →
  visual QA → render, twice: `html_render.py` + Jinja templates for PDF/PNG, and `house_pptx.py` for the
  PPTX.
- **The legacy renderer has other users:** classic `pptx`/`pdf` reports (`deck_from_plan`), the
  stewardship client report, and stored house decks.
- **Grounding:** charts and tables reference datasets by id. Lint flags numbers not found in the
  sources.
- **Company template frames** override fonts and the headline, subheading and body boxes
  (spec `2026-11-14-template-frame-design.md`).

## Decisions taken with the owner

1. **Typed components** replace generic layout variants for house decks.
2. **Ideas adopted from the blueprint:**
   - typed components;
   - a fixed slide anatomy (label line, action title, subtitle, source line);
   - component choice and a rationale in the outline;
   - audience profiles that shape the deck's arc;
   - chart data labels and units;
   - positions computed by code.
3. **Blueprint ideas rejected:**
   - chart numbers written by the AI (ARP keeps dataset references);
   - character limits instead of measuring;
   - hard-coded safe areas;
   - LibreOffice previews;
   - separate Node/Gemini services;
   - status colours on slides.
4. **The look is the Graphite mockup set.** ▲/▼ deltas are drawn in ink, never green or red.

## Goals

1. Eight typed components that each lay out their own content: cover, section, KPI row, chart with
   insight card, step flow, comparison table, executive two-column, next steps.
2. One render model: each slide becomes a list of positioned primitives once, and both the HTML and
   the PPTX writers draw that list. PDF and PPTX match by construction.
3. Every content slide has the same anatomy in fixed zones, on one 8 px spacing scale.
4. The outline assigns a component to each slide, with a rationale, shaped by a deck profile.
5. Measured design checks (underfill, grid alignment, minimum text size, contrast, one emphasis) report
   findings the way overflow does today.
6. A review sheet renders every component from fixtures, guarded by a screenshot test.

## Non-goals

- Refining or undoing edits on one slide at a time (a follow-up spec).
- The shared app/deck token file (the parked deck-design-system spec; it is rebased onto this one
  later). This spec puts the Graphite values in the deck's own `tokens.json`.
- Flow diagrams, swimlanes, D2/Mermaid diagrams, images, quotes, 2×2 matrices, line or donut charts.
  Components for these can be added later on the same render model.
- Changing classic `pptx`/`pdf` reports, the stewardship client report, or how stored house decks
  render.
- Status or signal colours on slides.

## Anti-goals

- A number on a slide that is in no source (KPI values and chart data stay grounded).
- PDF and PPTX differing in any position, size or colour.
- Text that overflows its box or shrinks to fit without a finding.
- A slide whose body is mostly empty, without a finding.

## Approaches

| | How | Trade-off |
|---|---|---|
| **Typed components on a render model (picked)** | Components compute primitives; two thin writers draw them. | The largest change, but every later visual is built once. |
| Components drawn by both renderers | Each component written twice, in Jinja and in python-pptx. | Faster to start, but doubles all future work, which is the problem the review found. |
| Blueprint as is | A separate compiler service, Node orchestrator and Gemini. | Duplicates ARP's stack and loses its grounding and fit checks. |

## Design

### Canvas, zones and spacing

- **Canvas:** 1920×1080 px. Margins: 96 px left and right.
- **Spacing scale:** every gap, padding and offset a component produces is one of 8, 16, 24, 32, 40,
  48, 64 or 96 px.
- **Content-slide zones** (y ranges in px; all zones span x 96–1824):

| Zone | y | Content |
|---|---|---|
| Label line | 64–88 | Signature strip (five 12×12 px squares, 4 px gaps; the third square is `highlight`, the others `ink`), then 16 px gap, then the kicker in mono 20 px uppercase, `muted`. |
| Action title | 104–232 | The approved headline: 56 px, weight 600, at most 2 lines. |
| Subtitle | 248–288 | 28 px, `muted`, 1 line. The zone is empty when there is no subtitle; the body does not move up. |
| Body | 328–920 | The component. |
| Source line | 952–1000 | 1 px `line` rule on top; the source text in mono 18 px `muted` on the left, the page number on the right. |

- **Under a company template frame:**
  - the action title, subtitle and body zones become the frame's boxes;
  - the label line sits 16 px above the frame's title box;
  - the source line keeps its zone when the body box ends at or above y 928; otherwise it moves to the
    speaker notes, as in the template-frame spec.
- **Cover and section** are full-bleed and use no zones (see Components).

### Colours

Defined in `style/tokens.json`, light / dark:

| Token | Light | Dark |
|---|---|---|
| `ground` | `#f4f6f9` | `#0d1015` |
| `panel` | `#ffffff` | `#141921` |
| `line` | `#d8dee7` | `#2c3644` |
| `well` | `#eaeef3` | `#1b222d` |
| `ink` | `#121722` | `#e8ebf0` |
| `muted` | `#4f5a6b` | `#a3acbb` |
| `highlight` | `#2a78d6` | `#3987e5` |
| `inverse_muted` (text on an `ink` block) | `#aab4c3` | `#4f5a6b` |

- **Slide background:** `panel`. Section slides use `ground`.
- **Emphasis:** an `ink` block with `panel` text.
- **Highlighted data:** `highlight`.
- **Other chart bars:** `well`.

### Slide anatomy fields

`SlideContent` (house decks) gains:

- `kicker: str` — at most 3 words. The outline gives each section a kicker; slides inherit it.
- `subtitle: str = ""` — at most 16 words. It replaces the template-frame `subheading` field; that
  field keeps working as an alias.
- `component: Component` — a discriminated union of the eight models below, on `type`. It replaces
  `layout`, `variant` and `slots` for house decks built after this change.
- `source_line: str` — computed by code, never by the AI. It reads `Source: ` + the cited datasets'
  `name` (plus `, rows a–b` when a table or chart shows a slice), joined by `; `. Notes-based slides get
  `Source: ` + the note topics from `source_refs`. Slides with no references get an empty line.

### Components

Field limits are checked by the model. Numbers in `kpi_row`, `chart_insight.stat` and
`two_column.kpis` are linted by `number_not_in_source` like any slide text.

| `type` | Fields | Layout in the body zone |
|---|---|---|
| `cover` | `title` (≤10 words), `context` (≤8 words, e.g. audience · date), `answer` (≤30 words), `figures` (0–2 of `value` ≤8 chars + `label` ≤4 words) | Full-bleed. Left 760 px is an `ink` panel holding the strip, context, title (72 px) and the deck subtitle. Right side: "The answer in one line" label, `answer` (44 px), then the figures (96 px), vertically centred. |
| `section` | `number` (1–9), `title` (≤6 words), `summary` (≤14 words), `agenda` (all section titles of the deck) | Full-bleed `ground`. The number is 200 px outline type, then the title (72 px) and summary (32 px), vertically centred. The agenda is bottom-right, with the current section marked by a square. |
| `kpi_row` | `tiles` (2–4 of `value` ≤8 chars, `label` ≤5 words, `delta` ≤6 words), `emphasis` (tile index or none) | Equal tiles across the full body width with 24 px gaps, full body height. Label at the top, value at the bottom (144 px), delta under it. The emphasised tile is an `ink` block. Deltas start with ▲ or ▼ in the tile's text colour. |
| `chart_insight` | `chart` (`ChartSpec` dataset ref, `bar` or `column`, one value column; `unit` ≤6 chars; `data_labels` default true; `highlight` category or none), `insight` (`stat` ≤8 chars, `headline` ≤12 words, `points` 0–2 of ≤12 words) | Chart on the left, card 520 px wide on the right with a 48 px gap. Chart: label line `<value column>, <unit>` in mono; bars `well`, the highlighted one `highlight`; a value label at each bar end with the unit; no axis or grid. Card: `ground` with a 4 px `ink` left edge, stat (96 px), headline (30 px), points with square bullets. |
| `step_flow` | `steps` (3–5 of `title` ≤4 words, `text` ≤16 words, `tag` ≤4 words, `when` ≤6 chars), `emphasis` (step index or none; default the last) | Equal cards 440 px tall, vertically centred in the body, 24 px gaps, joined by 2 px `ink` connectors. Each card: number square plus `when` at the top, title (36 px), text (26 px), tag pill at the bottom. The emphasised card is an `ink` block. |
| `comparison_table` | `table` (`TableSpec` dataset ref, 2–6 columns, ≤8 rows), `highlight_column` (column name or none), `total_row` (per numeric column: `sum`, `mean` or `none`; computed by code) | Full body width, 28 px text. Text columns are left-aligned, number columns right-aligned in mono. Header: mono uppercase, 2 px `ink` rule. The highlighted column has an `ink` header and `ground` cells with weight 600. Total row: 2 px `ink` rule on top, weight 600. |
| `two_column` | `kpis` (0–3 of `value` + `label`), `left` and `right` (`title` ≤5 words, `points` 2–4 of ≤14 words) | KPI strip on top (`ground`, 1 px dividers), then two columns 64 px apart. Each column has a mono title over a 2 px `ink` rule, then numbered points (`01`, `02`) separated by 1 px rules. |
| `next_steps` | `actions` (2–5 of `text` ≤12 words, `owner` ≤3 words, `when` ≤10 chars), `emphasis` (index; default 0) | Rows vertically centred in the body, 16 px gaps. Each row: `ground` fill, number square, action text (30 px; weight 600 when emphasised), owner (mono label), `when` pill on the right. |

**Emphasis rule:** at most one emphasised item per slide. The emphasis index must exist in the
component; otherwise it is dropped and a `bad_reference` finding is logged.

### Render model

- `arp/reporting/render_model.py`: `render_slide(slide: SlideContent, index: int, deck: Deck, tokens:
  Tokens, datasets) -> list[Primitive]`.
- **Primitive types:** `Rect` (fill, line), `Text` (box, runs, size, weight, family, colour, alignment,
  anchor), `Line`, `ChartBars` (bars with values and colours, value labels) and `TableGrid`.
- **Each primitive** carries its x, y, w and h in canvas px and a `name` (e.g. `title`, `kpi:tile:2`,
  `card:insight`, `step:3`).
- **Two writers draw the same list:**
  - `html_writer.py` produces absolutely positioned elements with `data-name`;
  - `pptx_writer.py` produces native shapes named the same: charts as native bar charts styled to
    match, tables as native tables.
- **One measurement:** `browser.measure` checks text primitives for overflow. A component overflowing
  its zone gets a `fit` finding. Fit shortens text slots as today; there are no roomier variants or
  splits for components.
- **Unchanged paths:** stored house decks (no `component` on their slides), `deck_from_plan` and the
  stewardship client report keep using the legacy renderer.

### Outline and deck profile

- **`AudienceProfile` gains `deck_profile`:**
  - `executive` — answer first, KPI and decision slides, at most 8 content slides;
  - `client_pitch` — problem, cost of inaction, evidence, plan, next steps;
  - `committee` — context, analysis, options, decision, next steps (the default);
  - `workshop` — more step flows and tables.
- **`StorylineSlide` gains:**
  - `component` (one of the six content types);
  - `rationale` (≤20 words);
  - `kicker`;
  - `subtitle`.
- **The storyline call also plans:** the cover's `answer` and figures, and the sections. The deck is
  cover, then for each section a `section` slide and its content slides, with `next_steps` last. The
  owner approves the storyline with the components visible and can change any slide's component.
- **`fill_slide`** fills the component the storyline chose. A component that doesn't validate gets one
  retry with the errors, then a `bad_reference` finding and a `two_column` placeholder built from the
  headline.
- **`style/design.md`** (new) explains which claim fits which component and the emphasis rule. It is
  part of the storyline and fill prompts.

### Design checks

These run in the fit stage. Findings have stage `fit`.

| Rule | Finding when |
|---|---|
| `underfill` | The union of a content slide's body primitives covers less than 50% of the body zone's height. |
| `off_grid` | A primitive's x or y (relative to its zone) is not a multiple of 8 px. Text baselines are excluded. |
| `small_text` | Any text is under 18 px. |
| `low_contrast` | Text contrast against its fill is under 4.5:1 (3:1 for text 48 px or larger). |
| `emphasis_count` | More than one `ink` block on a content slide. |

### Review sheet

- `arp report sheet --out <dir>` renders the eight components from fixtures in
  `arp/reporting/fixtures/sheet.json` (the mockup content). It writes one PNG per component and
  `sheet.png` (a 2-column contact sheet).
- A test compares each PNG with a committed golden in `backend/tests/golden/slides/` and fails when
  more than 0.5% of pixels differ by more than 16/255.

### Left to the builder

- Module boundaries inside `render_model.py`.
- How PPTX native charts reproduce the bar styling (gap width, label font).
- The pixel-diff implementation.
- The `design.md` wording, within the rules above.

## Acceptance

The **sheet deck** is the eight fixtures in `arp/reporting/fixtures/sheet.json`, in order:

0. cover
1. section
2. kpi_row (4 tiles, emphasis 0)
3. chart_insight (eps data, highlight "Utilities", unit "%")
4. step_flow (4 steps, emphasis default)
5. comparison_table (`names` data, highlight_column "Net debt / EBITDA", total_row sum/mean)
6. two_column (3 KPIs)
7. next_steps (4 actions)

It is built in light mode without a template unless a row says otherwise. Positions are in canvas px;
PPTX is converted at 9525 EMU/px.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | the sheet deck | build HTML and PPTX | for every primitive name on every slide, the HTML element `[data-name]` box equals the PPTX shape box of the same name (±1 px) | holdout |
| AC-2 | the sheet deck | build PPTX | slides 2–7 each have shapes `strip:1`..`strip:5` at y 64 (±1), 12×12 px, x 96, 112, 128, 144, 160; `strip:3` fill `2a78d6`, the others `121722` | holdout |
| AC-3 | the sheet deck | build PPTX | on slides 2–7, `title` has its top at 104 and height 128; `source` text starts with `Source: ` and sits at y 952–1000 (±1 px) | holdout |
| AC-4 | slide 3 (chart_insight) | read `source` | equals `Source: EPS growth 2025, rows 1–6` | holdout |
| AC-5 | slide 2 (kpi_row, 4 tiles, emphasis 0) | build PPTX | tiles `kpi:tile:1`..`4` have equal width (±1 px), 24 px gaps, together span x 96–1824; tile 1 fill `121722`, others `f4f6f9`; tile 1 value runs `ffffff` | holdout |
| AC-6 | slide 3 | build PPTX | native bar chart with 6 points; the "Utilities" point fill `2a78d6`, the others `eaeef3`; data labels on, number format ends with `%`; card `card:insight` is 520 px wide with fill `f4f6f9` | holdout |
| AC-7 | slide 4 (step_flow, 4 steps) | build PPTX | cards `step:1`..`4` are each 440 px tall, vertically centred in 328–920 (±2 px), 24 px apart; `step:4` fill `121722`; 3 connectors `connector:1..3` | holdout |
| AC-8 | slide 5 (comparison_table) | build PPTX | native table with 5 body rows + 1 total row; the total row shows `6.5` for Weight % (sum) and `4.4` for EPS growth % (mean, 1 decimal); the "Net debt / EBITDA" header cell fill `121722` | holdout |
| AC-9 | a `kpi_row` tile value `9.9%` absent from all sources | lint the deck | one `number_not_in_source` finding for that slide | holdout |
| AC-10 | a `kpi_row` with `emphasis: 7` (4 tiles) | fill with a stand-in LLM | emphasis is None; one `bad_reference` finding; no tile is an `ink` block | holdout |
| AC-11 | a `two_column` slide with one point per column | run the design checks | one `underfill` finding for that slide | holdout |
| AC-12 | the sheet deck | run the design checks | no `underfill`, `off_grid`, `small_text`, `low_contrast` or `emphasis_count` finding | holdout |
| AC-13 | a component patched to place a primitive at x offset 12 | run the design checks | one `off_grid` finding naming that primitive | holdout |
| AC-14 | a `kpi_row` with two emphasised tiles (forced in a test) | run the design checks | one `emphasis_count` finding | holdout |
| AC-15 | the sheet deck in dark mode | build PPTX | slide background `141921` on slides 2–7; the emphasis block fill `e8ebf0` with value runs `141921` | holdout |
| AC-16 | a request with `deck_profile: committee` and a stand-in LLM | draft the storyline | the recorded prompt contains `committee` and the component list; every returned slide keeps its `component` and `rationale` | holdout |
| AC-17 | an approved storyline with 2 sections of 2 content slides | build the deck | the slide types are, in order: cover, section, content, content, section, content, content, next_steps | holdout |
| AC-18 | the sheet deck | `arp report sheet --out d` | exits 0; `d` holds `sheet.png` and 8 component PNGs of 1920×1080 | holdout |
| AC-19 | the committed goldens | run the sheet test after changing `ink` to `#000000` | the test fails | holdout |
| AC-20 | the sheet deck with the template-frame fixture | build PPTX (6350 EMU/px) | the `title` box equals the frame headline box and `strip:1` bottom is 16 px above it (±1 px) | holdout |
| AC-21 | the rendered sheet | look at every page | layout, spacing and emphasis match the approved mockups; nothing overlaps or is clipped | evaluator |

Must not change:

| ID | Given | When | Then | Checked by |
|----|-------|------|------|------------|
| AC-22 | a stored house deck whose slides have no `component` | re-render | output positions and fonts equal a build on `main` before this change (±1 px) | holdout |
| AC-23 | a classic `pptx` report and the stewardship client report | build | they still use the 21 layout variants (shape names `slot:*` present) | holdout |
| AC-24 | any built sheet deck slide, light and dark | build PPTX | no shape or run colour is `ea4c14`, `85601a`, `d4a650`, `13804f`, `c8323f`, `4fd69c`, `ff6b7a` or `2563c9` | holdout |
