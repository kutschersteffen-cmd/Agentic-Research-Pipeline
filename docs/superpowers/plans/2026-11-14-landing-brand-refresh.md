# Landing Brand Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the landing page (`#/welcome`) to the new brand: a pixel lockup header, the network → orange orb → pixel "ARP" animation, new copy and a see-through intro.

**Architecture:** This changes only the landing page. The phase table lives in `lib/landingMotion.ts`. `LandingCanvas.tsx` is a port of the approved mockup's script. The CSS tokens and `.landing*` rules are in `index.css`, and the copy and header markup are in `pages/Landing.tsx`.

**Tech Stack:** React 19, TypeScript, Canvas 2D, `node --test` (source and CSS checks).

**Spec:** `docs/superpowers/specs/2026-11-14-landing-brand-refresh-design.md`. The mockup to port is at `docs/superpowers/specs/assets/2026-11-14-landing-mock.html`.

## Global Constraints

- No hex, `rgb(`, `rgba(`, `hsl(` or `oklch(` literal in `.landing*` CSS, `Landing.tsx` or `LandingCanvas.tsx`; every canvas colour comes from `readColours`.
- No `var(--hi`, `--hi-ink`, `--await-edge` or `"--hi"` on the landing page.
- Keep these tests unchanged: `r5_ac1`, `r5_ac2`, `r5_ac11`, `phones_can_scroll_the_landing_page`, `resize_rebuild_is_throttled`, `zero_size_canvas_does_not_crash`.
- Rewrite these tests, don't delete them: `phase_boundaries` (AC-1) and `text_backdrop_solid_behind_intro` (AC-12a). List both in the PR.
- Copy, verbatim: `Company research and stewardship at scale.` and `Leveraging expert judgement through Agents.`

## Review Focus

1. **Theme switch while the page is open:** the colours and the dark flag must follow at once. AC-20 doesn't exercise this. Task 4 adds a source test for the `data-theme` MutationObserver and the `matchMedia` `change` listener.
2. **Very small or zero-size canvas:** `build()` must return early and `draw` must not throw. `zero_size_canvas_does_not_crash` covers the early return; Task 4 keeps the guard as the first line of `build`.
3. **Resize mid-loop:** the particle count `N` changes, so the cached arrays must be rebuilt together. Task 4 keeps one `build()` that reassigns everything.
4. **Tab hidden and shown again:** colours are re-read. The existing `visibilitychange` safeguard stays (AC-20).
5. **Reduced motion:** exactly one draw at 18 500 ms and no animation loop (AC-19). Task 4 adds a source test.

---

### Task 1: 24 s phase table

**Files:**
- Modify: `frontend/src/lib/landingMotion.ts`
- Test: `frontend/tests/landing.test.ts` (rewrite `phase_boundaries`)

**Interfaces:**
- Produces: `type Phase = "network" | "gather" | "orb" | "emerge" | "formed" | "dissolve"`, `LOOP_MS = 24_000`, `phaseAt(ms: number): { phase: Phase; t: number }`.

- [ ] **Step 1:** Rewrite `phase_boundaries` to assert that `p(0)→["network",0]`, `p(2500)→["network",0.5]`, `p(5000)→["gather",0]`, `p(7000)→["gather",0.5]`, `p(9000)→["orb",0]`, `p(11000)→["orb",0.5]`, `p(13000)→["emerge",0]`, `p(16500)→["formed",0]`, `p(18500)→["formed",0.5]`, `p(20500)→["dissolve",0]` and `p(24000)→["network",0]`. Use the existing `p` helper, which rounds to 2 places.
- [ ] **Step 2:** Run `cd frontend && npm test`. Expected: `phase_boundaries` fails.
- [ ] **Step 3:** Set `PHASES` to network 5000, gather 4000, orb 4000, emerge 3500, formed 4000, dissolve 3500, and `LOOP_MS = 24_000`.
- [ ] **Step 4:** Run `npm test`. Expected: it passes, and so does every other landing test.
- [ ] **Step 5:** Commit: `feat(landing): 24 s six-phase loop`.

### Task 2: Tokens and landing CSS

**Files:**
- Modify: `frontend/src/index.css` (the token blocks at about lines 1–160 and the `.landing*` rules at about lines 2431–2451)
- Test: `frontend/tests/landing.test.ts`

- [ ] **Step 1:** Write failing tests. Find each rule with a regex, the way `text_backdrop_solid_behind_intro` does.
  - `ac4_brand_apex`: `--brand-apex: #ea4c14` in `:root`, and `--brand-apex: #ff6a2b` in both dark blocks.
  - `ac5_orb_token`: the same for `--orb`.
  - `ac6_no_signal_on_landing`: no `.landing*` rule contains `--hi` or `--await-edge`.
  - `ac7_no_colour_literals_in_landing_css`: no `.landing*` rule contains `#[0-9a-f]{3,8}\b`, `rgb(` or `oklch(`.
  - `ac12a`: rewrite `text_backdrop_solid_behind_intro` under this name to assert `.landing-main { … linear-gradient(90deg, color-mix(in srgb, var(--bg) 40%, transparent) 55%, transparent)`.
  - `ac12b`: `.landing-main h1` and `.landing-main p` set `text-shadow: 0 0 14px var(--bg), 0 0 4px var(--bg)`.
  - `ac12c`: in the last `@media (max-width: 700px)`, `.landing-main` sets `linear-gradient(180deg, color-mix(in srgb, var(--bg) 40%, transparent) 70%, transparent)`.
  - `ac15a`: the `.landing-main h1` rule has `font-family: "Source Serif 4"…`, `font-weight: 500` and `letter-spacing: -0.01em`.
  - `ac15b`: the same rule keeps `clamp(2.5rem, 2rem + 3vw, 4.2rem)` and `line-height: 1.02`.
  - `ac16`: `.landing-promises b::before` sets `width: 6px`, `height: 6px`, `border-radius: 0` and `background: var(--text)`.
- [ ] **Step 2:** Run `npm test`. Expected: the new tests fail.
- [ ] **Step 3:** Edit the CSS.
  - Add `--brand-apex` and `--orb` to `:root` and both dark blocks.
  - Apply the gradients and text-shadow from the spec. Keep the existing `.landing-main` padding.
  - On `.landing-main h1`: font family `"Source Serif 4", Georgia, serif`, weight 500, letter-spacing −0.01em.
  - `.landing-mark { height: 28px; width: auto; }`.
  - The `.landing-promises b::before` rule (inline-block, `margin-right: 9px`, `vertical-align: 2px`).
- [ ] **Step 4:** Run `npm test && npm run lint`. Expected: everything passes.
- [ ] **Step 5:** Commit: `feat(landing): brand tokens, see-through intro, serif headline`.

### Task 3: Header lockup and copy

**Files:**
- Modify: `frontend/src/pages/Landing.tsx`
- Test: `frontend/tests/landing.test.ts`

- [ ] **Step 1:** Write failing source tests.
  - `ac3_lockup_svg`: `Landing.tsx` contains `role="img"`, `aria-label="ARP"` and `var(--brand-apex)`, and contains no `>\s*ARP\s*<` text node outside the SVG.
  - `ac14_copy`: it contains `Company research and stewardship at scale.` and `Leveraging expert judgement through Agents.`, and no longer contains `Agents propose.`.
  - `ac7_no_colour_literals_in_landing_tsx`: no hex, `rgb(` or `oklch(` literal.
  - `ac6_no_signal_in_landing_tsx`: no `--hi`.
- [ ] **Step 2:** Run `npm test`. Expected: the new tests fail.
- [ ] **Step 3:** Edit `Landing.tsx`.
  - Replace the mark SVG and the "ARP" text with `<svg className="landing-mark" viewBox="0 0 206 62" role="img" aria-label="ARP">`. Inside it go a `<path fill="currentColor" d=…>` with the path from `docs/brand/arp-lockup.svg` and `<rect x="26" y="2" width="10" height="10" fill="var(--brand-apex)" />`.
  - The `h1` becomes the new headline, without a `<br />`.
  - The intro `p` becomes the new line.
  - Keep `PROMISES` and the link.
- [ ] **Step 4:** Run `npm test && npx tsc -b`. Expected: everything passes.
- [ ] **Step 5:** Commit: `feat(landing): pixel lockup header and new copy`.

### Task 4: Port the orb animation

**Files:**
- Modify: `frontend/src/components/LandingCanvas.tsx`
- Test: `frontend/tests/landing.test.ts`

**Interfaces:**
- Consumes: `phaseAt`, `Phase` and `LOOP_MS` from Task 1; the `--orb` and `--brand-apex` tokens from Task 2.

- [ ] **Step 1:** Write failing source tests.
  - `ac7b_canvas_colours_from_tokens`: no hex, `rgb(`, `rgba(`, `hsl(` or `oklch(` literal; it contains `--orb` and `--brand-apex`.
  - `ac6_no_signal_in_canvas`: no `--hi`.
  - `theme_follows_live`: contains `MutationObserver`, `attributeFilter: ["data-theme"]` and `prefers-color-scheme: dark`.
  - `reduced_motion_single_frame`: contains `draw(18500)` or `draw(18_500)` in the reduced-motion branch.
  - `no_debug_global`: does not contain `__arp`.
- [ ] **Step 2:** Run `npm test`. Expected: the new tests fail.
- [ ] **Step 3:** Port the mockup's `<script>` into the existing `useEffect`, typed.
  - Keep from the mockup: the particle, edge, ring, group and pulse data; `build`, `orbPos` and `draw`; seed 11; and every parameter listed in the spec's "Decided".
  - Keep from today's component: the `IntersectionObserver`, `visibilitychange`, throttled `resize`, `if (!W || !H) return;` and cleanup.
  - `readColours` reads `--muted`, `--run`, `--text`, `--orb`, `--brand-apex` and `--bg`. It sets `dark` from `data-theme`, or from the media query when `data-theme` is absent.
  - Drop the mockup's review controls and `window.__arp`.
- [ ] **Step 4:** Run `npm test && npm run lint && npx tsc -b`. Expected: everything passes, including `r5_ac11`, `resize_rebuild_is_throttled` and `zero_size_canvas_does_not_crash`.
- [ ] **Step 5:** Commit: `feat(landing): network to orange orb to pixel ARP animation`.

### Task 5: Verify in the browser

- [ ] **Step 1:** Run `npx vite --port 5199`. Capture `#/welcome` at 1440×900 in light and dark at 2.5, 11 and 18.5 s, and at 400×800 at 18.5 s. Check AC-8, AC-9, AC-10a/b, AC-11, AC-13 and AC-17 with the same measuring script used to calibrate the spec. Expected: every threshold met.
- [ ] **Step 2:** Run `/impeccable:impeccable audit` on the landing screenshots, and fix anything it rates blocking.
- [ ] **Step 3:** Run `/ponytail:ponytail-review` and `/code-review` on the branch diff, and fix real findings.
- [ ] **Step 4:** Open a PR against `main`.
  - Title: `Landing brand refresh: orange orb, pixel ARP, new copy`.
  - Label: `risk:normal` (the canvas port is logic, not only styles or copy).
  - Description: a `Spec: landing-brand-refresh` line, and the two rewritten tests listed.
