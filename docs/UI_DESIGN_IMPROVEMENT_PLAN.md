# UI Design Improvement Plan

A design proposal for the `frontend/` React app: what is wrong today, the system that
fixes it, and a phased route to get there without a rewrite.

## 1. Where the UI stands today

The visual *direction* is sound and does not need replacing. The light indigo-accented
shell, the Space Grotesk / IBM Plex Sans / Space Mono type trio, and the
validated chart palette in `frontend/src/lib/palette.ts` are a deliberate, coherent
choice, and the dataviz layer is the strongest part of the app.

What is missing is a **system**. Every screen was styled by hand in one 634-line global
stylesheet (`frontend/src/index.css`), so each new page invented values rather than
reusing them. The result reads as twenty-one separately designed tools sharing a
sidebar, not one product. The measurable symptoms:

| Symptom | Evidence |
| --- | --- |
| No type scale | 15 distinct `font-size` values (`0.68rem`, `0.74rem`, `0.76rem`, `0.78rem`, `0.8rem`, `0.82rem`, `0.85rem`, `0.88rem`, …) |
| No radius/spacing scale | 9 distinct `border-radius` values; paddings drawn from 2/3/4/6/8/9/10/12/14/18/22/24px |
| Stylesheet drift | 25 class selectors are declared **twice** in `index.css` (`.card`, `.data-table`, `.page`, `.chart-legend`, `.stat-tile`, …), so which rule wins depends on file order |
| Design tokens leak | 47 inline `style={{…}}` objects across 19 components hold layout and color outside the token layer |
| No button hierarchy | The bare `button` element selector paints **every** button indigo with a magic `margin-top: 12px`; a destructive delete and a "Refresh" link look equally important |
| Ad-hoc state rendering | 56 hand-written `error-text` sites and a dozen different `"Loading…"` / `"Searching…"` / `"Rendering preview…"` strings |
| Navigation reuse | In-page tabs reuse the sidebar's `.nav-tab` class (`BackgroundAgents.tsx:30`, `IndexBuilder.tsx:274`, +4), so a selected sub-tab renders as a filled sidebar pill in the middle of the content column |
| Accessibility floor | `focus-visible` appears 0 times; `aria-current` 0 times; 1 of 140 `<label>`s uses `htmlFor`; `window.confirm` is still the destructive-action dialog |
| No deep links | `App.tsx` drives 21 destinations from `useState`, so no URL, no back button, no refresh-safe state, nothing shareable |
| Light only | `color-scheme: light` is hard-coded although the chart ramps were already validated as mode-invariant |

Those are all one problem wearing ten hats: **there is no layer between the raw CSS and
the screens.** Everything below builds that layer.

## 2. Design principles for this app

1. **Evidence stays visible.** This is a research tool whose output is contestable
   numbers. Provenance (citations, source panel, confidence, "not disclosed" vs "zero")
   is never collapsed to save space.
2. **Density with air.** Analysts read tables of 200 rows. Default to compact rows and
   tabular numerals, but keep an 8px rhythm so density never becomes noise.
3. **One way to do each thing.** One button hierarchy, one tab pattern, one empty state,
   one error surface. A new page composes; it does not invent.
4. **Long-running work is first-class.** Runs take minutes. Progress, partial results,
   and failure are part of the layout, not an afterthought.
5. **The system is enforceable.** Every rule below is checkable by a linter or a CI
   script, otherwise it will drift again within two features.

## 3. The design

### 3.1 Token layer — `styles/tokens.css`

Replace the ad-hoc values with a closed set. Three scales, no exceptions.

```css
:root {
  /* Type — 6 steps replace 15 */
  --fs-50: 0.75rem;   /* 12px  micro labels, table meta */
  --fs-100: 0.8125rem;/* 13px  secondary text, chips */
  --fs-200: 0.875rem; /* 14px  body, table cells, inputs */
  --fs-300: 1rem;     /* 16px  card titles */
  --fs-400: 1.25rem;  /* 20px  section titles */
  --fs-500: 1.5rem;   /* 24px  page titles */
  --lh-tight: 1.25; --lh-body: 1.55;

  /* Space — 4px base, 7 steps replace 12 */
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px;
  --sp-5: 24px; --sp-6: 32px; --sp-7: 48px;

  /* Radius — 4 steps replace 9 */
  --r-sm: 6px; --r-md: 8px; --r-lg: 12px; --r-full: 999px;

  /* Elevation — only two, both neutral-tinted */
  --shadow-1: 0 1px 2px oklch(13% 0 0 / 0.06);
  --shadow-2: 0 8px 24px oklch(13% 0 0 / 0.12);

  /* Focus — one ring, used by every interactive element */
  --focus-ring: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent);
}
```

Semantic surface tokens (`--bg`, `--panel`, `--panel-border`, `--well`, `--text`,
`--muted`, `--accent`, `--high/--mid/--low`) keep their current names, so no component
has to change when dark mode lands.

**Dark mode** (Phase 4) redefines only the surface tokens:

```css
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* surface tokens re-pointed */ }
}
:root[data-theme="dark"] { /* same block, explicit opt-in */ }
```

`SEQUENTIAL_BLUE` is already mode-invariant. `CATEGORICAL` must be re-run through
`scripts/validate_palette.js` against the dark panel colour before dark mode ships —
if a slot fails the CVD or lightness gate, add a dark-surface variant rather than
shipping an unvalidated palette.

### 3.2 Stylesheet architecture — cascade layers

`index.css` becomes an import manifest only:

```css
@layer reset, tokens, base, components, pages, utilities;
@import "./styles/reset.css"      layer(reset);
@import "./styles/tokens.css"     layer(tokens);
@import "./styles/base.css"       layer(base);        /* element defaults */
@import "./styles/components.css" layer(components);  /* .btn, .card, .table … */
@import "./styles/pages/*.css"    layer(pages);       /* decision-studio, engagement … */
```

Layers make the duplicate-selector problem structurally impossible to repeat: a page
rule can never silently outrank a component rule, and the 25 double declarations get
resolved once, during the move.

### 3.3 Component primitives — `frontend/src/ui/`

Thirty components exist but no primitives, so each page re-solves the same problems.
Add eight, each a thin wrapper over the token layer — no new dependency.

| Primitive | Replaces | Contract |
| --- | --- | --- |
| `<Button>` | the global `button` selector | `variant: primary \| secondary \| ghost \| danger`, `size: sm \| md`, `loading`, `iconOnly` (requires `aria-label`). One primary per view. Never sets its own margin. |
| `<Field>` | 140 unlabelled `<label>`s | `useId()` pairs label ↔ control, renders hint and error text, sets `aria-describedby` / `aria-invalid` |
| `<PageHeader>` | bare `<h2>` on 21 pages | title, one-line purpose, breadcrumb for sub-pages, and a right-aligned primary-action slot |
| `<Tabs>` | `.sub-nav` reusing `.nav-tab` | underline tabs with `role="tablist"`, arrow-key roving focus, URL-synced. Visually distinct from sidebar nav. |
| `<DataTable>` | `.data-table` + `.table-wrap` | sticky header, right-aligned numeric columns with `font-variant-numeric: tabular-nums`, sort affordance, row-hover, density toggle, virtualized past 500 rows |
| `<StateBlock>` | 56 `error-text` sites + a dozen "Loading…" strings | `kind: loading \| empty \| error`; loading renders skeletons shaped like the content, empty gives a cause and a next action, error gives the message plus Retry |
| `<Dialog>` | `.modal-overlay` + `window.confirm` | native `<dialog>`: focus trap, Escape, restore focus, scroll lock |
| `<Toast>` | `setStatus("Uploading…")` strings | transient confirmations for background work, `aria-live="polite"` |

A page is then: `PageHeader` → optional `Tabs` → `Card`s of `Field`s → `Button` →
`StateBlock` or `DataTable`. Nothing bespoke.

### 3.4 Navigation at 21 destinations

The sidebar already groups tabs sensibly; the problem is scale and statelessness.

- **URL routing.** Move `App.tsx`'s `useState` to a route per destination
  (`/extraction`, `/portfolio-monitoring/pivot`, `/review?run=…`). Deep links,
  browser back, refresh-safe state, and shareable links to a specific run — the single
  highest-value change in this plan. Hash routing suffices and keeps `nginx.conf`
  untouched; `react-router` if nested routes are wanted.
- **`⌘K` command palette.** With 21 destinations plus sub-tabs, search beats scanning.
  Jump to a page, a recent run, or a company. ~120 lines, no dependency.
- **Sidebar states.** Full (≥1200px), icon-rail with tooltips (900–1200px), and a
  slide-over drawer below 900px. Persist the collapse in `localStorage`; `aria-current="page"`
  on the active item; a skip-to-content link as the first focusable element.
- **Cross-page handoffs** (`sendToExtraction`, `openReview`) become route params instead of
  parent state, which removes the prop-drilling in `App.tsx` and makes the handoff linkable.

### 3.5 Three page templates

Every screen is one of three shapes. Fixing the templates fixes all 21 pages.

**A. Workflow (Extraction, Theme Builder, Discovery, Index Builder, Report Builder).**
Today these are a vertical stack of cards where step 3's controls are visible and
clickable before step 1 is done. Give them an explicit spine: a step rail
(`Configure → Run → Review`) with each step's state, only the active step expanded,
completed steps collapsed to a one-line summary with an Edit affordance, and the
primary action fixed in the page header. `RunProgress` is promoted out of the page
body into a persistent run strip so progress stays visible while the analyst scrolls
results — and stays visible after navigating away, since long runs are the norm.

**B. Explorer (Search, Data Library, Taxonomy Library, Run History, Company Profiles).**
A consistent filter bar (filters as removable chips showing the active query),
`DataTable` below, detail in a right-hand drawer rather than an inline expanded row so
list context is never lost. The split-screen review pattern in `SourcePanel` is the
model here — it already does this well; generalize it.

**C. Dashboard (Monitoring, Engagement, Decision Studio KPIs).**
Fix the stat tile: value in tabular mono, label above, delta and its comparison window
below, and a click target into the filtered list behind the number. Cap at 4–6 tiles
per row; anything more is a table. Charts keep the existing dataviz rules.

### 3.6 Feedback and the run lifecycle

One state machine, rendered the same way everywhere:

`idle → submitting → running (n/N, elapsed) → partial → completed | failed | cancelled`

- Buttons own their pending state (`loading` prop) instead of pages toggling a `busy` flag
  that leaves the control looking clickable.
- Errors render in place with the failing action's context and a Retry — never a bare
  red paragraph at the bottom of a card, and never `window.confirm` for a destructive one.
- Skeletons shaped like the arriving content replace `"Loading…"` text; the layout does
  not jump when data lands.
- Toasts for background completions; inline for anything the user must act on.

### 3.7 Accessibility baseline (non-negotiable, checked in CI)

- One `:focus-visible` ring token on every interactive element, including nav and table rows.
- `htmlFor`/`id` on every control via `<Field>`; `aria-label` on every icon-only button.
- Status is never colour alone: `.status-pill` and `.badge` gain a shape or glyph, which
  also fixes the red/green pair for deuteranopia.
- Contrast: verify `--muted` (`oklch(48%)`) at `--fs-50` against `--panel`; darken to
  ~`oklch(44%)` if it misses 4.5:1.
- Modals: native `<dialog>`, focus trap, Escape, restored focus.
- Full keyboard path through every workflow, tab order matching visual order.

## 4. Phased delivery

Each phase ships independently and leaves the app working.

| Phase | Scope | Effort | Risk | Visible change |
| --- | --- | --- | --- | --- |
| 0 | Split `index.css` into layers, extract tokens, resolve the 25 duplicate selectors | 0.5 d | Low | None — pixel-identical by design |
| 1 | `ui/` primitives; retire the global `button` selector; migrate `Button`, `Field`, `StateBlock` app-wide | 1.5 d | Medium | Button hierarchy appears; forms become labelled |
| 2 | Routing, command palette, responsive sidebar, a11y baseline | 1.5 d | Medium | Deep links and back button work |
| 3 | Apply the three templates, starting with Extraction, Monitoring, Review Queue, Search, Index Builder | 2 d | Medium | The app reads as one product |
| 4 | `DataTable` upgrades, run strip, dark mode + palette re-validation | 1.5 d | Low | Density and mode choice |
| 5 | Guardrails: stylelint scale enforcement, a CI grep for raw hex / inline `style={{` in `.tsx`, an axe pass on the five busiest pages | 0.5 d | Low | None — keeps the system from drifting |

Phases 0 and 1 are worth doing even if nothing else is: they are where the
twenty-one-separate-tools feeling actually comes from.

## 5. Explicitly out of scope

- **No Tailwind / CSS-in-JS / component-library migration.** The app has two runtime
  dependencies (react, react-dom). The token layer gets the consistency without the
  bundle, the build change, or the rewrite.
- **No new visual identity.** Colour, type and the chart palette stay; this is about
  applying them consistently.
- **No chart redesign.** `lib/palette.ts` and the chart components already follow the
  validated rules. Dark mode is the only thing that touches them.
- **No backend change.** Everything here is `frontend/`.

## 6. Acceptance checks

The plan is done when:

1. `index.css` holds only `@layer`/`@import`; no selector is declared twice.
2. `grep -c 'style={{' src -r` is in single digits, all of them dynamic values (chart
   geometry, computed widths).
3. `font-size` outside `tokens.css` is zero; the same for `border-radius` and raw hex.
4. Every destination is reachable by URL, and refreshing keeps the analyst where they were.
5. An axe scan of Dashboard, Extraction, Review Queue, Search and Index Builder reports
   no serious or critical issues; each is fully operable by keyboard.
6. Adding a new page means composing `PageHeader + Tabs + Card + DataTable` — and a
   reviewer can tell at a glance if it did not.
