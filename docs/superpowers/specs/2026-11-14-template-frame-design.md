# Company template frame for the house deck

## Why

Decks built by ARP must look like the company's own slides: the headline, the subheading and the body
sit exactly where the company template puts them, in the company's fonts. Everything inside the body
(layouts, type sizes, colours, word limits, the lint, fit and visual-QA checks) keeps following ARP's own
rules in `backend/arp/reporting/style/tokens.json` and `layouts.json`, which are already enforced.

## What exists today

- `POST /reporting/templates` ingests a .pptx (`style_profile.py`). It reads theme colours, theme fonts and
  each layout's placeholder *types*, but not their positions or sizes.
- The house deck (`house_pipeline.py`) ignores `template_id`: the PDF/PNGs come from `html_render.py` and the
  PPTX from `house_pptx.py`, both placing everything from `tokens.json` on a 1920×1080 px canvas.
- Content slots sit on a 12-column × 12-row grid inside the body area (`house_style.slot_rect`).
- A house slide has a headline and no subheading. The storyline (`storyline.py`) is approved by a person
  before any slide is built; headlines are never rewritten afterwards.

## Goals

1. A template upload records three boxes from one content layout (headline, subheading, body) and the
   headline and subheading font family, size and bold flag. It also takes the font files.
2. A house deck built with a `template_id` puts the headline, subheading and body in those boxes, in the
   template fonts, in the PDF, the PNG previews and the PPTX alike.
3. Each content slide gets a one-line subheading, drafted with its headline in the storyline and approved
   with it.

## Non-goals

- Copying the template's master slide: logos, background images, footers, page numbers.
- Template colours. Colours stay ARP's (light and dark mode as today).
- Moving or resizing the boxes by hand after upload (approach C, left for later).
- Non-16:9 templates.

## Anti-goals

- A deck that looks right in the PDF but has text in other positions or fonts in the PPTX.
- A text box that silently moves or shrinks because the text is too long. Overflow is reported, never
  hidden.
- Any change to decks built without a `template_id`.

## Approaches

| | How | Trade-off |
|---|---|---|
| **A (picked)** | Read the title, subheading and body placeholder boxes from a content layout of the .pptx, show a preview with the boxes drawn, refuse uploads where one is missing. | Automatic and exact for well-built templates; a template without proper placeholders is refused. About 1 day. |
| B | Template gives fonts only; the three boxes are typed in as numbers. | Exact, but manual per template. About half a day. |
| C | A plus a drag editor in the preview to correct the boxes. | Most robust, about 2 days. Can be added on top of A later. |

The owner picked A.

## Design

### Upload (`POST /reporting/templates`)

- Accepts the .pptx plus zero or more font files (`.ttf`, `.otf`, `.woff2`) and an optional `layout_name`.
- **Layout choice:** the layout named `layout_name`; without it, the first layout (in file order) with one
  title placeholder and at least two further body/subtitle placeholders.
- **Boxes:** headline = the title placeholder. Subheading = the body/subtitle placeholder whose top edge is
  closest below the headline's top edge and that is shorter than a third of the slide height. Body = the
  largest remaining body/object placeholder by area. Positions come from the layout, falling back to the
  master's matching placeholder when the layout does not set them (PowerPoint's own inheritance).
- **Fonts and sizes:** for headline and subheading, family, size (pt) and bold are read from the placeholder,
  then the master's title or body style, then the theme fonts. Body text uses the theme minor font.
  House type sizes stay for everything in the body.
- **Refusals (HTTP 422, the message names the problem):**
  - slide size not 16:9: `Template must be 16:9 (got <w>×<h>).`
  - no layout with all three boxes: `No layout has a title, a subheading and a body placeholder.`
  - a headline, subheading or body font family with no uploaded file and not one of ARP's bundled fonts:
    `Upload the font file for "<family>".`
- **Stored:** the profile gains `frame` = { `layout_name`, `headline`, `subheading`, `body` (each x, y, w, h in
  canvas px, scaled so the slide width is 1920), `headline_font`, `subheading_font` (family, size_px, bold),
  `body_font_family` }. Font files are stored under the template's directory.
- **Response** includes the profile and a `preview_png` URL: the chosen layout at 1920×1080 with the three
  boxes outlined and labelled.

### Rendering (template active)

- **Headline and subheading** are drawn in their boxes in their template font, size and bold. ARP's colours
  apply. The accent rule above the headline is dropped (it belongs to the house frame).
- **Body grid:** the 12×12 grid is laid out inside the body box (house gutter kept); every existing layout
  and variant works unchanged.
- **All text** uses the template families: heading family for headline, subheading, big numbers and
  subheads; body family for the rest. Font files are inlined in the HTML like the house fonts are today.
  The PPTX names the same families (embedding is not possible with python-pptx).
- **Footer (source refs and page number)** sits at the house footer position if the space between the
  body box and the slide's bottom edge is at least the footer band (56 px); otherwise it is left out and the
  source refs are appended to the speaker notes.
- **Title and section slides** keep their house layout, in the template fonts. (Builder's call, flagged.)
- `render_house_outputs`, `fit_deck` and `visual_qa` measure against the template geometry, so fit and QA
  see what the user will see.

### Subheading

- `StorylineSlide` gains `subheading: str = ""` and `SlideContent` gains `subheading: str = ""`.
- With a `template_id`, the storyline prompt asks for one subheading per slide: one sentence, at most 20
  words, adding the evidence or scope behind the headline. Without a template it asks for none.
- The storyline review screen shows an editable subheading field under each headline. Approval covers both.
- Subheadings are linted like headlines and never rewritten. A subheading that overflows its box gets a
  `fit` finding with rule `subheading_overflow`, like a headline overflow does today.

### Left to the builder

- Module layout (a `TemplateFrame` model next to `Tokens` is the obvious seam).
- How the preview PNG is drawn (the existing Chromium path is fine).
- Exact wording of the subheading prompt, within the rules above.

## Acceptance

Fixture: `frame.pptx`, built in the test with python-pptx: 16:9 (12192000 × 6858000 EMU), one layout
"Content" with a title at (1, 0.5, 11, 1) inches, a body placeholder at (1, 1.6, 11, 0.5) inches with 18 pt
text, a body placeholder at (1, 2.4, 11, 4.2) inches, theme major font "Testa Serif", minor "Testa Sans",
title 32 pt bold; plus `TestaSerif-700.ttf` and `TestaSans-400.ttf` (any valid font files renamed).
1 inch = 96 px on the 1920 px canvas (12192000 EMU = 1920 px).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `frame.pptx` and both font files | POST `/reporting/templates` | 200; `frame.layout_name` = `"Content"`; `frame.headline` = {x 96, y 48, w 1056, h 96}; `frame.subheading` = {x 96, y 153.6, w 1056, h 48}; `frame.body` = {x 96, y 230.4, w 1056, h 403.2} (each ±1 px) | holdout |
| AC-2 | same upload | read `frame` fonts | `headline_font` = {family "Testa Serif", size_px 42.67 ±0.1, bold true}; `subheading_font.family` = "Testa Sans", `size_px` 24 ±0.1; `body_font_family` = "Testa Sans" | holdout |
| AC-3 | `frame.pptx` saved at 4:3 (9144000 × 6858000) | POST upload | 422, detail = `Template must be 16:9 (got 9144000×6858000).` | holdout |
| AC-4 | `frame.pptx` without the 0.5-inch body placeholder | POST upload | 422, detail = `No layout has a title, a subheading and a body placeholder.` | holdout |
| AC-5 | `frame.pptx`, only `TestaSans-400.ttf` uploaded | POST upload | 422, detail = `Upload the font file for "Testa Serif".` | holdout |
| AC-6 | the AC-1 template and a deck of one `bullets/three` slide with a stand-in LLM | build the house deck | `output.pptx` slide 1: shape `headline` at the AC-1 headline box and `subheading` at the AC-1 subheading box (±1 px); headline runs use font "Testa Serif", 32 pt, bold | holdout |
| AC-7 | same build | inspect `output.pptx` | every `slot:*` shape lies inside the AC-1 body box (±1 px); the `items` slot's left edge = 96 px and right edge = 1152 px (±1 px) | holdout |
| AC-8 | same build | inspect the rendered HTML | the headline element's computed box equals the PPTX `headline` shape box (±2 px) and its computed font-family starts with "Testa Serif" | holdout |
| AC-9 | the AC-1 template (447 px from body bottom to slide bottom) | build | slide 1 has shapes `footer:refs` and `footer:page` | holdout |
| AC-10 | a template whose body box ends 40 px above the slide's bottom edge, slide with `source_refs = ["ds_1"]` | build | no `footer:*` shapes; speaker notes end with `ds_1` | holdout |
| AC-11 | a request with the AC-1 `template_id` and a stand-in LLM returning a storyline with subheadings | draft the storyline | the storyline prompt contains the words `subheading` and `at most 20 words`; every returned slide keeps its subheading | holdout |
| AC-12 | a subheading of 60 words on the AC-1 template | build | the deck keeps the subheading text unchanged and has one finding with `stage` "fit", `rule` "subheading_overflow", `slide` 0 | holdout |
| AC-13 | a report with the AC-1 template awaiting storyline approval | open the report in the app | each storyline slide shows an editable subheading field under its headline; an edited subheading appears unchanged on that slide in the preview PNG after approval | evaluator |
| AC-14 | AC-1 upload | open `preview_png` | a 1920×1080 PNG with three outlined boxes labelled "Headline", "Subheading", "Body" at the AC-1 positions | evaluator |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-15 | a request without `template_id` | draft the storyline | the prompt does not contain `subheading`; storyline slides have `subheading` = "" | holdout |
| AC-16 | the same deck without `template_id` | build | `output.pptx` shape positions and fonts are byte-identical in position and family to a build on `main` (headline at x 96, y 96, family "Geist"; `accent_rule` present) | holdout |
| AC-17 | an existing stored template profile without `frame` | GET `/reporting/templates` | 200 and the profile is listed with `frame` = null | holdout |
