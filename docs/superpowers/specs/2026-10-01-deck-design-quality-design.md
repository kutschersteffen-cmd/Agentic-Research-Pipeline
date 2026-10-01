# Deck design quality: design

Status: draft for review · Extends the house-deck pipeline (`docs/superpowers/specs/2026-09-30-automated-decks-design.md`)

## Goal

House decks must look professionally designed: editorial/product style (Stripe, Linear). That means:
- big type
- whitespace that is intended, not left over
- one strong visual per slide
- no near-empty slides and no plain bullet slides

Today the decks fit, read cleanly and follow the style, but the layouts themselves are sparse. The first real deck showed this: the TPA pitch, `rpt_539893ef602b` on 2026-10-01. Its title slide was weak, its bullet slides used only the top third, and its table text was 20px.

## Decisions

| Question | Decision |
|---|---|
| Where design skill is missing | All four: the layouts, layout choice per slide, a reusable Claude skill, and the visual review |
| Reference style | Editorial / product (Stripe, Linear) inside the locked DESIGN.md system |
| Approach | Redesigned layout library, deterministic art director, measured design check, one shared design-rules file |
| Role of `/impeccable` | Design-time only: it redesigns the layouts and runs critiques in dev sessions. The production runtime calls the Claude API and cannot use Claude Code skills |

Unchanged:
- DESIGN.md: monochrome, ink metric numbers, mono labels, square corners, light and dark.
- The fit rules: fonts never shrink below the role size, and the loop shortens, then uses a roomier layout, then splits.
- Headlines are never rewritten.

## 1. Layout library v2

Every layout follows three rules:

1. **One focal element.** The slide's largest type is a number, a statement, a chart or a diagram, never a paragraph.
2. **Fill by design.** The layout places its content to fill the body area. When content is short, it uses a larger fixed type step (for example body text 28 → 36px, from the token scale). It never stretches or scales freely.
3. **No plain bullet slides.** Lists render as cards, steps or stat rows.

| Layout | Use | Variants |
|---|---|---|
| `statement` | one big claim | with support line, without |
| `cards` | parallel points | 3, 4 (mono number + short title + one line) |
| `steps` | sequence or process | 3, 4, 5 (numbered nodes on a connector) |
| `stat_row` | key figures | 1 (hero), 2, 3, 4 |
| `split` | claim plus evidence | evidence = chart, table or list |
| `chart_focus` | one exhibit | full width with one in-chart callout |
| `compare` | before/after, us/them | two mirrored panels |
| `title`, `section`, `quote`, `table`, `summary` | kept and redesigned | larger title, a section number, table type of 24px or more |

- Existing layout ids stay loadable, so old plans and stewardship decks still render. `deck_compat` and the art director map `bullets` to `cards` (or to `steps` when the content is ordered).
- The redesign is done with `/impeccable`: `critique`, then `layout`, `typeset` and `polish`. It runs on the stress deck and the TPA pitch deck in both modes.
- A sample PDF goes to the user for approval before the later steps build on it.
- Slot word and item limits are re-measured with the stress deck, as before.
- The PPTX export gets the same new layouts from the same grid rectangles.

## 2. Art director

`arp/reporting/art_direct.py` is deterministic and makes no LLM calls. It runs after slide fill and before lint.

**Content shape to layout:**

| Content | Layout |
|---|---|
| one number and a label | `stat_row/1` |
| 2–4 numbers | `stat_row/N` |
| 3–4 parallel items, each under 12 words | `cards/N` |
| ordered items (dates, "first/then", numbered) | `steps/N` |
| one sentence, no data | `statement` |
| a chart and 1–2 sentences | `chart_focus` (`split` when the text is over 25 words) |
| two contrasting blocks | `compare` |

**Rhythm rules across the deck:**
- never the same layout on three consecutive slides
- at least one visual slide (chart, numbers or steps) in every three content slides
- a `section` divider every 5–7 slides in decks of 12 or more

When a rule breaks, the next layout that fits the same content shape is used.

**Other behaviour:**
- The model's layout pick is a hint. The content-shape rules win.
- Every change is logged as `Finding(stage="design", rule="relayout", severity info)`, for example "slide 5: bullets → cards (3 parallel items)". The findings list shows these as info, not as problems.
- The rules live in one table in code, with one test per rule.

## 3. Measured design check

`browser.measure` adds design rules with `stage="design"`. They are computed from the boxes it already collects:

| Rule | Fails when |
|---|---|
| `sparse` | content covers less than 55% of the body area height |
| `unbalanced` | the content's centre of mass is more than 20% off the body centre, beyond what the layout intends |
| `small_text` | any rendered text is under 24px |
| `no_focal` | the largest text is less than 1.6× the body size |
| `crowded` | text blocks are closer than the token gutter |

**Handling a failing slide:**
- It goes back to the art director once, for its next fitting layout, and is measured again.
- If it still fails, the finding is kept and shown. Nothing ships silently.

**Visual QA:** the visual QA prompt takes its checklist from `design.md`:
- focal point and hierarchy
- intended whitespace
- rhythm
- the slide-relevant items of impeccable's craft floor

Its edit limits are unchanged.

**CI:**
- The stress deck and the 4 golden decks assert zero `design` findings.
- `impeccable detect` is a dev-time check run through the skill, not in CI, because the plugin is not installed there. When it runs, it ignores the brand font and headline leading.

## 4. Shared design rules and the Claude skill

**`backend/arp/reporting/style/design.md`** (about 1.5 pages) is the single source. It holds:
- the editorial principles
- the layouts and what each is for
- the content-to-layout table
- the rhythm rules
- the focal and whitespace rules
- 4 before/after examples

It is injected into the slide-fill prompt (so the model suggests layouts well) and into the visual QA prompt.

**`.claude/skills/deck-design/SKILL.md`** triggers on requests to make or improve decks or slides. It tells the agent to:
1. build through the house-deck pipeline, never by hand-writing a PPTX
2. read `style/design.md`
3. look at the rendered PNGs and run `/impeccable critique` on the deck HTML
4. change layouts or tokens through the library, never by editing a single deck

The skill reads the runtime's `design.md`, so the two cannot drift apart.

## Build order

1. Layout library v2, redesigned with `/impeccable` in both modes. The sample PDF needs **user approval** before the next step.
2. Art director: `art_direct.py`, the rules table and its tests.
3. Measured design check, the art-director retry, and the visual QA checklist from `design.md`.
4. `design.md`, the skill, the prompt wiring, and the docs.

## Acceptance

- The TPA pitch deck (`backend/tests/fixtures` gets its content as a golden brief) rebuilds with zero `fit`, `lint` and `design` findings.
- The user approves how it looks.
- The existing reporting tests stay green.

## Out of scope

- Images or illustration generation.
- New fonts or colours (DESIGN.md is locked).
- Animations.
- Changing the storyline step.
