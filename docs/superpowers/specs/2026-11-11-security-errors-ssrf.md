# Security fixes: API error handlers, `check-postgres` password, CGNAT SSRF gap, reindex SSRF guard

## Intent

A deep code review found four related security problems. All four were checked on `main` bc0974d by
reading and running the code. All four reproduce, so none is dropped. The implementing work is
**risk:high** (security, secrets in logs) and is split into two PRs (see Decided).

## Evidence (reproduced on `main` bc0974d)

1. **API-3, the global handlers hide server bugs and echo input.** `backend/arp/api/main.py`
   (`runtime_error_handler`, `value_error_handler`) turn every `RuntimeError` into 503 and every
   `ValueError` into 400, body `{"detail": str(exc)}`, with no logging. pydantic's `ValidationError` is a
   `ValueError`. Reproduced: a route that runs `M(n="secret-input")` (`M` has `n: int`) returns
   `400 {"detail":"1 validation error for M\nn\n  Input should be a valid integer ... input_value='secret-input' ..."}`
   and writes nothing to the log. So a server-side model bug looks like a client error, echoes the input, and
   leaves no trace. The same handler is what makes `UnsafeURLError` (a `ValueError`) a 400 for
   `GET /api/taxonomies/sources/inspect` (`fetch_source_original` deliberately lets it propagate; its comment
   and `taxonomies.py` rely on that). `build_llm_client` (`backend/arp/llm/factory.py`) raises a bare
   `RuntimeError` for a missing Anthropic or Gemini key, and `auth.py` raises `RuntimeError` for a bad users
   file; both depend on the 503. 32 domain classes subclass `ValueError` or `RuntimeError` and
   today map to 400 or 503 only through these handlers. Bare `raise ValueError` also sits in routers
   (`review_endpoints.py` `submit_review`, three sites; `signals.py` `_run_upload`, two sites).
   `UnsafeIdentifierError` (`arp/storage/safe_path.py`) and `UniverseRejected` (`arp/universe.py`) already exist.
2. **CLI-5, `check-postgres` prints the password.** `backend/arp/cli/db.py` `db_check_postgres` prints
   `f"Postgres schema at {settings.postgres_dsn}:"`. `init-postgres` already uses
   `make_url(...).render_as_string(hide_password=True)`. CI logs and deploy gates run this command.
3. **CLI-8, carrier-grade NAT is not blocked.** `backend/arp/net_safety.py` `_is_disallowed_ip` returns False
   for `100.64.0.1`, `100.100.100.200` (an Alibaba Cloud metadata address), `100.127.255.255` and
   `::ffff:100.64.0.1`. It returns True for `::ffff:127.0.0.1`, `192.0.0.8`, `169.254.169.254`, `10.0.0.1`,
   `64:ff9b::a00:1`. Separately `assert_safe_fetch_target` resolves the name and httpx resolves it again
   (DNS rebinding).
4. **CLI-4, `reindex object-store` has no SSRF guard.** `arp db reindex object-store` calls
   `httpx.get(doc_ref.source_url, headers={"User-Agent": settings.edgar_user_agent}, follow_redirects=True)`.
   `net_safety.py` says every fetch of a URL the app did not hardcode must use the guard. The command also
   sends the EDGAR User-Agent (which carries a contact address) to any host, and reads any `local_path` stored
   in the database, wherever it points.

## Goals

- A server fault returns a generic 500 with a request id and is logged with its traceback. It never echoes
  the exception text or the input.
- 400 and 503 are produced only by dedicated exception classes, not by "any `ValueError`/`RuntimeError`".
- `check-postgres` output contains no password.
- `100.64.0.0/10` is disallowed in both IPv4 and IPv4-mapped IPv6 form.
- `reindex object-store` never sends a request to an unsafe URL, never sends the EDGAR User-Agent to a
  non-SEC host, and reads only files under `settings.documents_dir`.
- AC-1 to AC-55 pass.

## Non-goals

- Pinning the resolved IP in the HTTP transport. Owner decision: not now, documented instead (see Decided).
- Changing the `UnsafeURLError` messages, any `HTTPException` use, or the per-router handlers that already
  exist (for example the `Run failed: RuntimeError` 500 in `signals.py`).
- Editing `.claude/` or `.github/`. Never printing or logging a real credential in tests or logs; tests use
  the fake password `s3cr3t-pw`.

## Anti-goals

- A domain error that is a client error today (for example `UniverseRejected`, `ProjectError`) silently
  becoming a 500 because it was missed. AC-55 pins the status of every such class.
- A new message that echoes the input of a server fault.

## Constraints

- Backend only. No request or response model changes, so no OpenAPI or `gen:api` run is needed.
- Add to the `net_safety.py` module docstring that DNS rebinding (resolve, then connect) is not closed and that
  deployments should run behind an egress proxy or firewall. A comment, not an acceptance row.
- The two PRs are independent: PR 2 must not need PR 1.
- Existing tests are not edited. If one asserts today's behaviour for a bare `ValueError`/`RuntimeError`,
  list it in the PR for the owner instead of changing it.

## Approaches

1. **Marker bases + generic 500 (chosen by the owner).** `ClientInputError(ValueError)` maps to 400,
   `NotConfigured(RuntimeError)` maps to 503, a catch-all `Exception` handler logs and returns 500. Existing
   domain classes inherit the right base. Cost: a survey of raise sites; benefit: nothing is classified by
   accident.
2. Keep 400 for every `ValueError`, only special-case pydantic. Smaller diff, leaves any bare `ValueError`
   message leaking. Rejected by the owner.
3. Logging only. Fixes nothing but the missing trace. Rejected by the owner.

For rebinding: accept and document (chosen) versus a pinned-IP transport touching every fetch site (a
separate follow-up if the app ever runs without an egress proxy).
For `reindex` on an unsafe URL: record the document as failed and carry on (chosen) versus abort.

## Decided (owner, this session)

- **Error taxonomy.** `ClientInputError(ValueError)` is 400 and `NotConfigured(RuntimeError)` is 503, both
  with body `{"detail": str(exc)}` exactly as today. Everything else is logged and answered with
  `500 {"detail":"Internal error","request_id":"<32 hex characters>"}`. A pydantic `ValidationError` raised
  inside a handler is a 500 like any other. Request-body validation (`RequestValidationError`) stays 422, but
  each item in `detail` carries only `type`, `loc` and `msg` (no `input`, `ctx`, `url`).
- **Rebinding.** Accept and document in `net_safety.py`; `100.64.0.0/10` is blocked regardless.
- **Reindex on an unsafe URL.** The document counts as failed, the run carries on, exit code unchanged.
- **Split.** PR 1: CLI-5, CLI-8, CLI-4 (AC-1 to AC-31). PR 2: API-3 (AC-32 to AC-55). Both `risk:high`; the
  owner merges them on GitHub.

## Builder's calls (not asked; the owner may overrule at approval)

- Names and location: `ClientInputError` and `NotConfigured` in a new `backend/arp/errors.py`;
  `UnsafeURLError`, `UnsafeIdentifierError`, `UniverseRejected` and the other 400-today classes inherit
  `ClientInputError` (still `ValueError` subclasses, so existing `except ValueError` keeps working);
  `OpenSearchNotConfigured`, `RefreshDisabledError`, `BrowserUnavailable` and the missing-key and users-file
  errors inherit `NotConfigured` (still `RuntimeError` subclasses). Other 503-today classes (for example
  `RunBusy`) keep 503 through an explicit handler or base; AC-55 pins them.
- The request id is `uuid4().hex`, put in the body and in the log message; no response header.
- Generic UA for non-SEC hosts is `settings.discovery_user_agent`. "SEC host" means `sec.gov` or a subdomain
  of it, matched on the parsed hostname (`www.sec.gov.evil.example` is not SEC).
- `reindex` reads a `local_path` only if its resolved path (symlinks followed) is inside
  `settings.documents_dir.resolve()`. Otherwise the local file is treated as absent: the document falls back
  to `source_url`, or counts as skipped when there is none. Downloader writes under `documents_dir`, so
  normal rows are unaffected.
- The `reindex` guard checks the first URL and every redirect hop (a sync `httpx.Client` request hook; the User-Agent is chosen per hop calling
  `assert_safe_fetch_target`; the existing hook is async and cannot be used with a sync client).
- Surveying bare `raise ValueError`/`raise RuntimeError` under `backend/arp/api`: only the five sites named
  above are converted here (to `ClientInputError`). Other sites are in pydantic validators (422) or are caught
  in their router. The builder greps once more and lists any other reachable site in the PR.

## Acceptance

`HOLDOUT_TOKEN` status is not known to the spec author. The `holdout` rows are AC-15 and AC-47 (they need the
running API). Every other row is `unit` until `HOLDOUT_TOKEN` is set; then the owner may move AC-4, AC-6, AC-8,
AC-13, AC-20, AC-24, AC-25 and AC-39 to AC-45 to `holdout`. Until then each PR lists its `unit` rows as owed.
AC-15 and AC-47 send the e2e stack's test token as `e2e_stack.sh` configures it; if the endpoint needs none
there, none is sent.

Fixtures. Password: the fake `s3cr3t-pw` only. CLI rows use `CliRunner` for `arp db ...` with `get_settings`
patched; "output" is stdout and stderr together. check-postgres rows patch `arp.storage.postgres_schema.schema_report` to return a dict with `vector_extension` True,
`applied_steps` `[]`, `missing_tables`/`missing_columns`/`pending_steps`/`drift` `[]`, `unmatched_company_rows` `{}`
and `current` True ("current") or False ("NOT current"). Net rows patch `socket.getaddrinfo` (no real network), and
`<resolved>` is exactly the string the patched `getaddrinfo` returned as the address (tests return `::ffff:100.64.0.1`
as written);
`assert_safe_fetch_target("http://<host>/")` is the observable entry point, with `<host>` a literal IP (as
`[::ffff:100.64.0.1]` for mapped forms) so `<host>` in the message is that literal. Reindex rows: a fake content
store (`list_all_documents` yields the listed docs; stored URIs are read back from it), `upload_document`
patched to store `(content_key, data)` in a dict, `socket.getaddrinfo` patched (`sec.gov`, `www.sec.gov`, `example.org`,
`www.sec.gov.evil.example` -> `93.184.216.34`; `internal.test` -> `10.0.0.5`), `httpx.HTTPTransport.handle_request`
patched to record requests and answer from a table. Settings: `object_store_endpoint_url="http://store.test"`,
`edgar_user_agent="EDGAR Test test@example.invalid"`,
`discovery_user_agent="ARP-DiscoveryBot/0.1 (+research use; respects robots.txt)"`, `documents_dir` a temp dir.
"Summary line" is stdout's last line, `Object-store backfill complete: uploaded=U skipped=S failed=F.`.
API rows use `TestClient(app, raise_server_exceptions=False)` with a temporary route on `app` that raises the
named exception, authorization satisfied as existing API tests do. "ERROR record" means a log record at level
ERROR with `exc_info` on logger `arp.api.main`. `RID` is the body's `request_id`.

### PR 1: `check-postgres`, CGNAT, reindex

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `postgres_dsn="postgresql+psycopg://arp:s3cr3t-pw@db.example:5432/arp"`; report current | `arp db check-postgres` | exit code 0 | unit |
| AC-2 | same | same | first output line is exactly `Postgres schema at postgresql+psycopg://arp:***@db.example:5432/arp:` | unit |
| AC-3 | same; report NOT current | same | exit code 1; output contains `NOT current -- run `arp db init-postgres` to apply what's missing.` | unit |
| AC-4 | the AC-1 and AC-3 runs | read the whole output | `s3cr3t-pw` appears nowhere | unit |
| AC-5 | `postgres_dsn="postgresql+psycopg://arp@db.example/arp"`; report current | `arp db check-postgres` | exit code 0; first line exactly `Postgres schema at postgresql+psycopg://arp@db.example/arp:` | unit |
| AC-6 | `getaddrinfo` returns the literal host itself | `assert_safe_fetch_target` with `100.64.0.0`, `100.64.0.1`, `100.100.100.200`, `100.127.255.255`, `[::ffff:100.64.0.1]`, `[::ffff:100.100.100.200]` | each raises `UnsafeURLError` with message exactly `<host> resolves to a disallowed address (<host>)` (for the mapped forms `<host>` is the address without brackets, in the form `getaddrinfo` returned) | unit |
| AC-7 | same | `100.63.255.255`, `100.128.0.0`, `[::ffff:100.63.255.255]`, `[::ffff:100.128.0.0]` | none raises | unit |
| AC-8 | `getaddrinfo("mixed.test")` returns `93.184.216.34` and `100.64.0.1` | `assert_safe_fetch_target("http://mixed.test/")` | raises `UnsafeURLError`, message exactly `mixed.test resolves to a disallowed address (100.64.0.1)` | unit |
| AC-9 | one doc, `source_url="http://169.254.169.254/latest/meta-data/"`, no `local_path` | `arp db reindex object-store` | no request is recorded | unit |
| AC-10 | same | same | summary line is exactly `Object-store backfill complete: uploaded=0 skipped=0 failed=1.`; exit code 0 | unit |
| AC-11 | same | same | stderr contains the exact line `Failed to archive d1: 169.254.169.254 resolves to a disallowed address (169.254.169.254)` (`d1` the doc id); nothing was stored | unit |
| AC-12 | one doc `d1` each, run separately: URL `http://100.100.100.200/`; `file:///etc/passwd`; `http://internal.test/a.pdf` | the command | for each: no request recorded; summary line `uploaded=0 skipped=0 failed=1.`; exit code 0; nothing stored; stderr line exactly `Failed to archive d1: 100.100.100.200 resolves to a disallowed address (100.100.100.200)`, `Failed to archive d1: Unsupported URL scheme: 'file'`, `Failed to archive d1: internal.test resolves to a disallowed address (10.0.0.5)` respectively | unit |
| AC-13 | one doc `https://www.sec.gov/a`; the transport answers 302 `Location: http://169.254.169.254/x` | the command | only `www.sec.gov` is requested (one request); nothing stored | unit |
| AC-14 | one doc `https://www.sec.gov/a`; the transport answers 302 `Location: http://169.254.169.254/x` | the command | summary line `uploaded=0 skipped=0 failed=1.`; exit code 0 | unit |
| AC-15 | the API started by `e2e_stack.sh up` | `GET /api/taxonomies/sources/inspect?url=http://100.100.100.200/` (a literal IP, so no DNS) | 400; `detail` is exactly `100.100.100.200 resolves to a disallowed address (100.100.100.200)` | holdout |
| AC-16 | four docs: `d1` `http://169.254.169.254/x`, `d2` `http://100.100.100.200/`, `d3` `file:///etc/passwd`, `d4` `https://www.sec.gov/Archives/x.htm` (answered 200, body `b"PDF"`), `d4.content_key="k4"` | the command | summary line exactly `uploaded=1 skipped=0 failed=3.` | unit |
| AC-17 | same | same | the stored uploads are exactly `{"k4": b"PDF"}`; the fake store has a storage URI for `d4` only | unit |
| AC-18 | one doc `https://www.sec.gov/Archives/x.htm`, 200 | the command | the one recorded request has header `User-Agent` exactly `EDGAR Test test@example.invalid` | unit |
| AC-19 | one doc `https://example.org/a.pdf`, 200 | the command | the request's `User-Agent` is exactly `ARP-DiscoveryBot/0.1 (+research use; respects robots.txt)` | unit |
| AC-20 | docs `https://www.sec.gov.evil.example/a.pdf`, 200 | the command | `User-Agent` is the discovery value, not containing `test@example.invalid` | unit |
| AC-21 | docs `https://sec.gov/a` and `https://SEC.GOV/b`, 200 | the command | both requests carry the EDGAR `User-Agent` | unit |
| AC-22 | doc `https://www.sec.gov/a` answers 302 `Location: https://example.org/b`, then 200 | the command | the second recorded request (to `example.org`) carries the discovery `User-Agent`, not the EDGAR one (the User-Agent is chosen per hop); summary `uploaded=1 skipped=0 failed=0.` (doc has `content_key="k"`, both 200 bodies are `b"x"`) | unit |
| AC-23 | one doc, `local_path` a file inside `documents_dir` (absolute path) holding `b"inside"`, no `source_url`, `content_key="k"` | the command | stored uploads exactly `{"k": b"inside"}`; no request recorded | unit |
| AC-24 | one doc, `local_path` an existing temp file outside `documents_dir` (`b"outside"`), no `source_url` | the command | summary line exactly `uploaded=0 skipped=1 failed=0.`; nothing stored | unit |
| AC-25 | one doc, `local_path` a symlink inside `documents_dir` to the AC-24 file, no `source_url` | the command | summary line exactly `uploaded=0 skipped=1 failed=0.`; nothing stored | unit |
| AC-26a | one doc, `local_path=<documents_dir>/../outside.txt` (exists, `b"outside"`), no `source_url` | the command | summary line exactly `uploaded=0 skipped=1 failed=0.`; nothing stored | unit |
| AC-26 | one doc, `local_path` the AC-24 file, `source_url="https://www.sec.gov/a"` answered 200 `b"url"`, `content_key="k"` | the command | stored uploads exactly `{"k": b"url"}`; summary `uploaded=1 skipped=0 failed=0.` | unit |
| AC-27 | one doc with `storage_uri="s3://b/k"` | the command | summary line exactly `uploaded=0 skipped=1 failed=0.`; no request recorded | unit |
| AC-28 | one doc with neither `local_path` nor `source_url` | the command | summary line exactly `uploaded=0 skipped=1 failed=0.`; no request recorded | unit |
| AC-29 | `object_store_endpoint_url` unset | the command | exit code 1; output `ARP_OBJECT_STORE_ENDPOINT_URL is not set -- nothing to upload.` (as today) | unit |
| AC-30 | `getaddrinfo` returns the literal host | `assert_safe_fetch_target` with `127.0.0.1`, `10.0.0.1`, `172.16.0.1`, `192.168.1.1`, `169.254.169.254`, `192.0.0.8`, `0.0.0.0`, `224.0.0.1`, `[::1]`, `[fe80::1]`, `[::ffff:127.0.0.1]`, `[64:ff9b::a00:1]` | each raises `UnsafeURLError` with message exactly `<host> resolves to a disallowed address (<resolved>)` | unit |
| AC-31 | same | `8.8.8.8`, `1.1.1.1`, `93.184.216.34`, `192.0.0.9`, `[2606:4700::1111]` | none raises | unit |

### PR 2: error handlers

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-32 | route raises `ClientInputError("bad group_by 'x'")` | GET | 400, body exactly `{"detail":"bad group_by 'x'"}` | unit |
| AC-33 | same | GET | no ERROR record | unit |
| AC-34 | route raises `UnsafeIdentifierError("Invalid id: '../x'")` / `UnsafeURLError("Unsupported URL scheme: 'file'")` / `UniverseRejected("bad GICS code '1' for company 'c'")` | GET each | 400, body `{"detail":"<that message>"}` | unit |
| AC-35 | route raises `NotConfigured("ARP_ANTHROPIC_API_KEY is not set.")` | GET | 503, body exactly `{"detail":"ARP_ANTHROPIC_API_KEY is not set."}` | unit |
| AC-36 | route calls `build_llm_client` with `standins_dir=None`, `llm_model="claude-sonnet-4-5"`, `anthropic_api_key=None` | GET | 503; `detail` is exactly the text `build_llm_client` raises on `main` bc0974d: `ARP_ANTHROPIC_API_KEY is not set. Provide an Anthropic API key via environment variable or a .env file before running any agent pipeline.` | unit |
| AC-37 | same with `llm_model="gemini-2.5-pro"`, `gemini_api_key=None` | GET | 503; `detail` exactly `ARP_GEMINI_API_KEY is not set, and the run uses the Gemini model gemini-2.5-pro.` | unit |
| AC-38 | route calls `load_users(Path("users.json"))` on a file with two users with the same `token` | GET | 503; `detail` exactly `Users file users.json has a blank or duplicate token or a duplicate user_id.` | unit |
| AC-39 | route runs `M(n="secret-input")` (`M` pydantic, `n: int`) | GET | status 500; body keys exactly `detail` and `request_id` | unit |
| AC-40 | same | same | `detail == "Internal error"`; `RID` matches `^[0-9a-f]{32}$` | unit |
| AC-41 | same | same | `secret-input` and `validation error` absent from the body | unit |
| AC-42 | same | same | exactly one ERROR record; its message contains `RID`; its exception type is `pydantic_core.ValidationError` | unit |
| AC-43 | same, GET twice | GET twice | two different `RID`s, each in its own ERROR record | unit |
| AC-44 | route raises `RuntimeError("db password=hunter2 down")` | GET | 500, keys and `detail` as AC-39 and AC-40; `hunter2` absent; one ERROR record of type `RuntimeError` | unit |
| AC-45 | route raises `ValueError("leak-45")` | GET | 500, keys and `detail` as AC-39 and AC-40; `leak-45` absent; one ERROR record | unit |
| AC-46 | `POST` route with body model `{n: int}`, body `{"n":"secret-input"}` | POST | 422; `detail` has one item with keys exactly `type`, `loc`, `msg`; `loc == ["body","n"]`; `type == "int_parsing"`; `secret-input` absent from the response | unit |
| AC-47 | the API started by `e2e_stack.sh up` | `GET /api/taxonomies/sources/inspect?url=http://169.254.169.254/latest/meta-data/` | 400; `detail` is exactly `169.254.169.254 resolves to a disallowed address (169.254.169.254)` | holdout |
| AC-48 | route raises `HTTPException(404, "nope")` | GET | 404, body `{"detail":"nope"}`; no ERROR record | unit |
| AC-49 | `signals_router.run_recipe` patched to raise `RuntimeError("secret detail")`; `POST /api/signals/runs` with a valid recipe, prices and no panels (fixture of `test_run_unexpected_failure_is_500_and_logged`) | the request | 500, body `{"detail":"Run failed: RuntimeError"}`, as on `main` | unit |
| AC-50 | `POST /api/themes/runs/r1/review` with `item_key="k"`, `decision="maybe"` | request | 400, `detail` exactly `decision must be one of ['approve', 'edit', 'escalate', 'reject']` | unit |
| AC-51 | the same endpoint, `item_key="held:x"`, `decision="approve"` | request | 400, `detail` exactly `decide this item through the review workbench` | unit |
| AC-52 | the same endpoint, `item_key="k"`, `decision="approve"`, run `r1` whose manifest `run_type` is `extraction` | request | 400, `detail` exactly `decide extraction items through the review workbench` | unit |
| AC-53 | `POST /api/signals/runs` with recipe bytes `b"{}"` | request | 400; `detail` equals `invalid recipe: ` plus each pydantic error as `<loc>: <msg>` joined by `; `, as `main` produces for `Recipe.model_validate_json(b"{}")` (the test records that string literally) | unit |
| AC-54 | `POST /api/signals/runs`, a valid recipe whose `method` is registered but not in `APP_RUNNABLE` (the test names it) | request | 400, `detail` exactly `<method> runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app` | unit |
| AC-55 | each class in the status-quo table, instantiated with the single string `"m"` (all 32 classes take a single message string) | raise from a route, GET | the listed status and body `{"detail":"m"}` | unit |

**Status-quo table for AC-55**, fixed now from `main` bc0974d (all return today the status shown; the owner
reviews the list; a class missing here is a 500 after the change, so the builder also greps every subclass of
`ValueError`/`RuntimeError` under `backend/arp` and adds a row to the owner for any not listed, rather than
deciding):
400: `UniverseRejected`, `UnsafeIdentifierError`, `UnsafeURLError`, `ProjectError`, `ShockError`,
`UnknownMaterial`, `LinkError`, `RecipeError`, `ThemeRunRefused`, `LayerSettingsError`, `NotResumable`,
`PlanScriptError`, `PlanRejected`, `SnapshotInvalid`, `SnapshotSettling`, `WithdrawalError`, `LicenceRefused`,
`BenchmarksError`, `IntakeError`, `MasterRejected`, `RuleBookError`, `ChartDataError`.
503: `OpenSearchNotConfigured`, `RefreshDisabledError`, `BrowserUnavailable`, `RunBusy`,
`PlanNotReplannable`, `PlanNotRunnable`, `StepLimitExceeded`, `SnapshotHashMismatch`, `SnapshotFrozen`,
`ConcurrentPublish`.

Must not change: the 400 and 503 statuses and bodies of every listed domain class (AC-32 to AC-38, AC-55);
HTTP exceptions (AC-48); the per-router 500 in `signals` (AC-49); the `check-postgres` output with no password
(AC-5) and its exit codes (AC-1, AC-3); already blocked and allowed addresses (AC-30, AC-31); the public-URL
reindex path (AC-16 to AC-18, AC-23, AC-26); the missing-endpoint exit (AC-29).

## Follow-ups (not in this change)

- Pin the resolved IP in the HTTP transport (DNS rebinding) if the app runs without an egress proxy.
- Audit the other `except ValueError` and `except Exception` sites under `backend/arp/api` (93 `except`
  clauses on these types) for messages that echo input.
- Whether `openwiki/` needs an update: no behaviour in the wiki changes except API error semantics; mention
  in the PR, do not edit `openwiki/` by hand.
