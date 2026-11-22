# Rename Strategy back to R&D Lab

Status: **approved by the owner on 22 Nov 2026** (button in the dispatcher thread, after three spec-critic rounds)
Slug: `rd-lab-rename`
Risk: this spec PR is `risk:low`. The build is 1 PR, `risk:low` (labels and copy only, no logic).
Size: S

## Decisions for the owner

1. The workspace is called **R&D Lab** again (Steffen, 22 Nov 2026: "yes. rename back").
2. Its main flow, today "Design a strategy", is renamed **Build a thematic portfolio** (default chosen by the
   dispatcher; the owner can pick another name before approving). It must not say "strategy" or "product".

## Why

The UI trim (`ui-trim-workspaces`, slice 1 and 4) renamed R&D Lab to Strategy and its flow to "Design a
strategy". Steffen reversed that: the area is for researching themes and finding the companies exposed to a
theme, and the name R&D Lab says that better. The decks already use R&D Lab.

## What the user can do afterwards that they cannot do today

- Find the theme research area under the name they know, R&D Lab, on the start page, in the Workspaces menu,
  in the workspace row and in Ctrl/⌘K.
- Read a one-line description that says what the area is for: research themes and find the companies exposed
  to them.

## Change

- `frontend/src/lib/processes.ts`, `WORKSPACES` entry `rdLab` (id unchanged): `name` "R&D Lab"; `purpose`
  "Research themes and find the companies exposed to them."; the `#/designStrategy` screen label and the
  process `thematic` title become "Build a thematic portfolio".
- The Argus process step Template reads "Build and ratify scoring templates in Decision Studio (R&D Lab); only
  ratified versions reach Argus."
- `frontend/src/App.tsx` `TABS`: `rdLab` label "R&D Lab"; `designStrategy` label "Build a thematic portfolio".
- `#/designStrategy` page: `h1` "Build a thematic portfolio"; intro, starting links and flow unchanged.
- The workspace row's accessible name follows (`WorkspaceRow.tsx` uses `${w.short ?? w.name} screens`), so it
  reads "R&D Lab screens".
- The failed-run line on `#/rdLab` reads "Last run failed: Build a thematic portfolio." (it names the process).
- Tests in the app repo that name "Strategy" as the workspace or "Design a strategy" as the flow follow the new
  names: `frontend/tests/searchOrAsk.test.ts`, `frontend/tests/workspaceCard.test.ts`,
  `backend/tests/e2e/test_ui_polish_1.py`, `backend/tests/e2e/test_authority_taxonomy_page.py`.

Defaults (decided here, not by the builder):

- Route ids stay: `#/rdLab`, `#/designStrategy`, component `DesignStrategy`. They are not visible text, and
  keeping them avoids breaking links and bookmarks.
- "Strategy Replication" (screen), "Research a strategy" (process) and the Decision Studio source "Strategy
  replication runs" stay: they are about investment strategies from papers, not the workspace name.
- The start card shows `name` (`ProcessHub.tsx` `WorkspaceCard`), so it reads "R&D Lab".
- Code comments that name the old labels (the `DesignStrategy.tsx` doc comment) are updated to the new names.
- No backend or API change. `openwiki/` needs no hand edit; the weekly refresh picks it up.

Must not change: the row's other links, the More menu items and its current-page state, the `#/designStrategy`
starting links and step buttons, and no visible "product". Rows AC-12 to AC-17 restate them under the new name.

## Supersedes

These `ui-trim-workspaces` rows assert the old names (directly or through the "Strategy screens" row name or a
superseded Given) and are replaced by the rows here. Their hidden tests are retired in the same holdout change
that adds this spec's tests:

| Old row | Replaced by |
|---|---|
| AC-12 (row reads Strategy, Design a strategy, …) | AC-1 |
| AC-13 (More menu items; its Given is AC-12) | AC-12 |
| AC-14 ("Strategy" row's More button is current on `#/taxonomy`) | AC-13 |
| AC-16 (start cards include Strategy) | AC-2 |
| AC-16b (Workspaces menu has Strategy, no R&D Lab) | AC-3, AC-3b, AC-3c |
| AC-22 (`#/designStrategy` `h1` is Design a strategy) | AC-7 |
| AC-23b (row link "Design a strategy" is current) | AC-8 |
| AC-36 (`#/rdLab` `h1` is Strategy) | AC-4 |
| AC-36b (process "Design a strategy" listed) | AC-6 |
| AC-34f, `#/rdLab` case only (intro is the old purpose) | AC-5; the other four workspaces keep AC-34f as it is |

Any other old hidden test that locates the row by the name "Strategy screens" or a label "Design a strategy"
moves to the new name in the same holdout change, with its assertion otherwise unchanged.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | e2e stack | open `#/rdLab` | the navigation named "R&D Lab screens" reads, in order: links R&D Lab, Build a thematic portfolio, Themes, Decision Studio, Portfolio Builder, then a button "More" | holdout |
| AC-2 | e2e stack | open `#/home` | the five start cards' names read, in order: StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub | holdout |
| AC-2b | e2e stack | open `#/home` | the R&D Lab start card shows the text "Research themes and find the companies exposed to them." | holdout |
| AC-3 | e2e stack | open the Workspaces menu on `#/home` | the item linking to `#/rdLab` has the label "R&D Lab": the text of `.start-topbar-place` minus its `.start-topbar-purpose` child, trimmed, equals "R&D Lab" | holdout |
| AC-3c | e2e stack | open the Workspaces menu on `#/home` | the item linking to `#/rdLab` shows the text "Research themes and find the companies exposed to them." | holdout |
| AC-3b | e2e stack | open the Workspaces menu on `#/home` | no item's visible text contains the word "Strategy" | holdout |
| AC-4 | e2e stack | open `#/rdLab` | the `h1` text is "R&D Lab" | holdout |
| AC-5 | e2e stack | open `#/rdLab` | the text "Research themes and find the companies exposed to them." is shown under the `h1` | holdout |
| AC-6 | e2e stack | open `#/rdLab` | a process titled "Build a thematic portfolio" is listed, and none titled "Design a strategy" or "Launch a thematic product" | holdout |
| AC-6b | e2e stack, with the browser's `/api/runs` response replaced by one that adds a run `{run_type: emerging_themes, status: failed}` at the top | open `#/rdLab` | the failed-run line (`.hub-failed-line`) starts with "Last run failed: Build a thematic portfolio." | holdout |
| AC-7 | e2e stack | open `#/designStrategy` | the `h1` text is "Build a thematic portfolio" | holdout |
| AC-8 | e2e stack | open `#/designStrategy` | in the navigation named "R&D Lab screens", the link "Build a thematic portfolio" has `aria-current="page"` | holdout |
| AC-9 | e2e stack | press Ctrl+K and type `R&D Lab` | an option reads "R&D Lab" that is not the `Ask ARP: …` option; pressing it opens `#/rdLab` | holdout |
| AC-10 | e2e stack | open each of `#/home`, `#/rdLab`, `#/designStrategy`, the Workspaces menu, and the Ctrl+K list with nothing typed | no visible text contains "Design a strategy" (case-insensitive) | holdout |
| AC-10b | same pages as AC-10 | open each | no visible element's trimmed `innerText` equals "Strategy" | holdout |
| AC-11 | the Argus workspace's process list (`WORKSPACES` entry `argus`) | read the step labelled Template | its `does` text is "Build and ratify scoring templates in Decision Studio (R&D Lab); only ratified versions reach Argus." (no screen shows it today, so a frontend unit test checks it) | unit |
| AC-12 | AC-1 | press "More" | its menu items read, in order: Taxonomy Library, Thematic Universe, Strategy Replication, Signals workbench, Value Chain Explorer (must not change) | holdout |
| AC-13 | e2e stack | open `#/taxonomy` | the "More" button in the navigation named "R&D Lab screens" has `aria-current="page"` (must not change) | holdout |
| AC-14 | e2e stack | open `#/designStrategy` | a link "Start from a theme" with `href` `#/themes` is present (must not change) | holdout |
| AC-15 | e2e stack | open `#/designStrategy` | a link "Start from a research paper" with `href` `#/strategyReplication` is present (must not change) | holdout |
| AC-16 | e2e stack | open `#/designStrategy` | the flow's step buttons read, in order: Spot, Define, Match, Review, Score, Construct, Report (must not change) | holdout |
| AC-17 | e2e stack | open each of `#/home`, `#/rdLab`, `#/designStrategy` | no visible text contains the whole word "product" or "products" (case-insensitive) (must not change) | holdout |

## Slices

| # | What | Risk | Rows |
|---|---|---|---|
| 1 | All of the above in one PR | `risk:low` | all rows |
