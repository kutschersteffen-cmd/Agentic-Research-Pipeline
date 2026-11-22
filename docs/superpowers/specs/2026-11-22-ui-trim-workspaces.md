# Trim the workspaces: fewer links, one search box, plainer words

Status: **approved by the owner on 22 Nov 2026** (button in the spec session, after four spec-critic rounds).
Slug: `ui-trim-workspaces`
Risk: this spec PR is `risk:low`. The build is 5 PRs (see `## Slices`); each names its own risk label.
Size: M

## Why

On 22 Nov 2026 Steffen said the UI has too many toggles, tabs and buttons and poor text. An audit of 39 screens
on `main` `ab3b197` (https://claude.ai/artifact/MxunFw1ChgJ7ApjwXbzBDP) found four ways to search, four rows of
navigation on Steward Workflow, nine links in the R&D Lab row (the last clipped at 1440 px), screens reachable
from two workspaces under two names, and help text that explains code instead of the job. Steffen then chose
option C of the structure page (https://claude.ai/artifact/1qeho3QR4Y9DzswWzxCmBi): keep the five workspaces
and trim them. He decided:

- "Index Construction" is called "Portfolio Builder" (PR #620, merged or merging separately; not part of this spec).
- R&D Lab is called **Strategy**; its main flow is **Design a strategy**.
- The word "product" never appears in the UI.
- "Review Queue" is renamed **Needs you**.
- Search and Ask become **one box**.
- Taxonomy Library and Thematic Universe go under **More** in the Strategy row.

## What the user can do afterwards that they cannot do today

- Find any screen or ask a question from one box in the top bar (Ctrl/⌘K).
- See at most 5 links plus "More" in every workspace row.
- Start "Design a strategy" from one page that shows the whole flow from idea to report.
- Read page intros and buttons that say what the person gets, without module or code names.

## What exists today

- Top bar: `frontend/src/components/AppTopbar.tsx`: "Search or jump to…" (opens `CommandPalette`, Ctrl/⌘K),
  "Ask ARP" (opens `AskPanel`, Ctrl/⌘J, shown only when `canAsk`), Workspaces menu, "Review Queue" with the
  waiting badge (`GET /api/waiting`), "Reports", user menu.
- `CommandPalette.tsx`: filters `PaletteItem`s by words; Enter navigates. `AskPanel.tsx`: sends a question to
  `POST /api/ask`, whose router (`backend/arp/api/routers/ask.py`) already routes to the tools `portfolio`,
  `smart_search`, `transition_plan` and `benchmark_sectors`.
- Workspace pages: `pages/ProcessHub.tsx` `WorkspacePage` renders `<h1>{w.name}</h1>` and an intro of `w.purpose`
  plus a sentence on dashed lines, then one `ProcessFlow` per process.
- Auth on the e2e stack: dev mode signs every request in as role `approver` (`backend/arp/api/auth.py:75`), so
  `canAsk` (`App.tsx`: signed in, role not `viewer`) is true. No model key is set there, so `POST /api/ask` fails.
- Workspace rows: `frontend/src/lib/processes.ts` `WORKSPACES[].screens`; `rowLinks()` adds the workspace itself
  first. Tab strips over several routes: `frontend/src/lib/nav.ts` `HUBS` (today "Library" and "Runs").
- Steward Workflow: `pages/StewardWorkflow.tsx`, stage tabs from `pages/steward/common.tsx` `STAGE_TABS`
  (Monitoring 1, Selection 2, Workbench, Overlap, Drafting 3, Voting 4, Checkpoint 5, Tracking 6, then a
  "Client…" select for Client policy 7, Reporting 8, Client program), and on Overview a "Process streams"
  button row (one per stream plus "+ Client stream").
- Risk Monitoring: `pages/PortfolioRiskMonitoringTool.tsx`, sub-tabs `lib/subTabs.ts` `SUB_TABS`
  (Dashboards (Superset), Monitoring & Alerts, Company Profiles, Ask the Portfolio, Holdings Intake).
- Visible "Review Queue" strings: `AppTopbar.tsx:107` (link), `App.tsx:79` (⌘K label), `processes.ts:109` (Argus row),
  `ReviewQueue.tsx:78` (`<h1>`), `ArgusResults.tsx:201` ("Open them in the Review Queue"). Route `#/review`.
- Thematic flow title in `processes.ts`: "Launch a thematic product".

## Goals

1. One search-or-ask box replaces the "Ask ARP" button. Search and Smart Search leave the Data Hub row, and the
   "Library" hub in `nav.ts` (Data Library · Search) is removed, so Data Library has no tab strip.
2. Every workspace row shows at most 5 links plus "More ▾"; removed screens keep their routes and stay in ⌘K.
3. R&D Lab is named Strategy, with a "Design a strategy" page as its first link.
4. Review Queue is named "Needs you" everywhere a user sees it.
5. Steward Workflow shows one row of stage tabs; the program is one select.
6. Risk Monitoring shows 3 tabs. Holdings Intake is in no workspace row: it is reached from a "Load holdings"
   link on Risk Monitoring and from ⌘K.
7. The copy rewrites listed in `## Design` replace their current text word for word.
8. No user-facing text outside Value Chain Explorer contains the word "product" or "products" (whole word,
   case-insensitive). Value Chain keeps it where it means a physical good ("product recipes").

## Non-goals

- No backend change, no API change, no route removed. Old links (`#/search`, `#/smartSearch`, `#/emergingThemes`,
  `#/portfolio-monitoring/ask`, `#/portfolio-monitoring/holdings`, `#/argusWalkthrough`) keep opening their screens.
- The Runs hub, Research plans and the Agent screen: the `agent-panel-code-mode` spec owns them.
- The in-page reworks of Decision Studio (8 tabs), Portfolio Builder (presets, "+ add" menus) and XBRL Facts
  (fetch-run picker): audit findings F5, F6, F12 get their own spec. Only their copy rows below are in scope.
- One shared in-page tab style (audit F13).

## Anti-goals

- Never hide a screen from ⌘K.
- Never remove a feature: Ask the Portfolio, Smart Search and Holdings Intake keep working at their routes.

## Design

### Top bar (slice 1)

Left to right: lockup, **Search or ask** (Ctrl/⌘K), Workspaces, **Needs you** with the badge, Reports, user menu.
The "Ask ARP" button is gone. Ctrl/⌘J still opens the Ask panel.

In the palette, after the matching screens, a last option reads `Ask ARP: “<typed text>”` whenever the typed text
is not empty and `canAsk` is true. Arrow keys reach it like any option. Enter on it, or Enter when no screen
matches, closes the palette, opens the Ask panel and sends the typed text as the question (the user turn shows
whatever the answer). With `canAsk`
false the palette works as today and shows no Ask row.

"Review Queue" becomes "Needs you": the top-bar link, the `#/review` page title, the ⌘K label and every other
visible "Review Queue" string listed above; `ArgusResults` reads "Open them in Needs you". The route `#/review`
stays. The palette's title (its dialog's accessible name) is "Search or ask". On a phone the top bar keeps its two
rows; the first row loses the Ask ARP button.

### Workspace rows (slice 1)

| Workspace | Row (after the workspace's own link) |
|---|---|
| StewardIQ | Cockpit · Steward Workflow · Engagement · Proxy Voting · RFP Answers |
| Argus | New extraction · XBRL Facts |
| Transition Intel | Risk Monitoring · Transition Barriers · Transition Plans |
| Strategy | Design a strategy · Themes · Decision Studio · Portfolio Builder · More ▾ |
| Data Hub | Feeds · Issues · Data Library · Outputs · Security Master |

- Argus drops Walkthrough (now the "How it works" link) and Review Queue (now "Needs you" in the top bar). Data Hub
  drops Search, Smart Search and Holdings Intake.
- `#/designStrategy` is added to `App.tsx` `TABS` (label "Design a strategy") and first in the `rdLab` screens.
- **More ▾** is a menu button. Its items, in order: Taxonomy Library, Thematic Universe, Strategy Replication,
  Signals workbench, Value Chain Explorer. When the open screen is one of them, the More button has
  `aria-current="page"` and the 2 px underline of the current link.
- **Themes** links to `#/themes`. A new hub in `HUBS`, label "Themes", tabs `themes` "Dossiers" and
  `emergingThemes` "Emerging themes", puts the same tab strip on both screens.
- Strategy: `WORKSPACES` entry `rdLab` keeps its id; `name` "Strategy", purpose "Spot themes and design
  strategies, from idea to portfolio." The start-page card, the workspace page `h1` and the Workspaces
  menu show "Strategy".
- Argus: the Argus page gets a link "How it works" to `#/argusWalkthrough` under its intro.
- Transition Intel: the link label "Transition Plan" becomes "Transition Plans"; the page it opens
  (`#/argus/new/transition_plan`) shows the title "Transition plan assessment" instead of "New extraction".

### Design a strategy (slice 4)

New route `#/designStrategy`, page title "Design a strategy", intro "From an idea to a portfolio you can report
on." It renders `ProcessFlow` (`ProcessHub.tsx`, exported for this) for the process `thematic`, now titled "Design a
strategy" (was "Launch a thematic product"): step buttons Spot, Define, Match, Review, Score, Construct, Report,
the details panel and its "Open <step> →" link, plus the process's cadence chip as on the workspace pages.
Slice 1 adds the route with this page's `h1` and intro only; slice 4 adds the rest. The
two starting points are listed first: "Start from a theme" links to `#/themes`, "Start from a research paper"
links to `#/strategyReplication`.

### Steward Workflow (slice 2)

- Stage row: Overview · 1 Monitoring · 2 Selection · 3 Drafting · 4 Voting · 5 Checkpoint · 6 Tracking. With a
  client program selected, it adds 7 Client policy · 8 Reporting · Client program. The "Client…" select goes.
- Workbench and Overlap are no longer tabs. Selection shows two sections under its studio: "Workbench" and
  "Overlap", each with a heading, holding today's `WorkbenchStudio` and `OverlapStudio`. `#/stewardship/workbench`
  and `#/stewardship/overlap` open Selection scrolled to that section.
- A select labelled "Program", shown next to the stage row on every tab, replaces the "Process streams" buttons.
  Options: each stream by its name from `GET /api/stewardship/streams` (the house stream first, named "House
  program"), then "+ New client stream…", which opens today's add-stream form. Choosing the house stream while a
  client tab (7, 8, Client program) is open switches to Overview.
- "Steward · Voting" (the StewardIQ process step label) becomes "Decided votes".

### Risk Monitoring (slice 3)

- ⌘K keeps every Steward stage and Risk Monitoring tab it lists today, including Workbench, Overlap, Ask the
  Portfolio and Holdings Intake, with the new labels (Alerts, Dashboards, Company profiles).
- Tabs: Alerts · Dashboards · Company profiles (ids `monitoring`, `dashboards`, `profiles`). Bare
  `#/portfolio-monitoring` still opens Alerts. `#/portfolio-monitoring/ask` and `/holdings` still render the Ask the
  Portfolio and Holdings Intake panes, with the 3 tabs shown and none selected.
- Under the portfolio choice a line holds "Save as group…" (a link that reveals today's group name field and save
  button) and "Load holdings" (a link to `#/portfolio-monitoring/holdings`).
- The group name field and "Save selection as group" are hidden until "Save as group…" is pressed.

### Copy (each slice, for its screens)

| ID | Screen | Now | New |
|---|---|---|---|
| C1 | Risk Monitoring | Use the companies held in all portfolios, latest in: | Send these companies to: |
| C2 | Risk Monitoring | Argus → | Extract data → |
| C3 | Risk Monitoring | Argus, Transition plan → | Assess transition plans → |
| C4 | Risk Monitoring | Pick a portfolio or group and an as-of date; the selection carries across the tabs below (Dashboards uses Superset's own filter bar). | Pick portfolios and a date. The choice applies to every tab. |
| C5 | Risk Monitoring alerts | open · acknowledged · escalated · resolved · false positive · all | Open · Acknowledged · Escalated · Resolved · False positive · All |
| C6 | Decision Studio | Turn any per-company table into a scored, ranked and tiered decision. The numbers are computed deterministically, with no LLM, and every automated choice and edit is recorded. | Score, rank and tier companies from any table. Fixed rules do the maths, not the AI model, and every choice is logged. |
| C7 | Steward Workflow | The stewardship process end to end. The overview shows every stage with its key numbers and the decisions waiting; each stage has its own studio to review its data, design and calibrate its rules, and take its decisions. | Each stage of the stewardship cycle, with the decisions waiting on you. |
| C8 | StewardIQ, Engagement step | A vote against management raises a vote_outcome trigger; open the engagement from Monitoring. | A vote against management opens a trigger in Monitoring. |
| C9 | All five workspace pages | `{purpose}` Click a step for its details; open it from there. A dashed re-entered by hand line means that output is typed into the next step, not passed on. | Intro is only `{purpose}`. One legend line under the flows: "Dashed line: typed in by hand, not passed on." |
| C10 | Portfolio Builder, Screens | Applied in order. Order is part of the methodology: screens do not commute once a later one is rank-based, and the funnel a committee reviews depends on the order they ran in. | Screens run top to bottom. Order changes the result once a screen ranks companies. |
| C11 | Portfolio Builder, Tilts | Applied in order, multiplicatively, onto the base weight. Floor and ceiling are mandatory: an unbounded tilt silently becomes an exclusion, which is a methodology change nobody approved. | Tilts multiply the base weight, in order. Set a floor and a ceiling: without them a tilt can drop a company to zero. |
| C12 | Portfolio Builder, Constraints | Applied by a deterministic waterfall, not a solver: pin every breach at its cap, redistribute pro-rata, repeat until no name breaches and the weights sum to one. | Any weight over a cap is cut back and the excess shared out, until every cap holds. |
| C13 | Portfolio Builder step rail (`#/index`, defaults) | `select_all` under Selection, `free_float_mcap` under Base weighting | "Select all", "Free float market cap" |
| C14 | XBRL Facts, Fetch | Choose a run to see its status again, for example after a reload or a visit to another page. | (removed) |
| C16 | Design a strategy (process cadence) | Per product idea | Per idea |
| C17 | Design a strategy, Report step | Product committee deck. | Committee deck. |
| C18 | Risk Monitoring, portfolio picker | Portfolios (none selected = all) | Label "Portfolios"; while none is ticked, a line under the boxes reads "All portfolios" |
| C19 | XBRL Facts, Tags | Update tag registry (button) | Download latest tag lists |
| C20 | XBRL Facts, Files | …Choose a company’s name to see its facts below. The annual report is third-party HTML: it is only downloaded, never opened in this app. | What is stored for each fetched company. Choose a company’s name to see its facts below. |
| C21 | Portfolio Builder, Run a review | Run & save (button) | Run review and save |
| C22 | Portfolio Builder, Constraints | `<h3>`How the constraints are satisfied`</h3>` and its paragraph (waterfall, least-squares projection, solver status), always shown | The same heading and paragraph inside a `<details>` whose summary reads "How this works", closed by default |
| C15 | XBRL Facts, Tags | Letters, digits, dot, underscore and hyphen, starting with a letter or digit, e.g. revenue-core. Saving cuts these tags out of every stored company. Saving reads every stored company file and can take a few minutes for large lists. (always shown) | Always shown: "Saving cuts these tags out of every stored company and can take a few minutes for large lists." Shown only while the name is invalid, as the field's error: "Use letters, digits, dot, underscore and hyphen, starting with a letter or digit, e.g. revenue-core." |

## Acceptance

Superseded by `2026-11-21-agent-panel-code-mode.md` Phase 7 (slice 13): AC-4, AC-4b and AC-7. The Ask panel is gone; the palette's ask and Ctrl/⌘J open the Agent screen (its AC-75 to AC-76d).

All rows run on the app started by `backend/scripts/e2e_stack.sh up` (dev auth, role `approver`, no model key),
at 1440 × 900, unless the Given says otherwise.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | e2e stack | open `#/home` | no button has the accessible name "Ask ARP" | holdout |
| AC-1b | e2e stack | open `#/home` | a button whose accessible name starts "Search or ask" is in the top bar | holdout |
| AC-2 | e2e stack | open `#/home` | the top bar has a link "Needs you" with `href` `#/review` | holdout |
| AC-2b | e2e stack | open each of `#/home`, `#/argus`, `#/review` | no visible text on the page is "Review Queue" | holdout |
| AC-3 | e2e stack | press Ctrl+K, type `outputs nobody uses` | the palette dialog's accessible name is "Search or ask" | holdout |
| AC-3b | e2e stack | press Ctrl+K, type `outputs nobody uses` | the palette's last option reads `Ask ARP: “outputs nobody uses”` | holdout |
| AC-4 | e2e stack | press Ctrl+K, type `zzqx nothing matches`, press Enter | the palette is closed, the Ask panel is open, and it shows a user turn with the text `zzqx nothing matches` | holdout |
| AC-4b | e2e stack | press Ctrl+K, type `outputs nobody uses`, press ArrowDown until the `Ask ARP: …` option is active, press Enter | the Ask panel is open with a user turn `outputs nobody uses` | holdout |
| AC-5 | e2e stack | press Ctrl+K, type `portfolio builder`, press Enter | the hash is `#/index` | holdout |
| AC-6 | unit test, `canAsk` false | type `abc` in the palette | no option text starts with "Ask ARP" | unit |
| AC-7 | e2e stack | press Ctrl+J on `#/home` | the Ask panel is open | holdout |
| AC-8 | e2e stack | open `#/review` | the `h1` text is "Needs you" | holdout |
| AC-9 | e2e stack | open `#/stewardiq` | the workspace row's links read, in order: StewardIQ, Cockpit, Steward Workflow, Engagement, Proxy Voting, RFP Answers | holdout |
| AC-10 | e2e stack | open `#/argus` | the workspace row's links read, in order: Argus, New extraction, XBRL Facts | holdout |
| AC-11 | e2e stack | open `#/transitionIntel` | the workspace row's links read, in order: Transition Intel, Risk Monitoring, Transition Barriers, Transition Plans | holdout |
| AC-12 | e2e stack | open `#/rdLab` | the workspace row reads, in order: links Strategy, Design a strategy, Themes, Decision Studio, Portfolio Builder, then a button "More" | holdout |
| AC-13 | AC-12 | press "More" | its menu items read, in order: Taxonomy Library, Thematic Universe, Strategy Replication, Signals workbench, Value Chain Explorer | holdout |
| AC-14 | e2e stack | open `#/taxonomy` | the Strategy row's "More" button has `aria-current="page"` | holdout |
| AC-15 | e2e stack | open `#/dataHub` | the workspace row's links read, in order: Data Hub, Feeds, Issues, Data Library, Outputs, Security Master | holdout |
| AC-15b | e2e stack | open `#/library` | the page has no tab strip with a tab "Search" | holdout |
| AC-16 | e2e stack | open `#/home` | the five start cards' names read, in order: StewardIQ, Argus, Transition Intelligence Platform, Strategy, Data Hub | holdout |
| AC-16b | e2e stack | open the Workspaces menu on `#/home` | an item reads "Strategy" and none reads "R&D Lab" | holdout |
| AC-17 | e2e stack | open each of `#/search`, `#/smartSearch`, `#/emergingThemes`, `#/argusWalkthrough`, `#/valueChain` | the `h1` reads, respectively: Search, Smart Search, Emerging Themes, Walkthrough, Value Chain Explorer | holdout |
| AC-17b | e2e stack | open `#/portfolio-monitoring/ask` | an `h2` "Ask the Portfolio" and a text box named "Question" are visible; no sub-tab is selected | holdout |
| AC-17c | e2e stack | open `#/portfolio-monitoring/holdings` | an `h2` "Holdings Intake", an `h3` "Upload holdings" and a file input are visible; no sub-tab is selected | holdout |
| AC-18 | e2e stack | press Ctrl+K and type, one at a time: `search`, `smart search`, `walkthrough`, `taxonomy`, `thematic universe`, `strategy replication`, `signals`, `value chain`, `emerging themes`, `holdings intake`, `ask the portfolio`, `needs you`, `workbench`, `overlap` | each shows at least one option that is not the `Ask ARP: …` option | holdout |
| AC-19 | e2e stack | open `#/themes`, then `#/emergingThemes` | both show a tab strip whose tabs read "Dossiers", "Emerging themes", with the open screen's tab selected | holdout |
| AC-20 | e2e stack | open `#/argus` | a link "How it works" with `href` `#/argusWalkthrough` is present | holdout |
| AC-21 | e2e stack | open `#/argus/new/transition_plan` | the `h1` text is "Transition plan assessment" | holdout |
| AC-22 | e2e stack | open `#/designStrategy` | the `h1` text is "Design a strategy" | holdout |
| AC-22b | e2e stack | open `#/designStrategy` | a link "Start from a theme" with `href` `#/themes` is present | holdout |
| AC-22c | e2e stack | open `#/designStrategy` | a link "Start from a research paper" with `href` `#/strategyReplication` is present | holdout |
| AC-23 | e2e stack | open `#/designStrategy` | the flow's step buttons read, in order: Spot, Define, Match, Review, Score, Construct, Report | holdout |
| AC-23b | e2e stack | open `#/designStrategy` | the Strategy row's link "Design a strategy" has `aria-current="page"` | holdout |
| AC-24 | e2e stack | open each of `#/home`, `#/stewardiq`, `#/argus`, `#/transitionIntel`, `#/rdLab`, `#/dataHub`, `#/designStrategy`, `#/index`, `#/decision`, the Workspaces menu, and the Ctrl+K list with nothing typed | no visible text contains the whole word "product" or "products" (case-insensitive) | holdout |
| AC-25 | e2e stack | open `#/stewardship` | the stage row's tabs read, in order: Overview, 1 Monitoring, 2 Selection, 3 Drafting, 4 Voting, 5 Checkpoint, 6 Tracking | holdout |
| AC-25b | e2e stack | open `#/stewardship` | no select has the accessible name "Client stages" | holdout |
| AC-26 | e2e stack | open `#/stewardship` | a select named "Program" is present; its first option is "House program" and its last is "+ New client stream…" | holdout |
| AC-26b | e2e stack | open `#/stewardship/drafting` | the select named "Program" is present | holdout |
| AC-27 | e2e stack, `POST /api/stewardship/streams` with `{"name":"Test client"}` before load | open `#/stewardship`, choose "Test client" in "Program" | the stage row ends: 6 Tracking, 7 Client policy, 8 Reporting, Client program | holdout |
| AC-28 | e2e stack | open `#/stewardship/selection` | headings "Workbench" and "Overlap" are present | holdout |
| AC-29 | e2e stack | open `#/stewardship/workbench` | the tab "2 Selection" is selected and the "Workbench" heading is in the viewport | evaluator |
| AC-29b | e2e stack | open `#/stewardship/overlap` | the tab "2 Selection" is selected and the "Overlap" heading is in the viewport | evaluator |
| AC-30 | e2e stack | open `#/stewardiq`, expand "Proxy season" | a step reads "Decided votes" and none reads "Steward · Voting" | holdout |
| AC-31 | e2e stack | open `#/portfolio-monitoring` | the sub-tabs read, in order: Alerts, Dashboards, Company profiles | holdout |
| AC-31b | e2e stack | open `#/portfolio-monitoring` | the sub-tab Alerts is selected | holdout |
| AC-32 | e2e stack | open `#/portfolio-monitoring` | no text field named "Group name" is visible | holdout |
| AC-32c | e2e stack | open `#/portfolio-monitoring` | a control "Save as group…" is present | holdout |
| AC-32b | AC-32 | press "Save as group…" | a text field "Group name" and a button "Save selection as group" are visible | holdout |
| AC-33 | e2e stack | open `#/portfolio-monitoring` | a link "Load holdings" with `href` `#/portfolio-monitoring/holdings` is present | holdout |
| AC-34 | e2e stack | open `#/portfolio-monitoring` | the texts of C1, C2, C3 and C4 "New" are visible and their "Now" texts are not | holdout |
| AC-34b | e2e stack | open `#/portfolio-monitoring` | the alert filter chips read, in order: Open, Acknowledged, Escalated, Resolved, False positive, All (C5) | holdout |
| AC-34c | e2e stack | open `#/decision` | the intro reads exactly the C6 "New" text | holdout |
| AC-34d | e2e stack | open `#/stewardship` | the intro reads exactly the C7 "New" text | holdout |
| AC-34e | e2e stack | open `#/stewardiq`, expand "Proxy season" | the Engagement step's text reads exactly the C8 "New" text | holdout |
| AC-34f | e2e stack | open each of `#/stewardiq`, `#/argus`, `#/transitionIntel`, `#/rdLab`, `#/dataHub` | the intro under the `h1` is exactly that workspace's purpose, and the line "Dashed line: typed in by hand, not passed on." is present (C9) | holdout |
| AC-34g | e2e stack | open `#/index` | the C10, C11 and C12 "New" texts are visible and their "Now" texts are not | holdout |
| AC-34h | e2e stack | open `#/index` | the step rail shows "Select all" under Selection and "Free float market cap" under Base weighting, and neither `select_all` nor `free_float_mcap` (C13) | holdout |
| AC-34i | e2e stack | open `#/designStrategy`, open the step Report | its text reads "Committee deck." (C17) | holdout |
| AC-34k | e2e stack | open `#/designStrategy` | the cadence chip reads "Per idea" (C16) | holdout |
| AC-34l | e2e stack | open `#/portfolio-monitoring` with no portfolio ticked | in the selection pane's picker (under the portfolio choice), the label reads "Portfolios" and the line "All portfolios" is visible; no text "(none selected = all)" is on the page (C18) | holdout |
| AC-34m | AC-34l | tick one portfolio in the selection pane's picker | that picker's "All portfolios" line is not visible | holdout |
| AC-34s | e2e stack | open `#/portfolio-monitoring` with no portfolio ticked in the alert scope picker | that picker's label reads "Portfolios" and its line "All portfolios" is visible (same component) | holdout |
| AC-34n | e2e stack | open `#/xbrl` | a button "Download latest tag lists" is present and none named "Update tag registry" (C19) | holdout |
| AC-34o | e2e stack | open `#/xbrl` | the Files help text reads exactly the C20 "New" text | holdout |
| AC-34p | e2e stack | open `#/index` | a button "Run review and save" is present and none named "Run & save" (C21) | holdout |
| AC-34q | e2e stack | open `#/index` | a `<details>` with summary "How this works" is present and closed, and "byte-identical" is not visible (C22) | holdout |
| AC-34r | AC-34q | press "How this works" | "byte-identical" is visible | holdout |
| AC-34j | e2e stack | open `#/xbrl` | the sentence "Choose a run to see its status again, for example after a reload or a visit to another page." is absent (C14) | holdout |
| AC-35 | e2e stack | open `#/xbrl`, type `bad name!` in "Selection name" | the error "Use letters, digits, dot, underscore and hyphen, starting with a letter or digit, e.g. revenue-core." is shown | holdout |
| AC-35b | e2e stack | open `#/xbrl` with "Selection name" empty | that error is not shown, and "Saving cuts these tags out of every stored company and can take a few minutes for large lists." is shown | holdout |
| AC-36 | e2e stack | open `#/rdLab` | the `h1` text is "Strategy" | holdout |
| AC-36b | e2e stack | open `#/rdLab` | a process titled "Design a strategy" is listed and none titled "Launch a thematic product" | holdout |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-37 | e2e stack (its `arp portfolio seed-demo` leaves 15 tier changes to confirm, so `GET /api/waiting` returns `total` 15) | open `#/home` | the "Needs you" badge shows 15, the same number as `total` | holdout |
| AC-38 | e2e stack | open `#/review` | the page lists as many review items as `GET /api/review/items` returns in `items` (the endpoint it reads today) | evaluator |
| AC-40 | the frontend suite | `npm test` | exits 0 | unit |

~~AC-39~~ retired before approval: covered by AC-17c.

## Slices

Each PR puts `Spec: ui-trim-workspaces` and its `Rows:` line in its description, and lists every test it changes.

| Slice | PR contents | Risk | Rows |
|---|---|---|---|
| 1 | Top bar (one box, Needs you), workspace rows, More menu, Themes hub, Library hub removed, Strategy name, `#/designStrategy` route with its `h1` and intro, How it works link, Transition plan title, `PRODUCT.md` term line | `risk:normal` | AC-1, AC-1b, AC-2, AC-2b, AC-3, AC-3b, AC-4, AC-4b, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-15b, AC-16, AC-16b, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-36, AC-37, AC-38, AC-40 |
| 2 | Steward Workflow stage row, Program select, Workbench and Overlap in Selection, Decided votes, copy C7, C8 | `risk:normal` | AC-25, AC-25b, AC-26, AC-26b, AC-27, AC-18, AC-28, AC-29, AC-29b, AC-30, AC-34d, AC-34e, AC-40 |
| 3 | Risk Monitoring tabs and hidden panes, group form, Load holdings, copy C1 to C5, C18 | `risk:normal` | AC-17b, AC-17c, AC-18, AC-31, AC-31b, AC-32, AC-32b, AC-32c, AC-33, AC-34, AC-34b, AC-34l, AC-34m, AC-34s, AC-40 |
| 4 | Design a strategy page and process rename, copy C6, C9 to C13, C16, C17, C21, C22, no "product" | `risk:normal` | AC-22b, AC-22c, AC-23, AC-23b, AC-24, AC-34c, AC-34f, AC-34g, AC-34h, AC-34i, AC-34k, AC-34p, AC-34q, AC-34r, AC-36b, AC-40 |
| 5 | XBRL copy C14, C15, C19, C20 | `risk:low` | AC-34j, AC-34n, AC-34o, AC-35, AC-35b, AC-40 |

Slice 1 goes first; slices 2 to 5 may run in parallel after it.

## Later (own specs)

- Second spec (Steffen, 22 Nov): Decision Studio tabs 8 → 6, Portfolio Builder presets as one select and "+ add" menus, XBRL fetch-run picker
  (audit F5, F6, F12), hiding the optimiser choice when it is not installed (its message
  `SOLVER_MISSING` is pinned by `showcase-themes-fixes` AC-65 and AC-69, so it changes there), and step names out of
  mono capitals (F14).
- One in-page tab style in DESIGN.md (F13).
- Agent: Run history and Standing agents as tabs of the Agent screen, and the Agent inbox counted in "Needs you",
  once `agent-panel-code-mode` slices 6 to 8 have merged.

## Defaults decided without the owner

- Steward Workflow keeps its Overview tab, because its stage cards show counts the StewardIQ page does not.
- "Ask the Portfolio" leaves the tab row but keeps its route, because Ask ARP's `portfolio` tool does not take the
  pane's portfolio and date selection.
- `PRODUCT.md` lists "review queue" as a term to keep; slice 1 changes that line to "Needs you (the review queue)".
