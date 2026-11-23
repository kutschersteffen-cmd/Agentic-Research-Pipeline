# Expressive ARP: the Orb, a black look, pixel titles and status that moves

Status: **approved by the owner on 22 Nov 2026** (button in the spec session, after two spec-critic rounds; decisions D1 to D8 as recommended).
Amended on 23 Nov 2026 (fixture R3; AC-44 and AC-79 use runs R1 and R3): runs R1 and R2 together leave no running
card, because R2's `theme` run also makes R&D Lab wait.
Amended again on 23 Nov 2026: the list of new signal-colour uses under `## Supersedes` now names the hero's
"items need you" link, which the Design section already sets in that colour.
Slug: `expressive-ui-orb`
Risk: this spec PR is `risk:low`. The build is 3 PRs (see `## Slices`), each `risk:normal`.
Size: M
Checked against `origin/main` `fe68d09`.

## Decisions for the owner

Approving this spec accepts all of them as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | **Dark only.** The light theme and the System / Light / Dark switch are removed; every page uses the black look. | Decided by the owner on 22 Nov 2026 (button). AC-1 to AC-5 | n/a |
| D2 | **DESIGN.md changes** as written in `## DESIGN.md amendment`: the Orb is gold and morphs gold, ice, ember, mint; amber still means only "a person must act", and the Orb's colours live only inside the Orb's canvas and its phase label; brand orange marks the logo apex and the landing caption's square; the landing headline, the start greeting and the five workspace titles are set in Geist Pixel Square. | Yes (AC-6, AC-8, AC-30) | Keep one of the old rules; the rows that depend on it are struck. |
| D3 | **The name is "Agentic Research Platform"** on the landing lockup and in the browser tab title. | Yes (AC-9, AC-10) | The app keeps "Agentic Research Pipeline". |
| D4 | **The start page hero has no activity list.** The mock's four-line list under the greeting is left out: each line repeats a card right below it, and the start page has had no list since the 15 Nov simplification. The hero keeps the one sentence that counts working agents and items that need you. | Yes (AC-33 to AC-36) | The list is added as a fourth slice with its own rows. |
| D5 | **The Orb changes colour by itself** every 8 to 11 seconds, as in the approved mock, and on a click. | Yes (AC-17, AC-18) | It changes only on a click; AC-18 is struck. |
| D6 | **Pixel titles inside the workspaces are the five workspace titles only (the four overview pages and Argus's start page).** Titles of the work screens (Steward Workflow, Portfolio Builder, …) stay in Geist: they sit above dense tables. | Yes (AC-47) | Every page title is pixel; one more row. |
| D7 | **Inside a workspace** follows the workspace mock (https://claude.ai/artifact/8C7kWYpdDxCUDc271qrFLc, approved by the owner on 22 Nov 2026), with two cuts: the "Ask ARP" card has the Orb and the question box but no live step list and no summary sentence (the list repeats the process panel next to it; the sentence would need model output the page does not have). | Yes (AC-46 to AC-58) | The step list is added from run data; the sentence needs a new endpoint and its own spec. |
| D8 | **A question typed in a workspace's "Ask ARP" box is sent as typed**, as a new ask thread on the Agent screen. It carries no hidden workspace context. | Yes (AC-56) | The workspace name is prefixed to the question; AC-56 changes. |

## Why

On 22 Nov 2026 Steffen said the ARP UI is too calm and asked for it to be more expressive: pixel style and an Orb
that stands for the AI component. He approved a start page mock (https://claude.ai/artifact/EZuM9e7gUAcTxK2FGzZhi8)
and a landing page mock (https://claude.ai/artifact/TLAUfUY9QkGGY43jSAi7kZ), and at 23:07 CET asked to "apply it
to landing and startpage as well as inside the workspaces. follow the factory approach". A third mock shows the
inside of a workspace (https://claude.ai/artifact/8C7kWYpdDxCUDc271qrFLc); he approved it on 22 Nov 2026
("approved", design thread).

He approved: a black background and a dark look; the gold holographic Orb with its transformations and colour
morphs; status rails in the workspace cards; the existing isometric drawings, static, with one highlighted part
that moves once when the status changes; Geist Pixel Square for the greeting and the landing headline; the
landing page keeping its text and structure with the Orb in place of the dot animation.

He rejected: streams into or out of the Orb, moving dots, a light theme, drawings that animate all the time.

The mocks are single HTML pages with three.js 0.147 from a CDN. Sources and stills are in the project folder
`/mnt/project-files/arp-ui-expressive/` (`arp-orb-source.html`, `arp-landing-source.html`,
`arp-workspace-source.html`, `landing-desktop.png`, `cards-status-highlights.png`,
`workspace-desktop-running.png`, `workspace-desktop-waiting.png`, `workspace-phone-waiting.png`), which every
factory session has mounted. Slice 1 copies them to `docs/superpowers/specs/assets/expressive-ui-orb/`; the
evaluator rows compare against those copies. They are the reference for look and motion, not code to paste.
They were only ever run in a headless software renderer.

## What the user can do afterwards that they cannot do today

- See on the start page, per workspace, which process runs and which waits on them: one rail segment per
  process, the running one flows, the waiting one breathes.
- Notice a status change at the moment it happens: the highlighted part of the workspace's drawing moves once.
- Read in one sentence how many agents are working and how many items need them.
- Recognise the AI at a glance: the Orb is on the landing page, the start page, each workspace page and the Agent
  screen. Hover lights it, a click sends a new colour across it and transforms it.
- Ask a question from inside a workspace, in a box under the Orb.
- Use the app on a machine without WebGL, with reduced motion or with a slow GPU, and get a still Orb instead of
  an error or a stutter.

## Three versions

- **Safe:** black tokens, pixel font, rails on the start cards, and a pre-rendered picture of the Orb. No
  three.js, no interaction.
- **Strong:** the live Orb (three.js, loaded on demand) on the landing and start page with fallbacks; rails and
  the moving highlight on the start cards; workspaces get only the black look.
- **Most ambitious (specified here):** Strong, plus the inside of the workspaces (pixel title, status line, the
  drawing with its highlight, a rail segment per step, an Ask ARP card with the Orb), the Orb on the Agent screen
  showing when a question is being answered, and a quality rule that steps the Orb down on slow GPUs.

The next step up, an Orb whose motion follows the agent's output as it is written, would need a streaming
endpoint; the Agent screen polls every 3 s today (`agent-panel-code-mode` D6).

## What exists today

- Themes: `frontend/src/index.css` has a light `:root` block, a dark block under
  `@media (prefers-color-scheme: dark)` and a dark block under `:root[data-theme="dark"]`.
  `components/ThemeSwitch.tsx` (in the user menu of `AppTopbar.tsx`) and an inline script in `frontend/index.html`
  pin a theme through `localStorage["arp.theme"]`.
- Landing: `pages/Landing.tsx` renders `components/LandingCanvas.tsx` (a 2D canvas dot animation driven by
  `lib/landingMotion.ts`), the ARP lockup with "Agentic Research Pipeline", the `h1` "Company research and
  stewardship at scale.", the line "Leveraging expert judgement through Agents.", the link "Open ARP →" to
  `#/home`, and three promises. The landing page is shown for the hashes ``, `#`, `#/` and `#/welcome`.
- Start page: `pages/ProcessHub.tsx` `StartPage`: an `h1` greeting ("Good morning|afternoon|evening[, name]."),
  five `WorkspaceCard` links and the Cockpit entry. A card shows a caption ("3 processes"), `WorkspaceDrawing`,
  the name, the purpose and a status line: one 8 px square per process (`.hub-mark`) and a status word with a
  detail. All of it comes from `lib/workspaceCard.ts` `cardView()`, fed by `useRuns()` (`GET /api/runs`,
  refreshed every 3 s while a run is `running` or `pending`, else every 15 s) and the house stewardship flow.
  **The real process status is already in the frontend; this spec needs no backend change.**
- Drawings: `lib/workspaceDrawing.ts` `drawing(id, accent)` returns the shapes of each workspace's isometric
  drawing; exactly one shape per drawing can carry the accent (`.ws-accent-wait`, `.ws-accent-now`).
- Workspace pages: `#/stewardiq`, `#/transitionIntel`, `#/rdLab` and `#/dataHub` render `ProcessHub.tsx`
  `WorkspaceOverview` (`#/argus` renders `pages/ArgusStart.tsx` instead, with its own `.argus-head` and `h1`
  "Argus"): `h1`, the purpose, a 120 px drawing, then one
  `ProcessFlow` section per process (`section.hub-process`: title, a status square and word in
  `.hub-process-state`, a cadence chip, step buttons with `aria-expanded` and one details panel). A process with
  no activity is folded behind "Show n steps". `#/designStrategy` reuses `ProcessFlow`.
- Agent: `pages/Agent.tsx` (`.agent-head` with the `h1` "Agent"). Asking happens there; the Ask panel is gone.
  `App.tsx` passes `onAsk` to the command palette: it navigates to `#/agent` and sends the text as a new ask
  thread. `canAsk` is true for a signed-in role other than `viewer`.
- Fonts come from Google Fonts in `index.html` (Geist, Geist Mono, Source Serif 4). The tab title is
  "Agentic Research Pipeline".
- Build: `vite build`; the entry script `dist/assets/index-<hash>.js` is 382 560 bytes on `fe68d09`. The test
  stack (`backend/scripts/e2e_stack.sh up`) serves this build with `vite preview` on port 5173. Its headless
  Chromium has WebGL 2 through a software renderer.

## Goals

1. One black look on every page; no light theme, no theme switch.
2. An Orb component: the approved gold hologram, live in WebGL, loaded on demand, with a still fallback.
3. The landing page shows the Orb in place of the dot animation; it assembles when the page opens.
4. The start page has a hero with the Orb, the greeting in pixel type and one sentence of counts; the five cards
   carry a rail and a drawing whose highlight moves once on a status change.
5. A workspace overview page has a pixel title, a status line, the drawing with its highlight, a rail segment per step and
   an Ask ARP card with the Orb. The Agent screen shows the Orb and when a question is being answered.
6. The Orb never costs the main bundle, never throws without WebGL, never moves under reduced motion and steps
   down on a slow GPU.
7. `DESIGN.md` says all of this.

## Non-goals

- No backend change, no new endpoint, no API change. The API's OpenAPI title stays as it is.
- The top bar keeps its content and layout; it only takes the new colours.
- The Agent screen's layout (threads, stream, composer pinned to the bottom, stage) is not touched.
- No redesign of work screens beyond the colours they read from the tokens.
- The hidden Arcade keeps its own palette.
- The start page activity list (D4) and a live summary in the Ask ARP card (D7).

## Anti-goals

- Never streams into or out of the Orb, never moving dots, never a drawing that animates while its status is
  unchanged.
- Never amber for anything but "a person must act".
- Never the word "product" in new text.

## Design

### The black look (slice 1)

`index.css` keeps one `:root` token block; the light block, the `prefers-color-scheme` media blocks and every
`[data-theme]` selector go. `ThemeSwitch.tsx`, its place in the user menu and the inline theme script in
`index.html` are removed. A stored `arp.theme` is ignored. `color-scheme` is `dark`.

Tokens that change against today's dark block (all others keep today's dark value):

| Token | Value |
|---|---|
| `--bg` | `#000000` |
| `--panel` | `#0b0c0f` |
| `--well` | `#101217` |
| `--panel-border` | `rgb(255 255 255 / 0.10)` |
| `--text`, `--accent` | `#eceef2` |
| `--muted` | `#9aa3b2` |
| `--accent-tint` | `rgb(236 238 242 / 0.08)` |
| `--on-accent`, `--on-hi` | `#000000` |
| `--hi`, `--hi-ink`, `--await-edge` | `#e0b25a` |
| `--await` | `rgb(224 178 90 / 0.14)` |
| `--run` | `#5fb0ff` |
| `--sidebar-bg` | `#050506` |
| new `--panel-2` | `#101217` (the top of a card's gradient) |
| new `--panel-border-strong` | `rgb(255 255 255 / 0.18)` (hover edge) |
| new `--font-pixel` | `"Geist Pixel Square", "Geist Mono", ui-monospace, monospace` |

`--brand-apex` and `--orb` are `#ff6a2b`. The evidence paper tokens (`--paper`, `--ink`, `--paper-mark`, …) and
the chart slots keep their values. Third-party editors (`lib/editorTheme.ts`) always use their dark setting.

Geist Pixel Square is self-hosted: `GeistPixel-Square.woff2` (28 540 bytes, SIL Open Font License) from the
`geist` npm package 1.9.2 (`dist/fonts/geist-pixel/`) is copied to `frontend/src/assets/fonts/` with its
`LICENSE.txt`, and declared with `@font-face` (`font-display: swap`). The `geist` package is not added as a
dependency: it needs `next` as a peer.

### The Orb component (slice 1)

Files: `frontend/src/components/Orb.tsx` (small, in the main bundle) and `frontend/src/orb/orbScene.ts` (the
three.js scene; `Orb.tsx` loads it with a dynamic `import()`, so Vite emits it as `assets/orbScene-<hash>.js`).
`three` is added to `dependencies` at one exact version (no `^`), 0.170 or later. Pure timing and quality logic
lives in `frontend/src/lib/orbMotion.ts` with unit tests.

What it draws is the approved mock: circuit shells in segments, ring discs, a six-blade iris core, ray fans and a
network; parts turn in steps and lock, counter-rotate, fold, slide in, swing to a new axis and telescope out;
bloom, depth of field, lens fringing and grain. Port it from `arp-orb-source.html` and `arp-landing-source.html`.

The Orb's root element is `<div data-orb="<place>" role="img" aria-label="ARP Orb">`, where `<place>` is
`landing`, `start`, `workspace` or `agent`. It is the square box the sphere fills (its side is at most twice the
radius named for the place); the canvas or the still is its only child. The phase label and the hover hint are
not inside it: they are siblings in the surrounding stage. It carries these attributes, which are its public contract:

| Attribute | Values | Meaning |
|---|---|---|
| `data-orb-mode` | `live`, `still` | `live`: a `<canvas>` child renders the Orb. `still`: an `<img>` child shows the still, there is no canvas. |
| `data-orb-phase` | `assembling`, `locked`, `idle`, `folding`, `realigning`, `unfolding`, `speaking` | live only; absent in `still`. |
| `data-orb-colour` | `gold`, `ice`, `ember`, `mint` | the colour the Orb has committed to; `gold` at start and in `still`. |
| `data-orb-quality` | `high`, `medium`, `low` | live only. |
| `data-orb-state` | `idle`, `working` | `working` is set only on the Agent screen. |
| `data-orb-paused` | `true` or absent | live only: rendering is paused. |

**Before the scene runs.** From mount until the scene has drawn its first frame the Orb has no `data-orb-mode`
attribute and an empty box: no canvas shown, no still.

**Still mode.** The Orb is `still` when any of these holds: neither `webgl2` nor `webgl` gives a context;
`prefers-reduced-motion: reduce` matches; the `orbScene` chunk fails to load; the WebGL context is lost; the
quality rule gives up (below); `sessionStorage["arp.orb.level"]` is `still` and nothing is pinned;
`localStorage["arp.orb"]` is `still`. Where the cause is known before the scene loads (no WebGL, reduced motion,
the stored or pinned `still`) the `orbScene` chunk is never requested. The still is a picture of the assembled gold Orb on black, exported from the
live component at quality `high`, committed as `frontend/src/assets/orb-still.webp` (800 × 800 px, at most
80 000 bytes). Nothing is logged to the console when the Orb goes still.

**Timeline.** Phases follow elapsed time, not frame count; a gap of more than 250 ms between two frames counts
as 250 ms.

- With the intro (landing page only): `assembling` for 2.6 s, `locked` until 3.5 s, then `idle`.
- Without the intro the Orb starts `idle`.
- A transformation lasts 3.3 s: `folding` until 0.75 s, `realigning` until 1.6 s, `unfolding` until 2.35 s,
  `locked` until 3.3 s; then `data-orb-colour` moves to the next of gold → ice → ember → mint → gold and the
  phase returns to `idle`.
- A transformation starts on a click (or tap) on the Orb while it is `idle`, and by itself 8 to 11 s (random)
  after the Orb became `idle`. Clicks during a transformation are ignored. While `speaking`, the timer for the
  self-started transformation is stopped; it starts again from zero on return to `idle`.
- Hovering the Orb while `idle` previews the next colour at the pointer and shows the hint "Click to transform"
  next to the pointer.
- `speaking` (the ring around the core pulses): on the landing page while "Open ARP" is hovered or has keyboard
  focus and the Orb is otherwise `idle`; on the Agent screen it is not used.
- In `idle`, parts keep turning in steps and locking, as in the mock.

**Phase label.** On the landing and start page and in the Ask ARP card, a mono caption shows the phase in the
stage's bottom right corner: an 8 px square in the Orb's current colour and one of "Assembling", "Locked", "Idle",
"Folding", "Re-aligning", "Unfolding", "Speaking" (CSS sets it in capitals). It is an element with
`data-orb-label`, `aria-hidden="true"`, present only in `live` mode.

**Quality.** `high`: pixel ratio up to 2 (capped so the canvas has at most 3.4 million pixels), bloom, depth of
field, fringing, grain. `medium`: pixel ratio 1, bloom at half resolution, no depth of field. `low`: pixel ratio
0.75, no post-processing, no network lines. The rule measures the difference between the timestamps passed to successive
`requestAnimationFrame` callbacks. The first frame after a pause (see Housekeeping) is not counted; any other
gap counts as at most 1000 ms:

- every 60 frames the mean frame time is taken; above 33.3 ms (under 30 frames a second) the Orb steps down one
  level, `high` → `medium` → `low`;
- at `low`, a mean above 50 ms (under 20 frames a second) over 60 frames switches the Orb to `still` for the rest
  of the page view;
- it never steps up. The level reached (`high`, `medium`, `low` or `still`) is kept in
  `sessionStorage["arp.orb.level"]`, and the next Orb in the same browser session starts there;
- `localStorage["arp.orb"]` set to `high`, `medium`, `low` or `still` pins that level: the rule is off and
  `sessionStorage` is neither read nor written. Any other value is ignored. There is no UI for it.

The Orb at place `agent` always runs at `low` (it is 56 px wide) and takes no part in the rule. It has no hover
preview, no hint and ignores clicks; it still transforms by itself.

**Housekeeping.** Rendering pauses (`data-orb-paused="true"`) while the Orb is outside the viewport or the tab is
hidden. Leaving the page disposes the renderer and its WebGL context. A lost context switches to `still`. The
canvas follows its container's size. At most one Orb is on a page.

### Landing page (slice 1)

`LandingCanvas.tsx` and `lib/landingMotion.ts` are deleted. `Landing.tsx` keeps its lockup, `h1`, line, "Open
ARP →" link (to `#/home`, navigating at once) and the three promises, word for word. Changes:

- The lockup's full name reads "Agentic Research Platform". `index.html`'s `<title>` reads the same.
- A caption above the headline: an 8 px brand-orange square and "Agents at work" (mono, capitals by CSS).
- The `h1` is set in `--font-pixel`, weight 400, `clamp(40px, 5.4vw, 80px)`, line height 0.96, at most 13ch wide.
- Above 860 px the text is the left column and the Orb (`data-orb="landing"`, with the intro) the right one; the
  Orb's radius is at most 300 px. At 860 px and below the Orb sits above the text.
- The gradient behind the text and the text halo go: the text no longer sits on the animation.

### Start page (slice 2)

The hero is the Orb's stage (at least 660 px high above 860 px): text on the left, the Orb
(`data-orb="start"`, no intro, radius at most 205 px) on the right; at 860 px and below the Orb sits above the
text.

- A mono caption with today's date and the time the page opened: `Sunday 22 Nov · 22:15` (English weekday, day,
  three-letter month, 24-hour local time).
- The greeting keeps its words ("Good evening, dev.") in an `h1`, now in `--font-pixel`, weight 400,
  `clamp(52px, 7.2vw, 104px)`, line height 0.92, ink colour.
- The lead, a `<p data-hero-lead>`: with `n` the number of loaded runs whose status is `running` or `pending`,
  it reads "No agent is working right now." (`n` = 0), "1 agent is working for you." (`n` = 1) or "`n` agents are
  working for you." Before the runs have loaded, or when loading them failed, this sentence is absent. With `t` the `total` of
  `GET /api/waiting`, a link to `#/review` follows in the signal colour: "1 item needs you." (`t` = 1) or "`t`
  items need you." (`t` ≥ 2); at `t` = 0, or when the count has not loaded or failed, the link is absent.

The cards keep their link, accessible name, caption, name and purpose. Changes:

- Grid: five in a row above 1180 px, three from 761 to 1180 px, two from 481 to 760 px, one at 480 px and below.
- The figure area is 200 px high, near-black, with a soft glow behind the drawing: blue when the card's status is
  running, amber when waiting, none otherwise.
- The rail replaces the 8 px squares: an element with `data-rail` holding one `data-seg` element per process, in
  process order, 10 px high, 3 px apart. `data-seg` is the process state: `done` (solid ink), `now` (blue,
  flowing), `wait` (amber, breathing), `failed` (solid `--low`), `idle` (outlined), `unknown` (dashed outline,
  before runs load). Flowing is an endless CSS animation on the segment's `::before`; breathing is an endless CSS
  animation on the segment itself; the other states have no animation.
- The status word stays; the detail moves to the right in mono. When the status is running the detail reads
  "`<step>` · step `i` of `n`": the label and 1-based position of the first step whose state is running, in the
  first process whose state is running, with `n` that process's number of steps. All other details stay. `cardStatus()` in
  `lib/workspaceCard.ts` keeps its results; the running detail is built next to it.
- A waiting card keeps the waiting edge and adds an amber glow; a running card has a blue glow. On hover a card
  lifts 3 px.
- The drawing, see next section. The Cockpit entry stays below the cards.

### The drawings and their highlight (slice 2)

`WorkspaceDrawing` renders `svg.ws-drawing` with `data-status` set to `now`, `wait` or `none`. Faces take dark
gradient fills; the highlighted part takes a blue or amber stroke, fill and glow. Only the top face of the
status part carries the class `ws-accent-now` or `ws-accent-wait`; its side faces move with it without that
class. The scan plane and the dashed outline in the table below carry the class `ws-extra`. While the status is `now` or
`wait` the status part is **out**; otherwise it is **in**:

| Workspace | Status part | Out |
|---|---|---|
| StewardIQ | top slab | lifted 13 units off the stack |
| Argus | centre column | 12 units taller; while running, a flat scan plane rests over the document |
| Transition Intel | the 4th fin while running, the 8th while waiting | 10 units taller |
| R&D Lab | first box | 9 units taller; while running, a dashed outline of its next level above it |
| Data Hub | top disc | lifted 7 units |

Until the runs have loaded `data-status` is `none`. The first status known after they load is drawn in place:
nothing moves. On every later change `data-status` takes the new value at once, the part moves from where it is
to its new place in 850 ms (overshooting slightly on the way out), and the figure area flashes once (950 ms).
During the move the `svg` has `data-moving="true"`; before and after, the attribute is absent. Nothing else in a
drawing ever moves. Under reduced motion the part is drawn at its new place at once: no move, no flash, no
`data-moving`, and cards do not lift on hover.

### Inside a workspace (slice 3)

`WorkspaceOverview` (`#/stewardiq`, `#/transitionIntel`, `#/rdLab`, `#/dataHub`), following the workspace mock.
Argus's start page (`ArgusStart.tsx`) changes in one thing only: its `h1` takes the same pixel type.

- Header. A mono caption "Workspace · `n` processes" ("1 process" for one). The `h1` keeps its text
  (`w.name`), set in `--font-pixel`, weight 400, `clamp(48px, 6.4vw, 92px)`, line height 0.94; a long name wraps.
  The intro stays the workspace's purpose, directly after the `h1`. Under it a status line, `<p data-ws-status>`:
  the 8 px status square, the card's status word and its detail; when running the detail is "`<process title>` ·
  `<step>` · step `i` of `n`".
- The drawing sits in a figure box (300 × 240 px above 760 px, full width × 200 px at 760 px and below, where it
  follows the status line), with the same glow, highlight and one-time move as on the card. It is shown at every
  width.
- Each `section.hub-process` becomes a panel (hairline, 12 px corners). It carries `data-state` with the process
  state; a `now` panel has a blue glow, a `wait` panel the waiting edge and an amber glow. Its heading, status
  square and word, cadence chip, fold ("Show n steps"), step buttons and details panel stay as they are.
- Above the step buttons sits a rail with one `data-seg` per step, in step order, using the step's state; a
  planned step is `data-seg="planned"` (dashed outline); until the runs have loaded every other segment is
  `unknown`. The rail is inside the fold: a folded process shows none.
- Under the label of a step that is running, a mono line "`c` of `m`" shows `completed_count` and `company_count`
  of the most recently updated `running` or `pending` run among that step's run types, when `m` > 0.
- The Ask ARP card, an `<aside aria-label="Ask ARP">`, only when `canAsk`: a caption "Ask ARP", the Orb
  (`data-orb="workspace"`, stage 180 px high, no intro) with its phase label, and a form with one text box whose
  accessible name and placeholder are "Ask about `<w.short or w.name>`". Enter opens `#/agent` and sends the trimmed text as a new ask thread, the way the command palette's ask does;
  Enter on an empty or whitespace-only box does nothing. Above 1080 px the card is a 340 px right column next to the header and panels; at 1080 px and
  below it sits between the header and the panels.
- `#/designStrategy` gets the rail and the panel look through `ProcessFlow`; nothing else changes there.

Agent screen: `.agent-head` shows the Orb (`data-orb="agent"`, 56 × 56 px, no intro, no phase label, not
clickable, quality `low`) before the `h1`. `data-orb-state` is `working` while an ask request is in flight (from
sending a question until its answer or error shows), else `idle`; plan and exploration actions leave it `idle`; while `working` the ring around the core pulses. The Orb is mounted in
`Agent.tsx` with one element; everything else about it lives in `Orb.tsx`.

### DESIGN.md amendment

Applied in slice 1 (AC-30). Replace as follows; text not named here stays.

1. Frontmatter: `name: Agentic Research Platform`; `description: A black instrument panel with a gold
   holographic Orb for the agents, where amber lights up only when a person must act.` The light colour entries
   and the `night-` prefix go: the colour list is the single token set of `### The black look` (same names
   without `night-`), plus `orb-gold: "#ff8f1f"`, `orb-ice: "#249eff"`, `orb-ember: "#ff451a"`,
   `orb-mint: "#1aeb9e"`. `landing-headline` and `display` take `fontFamily: "Geist Pixel Square, Geist Mono,
   ui-monospace, monospace"`, `fontWeight: 400`, `letterSpacing: "0"`, with `fontSize` and `lineHeight` as in
   this spec. The heading reads `# Design System: Agentic Research Platform`.
2. Overview, second paragraph, last two sentences become: "There is one theme: black. Every component reads its
   colours from the same tokens." The first Key Characteristic becomes: "Black ground, ink accent for controls,
   amber reserved for 'waiting on a person'." Add a Key Characteristic: "The Orb, a gold hologram, stands for the
   agents; it is the only place where colour is spectacle."
3. Colour values in the prose take the token table's values, with no light / dark pairs.
4. **The Brand Colour Rule** becomes: "Brand orange (#ff6a2b) appears in two places only: the logo apex and the
   square of the landing caption. It never appears elsewhere in the interface, so it cannot be mistaken for the
   amber signal."
5. Add **The Orb Colour Rule**: "The Orb is gold and morphs through ice, ember and mint. These four colours live
   only inside the Orb's canvas and its phase label. They carry no meaning: they are not status and not the
   signal. Nothing outside the Orb may use them, and the Orb never uses `--hi`."
6. **The One Signal Rule**: after "When nothing waits, no amber appears anywhere on the screen." add "The Orb's
   gold is not amber and is exempt (see The Orb Colour Rule)."
7. Typography: add "**Pixel Font:** Geist Pixel Square, for the landing headline, the start-page greeting and the
   five workspace titles only". "Source Font" loses "and the landing headline". **Display** becomes "(Geist Pixel
   Square 400, clamp(52px → 104px), 0.92): the start-page greeting; the workspace titles use the same face at
   clamp(48px → 92px)". **The Serif Means Source Rule** becomes: "The serif is for text quoted from a source
   document (the evidence paper). Nothing else uses it." Add **The Pixel Means Presence Rule**: "Pixel type marks
   the three places where ARP presents itself: the landing headline, the greeting and a workspace's title. Never
   set running text, tables or controls in it."
8. Layout: the start-page sentence becomes "The start page is the hero (the Orb, the greeting, one sentence of
   counts), then the five workspace cards in one row (three per row at 1180px and below, two at 760px, one at
   480px)."
9. Elevation: **The Flat Card Rule** gains: "Glows are status light, not elevation: a start card or process
   panel that runs or waits, its figure area and the lit part of its drawing glow in the status colour. Nothing
   else glows."
10. Signature Elements: "Three elements" becomes "Five elements"; add two headings, `### The Orb` and
    `### Status Rail`, each followed by its body:
    The Orb: "The visual for ARP's agents: a gold holographic sphere whose parts turn in steps, fold and
    lock. It appears on the landing page, the start page, a workspace's Ask ARP card and the Agent screen, once
    per page. Hover previews the next colour, a click transforms it. Without WebGL, under reduced motion or on a
    slow GPU it is a still picture. Never draw streams into or out of it."
    Status Rail: "Processes and steps are shown as a rail of 10px segments, 3px apart: solid ink = done,
    blue and flowing = running, amber and breathing = waiting on you, red = failed, outlined = idle, dashed =
    unknown or planned. Under reduced motion nothing flows or breathes."
11. **The Icon Accent Rule** gains: "The lit element is out of place while lit (lifted or taller) and moves once,
    in 850ms, when the status changes. Nothing else in a drawing moves."
12. Navigation: in **Top bar**, "(reviewer name, sign-in, theme, Arcade)" becomes "(reviewer name, sign-in,
    Arcade)". **Workspace overview header** becomes: "a caption, the pixel title, the intro and a status line on
    the left; the workspace drawing in a 300 × 240px figure box on the right (full width under the status line on
    phones). The drawing lights up like the workspace's start-page card. With asking allowed, an Ask ARP card
    with the Orb and a question box is the right column (above the process panels at 1080px and below)."
13. **Process Card**: "an 8px square per process (…)" becomes "a status rail with one segment per process"; add
    "When a process runs, the status line names the running step and its position ('Spot · step 1 of 7')."
14. Do's and Don'ts: "both themes depend on it" becomes "the theme depends on it"; "in both themes" is dropped;
    "Don't use brand orange anywhere but the logo apex and the landing animation." becomes "Don't use brand
    orange anywhere but the logo apex and the landing caption."; add "Don't use the Orb's colours outside the
    Orb." and "Don't animate a drawing while its status is unchanged."

## Supersedes

These rows of earlier specs are replaced; their tests are rewritten or removed in the slice named, and each
change is listed in that PR.

- Night Desk colours, status and excerpt (`2026-11-08-night-desk-*.md`): every row that pins a light token, the
  two dark blocks or a value in the token table above. `frontend/tests/nightDeskTokens.test.ts` then pins the one
  token block; its contrast tests keep their thresholds and run on that block. Slice 1. Its
  `ac13_amber_usage_unchanged` allow-list gains, in slices 2 and 3, the new uses of the signal colour and only
  these: the start page hero's "items need you" link, the rail's `wait` segment, the waiting glow of a start
  card, of a figure area and of a process panel, and the drawing's status part.
- Night Desk landing and landing brand refresh (`2026-11-09-night-desk-landing-design.md`,
  `2026-11-14-landing-brand-refresh-design.md`): the dot animation, its phases, the serif headline, the
  see-through intro and the light `--orb` / `--brand-apex` values. In `frontend/tests/landing.test.ts`:
  `phase_boundaries`, `r5_ac11`, `ac12a_see_through_intro`, `ac12b_text_halo`, `ac12c_see_through_intro_narrow`,
  `ac15a_serif_headline`, `ac15b_headline_size_unchanged`, `resize_rebuild_is_throttled`,
  `zero_size_canvas_does_not_crash`, `ac7b_canvas_colours_from_tokens`, `ac6_no_signal_in_canvas`,
  `theme_follows_live`, `reduced_motion_single_frame`, `draw_skips_zero_size_canvas`,
  `reduced_motion_frame_follows_theme_and_resize`, `no_debug_global`, `depth_bucket_clamps_out_of_range_depth`
  are removed; `ac4_brand_apex` and `ac5_orb_token` pin `#ff6a2b` in the one block. Slice 1.
- Start page (`2026-11-09-night-desk-start-page-design.md`, `2026-11-15-start-page-simplified-design.md`): the
  3 + 2 grid, the 8 px process squares on the cards and the flat drawing fill. In
  `frontend/tests/startPage.test.ts`: `sp_ac10_grid`, `sp_tablet_last_card_fills_its_row`, `sp_ac12d_marks`,
  `sp_ac13c_drawing_look`. Slice 2. The card's running detail changes on the card only; `cardStatus()` and its
  tests in `frontend/tests/workspaceCard.test.ts` stay.
- App-wide top bar (`2026-11-15-app-wide-top-bar-design.md`): the theme switch in the user menu (slice 1); the
  120 px header drawing right of the title and hidden on phones, in `backend/tests/e2e/test_top_bar_pr2.py`
  `test_ac30_drawing_right_of_title` and the tests that use `HEAD_DRAWING`, and the `.ws-drawing` display rule in
  `frontend/tests/topbarPr2.test.ts` (slice 3). The tests of `.hub-mark` on start cards in
  `backend/tests/e2e/test_top_bar_pr2.py` go in slice 2; those on `.hub-process-state` stay.
- Public browser tests that set `color_scheme` or a light theme (`backend/tests/e2e/test_ui_polish_2.py`,
  `test_top_bar_pr3.py`, `test_value_chain_portfolio.py`) drop the light case. Slice 1.
- UI polish 1 and 2 (`2026-11-15-*`, `2026-11-16-ui-polish-2-linear-design.md`), slice 1:
  `backend/tests/e2e/test_ui_polish_1.py` expects no `.theme-switch` in the user menu (was 1);
  `test_ui_polish_2.py` expects the hairline `rgba(255, 255, 255, 0.1)` (was `rgba(232, 235, 240, 0.12)`);
  `frontend/tests/polish2.test.ts` expects the font-smoothing rule on `body` in the one block. The
  `.theme-switch` CSS itself stays: `ReportBuilder.tsx` uses it for the deck's colour theme.
- By row, for whoever retires tests of earlier specs: `start-page-simplified` AC-1e (greeting font) and AC-7b
  (theme switch in the menu); `ui-polish-1` AC-1; `ui-polish-2` AC-2, AC-6, AC-6b, AC-8, AC-9 (light theme and
  old dark values); `app-wide-top-bar` AC-30, AC-30b (header drawing). Any other earlier row that pins a light
  token, a value changed in the token table, the dot animation, the serif headline, the 3 + 2 grid or the card
  squares is superseded the same way.

No row of `ui-trim-workspaces`, `rd-lab-rename`, `agent-panel-code-mode` or `agent-board` is superseded.

## Acceptance

All rows run on the app started by `backend/scripts/e2e_stack.sh up` (dev auth, role `approver`, no model key),
in headless Chromium at 1440 × 900 with its default software WebGL, and **pinned low**, unless the Given says
otherwise ("no pin", "no WebGL", "reduced motion" or another `arp.orb` value replace the pin).

Terms used in the rows:

- **landing** is the URL with no hash; **the Orb** is the element with `data-orb`.
- **Pinned low** means the test sets `localStorage["arp.orb"] = "low"` before the app loads.
- **No WebGL** means an init script makes `HTMLCanvasElement.prototype.getContext` return `null` for `webgl2`,
  `webgl` and `experimental-webgl`.
- **Reduced motion** means the browser context emulates `prefers-reduced-motion: reduce`.
- **Runs R0, R1, R2, R3** mean the test answers every `GET /api/runs*` with `{"runs": [...]}`: R0 an empty list; R1
  one run `{run_id: "r1", run_type: "emerging_themes", status: "running", review_count: 0, company_count: 480,
  completed_count: 212, failed_count: 0, …}`; R2 one run `{run_id: "r2", run_type: "theme", status:
  "completed", review_count: 2, company_count: 5, completed_count: 5, failed_count: 0, …}`; R3
  one run `{run_id: "r3", run_type: "extraction", status: "completed", review_count: 2, company_count: 5,
  completed_count: 5, failed_count: 0, params: {}, …}`. Other manifest fields take any valid value; `created_at` and
  `updated_at` are `2026-11-22T10:00:00Z`. R2 makes both the Argus card and the R&D Lab card wait; R3 makes only
  the Argus card wait. "Runs R1 and R3" is the list of both runs: the R&D Lab card runs (rail `now`, `idle`,
  `idle`, `idle`) and the Argus card waits (rail `wait`, `idle`).
- **Waiting W** means the test answers `GET /api/waiting` with `{"review": 2, "decisions": 0, "ballots": 0,
  "total": 2}`; **W0** with all four at 0.
- **The R&D Lab card** and **the Argus card** are the start-page links whose accessible names start "R&D Lab."
  and "Argus.".

### The black look

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | e2e stack | open each of landing, `#/home`, `#/rdLab`, `#/agent`, `#/review`, `#/index` | the computed `background-color` of `body` is `rgb(0, 0, 0)` | holdout |
| AC-2 | the browser context emulates `prefers-color-scheme: light` | open `#/home` | the computed `background-color` of `body` is `rgb(0, 0, 0)` | holdout |
| AC-3 | `localStorage["arp.theme"] = "light"` set before load | open `#/home` | the computed `background-color` of `body` is `rgb(0, 0, 0)` and `<html>` has no `data-theme` attribute | holdout |
| AC-4 | e2e stack | open `#/home`, open the user menu | no element with role `group` named "Colour theme" exists, and no button named "Light", "Dark" or "System" is in the menu | holdout |
| AC-5 | e2e stack | open `#/home` | on `:root` the computed custom properties read `--panel` `#0b0c0f`, `--text` `#eceef2`, `--muted` `#9aa3b2`, `--hi` `#e0b25a`, `--run` `#5fb0ff`, `--orb` `#ff6a2b` | holdout |
| AC-6 | e2e stack | open landing, wait for `document.fonts.ready` | `[...document.fonts].some(f => f.family.includes("Geist Pixel Square") && f.status === "loaded")` is `true` | holdout |
| AC-7 | e2e stack, the test records every request | open landing, wait for `document.fonts.ready` | exactly one request URL contains `GeistPixel-Square`, and it goes to the app's own origin | holdout |

### Names

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-8 | e2e stack | open landing | the computed `font-family` of the `h1` starts with `"Geist Pixel Square"` | holdout |
| AC-9 | e2e stack | open landing | the text "Agentic Research Platform" is visible in the header and "Agentic Research Pipeline" is not on the page | holdout |
| AC-10 | e2e stack | open landing | `document.title` is "Agentic Research Platform" | holdout |

### The Orb

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-11 | pinned low | open landing | within 5 s one Orb is on the page with `data-orb="landing"`, `data-orb-mode="live"`, `data-orb-quality="low"`, `data-orb-colour="gold"`, and it has one `<canvas>` child | holdout |
| AC-12 | pinned low | open landing, read `data-orb-phase` as soon as `data-orb-mode` is `live` | it is `assembling` | holdout |
| AC-13 | pinned low | open landing, wait 6 s after `data-orb-mode` became `live` | `data-orb-phase` is `idle` | holdout |
| AC-14 | pinned low | open `#/home`, read `data-orb-phase` as soon as `data-orb-mode` is `live` | it is `idle` (no intro on the start page) | holdout |
| AC-15 | `#/home`, Orb `idle` | click the centre of the Orb, then record every change of `data-orb-phase` for 10 s | the recorded changes begin `folding`, `realigning`, `unfolding`, `locked`, `idle`, in that order | holdout |
| AC-16 | AC-15 | after the phase is `idle` again | `data-orb-colour` is `ice` | holdout |
| AC-17 | pinned low, `#/home`, Orb `idle` | click the Orb, wait until `idle`; repeat three more times | `data-orb-colour` reads `ice`, `ember`, `mint`, `gold` after the first to fourth click | holdout |
| AC-18 | pinned low, `#/home`, no pointer input | wait 16 s after the Orb first became `idle` | `data-orb-colour` is `ice` or the phase is one of `folding`, `realigning`, `unfolding`, `locked` (it transformed by itself) | holdout |
| AC-19 | pinned low, `#/home`, Orb `idle` | move the pointer to the Orb's centre | the text "Click to transform" is visible | holdout |
| AC-20 | pinned low | open landing, wait until `idle`, focus the link "Open ARP" with the keyboard | within 1 s `data-orb-phase` is `speaking`, and the element with `data-orb-label` reads "Speaking" | holdout |
| AC-21 | pinned low | open landing, read the element with `data-orb-label` while the phase is `assembling` | its text is "Assembling" | holdout |
| AC-22 | no WebGL | open each of landing, `#/home`, `#/rdLab`, `#/agent` | the Orb has `data-orb-mode="still"`, one visible `<img>` child whose natural width is 800, no `<canvas>` child and no `data-orb-phase` attribute | holdout |
| AC-23 | no WebGL, the test records console messages and page errors | open each of landing, `#/home`, `#/rdLab`, `#/agent` and wait 5 s on each | no console message of type `error` and no uncaught page error | holdout |
| AC-24 | no WebGL, the test records every request | open landing, then `#/home`, wait 5 s on each | no request URL contains `orbScene` | holdout |
| AC-25 | reduced motion | open each of landing and `#/home` | the Orb has `data-orb-mode="still"` and no `<canvas>` child, and no request URL contains `orbScene` | holdout |
| AC-26 | no pin; an init script replaces `requestAnimationFrame` with one that calls back after a 5 ms timer with timestamps that advance 100 ms per call | open `#/home` and record every change of the Orb's attributes for 60 s | `data-orb-quality` is seen as `high`, then `medium`, then `low`, in that order | holdout |
| AC-27 | AC-26 | at the end of the 60 s | `data-orb-mode` is `still`, the Orb has no `<canvas>` child and `sessionStorage["arp.orb.level"]` is `still` | holdout |
| AC-28 | `orbMotion.ts` quality rule, unit test | feed, each from the level named: at `high` 60 frame gaps of 30 ms; at `high` 60 of 34 ms; at `low` 60 of 45 ms; at `low` 60 of 51 ms; at `high` 59 of 20 ms plus one first-after-pause gap of 5000 ms; at `high` 59 of 20 ms plus one gap of 5000 ms that is not after a pause | the level is then `high`; `medium`; `low`; `still`; `high`; `medium` (the gap counts as 1000 ms, mean 36.3 ms) | unit |
| AC-29 | `sessionStorage["arp.orb.level"] = "medium"` set before load, no pin | open `#/home`, read `data-orb-quality` as soon as `data-orb-mode` is `live` | it is `medium` | holdout |
| AC-30 | slice 1's diff | read `DESIGN.md` with every `*` removed and runs of whitespace collapsed to one space | it contains each sentence quoted in `## DESIGN.md amendment` items 2, 4, 5, 6, 7, 9, 10, 11 and 14 (compared the same way), the headings `# Design System: Agentic Research Platform`, `### The Orb` and `### Status Rail`, and neither "in light and dark" nor "the landing animation's orb glow" | unit |
| AC-31 | pinned low | open landing; the Orb's canvas has `width` attribute `w` and CSS width `c` | `w` ≤ 0.75 × `c` + 1 | holdout |
| AC-32 | pinned low, `#/home`, Orb `live` | the test calls `loseContext()` of the `WEBGL_lose_context` extension on the Orb canvas's WebGL context | within 2 s `data-orb-mode` is `still` and no uncaught page error occurred | holdout |
| AC-59 | pinned low, `#/home` | scroll the page so the Orb is fully outside the viewport (viewport 1440 × 500) | within 1 s the Orb has `data-orb-paused="true"`; after scrolling back to the top the attribute is absent within 1 s | holdout |
| AC-60 | pinned low, the test records console messages | go `#/home` → `#/rdLab` → `#/home` 20 times, waiting for `data-orb-mode="live"` each time | no console message contains "Too many active WebGL contexts" | holdout |
| AC-61 | the test aborts every request whose URL contains `orbScene` | open landing | within 5 s the Orb has `data-orb-mode="still"` and the `h1` "Company research and stewardship at scale." is visible | holdout |
| AC-62 | `localStorage["arp.orb"] = "still"` set before load | open `#/home` | the Orb has `data-orb-mode="still"` and no request URL contains `orbScene` | holdout |
| AC-63 | pinned low, the test records console messages and page errors | open each of landing, `#/home`, `#/rdLab`, `#/agent`, wait 10 s on each; on `#/home` click the Orb once | no console message of type `error` and no uncaught page error | holdout |

### Bundle

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-64 | e2e stack | fetch the page's HTML, then the `src` of its `<script type="module">` | the script's body is at most 420 000 bytes | holdout |
| AC-65 | AC-64 | search that script's body | it does not contain the string `WebGLRenderer` | holdout |
| AC-66 | pinned low, the test records every script response | open landing, wait for `data-orb-mode="live"` | exactly the scripts whose URL contains `orbScene` contain the string `WebGLRenderer`, and their bodies total at most 800 000 bytes | holdout |
| AC-67 | no WebGL | open landing; read the `<img>` inside the Orb and fetch its `src` | the response is at most 80 000 bytes | holdout |

### Landing page

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-68 | e2e stack | open landing | the text "Agents at work" is visible above the `h1` | holdout |
| AC-69 | e2e stack | open landing | no element with class `landing-canvas` exists | holdout |
| AC-70 | pinned low, 1440 × 900 | open landing | the Orb's bounding box lies entirely right of the `h1`'s bounding box | holdout |
| AC-71 | pinned low, 390 × 844 | open landing | the Orb's bounding box lies entirely above the `h1`'s, and `document.documentElement.scrollWidth` is at most 390 | holdout |
| AC-72 | e2e stack | open landing, compare with `landing-desktop.png` and the landing mock source | the Orb reads as the same object: gold, circuit shells, ring discs, a bright iris core; it assembles from the core outwards; the headline is in pixel type; no dots move anywhere and no lines or particles travel into or out of the Orb | evaluator |

### Start page

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-33 | runs R1, waiting W | open `#/home` | the element with `data-hero-lead` reads "1 agent is working for you. 2 items need you." | holdout |
| AC-34 | runs R1, waiting W | open `#/home` | inside `data-hero-lead`, "2 items need you." is a link with `href` `#/review` | holdout |
| AC-35 | runs R0, waiting W0 | open `#/home` | the element with `data-hero-lead` reads "No agent is working right now." and contains no link | holdout |
| AC-36 | runs: two copies of R1's run with ids `r1`, `r1b`; waiting `{"review": 1, "decisions": 0, "ballots": 0, "total": 1}` | open `#/home` | the element with `data-hero-lead` reads "2 agents are working for you. 1 item needs you." | holdout |
| AC-37 | e2e stack | open `#/home` | the computed `font-family` of the `h1` starts with `"Geist Pixel Square"`, and its text matches `^Good (morning|afternoon|evening)(, .+)?\.$` | holdout |
| AC-38 | e2e stack | open `#/home` | a caption above the `h1` matches `^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) \d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) · \d{2}:\d{2}$` | holdout |
| AC-39 | runs R1 | open `#/home` | the R&D Lab card's rail has four `data-seg` elements reading, in order, `now`, `idle`, `idle`, `idle` | holdout |
| AC-40 | runs R1 | open `#/home` | the R&D Lab card shows "Running" and "Spot · step 1 of 7" | holdout |
| AC-41 | runs R2 | open `#/home` | the Argus card's rail has two `data-seg` elements reading `wait`, `idle`, and the card shows "Waiting on you" | holdout |
| AC-42 | runs R1 | open `#/home` | on the R&D Lab card, the `now` segment's `::before` has a computed `animation-name` other than `none` with `animation-iteration-count` `infinite`, and the three `idle` segments and their pseudo-elements have `animation-name` `none` | holdout |
| AC-43 | runs R2 | open `#/home` | on the Argus card, the `wait` segment has a computed `animation-name` other than `none` with `animation-iteration-count` `infinite` | holdout |
| AC-44 | runs R1 and R3, reduced motion | open `#/home` | the R&D Lab card's rail has a `now` segment, the Argus card's a `wait` segment, and every `data-seg` element and its `::before` and `::after` have computed `animation-name` `none` | holdout |
| AC-45 | no route override | open `#/home` | no element with class `hub-mark` is inside a start card | holdout |
| AC-73 | runs R1 | open `#/home` | the R&D Lab card's `svg.ws-drawing` has `data-status="now"` and exactly one path with class `ws-accent-now`; the Argus card's has `data-status="none"` and no path whose class starts `ws-accent-` | holdout |
| AC-74 | runs R1 | open `#/home` and record every attribute change of the R&D Lab card's `svg.ws-drawing` for 3 s | `data-status` ends as `now` and `data-moving` was never present (the first known status is drawn in place) | holdout |
| AC-75 | runs R1 at load; once the R&D Lab card shows `data-status="now"`, the test switches the answer to R0 | wait up to 8 s, recording every attribute change of the R&D Lab card's `svg.ws-drawing` | when `data-status` becomes `none`, `data-moving="true"` is set within 100 ms; 1.5 s later `data-moving` is absent | holdout |
| AC-76 | AC-75 with reduced motion | same | `data-status` becomes `none` and `data-moving` is never present | holdout |
| AC-77 | runs R1 at load, then R0 | watch the R&D Lab card across the change | only the highlighted box changes place; every other shape of the drawing and the four other drawings stay still | evaluator |
| AC-78 | runs R0 | open `#/home` at widths 1440, 1000, 700 and 390 | the number of workspace cards sharing the first card's top edge is 5, 3, 2 and 1 | holdout |
| AC-79 | runs R1 and R3 | open `#/home`, compare with `cards-status-highlights.png` and the start page mock source | the R&D Lab card glows blue and its `now` segment visibly flows; the Argus card has an amber edge and its `wait` segment breathes; the Orb sits right of the greeting and matches the mock; no lines or particles travel into or out of the Orb | evaluator |

### Inside a workspace

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-46 | e2e stack | open `#/rdLab` | a caption reading "Workspace · 4 processes" is above the `h1`; on `#/dataHub` it reads "Workspace · 1 process" | holdout |
| AC-47 | e2e stack | open each of `#/stewardiq`, `#/argus`, `#/transitionIntel`, `#/rdLab`, `#/dataHub` | the computed `font-family` of the page's `h1` starts with `"Geist Pixel Square"`; on `#/stewardship` the `h1`'s does not | holdout |
| AC-48 | runs R1 | open `#/rdLab` | the element with `data-ws-status` reads "Running" followed by "Build a thematic portfolio · Spot · step 1 of 7" | holdout |
| AC-49 | runs R1 | open `#/rdLab` | the section labelled "Build a thematic portfolio" has `data-state="now"` and a rail of seven `data-seg` elements reading `now`, then six `idle` | holdout |
| AC-50 | runs R1 | open `#/rdLab` | the button `#step-thematic-0` (step "Spot" of "Build a thematic portfolio") shows the text "212 of 480" | holdout |
| AC-51 | runs R2 | open `#/rdLab` | the section labelled "Build a thematic portfolio" has `data-state="wait"`, and its rail reads `idle`, `idle`, `done`, `wait`, `idle`, `idle`, `idle` | holdout |
| AC-52 | runs R1 | open `#/rdLab` | the page has one `svg.ws-drawing`, with `data-status="now"`, and it is visible at 1440 × 900 and at 390 × 844 | holdout |
| AC-53 | runs R1 at load, then R0 once the page shows `data-status="now"` | wait up to 8 s on `#/rdLab`, recording every attribute change of `svg.ws-drawing` | when `data-status` becomes `none`, `data-moving="true"` is set within 100 ms; 1.5 s later `data-moving` is absent | holdout |
| AC-54 | e2e stack (role `approver`) | open `#/rdLab` | a complementary region named "Ask ARP" holds one Orb with `data-orb="workspace"` and a text box named "Ask about R&D Lab"; on `#/transitionIntel` the box is named "Ask about Transition Intel" | holdout |
| AC-55 | unit test, `canAsk` false | render the workspace overview | no region named "Ask ARP" and no Orb | unit |
| AC-56 | e2e stack; the test holds `POST /api/agent/asks` open | on `#/rdLab` type `zzqx which themes` in "Ask about R&D Lab", press Enter | the hash starts `#/agent`, and a user turn with exactly the text `zzqx which themes` is visible | holdout |
| AC-57 | AC-56, the request still held | read the Orb on the Agent screen | it has `data-orb="agent"` and `data-orb-state="working"`; after the test fulfils the request with status 500, `data-orb-state` is `idle` within 2 s | holdout |
| AC-58 | e2e stack | open `#/agent` | one Orb with `data-orb="agent"` is inside the element with class `agent-head`, before the `h1`, and its box is 56 × 56 px (± 1) | holdout |
| AC-58b | e2e stack, no ask in flight | open `#/agent` | the Orb has `data-orb-state="idle"` | holdout |
| AC-58c | e2e stack, `#/agent`, Orb phase `idle` | move the pointer onto the Orb and click it | the text "Click to transform" is not on the page, and for 2 s after the click `data-orb-phase` stays `idle` | holdout |
| AC-80 | e2e stack | open `#/rdLab` at 390 × 844, and `#/transitionIntel` at 390 × 844 | `document.documentElement.scrollWidth` is at most 390 on both | holdout |
| AC-81 | runs R1, 1440 × 900 | open `#/rdLab`, compare with `workspace-desktop-running.png` | pixel title; the drawing in its box right of the title with the first box lit blue; the running panel glows blue and its first rail segment flows; the Ask ARP card is the right column with the Orb above the question box; no lines or particles travel into or out of the Orb | evaluator |
| AC-82 | runs R1 | open `#/designStrategy` | the flow has a rail of seven `data-seg` elements reading `now`, then six `idle` | holdout |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-83 | e2e stack | open landing | the `h1` reads "Company research and stewardship at scale.", the line "Leveraging expert judgement through Agents." and the three promise titles "The LLM plans, code computes", "Every citation re-verified", "Nothing flagged ships" are visible | holdout |
| AC-84 | e2e stack | open landing, press the link "Open ARP" | the hash is `#/home` within 1 s | holdout |
| AC-85 | runs R1 | open `#/home` | the R&D Lab card's accessible name is "R&D Lab. Build a thematic portfolio: running; Research a theme: no activity yet; Research a strategy: no activity yet; Research a signal: no activity yet" | holdout |
| AC-86 | e2e stack | open `#/home` | the Cockpit entry (link named "Cockpit, StewardIQ") is present below the five cards | holdout |
| AC-87 | runs R1 (the process is unfolded) | open `#/rdLab` | in the section labelled "Build a thematic portfolio" the `.hub-step-title` texts read, in order, Spot, Define, Match, Review, Score, Construct, Report, and pressing `#step-thematic-0` sets its `aria-expanded` to `true` | holdout |
| AC-93 | runs R0, waiting W0, `localStorage["arp.orb"] = "still"` | open `#/rdLab` | no visible element has a computed `color`, `background-color` or `border-top-color` of `rgb(224, 178, 90)` (nothing waits, so no amber) | holdout |
| AC-88 | e2e stack | open `#/stewardiq` | every `.hub-process-state` holds one 8 × 8 px status square and a status word | holdout |
| AC-89 | e2e stack | open each of landing, `#/home`, `#/rdLab` | no visible text contains the whole word "product" or "products" (case-insensitive) | holdout |
| AC-90 | e2e stack | open `#/home` | on `:root` the computed custom property `--paper` reads `#f5f2ea` (the evidence paper stays light) | holdout |
| AC-91 | the frontend suite after each slice | `cd frontend && npm run lint && npx tsc -b && npm test` | exits 0 | unit |
| AC-92 | e2e stack, 1440 × 900, a thread with more turns than fit the screen | open it on `#/agent` and scroll the stream | the composer stays at the bottom of the screen while the turns scroll inside the stream region; the Orb in the head does not push the composer out of view | evaluator |

The factory cannot check frame rate on a real GPU: its browsers render in software. After slice 1 merges, the
owner opens the landing page on his laptop once; if the Orb stutters or turns into a still there, that is a bug
report against the quality rule's numbers.

## Slices

Each PR puts `Spec: expressive-ui-orb` and its `Rows:` line in its description, lists every test it changes, and
is `risk:normal`. They go in this order, one after the other.

| Slice | PR contents | Rows |
|---|---|---|
| 1 | Black tokens, light theme and theme switch removed, pixel font, `Orb.tsx`, `orb/orbScene.ts`, `lib/orbMotion.ts`, the still, `three` dependency, landing page, tab title, `DESIGN.md` amendment | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-20, AC-21, AC-28, AC-30, AC-31, AC-61, AC-64, AC-65, AC-66, AC-67, AC-68, AC-69, AC-70, AC-71, AC-72, AC-83, AC-84, AC-90, AC-91 |
| 2 | Start page hero (Orb, caption, pixel greeting, lead), card grid, rails, running detail, drawings with highlight and one-time move | AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-26, AC-27, AC-29, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-59, AC-62, AC-64, AC-65, AC-73, AC-74, AC-75, AC-76, AC-77, AC-78, AC-79, AC-85, AC-86, AC-91 |
| 3 | Workspace overview (header, figure box, panels, step rails, counts, Ask ARP card), Orb on the Agent screen | AC-22, AC-23, AC-24, AC-25, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-58, AC-58b, AC-58c, AC-60, AC-63, AC-64, AC-65, AC-80, AC-81, AC-82, AC-87, AC-88, AC-89, AC-92, AC-93, AC-91 |

Rows that open several pages (AC-22 to AC-25, AC-47, AC-60, AC-63, AC-89) belong to slice 3, the first slice in which
all of those pages carry the Orb; slices 1 and 2 must already behave that way on the pages they build.

Slice 3 touches files the agent-panel feature is still changing: `frontend/src/pages/Agent.tsx` (one mount
element in `.agent-head` and the `working` flag), `frontend/src/App.tsx` (passing `canAsk` and the ask handler
to the workspace overview) and `frontend/src/index.css`. It builds on merged `main`, merges `origin/main` in
before the PR opens, keeps the Orb in `Orb.tsx`, and leaves the chat layout as it is. Its other files:
`frontend/src/pages/ProcessHub.tsx`, `frontend/src/lib/workspaceCard.ts`, `frontend/src/components/WorkspaceDrawing.tsx`,
`frontend/src/pages/ArgusStart.tsx` (the `h1`'s font only).

## Defaults decided without the owner

- Marks outside the Orb's canvas (the landing caption's square) are brand orange; the phase label's square
  follows the Orb's current colour.
- "Open ARP" navigates at once; the mock's farewell animation is dropped.
- The top bar keeps today's ARP lockup and layout; the mock's "Ask ARP" button is not brought back.
- Start cards keep their names as today ("Transition Intelligence Platform").
- An "agent working" in the hero sentence is a run whose status is `running` or `pending`.
- The font is copied into the repo instead of adding the `geist` package, which requires `next`.
- `three` is pinned to one exact version.
- The Orb's quality level can be pinned through `localStorage["arp.orb"]`; there is no setting for it in the UI.
- The Agent screen's Orb is 56 px, always at quality `low`, and not clickable.
- The drawing is shown on phones inside a workspace (it was hidden there).
- After a change that alters behaviour the wiki needs an update: `openwiki/` pages on the frontend's theme, the
  landing page and the start page; the weekly `/context-refresh` regenerates them.

## Later (own specs)

- The start page activity list (D4's alternative).
- A live summary in the Ask ARP card and an Orb that follows the agent's output; both need a streaming endpoint.
- A setting in the user menu to turn the Orb's motion off.
