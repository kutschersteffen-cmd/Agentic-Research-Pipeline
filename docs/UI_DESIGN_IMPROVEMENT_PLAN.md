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
| Stylesheet drift | Component rules, page rules and chart rules share one flat 634-line file, with nothing to stop a page rule outranking a component one; `.chart-legend`, `.chart-legend-item` and `.chart-legend-swatch` are each declared twice, 80 lines apart, so a legend's effective style is the merge of two rules no reader sees together |
| Design tokens leak | 47 inline `style={{…}}` objects across 19 components hold layout and color outside the token layer |
| No button hierarchy | The bare `button` element selector paints **every** button indigo with a magic `margin-top: 12px`; a destructive delete and a "Refresh" link look equally important |
| Ad-hoc state rendering | 56 hand-written `error-text` sites and a dozen different `"Loading…"` / `"Searching…"` / `"Rendering preview…"` strings |
| Navigation reuse | In-page tabs reuse the sidebar's `.nav-tab` class (`BackgroundAgents.tsx:30`, `IndexBuilder.tsx:274`, +4), so a selected sub-tab renders as a filled sidebar pill in the middle of the content column |
| Accessibility floor | `focus-visible` appears 0 times; `aria-current` 0 times; 1 of 140 `<label>`s uses `htmlFor`; both modals are hand-rolled `div` overlays with no focus trap, no Escape and no focus restoration |
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

| Phase | Scope | Effort | Risk | Visible change | Status |
| --- | --- | --- | --- | --- | --- |
| 0 | Split `index.css` into layers, extract tokens, merge the duplicated legend rules | 0.5 d | Low | Values snap to the scale (1–2px in places) | **Landed** |
| 1 | `ui/` primitives; retire the global `button` selector; migrate `Button`, `Field`, `StateBlock` app-wide | 1.5 d | Medium | Button hierarchy appears; forms become labelled | **Landed** |
| 2 | Routing, command palette, responsive sidebar, a11y baseline | 1.5 d | Medium | Deep links and back button work | **Landed** |
| 3 | Apply the three templates, starting with Extraction, Monitoring, Run History, Search | 2 d | Medium | The app reads as one product | **Landed** |
| 4 | `DataTable` upgrades, dark mode + palette re-validation | 1.5 d | Low | Density and mode choice | Next |
| 5 | Guardrails: stylelint scale enforcement, a CI grep for raw hex / inline `style={{` in `.tsx`, an axe pass on the five busiest pages | 0.5 d | Low | None — keeps the system from drifting | |

Phases 0 and 1 are worth doing even if nothing else is: they are where the
twenty-one-separate-tools feeling actually comes from.

### What phases 0 and 1 actually changed

- `index.css` is now a 14-line manifest; the rules live in `src/styles/`
  (`tokens`, `reset`, `base`, `components`, `shell`, `charts`,
  `pages/*`, `utilities`) ordered by `@layer`.
- 15 font sizes became 7 scale steps, 9 radii became 5, and the spacing values
  snapped to a 4px grid. Some values therefore moved by 1–2px; nothing moved by
  more. Card radius (10 → 12px) and card padding (18/20 → 16/24px) are the
  largest single changes.
- `--muted` was darkened from `oklch(48%)` to `oklch(44%)` so secondary text
  clears 4.5:1 on `--panel` at the smallest sizes.
- 173 buttons now render through `<Button>` with an explicit variant; the 34 that
  remain are the sidebar/sub-tab and toggle affordances that Phase 2 replaces
  with `<Tabs>`. The bare `button` element selector no longer paints anything.
- 102 controls are wrapped in `<Field>`, which associates label and control; the
  labels that captioned a *group* of controls became `<span>`s, since a label
  pointing at nothing helps no one.
- 87 loading, empty and error states render through `<StateBlock>`. An empty
  state stays a quiet muted line unless it carries a title or an action, so the
  migration did not turn 29 "none yet" lines into 29 dashed boxes. The 8
  remaining `.error-text` uses are inline emphasis inside a sentence, list item
  or table cell — not failed actions.
- Verified with `npm run build`, `npm run lint` (one pre-existing warning), and a
  headless pass over 9 screens: no page errors, 13 of 13 form controls on the
  form-heavy screens carry an accessible name, and the focus ring resolves on the
  first tab stop.

### What phase 3 actually changed

- **Every page opens the same way.** `PageHeader` (title, purpose, an actions
  slot) is on all 21 pages; the two that had no description now say what they
  are for.
- **Workflow (Extraction).** A step rail — Describe → Review fields → Company
  universe → Run & review — replaces four hand-numbered `<h3>`s, and follows the
  mode (the financials path is two steps, not four). A step you have passed
  collapses to its one-line result ("3 fields", "84 companies") with an Edit
  control that re-opens it, so the step you are on is the one filling the
  screen. `RunProgress` sits in a sticky strip: a run takes minutes and its
  results run long, so progress no longer scrolls away above the table.
- **Explorer (Search, Run History).** One `FilterBar`: controls, then the active
  filters as removable chips, then a line saying what the list currently holds.
  Run History's filters live in the URL, so a filtered history is a link — which
  is what lets a dashboard tile point at the runs behind its number.
- **Dashboard (Monitoring).** `StatTile` puts the label above the figure, adds
  the window the figure is measured over ("most recent 25", "of 12 logged"), and
  links to the list it came from. A stat nobody can open is a dead end.
- **`Dialog`.** Both hand-rolled overlays are now one primitive on the native
  `<dialog>`: focus trapped inside, Escape closing, focus returned to whatever
  opened it, the page behind inert and not scrolling. The old `.modal-overlay`
  rules are gone.
- **Inline styles: 47 → 9**, and all nine are genuinely dynamic (a bar's width, a
  tooltip's offset, a data-driven fill). The static ones became a small closed
  set of utilities.
- Also fixed on the way past: `Search` reported failures with `className="error"`,
  a class that exists nowhere, so a failed search rendered as ordinary body text.
- Verified against the built app: 8 behaviour checks (tile → filtered history,
  chip clears its param, a filtered list is addressable, the rail and its mode,
  `PageHeader` on 8 sampled pages, search error state) and 10 for the dialog
  (modal, dimmed backdrop, scroll lock, focus trapped, background inert, Escape,
  focus restored, backdrop click, panel click). The dialog pass caught one
  defect: React unmounts the element before the cleanup runs, so the native
  focus restoration never fired — the dialog now restores focus itself.

**Two deliberate deviations from the plan above.** A workflow page's committing
action stays in its step rather than moving to the page header: each step has a
different one, so a header-mounted button would either duplicate it or separate
it from the field it acts on — the rail supplies the orientation the header
action was meant to give. And the explorer's right-hand detail drawer is not
built: the two pages migrated here have no expanded-row detail, and the pages
that do already use the split-review `SourcePanel`, which keeps list context the
same way. Both belong with the remaining explorer pages in a later pass.

### What phase 2 actually changed

- **Every view has an address.** `src/router.ts` is a ~90-line hash router
  (`#/<tab>[/<sub-tab>][?params]`) built on `useSyncExternalStore`, with no
  dependency and no change to `nginx.conf`. Sidebar items are real links, so
  middle-click and "copy link" work; the back button, a refresh and a pasted
  link all land where they should.
- **Handoffs travel in the URL.** "Send this universe to extraction", "open this
  run in the review queue" and "use this taxonomy" were parent state in
  `App.tsx`; they are now route params, so the result of a handoff is a link an
  analyst can keep or send to a colleague.
- **`⌘K` / `Ctrl-K` opens a command palette** over every destination in
  `src/nav.ts` — 21 pages and their 28 sub-tabs, one registry that the sidebar,
  the palette and each page's tab strip all read, so a view cannot be reachable
  from one and invisible to the others.
- **Sub-tabs became `<Tabs>`**: underline tabs with `role="tablist"`, arrow-key
  and Home/End movement, and the active tab in the URL. They no longer borrow
  the sidebar's filled pill, which read as a page's primary action sitting in
  the content column. The nine in-content buttons and two filter rows that had
  also borrowed `.nav-tab` became secondary buttons and segmented controls, so
  the class now belongs to the sidebar alone.
- **The sidebar has three states**: full, an icon rail between 900 and 1200px
  where the labels would truncate anyway, and an off-canvas drawer below 900px
  with a scrim. The collapse preference persists, and a `localStorage` that
  throws costs nothing but the preference.
- **Accessibility**: a skip link as the first tab stop, `aria-current="page"` on
  the active destination, keyboard-operable tabs, and a glyph on every status
  pill so run status is not carried by colour alone.
- **New in this phase, because deep links created the risk:** URL params are
  validated before a page sees them (an unknown `?kind=` used to index a lookup
  table and take the whole window down with it), and an error boundary around
  the routed view turns a page that throws into a message with a way out
  instead of a blank window.
- Verified headlessly against the built app: 11 behaviour checks (deep link to a
  page and to a sub-tab, back button, refresh, `aria-current`, palette jump,
  arrow-key tabbing, skip link, handoff params, unknown route, unknown param)
  all pass, and the three sidebar states plus the drawer were checked at 1440,
  1100 and 720px. That pass also caught two defects, both fixed: the blank-window
  crash above, and a scrim left covering the app when the window was widened with
  the drawer open.

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

1. `index.css` holds only `@layer`/`@import`; no selector is declared twice within a layer (a responsive override inside `@media` is not a duplicate). **Met.**
2. `grep -c 'style={{' src -r` is in single digits, all of them dynamic values (chart
   geometry, computed widths). **Met** — 47 at the start, 9 now, every one computed.
3. `font-size` outside `tokens.css` is zero; the same for `border-radius` and raw hex. **Met** (the one numeric radius left is a `0` corner in a segmented control).
4. Every destination is reachable by URL, and refreshing keeps the analyst where they were. **Met.**
5. An axe scan of Dashboard, Extraction, Review Queue, Search and Index Builder reports
   no serious or critical issues; each is fully operable by keyboard.
6. Adding a new page means composing `PageHeader + Tabs + Card + DataTable` — and a
   reviewer can tell at a glance if it did not. *Everything but `DataTable` exists;
   phase 4 builds it.*
