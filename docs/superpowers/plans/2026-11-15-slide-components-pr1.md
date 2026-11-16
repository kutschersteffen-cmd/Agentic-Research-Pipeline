# Slide Components (PR 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New house decks are built from typed visuals, laid out by one render model and drawn identically to HTML/PDF and editable PPTX, with a fit ladder, design checks, deck settings and a review sheet.

**Architecture:**

- Each slide with a `visual` becomes a `list[Primitive]` (`render_model.render_slide`). Two thin writers draw that list; slides without a visual keep the legacy renderer.
- The fit ladder and design checks read the same primitives.
- The storyline plans sections and visuals; code assembles cover → sections → next steps.

**Tech Stack:** Python 3.13, pydantic, python-pptx, Playwright/Chromium, Pillow, FastAPI, typer. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-15-slide-components-design.md` (approved 2026-11-15). This plan covers PR 1 only. AC-n refers to the spec's Acceptance table.

## Global Constraints

- **Canvas and zones:**
  - canvas 1920×1080, margins 96;
  - zones y: label 64–88, title 104–232, subtitle 248–288, body 328–920, source 952–1000.
- **Spacing:** gaps and paddings come only from 4, 8, 12, 16, 24, 32, 40, 48, 64, 96 (constants in `render_model.py`).
- **Strip:** five 12×12 squares with 4 px gaps at y 64, x 96–160. Square 3 is `highlight`, the rest `ink`. Under a frame, the strip's top is 40 px above the frame headline box top, at its left edge.
- **Colours:** `graphite` and `graphite_dark` exactly as in the spec's Colours table. The legacy colour keys stay untouched. Never use `ea4c14 85601a d4a650 13804f c8323f 4fd69c ff6b7a 2563c9`.
- **Text:** never smaller than 18 px. Highlight is a fill only. ▲/▼ deltas use the text colour.
- **Field limits:** validation rules on what the AI returns. Overflow within those limits belongs to the fit ladder.
- **Headlines:** the approved headline and `subheading` are never rewritten by the ladder.
- **PPTX scale:** 9525 EMU/px without a frame, `slide_width_emu/1920` with one.
- **Legacy paths unchanged:**
  - stored decks without `visual`;
  - `deck_from_plan` (classic reports);
  - the stewardship client report.
- **Repo rules:**
  - `ruff check .`;
  - after model changes: `python scripts/export_openapi.py`, then `npm run gen:api`, then `npx tsc -b`; commit both generated files;
  - list every changed existing test in the PR description;
  - PR body has `Spec: slide-components-design` and `Rows: AC-1, …` (this plan's rows plus AC-51; see Task 8).

## Review Focus

1. **A dataset column holding text** where the chart expects numbers. Expect a `bad_reference` finding and a `points` fallback, not a crash. Test in Task 5: `test_chart_non_numeric_column_falls_back`.
2. **Negative values in bar/column charts** (e.g. EPS −1). Bars grow left/down from a zero line, and labels show `−1`. Task 5: `test_bar_negative_values`.
3. **Dark mode** of every PR-1 visual keeps contrast. Task 7 runs `design_checks` on the sheet in dark mode (`test_sheet_dark_has_no_contrast_findings`).
4. **A stored deck saved before this change** (no `visual`, no `kicker`) still loads and re-renders. Task 1: `test_old_deck_json_loads`. Task 3: AC-22.
5. **Unicode in labels** (`−`, `€`, `▲`) survives into the PPTX runs and the HTML. Task 4: `test_unicode_text_round_trip`.

---

### Task 1: Models, tokens and deck settings

**Files:**
- Create: `backend/arp/schemas/visuals.py`
- Modify: `backend/arp/schemas/reporting.py` (`SlideContent`, `StorylineSlide`, `Storyline`, `ReportRequest`, `Finding.rule` if typed)
- Modify: `backend/arp/reporting/style/tokens.json`, `backend/arp/reporting/house_style.py` (`Tokens`)
- Test: `backend/tests/test_visuals_models.py`

**Interfaces:**

Produces in `arp/schemas/visuals.py`:

- **Visual models** (pydantic, limits exactly as the spec's Visual calls table):
  - `Cover`, `Section`, `KpiRow(tiles: list[Tile], emphasis: int | None)`;
  - `Chart(data: ChartSpec, kind: Literal["bar","column","stacked_column","line"], unit: str, data_labels: bool = True, highlight: str | None, callout: Callout | None, insight: Insight | None)`;
  - `ComparisonTable(table: TableSpec, highlight_column: str | None, total_row: dict[str, Literal["sum","mean","none"]])`;
  - `TwoColumn`, `Points(points, emphasis)`, `NextSteps(actions, emphasis=0)`.
- **Union:** `Visual = Annotated[Cover | Section | KpiRow | Chart | ComparisonTable | TwoColumn | Points | NextSteps, Field(discriminator="type")]`.
- **Friendly names:** `FRIENDLY_NAMES: dict[str, str]`, e.g. `{"kpi_row": "KPI row", "chart": "Chart", ...}`.

Produces in `arp/schemas/reporting.py`:

- `DeckSettings(profile="committee", purpose="recommendation", detail="balanced", max_slides=12)`, with `max_slides` 3–25;
- `ReportRequest.deck: DeckSettings`;
- `SlideContent`:
  - new fields `kicker=""`, `visual: Visual | None = None`, `source_line=""`, `needs_review=False`;
  - `layout`/`variant` default `""`;
- `StorylineSlide`: `visual: str | None = None`, `chart_kind: str | None = None`, `rationale=""`, `section: int | None = None`, `kicker=""`;
- `Storyline`: `answer=""`, `figures=[]`, `sections: list[SectionPlan] = []`, `closing: list[NextAction] = []`.

Produces in `house_style.py`: `Tokens.graphite: dict[str, str]` and `Tokens.graphite_dark: dict[str, str]`.

- [ ] **Step 1: Write failing tests**
  - `test_limits_enforced`: `KpiRow` with 5 tiles raises `ValidationError`, and a label of 6 words raises.
  - `test_emphasis_out_of_range_is_valid`: `KpiRow(tiles=4 tiles, emphasis=7)` validates. Dropping it is Task 8's job.
  - `test_old_deck_json_loads`: a `Deck` JSON from `main` (`layout`/`variant`/`slots` only) validates with `visual is None`.
  - `test_deck_settings_defaults`: `ReportRequest(title="T", qualitative_notes="n").deck` equals `committee/recommendation/balanced/12`.
  - `test_graphite_tokens`: `load_tokens().graphite["ink"] == "#121722"`, `graphite_dark["panel"] == "#141921"`, and the legacy `color.accent` is unchanged at `"#ea4c14"`.
- [ ] **Step 2:** `cd backend && python3 -m pytest tests/test_visuals_models.py -q` → FAIL.
- [ ] **Step 3:** Implement the models, fields and the two token keys with the spec's values.
- [ ] **Step 4:** Run the file → PASS. Run `tests/test_reporting_house_service.py tests/test_reporting_storyline.py -q` → PASS (existing). Run `python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b`.
- [ ] **Step 5:** Commit `feat(reporting): visual models, deck settings, graphite tokens`.

### Task 2: Render model core (primitives, anatomy, source line)

**Files:**
- Create: `backend/arp/reporting/render_model.py`
- Test: `backend/tests/test_render_model.py`

**Interfaces:**

Consumes: Task 1 models and tokens.

Produces in `render_model.py`:

- **Primitives:** `Rect(name, x, y, w, h, fill, line=None, line_w=0, emphasis=False)`; `Text(name, x, y, w, h, text, size, weight, family, color, align="left", anchor="top", fill_under=None, outline=False)`; `Line(name, points, color, width, arrow=False)`; `ChartPrim(name, x, y, w, h, kind, categories, series: list[Series], unit, labels: bool)`; `TablePrim(name, x, y, w, h, header, rows, total, highlight_col, style)`. All are frozen dataclasses with `emphasis: bool = False`.
- **Main function:** `render_slide(slide: SlideContent, index: int, deck: Deck, tokens: Tokens, datasets: dict[str, QuantitativeDataset], mode: Mode = "light") -> list[Primitive]`.
- **Anatomy:** `anatomy(slide, index, tokens, mode) -> list[Primitive]` draws the strip, kicker, title, subheading, source rule and text, and the page number. It honours `tokens.frame`, and leaves out the source line (appending to the notes instead) when the frame body ends below y 928.
- **Body box:** `body_box(tokens) -> Box`, the zone 96, 328, 1728, 592, or the frame body box.
- **Source line:** `source_line(slide: SlideContent, datasets) -> str`, following the spec's rule exactly.
- **Dispatch:** a `VISUALS: dict[str, Callable[[visual, Box, ctx], list[Primitive]]]` registry, filled in Tasks 4–5.

Steps:

- [ ] **Step 1: Write failing tests** (a slide with `visual=Points(...)`, rendered through `render_slide`):
  - `test_ac2_strip`: five `Rect`s `strip:1..5`, 12×12, y 64, x 96..160; `strip:3` fill `#2a78d6`.
  - `test_ac3_title_and_source_zones`: `title` y 104, h 128; `source` within 952–1000.
  - `test_ac4_source_line`: `source_refs=["eps"]` and dataset name "EPS growth 2025" gives `"Source: EPS growth 2025"`. A table slice gives `", rows 2–4"`. A non-dataset ref appears as written.
  - `test_ac20_frame_strip`: with `with_frame(...)` from the template-frame fixture, `title` equals the frame headline box and `strip:1` has x 144, y 32.
  - `test_ac30_source_to_notes`: a frame body ending at 1040 means no `source` primitive. Task 3 checks the notes.
- [ ] **Step 2:** `python3 -m pytest tests/test_render_model.py -q` → FAIL.
- [ ] **Step 3:** Implement as in Interfaces.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(reporting): render model core and slide anatomy`.

### Task 3: Writers (HTML and PPTX) and dispatch

**Files:**
- Create: `backend/arp/reporting/html_writer.py`, `backend/arp/reporting/pptx_writer.py`
- Modify: `backend/arp/reporting/html_render.py` (`render_deck_html`), `backend/arp/reporting/house_pptx.py` (`build_house_pptx`)
- Test: `backend/tests/test_render_writers.py`

**Interfaces:**

Consumes: `render_slide`, primitives.

Produces:

- `html_slide(prims, tokens, mode) -> str`: absolutely positioned elements with `data-name`; charts as inline SVG drawn from `ChartPrim`.
- `pptx_slide(slide_obj, prims, tokens, mode, emu_per_px)`:
  - native shapes named after the primitive;
  - `ChartPrim` becomes a native chart (bar/column clustered, stacked column, line with markers), with per-point fills and number format `0"<unit>"`;
  - `TablePrim` becomes a native table, with borders via `a:lnT`/`a:lnB` XML;
  - `Line` becomes a freeform (`close=False`, no fill), with an arrowhead via `a:tailEnd`.
- **Dispatch:** `render_deck_html` and `build_house_pptx` send slides with a `visual` to the writers, and slides without one to today's code, unchanged. When there is no source line, the notes get `source_line` appended (newline unless the notes are empty).

Steps:

- [ ] **Step 1: Write failing tests**
  - `test_ac1_boxes_match`: for a `Points` slide, every primitive's HTML `getBoundingClientRect()`, relative to its `section.slide` (Chromium via `browser._page`), equals the PPTX shape box (EMU/9525) within ±1.
  - `test_ac30_notes`: completes Task 2's case; the notes end with `Source: EPS growth 2025`.
  - `test_ac22_legacy_unchanged`: `tests/fixtures/stress_deck.py` built before and after gives identical `(name, left, top, width, height, font)` per shape. Capture the "before" values by running the test once against `main` and committing them to `tests/golden/legacy_stress_shapes.json`.
  - `test_ac23_classic_and_stewardship`: `deck_from_plan` output and `client_report` output contain `slot:*` shapes.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the new file plus `tests/test_reporting_house_pptx.py tests/test_reporting_html_render.py tests/test_stewardship_client_report.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(reporting): html and pptx writers for primitives`.

### Task 4: Text visuals: cover, section, KPI row, two columns, points, next steps

**Files:**
- Create: `backend/arp/reporting/visuals/{cover,section,kpi_row,two_column,points,next_steps}.py`
- Test: `backend/tests/test_visuals_text.py`

**Interfaces:**

- Each module registers `render(visual, box: Box, ctx: RenderCtx) -> list[Primitive]` into `render_model.VISUALS[type]`.
- `RenderCtx` carries `tokens`, `mode`, `deck`, `index` and `type_step: int = 0` (0, 1 or 2; Task 8 raises it).
- Layout values come from the spec table and the mockups `0-cover`, `1-section`, `2-kpi_row`, `6-two_column` and `7-next_steps`.
- Type sizes per step:

  | Role | Step 0 | Step 1 | Step 2 |
  |---|---|---|---|
  | KPI value | 144 | 112 | 96 |
  | Body | 28 | 24 | 24 |
  | Titles | 36 | 30 | 30 |

Steps:

- [ ] **Step 1: Write failing tests**
  - `test_ac5_kpi_tiles`: `kpi:tile:1..4` have w 414 and x 96, 534, 972, 1410. Tile 1 has fill `#121722`, `emphasis` true, and its value `Text` colour `#ffffff`. The others have fill `#f4f6f9`.
  - `test_ac15_dark`: in dark mode, tile 1 fill is `#e8ebf0` with value colour `#141921`.
  - `test_next_steps_rows_centred`: the row stack is vertically centred in 328–920 (±2).
  - `test_unicode_text_round_trip`: `−7 pts`, `€12m` and `▲ 2 pts` appear unchanged in the PPTX runs and the HTML text.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the six renderers.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(reporting): text visuals`.

### Task 5: Charts and comparison table

**Files:**
- Create: `backend/arp/reporting/visuals/chart.py`, `backend/arp/reporting/visuals/table.py`
- Test: `backend/tests/test_visuals_data.py`

**Interfaces:**

- **`chart`** renders with or without the insight card (520 px card, 48 px gap). It draws no axes or grid.
  - Value labels are `ink`, placed beside bars and at line ends.
  - Bars default to `well`; the `highlight` category or series is `highlight`; the second series is `series_2`.
  - Over 10 categories (bar/column): top 9 by value plus "Other" (their sum), and a finding `chart_capped`.
  - The finding is returned through `ctx.findings.append(Finding(...))`; `RenderCtx` gains `findings: list[Finding]`.
- **`comparison_table`:**
  - text columns are left-aligned, numbers right-aligned in mono;
  - the highlighted column gets an `ink` header with `ground` cells at weight 600;
  - `total_row`: a sum is rounded to the most decimals any value in that column has as written; a mean is rounded to 1 decimal.

Steps:

- [ ] **Step 1: Write failing tests**
  - `test_ac6_bar_insight`: a native bar chart with 6 points; "Utilities" `2a78d6`, the others `eaeef3`; number format ends in `%`; `card:insight` w 520, fill `f4f6f9`.
  - `test_ac8_totals`: on the `names` fixture, the total row reads `6.5`, `4.4`, `4.9`; the "Net debt / EBITDA" header fill is `121722`.
  - `test_ac32_cap`: 14 categories give 10 points, the last "Other" = sum of the 5 smallest, and one `chart_capped` finding.
  - `test_ac34_line`: on `eps_q`, a native line chart with 2 series × 8; `utilities` line `2a78d6`, `market` `c4ccd7`; a `callout` primitive at Q3 24.
  - `test_bar_negative_values`: value −1 draws to the left of the zero line, labelled `−1`.
  - `test_chart_non_numeric_column_falls_back`: a value column of strings raises `VisualDataError`. Task 8 turns that into `bad_reference` plus a `points` fallback.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(reporting): chart and comparison table visuals`.

### Task 6: Design checks

**Files:**
- Create: `backend/arp/reporting/design_checks.py`
- Test: `backend/tests/test_design_checks.py`

**Interfaces:**

- `check_slides(slides: list[list[Primitive]], tokens, mode="light") -> list[Finding]`, with stage `fit`.
- `design_checks(deck, datasets, tokens=None, mode="light") -> list[Finding]`.
- Rules, exactly as in the spec:
  - `underfill`: the span of all body primitives is under 296 px;
  - `small_text`: text under 18 px;
  - `low_contrast`: a filled `Text` against `fill_under` is under 4.5:1, or under 3:1 at 48 px and up;
  - `emphasis_count`: more than one `emphasis`.
- Contrast is computed with the WCAG relative luminance formula.

Steps:

- [ ] **Step 1: Write failing tests** `test_ac11_underfill`, `test_ac14_emphasis_count`, `test_ac25_small_text` and `test_ac26_low_contrast` (`#aab4c3` on `#ffffff`), each asserting exactly one finding with that rule.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(reporting): design checks`.

### Task 7: Review sheet, CLI and goldens

**Files:**
- Create: `backend/arp/reporting/sheet.py`, `backend/tests/test_slide_sheet.py`, `backend/tests/golden/slides/*.png`
- Modify: `backend/arp/cli/reporting.py` (new `sheet` command)

**Interfaces:**

- `sheet_deck() -> tuple[Deck, list[QuantitativeDataset], str]` builds slides 0–8, using the spec's fixtures and texts. Slide 4 is a `Points` slide carrying the four step titles.
- `arp report sheet --out DIR` writes `0-cover.png` … `8-line.png` and `sheet.png`, each 1920×1080, via `write_pngs(scale=1)`.

Steps:

- [ ] **Step 1: Write failing tests**
  - `test_ac18_cli`: through typer `CliRunner`, exit 0, 9 named PNGs plus `sheet.png`, each 1920×1080.
  - `test_ac12_sheet_clean`: `design_checks` on the sheet returns no `underfill`, `small_text`, `low_contrast` or `emphasis_count` finding.
  - `test_sheet_dark_has_no_contrast_findings`: the same in dark mode.
  - `test_ac24_no_reserved_colours`: across PPTX XML and HTML computed colours, light and dark, none of the 8 hexes appears.
  - `test_ac1_sheet_boxes_match`: Task 3's check over the whole sheet.
  - `test_sheet_matches_goldens`: per PNG, at most 0.5% of pixels differ by more than 16 in any channel, compared with Pillow `ImageChops.difference`.
  - **AC-19:** set `graphite.ink` to `#000000` and the golden test fails. Done once by hand; record it in the ledger.
- [ ] **Step 2:** Generate the goldens with `arp report sheet --out tests/golden/slides`. Look at each PNG against `docs/superpowers/specs/assets/slide-components/` and fix layout bugs before committing them.
- [ ] **Step 3:** Run all tests → PASS.
- [ ] **Step 4:** Commit `feat(reporting): review sheet, CLI and goldens`.

### Task 8: Fill, fit ladder, needs-review gate

**Files:**
- Modify: `backend/arp/reporting/slide_fill.py`, `fit.py`, `browser.py`, `lint.py`, `house_pipeline.py`, `backend/arp/api/routers/reporting.py`
- Test: `backend/tests/test_fit_ladder.py`

**Interfaces:**

- **`fill_slide`:**
  - for storyline slides with `visual` set, asks for `SlideContent` with that visual type;
  - drops an invalid `emphasis` to `None` with a `bad_reference` finding;
  - after one failed retry, or on a `VisualDataError`, builds `Points` from the headline and rationale with a `bad_reference` finding.
- **Lint:** `lint._texts` yields every text field of a visual (tile values, labels, deltas, insight stat, points…), so `number_not_in_source` covers them.
- **`fit_ladder(deck, request, llm, tokens, usage) -> tuple[Deck, list[Finding]]`**, in `fit.py`. Steps per spec:
  1. shorten (visual text only);
  2. `type_step` 1 and 2;
  3. switch (the spec's table; it needs the item count to qualify);
  4. split: halves, the first takes the extra item; kickers ` 1/2` and ` 2/2`; each half runs 1–3 again;
  5. `needs_review`.

  Findings: `shortened`, `type_step`, `switched`, `split`, `needs_review`. Underfill gets a step-up (`type_step = -1`, i.e. one size larger) and centring, then the `underfill` finding if still under 50%.
- **`browser.measure`:** on visual slides, reports only `overflow` and `overflow_x`.
- **Router:**
  - `download_report` returns 409 `Slide <n> needs review` (1-based, the first flagged slide) while any slide has `needs_review`;
  - `POST /api/reports/{id}/slides/{n}/approve` clears it. This brings AC-51 into PR 1; see the Ruling below.

Steps:

- [ ] **Step 1: Write failing tests** (stand-in `fake_llm`, `build_house_deck`):
  - `test_ac9_visual_numbers_linted`;
  - `test_ac10_emphasis_dropped`;
  - `test_ac27_switch_to_table` (frame fixture with body box 900 px wide);
  - `test_ac28_split`;
  - `test_ac31_needs_review_blocks_download`;
  - `test_ac51_approve_unblocks`;
  - `test_ac53_shortened`;
  - `test_ac54_points_fallback`.

  Each asserts exactly what its AC row states.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run, plus `tests/test_reporting_fit.py tests/test_reporting_house_service.py tests/test_reporting_lint.py tests/test_reporting_slide_fill.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(reporting): fit ladder and review gate`.

**Ruling:** AC-51 (approve) moves from PR 3 into PR 1. Without it, PR 1's download gate would have no way out. Record this in the PR.

### Task 9: Deck settings, storyline and deck assembly

**Files:**
- Create: `backend/arp/reporting/style/design.md`
- Modify: `backend/arp/reporting/storyline.py`, `slide_fill.py` (prompt), `house_pipeline.py`
- Test: `backend/tests/test_deck_assembly.py`

**Interfaces:**

- **Storyline prompt:** names `request.deck.profile`, `purpose`, `detail`, the PR 1 content types `kpi_row, chart, comparison_table, two_column, points`, and includes the full `design.md`.
- **`build_house_deck`:** assembles the deck as cover (from `answer`/`figures`) → per section: `Section` + its slides → `NextSteps` from `closing`.
  - `agenda` is filled from the section titles.
  - Content slides beyond `max_slides` (8 for `executive`) are dropped, with `profile_cap`.
- **`design.md`:** one line per content type saying which claim it fits, plus the emphasis rule (≤12 lines).

Steps:

- [ ] **Step 1: Write failing tests** `test_ac16_prompt`, `test_ac17_order` and `test_ac33_profile_cap`, as their rows state.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(reporting): deck settings and deck assembly`.

### Finish

- [ ] Full checks:
  - `cd backend && ruff check . && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python3 -m pytest tests/test_reporting_*.py tests/test_visuals_*.py tests/test_render_*.py tests/test_design_checks.py tests/test_fit_ladder.py tests/test_deck_assembly.py tests/test_slide_sheet.py tests/test_stewardship_client_report.py -q`;
  - frontend: `npm run lint && npx tsc -b && npm test`.
- [ ] Mark the superseded template-frame hidden tests (spec list) in the PR description, so they are retired.
- [ ] Run `/ponytail:ponytail-review` and `/code-review`, and fix confirmed findings.
- [ ] Open a PR against `main`:
  - label `risk:normal`;
  - `Spec: slide-components-design`;
  - `Rows:` AC-1–6, 8–12, 14–28, 30–34, 51, 53, 54;
  - list every changed existing test.
- [ ] Say that `openwiki/` needs an update (house deck pipeline).
