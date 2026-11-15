# Arctic foundation

## Intent

First of three PRs that bring the app in line with `DESIGN.md` ("The Annotated Report", merged in
#453). This one switches the colour tokens to the Arctic palette in both themes, lifts cards off the
page, makes rating badges pastel, and puts the pixel "ARP" lockup in the sidebar. The owner chose this
split: typography (serif titles and figures) and the signature elements follow as their own PRs.

## Goals

- **Palette:** the token blocks in `frontend/src/index.css` (`:root`, the `prefers-color-scheme: dark`
  block, and `:root[data-theme="dark"]`) take the Arctic values in the table under Decided. Every
  screen changes colour through the tokens alone.
- **Lifted cards:** `.card` and `.stat-tile` take `box-shadow: var(--shadow-card)`, with the values
  from DESIGN.md's Shadow Vocabulary.
- **Pastel rating badges:** `.badge-high`, `.badge-mid`, `.badge-low` and `.badge-neutral` become a
  16% tint of their status colour, with a label mixed 62% status / 38% `--text`, a 1px border at a
  32% tint, and 2px corners.
- **Sidebar lockup:** the sidebar brand shows the "ARP" lockup from `docs/brand/arp-lockup.svg` at 32px
  high instead of the mark plus the text "ARP". The mobile top bar keeps the mark alone. Both colour
  the apex with `--brand-apex`.

## Non-goals

- Serif typography (PR 2) and the signature elements: square dots, needs-you shape, evidence paper
  (PR 3). The lineage trail needs backend data and is not planned yet.
- Any change to amber (`--hi`, `--hi-ink`, `--await`, `--await-edge`, `--on-hi` in light), status
  colours (`--high`, `--mid`, `--low`, `--neutral`), chart slots or radii.
- The landing page, which already uses these tokens.

## Anti-goals

- Text or controls fall below DESIGN.md's contrast floors in either theme.
- A component gets its own colour literal instead of a token.
- Amber shows up anywhere it does not today.

## Approaches

1. **Tokens plus three rules (chosen).** Change only the token values, add `--shadow-card`, rewrite the
   four badge rules, and swap the sidebar SVG. Every screen follows the tokens.
2. Per-component restyle. More control, but hundreds of rules and the same visual result. Rejected.

## Decided

**Token values.** Tokens not listed keep their current values.

| Token | Light (`:root`) | Dark (both blocks) |
|---|---|---|
| `--bg` | `#ffffff` | `#06141d` |
| `--panel` | `#ffffff` | `#0b1d29` |
| `--panel-border` | `#d9e8f2` | `#1d3a4d` |
| `--field-border` | `#6f8a9c` | `#5f8399` |
| `--well` | `#eef6fb` | `#10293a` |
| `--sidebar-bg` | `#f1f7fc` | `#081822` |
| `--text` | `#082f49` | `#e2f1fa` |
| `--muted` | `#3d5a6e` | `#94b6c9` |
| `--accent` | `#0a4a8f` | `#38bdf8` |
| `--accent-ink` | `#08396f` | `#7dd3fc` |
| `--accent-tint` | `rgb(10 74 143 / 0.06)` | `rgb(56 189 248 / 0.09)` |
| `--on-accent` | `#ffffff` | `#06141d` |
| `--on-hi` | (unchanged `#ffffff`) | `#06141d` |
| `--run` | `#0284c7` | `#7dd3fc` |
| `--shadow-card` (new) | `0 1px 2px rgb(16 24 40 / 0.07), 0 6px 18px rgb(16 24 40 / 0.09)` | `0 1px 2px rgb(16 24 40 / 0.44), 0 6px 18px rgb(16 24 40 / 0.56)` |

**Badge rule.** One shared rule plus four selectors that set `--st`:
`.badge { --st: var(--neutral); background: color-mix(in srgb, var(--st) 16%, var(--panel)); color: color-mix(in oklch, var(--st) 62%, var(--text)); border: 1px solid color-mix(in srgb, var(--st) 32%, var(--panel)); border-radius: 2px; }`
and `.badge-high { --st: var(--high); }` (and the same for mid, low, neutral). The existing `.badge`
padding, size and weight stay.

**Sidebar:**
- A new `ArpLockup` component in `App.tsx` uses the paths of `arp-lockup.svg`, `role="img"`,
  `aria-label="ARP"`, ink in `currentColor` and the apex in `var(--brand-apex)`.
- `.app-sidebar-mark` becomes `height: 32px; width: auto; color: var(--text)`.
- The `app-sidebar-wordmark` span and its CSS rule go.
- `ArpMark`'s apex changes from `var(--hi)` to `var(--brand-apex)`.

## Supersedes

From `2026-11-08-night-desk-colours`:
- AC-1, AC-2, AC-3 (exact token values): restated as AC-1 to AC-3 below.
- AC-14 (untouched tokens): its keep-list loses `--accent-ink` and `--accent-tint`, which this spec
  changes.

In `frontend/tests/nightDeskTokens.test.ts`:
- `ac1_light_tokens`, `ac2_dark_switch_tokens` and `ac3_dark_media_tokens` are rewritten to the new
  values.
- `ac14_untouched_tokens` drops the two tokens from its keep-list.
- `ac13_amber_usage_unchanged` drops the logo-rect pattern from its allow-list, since no `--hi` logo
  rect remains.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `frontend/src/index.css` | `:root` is read | Every light value in the Decided table is present exactly | unit |
| AC-2 | The same | `:root[data-theme="dark"]` is read | Every dark value in the Decided table is present exactly | unit |
| AC-3 | The same | The `prefers-color-scheme: dark` block is read | Every dark value in the Decided table is present exactly | unit |
| AC-4 | All three token blocks | Contrast is computed (the existing `ac6_text_contrast` and `ac6b_fill_contrast` method) | `--text`, `--muted` and `--hi-ink` reach 4.5:1 on `--bg`, `--panel` and `--well`; `--on-accent` on `--accent`, `--on-hi` on `--hi` and `--hi-ink` on `--await` reach 4.5:1 | unit |
| AC-5 | The same | Contrast is computed | `--field-border` reaches 3:1 on `--panel` and on `--bg` | unit |
| AC-6 | `index.css` | Read | The `.card` rule and the `.stat-tile` rule each contain `box-shadow: var(--shadow-card)` | unit |
| AC-7 | `index.css` | Read | The `.badge` rule contains `background: color-mix(in srgb, var(--st) 16%, var(--panel))`, `color: color-mix(in oklch, var(--st) 62%, var(--text))`, `border: 1px solid color-mix(in srgb, var(--st) 32%, var(--panel))` and `border-radius: 2px` | unit |
| AC-8 | `index.css` | Read | `.badge-high`, `.badge-mid`, `.badge-low` and `.badge-neutral` each set only `--st` to `var(--high)`, `var(--mid)`, `var(--low)` and `var(--neutral)` respectively | unit |
| AC-9 | The running app, light and dark | A screen with a High, a Mid and a Low badge is open (e.g. the extraction review list) | Each badge's label reaches 4.5:1 against its own computed background | evaluator |
| AC-10 | The running app, any width ≥ 1024px | The start page is open | `.app-sidebar-brand` contains an `svg[role=img][aria-label=ARP]` of rendered height 32px, and its innerText is empty | evaluator |
| AC-11 | `App.tsx` | Read | It contains `var(--brand-apex)` at least twice (lockup and mark) and no `fill="var(--hi)"` | unit |
| AC-12 | The running app, light | The start page is open | The page background (`body`) is `rgb(255, 255, 255)` and a `.card` has a non-`none` computed `box-shadow` | evaluator |
| AC-13 | The running app, dark (`data-theme="dark"`) | The start page is open | The page background is `rgb(6, 20, 29)` and the active nav item's background is `rgb(56, 189, 248)` | evaluator |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-14 | `index.css` against `main` | The keep-list tokens (`--mid`, `--neutral`, `--text-*`, `--s-*`, `--shadow-md`, `--shadow-lg`, `--ease`, `--dur`) are compared | They are identical | unit |
| AC-15 | `index.css` | Read | The amber tokens (`--hi`, `--hi-ink`, `--await`, `--await-edge`), `--high`, `--low`, `--cat-1..4` and the radii keep their current values in all three blocks | unit |
| AC-16 | `frontend/tests/` | `npm test` runs | Every test passes; only the four tests named under Supersedes changed | unit |
| AC-17 | The landing page | The tests in `landing.test.ts` run | They pass unchanged | unit |
