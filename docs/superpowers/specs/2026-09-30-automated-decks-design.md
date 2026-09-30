# Automated decks: design

Status: draft for review · Extends function 13 (Presentation & Reporting Tool)

## Goal

Stop building presentations by hand. A brief goes in, and a finished deck comes out. The deck
always follows one house style, adapts its layout to each slide's content, and reads as if a
person wrote it. The only manual step is approving a one-page storyline.

## Decisions

| Question | Decision |
|---|---|
| Deck types in scope | Free-form topics, pipeline results, recurring periodic decks, client/stewardship decks |
| Style source | A new house style, designed once and locked. No corporate template |
| Output | PDF (primary, exact) and editable `.pptx` (close, not pixel-identical) |
| Human involvement | Approve the storyline (one headline per slide). Everything after that is automatic |
| Language | English |
| Rendering approach | HTML-first. Chromium renders and measures; the `.pptx` is built from a matching master |

Unchanged constraints from the repo: every number traces to supplied data or notes. Stewardship
decks keep their "no model-written text" rule. They skip the LLM steps and use only the new renderer.

## Current state (what this fixes)

`backend/arp/reporting/` already drafts a `ReportPlan` with one LLM call and renders it with python-pptx,
python-docx and reportlab. Gaps:

- There is no text fitting. Long bullets and headings overflow (`deck_builder.py` sets only
  `word_wrap`). `target_length` is only a prompt hint, even though the schema docstring says it is enforced.
- Layout choice is limited to four `layout_hint` values, so the deck looks the same on every slide.
- Tone is an enum passed through with no guidance. There is no style guide and no check for AI tells.
- Dataset and column references are validated only at render time, where a bad reference fails the whole render.
- The pdf renderer passes LLM text into reportlab `Paragraph` markup unescaped, so `&` or `<` can break it.

## Pipeline

```
Brief ─► Storyline ─► [approve] ─► Slide fill ─► Write-check ─► Render+fit ─► Visual QA ─► PDF + PPTX
```

### 1. Brief

This extends `ReportRequest` with:

- `goal`: what the audience should decide or believe (required).
- `sources`: notes, documents, datasets (existing), and optional `run_refs` (pipeline run IDs).
- `audience`: existing `AudienceProfile`.

**Pipeline adapters** (`reporting/adapters/<function>.py`) turn a run's results into
`QuantitativeDataset`s plus a short list of key facts. Adapters never produce slides. Start with Decision
Studio, portfolio/climate analytics and universe runs. Add others when a deck needs them.

**Periodic decks** are a saved brief plus an approved storyline plus a schedule. Each re-run reuses
the storyline, refreshes the data through the adapters, and redoes slide fill onward. If a headline's
claim no longer holds on the new data (the linter's number check fails), the run stops and asks for
re-approval instead of shipping.

### 2. Storyline (LLM call 1)

The output is `Storyline{title, slides[{headline, purpose, source_refs}]}`. Every headline is a full
sentence that states the takeaway. Read top to bottom, the headlines tell the whole argument.

Approval uses the existing plan editor in `ReportBuilder.tsx`: edit, reorder, add or delete headlines, then approve.

### 3. Slide fill (LLM call per slide)

For each approved headline the model returns `{layout, variant, slots{…}, chart?, table?, speaker_notes}`.
Code checks this straight after the call:

- `layout` and `variant` exist in the library.
- The slot names match the variant.
- Every `dataset_id` and column exists. A failure gets one retry with the error message, then a
  flagged placeholder. It never fails the whole deck.

`content_planner.py` splits into `storyline.py` and `slide_fill.py`. `ReportSection` gains `layout`,
`variant` and `slots`. The old `layout_hint` maps onto layouts so that existing plans still render.

### 4. Write-check

See **Writing** below.

### 5. Render and fit

- Jinja templates, one per layout, share one CSS file generated from `tokens.json`.
- Playwright plus the preinstalled Chromium render the slides. For every slot the renderer reads
  `scrollHeight > clientHeight` and `scrollWidth > clientWidth`, and checks bounding boxes for
  collisions and grid violations.
- The fix order for an overflowing slot is:
  1. rewrite shorter (LLM, target word count computed from the overflow ratio)
  2. switch to a roomier variant
  3. split into two slides
- Font size never shrinks. The loop is capped at 3 passes per slide. Anything left over is reported.
- The PDF comes from `page.pdf()` (vector text). PNG thumbnails come from the same page and feed
  the existing preview strip, replacing the LibreOffice preview path for HTML-rendered decks.
- All text is HTML-escaped by Jinja autoescape. That also fixes the pdf markup bug for the new path.

### 6. Visual QA (one vision-LLM pass)

This pass sends the slide PNGs with a fixed checklist:

- hierarchy clear
- one focal point
- orphan words
- lone bullets
- near-empty slides
- chart supports the headline

It returns edits in the slide-fill schema and runs the fit loop once more. There is only one round.

### 7. PPTX export

- `house.pptx` is generated by a script from `tokens.json`, with one slide layout per HTML layout
  variant. Positions come from the same grid numbers, so the two renderers cannot drift apart.
- The text is the fitted text from the HTML render. There is no separate fitting.
- Charts are native and editable, reusing `chart_builder.py` with token colours.
- `deck_builder.py` gains a layout-by-name path. The old heuristics stay for template-based decks.

## House style

`reporting/style/tokens.json` is the single source for both renderers:

- **Canvas:** 16:9, 1920×1080, 12-column grid, fixed outer margins, fixed headline band.
- **Type:** 5 sizes (headline, subhead, body, caption, big number). Two open-licence fonts are
  embedded in the PDF and named in the `.pptx`. Line lengths are capped per slot.
- **Colour:** ink, muted neutral, one accent (used only for the slide's focal element), and the existing
  CVD-safe chart palette. Both themes must pass WCAG AA contrast, per PRODUCT.md's projector rule.
- **Recurring elements:** headline position, accent rule, footer with source line and page number.

The look is designed once. The impeccable and ui-ux-pro-max skills produce 3 visual directions,
rendered as the stress-test deck, and the user picks one before the build starts.

### Layout library

About 12 layouts, each with 2–3 variants. Each variant declares its slots and, for each slot, a
max word count, a max item count and allowed content (text, chart, table, image).

| Layout | Use | Variants |
|---|---|---|
| title | opening | plain, with key figure |
| section | divider | — |
| big-number | one striking stat | 1, 2, 3 numbers |
| chart-takeaway | chart plus 1–3 lines | chart left, chart right, full width plus caption |
| two-column | compare, pros/cons | text/text, text/chart |
| table | dense figures | compact, highlighted row |
| bullets | short argument | 3 items, 5 items |
| timeline | sequence, roadmap | 3–6 steps |
| quote | voice of client or source | — |
| matrix | 2×2 positioning | — |
| image | photo or diagram plus caption | — |
| summary | recommendations, next steps | — |

Flexibility comes from the model choosing a layout and variant per slide. Consistency comes from
code enforcing each variant's limits. Adding a layout means one template, one entry in `layouts.json`,
one pptx layout and one stress-test slide.

## Writing

1. **Style guide** (`reporting/style/writing.md`, about 1 page, injected into both prompts). It covers:
   - headlines as conclusions
   - plain verbs, digits for numbers, and naming the specific thing
   - hedging only on real uncertainty
   - concrete rules per audience level and per tone
   - three before/after examples
2. **Linter** (`reporting/lint.py`, deterministic, no LLM). Each rule is one entry. Findings name the
   slide, the slot and the rule. The first rules:
   - over a slot's word limit
   - stock AI vocabulary (seeded from the humanizer plugin's list: leverage, delve, robust,
     seamless, landscape, pivotal, …)
   - "not X but Y" contrasts
   - reflexive triads
   - more than one dash per slide
   - bold-as-label
   - exclamation marks
   - the same sentence opener repeated across slides
   - any number absent from the source data or notes
3. **Targeted rewrite.** Only flagged slots go back to the LLM with their rule, for at most 2 rounds.
   Anything still failing appears in a findings list on the review screen and is never dropped silently.

## Error handling

- An LLM call failure uses the existing bounded retry in `arp/llm/base.py`. After that the slide
  becomes a flagged placeholder, and the deck still renders.
- A bad data reference gets one retry, then a placeholder with the reason.
- Leftover overflow, lint or QA findings ship with the deck as a findings list, shown in the UI
  and written to `reports/<id>/findings.json`.
- A missing Chromium is a hard error at render, with an install hint. There is no silent fallback to the old renderer.

## Testing

- **Stress-test deck:** every layout and variant filled with max-length and min-length content.
  It must render with zero overflow and zero collisions. A PNG snapshot is committed.
- **Linter:** one test per rule (a sentence that should flag and one that should not).
- **Golden briefs:** 4, one per deck type, run end to end with the existing fake-LLM pattern, checking
  structure, fit and the findings list.
- **Parity:** the `.pptx` is rendered through LibreOffice and its text box positions are compared
  with the PDF, within a tolerance.
- The existing 40 `test_reporting_*` tests stay green.

## Build order

Each step ships something usable.

0. Pick a visual direction (3 options rendered as the stress-test deck).
1. `tokens.json`, the 12 layouts, the HTML renderer and the fit check. Existing plans render through
   the old `layout_hint` mapping. (2–3 days)
2. Storyline and slide-fill split, plus storyline approval in the Report Builder. (about 1 day)
3. Style guide, linter and targeted rewrite. (about 1 day)
4. `house.pptx` generator and PPTX export. (about 1 day)
5. Visual QA pass, pipeline adapters, periodic re-runs. (1–2 days)

## Out of scope

- Languages other than English. The linter rules are English-specific.
- Corporate templates for the HTML path. The existing template-ingest path stays as it is.
- Animations and transitions.
- docx output for the new path. Existing docx rendering is unchanged.
