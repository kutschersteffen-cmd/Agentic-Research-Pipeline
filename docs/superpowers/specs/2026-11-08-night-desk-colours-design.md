# Night Desk, release 1: colours and fonts

## Intent

The owner chose the Night Desk direction (mockups: `docs/design-directions.html`). Release 1 brings
only its colours, fonts and corner radii into the real app, in light and dark, so every page changes
look at once without any layout or behaviour change. Later releases add the step status lines, the
start-page layout, the review-queue source excerpt and the landing page.

Why: the owner wants one signal colour for "waiting on you" in both themes (toned amber instead of
light-mode orange and dark-mode lime), a cooler blue-grey ground, and the same fonts in both themes.

## Goals

- Light and dark colour values in `frontend/src/index.css` match Night Desk.
- "Waiting on you" is the same amber family in both themes.
- Dark mode uses Geist and Geist Mono, like light mode.
- Corners are rounded (Night Desk), replacing today's square corners.

## Non-goals

- No layout, markup or copy changes; no new components.
- No running-blue status colour in use yet (needs markup; release 2).
- No sidebar status dots, step status lines, start-page or review-queue redesign, landing page.
- No backend change.

## Anti-goals

- Text that falls below WCAG AA contrast anywhere the current colours pass.
- Amber used for anything other than "waiting on a person".

## Approaches

| | Approach | Trade-off |
|---|---|---|
| **A (picked)** | Replace the token values in place in `index.css` | Smallest change; everyone gets it; revert restores the old look |
| B | Night Desk as a fourth theme option | Old look stays, but every token set is doubled |
| C | Hidden tester switch | Safe trial, but a switch to remove later |

The owner picked A.

## Decided

Token values (the names already exist in `index.css`; only values change).

| Token | Light (`:root`) | Dark (both dark blocks) |
|---|---|---|
| `--bg` | `#f4f6f9` | `#0d1015` |
| `--panel` | `#ffffff` | `#141921` |
| `--panel-border` | `#d8dee7` | `#2c3644` |
| `--field-border` | `#7b8696` | `#6d7889` |
| `--well` | `#eaeef3` | `#1b222d` |
| `--text` | `#121722` | `#e8ebf0` |
| `--muted` | `#4f5a6b` | `#a3acbb` |
| `--accent` | `#121722` | `#e8ebf0` |
| `--sidebar-bg` | `#eaeef3` | `#10141a` |
| `--on-accent` | `#ffffff` | `#0d1015` |
| `--await` | `#f6ecd6` | `rgb(212 166 80 / 0.14)` |
| `--await-edge` | `#85601a` | `#d4a650` |
| `--hi` | `#85601a` | `#d4a650` |
| `--hi-ink` | `#85601a` | `#d4a650` |
| `--on-hi` | `#ffffff` | `#0d1015` |
| `--high` | `#13804f` | `#4fd69c` |
| `--low` | `#c8323f` | `#ff6b7a` |

Unchanged: `--mid`, `--neutral`, `--accent-ink`, `--accent-tint`, the type scale, spacing, shadows,
motion, chart slots `--cat-1..4` and `lib/palette.ts`.

Dark fonts: `--font-display` becomes `"Geist", …` and `--font-mono` `"Geist Mono", …` in both dark
blocks, the same stacks as light.

Radii: `--r-sm: 6px`, `--r-md: 8px`, `--r-lg: 12px` (`--r-pill` stays `999px`).

The header comments above the light and dark blocks are rewritten to describe Night Desk (amber is the
one "waiting on you" colour in both themes).

## Left to the builder

- Whether to drop Hanken Grotesk and JetBrains Mono from the Google Fonts link in `frontend/index.html`
  once nothing uses them (my call: drop them).
- Any token whose new value fails a contrast pair the current value passed: report it rather than
  inventing a value.

## Known risk

Dark `--mid` (`#f2c94c`, used for warning and escalation states) is a yellow close to the new amber
`#d4a650`. AC-9 requires a colour difference of at least 10 (it is about 20 with these values).

## Acceptance

Token rows are checked with jsdom loading `frontend/src/index.css`: each value is read with
`getComputedStyle(document.documentElement).getPropertyValue(name)`, lower-cased and trimmed, and must
equal the table string exactly. A contrast pair that fails is a failed row and goes back to the owner;
the builder does not pick a new value.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | No `data-theme` on `<html>`, OS light | `index.css` is loaded | Each of the 17 tokens in the table equals its Light value | unit |
| AC-2 | `data-theme="dark"` on `<html>` | `index.css` is loaded | Each of the 17 tokens equals its Dark value | unit |
| AC-3 | No `data-theme`, `prefers-color-scheme: dark` | `index.css` is loaded | Each of the 17 tokens equals its Dark value | unit |
| AC-4a | `data-theme="dark"` | `index.css` is loaded | `--font-display` starts with `"Geist"`; `--font-mono` starts with `"Geist Mono"` | unit |
| AC-4b | No `data-theme`, `prefers-color-scheme: dark` | `index.css` is loaded | `--font-display` starts with `"Geist"`; `--font-mono` starts with `"Geist Mono"` | unit |
| AC-5 | The branch | `grep -i "c6ff3d\|ea4c14" frontend/src/index.css` runs | It prints nothing | unit |
| AC-6 | Light, then dark | Contrast is computed for `--text`, `--muted`, `--hi-ink` on `--bg`, `--panel`, `--well` | All 9 pairs are at least 4.5:1 in each theme | unit |
| AC-6b | Light, then dark | Contrast is computed for `--on-accent` on `--accent`, `--on-hi` on `--hi`, `--hi-ink` on `--await` (dark `--await` composited over `--panel`) | Each pair is at least 4.5:1 in each theme | unit |
| AC-6c | Light, then dark | Contrast is computed for `--high` and `--low` on `--panel` | Each is at least 3:1 in each theme | unit |
| AC-7 | Light, then dark | `--r-sm`, `--r-md`, `--r-lg`, `--r-pill` are read | They equal `6px`, `8px`, `12px`, `999px` | unit |
| AC-8a | Light mode, the sidebar rendered by the existing `App` component test setup with a review count of 1 | The Review Queue count pill renders | Its computed `border-color` or `color` is `rgb(133, 96, 26)` | unit |
| AC-8b | Light mode, the same render | All elements are scanned | No element's computed `color`, `background-color` or `border-color` is `rgb(234, 76, 20)` | unit |
| AC-9 | Dark tokens | The CIE76 colour difference (ΔE*ab) between dark `--mid` and dark `--hi` is computed | It is at least 10 | unit |
| AC-10 | Each sidebar page (Start, Review Queue, StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub, Presentations & Reports, Arcade) at 1440×900, light | Compared with `main` | The same headings, buttons, sidebar items and table columns are present in the same count and order; layout differs only by corner rounding | evaluator |
| AC-10b | The same pages, dark | Compared with `main` | Same as AC-10; text may wrap differently only because the font changed | evaluator |
| AC-11a | The app running, sidebar switch | System, Light, Dark are clicked in turn | After each click, without reload, `--bg` equals that theme's table value (System follows the OS) | evaluator |
| AC-11b | After each click in AC-11a | The page is reloaded | The switch shows the same choice and `--bg` has the same value as before the reload | evaluator |
| AC-12 | Light, then dark | `--cat-1..4` are read; `git diff origin/main -- frontend/src/lib/palette.ts` runs | Light `#2a78d6 #c2407f #a87400 #6250d6`, dark `#3987e5 #d55181 #c98500 #9085e9`; the diff prints nothing | unit |
| AC-13 | The branch vs `origin/main` | The set of CSS selectors in `frontend/src` that reference `--hi`, `--hi-ink`, `--await` or `--await-edge` is listed | It is identical to the set on `origin/main` (amber stays limited to "waiting on a person") | unit |
| AC-14 | Light, then dark | `--mid`, `--neutral`, `--accent-ink`, `--accent-tint`, `--text-xs..xl`, `--s-*`, `--shadow-md`, `--shadow-lg`, `--ease`, `--dur` are read | Each equals its value on `origin/main` in the same theme | unit |

Must not change: layout and markup (AC-10, AC-10b), theme switching (AC-11a, AC-11b), chart colours
(AC-12), where amber is used (AC-13), untouched tokens (AC-14).
