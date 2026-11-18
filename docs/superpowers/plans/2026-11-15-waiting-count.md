# One waiting count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The top-bar badge shows one number for everything waiting on a decision: open review items, open stewardship
decisions and undecided ballots. A new `GET /api/waiting` counts all three, and the badge's label and the Review Queue name the
parts.

**Architecture:**
- The backend counts in one pure function, `waiting_counts`, which takes the run store, the caller and a house-flow dict.
- A thin router serves it.
- The frontend gets one pure helper, `waitingBadge`, which feeds the badge and the Review Queue note. App fetches
  `/api/waiting` where it used to sum `review_count`.

**Tech Stack:** FastAPI + Pydantic, pytest; React 19 + TS; `node --test` source checks; Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-11-15-waiting-count-design.md`, all rows AC-1 to AC-14.

**Starts from:** `main` after PR #484 (app-wide top bar) merges. The badge lives in `frontend/src/components/AppTopbar.tsx`.

## Global Constraints

- Response keys are exactly `review`, `decisions`, `ballots` and `total`, with `total = review + decisions + ballots`.
- Badge visible text: `total` alone.
- Title and `aria-label`: `<total> waiting for a decision: <review> review items, <decisions> stewardship decisions, <ballots> ballots`.
  Each part is singular at 1, and parts at 0 are left out.
- No badge when `total` is 0 or the request fails.
- Review Queue note sentences: "N stewardship decisions also wait, in Steward Workflow →" (link `#/stewardship`) and "N ballots
  also wait, in Proxy Voting →" (link `#/voting`). Singular at 1.
- `decisions` counts only the house flow's stages `checkpoint` and `tracking`.
- `review_count` on manifests is not changed. `listAllRuns` stays in App for the palette's recent runs.
- Amber only for waiting. Every changed or retired test is listed in the PR.

## Review Focus

- **A decision made in another tab.** The badge refreshes on navigation and after decisions in this tab, which is fine. A stale
  badge must never show a negative number or `NaN`. Test: Task 2, `wc_waiting_badge_rejects_bad_input` (non-integer or negative
  parts give `null`).
- **House flow failing to build** (for example a broken policy file). Counting `decisions` as 0 would be a guess the spec forbids.
  Rule: on a `flow()` exception the endpoint answers 503 with a plain message, and the badge hides, as for any failure. Test:
  Task 1, `test_broken_flow_is_503`.
- **A proxy-voting run with no review queue file yet** (still running). It must count as 0 ballots, not crash. Test: Task 1,
  `test_ballots_zero_without_queue`.
- **Item keys decided twice** (a decision changed). They count once as decided, never below 0. Test: Task 1,
  `test_ballots_changed_decision_counts_once`.
- **The Review Queue note while the queue is still loading.** The note doesn't flash "0". It appears only once `/api/waiting`
  answers. Covered by AC-9b and AC-10 in Task 3.

---

### Task 1: `waiting_counts` and `GET /api/waiting`

**Files:**
- Create: `backend/arp/review/waiting.py`
- Create: `backend/arp/api/routers/waiting.py`, registered in `backend/arp/api/main.py` next to `review.router` (same `authorize`
  dependency)
- Modify: `backend/openapi.json` and `frontend/src/api/schema.gen.ts` (regenerated); `frontend/src/api/client.ts` (add
  `getWaiting`)
- Test: `backend/tests/test_waiting.py`

**Interfaces:**
- Produces:
  - `class WaitingCounts(BaseModel): review: int; decisions: int; ballots: int; total: int`
  - `def waiting_counts(run_store: RunStore, principal: Principal, house_flow: dict) -> WaitingCounts`
  - `GET /api/waiting` → `WaitingCounts`, built from `flow(HOUSE, streams, engagements.list_all(), settings.engagement_sla_days)`.
    If `flow()` raises, it returns 503 "Stewardship decisions could not be counted".
  - Frontend: `api.getWaiting(): Promise<Served<S["WaitingCounts"]>>`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_waiting.py`. Use the fixture run-store pattern of
  `tests/test_review_decide.py::env` for review items. Test names and assertions:
  - `test_ac1_shape`: the response keys are exactly `{review, decisions, ballots, total}`, and `total == review + decisions + ballots`.
  - `test_ac2_review_equals_open_items`: `review == len(list_open_items(rs, principal))`, with open items in two reviewable runs.
  - `test_ac3_single_review_approve_drops_one`: a non-high-risk item that needs no second review, decided `approve` via `decide(...)`,
    makes `review` drop by exactly 1.
  - `test_ac3b_first_of_two_unchanged`: an item that needs a second review gets its first review, and `review` is unchanged.
  - `test_ac4_decisions_checkpoint_and_tracking_only`: `house_flow = {"stages": [{"id": "checkpoint", "decisions": [3 items]},
    {"id": "tracking", "decisions": [1 item]}, {"id": "voting", "decisions": [3 items]}]}` gives `decisions == 4`.
  - `test_ac4b_ballots`: a `proxy_voting` run with 5 queued item keys, 2 of them with recorded decisions, gives `ballots == 3`.
  - `test_ballots_zero_without_queue`: a `proxy_voting` manifest with no queue file gives `ballots == 0`.
  - `test_ballots_changed_decision_counts_once`: one key decided twice gives `ballots == 4`, out of 5 queued.
  - `test_broken_flow_is_503`: with `flow` patched to raise, `GET /api/waiting` returns 503.
  - `test_endpoint_200`: `GET /api/waiting` through `TestClient` returns 200 with the AC-1 shape.
- [ ] **Step 2:** Run `cd backend && python3 -m pytest tests/test_waiting.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `waiting_counts` and the router.**
  - `review = len(list_open_items(run_store, principal))`.
  - `decisions = sum(len(s["decisions"]) for s in house_flow["stages"] if s["id"] in {"checkpoint", "tracking"})`.
  - `ballots = sum(len({q["item_key"] for q in run_store.read_review_queue(m.run_id)} - set(latest_decisions(run_store, m.run_id))) for m in run_store.list_runs() if m.run_type == "proxy_voting")`.
    A missing queue file reads as an empty list; check what `read_review_queue` does first.
  - Add a one-line `shortcut:` comment on the router: `flow()` and `list_open_items` run per request; cache when the endpoint
    takes more than 300 ms.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then `ruff check .`.
- [ ] **Step 5: Contract.**
  1. `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`.
  2. Add `getWaiting: () => request<Served<S["WaitingCounts"]>>("/api/waiting")` to `client.ts`, matching the neighbouring style.
  3. `npx tsc -b`. Expected: clean.
- [ ] **Step 6:** Commit `feat(api): /api/waiting counts review items, stewardship decisions and ballots`.

### Task 2: `waitingBadge`, the badge and the Review Queue note

**Files:**
- Modify: `frontend/src/lib/workspaceCard.ts`. Add `waitingBadge`, and delete `reviewBadge` once nothing uses it.
- Modify: `frontend/src/App.tsx`. Replace the `review_count` sum with `api.getWaiting()`, on the same triggers as today:
  `[route, decidedAt]`, setting `waiting` to `null` on failure. `waiting` becomes `WaitingCounts | null`.
- Modify: `frontend/src/components/AppTopbar.tsx`. The prop becomes `waiting: WaitingCounts | null` instead of
  `reviewCount: number`; the badge uses `waitingBadge`; the visually hidden `.nav-count-word` and its CSS go.
- Modify: `frontend/src/lib/nav.ts`. Delete `navCount` if nothing else uses it (grep first).
- Modify: `frontend/src/pages/ReviewQueue.tsx`. Add the "also wait" note above the list. It reads `api.getWaiting()` once on
  mount and shows nothing until the response arrives.
- Test: `frontend/tests/workspaceCard.test.ts`, `frontend/tests/startTopbar.test.ts`, `frontend/tests/nav.test.ts`

**Interfaces:**
- Consumes: `api.getWaiting()` (Task 1).
- Produces:
  - `waitingBadge(w: {review: number; decisions: number; ballots: number; total: number}): {text: string; title: string} | null`
  - `alsoWaiting(w): {text: string; href: string}[]`, also in `workspaceCard.ts`.

- [ ] **Step 1: Write the failing tests.** Replace `sp_ac4_review_badge` with:
  - `wc_ac5_waiting_badge`: `waitingBadge({review: 82, decisions: 15, ballots: 3, total: 100})` deep-equals
    `{text: "100", title: "100 waiting for a decision: 82 review items, 15 stewardship decisions, 3 ballots"}`.
  - `wc_ac6_singulars_and_zero`: the four cases from spec AC-6, exactly.
  - `wc_waiting_badge_rejects_bad_input`: `{review: -1, …}`, `{total: NaN, …}`, or a `total` that is not the sum gives `null`.
  - `wc_also_waiting`: `alsoWaiting({review: 0, decisions: 15, ballots: 3, total: 18})` deep-equals
    `[{text: "15 stewardship decisions also wait, in Steward Workflow →", href: "#/stewardship"}, {text: "3 ballots also wait, in Proxy Voting →", href: "#/voting"}]`.
    `{1, 1, 0, 2}` gives a singular "1 stewardship decision also waits…". `{5, 0, 0, 5}` gives `[]`.

  In `startTopbar.test.ts`:
  - `sp_ac5_same_badge_source` asserts `AppTopbar.tsx` includes `waitingBadge(` and `App.tsx` includes `getWaiting(`.
  - Add `wc_ac12_no_review_count_sum`: `App.tsx` no longer contains `review_count`.

  In `nav.test.ts`: retire the `navCount` test if `navCount` is deleted, and note it.
- [ ] **Step 2:** Run `cd frontend && npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the helpers, the App fetch, the AppTopbar prop and badge, the Review Queue note (a `<p className="help-text">`
  with links, placed directly above `.split-review`), and the removals.
- [ ] **Step 4:** Run `npm test && npx tsc -b && npm run lint`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(nav): one waiting count on the badge; Review Queue names the other parts`.

### Task 3: DESIGN.md, e2e, verification and PR

**Files:**
- Modify: `DESIGN.md`. In the "Needs you" count entry, and the Signal Amber line if it describes the count, use the spec's exact phrase.
- Modify: `backend/tests/e2e/test_app_smoke.py`. `_long_badge` rewrites `**/api/waiting` to
  `{"review": 100, "decisions": 20, "ballots": 3, "total": 123}`. The 360px test asserts the badge `aria-label`
  is `123 waiting for a decision: 100 review items, 20 stewardship decisions, 3 ballots`.
- Test: `frontend/tests/designDoc.test.ts`: add `wc_ac13_design_md`.

- [ ] **Step 1:** Write `wc_ac13_design_md` and the e2e edits. Add e2e tests:
  - `test_badge_reads_waiting_not_runs` (AC-7: stub `/api/runs` with `review_count` 999 and `/api/waiting` with `{82, 15, 3, 100}`;
    the badge text is `100`);
  - `test_review_queue_names_other_parts` (AC-9, stubbed `{0, 15, 3, 18}`);
  - `test_review_queue_no_note` (AC-9b `{5, 0, 0, 5}`, and AC-10 with `/api/waiting` stubbed to 500: no badge and no note).

  Run them. Expected: FAIL.
- [ ] **Step 2:** Edit DESIGN.md. Rebuild (`vite build`), then run `pytest -m e2e tests/e2e/test_app_smoke.py`. Expected: PASS.
- [ ] **Step 3: Evaluator rows on the stack.**
  - AC-8: the number in "N awaiting a decision" equals `review` from `curl /api/waiting`.
  - AC-11: decide one single-review item and see the badge drop by 1 within 2 s.
  - AC-14 at 360×800.

  Save screenshots.
- [ ] **Step 4:** Full e2e suite, `/impeccable:impeccable audit` on `#/review` and the top bar, and a fresh whole-branch review. Fix
  Critical and Important findings, each with a failing test first.
- [ ] **Step 5:** Merge `origin/main` and push. Open a PR against `main` with label `risk:normal` and `Spec: waiting-count` in the
  body, listing every changed or retired test. Ask the owner for `tests-weakened-ok` if any test was retired.
