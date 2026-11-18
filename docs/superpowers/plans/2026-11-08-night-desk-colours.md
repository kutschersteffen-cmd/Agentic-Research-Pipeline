# Night Desk Release 1 (colours and fonts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ARP's light and dark colour, font and radius values with Night Desk's, in `frontend/src/index.css` only.

**Architecture:** Every colour is already a custom property in three blocks of `index.css` (`:root`, `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`, `:root[data-theme="dark"]`). Only values change. A DOM-less node test parses those three blocks from the CSS text and checks the spec's values.

**Tech Stack:** CSS custom properties; `node --test --experimental-strip-types` (the repo's frontend test runner, no jsdom).

**Spec:** `docs/superpowers/specs/2026-11-08-night-desk-colours-design.md`

## Global Constraints

- Change only values of existing tokens in `frontend/src/index.css`, the header comments above the light and dark blocks, and the Google Fonts link in `frontend/index.html`. No markup, layout or copy change.
- Token values are exactly the spec's table (lower-case hex as written there; dark `--await` is `rgb(212 166 80 / 0.14)`).
- Untouched: `--mid`, `--neutral`, `--accent-ink`, `--accent-tint`, type scale, spacing, shadows, `--ease`, `--dur`, `--cat-1..4`, `frontend/src/lib/palette.ts`.
- A contrast pair that fails is reported to the owner, never fixed with a new value.

## Review Focus

- Dark `--await` is translucent: contrast for `--hi-ink` on it must be computed over `--panel` (AC-6b). Test composites before measuring.
- The two dark blocks drift apart (one edited, one not): the test checks both blocks, not one.
- Hard-coded `#ea4c14` or lime outside the token blocks (e.g. in a component rule) survives the swap: AC-5 grep covers the whole file.
- Amber leaking into new selectors: AC-13 compares `var(--hi…)`/`var(--await…)` locations with `origin/main`.
- Fonts: dark Geist needs the font loaded; Geist is already in the Google Fonts link, so only the unused families are dropped.

---

### Task 1: Token test (red)

**Files:**
- Create: `frontend/tests/nightDeskTokens.test.ts`

**Interfaces:**
- Produces: `readBlock(css: string, selectorStart: string): Map<string,string>` (local helper in the test file) returning lower-cased, trimmed custom-property values of the first block whose selector text starts with `selectorStart`; for the media block, search inside the `@media (prefers-color-scheme: dark)` body for `:root:not([data-theme="light"])`.

- [ ] **Step 1: Write the tests** (one `test()` per AC row, names `ac1_light_tokens`, `ac2_dark_switch_tokens`, `ac3_dark_media_tokens`, `ac4a_dark_switch_fonts`, `ac4b_dark_media_fonts`, `ac5_no_old_signal_colours`, `ac6_text_contrast`, `ac6b_fill_contrast`, `ac6c_status_contrast`, `ac7_radii`, `ac8_nav_count_uses_signal_token`, `ac9_mid_vs_hi_delta`, `ac12a_chart_slots`, `ac14_untouched_tokens`):
  - AC-1/2/3: each of the 17 tokens equals the spec table value for that block.
  - AC-4a/4b: `--font-display` starts with `"Geist"`, `--font-mono` with `"Geist Mono"` in both dark blocks.
  - AC-5: the CSS text contains neither `c6ff3d` nor `ea4c14` (case-insensitive).
  - AC-6/6b/6c: WCAG contrast (sRGB relative luminance) ≥ 4.5 / 4.5 / 3.0 for the spec's pairs, per theme; dark `--await` alpha-composited over `--panel` first.
  - AC-7: `--r-sm 6px`, `--r-md 8px`, `--r-lg 12px`, `--r-pill 999px` in `:root`.
  - AC-8 (DOM-less stand-in for 8a/8b): the `.nav-count` rule's colour declarations reference only `var(--hi` / `var(--await` tokens, so with AC-1 it resolves to `#85601a`; the evaluator confirms the rendered pixel colour.
  - AC-9: CIE76 ΔE*ab between dark `--mid` and dark `--hi` ≥ 10.
  - AC-12a: `--cat-1..4` light `#2a78d6 #c2407f #a87400 #6250d6`, dark `#3987e5 #d55181 #c98500 #9085e9`.
  - AC-14: untouched tokens equal the values listed in the spec's Global Constraints, read from `git show origin/main:frontend/src/index.css` via `child_process.execSync`.

- [ ] **Step 2: Run, expect failures**

Run: `cd frontend && node --test --experimental-strip-types tests/nightDeskTokens.test.ts`
Expected: AC-1..7 fail (old values); AC-9, AC-12a, AC-14 pass.

### Task 2: Swap the values (green)

**Files:**
- Modify: `frontend/src/index.css` (`:root` lines 1–92, dark media block ~98–131, `[data-theme="dark"]` ~132–163, radius tokens lines 67–69)
- Modify: `frontend/index.html:10` (drop `Hanken+Grotesk` and `JetBrains+Mono` families from the Google Fonts URL)

- [ ] **Step 1:** Set the 17 tokens in all three blocks to the spec table, the dark font stacks to the light ones, the radii to 6/8/12px, and rewrite the two header comments to describe amber as the one "waiting on you" colour in both themes.
- [ ] **Step 2:** Run `cd frontend && node --test --experimental-strip-types tests/nightDeskTokens.test.ts` — expected: all pass. If a contrast row fails, stop and report the pair.
- [ ] **Step 3:** Run `git diff origin/main -- frontend/src/lib/palette.ts` (AC-12b) — expected: empty. For AC-13 run `git grep -n -E "var\(--(hi|hi-ink|await|await-edge)\)" origin/main -- frontend/src` and the same on `HEAD`; expected: identical output.
- [ ] **Step 4:** Run `cd frontend && npm run lint && npx tsc -b && npm test` — expected: all pass.
- [ ] **Step 5:** Screenshot Start and Review Queue in light and dark with Playwright (dev server on 5199), attach to the PR; run `/impeccable:impeccable audit` per CLAUDE.md.
- [ ] **Step 6: Commit** `feat(frontend): Night Desk colours, fonts and radii` with the test file, `index.css`, `index.html`.

Evaluator rows (AC-8 rendered colour, AC-10, AC-10b, AC-11a, AC-11b) are checked by the evaluator after CI is green.
