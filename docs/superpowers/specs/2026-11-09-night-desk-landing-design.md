# Night Desk, release 5: landing page

## Intent

Give ARP a front door (owner, after the mockups): opening ARP shows a full-screen landing page with the
Night Desk dot animation, where a network of dots streams through an invisible funnel and forms the
ARP logo, the product promise and one way in. Everyone sees it when they open ARP, signed in or not
(owner's call). Mockup: `docs/design-directions.html`, "Landing page".

## Goals

- Opening ARP with no page in the address (`/`, `#`, `#/`) shows the landing page, full screen, no sidebar.
- `#/welcome` shows it too.
- "Open ARP →" goes to the start page (`#/home`).
- The page shows the ARP logo with "Agentic Research Pipeline" in a top bar, the headline
  "Agents propose. People ratify.", a one-line intro, the button and three promises.
- The dot animation runs behind the content; it pauses off-screen and is a still frame for people who
  turn off motion.

## Non-goals

- No sign-in on the page; name and token stay in the sidebar.
- No "How it works", "Security", "Sign in" or "N things wait on you" links (mockup placeholders).
- Direct links to any other page are unchanged.
- No backend change.

## Anti-goals

- A direct link (e.g. `#/review/extraction/<id>`) that lands on the landing page instead of its page.
- Content unreadable over the animation, or the animation making the page sluggish.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| A | Show when not signed in | Owner rejected: everyone should see it for now |
| B | Show when no token, with a skip button | Owner rejected, same reason |
| **C (picked, as the owner changed it)** | Show on every app open with no page in the address; direct links bypass it | Simplest; the front door for everyone |

## Decided

**Route.** A pure function `entryTab(hash: string): "welcome" | null` in `frontend/src/lib/nav.ts`
returns `"welcome"` for `""`, `"#"`, `"#/"` and `"#/welcome"`, else `null`. `App.tsx` adds a
`welcome` tab id; when the route is `welcome` it renders `<Landing />` instead of the app shell
(no sidebar, no top bar). Every other hash routes as today, so unknown hashes still go to `home`.

**Copy** (exact):
- Top bar: logo mark, `ARP`, and `Agentic Research Pipeline` in muted text.
- Headline: `Agents propose.` / `People ratify.` (two lines, one `h1`).
- Intro: `Thematic universes, cited extraction, transition assessment and stewardship for up to 4,000
  companies per run. Every number traces back to a verified source.`
- Button: `Open ARP →`, a link to `#/home`.
- Promises (title, then line):
  - `The LLM plans, code computes` / `Models draft the plan; deterministic code does the maths.`
  - `Every citation re-verified` / `Each quote is checked against the source document, not trusted from the model.`
  - `Nothing flagged ships` / `No flagged item reaches an export until a named person approves it.`

**Animation.** `frontend/src/components/LandingCanvas.tsx` ports the mockup's canvas script
(`docs/design-directions.html`, the `flowviz` script): 22-second loop; network of up to 3,200 dots;
a share equal to the logo's dot count lights up blue (`--run`), streams through an invisible funnel
and forms the ARP mark (amber square `--hi`) and the word "ARP" in the right part of the screen;
then dissolves. Timeline within each 22 s loop (from page load): 0–4 s network, 4–6 s light up,
6–14 s stream through the funnel and land, 14–18 s formed (logo fully drawn), 18–22 s dissolve.
Colours come from the theme tokens. It stops drawing while off-screen
(`IntersectionObserver`) and when the page is hidden, cancels its frame loop on unmount, and with
`prefers-reduced-motion: reduce` draws one still frame of the formed logo. The canvas is
`aria-hidden="true"`.

**Readability.** Text sits on the left over a gradient from `var(--bg)` (opaque) to transparent, so
it reads over the dots.

## Left to the builder

- Exact spacing and type sizes within the mockup's look; behaviour below 700px wide (stack the
  promises, shrink the headline).

## Acceptance

Rows marked `unit` are owed as `holdout` once `HOLDOUT_TOKEN` is set; the PR lists them.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `""`, `"#"`, `"#/"`, `"#/welcome"` | `entryTab` | Each returns `"welcome"` | unit |
| AC-2 | `"#/home"`, `"#/review/extraction/r1"`, `"#/argus"`, `"#/nonsense"` | `entryTab` | Each returns `null` | unit |
| AC-3 | The running app | `/` is opened | The landing page shows: an `h1` whose `innerText` has two lines, `Agents propose.` and `People ratify.`; no `.app-sidebar` element is in the DOM | evaluator |
| AC-3b | The running app | `/#/` and then `/#/welcome` are opened | Each shows the AC-3 `h1` and no `.app-sidebar` element | evaluator |
| AC-4 | The landing page | `Open ARP →` is clicked | The URL hash is `#/home`, `.app-sidebar` is present, and the landing `h1` is gone | evaluator |
| AC-5 | The running app | `#/review` is opened directly | The Review Queue shows, not the landing page | evaluator |
| AC-6 | The running app | `#/nonsense` is opened | The start page shows (as on `main`) | evaluator |
| AC-7 | The landing page | Its text is read | The top bar, intro, button and three promises match the Copy section exactly | evaluator |
| AC-8a | The landing page, 1440×900 | Two canvas captures are taken 1 s apart | They differ | evaluator |
| AC-8b | The landing page, 1440×900, light and dark | A capture is taken 16 s after load | An amber square and the dot-word "ARP" both sit in the right half of the canvas | evaluator |
| AC-8c | The same | A capture is taken 2 s after load (network phase) | No amber logo square is visible | evaluator |
| AC-9 | `prefers-reduced-motion: reduce` | The landing page opens | The canvas shows the formed logo and does not change over 5 seconds | evaluator |
| AC-10 | The landing page 16 s after load, both themes | Every backdrop pixel inside the headline and intro bounding boxes is compared with the text colour | Contrast is at least 4.5:1 for every pixel | evaluator |
| AC-11 | `LandingCanvas.tsx` | Its source is read | It uses `IntersectionObserver`, listens for `visibilitychange` (or reads `document.hidden`) before drawing, checks `prefers-reduced-motion`, calls `cancelAnimationFrame` in the effect cleanup, and the canvas has `aria-hidden="true"` | unit |
| AC-11b | The landing page in the e2e Chromium at 1440×900 | A 5 s performance trace is recorded | No long task over 50 ms | evaluator |
| AC-12 | The branch vs `origin/main` | `git diff origin/main -- frontend/tests` is read | No test or assert removed | unit |
| AC-12b | The branch | `npm test` runs | Exits 0 | unit |

Must not change: direct links and unknown hashes (AC-5, AC-6), existing tests (AC-12, AC-12b).
