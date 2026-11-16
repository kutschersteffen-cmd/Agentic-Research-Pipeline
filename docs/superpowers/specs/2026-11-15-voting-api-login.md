# Proxy-voting API needs sign-in

Slug: voting-api-login

Risk: `risk:high` (sign-in and permissions). Size S, 1 PR, backend only.

Status: **approved by the owner on 15 Nov 2026** (buttons in the spec session, after the spec-critic
rounds). Round 2 of the findings clean-up the owner asked for on 15 Nov 2026 ("clean up further bugs and
findings"). Checked against `origin/main` `5df84c4`.

## Why

Every router in `backend/arp/api/main.py` is mounted with `dependencies=[Depends(authorize)]` except one:
`app.include_router(voting.router)`. So the seven `/api/voting` routes (create a run, read ballots, read the review
queue and history, record a review decision, cast votes, read cast votes) answer anyone who can reach the server,
signed in or not. `backend/tests/test_auth.py::test_voting_router_unchanged` pins that open behaviour.

It was left open on purpose in October, while voting was "frozen" (`docs/superpowers/plans/2026-10-03-step1-*`).
The freeze no longer holds: voting gets fixes like every other screen, and casting a vote is a decision that has to
be recorded against a signed-in person.

## Goals

- The voting router gets the same sign-in rule as the stewardship routers: `authorize` (a viewer may read, an
  analyst or higher may change).
- The voting screens keep working where they work today: in dev sign-in (loopback, or the trusted networks) and
  for a user with a token.

## Non-goals

- New roles, per-ballot or per-run access.
- The `reviewer` name a review decision records still comes from the form (`ReviewerField`), not from the
  signed-in user. Binding the two is a separate change.
- Any change to `arp/voting/`, the voting CLI, or the frontend.

## Approach

One sensible way: add `dependencies=[Depends(authorize)]` to the `voting.router` line, as on the other 56
routers. A per-route dependency inside `voting.py` was dropped: it repeats what `main.py` does for every router.

Checked by reading the code, no change needed:

- **The frontend already sends the token.** All six `/api/voting` calls in `frontend/src/api/client.ts`
  (`startVotingRun`, `getVotingBallots`, `getVotingReviewQueue`, `submitVotingReview`, `castVotes`, `getCastVotes`;
  nothing calls `review-history`) go
  through `request()` → `authFetch()`, which adds `Authorization: Bearer <token>` when a token is stored.
- **Dev sign-in covers the voting pages.** With `ARP_AUTH_MODE=dev` (the default), a request from loopback or
  from `ARP_DEV_TRUSTED_NETWORKS`, with no `Origin` or an allowed one, is the dev user with role `approver`, so
  reads and writes both pass.
- **The showcase loader** (`backend/scripts/load_showcase_pack.py`) creates its voting run with
  `ARP_SHOWCASE_TOKEN` when set, else through dev sign-in.

**What the showcase needs.** Nothing new. The bank JupyterLab setup (spec `bank-jupyter-launch`) runs
`ARP_AUTH_MODE=dev` with `ARP_DEV_TRUSTED_NETWORKS=["0.0.0.0/0"]` and `ARP_ALLOWED_ORIGINS=["*"]`, so everyone
who opens the proxy URL is the dev approver and the voting pages load and cast as before. Only if the showcase
switched to `ARP_AUTH_MODE=local` would the presenter need to enter an analyst (or higher) token in the sidebar
first, as on every other page.

## Test change (list it in the PR)

`backend/tests/test_auth.py::test_voting_router_unchanged` becomes `test_voting_router_requires_sign_in`: without a
token `GET /api/voting/runs/r1/review-queue` answers 401 (was: anything but 401), and with the analyst token it
answers 200. The themes assertion in the same test stays. This tightens the test; nothing is weakened.
`test_untrusted_host_header_is_400` (same file) also calls a voting route; its assertion stays, since the route
now answers 401 there, which still satisfies `!= 400`; only its comment `(not auth)` is corrected.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The app started by `backend/scripts/e2e_stack.sh up` (`ARP_AUTH_MODE`, `ARP_ALLOWED_ORIGINS` and `ARP_DEV_TRUSTED_NETWORKS` unset, so `dev`, `["http://localhost:5173", "http://127.0.0.1:5173"]` and `[]`) | `GET http://127.0.0.1:8000/api/voting/runs/ac1_none/review-queue` with header `Origin: https://example.org` and no `Authorization` header | Status 401, header `WWW-Authenticate: Bearer` | holdout |
| AC-2 | AC-1's app | Each of `POST http://127.0.0.1:8000/api/voting/runs` (body `{"companies": []}`), `GET …/runs/ac2_none/ballots`, `GET …/runs/ac2_none/review-history?item_key=k`, `POST …/runs/ac2_none/review` (body `{"item_key": "k", "decision": "approve", "reviewer": "x"}`), `POST …/runs/ac2_none/cast`, `GET …/runs/ac2_none/cast`, all with header `Origin: https://example.org` and no `Authorization` header | Each answers status 401 | holdout |
| AC-3 | AC-1's app | `GET http://127.0.0.1:8000/api/voting/runs/ac3_none/review-queue` from `127.0.0.1` with no `Origin` and no `Authorization` header (dev sign-in) | Status 200, body `{"pending": [], "decided": []}` (must not change) | holdout |
| AC-4 | `ARP_AUTH_MODE=local`, a users file with a `viewer` token and an `analyst` token | `GET /api/voting/runs/ac4_none/review-queue` with `Authorization: Bearer <viewer token>` | Status 200, body `{"pending": [], "decided": []}` | unit |
| AC-5 | AC-4's settings | `POST /api/voting/runs/ac5_none/cast` with `Authorization: Bearer <viewer token>` | Status 403, detail `Requires role 'analyst' or higher` | unit |
| AC-6 | AC-4's settings | `GET /api/voting/runs/ac6_none/review-queue` with no `Authorization` header | Status 401 | unit |
| AC-7 | AC-1's app | A user opens `#/voting/ac7_none` in the browser (this route loads the ballots, review queue and cast votes) | The page shows the heading `Proxy Voting` and no text on the page contains `401` or `Missing or invalid bearer token` (must not change) | evaluator |
| AC-8 | AC-4's settings | `POST /api/voting/runs/ac8_none/cast` with `Authorization: Bearer <analyst token>` | Status 200, body `{"cast_count": 0, "votes": []}` | unit |
| AC-10 | `ARP_AUTH_MODE=dev`, `ARP_DEV_TRUSTED_NETWORKS=["0.0.0.0/0"]`, `ARP_ALLOWED_ORIGINS=["*"]` (the bank JupyterLab settings) | `POST /api/voting/runs/ac10_none/cast` from client `10.1.2.3` with header `Origin: https://hub.example` and no `Authorization` header | Status 200, body `{"cast_count": 0, "votes": []}` (must not change) | unit |
| AC-9 | AC-1's app | `POST http://127.0.0.1:8000/api/voting/runs/ac9_none/cast` from `127.0.0.1` with no `Origin` and no `Authorization` header (dev sign-in) | Status 200, body `{"cast_count": 0, "votes": []}` (must not change) | holdout |

Must not change: dev sign-in reads and writes on `/api/voting` (AC-3, AC-9), also under the showcase settings (AC-10); the voting page loads under dev
sign-in (AC-7).
