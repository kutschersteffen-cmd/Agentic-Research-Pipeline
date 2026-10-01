# Automated Decks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A brief goes in, and a house-styled PDF plus an editable `.pptx` comes out. The text fits every
slide and reads like a person wrote it. The only manual step is approving the storyline.

**Architecture:** The code adds a new `house_deck` output format beside the existing pptx/docx/pdf paths in
`backend/arp/reporting/`. The flow is: LLM storyline → human approval → per-slide LLM fill → deterministic lint +
targeted rewrite → Jinja HTML render in headless Chromium with measured fit → one vision QA pass → PDF (Chromium)
and PPTX (python-pptx, positions computed from the same grid). One `tokens.json` and one `layouts.json` drive both renderers.

**Tech Stack:** Python 3.11, Pydantic 2, Jinja2 (already installed), Playwright for Python + Chromium, python-pptx,
matplotlib (SVG charts), FastAPI, React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-30-automated-decks-design.md`

## Global Constraints

- Every number on a slide traces to the notes, datasets or pipeline adapters. The lint rule `number_not_in_source` enforces this.
- Stewardship decks never get model-written text. They enter through `deck_from_plan`, which calls no LLM.
- Canvas is 16:9, 1920×1080 CSS px. The grid has 12 columns. The type scale has exactly 5 sizes: `headline, subhead, body, caption, big_number`.
- Font size never shrinks to fit. Overflow is fixed in this order: shorten, then a roomier variant, then split.
- The fit loop runs at most 3 passes per slide, lint rewrite at most 2 rounds, and visual QA exactly 1 round.
- Nothing fails silently. Leftovers are `Finding`s written to `reports/<id>/findings.json` and shown in the UI.
- A missing Chromium is a hard error with an install hint. There is no fallback to the old renderer.
- English only. Existing `test_reporting_*` tests stay green. `ruff check .` stays clean.
- Existing pptx/docx/pdf paths and template ingestion are unchanged.

## Review Focus

1. **A single word longer than its slot's width,** such as a URL or a long company name. It must be reported as overflow, never clipped silently. The test goes in Task 2.
2. **Numbers written differently from the source:** "12%" against source `0.12`, "1.2bn" against `1200000000`, "1,234" against `1234.0`. These must not be flagged. The test goes in Task 5.
3. **A split that doesn't help.** When a slide's list is split and the halves still overflow, the loop must stop at the pass cap and report. It must not split forever. The test goes in Task 6.
4. **A storyline edited to 0 slides, or approved twice.** The API rejects both with 409/422 and never renders an empty deck. The test goes in Task 4.
5. **LLM-written text containing `<script>`, `&` or `{{ }}`.** It must render as literal text in HTML, PDF and PPTX. The test goes in Task 2.

---

## File map

All paths are under `backend/` unless noted.

| File | Responsibility |
|---|---|
| `arp/schemas/reporting.py` (modify) | New models: `SlideContent`, `Deck`, `Storyline`, `StorylineSlide`, `Finding`, `RunRef`; `OutputFormat.HOUSE_DECK`; `ReportStatus.STORYLINE_READY`; `ReportRequest.goal`, `.run_refs`; `ReportManifest.output_files` |
| `arp/reporting/style/tokens.json` | design tokens (the single style source) |
| `arp/reporting/style/layouts.json` | layout → variants → slots with limits |
| `arp/reporting/style/writing.md` | writing style guide injected into prompts |
| `arp/reporting/style/fonts/` | two OFL fonts (woff2 for HTML, ttf kept for reference) |
| `arp/reporting/style/templates/` | `base.html.j2`, `deck.css.j2`, one `<layout>.html.j2` per layout |
| `arp/reporting/house_style.py` | load + validate tokens/layouts; grid → slot rects |
| `arp/reporting/html_render.py` | `Deck` → HTML string (Jinja, autoescape) |
| `arp/reporting/browser.py` | Playwright: measure fit, write PDF, write PNGs |
| `arp/reporting/deck_compat.py` | `ReportPlan` → `Deck` (legacy + stewardship entry, no LLM) |
| `arp/reporting/storyline.py` | LLM call 1: storyline |
| `arp/reporting/slide_fill.py` | LLM call per slide + reference validation + `rewrite_slot` |
| `arp/reporting/lint.py` | deterministic writing rules |
| `arp/reporting/fit.py` | shorten → roomier → split loop |
| `arp/reporting/visual_qa.py` | one vision pass |
| `arp/reporting/house_pptx.py` | `Deck` → `.pptx` from grid rects |
| `arp/reporting/adapters.py` | pipeline outputs → `QuantitativeDataset`s |
| `arp/reporting/house_pipeline.py` | orchestrates fill → lint → fit → QA → outputs |
| `arp/reporting/service.py`, `arp/storage/reporting_store.py`, `arp/api/routers/reporting.py`, `arp/cli/reporting.py` (modify) | wiring |
| `arp/llm/base.py`, `arp/llm/langchain_client.py`, `tests/conftest.py` (modify) | optional `images` on `complete_structured` |
| `tests/fixtures/stress_deck.py` | max/min content deck for every layout and variant |
| `frontend/src/pages/ReportBuilder.tsx`, `frontend/src/api/client.ts` (modify) | storyline editor + approve + findings |
| `.github/workflows/ci.yml` (modify) | install Chromium for pytest |

---

### Task 1: Schemas and the house-style loader

**Files:**
- Modify: `arp/schemas/reporting.py`
- Create: `arp/reporting/house_style.py`, `arp/reporting/style/tokens.json`, `arp/reporting/style/layouts.json`
- Test: `tests/test_reporting_house_style.py`

**Interfaces:**
- Produces (schemas):
  - `SlideContent(headline: str, layout: str, variant: str, slots: dict[str, str | list[str]] = {}, chart: ChartSpec | None = None, table: TableSpec | None = None, image_path: str | None = None, speaker_notes: str = "", source_refs: list[str] = [])`
  - `Deck(title: str, subtitle: str = "", slides: list[SlideContent])`
  - `StorylineSlide(headline: str, purpose: str, source_refs: list[str] = [])`
  - `Storyline(title: str, subtitle: str = "", slides: list[StorylineSlide], approved: bool = False)`
  - `Finding(slide: int, slot: str | None, stage: Literal["data","lint","fit","qa"], rule: str, message: str)`
  - `RunRef(kind: Literal["decision","run"], ref_id: str)`
  - `OutputFormat.HOUSE_DECK = "house_deck"`, `ReportStatus.STORYLINE_READY = "storyline_ready"`
  - `ReportRequest.goal: str = ""`, `ReportRequest.run_refs: list[RunRef] = []`, `ReportManifest.output_files: list[str] = []`
- Produces (`house_style.py`):
  - `Tokens` (pydantic; fields: `canvas: {width:int, height:int}`, `grid: {columns:int, margin_x:int, margin_top:int, margin_bottom:int, gutter:int, headline_band:int, footer_band:int}`, `type: dict[str, {size:int, line_height:float, weight:int, font:str}]` with exactly the 5 keys, `color: {ink, ink_muted, neutral, accent, background, categorical: list[str]}`, `fonts: {heading:str, body:str}`)
  - `SlotSpec(name: str, kind: Literal["text","list","number","chart","table","image"], col: int, span: int, row: int, rows: int, max_words: int | None, max_items: int | None, type_role: str)`. `row`/`rows` count 12 body rows.
  - `VariantSpec(id: str, slots: list[SlotSpec], roomier: str | None)`, `LayoutSpec(id: str, purpose: str, variants: list[VariantSpec])`
  - `load_tokens() -> Tokens`, `load_layouts() -> dict[str, LayoutSpec]` (both `functools.cache`)
  - `slot_rect(tokens: Tokens, slot: SlotSpec) -> Rect`, with `Rect = NamedTuple(x, y, w, h)` in px
  - `get_variant(layout: str, variant: str) -> VariantSpec` (raises `KeyError` with a readable message)

- [ ] **Step 1: Write the failing tests**

```python
def test_layouts_cover_spec_library():
    assert set(load_layouts()) == {"title","section","big_number","chart_takeaway","two_column","table",
                                   "bullets","timeline","quote","matrix","image","summary"}

def test_type_scale_has_exactly_five_sizes():
    assert set(load_tokens().type) == {"headline","subhead","body","caption","big_number"}

def test_every_slot_rect_inside_canvas_and_slots_disjoint():
    t = load_tokens()
    for layout in load_layouts().values():
        for v in layout.variants:
            rects = [slot_rect(t, s) for s in v.slots]
            for r in rects:
                assert r.x >= t.grid.margin_x and r.x + r.w <= t.canvas.width - t.grid.margin_x
                assert r.y >= t.grid.margin_top + t.grid.headline_band
                assert r.y + r.h <= t.canvas.height - t.grid.margin_bottom - t.grid.footer_band
            assert not any(_overlap(a, b) for a, b in itertools.combinations(rects, 2)), (layout.id, v.id)

def test_roomier_points_to_existing_variant_of_same_layout():
    for layout in load_layouts().values():
        ids = {v.id for v in layout.variants}
        assert all(v.roomier in ids | {None} for v in layout.variants)

def test_text_slots_declare_word_limits():
    for layout in load_layouts().values():
        for v in layout.variants:
            for s in v.slots:
                if s.kind in ("text", "list"):
                    assert s.max_words, (layout.id, v.id, s.name)
                if s.kind == "list":
                    assert s.max_items

def test_get_variant_unknown_raises_readable_keyerror():
    with pytest.raises(KeyError, match="bullets/seven"):
        get_variant("bullets", "seven")
```

- [ ] **Step 2: Run** `cd backend && pytest tests/test_reporting_house_style.py -q`. Expected: FAIL (ImportError).
- [ ] **Step 3: Add the schema models above to `arp/schemas/reporting.py`.** Put them after `ReportPlan`, with defaults exactly as listed.
- [ ] **Step 4: Write `tokens.json` with a neutral placeholder direction.** Use body 28px, headline 56px, subhead 36px, caption 20px, big_number 160px, margins 96px, gutter 32px, headline band 180px, footer band 56px. Take the categorical colours from `design.CATEGORICAL_PALETTE`. Task 3 replaces the look but keeps the keys.
- [ ] **Step 5: Write `layouts.json` with the 12 layouts and the variants from the spec table.** Variant ids: `title/{plain,key_figure}`, `section/{default}`, `big_number/{one,two,three}`, `chart_takeaway/{chart_left,chart_right,full}`, `two_column/{text_text,text_chart}`, `table/{compact,highlight}`, `bullets/{three,five}` (three.roomier = five), `timeline/{three,six}`, `quote/{default}`, `matrix/{default}`, `image/{default}`, `summary/{default}`. `chart_left.roomier = full`; `chart_right.roomier = full`.
- [ ] **Step 6: Implement `house_style.py`.** `slot_rect`: column width = `(canvas.width - 2*margin_x - 11*gutter)/12`. Row height = the body area divided by 12, with no row gutter.
- [ ] **Step 7: Run the tests.** Expected: PASS. Also run `pytest tests/test_reporting_*.py -q && ruff check .`. Expected: all green.
- [ ] **Step 8: Commit** `feat(reporting): house-style tokens, layout library and deck schemas`.

---

### Task 2: HTML renderer, browser fit measurement, PDF and PNG output

**Files:**
- Create: `arp/reporting/style/templates/base.html.j2`, `deck.css.j2`, one `<layout>.html.j2` per layout; `arp/reporting/html_render.py`; `arp/reporting/browser.py`; `arp/reporting/deck_compat.py`; `tests/fixtures/stress_deck.py`
- Modify: `arp/reporting/chart_builder.py` (add `render_chart_svg`), `pyproject.toml` (add `playwright>=1.45,<2.0`), `arp/config.py` (add `chromium_path: str | None = None`, env `ARP_CHROMIUM_PATH`), `.github/workflows/ci.yml` (add a step `python -m playwright install --with-deps chromium` after the pip install)
- Test: `tests/test_reporting_html_render.py`, `tests/test_reporting_browser.py`

**Interfaces:**
- Consumes: Task 1 `Deck`, `Tokens`, `load_layouts`, `get_variant`, `slot_rect`.
- Produces:
  - `render_chart_svg(spec: ChartSpec, datasets: list[QuantitativeDataset], *, width_px: int, height_px: int, theme: DesignTheme) -> str`. This reuses `render_chart_image`'s drawing code with `format="svg"` and `svg.fonttype="none"`.
  - `theme_from_tokens(tokens: Tokens) -> DesignTheme`, in `html_render.py`.
  - `render_deck_html(deck: Deck, datasets: list[QuantitativeDataset], tokens: Tokens | None = None) -> str`.
    Every slot element carries `data-slide="<i>" data-slot="<name>"`, has a fixed `width/height` from `slot_rect`, and has `overflow:hidden`.
    Every slide is a `<section class="slide">` of the canvas size with `page-break-after: always`.
    The footer shows the slide's `source_refs` joined by " · " and the page number.
    Autoescape is on, and slot text never passes through `|safe`. Chart SVG is the only `|safe` value.
  - `class BrowserUnavailable(RuntimeError)`. Its message includes `python -m playwright install chromium` and `ARP_CHROMIUM_PATH`.
  - `async def measure(html: str) -> list[Finding]`. It emits `stage="fit"` with these rules:
    - `overflow`, with message `ratio=<scrollHeight/clientHeight:.2f>`
    - `overflow_x`, for a single unbreakable token
    - `collision`
    - `off_grid`
  - `async def write_pdf(html: str, out: Path) -> Path` uses `page.pdf(width="1920px", height="1080px", print_background=True)`.
  - `async def write_pngs(html: str, out_dir: Path, scale: float = 0.5) -> list[Path]` writes one PNG per `section.slide`, named `page-{n:03d}.png`. The zero padding keeps `sorted()` in `preview.ensure_preview_images` correct past 9 slides. Write the PNGs after the PDF so its mtime cache treats them as fresh.
  - `deck_from_plan(plan: ReportPlan) -> Deck` maps:
    - `SECTION_HEADER` → `section/default`
    - `CHART_FOCUS` → `chart_takeaway/full`
    - `TEXT_ONLY` → `bullets/five`
    - `STANDARD` + chart → `chart_takeaway/chart_left`
    - `STANDARD` + table → `table/compact`
    - otherwise → `bullets/five`

    It also prepends `title/plain` from `plan.title`/`plan.subtitle`.
  - `stress_deck(mode: Literal["max","min"]) -> tuple[Deck, list[QuantitativeDataset]]`. It has one slide per layout×variant. In max mode every text slot holds exactly `max_words` words of average English length (`"lorem"` style words, 6 chars) and every list slot holds `max_items` items. Min mode has 1 word or item per slot.
- One Chromium launch per call. Use `executable_path=settings.chromium_path` when that setting is set. `measure` runs a single `page.evaluate` script that returns all slot boxes and scroll sizes. Collision and off-grid are computed in Python from those boxes.

- [ ] **Step 1: Write the failing tests**

```python
# test_reporting_html_render.py (no browser)
def test_html_escapes_llm_text():
    deck = Deck(title="T", slides=[SlideContent(headline="<script>x</script> & {{ y }}", layout="bullets", variant="three",
                                                slots={"items": ["a & b"]})])
    html = render_deck_html(deck, [])
    assert "<script>x" not in html and "&lt;script&gt;" in html and "{{ y }}" in html

def test_deck_from_plan_maps_layout_hints():
    plan = ReportPlan(title="T", sections=[ReportSection(heading="S", layout_hint="section_header"),
                                           ReportSection(heading="C", layout_hint="chart_focus", chart=ChartSpec(dataset_id="d"))])
    d = deck_from_plan(plan)
    assert [(s.layout, s.variant) for s in d.slides] == [("title","plain"),("section","default"),("chart_takeaway","full")]

def test_every_slot_has_data_attributes():
    deck, ds = stress_deck("min")
    html = render_deck_html(deck, ds)
    expected = sum(len(get_variant(s.layout, s.variant).slots) for s in deck.slides)
    assert html.count("data-slot=") == expected

# test_reporting_browser.py (real Chromium)
async def test_stress_deck_max_has_no_fit_findings():
    deck, ds = stress_deck("max")
    assert await measure(render_deck_html(deck, ds)) == []

async def test_overlong_text_reports_overflow_with_ratio():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="bullets", variant="three",
                                                slots={"items": ["word " * 400]})])
    [f] = await measure(render_deck_html(deck, []))
    assert (f.rule, f.slot, f.slide) == ("overflow", "items", 0) and float(f.message.split("=")[1]) > 1.5

async def test_unbreakable_token_reports_overflow_x():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="quote", variant="default",
                                                slots={"quote": "https://" + "x" * 300, "attribution": "a"})])
    assert {f.rule for f in await measure(render_deck_html(deck, []))} == {"overflow_x"}

async def test_pdf_has_one_page_per_slide(tmp_path):
    deck, ds = stress_deck("min")
    out = await write_pdf(render_deck_html(deck, ds), tmp_path / "d.pdf")
    assert len(PdfReader(out).pages) == len(deck.slides)

async def test_missing_chromium_raises_install_hint(monkeypatch):
    monkeypatch.setenv("ARP_CHROMIUM_PATH", "/nonexistent/chrome")
    with pytest.raises(BrowserUnavailable, match="playwright install chromium"):
        await measure("<html></html>")
```

- [ ] **Step 2: Run** `pytest tests/test_reporting_html_render.py tests/test_reporting_browser.py -q`. Expected: FAIL (ImportError).
- [ ] **Step 3: Install and check the browser.** Add the dependency, then run `pip install -e ".[dev]"`. Check that `python -c "import asyncio; from playwright.async_api import async_playwright"` works. If Chromium's revision doesn't match, set `ARP_CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` locally. Do not run `playwright install` in the cloud container.
- [ ] **Step 4: Implement the templates and `html_render.py`.** Build the CSS from tokens as custom properties. Fonts load from `style/fonts/` via `@font-face` with `file://` URLs, because the page is loaded with `page.set_content` plus a `base_url` pointing at `style/`.
- [ ] **Step 5: Implement `render_chart_svg`, `browser.py` and `deck_compat.py`.**
- [ ] **Step 6: Build `stress_deck`.** Then tune `max_words`/`max_items` in `layouts.json` until `test_stress_deck_max_has_no_fit_findings` passes. The limits are measured, not guessed. Commit the tuned numbers.
- [ ] **Step 7: Run** `pytest tests/test_reporting_*.py -q && ruff check .`. Expected: all green.
- [ ] **Step 8: Commit** `feat(reporting): HTML deck renderer with measured fit, PDF and PNG output`.

---

### Task 3: Pick the visual direction (human gate)

**Files:**
- Modify: `arp/reporting/style/tokens.json`, `arp/reporting/style/fonts/`, `arp/reporting/style/templates/deck.css.j2`
- Create: `docs/decks/house-style.pdf` (the chosen stress deck, committed as the reference)

- [ ] **Step 1: Design 3 directions with `/impeccable:impeccable` and `/ui-ux-pro-max:design-system`.** Each direction is a full `tokens.json` plus two OFL fonts, and changes the CSS only where needed. Constraints:
  - WCAG AA contrast for ink on background and for chart colours on background (PRODUCT.md's projector rule).
  - One accent colour.
  - The 5 type roles.
- [ ] **Step 2: Render each direction's stress deck.** Render `stress_deck("max")` plus a 6-slide realistic sample (title, big_number/two, chart_takeaway/chart_left, table/highlight, timeline/six, summary) to `scratchpad/direction-{a,b,c}.pdf`, and send all three to the user.
- [ ] **Step 3: STOP. Wait for the user to pick one.** Do not proceed without an answer.
- [ ] **Step 4: Commit the chosen tokens, fonts and CSS.** Re-run `pytest tests/test_reporting_browser.py -q`, which must be green; retune `layouts.json` limits if the new type scale needs it. Save the chosen PDF to `docs/decks/house-style.pdf`.
- [ ] **Step 5: Commit** `feat(reporting): lock house visual direction`.

---

### Task 4: Storyline, slide fill, approval API and UI

**Files:**
- Create: `arp/reporting/storyline.py`, `arp/reporting/slide_fill.py`, `arp/reporting/house_pipeline.py`
- Modify: `arp/reporting/service.py`, `arp/storage/reporting_store.py`, `arp/api/routers/reporting.py`, `arp/cli/reporting.py`, `frontend/src/api/client.ts`, `frontend/src/pages/ReportBuilder.tsx`
- Test: `tests/test_reporting_storyline.py`, `tests/test_reporting_slide_fill.py`, `tests/test_reporting_house_service.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `async def draft_storyline(request: ReportRequest, llm: LLMClient) -> tuple[Storyline, LLMUsage]`.
    The prompt includes `goal`, the audience, notes and dataset summaries.
    The system prompt says:
    - each headline is one full sentence stating the takeaway, at most 14 words
    - read in order, the headlines tell the argument
    - `target_length`, when set, is the exact slide count
  - `async def fill_slide(slide: StorylineSlide, index: int, request: ReportRequest, llm: LLMClient) -> tuple[SlideContent, list[Finding], LLMUsage]`.
    - The system prompt lists every layout/variant with its slot names, kinds and limits, generated from `load_layouts()`, so it can't drift from the library.
    - The headline is copied from the storyline, never rewritten.
    - After the call, `validate_slide(slide, datasets) -> list[str]` checks the layout/variant, the slot names, and each dataset_id and column.
    - On errors: one retry with the error text appended to the prompt. If it still fails, return `SlideContent(layout="bullets", variant="three", headline=..., slots={"items": []})` plus `Finding(stage="data", rule="bad_reference", message=<errors>)`.
  - `async def rewrite_slot(slide: SlideContent, slot: str, instruction: str, request: ReportRequest, llm: LLMClient) -> SlideContent` returns a copy with only that slot replaced. Its output model is `SlotRewrite(text: str | list[str])`.
  - `async def build_house_deck(report_id: str, request: ReportRequest, storyline: Storyline, llm: LLMClient, store: ReportingStore) -> tuple[Deck, list[Finding]]` (`house_pipeline.py`). In this task it does fill, measure, PDF and PNGs. Tasks 5, 6, 8 and 9 insert their stages here.
  - `preview.ensure_preview_images`: treat `HOUSE_DECK` like `PDF` (the source is `output.pdf`). This is only a fallback when the PNGs are missing.
  - Store methods: `save_storyline/load_storyline`, `save_deck/load_deck`, `save_findings/load_findings`, stored as `storyline.json`, `deck.json`, `findings.json`.
  - Service:
    - `create_and_plan` branches on `HOUSE_DECK`: it drafts the storyline and sets status `STORYLINE_READY`.
    - `async def approve_storyline(report_id, llm) -> ReportManifest` raises `ValueError` if the storyline is already approved or has 0 slides. It builds the deck, writes `output.pdf` and `output.pptx`, sets `output_files` and status `COMPLETED`, and sets `output_filename` = `output.pdf`.
    - `render_from_plan` for `HOUSE_DECK` re-renders from `deck.json` with no LLM.
  - API:
    - `GET/PUT /api/reports/{id}/storyline`: PUT returns 409 if approved, 422 if empty.
    - `POST /api/reports/{id}/storyline/approve`: 409 or 422 per the rules above.
    - `GET /api/reports/{id}/findings`.
    - `GET /{id}/download?file=output.pptx`: `file` must be in `output_files`, otherwise 404.
  - CLI: `arp report approve <id>`.
  - UI: when the output format is "House deck (PDF + PPTX)", "Draft" shows a headline list. You can edit text, reorder with up/down, add and delete, reusing the section-editor controls at `ReportBuilder.tsx:188-205`. The UI has Save and Approve & build buttons, a findings list grouped by slide, and two download buttons.

- [ ] **Step 1: Write the failing tests** (FakeLLMClient, keyed by output model name)

```python
async def test_storyline_prompt_carries_goal_and_target_length(fake_llm): ...
    # assert "Goal: Approve the utilities underweight" in llm.prompts[0] and "exactly 5 slides" in llm.prompts[0]

async def test_fill_slide_keeps_storyline_headline(fake_llm): ...
    # scripted SlideContent has headline "different" -> returned slide.headline == storyline headline

async def test_fill_slide_retries_once_on_bad_column_then_placeholder(fake_llm):
    # script two SlideContent with chart.value_columns=["nope"]
    # assert llm.calls == ["SlideContent", "SlideContent"]
    # assert findings[0].rule == "bad_reference" and slide.layout == "bullets"

async def test_fill_slide_accepts_valid_retry(fake_llm): ...
    # first bad, second good -> no findings

def test_system_prompt_lists_every_variant():
    # every "layout/variant" id from load_layouts() appears in slide_fill._system_prompt()

async def test_approve_rejects_empty_and_double_approval(tmp_path, fake_llm): ...
    # empty storyline -> ValueError("no slides"); approve twice -> ValueError("already approved")

async def test_house_deck_end_to_end_writes_pdf_png_and_findings(tmp_path, fake_llm):
    # 3-slide storyline -> manifest.output_files == ["output.pdf", "output.pptx"] after Task 7;
    # until Task 7 lands assert only "output.pdf" and PNG count == 4 (title + 3)

def test_put_storyline_after_approval_is_409(client): ...
def test_download_rejects_file_not_in_output_files(client): ...
```

- [ ] **Step 2: Run** `pytest tests/test_reporting_storyline.py tests/test_reporting_slide_fill.py tests/test_reporting_house_service.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the backend** in the order `storyline.py` → `slide_fill.py` → store → `house_pipeline.py` → service → router → CLI. Slides are filled concurrently with `asyncio.gather`. The title slide is added deterministically from `storyline.title` and `storyline.subtitle`.
- [ ] **Step 4: Run the backend tests.** Expected: PASS. Then run `pytest tests/test_reporting_*.py -q && ruff check .`.
- [ ] **Step 5: Implement the frontend.** Check with `cd frontend && npm run build && npm run lint`. Expected: clean. Then check it by hand with the `run` skill: draft, edit, approve, and see the PDF preview.
- [ ] **Step 6: Commit** `feat(reporting): storyline approval and per-slide fill for house decks`.

---

### Task 5: Writing guide, linter and targeted rewrite

**Files:**
- Create: `arp/reporting/style/writing.md`, `arp/reporting/lint.py`
- Modify: `arp/reporting/storyline.py`, `arp/reporting/slide_fill.py` (inject `writing.md`), `arp/reporting/house_pipeline.py`
- Test: `tests/test_reporting_lint.py`

**Interfaces:**
- Consumes: `SlideContent`, `Deck`, `Finding`, `get_variant`, `rewrite_slot`.
- Produces:
  - `lint_deck(deck: Deck, request: ReportRequest) -> list[Finding]`, all `stage="lint"`.
  - `RULES: dict[str, Callable]`. Adding a rule means one entry and one test pair.
  - `async def lint_and_rewrite(deck: Deck, request: ReportRequest, llm: LLMClient, max_rounds: int = 2) -> tuple[Deck, list[Finding]]`. Each round calls `rewrite_slot` only for flagged slots, with the rule's `message` as the instruction. Headline findings are reported, never rewritten, because the user approved the headlines.
- Rules and exact behaviour:

| rule | flags | does not flag |
|---|---|---|
| `over_word_limit` | slot words > `max_words`; list items > `max_items` | at the limit |
| `stock_ai_word` | whole-word, case-insensitive: leverage, delve, robust, seamless, landscape, pivotal, tapestry, unlock, empower, holistic, synergy, cutting-edge, game-changer, navigate (figurative), realm, foster, underscore, showcase, testament, crucial, vibrant, elevate, streamline, paradigm | "leveraged loan", "leverage ratio" (finance terms, exempt when followed by loan/ratio/buyout) |
| `not_x_but_y` | `\bnot (just |only |merely )?[^.;]{1,60}?,? but\b` | "not yet" |
| `triad_repeat` | ≥3 slides whose lists all have exactly 3 items **and** every item under 5 words | a single 3-item list |
| `dash_overuse` | >1 em/en dash (`—`, `–`, ` - `) per slide across all slots | a hyphenated word |
| `bold_label` | `**Word:**` or `Word:` at the start of ≥2 list items on a slide | a time "10:30" |
| `exclamation` | any `!` | — |
| `repeated_opener` | the same first word starting ≥3 slots across the deck, ignoring "the/a/an" | — |
| `number_not_in_source` | a number in slot text that matches no source value | see algorithm |

- `number_not_in_source` algorithm (not determined by the tests alone):
  - **Sources:** every number in `qualitative_notes`, plus every numeric cell of every dataset.
  - **Parse text numbers** with `r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?\s*(%|bn|m|k|x)?"`. Strip commas. Apply the suffix as a multiplier: `bn`=1e9, `m`=1e6, `k`=1e3.
  - **Match rule:** a text number `n` with `d` decimals matches a source `v` if `abs(n - v) <= 0.5 * 10**-d`. For `%`, `v*100` is also tried. For `bn/m/k`, the tolerance scales with the multiplier.
  - **Exempt:** integers 0–10 and years 1900–2100.

- [ ] **Step 1: Write the tests.** For each rule, write `test_<rule>_flags` and `test_<rule>_ignores` using the table's examples. Also write:

```python
def test_number_formats_match_source():
    req = _req(notes="Emissions fell 12.4% to 1,234 kt; capex was 1200000000.", datasets=[_ds({"share": 0.12})])
    for text in ["12.4%", "1,234", "1.2bn", "12%", "1234"]:
        assert not _lint_one(text, req), text

def test_invented_number_flagged():
    assert _rules(_lint_one("Emissions fell 17%", _req(notes="fell 12%"))) == {"number_not_in_source"}

async def test_rewrite_only_touches_flagged_slots_and_stops_after_two_rounds(fake_llm):
    # script SlotRewrite that keeps the stock word -> llm.calls == ["SlotRewrite"]*2, finding remains

async def test_headline_findings_never_rewritten(fake_llm):
    # headline contains "leverage" -> llm.calls == [] and finding present
```

- [ ] **Step 2: Run** `pytest tests/test_reporting_lint.py -q`. Expected: FAIL.
- [ ] **Step 3: Write `writing.md`** (one page) with:
  - headlines as conclusions
  - plain verbs; digits for numbers; name the specific company, sector or figure
  - hedge only on real uncertainty
  - one short rule per `AudienceLevel` and one per `Tone`
  - three before/after pairs, written in this repo's domain (portfolio emissions, Decision Studio tiers, a theme universe)

  Inject it into both system prompts.
- [ ] **Step 4: Implement `lint.py` and wire `lint_and_rewrite` into `build_house_deck`** after the fill step.
- [ ] **Step 5: Run** `pytest tests/test_reporting_*.py -q && ruff check .`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(reporting): writing guide, deterministic linter, targeted rewrite`.

---

### Task 6: The fit loop

**Files:**
- Create: `arp/reporting/fit.py`
- Modify: `arp/reporting/house_pipeline.py`
- Test: `tests/test_reporting_fit.py` (uses real Chromium)

**Interfaces:**
- Consumes: `measure`, `render_deck_html`, `rewrite_slot`, `get_variant`, `lint_deck` (a shortened slot is re-linted).
- Produces: `async def fit_deck(deck: Deck, request: ReportRequest, llm: LLMClient, max_passes: int = 3) -> tuple[Deck, list[Finding]]`.
- Per pass: render the whole deck, run `measure`, and apply one action per overflowing slide:
  1. **`overflow` on a text/list slot with ratio ≤ 1.6:** call `rewrite_slot` with `instruction=f"Shorten to at most {floor(words/ratio*0.9)} words. Keep every number."`
  2. **Else, if the variant has `roomier`:** switch the variant. Slots are carried over by name. A slot missing in the roomier variant becomes a `Finding(rule="slot_dropped")` and is never lost silently.
  3. **Else, if the overflowing slot is a `list` or `table` with ≥2 items/rows:** split the slide into two slides with the same layout, variant and headline, and half the items each. Record `split_from` in `speaker_notes`.
  4. **Else:** leave it. It is reported after the last pass.

  `overflow_x` never triggers a rewrite; it is reported as-is. After `max_passes`, the remaining fit findings are returned.

- [ ] **Step 1: Write the failing tests**

```python
async def test_fit_shortens_mild_overflow(fake_llm): ...        # ratio ~1.3 -> one SlotRewrite call, no findings
async def test_fit_switches_to_roomier_variant(fake_llm): ...   # bullets/three with 5 items -> bullets/five, no LLM call
async def test_fit_splits_long_list(fake_llm): ...              # bullets/five with 10 items -> 2 slides, same headline
async def test_fit_gives_up_after_three_passes(fake_llm):
    # 40 items of 30 words each: len(result.slides) is bounded (<= 8) and findings contain "overflow"
async def test_fit_reports_dropped_slot_on_variant_switch(fake_llm): ...
```

- [ ] **Step 2: Run** `pytest tests/test_reporting_fit.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `fit_deck`.** Wire it into `build_house_deck` after lint and before PDF/PNG.
- [ ] **Step 4: Run** `pytest tests/test_reporting_*.py -q && ruff check .`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(reporting): shorten/roomier/split fit loop`.

---

### Task 7: PPTX export from the same grid

**Files:**
- Create: `arp/reporting/house_pptx.py`
- Modify: `arp/reporting/house_pipeline.py`
- Test: `tests/test_reporting_house_pptx.py`

**Interfaces:**
- Consumes: `Deck`, `load_tokens`, `get_variant`, `slot_rect`, `chart_builder.build_native_chart_data` / `style_native_chart` / `render_chart_image`, and `theme_from_tokens`.
- Produces: `build_house_pptx(deck: Deck, datasets: list[QuantitativeDataset], out: Path, tokens: Tokens | None = None) -> Path`.
- **Construction:**
  - Start from `Presentation()` with slide size 1920×1080 px. Convert px to EMU at 9525 EMU/px.
  - Use the blank layout. Every slot is a textbox, native chart or table at exactly `slot_rect`.
  - Headline, footer and accent rule go at the same token positions as in the HTML.
  - Fonts, sizes and colours come from tokens. px become pt at ×0.75.
  - `speaker_notes` go into notes.
  - Text is the fitted text from `deck.json`; nothing is re-fitted.
- **Deviation from spec, deliberate:** the spec describes a generated `house.pptx` master with one layout per variant. python-pptx cannot author slide layouts, so we'd have to write raw XML. Placing shapes from the same `slot_rect` gives the same positions with ~150 fewer lines. The cost is that PowerPoint's "Layout" menu won't offer the house layouts. Revisit if people build new slides by hand in PowerPoint.

- [ ] **Step 1: Write the failing tests**

```python
def test_pptx_positions_match_grid(tmp_path):
    deck, ds = stress_deck("min")
    prs = Presentation(build_house_pptx(deck, ds, tmp_path / "d.pptx"))
    for slide, content in zip(prs.slides, deck.slides):
        for spec in get_variant(content.layout, content.variant).slots:
            r = slot_rect(load_tokens(), spec)
            shape = next(s for s in slide.shapes if s.name == f"slot:{spec.name}")
            assert (shape.left, shape.top, shape.width, shape.height) == tuple(round(v * 9525) for v in r)

def test_pptx_charts_are_native(tmp_path): ...     # chart_takeaway slide -> shape.has_chart
def test_pptx_escapes_nothing_and_keeps_literal_text(tmp_path): ...  # "<script> & {{x}}" appears verbatim in text_frame.text

def test_pptx_matches_pdf_text_positions(tmp_path):
    # needs soffice; pytest.skip if shutil.which("soffice") is None
    # render both to PDF; pypdf extract text boxes per page; every slot's first word within 12px of its PDF counterpart
```

- [ ] **Step 2: Run** `pytest tests/test_reporting_house_pptx.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement it and wire it into `build_house_deck`.** `output.pptx` joins `output_files`. Update the Task 4 end-to-end test to expect both files.
- [ ] **Step 4: Run** `pytest tests/test_reporting_*.py -q && ruff check .`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(reporting): editable pptx export from the house grid`.

---

### Task 8: Visual QA pass

**Files:**
- Create: `arp/reporting/visual_qa.py`
- Modify: `arp/llm/base.py`, `arp/llm/langchain_client.py`, `tests/conftest.py`, `arp/reporting/house_pipeline.py`
- Test: `tests/test_reporting_visual_qa.py`, `tests/test_llm_images.py`

**Interfaces:**
- Consumes: `write_pngs`, `fit_deck`, `SlideContent`.
- Produces:
  - `complete_structured(..., images: list[bytes] | None = None)` on `LLMClient`, `LangChainAnthropicClient` and `FakeLLMClient`.
    - Images are sent as base64 PNG content blocks before the text prompt.
    - The cache key includes `sha256` of each image.
    - `FakeLLMClient` records `self.images: list[list[bytes] | None]`.
  - `QAEdit(slide: int, layout: str | None = None, variant: str | None = None, slot: str | None = None, text: str | list[str] | None = None, reason: str)` and `QAResult(edits: list[QAEdit])`.
  - `async def visual_qa(deck: Deck, pngs: list[Path], request: ReportRequest, llm: LLMClient) -> tuple[Deck, list[Finding]]`.
    - One call with all PNGs. The checklist is fixed in the system prompt:
      - hierarchy clear
      - one focal point
      - orphan words
      - a lone bullet
      - a near-empty slide
      - the chart supports the headline
    - Edits are applied only if the layout, variant and slot are valid, and never to headlines.
    - Invalid edits become `Finding(stage="qa", rule="invalid_edit")`.
    - Applied edits are recorded as `Finding(stage="qa", rule="applied", message=reason)`.
    - Then `fit_deck(max_passes=1)` runs once. There is no second QA call.

- [ ] **Step 1: Write the failing tests**

```python
async def test_qa_sends_one_png_per_slide_in_one_call(fake_llm): ...  # llm.calls == ["QAResult"], len(llm.images[0]) == len(slides)
async def test_qa_ignores_headline_edits_and_invalid_variants(fake_llm): ...
async def test_qa_runs_exactly_once(fake_llm): ...                     # llm.calls.count("QAResult") == 1
def test_image_hash_changes_cache_key(): ...                           # DiskLLMCache key differs when image bytes differ
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement it.** Wire it into `build_house_deck`: after fit, write PNGs, run QA, then write the final PDF, PNGs and PPTX.
- [ ] **Step 4: Run** `pytest -q && ruff check .`. This is the full suite, because the `LLMClient` signature changed. Expected: PASS.
- [ ] **Step 5: Commit** `feat(reporting): one-pass visual QA on rendered slides`.

---

### Task 9: Pipeline adapters, periodic re-runs, stewardship on the new renderer

**Files:**
- Create: `arp/reporting/adapters.py`, `arp/reporting/scheduler.py`
- Modify: `arp/reporting/service.py`, `arp/reporting/house_pipeline.py`, `arp/cli/reporting.py`, `arp/api/main.py` (start/stop the scheduler like the existing ones), `arp/stewardship/client_report.py:202`, `arp/stewardship/program.py:474`
- Test: `tests/test_reporting_adapters.py`, `tests/test_reporting_rerun.py`, `tests/test_stewardship_client_report.py` (update)

**Interfaces:**
- Produces:
  - `load_run_datasets(refs: list[RunRef], settings: Settings) -> list[QuantitativeDataset]`.
    - For `kind="decision"`, read `DecisionStore.get_published(ref_id)`. `rows` become one dataset named `framework_name`, with `as_of` in the description.
    - For `kind="run"`, read `RunStore.results_path(ref_id)` JSONL; flatten top-level scalar fields into one dataset named after the run type.
    - Column kinds use `datasets._infer_kind`.
    - An unknown id raises `ValueError(f"unknown {kind} {ref_id}")`.
  - `build_house_deck` merges these datasets into `request.datasets` before the fill step.
  - `async def rerun(report_id: str, llm: LLMClient) -> ReportManifest` (service).
    - Creates a new report with the same request, reloads the adapters, and copies the approved storyline.
    - If `lint_deck` returns `number_not_in_source` on any **headline**, it stops with status `STORYLINE_READY`, the storyline not approved, and those findings. The approved claim no longer holds, so a person must re-approve.
    - Otherwise it builds the deck.
  - `ReportScheduleConfig(enabled: bool = False, interval_hours: int = 720, report_ids: list[str] = [])`.
  - `ReportScheduler(IntervalScheduler)` with `job_id="report_reruns"`, state in `reports_dir/_schedule`. `_run` calls `rerun` for each id and logs failures per id without stopping the others.
  - CLI: `arp report rerun <id>` and `arp report schedule --every-hours N --add <id> --remove <id> --enable/--disable`.
  - Stewardship: replace `build_deck(plan, …)` with `build_house_pptx(deck_from_plan(plan), …)`. Also write `write_pdf(render_deck_html(...))` next to it. No LLM is called.
- Portfolio/climate analytics have no stored result to read; they're computed on request. Their adapter is left out of this plan. Add it when a periodic portfolio deck needs it, calling the aggregation engine directly.

- [ ] **Step 1: Write the failing tests**

```python
def test_decision_adapter_turns_published_rows_into_dataset(tmp_path): ...
def test_run_adapter_flattens_results_jsonl(tmp_path): ...
def test_unknown_ref_raises(tmp_path): ...
async def test_rerun_reuses_storyline_with_fresh_data(tmp_path, fake_llm): ...    # llm.calls has no "Storyline"
async def test_rerun_stops_when_headline_number_no_longer_in_data(tmp_path, fake_llm): ...
    # status == STORYLINE_READY, storyline.approved is False, finding rule == "number_not_in_source"
async def test_scheduler_continues_after_one_failing_report(tmp_path, fake_llm): ...
def test_stewardship_client_report_uses_house_renderer_without_llm(tmp_path): ...  # no LLM passed; pptx + pdf exist
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement it** in the order adapters → rerun → scheduler → CLI → stewardship swap.
- [ ] **Step 4: Run** `pytest -q && ruff check .`, then `cd ../frontend && npm run build`. Expected: all green.
- [ ] **Step 5: Commit** `feat(reporting): pipeline adapters, scheduled deck re-runs, stewardship on house renderer`.

---

### Task 10: Golden briefs and docs

**Files:**
- Create: `tests/test_reporting_golden_briefs.py`
- Modify: `README.md` (function 13 row and the CLI example), `docs/TECHNICAL_REFERENCE.md` (reporting section)

- [ ] **Step 1: Write one end-to-end test per deck type** with FakeLLMClient and real Chromium: free-form, pipeline (decision adapter), periodic (rerun), client/stewardship (`deck_from_plan`). Each asserts:
  - `output.pdf` and `output.pptx` exist
  - zero `fit` findings
  - zero `lint` findings except any the scripted text deliberately contains
  - the page count equals the slide count
- [ ] **Step 2: Run** `pytest -q && ruff check .`. Expected: PASS.
- [ ] **Step 3: Update the docs.** In `README.md` add one sentence on house decks plus `arp report plan --format house_deck …` / `arp report approve <id>`. In `TECHNICAL_REFERENCE.md` describe the pipeline stages, files and limits.
- [ ] **Step 4: Commit** `test(reporting): golden briefs per deck type; docs`.
