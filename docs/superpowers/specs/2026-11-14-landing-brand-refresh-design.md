# Landing brand refresh

## Intent

Bring the landing page (`#/welcome`) in line with the brand rules in `DESIGN.md` and `docs/BRAND.md`
(merged in PR #453), with a new animation and new copy that the owner chose from the mockup
(artifact "ARP Landing Mockup", version 5). Visitors see a huge, chaotic network gather into a glowing
orange orb, out of which the pixel "ARP" emerges.

## Goals

- **Header:** the pixel "ARP" lockup from `docs/brand/arp-lockup.svg`, not "ARP" as text.
- **Animation:** a 24 s loop in six phases:
  - **network** (5 s): nodes over the whole canvas, wired to their nearest neighbours, with signals
    running along the wires;
  - **gather** (4 s): the nodes pull into a sphere;
  - **orb** (4 s): a rotating 3D orb of tilted rings, latitude bands, spokes, a core and loose
    fragments, glowing orange;
  - **emerge** (3.5 s): the orb opens and a share of its particles flies into the pixel "ARP";
  - **formed** (4 s): "ARP" holds in front of the dimmed, still-turning orb;
  - **dissolve** (3.5 s): everything returns to the network.
- **Orange:** the orb glows in `--orb`, and the A's apex in the formed "ARP" and in the header uses
  `--brand-apex`. Both are brand orange (DESIGN.md, The Brand Colour Rule).
- **Copy:** the headline is "Company research and stewardship at scale.", and the line under it is
  "Leveraging expert judgement through Agents.". Nothing else is in the intro. The button and the
  three promises stay.
- **Headline style:** Source Serif 4, weight 500, letter-spacing −0.01em. Size and line-height stay
  as today. (This is the landing headline, an accepted exception to DESIGN.md's "Display is the
  start-page status line only".)
- **See-through intro:** the network shows through behind the intro, and a soft halo of `--bg` around
  the text keeps it legible.
- **Pixel mark language:** particles are drawn as squares, and each promise title starts with a 6px
  ink square.

## Non-goals

- The Arctic palette, card shadow and pastel badges for the whole app. They come with the separate
  app-wide CSS PR; the landing page picks them up from the tokens.
- The sidebar lockup in `App.tsx`.
- The mockup's review controls (Light, Dark, Show orb, Show formed, Replay, phase label). They are
  mockup only and are not built.

## Anti-goals

- The landing page carries its own colour values instead of tokens. The canvas reads every colour
  from CSS custom properties.
- The amber signal (`--hi`, `--hi-ink`, `--await-edge`) appears on the landing page: nothing there
  waits on a person.
- The animation causes long tasks, or loses its reduced-motion, off-screen, visibility and resize
  safeguards.
- The intro text becomes hard to read over the network.

## Approaches

1. **Landing only (chosen).** Change `Landing.tsx`, `LandingCanvas.tsx`, `lib/landingMotion.ts`
   and the landing CSS now; colours follow the later app-wide CSS PR. Small and safe.
2. App-wide CSS first, then the landing page. Shows Arctic at once, but two PRs in a row and the first
   touches every screen.
3. Landing with its own Arctic colours. Fastest, but drifts from the app. Rejected.

## Decided

- **Port the mockup's animation:** the `<script>` of the "ARP Landing Mockup" artifact, version 5,
  copied into this spec's folder as `assets/2026-11-14-landing-mock.html`. Port it into
  `LandingCanvas.tsx` (drawing) and `lib/landingMotion.ts` (the phase table and `phaseAt`). Keep its
  parameters:
  - `N = clamp(W·H / 900, 500, 1400)` particles; up to 3 neighbour wires each, within
    `max(60, √(W·H/N)·1.7)` px; `N/30` signals.
  - Orb: 9 rings, 3 of them latitude bands, 58% of particles; 14 spokes, 14%; core 5%; the rest are
    shell fragments.
  - Orb centre `(0.7W, H/2)` with radius `min(0.34H, 0.2W)`. Below 700px wide: centre `(W/2, H/2)`
    with radius `min(0.42W, 0.3H)`.
  - "ARP" cells are `floor(1.75R/17)` px, with 5, 4 or 3 dots per cell side: the largest whose total
    dots stay ≤ 0.45N.
- **Phases** (`landingMotion.ts`): network 5000, gather 4000, orb 4000, emerge 3500, formed 4000,
  dissolve 3500 ms; `LOOP_MS = 24_000`.
- **Tokens** in `index.css`:
  - `--brand-apex`: `#ea4c14` in `:root`, `#ff6a2b` in both dark blocks.
  - `--orb`: `#ea4c14` in `:root`, `#ff6a2b` in both dark blocks (the same values as `--brand-apex`;
    a separate token so the glow can be tuned without moving the logo colour).
  - The canvas reads `--muted`, `--run`, `--text`, `--orb`, `--brand-apex` and `--bg` in
    `readColours`.
- **Blending:** in dark themes the orb and the signals draw with `globalCompositeOperation =
  "lighter"`; light themes use `source-over`. The theme is dark when `<html data-theme="dark">`, or
  when there is no `data-theme` and `matchMedia('(prefers-color-scheme: dark)')` matches.
  `readColours` (colours and the dark flag) reruns on that media query's `change`, on
  `visibilitychange`, and when `<html>`'s `data-theme` attribute changes.
- **Port details:** drop the mockup's debug global `window.__arp`; keep `seed = 11` so frames repeat.
- **Header:**
  - The mark SVG is replaced by the lockup SVG: the paths of `arp-lockup.svg`, ink in `currentColor`,
    apex in `var(--brand-apex)`, with `role="img" aria-label="ARP"`.
  - The "ARP" text node is removed; "Agentic Research Pipeline" stays.
  - `.landing-mark` becomes `height: 28px; width: auto`.
- **See-through intro:**
  - `.landing-main` background becomes
    `linear-gradient(90deg, color-mix(in srgb, var(--bg) 40%, transparent) 55%, transparent)`.
  - Under 700px it becomes `linear-gradient(180deg, color-mix(in srgb, var(--bg) 40%, transparent) 70%, transparent)`.
  - `h1` and `p` get `text-shadow: 0 0 14px var(--bg), 0 0 4px var(--bg)`.
- **Promise squares:** `.landing-promises b::before`, 6px × 6px, `border-radius: 0`,
  `background: var(--text)`.
- **Reduced motion:** draw one still frame at 18 500 ms (the formed phase) and stop.

## Supersedes

From `2026-11-09-night-desk-landing`:
- **Copy:** AC-3 and AC-3b (the old headline) and AC-7 (the old copy).
- **Amber logo square:** AC-8b and AC-8c.
- **Timings moved to the 24 s loop:** AC-9 → AC-19a/AC-19b, AC-10 → AC-13, AC-11b → AC-18.

In `frontend/tests/landing.test.ts`, two tests change with this spec. They are rewritten, not
deleted:
- `phase_boundaries` (the 22 s loop) is replaced by AC-1.
- `text_backdrop_solid_behind_intro` (solid intro backdrop) is replaced by AC-12a.

## Left to the builder

- How the ported code is split inside `LandingCanvas.tsx`, as long as the safeguards in AC-20 stay.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `phaseAt` from `lib/landingMotion.ts` | Called at 0, 2500, 5000, 7000, 9000, 11000, 13000, 16500, 18500, 20500, 24000 ms | Returns `network 0`, `network 0.5`, `gather 0`, `gather 0.5`, `orb 0`, `orb 0.5`, `emerge 0`, `formed 0`, `formed 0.5`, `dissolve 0`, `network 0` | unit |
| AC-2 | The app at `#/welcome`, any theme | The page loads | The header's visible text (innerText) is exactly `Agentic Research Pipeline` | evaluator |
| AC-3 | The same | The page loads | The header contains an `svg[role=img][aria-label=ARP]` whose rendered height is 28px | evaluator |
| AC-4 | `frontend/src/index.css` | Read | `--brand-apex` is `#ea4c14` in `:root` and `#ff6a2b` in both the `prefers-color-scheme: dark` block and the `[data-theme="dark"]` block | unit |
| AC-5 | The same | Read | `--orb` is `#ea4c14` in `:root` and `#ff6a2b` in both dark blocks | unit |
| AC-6 | `Landing.tsx`, `LandingCanvas.tsx` and every `.landing*` rule in `index.css` | Read | None contains `var(--hi`, `--hi-ink`, `--await-edge` or `"--hi"` | unit |
| AC-7 | `index.css` and `Landing.tsx` | Read | No `.landing*` rule, and no attribute or `style` in `Landing.tsx` (SVG `fill` included), contains a hex, `rgb(` or `oklch(` colour literal | unit |
| AC-7b | `LandingCanvas.tsx` | Read | It contains no hex, `rgb(`, `rgba(`, `hsl(` or `oklch(` literal; every `fillStyle`, `strokeStyle` and gradient stop is a value read in `readColours` or `"transparent"` | unit |
| AC-8 | The landing page, 1440×900, motion allowed, light or dark | A canvas capture is taken 2.5 s after load (network) | At least 36 of the canvas's 60 equal regions (10 × 6) contain at least one non-background pixel | evaluator |
| AC-9 | The same | A capture is taken 11 s after load (orb) | Of the pixels inside the circle at `(0.7W, H/2)` of radius `1.25·min(0.34H, 0.2W)`, at least 0.5% (light) / 5% (dark) have hue within ±15° of `--orb` and saturation ≥ 0.4; under 0.5% of the pixels outside 1.5× that radius do. (Measured on the mockup with the app's current `index.css` tokens: 1.0% light, 23.0% dark inside, 0.00% outside; with Arctic tokens: 1.0% / 10.3% / 0.00%. Re-checked when the Arctic CSS PR lands.) | evaluator |
| AC-10a | The same | A capture is taken 18.5 s after load (formed) | The squares in `--text` colour form the letters "A", "R", "P" in a row whose bounding boxes have the same height (±1 dot) | evaluator |
| AC-10b | The same | A capture is taken 18.5 s after load | The bounding box of all "ARP" squares lies in the right half of the canvas | evaluator |
| AC-11 | The same | A capture is taken 18.5 s after load | The squares on the A's apex cell are within ΔE 10 of `--brand-apex` (`#ea4c14` light, `#ff6a2b` dark); no square in the "ARP" outside that cell is | evaluator |
| AC-12a | `index.css` | Read | The `.landing-main` rule's background is `linear-gradient(90deg, color-mix(in srgb, var(--bg) 40%, transparent) 55%, transparent)` | unit |
| AC-12b | `index.css` | Read | `.landing-main h1` and `.landing-main p` set `text-shadow: 0 0 14px var(--bg), 0 0 4px var(--bg)` | unit |
| AC-12c | `index.css` | Read | Inside the last `@media (max-width: 700px)` block, `.landing-main`'s background is `linear-gradient(180deg, color-mix(in srgb, var(--bg) 40%, transparent) 70%, transparent)` | unit |
| AC-13 | The landing page, both themes, 1440×900 | Captures are taken 2.5 s and 11 s after load with the `h1` and `p` text set to `color: transparent` (text-shadow kept) | Inside each line box of the `p`, at least 99% of pixels reach 4.5:1 against the `p`'s computed `color`; inside each line box of the `h1`, at least 99% reach 3:1 against the `h1`'s computed `color` (WCAG large text). (Measured on the mockup: ≥ 99.90% with the app's current tokens, ≥ 99.96% with Arctic tokens. Re-checked when the Arctic CSS PR lands.) | evaluator |
| AC-14 | The landing page | Its DOM is read | `.landing-main` holds exactly three elements: the `h1` (`Company research and stewardship at scale.`), one `p` (`Leveraging expert judgement through Agents.`) and the `Open ARP →` link | evaluator |
| AC-15a | `index.css` | Read | The `.landing-main h1` rule sets `font-family` starting with `"Source Serif 4"`, `font-weight: 500` and `letter-spacing: -0.01em` | unit |
| AC-15b | `index.css` | Read | The `.landing-main h1` rule keeps `font-size: clamp(2.5rem, 2rem + 3vw, 4.2rem)` and `line-height: 1.02` | unit |
| AC-16 | `index.css` | Read | A `.landing-promises b::before` rule sets `width: 6px`, `height: 6px`, `border-radius: 0` and `background: var(--text)` | unit |
| AC-17 | Narrow screen, 400×800 | A capture is taken 18.5 s after load | The whole pixel "ARP" is inside the canvas and its centre is within ±8px of the canvas centre horizontally | evaluator |
| AC-18 | The landing page in the e2e Chromium at 1440×900 | A 5 s performance trace is recorded at 9–14 s after load (orb) | No long task over 50 ms | evaluator |
| AC-19a | The landing page, `prefers-reduced-motion: reduce` | Two captures are taken 1 s apart | They are pixel-identical | evaluator |
| AC-19b | The same | A capture is taken | It shows the formed pixel "ARP" as in AC-10a | evaluator |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-20 | `frontend/tests/landing.test.ts` | `npm test` runs | `r5_ac1`, `r5_ac2`, `r5_ac11`, `phones_can_scroll_the_landing_page`, `resize_rebuild_is_throttled` and `zero_size_canvas_does_not_crash` pass unchanged | unit |
| AC-21 | The landing page | Its text is read | The button reads `Open ARP →` and the three promise titles and lines match `main` exactly | evaluator |
| AC-22 | The landing page | `Open ARP →` is clicked | The URL hash is `#/home` | evaluator |
| AC-23 | The same | `Open ARP →` is clicked | `.app-sidebar` is present and the landing `h1` is gone | evaluator |
