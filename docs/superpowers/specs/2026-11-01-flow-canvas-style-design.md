# Flow canvas style (RAGFlow-inspired, Signal Room rules)

Status: draft, awaiting owner approval.

## Goal

Give every React Flow canvas in ARP the look of RAGFlow's agent canvas (dot-grid ground, header row with
icon and title, visible connection dots, curved edges, a selected node clearly marked) while keeping every rule
in `DESIGN.md`. Style only: no new features, no data or API change.

## Canvases in scope

| Canvas | File | Node classes today |
|---|---|---|
| Argus / extraction stage flow | `frontend/src/components/StageFlowChart.tsx` | `.pipeline-card-*` |
| Pipeline editor (setup and run mode) | `frontend/src/components/PipelineEditor.tsx` | `.pipeline-card-*`, `.pipeline-pill-*` |
| Steward flow | `frontend/src/pages/steward/flow.tsx` | `.flow-node-*`, `.flow-band-node` |

All three already sit inside `.flow-rf`, so the shared rules go there once in `frontend/src/index.css`.

## RAGFlow element → ARP rendering

| RAGFlow | ARP version | Rule kept |
|---|---|---|
| Dark gradient canvas with dot grid | React Flow `<Background variant="dots">`, dots in `--panel-border` on `--bg`; no gradient | Flat-By-Default; tokens only |
| Rounded cards, teal border on notes | Square cards, 1px hairline, panel fill | Shapes: square |
| Header: icon + bold title | Same: icon from the existing stroke family (StageFlowChart and steward get the icon slot PipelineEditor already has) + title in `--font-display` 600 | Typography |
| Teal connection dots | Visible 7px handles, ink ring on panel fill; steward hides them today (`opacity: 0`) and keeps hiding them only where it has no edges | One Signal Rule (no colour) |
| Curved bezier edges | `type: "default"` (bezier), stroke `--neutral` 1.4px, arrowhead kept | Tokens |
| Teal highlight on selected node | 2px ink outline, no tint, no shadow | Focus is ink |
| Red bar under node with missing settings | Not copied as decoration. A failed node keeps the existing red status pill | Status Is Not The Signal |
| Zoom/fit control bar at bottom centre | Same position, existing square bordered style | Shapes |
| Hover lift | Float shadow on hover only (DESIGN.md already allows it on pipeline cards) | Elevation |

Both themes (Graphite and Night) come from the existing tokens; nothing is hard-coded.

## Out of scope

Canvas notes, click-to-open side panel on StageFlowChart, pre-run checklist, drag-to-edit, React Flow 12 upgrade.
Each would be its own spec.

## Acceptance

Definitions used below:
- **Canvases:** C1 = StageFlowChart on the Extraction page (`pages/Extraction.tsx`) with a job selected;
  C2 = PipelineEditor in setup mode on the Extraction page; C3 = steward FlowChart on the StewardIQ workflow
  page (`pages/StewardWorkflow.tsx`), Flow view. All reachable in the e2e stack with its seeded demo data.
- **Card:** a node element matching `.pipeline-card` (C1, C2) or `.flow-node` (C3). Pill nodes
  (`.pipeline-pill-*`) and the steward band (`.flow-band-node`) are not cards and keep today's look.
- **Ink** = computed `var(--accent)`; **signal** = computed `var(--hi)`; **neutral** = computed `var(--neutral)`.
- No `tabindex` is added or removed; nodes that are focusable today stay so, others stay unfocusable.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | C1 | Page renders | `.flow-rf .react-flow__background` contains `circle` pattern dots with fill = computed `var(--panel-border)` | evaluator |
| AC-2 | C2 | Page renders | Same as AC-1 | evaluator |
| AC-3 | C3 | Page renders | Same as AC-1 | evaluator |
| AC-4 | C1, C2, C3; Graphite and Night | Page renders | Every card has computed `border-radius: 0px` | evaluator |
| AC-5 | C1, C2, C3; both themes | Page renders | Every card has a `1px solid` border; colour = computed `var(--panel-border)` unless it is selected or waiting (AC-13, AC-16) | evaluator |
| AC-6 | C1, C2, C3 | Pointer not over a card | Every card has computed `box-shadow: none` | evaluator |
| AC-7 | C1, C2, C3 | Pointer hovers a card | That card's `box-shadow` = computed `var(--shadow-md)` | evaluator |
| AC-8 | C1 | Page renders | Each card's first header row has an `svg` icon as first child and the title as second child; title `font-weight` 600, `font-family` = `var(--font-display)` | evaluator |
| AC-9 | C2 | Page renders | Same as AC-8 | evaluator |
| AC-10 | C3 | Page renders | Same as AC-8 | evaluator |
| AC-11 | C1, C2, C3 with edges | Page renders | Every `.react-flow__edge-path` has a `d` attribute containing `C` (bezier), stroke = neutral, `stroke-width` 1.4px | evaluator |
| AC-12 | C1, C2, C3 with edges | Page renders | Every edge path has a `marker-end` (arrowhead) | evaluator |
| AC-13 | C2 setup mode | User clicks step A, then step B | After the first click A's card has `outline: 2px solid` ink; after the second B has it and A has no outline | evaluator |
| AC-14 | C3 | User clicks stage A, then stage B | Same as AC-13 | evaluator |
| AC-15 | C1, C2, C3 | Page renders | `.react-flow__handle` on nodes with at least one edge is 7×7px, border 1px ink, fill = computed `var(--panel)`, opacity 1; on C3 nodes with no edge, opacity 0 | evaluator |
| AC-16 | C3 with a stage that has open decisions (seeded demo case) | Page renders | That stage shows `.flow-node-badge` reading `<n> to decide` in the signal colour | evaluator |
| AC-17 | C1, C2, C3; no stage waiting on a person (no open decisions, no `ready` stage) | Page renders | No element inside `.flow-rf` has computed `color`, `background-color`, `border-*-color` or `outline-color` equal to signal | evaluator |
| AC-18 | C1, C2, C3 | Page renders | `.react-flow__controls` is horizontally centred at the bottom of the canvas (left and right gaps differ by ≤2px), `border-radius` 0px | evaluator |
| AC-19 | C1 with a failed stage | Page renders | The stage shows the existing `.status-failed` pill reading `Failed`; no other red element is added to the card | evaluator |
| AC-20 | C1, C2, C3; both themes | Page renders | Every text element in a card has computed `font-size` ≥ 13px | evaluator |
| AC-21 | C1, C2, C3; both themes | Page renders | Every text element in a card has contrast ≥ 4.5:1 against its nearest opaque background | evaluator |
| AC-22 | Viewport 390px wide | C1, C2 and the StewardIQ page render | `document.documentElement.scrollWidth` ≤ 390 | evaluator |
| AC-23 | Viewport 390px wide | StewardIQ page renders | The List view (`.flow-list.phone-only`) is visible and no `.react-flow` element is visible | evaluator |
| AC-24 | C1 | Page renders | Same labels, counts, status pills, `Start` / `Run again` buttons and handover toggles (Manual / Automatic / Skip) as on `main` for the same data | evaluator |
| AC-25 | C2 setup mode | User clicks a step | The same `.pipeline-detail` settings panel opens as on `main` | evaluator |
| AC-26 | C3 | User clicks a stage | The same stage is selected (same detail shown) as on `main` | evaluator |
| AC-27 | Frontend suite | `npm test` | All existing tests pass unchanged | unit |

Must not change: node content and click behaviour (AC-24, AC-25, AC-26), the phone List view (AC-23), the
existing test suite (AC-27).
