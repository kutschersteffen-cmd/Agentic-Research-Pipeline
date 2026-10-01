# Deck Design Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** House decks look editorially designed: no sparse or plain-bullet slides, a layout chosen to fit each slide's content, a measured design check, and one shared set of design rules.

**Architecture:**
- **Layout library v2.** Layouts are redesigned with `/impeccable` at design time and are data plus templates in `style/`.
- **Art director (`art_direct.py`).** Deterministic code that maps the shape of each slide's content to a layout and enforces rhythm across the deck.
- **Measured design check.** `browser.measure` gains design rules (`stage="design"`), and slides that fail get one relayout retry.
- **Shared rules.** `style/design.md` feeds the slide-fill and visual-QA prompts and the `.claude/skills/deck-design` skill.

**Tech Stack:** Python 3.11, Pydantic 2, Jinja2, Playwright/Chromium, python-pptx, React/TS (one finding-severity tweak).

**Spec:** `docs/superpowers/specs/2026-10-01-deck-design-quality-design.md`

## Global Constraints

- **Locked style.** DESIGN.md is locked: monochrome, metric numbers in ink, mono labels and table headers, square corners, light and dark. No new fonts or colours.
- **Type.** Font size never goes below its role size. "Fill by design" may only step *up* to a larger token role. The projector floor is 24px for all slide text except the footer chrome.
- **Headlines.** They are never rewritten. Slide 0 (title) and `section` slides are exempt from rhythm and from the `sparse`/`unbalanced` rules.
- **Thresholds** are copied verbatim from the spec:

| Rule | Fails when |
|---|---|
| `sparse` | content covers less than 55% of the body height |
| `unbalanced` | content is more than 20% off its intended anchor |
| `small_text` | text is under 24px |
| `no_focal` | the largest text is less than 1.6× the body size |
| `crowded` | the gap between blocks is less than the token gutter |

- **Rhythm** is copied verbatim from the spec:
  - never the same layout on 3 consecutive slides
  - at least one visual slide (chart, numbers or steps) in every 3 content slides
  - a `section` divider every 5–7 slides in decks of 12 or more
- **No silent changes.** Every relayout is a `Finding(stage="design", rule="relayout", severity="info")`. Leftover design problems are `severity="warn"` findings. Nothing is changed silently.
- **Compatibility.** Old layout ids still load. Stewardship decks keep their no-LLM path.
- **Done when** the existing `tests/test_reporting_*.py` and `tests/test_stewardship_*.py` stay green and `ruff check .` is clean.

## Review Focus

1. **Placeholder slide with empty slots** (from `llm_failed` or `bad_reference`). Expected: the art director leaves it as is, the design check reports `sparse` once, and nothing loops. Tested in Task 3.
2. **Title and section slides.** Expected: no `sparse`, `unbalanced` or rhythm findings; they are sparse on purpose. Tested in Task 4.
3. **A relayout drops content**, for example a chart slot when the target layout has no chart. Expected: the art director never picks such a layout while content would be dropped. If one is ever forced, there is a `slot_dropped` finding. Tested in Task 3.
4. **Cards whose items differ a lot in length** (3 words vs 12 words). Expected: the cards keep equal heights, the fit check still passes, and the text doesn't clip. Tested in Task 1 via the stress deck.
5. **Dark mode.** Expected: the design measures give the same result in dark mode, since the heading font differs. Tested in Task 4 (parametrised over mode).

---

## File map (backend/ unless noted)

| File | Responsibility |
|---|---|
| `arp/schemas/reporting.py` (modify) | `Finding.stage` adds `"design"`; `Finding.severity: Literal["info","warn"] = "warn"` |
| `arp/reporting/house_style.py` (modify) | `SlotSpec.type_role_short: str \| None`, `SlotSpec.short_words: int \| None`; `VariantSpec.anchor: Literal["center","top"] = "center"`; `VariantSpec.visual: bool = False` |
| `arp/reporting/style/layouts.json` (modify) | layout library v2 |
| `arp/reporting/style/templates/*.j2`, `deck.css.j2` (modify/create) | v2 templates |
| `arp/reporting/house_pptx.py` (modify) | v2 layouts in PPTX |
| `arp/reporting/art_direct.py` (create) | content shape → layout, rhythm, relayout |
| `arp/reporting/browser.py` (modify) | design measures |
| `arp/reporting/house_pipeline.py`, `deck_compat.py` (modify) | wiring |
| `arp/reporting/style/design.md` (create) | shared design rules |
| `arp/reporting/slide_fill.py`, `visual_qa.py` (modify) | inject `design.md` |
| `.claude/skills/deck-design/SKILL.md` (create, repo root) | Claude skill |
| `tests/fixtures/tpa_pitch.py` (create) | TPA pitch golden brief |
| `frontend/src/pages/ReportBuilder.tsx` (modify) | show info-severity findings muted |

---

### Task 1: Layout library v2 (HTML), designed with `/impeccable` + user gate

**Files:**
- Modify: `arp/schemas/reporting.py`, `arp/reporting/house_style.py`, `arp/reporting/style/layouts.json`, `arp/reporting/style/templates/*`, `arp/reporting/html_render.py`, `tests/fixtures/stress_deck.py`
- Create: `tests/fixtures/tpa_pitch.py`
- Test: `tests/test_reporting_house_style.py`, `tests/test_reporting_browser.py`

**Interfaces:**
- **Produces, layouts.** The new layouts and variants:
  - `statement/{support,plain}`: slots `statement` text, `support` text
  - `cards/{three,four}`: slot `items` list
  - `steps/{three,four,five}`: slot `items` list
  - `stat_row/{one,two,three,four}`: slots `number_i`, `label_i`
  - `split/{chart,table,list}`: slot `statement` text, plus `chart`, `table` or `items`
  - `chart_focus/full`: slots `chart`, `callout` text
  - `compare/default`: slots `left`, `right` text
- **Kept and redesigned:** `title`, `section` (gains a `number` text slot), `quote`, `table`, `summary`. The title slide's title uses the `big_number` role or larger. Table body and header text is at least 24px.
- **Old layouts still load:** `bullets`, `big_number`, `chart_takeaway`, `two_column`, `timeline`, `matrix`, `image`.
- **Slot-name families stay shared:** every list layout uses `items`, every stat layout uses `number_i`/`label_i`, and chart/table slots use `chart`/`table`. A relayout therefore carries the slots over by name.
- **Card items** split on the first `": "` into a title and a body; with no colon the whole item is the title.
- **Produces, schema.** `SlotSpec.type_role_short` and `SlotSpec.short_words`: when the slot's word count is ≤ `short_words`, the renderer uses `type_role_short`. This is how "fill by design" works.
  - `VariantSpec.anchor`
  - `VariantSpec.visual`: true for `stat_row`, `steps`, `chart_focus`, `split/chart`, `cards`
  - `Finding.severity`
- **Produces, fixture.** `tpa_pitch() -> tuple[ReportRequest, Storyline, list[SlideContent]]`. It holds the TPA pitch content from session scratch `pitch/build.py`: the notes, the 2 datasets, 10 headlines and fills. It is ported verbatim, with layouts unchanged (`bullets` etc.), so the art director has real work in Task 3.

- [ ] **Step 1: Write the failing tests.**

```python
def test_v2_layouts_present():
    assert {"statement","cards","steps","stat_row","split","chart_focus","compare"} <= set(load_layouts())

def test_list_layouts_share_items_slot():
    for lid in ("cards","steps","summary","bullets","timeline"):
        for v in load_layouts()[lid].variants:
            assert [s.name for s in v.slots if s.kind == "list"] == ["items"]

def test_short_text_steps_up_type_role():   # renderer picks type_role_short when words <= short_words
    html = render_deck_html(Deck(title="T", slides=[SlideContent(headline="h", layout="statement", variant="plain",
                                                                  slots={"statement": "Short claim."})]), [])
    assert 'data-role="big_number"' in html or 'data-role="headline"' in html   # whichever role layouts.json pins

async def test_stress_deck_max_fits_in_both_modes(mode): ...   # existing test, now over v2 layouts too
async def test_table_text_at_least_24px(mode): ...   # table/compact → every td/th computed font-size >= 24px
async def test_cards_with_uneven_items_keep_equal_heights(mode):
    # cards/three with items of 3, 8 and 12 words → three card boxes with equal height (±1px), zero fit findings
```

- [ ] **Step 2: Run** `python -m pytest tests/test_reporting_house_style.py tests/test_reporting_browser.py -q`. Expected: FAIL.
- [ ] **Step 3: Design the v2 layouts with `/impeccable`.** Run `critique` on the current deck HTML (the stress deck and the TPA pitch), then `layout`, `typeset` and `polish`. Stay inside DESIGN.md (mode "Read/Persuade hybrid: a slide is presented"). Implement the templates and CSS, plus the schema fields above.
- [ ] **Step 4: Measure the stress-deck limits.** Re-measure `max_words`/`max_items` with the stress deck in both modes. Also check `short_words`: a slot at `short_words` words with `type_role_short` must fit.
- [ ] **Step 5: Render the sample PDFs.** Render the TPA pitch fixture with each slide's layout set **by hand** to the v2 layout the spec table implies, in light and dark. Write the PDFs to scratch `design-v2/tpa-{light,dark}.pdf` and look at the PNGs yourself.
- [ ] **Step 6: Run** `python -m pytest tests/test_reporting_*.py -q && ruff check .`. Expected: PASS. Commit with message `feat(reporting): layout library v2 (editorial), designed with impeccable`.
- [ ] **Step 7: STOP. User gate.** The controller sends the two PDFs. Only after the user approves do Task 2 and later begin. Revisions loop back to Step 3.

---

### Task 2: v2 layouts in PPTX

**Files:**
- Modify: `arp/reporting/house_pptx.py`
- Test: `tests/test_reporting_house_pptx.py`

**Interfaces:**
- **Consumes:** the Task 1 layouts, `type_role_short`/`short_words`, and the card title/body split rule.
- **Produces:** `build_house_pptx` renders every v2 layout:
  - shapes named `slot:<name>` at their `slot_rect`
  - each card or step item as its own shape, named `slot:items:<i>`
  - step connectors as a line shape

- [ ] **Step 1: Write the failing tests.**

```python
def test_pptx_renders_every_v2_variant(tmp_path):   # stress_deck("min") → one slide per variant, no exception
def test_pptx_cards_are_separate_shapes(tmp_path):  # cards/three → shapes slot:items:0..2, titles from "Title: body"
def test_pptx_short_text_uses_short_role(tmp_path): # statement with 3 words → font size == type_role_short px*0.75 pt
```

- [ ] **Step 2: Run** `python -m pytest tests/test_reporting_house_pptx.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse the existing `_box`, text and chart helpers. For the step connector, draw one straight line at node-centre height across the slot.
- [ ] **Step 4: Run** `python -m pytest tests/test_reporting_*.py -q && ruff check .`. Expected: PASS. Also run the parity test where `soffice` is available. Commit with message `feat(reporting): v2 layouts in pptx`.

---

### Task 3: Art director

**Files:**
- Create: `arp/reporting/art_direct.py`
- Modify: `arp/reporting/house_pipeline.py` (after fill, before lint), `arp/reporting/deck_compat.py` (old `bullets` → `cards`/`steps` via `art_direct`), `frontend/src/pages/ReportBuilder.tsx` (info findings muted, under a "Layout changes" label)
- Test: `tests/test_reporting_art_direct.py`

**Interfaces:**
- **Consumes:** `load_layouts`, `get_variant`, `VariantSpec.visual`, and the Task 1 slot families.
- **Produces:**
  - `shape_of(slide: SlideContent) -> str`, returning one of: `"stat_1"`, `"stats"`, `"parallel"`, `"ordered"`, `"statement"`, `"chart_short"`, `"chart_long"`, `"contrast"`, `"table"`, `"other"`.
  - `candidates(shape: str, slide: SlideContent) -> list[tuple[str, str]]` returns an ordered list of (layout, variant).
  - `relayout(slide: SlideContent, layout: str, variant: str) -> tuple[SlideContent, list[str]]` returns the moved slide and the names of any dropped slots.
  - `direct(deck: Deck) -> tuple[Deck, list[Finding]]`. It skips slide 0 and `section` slides.
  - `next_layout(slide: SlideContent) -> tuple[str, str] | None` returns the next candidate after the current one. Task 4 uses it.
- **Shape rules** (the spec table):

| Shape | Condition |
|---|---|
| `stat_1` | exactly 1 number slot filled |
| `stats` | 2–4 numbers filled |
| `parallel` | 3–4 list items, each under 12 words, not ordered |
| `ordered` | 3–5 list items, ordered |
| `statement` | exactly one text slot filled, no data |
| `chart_short` | a chart plus 25 words or fewer of text |
| `chart_long` | a chart plus more than 25 words of text |
| `contrast` | two text slots `left`/`right` |
| `table` | a table |

  A list counts as **ordered** when any item starts with one of:
  - a month, a quarter or a year (`^(Jan|Feb|…|Dec|Q[1-4]|\d{4})\b`)
  - `^\d+[.)]`
  - `^(First|Then|Next|Finally)\b`

- **Algorithm** (one pass, left to right):
  1. Take the first candidate that drops no non-empty slot.
  2. Apply the rhythm rules. On a third consecutive repeat, take the next candidate. If 3 content slides in a row are non-visual, the third switches to its first `visual` candidate when one exists.
  3. In decks of 12 or more slides with no `section` slide between slides 5 and 7, insert `section` with `title` set to the next slide's headline and `number` set to the ordinal. This is the only time a slide is added; record a `relayout` finding.

- [ ] **Step 1: Write the failing tests.** One test per shape rule, plus:

```python
def test_bullets_three_short_items_become_cards(): ...
def test_dated_items_become_steps(): ...
def test_no_three_in_a_row(): ...            # 4 parallel-list slides → layouts not equal for any 3 consecutive
def test_visual_every_three_content_slides(): ...
def test_section_inserted_in_long_deck(): ...
def test_title_and_section_untouched(): ...
def test_placeholder_slide_left_alone(): ...  # bullets/three with items [] → unchanged, no finding
def test_never_drops_non_empty_slot(): ...    # slide with chart + items → never a layout lacking chart
def test_every_change_is_an_info_finding(): ...
def test_tpa_fixture_has_no_plain_bullets_after_direct(): ...  # tpa_pitch() fills → no layout == "bullets"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_reporting_art_direct.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement and wire it in.** Wire `direct` into `build_house_deck` right after the deck is assembled from the fills. Wire it into `deck_compat.deck_from_plan` too, so stewardship decks get it with no LLM involved.
- [ ] **Step 4: Run** `python -m pytest tests/test_reporting_*.py tests/test_stewardship_*.py -q && ruff check .`, then `cd ../frontend && npm run build && npm run lint`. Expected: PASS. Commit with message `feat(reporting): deterministic art director`.

---

### Task 4: Measured design check and one relayout retry

**Files:**
- Modify: `arp/reporting/browser.py`, `arp/reporting/house_pipeline.py`, `arp/reporting/style/templates/*` (mark footer and page number with `data-chrome`)
- Test: `tests/test_reporting_browser.py`, `tests/test_reporting_house_service.py`

**Interfaces:**
- **Consumes:** `VariantSpec.anchor`, `art_direct.next_layout`, `art_direct.relayout`.
- **Produces:** `measure(html)` also returns `stage="design"`, `severity="warn"` findings with the rules and thresholds in Global Constraints.
- **What is measured:**
  - **Content extent:** the union of each slot's actual content rects (a Range over its text nodes, plus chart, table and img boxes). The fixed slot boxes are not used.
  - **`sparse`:** content-union height divided by body height is less than 0.55.
  - **`unbalanced`:** compute the area-weighted vertical centre of the content rects. For `anchor="center"`, it fails when `abs(c − body_mid) / body_h > 0.20`. For `anchor="top"`, the check is skipped.
  - **`small_text`:** any computed font-size under 24px, ignoring elements with `data-chrome`.
  - **`no_focal`:** the largest font-size on the slide divided by the body role px is less than 1.6.
  - **`crowded`:** the vertical or horizontal gap between content rects of different slots is less than `tokens.grid.gutter`.
  - Slide 0 and `section` slides skip `sparse` and `unbalanced`.
- **Pipeline:** after `fit_deck`, every slide with a warn `design` finding gets `art_direct.next_layout` **once**. If there is one, it is relayed out (with an info `relayout` finding), fit with `max_passes=1`, and measured again. What is left is kept. The retry happens before visual QA.

- [ ] **Step 1: Write the failing tests.**

```python
async def test_sparse_slide_flagged(mode):        # bullets/three with 3 four-word items (old layout) → "sparse"
async def test_title_and_section_not_sparse(mode):
async def test_small_text_flagged(mode):          # table with 40 rows forcing caption < 24px → "small_text"  (or a CSS override fixture)
async def test_footer_chrome_ignored(mode):       # stress deck min → no small_text from footer
async def test_tpa_v2_layouts_have_no_design_findings(mode):  # tpa fixture after art_direct.direct → measure → no design warns
async def test_pipeline_retries_relayout_once(tmp_path, fake_llm):  # a slide that is sparse in its first candidate moves to the next; exactly one extra relayout finding
async def test_placeholder_reports_sparse_once_and_stops(tmp_path, fake_llm):
```

- [ ] **Step 2: Run** `python -m pytest tests/test_reporting_browser.py tests/test_reporting_house_service.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Extend the single `page.evaluate` script so it also returns content rects, font sizes and anchors per slot. Compute the rules in Python.
- [ ] **Step 4: Check the threshold tests.** If the stress deck or the golden decks trip a rule, fix the layout. Never loosen a threshold in the spec.
- [ ] **Step 5: Run** `python -m pytest tests/test_reporting_*.py -q && ruff check .`. Expected: PASS. Commit with message `feat(reporting): measured design check with one relayout retry`.

---

### Task 5: Shared design rules, skill, prompts, acceptance

**Files:**
- Create: `arp/reporting/style/design.md`, `.claude/skills/deck-design/SKILL.md`, `tests/test_reporting_golden_briefs.py::test_tpa_pitch_acceptance`
- Modify: `arp/reporting/slide_fill.py`, `arp/reporting/visual_qa.py`, `pyproject.toml` (package-data already covers `style/*.md`; verify), `docs/TECHNICAL_REFERENCE.md` §3.14, `.claude/CLAUDE.md` (one line under "Which plugin does what": decks → deck-design skill)

**Interfaces:**
- **Consumes:** everything above.
- **Produces:** `design.md` sections, each with an exact `## ` heading:
  - `Principles`
  - `Layouts`, one line per layout naming what content it is for
  - `Content to layout`, the spec table
  - `Rhythm`
  - `Focal point and whitespace`
  - `Review checklist`, which `visual_qa` injects verbatim
  - `Examples`, 4 before/after pairs

  `slide_fill` injects everything except `Review checklist`. `visual_qa` injects `Review checklist`.
- **Skill.** The front matter `description` triggers on "deck", "slides", "presentation", "pitch". The body holds the 4 steps from the spec and points to `backend/arp/reporting/style/design.md`. It includes the dev-time `impeccable detect` command with its ignore list (the Geist brand font, headline leading).

- [ ] **Step 1: Write the failing tests.**

```python
def test_design_md_has_required_sections(): ...         # all seven "## " headings present
def test_fill_prompt_includes_design_rules(fake_llm): ... # "Content to layout" text in system prompt, "Review checklist" absent
def test_qa_prompt_includes_review_checklist(fake_llm): ...
async def test_tpa_pitch_acceptance(tmp_path, fake_llm):
    # tpa_pitch() through approve_storyline with QAResult(edits=[]) → output.pdf + output.pptx,
    # zero fit/lint findings, zero severity="warn" design findings, no slide layout == "bullets"
```

- [ ] **Step 2: Run** `python -m pytest tests/test_reporting_golden_briefs.py tests/test_reporting_slide_fill.py tests/test_reporting_visual_qa.py -q`. Expected: FAIL.
- [ ] **Step 3: Write `design.md` and the skill** in plain human wording, applying the humanizer rules. Wire both prompts.
- [ ] **Step 4: Run** `python -m pytest -q` and compare against the baseline of 8 missing-dependency failures. Also run `ruff check .`, then the frontend build. Then rebuild the TPA pitch in both modes to scratch `design-v2/final-{light,dark}.pdf` and look at the PNGs.
- [ ] **Step 5: Commit** with message `feat(reporting): shared design rules, deck-design skill, TPA acceptance`. The controller sends the final PDFs to the user for the spec's acceptance sign-off.

---

## Plan revision after the spec amendment (2026-10-01)

The approved spec amendment adds two density modes and 7 committee layouts. The user's gate verdict on the first v2 round was "revise". Changes per task:

**Task 1 gets revision round R1** (same files; it also creates `tests/fixtures/tpa_pitch_committee.py`).
- Fix the gate findings:
  - Cards: a bold short title with the body directly under the number, so the card has no empty middle. A colon-less item renders as body-size text, not a 36px title.
  - `compare` panels: content anchored to the top, a larger type step for short prose, and panels that size to their content.
- Add the schema fields:
  - `LayoutInstructions.density` (`"present"` | `"committee"`, default `"present"`)
  - `SlideContent.eyebrow`
  - the `takeaway_bar` slot
- Render density with a `data-density` attribute on `<body>` so CSS can switch type steps. Committee mode uses the body role and is never below 24px.
- Add the HTML layouts `flow`, `profile`, `scatter_zone`, `table/heat`, `matrix2x2`, `tree` and `decisions`, with the item formats given in the amendment. Put their parsers in `arp/reporting/structured.py`:
  - `parse_flow(items) -> list[Stage]`
  - `parse_meters`
  - `parse_quadrants`
  - `parse_tree(items) -> TreeNode`
  - `parse_deltas`

  Each parser raises `ValueError` with a readable message.
- Draw the decision tree as an SVG: nodes laid out left to right by depth, with orthogonal connectors labelled Yes and No. Support at most 4 levels; deeper trees raise `ValueError`.
- Tests:
  - one parser test per format, valid and invalid
  - a stress-deck slide per new variant, with zero fit findings in both modes and both densities
  - the eyebrow renders above the headline
  - the takeaway bar renders as a tinted box with a bold label
  - status tints use only the DESIGN.md status tokens
- Fixture: `tpa_pitch_committee()` holds the same 10 headlines with committee-density fills, about 80–150 words per slide, eyebrows and takeaway bars. It uses `profile` (one illustrative profile built from the indicator **structure** only: walk 34, talk 30 and the category counts, never invented company scores), `flow` (assessment pipeline: retrieve → answer → verify → ground → review), `table/heat`, `matrix2x2` (walk/talk × barrier headroom, following METHODOLOGY's ambition-vs-headroom framing) and `decisions`.
- Render to scratch `design-v2/r1/tpa-present-{light,dark}.pdf` and `tpa-committee-{light,dark}.pdf`. **STOP: user gate again.**

**Task 2** (PPTX) also covers the 7 new layouts, `eyebrow` and `takeaway_bar`:
- flow arrows as connector lines
- the tree as native shapes and connectors
- meters as two rectangles each
- heat cells as filled table cells

**Task 3** (art director) is density-aware:
- In committee mode it prefers `split`, `profile`, `table/heat` and `scatter_zone` for exhibit-plus-text content.
- It maps ordered lists of 4–6 stages that have sub-boxes to `flow`.
- Decision-like lists (imperatives) at the end of the deck go to `decisions`.
- Tests for each.

**Task 4** (design check) adds:
- density-dependent `sparse` thresholds: 0.55 in present mode, 0.70 in committee mode
- the `dense` rule: words per slide over 60 in present mode or 180 in committee mode. Its fix order is a split via `fit`, then `appendix=True` with an info finding.
- the headline 2-line cap, enforced through the existing `overflow` on `headline`. The headline box height becomes 2 lines.

**Task 5:** `design.md` documents both densities and the 7 new layouts. The acceptance test covers both TPA fixtures.
