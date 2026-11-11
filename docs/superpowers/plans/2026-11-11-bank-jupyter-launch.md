# Bank Jupyter Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `main` runs in the bank's JupyterLab (Vertex AI Gemini, one port behind Jupyter Server Proxy) after `git pull` and `scripts/launch_jupyter.sh up`.

**Architecture:** Three settings switch the existing `GeminiClient` to Vertex mode. One setting makes the FastAPI app serve the built frontend at `/`; the frontend build goes relative when `VITE_API_BASE=.`. A new `arp preflight` command holds the readiness checks; a bash script wraps build, start, stop and check.

**Tech Stack:** Python 3.11, FastAPI/Starlette `StaticFiles`, `google-genai` (already a dependency), Typer, Vite, bash, Playwright (existing e2e setup).

**Spec:** `docs/superpowers/specs/2026-11-11-bank-jupyter-launch-design.md` (AC ids below refer to it).

## Global Constraints

- No new dependencies.
- Without the new settings everything behaves as today (AC-3, AC-6, AC-8, AC-34).
- Setting names exactly: `ARP_GEMINI_USE_VERTEX`, `ARP_GCP_PROJECT`, `ARP_GCP_LOCATION` (default `global`), `ARP_FRONTEND_DIST`, `ARP_PREFLIGHT_FETCH_URL` (default `https://www.sec.gov/robots.txt`).
- Pre-flight output lines exactly `ok <name>`, `skip <name>`, `FAIL <name>: <reason>`; names in order: `postgres`, `model <id>`, `verifier <id>`, `compute models`, `compute parse`, `frontend`, `fetch`.
- No production code path skips Google authentication to make a test pass.
- Never weaken an existing test. List every test change in the PR description. PR says `Spec: bank-jupyter-launch`, label `risk:normal`.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; `cd frontend && npm run lint && npx tsc -b && npm test`.

## Review Focus

1. Decision Studio needs cross-origin isolation (`Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp`; see `frontend/vite.config.ts`). Served by the API, the page must carry both headers or the rule engine fails. Test in Task 2.
2. Vertex on with a Claude model name in `ARP_LLM_MODEL` and no Anthropic key: the fallback path must build a Vertex Gemini client, not raise for a missing key. Test in Task 1.
3. Absolute URLs left in the frontend (`/something` in `src`, `public/` assets, download links built from `API_BASE`) break only under the proxy prefix. Test in Task 3 (AC-29 plus the browser test opening a second view).
4. `ARP_STANDINS_DIR` forbids model keys today; Vertex on together with stand-ins must be rejected the same way. Test in Task 1.
5. `up` run twice, or run while port 8000 is held by another process: must not kill the other process or report success. Test in Task 5 (AC-11c) plus a foreign-listener case.

---

### Task 1: Vertex mode for Gemini

**Files:**
- Modify: `backend/arp/config.py` (three fields next to `gemini_api_key`; one `model_validator`; extend `_standins_only_without_model_key`)
- Modify: `backend/arp/llm/gemini_client.py` (`GeminiClient.__init__`)
- Modify: `backend/arp/llm/factory.py` (`build_llm_client`)
- Modify: `backend/.env.example` (commented Vertex block)
- Test: `backend/tests/test_llm_vertex.py`

**Interfaces:**
- Produces: `Settings.gemini_use_vertex: bool = False`, `Settings.gcp_project: str | None = None`, `Settings.gcp_location: str = "global"`, property `Settings.gemini_available -> bool` (`gemini_use_vertex or bool(gemini_api_key)`).
- Produces: `GeminiClient(api_key: str | None, model, cache_dir, cache_enabled=True, cache_refresh=False, fallback_from="", *, vertex_project: str | None = None, vertex_location: str = "global")`. With `vertex_project` set it calls `genai.Client(vertexai=True, project=..., location=..., http_options=...)` and passes no `api_key`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_llm_vertex.py`. The recorder is an `httpx.MockTransport` passed through `types.HttpOptions(async_client_args={"transport": ...})` or, if the SDK version does not accept that, a patched `google.auth.default` returning `google.auth.credentials.AnonymousCredentials`-style test credentials with a fixed token plus `respx`-free monkeypatch of the SDK's async HTTP client; pick whichever the installed `google-genai` supports and keep it in one fixture `vertex_recorder`. Tests:
  - `test_vertex_request_goes_to_aiplatform` (AC-1, AC-30 location default): Vertex on, project `p`, no location, no keys, model `gemini-3.6-flash`; one `complete_structured` call; recorded host ends `aiplatform.googleapis.com`, path contains `projects/p/locations/global`, no `x-goog-api-key` header, no `key=` in the query.
  - `test_vertex_verifier_client` (AC-30): same through `build_verifier_llm_client`.
  - `test_vertex_ignores_api_key` (AC-12): as first, plus `gemini_api_key="k"`.
  - `test_api_key_mode_unchanged` (AC-3): Vertex off, key `k`; host `generativelanguage.googleapis.com`, header `x-goog-api-key: k`, nothing sent to `aiplatform.googleapis.com`.
  - `test_vertex_without_project_fails` (AC-2): `Settings(gemini_use_vertex=True)` and `gcp_project=""` both raise `ValueError` matching `ARP_GCP_PROJECT`.
  - `test_vertex_replaces_claude_model_without_anthropic_key` (Review Focus 2): `llm_model="claude-sonnet-5-5"`, Vertex on, no keys; `build_llm_client` returns a `GeminiClient` with `fallback_from == "claude-sonnet-5-5"`.
  - `test_vertex_with_standins_rejected` (Review Focus 4): `standins_dir` set and Vertex on raises `ValueError` matching `ARP_STANDINS_DIR`.
- [ ] **Step 2:** Run `cd backend && python3 -m pytest tests/test_llm_vertex.py -q`. Expected: all fail (unknown fields).
- [ ] **Step 3:** Implement the settings, validator and `gemini_available`.
- [ ] **Step 4:** Implement the `GeminiClient` change; in `factory.py` replace each `settings.gemini_api_key` truth test with `settings.gemini_available` and pass `vertex_project=settings.gcp_project if settings.gemini_use_vertex else None, vertex_location=settings.gcp_location` at both `GeminiClient(...)` call sites. The "ARP_GEMINI_API_KEY is not set" error names both options.
- [ ] **Step 5:** `grep -rn "gemini_api_key" backend/arp` and switch every remaining availability check (not the value pass-through) to `gemini_available`.
- [ ] **Step 6:** Run `python3 -m pytest tests/test_llm_vertex.py tests/test_factory.py tests/test_llm_gemini_fallback.py tests/test_gemini_and_modes.py -q && ruff check .`. Expected: pass.
- [ ] **Step 7:** Commit `feat(llm): Gemini through Vertex AI (ARP_GEMINI_USE_VERTEX)`.

### Task 2: API serves the built frontend

**Files:**
- Modify: `backend/arp/config.py` (`frontend_dist: Path | None`; a `field_validator` turning `""` into `None`)
- Modify: `backend/arp/api/main.py` (after the last `include_router`, around line 194 onwards; keep it last in the file's route setup)
- Test: `backend/tests/test_frontend_dist.py`

**Interfaces:**
- Produces: when `settings.frontend_dist` is set, `GET /` and asset paths are served from it with the two isolation headers; unknown `/api/...` stays JSON 404.

- [ ] **Step 1: Write failing tests.** Each builds the app with the setting applied the way existing API tests do (follow `backend/tests/test_api_*.py` for the app/settings fixture; if the app reads settings at import, reload `arp.api.main` in a fixture):
  - `test_root_serves_index` (AC-4): body contains `ARP-TEST-INDEX`, status 200.
  - `test_root_has_isolation_headers` (Review Focus 1): response headers `cross-origin-opener-policy == "same-origin"`, `cross-origin-embedder-policy == "require-corp"`.
  - `test_health_still_wins` (AC-5): `{"status": "ok"}`.
  - `test_unknown_api_path_is_json_404` (AC-14): body `{"detail": "Not Found"}`.
  - `test_docs_and_openapi_unchanged` (AC-34): status codes of `/docs` and `/openapi.json` equal those without the setting.
  - `test_unset_root_is_404` (AC-6) and `test_empty_value_is_unset` (AC-28).
  - `test_missing_dir_fails` (AC-13) and `test_dir_without_index_fails` (AC-27): creating the app raises with `ARP_FRONTEND_DIST` in the message.
- [ ] **Step 2:** Run `python3 -m pytest tests/test_frontend_dist.py -q`. Expected: fail.
- [ ] **Step 3:** Implement: validate in `Settings` (directory with `index.html`), mount `StaticFiles(directory=..., html=True)` at `/` last, with a small subclass or middleware adding the two headers to its responses only. A plain mount (no SPA catch-all) keeps `/api/...` 404s as JSON because routers are registered first.
- [ ] **Step 4:** Run the test file and `ruff check .`. Expected: pass.
- [ ] **Step 5:** Commit `feat(api): serve the built frontend when ARP_FRONTEND_DIST is set`.

### Task 3: Frontend works under a path prefix

**Files:**
- Modify: `frontend/vite.config.ts` (`base: process.env.VITE_API_BASE === '.' ? './' : '/'`)
- Modify: `frontend/src/api/client.ts` only if a use of `API_BASE` breaks with `"."` (line 510 slices by `API_BASE.length`; verify)
- Modify: any file found by the grep in Step 3
- Test: `frontend/tests/build-base.test.ts` (or the existing test folder's convention), `backend/tests/e2e/test_proxy_prefix.py`

**Interfaces:**
- Consumes: Task 2's `ARP_FRONTEND_DIST`.
- Produces: `VITE_API_BASE=. npm run build` yields a `frontend/dist` usable at any path prefix.

- [ ] **Step 1: Write failing tests.**
  - Frontend build test, two cases, each running `vite build --outDir <tmp>`: with `VITE_API_BASE=.` no output file contains `http://localhost:8000` and every `src`/`href` in `index.html` pointing at a build asset starts with `./assets/` (AC-29); without it a JS asset contains `http://localhost:8000` and those attributes start with `/assets/` (AC-8). If a build inside the unit test run is too slow for `npm test`, put it in `backend/tests/e2e/test_proxy_prefix.py` instead and say so in the PR.
  - `backend/tests/e2e/test_proxy_prefix.py` (AC-7a to 7c), marked `e2e`: start uvicorn on a free port with `ARP_FRONTEND_DIST` at the relative build; start a tiny in-test reverse proxy (stdlib `http.server` + `urllib`, about 30 lines) on another port that accepts only paths starting `/user/x/proxy/8000/`, strips that prefix and forwards, and returns 404 for anything else; open `http://127.0.0.1:<proxy>/user/x/proxy/8000/#home` with Playwright; collect responses until network idle; assert a heading matching `^Good (morning|afternoon|evening)` is visible, every same-origin response has status < 400, at least one `/user/x/proxy/8000/api/` response is 200. Then navigate to `#decision` and `#argus` and assert the same status rule (Review Focus 3).
- [ ] **Step 2:** Run both. Expected: fail (assets requested at `/assets/...` get the proxy's 404).
- [ ] **Step 3:** Set `base` in `vite.config.ts`. Then `grep -rnE "[\"'\`]/(assets|api|fonts|wasm|[a-z-]+\\.(svg|png|wasm|json|woff2?))" frontend/src frontend/index.html` and make each root-absolute URL relative to `import.meta.env.BASE_URL` or `API_BASE`.
- [ ] **Step 4:** Run `cd frontend && npm run lint && npx tsc -b && npm test`, then the e2e file per CLAUDE.md "Browser flow". Expected: pass.
- [ ] **Step 5:** Commit `feat(frontend): relative build for serving under a proxy path`.

### Task 4: `arp preflight`

**Files:**
- Create: `backend/arp/preflight.py`
- Create: `backend/arp/cli/preflight.py`; register in `backend/arp/cli/__init__.py` as a top-level command `preflight` (it must run the same DB cut-over rules as other commands except that a DB failure becomes a `FAIL postgres:` line, so register it alongside `db` in the cut-over skip list)
- Modify: `backend/arp/config.py` (`preflight_fetch_url: str = "https://www.sec.gov/robots.txt"`)
- Test: `backend/tests/test_preflight.py`

**Interfaces:**
- Produces: `async def run_preflight(settings: Settings, *, base_url: str = "http://127.0.0.1:8000", llm_factory=build_llm_client, http: httpx.AsyncClient | None = None) -> list[str]` returning exactly 7 lines; `arp preflight [--base-url URL]` prints them to stdout and exits 1 if any starts with `FAIL`.
- Each model check builds the client with `llm_factory(settings, model=<exact id>, cache_refresh=True)` on a settings copy that has every other provider's key cleared, so no fallback can answer, and asks for a one-field structured reply.

- [ ] **Step 1: Write failing tests** with stand-in `llm_factory` and `httpx.MockTransport`:
  - `test_all_ok_exact_lines` (AC-9, AC-22): exact 7 lines as in Global Constraints with the configured ids; exit code 0 through the CLI runner.
  - `test_bad_model_fails_without_fallback` (AC-10, AC-23): stand-in raises `RuntimeError("model not found")` for `nope`; line 2 is `FAIL model nope: model not found`; 7 lines; the other 6 start `ok`; the factory was called for `nope` and never for another model on that line; exit 1.
  - `test_bad_verifier` (AC-15): line 3 `FAIL verifier nope: model not found`.
  - `test_unset_compute_is_skip` (AC-19): line 4 is `skip compute models`, 7 lines, exit 0.
  - `test_unmigrated_db` (AC-24): line 1 starts `FAIL postgres:`.
  - `test_frontend_404` (AC-25): line 6 starts `FAIL frontend:`.
  - `test_fetch_timeout` (AC-26): line 7 is `FAIL fetch: timeout`; the transport saw `settings.preflight_fetch_url`.
- [ ] **Step 2:** Run `python3 -m pytest tests/test_preflight.py -q`. Expected: fail.
- [ ] **Step 3:** Implement. Postgres check reuses the migration check the CLI start-up already runs (find it in `backend/arp/cli/__init__.py` / `arp/db`). Compute checks reuse the existing compute client's health call if one exists, else `GET <url>/health` with the ID token helper in `arp/compute/`. Reasons are the exception message, first line, at most 200 characters.
- [ ] **Step 4:** Run the test file and `ruff check .`. Expected: pass.
- [ ] **Step 5:** Commit `feat(cli): arp preflight readiness checks`.

### Task 5: Launch script and install docs

**Files:**
- Create: `scripts/launch_jupyter.sh` (model on `backend/scripts/e2e_stack.sh`: same `wait_for`, pid and log files under `${TMPDIR:-/tmp}/arp-jupyter`)
- Modify: `docs/INSTALLATION.md` (new section `## Bank Jupyter (Vertex)` and a table-of-contents line)
- Test: `backend/tests/test_launch_jupyter_doc.py` (AC-33); evaluator rows cover the script

**Interfaces:**
- Consumes: `ARP_FRONTEND_DIST` (Task 2), relative build (Task 3), `arp preflight` (Task 4).
- Produces: `scripts/launch_jupyter.sh up|down|check`.

- [ ] **Step 1:** Write `test_installation_has_bank_section` (AC-33): the section under the heading `Bank Jupyter (Vertex)` contains `ARP_GEMINI_USE_VERTEX`, `ARP_GCP_PROJECT` and `scripts/launch_jupyter.sh up`. Run it. Expected: fail.
- [ ] **Step 2:** Write the script.
  - `up`: load `backend/.env` only to check that `ARP_POSTGRES_DSN`, `ARP_LLM_MODEL`, `ARP_LLM_VERIFIER_MODEL` (and `ARP_GCP_PROJECT` when `ARP_GEMINI_USE_VERTEX=true`) are set in the environment or that file; on a missing one print its name and exit 1 before starting anything (AC-17). If the pid file's process is alive, print `already running (pid N)` and exit 0 (AC-11c). If port 8000 is held by any other process, print `port 8000 is in use by another process` and exit 1 without killing it (Review Focus 5). Run `arp db init-postgres`. Rebuild with `VITE_API_BASE=. npm run build` when `frontend/dist/index.html` is missing or older than any file under `frontend/src` (AC-11b, AC-18, AC-31); run `npm ci` first only if `frontend/node_modules` is missing. Start `ARP_FRONTEND_DIST=<repo>/frontend/dist uvicorn arp.api.main:app --host 0.0.0.0 --port 8000` with `nohup`. Wait up to 120 s for `/api/health`; on timeout print the log path, stop the process, exit 1 (AC-32). Print one line: `${JUPYTERHUB_SERVICE_PREFIX}proxy/8000/` when that variable is set, else `http://localhost:8000/` (AC-11a, AC-11d).
  - `down`: stop the pid if alive, remove the pid file, exit 0 either way (AC-16).
  - `check`: `cd backend && exec arp preflight` (AC-21).
- [ ] **Step 3:** Rehearse the evaluator rows by hand in this container: `bash backend/scripts/e2e_stack.sh down`, `bash .claude/hooks/ensure-deps.sh postgres`, then AC-11a to 11d, 16, 17, 18, 20, 21, 31, 32 in order with `JUPYTERHUB_SERVICE_PREFIX=/user/x/`. Record the commands and output in the PR description.
- [ ] **Step 4:** Write the `docs/INSTALLATION.md` section: the `.env` block from the spec's target environment, the three commands, the note that everyone is signed in as the dev approver, and how to point pip and npm at Artifactory (`PIP_INDEX_URL`, `npm config set registry`) as placeholders the reader fills in.
- [ ] **Step 5:** Run `python3 -m pytest tests/test_launch_jupyter_doc.py -q`, `bash -n scripts/launch_jupyter.sh`, and `shellcheck scripts/launch_jupyter.sh` if installed. Expected: pass.
- [ ] **Step 6:** Commit `feat: scripts/launch_jupyter.sh and Bank Jupyter install section`.

### Task 6: Open the PR

- [ ] **Step 1:** Run the full check set from Global Constraints on changed areas; regenerate the API contract only if a request/response model changed (none is expected).
- [ ] **Step 2:** Follow `.claude/skills/steward/SKILL.md`: PR against `main`, `Spec: bank-jupyter-launch`, `risk:normal`, list of test changes (new files only), the Step 3 transcript from Task 5, and the accepted exception (real Vertex call is verified by the owner running `check` in Jupyter).
- [ ] **Step 3:** Say in the PR whether `openwiki/` needs an update (yes: quickstart "Run it locally" gains the Jupyter path; left to `/context-refresh`).
