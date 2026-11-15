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
- **Lifted cards:** `.card`, `.stat-tile` and the start page's workspace cards (`.hub-card`) take
  `box-shadow: var(--shadow-card)`, with the values from DESIGN.md's Shadow Vocabulary.
- **Pastel rating badges:** `.badge-high`, `.badge-mid`, `.badge-low` and `.badge-neutral` become a
  16% tint of their status colour, with a label mixed 62% status / 38% `--text`, a 1px border at a
  32% tint, and 2px corners.
- **Sidebar lockup:** the sidebar brand shows the "ARP" lockup from `docs/brand/arp-lockup.svg` at 32px
  high instead of the mark plus the text "ARP". The mobile top bar keeps the mark alone. Both draw the
  ink in `--text` (BRAND.md: ink everywhere except the apex) and the apex in `--brand-apex`.

## Non-goals

- Serif typography (PR 2) and the signature elements: square dots, needs-you shape, evidence paper
  (PR 3). The lineage trail needs backend data and is not planned yet.
- Any change to amber (`--hi`, `--hi-ink`, `--await`, `--await-edge`, `--on-hi` in light), status
  colours (`--high`, `--mid`, `--low`, `--neutral`), chart slots or radii.
- Landing page code: no landing rule or component changes. The landing page changes colour through the
  tokens it already uses (`--bg`, `--text`, `--muted`, `--accent`, `--run`), and its contrast row is
  re-checked (AC-20).

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
| `--run` | `#0369a1` | `#7dd3fc` |
| `--shadow-card` (new) | `0 1px 2px rgb(16 24 40 / 0.07), 0 6px 18px rgb(16 24 40 / 0.09)` | `0 1px 2px rgb(16 24 40 / 0.44), 0 6px 18px rgb(16 24 40 / 0.56)` |

**Badge rule.** One shared rule plus four selectors that set `--st`:
`.badge { --st: var(--neutral); background: color-mix(in srgb, var(--st) 16%, var(--panel)); color: color-mix(in oklch, var(--st) 62%, var(--text)); border: 1px solid color-mix(in srgb, var(--st) 32%, var(--panel)); border-radius: 2px; }`
and `.badge-high { --st: var(--high); }` (and the same for mid, low, neutral). The existing `.badge`
padding, size and weight stay.

**Sidebar and top bar:**
- A new `ArpLockup` component in `App.tsx` with `className="app-sidebar-lockup"`. It uses the path
  data of `arp-lockup.svg` with `fill="currentColor"` (not the file's literal fills), a
  `<rect … fill="var(--brand-apex)">` for the apex, `role="img"` and `aria-label="ARP"`. It replaces
  `<ArpMark />` plus the wordmark span in the sidebar brand.
- New rule `.app-sidebar-lockup { height: 32px; width: auto; color: var(--text); flex-shrink: 0; }`.
- `ArpMark` stays in the top bar only, with the same `app-sidebar-mark` class and 32 × 32 size. Its rule's
  `color` changes from `var(--accent)` to `var(--text)`, and its apex from `var(--hi)` to
  `var(--brand-apex)`.
- The `app-sidebar-wordmark` span and its CSS rule go.

**Badge check fixture:** the e2e seed has no screen with all three ratings, so AC-9 is checked by
inserting `<span class="badge badge-high">High</span>`, `…badge-mid…Mid` and `…badge-low…Low` into
`.app-main` on `#/home` from the browser console and measuring them.

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
- `r2_ac1_run_token` is rewritten to `#0369a1` / `#7dd3fc` (`r2_ac2_run_contrast` is unchanged and
  must still pass).

From `2026-11-08-night-desk-status`: AC-1 (`--run` values) is restated as AC-1 to AC-3 here.
From `2026-11-08-night-desk-colours` AC-13: narrowed so that removing a `var(--hi…)` location is
allowed; the sidebar logo rect leaves the set.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `frontend/src/index.css` | `:root` is read | Every light value in the Decided table is present exactly | unit |
| AC-2 | The same | `:root[data-theme="dark"]` is read | Every dark value in the Decided table is present exactly | unit |
| AC-3 | The same | The `prefers-color-scheme: dark` block is read | Every dark value in the Decided table is present exactly | unit |
| AC-4 | All three token blocks | Contrast is computed (the existing `ac6_text_contrast` and `ac6b_fill_contrast` method) | `--text`, `--muted` and `--hi-ink` reach 4.5:1 on `--bg`, `--panel` and `--well`; `--on-accent` on `--accent`, `--on-hi` on `--hi` and `--hi-ink` on `--await` reach 4.5:1 | unit |
| AC-4b | The same | Contrast is computed | `--run`, `--accent` and `--accent-ink` reach 4.5:1 on `--bg`, `--panel` and `--well` | unit |
| AC-5 | The same | Contrast is computed | `--field-border` reaches 3:1 on `--panel` and on `--bg` | unit |
| AC-6 | `index.css` | Read | The `.card`, `.stat-tile` and `.hub-card` rules each contain `box-shadow: var(--shadow-card)` | unit |
| AC-7 | `index.css` | Read | The `.badge` rule contains `background: color-mix(in srgb, var(--st) 16%, var(--panel))`, `color: color-mix(in oklch, var(--st) 62%, var(--text))`, `border: 1px solid color-mix(in srgb, var(--st) 32%, var(--panel))` and `border-radius: 2px` | unit |
| AC-8 | `index.css` | Read | `.badge-high`, `.badge-mid`, `.badge-low` and `.badge-neutral` each set only `--st` to `var(--high)`, `var(--mid)`, `var(--low)` and `var(--neutral)` respectively | unit |
| AC-9a | The running app at `/#/home`, light, with the badge fixture from Decided inserted | The badges are measured | Each badge's label reaches 4.5:1 against its own computed background | evaluator |
| AC-9b | The same with `data-theme="dark"` | The badges are measured | Each badge's label reaches 4.5:1 against its own computed background | evaluator |
| AC-10 | The running app at `/#/home`, 1440×900 | The page loads | `.app-sidebar-brand` contains an `svg[role=img][aria-label=ARP]` of rendered height 32px, and its innerText is empty | evaluator |
| AC-10b | The running app at `/#/home`, 390×844 | The page loads | `.app-topbar` contains one `svg[aria-hidden=true]` with viewBox `0 0 62 62` and no `svg[aria-label=ARP]` | evaluator |
| AC-11 | `App.tsx` | Read | It contains `var(--brand-apex)` at least twice and no `fill="var(--hi)"` | unit |
| AC-11b | `App.tsx` | Read | It contains no `#[0-9a-fA-F]{3,8}`, `rgb(` or `oklch(` literal | unit |
| AC-12 | The running app at `/#/home`, 1440×900, light | The page loads | `body`'s background is `rgb(255, 255, 255)` and a `.hub-card` has a computed `box-shadow` other than `none` | evaluator |
| AC-13 | The same with `data-theme="dark"` | The page loads | `body`'s background is `rgb(6, 20, 29)` and the active nav item's background is `rgb(56, 189, 248)` | evaluator |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-14 | `index.css` against `origin/main` | These tokens are compared in all three blocks: `--mid`, `--neutral`, `--text-xs`, `--text-sm`, `--text-base`, `--text-md`, `--text-lg`, `--text-xl`, `--s-*`, `--shadow-md`, `--shadow-lg`, `--ease`, `--dur` | They are identical | unit |
| AC-15 | `index.css` | Read | `--hi`, `--hi-ink`, `--await`, `--await-edge`, `--high`, `--low`, `--cat-1` to `--cat-4` and `--r-sm`, `--r-md`, `--r-lg`, `--r-pill` keep their current values in all three blocks | unit |
| AC-16 | `frontend/tests/` | `npm test` runs | Every test passes. The only existing tests edited are those listed under Supersedes; new tests may be added | unit |
| AC-17 | `frontend/tests/landing.test.ts` | It runs | It passes unchanged | unit |
| AC-18 | `frontend/src` against `origin/main` | The `var(--hi\|--hi-ink\|--await\|--await-edge)` locations are listed | They equal the `origin/main` set minus the sidebar logo rect | unit |
| AC-20 | The landing page, both themes, 1440×900 | Landing-brand-refresh AC-13 is re-run (captures at 2.5 s and 11 s, text set transparent) | At least 99% of `p` line-box pixels reach 4.5:1 and of `h1` line-box pixels reach 3:1 | evaluator |
