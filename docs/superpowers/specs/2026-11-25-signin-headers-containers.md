# Sign-in guard, security headers and containers

Status: Draft, for owner approval
Slug: `signin-headers-containers`
Risk: `risk:high` for every slice (sign-in, response headers, CSP, container and sandbox service)
Size: `M`, three slices, one PR each (bug-list bundle E = items 10 + 12)

## Decisions for the owner

Answered by the owner in the spec thread on 2026-11-25:

1. **Broken users file while the API runs** (rows AC-9, AC-10): keep serving the users of the last valid version
   and log an error.
2. **Sandbox on a machine where worker memory cannot be measured** (macOS, Windows; row AC-61): start, and print a
   warning that the memory limit is off.

Every other choice is under "Defaults taken"; approving the spec approves them.

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`; consolidated rows M3, L14,
L15, L17, LM1, H7, M6, M30, LM3, L12, L13 in `all-findings.md`) found these, re-checked on `main` at `a021636`:

1. **M3.** In dev sign-in mode (`auth_mode` default `dev`), `"*"` in `allowed_origins` counts every `Origin` as
   same-site (`backend/arp/api/auth.py:72`), so any web page open in the same browser acts as the dev approver.
   The README warns against it (line 120) but nothing stops it.
2. **L15.** `load_users` is `@lru_cache`d (`auth.py:35`): removing a person from `config/users.json` does not
   revoke their token until the API restarts.
3. **L14.** `GET /api/documents/{company_id}/{doc_type}/{filename}/raw` (`routers/documents.py:110`) serves stored
   files inline with no `X-Content-Type-Options` and no CSP, so an uploaded HTML or SVG file runs script on the
   app's origin when opened.
4. **L17.** `frontend/nginx.conf` sends no CSP, `nosniff`, `Referrer-Policy` or `X-Frame-Options`, and no gzip.
5. **LM1.** The Agent board's diagram frame is `sandbox="allow-scripts allow-same-origin"`
   (`frontend/src/components/AgentBoard.tsx:432`): script in the frame shares the app's origin, so the sandbox
   does not hold if Mermaid is ever tricked into running script.
6. **H7, M30.** There is no container image for `sandbox/` and no `sandbox` service in `docker-compose.yml`, so in
   the compose stack every Agent exploration fails with "sandbox … did not answer".
7. **LM3.** `sandbox/server.mjs` starts one workerd process per `/execute` with no upper bound.
8. **L12.** `server.mjs` has no `error` handler on the spawned child: a missing or non-executable workerd binary
   crashes the whole service.
9. **L13.** Memory is read from `/proc/<pid>/statm` × 4096, which is wrong on 16 KB / 64 KB page kernels.

Already fixed on `main`, kept as guard rows only: `.dockerignore` excludes `**/.env` and `**/.env.*` (M6), and
`backend/Dockerfile.compute` ends with `USER arp`.

The Antigravity patch is a hint only; this spec states the behaviour.

## What the user can do afterwards that they cannot do today

- Revoke or add a token by editing `config/users.json`, without restarting the API.
- Run `docker compose up --build` and use Agent explorations: the sandbox runs as its own container.
- Open a stored HTML or SVG document from the source panel or a direct `/raw` link without it running script on
  ARP's origin; PDFs still open at the cited page.
- Get a clear startup error instead of a silent hole when `"*"` is combined with dev sign-in.

## What exists today (main `a021636`)

- `api/main.py` `lifespan`: checks rule book, benchmarks, Postgres, cutover, then `load_users` only when
  `auth_mode == "local"`. A bad users file stops startup with `NotConfigured`.
- `auth.load_users(path)`: cached forever per path; raises `NotConfigured("Users file {path} is missing or invalid
  ({why}); see config/users.example.json.")` and two other messages. Also used by the CLI
  (`arp/cli/_shared.py:151`), once per process.
- `Settings.trusted_hosts` default is `["localhost", "127.0.0.1", "[::1]", "backend", "testserver"]`: `backend` is
  already there, so a sandbox container calling `http://backend:8000` passes the host check with no compose change.
- `/raw` answers `FileResponse` with `Content-Type` from `mimetypes.guess_type` (else `application/octet-stream`) and
  `Content-Disposition: inline; filename="<name>"`. The frontend's source panel fetches it into a `blob:` URL and
  shows it in an iframe (`FileLink.tsx` `FileFrame`), sandboxed unless the type is inline-safe.
- `nginx.conf`: four static locations (`/`, `~* \.wasm$`, the asset regex, `= /index.html`) each add COOP/COEP
  (nginx drops server-level `add_header` in a location that sets its own); `/api/` is proxied with buffering off
  (streamed answers).
- `board-diagram.html` carries its own meta CSP (`default-src 'none'; script-src 'self'; …`). The parent checks
  `e.source === frame.contentWindow && e.origin === location.origin` and posts with target `location.origin`; the
  frame checks `e.source === window.parent && e.origin === location.origin` and replies with target
  `location.origin`.
- `sandbox/server.mjs`: listens on `127.0.0.1` (port `ARP_SANDBOX_PORT`, default 8790); env `ARP_API_URL`,
  `ARP_SANDBOX_WALL_MS`, `ARP_SANDBOX_MEMORY_MB`; workerd from `require("workerd")`. `sandbox.capnp` embeds
  `deny.js` and `dist/host.js` (built by `npm run build`).
- `backend/arp/agent/sandbox.py` `execute`: any `httpx.HTTPError` (a 429 too) becomes
  `failed` / `sandbox at {sandbox_url} did not answer: {ExceptionName}`.
- `backend/Dockerfile` copies all of `backend/`, `tests/` included; `arp golden-set …` commands read
  `backend/tests/golden/` at run time, so the image needs it.

## Goals

1. The API refuses to start in dev sign-in mode when `"*"` is in `allowed_origins`; the CLI is not affected.
2. A users-file edit takes effect on the next request; a broken edit never lets anyone extra in.
3. `/raw` sends `nosniff` always, and `Content-Security-Policy: sandbox` on everything that is not a PDF.
4. nginx sends a CSP, `nosniff`, `Referrer-Policy`, `X-Frame-Options: SAMEORIGIN` on every static answer, and
   gzips static text, without breaking the rule engine, board diagrams or PDFs in the source panel. The Superset
   embed is covered by the `frame-src` text only (AC-22, AC-23): running it needs Superset and its secrets.
5. The board diagram frame runs without `allow-same-origin` and still draws.
6. `sandbox/` builds into a non-root image, runs as a compose service the backend reaches, caps parallel runs,
   survives a spawn failure, and measures memory correctly.

## Non-goals

- Making `local` the default sign-in mode, or any default change off localhost (finding M3's second half).
- The separate sandbox-hardening item: gVisor, a container per execution, fail-closed `/check`, isolated RFP
  parsing, offline Chromium. Not folded in.
- A published ghcr image for the sandbox (`.github/workflows/images.yml` is untouched). Compose builds it.
- A CSP on the Vite dev server (`npm run dev`) or on `/api/` answers.
- Anything bundle F owns (other workflows, `.github/scripts/*`, `frontend/tsconfig*.json`, routers other than
  `documents.py`, `arp/net_safety.py`, `AskCards.tsx`).

## Anti-goals (must stay true)

- Every non-container path works exactly as today: venv `uvicorn`, `npm run dev`, `node sandbox/server.mjs` (still
  on `127.0.0.1:8790`), `bash backend/scripts/e2e_stack.sh up`. Every new env var defaults to today's behaviour.
- PDFs open in the browser's own viewer and jump to `#page=N`, from `/raw` directly and in the source panel.
- COOP `same-origin` and COEP `require-corp` stay on every static location; the Decision Studio rule engine runs.
- `/api/` keeps streaming (no buffering, no gzip).
- The sandbox isolate still has no network, no `process`, no token global (existing `sandbox/test` cases).

## Design

### Slice 1: backend sign-in and `/raw`

**Startup refusal (M3).** The first check in `lifespan`, before `check_rule_book()`: if
`settings.auth_mode == "dev"` and `"*" in settings.allowed_origins`, raise `NotConfigured` with exactly:

```
ARP_AUTH_MODE=dev with "*" in ARP_ALLOWED_ORIGINS lets any website act as the dev approver. List the real origins in ARP_ALLOWED_ORIGINS, or set ARP_AUTH_MODE=local.
```

Not a `Settings` validator: `Settings(...)` and every CLI command keep working with these values.

**Users-file reload (L15).** `load_users(path)` keeps its signature and its three error messages. It stats the
file on every call and re-reads it when `(st_mtime_ns, st_size)` differs from the version it last read. When re-reading fails and an earlier read of the same path succeeded, it returns that earlier
mapping and logs, on logger `arp.api.auth` at level `ERROR`, once per file version (same `(mtime_ns, size)`, or
the file missing), the message the failure would have raised followed by ` Still using the users from the last
valid version.` A missing file counts as a failure. With no earlier good read it raises as today (startup in
`local` mode still fails on a bad file; in dev mode a bearer request still gets today's 503).
`load_users.cache_clear()` stays callable (tests use it) and forgets every remembered version. The remembered
state is safe under concurrent requests (one lock is enough).

**`/raw` headers (L14).** Every `/raw` answer adds `X-Content-Type-Options: nosniff`. Every answer whose
`Content-Type` media type is not `application/pdf` also adds `Content-Security-Policy: sandbox`. `Content-Type`
and `Content-Disposition` are unchanged.

**Docs.** README "Sign-in": the sentence at line 120 ("Never combine … act as the dev approver.") becomes "The API
refuses to start with `ARP_AUTH_MODE=dev` and `"*"` in `ARP_ALLOWED_ORIGINS`: `"*"` would let any website open in
the same browser act as the dev approver."; step 3 drops "(also after every later edit of the users file: it is
read once)" and adds "Later edits of the users file take effect on the next request, no restart needed." The
`docker-compose.yml` comment "Restart the backend after editing it." becomes "Edits take effect without a
restart." Bundle F may edit the same README section (its L22): the second PR to merge takes `origin/main` first.

### Slice 2: nginx headers and the diagram frame

**nginx (L17).** Every answer from the four static locations (`/`, `~* \.wasm$`, the asset regex,
`= /index.html`), errors included (`always`), carries, besides today's COOP/COEP/Cache-Control:

| Header | Value |
|---|---|
| `Content-Security-Policy` | the CSP below |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Frame-Options` | `SAMEORIGIN` |

The CSP, as written in the template (one line, exactly this text):

```
default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self'; frame-src 'self' blob: ${ARP_SUPERSET_ORIGIN}; object-src 'self' blob:; base-uri 'self'; form-action 'self'; frame-ancestors 'self'
```

Why each allowance:

| Directive | Allowance | Reason |
|---|---|---|
| `script-src` | `'wasm-unsafe-eval'` | Decision Studio compiles the Zen rule engine with WebAssembly (`lib/zenEngine.ts`). |
| `style-src` | `'unsafe-inline'` | React `style=` attributes, Mermaid's inline `<style>` in the diagram frame, the Refine slide preview's injected `<style>`. |
| `style-src` / `font-src` | Google Fonts hosts | `index.html` and `board-diagram.html` load Geist / Source Serif 4 from there. |
| `img-src` | `data: blob:` | Mermaid labels, mini-app images (`data:`), authenticated images shown through object URLs (`FileImg`). |
| `worker-src` | `'self'` | the Zen engine worker is a same-origin module (`zenWorker.ts`). |
| `frame-src` | `'self'` | `board-diagram.html`; `srcdoc` frames (mini-apps, Refine preview). |
| `frame-src` / `object-src` | `blob:` | the source panel shows `/raw` files (PDFs included) in a `blob:` iframe; a `blob:` document inherits this policy, and Chrome's PDF viewer inside it is a plugin. |
| `frame-src` | `${ARP_SUPERSET_ORIGIN}` | the Superset dashboard embed (`lib/biEmbed.ts`, `VITE_SUPERSET_URL`, default `http://127.0.0.1:8088`). |
| `frame-ancestors` | `'self'` | the app frames its own `board-diagram.html`; same reason `X-Frame-Options` is `SAMEORIGIN`, not `DENY`. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Superset's embedded view checks the referrer against its allowed domains; `no-referrer` would break the embed. |

`ARP_SUPERSET_ORIGIN` is a new template variable: `frontend/Dockerfile` sets `ENV ARP_SUPERSET_ORIGIN=http://127.0.0.1:8088`
and adds it to `NGINX_ENVSUBST_FILTER`. The served CSP with the default therefore contains
`frame-src 'self' blob: http://127.0.0.1:8088;`. Someone who builds with another `VITE_SUPERSET_URL` sets the
same origin here.

`gzip on` for `text/css application/javascript application/wasm application/json image/svg+xml` (and `text/html`,
nginx's default) on the static locations; `/api/` gets no gzip and none of the four headers above (the backend owns
its headers; `/raw` sets its own in slice 1). How the headers are repeated (per location, or one `include`d
snippet copied into the image) is the builder's choice. The static locations may also send
`Access-Control-Allow-Origin: *` if the diagram frame needs it (see below); they are public build files.

**Diagram frame (LM1).** The iframe's `sandbox` attribute becomes exactly `allow-scripts`. The frame's origin is
then opaque (`"null"`), so:

- Parent → frame: `postMessage(msg, "*")` (an opaque origin cannot be named as a target). The content is the
  diagram source and theme the parent already shows.
- Frame → parent: the parent accepts a message only when `e.source === frame.contentWindow` (the origin check is
  dropped: it would be `"null"`).
- The frame accepts a message only when `e.source === window.parent`, and replies to `window.parent` only.
- The frame's module scripts now load cross-origin from an opaque origin under COEP `require-corp`; whatever CORS
  header this needs is added on the Vite dev server (`vite.config.ts`) and on nginx's static locations.

`board-diagram.html`'s own meta CSP stays as it is.

### Slice 3: sandbox container and service

**`sandbox/Dockerfile` (H7)**, build context `sandbox/`: `FROM node:22-bookworm-slim` (workerd needs glibc; not
alpine), `WORKDIR /app`, `npm ci`, `npm run build`, the whole service (`server.mjs`, `check.mjs`, `host.js`,
`deny.js`, `sandbox.capnp`, `dist/host.js`, `node_modules`), `ENV ARP_SANDBOX_HOST=0.0.0.0`, a non-root `USER`,
`EXPOSE 8790`, `CMD ["node", "server.mjs"]`. A `sandbox/.dockerignore` keeps the host's `node_modules`, `dist`,
`**/.env` and `**/.env.*` out of the context. No secrets, no build args.

**`server.mjs` changes:**

- Listen host from `ARP_SANDBOX_HOST`, default `127.0.0.1`. The start line becomes
  `sandbox listening on <host>:<port>` (today's text with the host filled in; unchanged by default).
- `ARP_SANDBOX_MAX_PARALLEL`, default `4`: at most that many `/execute` requests in progress. One more answers
  HTTP 429 with `{"detail": "sandbox busy: <N> of <N> executions running"}` (N = the limit) after reading and discarding the
  request body, without parsing or checking it. The slot is released on every outcome (done, failed, timeout, memory kill, spawn error).
  `/check` and `/health` are never capped. Unset or empty means 4; any other value must match `^[1-9][0-9]*$`, else the process prints
  `ARP_SANDBOX_MAX_PARALLEL must be a whole number of at least 1` to stderr and exits with code 1.
- `ARP_SANDBOX_WORKERD`, default the bundled `require("workerd")` binary: the binary to run. Exists so a spawn
  failure can be tested, and for machines with a system workerd.
- A spawn failure (`child` `error` event: ENOENT, EACCES, …) makes that execution answer
  `{"status": "failed", "result": null, "error": "sandbox error: <err.message>"}` (for a missing binary
  `sandbox error: spawn <path> ENOENT`) and the service keeps running.
- Memory: resident size from the `VmRSS:` line of `/proc/<pid>/status` (kB → MB), not `statm`. 
  At start the server reads `/proc/self/status`; if it has no `VmRSS:` line or cannot be read, it prints
  `memory limit off: cannot read process memory on this system, so ARP_SANDBOX_MEMORY_MB is not enforced` to
  stderr and starts.

**Backend (`arp/agent/sandbox.py`).** When `/execute` answers 429, `execute` returns status `failed` and error
exactly `sandbox at {sandbox_url} is busy (too many code runs at once); try again in a moment`. Every other
failure keeps today's `did not answer: …` text.

**Compose (M30).** A `sandbox` service: `build: ./sandbox`, no `ports`, no `env_file`, `environment:
ARP_API_URL: http://backend:8000`. The `backend` service gets `ARP_SANDBOX_URL: http://sandbox:8790` and
`sandbox: {condition: service_started}` added to its existing `depends_on` mapping (so `docker compose up backend
frontend` starts it; `postgres` keeps `condition: service_healthy`). The usage comment at the top names
the service. Nothing else changes: `backend` is already in `ARP_TRUSTED_HOSTS`' default.

Security note for the review: the sandbox container sits in the Docker bridge range the compose file trusts for the
dev bypass (`172.16.0.0/12`). The isolate cannot reach the API (`globalOutbound = "deny"`); only `host.js` calls
`/api/sandbox/tools/<name>` with the execution's token. The `node` service process itself could call the API as
the dev approver; it runs only this repo's `server.mjs`.

## Defaults taken

- The M3 check is the first startup check, so it fails fast even without Postgres.
- Reload key is `(st_mtime_ns, st_size)`, checked on every call (one `stat` per authenticated request).
- `/raw`: the CSP decision is by served media type, so a `.pdf` file is the only exemption; `Content-Security-Policy:
  sandbox` with no tokens (no `allow-scripts`, no `allow-same-origin`).
- `backend/tests/` stays in the backend and compute images: `arp golden-set` commands read `backend/tests/golden/`.
  No `.dockerignore` change.
- `/api/` gets no nginx security headers and no gzip.
- Superset origin is a runtime template variable, default matching `VITE_SUPERSET_URL`'s default.
- Parallel cap default 4; the cap counts `/execute` requests, checked before the code check.
- The sandbox image sets `ARP_SANDBOX_HOST=0.0.0.0` (needed inside a container); outside a container the default
  stays `127.0.0.1`.
- `backend` depends on `sandbox` with `condition: service_started` (no healthcheck).
- No sandbox healthcheck in compose, no ghcr image.

## Notes for the builder

- Smallest possible diff with the lowest complexity: no refactors, no new abstractions, no unrelated cleanup.
- `backend/tests/e2e/test_agent_board.py:193` asserts `"allow-scripts allow-same-origin"`; slice 2 changes it to
  `"allow-scripts"`. List it in the PR description. This spec supersedes `2026-11-22-agent-board.md` AC-49d (an
  `evaluator` row, no hidden test) for the attribute value.
- The E2E job runs the Vite dev server, so nothing in CI exercises `nginx.conf` in a browser. AC-29 to AC-33 are the
  evaluator's; AC-21 to AC-28 run the template in a real nginx.
- Touching `sandbox/` runs the exploration golden set; it is not a merge gate (credits are empty).

## Acceptance

**API rows** use FastAPI's `TestClient` on `arp.api.main:app` with the named env set and the settings cache cleared.
"Starting the API" means entering the client's context (`with TestClient(app):`), which runs `lifespan`. Postgres is
the holdout job's; rows that enter the lifespan run in their own test module, before or apart from browser rows
(the lifespan reaps `running` turns in that database). **`/raw` rows** put the file at
`$ARP_DOCUMENTS_DIR/acme/other/<name>`, set `ARP_AUTH_MODE=dev` and request
`GET /api/documents/acme/other/<name>/raw` from `TestClient(app, client=("127.0.0.1", 1))`. **Sandbox rows** start `node sandbox/server.mjs` from the repo checkout (its `node_modules`
installed, `npm run build` done) as a subprocess with the named env, `ARP_SANDBOX_PORT` a free port, `ARP_API_URL`
a stand-in HTTP server unless stated (it answers every `POST` 200 with
`{"echo": <the request body>}`), and drive it over HTTP; "the start line" is the first stdout line. **nginx
rows** fill `frontend/nginx.conf` with `envsubst` for `ARP_BACKEND_URL=http://127.0.0.1:<stand-in port>`,
`ARP_PUBLIC_HOSTS="localhost 127.0.0.1"`, `NGINX_LOCAL_RESOLVERS=127.0.0.53`,
`ARP_SUPERSET_ORIGIN=http://127.0.0.1:8088` (and any include file slice 2 adds, copied as the Dockerfile copies
it), change only the `listen` port and `root`, wrap it as `http { include /etc/nginx/mime.types; types { application/wasm
wasm; } <filled file> }` with `pid`, `error_log` and temp paths under a temp dir, and run the real `nginx` binary
(installed with apt if missing) as `nginx -p <tmp> -c <conf>`, against a root holding `index.html`,
`board-diagram.html`, `assets/app.js`, `assets/app.css`, `assets/x.wasm`, `favicon.svg`, each at least 4 KB of
compressible text. **Frame rows** run in headless Chromium against `e2e_stack.sh up` (Vite dev server,
dev auth) on a board with the mind map M and the grouped flowchart G of `test_agent_board.py`. **Evaluator rows**
serve the `dist/` of `cd frontend && VITE_API_BASE= npm run build` (empty, as `frontend/Dockerfile` builds it, so
the page calls `/api/` on its own origin) with the filled template (as above, `ARP_BACKEND_URL=http://127.0.0.1:8000`) on
port 8080 next to `e2e_stack.sh up`, and open `http://localhost:8080` in Chromium; "no CSP error" means the
console shows no message containing `Content Security Policy` or `Refused to`.

### Slice 1: sign-in and `/raw`

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `ARP_AUTH_MODE=dev`, `ARP_ALLOWED_ORIGINS=["*"]` | starting the API | raises `NotConfigured` whose `str` is exactly `ARP_AUTH_MODE=dev with "*" in ARP_ALLOWED_ORIGINS lets any website act as the dev approver. List the real origins in ARP_ALLOWED_ORIGINS, or set ARP_AUTH_MODE=local.` | holdout |
| AC-2 | `ARP_AUTH_MODE=dev`, `ARP_ALLOWED_ORIGINS=["http://localhost:5173","*"]` | starting the API | the same `NotConfigured` and message as AC-1 | holdout |
| AC-3 | `ARP_AUTH_MODE=dev`, `ARP_ALLOWED_ORIGINS=["*"]`, `ARP_POSTGRES_DSN` unset | starting the API | the AC-1 error, not the Postgres one (the check runs first) | holdout |
| AC-4 | `ARP_AUTH_MODE=local`, `ARP_ALLOWED_ORIGINS=["*"]`, a valid users file | starting the API, then `GET /api/health` | starts; 200 | holdout |
| AC-5 | `ARP_AUTH_MODE=dev`, default `ARP_ALLOWED_ORIGINS` | starting the API, then `GET /api/me` with no `Authorization` from client address `127.0.0.1` (`TestClient(app, client=("127.0.0.1", 1))`) | starts; 200 with `user_id` `dev` and `role` `approver` (unchanged) | holdout |
| AC-6 | `ARP_AUTH_MODE=dev`, `ARP_ALLOWED_ORIGINS=["*"]` in the environment | `Settings()`; and `arp --help` as a subprocess | `Settings()` raises nothing; `arp --help` exits 0 | holdout |
| AC-7 | `ARP_AUTH_MODE=local`; users file with token `tok-a` (user `a`, viewer); API started | the file is rewritten to hold only `tok-b` (user `b`, viewer), its mtime set 2 s later than before; then `GET /api/me` with `Bearer tok-a`, then with `Bearer tok-b` | `tok-a`: 401; `tok-b`: 200 with `user_id` `b`. No restart in between | holdout |
| AC-8 | as AC-7 after the edit | the file is rewritten to hold `tok-a` and `tok-b` again (mtime +2 s); `GET /api/me` with `Bearer tok-a` | 200 with `user_id` `a` | holdout |
| AC-9 | `ARP_AUTH_MODE=local`; users file with `tok-a`; API started; one request with `tok-a` answered 200 | the file is overwritten with `{not json` (mtime +2 s); two `GET /api/me` with `Bearer tok-a`, one with `Bearer nope` | both `tok-a` requests 200 with `user_id` `a`; `nope` 401; exactly one `ERROR` record on logger `arp.api.auth`, whose message starts `Users file ` and ends `Still using the users from the last valid version.` and does not contain `tok-a` | holdout |
| AC-10 | as AC-9 after the broken write | the file is deleted; `GET /api/me` with `Bearer tok-a` | 200 with `user_id` `a`; one more `ERROR` record ending `Still using the users from the last valid version.` | holdout |
| AC-11 | `ARP_AUTH_MODE=local`; users file `{not json` | starting the API | raises `NotConfigured` whose message starts `Users file ` and contains `is missing or invalid` (unchanged) | holdout |
| AC-12 | `ARP_AUTH_MODE=dev`; `ARP_USERS_FILE` points at a missing file | `GET /api/me` with `Bearer x` from a client address outside loopback (`TestClient(app, client=("10.0.0.9", 1))`) | 503 whose `detail` starts `Users file ` (unchanged: no earlier good read) | holdout |
| AC-13 | a stored document `report.pdf` | `GET …/report.pdf/raw` | 200; `Content-Type: application/pdf`; `X-Content-Type-Options: nosniff`; no `Content-Security-Policy` header; `Content-Disposition: inline; filename="report.pdf"` | holdout |
| AC-14 | stored documents `page.html`, `pic.svg`, `data.xml`, `notes.txt`, `blob.bin` | `GET …/<name>/raw` for each | each 200 with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; `Content-Type` media types `text/html`, `image/svg+xml`, `application/xml` or `text/xml` (as `mimetypes` says), `text/plain`, `application/octet-stream` | holdout |
| AC-15 | stored `page.html` | `GET …/page.html/raw` | `Content-Disposition: inline; filename="page.html"` (unchanged) and the body is the file's bytes | holdout |

### Slice 2: nginx and the diagram frame

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-21 | nginx as in the preamble | `GET /`, `/index.html`, `/board-diagram.html`, `/assets/app.js`, `/assets/app.css`, `/assets/x.wasm`, `/favicon.svg`, `/some/app/route`, `/assets/missing.js` | every answer (the last one 404) has `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: SAMEORIGIN`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp` | holdout |
| AC-22 | as AC-21 | the same requests | every answer's `Content-Security-Policy` is exactly `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self'; frame-src 'self' blob: http://127.0.0.1:8088; object-src 'self' blob:; base-uri 'self'; form-action 'self'; frame-ancestors 'self'` | holdout |
| AC-23 | as AC-21 but `ARP_SUPERSET_ORIGIN=https://bi.example.com` | `GET /` | the CSP contains `frame-src 'self' blob: https://bi.example.com;` | holdout |
| AC-24 | as AC-21 | `GET /index.html`, `/assets/app.js`, `/assets/x.wasm` | `/index.html`: the only `Cache-Control` value is `no-cache`; `/assets/app.js`: one of its `Cache-Control` header lines is exactly `public, max-age=604800, immutable` (today's `expires 7d` line `max-age=604800` and the `Expires` header stay); `/assets/x.wasm`: the only `Cache-Control` value is `public, max-age=604800, immutable` (all unchanged) | holdout |
| AC-25 | as AC-21 | `GET /assets/app.js`, `/assets/app.css`, `/assets/x.wasm`, `/index.html` with `Accept-Encoding: gzip` | each has `Content-Encoding: gzip` | holdout |
| AC-26 | as AC-21; the stand-in backend answers `GET /api/ping` with 2 KB of JSON | `GET /api/ping` with `Accept-Encoding: gzip` and `Host: localhost` | 200, no `Content-Encoding` header, no `Content-Security-Policy`, no `X-Frame-Options` header added by nginx | holdout |
| AC-27 | as AC-21 | `GET /api/ping` with `Host: attacker.example` | 421 (unchanged host allow-list) | holdout |
| AC-28 | `frontend/Dockerfile` | read its text | `NGINX_ENVSUBST_FILTER` matches `ARP_SUPERSET_ORIGIN` as well as `ARP_BACKEND_URL`, `ARP_PUBLIC_HOSTS`, `NGINX_LOCAL_RESOLVERS`, and an `ENV` line sets `ARP_SUPERSET_ORIGIN=http://127.0.0.1:8088` | holdout |
| AC-29 | evaluator setup | open Home, then the Agent screen and a board with a diagram | the page and the diagram draw; no CSP error | evaluator |
| AC-30 | evaluator setup | open Decision Studio and run a rule preview on a seeded rule | the preview shows a result (the wasm engine ran); no CSP error | evaluator |
| AC-31 | evaluator setup, a seeded PDF document with a cited value | open the citation's source in the source panel; then open its `/raw` link with `#page=N` in a new tab | both show the PDF in the browser's viewer at page N; no CSP error | evaluator |
| AC-32 | evaluator setup, a Refine deck thread | open a slide preview | the slide shows with its fonts; no CSP error | evaluator |
| AC-33 | evaluator setup | in the console, `fetch('/api/health').then(r => r.status)` | `200` (connect-src `'self'` and the proxy work) | evaluator |
| AC-34 | frame setup | open the Board tab | each diagram `iframe.board-frame` has a `sandbox` attribute exactly `allow-scripts` (supersedes agent-board AC-49d) | holdout |
| AC-35 | frame setup | in each `board-diagram.html` frame, evaluate `window.origin` | `"null"` | holdout |
| AC-36 | frame setup | in a frame, evaluate `(() => { try { return typeof window.parent.document } catch (e) { return e.name } })()` | `"SecurityError"` | holdout |
| AC-37 | frame setup | wait for the diagrams | M's frame `#diagram svg` text contains `Topics` and `LinkedIn`; G's three named nodes have three distinct fills (as `test_diagrams_draw_in_a_sealed_frame`) | holdout |
| AC-38 | frame setup plus a stored diagram `flowchart LR\n  a -->` | open the Board tab | the page shows `This diagram could not be drawn:` and the source under it (unchanged) | holdout |
| AC-39 | frame setup, M drawn | inside M's frame, `window.postMessage({type: "draw", source: "flowchart LR\n  forgedA --> forgedB", theme: {}, available: 600}, "*")`, then wait 1 s | M's `#diagram svg` text still contains `Topics` and does not contain `forgedA` (the frame ignores messages not from its parent) | holdout |
| AC-40 | frame setup, diagrams drawn | in the top page, `window.postMessage({type: "error", message: "forged"}, "*")`, then wait 1 s | no text `This diagram could not be drawn: forged` on the page | holdout |
| AC-41 | frame setup | load the Board tab and wait for the diagrams | no browser console error about loading a script or module for `board-diagram.html` (messages naming CORS, `Cross-Origin` or `require-corp`); messages naming `ws://` or `@vite` (the dev server's reload socket) are ignored | holdout |
| AC-42 | as AC-21; the stand-in backend answers `GET /api/stream` by sending `a`, waiting 2 s, then sending `b` | `GET /api/stream` through nginx with `Host: localhost` | the client receives `a` more than 1 s before `b` (streaming unchanged) | holdout |

### Slice 3: sandbox and containers

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-51 | sandbox with no `ARP_SANDBOX_HOST` | start it | the start line is `sandbox listening on 127.0.0.1:<port>`; a TCP connect to the machine's non-loopback address on that port is refused | holdout |
| AC-52 | sandbox with `ARP_SANDBOX_HOST=0.0.0.0` | start it; `GET /health` on the machine's non-loopback address | start line `sandbox listening on 0.0.0.0:<port>`; 200 `{"ok":true}` | holdout |
| AC-53 | `ARP_SANDBOX_MAX_PARALLEL=1`, `ARP_SANDBOX_WALL_MS=4000` | `POST /execute` `{"code":"while (true) {}","token":"t","capabilities":[]}` and, 500 ms later while it runs, a second `POST /execute` `{"code":"return 1","token":"t","capabilities":[]}` | second: HTTP 429, body `{"detail":"sandbox busy: 1 of 1 executions running"}`; first: 200 with `status` `timeout` | holdout |
| AC-54 | as AC-53, during the first execution | `GET /health` and `POST /check` `{"code":"return 1"}` | 200 `{"ok":true}`; 200 `{"ok":true,"error":null}` (not capped) | holdout |
| AC-55 | as AC-53, after the first execution finished | `POST /execute` `{"code":"return 1",…}` | 200 `{"status":"done","result":1,"error":null}` (slot released) | holdout |
| AC-56 | no `ARP_SANDBOX_MAX_PARALLEL` | four `POST /execute` `while (true) {}` at once (wall 4000), then a fifth while they run | the four answer 200 `timeout`; the fifth 429 `{"detail":"sandbox busy: 4 of 4 executions running"}` | holdout |
| AC-57 | `ARP_SANDBOX_MAX_PARALLEL=0` (and separately `abc`) | start the sandbox | exits with code 1; stderr contains `ARP_SANDBOX_MAX_PARALLEL must be a whole number of at least 1` | holdout |
| AC-58 | `ARP_SANDBOX_WORKERD=/nonexistent/workerd`, `ARP_SANDBOX_MAX_PARALLEL=1` | `POST /execute` `{"code":"return 1",…}` twice in a row, then `GET /health` | both 200 `{"status":"failed","result":null,"error":"sandbox error: spawn /nonexistent/workerd ENOENT"}` (the second not 429); `/health` 200; the process is still running | holdout |
| AC-59 | `ARP_SANDBOX_MEMORY_MB=256` (Linux) | `POST /execute` with code that keeps allocating 1 MB arrays | 200 `{"status":"failed","result":null,"error":"execution exceeded the 256 MB memory limit"}` within 4 s; the next `return 4` gives result `4` (unchanged) | holdout |
| AC-60 | Linux | start the sandbox | stderr has no `memory limit off` line | holdout |
| AC-61 | a machine whose process status has no `VmRSS:` line (simulated in the builder's test) | start the sandbox | it starts and prints `memory limit off: cannot read process memory on this system, so ARP_SANDBOX_MEMORY_MB is not enforced` to stderr | unit |
| AC-61b | a stand-in process status text with `VmRSS:\t300000 kB` and `ARP_SANDBOX_MEMORY_MB=256` (builder's test) | the memory watch reads it | the execution is killed with `execution exceeded the 256 MB memory limit` (kB read as kB, no page size involved) | unit |
| AC-62 | `ARP_API_URL=http://localhost:<stand-in port>` (a host name, not an IP) | `POST /execute` `{"code":"return await codemode.benchmark_sectors({})","token":"tok","capabilities":["benchmark_sectors"]}` | 200 `status` `done` with `result` `{"echo":{}}`; the stand-in, listening on both `127.0.0.1` and `::1`, saw `POST /api/sandbox/tools/benchmark_sectors` with `Authorization: Bearer tok` (workerd reaches the API by host name, as `backend:8000` in compose; unchanged behaviour, a guard for compose) | holdout |
| AC-63 | a stand-in sandbox that answers `POST /execute` with 429 `{"detail":"sandbox busy: 4 of 4 executions running"}`; `ARP_SANDBOX_URL` pointing at it | `asyncio.run(arp.agent.sandbox.execute("return 1", <viewer principal>))`, settings cache cleared | `status` `failed`, `result` `None`, `error` exactly `sandbox at <ARP_SANDBOX_URL> is busy (too many code runs at once); try again in a moment` | holdout |
| AC-64 | a stand-in sandbox that answers `/execute` with 500; and a URL nothing listens on | the same call | `error` `sandbox at <url> did not answer: HTTPStatusError`; `… did not answer: ConnectError` (unchanged) | holdout |
| AC-65 | default settings | `GET /api/health` with `Host: backend:8000` | 200 (the sandbox container's calls pass the host check) | holdout |
| AC-66 | Docker on the runner | `docker build -t arp-sandbox-test sandbox`, then `docker run --rm arp-sandbox-test id -u` | the build succeeds; `id -u` prints a number other than `0` | holdout |
| AC-67 | the AC-66 image | `docker run -d -p 127.0.0.1:<port>:8790 arp-sandbox-test` (no env), then `GET /health`, then `POST /execute` `{"code":"return 1 + 1","token":"t","capabilities":[]}` | `/health` 200 within 60 s; `/execute` 200 `{"status":"done","result":2,"error":null}` (`deny.js` and `dist/host.js` are in the image) | holdout |
| AC-68 | the AC-66 image | `docker run --rm arp-sandbox-test sh -c 'find /app -path /app/node_modules -prune -o \( -name ".env" -o -name ".env.*" \) -print'` | prints nothing | holdout |
| AC-69 | `docker-compose.yml` parsed as YAML | read `services.sandbox` | `build` is `./sandbox` (or `{context: ./sandbox}`); no `ports` key; no `env_file` key; `environment.ARP_API_URL` is `http://backend:8000` | holdout |
| AC-70 | as AC-69 | read `services.backend` | `environment.ARP_SANDBOX_URL` is `http://sandbox:8790`; `depends_on` has a `sandbox` key and `postgres` keeps `condition: service_healthy`; `ports` still exactly `["127.0.0.1:8000:8000"]` | holdout |
| AC-71 | `.dockerignore` (repo root) | read its lines | contains `**/.env` and `**/.env.*` (guard, unchanged) | holdout |
| AC-72 | `backend/Dockerfile.compute` | read its text | the last `USER` instruction is `USER arp` (guard, unchanged) | holdout |
| AC-73 | default sandbox env | `POST /execute` `{"code":"return typeof process + \",\" + typeof globalThis.ARP_TOKEN","token":"t","capabilities":[]}` | 200 `{"status":"done","result":"undefined,undefined","error":null}` (unchanged) | holdout |
| AC-74 | default sandbox env | `POST /execute` `{"code":"return await fetch(\"https://example.com\")","token":"t","capabilities":[]}` | 200 with `status` `failed` and `error` containing `network access is not allowed` (unchanged) | holdout |

Must not change: dev sign-in without `"*"` (AC-5), the CLI (AC-6), startup on a bad users file (AC-11), dev mode
with no users file (AC-12), `/raw`'s body and disposition (AC-15), cache headers (AC-24), the `/api/` proxy and its
host allow-list and streaming (AC-26, AC-27, AC-42), drawing and error display in the frame (AC-37, AC-38), the parent's source check
(AC-40), the sandbox's loopback default (AC-51), memory limit on Linux (AC-59), other sandbox failures (AC-64), the
host check (AC-65), the `.env` and compute-image guards (AC-71, AC-72), the isolate's
limits (AC-73, AC-74).

## Slices

Three PRs, each `risk:high` (the owner merges each on GitHub), each with `Spec: signin-headers-containers` and its
`Rows:` line in the description, release notes, and every test it changes listed. They are independent; slices 1
and 3 both edit `docker-compose.yml` (a comment line vs. a new service), so the later one merges `origin/main` first.

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | S | Backend sign-in and `/raw`: `api/main.py` startup check, `api/auth.py` reload, `routers/documents.py` headers, README sign-in lines, compose users.json comment, tests | AC-1 to AC-15 |
| 2 | M | nginx headers + gzip, `frontend/Dockerfile` (`ARP_SUPERSET_ORIGIN`), diagram frame without `allow-same-origin` (`AgentBoard.tsx`, `boardDiagram.ts`, `vite.config.ts` if needed), `test_agent_board.py:193`. Needs `UI review (factory)` | AC-21 to AC-42 |
| 3 | M | `sandbox/Dockerfile`, `sandbox/.dockerignore`, `server.mjs` (host, cap, workerd path, spawn error, VmRSS), `sandbox/test`, `arp/agent/sandbox.py` busy message, compose `sandbox` service | AC-51 to AC-74 (AC-61, AC-61b `unit`) |
