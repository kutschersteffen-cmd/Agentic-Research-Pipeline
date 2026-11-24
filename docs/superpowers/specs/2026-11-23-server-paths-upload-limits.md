# Server file paths and upload limits

Status: **approved by the owner on 24 Nov 2026** (button in the spec session, after two spec-critic rounds; decisions D1 to D3 as recommended).
Slug: `server-paths-upload-limits`
Risk: this spec PR is `risk:low`. The build is 5 PRs, each `risk:high` (backend security; the owner merges them).
Size: each slice S
Source: bug-list item 3 (M1 = C1.3, M2 = A4 + C1.8) in the Antigravity patch review. Checked against
`origin/main` `eafa683`. The Antigravity patch itself is not applied; it was a hint only.

## Decisions for the owner

Approving this spec accepts all three as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | **A plan may only name a saved universe.** Today a plan's "build universe" step may name any `.csv` or `.json` file the server can reach. An earlier spec approved that on purpose (showcase-themes-fixes AC-118: "an existing file path is still accepted"). It is the same hole as M1, reached through a brief instead of a form. | Close it: saved universes only, in the API, in `arp plan draft` and `arp plan replan`, and when a plan runs (AC-32 to AC-35, AC-58, AC-59, AC-70, AC-71). AC-118 is retired. | Plans keep accepting any file path. AC-32, AC-34, AC-35, AC-58, AC-59, AC-70 and AC-71 are struck, and the risk register row "server paths taken from requests" stays "Partial". |
| D2 | **The size limit for one uploaded file is 100 MB**, the limit the 15 uploads that already have one use (`max_upload_bytes`). The biggest real file in the repo and the demo data is 5.1 MB (a voting record CSV); the biggest deck is 2.0 MB. So nothing real comes near it. | 100 MB, one number for every upload (AC-36 to AC-39) | 25 MB: closer to real files, but then the 15 existing uploads change too, and the number in AC-36 to AC-39 and D3 changes. |
| D3 | **A limit for the whole request, not only for each file.** Without it the server still stores an oversized upload on disk before it looks at the size, and a request without files (JSON) has no limit at all. Recommended: 250 MB for a request that carries files, 20 MB for every other request. One side effect: a table uploaded for a report slide travels back to the server inside the report request, so a table above roughly 15 MB can no longer go on a slide. | Yes, 250 MB and 20 MB (AC-44 to AC-50, AC-61) | No whole-request limit: AC-44 to AC-50, AC-61 and slice 4 are struck, and the register row "request size limits" stays "Partial". Or other numbers: they replace 250 and 20 in those rows. |

## Why

Two findings from the review of the Antigravity patch, both confirmed on `main`:

- **M1.** Twelve run-start requests take a `universe_path` and hand it to the file loader as it is. A signed-in
  user can make the server read any `.csv` or `.json` file it can reach, and can tell whether a file exists:
  a missing file answers 500, an existing one does not. Three routes already do it right (Argus, the universe
  workbench, "save from companies"): they accept only a file inside `runs/_universes`.
- **M2.** Fourteen upload reads in five routers (twelve in four routers, plus Strategy Replication's two) have no size limit (`await file.read()`), so one request can use
  up the server's memory. Fifteen other uploads already stop at `max_upload_bytes` with a 413.

While checking callers I found the same two problems in more places than the brief lists. They are in this
spec because the risk register rows cannot be closed without them:

- The same unchecked file path in five more request fields: the two schedule forms (`universe_path`), ETF
  overlap (`funds`), the revenue catalogue (`catalogue_path`, `revenue_catalogue_path`), a plan's universe
  `source`, and the Strategy Replication backtest (`prices_ref`, `characteristics_refs`).
- Signals reads three kinds of file parts without a limit, not one (`recipe`, `prices` and each `panel_<name>`).
- Requests without files have no size limit, and a per-file limit is only checked after the whole request has
  been received and stored.

## What the user can do afterwards that they cannot do today

Nothing new on the screens. What changes is what a signed-in user, or a script with their token, can no longer do:

- Make the server read a file outside the folders the app's own uploads go to.
- Find out whether a file exists on the server.
- Take the server down with one oversized upload or one oversized request.

And one thing gets better for a normal user: a universe file that cannot be read gives a sentence, not
"Internal error".

## Three versions

1. Safe (the brief as written): the 12 `universe_path` reads accept saved universes only; the unbounded upload
   reads stop at 100 MB.
2. Strong: plus every other request field that names a server file, plus every file part of every upload
   (Signals' recipe and prices, a template's fonts).
3. Most ambitious, specified here: plus a limit for the whole request that is checked before the body is stored
   or parsed, and two guard tests that fail when a later change adds an unchecked path field or an uncapped
   upload read.

The next step up is storing uploads without holding them in memory, and a quota per user. It needs the SSO
decision (who is "a user") and a decision on how much disk each user may fill.

## What exists today

Terms used in the rows:

- **The universes folder**: `<runs_dir>/_universes` (`settings.runs_dir`, default `<repo>/runs`). All three
  universe uploads write there: `POST /api/universe/upload` saves `<name>`, `POST /api/universe/raw-upload`
  saves `_raw_<name>`, `POST /api/universe/from-holdings` saves `_raw_holdings_<name>` and a `…_universe.json`.
  Each returns the saved file's path as `path`.
- **A saved universe file**: a path that, after symlinks and `..` are resolved (`Path.resolve()`; a relative
  path is resolved against the server's working directory, as today), is a regular file inside the universes
  folder at any depth.
- **U**: the `path` returned by uploading a valid universe (`company_id,name` header and one row) to
  `POST /api/universe/upload`. **UDIR**: U's folder.
- **OUTSIDE**: an existing, valid universe CSV in a temporary folder outside the universes folder.
  **MISSING**: `/nonexistent-arp/x.csv`. **MISSING-INSIDE**: `UDIR/nope-<random>.csv`.
- The 400 text already used by the three routes that check: `Universe file must be a saved universe.`

The 12 unchecked `universe_path` reads. "Body" is what a request needs besides `universe_path` to reach the
universe step on `main` today (all other fields left out):

| # | Route | Body | Group |
|---|---|---|---|
| 1 | `POST /api/themes/runs` | `{"taxonomy_id": "none"}` | A |
| 2 | `POST /api/voting/runs` | `{}` | A |
| 3 | `POST /api/tnfd/runs` | `{"as_of": "FY2025"}` | A |
| 4 | `POST /api/discovery/runs` | `{}` | A |
| 5 | `POST /api/emerging-themes/runs` | `{}` | A |
| 6 | `POST /api/extraction/runs` | `{"datapoint_schema": {"name": "x"}}` | A |
| 7 | `POST /api/extraction/start` | `{"profile": "tnfd", "as_of": "FY2025"}` | A |
| 8 | `POST /api/identity/runs` | `{}` | A |
| 9 | `POST /api/financials/runs` | `{}` | A |
| 10 | `POST /api/taxonomies` | `{"name": "x"}` | A |
| 11 | `POST /api/xbrl/runs` | `{}` | B |
| 12 | `POST /api/documents/readiness` | `{}` | C |

Today on all 12: OUTSIDE is read; MISSING answers 500 on Group A, 400 `Could not read the universe file.` on
B and 400 `Universe file not found: <the path>` on C. A file that exists but is not a universe: Group A answers
400 with the loader's sentence when it has one (`The file is not valid JSON.`, `Row 3: name is required.`,
`Unsupported file type ".txt". Upload a .csv or .json file.`) and 500 otherwise (a JSON object instead of a
list, a CSV that is not UTF-8); B answers 400 `Could not read the universe file.` for all of them; C answers
400 `Universe file could not be read: <reason>` or 500.

Other request fields that name a server file:

| Field | Route | Today |
|---|---|---|
| `universe_path` | `PUT /api/emerging-themes/schedule`, `PUT /api/discovery/schedule` | stored unchecked; the scheduler reads it later. The Emerging Themes page has a free-text box for it. |
| `funds` (name → path) | `POST /api/etf-overlap` | any path is read; missing → 404 `Holdings file not found: <the path>`. The UI sends paths from `raw-upload`. |
| `catalogue_path` | `POST /api/revenue-catalogue/suggest-mapping` | any path is read; missing → 404 `Catalogue file not found: <the path>`, after the taxonomy lookup. The UI sends a path from `raw-upload`. |
| `revenue_catalogue_path` | `POST /api/themes/runs` | any path is read, after the taxonomy lookup. |
| `source` of a `universe_build` step | drafting: `POST /api/plans`, `POST /api/plans/{id}/replan`, the agent route that drafts a plan (`routers/agent.py`), `arp plan draft`, `arp plan replan`; editing: `PUT /api/plans/{id}`; running: the plan worker | The three API drafting routes check with `universe_source_errors` (`arp/universe.py`): a saved universe's file name, or any existing `.csv`/`.json` path. The two CLI commands and `PUT` do not check at all. The worker resolves with `universe_source_path`: a saved universe's file name, else the string as a path. |
| `prices_ref`, `characteristics_refs` | `POST /api/replication/specs/{spec_run_id}/backtest` | any path is read. The UI sends the `ref` the two replication uploads return, which is inside that spec run's folder (`run_store.run_dir(spec_run_id)`). |

Already checked, not changed: `universe_path` on `POST /api/universe/workbench` and
`POST /api/argus/flows/{id}/companies`, `base_path` on `POST /api/universe/from-companies`, `files` on the
authority taxonomy run (inside `documents_dir`). The workbench has no "is a file" test: a folder inside the
universes folder answers `Could not read the universe file.` there, and keeps that answer if it switches to the
helper.

Callers checked (the brief asked for this before any row): the UI sends only paths that an upload or the saved
universe list returned, all inside the universes folder (`UniversePicker`, `XbrlFetchArea`, `ThemeBuilder`,
`TaxonomyLibrary`, `ArgusFlow`, `EmergingThemesDetector`); the one exception is the schedule's free-text box.
The CLI reads universe files itself and does not go through these routes. The browser tests in
`backend/tests/e2e` post no path outside the universes folder. Backend unit tests that post a temp-folder path
to routes 1 to 12 (`tests/test_api_xbrl.py`, `tests/test_document_readiness.py`, `tests/test_extraction_start.py`
and others) have to move their file into the test's universes folder; the builder lists each such change in the
PR. The `holdout` repo could not be checked from this session: see "For the test writer".

The 12 unbounded upload reads:

| # | Route | File part (with the file name to send; Signals ignores a part without one) | Other parts a request needs |
|---|---|---|---|
| 1 | `POST /api/universe/upload` | `file` (`big.csv`) | |
| 2 | `POST /api/universe/raw-upload` | `file` (`big.csv`) | |
| 3 | `POST /api/universe/from-holdings` | `file` (`big.csv`) | |
| 4 | `POST /api/decision/datasets` | `file` (`big.csv`) | |
| 5 | `POST /api/decision/mechanisms/from-indicators` | `file` (`big.csv`) | form field `name=x` |
| 6 | `POST /api/reports/templates` | `file` (`big.pptx`) | |
| 7 | `POST /api/reports/templates` | one `fonts` part (`Big-400.ttf`) | `file`: any small `.pptx`-named file |
| 8 | `POST /api/reports/datasets/upload` | `file` (`big.csv`) | |
| 9 | `POST /api/signals/runs` | `recipe` (`recipe.yaml`) | `prices` (`prices.csv`): 1 byte |
| 10 | `POST /api/signals/runs` | `prices` (`prices.csv`) | `recipe` (`recipe.yaml`): 1 byte |
| 11 | `POST /api/signals/runs` | `panel_a` (`panel_a.csv`) | `recipe` and `prices` as above: 1 byte each |
| 12 | `POST /api/reports/images` | `file` (`big.png`) | has its own limit of 20 × 1024 × 1024 bytes, checked after the whole file is in memory |

The two Strategy Replication uploads are the 13th and 14th; item 1 of the bug list caps them (see Non-goals).

The existing limit: `max_upload_bytes` (default 100,000,000; env `ARP_MAX_UPLOAD_BYTES`), answer 413
`{"detail": "File is larger than the 100 MB upload limit."}` where 100 is `max_upload_bytes // 1_000_000`.
The app has no limit on a request's total size (`backend/arp/api/main.py` has no such middleware).

## Design

### 1. One rule for a file path in a request

One helper (the builder picks its home; `arp/storage/safe_path.py` holds the related ones) answers "is this
path a regular file inside this folder, after resolving it?". It never raises for a bad path (NUL byte, too
long, a loop of symlinks): that is a "no". Every route below uses it, and the three routes that already check
by hand may switch to it as long as their answers stay as they are.

**`universe_path`, routes 1 to 12.** When `companies` is empty or absent and `universe_path` is a non-empty
string that is not a saved universe file, the answer is 400 `{"detail": "Universe file must be a saved universe."}`.
The answer is the same bytes whether the file exists outside, does not exist, is a folder, or is a symlink that
leaves the folder. Nothing is read from a path that fails the check. The check sits where the file is loaded
today, so the "Body" column above still reaches it.

A saved universe file that cannot be loaded:

- Group A: 400 with the loader's own sentence when the loader raises `UniverseRejected`, as today; any other
  failure is 400 `{"detail": "Could not read the universe file."}` (500 today).
- Group B (XBRL): unchanged, 400 `Could not read the universe file.` for every failure.
- Group C (readiness): unchanged where it answers 400 today (`Universe file could not be read: <reason>`); a
  failure that is a 500 today becomes 400 `Could not read the universe file.`

No answer contains the submitted path or the universes folder's path; the server log may. The loader's own
sentences stay as they are, also where they quote a row's content (`Row 3: name is required.`). On readiness a
CSV that is not UTF-8 keeps its current 400 (`Universe file could not be read: <codec message>`).

**The two schedules.** `PUT /api/emerging-themes/schedule` and `PUT /api/discovery/schedule` accept a
`universe_path` that is null, an empty string, a saved universe file, or the same string the schedule holds
right now (what `GET` on the same route returns; this keeps a path the operator set through
`ARP_EMERGING_THEMES_SCHEDULE_UNIVERSE_PATH` or `ARP_DISCOVERY_SCHEDULE_UNIVERSE_PATH` working when the form is
saved again). Anything else: 400 `Universe file must be a saved universe.`, and nothing is saved. On Emerging
Themes the interval check (422) still comes first. The scheduler itself is not changed.

**ETF overlap.** After the "at least two funds" check, every value of `funds` must be a regular file inside the
universes folder; else 400 `{"detail": "Holdings file must be an uploaded file."}` (404 with the path today).
An empty string is such a value and gets the same 400. All values are checked before any file is read.

**Revenue catalogue.** `catalogue_path` on `suggest-mapping` and `revenue_catalogue_path` on
`POST /api/themes/runs` must be a regular file inside the universes folder; else 400
`{"detail": "Catalogue file must be an uploaded file."}`. On `suggest-mapping` this check comes before the
taxonomy lookup. On `themes/runs` it comes right after the universe step: before the taxonomy lookup and before
the "Provide both revenue_catalogue_path and catalogue_mapping together" check. An empty or absent
`revenue_catalogue_path` is "no catalogue", as today; an empty `catalogue_path` on `suggest-mapping` gets the 400.

**Plans (D1).** A `universe_build` step's `source` is valid when it is the file name of a saved universe (as
`saved_universes()` lists them), or a path that is a saved universe file. Everything else gets the existing
sentence from `not_saved_message()` (`"<source>" is not a saved universe. Save one on …`). This holds everywhere a
plan's script comes in or runs:

- the three API drafting routes (`POST /api/plans`, `POST /api/plans/{id}/replan`, the agent route): 422, as
  today for a file that does not exist;
- `PUT /api/plans/{id}` (a hand-edited script), which has no source check today: 422 with that sentence, and
  the plan is not changed;
- `POST /api/plan-templates/{name}/instantiate`, which writes its `source` into the script with no check
  today: 422 with that sentence, and no plan is created;
- `arp plan draft` and `arp plan replan`, which have no source check today: the builder adds it; they exit
  non-zero and print the sentence;
- the plan worker when it runs the step: the step fails with that sentence and the file is not read. The
  worker's order stays as it is (the taxonomy lookup comes before the source).

**Strategy Replication backtest.** `prices_ref` and every value of `characteristics_refs` must be a regular
file inside `run_store.run_dir(spec_run_id)`; else (an empty string too) 400
`{"detail": "Dataset must be an uploaded file."}`. The
check comes after the existing 404 (unknown spec run) and 403 (spec not approved). What a path inside that
folder that does not load answers is item 1's subject and is not changed here.

### 2. One capped read for uploads

One helper (`read_capped`; the builder picks its home) reads at most `max_upload_bytes + 1` bytes of a file
part and raises 413 `File is larger than the <N> MB upload limit.` (`N = max_upload_bytes // 1_000_000`) when
it got more than `max_upload_bytes`. Reads 1 to 11 in the table use it. The 15 uploads that already do this by
hand may switch to it; their answers stay the same.

- The size check comes before anything looks at a part's content. A check of the file name or type (unsafe
  name, not `.pptx`, a font not named `<Family>-<weight>.ttf`, a missing Signals part) may still come first.
- On Signals and on a template with fonts, every file part is checked before any part is parsed.
- After a 413 nothing from that request is left on disk: no saved file, no `.part` file.
- `POST /api/reports/images` (read 12) keeps its own limit and sentence
  (413 `image '<name>' is larger than 20 MB`), but reads at most 20 × 1024 × 1024 + 1 bytes to find that out.

### 3. A limit for the whole request (D3)

Two new settings: `max_request_bytes` (default 250,000,000, env `ARP_MAX_REQUEST_BYTES`) for a request whose
`Content-Type` starts with `multipart/form-data`, and `max_body_bytes` (default 20,000,000, env
`ARP_MAX_BODY_BYTES`) for every other request. It covers every route of the app.

- A request whose `Content-Length` is above its limit is answered 413 before any of its body is read.
- A request without `Content-Length` is answered 413 once more bytes than its limit have arrived.
- The answer is `{"detail": "Request is larger than the <N> MB limit."}` with `N = limit // 1_000_000`.
- A request at or under its limit is not touched.
- The check runs before sign-in and before anything reads the body, and inside the CORS layer, so the browser
  UI can read the 413 like any other answer.
- Accepted gap: the limit is picked from the `Content-Type` header, so a request to a JSON route that claims to
  be `multipart/form-data` is held to 250 MB, not 20 MB. It is still bounded.

The per-file limit still gives its own sentence: a 100,000,001-byte file in a request under 250 MB gets
`File is larger than the 100 MB upload limit.`

### 4. Two guard tests

So the next upload or path field cannot quietly skip the rules, two tests in `backend/tests/`:

- **Upload guard:** fails, naming file and line, when a file under `backend/arp/api/routers/` holds a call
  `.read()` with no argument, whatever it is called on. Its allow-list holds exactly the two Strategy
  Replication upload lines until they are capped (by item 1, or by slice 3 if item 1 merged first); whoever caps
  them removes the entries.
- **Path guard:** reads `app.openapi()` (the running app's document, not the committed
  `frontend/src/api/openapi.json`) and collects every pair (method and route, property) where a
  request-body property, at any depth, is named `path`, `funds`, `files`, or ends in `_path`, `_ref` or `_refs`.
  It fails when that set of pairs differs from a list written in the test. Each entry says either which folder
  the route confines the value to, or `not a server path: <reason>` (for example `Citation.table_ref`,
  `ReportRequest.run_refs`, the uploaded `files` of `POST /api/rfp/library/import`). Slice 2 lists the two
  backtest fields as `unconfined until slice 5`; slice 5 changes those two entries to the spec run's folder.
  The name rule does not match a plan's `source`; the list names the pair
  (`POST /api/plan-templates/{name}/instantiate`, `source`) by hand.

### Risk register

The register is the Claude Doc "Agentic Research Platform (ARP): Architecture and Risk Review", section 10, not
a file in this repo. Two rows are added there with this spec, both "Planned" and pointing at this spec:
"Server paths taken from requests" and "Request size limits". The dispatcher sets them to "Addressed" when the
last slice has merged ("Partial" if D1 or D3 is declined).

## Defaults I chose (not owner decisions)

- The universes folder is the one allowed folder for universes, holdings exports and catalogues, because all
  three arrive through the same uploads today. No new folders.
- A bare file name is not a `universe_path`. Only plans accept a saved universe's file name, as today.
- When `companies` is given, `universe_path` is ignored and not checked, as today.
- Wrong path answers are 400 everywhere, also where a missing file was a 404 (`etf-overlap`, `suggest-mapping`).
  A 404 would say "this file does not exist", which is the hint this spec removes.
- No UI change. The Emerging Themes schedule box keeps its free text; a wrong path now shows the 400 sentence
  when the form is saved, where today it failed silently when the schedule fired.
- The limits count bytes as sent. A limit is a setting, so the operator can raise it without a code change.
- No startup check that `max_request_bytes` is larger than `max_upload_bytes`.
- A stored schedule or plan that already holds an outside path is not rewritten. The schedule keeps working
  (see "the same string"); the plan fails at its universe step with the not-saved sentence.

## Non-goals

- The two Strategy Replication uploads' size limit (item 1). If item 1 has merged when slice 3 starts, slice 3
  may switch them to `read_capped` without changing their answers; otherwise it leaves them alone.
- `documents/upload` without a file (item 2), and every other bug-list item.
- Per-user quotas, cleaning up old uploads, virus scanning, checking a file's type by its content.
- The nginx or any proxy in front of the app.
- Paths the operator sets in settings or passes to the CLI as a universe file (`--universe`). They are trusted.
  A plan's `source` is not one of these (see Plans).
- Changing the sentences of the 15 uploads and 3 routes that already check.

## Slices

One PR each, in this order, each `risk:high` with `Spec: server-paths-upload-limits` and a `Rows:` line.
Slice 2 starts after slice 1 has merged (it uses the path helper). Slices 3 and 4 depend on nothing here and may
run beside slice 1.

| Slice | What | Rows | Size |
|---|---|---|---|
| 1 | The path helper; `universe_path` on routes 1 to 12 and the two schedules | AC-1 to AC-25, AC-62, AC-63, AC-66, AC-69 | S |
| 2 | ETF overlap, revenue catalogue, plans; the path guard test | AC-26 to AC-35, AC-57 to AC-60, AC-64, AC-67, AC-68, AC-70 to AC-73 | S |
| 3 | `read_capped` on reads 1 to 11, the image read; the upload guard test | AC-36 to AC-43 | S |
| 4 | The whole-request limit | AC-44 to AC-50, AC-61 | S |
| 5 | Strategy Replication backtest paths. Starts only after bug-list item 1 has merged, and merges `origin/main` first. Adds its two fields to the path guard's list. | AC-53 to AC-56, AC-65, AC-74 | S |

AC-51 and AC-52 were not used.

## For the test writer

- Hidden tests run against the started app with default settings, on the same machine, so a test can create
  OUTSIDE in a temp folder and gets U from the upload route. Use a random file name per test:
  `POST /api/universe/upload` overwrites a file of the same name.
- This session could not see the `holdout` repo. Before writing, search `regression/` for tests that post a
  `universe_path`, `funds`, `catalogue_path` or `revenue_catalogue_path` outside the universes folder, or that
  expect `Universe file not found:`, `Holdings file not found:`, `Catalogue file not found:` or a 500 from
  routes 1 to 12. Those expectations are superseded by this spec; change them in the same holdout PR and say
  which.
- Route 5 asks for the model client before the route body runs. In the hidden-test run that is the stand-in
  client (`ARP_STANDINS_DIR` is set), so it reaches the universe step; no model answer is needed.
- AC-36 sends eleven bodies of 100,000,001 bytes over loopback. Build each once and stream it.

## Supersedes

- `showcase-themes-fixes` AC-118 ("an existing file path is still accepted" as a plan source) is retired by
  D1. It is a `unit` row, so there is no hidden test to retire; the builder changes its unit test and lists it.

## Acceptance

"Routes 1 to 12", "Group A", U, UDIR, OUTSIDE, MISSING and MISSING-INSIDE are defined under "What exists
today". Each route is called with its "Body" plus the named `universe_path`. `SAVED-ONLY` stands for status 400
with the body `{"detail": "Universe file must be a saved universe."}`.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | OUTSIDE exists | each of routes 1 to 12 is called with `universe_path` = OUTSIDE | `SAVED-ONLY` | holdout |
| AC-2 | MISSING does not exist | each of routes 1 to 12 is called with `universe_path` = MISSING | the status and the body are the same bytes as in AC-1 for that route | holdout |
| AC-3 | U was uploaded | each of routes 1 to 12 is called with `universe_path` = MISSING-INSIDE | `SAVED-ONLY` | holdout |
| AC-4 | U was uploaded | each of routes 1 to 12 is called with `universe_path` = UDIR | `SAVED-ONLY` | holdout |
| AC-5 | — | each of routes 1 to 12 is called with `universe_path` = `"a\u0000b"` | `SAVED-ONLY` | holdout |
| AC-6 | U was uploaded | each of routes 1 to 12 is called with `universe_path` = `UDIR/../../../../../../../../etc/passwd` | `SAVED-ONLY` | holdout |
| AC-7 | a symlink `UDIR/link.csv` points at OUTSIDE | each of routes 1 to 12 is called with `universe_path` = that symlink | `SAVED-ONLY` | unit |
| AC-8 | the calls of AC-1, AC-2 and AC-3 | their response bodies are read | none contains the file name of the submitted path, nor the text `_universes` | holdout |
| AC-9 | OUTSIDE-BAD is a file outside the universes folder, named `<random>.json`, with the content `not json` | each of routes 1 to 12 is called with `universe_path` = OUTSIDE-BAD | `SAVED-ONLY` (not the loader's sentence: the file was not read) | holdout |
| AC-10 | U was uploaded | `POST /api/documents/readiness` with `{"universe_path": U}` | status 200 | holdout |
| AC-11 | U was uploaded, named `<name>` | `POST /api/documents/readiness` with `universe_path` = `UDIR/../_universes/<name>` | status 200 | holdout |
| AC-12 | U was uploaded | each of routes 1 to 11 is called with `universe_path` = U, with the run launcher replaced by a recorder | no answer is `SAVED-ONLY` and none has a 5xx status | unit |
| AC-13 | a file with the content `not json` was sent to `POST /api/universe/raw-upload` as `<random>.json`; P is the returned `path` | each Group A route is called with `universe_path` = P | status 400, body `{"detail": "The file is not valid JSON."}` | holdout |
| AC-14 | a file with the content `{"a": 1}` was sent to `raw-upload` as `<random>.json`; P is the returned `path` | each Group A route and `POST /api/documents/readiness` is called with `universe_path` = P | status 400, body `{"detail": "Could not read the universe file."}` | holdout |
| AC-15 | a file with the three bytes `FF FE 00` was sent to `raw-upload` as `<random>.csv`; P is the returned `path` | each Group A route is called with `universe_path` = P | status 400, body `{"detail": "Could not read the universe file."}` | holdout |
| AC-16 | — | each of routes 2 to 9, 11 and 12 is called with its Body only (no `universe_path`, no `companies`), and route 1 with `{"taxonomy_id": "none"}` | status 400, body ``{"detail": "Provide either `companies` or `universe_path`."}`` (must not change) | holdout |
| AC-17 | the P of AC-13 | `POST /api/xbrl/runs` with `{"universe_path": P}` | status 400, body `{"detail": "Could not read the universe file."}` (must not change) | holdout |
| AC-18 | OUTSIDE exists | `POST /api/universe/workbench` with `{"universe_path": OUTSIDE}` | `SAVED-ONLY` (must not change) | holdout |
| AC-19 | OUTSIDE exists | `POST /api/universe/from-companies` with `{"companies": [{"company_id": "a", "name": "A"}], "base_path": OUTSIDE}` | `SAVED-ONLY` (must not change) | holdout |
| AC-20 | OUTSIDE exists | `POST /api/documents/readiness` with `{"companies": [{"company_id": "a", "name": "A"}], "universe_path": OUTSIDE}` | status 200 (must not change: with `companies`, the path is ignored) | holdout |
| AC-21 | S is what `GET /api/emerging-themes/schedule` returns; OUTSIDE exists | `PUT /api/emerging-themes/schedule` with S, its `universe_path` replaced by OUTSIDE | `SAVED-ONLY` | holdout |
| AC-22 | the state after AC-21 | `GET /api/emerging-themes/schedule` | the body equals S | holdout |
| AC-23 | S is what `GET /api/discovery/schedule` returns; OUTSIDE exists | `PUT /api/discovery/schedule` with S, its `universe_path` replaced by OUTSIDE | `SAVED-ONLY` | holdout |
| AC-24 | U was uploaded; S as in AC-21 and AC-23 | on each of the two schedule routes: `PUT` with S and `universe_path` = U; then `PUT` with `universe_path` = null; then `PUT` with `universe_path` = `""` | each `PUT` answers 200 and echoes the `universe_path` it was sent | holdout |
| AC-25 | the server runs with `emerging_themes_schedule_universe_path` set to OUTSIDE and no schedule saved | `PUT /api/emerging-themes/schedule` with what `GET` returned, `enabled` flipped | status 200 | unit |
| AC-26 | OUTSIDE-H is an existing holdings CSV outside the universes folder; H is the `path` `raw-upload` returned for the same file | `POST /api/etf-overlap` with `{"funds": {"a": H, "b": OUTSIDE-H}}` | status 400, body `{"detail": "Holdings file must be an uploaded file."}` | holdout |
| AC-27 | H as in AC-26 | `POST /api/etf-overlap` with `{"funds": {"a": H, "b": MISSING}}` | the status and the body are the same bytes as in AC-26 | holdout |
| AC-28 | the same holdings CSV (one the route reads today, for example columns `ticker,name,weight` and two rows) was sent to `raw-upload` twice under two names; H1 and H2 are the returned paths | `POST /api/etf-overlap` with `{"funds": {"a": H1, "b": H2}}` | status 200 (must not change) | holdout |
| AC-29 | OUTSIDE exists | `POST /api/revenue-catalogue/suggest-mapping` with `{"taxonomy_id": "none", "catalogue_path": OUTSIDE}` | status 400, body `{"detail": "Catalogue file must be an uploaded file."}` | holdout |
| AC-30 | — | the AC-29 request with `catalogue_path` = MISSING | the status and the body are the same bytes as in AC-29 | holdout |
| AC-31 | OUTSIDE exists | `POST /api/themes/runs` with `{"taxonomy_id": "none", "companies": [{"company_id": "a", "name": "A"}], "revenue_catalogue_path": OUTSIDE}` | status 400, body `{"detail": "Catalogue file must be an uploaded file."}` | holdout |
| AC-32 | D1 accepted; OUTSIDE exists; the planner model is a stand-in that answers a script whose `universe_build` step has `source` = OUTSIDE | the plan is drafted with `POST /api/plans` | status 422; the body contains `is not a saved universe` (retires showcase-themes-fixes AC-118) | unit |
| AC-33 | a saved universe `eu.json` exists; the stand-in answers a script with `source` = `eu.json`, and in a second case with `source` = the absolute path of `eu.json` | the plan is drafted with `POST /api/plans` | status 200 in both cases (must not change) | unit |
| AC-34 | D1 accepted; a stored plan whose `universe_build` step names a released taxonomy and has `source` = OUTSIDE-BAD (AC-9) | the plan worker runs that step | the step fails with an error that contains `is not a saved universe` and does not contain `not valid JSON` | unit |
| AC-35 | D1 accepted; OUTSIDE exists; the same stand-in as AC-32 | `arp plan draft` drafts a plan from a brief | it exits non-zero and prints a line that contains `is not a saved universe` | unit |
| AC-36 | default settings (`max_upload_bytes` 100,000,000); the named file part is 100,000,001 bytes of the letter `a`; the other parts are as in the table of upload reads | each of upload reads 1 to 11 is sent | status 413, body `{"detail": "File is larger than the 100 MB upload limit."}` | holdout |
| AC-37 | `max_upload_bytes` = 2,000,000 | `POST /api/universe/raw-upload` with a file of exactly 2,000,000 bytes, then with one of 2,000,001 bytes | the first answers 200; the second answers 413 with `{"detail": "File is larger than the 2 MB upload limit."}` | unit |
| AC-38 | `max_upload_bytes` = 2,000,000; the universes folder and `frameworks_dir/_uploads` are listed before | upload reads 1 to 5 are each sent with a 2,000,001-byte file | afterwards both folders list the same files as before (no saved file, no `.part` file) | unit |
| AC-39 | `max_upload_bytes` = 2,000,000 | `POST /api/signals/runs` with a 1-byte `recipe`, a 1-byte `prices`, a 1-byte `panel_a` and a 2,000,001-byte `panel_b` | status 413 with the AC-37 sentence (every part is checked before any is parsed) | unit |
| AC-40 | a file named `big.png` of 20 × 1024 × 1024 + 1 bytes | `POST /api/reports/images` | status 413, body `{"detail": "image 'big.png' is larger than 20 MB"}` (must not change) | holdout |
| AC-41 | a valid universe CSV with 2 companies | `POST /api/universe/upload` | status 200; `company_count` is 2; `path` ends with the uploaded file name (must not change) | holdout |
| AC-42 | `max_upload_bytes` = 2,000,000 | `POST /api/documents/upload` and `POST /api/holdings/upload` are each sent a 2,000,001-byte file with the form fields the route requires | status 413 with the AC-37 sentence (must not change: uploads that already had the limit) | unit |
| AC-43 | a copy of the routers folder in which one file gains a line `data = await file.read()` | the upload guard test's check is run on that copy | it fails and its message names that file and line; on the real folder, with the allow-list of Design 4, it passes | unit |
| AC-44 | D3 accepted; default settings | a `POST /api/universe/workbench` with `Content-Type: application/json` and a body of 20,000,001 bytes (`{"companies": [], "pad": "aaa…"}`) | status 413, body `{"detail": "Request is larger than the 20 MB limit."}` | unit |
| AC-45 | D3 accepted; default settings | the AC-44 request with a body of exactly 20,000,000 bytes | status 400, body ``{"detail": "Provide either `companies` or `universe_path`."}`` | holdout |
| AC-46 | D3 accepted; default settings | a `multipart/form-data` request to `POST /api/universe/raw-upload` whose header says `Content-Length: 250000001` and of which the client sends the headers only | status 413, body `{"detail": "Request is larger than the 250 MB limit."}` | unit |
| AC-47 | D3 accepted; `max_body_bytes` = 1,000,000 | a JSON request without `Content-Length` whose body arrives in chunks totalling 1,000,001 bytes | status 413, body `{"detail": "Request is larger than the 1 MB limit."}` | unit |
| AC-48 | D3 accepted; `max_request_bytes` = 3,000,000 and `max_upload_bytes` = 2,000,000 | `POST /api/universe/raw-upload` with one 2,000,001-byte file (the request is under 3,000,000 bytes) | status 413 with the per-file sentence `File is larger than the 2 MB upload limit.` | unit |
| AC-49 | D3 accepted; the environment has `ARP_MAX_REQUEST_BYTES=5000000` and `ARP_MAX_BODY_BYTES=3000000` | `Settings()` is built | `max_request_bytes` is 5,000,000 and `max_body_bytes` is 3,000,000 | unit |
| AC-50 | D3 accepted; default settings | `GET /api/health`, and `POST /api/universe/upload` with the AC-41 file | 200 and 200 (must not change) | holdout |
| AC-53 | an approved spec run R; OUTSIDE-P is an existing prices CSV outside R's folder | `POST /api/replication/specs/R/backtest` with `prices_ref` = OUTSIDE-P | status 400, body `{"detail": "Dataset must be an uploaded file."}` | unit |
| AC-54 | an approved spec run R with an uploaded prices file | the backtest request with `characteristics_refs` = `{"x": OUTSIDE-P}` | the AC-53 answer | unit |
| AC-55 | an approved spec run R | the backtest request with `prices_ref` = MISSING | the status and the body are the same bytes as in AC-53 | unit |
| AC-56 | an approved spec run R; prices and one characteristics file were uploaded through the two replication upload routes | the backtest request with the two returned `ref` values | the answer is not the AC-53 answer and has no 5xx status (must not change) | unit |
| AC-57 | a copy of the app's OpenAPI document in which one request body gains a property `foo_path` | the path guard test's check is run on that copy | it fails and its message names `foo_path`; on the real document it passes | unit |
| AC-58 | D1 accepted; OUTSIDE exists; a failed plan; the planner stand-in answers a script with `source` = OUTSIDE | `arp plan replan` re-plans it | it exits non-zero and prints a line that contains `is not a saved universe` | unit |
| AC-59 | D1 accepted; OUTSIDE exists; a draft plan | `PUT /api/plans/{id}` with a script whose `universe_build` step has `source` = OUTSIDE, then `GET /api/plans/{id}` | the `PUT` answers 422 and its body contains `is not a saved universe`; the `GET` shows the script as it was before | unit |
| AC-60 | a copy of the app's OpenAPI document in which a route not on the list gains a request-body property `universe_path` | the path guard test's check is run on that copy | it fails and its message names that route and `universe_path` | unit |
| AC-61 | D3 accepted; `allowed_origins` holds `http://localhost:5173`; no sign-in is sent and `auth_mode` is `local` | the AC-44 request with the header `Origin: http://localhost:5173` | status 413 (not 401), and the answer has `access-control-allow-origin: http://localhost:5173` | unit |
| AC-62 | the P of AC-13 | `POST /api/documents/readiness` with `{"universe_path": P}` | status 400, body `{"detail": "Universe file could not be read: The file is not valid JSON."}` (must not change) | holdout |
| AC-63 | OUTSIDE exists; S as in AC-21 | `PUT /api/emerging-themes/schedule` with S, `interval_hours` = 0 and `universe_path` = OUTSIDE | status 422, body `{"detail": "Interval must be greater than 0 hours."}` (must not change: the interval check comes first) | holdout |
| AC-64 | OUTSIDE exists | `POST /api/etf-overlap` with `{"funds": {"a": OUTSIDE}}` | status 400, body `{"detail": "Provide at least two funds to compare."}` (must not change: this check comes first) | holdout |
| AC-65 | a spec run R that is not approved; OUTSIDE-P as in AC-53 | the backtest request with `prices_ref` = OUTSIDE-P | status 403 (must not change: the approval check comes first) | unit |
| AC-66 | the server runs with `discovery_schedule_universe_path` set to OUTSIDE and no schedule saved | `PUT /api/discovery/schedule` with what `GET` returned, `enabled` flipped | status 200 | unit |
| AC-67 | C is the `path` `raw-upload` returned for any small CSV | `POST /api/revenue-catalogue/suggest-mapping` with `{"taxonomy_id": "none", "catalogue_path": C}` | status 404, body `{"detail": "Taxonomy not found: none"}` (an uploaded catalogue passes the path check; the taxonomy lookup follows it) | holdout |
| AC-68 | — | `POST /api/revenue-catalogue/suggest-mapping` with `{"taxonomy_id": "none", "catalogue_path": ""}` | the AC-29 answer | holdout |
| AC-69 | the state after AC-23 | `GET /api/discovery/schedule` | the body equals S | holdout |
| AC-70 | D1 accepted; a plan template exists; OUTSIDE exists | `POST /api/plan-templates/{name}/instantiate` with `source` = OUTSIDE, then `GET /api/plans` | the `POST` answers 422 and its body contains `is not a saved universe`; the `GET` lists no new plan | unit |
| AC-71 | D1 accepted; OUTSIDE exists; the planner stand-in answers a script with `source` = OUTSIDE | a failed plan is re-planned with `POST /api/plans/{id}/replan`, and a plan is drafted through the agent route (`routers/agent.py`) | replan answers 422 with a `detail` list whose first item contains `is not a saved universe`, and the plan is still `failed`; the agent route creates no plan | unit |
| AC-72 | C as in AC-67 | `POST /api/themes/runs` with `{"taxonomy_id": "none", "companies": [{"company_id": "a", "name": "A"}], "revenue_catalogue_path": X}`, once with X = `""` and once with X = C | status 404, body `{"detail": "Taxonomy not found: none"}` both times (must not change for `""`; an uploaded catalogue passes the path check) | holdout |
| AC-73 | H as in AC-26 | `POST /api/etf-overlap` with `{"funds": {"a": H, "b": ""}}` | the AC-26 answer | holdout |
| AC-74 | an approved spec run R | the backtest request with `prices_ref` = `""` | the AC-53 answer | unit |

Must not change: the answers of the routes that already check a path (AC-18, AC-19) or a size (AC-40, AC-42);
"Provide either…" (AC-16); XBRL's and readiness's own sentences (AC-17, AC-62); the order of checks (AC-63 to AC-65); `companies` wins over `universe_path` (AC-20); a saved
universe still starts each run (AC-10 to AC-12); plans naming a saved universe (AC-33); normal uploads and
bodyless requests (AC-41, AC-50); the backtest with its own uploads (AC-56); a schedule path the operator set
(AC-25, AC-66); an uploaded catalogue (AC-67).
