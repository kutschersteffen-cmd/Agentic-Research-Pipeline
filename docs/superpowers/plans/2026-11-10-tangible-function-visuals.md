# Tangible function visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four slides to the published ARP deck that show extraction, the theme funnel and emerging themes as machine lines (documents in, instruction card into a machine, cited cards out).

**Architecture:** A small Python generator writes the four slide files in the deck's closed HTML subset, using one shared layout helper so the three machine-line slides share column positions. A second script renders the slides in Chromium and checks the acceptance rows that can be measured. Page images are cropped from real public filings, uploaded to the artifact's asset store and referenced as `/_blob/<id>`.

**Tech Stack:** Python 3 (scratchpad scripts, not repo code), PyMuPDF or `pdftoppm` for page crops, Playwright chromium for rendering, the Artifact tool for upload and publish.

**Spec:** `docs/superpowers/specs/2026-11-10-tangible-function-visuals-design.md`

## Global Constraints

- Slide canvas 1920x1080, inline styles from the closed subset, at most 200 elements per slide, no text under 24 px outside page images.
- Column left edges: IN x=128 (520 wide), MACHINE x=680 (520 wide), OUT x=1232 (560 wide), 32 px gaps.
- Images only as `/_blob/<id>` uploads. Caption form: `<company name> · <document title> · p.<page number>`.
- Exact texts: "Public filings, shown for illustration" (extraction slides), "demo data" (theme funnel and emerging themes), "grounded in code", "verified by a second model".
- No third-party logos outside page images; no "with", "powered by" or "in partnership" beside a filer's name.
- No figure or quote is typed by hand: each comes from a source page text layer or a stored run, and is listed in the speaker notes with its source.
- The deck stays private. Existing slides, ids and order do not change; the deck gains exactly 4 slides.
- Scripts live in the scratchpad, not in the repo.

## Review Focus

1. A quote wraps to many lines and overflows its card: cards must grow in height and the slide must still pass the 1080 px canvas check.
2. A page crop is unreadable at slide size: crop to the quoted region plus context, never a whole page at thumbnail size.
3. A demo or stored run for the theme funnel or emerging themes does not exist in this environment: stop and ask the owner, never write cards by hand.
4. A filing cannot be fetched from this environment: fall back to a page image already in the deck, and say so.
5. The status chip or a check dot would show a step that did not happen: derive both from the stored run, never from a default.

---

### Task 1: Source pack

**Files:**
- Create: `<scratchpad>/vis/sources.json`, `<scratchpad>/vis/pages/*.png`, `<scratchpad>/vis/check_sources.py`

**Interfaces:**
- Produces: `sources.json` with a list of entries `{id, kind: "page"|"run"|"slide", company, document, page, url, text, blob_url}`; page entries hold the source PDF's text-layer excerpt in `text`.

- [ ] **Step 1: Write `check_sources.py`** that loads `sources.json` and asserts every `page` entry's quoted strings appear in its `text` after collapsing whitespace, and every entry has a non-empty `url`.
- [ ] **Step 2: Run it** with an empty `sources.json`; expected: it fails on "no entries".
- [ ] **Step 3: Collect sources.** Read the deck slides `argus-walkthrough` and `rwe-tp-answers` for the stored Signify and RWE run values and pages. Fetch the public filing PDFs, render the cited pages to PNG, crop to the quoted region, extract the text layer. Upload each PNG with the Artifact tool (`asset: true`) and record its `/_blob/` URL. Entries needed: the Signify page (close-up), two more pages from Signify or RWE documents for the machine line.
- [ ] **Step 4: Run `check_sources.py`**; expected exit 0.
- [ ] **Step 5: Gate.** If a filing cannot be fetched, reuse the page image already in the deck and record that in `sources.json` as `"fallback": true`.

### Task 2: Shared layout helper

**Files:**
- Create: `<scratchpad>/vis/make_vis.py`, `<scratchpad>/vis/test_make_vis.py`

**Interfaces:**
- Produces in `make_vis.py`: constants `COLS = {"IN": 128, "MACHINE": 680, "OUT": 1232}`, `WIDTHS = {"IN": 520, "MACHINE": 520, "OUT": 560}`; functions `page_img(src: str, caption: str) -> str`, `instruction_card(title: str, items: list[str]) -> str`, `machine(card_html: str) -> str`, `value_card(value: str, unit: str, period: str, quote: str, page: str, status: str, dots: tuple[bool, bool, bool]) -> str`, `machine_slide(slide_id: str, eyebrow: str, title: str, in_html: str, machine_html: str, out_html: str, captions: tuple[str, str, str], notes: str, footer_right: str) -> str`, `slide(...)` for the close-up. All return HTML in the deck's subset.

- [ ] **Step 1: Write `test_make_vis.py`**: `test_columns_positions` asserts a rendered `machine_slide` places the three column wrappers at `left` 128, 680, 1232 (parse the inline `left:` values); `test_no_small_text` asserts every `font-size` in the output is at least 24; `test_headings` asserts the strings "IN", "MACHINE", "OUT" appear in that order; `test_status_values` asserts `value_card` raises `ValueError` for a status other than "accepted" or "needs review".
- [ ] **Step 2: Run** `python3 -I -m pytest test_make_vis.py -q`; expected: fail, module missing.
- [ ] **Step 3: Implement `make_vis.py`** reusing the deck's styles from `make.py` (fonts IBM Plex Sans and Mono, colours `#0F172A`, `#15803D`, `#2563EB`, `#E2E8F0`, `#DCFCE7`). Columns are absolutely positioned with `left` and `width` from `COLS` and `WIDTHS`; the footer matches the deck's footer row.
- [ ] **Step 4: Run the tests**; expected: all pass.

### Task 3: Extraction machine-line slide

**Files:**
- Create: `<scratchpad>/vis/slides/vis-extraction.html` (generated), `<scratchpad>/vis/build_extraction.py`

**Interfaces:**
- Consumes: `sources.json` entries from Task 1; `machine_slide`, `page_img`, `instruction_card`, `value_card` from Task 2.
- Produces: slide id `vis-extraction`.

- [ ] **Step 1: Write `build_extraction.py`** that reads `sources.json`, picks the three page entries and the three run values, and builds the slide. Instruction card: 5 to 7 field names read from the `sch_green_lowcarbon` schema in ARP (`backend/arp/presets`, field ids as stored), with the full names in the speaker notes. The status chip and dots come from the stored run entry, never defaults. Footer text "Public filings, shown for illustration" in one text element.
- [ ] **Step 2: Run it**; expected: the slide file exists and `test_make_vis.py` still passes.
- [ ] **Step 3: Check** by running Task 7's `check_deck.py --slide vis-extraction`; expected: rows AC-1 to AC-7, AC-19 to AC-21, AC-22 to AC-24, AC-28 to AC-31 report pass.

### Task 4: Extraction close-up slide

**Files:**
- Create: `<scratchpad>/vis/build_closeup.py`, `<scratchpad>/vis/slides/vis-extraction-closeup.html`

**Interfaces:**
- Consumes: the Signify page entry and its run value from Task 1.
- Produces: slide id `vis-extraction-closeup`.

- [ ] **Step 1: Write `build_closeup.py`**: one page image with one bordered rectangle (pixel box computed from the PDF text layer's quote bounding box, margin at most 8 px) around the quoted sentence; one value card; two filled check marks labelled "grounded in code" and "verified by a second model" and no other check label.
- [ ] **Step 2: Add a test** `test_box_matches_quote` that asserts the boxed sentence equals the card's quote after whitespace collapse.
- [ ] **Step 3: Run it and `check_deck.py --slide vis-extraction-closeup`**; expected: AC-8 to AC-10, AC-24, AC-28 to AC-31 pass.

### Task 5: Theme funnel slide

**Files:**
- Create: `<scratchpad>/vis/build_funnel.py`, `<scratchpad>/vis/slides/vis-theme-funnel.html`

**Interfaces:**
- Consumes: `machine_slide`, `instruction_card`, `value_card` style cards from Task 2.
- Produces: slide id `vis-theme-funnel`.

- [ ] **Step 1: Find the data.** Look for a stored thematic universe run (Postgres or `runs/`). If none exists, check for a model key (`ARP_ANTHROPIC_API_KEY`); if one exists, run a small thematic run and store it. If neither, stop and report to the owner: the only real, human-checked material in this environment is the exposure golden sets in `backend/tests/golden/exposure` (labels, rationale, primary-source quotes), which are reference labels, not ARP output, so using them needs the owner's decision on wording. Never write cards by hand.
- [ ] **Step 2: Build the slide**: IN holds exactly 2 cards (theme card, ratified taxonomy card); the taxonomy card is the instruction card; one row of three tier labels "Catalogue", "Extraction", "Debate"; exactly 3 exposure cards, each with one chip from "pure play", "significant", "minor", "none", a verbatim quote, and the caption "demo data".
- [ ] **Step 3: Run `check_deck.py --slide vis-theme-funnel`**; expected: AC-11 to AC-15, AC-20, AC-22 to AC-24, AC-28 to AC-31 pass.

### Task 6: Emerging themes slide

**Files:**
- Create: `<scratchpad>/vis/build_emerging.py`, `<scratchpad>/vis/slides/vis-emerging-themes.html`

**Interfaces:**
- Consumes: Task 2 helpers.
- Produces: slide id `vis-emerging-themes`.

- [ ] **Step 1: Find the data.** Look for a stored scan (stored `TopicCluster` rows or run files). If none, the same gate as Task 5, Step 1: stop and report. The IN snippets must be source items of the same scan that produced the topic cards.
- [ ] **Step 2: Build the slide**: IN holds exactly 3 snippets labelled "EDGAR", "News", "Regulatory RSS" top to bottom; the middle names clustering, lineage and novelty; OUT holds exactly 3 topic cards, each with the stored transition word (one of "birth", "growth", "split", "merge") and the stored novelty score with two decimals; caption "demo data".
- [ ] **Step 3: Run `check_deck.py --slide vis-emerging-themes`**; expected: AC-16 to AC-20, AC-22 to AC-24, AC-28 to AC-31 pass.

### Task 7: Assemble, check and publish

**Files:**
- Create: `<scratchpad>/vis/check_deck.py`
- Modify: the deck's `project/deck.json` (order only) in the artifact working folder

**Interfaces:**
- `check_deck.py --slide <id>` renders the slide at 1920x1080 in Chromium and prints `AC-n pass|fail` for the measurable rows: element count, image sources, font sizes (outside images), canvas bounds, column left edges within 8 px of 128, 680 and 1232, exact label strings, absence of "demo data" on the extraction slides, and presence of the notes. `--deck` also checks AC-33 to AC-35.

- [ ] **Step 1: Write `check_deck.py`** with one function per row group and a `main()` that prints one line per row.
- [ ] **Step 2: Insert the four ids** into `order`: `vis-extraction` and `vis-extraction-closeup` adjacent to the Argus feature slides, `vis-theme-funnel` directly after `themes`, `vis-emerging-themes` directly after the existing emerging themes explanation slide. Edit the index only (never rewrite it).
- [ ] **Step 3: Publish** the four slide files and the index in one Artifact call to the existing deck URL.
- [ ] **Step 4: Run `check_deck.py --deck`**; expected: every measurable row prints `pass`.
- [ ] **Step 5: Evaluator pass.** A fresh session that did not build the slides checks the rows `check_deck.py` cannot measure (AC-2, AC-3, AC-5, AC-6, AC-8, AC-9, AC-22, AC-32) by looking at the published deck and posts an AC matrix.
- [ ] **Step 6: Report** to the owner: the link, any fallback used, and anything that blocked a row.

## Self-review notes

- Every Acceptance row maps to a task step above; AC-32 (first-time viewers) is evaluator-only.
- Names are consistent across tasks: `machine_slide`, `value_card`, `instruction_card`, `COLS`, `WIDTHS`, `sources.json`, `check_deck.py`.
- Open dependency: Tasks 5 and 6 need stored data or a model key; they stop and ask rather than invent.
