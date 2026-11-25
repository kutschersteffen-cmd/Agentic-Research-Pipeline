# CI hardening and small hygiene: scans that block, least-privilege workflows, pinned actions, and eight small code fixes

Status: Draft, for owner approval
Slug: `ci-hardening-hygiene`
Risk: slice 1 `risk:normal`; slices 2 and 3 `risk:high` (slice 2 edits `.github/workflows/**` and `.github/scripts/**`; slice 3 edits the database schema check)
Size: `M`, three slices (bug-list bundle F = items 11 + 14)

## Decisions for the owner

One decision changes the result; approving the spec approves it.

1. **Pillow findings are accepted for now, not fixed.** `pip-audit` and Trivy report 42 and 29 Pillow findings (5 CRITICAL in Trivy), all fixed only in Pillow 13.0.0. Pillow 13 cannot be installed: `docling-core==2.101.1`, `docling-parse==7.22.3` and `docling-ibm-models==4.0.3` (pinned in `backend/pyproject.toml:28-31`) require `pillow<13`. I checked: `pip install pillow==13.0.0` ends with `pip check` errors for all three. Moving docling to versions that allow Pillow 13 changes the PDF parser the whole extraction pipeline runs on, so it is its own factory item, not part of this one. Until then the Pillow IDs sit on the allow-list with a review date of 2027-02-28. The app uses Pillow only on images an analyst uploads (`arp/storage/report_images.py`, `arp/reporting/*`).

Everything else is decided under "Defaults taken".

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`; IDs in brackets below) found, still present on `main` at `a021636`:

- **M4 [C3.8]** The four security scans in `ci.yml` (`pip-audit`, `npm audit`, two Trivy image scans) have `continue-on-error: true`, so they can never fail the build. The latest `main` run (`45572765321`) shows they find plenty: 42 Pillow advisories, 12 npm advisories (10 high), 92 and 70 high/critical image findings.
- **M5 [C3.9]** `ci.yml`, `golden-set.yml`, `holdout.yml` and `mutation.yml` have no top-level `permissions:`, so every job gets the repository default token. Actions are referenced by movable tags (`@v4`), so a hijacked tag runs in our CI.
- **L25 [C3.11]** `.github/scripts/mutation_frontend.py:24` runs Stryker with `typescript@5.9.2`; the app uses `~6.0.2`. `frontend/tsconfig.app.json` and `tsconfig.node.json` never set `strict`.
- **Dead rule** `("PRODUCT.md", NONE)` in `.github/scripts/ci_changes.py:31` (the file was deleted in #712).
- **LM2 [A12, C2.4]** Five routes start a background run with a bare `asyncio.create_task(...)` and keep no reference. Python may garbage-collect such a task mid-run, and an exception in it is never logged.
- **L3 [A14, C2.7]** Blocking work runs on the event loop in the Ask portfolio branch and in `universe_from_companies`.
- **L4 [A15]** An uploaded benchmark with no date shows "Sector weights of X as of ." and "Source: X · as of ".
- **L16 [C1.9]** `ssrf_guard_request_hook` calls blocking `socket.getaddrinfo` inside an async httpx hook.
- **L19 [C2.6a]** `_deck_response` leaks its temp directory when the deck build raises.
- **L18 [C2.3]** The startup schema check skips missing columns, so a backend with a missing column starts and fails on its first query.

The Antigravity patch is a hint only; this spec states the behaviour.

## What changes for the user

- A pull request with a new fixable HIGH/CRITICAL dependency or image finding now fails CI instead of passing silently.
- An Ask answer about an undated benchmark reads "Sector weights of X." and "Source: X".
- The backend refuses to start when the database lacks a column the code expects, and says to run `arp db init-postgres`.
- A failing background run (discovery, calibration, emerging themes, Argus documents, transition-barrier refresh) leaves a stack trace in the log.

## Slices

Three PRs, each with `Spec: ci-hardening-hygiene` and its `Rows:` line, every changed test listed. Slice 1 first; slices 2 and 3 touch no common file and may build in parallel with it or after it.

| Slice | Risk | Size | Contents | Rows |
|---|---|---|---|---|
| 1 | `risk:normal` | S | LM2, L3, L4, L16, L19 (backend and Ask UI; needs a UI review because it edits `frontend/src/**`) | AC-1 to AC-14 |
| 2 | `risk:high`, owner merges | M | M4, M5, L25, the dead `ci_changes.py` rule; the `mermaid` bump | AC-15 to AC-33 |
| 3 | `risk:high`, owner merges | S | L18 | AC-34 to AC-37 |

Bundle E runs at the same time. This spec does **not** touch: any Dockerfile, `.dockerignore`, `docker-compose.yml`, nginx config, `sandbox/`, auth or token code, the `/raw` documents route, or `.github/workflows/images.yml`.

## Slice 1: backend and Ask UI hygiene

### LM2: background tasks are kept and their failures logged

Five routes start a run with `asyncio.create_task(...)` and drop the result: `argus.py:291` (`find_documents`), `calibration.py:35`, `discovery.py:56`, `emerging_themes.py:71`, `transition_barrier.py:151` (`start_refresh_run`). Add one helper that creates the task, keeps it in a module-level `set` until it is done (`task.add_done_callback(tasks.discard)`), and logs an exception that ends it with `logger.exception(...)`/`logger.error(..., exc_info=...)` at ERROR. The five routes call it. Where it lives is the builder's choice (the smallest diff; `arp/orchestration/jobs.py` already has the same pattern in `LocalJobLauncher.launch`, but moving these routes onto the launcher is **not** wanted: it adds a run lease and changes behaviour). Nothing else about the routes changes, including their response bodies.

The strong reference cannot be seen from outside (a suspended task is reachable from the event loop either way), so no row pins it; the code review checks it.

### L3: stop blocking the event loop

- `routers/ask.py`, portfolio branch of `answer()`: `portfolio_directories(d.store)` runs through `run_in_threadpool` (already imported there). In `arp/portfolio/qa_agent.py` `answer_question`, the first two store reads, `store.list_portfolios()` and the `dates_of` line (`store.list_snapshot_dates(pid)` per portfolio), run through `run_in_threadpool` as well. The later reads in that function (`analytics.execute`, `load_holdings_as_of`, `_simulated_note`) stay as they are; see "Not done".
- `routers/universe.py:105` `universe_from_companies` becomes a plain `def`. Its body has no `await`, so FastAPI then runs it in a worker thread.
- `routers/dossier_position.py:279` `activate_standards` stays `async def`. The brief asked for a plain `def`, but that would break it: it calls `start_extraction`, which reaches `get_job_launcher().launch(...)` and `asyncio.create_task(...)`, and `create_task` raises "no running event loop" in a worker thread. The route would answer 502 "extraction could not start" every time.
- `find_documents`, `resume_run_endpoint` (`runs.py:109`), `start_refresh_run` and xbrl `start_run` (`xbrl.py:67`) stay `async def` for the same reason (they start tasks).

### L4: no "as of ." for an undated benchmark

`arp/ask.py:135` builds `f"Sector weights of {name} as of {as_of}."`. When `as_of` is empty (`""` or `None`; stewardship benchmarks store `""`) the text is `f"Sector weights of {name}."`. `frontend/src/components/AskCards.tsx:15` builds `Source: ${b.name} · as of ${b.check.as_of}`; when `b.check.as_of` is empty the line is `Source: ${b.name}`. The card's `check.as_of` value is not changed (it stays `""`). The sample branch (`SAMPLE_TEXT`, "synthetic sample") is unchanged. The "As of" row further down the card (`AskCards.tsx:57`, `c.as_of ?? "—"`) is not touched.

### L16: the SSRF hook no longer blocks the loop

`ssrf_guard_request_hook` (async) runs `assert_safe_fetch_target(request.url)` through `await asyncio.to_thread(...)`. `assert_safe_fetch_target` and `ssrf_guard_sync_request_hook` stay as they are. The hook is **not** added to the three operator-configured clients (change detector, regulatory RSS, XBRL registry): their URLs come from operator config, not from users.

### L19: no leaked temp directory

In `routers/stewardship.py` `_deck_response`, if `build(...)` raises, the temp directory (`arp_deck_*`) is removed and the exception propagates unchanged. On success the behaviour stays: the directory is removed by the background task after the file is sent.

## Slice 2: CI hardening

### M4: scans block, with an allow-list

The four steps lose `continue-on-error: true` and take `continue-on-error: ${{ github.event_name != 'pull_request' }}` instead (`ci.yml`: `pip-audit` ~418, `npm audit` ~456, "Scan backend image" ~486, "Scan frontend image" ~493). Their comments "Non-blocking for now" go too. Policy: **a fixable HIGH or CRITICAL finding blocks; everything else does not.**

**Triage of the latest `main` run (`45572765321`, 25 Nov 2026), one line per finding group**

| Scan | Finding | Verdict |
|---|---|---|
| pip-audit | `pillow 12.3.0`, 42 advisories, fix 13.0.0 | Allow-list (Appendix A): Pillow 13 conflicts with docling's pins, see Decisions. Review by 2027-02-28 |
| npm audit | `lodash-es` (GHSA-r5fr-rjxr-66jc, GHSA-xxjr-mmjv-4gpg) and `uuid` (GHSA-w5hq-g745-h8pq), pulled in by `mermaid@11.4.1` | **Fix in this slice**: pin `mermaid` to `11.17.2` in `frontend/package.json` and regenerate `package-lock.json`. I tried it: `npm audit` then no longer lists `lodash-es` or `uuid` |
| npm audit | `katex` GHSA-238p-pmpm-9mq7 (prototype pollution), fix only with `mermaid@12`, a breaking change | Allow-list. KaTeX renders only text from the app's own board diagrams (`src/boardDiagram.ts`). Review by 2027-02-28 |
| npm audit | `zod` GHSA-mrhx-c7xc-m3w5 (memory use on oversized collections) via `@gorules/jdm-editor@1.52.0`; npm's only "fix" is a downgrade to 1.10.0 | Allow-list. Review by 2027-02-28 |
| Trivy backend image, Debian 13.8 | 92 findings (91 HIGH, 1 CRITICAL); the 89 I could read are all `affected` or `fix_deferred`, none has a fixed version | Not blocking: `ignore-unfixed` |
| Trivy backend image, Python | `pillow 12.3.0` (29 of the 31, 5 CRITICAL) | Allow-list (Appendix B), same reason as pip-audit |
| Trivy backend image, Python | `jaraco.context 5.3.0` (CVE-2026-23949), `wheel 0.45.1` (CVE-2026-24049), both vendored in the base image's own `setuptools` under `/usr/local/lib/python3.11/site-packages/setuptools/_vendor` | Allow-list (Appendix B). The fix is a `pip install -U setuptools` or a newer base in `backend/Dockerfile`, which is bundle E's file. Review by 2027-02-28 |
| Trivy backend image, secrets | 11 CRITICAL "gcp-service-account" in `anthropic/.../agents.py` docstrings (`{*****}` placeholders) | False positives. Not blocking: the Trivy steps scan `vuln` only (`scanners: vuln`) |
| Trivy frontend image, Alpine 3.21.3 (`nginx:1.27-alpine`) | 70 findings (3 CRITICAL), 54 distinct IDs, all with fixed versions | Allow-list (Appendix C). The fix is a newer base image tag in `frontend/Dockerfile`, which is bundle E's file. Review by 2027-02-28; delete the entries when the base moves |

**New advisories after today.** Base images move under us. The scans are therefore limited in four ways, so an unrelated PR is not blocked by noise: they report only HIGH and CRITICAL; they ignore findings with no fixed version (`ignore-unfixed: true`); they scan for vulnerabilities only; and every accepted finding is on a file-based allow-list with a review date. A finding that is both fixable and new still blocks a **pull request**, deliberately; the recovery is a PR that bumps the dependency or adds the ID to the allow-list with a reason. That PR is `risk:high` (it edits `.github/`), so the owner merges it. On a **push to `main`** the four steps do not fail the run (they still print their findings): otherwise an advisory published between a PR's green run and its merge would turn `main` red, and Main guard would propose reverting an innocent merge.

**Mechanics (the builder follows these exactly)**

- `pip-audit` step (job `backend-supply-chain`): read `.github/allowlists/pip-audit.txt`, one advisory ID per entry, and pass every ID as `--ignore-vuln <ID>`, e.g. `pip-audit $(grep -v '^[[:space:]]*#' .github/allowlists/pip-audit.txt | grep -v '^[[:space:]]*$' | awk '{print "--ignore-vuln " $1}')` (entry lines are `<ID>`, optionally followed by a `# comment`). On a pull request the step fails when `pip-audit` finds anything else.
- `npm audit` step (job `frontend-supply-chain`): replace `npm audit --audit-level=high` with `npx --yes audit-ci@7.1.0 --config ../.github/allowlists/audit-ci.jsonc` (the job's working directory is `frontend/`). The config file is JSONC: `{"high": true, "package-manager": "npm", "allowlist": [...]}`. The builder reads the tool's README for the exact keys.
- Both Trivy steps (job `container-scan`): `severity: "CRITICAL,HIGH"`, `ignore-unfixed: true`, `scanners: vuln`, `exit-code: "1"`, `trivyignores: .github/allowlists/trivy.ignore`.
- Entry rule for all three allow-list files: every entry belongs to a block that starts with a comment line containing the reason and `review by YYYY-MM-DD`. In `trivy.ignore`, each ID also carries `exp:YYYY-MM-DD` (Trivy stops ignoring it on that day, which is the reminder).
- After the merge (owner, GitHub settings, not code): add "Backend dependency audit + SBOM", "Frontend dependency audit + SBOM" and "Container image scan (Trivy)" to the required checks of `main`. A failing job that is not required does not stop a merge.

### M5: least privilege and pinned actions

- `ci.yml`, `golden-set.yml`, `holdout.yml` and `mutation.yml` get a top-level `permissions: contents: read`. Job-level `permissions` that already exist stay as they are (`holdout.yml`: `setup`, `test`, `acceptance`). **`ci.yml` job `secret-scan` gets its own job-level `permissions: contents: read` and `pull-requests: read`:** `gitleaks/gitleaks-action` lists the PR's commits through the API, and a top-level `contents: read` takes that away.
- `context-graph.yml`, `main-guard.yml` and `pr-guards.yml` already declare `permissions` and keep them; they are pinned like the rest.
- In every workflow except `images.yml`, every `uses:` is pinned to the full 40-character commit SHA with the tag in a trailing comment, using exactly these values (read from the `main` run logs of 25 Nov 2026; `actions/cache/restore` and `actions/cache/save` use the `actions/cache` SHA):

| Action | Tag | SHA |
|---|---|---|
| `actions/checkout` | `v4` | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/cache` | `v4` | `0057852bfaa89a56745cba8c7296529d2fc39830` |
| `actions/download-artifact` | `v4` | `d3f86a106a0bac45b974a628896c90dbdf5c8093` |
| `actions/setup-node` | `v4` | `49933ea5288caeca8642d1e84afbd3f7d6820020` |
| `actions/setup-python` | `v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/upload-artifact` | `v4` | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| `gitleaks/gitleaks-action` | `v2` | `ff98106e4c7b2bc287b24eaf42907196329070c7` |
| `aquasecurity/trivy-action` | `v0.36.0` | `ed142fd0673e97e23eac54620cfb913e5ce36c25` |

- `images.yml` is left untouched (bundle E; its pins are a follow-up).
- Add `.github/dependabot.yml` with the `github-actions` ecosystem, directory `/`, weekly, so the pins stay current. Dependabot PRs edit workflows, so they are `risk:high` and the owner merges them.

### L25 and the dead rule

- `.github/scripts/mutation_frontend.py:24`: `typescript@5.9.2` becomes `typescript@~6.0.2`, the app's own range (`frontend/package.json:34`).
- `"strict": true` is added to `compilerOptions` of `frontend/tsconfig.app.json` and `frontend/tsconfig.node.json`. I ran `npx tsc -b` with it on `main`: no errors (TypeScript 6 already defaults to strict).
- Remove `("PRODUCT.md", NONE)` from `RULES` in `.github/scripts/ci_changes.py`. A changed `PRODUCT.md` then falls through to the default and runs everything; nothing else changes.

## Slice 3: the startup schema check sees missing columns

`schema_gaps` (`backend/arp/storage/postgres_schema.py:695`) returns only missing tables and pending steps, so `require_cutover` (`backend/arp/db/session.py:49`) lets a backend start with a table that lacks a column the models define, and the first query fails. `schema_report` already finds those columns with `_missing_columns(conn)` (one inspector read per existing table).

Change: `schema_gaps` also returns the missing columns, reported as `"table.column"` strings, in the order `_missing_columns` yields them, and `require_cutover` puts them in its message. The message becomes
`Not cut over to Postgres: the database schema is not current (missing tables: [...], missing columns: [...], pending steps: [...]). Run `arp db init-postgres`, `arp db import`, then `arp db verify` (docs/INSTALLATION.md); set ARP_SKIP_CUTOVER_CHECK=1 to start anyway.`
(only the `missing columns: [...]` part is new; `arp db init-postgres` is already named). `schema_gaps` has no other caller, so its return shape is the builder's choice (a 3-tuple is the smallest change).

**Cost, measured** on `main` with local Postgres 16 (`ensure-deps.sh postgres`, 67 tables, schema created by `ensure_schema`): the current check takes about 0.004 s; the column scan alone takes 0.06 to 0.08 s. The extra cost is under 0.1 s, far below the 1 s limit, so the slice stays and there is no question to the owner. On a remote database it is a few extra round trips (SQLAlchemy reads each table's columns in one batch per table).

A backend that started before may now refuse to start. That is the intent: it was running on a schema its own queries cannot use.

## Defaults taken

1. **`ARP_SKIP_CUTOVER_CHECK=1` still skips the whole check**, columns included.
2. **A dropped table is reported once**, under "missing tables", not again as its columns (as `_missing_columns` does today).
3. **Allow-list review date is 2027-02-28** (three months) for every entry. After that date Trivy ignores nothing on `trivy.ignore`, which then fails every app PR; the date is a deliberate nag, so the owner or a factory item must clear it first.
4. **`audit-ci@7.1.0`** is run through `npx` at a pinned version; it is the only new tool.
5. **Trivy `scanners: vuln`** drops secret scanning of image layers. `gitleaks` still scans the repository, and the image "secrets" were false positives.
6. **No allow-list for `images.yml`**, and no pinning of its actions: bundle E owns that file.
7. **The `mermaid` bump is `11.4.1` → `11.17.2`**, the version `npm audit` names. The builder runs `npm test` and the diagram-related tests; if mermaid 11.17.2 breaks them, the builder stops and asks (`factory:blocked`).
8. **The scans fail only pull-request runs.** On a push to `main` they print and pass (`continue-on-error: ${{ github.event_name != 'pull_request' }}`), so Main guard never reverts a merge over a newly published advisory.
9. **Slice 3 touches `schema_gaps` only.** `schema_report`, the drift check and `ensure_schema` are unchanged.

## Not done (follow-ups, listed so nobody assumes otherwise)

- Moving docling to versions that allow Pillow 13, then deleting Appendix A and the Pillow entries of Appendix B.
- A newer `nginx` base image for the frontend and `pip install -U setuptools` (or a newer Python base) for the backend image: both are Dockerfile edits (bundle E). Delete Appendix C and the `jaraco.context`/`wheel` entries then.
- `answer_question`'s later store reads (`analytics.execute`, `load_holdings_as_of`, `_simulated_note`) still run on the event loop, and `activate_standards`' store reads too.
- Pinning `images.yml` actions to SHAs.
- Showing "—" for an empty "As of" in the Ask card's detail table.

## Acceptance

Backend rows call the named function or route inside a running event loop (`pytest-asyncio`; `httpx.AsyncClient` with `ASGITransport`, because a `TestClient` ends its loop, and the background tasks with it, when the call returns). "Off the loop thread" means `threading.get_ident()` differs from the loop thread's ident. Workflow rows parse the files at the repository root of `main` with a YAML parser (a `uses:` key is read from the parsed step, its comment from the raw line). Browser rows run in headless Chromium at 1440 × 900 against `backend/scripts/e2e_stack.sh up` and stub the API with `page.route` as `backend/tests/e2e/test_agent_ask_actions_focus.py` does: the ask thread is `#/agent/ask/<thread id>` and its single ask carries a `benchmark_sectors` card.

### Slice 1 (`Rows: AC-1 ... AC-14`)

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | for each of the five routes, the name the router module imports replaced (`argus.find_documents` → `argus.execute_discovery_run`; the discovery start route → `discovery.execute_discovery_run`; the calibration start route → `calibration.execute_calibration_run`; the emerging-themes start route → `emerging_themes.execute_emerging_themes_run`; `transition_barrier.start_refresh_run` → `transition_barrier.execute_refresh_run`) by an `async def` that raises `RuntimeError("boom-<route>")` | the route is called and the loop then runs until the background task has ended | a log record of level ERROR (any logger) exists whose `exc_info[1]` is that `RuntimeError` (message `boom-<route>`) | holdout |
| AC-2 | the same five routes, the run function replaced by one that returns normally | the route is called and the loop runs until the task has ended | the route returns the body it returns today (`{"run_id": ..., "company_count": ...}` for discovery and emerging themes, `{"run_id": ...}` for calibration, `{"run_id": ..., "source_count": ...}` for the refresh, for Argus the same flow view the route returned before the change) and no ERROR record was logged | holdout |
| AC-3 | `answer()` in `routers/ask.py` with the routing model answering tool `portfolio`, and a `PortfolioStore` holding one portfolio `p1` with one snapshot date, whose `list_securities`, `list_companies`, `list_portfolios` and `list_snapshot_dates` record `threading.get_ident()` | `answer()` is awaited | every recorded ident from those four methods differs from the event-loop thread's ident, and each method was called at least once | holdout |
| AC-4 | a store method that `universe_from_companies` calls while saving (the saved-universe write) replaced by one recording `threading.get_ident()` | `POST /api/universe/from-companies` with one company through `httpx.AsyncClient(ASGITransport)` | the response is 200 and the recorded ident differs from the event-loop thread's ident | holdout |
| AC-5 | (structural check) the modules of the routes below | `inspect.iscoroutinefunction(f)` for `dossier_position.activate_standards`, `argus.find_documents`, `runs.resume_run_endpoint`, `transition_barrier.start_refresh_run`, `xbrl.start_run` | is `True` for all five | holdout |
| AC-6 | an uploaded benchmark named `Test Index` whose stored `as_of` is `""`, and again with `None` | `benchmark_sectors(streams_root, <its id>)` | the returned text is exactly `Sector weights of Test Index.` in both cases | holdout |
| AC-7 | the same benchmark with `as_of` `"Oct 20, 2026"` | `benchmark_sectors(...)` | the returned text is exactly `Sector weights of Test Index as of Oct 20, 2026.` | holdout |
| AC-8 | the Ask thread page whose answer is a `benchmark_sectors` card named `Test Index` with `check.as_of` `""` | the page has loaded | the text of the element starting with `Source:` inside the benchmark card (`.ask-turn`) is exactly `Source: Test Index` | holdout |
| AC-9 | the same card with `check.as_of` `"Oct 20, 2026"` | the page has loaded | the text of the element starting with `Source:` inside the benchmark card (`.ask-turn`) is exactly `Source: Test Index · as of Oct 20, 2026` | holdout |
| AC-10 | `socket.getaddrinfo` replaced by a function that records `threading.get_ident()` and returns one public address (`93.184.216.34`), and an `httpx.Request("GET", "https://example.test/")` | `await ssrf_guard_request_hook(request)` | it returns `None` and the recorded ident differs from the event-loop thread's ident | holdout |
| AC-11 | `socket.getaddrinfo` returning `127.0.0.1` for `internal.test` | `await ssrf_guard_request_hook(httpx.Request("GET", "http://internal.test/"))` | raises `UnsafeURLError` whose message contains `internal.test resolves to a disallowed address (127.0.0.1)` | holdout |
| AC-12 | `tempfile.mkdtemp` wrapped to record the directory it returns, and a `build` function that raises `ValueError("deck failed")` | `_deck_response(build, data, "x.pptx", BackgroundTasks())` | it raises `ValueError("deck failed")` and the recorded directory no longer exists | holdout |
| AC-13 | the same wrapper and a `build` that writes the file it is given and returns its path | `_deck_response(...)`, then the `BackgroundTasks` are run | right after the call the file exists; after the tasks have run the recorded directory no longer exists | holdout |
| AC-14 | `socket.getaddrinfo` replaced by a function that records `threading.get_ident()` and returns one public address | `ssrf_guard_sync_request_hook(request)` is called from the test thread | it returns `None` and the recorded ident equals the calling thread's ident (the sync hook is unchanged) | holdout |

### Slice 2 (`Rows: AC-15 ... AC-33`)

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-15 | `ci.yml`, `golden-set.yml`, `holdout.yml`, `mutation.yml` parsed | the top-level `permissions` key is read | it equals `{"contents": "read"}` in each of the four files | holdout |
| AC-16 | `holdout.yml` parsed | the job-level `permissions` are read | `setup` is `{contents: read, pull-requests: read, actions: read}`, `test` is `{contents: read}`, `acceptance` is `{contents: read, actions: read, checks: read, issues: write}` | holdout |
| AC-17 | `ci.yml` parsed | job `secret-scan` is read | its job-level `permissions` equals `{contents: read, pull-requests: read}` | holdout |
| AC-18 | every file in `.github/workflows/` except `images.yml` | every step `uses:` value is read | each matches `^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$` and its line ends in `# <tag>` where `<tag>` starts with `v` | holdout |
| AC-19 | the same files | each `uses:` repository is looked up in the SHA table of this spec | the SHA after `@` equals the table's value for that repository (`actions/cache/restore` and `/save` use the `actions/cache` value), and the comment equals the table's tag | holdout |
| AC-20 | `.github/dependabot.yml` | parsed | `version == 2` and `updates` holds an entry with `package-ecosystem: github-actions`, `directory: "/"`, `schedule.interval: weekly` | holdout |
| AC-21 | `ci.yml` job `backend-supply-chain`, step named `pip-audit` | the step is read | its `continue-on-error` is exactly `${{ github.event_name != 'pull_request' }}`, and its `run` text contains `.github/allowlists/pip-audit.txt` and `--ignore-vuln` | holdout |
| AC-22 | `ci.yml` job `frontend-supply-chain`, step named `npm audit` | the step is read | its `continue-on-error` is exactly `${{ github.event_name != 'pull_request' }}`, and its `run` text contains `audit-ci@7.1.0` and `.github/allowlists/audit-ci.jsonc` | holdout |
| AC-23 | `ci.yml` job `container-scan`, steps "Scan backend image" and "Scan frontend image" | both steps are read | for both, `continue-on-error` is exactly `${{ github.event_name != 'pull_request' }}`; both have `with.severity == "CRITICAL,HIGH"`, `with.ignore-unfixed` the boolean `true`, `with.scanners == "vuln"`, `with.exit-code == "1"` and `with.trivyignores == ".github/allowlists/trivy.ignore"` | holdout |
| AC-24 | `.github/allowlists/pip-audit.txt`, `.github/allowlists/audit-ci.jsonc`, `.github/allowlists/trivy.ignore` | each is read, blank lines ignored | each exists, and every entry (an ID line, or a quoted ID in the JSONC array) sits in a block (consecutive entry lines directly after a comment line, ended by a blank line; in the JSONC, a `//` line directly before its quoted IDs) whose comment contains `review by ` and a `YYYY-MM-DD` date; one block may hold many IDs; every non-comment line of `trivy.ignore` also carries `exp:YYYY-MM-DD` | holdout |
| AC-25 | `.github/allowlists/audit-ci.jsonc` (comments stripped) | parsed | `allowlist` contains `GHSA-238p-pmpm-9mq7` and `GHSA-mrhx-c7xc-m3w5` (a superset is fine), `high` is `true` | holdout |
| AC-26 | `.github/allowlists/pip-audit.txt` | the IDs on entry lines are collected | the set contains every ID of Appendix A | holdout |
| AC-27 | `.github/allowlists/trivy.ignore` | the IDs on entry lines are collected | the set contains every ID of Appendix B and Appendix C | holdout |
| AC-28 | `frontend/package.json` and `frontend/package-lock.json` | parsed | `dependencies.mermaid == "11.17.2"`, the lockfile's `packages["node_modules/mermaid"].version == "11.17.2"`, no `lodash-es` entry in `packages` has a version below `4.17.23`, and no `uuid` entry has a version below `11.1.1` | holdout |
| AC-29 | `.github/scripts/mutation_frontend.py` | the `STRYKER` list is read | it contains `typescript@~6.0.2` and not `typescript@5.9.2` | holdout |
| AC-30 | `frontend/tsconfig.app.json` and `frontend/tsconfig.node.json` | parsed | `compilerOptions.strict` is `true` in both | holdout |
| AC-31 | `.github/scripts/ci_changes.py` | `jobs(["PRODUCT.md"])` | returns `{"backend": True, "frontend": True, "app": True}` | holdout |
| AC-32 | the same module | `jobs(["README.md"])` and `jobs(["GLOSSARY.md"])` | each returns `{"backend": False, "frontend": False, "app": False}` | holdout |
| AC-33 | `python .github/scripts/ci_changes.py --selftest`, whose `CASES` the slice extends with a `PRODUCT.md` case expecting `backend frontend app` | it is run | exit code 0 and its output contains a line starting `ok   PRODUCT.md` | holdout |

Not covered by a row: that a pull request with a new fixable finding actually fails CI. That needs a live scanner run; the PR's own CI run and the code review check it, and the PR description must show one allow-listed and one unlisted ID behaving as intended where the log allows.

### Slice 3 (`Rows: AC-34 ... AC-37`)

The Holdout job runs a Postgres service (`holdout.yml` `services: postgres`), so these are `holdout` rows. Each row creates the schema with `ensure_schema(dsn)` in a scratch Postgres database (`ARP_TEST_POSTGRES_DSN`), with `runs_dir` an empty temporary directory and `skip_cutover_check` false.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-34 | the schema current, then `ALTER TABLE agent_asks DROP COLUMN standalone_question` (a nullable text column, no key or index) | `require_cutover(settings)` | raises `RuntimeError` whose message starts with ``Not cut over to Postgres: the database schema is not current (missing tables: [], missing columns: ['agent_asks.standalone_question'], pending steps: [])`` and contains `` `arp db init-postgres` `` | holdout |
| AC-35 | the database of AC-34, then `ensure_schema(dsn)` again | `require_cutover(settings)` | returns `None` | holdout |
| AC-36 | the schema current and nothing dropped | `require_cutover(settings)` | returns `None` | holdout |
| AC-37 | the database of AC-34 and `skip_cutover_check` true | `require_cutover(settings)` | returns `None` | holdout |

Must not change (each also a row above): the activate route keeps starting extraction (AC-5); the five other async routes stay async (AC-5); a dated benchmark keeps its text and source line (AC-7, AC-9); a safe address passes the SSRF hook, an unsafe one is refused, and the sync hook is unchanged (AC-10, AC-11, AC-14); a successful deck still cleans up after being sent (AC-13); a current database still starts (AC-36); `ARP_SKIP_CUTOVER_CHECK=1` still skips the check (AC-37); the secret-scan job keeps its pull-request read access (AC-17). `images.yml` and every Dockerfile stay untouched: the code review checks it, no row can.

## Appendices

Allow-list contents, copied from the CI log of `main` run `45572765321`. All entries: review by 2027-02-28.

**A. pip-audit, Pillow 12.3.0, fixed only in 13.0.0 (42)**
`PYSEC-2026-4326 PYSEC-2026-4327 PYSEC-2026-4328 PYSEC-2026-4329 PYSEC-2026-4330 PYSEC-2026-4331 PYSEC-2026-4332 PYSEC-2026-4333 PYSEC-2026-4334 PYSEC-2026-4335 PYSEC-2026-4336 PYSEC-2026-4337 PYSEC-2026-4338 PYSEC-2026-4339 PYSEC-2026-4340 PYSEC-2026-4341 PYSEC-2026-4342 PYSEC-2026-4343 PYSEC-2026-4363 CVE-2026-112390 CVE-2026-112391 CVE-2026-112393 CVE-2026-112395 CVE-2026-112399 CVE-2026-112400 CVE-2026-112401 CVE-2026-112404 CVE-2026-112406 CVE-2026-112891 CVE-2026-112892 CVE-2026-112893 CVE-2026-112894 CVE-2026-112895 CVE-2026-112897 CVE-2026-112899 CVE-2026-112900 CVE-2026-96638 CVE-2026-96640 CVE-2026-96778 CVE-2026-128066 CVE-2026-128067 GHSA-78g4-xqwv-q3g8`

**B. Trivy, backend image, Python (31)**
`CVE-2026-112390 CVE-2026-112392 CVE-2026-112393 CVE-2026-112397 CVE-2026-112398 CVE-2026-112399 CVE-2026-112400 CVE-2026-112402 CVE-2026-112403 CVE-2026-112404 CVE-2026-112405 CVE-2026-112406 CVE-2026-112892 CVE-2026-112893 CVE-2026-112894 CVE-2026-112895 CVE-2026-112896 CVE-2026-112897 CVE-2026-112900 CVE-2026-112902 CVE-2026-128067 CVE-2026-23949 CVE-2026-24049 CVE-2026-96637 CVE-2026-96639 CVE-2026-96640 CVE-2026-96642 CVE-2026-96643 CVE-2026-96644 CVE-2026-96778 GHSA-78g4-xqwv-q3g8`
(CVE-2026-23949 = `jaraco.context`, CVE-2026-24049 = `wheel`, the rest Pillow.)

**C. Trivy, frontend image, Alpine 3.21.3 (54 distinct)**
`CVE-2025-15467 CVE-2025-32414 CVE-2025-32415 CVE-2025-49794 CVE-2025-49795 CVE-2025-49796 CVE-2025-59375 CVE-2025-64720 CVE-2025-65018 CVE-2025-66293 CVE-2025-69421 CVE-2026-103111 CVE-2026-107891 CVE-2026-111497 CVE-2026-113351 CVE-2026-115506 CVE-2026-117610 CVE-2026-118370 CVE-2026-125350 CVE-2026-22184 CVE-2026-22695 CVE-2026-22801 CVE-2026-25210 CVE-2026-25646 CVE-2026-27135 CVE-2026-28387 CVE-2026-28388 CVE-2026-28389 CVE-2026-28390 CVE-2026-31789 CVE-2026-33630 CVE-2026-40200 CVE-2026-45186 CVE-2026-45447 CVE-2026-4775 CVE-2026-5773 CVE-2026-6276 CVE-2026-66046 CVE-2026-6732 CVE-2026-76641 CVE-2026-76956 CVE-2026-76957 CVE-2026-77214 CVE-2026-8286 CVE-2026-84782 CVE-2026-85091 CVE-2026-86145 CVE-2026-87636 CVE-2026-89157 CVE-2026-89161 CVE-2026-8927 CVE-2026-92392 CVE-2026-93990 CVE-2026-9947`

If the slice's own CI run reports another fixable HIGH or CRITICAL ID that is not listed (the scanner database moves daily), the builder adds it to the matching file with a reason and the same review date, and names it in the PR description.
