# Company Template Frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** House decks built with a `template_id` place headline, subheading and body in the boxes read from the company .pptx, in its fonts; ARP's tokens and layouts fill the body.

**Architecture:** Upload extracts a `TemplateFrame` (three boxes + fonts, in 1920-px canvas units) onto the stored template profile. At build time `house_tokens()` returns `Tokens` carrying that frame; every geometry reader (`slot_rect`, `html_render`, `house_pptx`, `browser.measure`) already takes `Tokens`, so the frame flows through one seam. Subheadings are a new storyline field that rides along like the headline.

**Tech Stack:** Python 3, FastAPI, pydantic, python-pptx, Jinja2, Playwright/Chromium; React + TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-11-14-template-frame-design.md` (approved 2026-11-14). Executors read both; AC-n below refers to its Acceptance table.

## Global Constraints

- Canvas stays 1920×1080 px. `px = EMU × 1920 / slide_width_emu`; `size_px = pt × 1920 / (slide_width_emu / 12700)`.
- With a frame, `output.pptx` slide size = template slide size, `slide_width_emu / 1920` EMU per px. Without one: unchanged (9525 EMU/px, 18288000 × 10287000).
- Upload never refuses for frame reasons; `frame_error` messages verbatim, checked in order:
  1. `Template must be 16:9 (got <w>×<h>).`
  2. `No layout named "<name>".`
  3. `No layout has a title, a subheading and a body placeholder.`
  4. `Upload the font file for "<family>".`
- House-deck create with a frameless template: 422 `Template <id> cannot frame a house deck: <frame_error or "re-upload it">`. Only when `layout.output_format == "house_deck"`.
- Bundled families needing no file: Geist, Geist Mono, Hanken Grotesk. Font file name `<Family-no-spaces>-<weight>.(ttf|otf|woff2)`, case-insensitive; any weight satisfies.
- Footer only when body bottom ≤ 1080 − 152; else `Sources: <refs " · ">` appended to notes (newline only if notes non-empty; nothing if no refs).
- Subheading overflow: exactly one finding `stage="fit", rule="subheading_overflow", slot="subheading"`; never rewritten, box and font size unchanged.
- No change to classic `pptx`/`docx` paths or no-template decks.
- Repo rules: `ruff check .`, frontend `npm run lint && npx tsc -b && npm test`; after model changes run `python scripts/export_openapi.py` then `npm run gen:api` and commit both generated files.

## Review Focus

1. A real template whose content layout uses `obj` placeholders and inherits position from the master (no `spPr/xfrm` on the layout) → boxes must come from the master; test in Task 2 (`test_inherits_master_position`).
2. Two layouts both qualify → the first in file order wins, deterministically; test in Task 2 (`test_first_qualifying_layout_wins`).
3. Dark mode with a frame → template fonts still apply, `heading_dark` is ignored (the template family wins); test in Task 4 (`test_dark_mode_keeps_template_heading_font`).
4. A fit split of an overflowing list slide → both halves keep the approved subheading; test in Task 5 (`test_split_keeps_subheading`).
5. Re-rendering an existing report after its template was re-uploaded is out of scope; the report keeps the `template_id` it was created with and reads that profile. No test; noted for review.

---

### Task 1: Models

**Files:**
- Modify: `backend/arp/schemas/reporting.py` (near `TemplateStyleProfile` :130, `SlideContent` :244, `StorylineSlide` :266)
- Modify: `backend/arp/reporting/house_style.py` (`Tokens`)
- Test: `backend/tests/test_reporting_template_frame.py` (new)

**Interfaces:**
- Produces (in `schemas/reporting.py`):
  - `class Box(BaseModel): x: float; y: float; w: float; h: float`
  - `class FrameFont(BaseModel): family: str; size_px: float; bold: bool`
  - `class TemplateFrame(BaseModel): layout_name: str; headline: Box; subheading: Box; body: Box; headline_font: FrameFont; subheading_font: FrameFont; body_font_family: str`
  - `TemplateStyleProfile.frame: TemplateFrame | None = None`, `.frame_error: str | None = None`, `.font_dir: str | None = None`
  - `StorylineSlide.subheading: str = ""`, `SlideContent.subheading: str = ""`
- Produces (in `house_style.py`): `Tokens.frame: TemplateFrame | None = None`, `Tokens.font_dir: str | None = None`

- [ ] **Step 1:** Test `test_old_profile_loads_with_null_frame`: `TemplateStyleProfile.model_validate(<dict without frame keys>)` has `frame is None` and `frame_error is None` (AC-23 basis).
- [ ] **Step 2:** Run `cd backend && python3 -m pytest tests/test_reporting_template_frame.py -v` → FAIL (attribute missing).
- [ ] **Step 3:** Add the models and fields above.
- [ ] **Step 4:** Run the test → PASS. Run `python scripts/export_openapi.py`, `cd ../frontend && npm run gen:api && npx tsc -b`.
- [ ] **Step 5:** Commit `feat(reporting): template frame and subheading models`.

### Task 2: Frame extraction and upload

**Files:**
- Create: `backend/arp/reporting/template_frame.py`
- Create: `backend/tests/fixtures/frame_template.py`
- Modify: `backend/arp/reporting/style_profile.py` (`ingest_template`)
- Modify: `backend/arp/api/routers/reporting.py:38` (`upload_template`)
- Modify: `backend/arp/storage/reporting_store.py` (add `template_font_dir(template_id) -> Path` = `template_dir(id) / "fonts"`)
- Test: `backend/tests/test_reporting_template_frame.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces:
  - `extract_frame(prs: Presentation, layout_name: str | None, font_families: set[str]) -> tuple[TemplateFrame | None, str | None]` — `font_families` are the families the uploaded files provide (already normalised: lowercase, no spaces).
  - `font_family_of(filename: str) -> str | None` — `"TestaSerif-700.ttf"` → `"testaserif"`; `None` for other extensions or no `-<digits>` suffix.
  - `ingest_template(store, source_path, source_filename, fonts: list[tuple[str, Path]] = (), layout_name: str | None = None) -> TemplateStyleProfile`
  - Upload route fields: `file: UploadFile`, `fonts: list[UploadFile] = File(default=[])`, `layout_name: str | None = Form(None)`.
- Fixture: `make_frame_pptx(path: Path, *, width_emu=12192000, height_emu=6858000, with_subheading=True, layouts=("Content",)) -> Path` builds the spec's `frame.pptx` from python-pptx's default template (rename a layout to "Content", set title + two body placeholders to the spec's inch boxes, title 32 pt bold, subheading 18 pt, theme fonts "Testa Serif"/"Testa Sans" by editing the theme XML). `frame_fonts(dir: Path, names=("TestaSerif-700.ttf", "TestaSans-400.ttf")) -> list[Path]` copies a bundled Geist ttf under those names.

- [ ] **Step 1: Write the failing tests** (TestClient against the router, as `tests/test_reporting_*` do today):
  - `test_ac1_boxes`: assert `frame.layout_name == "Content"` and the three boxes equal AC-1's values with `pytest.approx(abs=1)`.
  - `test_ac2_fonts`: headline `("Testa Serif", 64, True)`, subheading `("Testa Sans", 36, False)` with `approx(abs=0.1)`, `body_font_family == "Testa Sans"`.
  - `test_ac3_not_16_9`, `test_ac4_no_subheading_placeholder`, `test_ac5_missing_font`, `test_ac26_unknown_layout_name`: status 200, `frame is None`, `frame_error` equals the spec string exactly.
  - `test_ac6_fonts_stored`: `sorted(os.listdir(store.template_font_dir(id))) == ["TestaSans-400.ttf", "TestaSerif-700.ttf"]`.
  - `test_ac23_old_profile_listed`: write a `style.json` without `frame`, GET `/api/reports/templates` → 200, entry has `"frame": None`.
  - `test_inherits_master_position`: fixture with the layout's body `xfrm` removed → body box equals the master body placeholder's box.
  - `test_first_qualifying_layout_wins`: `layouts=("Content", "Content 2")` → `layout_name == "Content"`.
  - `test_font_family_of`: `"TestaSerif-700.ttf"→"testaserif"`, `"x.otf"→None`, `"Geist-400.WOFF2"→"geist"`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `template_frame.py`. Placeholder kinds counted: title/center-title for the headline; body, subtitle, object for the others. Subheading = top edge first below the headline's top and height < slide_height/3; body = largest remaining by area. Position: `ph.left/top/width/height`, falling back to the master placeholder of the same `idx`/type when `None`. Font size/bold: placeholder `lstStyle` lvl1 → master `titleStyle`/`bodyStyle` lvl1 → theme (major for headline, minor otherwise); if no size anywhere, use the house token size scaled to px. Bundled families compare normalised against `{"geist", "geistmono", "hankengrotesk"}`.
- [ ] **Step 4:** Extend `ingest_template` and the route; save font files to `template_font_dir`, set `font_dir`. Run tests → PASS. Run `test_reporting_*template*` and the existing upload tests → PASS.
- [ ] **Step 5:** Commit `feat(reporting): read template frame on upload`.

### Task 3: Template preview PNG

**Files:**
- Modify: `backend/arp/api/routers/reporting.py` (new `GET /templates/{template_id}/preview.png`, declared before `/{report_id}` routes)
- Modify: `backend/arp/reporting/template_frame.py`
- Test: `backend/tests/test_reporting_template_frame.py`

**Interfaces:**
- Produces: `frame_preview_html(frame: TemplateFrame, tokens: Tokens) -> str` — a 1920×1080 page with three outlined, labelled boxes ("Headline", "Subheading", "Body"); PNG via the existing `browser._page` path at scale 1, cached as `report_templates/<id>/preview.png`.

- [ ] **Step 1:** Tests: `test_ac20_preview_404_without_frame` (AC-3 template → 404); `test_preview_html_labels` (the HTML contains the three labels and `left:144px;top:72px` for the headline box — pure function, no browser).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. Add `preview_png` URL to the upload response when `frame` is set.
- [ ] **Step 5:** Commit `feat(reporting): template frame preview`.

### Task 4: Render the frame (HTML + PPTX)

**Files:**
- Modify: `backend/arp/reporting/house_style.py` (`slot_rect`, new `with_frame`)
- Modify: `backend/arp/reporting/html_render.py`, `style/templates/base.html.j2`, `style/templates/deck.css.j2`
- Modify: `backend/arp/reporting/house_pptx.py` (`_Builder.slide`, `build_house_pptx`)
- Modify: `backend/arp/reporting/browser.py` (`measure(html, tokens=None)`)
- Test: `backend/tests/test_reporting_house_frame.py` (new)

**Interfaces:**
- Consumes: `Tokens.frame`, `Tokens.font_dir`.
- Produces:
  - `with_frame(tokens: Tokens, frame: TemplateFrame, font_dir: str | None) -> Tokens` (a `model_copy`).
  - `slot_rect(tokens, slot)`: with `tokens.frame`, the 12×12 grid fills `frame.body` (house gutter); title/section slots keep the house geometry — pass `house=True` from callers for those two layouts: `slot_rect(tokens, slot, house: bool = False)`.
  - `footer_fits(tokens) -> bool`: `tokens.frame is None or frame.body.y + frame.body.h <= canvas.height - 152`.
  - `measure(html: str, tokens: Tokens | None = None) -> list[Finding]`: safe area = frame body when framed; a box with `data-slot="subheading"` that overflows yields `rule="subheading_overflow"` (and no `overflow`).
  - `build_house_pptx(..., tokens=...)`: framed → `prs.slide_width/height = template size`, EMU/px = `slide_width_emu / 1920`; shapes `headline`, `subheading` at frame boxes, runs in frame fonts (pt = size_px × 0.75 × 9525 / emu_per_px); no `accent_rule`; footer per `footer_fits`, else notes suffix.
  - Template families: headline + big numbers + subheads use `headline_font.family`, everything else `body_font_family`; `heading_dark` ignored when framed. `_font_faces` also loads `.otf` and files from `tokens.font_dir` (name rule from Task 2, case-insensitive).
- [ ] **Step 1: Write the failing tests** (build with a stand-in deck, no LLM; read `output.pptx` with python-pptx; px = EMU / 6350):
  - `test_ac8_slide_size_and_boxes`, `test_ac9_headline_runs` (Testa Serif, 32 pt, bold), `test_ac27_subheading_runs` (Testa Sans, 18 pt, not bold), `test_ac28_body_runs` (Testa Sans).
  - `test_ac10_slots_inside_body`: all `slot:*` inside body ±1; `slot:items` left 144, right 1458.7 ±1; no `accent_rule`.
  - `test_ac12_footer_present`: `footer:refs`/`footer:page` top 928, height 56 ±1.
  - `test_ac13_footer_to_notes`: body ending 40 px above bottom, refs `["ds_1"]`, notes `"N"` → no `footer:*`, notes == `"N\nSources: ds_1"`; plus notes `""` → `"Sources: ds_1"`; plus refs `[]` → notes unchanged.
  - `test_ac14_title_slide`: slide 0 `slot:title` box equals the no-template build's, font Testa Serif, no `accent_rule`.
  - `test_ac11_html_matches` (`@pytest.mark.asyncio`, Chromium): headline element box == AC-1 box ±2, computed font-family starts with "Testa Serif".
  - `test_ac22_no_template_unchanged`: no frame → slide size 18288000×10287000, headline at (96, 96), font Geist, `accent_rule` present, `footer:refs` top 928.
  - `test_dark_mode_keeps_template_heading_font`: `mode="dark"` framed → headline runs Testa Serif.
  - `test_measure_subheading_overflow`: 60-word subheading → exactly one finding with slot `subheading`, rule `subheading_overflow`.
- [ ] **Step 2:** Run `python3 -m pytest tests/test_reporting_house_frame.py -v` → FAIL.
- [ ] **Step 3:** Implement as in Interfaces. In the HTML the subheading is an element with `data-slide`/`data-slot="subheading"` positioned at `frame.subheading`, like `h1.t-headline` is today.
- [ ] **Step 4:** Run the new file and all existing `tests/test_reporting_house_pptx.py`, `test_reporting_html_render.py`, `test_reporting_fit.py` → PASS.
- [ ] **Step 5:** Commit `feat(reporting): render house deck inside the template frame`.

### Task 5: Pipeline wiring and the create check

**Files:**
- Modify: `backend/arp/reporting/template_frame.py` (`house_tokens`)
- Modify: `backend/arp/reporting/house_pipeline.py`, `fit.py`, `visual_qa.py`, `service.py` (`create_and_plan`, the house re-render paths), `slide_fill.py:126`
- Test: `backend/tests/test_reporting_house_frame.py`, `backend/tests/test_reporting_template_frame.py`

**Interfaces:**
- Produces:
  - `house_tokens(request: ReportRequest, store: ReportingStore) -> Tokens`: no `template_id` → `load_tokens()`; else `with_frame(load_tokens(), profile.frame, profile.font_dir)`; raises `ValueError(<the 422 detail>)` when the frame is null.
  - `fit_deck(..., tokens: Tokens | None = None)`, `visual_qa(..., tokens: Tokens | None = None)`, `render_house_outputs(..., tokens: Tokens | None = None)`: passed to every `render_deck_html`/`measure`/`build_house_pptx` call. `fit_deck` never rewrites `subheading` (treat like `headline` at fit.py:80).
  - `fill_slide` copies `slide.subheading` onto the returned `SlideContent`, like the headline.
  - `ReportingService.create_and_plan`: when `output_format == HOUSE_DECK` and `template_id` is set, call `house_tokens` first; the router maps its `ValueError` to 422.
- [ ] **Step 1:** Tests: `test_ac7_frameless_house_deck_422`, `test_ac24_old_profile_422` (detail ends `re-upload it`), `test_ac25_classic_pptx_accepts_frameless` (`?render=false`, `output_format="pptx"` → 200, manifest `template_id` matches), `test_ac16_subheading_never_rewritten` (stand-in LLM, full `build_house_deck`: text unchanged, box unchanged, runs 18 pt, exactly one `slot == "subheading"` finding with `rule="subheading_overflow"`, `stage="fit"`, `slide=1`), `test_split_keeps_subheading`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run these plus `tests/test_reporting_house_service.py`, `test_reporting_service.py` → PASS.
- [ ] **Step 5:** Commit `feat(reporting): build house decks with the template frame`.

### Task 6: Subheadings in the storyline

**Files:**
- Modify: `backend/arp/reporting/storyline.py`, `backend/arp/reporting/lint.py` (`_texts`)
- Test: `backend/tests/test_reporting_storyline.py`

**Interfaces:**
- `draft_storyline(request, llm)` appends a subheading rule to the system prompt only when `request.template_id` is set. The rule includes the literal words `subheading` and `at most 20 words`. Without a template, any returned subheading is cleared to `""`.
- `_texts(slide, headline=True)` also yields `("subheading", slide.subheading)` when it is non-empty. Lint reports it but never rewrites it.
- [ ] **Step 1:** Tests: `test_ac15_prompt_asks_for_subheadings` (recording stand-in: prompt contains both phrases; returned subheadings kept), `test_ac21_no_template_no_subheading` (prompt lacks `subheading`; all `""`), `test_lint_flags_subheading_not_rewritten`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run `tests/test_reporting_storyline.py tests/test_reporting_lint.py` → PASS.
- [ ] **Step 5:** Commit `feat(reporting): subheadings in the storyline`.

### Task 7: Storyline screen

**Files:**
- Modify: `frontend/src/pages/ReportBuilder.tsx:570-605` (storyline editor), `frontend/src/types.ts` if the storyline type lives there
- Test: the page's existing test file under `frontend/src` (`ReportBuilder.test.tsx`) or `frontend/tests/`

**Interfaces:**
- Under each headline input, when the report has a `template_id`, a text input `aria-label="Slide <n> subheading"`, disabled once approved, saved through the existing `PUT .../storyline` call. "+ Add headline" adds `subheading: ""`.
- [ ] **Step 1:** Test `shows an editable subheading field per slide when a template is set`, and the inverse without a template.
- [ ] **Step 2:** `cd frontend && npm test` → FAIL. **Step 3:** Implement. **Step 4:** `npm run lint && npx tsc -b && npm test` → PASS.
- [ ] **Step 5:** Screenshot the storyline step with Playwright and run `/impeccable:impeccable audit`, as `CLAUDE.md` requires after a UI change. Commit `feat(frontend): edit subheadings in the storyline`.

### Finish

- [ ] Full backend check: `cd backend && ruff check . && python3 -m pytest tests/test_reporting_*.py`.
- [ ] Run `/ponytail:ponytail-review` and `/code-review`, then fix what they find.
- [ ] Open a PR against `main` following the steward skill: label `risk:normal`, put `Spec: template-frame` in the body, and list every test change. AC-17, AC-18 and AC-19 are left for the evaluator.
- [ ] Say whether `openwiki/` needs an update (it does: house deck geometry and the upload fields change).
