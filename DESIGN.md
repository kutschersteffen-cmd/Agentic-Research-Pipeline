---
name: Agentic Research Platform
description: A black instrument panel with a gold holographic Orb for the agents, where amber lights up only when a person must act.
colors:
  ink: "#eceef2"
  accent: "#eceef2"
  accent-ink: "#ffffff"
  accent-tint: "rgb(236 238 242 / 0.08)"
  ground: "#000000"
  panel: "#0b0c0f"
  panel-2: "#101217"
  hairline: "rgb(255 255 255 / 0.10)"
  hairline-strong: "rgb(255 255 255 / 0.18)"
  field-border: "#6d7889"
  well: "#101217"
  muted: "#9aa3b2"
  text-2: "color-mix(in oklch, #eceef2 80%, #9aa3b2)"
  signal-amber: "#e0b25a"
  signal-amber-wash: "rgb(224 178 90 / 0.14)"
  status-high: "#4fd69c"
  status-mid: "#f2c94c"
  status-low: "#ff6b7a"
  status-run: "#5fb0ff"
  status-neutral: "#9a9ba0"
  sidebar: "#050506"
  paper: "#f5f2ea"
  paper-mark: "#f6ecd6"
  brand-orange: "#ff6a2b"
  orb-gold: "#ff8f1f"
  orb-ice: "#249eff"
  orb-ember: "#ff451a"
  orb-mint: "#1aeb9e"
typography:
  display:
    fontFamily: "Geist Pixel Square, Geist Mono, ui-monospace, monospace"
    fontSize: "clamp(52px, 7.2vw, 104px)"
    fontWeight: 400
    lineHeight: 0.92
    letterSpacing: "0"
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
    fontFamily: "Geist Pixel Square, Geist Mono, ui-monospace, monospace"
    fontSize: "clamp(40px, 5.4vw, 80px)"
    fontWeight: 400
    lineHeight: 0.96
    letterSpacing: "0"
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  marker: "0"
  pill: "999px"
shadows:
  float: "0 2px 6px rgb(0 0 0 / 0.4), 0 8px 24px rgb(0 0 0 / 0.5)"
  overlay: "0 12px 32px rgb(0 0 0 / 0.6)"
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

# Design System: Agentic Research Platform

## Overview

**Creative North Star: "The Annotated Report"**

ARP is a calm instrument panel for teams that run long agent pipelines and ratify what the agents propose. It reads like a well-kept research report: ink on a black ground, titles and figures in one engineered sans, and every number traceable to the page it came from. One colour, amber, is reserved for one reason only: a person must act. When nothing waits on anyone, no amber appears.

The system is precise and quiet. Cards are flat panels set off by a hairline; Geist carries titles, figures, text and controls, Geist Mono carries IDs and state, and a serif appears only where text is quoted from a source. Density is high enough for tables of thousands of companies while staying legible on a projector. There is one theme: black. Every component reads its colours from the same tokens.

**Key Characteristics:**
- Black ground, ink accent for controls, amber reserved for 'waiting on a person'.
- Status colours (green / amber-brown / red / blue) describe runs and ratings, never the person-must-act state.
- Cards are flat: a panel fill and a hairline, no shadow.
- Geist for titles, figures and reading; Geist Mono for IDs, labels and state; a serif only for quoted source text.
- Five signature elements carry the identity: the Pixel mark language, the needs-you shape, evidence paper, the Orb and the status rail.
- The start page leads with the five workspaces; everything else is reached from them.
- The Orb, a gold hologram, stands for the agents; it is the only place where colour is spectacle.

## Users and principles

**Users.** Primary: a stewardship and ESG team at an asset manager, who run engagement, decide proxy votes and assess transition plans and barriers. The research functions (thematic universes, extraction, index construction, strategy replication) serve them and adjacent analysts, and are secondary.

**Operating context.** ARP is often screen-shared in committees and client meetings, and used on phones, laptops, wide screens and projectors. Phone use is real: checking a run, a stalled issue or a pending vote away from the desk.

**Principles.**
1. Provenance over polish: a figure without its source is unfinished.
2. Propose, never apply: automation suggests, a named person decides.
3. Show the uncertainty: guesses, gaps and rank ranges are surfaced, never smoothed away.
4. Legible in the room: the screen must read when shared, to people who did not drive it.
5. Same truth at every size: a phone shows fewer things, never a different or less-sourced answer.

**Terms to keep.** run, Needs you (the review queue), grounded / ungrounded citation, ratify, calibration, escalation stage, walk / talk, tier.

**Evidence and accessibility.** No customers, testimonials, benchmarks or pricing exist; none may be invented. WCAG 2.1 AA is the working bar, plus projector and screen-share legibility.

## Colors

An ink-on-black palette with one reserved signal and a small set of status colours.

### Primary
- **Accent** (`--accent`: ink, #eceef2): primary buttons, links, done-step dots and lineage steps that are complete. Hover goes to **Accent Ink** (#ffffff); a faint **Accent Tint** (`--accent-tint`) backs secondary-button hover and a pressed filter chip.
- **Ink** (`--text`: #eceef2): all text and structural lines.
- **Signal Amber** (#e0b25a): the one colour for "a person must act": the "Needs you" count in the top bar, waiting step dots and borders, proposed-not-ratified items. It is text-safe on the ground, the panel and the well; its wash (amber at 14%) backs waiting tiles and pending banners.

### Secondary
- **Status High / Mid / Low / Run / Neutral** (green, yellow, red, blue, grey; see frontmatter): run status pills, escalation stage, H/M/L ratings. Rating badges are pastel: a 16% tint of the status colour with a label mixed 62% status / 38% ink and a 32% tint border. Labels sit at text contrast (≥4.5:1) on every ground they appear on.

### Neutral
- **Ground** (`--bg`: #000000): the page.
- **Panel** (`--panel`: #0b0c0f): cards, tables, inputs. A card is set off from the ground by its hairline; there is no card shadow.
- **Hairline** (`--panel-border`: white at 10%): every border and divider; white at 18% (`--panel-border-strong`) is the hover edge.
- **Field Border** (#6d7889): the edge of form fields only; it clears 3:1 on the field and the page (WCAG 1.4.11), which the hairline does not.
- **Well** (#101217): recessed areas, disabled controls, hover rows, the Ask panel's header and form.
- **Muted** (#9aa3b2): secondary text and labels; ≥4.5:1 on ground, panel and well.
- **Secondary text** (`--text-2`: 80% ink, 20% muted): page intros, process descriptions and start-card purposes. Meta lines and captions stay muted.

### Named Rules
**The One Signal Rule.** Amber means one thing only: a person must act. Never use it for branding, decoration, hover, focus of a normal control, or "running". When nothing waits, no amber appears anywhere on the screen. The Orb's gold is not amber and is exempt (see The Orb Colour Rule). Keyboard focus is an accent outline. A proposed item's box is neutral; only its "Proposed" tag and the needs-you shape carry the signal, so a queue never turns into a wall of amber. The flagged vote that needs a second person takes the signal border.

**The Brand Colour Rule.** Brand orange (#ff6a2b) appears in two places only: the logo apex and the square of the landing caption. It never appears elsewhere in the interface, so it cannot be mistaken for the amber signal.

**The Orb Colour Rule.** The Orb is gold and morphs through ice, ember and mint. These four colours live only inside the Orb's canvas and its phase label. They carry no meaning: they are not status and not the signal. Nothing outside the Orb may use them, and the Orb never uses `--hi`.

**Provenance Is Not Status.** Where a number came from (live, synthetic sample, portfolio holdings, not built) is shown with neutral marks: filled, half, ring, dashed ring. Metric numbers are ink. Green, amber-brown and red stay for status.

**The Status Is Not The Signal Rule.** Status colours describe runs and ratings. Red marks a failed run and also a Low (L) rating on Transition Barriers; that second use is a deliberate, confirmed exception, because the matrix reads as a traffic light. It never marks something waiting on a person.

**Chart Colours.** Charts with categories use four slots, `--cat-1` to `--cat-4` (blue, magenta, gold, violet; `lib/palette.ts` explains the validation). They are neither status nor signal. Board diagrams colour up to four flowchart groups with `--cat-1`, `--cat-4`, `--cat-2`, then `--muted`, never gold or amber, because amber means a person must act.

**The Arcade Exception.** The hidden arcade games draw in their own neon palette. They sit outside the product and are the only place where neon is decoration.

**The Icon Accent Rule.** Each workspace drawing has exactly one element that can light up: in the signal colour (`--hi`) when the workspace waits on someone, in the running colour (`--run`) when it runs. Otherwise the whole drawing is a quiet wireframe. The lit element is out of place while lit (lifted or taller) and moves once, in 850ms, when the status changes. Nothing else in a drawing moves.

## Typography

**Title, Figure and Body Font:** Geist (system sans fallback), `--font-display` for titles
**Label / Mono Font:** Geist Mono
**Source Font:** Source Serif 4 (Georgia fallback), for quoted source text only
**Pixel Font:** Geist Pixel Square, for the landing headline, the start-page greeting and the five workspace titles only

**Character:** a report voice in one engineered sans. Titles and big figures are Geist at medium weight with tight tracking; running text and controls are Geist; a monospace carries IDs, step labels and state, so data never shifts width. The serif is kept for text that comes from a document, so a quotation looks quoted.

### Hierarchy
The CSS scale tokens are `--text-xs` (13px), `--text-sm` (14px), `--text-base` (15px), `--text-md` (16px), `--text-lg` (22px) and `--text-xl` (24px).

- **Display** (Geist Pixel Square 400, clamp(52px → 104px), 0.92): the start-page greeting; the workspace titles use the same face at clamp(48px → 92px)
- **Headline** (Geist 500, clamp(1.75rem → 2.5rem), 1.05, `--track-display`): page titles.
- **Title** (Geist 500, 1.25rem, `--track-title`): card titles and workspace card names. Section and card headings under 20px stay at their bolder weight.
- **Figure** (Geist 500, 2rem, tabular): the big number on stat tiles.
- **Body** (sans 400, 0.9375rem / 15px, 1.45): all running text and controls; keep help text to about 70ch.
- **Label** (mono 500, 0.8125rem / 13px): counts, run IDs, step labels, chips, table meta. 13px is the floor for any text.

### Named Rules
**The Serif Means Source Rule.** The serif is for text quoted from a source document (the evidence paper). Nothing else uses it.

**The Pixel Means Presence Rule.** Pixel type marks the three places where ARP presents itself: the landing headline, the greeting and a workspace's title. Never set running text, tables or controls in it.

**The Mono Means Data Rule.** Mono is for IDs, labels and state. Never set a sentence of prose in mono for a "technical" feel.

- **Tracking by size band:** `--track-display` (−0.025em) for page titles, `--track-title` (−0.015em) for card and section titles, `--track-body` (−0.008em) for body text. `kbd` and `code` keep normal tracking.
- **Heading weight:** headings of 20px and up are 500; smaller ones keep their weight.
- **Page intro:** above 760px the paragraph under a page title is a 17px lead in `--text-2`, capped at 62ch.
- **Motion:** `--dur-fast` (100ms) for colour hovers, `--dur` (140ms) with `--ease` for state changes, `--dur-slow` (240ms) with `--ease-out` for bars and panels.

## Layout

Spacing runs on a 4px base (4, 8, 12, 16, 24, 32, 48), plus two half steps for dense parts: 2px (`--s-0_5`: the nav stack, segmented bars, compact pills and row buttons) and 6px (`--s-1_5`: chip rows, icon-to-label gaps). New padding, margin and gap values read from these tokens rather than raw pixels. Groups are tight (8–12px inside), sections are generous (24–48px between). There is no sidebar. One top bar runs across every page but the landing page (lockup, search, Ask ARP, Workspaces, Review Queue, Reports, user menu); inside a workspace a slim workspace row sits under it, so every page gets the full width for tables and diagrams. The start page is the hero (the Orb, the greeting, one sentence of counts), then the five workspace cards in one row (three per row at 1180px and below, two at 760px, one at 480px). Wide tables scroll inside their frame and show a shadow on any edge with more columns; tables never push the page sideways.

## Elevation & Depth

Cards are flat. A card is a panel with a hairline on the black ground; tables, wells and inputs stay flat inside it. Only things that genuinely float take a shadow.

### Shadow Vocabulary
- **Float** (`--shadow-md`: `0 2px 6px rgb(0 0 0 / 0.4), 0 8px 24px rgb(0 0 0 / 0.5)`): popovers, menus and the hover lift on pipeline and flow cards.
- **Overlay** (`--shadow-lg`: `0 12px 32px rgb(0 0 0 / 0.6)`): modals.

### Named Rules
**The Flat Card Rule.** Cards and stat tiles take a hairline, never a shadow. Nothing inside a card takes a shadow. Never stack a card on a card. Glows are status light, not elevation: a start card or process panel that runs or waits, its figure area and the lit part of its drawing glow in the status colour. Nothing else glows.

## Shapes

Containers are softly rounded; markers are square. Buttons use `--r-md` (8px), inputs `--r-sm` (6px), cards and tiles `--r-lg` (12px), chips and pills `--r-pill`. Everything that marks state is square, taken from the Pixel A grid: status dots, lineage steps, count badges (2px) and chart segments. Borders are 1px hairlines; a dashed edge marks something proposed and not yet ratified.

## Signature Elements

Five elements make an ARP screen recognisable. Use them as specified; don't invent variants.

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
- Serif 16px / 1.6 on `--paper` (a light sheet on the black page), with a hairline and `--r-sm` corners.
- The cited span gets the paper's amber highlighter mark (`--paper-mark`).

### Lineage Trail
Where a value's history matters, a four-step trail shows source → extracted → reviewed → published: accent squares for done steps, amber for waiting on a person, red for a conflict, blue for running, hollow for not reached.

### The Orb
The visual for ARP's agents: a gold holographic sphere whose parts turn in steps, fold and lock. It appears on the landing page, the start page, a workspace's Ask ARP card and the Agent screen, once per page. Hover previews the next colour, a click transforms it. Without WebGL, under reduced motion or on a slow GPU it is a still picture. Never draw streams into or out of it.

### Status Rail
Processes and steps are shown as a rail of 10px segments, 3px apart: solid ink = done, blue and flowing = running, amber and breathing = waiting on you, red = failed, outlined = idle, dashed = unknown or planned. Under reduced motion nothing flows or breathes.

## Components

### Buttons
- **Shape:** `--r-md` (8px).
- **Primary:** accent (ink) fill, `--on-accent` text (black), 9px × 16px padding, weight 500.
- **Hover / Focus:** goes to Accent Ink; keyboard focus shows a 2px accent outline.
- **Secondary:** transparent with a hairline border and accent text; hover fills with the accent tint.
- **Link button:** accent text, no padding inside tables.
- **In tables:** per-row actions are compact outlined buttons (2px × 10px), never a column of solid primaries.
- **Disabled:** well fill and muted text; readable, never louder than live controls.

### Chips and Badges
- **Rating badge:** pastel (see Secondary colours), 2px corners.
- **Status pill:** an 8px square in the status colour, then the status word; no border (running is `--run` blue).
- **"Needs you" count:** amber fill with black text, square (2px), on the top bar's Review Queue link. One number for everything waiting on a decision: open review items, open stewardship decisions and undecided ballots (`GET /api/waiting`); the label names each part. Hidden at 0 and when the count fails.
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
- **Top bar:** on every page but the landing page, left to right: the ARP lockup (28px high, where the landing header puts it), search (⌘K), Ask ARP (⌘J), then Workspaces (a menu of Start and the five workspaces, each with its status square and word when it waits, runs or failed), Review Queue with the square signal count, Reports, and the user menu (reviewer name, sign-in, Arcade). The current Review Queue or Reports link is underlined. On a phone it is two rows: lockup, search, Ask ARP and the user menu, then Workspaces, Review Queue and Reports; every control is 44px tall.
- **Workspace row:** inside a workspace, a 44px row under the top bar: the workspace's name, then its screens as plain links; the current one is underlined 2px in ink. It scrolls sideways inside itself on a phone and never widens the page.
- **Workspace overview header:** a caption, the pixel title, the intro and a status line on the left; the workspace drawing in a 300 × 240px figure box on the right (full width under the status line on phones). The drawing lights up like the workspace's start-page card. With asking allowed, an Ask ARP card with the Orb and a question box is the right column (above the process panels at 1080px and below).
- **Process flow** (workspace overviews): each step card is a button with `aria-expanded`; a click opens one details panel per process under its flow (step i of n, what it does, status square and word, the Now line, the latest run, an "Open <step> →" link, the only thing that navigates). Click the open step again or press Esc to close it. The running step has a `--run` edge, a soft `--run` ring and a pulsing status square (still under reduced motion); connectors after reached (done) steps are ink, the one into the running step is `--run`.

### Process Card (signature component)
The start page's five cards (StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub). Each card is one link: a figure area with a mono caption ("3 processes") and an isometric wireframe drawing of the workspace, the name, a one-line purpose, and one status line: a status rail with one segment per process, the state in words (Waiting on you, Running, Last run failed, Up to date, No runs yet, Status unknown) and, where there is one, " · " and the process it concerns. When a process runs, the status line names the running step and its position ('Spot · step 1 of 7'). There is no "Open →": the whole card is the link. A card that waits on you takes the waiting edge. The card carries no counts; waiting work is counted in the Review Queue badge. The start page has no Needs you list: each waiting item lives in the Review Queue or its workspace.

## Do's and Don'ts

### Do:
- **Do** read every colour from the tokens (`var(--hi)`, `var(--accent)`, `var(--text)`, …); the theme depends on it.
- **Do** use amber for exactly one meaning: a person must act (see The One Signal Rule).
- **Do** give anything that waits on a person the needs-you shape as well as the colour.
- **Do** keep text at 13px or larger and at ≥4.5:1 contrast.
- **Do** set titles and figures in Geist, IDs and state in the mono face, and keep the serif for quoted source text.
- **Do** let wide tables scroll inside their frame, with the edge shadow cue.

### Don't:
- **Don't** use amber for anything that doesn't wait on a person: not branding, not "running", not hover.
- **Don't** use brand orange anywhere but the logo apex and the landing caption.
- **Don't** use the Orb's colours outside the Orb.
- **Don't** animate a drawing while its status is unchanged.
- **Don't** put shadows on cards, tables, wells or inputs, or stack cards.
- **Don't** round markers: dots, steps and segments are square.
- **Don't** use emoji as icons or status markers; draw icons in the shared stroke family. (The ✎ on "Proposed" is a text glyph, not an icon.)
- **Don't** hard-code colours or fonts in components (third-party editors included); follow the live theme.
- **Don't** fade disabled or switched-off items with opacity; mark them with the well fill or a dashed edge and keep text legible.
