# Night Desk Release 5 (landing page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opening ARP (no page in the address, or `#/welcome`) shows a full-screen landing page with the dot animation; "Open ARP →" goes to the start page.

**Architecture:** `entryTab` in `frontend/src/lib/nav.ts` decides the landing route; `App.tsx` renders `<Landing />` outside the app shell for it; `pages/Landing.tsx` holds the copy; `components/LandingCanvas.tsx` ports the mockup's canvas animation; pure animation maths (timeline phase, sentence-free) lives in `lib/landingMotion.ts` so it can be unit-tested.

**Tech Stack:** React + TypeScript, canvas 2D, CSS, `node --test --experimental-strip-types`.

**Spec:** `docs/superpowers/specs/2026-11-09-night-desk-landing-design.md`

## Global Constraints

- Landing hashes: `""`, `"#"`, `"#/"`, `"#/welcome"`. Every other hash routes as today.
- Copy exactly as the spec's Copy section.
- Loop 22 s: 0–4 s network, 4–6 s light up, 6–14 s stream and land, 14–18 s formed, 18–22 s dissolve.
- Up to 3,200 dots; colours from tokens (`--muted`, `--run`, `--text`, `--hi`).
- Pauses off-screen and when `document.hidden`; reduced motion draws one formed frame; canvas `aria-hidden="true"`; `cancelAnimationFrame` on unmount.

## Review Focus

- Back button: pressing Back from the start page after "Open ARP" returns to the landing page (a normal link, not `replaceState`); expected by users. Evaluator note, no test.
- Window resize while animating: targets are re-sampled; no stretched canvas. Covered by a resize listener and cleanup in AC-11's source check.
- Tiny screens (≤ 400px): the logo would collide with the text; below 700px the canvas sits behind the text at lower opacity and the logo forms centred. Test `phaseAt` only; layout checked in screenshots.
- Theme switch while on the page: colours re-read on the next loop (cheap: read tokens each frame is too slow; read on `matchMedia` change and on `data-theme` mutation). Evaluator note.
- Very slow devices: dot count scales with area (`min(3200, area/170)`), already in the mockup.

---

### Task 1: Route and timeline helpers

**Files:** Modify `frontend/src/lib/nav.ts`; Create `frontend/src/lib/landingMotion.ts`; Test `frontend/tests/landing.test.ts` (new)

**Interfaces — Produces:**
- `entryTab(hash: string): "welcome" | null`
- `phaseAt(ms: number): { phase: "network" | "light" | "stream" | "formed" | "dissolve"; t: number }` (`t` = 0–1 progress within the phase; `ms` modulo 22 000)

- [ ] **Step 1:** Tests `r5_ac1` (the four landing hashes → `"welcome"`), `r5_ac2` (`#/home`, `#/review/extraction/r1`, `#/argus`, `#/nonsense` → `null`), `phase_boundaries` (`phaseAt(0)` network t 0; `phaseAt(2000)` network t .5; `phaseAt(5000)` light t .5; `phaseAt(10000)` stream t .5; `phaseAt(16000)` formed t .5; `phaseAt(20000)` dissolve t .5; `phaseAt(22000)` network t 0).
- [ ] **Step 2:** `cd frontend && node --test --experimental-strip-types tests/landing.test.ts` — Expected: fail (not exported).
- [ ] **Step 3:** Implement both.
- [ ] **Step 4:** Same command — Expected: pass. Commit `feat(frontend): landing route and animation timeline helpers`.

### Task 2: Landing page and canvas

**Files:** Create `frontend/src/pages/Landing.tsx`, `frontend/src/components/LandingCanvas.tsx`; Modify `frontend/src/App.tsx` (add `welcome` route: when `entryTab(window.location.hash)` is `"welcome"` on load and on `hashchange`, render `<Landing />` instead of the shell), `frontend/src/index.css` (`.landing*` rules); Test `frontend/tests/landing.test.ts` (append `r5_ac11` source check).

**Interfaces — Consumes:** `entryTab`, `phaseAt`.

- [ ] **Step 1:** Test `r5_ac11`: read `LandingCanvas.tsx` source and assert it contains `IntersectionObserver`, `visibilitychange`, `prefers-reduced-motion`, `cancelAnimationFrame`, `aria-hidden="true"` and `removeEventListener("resize"`.
- [ ] **Step 2:** Run — Expected: fail (file missing).
- [ ] **Step 3:** `LandingCanvas`: port the mockup script (`docs/design-directions.html`, the `flowviz` script) into a `useEffect`, driving phases from `phaseAt`; logo targets sampled from an offscreen canvas in the right 40% (centred below 700px). `Landing`: top bar, `h1` with two lines (`Agents propose.` `<br />` `People ratify.`), intro, `<a className="landing-open" href="#/home">Open ARP →</a>`, three promises, text column over `linear-gradient(90deg, var(--bg) 40%, transparent)`.
- [ ] **Step 4:** Run the test, commit, then `npm run lint && npx tsc -b && npm test` — Expected: exit 0.
- [ ] **Step 5:** Playwright screenshots at 2 s and 16 s, light and dark, plus a reduced-motion still; check AC-10 contrast by sampling backdrop pixels in the headline box; `/impeccable:impeccable audit`. Commit screenshots.

AC-3..10 and AC-11b are evaluator rows; AC-12/12b in the PR.
