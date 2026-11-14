# Company template frame for the house deck

## Why

Decks built by ARP must look like the company's own slides. The headline, the subheading and the body
sit exactly where the company template puts them, in the company's fonts. Everything inside the body
follows ARP's rules in `backend/arp/reporting/style/tokens.json` and `layouts.json`, which ARP already
enforces: layouts, type sizes, colours, word limits, and the lint, fit and visual-QA checks.

## What exists today

- `POST /api/reports/templates` ingests a .pptx (`style_profile.py`). It reads theme colours, theme fonts and
  each layout's placeholder *types*, but not their positions or sizes. The classic `pptx` output path uses
  this profile too.
- The house deck (`house_pipeline.py`) ignores `template_id`. The PDF and PNGs come from `html_render.py`
  and the PPTX from `house_pptx.py`. Both place everything from `tokens.json` on a 1920×1080 px canvas, and
  the PPTX is 20 in wide (9525 EMU per px).
- Content slots sit on a 12-column × 12-row grid inside the body area (`house_style.slot_rect`).
- A house deck's slide 0 is always the title slide (`house_pipeline.py:45`); content slides start at index 1.
- A house slide has a headline and no subheading. A person approves the storyline (`storyline.py`) before
  any slide is built, and the headlines are never rewritten afterwards.

## Goals

1. A template upload records three boxes from one content layout (headline, subheading, body). It also
   records the headline and subheading font family, size and bold flag, and stores the font files.
2. A house deck built with a `template_id` puts the headline, subheading and body in those boxes, in the
   template fonts, in the PDF, the PNG previews and the PPTX alike.
3. Each content slide gets a one-line subheading. It is drafted with its headline in the storyline and
   approved with it.

## Non-goals

- Copying the template's master slide: logos, background images, footers, page numbers.
- Template colours. Colours stay ARP's, in light and dark mode as today.
- Moving or resizing the boxes by hand after upload (approach C, left for later).
- Changing the classic `pptx`/`docx` output paths.

## Anti-goals

- A deck that looks right in the PDF but puts text in other positions or fonts in the PPTX.
- A text box that silently moves or shrinks because the text is too long. Overflow is reported, never
  hidden.
- Any change to decks built without a `template_id`, or to template uploads that work today.

## Approaches

| | How | Trade-off |
|---|---|---|
| **A (picked)** | Read the title, subheading and body placeholder boxes from a content layout of the .pptx and show a preview with the boxes drawn. If a box is missing, record why. | Automatic and exact for well-built templates. A template without proper placeholders can't be used for house decks. About 1 day. |
| B | Template gives fonts only; the three boxes are typed in as numbers. | Exact, but manual for every template. About half a day. |
| C | A, plus a drag editor in the preview to correct the boxes. | Most robust; about 2 days. Can be added on top of A later. |

The owner picked A.

## Design

### Scale

- **Canvas:** the template slide maps onto the existing 1920×1080 px canvas.
  `px = EMU × 1920 / slide_width_emu`. A 13.33 in (12192000 EMU) slide gives 144 px per inch.
- **Font sizes** scale the same way: `size_px = pt × 1920 / (slide_width_emu / 12700)`. On a 13.33 in
  slide that is pt × 2.
- **Output PPTX size:** with a template, `output.pptx` takes the template's slide size, at
  `slide_width_emu / 1920` EMU per px. Template text therefore keeps its point size: a 32 pt template title
  is 32 pt in the output. Without a template nothing changes (20 in, 9525 EMU per px).

### Upload (`POST /api/reports/templates`)

- **Multipart fields:** `file` (the .pptx, as today), `fonts` (zero or more font files, repeated) and
  `layout_name` (optional text).
- **Layout choice:** the layout named `layout_name`. Without it, the first layout in file order that has
  one title placeholder and at least two further body or subtitle placeholders.
- **Boxes:**
  - Headline: the title placeholder.
  - Subheading: the body or subtitle placeholder whose top edge is the first one below the headline's top
    edge, and that is less than a third of the slide height tall.
  - Body: the largest remaining body or object placeholder by area.

  Positions come from the layout. Where the layout doesn't set them, they come from the master's matching
  placeholder, the same inheritance PowerPoint uses.
- **Fonts:**
  - Headline and subheading: family, size and bold are read from the placeholder, then the master's title
    or body style, then the theme fonts (major for the headline, minor for the subheading).
  - The body family is the theme minor font. Everything in the body keeps the house type sizes.
- **Font files:** a file matches a family when its name is `<Family>-<weight>.(ttf|otf|woff2)`. The family
  in the file name has its spaces removed, and the comparison ignores case, the same rule
  `html_render._font_faces` uses for the house fonts. Files are stored in `report_templates/<id>/fonts/`.
  ARP's bundled families, Geist, Geist Mono and Hanken Grotesk, need no file.
- **No refusals.** Every upload that works today keeps working. The profile gains:
  - `frame`: `layout_name`, `headline`, `subheading`, `body` (each `{x, y, w, h}` in canvas px),
    `headline_font` and `subheading_font` (each `{family, size_px, bold}`), and `body_font_family`.
  - `frame_error`: a string.

  When a frame can't be built, `frame` is null and `frame_error` holds the first matching reason, checked
  in this order:
  1. `Template must be 16:9 (got <w>×<h>).` (EMU)
  2. `No layout has a title, a subheading and a body placeholder.`
  3. `Upload the font file for "<family>".`
- **Preview:** `GET /api/reports/templates/{template_id}/preview.png` returns the chosen layout at
  1920×1080 with the three boxes outlined and labelled "Headline", "Subheading" and "Body". It returns
  404 when `frame` is null.

### Using a template for a house deck

- `POST /api/reports` with `layout.output_format` = "house_deck" and a `template_id` whose profile has `frame` null returns 422 with detail
  `Template <id> cannot frame a house deck: <frame_error>`. A template without `frame_error`, stored
  before this change, gives `re-upload it` as the reason.
- **Headline and subheading:** drawn in their boxes, in their template family, size and bold, using ARP's
  colours. The accent rule above the headline is dropped, because it belongs to the house frame.
- **Body grid:** the 12×12 grid is laid out inside the body box, keeping the house gutter. Every existing
  layout and variant works unchanged.
- **Other text:** big numbers and subheads use the headline family; all other text uses the body family.
  The HTML inlines the font files the way it inlines the house fonts today. The PPTX names the same
  families; python-pptx cannot embed fonts.
- **Footer** (source refs and page number):
  - It stays at the house position, the 56 px row ending 96 px above the slide's bottom edge, when the
    body box ends at least 152 px above the bottom edge.
  - Otherwise there is no footer, and `\nSources: <refs joined by " · ">` is appended to the speaker
    notes.
- **Title and section slides** keep their house layout and positions and use the template families: the
  headline family for the title, the body family for the subtitle.
- `render_house_outputs`, `fit_deck` and `visual_qa` measure against the template geometry, so fit and QA
  see what the user will see.

### Subheading

- `StorylineSlide` and `SlideContent` each gain `subheading: str = ""`.
- **With a `template_id`,** the storyline prompt asks for one subheading per slide: one sentence of at
  most 20 words that adds the evidence or scope behind the headline.
- **Without a template,** the prompt never mentions subheadings.
- **Review screen:** the storyline review shows an editable subheading field under each headline, and
  approval covers both.
- **Checks:** subheadings are linted like headlines and never rewritten. When one overflows its box, its
  box keeps its size and the deck gets a finding with `stage` "fit", `rule` "subheading_overflow" and
  `slot` "subheading".

### Left to the builder

- Module layout. A `TemplateFrame` model next to `Tokens` is the obvious seam.
- How the preview PNG is drawn. The existing Chromium path is fine.
- The exact wording of the subheading prompt, within the rules above.

## Acceptance

**Fixture `frame.pptx`**, built in the test with python-pptx:

- Slide size 16:9, 12192000 × 6858000 EMU, so 144 px per inch.
- One layout, "Content", with:
  - a title placeholder at (1, 0.5, 11, 1) in (x, y, w, h), 32 pt bold;
  - a body placeholder at (1, 1.6, 11, 0.5) in, 18 pt, not bold;
  - a body placeholder at (1, 2.4, 11, 3.9) in.
- Theme major font "Testa Serif", minor font "Testa Sans".
- Font files `TestaSerif-700.ttf` and `TestaSans-400.ttf`: any valid font files, renamed.

The body box ends at 907.2 px, 172.8 px above the bottom edge. Slide indices are 0-based, and index 1 is
the first content slide.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `frame.pptx` and both font files | POST `/api/reports/templates` | 200; `frame.layout_name` = "Content"; `frame.headline` = {x 144, y 72, w 1584, h 144}; `frame.subheading` = {x 144, y 230.4, w 1584, h 72}; `frame.body` = {x 144, y 345.6, w 1584, h 561.6} (each ±1 px) | holdout |
| AC-2 | same upload | read the response | `headline_font` = {family "Testa Serif", size_px 64 ±0.1, bold true}; `subheading_font` = {family "Testa Sans", size_px 36 ±0.1, bold false}; `body_font_family` = "Testa Sans" | holdout |
| AC-3 | `frame.pptx` saved at 9144000 × 6858000 EMU | POST upload | 200; `frame` = null; `frame_error` = `Template must be 16:9 (got 9144000×6858000).` | holdout |
| AC-4 | `frame.pptx` without the 0.5 in body placeholder | POST upload | 200; `frame` = null; `frame_error` = `No layout has a title, a subheading and a body placeholder.` | holdout |
| AC-5 | `frame.pptx`, only `TestaSans-400.ttf` uploaded | POST upload | 200; `frame` = null; `frame_error` = `Upload the font file for "Testa Serif".` | holdout |
| AC-6 | AC-1 upload | list `report_templates/<id>/fonts/` | contains exactly `TestaSerif-700.ttf` and `TestaSans-400.ttf` | holdout |
| AC-7 | the AC-5 template | POST `/api/reports` with its `template_id` and `layout.output_format` "house_deck" | 422; detail = `Template <id> cannot frame a house deck: Upload the font file for "Testa Serif".` | holdout |
| AC-8 | the AC-1 template; a storyline of one slide (headline "H", subheading "S"), filled as `bullets/three` by a stand-in LLM | build the house deck | `output.pptx` slide size = 12192000 × 6858000 EMU; on slide 1, shape `headline` is at the AC-1 headline box and shape `subheading` at the AC-1 subheading box (±1 px at 6350 EMU/px) | holdout |
| AC-9 | same build | inspect slide 1's `headline` runs | font "Testa Serif", 32 pt, bold | holdout |
| AC-10 | same build | inspect slide 1 | every `slot:*` shape lies inside the AC-1 body box (±1 px); the `slot:items` shape's left edge is 144 px and its right edge 1728 px (±1 px); there is no `accent_rule` shape | holdout |
| AC-11 | same build | render the HTML, measure slide 1 in Chromium | the headline element's box equals the AC-1 headline box (±2 px); its computed font-family starts with "Testa Serif" | holdout |
| AC-12 | same build | inspect slide 1 | shapes `footer:refs` and `footer:page` exist, each with top 928 px and height 56 px (±1 px) | holdout |
| AC-13 | a template with the body box ending 40 px above the bottom edge; content slide with `source_refs` = ["ds_1"] and speaker notes "N" | build | slide 1 has no `footer:*` shape; its speaker notes are `N\nSources: ds_1` | holdout |
| AC-14 | same build | inspect slide 0 (title) | `slot:title` is at the same box as in a build without a template, and its runs use font "Testa Serif" | holdout |
| AC-15 | a request with the AC-1 `template_id`; a stand-in LLM that records its prompt and returns slides with subheadings | draft the storyline | the recorded prompt contains `subheading` and `at most 20 words`; the stored storyline slides keep the returned subheadings | holdout |
| AC-16 | the AC-8 build with a subheading of 60 words | build | slide 1's `subheading` text equals the 60 words unchanged; its shape box still equals the AC-1 subheading box; the findings contain exactly one with `rule` "subheading_overflow", and it has `stage` "fit", `slot` "subheading", `slide` 1 | holdout |
| AC-17 | a report with the AC-1 template awaiting storyline approval | open it in the app | every storyline slide shows an editable subheading field under its headline | evaluator |
| AC-18 | same report; edit slide 1's subheading to "Edited sub" and approve | open the slide 1 preview PNG | "Edited sub" appears in the subheading box, under the headline | evaluator |
| AC-19 | AC-1 upload | GET `/api/reports/templates/{id}/preview.png` | a 1920×1080 PNG with three outlined boxes labelled "Headline", "Subheading", "Body" at the AC-1 positions | evaluator |
| AC-20 | the AC-3 template | GET its `preview.png` | 404 | holdout |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-21 | a request without `template_id` | draft the storyline with a recording stand-in LLM | the recorded prompt does not contain `subheading`; every storyline slide has `subheading` = "" | holdout |
| AC-22 | the AC-8 deck without `template_id` | build | `output.pptx` slide size = 18288000 × 10287000 EMU; on slide 1 `headline` is at x 96, y 96 px, its runs use font "Geist"; an `accent_rule` shape exists; `footer:refs` has top 928 px (±1 px) | holdout |
| AC-23 | a template profile stored before this change (no `frame` key) | GET `/api/reports/templates` | 200; that profile is listed with `frame` = null | holdout |
| AC-24 | a profile stored before this change | POST `/api/reports` with its `template_id` and `layout.output_format` "house_deck" | 422; detail ends with `re-upload it` | holdout |
| AC-25 | the AC-5 template (no frame) | POST `/api/reports?render=false` with its `template_id` and `layout.output_format` "pptx", stand-in LLM | 200; the manifest's `template_id` equals it (the classic path still accepts frameless templates) | holdout |
