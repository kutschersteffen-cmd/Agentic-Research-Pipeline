---
name: Agentic Research Pipeline
description: A calm blue instrument panel on white paper, where amber lights up only when a person must act.
colors:
  ink: "#082f49"
  accent: "#0a4a8f"
  accent-deep: "#08396f"
  ground-white: "#ffffff"
  panel-white: "#ffffff"
  hairline: "#d9e8f2"
  field-border: "#6f8a9c"
  well: "#eef6fb"
  sidebar: "#f1f7fc"
  muted: "#3d5a6e"
  signal-amber: "#85601a"
  signal-amber-wash: "#f6ecd6"
  status-high: "#13804f"
  status-mid: "oklch(52% 0.125 70)"
  status-low: "#c8323f"
  status-run: "#0284c7"
  status-neutral: "oklch(50% 0.010 64)"
  paper: "#ffffff"
  paper-mark: "#f6ecd6"
  brand-orange: "#ea4c14"
  night-ground: "#06141d"
  night-panel: "#0b1d29"
  night-hairline: "#1d3a4d"
  night-field-border: "#5f8399"
  night-well: "#10293a"
  night-sidebar: "#081822"
  night-ink: "#e2f1fa"
  night-muted: "#94b6c9"
  night-accent: "#38bdf8"
  night-accent-deep: "#7dd3fc"
  night-signal-amber: "#d4a650"
  night-signal-amber-wash: "rgb(212 166 80 / 0.14)"
  night-high: "#4fd69c"
  night-mid: "#f2c94c"
  night-low: "#ff6b7a"
  night-run: "#7dd3fc"
  night-paper: "#f5f2ea"
  brand-turquoise: "#2ee6d6"
typography:
  display:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "clamp(2rem, 1.2rem + 2.4vw, 3.25rem)"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.875rem"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.125rem"
    fontWeight: 500
    lineHeight: 1.3
  figure:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.6875rem"
    fontWeight: 500
    lineHeight: 1.1
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
  excerpt:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  marker: "0"
  pill: "999px"
shadows:
  card: "0 1px 2px rgb(16 24 40 / 0.07), 0 6px 18px rgb(16 24 40 / 0.09)"
  night-card: "0 1px 2px rgb(16 24 40 / 0.44), 0 6px 18px rgb(16 24 40 / 0.56)"
  float: "0 2px 6px oklch(20% 0.014 58 / 0.07), 0 8px 24px oklch(20% 0.014 58 / 0.10)"
  overlay: "0 12px 32px oklch(20% 0.014 58 / 0.16)"
spacing:
  s-0_5: "2px"
  s-1: "4px"
  s-1_5: "6px"
  s-2: "8px"
  s-3: "12px"
  s-4: "16px"
  s-6: "24px"
  s-8: "32px"
  s-12: "48px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.accent-deep}"
  button-secondary:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.accent}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-disabled:
    backgroundColor: "{colors.well}"
    textColor: "{colors.muted}"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.panel-white}"
    rounded: "{rounded.lg}"
    shadow: "{shadows.card}"
    padding: "18px 20px"
  input:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  nav-item-active:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.md}"
    padding: "7px 10px"
  badge-needs-you:
    backgroundColor: "{colors.signal-amber}"
    textColor: "{colors.panel-white}"
    rounded: "2px"
    padding: "1px 6px"
---

# Design System: Agentic Research Pipeline

## Overview

**Creative North Star: "The Annotated Report"**

ARP is a calm instrument panel for teams that run long agent pipelines and ratify what the agents propose. It reads like a well-kept research report: white paper, deep blue ink, serif headings and figures, and every number traceable to the page it came from. One colour, amber, is reserved for one reason only: a person must act. When nothing waits on anyone, no amber appears.

The system is precise and quiet. Cards lift slightly off a white page; text is set in a workhorse sans with a serif for titles and figures and a monospace for IDs and state. Density is high enough for tables of thousands of companies while staying legible on a projector. Two themes share one structure: **Arctic** (light) and **Arctic Night** (dark). The sidebar switch (System / Light / Dark) chooses between them, and every component reads its colours from the same tokens.

**Key Characteristics:**
- White page, deep blue accent for controls, amber reserved for "waiting on a person".
- Status colours (green / amber-brown / red / blue) describe runs and ratings, never the person-must-act state.
- Cards lift off the page with a soft shadow and a hairline.
- Serif for titles and figures, sans for reading, mono for IDs, labels and state.
- Four signature elements carry the identity: the Pixel mark language, the needs-you shape, evidence paper and the serif figure.
- The start page leads with the five workspaces; everything else is reached from them.

## Colors

A white-and-blue palette with one reserved signal per theme and a small set of status colours.

### Primary
- **Accent** (#0a4a8f light / #38bdf8 Night): primary buttons, the active navigation item, links, done-step dots and lineage steps that are complete. Hover deepens to **Accent Deep** (#08396f / #7dd3fc).
- **Ink** (#082f49 / #e2f1fa): all text and structural lines.
- **Signal Amber** (#85601a light, #d4a650 Night): the one colour for "a person must act": sidebar "Needs you" counts, the waiting count on the start page, waiting step dots and borders, proposed-not-ratified items. #85601a is text-safe on white (5.7:1); its pale wash (#f6ecd6 / amber at 14%) backs waiting tiles and pending banners.

### Secondary
- **Status High / Mid / Low / Run / Neutral** (green, amber-brown, red, blue, grey; see frontmatter for both themes): run status pills, escalation stage, H/M/L ratings. Rating badges are pastel: a 16% tint of the status colour with a label mixed 62% status / 38% ink and a 32% tint border. Labels sit at text contrast (≥4.5:1) on every ground they appear on.

### Neutral
- **Ground White** (#ffffff) / **Night Ground** (#06141d): the page.
- **Panel White** (#ffffff) / **Night Panel** (#0b1d29): cards, tables, inputs. On the white page a card is set off by its hairline and the card shadow.
- **Hairline** (#d9e8f2 / #1d3a4d): every border and divider.
- **Field Border** (#6f8a9c / #5f8399): the edge of form fields only; it clears 3:1 on the field and the page (WCAG 1.4.11), which the hairline does not.
- **Well** (#eef6fb / #10293a) and **Sidebar** (#f1f7fc / #081822): recessed areas, disabled controls, hover rows, the navigation column.
- **Muted** (#3d5a6e / #94b6c9): secondary text and labels; ≥4.5:1 on ground, panel and well.

### Named Rules
**The One Signal Rule.** Amber means one thing only: a person must act. Never use it for branding, decoration, hover, focus of a normal control, or "running". When nothing waits, no amber appears anywhere on the screen. Keyboard focus is an accent outline. A proposed item's box is neutral; only its "Proposed" tag and the needs-you shape carry the signal, so a queue never turns into a wall of amber. The flagged vote that needs a second person takes the signal border.

**The Brand Colour Rule.** The logo apex is the only place for the brand colours: orange (#ea4c14) in light, turquoise (#2ee6d6) in Night. They never appear in the interface itself, so they cannot be mistaken for the signal.

**Provenance Is Not Status.** Where a number came from (live, synthetic sample, portfolio holdings, not built) is shown with neutral marks: filled, half, ring, dashed ring. Metric numbers are ink. Green, amber-brown and red stay for status.

**The Status Is Not The Signal Rule.** Status colours describe runs and ratings. Red marks a failed run and also a Low (L) rating on Transition Barriers; that second use is a deliberate, confirmed exception, because the matrix reads as a traffic light. It never marks something waiting on a person.

**Chart Colours.** Charts with categories use four slots, `--cat-1` to `--cat-4` (blue, magenta, gold, violet; `lib/palette.ts` explains the validation). They are neither status nor signal.

**The Arcade Exception.** The hidden arcade games draw in their own neon palette. They sit outside the product and are the only place where neon is decoration.

**The Icon Accent Rule.** Each process icon has exactly one element drawn in the signal colour, and it only lights up when that process waits on someone. Otherwise the whole icon is ink.

## Typography

**Title / Figure Font:** Source Serif 4 (Georgia fallback)
**Body Font:** Geist (system sans fallback)
**Label / Mono Font:** Geist Mono

**Character:** a report voice. Serif headings and big figures make the page read like a document someone signs off; an engineered sans carries running text and controls; a monospace carries IDs, step labels and state, so data never shifts width.

### Hierarchy
The CSS scale tokens are `--text-xs` (13px), `--text-sm` (14px), `--text-base` (15px), `--text-md` (16px), `--text-lg` (22px) and `--text-xl` (24px).

- **Display** (serif 500, clamp(2rem → 3.25rem), 1.05): the start-page status line only, e.g. "28 outputs wait on you."
- **Headline** (serif 500, 1.875rem, 1.1): page titles.
- **Title** (serif 500, 1.125rem, 1.3): card and section headings.
- **Figure** (serif 500, 1.6875rem, tabular): the big number on stat tiles.
- **Body** (sans 400, 0.9375rem / 15px, 1.45): all running text and controls; keep help text to about 70ch.
- **Label** (mono 500, 0.8125rem / 13px): counts, run IDs, step labels, chips, table meta. 13px is the floor for any text.

### Named Rules
**The Serif Means Document Rule.** Serif is for titles, figures and anything quoted from a source. Buttons, navigation, table body text and form labels stay in the sans.

**The Mono Means Data Rule.** Mono is for IDs, labels and state. Never set a sentence of prose in mono for a "technical" feel.

## Layout

Spacing runs on a 4px base (4, 8, 12, 16, 24, 32, 48), plus two half steps for dense parts: 2px (`--s-0_5`: the nav stack, segmented bars, compact pills and row buttons) and 6px (`--s-1_5`: chip rows, icon-to-label gaps). New padding, margin and gap values read from these tokens rather than raw pixels. Groups are tight (8–12px inside), sections are generous (24–48px between). A 248px sidebar holds navigation on wide screens; below 1024px it collapses into a drawer behind a top bar (53px), so tablets get the full width for tables and diagrams. The sidebar opens with the ARP lockup at its large size (see `docs/BRAND.md`). The start page is a status line, then the five workspace cards (five columns on wide screens, three below 1400px, two below 1100px, one below 640px), then a row of run chips. Wide tables scroll inside their frame and show a shadow on any edge with more columns; tables never push the page sideways.

## Elevation & Depth

Cards lift. On the white page, a card is a white sheet with a hairline and a soft two-layer shadow; tables, wells and inputs stay flat inside it. Things that genuinely float get stronger shadows.

### Shadow Vocabulary
- **Card** (`0 1px 2px rgb(16 24 40 / 0.07), 0 6px 18px rgb(16 24 40 / 0.09)`; Night `/ 0.44` and `/ 0.56`): cards and stat tiles, `--shadow-card`.
- **Float** (`0 2px 6px oklch(20% 0.014 58 / 0.07), 0 8px 24px oklch(20% 0.014 58 / 0.10)`): popovers, the evidence paper card and hover lift on pipeline cards.
- **Overlay** (`0 12px 32px oklch(20% 0.014 58 / 0.16)`): modals and the drawer.

### Named Rules
**The Lifted Card Rule.** Every card and stat tile takes the card shadow and a hairline. Nothing inside a card takes a shadow except the evidence paper. Never stack a card on a card.

## Shapes

Containers are softly rounded; markers are square. Buttons and nav items use `--r-md` (8px), inputs `--r-sm` (6px), cards and tiles `--r-lg` (12px). Everything that marks state is square, taken from the Pixel A grid: status dots, lineage steps, nav group markers, count badges (2px) and chart segments. Borders are 1px hairlines; a 1.5px dashed edge marks something unsigned or pending.

## Signature Elements

Four elements make an ARP screen recognisable. Use them as specified; don't invent variants.

### Pixel Mark Language
The Pixel A's square is the system's marker.
- Status dots, pill dots and lineage steps are squares (radius 0), not circles.
- Each sidebar group label starts with a 6px ink square.
- Bar charts and progress tracks are drawn as 8px segments with 2px gaps.
- A five-square strip sits at the foot of the sidebar; its middle square takes the signal colour.

### The Needs-You Shape
Anything that waits on a person has a shape as well as a colour, so it reads in grayscale.
- **Unsigned edge:** a 1.5px dashed border in signal amber.
- **Folded corner:** an 18px fold at the top right, filled with the signal colour; that corner has no radius.
- **Stamp label:** the label is uppercase, 10.5px, 700, letter-spaced 0.1em, boxed in a 1.5px signal border and turned −2°.
- "Proposed" tags carry a ✎ before the word; "Needs you" counts are square (2px).

### Evidence Paper
Source excerpts are shown as a sheet of paper.
- Serif 16px / 1.6 on `--paper`, with the float shadow.
- A mono line-number gutter on the left, separated by a hairline.
- The cited span gets a highlighter mark: a soft amber stroke with ragged ends (gradient fill, uneven radius), never a flat underline.
- Proposed values in tables are set in the serif with an amber highlighter underline, so an unratified number visibly comes from a document.

### Lineage Trail
Where a value's history matters, a four-step trail shows source → extracted → reviewed → published: accent squares for done steps, amber for waiting on a person, red for a conflict, blue for running, hollow for not reached.

## Components

### Buttons
- **Shape:** `--r-md` (8px).
- **Primary:** accent fill, white text (Night: dark text on the light accent), 9px × 16px padding, weight 600.
- **Hover / Focus:** deepens to Accent Deep; keyboard focus shows a 2px accent outline.
- **Secondary:** white with a hairline border and accent text; hover fills with the well.
- **Link button:** accent text, no padding inside tables.
- **In tables:** per-row actions are compact outlined buttons (2px × 10px), never a column of solid primaries.
- **Disabled:** well fill and muted text; readable, never louder than live controls.

### Chips and Badges
- **Rating badge:** pastel (see Secondary colours), 2px corners.
- **Status pill:** a square dot and the status word.
- **"Needs you" count:** amber fill with white text (Night: dark text), square (2px), sidebar only.
- **Run chip (start page):** hairline border, mono label, a leading square state dot; the needs-you shape marks runs waiting on you.

### Cards / Containers
- **Corner Style:** `--r-lg` (12px).
- **Background:** panel white / Night panel.
- **Shadow Strategy:** the card shadow (see Elevation).
- **Border:** 1px hairline; a card that waits on you takes the needs-you shape.
- **Internal Padding:** 18px × 20px (28px × 24px on start-page cards).

### Inputs / Fields
- **Style:** panel fill, field border, `--r-sm`, 8px × 10px padding.
- **Rows:** fields in a row centre on one line and wrap as a group; checkbox labels and buttons never break mid-label.
- **Native controls:** checkboxes follow the accent; file pickers get a themed button.

### Navigation
- **Sidebar:** the ARP lockup ("ARP" on the Pixel A grid, 32px high) first, no side bars or stripes on items, then groups by the team's day ("Needs you" first). Items are 14px sans; the active item is an accent fill with inverted text; "Needs you" items carry the square signal count.
- **Mobile / tablet:** below 1024px the sidebar becomes a drawer behind a top bar showing the current screen's name.

### Process Card (signature component)
The start page's five cards (StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub): an icon from one 48-grid family, the name, a one-line purpose, the workspace's processes as square dots on a line (accent = done, ring = running, signal = waiting on you, red diamond = failed, hollow = idle), one mono line naming the process that matters now, and "Open →". The card is a way in: it carries no counts, because waiting work is counted once, in the start page headline. The start page has no Needs you list: each waiting item lives in the Review Queue or its workspace.

## Do's and Don'ts

### Do:
- **Do** read every colour from the tokens (`var(--hi)`, `var(--accent)`, `var(--text)`, …); both themes depend on it.
- **Do** use amber for exactly one meaning: a person must act (see The One Signal Rule).
- **Do** give anything that waits on a person the needs-you shape as well as the colour.
- **Do** keep text at 13px or larger and at ≥4.5:1 contrast in both themes.
- **Do** set titles and figures in the serif, IDs and state in the mono face.
- **Do** let wide tables scroll inside their frame, with the edge shadow cue.

### Don't:
- **Don't** use amber for anything that doesn't wait on a person: not branding, not "running", not hover.
- **Don't** use the brand orange or turquoise anywhere but the logo apex.
- **Don't** put shadows on tables, wells or inputs inside a card, or stack cards.
- **Don't** round markers: dots, steps and segments are square.
- **Don't** use emoji as icons or status markers; draw icons in the shared stroke family. (The ✎ on "Proposed" is a text glyph, not an icon.)
- **Don't** hard-code colours or fonts in components (third-party editors included); follow the live theme.
- **Don't** fade disabled or switched-off items with opacity; mark them with the well fill or a dashed edge and keep text legible.
