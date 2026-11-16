# Showcase runs with real sign-in

Slug: showcase-login-origins

Risk: `risk:high` for the build (sign-in and permissions). Size S, 1 PR: run book, install guide, launch script.

Status: owner's choices recorded 16 Nov 2026 (buttons in the spec session); waiting for approval of this spec.
Source: security review of PR #529 (`voting-api-login`), 16 Nov 2026, point 1; the owner chose "fix it as its own
item". Checked against `origin/main` `bb70169` and PR #529 head `279f4a4`.

## Why

In `auth_mode` `dev` (the default, `backend/arp/config.py:86`) a request from loopback or `dev_trusted_networks`
is signed in as the dev user, role `approver`. `current_user` (`backend/arp/api/auth.py:69-73`) withholds that
when the request's `Origin` is not in `allowed_origins`, but treats `"*"` there as "any origin". CORS
(`backend/arp/api/main.py:155-162`) takes `allow_origins` from the same setting with `allow_credentials=True`.

The showcase settings (`docs/INSTALLATION.md`, section "Bank Jupyter (Vertex)"; spec `bank-jupyter-launch`) are
`ARP_AUTH_MODE=dev`, `ARP_DEV_TRUSTED_NETWORKS=["0.0.0.0/0"]`, `ARP_ALLOWED_ORIGINS=["*"]`. So while ARP runs
on the bank JupyterLab, any other website open in the same browser can act as the approver.

**Reproduced** on 16 Nov in this session: PR #529's head, one uvicorn process on Postgres with exactly those three
settings plus `ARP_TRUSTED_HOSTS=["*"]`.

- `POST /api/voting/runs/x_none/cast` with `Origin: https://evil.example` and no token: `200
  {"cast_count":0,"votes":[]}`, with `access-control-allow-origin: https://evil.example` and
  `access-control-allow-credentials: true`. The same happens with `Origin: null`.
- The CORS preflight for that origin answers 200 with the same two headers. So a foreign page can also send JSON
  writes and **read the replies** (a `GET …/review-queue` came back the same way).
- With `ARP_AUTH_MODE=local` and a users file, and nothing else changed: no token gives 401, from a foreign origin
  and from loopback alike. An approver token casts (200). A viewer token reads (200) but cannot cast (403).

`launch_jupyter.sh up` binds `0.0.0.0`. So with `["0.0.0.0/0"]`, anyone on the bank network who can reach port
8000 directly is the approver too, with no browser involved. Local mode closes that as well.

## What the owner decided (16 Nov 2026)

- **The showcase uses real sign-in** (`ARP_AUTH_MODE=local`). The presenter pastes a token once into the
  "Access token" box at the top left. That box, `config/users.json` and `scripts/launch_jupyter.sh users` exist
  today. **No change to the app's sign-in code.** Dev mode with `"*"` stays possible on other installs. The guide
  and README warn against it.
- **Analysts who get the link can do nothing.** No token is handed out except the presenter's. Without one they
  see the token box and every API call answers 401.

Not chosen: (b) keep dev mode with the exact proxy origin. Everyone with the link stays the one anonymous approver,
and direct network access still is. (c) Both, plus an app-side refusal of dev mode with `"*"`.

## Goals

- The showcase install signs nobody in without a token.
- The run book says, step by step, how the presenter gets and uses a token, including for the loader script.
- `launch_jupyter.sh up` will not start the showcase in dev mode, so a forgotten `.env` line fails loudly the day
  before rather than silently reopening the gap.

## Non-goals

- Any change under `backend/arp/` (auth, CORS, config defaults).
- SSO or per-analyst accounts; a read-only analyst token.
- Changing the e2e stack (`backend/scripts/e2e_stack.sh` keeps dev mode with the two localhost origins; it never
  had `"*"`), or `backend/tests/e2e/test_proxy_prefix.py` (dev mode with `"*"` behind a test proxy, loopback only).

## Design

1. **`scripts/launch_jupyter.sh up`** refuses to start unless `setting ARP_AUTH_MODE` is `local`. It runs this
   check with the existing required-settings check, before touching the database. It prints AC-5's line to stderr
   and exits 1. Unset counts as not `local`, since the app's default is `dev`. `down`, `check` and `users` are
   unchanged.
2. **`docs/INSTALLATION.md`, "Bank Jupyter (Vertex)"**: the `.env` block replaces the four sign-in lines with
   `ARP_AUTH_MODE=local`, `ARP_USERS_FILE=<repo>/config/users.json` and `ARP_TRUSTED_HOSTS=["*"]`.
   `ARP_DEV_TRUSTED_NETWORKS` and `ARP_ALLOWED_ORIGINS` are gone: in local mode the page and the API share one
   origin through the proxy, so CORS plays no part. The steps become `users` → paste the two printed lines into
   `.env` → `up`. "Sign-in behind the proxy" and "Two reviewers" are rewritten to match. One sentence says never to
   combine `ARP_AUTH_MODE=dev` with `ARP_ALLOWED_ORIGINS=["*"]`, and why. `README.md`'s sign-in section
   (about line 112) gets the same sentence, because its claim that another website gets no bypass is false with
   `"*"`.
3. **Run book**, `demo/showcase/RUN_SHEET.md` "Day before" and `demo/showcase/README.md`: before `up`, run
   `scripts/launch_jupyter.sh users` once. Edit the first reviewer's `name` to the presenter's name, since the
   release in step 4 records it. Add the two lines to `backend/.env`. The loader step becomes
   `ARP_SHOWCASE_TOKEN=<first token> python scripts/load_showcase_pack.py`, so its voting run is created as that
   user. Then sign in once in the browser you present from. The second token is for a second review only. Hand
   out no token: an analyst who opens the link sees the token box and nothing else. Keep the tokens out of
   screen-shared windows. "Start from an empty database" keeps `config/users.json`.
4. **Spec `voting-api-login`, row AC-10** (edited in the build PR). Its Given loses "(the bank JupyterLab
   settings)" and reads "(the showcase settings before spec `showcase-login-origins`; no install guide uses them
   now)". The "Must not change" line drops "also under the showcase settings (AC-10)". A note under the table says
   AC-10 pins a known gap, not a promise: a later fix that refuses this combination retires the row. The row's
   expected result stays as written, because the app code does not change. So its test
   (`test_auth.py::test_voting_cast_open_under_showcase_dev_settings`, and any hidden test written for it) keeps
   passing. Only a name or comment that calls these "the showcase settings" is reworded. Nothing is deleted or
   weakened.

**Requests without an `Origin` header.** In local mode nothing changes for them, and nothing needs to: every
request needs a token, with or without `Origin`, from loopback too (AC-3). A cross-site attack needs the browser
to add the credential by itself. A bearer token in the app's own storage is never added that way. In dev mode
(other installs) Origin-less requests keep today's rule.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| A (owner's pick) | Showcase in local mode; run book, guide and launch script only | Closes the gap and direct network access for the showcase; dev mode with `"*"` still opens it elsewhere |
| B | Keep dev mode, exact proxy origin, `"*"` disables the bypass | No token to paste; everyone with the link stays the one approver, and so does anyone reaching port 8000 directly |
| C | A plus an app-side refusal of dev mode with `"*"` | Closes it for every install; a code change and its tests on top |

## Left to the builder

The wording of the run-book and guide paragraphs, within design points 2 and 3.

## Sequencing

After PR #529 merges. AC-1, AC-2 and AC-4 use `/api/voting`, which needs sign-in only from #529 on.

## Acceptance

Settings "Showcase-local" for every row that names them: `ARP_AUTH_MODE=local`, `ARP_USERS_FILE` pointing at a
users file with an `approver` token `tok_presenter` (user `u_presenter`, name `Presenter`), and
`ARP_TRUSTED_HOSTS=["*"]`. The worst case leaves the old lines in: `ARP_DEV_TRUSTED_NETWORKS=["0.0.0.0/0"]`,
`ARP_ALLOWED_ORIGINS=["*"]`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Showcase-local, the old `ARP_DEV_TRUSTED_NETWORKS` and `ARP_ALLOWED_ORIGINS` lines still set | `POST /api/voting/runs/ac1_none/cast` from client `10.1.2.3` with header `Origin: https://evil.example` and no `Authorization` header | Status 401, header `WWW-Authenticate: Bearer` | holdout |
| AC-2 | AC-1's settings | `GET /api/voting/runs/ac2_none/review-queue` from client `10.1.2.3` with header `Origin: https://evil.example` and no `Authorization` header | Status 401 | holdout |
| AC-3 | AC-1's settings | `POST /api/voting/runs/ac3_none/cast` from `127.0.0.1` with no `Origin` and no `Authorization` header | Status 401 (no dev sign-in from loopback in local mode) | holdout |
| AC-4 | Showcase-local, `ARP_DEV_TRUSTED_NETWORKS` and `ARP_ALLOWED_ORIGINS` unset (the new guide) | `POST /api/voting/runs/ac4_none/cast` from client `10.1.2.3` with header `Origin: https://hub.example` and `Authorization: Bearer tok_presenter` | Status 200, body `{"cast_count": 0, "votes": []}` | holdout |
| AC-5 | `ARP_POSTGRES_DSN`, `ARP_LLM_MODEL`, `ARP_LLM_VERIFIER_MODEL` set; `ARP_AUTH_MODE=dev` (and, separately, unset); no `backend/.env`; `ARP_LAUNCH_PORT=8765` | `scripts/launch_jupyter.sh up` | Exit status 1; stderr contains the line `ARP_AUTH_MODE must be local for this launch: run scripts/launch_jupyter.sh users, add the two lines it prints to backend/.env, then up again`; nothing answers on `http://127.0.0.1:8765/api/health` | holdout |
| AC-6 | Postgres from `ensure-deps.sh postgres`, `backend/.env` with the new guide's sign-in lines and a users file from `scripts/launch_jupyter.sh users`, `JUPYTERHUB_SERVICE_PREFIX=/user/x/` | `scripts/launch_jupyter.sh up` | Stdout has exactly one line containing `/user/x/proxy/8000/`, and `GET http://localhost:8000/api/health` returns 200 (`bank-jupyter-launch` AC-11a, must not change) | evaluator |
| AC-7 | AC-6's running app | A browser with no stored token opens `http://localhost:8000/` | The top-left shows the label `Access token` and an input with placeholder `Paste your token`. After a token from the users file is pasted and Enter pressed, it shows `Signed in as First Reviewer (approver)` and a `Sign out` button | evaluator |
| AC-8 | The build is merged | `docs/INSTALLATION.md`, section `## Bank Jupyter (Vertex)`, is read | It contains `ARP_AUTH_MODE=local`, `ARP_USERS_FILE` and `scripts/launch_jupyter.sh users`. It does not contain `ARP_AUTH_MODE=dev`, `0.0.0.0/0` or `ARP_ALLOWED_ORIGINS=["*"]` | unit |
| AC-9 | The build is merged | `demo/showcase/RUN_SHEET.md`, section `## Day before`, is read | `scripts/launch_jupyter.sh users` appears before the first `scripts/launch_jupyter.sh up`, and the loader command contains `ARP_SHOWCASE_TOKEN=` | unit |
| AC-10 | The build is merged | `docs/superpowers/specs/2026-11-15-voting-api-login.md` is read | Row AC-10's Given contains `showcase-login-origins` and not `the bank JupyterLab settings`; the `Must not change` line does not contain `AC-10` | unit |

Must not change: `voting-api-login` AC-1 to AC-9 (dev mode with the e2e stack's settings: loopback dev sign-in still
reads and casts); `launch_jupyter.sh up` with a valid local-mode `.env` (AC-6).
