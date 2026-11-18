# Night Desk Release 6 (waiting link target) Implementation Plan

**Goal:** The start page waiting link opens `#/stewardiq` when the Review Queue is empty and stewardship decisions are open; otherwise `#/review`.

**Spec:** `docs/superpowers/specs/2026-11-09-night-desk-waiting-link-design.md`

## Global Constraints

- Sentence, total, counts and "What counts?" unchanged; `useWaitingTotal`'s return stays `number | null | "error"`.
- No backend change.

## Review Focus

- Queue and stewardship must come from the same fetch as the total, so the link never disagrees with the number.
- While items are still loading the link is not shown (today's guard), so the split is never read early.

### Task 1: Helpers

**Files:** Modify `frontend/src/lib/workspaceCard.ts`; Test `frontend/tests/workspaceCard.test.ts` (append)

- [ ] Tests `r6_ac1`..`r6_ac8` with the spec rows' exact calls; run `cd frontend && node --test --experimental-strip-types tests/workspaceCard.test.ts`, expect failure.
- [ ] Add `waitingTarget(queue, stewardship)`; give `waitingLink` a 4th parameter `target: "#/review" | "#/stewardiq" = "#/review"`. Run again, expect pass. Commit.

### Task 2: Wire the start page

**Files:** Modify `frontend/src/lib/useWaitingTotal.ts` (add exported `useWaitingSplit(runs, flow): { queue: number; stewardship: number }` sharing the same state, or return the split from a sibling hook reading the same fetch), `frontend/src/pages/ProcessHub.tsx` (`waitingLink(known, error, needsTotal, waitingTarget(queue, stewardship))`).

- [ ] Smallest wiring: move the hook's state to return `{ total, queue, stewardship }` internally and keep `useWaitingTotal` returning `total` for other callers.
- [ ] `npm run lint && npx tsc -b && npm test` exit 0. Playwright check: with the e2e seed the link's `href` is `#/stewardiq`. Commit, push, PR.
