# Showcase runs with real sign-in

Slug: showcase-login-origins

Risk: `risk:high` for the build (sign-in and permissions). Size S, 1 PR: launch script, install guide, root `README.md`, run book (`RUN_SHEET.md`,
`demo/showcase/README.md`), and two earlier specs' rows (`voting-api-login` AC-10, `bank-jupyter-launch` AC-11a).

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
- `scripts/launch_jupyter.sh up` refuses to start any install unless `ARP_AUTH_MODE=local`, so a forgotten `.env`
  line fails loudly the day before rather than silently reopening the gap. Dev mode stays possible only when the
  API is started some other way (e2e stack, compose, plain uvicorn).

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
   `.env` → `up`. "Sign-in behind the proxy" and "Two reviewers" are rewritten to match, and the section's prose
   (outside the `ini` block) gets this sentence, verbatim: *Never combine `ARP_AUTH_MODE=dev` with
   `ARP_ALLOWED_ORIGINS=["*"]`: `"*"` lets any website open in the same browser act as the dev approver.*
   `README.md`'s sign-in section gets the same sentence, and its clause "so another website cannot act as you"
   (about line 112), false with `"*"`, is reworded so it no longer says `another website cannot`.
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
   passing. Its function name stays; only comments that call these "the showcase settings" are reworded.
   Nothing is deleted, renamed or weakened.
5. **Spec `bank-jupyter-launch`, row AC-11a** (edited in the build PR): "a valid `backend/.env`" becomes "a valid
   `backend/.env` (with `ARP_AUTH_MODE=local` and `ARP_USERS_FILE` pointing at an existing users file, spec
   `showcase-login-origins`)". The rows that start "After AC-11a" follow from it unchanged.

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

After PR #529 merges. AC-1 to AC-4 and AC-11 use `/api/voting`, which needs sign-in only from #529 on.

## Acceptance

Settings "Showcase-local" for every row that names them: `ARP_AUTH_MODE=local`, `ARP_USERS_FILE` pointing at a
users file with an `approver` token `tok_presenter` (user `u_presenter`, name `Presenter`), and
`ARP_TRUSTED_HOSTS=["*"]`. The `unit` rows that send requests use the real app in process with the client address
set, like `real_client_at` in `backend/tests/test_auth.py`; the e2e stack stays in dev mode (Non-goals).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Showcase-local, and the old lines left in: `ARP_DEV_TRUSTED_NETWORKS=["0.0.0.0/0"]`, `ARP_ALLOWED_ORIGINS=["*"]` | `POST /api/voting/runs/ac1_none/cast` from client `10.1.2.3` with header `Origin: https://evil.example` and no `Authorization` header | Status 401, header `WWW-Authenticate: Bearer` | unit |
| AC-2 | AC-1's settings | `GET /api/voting/runs/ac2_none/review-queue` from client `10.1.2.3` with header `Origin: https://evil.example` and no `Authorization` header | Status 401 | unit |
| AC-3 | AC-1's settings | `POST /api/voting/runs/ac3_none/cast` from `127.0.0.1` with no `Origin` and no `Authorization` header | Status 401 | unit |
| AC-11 | AC-1's settings | `POST /api/voting/runs/ac11_none/cast` from client `10.1.2.3` with no `Origin` and no `Authorization` header (a direct call on the bank network) | Status 401 | unit |
| AC-4 | Showcase-local, `ARP_DEV_TRUSTED_NETWORKS` and `ARP_ALLOWED_ORIGINS` unset (the new guide) | `POST /api/voting/runs/ac4_none/cast` from client `10.1.2.3` with header `Origin: https://hub.example` and `Authorization: Bearer tok_presenter` | Status 200, body `{"cast_count": 0, "votes": []}` | unit |
| AC-5a | `ARP_POSTGRES_DSN`, `ARP_LLM_MODEL`, `ARP_LLM_VERIFIER_MODEL` set in the environment; `ARP_AUTH_MODE=dev` in the environment; `ARP_LAUNCH_PORT=8765` | `scripts/launch_jupyter.sh up` | Exit status 1; stderr contains the line `ARP_AUTH_MODE must be local for this launch: run scripts/launch_jupyter.sh users, add the two lines it prints to backend/.env, then up again`; nothing answers on `http://127.0.0.1:8765/api/health` | holdout |
| AC-5b | AC-5a's settings, but `ARP_AUTH_MODE` not in the environment and no `backend/.env` | `scripts/launch_jupyter.sh up` | The same as AC-5a | holdout |
| AC-6a | The e2e stack is down; Postgres from `ensure-deps.sh postgres`; `backend/.env` has `ARP_POSTGRES_DSN`, `ARP_LLM_MODEL`, `ARP_LLM_VERIFIER_MODEL` and the guide's three sign-in lines (`ARP_AUTH_MODE=local`, `ARP_USERS_FILE=<repo>/config/users.json`, `ARP_TRUSTED_HOSTS=["*"]`); the users file from `scripts/launch_jupyter.sh users`; `JUPYTERHUB_SERVICE_PREFIX=/user/x/` | `scripts/launch_jupyter.sh up` | Stdout has exactly one line containing `/user/x/proxy/8000/` (must not change) | evaluator |
| AC-6b | After AC-6a | `GET http://localhost:8000/api/health` | Status 200 (must not change) | evaluator |
| AC-7a | AC-6a's running app | A browser with no stored token opens `http://localhost:8000/` | The top left shows the label `Access token` and an input with placeholder `Paste your token` | evaluator |
| AC-7b | After AC-7a | The First Reviewer token from the users file is pasted into that input and Enter pressed | The page shows `Signed in as First Reviewer (approver)` and a `Sign out` button | evaluator |
| AC-8 | The build is merged | `docs/INSTALLATION.md`, section `## Bank Jupyter (Vertex)`, is read | Its `ini` block contains `ARP_AUTH_MODE=local` and `ARP_USERS_FILE`, and does not contain `ARP_AUTH_MODE=dev`, `ARP_DEV_TRUSTED_NETWORKS` or `ARP_ALLOWED_ORIGINS`; the section contains `scripts/launch_jupyter.sh users` | unit |
| AC-12 | The build is merged | `docs/INSTALLATION.md` section `## Bank Jupyter (Vertex)` and `README.md` are read | Each contains the sentence of design point 2 verbatim; `README.md` does not contain `another website cannot` | unit |
| AC-9 | The build is merged | `demo/showcase/RUN_SHEET.md`, section `## Day before`, is read | `scripts/launch_jupyter.sh users` appears before the first `scripts/launch_jupyter.sh up`, and every line containing `load_showcase_pack.py` also contains `ARP_SHOWCASE_TOKEN=` | unit |
| AC-13 | The build is merged | `demo/showcase/README.md` is read | `scripts/launch_jupyter.sh users` appears before the first `scripts/launch_jupyter.sh up`, and every line containing `load_showcase_pack.py` also contains `ARP_SHOWCASE_TOKEN=` | unit |
| AC-10 | The build is merged | `docs/superpowers/specs/2026-11-15-voting-api-login.md` is read | Row AC-10's Given contains `showcase-login-origins` and not `the bank JupyterLab settings`; the `Must not change` line does not contain `AC-10` | unit |
| AC-14 | The build is merged | `docs/superpowers/specs/2026-11-11-bank-jupyter-launch-design.md` is read | Row AC-11a's Given contains `ARP_AUTH_MODE=local` and `showcase-login-origins` | unit |
| AC-15 | No `config/users.json` (a temporary repo copy) | `scripts/launch_jupyter.sh users` | Exit 0; stdout contains the lines `  ARP_AUTH_MODE=local` and `  ARP_USERS_FILE=<repo>/config/users.json` (must not change) | unit |

Must not change: AC-6a, AC-6b, AC-15 here. The regression guard for dev mode is `voting-api-login` AC-1 to AC-9
(loopback dev sign-in on the e2e stack still reads and casts), and for `down` and `check` it is `bank-jupyter-launch`
AC-16 and AC-21; no new rows for those.
