---
name: deck-design
description: Use when making, rebuilding, reviewing or improving a deck, slides, a slide deck, a presentation, a pitch or a committee pre-read in this repo, or when changing the house-deck layouts, the art director or the design check. Builds decks through the house-deck pipeline and reviews them against the shared design rules in backend/arp/reporting/style/design.md.
---

# Deck design

House decks come out of one pipeline and follow one set of design rules. The rules live in
`backend/arp/reporting/style/design.md`. The slide-fill and visual QA prompts read that same file at runtime, so
read it there and do not copy it anywhere else.

## 1. Build through the pipeline

Never hand-write a PPTX, HTML or PDF. Every deck goes through the house-deck pipeline
(`backend/arp/reporting/house_pipeline.py`): storyline, fill, art direction, lint, fit, design check, visual QA,
then `output.pdf`, `output.pptx` and one PNG per slide.

- With an API key, from `backend/`: `arp report plan --title ... --notes notes.md --format house_deck --out story.json`
  drafts the storyline. Edit the headlines (in the UI or with `PUT /api/reports/{id}/storyline`), then
  `arp report approve <report_id>` builds the deck. The API flow is the same: create the report, then
  `POST /api/reports/{id}/storyline/approve`.
- Density is `layout.density` on the request: `committee` (the default, a consulting-style pre-read) or `present`
  (a short spoken pitch); on the CLI, `--density present|committee`. Theme is `layout.theme` (`--theme light|dark`).
- Without an API key, script the model the way `backend/tests/test_reporting_golden_briefs.py` does: a fake LLM
  that returns a `Storyline`, one `SlideContent` per slide and `QAResult(edits=[])`, passed to
  `ReportingService.create_and_plan` and `approve_storyline`. The TPA fixtures in `backend/tests/fixtures/`
  (`tpa_pitch.py`, `tpa_pitch_committee.py`) are worked examples of fills in both densities.

Read `findings.json` after every build. `design` findings with severity `info` record what the art director moved;
any `warn` finding is a problem to fix.

## 2. Read the rules

Read `backend/arp/reporting/style/design.md` before writing fills or judging a slide. It holds the two densities,
every layout with its item format, the content-to-layout table, the rhythm rules, the measured design check and
four before/after examples.

## 3. Look at the slides

- Open every PNG in the report's preview folder (`page-001.png` and on) and check each one against the
  "Review checklist" section of `design.md`. Check both themes when the deck ships in both.
- Render the deck HTML (`render_deck_html(deck, request.datasets, mode=..., density=...)` from
  `arp.reporting.html_render`, with the saved `deck.json`) to a scratch file and run `/impeccable critique` on it.
- Run the impeccable detector on the same file. Use the impeccable skill's `scripts/impeccable detect` (the skill
  prints its base directory when it loads; a local install sits under
  `~/.claude/plugins/cache/impeccable/impeccable/<version>/skills/impeccable`). Two rules are ignored: the Geist
  brand font (`overused-font`) and the tight leading of headlines and big numbers (`tight-leading`). Both are
  DESIGN.md decisions.

```sh
"<impeccable skill dir>/scripts/impeccable" detect --json deck.html \
  | python3 -c 'import json, sys; [print(f["antipattern"], "|", f["snippet"]) for f in json.load(sys.stdin) if f["antipattern"] not in ("overused-font", "tight-leading")]'
```

The detector is a dev-time check. It does not run in CI, where the plugin is not installed.

## 4. Fix the library, not the deck

A problem on one slide is almost always a rule or a layout problem. Fix it where every deck picks it up:
- layout geometry, slot limits and variants in `backend/arp/reporting/style/layouts.json`
- type, colour and grid tokens in `backend/arp/reporting/style/tokens.json` (DESIGN.md is locked: no new fonts or colours)
- HTML and CSS in `backend/arp/reporting/style/templates/`, the PPTX twin in `house_pptx.py`
- layout choice and rhythm in `art_direct.py`, the measured rules in `browser.py`
- the shared wording in `style/design.md`

Then rebuild the deck through the pipeline and look at the PNGs again. Never edit a single deck's output files.
Run `python -m pytest tests/test_reporting_*.py -q` from `backend/`: the stress deck and the golden briefs must
stay free of fit, lint and design warnings.
