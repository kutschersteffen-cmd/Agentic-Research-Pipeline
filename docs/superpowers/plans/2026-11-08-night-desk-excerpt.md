# Night Desk Release 3 (source excerpt) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the review queue's source quote as a paper-like excerpt card with context sentences and the cited span highlighted.

**Architecture:** Two pure functions in `frontend/src/lib/sourceText.ts` (`excerptParts`, `excerptView`) decide the content; `SourcePanel.tsx` renders their output in place of the `source-panel-quote` paragraph; CSS tokens and rules in `index.css`; the serif font in `index.html`.

**Tech Stack:** React + TypeScript, CSS, `node --test --experimental-strip-types` (DOM-less, no JSX in tests).

**Spec:** `docs/superpowers/specs/2026-11-08-night-desk-excerpt-design.md`

## Global Constraints

- Boundaries: right after `". "`, `"? "`, `"! "` or `"\n"`; a span ending exactly at a boundary has `after === ""`.
- Trim first, then cut: `lead` keeps its last 240 characters, `trail` its first 240; `before`'s end and `after`'s start are not trimmed.
- Caption: `title` plus `" · p. <page>"` when `source.text?.page` is a number.
- Tokens: `--paper` light `#ffffff`, dark `#f5f2ea`; `--ink` light `var(--text)`, dark `#1b1a17`.
- Excerpt face: `"Source Serif 4", Georgia, serif`, 16px, line-height 1.6.
- Only new amber references: `.source-excerpt-page mark` (`var(--await)`, `var(--await-edge)`).

## Review Focus

- `char_start`/`char_end` set but `page_text` empty or offsets past its end: `excerptView` falls back to the quote (AC-9c).
- Page text with Windows line breaks (`"\r\n"`): the `"\n"` boundary still splits; the `"\r"` is trimmed away. Test: `"L1\r\nIn X\r\nL3"` gives `lead === "L1"`.
- A quote of only whitespace: treated as no quote (no empty card). Test: `excerptView({ title: "T", src: "", quote: "  " }) === null`.
- Decimal points and abbreviations inside a sentence (`"€39.0bn"`, `"e.g. this"`): only `". "` with a following space splits, so `"€39.0bn"` stays whole; `"e.g. this"` does split (accepted, documented in a test comment).
- The page number `0` or a missing page: caption has no page suffix unless `page` is a number ≥ 1.

---

### Task 1: Excerpt helpers

**Files:**
- Modify: `frontend/src/lib/sourceText.ts` (append)
- Test: `frontend/tests/sourceText.test.ts` (append)

**Interfaces:**
- Produces:
  - `excerptParts(text: string, start: number, end: number): { lead: string; before: string; mark: string; after: string; trail: string } | null`
  - `excerptView(source: ActiveSource): null | { caption: string; quote: string } | { caption: string; parts: NonNullable<ReturnType<typeof excerptParts>> }` (type-only import of `ActiveSource` from `../components/SourcePanel`)

- [ ] **Step 1: Tests** named `r3_ac1` … `r3_ac9d` with the spec's exact inputs and outputs (AC-1..AC-9d), plus the Review Focus cases: `crlf_lines`, `blank_quote_is_null`, `decimal_point_not_a_boundary` (`"Revenue was €39.0bn in 2025. Next."`, span on `"€39.0bn"` → `before === "Revenue was "`), `page_zero_has_no_suffix`.
- [ ] **Step 2:** `cd frontend && node --test --experimental-strip-types tests/sourceText.test.ts` — Expected: new tests fail (not exported).
- [ ] **Step 3:** Implement both functions. Split the text into sentences once (scan for the boundary patterns, record sentence start offsets), find the sentence index of `start` and of `end - 1` (or of `end` when `end` is a boundary, per the rule), and build the parts from those offsets. Only page numbers ≥ 1 add the suffix; a quote of only whitespace counts as absent.
- [ ] **Step 4:** Same command — Expected: all pass.
- [ ] **Step 5:** Commit `feat(frontend): source excerpt helpers`.

### Task 2: Card, styles, font

**Files:**
- Modify: `frontend/src/components/SourcePanel.tsx` (replace the `source-panel-quote` paragraph, lines ~59)
- Modify: `frontend/src/index.css` (`--paper`, `--ink` in the three token blocks; `.source-excerpt*` rules)
- Modify: `frontend/index.html` (Google Fonts URL adds `Source+Serif+4:opsz,wght@8..60,400;8..60,500`)
- Modify: `DESIGN.md` (one line: Source Serif 4 is the excerpt face)
- Test: `frontend/tests/nightDeskTokens.test.ts` (append `r3_ac10`, `r3_ac11`, `r3_ac11b`, `r3_ac12`; extend `ac13_amber_usage_unchanged` to allow the two excerpt `mark` references)

**Interfaces:**
- Consumes: `excerptView` from Task 1.

- [ ] **Step 1: Tests** for AC-10, AC-11, AC-11b (token values in all three blocks, `.source-excerpt-page` uses `var(--paper)` and `var(--ink)`), AC-12; extend the amber test: HEAD list = `origin/main` list + `var(--await)` + `var(--await-edge)`.
- [ ] **Step 2:** `cd frontend && node --test --experimental-strip-types tests/nightDeskTokens.test.ts` — Expected: the new `r3_*` tests fail.
- [ ] **Step 3:** `SourcePanel`: `const ex = excerptView(source)`; render `figure.source-excerpt` > `figcaption.source-excerpt-meta` (caption) and `blockquote.source-excerpt-page` with either `span.source-excerpt-ctx` (lead), before, `<mark>`, after, `span.source-excerpt-ctx` (trail), or the quote. Empty `lead`/`trail` render no span. CSS: paper card per Global Constraints, context in `var(--muted)`, `mark` background `var(--await)` with `box-shadow: inset 0 -2px var(--await-edge)` (keeps the amber reference count to these two tokens). Remove the now-unused `.source-panel-quote` rule.
- [ ] **Step 4:** Same command, then commit (the amber test reads `HEAD`), then `cd frontend && npm run lint && npx tsc -b && npm test` — Expected: exit 0.
- [ ] **Step 5:** Playwright screenshot of the review queue with the source panel open (mocked runs and a mocked source text), light and dark; `/impeccable:impeccable audit`.
- [ ] **Step 6:** Commit `feat(frontend): Night Desk source excerpt`.

AC-13, AC-14, AC-14b are evaluator rows. AC-15/15b are covered by the PR's test list and the suite run.
