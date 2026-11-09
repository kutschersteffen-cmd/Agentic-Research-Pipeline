# Night Desk, release 4: start page

## Intent

Bring the start page in line with the Night Desk mockup (`docs/design-directions.html`, "Start page"):
a short greeting, the waiting count as the first, amber number in the counts at the top right, a small
amber link to the review queue directly above the workspace cards, and cards with an icon tile and a
footer strip. The owner wants the greeting calm and the "what waits on me" signal next to where they
act (the cards), not as a second headline line.

## Goals

- The headline shows only the greeting ("Good morning, <name>.").
- The counts show "waiting on you" first, in amber, then running, failed this week, done today.
- A link directly above the cards carries today's waiting sentence and opens the Review Queue.
- Workspace cards show their icon in a rounded tile and their footer as a strip with a top rule.
- The "Now" row and the "What counts?" note stay, restyled.

## Non-goals

- No change to how counts or card states are computed (`useWaitingTotal`, `cardView`, `stepState`).
- No landing page; no other page changes.
- No backend change.

## Anti-goals

- Losing a state the page shows today: loading, runs error, waiting error, nothing waiting.
- Amber on anything other than the waiting count, the waiting link and cards that await a person.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| **A (picked)** | Rework `StartPage` in place | Smallest; keeps every existing state |
| B | CSS only | Reading order stays wrong for screen readers |
| C | New component | Duplicates loading and error logic |

The owner picked A and chose to keep the Now row and the "What counts?" note.

## Decided

**Waiting sentence.** The existing ternary in `StartPage` moves unchanged into a pure function
`waitingSentence(known: boolean, error: string | null, needsTotal: number | "error" | null): string`
in `frontend/src/lib/workspaceCard.ts`. Its texts are exactly today's: `"Runs could not be loaded."`,
`"Loading runs…"`, `"What waits on you could not be loaded."`, `"Loading what waits on you…"`,
`"1 decision waits on you."`, `"<n> decisions wait on you."`, `"Nothing waits on you."`.

**Link and count helpers.** Pure functions next to it:
`waitingLink(known, error, needsTotal): { text: string; href: "#/review" | null }`: when `needsTotal`
is a number > 0, `text` is the sentence without its final `"."` plus `" →"` and `href` is
`"#/review"`; otherwise `text` is the sentence and `href` is `null`.
`waitingStat(needsTotal): string`: the number as text, or `"—"` when it is not a number.
`StartPage` renders the link as `a.hub-waiting` when `href` is set, else `p.hub-waiting.hub-waiting-quiet`,
and the first count's `<dd>` from `waitingStat`.

**Headline.** `<h1>` keeps only the greeting span (greeting, `, <name>` when set, `.`). The second span
is removed from the `<h1>`.

**Waiting link.** Directly above `.hub-cards`: when the waiting total is a number greater than 0,
`<a class="hub-waiting" href="#/review">{sentence without the final "."} →</a>`; otherwise
`<p class="hub-waiting hub-waiting-quiet">{sentence}</p>` (loading, errors, nothing waiting). The
"What counts?" `<details>` moves to directly after `.hub-cards` (before the legend).

**Counts.** A first `<div class="you">` with `<dt>waiting on you</dt>` and `<dd>` = the waiting total,
or `"—"` while not a number. Running, failed this week and done today follow unchanged. The existing
`.hub-stats .you dd { color: var(--hi) }` rule colours it.

**Cards.** The icon is wrapped in `<span class="hub-card-icon">` (a 44px rounded tile:
`border: 1px solid var(--panel-border)`, `border-radius: var(--r-md)`, `background: var(--bg)`;
for `.hub-card-await` the tile border is `var(--await-edge)`). `.hub-card-foot` gets
`border-top: 1px solid var(--panel-border)`.

**Link look.** `.hub-waiting`: `var(--hi-ink)`, `var(--text-md)`, weight 500, no underline until
hover. `.hub-waiting-quiet`: `var(--muted)`, not a link.

## Left to the builder

- Spacing between greeting, counts, link and cards, within the mockup's look.
- Whether the card footer strip runs edge to edge (negative margin) or inside the card padding.

## Acceptance

Rows marked `unit` are owed as `holdout` once `HOLDOUT_TOKEN` is set; the PR lists them. The frontend
tests run without a DOM, so rendering is checked through the pure helpers and by the evaluator.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `known=false, error="x"` | `waitingSentence` | `"Runs could not be loaded."` | unit |
| AC-2 | `known=false, error=null` | `waitingSentence` | `"Loading runs…"` | unit |
| AC-3 | `known=true, needsTotal="error"` | `waitingSentence` | `"What waits on you could not be loaded."` | unit |
| AC-4 | `known=true, needsTotal=null` | `waitingSentence` | `"Loading what waits on you…"` | unit |
| AC-5 | `known=true, needsTotal=1` | `waitingSentence` | `"1 decision waits on you."` | unit |
| AC-6 | `known=true, needsTotal=7` | `waitingSentence` | `"7 decisions wait on you."` | unit |
| AC-7 | `known=true, needsTotal=0` | `waitingSentence` | `"Nothing waits on you."` | unit |
| AC-8 | `known=true, needsTotal=7` | `waitingLink` | `{ text: "7 decisions wait on you →", href: "#/review" }` | unit |
| AC-8b | `known=true, needsTotal=1` | `waitingLink` | `{ text: "1 decision waits on you →", href: "#/review" }` | unit |
| AC-8c | Each of AC-1, AC-2, AC-3, AC-4, AC-7's inputs | `waitingLink` | `href` is `null` and `text` equals that row's sentence | unit |
| AC-9 | `needsTotal` = `7`, `0`, `null`, `"error"` | `waitingStat` | `"7"`, `"0"`, `"—"`, `"—"` | unit |
| AC-10 | `index.css` | `.hub-card-icon` is read | It sets `border-radius: var(--r-md)` and `border: 1px solid var(--panel-border)` | unit |
| AC-10b | `index.css` | `.hub-card-await .hub-card-icon` is read | It sets `border-color: var(--await-edge)` | unit |
| AC-10c | `index.css` | `.hub-card-foot` is read | It sets `border-top: 1px solid var(--panel-border)` | unit |
| AC-11 | `index.css` | `.hub-waiting` is read | It sets `color: var(--hi-ink)`, `font-weight: 500` and `text-decoration: none` | unit |
| AC-11b | `index.css` | `.hub-waiting-quiet` is read | It sets `color: var(--muted)` | unit |
| AC-11c | `index.css` | `.hub-stats .you dd` is read | It sets `color: var(--hi)` (unchanged from `origin/main`) | unit |
| AC-12 | The branch vs `origin/main` | Added lines in `frontend/src` containing `var(--hi` or `var(--await` are listed | Every added match is in the rule `.hub-waiting` or `.hub-card-await .hub-card-icon`; there are no others | unit |
| AC-13a | The running app with at least one waiting item and a reviewer name (e2e seed; a stack without them counts as a fail) | The start page opens | The `h1` text is exactly `<greeting>, <name>.` with nothing else | evaluator |
| AC-13b | The same | The start page opens | `.hub-stats` items are, in order, `waiting on you` = N, `running`, `failed this week`, `done today` | evaluator |
| AC-13c | The same | The start page opens | The element directly before `.hub-cards` is `a.hub-waiting[href="#/review"]` and its text is exactly the AC-8 form for N | evaluator |
| AC-14 | The running app with the backend stopped | The start page opens | `.hub-waiting-quiet` reads `Runs could not be loaded.`; an alert reads `Runs could not be loaded: <error>. Counts are unknown until the backend responds.` followed by a `Retry` button | evaluator |
| AC-15 | The running app with at least one running run and the waiting total known (a stack without them counts as a fail) | The start page opens | `nav.hub-now` and a `details` whose summary is `What counts?` are both present | evaluator |
| AC-16 | The branch vs `origin/main` | `git diff origin/main -- frontend/src/lib/workspaceCard.ts` is read | It only adds `waitingSentence`, `waitingLink` and `waitingStat`; `cardView`, `stepState`, `processState` and `stepStatusLine` are unchanged | unit |
| AC-17 | The branch vs `origin/main` | `git diff origin/main -- frontend/tests` is read | No test or assert is removed except an allow-list extension in `ac13_amber_usage_unchanged` for the two new selectors | unit |
| AC-17b | The branch | `npm test` runs | It exits 0 | unit |

Must not change: count and card-state computation (AC-16), error and loading states (AC-1..4, AC-8c,
AC-14), existing tests (AC-17, AC-17b).
