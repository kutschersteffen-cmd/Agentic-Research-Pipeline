# UI polish 2: the owner's picks from the Linear study

## Intent

The owner asked to take more style ideas from a website they like (linear.app/ai). Fifteen ideas were measured from that page
and shown as before/after screenshots of the real ARP (the "Linear ideas: before and after" page). The owner picked twelve. They
make the app calmer and easier to scan: a clearer text hierarchy, lighter headings, quieter dark-mode lines, one tile strip,
filter chips, and phone tables that read as cards. We borrow ideas, never Linear's brand, copy, imagery or colours.

Not picked, so not here: L11 (gating motion behind `prefers-reduced-motion: no-preference`), L14 (landing section rhythm) and L15
(framed product shot on the landing page).

## Decisions the owner made

- **L1 strength:** `--text-2` mixes 80% `--text` with 20% `--muted`, as in the mockup.
- **L13:** the top bar is 80% opaque with a 20px blur, on desktop only.
- **L9 reach:** every table that stacks on a phone (`table.stack-on-phone`) becomes cards. The compact Argus layout is the one
  shown in the mockup.
- **Rollout:** two PRs.
  - **PR A, type and surfaces:** L1, L2, L3, L4, L6, L10, L12 and L13.
  - **PR B, layout and components:** L5, L7, L8 and L9.

## Approaches

1. **Tokens and CSS first, with a component change only where markup must change (chosen).** Most ideas are new tokens plus
   rules in `index.css`. Only L8 (a real "All" control) and L9 (a status attribute for the dot colour) touch TSX.
2. **A per-page restyle.** This would give finer control, but it is twelve times the diff, and it drifts from the shared tokens.
3. **Ship the mockup overlays as they are.** This is quickest, but the overlays use mockup-only DOM (the fake "All" chip, statuses
   copied from cell text in the browser) and `!important` overrides.

## The changes

### PR A

- **L1 Secondary text tier.**
  - New token in `:root`: `--text-2: color-mix(in oklch, var(--text) 80%, var(--muted))`. It follows both themes because it is
    built from theme tokens.
  - It applies to:
    - the page intro, meaning a `.help-text` or `.muted` paragraph that directly follows a page's `h1`;
    - each process's description on a workspace page (`.hub-process .help-text`);
    - start-page card purposes (`.hub-card-purpose`).
  - Meta lines and captions keep `--muted`.
- **L2 Size-banded tracking.**
  - Tokens: `--track-display: -0.025em`, `--track-title: -0.015em` and `--track-body: -0.008em`.
  - Where each applies:
    - body text uses `--track-body`;
    - `.page h1` and the start page's hero `h1` use `--track-display`;
    - `.card h2`, `.hub-card-name` and `.section-heading h2` use `--track-title`.
  - `kbd` and `code` get `letter-spacing: normal`, so they do not inherit the body's tracking. Mono labels that set their own
    tracking keep it.
- **L3 Medium-weight headings.** Headings whose computed size is 20px or more use weight 500 instead of 600: `.page h1`, the
  start hero `h1`, `.hub-card-name` and `.card h2`. Smaller headings stay at 600.
- **L4 Lead paragraph.**
  - Above 760px, the page intro (as defined in L1) is `1.0625rem` (17px) with line-height 1.5, colour `--text-2`, `max-width: 62ch`
    and `text-wrap: pretty`.
  - At 760px and below it goes back to the body size.
  - The dashed "re-entered by hand" key inside it never breaks at its hyphen (`white-space: nowrap`).
  - The workspace-page intros use this lead; Argus's intro sits inside `.argus-head`, so it keeps today's style.
- **L6 Translucent dark hairlines.**
  - In dark mode only (both the `prefers-color-scheme` block and `[data-theme="dark"]`), `--panel-border` becomes
    `rgb(232 235 240 / 0.12)`.
  - `--field-border` (form controls) stays solid, for WCAG 1.4.11.
  - Light mode is unchanged.
- **L10 Motion tokens.**
  - New tokens: `--dur-fast: 100ms`, `--dur-slow: 240ms` and `--ease-out: cubic-bezier(0.25, 0.46, 0.45, 0.94)`. `--dur` (140ms)
    and `--ease` stay.
  - Uses:
    - The shared hover transition on buttons, tabs and clickable rows (the `:where(button, .nav-tab, .clickable-row, …)` rule)
      uses `--dur-fast`.
    - `.progress-bar-fill` uses `--dur-slow` with `--ease-out` instead of `0.4s cubic-bezier(0.16, 1, 0.3, 1)`.
    - The flow-node transition uses `--dur` instead of the hard-coded `0.15s`.
    - `.hub-step-go` uses `--dur-fast` with `--ease-out` instead of the hard-coded `0.15s`.
  - The spinner and pulse loops keep their own timings.
- **L12 Text wrapping and dark smoothing.**
  - `:where(h1, h2, h3, h4) { text-wrap: balance }`.
  - `:where(p, li, dd, figcaption) { text-wrap: pretty }`.
  - In dark mode only, `body` gets `-webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale`.
- **L13 Translucent top bar.**
  - Above 760px, `.start-topbar` has `background: color-mix(in srgb, var(--bg) 80%, transparent)` and
    `backdrop-filter: blur(20px)` (with the `-webkit-` prefix).
  - At 760px and below the bar keeps its opaque `--bg`. That bar scrolls away with the page.
- **DESIGN.md:** the colour section names `--text-2` and where it is used. The type section names the three tracking tokens and
  the 500 weight for headings of 20px and up. A motion line names `--dur-fast`, `--dur-slow` and `--ease-out`.

### PR B

- **L5 Two-column page head.**
  - On the workspace overview pages that `ProcessHub` renders (StewardIQ, Transition Intel, R&D Lab, Data Hub), at 1100px and
    up, the `h1` and its intro share one row: the title in the left half, the intro in the right half, bottoms aligned.
  - Below 1100px they stack as today.
  - Other pages (Review Queue, Run History, the start page, Argus) keep the stacked head.
- **L7 Tile strip.**
  - The five Argus step tiles become one strip: no gap between tiles, and adjacent tiles share one 1px border. The strip's outer
    corners use `--r-lg` and its inner corners are square.
  - At 640px and below the tiles stack in one column, sharing their horizontal borders, with the outer corners at the top and
    bottom.
  - A waiting, failed, hovered or pressed tile draws its coloured border above its neighbours', so the whole edge shows.
- **L8 Filter chips.**
  - On `#/argus`, the "Only mine" checkbox becomes a group of two chips, "All" and "Only mine". Each is a `button` with
    `aria-pressed`, inside a `role="group"` named "Show runs".
  - Exactly one chip is pressed, and "All" is pressed by default. "Only mine" filters exactly as the checkbox did.
  - When nobody is signed in, "Only mine" is disabled, as the checkbox was.
  - Chips are pills (`--r-pill`), 32px tall above 1024px and 44px tall at 1024px and below. The pressed chip has an
    `--accent-tint` background and a `--text` label; the other has a `--muted` label.
- **L9 Phone cards.**
  - **Every stacked table.** At 560px and below (the breakpoint where `stack-on-phone` tables stack today), each row of a
    `table.stack-on-phone` is a card: 1px `--panel-border`, `--r-md` corners, a `--panel` background, `--s-3` padding, and
    `--s-2` between cards. The cells keep their labels as today.
  - **Status cells.** A cell labelled "Status" in such a card shows as a pill: `--r-pill`, a 1px `--panel-border`, `--text-xs`,
    and a 6px square dot before the word. The dot is `--muted` unless the cell has a `data-status`.
  - **The Argus runs table** (`#/argus`) uses the compact layout from the mockup:
    - the run name, bold, with its meta line under it;
    - the status pill at the top right;
    - "N companies · <step>" in `--muted` `--text-sm`;
    - the actions on a last row above a `--panel-border` hairline;
    - no field labels.
  - **Status dot colour.** `ArgusStart` sets `data-status` on its status cell:
    - `running` uses `--run`;
    - `needs-you` uses `--hi`;
    - `failed` uses `--low`;
    - `finished` uses `--text`;
    - `stopped` uses `--muted`;
    - `draft` is hollow (an inset 1px `--muted` ring).
  - Above 560px every table is unchanged.
- **DESIGN.md:** new **Tile strip**, **Filter chips** and **Phone tables** entries. The last says that at 560px and below a stacked
  table's rows become cards.

## Non-goals

- L11, L14 and L15.
- Filter chips anywhere other than `#/argus`.
- Any change to colour tokens other than adding `--text-2` and the dark `--panel-border`. No font change.
- Changing `prefers-reduced-motion` handling. The existing `reduce` overrides stay.

## Constraints

- Amber only for "waiting on a person". Running is `--run`, failed is `--low`.
- Status dots and squares stay square: radius 0.
- Body and intro text keep at least 4.5:1 contrast on `--bg` in both themes.
- Touch targets stay at least 44px at 1024px and below.
- No new `!important`. The mockup used it only to override the overlay. The existing one in the `stack-on-phone` rule may stay.

## Left to the builder

- The exact selectors, as long as the rows below hold.
- Whether the Argus compact card uses grid areas or the mockup's floats.
- Which existing tests read the values this changes. Examples: the `.page h1` weight, the dark `--panel-border` hex, the
  "Only mine" checkbox in e2e (`#argus-only-mine`), and the hard-coded `0.15s`. Each is listed in the PR as changed, with the
  reason.

## Supersedes

- Any test that asserts weight 600 on `.page h1`, `.hub-card-name` or `.card h2`.
- Any test that asserts `#2c3644` as the dark `--panel-border`.
- Any test that selects the "Only mine" checkbox (`#argus-only-mine`, `get_by_label("Only mine")`).

The builder lists each one in the PR.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `index.css` | Read | `:root` defines `--text-2: color-mix(in oklch, var(--text) 80%, var(--muted))` | unit |
| AC-2 | `#/stewardiq` at 1440×900, dark and then light theme | The page intro (the paragraph right after the `h1`) is measured | Its computed colour equals the computed colour of an element styled `color: var(--text-2)`, differs from computed `--muted`, and has a contrast of at least 4.5:1 on computed `--bg` | evaluator |
| AC-2b | `#/home` at 1440×900, dark | A start-page card's purpose line is measured | Its computed colour equals the computed colour of an element styled `color: var(--text-2)` | evaluator |
| AC-2c | `#/stewardiq` at 1440×900, dark | The first `.hub-process .help-text` is measured | Its computed colour equals the same `--text-2` probe | evaluator |
| AC-3 | `#/stewardiq` at 1440×900 | The page intro is measured | Computed font-size `17px`, line-height `25.5px`, `text-wrap` `pretty`, and max-width equal to 62 times the width of a "0" in that font (±1px) | evaluator |
| AC-3b | `#/stewardiq` at 390×844 | The page intro is measured | Its computed font-size equals `body`'s computed font-size, and the element containing "re-entered by hand" has a single line box (its height equals its line-height ±1px) | evaluator |
| AC-4 | `index.css` | Read | `:root` defines `--track-display: -0.025em`, `--track-title: -0.015em` and `--track-body: -0.008em` | unit |
| AC-4b | `#/stewardiq` at 1440×900 | `body`, the `h1` and a `.section-heading h2` are measured | `body` letter-spacing is `-0.12px` (at 15px). The `h1`'s letter-spacing is −0.025 × its computed font-size (±0.05px), and the `h2`'s is −0.015 × its font-size (±0.05px) | evaluator |
| AC-4c | `#/stewardiq` at 1440×900 | The top bar's `kbd` is measured | Its computed letter-spacing is `normal` | evaluator |
| AC-5 | `#/stewardiq` and `#/home` at 1440×900 | The page `h1`, the start hero `h1` and a `.hub-card-name` are measured | Each has computed font-size ≥ 20px and font-weight `500` | evaluator |
| AC-5b | `#/stewardiq` at 1440×900 | A process `.section-heading h2` (under 20px) is measured | Computed font-weight `600` | evaluator |
| AC-6 | `#/argus` at 1440×900, dark theme | The `.card` (Waiting for you) is measured, then Ctrl+K is pressed and the `.palette-input` is measured | The card's computed border-color is `rgba(232, 235, 240, 0.12)`. The input's border-color equals the computed colour of a `var(--field-border)` probe and is opaque (alpha 1) | evaluator |
| AC-6b | The same, light theme | The card is measured | Its computed border-color is `rgb(216, 222, 231)` (`#d8dee7`, unchanged) | evaluator |
| AC-7 | `index.css` | Read | `:root` defines `--dur-fast: 100ms`, `--dur-slow: 240ms` and `--ease-out: cubic-bezier(0.25, 0.46, 0.45, 0.94)`. No `transition` declaration contains a literal `0.15s` or `0.4s`. `.progress-bar-fill`'s transition uses `var(--dur-slow) var(--ease-out)` | unit |
| AC-7b | `#/stewardiq` at 1440×900 | A top-bar `button` is measured | Its computed `transition-duration` includes `0.1s` | evaluator |
| AC-8 | `index.css` | Read | It has `:where(h1, h2, h3, h4)` with `text-wrap: balance` and `:where(p, li, dd, figcaption)` with `text-wrap: pretty`. `-webkit-font-smoothing: antialiased` appears only inside the dark-theme blocks | unit |
| AC-9 | `#/stewardiq` at 1440×900, dark and then light theme | `.start-topbar` is measured | Computed `backdrop-filter` is `blur(20px)`, and its background colour (in `rgb()` or `color(srgb …)` form) has alpha 0.8 (±0.01) with the RGB of `--bg` | evaluator |
| AC-9b | `#/stewardiq` at 390×844 | `.start-topbar` is measured | Computed `backdrop-filter` is `none`, and the background alpha is 1 | evaluator |
| AC-9c | `#/stewardiq` at 1440×900 with `/api/waiting` stubbed to `{"review": 100, "decisions": 20, "ballots": 3, "total": 123}` | The Review Queue badge is measured | Its background is opaque (alpha 1) and its text-to-background contrast is at least 4.5:1 (must not change: the badge stays solid on the translucent bar) | evaluator |
| AC-10 | `DESIGN.md` | Read | It contains `--text-2`, `--track-display`, `--dur-fast`, `--dur-slow` and `--ease-out` | unit |
| AC-11 | `#/stewardiq` and `#/rdLab` at 1440×900 | The `h1` and the intro are measured | The intro's left edge is ≥ the `h1`'s right edge, and their bottom edges differ by ≤ 4px | evaluator |
| AC-11b | `#/stewardiq` at 1099×900, and `#/review` at 1440×900 | The `h1` and the paragraph after it are measured | The paragraph's top edge is ≥ the `h1`'s bottom edge (stacked) | evaluator |
| AC-12 | `#/argus` at 1440×900 | The five `.argus-tile`s are measured | They share one row. Each tile's left edge equals the previous tile's right edge minus 1px (±0.5px). The first tile's top-left and the last tile's top-right corner radius are `12px`; the inner corners are `0px` | evaluator |
| AC-12b | `#/argus` at 390×844 | The tiles are measured | They stack in one column. Each tile's top edge equals the previous tile's bottom edge minus 1px (±0.5px) | evaluator |
| AC-12c | `#/argus` at 1440×900 with `/api/runs` stubbed to add two `failed` extraction runs at step 4 (so step 4's tile has class `argus-tile-failed`) | That tile is measured | Its computed `z-index` is greater than an ordinary neighbouring tile's, and its border-color equals computed `--low` | evaluator |
| AC-13 | `#/argus` at 1440×900, signed in | The page loads | A group named "Show runs" holds two buttons, "All" (`aria-pressed="true"`) and "Only mine" (`aria-pressed="false"`), each 32px tall with radius ≥ 16px. No checkbox labelled "Only mine" exists | evaluator |
| AC-13b | The same | "Only mine" is clicked | "Only mine" has `aria-pressed="true"` and "All" has `"false"`. The pressed chip's background equals the computed colour of a `var(--accent-tint)` probe | evaluator |
| AC-13e | `#/argus` at 1440×900 with `/api/runs` stubbed to three extraction runs, two started by `dev` and one by `other` | "Only mine" is clicked, then "All" | After "Only mine" the table lists exactly the two `dev` runs; after "All" it lists all three | evaluator |
| AC-13c | `#/argus` at 1024×800 | The chips are measured | Each is ≥ 44px tall | evaluator |
| AC-13d | `#/argus` with `/api/me` stubbed to 401 | The page loads | "Only mine" is disabled, and "All" is pressed | evaluator |
| AC-14 | `#/argus` at 390×844 with `/api/runs` stubbed to three extraction runs | A runs-table row is measured | It has a 1px solid border of computed `--panel-border`, an 8px radius and the computed `--panel` background, and the next row starts ≥ 8px below it | evaluator |
| AC-14b | `#/voting` at 390×844 with `/api/runs` stubbed to one `proxy_voting` run | A row of its runs table is measured | Same frame as AC-14, and its cells still show their `data-label` text | evaluator |
| AC-15 | `#/argus` at 390×844 with the AC-14 stub | A run card is read | The first line is the run name, and the status pill's right edge is within the card's top-right quarter. A line matches `^\d+ compan(y|ies) · \d \w+`. The actions sit below a hairline. No visible text reads "Run", "Companies", "Step" or "Status" | evaluator |
| AC-15b | `#/argus` at 390×844 with `/api/runs`, `/api/argus/flows` and `/api/review/items` stubbed so the table has one row in each status: Draft, Running, Needs you, Stopped, Failed and Finished | The status pills' dots are measured | Each dot is 6×6px with border-radius 0. Compared with probes of each token: "Needs you" → `--hi`, "Running" → `--run`, "Failed" → `--low`, "Finished" → `--text`, "Stopped" → `--muted`; "Draft" has a transparent background with an inset ring | evaluator |
| AC-16 | `#/argus` at 1440×900 | The runs table is read | Its `thead` is visible and rows have no card border (desktop unchanged) | evaluator |
| AC-17 | `DESIGN.md` | Read | It has **Tile strip**, **Filter chips** and **Phone tables** entries, and the **Phone tables** entry contains "card" | unit |
| AC-18 | PR B's diff | `git diff origin/main -- frontend/src/index.css` is read | No added line contains `!important` | unit |

Must not change:
- Amber appears only for waiting. AC-15b checks the one new place colour is used.
- The Review Queue badge stays solid and readable on the translucent bar (AC-9c).
- Touch targets are at least 44px at 1024px and below (AC-13c).
- The top bar keeps its two phone rows (PR #484 AC-16).
- Desktop tables (AC-16).
