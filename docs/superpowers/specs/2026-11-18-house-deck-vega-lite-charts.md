# House-deck charts drawn by Vega-Lite, with waterfall and heatmap

Slug: house-deck-vega-lite-charts

Risk of the build: `risk:normal`. Four slices of size S (see `## Slices`). Plan PR 6 of
[Improve the house-deck builder](https://claude.ai/artifact/HrvD3WdtCD3e15cMGPjesm).

Status: draft, waiting for the owner's approval (spec-critic: three passes, all findings fixed).

## Decisions for the owner

1. **Waterfall and heatmap as new component chart kinds** (asked in the spec session, 18 Nov 2026). Recommended:
   yes. The model can then pick them for a chart slide. The waterfall stays an editable native chart in PowerPoint
   (a stacked column over an invisible base, as `2026-11-15-slide-components-design.md` AC-35 already specifies);
   the heatmap goes into PowerPoint as a picture with a `chart_picture` finding. If the owner says "same four kinds
   only", slices 3 and 4 and rows AC-30 to AC-52 are dropped and nothing else changes.

Everything else is decided below under "Defaults".

## Why

The house deck draws every chart twice: PowerPoint's own chart engine for the `.pptx`, and ARP's own drawing code
for the HTML that becomes the PDF and the preview PNGs. The HTML side is two hand-written drawers: about 50 lines of
SVG in `html_writer._chart` for component slides, and matplotlib (`chart_builder.render_chart_svg`) for layout
slides. Each new chart kind means new geometry code in both, so the component chart only knows bar, column, stacked
column and line, and the waterfall and doughnut the slide-components spec promised were never built. On 18 Nov the
59-slide engineering deck needed a waterfall (how 10,446 tests add up) and a heatmap (commits per package per day);
both were drawn by hand outside ARP (`/mnt/project-files/deck-tools-samples/source/charts.py`).

## What the owner can do afterwards that they cannot do today

- Get a **waterfall** chart slide from the deck builder: house look in the PDF, an editable native chart in the
  PowerPoint.
- Get a **heatmap** chart slide: house look in the PDF, a picture in the PowerPoint with a finding that says so.
- Read every HTML/PDF chart's data from the page itself: each bar, point or cell carries its category, series and
  label, so a test checks the PDF chart against the PowerPoint chart number by number.
- Change the look of every PDF chart (fonts, sizes, text colours) in one file,
  `backend/arp/reporting/style/chart_theme.json`.

## Three versions considered

| Version | What it delivers | Verdict |
|---|---|---|
| Safe | Vega-Lite replaces both HTML drawers for the kinds that exist today; parity test | Leaves the deck's real gap (waterfall, heatmap) open |
| **Strong (this spec)** | Safe, plus waterfall (native in PowerPoint) and heatmap (picture plus finding) as component chart kinds | Every row exact; four S slices |
| Most ambitious | Strong, plus doughnut, scatter, area and small multiples as component kinds, the Word report's charts on Vega-Lite so matplotlib leaves the repo, radar in Vega | Not specified |

Next step up would need fit rules for each extra kind (label density, minimum mark size, how many facets fit a
1920 × 1080 slide) measured on real decks first, and a Vega (not Vega-Lite) spec for radar.

## Goals

- G1. Component chart slides (`visual.type == "chart"`) are drawn in the HTML by Vega-Lite, rendered in-process by
  `vl-convert-python` (no browser), for bar, column, stacked column and line.
- G2. The HTML chart and the PowerPoint chart of the same slide show the same categories, in the same order, the same
  values and the same data labels.
- G3. One house theme file sets every Vega-Lite chart's fonts, text sizes and text colours, filled from the deck's
  tokens and mode.
- G4. Layout slides (`slide.chart`, a `ChartSpec`) are drawn in the HTML by Vega-Lite for every `ChartType` except
  radar and table, and their PowerPoint pictures (waterfall, heatmap) are the PNG of the same spec.
- G5. Every chart that is a picture in the PowerPoint gets a `chart_picture` finding.
- G6. Waterfall and heatmap are component chart kinds the storyline can choose.

## Non-goals

- No frontend changes, no `.html.j2` template changes, no change to `report_builder` (the Word report keeps
  matplotlib).
- No new kinds beyond waterfall and heatmap. Doughnut stays owed by the slide-components spec. Radar on layout
  slides keeps its matplotlib SVG.
- No legends added to the HTML charts (the HTML has none today; the PowerPoint keeps its own).
- No interactivity (tooltips, zoom) in the HTML.

## Anti-goals

- The model never writes Vega-Lite: the `Chart` visual gets no field for it, and code builds the spec (AC-24).
- No browser for chart drawing (AC-25).
- No change to the PowerPoint native charts for bar, column, stacked column and line (AC-14).

## Design

### Dependency

`vl-convert-python>=1.9,<2` in `backend/pyproject.toml` dependencies. The Vega-Lite version is passed explicitly
on every call (`vl_version="6.4"`, the newest one vl-convert 1.9 ships), so an upgrade of the wheel cannot change
the charts silently. Measured here: about 20 ms per chart, linux wheel from PyPI, no system packages.

`chart_builder` imports matplotlib only inside the functions that still use it (the radar SVG and
`render_chart_image` for the Word report), so `html_render`, `house_pptx` and `chart_builder`'s native-chart helpers
import without matplotlib.

### One module, one theme file

A new module `backend/arp/reporting/vega.py` turns a `ChartPrim` (component slides) or a `ChartSpec` plus datasets
(layout slides) into a Vega-Lite spec, and renders it to SVG (HTML) or PNG (PowerPoint picture).

`backend/arp/reporting/style/chart_theme.json` is a Vega-Lite `config` object. In it, a string value `{key}` is
replaced by `palette(tokens, mode)[key]` (keys: ground, panel, line, well, ink, muted, highlight, series_2), and
`{body}` by the first family of `tokens.fonts.body`. It sets fonts, text sizes and text colours for component and
layout charts alike; code sets none of these. Mark fills are data, not theme: component charts take them from the
`ChartPrim` series colours (as today); layout charts from `categorical_color(theme, i)` per series (pie and doughnut
per category), as today. The fonts in `style/fonts/` and in `tokens.font_dir` are registered with vl-convert once
per process, so label widths are measured with the real faces.

### The HTML chart element (component slides)

The Vega SVG replaces today's hand-drawn `<svg>` in place: same element, same `data-name`, same absolute box
(`left`, `top`, `width`, `height` in px from the `ChartPrim`), plus Vega's own `class="marks"`.

Geometry: Vega-Lite `width` and `height` are the full box (`p.w`, `p.h`), `autosize: none`, padding 0, background
none (the slide panel shows through). There are no Vega axes. Each position scale gets an explicit `domain` and
`range`: the domain is `value_range(p)` (bar, column, stacked column) or `line_scale(p)` (line); the range is the
render_model plot extent (`bar_plot_x` for bars, `column_plot_y` for columns, the `line_point` extents for lines),
and category bands are equal bands across the box as today. Category labels and data labels are Vega text layers at
the positions today's drawer uses. So bars, points and the callout boxes line up with the PowerPoint chart as they
do today.

Look, unchanged from today: bars and columns take 60% of their band; lines are 6 px for a series coloured
`highlight` and 4 px otherwise, with a filled point of radius 6 at each value; category labels `muted`, data labels
`ink`, all chart text 24 px (`CHART_LABEL`). Category labels wider than their room are cut by the text mark's
`limit`; the existing `overflow` finding still reports them.

Data marks: each bar, point or cell gets a Vega-Lite `description`, so its `aria-label` reads

    <category> | <series> | <label>

where `<label>` is the value formatted exactly as the data label: `decimals()` places over all the chart's values,
then the unit, with `−` (U+2212) for minus. A heatmap cell reads `<row> | <column> | <label>` instead. Text marks
and the line paths set `aria: false`, so the only elements with ` | ` in their `aria-label` are the data marks. Data
marks are emitted series by series, each in category order (heatmap: row by row, each in column order).

### Layout slides

`html_render` draws `slide.chart` with the same module: the same geometry rules inside the chart slot, the same
text layers, the same `aria-label` contract (labels formatted with an empty unit), no highlight. Line and area
carry the radius-6 points; scatter uses `x` formatted as the category. Kinds with no render_model geometry: pie radius 0.4 × min(w, h), centred, labels outside the arc; doughnut the
same with inner radius 0.6 × radius; area uses `value_range` (zero included) and the `column_plot_y` extent;
scatter puts both scales min to max with 10% padding (as `line_scale`) over the `LINE_PAD` plot extent.
Layout waterfall keeps today's meaning: each
row is a signed change from a running total that starts at 0, no total bar, labels signed (`+12`), fills
`categorical_color(theme, 0)`. Layout heatmap uses the heatmap rules below with `y_column` rows, `category_column`
columns and `value_column` cells.

### Component chart kinds

`Chart.kind` (in `arp/schemas/visuals.py`) becomes `bar | column | stacked_column | line | waterfall | heatmap`.
The storyline prompt and `DESIGN_GUIDE` (`style/design.md`) list the two new kinds with when to use them (waterfall:
a bridge from one total to another; heatmap: one number across two categories).

- **Waterfall** (the slide-components spec's design, AC-35 there): `category_column` and exactly 1 value column.
  The first row is the start total and the last row the end total, by position; rows between are signed changes.
  3 to 10 rows. The end total must equal the start plus the changes, rounded to the values' decimals. Each change
  bar floats from the running total before it to the one after it. Fills: totals `ink`, the step named by
  `highlight` `highlight`, other steps `series_2`. Labels: changes signed (`+4`, `−14`), totals plain (a negative
  total cannot occur, see below). Every running total, start and end included, must be at or above 0, because a
  stacked column cannot draw a bar that crosses zero; otherwise the visual is rejected so the model picks another
  kind. The checks run in this order: row count, end total, running total at or above 0. PowerPoint: a native stacked column chart, the visible series over an invisible base series,
  as slide-components AC-35 states.
- **Heatmap:** `category_column` is the column axis, `y_column` the row axis, and `value_columns[0]` (exactly one)
  the cell value; `ChartSpec.value_column` is ignored on component charts. At most 8 rows and 10 columns, each in
  first-seen dataset order. A missing (row, column) pair is an empty cell with no mark; a duplicate pair is an
  error. Cell fill runs from `ground` (lowest value) to `highlight` (highest), interpolated in RGB. Every cell shows
  its label; the label is `panel` when the value is above the midpoint of lowest and highest, else `ink`. When all
  values are equal, every cell is filled `highlight` and labelled `panel`. In the
  `ChartPrim`, `categories` are the columns and there is one `Series` per row (`name` = row label). PowerPoint: a
  picture.
- Validation order on `Chart`: the existing "a chart plots 1 to 3 value columns" check first, then the kind's own
  checks.
- The 10-category cap (`chart_capped`) stays for bar and column only, as today.
- A callout on a waterfall is placed like a column callout; on a heatmap it is not drawn.

### PowerPoint pictures

Heatmap on component slides, and waterfall and heatmap on layout slides (`ChartType.WATERFALL`,
`ChartType.HEATMAP`), are one picture: the PNG of the same Vega-Lite spec at scale 2, sized `round(2 × w)` ×
`round(2 × h)` px for a box of `w` × `h` px. Shape name as today (`chart` on component slides, `slot:<name>` on
layout slides). Layout-slide pictures move from matplotlib to Vega-Lite.

### Finding

A new lint rule `chart_picture`, one finding per slide whose chart is a picture in the PowerPoint:
`Finding(slide=i, slot="chart", stage="lint", rule="chart_picture", message="<kind> chart is a picture in the
PowerPoint: change its data in ARP and build again")`, with `<kind>` `waterfall` or `heatmap`. `lint_and_rewrite`
never sends it for rewriting.

### Tests replaced

These existing tests check today's drawers and are replaced in the slice that removes the drawer, each by the rows
named, listed in that PR's description:

- `tests/test_render_writers.py::test_html_chart_is_inline_svg` (`<rect>`, `<polyline>`): AC-1 to AC-5 (slice 1).
- `tests/test_visuals_data.py::test_bar_negative_values` (parses `<rect x=… width=…>`): AC-2 and AC-12 (slice 1).
- `tests/test_visuals_data.py::test_ac34_line`, its one HTML assertion (`stroke="#2a78d6" stroke-width="6"`): AC-11b
  (slice 1). Its PowerPoint assertions stay.
- `tests/test_reporting_html_render.py::test_chart_svg_uses_dark_ink_and_projector_sized_text` (matplotlib SVG
  format): AC-21 and AC-21b (slice 2).

## Defaults (decided here, not asked)

- Radar on layout slides keeps matplotlib in the HTML; it is the only one.
- The Word report (`report_builder`) is unchanged.
- No legend in the HTML, as today. Parity covers categories, order, values and data labels, not legends.
- Layout waterfall keeps its meaning (changes from 0, no total); only component waterfalls have start and end
  totals.
- Heatmap limits 8 × 10; waterfall 3 to 10 rows (the bar cap).
- Layout-slide labels use the same formatter with an empty unit.
- PNG scale 2 for pictures.
- Vega-Lite 6.4 pinned per call.

## Risk

`risk:normal`: changes what every PDF chart looks like, adds a runtime dependency, and touches the storyline prompt
(not `arp/llm`, so no golden-set run). Nothing in `risk:high` paths.

## Slices

| Slice | PR | Rows |
|---|---|---|
| 1 | Vega-Lite for component charts in the HTML: dependency, `vega.py`, theme file, `html_writer` | AC-1 to AC-19 |
| 2 | Layout-slide charts on Vega-Lite (HTML and the PowerPoint picture), lazy matplotlib, the `chart_picture` lint rule | AC-20 to AC-28 |
| 3 | Waterfall component kind (HTML and native PowerPoint) | AC-30 to AC-41 |
| 4 | Heatmap component kind | AC-42 to AC-52 |

Order: 1, 2, then 3 and 4 in either order (both need 1 and 2).

## Acceptance

Shared setup for the rows below, unless a row says otherwise: default tokens `load_tokens()`, light mode,
`P = palette(tokens, mode)`. "HTML" is `html_slide([prim], tokens, mode)` for a `ChartPrim` and
`render_deck_html(deck, datasets, tokens, mode)` for a deck. "PPTX" is `build_house_pptx(deck, datasets, path,
tokens, mode)` for a deck, or `pptx_slide` on a blank slide for a `ChartPrim`. "Chart svg" is the `<svg>` element
whose `data-name` is the chart's name (component) or the `<svg>` inside the chart slot (layout). "Data marks" are the
elements in the chart svg whose `aria-label` contains ` | `, in document order. "Texts" is the multiset of the text
contents of every `<text>` element in the chart svg. Colours are compared as RGB triples (hex, `rgb()` and case
ignored). A picture's "px size" is its shape's width and height in EMU divided by `tokens.emu_per_px`.

Fixture `BAR`: `ChartPrim("chart", 96, 300, 1200, 500, "bar", ["Tech", "Utilities", "Energy"],
[Series("growth", [18, 4, -2.5], [P["well"], P["highlight"], P["well"]])], "%", True)`.

Fixture `TWO(kind)`: `ChartPrim("chart", 96, 300, 1200, 500, kind, ["Q1", "Q2", "Q3"], [Series("a", [1.5, 2, 3],
[P["highlight"]] * 3), Series("b", [4, -1, 0.25], [P["series_2"]] * 3)], "", True)`.

Expected data marks for `TWO`: `Q1 | a | 1.50`, `Q2 | a | 2.00`, `Q3 | a | 3.00`, `Q1 | b | 4.00`,
`Q2 | b | −1.00`, `Q3 | b | 0.25`.

Layout deck `L(T, **kw)`: one `chart_takeaway` slide (variant `full`) with `ChartSpec(dataset_id="d", chart_type=T,
category_column="region", value_columns=["sales"])` updated by `kw` (a key in `kw` replaces the default), dataset `d` with columns `region`, `sales`, `cost` and
rows North 12 5, South 8 3, West 15 9.

Component deck `C(chart)`: one slide whose `visual` is the given `Chart`, with its dataset.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `BAR` | HTML | Exactly one `<svg` element has `data-name="chart"`; it has `class` containing `marks`, attributes `width="1200"` and `height="500"`, and a `style` declaring `left:96px`, `top:300px`, `width:1200px`, `height:500px` | holdout |
| AC-2 | `BAR` | HTML | Data marks are exactly `Tech \| growth \| 18.0%`, `Utilities \| growth \| 4.0%`, `Energy \| growth \| −2.5%`, in that order | holdout |
| AC-3 | `BAR` | HTML | Texts are exactly {`Tech`, `Utilities`, `Energy`, `18.0%`, `4.0%`, `−2.5%`} | holdout |
| AC-4 | `TWO(k)` for each k in `bar`, `column`, `stacked_column`, `line` | HTML | Data marks equal the expected list for `TWO`, in that order | holdout |
| AC-5 | `TWO("line")` | HTML | Texts are exactly {`Q1`, `Q2`, `Q3`, `a 3.00`, `b 0.25`} | holdout |
| AC-6 | `TWO(k)` for each k in `bar`, `column`, `stacked_column` | HTML | Texts are exactly {`Q1`, `Q2`, `Q3`, `1.50`, `2.00`, `3.00`, `4.00`, `−1.00`, `0.25`} | holdout |
| AC-7 | `BAR` and `TWO("line")` | HTML | Every `<text>` in the chart svg has font size 24px and a `font-family` whose first family is `Geist` | holdout |
| AC-7b | `BAR` | HTML | The 3 category labels are filled `P["muted"]` and the 3 data labels `P["ink"]` | holdout |
| AC-8 | `BAR`, dark mode (`P` = dark palette) | HTML | The category labels are filled `#a3acbb` and the data labels `#e8ebf0` | holdout |
| AC-9 | `BAR` | HTML | The chart svg contains no `<rect` element and no element filled white (`#ffffff`) | holdout |
| AC-10 | `TWO(k)` for each k in `bar`, `column`, `stacked_column`, `line` | PPTX | The chart's series names are `a`, `b`; its categories `Q1`, `Q2`, `Q3`; its values `[1.5, 2, 3]` and `[4, -1, 0.25]`: the same categories, order and numbers as AC-4's data marks (labels read with `−` as `-`) | holdout |
| AC-10b | `BAR` | PPTX | The plot's data-label number format is `0.0"%";"−"0.0"%"`, which renders 18, 4, −2.5 as the HTML labels `18.0%`, `4.0%`, `−2.5%` (must not change) | holdout |
| AC-11 | `TWO("line")` | HTML | For each data mark of a series at category i with value v, the sum of the `translate(x,y)` of the mark and of its ancestor elements inside the chart svg, plus (96, 300), is within 2 px of `line_point(prim, i, v)` | holdout |
| AC-11b | `TWO("line")` | HTML | The line of series `a` (coloured `P["highlight"]`) has stroke width 6 and the line of series `b` stroke width 4 | holdout |
| AC-12 | `TWO("column")` and `BAR` | HTML, builder's own geometry check | Each bar's centre across the band is within 2 px of the band centre the callout uses (`x + (i + 0.5) · w / n` for column, `y + (i + 0.5) · h / n` for bar); its value end is within 2 px of the `value_range` scale; `BAR`'s `Energy` bar ends at the zero line where the other two start | unit |
| AC-13 | `ChartPrim` like `BAR` with series colour `#000"><script>x()</script>` and unit `"<b>` | HTML | The output contains no `<script` and no `<b>` element (must not change) | holdout |
| AC-14 | `TWO(k)` for k = `bar`, `column`, `stacked_column`, `line` | PPTX | The `chart` shape is a native chart of type 57, 51, 52, 65 respectively (must not change) | holdout |
| AC-15 | `C(Chart(kind="column", …))` over a dataset with 12 categories | `render_slide` findings | Exactly one `chart_capped` finding (must not change) | holdout |
| AC-15b | AC-15 | HTML | The chart has 10 data marks; the last has category `Other` (must not change) | holdout |
| AC-16 | `C(Chart(kind="bar", …))`, no insight, one category `Infrastructure and utilities services` | `render_slide` findings | One `overflow` finding with slot `chart` whose message starts `ratio=` (must not change) | holdout |
| AC-17 | A deck with one component slide of each of the four kinds | HTML and PPTX | Each `chart` box in the HTML equals its PPTX shape's box within 1 px (must not change) | holdout |
| AC-18 | `chart_theme.json` with `text.fontSize` (or whichever key sets the label size in the shipped file) changed to 30 | HTML of `BAR` | Category labels are 30 px; with the shipped file they are 24 px | unit |
| AC-19 | `backend/pyproject.toml` | read | Its dependencies contain `vl-convert-python` with a lower bound of at least 1.9 and an upper bound below 2 | unit |
| AC-20 | `L(T)` for T in `bar`, `column`, `stacked_column`, `line`, `area`, `pie`, `doughnut` | `render_deck_html` | The chart slot holds one `<svg` with class `marks`, and its data marks are exactly `North \| sales \| 12`, `South \| sales \| 8`, `West \| sales \| 15` | holdout |
| AC-20b | `L("scatter", x_column="cost")` | `render_deck_html` | Data marks are exactly `5 \| sales \| 12`, `3 \| sales \| 8`, `9 \| sales \| 15` | holdout |
| AC-20c | `L("waterfall")` | `render_deck_html` | Data marks are exactly `North \| sales \| +12`, `South \| sales \| +8`, `West \| sales \| +15` (changes from 0, no total) | holdout |
| AC-20d | `L("heatmap", y_column="region", category_column="cost", value_column="sales")` | `render_deck_html` | Data marks are exactly `North \| 5 \| 12`, `South \| 3 \| 8`, `West \| 9 \| 15` | holdout |
| AC-21 | `L("bar")`, dark mode | `render_deck_html` | Every `<text>` in the chart svg has font size 24px | holdout |
| AC-21b | `L("bar")`, dark mode | `render_deck_html` | The category labels are filled `#a3acbb` (`palette(tokens, "dark")["muted"]`) | holdout |
| AC-22 | `L("radar")` | `render_deck_html` | The chart slot holds one `<svg>` (radar keeps matplotlib; must not change) | holdout |
| AC-23 | `L("waterfall")`, and separately AC-20d's deck | `build_house_pptx` | The chart slot is one picture shape named `slot:<slot name>`, no chart shape; its image's pixel width and height are each within 1 px of 2 × its px size | holdout |
| AC-24 | `Chart.model_json_schema()` | read | Its `properties` are exactly `callout`, `data`, `data_labels`, `highlight`, `insight`, `kind`, `type`, `unit` (must not change) | holdout |
| AC-25 | `ARP_CHROMIUM_PATH=/nonexistent/chrome`; `C(Chart(kind="column", data=ChartSpec(dataset_id="t", category_column="q", value_columns=["a", "b"])))`, dataset `t` rows (`q`, `a`, `b`): Q1 1.5 4, Q2 2 −1, Q3 3 0.25 | `render_deck_html` | Returns HTML with one chart svg with class `marks` whose data marks equal the expected list for `TWO` | holdout |
| AC-26 | A Python process where `import matplotlib` raises `ImportError` | `render_deck_html` on a deck with one component chart of each kind `bar`, `column`, `stacked_column`, `line` and `L(T)` slides for T in `bar`, `pie`, `scatter` (`x_column="cost"`), `waterfall` | Returns HTML with 8 chart svgs with class `marks`, no error | holdout |
| AC-27 | `L("waterfall")` | `lint_deck(deck, request)` | Exactly one finding with rule `chart_picture`: slide 0, slot `chart`, stage `lint`, message `waterfall chart is a picture in the PowerPoint: change its data in ARP and build again` | holdout |
| AC-27b | `L("pie")` | `lint_deck(deck, request)` | No finding with rule `chart_picture` | holdout |
| AC-28 | A deck whose only lint finding is `chart_picture`, an LLM stand-in that counts calls | `lint_and_rewrite` | 0 calls; the finding is returned | unit |
| AC-30 | `Chart(kind="waterfall", data=ChartSpec(dataset_id="w", category_column="step", value_columns=["v", "u"]))` | validate | Raises a validation error containing `a waterfall plots 1 value column` | holdout |
| AC-31 | `W`: `C(Chart(kind="waterfall", data=ChartSpec(dataset_id="w", category_column="step", value_columns=["v"]), highlight="Funding cost"))`, dataset `w` rows (`step`, `v`): Start 100, Funding cost −14, Fees −6, Volume 4, FX −2, End 82; unit "" | HTML | Data marks are exactly `Start \| v \| 100`, `Funding cost \| v \| −14`, `Fees \| v \| −6`, `Volume \| v \| +4`, `FX \| v \| −2`, `End \| v \| 82` | holdout |
| AC-32 | `W` | HTML | Texts are exactly {`Start`, `Funding cost`, `Fees`, `Volume`, `FX`, `End`, `100`, `−14`, `−6`, `+4`, `−2`, `82`} | holdout |
| AC-33 | `W` | HTML | The `Start` and `End` marks are filled `P["ink"]`, `Funding cost` `P["highlight"]`, the other three `P["series_2"]` | holdout |
| AC-34 | `W` | HTML, builder's own geometry check | Each change bar spans the value scale from the running total before it to the one after it (Funding cost: 100 to 86), within 2 px; Start spans 0 to 100, End 0 to 82 | unit |
| AC-35 | `W` | PPTX | A native stacked column chart whose visible series is 100, 14, 6, 4, 2, 82 over an invisible base 0, 86, 80, 80, 82, 0; first and last points `121722`, "Funding cost" `2a78d6`, the others `c4ccd7`; point labels `100`, `−14`, `−6`, `+4`, `−2`, `82` (slide-components AC-35) | holdout |
| AC-36 | `W` | `lint_deck` | No finding with rule `chart_picture` | holdout |
| AC-37 | `W` with 11 rows (Start, 9 changes, End) | `render_slide` | Raises `VisualDataError` with message `a waterfall has 3 to 10 rows (got 11)` | holdout |
| AC-37b | `W` with 2 rows (Start 100, End 100) | `render_slide` | Raises `VisualDataError` with message `a waterfall has 3 to 10 rows (got 2)` | holdout |
| AC-38 | `W` with End 80 | `render_slide` | Raises `VisualDataError` with message `waterfall end total 80 is not the start plus the changes (82)` | holdout |
| AC-39 | `C(Chart(kind="waterfall", data=ChartSpec(dataset_id="w", category_column="step", value_columns=["v"])))`, dataset `w` with exactly three rows (`step`, `v`): Start 10, Loss −30, End −20 | `render_slide` | Raises `VisualDataError` with message `a waterfall's running total must stay at or above 0 (Loss: −20)` | holdout |
| AC-40 | The storyline prompt for a request | build the prompt | It names the chart kinds as `bar, column, stacked_column, line, waterfall or heatmap` | unit |
| AC-41 | A storyline slide with `visual="chart"`, `chart_kind="waterfall"`, and a model stand-in returning `W`'s visual | slide fill | The filled slide's visual has kind `waterfall` and no fill error | unit |
| AC-42 | `Chart(kind="heatmap", data=ChartSpec(dataset_id="h", category_column="day", value_columns=["commits"]))` (no `y_column`) | validate | Raises a validation error containing `a heatmap needs y_column` | holdout |
| AC-43 | `Chart(kind="heatmap", data=ChartSpec(dataset_id="h", category_column="day", y_column="pkg", value_columns=["commits", "x"]))` | validate | Raises a validation error containing `a heatmap plots 1 value column` | holdout |
| AC-44 | `H`: `C(Chart(kind="heatmap", data=ChartSpec(dataset_id="h", category_column="day", y_column="pkg", value_columns=["commits"])))`, dataset `h` rows (`pkg`, `day`, `commits`): api Mon 3, api Tue 5, cli Mon 1, cli Tue 0 | HTML | Data marks are exactly `api \| Mon \| 3`, `api \| Tue \| 5`, `cli \| Mon \| 1`, `cli \| Tue \| 0` | holdout |
| AC-45 | `H` | HTML | Texts are exactly {`api`, `cli`, `Mon`, `Tue`, `3`, `5`, `1`, `0`} | holdout |
| AC-46 | `H` | HTML | The `cli \| Tue \| 0` mark is filled `P["ground"]` and the `api \| Tue \| 5` mark `P["highlight"]` | holdout |
| AC-47 | `H` | HTML | The labels `3` and `5` are filled `P["panel"]`, `1` and `0` `P["ink"]` | holdout |
| AC-47b | `H` with all four values 2 | HTML | Every cell mark is filled `P["highlight"]` and every label `P["panel"]` | holdout |
| AC-48 | `H` without the row cli Tue | HTML | Exactly 3 data marks; none reads `cli \| Tue \| …` | holdout |
| AC-49 | `H` over 9 distinct `pkg` values and 2 days | `render_slide` | Raises `VisualDataError` with message `a heatmap shows at most 8 rows and 10 columns (got 9 × 2)` | holdout |
| AC-50 | `H` plus a row api Mon 4 | `render_slide` | Raises `VisualDataError` with message `duplicate heatmap cell (api, Mon)` | holdout |
| AC-51 | `H` | PPTX | One picture named `chart` and no chart shape; its image's pixel width and height are each within 1 px of 2 × its px size | holdout |
| AC-52 | `H` | `lint_deck` | One `chart_picture` finding for that slide with message `heatmap chart is a picture in the PowerPoint: change its data in ARP and build again` | holdout |

Must not change: escaping of template-supplied colours and units (AC-13), the native PowerPoint chart types and
label formats (AC-10b, AC-14), the 10-category cap (AC-15, AC-15b), the label overflow finding (AC-16), the
HTML/PPTX chart box (AC-17), the `Chart` fields (AC-24), radar on layout slides (AC-22).

Earlier rows: `2026-11-15-slide-components-design.md` AC-35 (native waterfall) is built here unchanged as AC-35; no
earlier row is retired.
