# One waiting count

## Intent

The top bar's Review Queue badge, the Review Queue page and the workspace screens give different answers to "what is waiting
on me". The critique of the new shell (2026-11-15, P1) found the badge at 21 while the Review Queue said 82. The team needs one
number it can defend in a committee, and every other waiting number on screen should be a visible part of it.

The numbers disagree for these reasons:
- **The badge** adds up each run's stored `review_count` for some run types. That field grows when items are flagged and never
  shrinks when they are decided.
- **The Review Queue** counts open items, using `list_open_items`.
- **StewardIQ's step lines** count two other things:
  - open stewardship decisions in the house flow (tier changes, escalations, outreach, client exceptions, commitments due);
  - ballots awaiting a vote on Proxy Voting runs.

  Neither is in the Review Queue. No screen shows a StewardIQ total, only per-step lines.

## Owner decisions (from the conversation)

- **The badge means everything waiting.** Owner's choice: Review Queue items plus stewardship decisions. *Call:* open proxy-vote
  ballots are added as a third part. They also wait on a person and sit in neither of the other two, so leaving them out would
  break "everything".
  - The badge's label says how the total splits.
  - Clicking the badge still opens the Review Queue, and the Review Queue says where the other parts are.
- **Approach:** a new server endpoint, `GET /api/waiting`, counted by the same code those screens use. The two rejected approaches
  are under Approaches.

## Goals

- **`GET /api/waiting`** (any signed-in user; the counts don't depend on who asks) returns
  `{"review": int, "decisions": int, "ballots": int, "total": int}`.
  - **`review`** is `len(list_open_items(run_store, principal))`, the exact list `GET /api/review/items` returns. An item that has had
    its first of two reviews (`first_done`) is still open and still counts.
  - **`decisions`** is the number of decision objects in the house stewardship flow's (`flow("house", …)`) stages `checkpoint` and
    `tracking`. These are the only house stages that carry decisions. The number equals the sum of `openCount(stage)` over those
    two stages as the frontend computes it.
  - **`ballots`**: for each `proxy_voting` run, the number of item keys in its review queue that have no entry in
    `latest_decisions(run_store, run_id)`. These are ballots no person has decided yet.
  - **`total`** is `review + decisions + ballots`.
  - A Pydantic response model is added. `backend/openapi.json` and `frontend/src/api/schema.gen.ts` are regenerated, and the client
    method is typed `Served<…>`, so `contract.ts` needs no new line.
- **The badge** (top bar, on the Review Queue link):
  - **Source:** a new pure helper, `waitingBadge(w: {review, decisions, ballots, total}) → {text, title} | null`, in
    `lib/workspaceCard.ts`, fed by `/api/waiting`. It replaces `reviewBadge` and the `review_count` sum in `App.tsx`. `listAllRuns`
    stays for the command palette's recent runs.
  - **Refresh:** on every navigation and after every decision (the existing `arp:decided` event), as today.
  - **Visible text:** `total` alone, e.g. `97`, at every width.
  - **`title` and `aria-label`:** `<total> waiting for a decision: <review> review items, <decisions> stewardship decisions, <ballots> ballots`.
    - Each part uses the singular at 1.
    - A part at 0 is left out, e.g. `15 waiting for a decision: 15 stewardship decisions`.
  - **No badge** when `total` is 0 or the request fails. A failure never shows a number nobody measured.
- **The Review Queue page** shows the parts it doesn't hold. A note sits above the list, with one sentence per non-zero part:
  - "15 stewardship decisions also wait, in Steward Workflow →", linking to `#/stewardship`;
  - "3 ballots also wait, in Proxy Voting →", linking to `#/voting`.

  Each is singular at 1. There is no note when both parts are 0 or the count is unknown.
- **Phone:** the visible text is already a bare number, so PR #484's visually hidden "items" word goes.
- **DESIGN.md:** the "Needs you" count is described as "everything waiting for a decision: open review items, open stewardship
  decisions and undecided ballots".

## Non-goals

- Changing `review_count` on run manifests (other screens use it as a run statistic).
- The Argus page's own waiting total and tiles, and StewardIQ's per-step lines. They stay as they are; they are parts of the same
  sources.
- Client-stream flows. Only the house flow is counted, as StewardIQ does today.
- Speed. `flow()` and `list_open_items` now run on every navigation. *shortcut:* acceptable at today's data size. Add a
  short-lived cache, or count from an index, once `/api/waiting` takes more than 300 ms on real data.

## Anti-goals

- A waiting number on any screen that is not one of the badge's parts.
- A badge showing `0` or a guessed number when the count could not be loaded.
- Amber used for anything but waiting.

## Approaches

1. **New `/api/waiting` (chosen).** One small request, counted by the same server code the screens use. It costs a backend change
   and the contract regeneration.
2. **Frontend only.** Download the full item list, the flow and every voting queue on each navigation. That is a heavy payload.
   Rejected.
3. **Fix the stored `review_count`.** This touches every pipeline that writes it, old runs stay wrong, and it still leaves out
   decisions and ballots. Rejected.

## Supersedes

These earlier checks are replaced:
- `2026-11-15-start-page-simplified` AC-4 and AC-5 (badge text `N items` and its source).
- `2026-11-15-app-wide-top-bar` AC-19 (`N items` / `N review items waiting on you`).

These tests are changed:
- `frontend/tests/workspaceCard.test.ts`: `sp_ac4_review_badge` becomes `waitingBadge`'s tests.
- `frontend/tests/startTopbar.test.ts`:
  - `sp_ac5_same_badge_source` asserts that `AppTopbar` calls `waitingBadge(` and that `App.tsx` passes the `/api/waiting`
    response.
  - `pr1_*` checks that mention `reviewBadge` follow suit.
- `frontend/src/lib/nav.ts` `navCount`: removed if nothing else uses it, along with its test in `nav.test.ts`.
- `backend/tests/e2e/test_app_smoke.py`:
  - `test_top_bar_two_rows_at_360` and `test_top_bar_controls_never_overlap_on_tablets` rewrite `/api/waiting` to
    `{"review": 100, "decisions": 20, "ballots": 3, "total": 123}`, instead of rewriting `/api/runs`;
  - the badge `aria-label` assertion (~l.152) expects the new title.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The API on a fixture run store | `GET /api/waiting` | 200 with exactly the keys `review`, `decisions`, `ballots` and `total`, all integers, and `total == review + decisions + ballots` | unit |
| AC-2 | A fixture store with open items in two reviewable runs | `GET /api/waiting` and `GET /api/review/items` | `review` equals the length of `items` | unit |
| AC-3 | A fixture extraction item that is not high-risk and needs no second review | It is decided `approve` | `review` drops by exactly 1 | unit |
| AC-3b | A fixture item that needs a second review | Its first review is recorded | `review` is unchanged | unit |
| AC-4 | A house flow stubbed with 2 `tier_change` decisions and 1 `outreach` decision in `checkpoint`, 1 `commitment_due` in `tracking`, and 3 decisions in another stage | `GET /api/waiting` | `decisions` is 4 | unit |
| AC-4b | A fixture `proxy_voting` run with 5 queued ballots, 2 of them decided | `GET /api/waiting` | `ballots` is 3 | unit |
| AC-5 | `lib/workspaceCard.ts` | `waitingBadge({review: 82, decisions: 15, ballots: 3, total: 100})` | Returns `{text: "100", title: "100 waiting for a decision: 82 review items, 15 stewardship decisions, 3 ballots"}` | unit |
| AC-6 | The same | Called with `{1,0,0,1}`, then `{0,1,0,1}`, then `{0,0,1,1}`, then `{0,0,0,0}` (review, decisions, ballots, total) | Titles: `1 waiting for a decision: 1 review item`, then `1 waiting for a decision: 1 stewardship decision`, then `1 waiting for a decision: 1 ballot` (text `"1"` each time), then `null` | unit |
| AC-7 | The running app, 1440×900; `/api/waiting` stubbed to `{82, 15, 3, 100}`; `/api/runs` stubbed so every run has `review_count` 999 | Any route loads | The Review Queue badge text is `100` and its `aria-label` is AC-5's title | evaluator |
| AC-8 | A stack with at least one open review item; `#/review` with the "All runs" filter and nothing decided on the page | The page loads | The number in "N awaiting a decision" equals `GET /api/waiting`'s `review` | evaluator |
| AC-9 | `/api/waiting` stubbed to `{0, 15, 3, 18}` | `#/review` loads | Above the list are "15 stewardship decisions also wait, in Steward Workflow →" (link `#/stewardship`) and "3 ballots also wait, in Proxy Voting →" (link `#/voting`) | evaluator |
| AC-9b | `/api/waiting` stubbed to `{5, 0, 0, 5}` | `#/review` loads | Neither sentence is shown | evaluator |
| AC-10 | `/api/waiting` answering 500 | Any route loads | The Review Queue link has no badge, and `#/review` shows no "also wait" note | evaluator |
| AC-11 | A stack with an open single-review item | That item is decided `approve` in the Review Queue | Within 2 s the badge's number is one lower | evaluator |
| AC-13 | `DESIGN.md` | Read | The "Needs you" count entry contains "open review items, open stewardship decisions and undecided ballots" | unit |
| AC-14 | 360×800; `/api/waiting` stubbed to `{100, 20, 3, 123}` | `#/stewardiq` loads | The top bar keeps exactly two rows, and the page does not scroll sideways | evaluator |

Must not change:
- the Argus and StewardIQ counts (non-goal);
- the badge's place on the Review Queue link and its amber look;
- the badge hiding at 0 or on failure (AC-6, AC-10).
