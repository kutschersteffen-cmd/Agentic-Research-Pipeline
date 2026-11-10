# Night Desk, release 6: waiting link target

## Intent

The evaluator found that the start page link "15 decisions wait on you →" opens the Review Queue,
which shows 0 items, because all 15 are open stewardship decisions listed in StewardIQ. The owner
picked a smart target: the link opens the place that actually holds what waits.

## Goals

- When the Review Queue has items, the link opens `#/review` (as today).
- When it has none but stewardship decisions are open, the link opens `#/stewardiq`.
- Otherwise (only ballots, failed runs or blocking data issues) it opens `#/review` (as today).

## Non-goals

- No change to the total, the sentence, the counts or "What counts?".
- The Review Queue does not start listing stewardship decisions.
- No backend change.

## Anti-goals

- A link that lands on a page showing nothing to do while the start page says something waits on
  StewardIQ.

## Decided

`useWaitingTotal` also exposes how many of the total are Review Queue items (`queue`) and how many are
open stewardship decisions (`stewardship`); its `number | null | "error"` total is unchanged.
A pure function in `frontend/src/lib/workspaceCard.ts`:
`waitingTarget(queue: number, stewardship: number): "#/review" | "#/stewardiq"` returns `"#/stewardiq"`
when `queue === 0 && stewardship > 0`, else `"#/review"`.
`waitingLink` takes the target as a fourth argument (default `"#/review"`) and uses it as `href`
when it links today; its text and the no-link cases are unchanged.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `waitingTarget(0, 15)` | called | `"#/stewardiq"` | unit |
| AC-2 | `waitingTarget(3, 15)` | called | `"#/review"` | unit |
| AC-3 | `waitingTarget(0, 0)` | called | `"#/review"` | unit |
| AC-4 | `waitingLink(true, null, 15, "#/stewardiq")` (release-4 argument order plus a 4th) | called | `{ text: "15 decisions wait on you →", href: "#/stewardiq" }` | unit |
| AC-5 | `waitingLink(true, null, 0, "#/stewardiq")` | called | `{ text: "Nothing waits on you.", href: null }` | unit |
| AC-6 | `waitingLink(false, "x", 15, "#/stewardiq")` | called | `{ text: "Runs could not be loaded.", href: null }` | unit |
| AC-7 | `waitingLink(true, null, "error", "#/stewardiq")` | called | `{ text: "What waits on you could not be loaded.", href: null }` | unit |
| AC-8 | `waitingLink(true, null, 7)` (three arguments) | called | `{ text: "7 decisions wait on you →", href: "#/review" }` | unit |
| AC-9 | The e2e seed (0 Review Queue items, 15 open stewardship decisions; a stack without them counts as a fail) | The start page opens | `a.hub-waiting` has `href="#/stewardiq"` and text `15 decisions wait on you →` | evaluator |
| AC-10 | The same | The link is clicked | The hash is `#/stewardiq` | evaluator |
| AC-11 | The same, after AC-10 | The page is read | A step shows `15 decisions open` | evaluator |
| AC-12 | The branch vs `origin/main` | `git diff --stat origin/main -- backend` | Empty output | unit |
| AC-13 | The branch vs `origin/main` | `git diff origin/main -- frontend/tests` is read | No test or assert removed | unit |
| AC-14 | The branch | `npm test` runs | Exits 0 | unit |

Must not change: the sentence and no-link cases (AC-5..8), the backend (AC-12), existing tests (AC-13, AC-14).
