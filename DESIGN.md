---
name: ARP (Agentic Research Pipeline)
description: Countersign. Security-printing register where agents prepare and a named person countersigns.
colors:
  intaglio-green: "#173d33"
  intaglio-ink: "#0e2921"
  underprint: "#eef2ee"
  certificate-paper: "#fbfcfa"
  hairline: "#c9d4cd"
  well: "#e4ebe6"
  ink: "#17211d"
  muted-ink: "#4e5c56"
  on-accent: "#ffffff"
  stamp-violet: "#5b3fa0"
  stamp-violet-tint: "#ebe5f8"
  verified-green: "#1c6e47"
  caution-ochre: "#8a5a00"
  error-red: "#b0231b"
  neutral-grey: "#55625c"
  void-black: "#1d1d1b"
  chrome-text: "#e3ece7"
  chrome-muted: "#a9c2b8"
  chrome-field: "#1f4a3e"
  chrome-rule: "#2f5c4f"
  chrome-active: "#f1f4f0"
  chrome-stamp-edge: "#c9b8f5"
typography:
  engraved-title:
    fontFamily: "Cinzel, Trajan Pro, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "0.06em"
  wordmark:
    fontFamily: "Cinzel, Trajan Pro, Georgia, serif"
    fontSize: "1rem"
    fontWeight: 700
    letterSpacing: "0.14em"
  due-headline:
    fontFamily: "Source Sans 3, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  title:
    fontFamily: "Source Sans 3, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
  body:
    fontFamily: "Source Sans 3, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    fontFeature: "tnum"
  body-sm:
    fontFamily: "Source Sans 3, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
  label:
    fontFamily: "Source Sans 3, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 700
    letterSpacing: "0.06em"
  data:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    fontFeature: "tnum"
rounded:
  none: "0px"
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
    backgroundColor: "{colors.intaglio-green}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.intaglio-ink}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.intaglio-green}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-danger-outline:
    backgroundColor: "transparent"
    textColor: "{colors.error-red}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  input-field:
    backgroundColor: "{colors.certificate-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
    typography: "{typography.body}"
  nav-tab:
    backgroundColor: "transparent"
    textColor: "{colors.chrome-text}"
    rounded: "{rounded.md}"
    padding: "7px 10px"
    typography: "{typography.body-sm}"
  nav-tab-active:
    backgroundColor: "{colors.chrome-active}"
    textColor: "{colors.intaglio-green}"
  nav-count:
    backgroundColor: "{colors.stamp-violet}"
    textColor: "{colors.chrome-text}"
    rounded: "{rounded.pill}"
    padding: "1px 6px"
  certificate-band:
    backgroundColor: "{colors.certificate-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "22px 26px 18px"
    typography: "{typography.due-headline}"
  register-cell:
    backgroundColor: "{colors.certificate-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "12px"
  register-column-head:
    textColor: "{colors.muted-ink}"
    typography: "{typography.label}"
    padding: "8px 12px"
  proposed-tag:
    backgroundColor: "{colors.stamp-violet-tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "1px 8px"
  banner-await:
    backgroundColor: "{colors.stamp-violet-tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
  void-stamp:
    backgroundColor: "transparent"
    textColor: "{colors.void-black}"
    rounded: "{rounded.none}"
    padding: "0 6px"
  card:
    backgroundColor: "{colors.certificate-paper}"
    rounded: "{rounded.lg}"
    padding: "18px 20px"
---

# Design System: ARP (Agentic Research Pipeline)

## Overview

**Creative North Star: "Countersign"**

The app is set like security printing: a share certificate, a banknote, a registrar's stamp. A figure counts as final only once a named person has countersigned it, so the whole visual system exists to show where that has happened and where it hasn't yet. Intaglio green does the chrome and the rules. It sits on a pale green-grey underprint, and depth comes from ruled lines, not shadows. Engraved capitals are rare, used for page titles, the wordmark and the VOID stamp. Everything a person reads or operates is set in a plain, legible sans with tabular figures.

The system gives each colour one job. Stamp violet means one thing only: this is waiting on a person. It usually arrives with a dashed stroke, which reads as a signature line. Red means an error. A black stamp saying VOID, rotated like a rubber stamp, marks a failed run. The guilloche rosette is the one ornament, and it appears only on the certificate band and on the seal that engraves itself when a ballot is cast.

The density is a working register, not a dashboard. On the Start page the register is a ruled table between 2px green rules. There are no cards there, no greeting, no hero metric and no icon tiles. Every count names what it is made of.

**Key Characteristics:**
- Solid intaglio-green sidebar with its own light-on-green token set.
- Ruled registers bounded by 2px accent rules; hairline row rules inside.
- Stamp violet plus dashed stroke means "awaiting a person" and nothing else.
- Cinzel capitals for page titles, the wordmark and the VOID stamp only.
- Source Sans 3 with tabular figures for all read or operated text; IBM Plex Mono for raw data.
- One guilloche rosette, used on the certificate band and on seals.
- Flat surfaces; shadow only on things that genuinely float.

## Colors

A single-ink security-print palette: intaglio green on a green-grey underprint, with three stamp colours that each carry one meaning.

### Primary
- **Intaglio Green** (`intaglio-green`): chrome and authority. It is the sidebar and phone top-bar ground, primary buttons, the 2px register rules, the certificate band's outer border, section headings on Start, serial numbers, links and the "running" step mark. **Intaglio Ink** (`intaglio-ink`) is its hover state.

### Secondary
- **Stamp Violet** (`stamp-violet`) and **Stamp Violet Tint** (`stamp-violet-tint`): waiting on a person. Used for the edge colour and figures (due counts in the band, the countersign column, dashed step marks, awaiting tags). The tint fills awaiting banners, proposed tags, nav counts and awaiting stat cells. Inside the green chrome the local tokens swap: `stamp-violet` becomes the fill and `chrome-stamp-edge` the edge.

### Tertiary
- **Verified Green** (`verified-green`): finished and success, including ticked step marks, success banners, the "running" tag on Start and the cast seal stroke.
- **Caution Ochre** (`caution-ochre`): partial completion, stalled runs and warnings.
- **Error Red** (`error-red`): errors only, meaning error banners, error text, danger buttons and failed status pills.
- **Void Black** (`void-black`): failed runs, drawn as the VOID stamp and the struck-through step mark.

### Neutral
- **Underprint** (`underprint`): page ground.
- **Certificate Paper** (`certificate-paper`): panels, band, register rows, inputs.
- **Hairline** (`hairline`): 1px borders and row rules.
- **Well** (`well`): recessed fills (row hover, progress track, JSON and quote wells).
- **Ink** (`ink`) and **Muted Ink** (`muted-ink`): body text and secondary text (14.6:1 and 6.2:1 on underprint).
- **Neutral Grey** (`neutral-grey`): cancelled, a person's choice and not a failure.
- **Chrome set** (`chrome-text`, `chrome-muted`, `chrome-field`, `chrome-rule`, `chrome-active`): the sidebar and top bar redefine `--text`, `--muted`, `--panel`, `--panel-border` and `--accent` locally, so every control inside inherits light-on-green without per-component rules.

Dark mode (system setting, or pinned by `data-theme` on `<html>`) redefines every token as the same certificate at night: a green-black ground, pale-ink controls and a lighter stamp violet. Values are in the sidecar.

### Named Rules
**The One Colour, One Meaning Rule.** Violet means waiting on a person, red means error, and void black means a failed run. Nothing automated ever uses violet, and no colour borrows another's meaning.

**The Signature Line Rule.** When something awaits a person, draw it with a dashed violet stroke (1 to 1.5px, `stamp-violet`): the unsigned reviewer field, proposed agent output, awaiting step marks and hub steps, the countersign column's signature line, and the awaiting stat cell. Once a person decides, it turns solid. The only other dashed status in the build is the ochre "stalled" pill.

## Typography

**Display Font:** Cinzel 600/700 (with Trajan Pro, Georgia)
**Body Font:** Source Sans 3 400/600/700 and 400 italic (with the system sans stack); also `--font-display`
**Label/Mono Font:** IBM Plex Mono 400/500 (with ui-monospace)

All three are self-hosted through @fontsource.

**Character:** Engraved Roman capitals give the certificate its authority. A humanist sans with tabular figures keeps every number legible on a projector.

### Hierarchy
- **Engraved title** (Cinzel 700, 1.5rem, 1.25, +0.06em): page `h2` titles on inner pages, balanced wrap.
- **Wordmark** (Cinzel 700, 1rem, +0.14em): the "ARP" wordmark and the sidebar mark.
- **Due headline** (Source Sans 3 600, 1.75rem / 1.35rem under 760px, 1.25, -0.01em, max 34ch): the Start band's due sentence. Its counts are upright `stamp-violet` tabular figures.
- **Title** (Source Sans 3 600, 1rem): section heads and card `h3`s. On Start they are set in intaglio green.
- **Body** (Source Sans 3 400, 0.9375rem): all running text. Ledes are capped at 72ch with 1.55 line height.
- **Body small** (0.875rem): help text, meta, prepared-by, process purposes.
- **Label** (Source Sans 3 700, 0.8125rem, +0.06em, uppercase): register column heads and state tags. Nav group labels use the same case at weight 600, +0.05em.
- **Data** (IBM Plex Mono): raw data only, such as JSON editing, level conditions, node numbers, rail counts and `kbd`. Register serials are sans with tabular figures, not mono.

### Named Rules
**The Engraving Is Rare Rule.** Cinzel appears on page titles, the wordmark and the VOID stamp, and nowhere else. Nothing a person reads at length or operates is set in capitals-only engraving.

**The 13px Floor Rule.** No text is set below `--text-xs` (0.8125rem). The type scale was raised for screen-share legibility.

## Layout

The layout is a sidebar-and-main shell. The sidebar is 232px wide, sticky and full height. The main area has 32px/36px padding with an 80px bottom, and pages are capped at 1200px. Spacing uses a 4px base (`s-1` to `s-12`): tight steps inside a group, 32px (`s-8`) between groups. A page header (title, lede, page tabs) reads as one tight group with a 32px gap before the working area.

Start stacks three blocks: the certificate band, then the ruled register ("Register of processes"), then "Runs needing attention". Each section head is a baseline-aligned row, with the title on the left and a muted gloss or link on the right, and 32px above it.

Responsive behaviour:
- **Under 760px:** the sidebar becomes an off-canvas drawer (min(288px, 85vw)) behind a 53px sticky green top bar that names the current page. Touch targets grow to 44px and main padding drops to 24/16/48px. Register rows become three-column grids: serial, process and open stay on the first line, and every other cell spans the full width below.
- **Under 560px:** data tables marked stack-on-phone turn into labelled rows. Columns are never hidden behind a sideways scroll.
- **Under 900px:** split review panes and process flows stack.
- **At 1180px and up:** the dashboard gets a 2:1 column split.

## Elevation & Depth

This world gets its depth from rules, not shadows. Resting surfaces are flat and bounded by 1px hairlines or 2px intaglio rules. The certificate band gets its engraved look from a double border: a 1px green outer rule and a hairline inset 5px inside it. Shadows are reserved for things that float (the modal dialog, the open drawer, chart tooltips) and for the sticky cast bar lifting off the ballot.

### Shadow Vocabulary
- **Float** (`--shadow-md`): chart tooltips.
- **Overlay** (`--shadow-lg`): modal dialogs and the open nav drawer.
- **Cast bar lift** (upward 16px, 8% green-black): the sticky ballot cast bar only.
- **Focus halo** (3px `accent-tint` ring): focused inputs.

### Named Rules
**The Rules, Not Shadow Rule.** A resting surface never carries a drop shadow. Separate things with hairlines and 2px accent rules.

## Shapes

The shape language has two registers. Printed objects are square: the certificate band, register tables, 2px rules and the VOID stamp all have 0 radius. Operated controls take gentle corners: buttons, inputs and nav tabs at 8px, tabs, wells and tooltips at 6px, and panels, dialogs and cards at 12px. Counts, badges, chips and progress tracks are pills. Step marks are ruled 22px circles (16px in the legend) with a 1.6px round-capped stroke. The VOID stamp is a 2px-bordered box rotated -4 degrees.

## Components

### Buttons
- **Shape:** gently rounded (8px).
- **Primary:** intaglio green fill with white text, 9px 16px padding, weight 500. On hover it deepens to intaglio ink. When disabled it drops to 50% opacity.
- **Secondary:** transparent with a green label and a 1px hairline border. On hover it takes the accent tint and a green border. The quiet action next to a primary is always a real bordered button, never bare text.
- **Danger outline:** transparent with a red-toward-ink label and a 1px red border, used for Reject so it never competes with the primary as a second solid button.
- **Link button:** green underlined text with a 1px underline offset 0.15em. It is used for inline recovery ("Retry") and "Change".
- **Focus:** a 2px intaglio-green outline at 2px offset on every interactive element.

### Chips
- **Status pill:** a 1px border in the state colour with matching text at 13px (running green, completed verified-green, partial or stalled ochre, failed red, cancelled neutral). Stalled is dashed.
- **Chip:** a well fill, hairline border and muted text.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** certificate paper with a 1px hairline border and 18px 20px padding.
- **Shadow Strategy:** none (see Elevation).
- Cards hold working screens such as ballots and settings. The Start page doesn't use them.

### Inputs / Fields
- **Style:** certificate paper, 1px hairline, 8px radius, 8px 10px padding, body size.
- **Focus:** the border turns intaglio green and a 3px accent-tint halo appears.
- **Awaiting:** the reviewer ("Deciding as") field with no name takes a 1.5px dashed stamp-violet border, because a person has to sign there. A hint underneath states that the name is typed, not verified.

### Navigation
- **Sidebar:** solid intaglio green. At the top are the wordmark and then the reviewer field, so the person deciding is the first thing set. Group labels are uppercase and muted. Tabs are 8px-radius rows with inline SVG icons. Hover fills them with the chrome rule colour. The active tab turns pale (`chrome-active`) with green text at weight 600. "Needs you" entries carry a violet pill count.
- **Mobile:** a 53px green top bar with a 44px menu button and the page name, and a drawer that slides in over a scrim (220ms, disabled under reduced motion).
- **Page tabs:** outlined 6px tabs. The active one gets a panel fill and a green inset ring. They are never filled pills.

### Certificate Band (signature)
This is the bordered band at the top of Start. It has a 1px green outer rule, a hairline inset rule 5px in, and square corners. Its heading is the due sentence, followed by an "As of" meta line. The guilloche rosette is clipped at the top-right corner: five rings crossed by six rotated ellipses, stroked green at 0.7 width and 22% opacity.

### Ruled Register (signature)
This table sits between 2px intaglio rules, with a 1px green rule under the head and hairlines between rows. The columns are serial (green, 700, +0.06em, e.g. "SIQ 0001"), process (bold name over a muted purpose), step marks, prepared, countersign and open. Countersign is the primary action column. It shows a dashed violet signature line over "N awaiting:" with each part linked by name, or "Nothing to sign" in muted text. Below it, a legend defines the step-mark vocabulary for every process view.

### Step Marks (signature)
Each mark is a ruled circle. Idle is a hairline circle. Done is a verified-green circle with a tick. Running is an intaglio circle with a filled dot. Awaiting is a dashed violet circle. Failed is a void circle struck through.

### VOID Stamp (signature)
A failed run shows VOID in Cinzel 700 capitals at +0.2em inside a 2px void-black border, rotated -4 degrees. This is the only failure marker in registers. Red is kept for errors.

### Cast Bar and Seal (signature)
On a ballot, the cast action rides a sticky bar at the bottom of the card, with a 2px green top rule and a lifted shadow, so it never scrolls away on a phone. Casting shows a success banner with the rosette seal (44px, verified-green stroke), which engraves itself stroke by stroke over 1.1s. Under reduced motion the seal appears already drawn.

### Proposed (agent output not yet ratified)
This container has a dashed violet border, an 8px radius and a 35% violet-tint fill, topped by a dashed "proposed" tag. It turns solid, with a name, once a person decides.

## Do's and Don'ts

### Do:
- **Do** bound registers with 2px intaglio-green rules and separate rows with 1px hairlines.
- **Do** use stamp violet with a dashed stroke for anything waiting on a person, and switch it to solid once someone signs.
- **Do** mark a failed run with the rotated VOID stamp in void black, and keep red for errors.
- **Do** build every count from named parts ("6 awaiting: 3 ballot items, 3 stage decisions"), and show "Unknown" rather than zero before data arrives.
- **Do** set every figure in tabular numerals.
- **Do** draw icons as inline SVG strokes (nav icons, step marks).
- **Do** keep the rosette to the certificate band and the cast seal.

### Don't:
- **Don't** use stamp violet for anything automated, decorative or merely "selected".
- **Don't** open the Start page with a greeting, a hero metric, icon cards or stat tiles. It is a ruled register under one certificate band.
- **Don't** put a small uppercase kicker or eyebrow above a heading.
- **Don't** use text glyphs (arrows, triangles, emoji) as icons.
- **Don't** set body, labels or controls in Cinzel. Engraving is for titles, the wordmark and the VOID stamp.
- **Don't** give resting surfaces a drop shadow.
- **Don't** set any text below 0.8125rem.
