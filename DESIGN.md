---
name: Agentic Research Pipeline
description: A quiet ink-on-blue-grey instrument panel, where amber lights up only when a person must act.
colors:
  ink: "#121722"
  accent: "#121722"
  accent-ink: "#000000"
  accent-tint: "rgb(20 20 20 / 0.06)"
  ground: "#f4f6f9"
  panel: "#ffffff"
  hairline: "#d8dee7"
  field-border: "#7b8696"
  well: "#eaeef3"
  muted: "#4f5a6b"
  text-2: "color-mix(in oklch, #121722 80%, #4f5a6b)"
  signal-amber: "#85601a"
  signal-amber-wash: "#f6ecd6"
  status-high: "#13804f"
  status-mid: "oklch(52% 0.125 70)"
  status-low: "#c8323f"
  status-run: "#2563c9"
  status-neutral: "oklch(50% 0.010 64)"
  paper: "#ffffff"
  paper-mark: "#f6ecd6"
  brand-orange: "#ea4c14"
  night-ground: "#0d1015"
  night-panel: "#141921"
  night-hairline: "rgb(232 235 240 / 0.12)"
  night-field-border: "#6d7889"
  night-well: "#1b222d"
  night-ink: "#e8ebf0"
  night-muted: "#a3acbb"
  night-accent: "#e8ebf0"
  night-accent-ink: "#ffffff"
  night-accent-tint: "rgb(232 232 227 / 0.08)"
  night-signal-amber: "#d4a650"
  night-signal-amber-wash: "rgb(212 166 80 / 0.14)"
  night-high: "#4fd69c"
  night-mid: "#f2c94c"
  night-low: "#ff6b7a"
  night-run: "#6cb4ff"
  night-paper: "#f5f2ea"
  brand-orange-night: "#ff6a2b"
typography:
  display:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "clamp(2rem, 1.2rem + 2.4vw, 3.25rem)"
    fontWeight: 500
    lineHeight: 1.02
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "clamp(1.75rem, 1.25rem + 1.4vw, 2.5rem)"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  figure:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "2rem"
    fontWeight: 500
    lineHeight: 1
  body:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "-0.008em"
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
  landing-headline:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "clamp(2.5rem, 2rem + 3vw, 4.2rem)"
    fontWeight: 500
    lineHeight: 1.02
    letterSpacing: "-0.01em"
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  marker: "0"
  pill: "999px"
shadows:
  float: "0 2px 6px oklch(20% 0.014 58 / 0.07), 0 8px 24px oklch(20% 0.014 58 / 0.10)"
  overlay: "0 12px 32px oklch(20% 0.014 58 / 0.16)"
  night-float: "0 2px 6px rgb(0 0 0 / 0.4), 0 8px 24px rgb(0 0 0 / 0.5)"
  night-overlay: "0 12px 32px rgb(0 0 0 / 0.6)"
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
    textColor: "{colors.panel}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.accent-ink}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-secondary-hover:
    backgroundColor: "{colors.accent-tint}"
  button-disabled:
    backgroundColor: "{colors.well}"
    textColor: "{colors.muted}"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.lg}"
    padding: "18px 20px"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  filter-chip-pressed:
    backgroundColor: "{colors.accent-tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
  badge-needs-you:
    backgroundColor: "{colors.signal-amber}"
    textColor: "{colors.panel}"
    rounded: "2px"
    padding: "2px 6px"
---

# Design System: Agentic Research Pipeline

## Overview

**Creative North Star: "The Annotated Report"**

ARP is a calm instrument panel for teams that run long agent pipelines and ratify what the agents propose. It reads like a well-kept research report: ink on a cool blue-grey ground, titles and figures in one engineered sans, and every number traceable to the page it came from. One colour, amber, is reserved for one reason only: a person must act. When nothing waits on anyone, no amber appears.

The system is precise and quiet. Cards are flat panels set off by a hairline; Geist carries titles, figures, text and controls, Geist Mono carries IDs and state, and a serif appears only where text is quoted from a source. Density is high enough for tables of thousands of companies while staying legible on a projector. Two themes share one structure: **Night Desk**, in light and dark. The theme switch (System / Light / Dark), in the top bar's user menu, chooses between them, and every component reads its colours from the same tokens.

**Key Characteristics:**
- Blue-grey ground, ink accent for controls (near-black in light, near-white in dark), amber reserved for "waiting on a person".
- Status colours (green / amber-brown / red / blue) describe runs and ratings, never the person-must-act state.
- Cards are flat: a panel fill and a hairline, no shadow.
- Geist for titles, figures and reading; Geist Mono for IDs, labels and state; a serif only for quoted source text.
- Three signature elements carry the identity: the Pixel mark language, the needs-you shape and evidence paper.
- The start page leads with the five workspaces; everything else is reached from them.

## Colors

An ink-and-blue-grey palette with one reserved signal per theme and a small set of status colours.

### Primary
- **Accent** (`--accent`: ink, #121722 light / #e8ebf0 dark): primary buttons, links, done-step dots and lineage steps that are complete. Hover goes to **Accent Ink** (#000000 / #ffffff); a faint **Accent Tint** (`--accent-tint`) backs secondary-button hover and a pressed filter chip.
- **Ink** (`--text`: #121722 / #e8ebf0): all text and structural lines.
- **Signal Amber** (#85601a light, #d4a650 Night): the one colour for "a person must act": the "Needs you" count in the top bar, waiting step dots and borders, proposed-not-ratified items. #85601a is text-safe on white (5.7:1); its pale wash (#f6ecd6 / amber at 14%) backs waiting tiles and pending banners.

### Secondary
- **Status High / Mid / Low / Run / Neutral** (green, amber-brown, red, blue, grey; see frontmatter for both themes): run status pills, escalation stage, H/M/L ratings. Rating badges are pastel: a 16% tint of the status colour with a label mixed 62% status / 38% ink and a 32% tint border. Labels sit at text contrast (≥4.5:1) on every ground they appear on.

### Neutral
- **Ground** (`--bg`: #f4f6f9 / #0d1015): the page.
- **Panel** (`--panel`: #ffffff / #141921): cards, tables, inputs. A card is set off from the ground by its hairline; there is no card shadow.
- **Hairline** (`--panel-border`: #d8dee7 light; white at 12% in dark): every border and divider.
- **Field Border** (#7b8696 / #6d7889): the edge of form fields only; it clears 3:1 on the field and the page (WCAG 1.4.11), which the hairline does not.
- **Well** (#eaeef3 / #1b222d): recessed areas, disabled controls, hover rows, the Ask panel's header and form.
- **Muted** (#4f5a6b / #a3acbb): secondary text and labels; ≥4.5:1 on ground, panel and well.
- **Secondary text** (`--text-2`: 80% ink, 20% muted, in both themes): page intros, process descriptions and start-card purposes. Meta lines and captions stay muted.

### Named Rules
**The One Signal Rule.** Amber means one thing only: a person must act. Never use it for branding, decoration, hover, focus of a normal control, or "running". When nothing waits, no amber appears anywhere on the screen. Keyboard focus is an accent outline. A proposed item's box is neutral; only its "Proposed" tag and the needs-you shape carry the signal, so a queue never turns into a wall of amber. The flagged vote that needs a second person takes the signal border.

**The Brand Colour Rule.** Brand orange (#ea4c14 light, #ff6a2b Night) appears in two places only: the logo apex and the landing animation's orb glow. It never appears in the app's interface, so it cannot be mistaken for the amber signal.

**Provenance Is Not Status.** Where a number came from (live, synthetic sample, portfolio holdings, not built) is shown with neutral marks: filled, half, ring, dashed ring. Metric numbers are ink. Green, amber-brown and red stay for status.

**The Status Is Not The Signal Rule.** Status colours describe runs and ratings. Red marks a failed run and also a Low (L) rating on Transition Barriers; that second use is a deliberate, confirmed exception, because the matrix reads as a traffic light. It never marks something waiting on a person.

**Chart Colours.** Charts with categories use four slots, `--cat-1` to `--cat-4` (blue, magenta, gold, violet; `lib/palette.ts` explains the validation). They are neither status nor signal.

**The Arcade Exception.** The hidden arcade games draw in their own neon palette. They sit outside the product and are the only place where neon is decoration.

**The Icon Accent Rule.** Each workspace drawing has exactly one element that can light up: in the signal colour (`--hi`) when the workspace waits on someone, in the running colour (`--run`) when it runs. Otherwise the whole drawing is a quiet wireframe.

## Typography

**Title, Figure and Body Font:** Geist (system sans fallback), `--font-display` for titles
**Label / Mono Font:** Geist Mono
**Source Font:** Source Serif 4 (Georgia fallback), for quoted source text and the landing headline only

**Character:** a report voice in one engineered sans. Titles and big figures are Geist at medium weight with tight tracking; running text and controls are Geist; a monospace carries IDs, step labels and state, so data never shifts width. The serif is kept for text that comes from a document, so a quotation looks quoted.

### Hierarchy
The CSS scale tokens are `--text-xs` (13px), `--text-sm` (14px), `--text-base` (15px), `--text-md` (16px), `--text-lg` (22px) and `--text-xl` (24px).

- **Display** (Geist 500, clamp(2rem → 3.25rem), 1.02, `--track-display`): the start-page greeting only, e.g. "Good morning, dev."
- **Headline** (Geist 500, clamp(1.75rem → 2.5rem), 1.05, `--track-display`): page titles.
- **Title** (Geist 500, 1.25rem, `--track-title`): card titles and workspace card names. Section and card headings under 20px stay at their bolder weight.
- **Figure** (Geist 500, 2rem, tabular): the big number on stat tiles.
- **Body** (sans 400, 0.9375rem / 15px, 1.45): all running text and controls; keep help text to about 70ch.
- **Label** (mono 500, 0.8125rem / 13px): counts, run IDs, step labels, chips, table meta. 13px is the floor for any text.

### Named Rules
**The Serif Means Source Rule.** The serif is for text quoted from a source document (the evidence paper) and the landing page's headline. Titles, figures, buttons, navigation, tables and forms stay in Geist.

**The Mono Means Data Rule.** Mono is for IDs, labels and state. Never set a sentence of prose in mono for a "technical" feel.

- **Tracking by size band:** `--track-display` (−0.025em) for page titles and the start greeting, `--track-title` (−0.015em) for card and section titles, `--track-body` (−0.008em) for body text. `kbd` and `code` keep normal tracking.
- **Heading weight:** headings of 20px and up are 500; smaller ones keep their weight.
- **Page intro:** above 760px the paragraph under a page title is a 17px lead in `--text-2`, capped at 62ch.
- **Motion:** `--dur-fast` (100ms) for colour hovers, `--dur` (140ms) with `--ease` for state changes, `--dur-slow` (240ms) with `--ease-out` for bars and panels.

## Layout

Spacing runs on a 4px base (4, 8, 12, 16, 24, 32, 48), plus two half steps for dense parts: 2px (`--s-0_5`: the nav stack, segmented bars, compact pills and row buttons) and 6px (`--s-1_5`: chip rows, icon-to-label gaps). New padding, margin and gap values read from these tokens rather than raw pixels. Groups are tight (8–12px inside), sections are generous (24–48px between). There is no sidebar. One top bar runs across every page but the landing page (lockup, search, Ask ARP, Workspaces, Review Queue, Reports, user menu); inside a workspace a slim workspace row sits under it, so every page gets the full width for tables and diagrams. The start page is the greeting, then the five workspace cards in 3 + 2 on a six-column grid (two per row at 1100px and below with the fifth card full width, one at 760px and below). Wide tables scroll inside their frame and show a shadow on any edge with more columns; tables never push the page sideways.

## Elevation & Depth

Cards are flat. A card is a panel with a hairline on the blue-grey ground; tables, wells and inputs stay flat inside it. Only things that genuinely float take a shadow.

### Shadow Vocabulary
- **Float** (`--shadow-md`: `0 2px 6px oklch(20% 0.014 58 / 0.07), 0 8px 24px oklch(20% 0.014 58 / 0.10)`; dark `rgb(0 0 0 / 0.4)` and `/ 0.5`): popovers, menus and the hover lift on pipeline and flow cards.
- **Overlay** (`--shadow-lg`: `0 12px 32px oklch(20% 0.014 58 / 0.16)`; dark `rgb(0 0 0 / 0.6)`): modals.

### Named Rules
**The Flat Card Rule.** Cards and stat tiles take a hairline, never a shadow. Nothing inside a card takes a shadow. Never stack a card on a card.

## Shapes

Containers are softly rounded; markers are square. Buttons use `--r-md` (8px), inputs `--r-sm` (6px), cards and tiles `--r-lg` (12px), chips and pills `--r-pill`. Everything that marks state is square, taken from the Pixel A grid: status dots, lineage steps, count badges (2px) and chart segments. Borders are 1px hairlines; a dashed edge marks something proposed and not yet ratified.

## Signature Elements

Three elements make an ARP screen recognisable. Use them as specified; don't invent variants.

### Pixel Mark Language
The Pixel A's square is the system's marker.
- Status dots, pill dots and lineage steps are squares (radius 0), not circles.
- Bar charts and progress tracks are drawn as 8px segments with 2px gaps.

### The Needs-You Shape
Anything that waits on a person has a shape as well as a colour, so it reads in grayscale.
- **Waiting edge:** a solid 1px signal-amber border (`--await-edge`); a waiting step card adds a 1px inset ring of the same colour, and a waiting banner sits on the amber wash (`--await`).
- **Proposed tag:** a dashed amber edge on the wash, with a ✎ before the word: agent output nobody has ratified yet.
- "Needs you" counts are square (2px).

### Evidence Paper
Source excerpts are shown as a sheet of paper.
- Serif 16px / 1.6 on `--paper` (a light sheet in both themes), with a hairline and `--r-sm` corners.
- The cited span gets the paper's amber highlighter mark (`--paper-mark`), the same amber in both themes.

### Lineage Trail
Where a value's history matters, a four-step trail shows source → extracted → reviewed → published: accent squares for done steps, amber for waiting on a person, red for a conflict, blue for running, hollow for not reached.

## Components

### Buttons
- **Shape:** `--r-md` (8px).
- **Primary:** accent (ink) fill, `--on-accent` text (white in light, dark in dark), 9px × 16px padding, weight 500.
- **Hover / Focus:** goes to Accent Ink; keyboard focus shows a 2px accent outline.
- **Secondary:** transparent with a hairline border and accent text; hover fills with the accent tint.
- **Link button:** accent text, no padding inside tables.
- **In tables:** per-row actions are compact outlined buttons (2px × 10px), never a column of solid primaries.
- **Disabled:** well fill and muted text; readable, never louder than live controls.

### Chips and Badges
- **Rating badge:** pastel (see Secondary colours), 2px corners.
- **Status pill:** an 8px square in the status colour, then the status word; no border (running is `--run` blue).
- **"Needs you" count:** amber fill with white text (Night: dark text), square (2px), on the top bar's Review Queue link. One number for everything waiting on a decision: open review items, open stewardship decisions and undecided ballots (`GET /api/waiting`); the label names each part. Hidden at 0 and when the count fails.
- **Tile strip:** related tiles (the Argus steps) sit in one bordered strip. Neighbours share a 1px edge, only the strip's outer corners are rounded, and a waiting, failed or focused tile draws its edge over its neighbours'. At 640px and below the strip stacks into one column.
- **Filter chips:** a list filter is a group of pill buttons with `aria-pressed` ("All", "Only mine"), exactly one pressed. The pressed chip has an `--accent-tint` fill and ink label, the others a muted label. 32px tall, 44px at 1024px and below.
- **Phone tables:** at 560px and below a stacked table's rows become cards (hairline, 8px corners, panel fill, 8px apart), each cell still labelled. The Argus runs card is compact: name and a status pill with a square dot on top, "N companies · step" under it, actions last.

### Cards / Containers
- **Corner Style:** `--r-lg` (12px).
- **Background:** panel (`--panel`).
- **Shadow Strategy:** none (see The Flat Card Rule).
- **Border:** 1px hairline; a card that waits on you takes the waiting edge.
- **Internal Padding:** 18px × 20px (28px × 24px on start-page cards).

### Inputs / Fields
- **Style:** panel fill, field border, `--r-sm`, 8px × 10px padding.
- **Rows:** fields in a row centre on one line and wrap as a group; checkbox labels and buttons never break mid-label.
- **Native controls:** checkboxes follow the accent; file pickers get a themed button.

### Navigation
- **Top bar:** on every page but the landing page, left to right: the ARP lockup (28px high, where the landing header puts it), search (⌘K), Ask ARP (⌘J), then Workspaces (a menu of Start and the five workspaces, each with its status square and word when it waits, runs or failed), Review Queue with the square signal count, Reports, and the user menu (reviewer name, sign-in, theme, Arcade). The current Review Queue or Reports link is underlined. On a phone it is two rows: lockup, search, Ask ARP and the user menu, then Workspaces, Review Queue and Reports; every control is 44px tall.
- **Workspace row:** inside a workspace, a 44px row under the top bar: the workspace's name, then its screens as plain links; the current one is underlined 2px in ink. It scrolls sideways inside itself on a phone and never widens the page.
- **Workspace overview header:** title, intro and the workspace drawing (120px) in three columns at 1100px and up, bottoms aligned; between 761 and 1099px the drawing sits top right of the stacked title and intro; hidden on phones. The drawing lights up like the workspace's start-page card (waiting amber, running blue).
- **Process flow** (workspace overviews): each step card is a button with `aria-expanded`; a click opens one details panel per process under its flow (step i of n, what it does, status square and word, the Now line, the latest run, an "Open <step> →" link, the only thing that navigates). Click the open step again or press Esc to close it. The running step has a `--run` edge, a soft `--run` ring and a pulsing status square (still under reduced motion); connectors after reached (done) steps are ink, the one into the running step is `--run`.

### Process Card (signature component)
The start page's five cards (StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub). Each card is one link: a figure area with a mono caption ("3 processes") and an isometric wireframe drawing of the workspace, the name, a one-line purpose, and one status line: an 8px square per process (ink = done, run colour = running, signal = waiting on you, red = failed, outlined = idle, dashed = unknown), the state in words (Waiting on you, Running, Last run failed, Up to date, No runs yet, Status unknown) and, where there is one, " · " and the process it concerns. There is no "Open →": the whole card is the link. A card that waits on you takes the waiting edge. The card carries no counts; waiting work is counted in the Review Queue badge. The start page has no Needs you list: each waiting item lives in the Review Queue or its workspace.

## Do's and Don'ts

### Do:
- **Do** read every colour from the tokens (`var(--hi)`, `var(--accent)`, `var(--text)`, …); both themes depend on it.
- **Do** use amber for exactly one meaning: a person must act (see The One Signal Rule).
- **Do** give anything that waits on a person the needs-you shape as well as the colour.
- **Do** keep text at 13px or larger and at ≥4.5:1 contrast in both themes.
- **Do** set titles and figures in Geist, IDs and state in the mono face, and keep the serif for quoted source text.
- **Do** let wide tables scroll inside their frame, with the edge shadow cue.

### Don't:
- **Don't** use amber for anything that doesn't wait on a person: not branding, not "running", not hover.
- **Don't** use brand orange anywhere but the logo apex and the landing animation.
- **Don't** put shadows on cards, tables, wells or inputs, or stack cards.
- **Don't** round markers: dots, steps and segments are square.
- **Don't** use emoji as icons or status markers; draw icons in the shared stroke family. (The ✎ on "Proposed" is a text glyph, not an icon.)
- **Don't** hard-code colours or fonts in components (third-party editors included); follow the live theme.
- **Don't** fade disabled or switched-off items with opacity; mark them with the well fill or a dashed edge and keep text legible.
