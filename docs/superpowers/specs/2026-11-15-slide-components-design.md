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
(not the AI) computing positions.

The owner approved mockups of eight components on 15 Nov 2026. They are committed in
`docs/superpowers/specs/assets/slide-components/` (`0-cover.png` … `7-next_steps.png`).

## What exists today

- **Build sequence:** storyline (headlines, approved by a person) → `fill_slide` picks one of 21
  `layouts.json` variants per slide and fills text slots → lint → fit (Chromium measures overflow) →
  visual QA → render, twice: `html_render.py` + Jinja templates for PDF/PNG, and `house_pptx.py` for the
  PPTX.
- **Colours:** `style/tokens.json` holds the legacy palette (`ink #141414`, `accent #ea4c14`, …).
- **The legacy renderer has other users:** classic `pptx`/`pdf` reports (`deck_from_plan`), the
  stewardship client report, and stored house decks.
- **Grounding:** charts and tables reference datasets by id. Lint flags numbers not found in the
  sources.
- **Company template frames** (spec `2026-11-14-template-frame-design.md`) override fonts and the
  headline, subheading and body boxes.

## Decisions taken with the owner

1. **Typed components** replace generic layout variants for house decks built after this change.
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
4. **The look is the approved mockup set.** ▲/▼ deltas are drawn in the tile's text colour, never
   green or red.

## Goals

1. Eight typed components that each lay out their own content.
2. One render model: each slide becomes a list of positioned primitives once, and both the HTML and
   the PPTX writers draw that list. PDF and PPTX match by construction.
3. Every content slide has the same anatomy in fixed zones, and every gap and padding comes from one
   spacing scale.
4. The outline assigns a component to each slide, with a rationale, shaped by a deck profile.
5. Measured design checks (underfill, minimum text size, contrast, one emphasis) report findings the
   way overflow does today.
6. A review sheet renders every component from fixtures, guarded by a screenshot test.

## Non-goals

- Refining or undoing edits on one slide at a time (a follow-up spec).
- The shared app/deck token file (the parked deck-design-system spec, to be rebased onto this one).
- Flow diagrams, swimlanes, D2/Mermaid, images, quotes, 2×2 matrices, line or donut charts.
- Changing classic `pptx`/`pdf` reports, the stewardship client report, or how stored house decks
  render.
- Status or signal colours on slides.
- Snapping every absolute position to an 8 px grid. Equal division and centring produce positions off
  the grid, and that is fine.

## Anti-goals

- A number on a slide that is in no source.
- PDF and PPTX differing in any position, size or colour.
- Text that overflows its box or shrinks to fit without a finding.
- A slide whose body is mostly empty, without a finding.

## Approaches

| | How | Trade-off |
|---|---|---|
| **Typed components on a render model (picked)** | Components compute primitives; two thin writers draw them. | The largest change, but every later visual is built once. |
| Components drawn by both renderers | Each component written twice, in Jinja and in python-pptx. | Faster to start, but doubles all future work. |
| Blueprint as is | A separate compiler service, Node orchestrator and Gemini. | Duplicates ARP's stack and loses its grounding and fit checks. |

## Design

### Canvas, zones and spacing

- **Canvas:** 1920×1080 px. Margins: 96 px left and right.
- **Spacing scale:** every gap and padding a component produces is one of 4, 8, 12, 16, 24, 32, 40,
  48, 64 or 96 px, named as constants in `render_model.py`. Widths and offsets that come from dividing
  or centring are computed and need not be on the scale.
- **Content-slide zones** (y ranges in px; all zones span x 96–1824):

| Zone | y | Content |
|---|---|---|
| Label line | 64–88 | Signature strip (five 12×12 px squares, 4 px gaps; the third square is `highlight`, the others `ink`), then a 16 px gap, then the kicker in mono 20 px uppercase, `muted`. |
| Action title | 104–232 | The approved headline: 56 px, weight 600, at most 2 lines. |
| Subtitle | 248–288 | 28 px, `muted`, 1 line. The zone stays empty when there is no subtitle. |
| Body | 328–920 | The component. |
| Source line | 952–1000 | 1 px `line` rule at y 952; the source text in mono 18 px `muted` on the left, the page number on the right. |

- **Under a company template frame:**
  - the action title, subtitle and body zones become the frame's headline, subheading and body boxes;
  - the label line keeps its house distance to the title: the strip's top sits 40 px above the frame's headline box
    top (as 64 is to 104), starting at the box's left edge;
  - the source line keeps its zone when the frame's body box ends at or above y 928. Otherwise there is
    no source line and `source_line` is appended to the speaker notes, after a newline unless the notes
    are empty.
- **Cover and section** are full-bleed and use no zones.

### Colours

New keys `graphite` and `graphite_dark` in `style/tokens.json`. The legacy colour keys stay unchanged
for the legacy renderer.

| Token | `graphite` | `graphite_dark` |
|---|---|---|
| `ground` | `#f4f6f9` | `#0d1015` |
| `panel` | `#ffffff` | `#141921` |
| `line` | `#d8dee7` | `#2c3644` |
| `well` | `#eaeef3` | `#1b222d` |
| `ink` | `#121722` | `#e8ebf0` |
| `muted` | `#4f5a6b` | `#a3acbb` |
| `highlight` | `#2a78d6` | `#3987e5` |
| `inverse_muted` (secondary text on an `ink` block) | `#aab4c3` | `#4f5a6b` |

- **Slide background:** `panel`. Section slides use `ground`.
- **Emphasis block:** `ink` fill, `panel` text, `inverse_muted` secondary text.
- **Non-emphasised tiles, cards and rows:** `ground`.
- **Highlighted data:** `highlight` as a fill only. Text is never set in `highlight` and never placed
  on it. Value labels sit beside the bar in `ink`.

### Slide fields

`SlideContent` gains these fields, all with defaults so stored decks still validate:

- `kicker: str = ""`
- `subtitle: str = ""` — at most 16 words. The template-frame `subheading` field is read as an alias.
- `component: Component | None = None` — a discriminated union on `type`.
- `source_line: str = ""`

`layout` and `variant` become optional (`""` by default). A slide with a `component` is rendered by
the render model; a slide without one by the legacy renderer.

**`source_line`** is computed by code, never by the AI. It reads `Source: ` followed by the cited
items, joined by `; `:

- a dataset's `name`;
- for a table that shows only part of its dataset, `, rows a–b` (1-based, inclusive);
- for notes-based references, the note topics from `source_refs`.

A slide with no references gets `""`.

### Components

Every model's field limits are enforced by pydantic. An `emphasis` index outside the component's
range is not a validation error: `fill_slide` sets it to `None` and returns one `bad_reference`
finding (stage `data`). Numbers in `kpi_row`, `two_column.kpis` and `chart_insight.insight.stat` are
linted by `number_not_in_source` like any slide text.

| `type` | Fields | Layout (body zone unless full-bleed) |
|---|---|---|
| `cover` | `title` (≤10 words), `context` (≤8 words), `answer` (≤30 words), `figures` (0–2 of `value` ≤8 chars + `label` ≤4 words) | Full-bleed. The left 760 px is an `ink` panel holding the strip (inverted), the context, the title (72 px) and the deck subtitle. On the right: an "The answer in one line" label, `answer` (44 px), then the figures (96 px), vertically centred. |
| `section` | `number` (1–9), `title` (≤6 words), `summary` (≤14 words), `agenda` (filled by code with all section titles) | Full-bleed `ground`. The number is 200 px outline type (2 px `line` stroke, no fill; decorative, so `low_contrast` skips it), then the title (72 px) and summary (32 px), vertically centred. The agenda is bottom-right, with the current section marked by a square. |
| `kpi_row` | `tiles` (2–4 of `value` ≤8 chars, `label` ≤5 words, `delta` ≤6 words), `emphasis` (index or None) | Equal tiles across the full body width, 24 px gaps, full body height. Label at the top; value (144 px) and delta at the bottom; 40 px padding. |
| `chart_insight` | `chart` (`ChartSpec`: `bar` or `column`, one value column, `unit` ≤6 chars, `data_labels` default true, `highlight` category or None), `insight` (`stat` ≤8 chars, `headline` ≤12 words, `points` 0–2 of ≤12 words) | Chart on the left, a 520 px card on the right, 48 px apart. Chart: a mono label `<value column>, <unit>`; bars in `well`, the highlighted one in `highlight`; a value label (`<value><unit>`) beside each bar; no axis or grid. Card: `ground` with a 4 px `ink` left edge, 48 px padding, the stat (96 px), the headline (30 px), points with square bullets. |
| `step_flow` | `steps` (3–5 of `title` ≤4 words, `text` ≤16 words, `tag` ≤4 words, `when` ≤6 chars), `emphasis` (index or None; default the last step) | Equal cards 440 px tall, vertically centred in the body, 24 px gaps, joined by 24 px × 2 px `ink` connectors. Each card has 40 px padding: number square and `when` at the top, title (36 px), text (26 px), tag pill at the bottom. |
| `comparison_table` | `table` (`TableSpec`, 2–6 columns, ≤8 rows), `highlight_column` (column name or None), `total_row` (per numeric column: `sum`, `mean` or `none`, computed by code; a sum keeps the column's decimals, a mean gets one more) | Full body width, 28 px text, 18 px cell padding top and bottom, 24 px left and right. Text columns are left-aligned; number columns right-aligned in mono. The header is mono uppercase over a 2 px `ink` rule. The highlighted column has an `ink` header and `ground` cells at weight 600. The total row has a 2 px `ink` rule on top and weight 600. |
| `two_column` | `kpis` (0–3 of `value` + `label`), `left` and `right` (`title` ≤5 words, `points` 2–4 of ≤14 words) | A KPI strip on top when there are KPIs (`ground`, 1 px `line` dividers, 32 px padding), 40 px gap, then two columns 64 px apart. Each column has a mono title over a 2 px `ink` rule, then numbered points (`01`, `02`) with 24 px padding and 1 px `line` rules. |
| `next_steps` | `actions` (2–5 of `text` ≤12 words, `owner` ≤3 words, `when` ≤10 chars), `emphasis` (index or None; default 0) | Rows vertically centred in the body, 16 px gaps, 28 px vertical / 40 px horizontal padding. Each row: `ground` fill, number square, action text (30 px; weight 600 when emphasised), owner as a mono label, `when` pill on the right. |

**Emphasis:**

- An emphasised tile, step card or (`cover`) left panel is an emphasis block.
- An emphasised `next_steps` row is not a block; only its text weight changes.
- Every primitive the render model emits carries `emphasis: bool`, true only for emphasis blocks.
- At most one emphasis block per content slide.

### Render model

- **Module:** `arp/reporting/render_model.py`.
- **Main function:** `render_slide(slide: SlideContent, index: int, deck: Deck, tokens: Tokens,
  datasets) -> list[Primitive]`.
- **Primitive types:** `Rect` (fill, line), `Text` (box, text, size, weight, family, colour, alignment,
  anchor), `Line`, `ChartBars` (categories, values, colours, unit, value labels) and `TableGrid`.
  Each carries `name`, its x, y, w and h in canvas px, and `emphasis`.
- **Primitive names:**
  - `strip:1`..`5`, `kicker`, `title`, `subtitle`, `source`, `page`;
  - per component: `kpi:tile:n`, `chart`, `card:insight`, `step:n`, `connector:n`, `table`, `row:n`,
    `kpis`, `col:left`, `col:right`.
- **Writers** (both draw the same list):
  - `render_deck_html(deck, datasets, tokens=None, mode="light")` gives each primitive an element with
    `data-name`;
  - `build_house_pptx(deck, datasets, out, tokens=None, mode="light")` names each native shape after its
    primitive (`ChartBars` → native bar chart, `TableGrid` → native table).
  - Slides without a component go through today's legacy code in the same two functions.
- **Fit:** on component slides `browser.measure` reports only `overflow` and `overflow_x` (its legacy `off_grid` and
  `collision` rules apply to legacy slides only).
  Fit shortens text fields with one targeted rewrite, never a slot rewrite or a split. Overflow left
  after the rewrite stays as an `overflow` finding.

### Design checks

`arp/reporting/design_checks.py`:

- `check_slides(slides: list[list[Primitive]], tokens) -> list[Finding]` (stage `fit`).
- `design_checks(deck, datasets, tokens=None, mode="light") -> list[Finding]` renders, then calls
  `check_slides`.

| Rule | Finding when |
|---|---|
| `underfill` | On a content slide, the vertical span from the topmost to the bottommost body primitive is less than 50% of the body zone height (296 px). |
| `small_text` | Any `Text` is smaller than 18 px. |
| `low_contrast` | A filled `Text` colour against the fill of the `Rect` directly under it (the slide background if none) is under 4.5:1, or 3:1 for text 48 px or larger. |
| `emphasis_count` | More than one primitive with `emphasis` true on a content slide. |

### Outline and deck profile

- **`AudienceProfile.deck_profile`**, default `committee`:
  - `executive` — answer first, KPI and decision slides, at most 8 content slides;
  - `client_pitch` — problem, cost of inaction, evidence, plan, next steps;
  - `committee` — context, analysis, options, decision;
  - `workshop` — more step flows and tables.
- **`Storyline` gains:**
  - `answer: str` (≤30 words);
  - `figures` (0–2 of `value` + `label`);
  - `sections: list[SectionPlan]`, each with `title` and `summary`;
  - `closing: list[NextAction]`: the `next_steps` actions (2–5).
- **`StorylineSlide` gains:**
  - `component` — one of `kpi_row`, `chart_insight`, `step_flow`, `comparison_table`, `two_column`;
  - `rationale` (≤20 words);
  - `section: int` (0-based index into `sections`);
  - `kicker`;
  - `subtitle`.
- **Deck order, built by code:** cover → for each section, a `section` slide then its content slides
  in storyline order → one `next_steps` slide built from `closing`, headline "Next steps" (kicker
  "Next steps"). `next_steps` belongs to no section.
- **`executive` profile:** a storyline with more than 8 content slides is cut to the first 8. A
  finding `rule="profile_cap"` (stage `data`) is logged.
- **Prompts:** the storyline prompt lists the five content component names and the profile's arc.
  `style/design.md` (which claim fits which component, and the emphasis rule) is part of the storyline
  and fill prompts.
- **Validation:** a fill that fails validation gets one retry with the errors, then a `bad_reference`
  finding and a `two_column` placeholder built from the headline.
- **Approval:** the owner approves the storyline with components visible, and can change any slide's
  component in the editor.

### Review sheet

- `arp.reporting.sheet.sheet_deck() -> tuple[Deck, list[QuantitativeDataset], str]` builds the eight
  fixture slides below and returns the fixture notes. The sheet deck's sources are
  `ReportRequest(title="Utilities outlook 2026", qualitative_notes=<notes>, datasets=<datasets>)`.
- `arp report sheet --out <dir>` writes `0-cover.png` … `7-next_steps.png` (1920×1080) and
  `sheet.png` (a 2-column contact sheet).
- The unit test `tests/test_slide_sheet.py::test_sheet_matches_goldens` compares each PNG with
  `backend/tests/golden/slides/<name>.png`. It fails when more than 0.5% of pixels differ by more than
  16/255 in any channel.

### Superseded rows of the template-frame spec

New house decks render through components, so these template-frame rows are superseded and their hidden
tests are retired in the same change:

- AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-27 and AC-28 (headline, subheading,
  `slot:*` and `footer:*` shapes): replaced by AC-20 and AC-30 here.
- AC-15 and AC-21 (a subheading only with a template): every slide now has a subtitle field.
- AC-22 (the `accent_rule` shape): legacy only.

Upload rows (AC-1–AC-7, AC-19, AC-20, AC-23–AC-26) and the storyline UI rows (AC-17, AC-18) stand.

### Left to the builder

- Module boundaries inside `render_model.py`.
- PPTX native chart styling details (gap width, label font).
- The pixel-diff implementation.
- The `design.md` wording, within the rules above.

## Acceptance

**Fixture data** (in `arp/reporting/sheet.py`):

- **`eps`** (name "EPS growth 2025"): category `sector`, value `growth_pct`. Rows: Tech 18,
  Financials 12, Market 11, Industrials 9, Energy 6, Utilities 4.
- **Notes** (`qualitative_notes`): "Sector funding cost rose to 6.2% from 3.9%. 30% of sector debt is due by 2027. Utilities trail the market by −7 pts; the market grew 11% and utilities 4%. Two central-bank cuts lower yields 60 bp. Brightline trades below 14x earnings."
- **`names`** (name "Utility holdings"): columns `Company`, `Weight %`, `EPS growth %`,
  `Net debt / EBITDA`, `Action`. Rows:
  - Northgrid 2.1 / 7 / 4.2 / Hold
  - Solvane Power 1.6 / 5 / 5.1 / Hold
  - Eastwater 1.2 / 2 / 6.0 / Engage
  - Kestrel Gas 0.9 / −1 / 5.8 / Engage
  - Brightline 0.7 / 9 / 3.4 / Add

**Sheet deck** (`sheet_deck()`), in order:

0. cover
1. section
2. `kpi_row` (4 tiles; values 4%, 11%, 6.2%, 30%; emphasis 0)
3. `chart_insight` (`eps`, highlight "Utilities", unit "%", stat "−7 pts")
4. `step_flow` (4 steps, emphasis default)
5. `comparison_table` (`names`, highlight_column "Net debt / EBITDA", total_row: Weight % sum, EPS growth % mean, Net debt / EBITDA mean)
6. `two_column` (3 KPIs)
7. `next_steps` (4 actions)

The text matches the approved mockups. Builds are in light mode without a template unless a row says
otherwise. Positions are in canvas px; PPTX is converted at 9525 EMU/px.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | the sheet deck | `render_deck_html` and `build_house_pptx` | for every primitive name on every slide, the HTML `[data-name]` element box equals the PPTX shape box of the same name (±1 px) | holdout |
| AC-2 | the sheet deck | build PPTX | slides 2–7 have shapes `strip:1`..`strip:5`, each 12×12 px at y 64, x 96, 112, 128, 144, 160 (±1 px); `strip:3` fill `2a78d6`, the others `121722` | holdout |
| AC-3 | the sheet deck | build PPTX | on slides 2–7, `title` has top 104 and height 128, and `source` lies within y 952–1000 (±1 px) | holdout |
| AC-4 | slide 3 | read the `source` text | `Source: EPS growth 2025` | holdout |
| AC-5 | slide 2 | build PPTX | `kpi:tile:1`..`4` each 414 px wide, at x 96, 534, 972, 1410 (±1 px); tile 1 fill `121722` with value runs `ffffff`; tiles 2–4 fill `f4f6f9` | holdout |
| AC-6 | slide 3 | build PPTX | a native bar chart with 6 points; the "Utilities" point fill `2a78d6`, the others `eaeef3`; data labels on with a number format ending in `%`; `card:insight` 520 px wide, fill `f4f6f9` | holdout |
| AC-7 | slide 4 | build PPTX | `step:1`..`4` each 440 px tall with top 404 (±2 px), each 414 px wide, 24 px apart; `step:4` fill `121722`; shapes `connector:1`..`3` present | holdout |
| AC-8 | slide 5 | build PPTX | a native table with a header, 5 body rows and a total row; the total row shows `6.5` (Weight %), `4.4` (EPS growth %), `4.9` (Net debt / EBITDA); the "Net debt / EBITDA" header cell fill `121722` | holdout |
| AC-9 | a sheet deck where tile 2's value is `9.9%`, with the sheet deck's sources | `lint_deck` | exactly one `number_not_in_source` finding on slide 2 | holdout |
| AC-10 | a stand-in LLM returning a valid `kpi_row` with 4 tiles and `emphasis: 7` | `fill_slide` | the slide is a `kpi_row` with `emphasis` None; one `bad_reference` finding; the stand-in was called once | holdout |
| AC-11 | a `two_column` slide, no KPIs, two points of ≤3 words per column | `design_checks` | exactly one `underfill` finding for that slide | holdout |
| AC-12 | the sheet deck | `design_checks` | no `underfill`, `small_text`, `low_contrast` or `emphasis_count` finding | holdout |
| ~~AC-13~~ | retired before approval: the `off_grid` rule was dropped (equal division and centring are off grid by design) | | | |
| AC-14 | `check_slides` on one slide holding two `Rect` primitives with `emphasis` true | run | exactly one `emphasis_count` finding | holdout |
| AC-15 | the sheet deck in dark mode | build PPTX | slides 2–7 background `141921`; `kpi:tile:1` fill `e8ebf0` with value runs `141921` | holdout |
| AC-16 | a request with no `deck_profile` and a recording stand-in LLM | draft the storyline | the prompt contains `committee` and each of `kpi_row`, `chart_insight`, `step_flow`, `comparison_table`, `two_column`; each returned slide keeps its `component` and `rationale` | holdout |
| AC-17 | an approved storyline with 2 sections of 2 slides each and 3 closing actions | build the deck with a stand-in LLM | the slide component types, in order: cover, section, (2 content), section, (2 content), next_steps; the last slide has 3 action rows | holdout |
| AC-18 | the repo | `arp report sheet --out d` | exits 0; `d` holds `sheet.png` and the eight named PNGs, each 1920×1080 | holdout |
| AC-19 | the committed goldens | change `graphite.ink` to `#000000` and run `test_sheet_matches_goldens` | the test fails | unit |
| AC-20 | the sheet deck with the template-frame fixture (`tests/fixtures/frame_template.py`, headline box 144, 72) | build PPTX (6350 EMU/px) | on slides 2–7, `title` equals the frame headline box (±1 px); `strip:1` has left 144 and top 32 (±1 px) | holdout |
| AC-21 | the rendered sheet | compare with `docs/superpowers/specs/assets/slide-components/*.png` | the layout, spacing and emphasis of each component match its mockup; nothing overlaps or is clipped | evaluator |
| AC-25 | `check_slides` on a slide with a 16 px `Text` | run | exactly one `small_text` finding | holdout |
| AC-26 | `check_slides` on a slide with 28 px `#aab4c3` text on a `#ffffff` `Rect` | run | exactly one `low_contrast` finding | holdout |
| AC-27 | a `kpi_row` tile label of 60 words, built with a stand-in LLM whose rewrite returns the same text | `build_house_deck` | the findings include `rule="overflow"`, stage `fit`, for that slide | holdout |
| AC-28 | `deck_profile: executive` and a storyline of 10 content slides | build the deck | it holds 8 content slides; one finding `rule="profile_cap"` | holdout |
| AC-30 | the sheet deck with a frame whose body box ends at y 1040 (the template-frame fixture with its body placeholder extended to the slide bottom) | build PPTX (6350 EMU/px) | slide 3 has no `source` shape and its notes end with `Source: EPS growth 2025` | holdout |

Must not change:

| ID | Given | When | Then | Checked by |
|----|-------|------|------|------------|
| AC-22 | a stored house deck whose slides have no `component` | `build_house_pptx` | shape names, positions and fonts equal a build on `main` before this change (±1 px) | holdout |
| AC-23 | a classic `pptx` report and the stewardship client report | build | `slot:*` shapes are present, from the legacy layouts | holdout |
| AC-24 | the sheet deck, light and dark | build PPTX and HTML | no shape fill, line or run colour, and no HTML computed colour, is `ea4c14`, `85601a`, `d4a650`, `13804f`, `c8323f`, `4fd69c`, `ff6b7a` or `2563c9` | holdout |
