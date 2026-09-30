---
name: Agentic Research Pipeline
description: A quiet monochrome instrument panel where one colour lights up only when a person must act.
colors:
  ink: "#141414"
  ink-deep: "#000000"
  graphite-ground: "#f3f3f0"
  panel-white: "#ffffff"
  hairline: "#dcdcd7"
  well-grey: "#ebebe7"
  sidebar-grey: "#eeeeea"
  muted-graphite: "#5c5c57"
  signal-orange: "#ea4c14"
  signal-orange-ink: "#b8400f"
  signal-orange-wash: "#ffe6db"
  status-high: "oklch(50% 0.150 149)"
  status-mid: "oklch(52% 0.125 70)"
  status-low: "oklch(54% 0.174 30)"
  status-neutral: "oklch(50% 0.010 64)"
  night-ground: "#0c0d0f"
  night-panel: "#131417"
  night-hairline: "#26272c"
  night-well: "#18191c"
  night-ink: "#e8e8e3"
  night-muted: "#9a9ba0"
  signal-lime: "#c6ff3d"
  signal-lime-wash: "#33420c"
  night-high: "#26c281"
  night-mid: "#ff9b42"
  night-low: "#ff4d4d"
typography:
  display:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "clamp(2rem, 1.2rem + 2.4vw, 3.25rem)"
    fontWeight: 600
    lineHeight: 1.02
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.3
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  pill: "999px"
spacing:
  s-1: "4px"
  s-2: "8px"
  s-3: "12px"
  s-4: "16px"
  s-6: "24px"
  s-8: "32px"
  s-12: "48px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.ink-deep}"
  button-secondary:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-disabled:
    backgroundColor: "{colors.well-grey}"
    textColor: "{colors.muted-graphite}"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.panel-white}"
    rounded: "{rounded.lg}"
    padding: "18px 20px"
  input:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
  nav-item-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.md}"
    padding: "7px 10px"
  badge-needs-you:
    backgroundColor: "{colors.signal-orange}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "1px 6px"
---

# Design System: Agentic Research Pipeline

## Overview

**Creative North Star: "The Signal Room"**

ARP is a quiet instrument panel for teams that run long agent pipelines and ratify what the agents propose. Almost everything on screen is ink on a neutral ground: graphite by day, near-black by night. Exactly one colour is allowed to light up, and it lights up for one reason only: a person must act. When nothing waits on anyone, the screen is monochrome.

The system is precise and restrained. Surfaces are flat and separated by hairlines rather than shadows. Controls are ink, text is set in a workhorse sans with a monospace for data and state, and density is high enough for tables of thousands of companies while staying legible on a projector. Two themes share one structure: **Graphite** (light) and **Night** (dark). The sidebar switch (System / Light / Dark) chooses between them, and every component reads its colours from the same tokens.

**Key Characteristics:**
- Monochrome by default; one signal colour per theme, reserved for "waiting on a person".
- Status colours (green / amber / red) describe runs and ratings, never the person-must-act state.
- Flat surfaces with hairline borders; shadows only for things that float.
- Sans for reading, mono for numbers, IDs, labels and state.
- The start page leads with the four processes; everything else is reached from them.

## Colors

A near-monochrome palette with one reserved signal per theme and a small set of status colours.

### Primary
- **Ink** (#141414 light / #e8e8e3 Night): text, primary buttons, the active navigation item, done-step dots and all structural lines. Hover deepens to **Ink Deep** (#000000 / #ffffff).
- **Signal Orange** (#ea4c14, Graphite) and **Signal Lime** (#c6ff3d, Night): the one colour for "a person must act": sidebar "Needs you" badges, the waiting count on the start page, waiting step dots and borders, proposed-not-ratified items. As a border or fill it clears 3:1 on its ground. For text in Graphite use **Signal Orange Ink** (#b8400f, 5:1 on white); Lime is already text-safe on Night. Its pale wash (#ffe6db / #33420c) backs pending banners.

### Secondary
- **Status High / Mid / Low / Neutral** (green, amber, red, grey; see frontmatter for both themes): run status pills, escalation stage, H/M/L ratings. They sit at text contrast (≥4.5:1) on every ground they appear on.

### Neutral
- **Graphite Ground** (#f3f3f0) / **Night Ground** (#0c0d0f): the page.
- **Panel White** (#ffffff) / **Night Panel** (#131417): cards, tables, inputs.
- **Hairline** (#dcdcd7 / #26272c): every border and divider.
- **Well Grey** (#ebebe7 / #18191c): recessed areas, disabled controls, hover rows.
- **Muted Graphite** (#5c5c57 / #9a9ba0): secondary text and labels; ≥4.5:1 on ground, panel and well.

### Named Rules
**The One Signal Rule.** Orange (Graphite) and lime (Night) mean one thing only: a person must act. Never use them for branding, decoration, hover, focus of a normal control, or "running". When nothing waits, no signal colour appears anywhere on the screen.

**The Status Is Not The Signal Rule.** Green, amber and red describe runs and ratings. Red marks a failed run and also a Low (L) rating on Transition Barriers; that second use is a deliberate, confirmed exception, because the matrix reads as a traffic light. It never marks something waiting on a person.

**The Icon Accent Rule.** Each process icon has exactly one element drawn in the signal colour, and it only lights up when that process waits on someone. Otherwise the whole icon is ink.

## Typography

**Display / Body Font:** Geist in Graphite, Hanken Grotesk in Night (both with the system sans fallback)
**Label / Mono Font:** Geist Mono in Graphite, JetBrains Mono in Night

**Character:** a plain, engineered sans for everything read, paired with a monospace that carries numbers, IDs, step labels and state, so data never shifts width and reads as measured.

### Hierarchy
- **Display** (600, clamp(2rem → 3.25rem), 1.02, −0.035em): the start-page status line only, e.g. "28 outputs wait on you."
- **Headline** (600, 1.5rem, 1.1): page titles and process card names.
- **Title** (600, 1rem, 1.3): card and section headings.
- **Body** (400, 0.9375rem / 15px, 1.45): all running text; keep help text to about 70ch.
- **Label** (mono 500, 0.8125rem / 13px): counts, run IDs, step labels, chips, table meta. 13px is the floor for any text.

### Named Rules
**The Mono Means Data Rule.** Mono is for numbers, IDs, labels and state. Never set a sentence of prose in mono for a "technical" feel.

## Layout

Spacing runs on a 4px base (4, 8, 12, 16, 24, 32, 48). Groups are tight (8–12px inside), sections are generous (24–48px between). A 248px sidebar holds navigation on wide screens; below 1024px it collapses into a drawer behind a top bar (53px), so tablets get the full width for tables and diagrams. The start page is a status line, then the four process cards (four columns on desktop, two below 1100px, one below 640px), then a row of run chips. Wide tables scroll inside their frame and show a shadow on any edge with more columns; tables never push the page sideways.

## Elevation & Depth

The system is flat. Depth comes from tonal layering (ground → panel → well) and 1px hairlines, not shadows. Shadows appear only on things that genuinely float: menus, modals, the command palette, the mobile drawer.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 2px 6px oklch(20% 0.014 58 / 0.07), 0 8px 24px oklch(20% 0.014 58 / 0.10)`): popovers and hover lift on pipeline cards.
- **Overlay** (`box-shadow: 0 12px 32px oklch(20% 0.014 58 / 0.16)`): modals and the drawer.

### Named Rules
**The Flat-By-Default Rule.** Cards and tables sit flat on a hairline. If you reach for a shadow, the element must float above the page.

## Shapes

Gently rounded and consistent: 6px for small controls and badges, 8px for buttons and inputs, 12px for cards and framed tables, full pills for status and count badges. Start-page process cards and run chips are square-cornered, which sets the start page apart as the instrument panel. Borders are always 1px hairlines; a 1.5px dashed edge marks a switched-off or pending pipeline step.

## Components

### Buttons
- **Shape:** gently rounded (8px).
- **Primary:** ink fill, white text (inverted in Night), 9px × 16px padding, weight 500.
- **Hover / Focus:** deepens to pure black / white; keyboard focus shows a 2px outline.
- **Secondary:** transparent with a hairline border and ink text; hover adds a 6% ink tint.
- **Link button:** underlined ink text, no padding inside tables.
- **In tables:** per-row actions are compact outlined buttons (2px × 10px), never a column of solid primaries.
- **Disabled:** well-grey fill and muted text; readable, never louder than live controls.

### Chips and Badges
- **Status pill:** pill-shaped, outlined in its status colour.
- **"Needs you" count:** signal fill with ink text, pill-shaped, sidebar only.
- **Run chip (start page):** square, hairline border, mono label, a leading state dot; the signal border marks runs waiting on you.

### Cards / Containers
- **Corner Style:** 12px (square on the start page).
- **Background:** panel white / Night panel.
- **Shadow Strategy:** none (see Elevation).
- **Border:** 1px hairline; a card that waits on you takes an ink border on the start page.
- **Internal Padding:** 18px × 20px (28px × 24px on start-page cards).

### Inputs / Fields
- **Style:** panel fill, hairline border, 8px radius, 8px × 10px padding.
- **Rows:** fields in a row centre on one line and wrap as a group; checkbox labels and buttons never break mid-label.
- **Native controls:** checkboxes follow the accent; file pickers get a themed button.

### Navigation
- **Sidebar:** grouped by the team's day ("Needs you" first). Items are 15px sans; the active item is an ink fill with inverted text; "Needs you" items carry the signal count badge.
- **Mobile / tablet:** below 1024px the sidebar becomes a drawer behind a top bar showing the current screen's name.

### Process Card (signature component)
The start page's four cards (StewardIQ, Theme Machine, Data Engineer, Design Studio): an icon from one 48-grid family, the name, a one-line purpose, the process steps as dots on a line (ink = done, ring = running, signal = waiting on you, red diamond = failed, hollow = idle), one mono line naming the step that matters now, and a status in the signal colour when someone is needed.

## Do's and Don'ts

### Do:
- **Do** read every colour from the tokens (`var(--hi)`, `var(--text)`, …); both themes depend on it.
- **Do** use the signal colour for exactly one meaning: a person must act (see The One Signal Rule).
- **Do** use `--hi-ink` (#b8400f) when orange is text in Graphite.
- **Do** keep text at 13px or larger and at ≥4.5:1 contrast in both themes.
- **Do** put numbers, IDs and state in the mono face.
- **Do** let wide tables scroll inside their frame, with the edge shadow cue.

### Don't:
- **Don't** use orange or lime for anything that doesn't wait on a person: not branding, not "running", not hover.
- **Don't** add shadows to flat cards or tables.
- **Don't** use emoji as icons or status markers; draw icons in the shared stroke family.
- **Don't** hard-code colours or fonts in components (third-party editors included); follow the live theme.
- **Don't** fade disabled or switched-off items with opacity; mark them with the well fill or a dashed edge and keep text legible.
