# Arctic Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch the app to the Arctic palette, lift cards, make rating badges pastel, and put the pixel "ARP" lockup in the sidebar.

**Architecture:** This changes token values and three rule groups in `frontend/src/index.css`, plus the sidebar brand in `frontend/src/App.tsx`. Screens pick the change up through the tokens.

**Tech Stack:** CSS custom properties, React 19, `node --test` (CSS and source checks).

**Spec:** `docs/superpowers/specs/2026-11-15-arctic-foundation-design.md`

## Global Constraints

- Token values are exactly the spec's Decided table. Amber, status, chart and radius tokens don't change.
- No colour literal outside the token blocks. `App.tsx` has none.
- Only the existing tests named under the spec's Supersedes are edited: `ac1_light_tokens`, `ac2_dark_switch_tokens`, `ac3_dark_media_tokens`, `ac14_untouched_tokens`, `ac13_amber_usage_unchanged` and `r2_ac1_run_token`. New tests may be added.

## Review Focus

1. **Badges in dark:** a pastel badge must stay readable on dark panels. AC-9b, browser check in Task 4.
2. **Text in `--run` on the well:** the start page's "Running" status text. Covered by AC-4b's unit check in Task 1.
3. **Hover states:** `--accent-ink` hover on primary buttons stays at 4.5:1 with `--on-accent`. Task 1 adds `accent_ink_hover_contrast`.
4. **Top bar on phones:** the mark alone, readable on the new sidebar colour. AC-10b in Task 4.
5. **Landing page:** contrast under the new `--bg`. AC-20 in Task 4.

---

### Task 1: Arctic tokens

**Files:**
- Modify: `frontend/src/index.css` (the three token blocks) and `DESIGN.md` (frontmatter `status-run`)
- Test: `frontend/tests/nightDeskTokens.test.ts`

- [ ] **Step 1:** Rewrite the existing tests.
  - The `LIGHT` and `DARK` maps in `ac1`/`ac2`/`ac3` take the spec table's values (`--on-hi` light stays `#ffffff`, dark becomes `#06141d`).
  - `r2_ac1_run_token` expects `#0369a1` / `#7dd3fc`.
  - `ac14_untouched_tokens` drops `accent-ink|accent-tint` from its keep-regex.
- [ ] **Step 2:** Add new tests.
  - `ac4b_text_token_contrast`: `--run`, `--accent` and `--accent-ink` reach 4.5:1 on `--bg`, `--panel` and `--well` in all three blocks. Use the `pairs` helper.
  - `ac15_untouched_signal_status_radii`: the values of `--hi`, `--hi-ink`, `--await`, `--await-edge`, `--high`, `--low`, `--cat-1..4` and the radii equal those parsed from `git show origin/main:frontend/src/index.css`. Skip if `origin/main` is missing, as `ac14` does.
  - `shadow_card_token`: `--shadow-card` has the spec's light and dark values.
  - `accent_ink_hover_contrast`: `--on-accent` on `--accent-ink` reaches 4.5:1.
- [ ] **Step 3:** Run `cd frontend && npm test`. Expected: the rewritten tests and the new tests fail.
- [ ] **Step 4:** Edit the token values in all three blocks, add `--shadow-card`, and set DESIGN.md `status-run: "#0369a1"`.
- [ ] **Step 5:** Run `npm test`. Expected: all tests pass.
- [ ] **Step 6:** Commit: `feat(theme): Arctic palette tokens`.

### Task 2: Lifted cards and pastel badges

**Files:**
- Modify: `frontend/src/index.css` (`.card`, `.stat-tile`, `.hub-card` and `.badge*`)
- Test: `frontend/tests/nightDeskTokens.test.ts`

- [ ] **Step 1:** Write the failing tests.
  - `ac6_lifted_cards`: `rule(".card")`, `rule(".stat-tile")` and `rule(".hub-card")` each contain `box-shadow: var(--shadow-card)`.
  - `ac7_pastel_badge`: `rule(".badge")` contains the spec's four declarations.
  - `ac8_badge_status`: `.badge-high|mid|low|neutral` each set `--st: var(--high|mid|low|neutral)` and nothing else.
- [ ] **Step 2:** Run `npm test`. Expected: the new tests fail.
- [ ] **Step 3:** Edit the CSS.
  - Add `box-shadow: var(--shadow-card);` to the three rules. If a `.hub-card:hover` rule sets its own shadow, keep it.
  - Rewrite `.badge` (keep its padding, size and weight) and the four modifiers.
- [ ] **Step 4:** Run `npm test && npm run lint`. Expected: everything passes.
- [ ] **Step 5:** Commit: `feat(theme): lifted cards and pastel rating badges`.

### Task 3: Sidebar lockup

**Files:**
- Modify: `frontend/src/App.tsx` (`ArpMark` and the sidebar brand) and `frontend/src/index.css` (`.app-sidebar-mark`, `.app-sidebar-wordmark` and `.app-sidebar-lockup`)
- Test: `frontend/tests/nightDeskTokens.test.ts` (`ac13`) and a new `frontend/tests/sidebarLockup.test.ts`

- [ ] **Step 1:** Write the failing tests.
  - In `sidebarLockup.test.ts`:
    - `ac11_brand_apex_in_app`: `App.tsx` contains `var(--brand-apex)` at least twice and no `fill="var(--hi)"`.
    - `ac11b_no_colour_literals_in_app`: no `#[0-9a-fA-F]{3,8}\b`, `rgb(` or `oklch(`.
    - `lockup_rule`: `.app-sidebar-lockup` has `height: 32px`, `width: auto` and `color: var(--text)`. `.app-sidebar-mark` has `color: var(--text)`, and there is no `.app-sidebar-wordmark` rule.
  - In `nightDeskTokens.test.ts`, remove the logo-rect alternative from `ac13`'s `allowed` regex.
- [ ] **Step 2:** Run `npm test`. Expected: the new tests fail.
- [ ] **Step 3:** Edit `App.tsx`.
  - Add `ArpLockup()`: `<svg className="app-sidebar-lockup" viewBox="0 0 206 62" role="img" aria-label="ARP">`, containing a `<path fill="currentColor" d=…>` with the path from `docs/brand/arp-lockup.svg` and an apex `<rect … fill="var(--brand-apex)" />`.
  - In the sidebar brand, replace `<ArpMark />` and the wordmark span with `<ArpLockup />`.
  - In `ArpMark`, the apex fill becomes `var(--brand-apex)`.
- [ ] **Step 4:** Edit the CSS: the `.app-sidebar-mark` colour, the new `.app-sidebar-lockup` rule, and remove `.app-sidebar-wordmark`.
- [ ] **Step 5:** Run `npm test && npx tsc -b && npm run lint`. Expected: everything passes, including `ac13`.
- [ ] **Step 6:** Commit: `feat(sidebar): pixel ARP lockup`.

### Task 4: Verify, review and PR

- [ ] **Step 1:** Run `npx vite --port 5199` and check with Playwright.
  - AC-9a/b: insert the badge fixture on `/#/home` and measure label contrast, light and dark.
  - AC-10: the lockup is 32px at 1440×900.
  - AC-10b: at 390×844 the top bar has the 62×62 mark and no ARP lockup.
  - AC-12 and AC-13: body background, `.hub-card` shadow, and the active nav colour in dark.
  - AC-20: the landing contrast measurement in both themes.

  Take screenshots of `#/home` in light and dark.
- [ ] **Step 2:** Run `/impeccable:impeccable audit` on the screenshots, and fix anything rated P0 or P1.
- [ ] **Step 3:** Run a fresh whole-branch review. Fix Critical and Important findings with RED→GREEN tests.
- [ ] **Step 4:** Merge `origin/main`, push, and open a PR against `main`.
  - Label: `risk:normal` (`App.tsx` gains a component, so it is not a text-only TSX edit).
  - Description: `Spec: arctic-foundation`, the edited tests listed, and screenshots.
