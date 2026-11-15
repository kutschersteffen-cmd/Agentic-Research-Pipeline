# Slide components: client-ready house decks from typed visuals

## Why

House decks come out correct but not designed. The review on 15 Nov 2026
(https://claude.ai/artifact/S8usSGVTxZbFFitSyhC63d) traced this to the structure:

- slides are fixed text boxes filled from the top;
- nothing measures composition;
- every visual is coded twice, once for HTML/PDF and once for PowerPoint;
- charts use matplotlib defaults;
- layouts are chosen one slide at a time;
- the person building a deck can only approve headlines, not shape the deck.

The owner reviewed an external slide-agent blueprint and chose to adopt its relevant ideas, to make the
presentation function meaningful and user-focused:

- **typed visual calls:** the AI fills a JSON schema per visual and code computes every position;
- **a fixed slide anatomy** with a source line;
- **deck settings** (audience, purpose, detail, slide count) that shape the deck's arc;
- **an outline review** showing each slide's visual and the reason for it;
- **single-slide refinement** by instruction, with undo;
- **chart data labels and units;**
- **a deterministic layout solver** for flows.

The owner approved mockups on 15 Nov 2026, committed in `docs/superpowers/specs/assets/slide-components/`:

- `0-cover` … `7-next_steps`: the first eight visuals;
- `8-line` … `13-doughnut`: the added visuals;
- `ui-outline`, `ui-refine`: the two new screens.

## What exists today

- **Build sequence:** storyline (headlines, approved by a person) → `fill_slide` picks one of 21
  `layouts.json` variants per slide and fills text slots → lint → fit (Chromium measures overflow) →
  visual QA → render, twice: `html_render.py` + Jinja templates for PDF/PNG, and `house_pptx.py` for the
  PPTX.
- **Charts:**
  - 11 `ChartType`s are drawn by matplotlib for the PDF.
  - In the PPTX, 8 are native charts (bar, column, stacked column, line, area, pie, doughnut, radar);
    the others are pictures.
  - There are no flow diagrams. The "timeline" is a numbered list.
- **Data:** uploaded CSV/Excel (`/api/reports/datasets/upload`) and ARP run results (`run_refs`). Charts
  and tables reference datasets by id. Lint flags numbers not found in the sources.
- **Colours:** `style/tokens.json` holds the legacy palette (`ink #141414`, `accent #ea4c14`, …).
- **The legacy renderer has other users:** classic `pptx`/`pdf` reports (`deck_from_plan`), the
  stewardship client report, and stored house decks.
- **Company template frames** (spec `2026-11-14-template-frame-design.md`) override fonts and the
  headline, subheading and body boxes.

## Decisions taken with the owner

1. **The full visual-call set below**, with the fit ladder, in three PRs.
2. **Blueprint ideas adopted:** those listed under Why.
3. **Blueprint ideas rejected:**
   - chart numbers typed by the AI (ARP keeps dataset references);
   - character limits instead of measuring;
   - hard-coded safe areas;
   - LibreOffice previews;
   - separate Node/Gemini services;
   - `elkjs` (a Python solver instead);
   - D2/Mermaid pictures;
   - PowerPoint elbow connectors that ignore the solved route;
   - status colours on slides.
4. **The look is the approved mockups.** ▲/▼ deltas are drawn in the text colour, never green or red.
5. **Pickers show friendly names** ("KPI row", "Chart + insight"), never internal type names.

## Goals

1. Thirteen typed visuals that each lay out their own content. All data comes from datasets; text
   numbers are checked against sources.
2. One render model: each slide becomes a list of positioned primitives once, and both writers draw it.
   PDF and PPTX match by construction, and PPTX shapes and charts stay editable.
3. A fixed slide anatomy in fixed zones on one spacing scale.
4. Content that doesn't fit is fixed by a fixed ladder of steps, and never reaches export silently.
5. Deck settings and an outline review let the user shape the deck before slides are built.
6. Any one slide can be refined by instruction, with history and undo.
7. Measured design checks and a screenshot-guarded review sheet keep the look from regressing.

## Non-goals

- The shared app/deck token file (the parked deck-design-system spec, to be rebased onto this one).
- Pie, area, scatter, radar and heatmap charts in the new visuals. They stay available to classic
  reports only.
- Org charts, D2/Mermaid diagrams, images and quotes.
- Changing classic `pptx`/`pdf` reports, the stewardship client report, or how stored house decks
  render.
- Status or signal colours on slides.
- Snapping every absolute position to an 8 px grid (equal division and centring produce off-grid
  positions).

## Anti-goals

- A number on a slide that is in no source.
- PDF and PPTX differing in any position, size or colour.
- Text that overflows or shrinks, reaching an export with no finding and no review.
- A refinement that silently changes numbers or sources.

## Approaches

| | How | Trade-off |
|---|---|---|
| **Typed visuals on a render model (picked)** | Visual calls compute primitives; two thin writers draw them. | The largest change, but every visual is built once. |
| Visuals drawn by both renderers | Each visual written twice. | Doubles all future work. |
| Blueprint as is | A separate compiler service, Node orchestrator and Gemini. | Duplicates ARP's stack and loses its grounding and fit checks. |

## Design

### Canvas, zones and spacing

- **Canvas:** 1920×1080 px. Margins: 96 px left and right.
- **Spacing scale:** every gap and padding is one of 4, 8, 12, 16, 24, 32, 40, 48, 64 or 96 px, named as
  constants in `render_model.py`. Widths and offsets from dividing or centring are computed.
- **Content-slide zones** (y in px; all zones span x 96–1824):

| Zone | y | Content |
|---|---|---|
| Label line | 64–88 | Signature strip (five 12×12 px squares, 4 px gaps; the third square is `highlight`, the others `ink`), a 16 px gap, then the kicker in mono 20 px uppercase, `muted`. |
| Action title | 104–232 | The approved headline: 56 px, weight 600, at most 2 lines. |
| Subtitle | 248–288 | 28 px, `muted`, 1 line. Empty when there is none. |
| Body | 328–920 | The visual. |
| Source line | 952–1000 | 1 px `line` rule at 952; source text in mono 18 px `muted` on the left; page number on the right. |

- **Under a company template frame:**
  - title, subtitle and body take the frame's headline, subheading and body boxes;
  - the strip's top sits 40 px above the frame's headline box top, at its left edge;
  - the source line keeps its zone when the frame's body box ends at or above y 928. Otherwise
    `source_line` is appended to the speaker notes, after a newline unless the notes are empty.
  - Visuals size from the actual body box (see the fit ladder).
- **Cover and section** are full-bleed and use no zones.

### Colours

New keys `graphite` and `graphite_dark` in `style/tokens.json`. The legacy colour keys are unchanged.

| Token | `graphite` | `graphite_dark` |
|---|---|---|
| `ground` | `#f4f6f9` | `#0d1015` |
| `panel` | `#ffffff` | `#141921` |
| `line` | `#d8dee7` | `#2c3644` |
| `well` | `#eaeef3` | `#1b222d` |
| `ink` | `#121722` | `#e8ebf0` |
| `muted` | `#4f5a6b` | `#a3acbb` |
| `highlight` | `#2a78d6` | `#3987e5` |
| `series_2` | `#c4ccd7` | `#4a5566` |
| `inverse_muted` | `#aab4c3` | `#4f5a6b` |

- **Backgrounds:** slides use `panel`; section slides use `ground`.
- **Emphasis block:** `ink` fill, `panel` text, `inverse_muted` secondary text.
- **Non-emphasised tiles, cards and rows:** `ground`.
- **Data colours:**
  - `highlight` marks the data the headline is about;
  - `series_2` is the comparison series or the other segments;
  - `well` is the rest.
- **Highlight is a fill only.** Text is never set in it or on it.

### Slide fields

`SlideContent` gains these fields, all with defaults so stored decks still validate:

- `kicker: str = ""`
- `subtitle: str = ""` (≤16 words; the template-frame `subheading` is read as an alias)
- `visual: Visual | None = None` (a discriminated union on `type`)
- `source_line: str = ""`
- `needs_review: bool = False`

`layout` and `variant` become optional. A slide with a `visual` goes through the render model; one
without goes through the legacy renderer.

**`source_line`** is computed by code. It reads `Source: ` followed by the cited items, joined by `; `:

- a dataset's `name`;
- `, rows a–b` (1-based) when a table shows only part of its dataset;
- note topics from `source_refs`.

A slide with no references gets `""`.

### Visual calls

- **Emphasis:**
  - At most one emphasis per slide.
  - An `emphasis` index outside the visual's range is dropped, with one `bad_reference` finding (stage
    `data`). It is not a validation error.
  - Every primitive carries `emphasis: bool`, true only for emphasis blocks: an emphasised tile, step
    card, timeline event marker, matrix quadrant or lane node, and the cover's left panel.
- **Grounding:** numbers in `kpi_row`, `two_column.kpis`, insight `stat`s, chart callouts and the cover's
  figures are linted by `number_not_in_source`.
- **Chart data** comes only from a dataset reference.

| `type` | Friendly name | Fields (limits enforced by pydantic) | Layout |
|---|---|---|---|
| `cover` | Cover | `title` ≤10 words, `context` ≤8, `answer` ≤30, `figures` 0–2 (`value` ≤8 chars, `label` ≤4 words) | Mockup `0-cover`: left 760 px `ink` panel; answer and figures on the right, vertically centred |
| `section` | Section divider | `number`, `title` ≤6 words, `summary` ≤14 words; `agenda` filled by code | Mockup `1-section`: full-bleed `ground`; outline number with a 2 px `line` stroke (decorative, skipped by `low_contrast`); agenda bottom-right |
| `kpi_row` | KPI row | `tiles` 2–4 (`value` ≤8 chars, `label` ≤5 words, `delta` ≤6 words), `emphasis` | Equal tiles, 24 px gaps, full body; label top, value 144 px and delta bottom, 40 px padding |
| `chart` | Chart (+ insight) | `data` (`ChartSpec`: dataset, category, 1–3 value columns), `kind` (`bar`, `column`, `stacked_column`, `line`, `waterfall`, `doughnut`), `unit` ≤6 chars, `data_labels` (default true), `highlight` (category or series), `callout` (≤8 words on one category, or none), `insight` (`stat` ≤8 chars, `headline` ≤12 words, `points` 0–2) or none | With `insight`: chart left, 520 px card right, 48 px gap (mockup `3`/`13`). Without: full body width (mockups `8`, `9`). No axes or grid lines except the category labels. Value labels in `ink` beside bars, line ends and segments. Line: series labels at the line ends. Waterfall: first and last bars `ink`, the highlighted step `highlight`, others `series_2`, steps computed from the dataset rows in order. Doughnut: ≤5 segments, centre shows the highlighted share. |
| `linear_flow` | Step flow | `steps` 3–5 (`title` ≤4 words, `text` ≤16, `tag` ≤4, `when` ≤6 chars), `emphasis` (default last) | Mockup `4`: equal cards 440 px tall, centred, 24 px gaps, 2 px `ink` connectors |
| `swimlane_flow` | Process with owners | `lanes` 2–4 (≤20 chars), `nodes` 3–12 (`id`, `lane`, `shape` start/process/decision, `label` ≤32 chars), `edges` 2–16 (`from`, `to`, `label` ≤12 chars or none), `emphasis` (node id) | Mockup `10`: lane bands alternating `ground`/`panel` with mono lane labels in the left 240 px. Node geometry and right-angle routes come from the solver. Nodes: pill, box or diamond, 2 px `ink` outline; decisions filled `ink`. |
| `comparison_table` | Comparison table | `table` (`TableSpec`, 2–6 columns, ≤8 rows), `highlight_column`, `total_row` (per numeric column: `sum` keeps the decimals, `mean` gets one more, or `none`) | Mockup `5`: text columns left-aligned, numbers right-aligned in mono, highlighted column `ink` header with `ground` cells at 600, total row with a 2 px `ink` rule |
| `matrix_2x2` | 2×2 matrix | `x_axis`, `y_axis` (≤5 words), `quadrants` 4 (`title` ≤5 words, `items` ≤6 words, `note` ≤8 words), `emphasis` | Mockup `11`: four quadrants, 16 px gaps, axis labels on the left and bottom |
| `timeline` | Timeline | `events` 3–6 (`date` ≤10 chars, `title` ≤4 words, `text` ≤8), `today` (index or none), `emphasis` | Mockup `12`: horizontal rule with square markers, labels alternating above and below, elapsed part 4 px `ink`, "Today" pill |
| `two_column` | Two columns | `kpis` 0–3, `left` and `right` (`title` ≤5 words, `points` 2–4 of ≤14 words) | Mockup `6` |
| `points` | Key points | `points` 3–6 of ≤20 words, `emphasis` | Numbered rows like `next_steps` without owner or time; the fallback for content that fits no other visual |
| `next_steps` | Next steps | `actions` 2–5 (`text` ≤12 words, `owner` ≤3, `when` ≤10 chars), `emphasis` (default 0) | Mockup `7` |

### Swimlane solver

`arp/reporting/flow_layout.py`: `solve_swimlane(flow, box) -> SolvedFlow`. It is deterministic: the same
input always gives the same output.

- **Column:** each node's column is the length of the longest path to it from any node without incoming
  edges. Back edges (cycles) are reversed for ranking only.
- **Row:** each node's row is its lane. Two nodes in the same lane and column are stacked within the lane.
- **Node sizes:** process 220×84, start 220×84 pill, decision 132×132 diamond. Columns are spaced evenly
  across the box after the 240 px lane-label strip.
- **Routes:**
  - Each edge leaves the source's right side and enters the target's left side through right-angle
    segments, with one vertical segment at the midpoint between the columns.
  - Edges to an earlier column loop below the lane.
  - Edge labels sit at the vertical segment.
- **PowerPoint:** connectors are freeform polylines along these routes, with arrowheads.
- **Too big:** more than 6 columns, or nodes that don't fit the box, goes to the fit ladder.

### Render model

- **Module:** `arp/reporting/render_model.py`.
- **Main function:** `render_slide(slide, index, deck, tokens, datasets) -> list[Primitive]`.
- **Primitive types:** `Rect`, `Text`, `Line` (polyline with an optional arrowhead), `Chart` (kind,
  categories, series, colours, labels, unit) and `Table`. Each carries a `name`, its x, y, w and h in
  canvas px, and `emphasis`.
- **Primitive names:**
  - `strip:1`..`5`, `kicker`, `title`, `subtitle`, `source`, `page`;
  - per visual: `kpi:tile:n`, `chart`, `card:insight`, `callout`, `step:n`, `connector:n`, `lane:n`,
    `node:<id>`, `edge:n`, `table`, `quadrant:n`, `event:n`, `row:n`, `col:left`, `col:right`.
- **Writers** (one list, two outputs):
  - `render_deck_html(deck, datasets, tokens=None, mode="light")`: elements with `data-name`; charts as
    inline SVG computed from the primitive, not matplotlib.
  - `build_house_pptx(deck, datasets, out, tokens=None, mode="light")`: native shapes named after
    primitives. `Chart` becomes a native chart of the same kind, with waterfall as a stacked column with
    an invisible base series. `Table` becomes a native table. `Line` becomes a freeform polyline.
  - Slides without a visual use today's legacy code in the same functions.

### Fit ladder

After rendering, `browser.measure` reports `overflow` and `overflow_x` for component slides (the legacy
`off_grid`/`collision` rules stay for legacy slides). For each slide with overflow, code tries these steps
in order and stops at the first that fits:

1. **Shorten:** one AI rewrite of the overflowing text fields, keeping every number.
2. **Step type down:** each visual has two smaller type steps (value 144 → 112 → 96 px; body 28 → 24 px;
   titles 36 → 30 px), never below 18 px.
3. **Switch visual:**
   - `linear_flow` with ≥5 steps, `kpi_row` with 4 tiles, or `timeline` with ≥5 events becomes a
     `comparison_table` of the same items;
   - a `chart` with an insight card drops the card: its stat becomes the subtitle and the chart goes
     full width;
   - a `two_column` drops its KPI strip, and the KPIs move into the subtitle.
4. **Split:** `comparison_table`, `linear_flow`, `points` and `next_steps` split into two consecutive
   slides with the same headline. The kicker gets ` 1/2` and ` 2/2`.
5. **Needs review:** the slide is kept, `needs_review` is set, and a `fit` finding with
   `rule="needs_review"` is logged. Export (download of `output.pdf`/`output.pptx`) returns 409 with
   `Slide <n> needs review` until each such slide is refined or approved in the refine screen.

Each step taken logs a `fit` finding: `shortened`, `type_step`, `switched`, `split`.

**Underfill:** a content slide whose body primitives span less than 50% of the body height (296 px) is
first stepped up one type size and its content centred. If it is still under 50%, an `underfill`
finding is logged.

**Chart cap:** a bar or column `chart` with more than 10 categories shows the top 9 by value, plus
"Other" (their sum). A `fit` finding `rule="chart_capped"` is logged.

### Design checks

`arp/reporting/design_checks.py`:

- `check_slides(slides: list[list[Primitive]], tokens) -> list[Finding]` (stage `fit`).
- `design_checks(deck, datasets, tokens=None, mode="light") -> list[Finding]`.

| Rule | Finding when |
|---|---|
| `underfill` | as in the fit ladder |
| `small_text` | any `Text` < 18 px |
| `low_contrast` | a filled `Text` against the fill under it < 4.5:1 (< 3:1 for ≥48 px) |
| `emphasis_count` | more than one `emphasis` primitive on a content slide |

### Deck settings and outline

- **`ReportRequest` gains `deck: DeckSettings`:**
  - `profile`: `executive`, `client_pitch`, `committee` (default) or `workshop`. Each sets the arc:
    - executive — answer first, KPI and decision slides;
    - client_pitch — problem, cost of inaction, evidence, plan, next steps;
    - committee — context, analysis, options, decision;
    - workshop — more flows and tables.
  - `purpose`: `recommendation`, `review`, `process` or `briefing`;
  - `detail`: `concise`, `balanced` (default) or `comprehensive`;
  - `max_slides` 3–25 (default 12; `executive` caps it at 8).
- **`Storyline` gains:**
  - `answer` (≤30 words), `figures` (0–2);
  - `sections` (each with `title` and `summary`);
  - `closing` (2–5 next actions).
- **`StorylineSlide` gains:**
  - `visual` (one of the content types);
  - `rationale` (≤20 words);
  - `section` (index);
  - `kicker`, `subtitle`.
- **Deck order, built by code:** cover → for each section, a `section` slide and its content slides →
  `next_steps` from `closing`. Content slides beyond `max_slides` are dropped, with a finding
  `rule="profile_cap"` (stage `data`).
- **Prompts:** the storyline prompt names the profile, purpose, detail, the content visual types and
  `style/design.md`. That file says which claim fits which visual, plus the emphasis rule.
- **Fill:** a fill that fails validation gets one retry, then a `bad_reference` finding and a `points`
  slide built from the headline and rationale.

### Outline review screen (frontend)

Mockup `ui-outline`, in the report builder's storyline step:

- **Settings row:** profile, purpose, detail and max slides, set before the storyline is drafted.
- **Answer:** "The answer in one line" (editable).
- **Slide table, grouped by section:** headline (editable), a visual picker with friendly names, and the
  rationale.
- **Actions:** add, remove and reorder slides; "Approve & build".
- Changing a visual in the picker updates `StorylineSlide.visual`.

### Single-slide refinement

**API:**

- `POST /api/reports/{id}/slides/{n}/refine` with `{ "instruction": str }`:
  1. One AI call returns an updated `SlideContent` for that slide, with the deck's datasets and notes as
     context.
  2. Code rejects the result (422, with the reason, deck unchanged) when it changes the headline, adds a
     number not in the sources, or references a dataset or column that doesn't exist.
  3. Otherwise the fit ladder (steps 1–4) and checks run on that slide, the slide is stored as a new
     version, outputs are re-rendered, and the response is the new slide plus its findings.
- `POST /api/reports/{id}/slides/{n}/undo` restores the previous version (409 when there is none).
- `GET /api/reports/{id}/slides/{n}/history` lists versions: `{version, instruction, summary, created_at}`.
- `POST /api/reports/{id}/slides/{n}/approve` clears `needs_review`.

**Storage:** versions live under `reports/<id>/slides/<n>/v<k>.json`. Version 1 is the slide as built.

**Screen** (mockup `ui-refine`):

- a large preview of the slide;
- quick suggestions: "Highlight the key point", "Turn into bars", "Simpler, for executives",
  "Make this a step flow", "Shorten the text";
- a free instruction field;
- history with Undo;
- a checks panel (fits, one emphasis, numbers in sources) and the source line.

### Review sheet

- `arp.reporting.sheet.sheet_deck() -> tuple[Deck, list[QuantitativeDataset], str]` builds fixture
  slides 0–13 (one per mockup) and returns the fixture notes.
- `arp report sheet --out <dir>` writes one 1920×1080 PNG per fixture, named like the mockups, plus
  `sheet.png`.
- `tests/test_slide_sheet.py::test_sheet_matches_goldens` compares them with
  `backend/tests/golden/slides/`. It fails when more than 0.5% of pixels differ by more than 16/255.

### Superseded template-frame rows

New house decks render through visuals, so these template-frame rows are superseded and their hidden
tests are retired in the same change:

- AC-8–AC-14, AC-16, AC-27 and AC-28 (headline, subheading, `slot:*`, `footer:*`): replaced here by
  AC-20 and AC-30.
- AC-15 and AC-21 (a subheading only with a template).
- AC-22 (`accent_rule`; legacy only).

Upload rows AC-1–AC-7, AC-19, AC-20, AC-23–AC-26 and storyline UI rows AC-17 and AC-18 stand.

### Delivery

| PR | Contents | Acceptance rows |
|---|---|---|
| 1 | Render model, zones, colours, cover, section, `kpi_row`, `chart` (bar, column, stacked, line), `comparison_table`, `two_column`, `points`, `next_steps`, fit ladder, design checks, deck settings and outline backend, review sheet | AC-1–AC-12, AC-14–AC-28, AC-30–AC-33 |
| 2 | `chart` waterfall and doughnut, `linear_flow`, `swimlane_flow` with the solver, `matrix_2x2`, `timeline` | AC-34–AC-41 |
| 3 | Outline review screen, single-slide refinement API and screen | AC-42–AC-49 |

Each PR puts `Spec: slide-components-design` and a `Rows:` line in its description.

### Left to the builder

- Module boundaries inside the render model.
- Native chart styling details.
- The pixel-diff implementation.
- The `design.md` wording, within the rules above.

## Acceptance

**Fixtures** (`arp/reporting/sheet.py`):

- **`eps`** ("EPS growth 2025"): `sector`, `growth_pct`. Rows: Tech 18, Financials 12, Market 11,
  Industrials 9, Energy 6, Utilities 4.
- **`eps_q`** ("Sector earnings, quarterly"): `quarter`, `utilities`, `market`. Quarters Q1 24 … Q4 25.
  `utilities`: 9.1, 8.4, 7.0, 5.9, 5.2, 4.6, 4.1, 4.0. `market`: 11.5, 11.2, 11.0, 10.8, 10.9, 11.1,
  11.0, 11.0.
- **`bridge`** ("EPS bridge 2024–2025"): `step`, `value`. Rows: 2024 EPS 100, Funding cost −14,
  Tariff lag −6, Volume 4, Opex −2, 2025 EPS 82.
- **`segments`** ("Holdings segments"): `segment`, `share`. Rows: Regulated networks 58,
  Generation 27, Retail 15.
- **`names`** ("Utility holdings"): `Company`, `Weight %`, `EPS growth %`, `Net debt / EBITDA`, `Action`.
  Rows:
  - Northgrid 2.1 / 7 / 4.2 / Hold
  - Solvane Power 1.6 / 5 / 5.1 / Hold
  - Eastwater 1.2 / 2 / 6.0 / Engage
  - Kestrel Gas 0.9 / −1 / 5.8 / Engage
  - Brightline 0.7 / 9 / 3.4 / Add
- **Notes:** "Sector funding cost rose to 6.2% from 3.9%. 30% of sector debt is due by 2027. Utilities
  trail the market by −7 pts; the market grew 11% and utilities 4%. Two central-bank cuts lower yields
  60 bp. Brightline trades below 14x earnings."

The sheet deck's sources are `ReportRequest(title="Utilities outlook 2026", qualitative_notes=<notes>,
datasets=<all five>)`.

**Sheet slides**, matching the mockups:

0. cover
1. section
2. `kpi_row` (4%, 11%, 6.2%, 30%; emphasis 0)
3. `chart` bar on `eps` (highlight Utilities, unit %, insight stat "−7 pts")
4. `linear_flow` (4 steps)
5. `comparison_table` on `names` (highlight "Net debt / EBITDA"; totals: sum, mean, mean)
6. `two_column` (3 KPIs)
7. `next_steps` (4 actions)
8. `chart` line on `eps_q` (highlight `utilities`, callout on Q3 24, full width)
9. `chart` waterfall on `bridge` (highlight Funding cost)
10. `swimlane_flow` (3 lanes, 6 nodes as in mockup 10)
11. `matrix_2x2` (emphasis 0)
12. `timeline` (5 events, today 2, emphasis 3)
13. `chart` doughnut on `segments` (highlight Regulated networks, with insight)

Builds are in light mode without a template unless a row says otherwise. Positions are in canvas px;
PPTX is converted at 9525 EMU/px.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | the sheet deck | `render_deck_html` and `build_house_pptx` | for every primitive name on every slide, the HTML `[data-name]` box equals the PPTX shape box of that name (±1 px) | holdout |
| AC-2 | the sheet deck | build PPTX | every content slide (2–13) has `strip:1`..`5`, 12×12 px at y 64 and x 96, 112, 128, 144, 160 (±1); `strip:3` fill `2a78d6`, the others `121722` | holdout |
| AC-3 | the sheet deck | build PPTX | on slides 2–13, `title` top 104 and height 128; `source` within y 952–1000 (±1) | holdout |
| AC-4 | slide 3 | read `source` | `Source: EPS growth 2025` | holdout |
| AC-5 | slide 2 | build PPTX | `kpi:tile:1`..`4` each 414 px wide at x 96, 534, 972, 1410 (±1); tile 1 fill `121722` with value runs `ffffff`; tiles 2–4 fill `f4f6f9` | holdout |
| AC-6 | slide 3 | build PPTX | native bar chart, 6 points; "Utilities" fill `2a78d6`, the others `eaeef3`; data labels on with a format ending in `%`; `card:insight` 520 px wide, fill `f4f6f9` | holdout |
| AC-7 | slide 4 | build PPTX | `step:1`..`4` each 440 px tall, top 404 (±2), 414 px wide, 24 px apart; `step:4` fill `121722`; `connector:1`..`3` present | holdout |
| AC-8 | slide 5 | build PPTX | native table: header, 5 body rows, total row `6.5`, `4.4`, `4.9`; the "Net debt / EBITDA" header cell fill `121722` | holdout |
| AC-9 | the sheet deck with tile 2's value changed to `9.9%` | `lint_deck` with the sheet sources | exactly one `number_not_in_source` finding on slide 2 | holdout |
| AC-10 | a stand-in LLM returning a valid 4-tile `kpi_row` with `emphasis: 7` | `fill_slide` | the slide is a `kpi_row` with `emphasis` None; one `bad_reference`; the stand-in was called once | holdout |
| AC-11 | a `two_column` slide, no KPIs, two points of ≤3 words per column | `design_checks` | exactly one `underfill` finding for that slide | holdout |
| AC-12 | the sheet deck | `design_checks` | no `underfill`, `small_text`, `low_contrast` or `emphasis_count` finding | holdout |
| AC-14 | `check_slides` on one slide with two `Rect`s whose `emphasis` is true | run | exactly one `emphasis_count` finding | holdout |
| AC-15 | the sheet deck in dark mode | build PPTX | slides 2–13 background `141921`; `kpi:tile:1` fill `e8ebf0` with value runs `141921` | holdout |
| AC-16 | a request without `deck` settings and a recording stand-in LLM | draft the storyline | the prompt contains `committee`, `balanced` and each of `kpi_row`, `chart`, `linear_flow`, `swimlane_flow`, `comparison_table`, `matrix_2x2`, `timeline`, `two_column`, `points`; returned slides keep `visual` and `rationale` | holdout |
| AC-17 | an approved storyline with 2 sections of 2 slides and 3 closing actions | build with a stand-in LLM | the visual types in order: cover, section, (2 content), section, (2 content), next_steps; the last slide has 3 rows | holdout |
| AC-18 | the repo | `arp report sheet --out d` | exits 0; `d` holds `sheet.png` and 14 PNGs named like the mockups, each 1920×1080 | holdout |
| AC-19 | the committed goldens | change `graphite.ink` to `#000000`, run `test_sheet_matches_goldens` | the test fails | unit |
| AC-20 | the sheet deck with the template-frame fixture (headline box 144, 72) | build PPTX (6350 EMU/px) | on slides 2–13, `title` equals the frame headline box (±1); `strip:1` left 144, top 32 (±1) | holdout |
| AC-21 | the rendered sheet | compare with the mockups in `assets/slide-components/` | each visual matches its mockup in layout, spacing and emphasis; nothing overlaps or is clipped | evaluator |
| AC-22 | a stored house deck whose slides have no `visual` | `build_house_pptx` | shape names, positions and fonts equal a build on `main` before this change (±1) | holdout |
| AC-23 | a classic `pptx` report and the stewardship client report | build | `slot:*` shapes present (legacy layouts) | holdout |
| AC-24 | the sheet deck, light and dark | build PPTX and HTML | no colour is `ea4c14`, `85601a`, `d4a650`, `13804f`, `c8323f`, `4fd69c`, `ff6b7a` or `2563c9` | holdout |
| AC-25 | `check_slides` with one 16 px `Text` | run | exactly one `small_text` finding | holdout |
| AC-26 | `check_slides` with 28 px `#aab4c3` text on a `#ffffff` `Rect` | run | exactly one `low_contrast` finding | holdout |
| AC-27 | a `kpi_row` tile label of 60 words; a stand-in whose shorten-rewrite returns the same text | `build_house_deck` | findings include `type_step`, then `switched`; the slide is now a `comparison_table` | holdout |
| AC-28 | a `comparison_table` of 8 rows whose cells each hold 40 words; a stand-in returning the same text | `build_house_deck` | the slide is split in two with the same headline, kickers ending ` 1/2` and ` 2/2`; one `split` finding | holdout |
| AC-30 | slide 3 under a frame whose body box ends at y 1040 | build PPTX (6350 EMU/px) | slide 3 has no `source` shape; its notes end with `Source: EPS growth 2025` | holdout |
| AC-31 | a slide forced past every ladder step (a 200-word headline) | build, then GET `/download` | the slide has `needs_review` true and one finding `needs_review`; the download returns 409 with `Slide <n> needs review` | holdout |
| AC-32 | a bar `chart` over a dataset with 14 categories | build PPTX | 10 points; the last is "Other" with the sum of the 5 smallest; one `chart_capped` finding | holdout |
| AC-33 | `deck.profile: executive`, a storyline of 10 content slides | build | 8 content slides; one `profile_cap` finding | holdout |
| AC-34 | slide 8 (line) | build PPTX | native line chart with 2 series and 8 points; the `utilities` series line `2a78d6`, `market` `c4ccd7`; a `callout` shape at Q3 24 | holdout |
| AC-35 | slide 9 (waterfall) | build PPTX | a native stacked column chart; the visible series shows 100, 14, 6, 4, 2, 82; first and last points `121722`; "Funding cost" `2a78d6`; the others `c4ccd7` | holdout |
| AC-36 | slide 13 (doughnut) | build PPTX | a native doughnut with 3 points; "Regulated networks" `2a78d6`; a centre text `58%` | holdout |
| AC-37 | slide 10's flow | `solve_swimlane` | node columns a 0, b 1, c 2, d 3, e 4, f 4; every edge route is right-angled and starts on its source's right edge and ends on its target's left edge (±1) | holdout |
| AC-38 | slide 10 | build PPTX | shapes `lane:1`..`3`, `node:a`..`f`, `edge:1`..`5`; each `edge:n` is a freeform whose points equal the solved route (±1) | holdout |
| AC-39 | a swimlane with 8 columns | build | the fit ladder applies; findings include `switched` or `needs_review` | holdout |
| AC-40 | slide 11 (matrix) | build PPTX | `quadrant:1`..`4`; `quadrant:1` fill `121722`, the others `f4f6f9`; 16 px gaps (±1) | holdout |
| AC-41 | slide 12 (timeline) | build PPTX | `event:1`..`5` markers on one horizontal line; `event:4` fill `2a78d6`; a `today` pill at event 3 | holdout |
| AC-42 | the outline review in the app with a drafted storyline | look at the screen | settings row (profile, purpose, detail, max slides), the answer line, and per slide the headline, a visual picker with friendly names, and the rationale, grouped by section | evaluator |
| AC-43 | the outline review | change slide 2's visual to "Comparison table" and approve | the built slide 2 is a `comparison_table` | evaluator |
| AC-44 | a built deck; a stand-in returning slide 3 with `highlight` "Energy" | POST `/slides/3/refine` `{"instruction":"Highlight Energy"}` | 200; history has versions 1 and 2; the PPTX "Energy" point fill is `2a78d6` | holdout |
| AC-45 | a stand-in returning slide 3 with a changed headline | POST refine | 422 with a detail naming `headline`; history unchanged | holdout |
| AC-46 | a stand-in returning slide 2 with a new tile value `99%` | POST refine | 422 with a detail naming `99%`; history unchanged | holdout |
| AC-47 | after AC-44 | POST `/slides/3/undo` | 200; history's current version is 1; "Utilities" fill `2a78d6` again | holdout |
| AC-48 | a slide at version 1 | POST undo | 409 | holdout |
| AC-49 | the refine screen in the app | use a quick suggestion, then Undo | the preview changes, then returns; history and checks panel as in mockup `ui-refine` | evaluator |
