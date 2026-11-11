# Bank Jupyter launch: Vertex, one port, one command

Slug: `bank-jupyter-launch` · Size: small project · Risk: normal

## Intent

The owner showcases ARP next week inside a JupyterLab on the bank's GCP landing zone. The copy running
there was patched in place and has drifted from `main`: it has Vertex AI settings, serves the built
frontend from the backend on port 8000, and a hand-written `LAUNCH_GUIDE.md`. None of that is in `main`,
so no fix made on GitHub reaches the showcase. The Jupyter machine can `git pull` from GitHub.

After this change, the showcase copy is `git pull` plus one command, and every later fix arrives by
`git pull`.

## The target environment (from the owner's screenshots, 2026-11-11)

- JupyterLab; the browser reaches the app through Jupyter Server Proxy at `…/user/<id>/proxy/8000/`.
- LLM: Gemini through Vertex AI, authenticated by the notebook's Google credentials, no API key.
  `ARP_LLM_MODEL` and `ARP_LLM_VERIFIER_MODEL` are both `gemini-3.6-flash`. No Anthropic access.
- Postgres with pgvector as a Kubernetes service, reached by `ARP_POSTGRES_DSN`.
- `ARP_AUTH_MODE=dev`, `ARP_DEV_TRUSTED_NETWORKS=["0.0.0.0/0"]`, `ARP_ALLOWED_ORIGINS=["*"]`,
  `ARP_TRUSTED_HOSTS=["*"]`: everyone who reaches the proxy URL is the dev approver.
- Python and npm packages come from Artifactory. GPU services for embeddings and rerank are provided
  (`ARP_COMPUTE_MODELS_URL`, `ARP_COMPUTE_PARSE_URL` already exist in `main`).
- No Superset, Neo4j, OpenSearch or MinIO.

## Goals

1. Gemini calls can go through Vertex AI with the notebook's credentials.
2. The backend serves the built frontend, and the UI works under a proxy path prefix.
3. One script starts ARP in that environment and one checks it is ready.

## Non-goals

- SSO or per-person sign-in. The showcase runs in dev sign-in mode.
- Superset, Neo4j, OpenSearch in the bank environment.
- Building the GPU service images through BuildKit and Artifactory (separate slice if needed).
- Merging the patches made inside the bank copy. They are replaced; anything they fixed that this spec
  misses comes back as a defect from the rehearsal.

## Anti-goals

- Changing behaviour for existing installs: without the new settings, everything runs as today.
- Hiding a failed Vertex call behind a silent fallback during the pre-flight check.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| A (picked) | Build the environment support into `main` behind settings; the bank copy becomes a plain checkout | A few days of work now; afterwards every fix deploys by `git pull` |
| B | Keep the patched bank copy, send fixes as patches | No work now; every fix needs manual merging in an environment without tests |
| C | Container image for the whole app via BuildKit | Closest to production; too slow and too many unknowns for one week |

Owner chose A on 2026-11-11 ("git pull from GitHub works").

## Design

**Vertex.** Three settings, named as the bank copy already names them so its `.env` keeps working:
`ARP_GEMINI_USE_VERTEX` (default false), `ARP_GCP_PROJECT`, `ARP_GCP_LOCATION` (default `global`).
With Vertex on, `GeminiLLMClient` builds its `google-genai` client in Vertex mode (project, location,
application default credentials) and needs no API key; an API key that is also set is ignored. Everywhere the code asks "is Gemini available"
(`arp/llm/factory.py`, the settings check in `arp/config.py`), Vertex on counts as yes. Starting with
Vertex on and no project fails at startup with a message naming `ARP_GCP_PROJECT`.

**One port.** New setting `ARP_FRONTEND_DIST` (default unset). When it points at a directory with an
`index.html`, the API serves it at `/`, after all `/api` routes; unknown `/api/...` paths stay JSON 404s.
A value that is not such a directory fails at startup with a message naming `ARP_FRONTEND_DIST`; an
empty value counts as unset. The frontend's API base and asset base
become relative when built with `VITE_API_BASE=.` so the same build works at `/` and under
`/user/<id>/proxy/8000/`. Default dev behaviour (`http://localhost:8000`, Vite on 5173) is unchanged.

**Launch script.** `scripts/launch_jupyter.sh` with three verbs:

- `up`: checks required settings (`ARP_POSTGRES_DSN`, `ARP_LLM_MODEL`, `ARP_LLM_VERIFIER_MODEL`, and
  `ARP_GCP_PROJECT` when Vertex is on), runs `arp db init-postgres`, builds the frontend if `frontend/dist`
  is missing or older than `frontend/src`, starts uvicorn on `0.0.0.0:8000` in the background with a
  log file, waits for `/api/health`, prints the URL: `<JUPYTERHUB_SERVICE_PREFIX>proxy/8000/`, or
  `http://localhost:8000/` when that variable is unset. A missing required setting stops it before
  anything starts. A second `up` reports the running server and starts nothing. If `/api/health` does not answer within
  120 s, it exits 1 and prints the log file path.
- `down`: stops it.
- `check`: the pre-flight for the morning of the showcase. One line per check, `ok` or `FAIL` with the
  reason, exit code 1 on any failure. Lines, in this order: `postgres` (reachable and migrated),
  `model <ARP_LLM_MODEL>` and `verifier <ARP_LLM_VERIFIER_MODEL>` (one real call each, on exactly
  that model, no fallback), `compute models` and `compute parse` (`skip` when the URL is unset),
  `frontend` (the running server answers `/`), `fetch` (GET `ARP_PREFLIGHT_FETCH_URL`, default
  `https://www.sec.gov/robots.txt`, expects 200). A failed check does not stop the later ones: all 7
  lines always print. Output goes to stdout as `ok <name>`, `skip <name>` or `FAIL <name>: <reason>`. The checks live
  in an `arp` command the script calls, so they are testable with stand-ins.

`docs/INSTALLATION.md` gets a "Bank Jupyter (Vertex)" section with the `.env` block and the three
commands. No separate `LAUNCH_GUIDE.md`.

## Left to the builder

- Where the Vertex switch is read inside the Gemini client and how the retry options carry over.
- How the static mount handles the SPA entry (the app uses hash routing, so `index.html` at `/` is enough).
- Log file and pid file location (follow `backend/scripts/e2e_stack.sh`).

## Open risk the owner should know

Dev sign-in with `0.0.0.0/0` means everyone who can open the proxy URL acts as an approver under the
name "dev". For a showcase that is acceptable; review decisions made by the audience will all be
recorded as "dev".

## Acceptance

"Recorder" below: the Gemini client's HTTP transport is replaced by one that records requests and returns
a canned answer; Google application default credentials are replaced by a test credential with a fixed
token, and no production code path skips authentication. "Stand-ins": model, compute and fetch calls replaced by test doubles.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `ARP_GEMINI_USE_VERTEX=true`, `ARP_GCP_PROJECT=p`, `ARP_GCP_LOCATION=global`, no `ARP_GEMINI_API_KEY`, no `ARP_ANTHROPIC_API_KEY`, `ARP_LLM_MODEL=gemini-3.6-flash`, recorder | The client from `build_llm_client(settings)` makes one call | The recorded request goes to a host ending `aiplatform.googleapis.com`, its path contains `projects/p/locations/global`, and it carries no `x-goog-api-key` header | unit |
| AC-2 | `ARP_GEMINI_USE_VERTEX=true` and `ARP_GCP_PROJECT` unset or empty | `Settings()` is created | It raises a validation error whose message contains `ARP_GCP_PROJECT` | unit |
| AC-3 | `ARP_GEMINI_USE_VERTEX` unset, `ARP_GEMINI_API_KEY=k`, `ARP_LLM_MODEL=gemini-3.6-flash`, recorder | The client makes one call | The recorded request goes to `generativelanguage.googleapis.com` with API key `k`; no request goes to `aiplatform.googleapis.com` (unchanged behaviour) | unit |
| AC-4 | `ARP_FRONTEND_DIST` points at a directory containing `index.html` with the text `ARP-TEST-INDEX` | `GET /` on the API | Status 200 and the body contains `ARP-TEST-INDEX` | unit |
| AC-5 | Same as AC-4 | `GET /api/health` | Status 200 and body `{"status":"ok"}` | unit |
| AC-6 | `ARP_FRONTEND_DIST` unset | `GET /` on the API | Status 404 (unchanged behaviour) | unit |
| AC-7a | Frontend built with `VITE_API_BASE=.`, served by the API through `ARP_FRONTEND_DIST`, behind a test proxy that strips the prefix `/user/x/proxy/8000` before forwarding; `ARP_AUTH_MODE=dev` | A browser opens `/user/x/proxy/8000/#home` | A heading starting with `Good morning`, `Good afternoon` or `Good evening` is visible | unit (browser test in `backend/tests/e2e`) |
| AC-7b | Same as AC-7a | Same | Every same-origin request path starts with `/user/x/proxy/8000/` and has a status below 400 | unit (same test) |
| AC-7c | Same as AC-7a | Same | At least one request to `/user/x/proxy/8000/api/...` returns 200 | unit (same test) |
| AC-8 | `VITE_API_BASE` unset | `npm run build` | A file in `frontend/dist/assets/*.js` contains `http://localhost:8000`, and every `src`/`href` in `frontend/dist/index.html` that points at a build asset starts with `/assets/` (unchanged behaviour) | unit |
| AC-9 | Server running, both compute URLs set, stand-ins that all succeed | The pre-flight check runs | Exactly 7 lines in this order, each starting `ok`: `postgres`, `model <ARP_LLM_MODEL>`, `verifier <ARP_LLM_VERIFIER_MODEL>`, `compute models`, `compute parse`, `frontend`, `fetch`; exit code 0 | unit |
| AC-10 | `ARP_LLM_MODEL=nope`, a stand-in that raises `model not found` for it, and a second usable provider key set | The pre-flight check runs | The model line is `FAIL model nope: model not found`, no other model is called for that line, exit code 1 | unit |
| AC-11a | The e2e stack is down, Postgres from `ensure-deps.sh postgres`, a valid `backend/.env`, `JUPYTERHUB_SERVICE_PREFIX=/user/x/` | `scripts/launch_jupyter.sh up` | Stdout has exactly one line containing `/user/x/proxy/8000/`, and `GET http://localhost:8000/api/health` returns 200 | evaluator |
| AC-11b | Same, and no `frontend/dist` before | Same | `frontend/dist/index.html` exists afterwards | evaluator |
| AC-11c | After AC-11a | `up` a second time | It prints a line starting `already running`, exits 0, and exactly one process listens on port 8000 | evaluator |
| AC-11d | As AC-11a but `JUPYTERHUB_SERVICE_PREFIX` unset | `up` | Stdout has exactly one line containing `http://localhost:8000/` | evaluator |
| AC-12 | As AC-1, plus `ARP_GEMINI_API_KEY=k` | The client makes one call | The request goes to Vertex as in AC-1 and carries no API key | unit |
| AC-13 | `ARP_FRONTEND_DIST=/nonexistent` | The API app is created | It raises an error whose message contains `ARP_FRONTEND_DIST` | unit |
| AC-14 | Same as AC-4 | `GET /api/does-not-exist` | Status 404 with body `{"detail":"Not Found"}` | unit |
| AC-15 | As AC-10 but for `ARP_LLM_VERIFIER_MODEL=nope` | The pre-flight check runs | The verifier line is `FAIL verifier nope: model not found`, exit code 1 | unit |
| AC-16 | After AC-11a | `scripts/launch_jupyter.sh down`, then `down` again | Nothing listens on port 8000; both calls exit 0 | evaluator |
| AC-17 | `ARP_POSTGRES_DSN` unset everywhere | `up` | It prints a line containing `ARP_POSTGRES_DSN`, exits 1, and nothing listens on port 8000 | evaluator |
| AC-18 | `frontend/dist/index.html` older than a file in `frontend/src` | `up` | `frontend/dist/index.html` has a newer modification time afterwards | evaluator |
| AC-19 | `ARP_COMPUTE_MODELS_URL` unset, otherwise as AC-9 | The pre-flight check runs | The `compute models` line starts with `skip`; exit code 0 | unit |

| AC-20 | After AC-11a | `GET http://localhost:8000/` | Status 200, the body contains `<div id="root"`, and no `src`/`href` in it starts with `/assets/` | evaluator |
| AC-21 | After AC-11a, on a database that was empty before `up`, no model credentials | `scripts/launch_jupyter.sh check` | Stdout has 7 lines; the first is `ok postgres`, the sixth is `ok frontend`; exit code 1 | evaluator |
| AC-22 | As AC-9 | The pre-flight check runs | Stdout is exactly: `ok postgres`, `ok model <ARP_LLM_MODEL>`, `ok verifier <ARP_LLM_VERIFIER_MODEL>`, `ok compute models`, `ok compute parse`, `ok frontend`, `ok fetch` (supersedes the looser wording of AC-9) | unit |
| AC-23 | As AC-10 | The pre-flight check runs | All 7 lines are printed; the other 6 start with `ok` | unit |
| AC-24 | Database reachable but not migrated; otherwise as AC-9 | The pre-flight check runs | Line 1 starts `FAIL postgres:`; exit code 1 | unit |
| AC-25 | The server answers `/` with 404; otherwise as AC-9 | The pre-flight check runs | Line 6 starts `FAIL frontend:`; exit code 1 | unit |
| AC-26 | The fetch stand-in raises `timeout`; otherwise as AC-9 | The pre-flight check runs | Line 7 is `FAIL fetch: timeout`; exit code 1; the stand-in was asked for the value of `ARP_PREFLIGHT_FETCH_URL` | unit |
| AC-27 | `ARP_FRONTEND_DIST` points at an existing empty directory | The API app is created | It raises an error whose message contains `ARP_FRONTEND_DIST` | unit |
| AC-28 | `ARP_FRONTEND_DIST=` (empty) | `GET /` on the API | Status 404 (as unset) | unit |
| AC-29 | Frontend built with `VITE_API_BASE=.` | The build output is read | No file in `frontend/dist` contains `http://localhost:8000`, and every build-asset `src`/`href` in `index.html` starts with `./assets/` | unit |
| AC-30 | As AC-1, plus `ARP_LLM_VERIFIER_MODEL=gemini-3.6-flash` and `ARP_GCP_LOCATION` unset | The verifier client makes one call | As AC-1: Vertex host, path contains `projects/p/locations/global`, no API key | unit |
| AC-31 | Server down, `frontend/dist` newer than every file in `frontend/src` | `up` | The modification time of `frontend/dist/index.html` is unchanged | evaluator |
| AC-32 | `ARP_POSTGRES_DSN` points at a closed port | `up` | Exits non-zero within 120 s and nothing listens on port 8000 | evaluator |
| AC-33 | The change is merged | `docs/INSTALLATION.md` is read | It has a heading `Bank Jupyter (Vertex)` whose section contains `ARP_GEMINI_USE_VERTEX`, `ARP_GCP_PROJECT` and `scripts/launch_jupyter.sh up` | unit |
| AC-34 | `ARP_FRONTEND_DIST` set as in AC-4 | `GET /docs` and `GET /openapi.json` | Same status codes as with `ARP_FRONTEND_DIST` unset | unit |

Clarifications from the second critique: AC-3's key travels as header `x-goog-api-key: k`; AC-12 has neither that
header nor a `key=` query parameter; AC-7b collects requests until network idle; AC-18's server is down
before `up`; AC-19 keeps 7 lines and line 4 is exactly `skip compute models`.

Must not change: AC-3, AC-6, AC-8, AC-34.

Author's calls after the second critique (owner approved the design before these rows were added; none
changes what the design does): all 7 check lines always print; the fetch target and its setting; an empty
`ARP_FRONTEND_DIST` counts as unset; the 120 s start timeout; the required-settings list.

Accepted exception: a real Vertex call cannot be checked in CI or by the evaluator (no bank credentials).
It is verified by `scripts/launch_jupyter.sh check` on the bank machine; the owner runs it and reports
the output.
