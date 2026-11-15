# Workbench review fixes: first rows in about 3 s, also after a restart, and five robustness bugs fixed

Slug: workbench-review-fixes

Risk: `risk:normal` for both PRs (see "Risk" below). Size M, 2 PRs: the speed PR first, then the robustness PR.

Parent spec: `2026-11-13-stewardship-priority-worklist-design.md` (the Workbench; its AC-44 is the 5 s row).
Builds on PR #491 (the Workbench screen, branch `stewardship-priority-worklist-pr4`). Both PRs start from `main`
after #491 has merged. Findings were checked on `main` b53ad65 and on #491's head a9c035c.

Status: draft, waiting for the owner's approval.

## Owner decisions

Asked for on 15 Nov 2026, from the open review findings of #491.

Taken by button in the dispatcher session, 15 Nov 2026:

1. Observation files are cached per server process and read again when a file's modification time or size changes.
   Triggers, engagements, selections, notes and programmes stay computed on every read. (The cache #491 adds.)
2. Speed: "3 s, and a fast restart". The cheap steps bring a normal (warm) load to about 3 s, and the data load also
   writes one compact file of the latest ESG values, so the first load after a restart is fast too. One new stored
   file is accepted. Moving ESG data into the database is not wanted before 27 Nov.
3. A damaged log line is skipped and a warning goes to the server log; the screens keep working. This applies to the
   selection log and the programme log here. The tiers picks log is fixed in the sibling item `tiers-review-fixes`.

Taken by button in this spec session, 15 Nov 2026:

4. Both speed targets are hard pass/fail rows, checked by the evaluator on the showcase data: a normal load, median of
   5 opens, under 3.5 s (AC-1); the first open after a restart, median of 3, under 5 s (AC-2). If one misses, the PR
   stops and the owner decides whether to accept it as an exception.

## Why

The Workbench is the screen the stewardship team works from, and it will be shown on about 27 Nov. Today, with
#491, its first rows take a median of 4.3 s on the 2,581-company showcase house (two runs took 5.0 s and 5.8 s, over
AC-44's 5 s). Right after a server restart they take 9 to 19 s, because the first request races the start-up thread
that fills the observation cache. A demo usually starts right after a restart.

The review of #491 also found five bugs in how selections, programmes and notes are stored. Two of them (2 and 3
below) can bite in the showcase. Three (1, 4, 5) only happen when more than one server process writes the same files.

## What the showcase runs on

The showcase runs as **one** uvicorn process on a bank JupyterLab, about 27 Nov. In one process, the existing
thread locks already keep selection and programme changes one at a time. So findings 1, 4 and 5 are robustness
fixes, not a showcase risk: they matter once someone runs `uvicorn --workers N`, or an `arp` command writes the same
files while the API runs. Findings 2 and 3 can happen in one process.

## Where the time goes today

Measured in #491's description, warm request on the showcase house: about 3.2 s of computing plus 0.35 s to turn
8 MB into JSON.

| Step | Time |
|---|---|
| Observation check (81k file `stat` calls) | 0.8 s |
| House universe | 0.5–1.0 s |
| Building the rows | 0.6 s |
| Engagements | 0.3 s |
| Vote ledger | 0.3 s |
| Funds | 0.1 s |

The first three run one after the other; engagements, vote ledger and funds do not depend on the observations.

## Goals

1. Speed PR: a normal (warm) load of `#/stewardship/workbench` on the showcase house shows its first rows in a median
   under 3.5 s (AC-1).
2. Speed PR: the first load after a server restart, opened the moment the server answers, shows its first rows in a
   median under 5 s (AC-2).
3. Speed PR: the cached values are never stale, before or after a restart (AC-3, AC-4).
4. Robustness PR: fix the five findings below (AC-11 to AC-26, AC-29).

## Non-goals

- Moving ESG observations into the database (owner decision 2: not before 27 Nov).
- Dropping fields from the worklist response. Compressing it (AC-7) does the same for transfer size without changing
  the API contract.
- Caching triggers, engagements, selections, notes, programmes, tiers, holdings or the vote ledger (owner decision 1).
- A damaged line in the notes log. `NoteLog.summary` reads `n["company_id"]` the same way, but owner decision 3 names
  only the selection and programme logs. It is listed as a follow-up.
- The tiers picks log (sibling item `tiers-review-fixes`).

## Anti-goals

- A value shown that is older than its file. Every cached value is checked against its file's modification time and
  size before use, also when it came from the compact file (AC-3, AC-4).
- A server that will not start, or a worklist that fails, because the compact file is missing or damaged (AC-5).
- A request that waits forever. A request that waits for the start-up fill gives up waiting after 60 s and reads
  the files itself (AC-28).
- A confirmed selection or a confirmed programme member lost to a stale write (AC-11, AC-12, AC-15).

## Approaches considered

For the first load after a restart (owner decision 2 settled that there is one compact file; the open part was when
it is written and how it stays correct):

- **A. The compact file seeds the per-process cache, and each entry is still checked against its file (chosen).**
  For each observation file the compact file holds the file's modification time and size at the time it was written,
  the `as_of` date, and the latest observation. At start-up the server reads this one file in place of 81k, then
  runs the same per-file check #491 already runs on every request (one `stat` per file). An entry whose file changed
  is read from the file. It can never be stale, and a missing or damaged compact file only costs speed. It keeps
  the 0.8 s check, which a warm request pays anyway.
- **B. Write-through: every new observation also updates the compact file, and requests trust it without checking
  the files.** About 0.8 s faster per request, but any file written outside `PortfolioStore.append_observation` (a
  hand edit, a copied data folder, an older `arp` version) is shown stale with no way to notice. A bulk load would
  also need batching to avoid rewriting the file 81k times. Rejected: it breaks owner decision 1 ("re-read when
  mtime or size changes").
- **C. Check the directory's modification time instead of each file.** Appending to a file does not change its
  directory's modification time, so an appended observation would be missed. Rejected.
- **D. Move observations into Postgres.** Rejected by owner decision 2 for now.

For the warm load, there is one sensible way: the cheap steps listed under "Speed PR". Nothing here changes what is
computed.

## Speed PR

What it does:

1. **Independent reads in parallel.** The vote ledger, engagements and fund holdings are read in threads at the same
   time as the observation check, then the rows are built as today.
2. **Compressed responses.** `GZipMiddleware(minimum_size=1000)` is added to the API app in `arp/api/main.py`, for
   all routes, as `arp/compute/server.py` already does. The 8 MB worklist is then sent compressed when the browser
   accepts it (AC-7); streamed exports keep the same content (AC-27).
3. **A request during start-up waits for the start-up fill** instead of reading the same files at the same time. It
   waits at most 60 s (a named module constant), then reads the files itself (AC-28).
4. **The start-up fill reads files with several threads.**
5. **The compact file** `<portfolios_dir>/observations_latest.json` (approach A):
   - Written, atomically (`arp/storage/atomic_io.atomic_write_text`), by `arp showcase load` when it finishes, and by
     the start-up fill when it finishes if it had to read any observation file (compact file missing, damaged, or an
     entry out of date). So a load through any other path (ESG intake, mock data) is in the file after the next
     restart, and until then the per-file check covers it.
   - Read once, at start-up. Never trusted without the per-file check.
   - Deleting it is always safe: the next start-up reads the 81k files (slow, about as today) and writes it again.
   - It sits outside `datapoints/`, so `list_observation_keys` never sees it.
6. **`e2e_stack.sh restart-api`**: a new subcommand that stops the API's uvicorn process (`$state/api.pid`) and starts
   it again with the same environment `up` exports, and nothing else: no seeding, no frontend build, `vite preview`
   keeps running. It returns as soon as `GET /api/health` answers 200. The evaluator uses it for AC-2.

The builder picks the order of these steps and may stop once AC-1 and AC-2 pass. Steps 2, 5 and 6 are required (AC-7,
AC-6, AC-2). If AC-1 cannot be met with them, say so on the PR with the measured times per step: that is a question for
the owner, not a reason to cache more (owner decision 1).

Text to amend in the same PR: the parent spec's Anti-goals sentence about the one cache, and `worklist.py`'s module
docstring, both gain: "At start-up the cache is filled from `observations_latest.json`; each entry is still checked
against its file's modification time and size before use."

## Robustness PR

The five findings, as checked on `main` b53ad65 and #491:

1. **A confirmed selection can be lost** (`worklist.py`, `SelectionLog._fold` and `_change`). `_fold` drops a row on
   any `removed` event, confirmed or not. `_change` checks "confirmed rows cannot be removed" under a thread lock,
   which does not hold across processes. With two server processes, one can confirm a company while the other, with
   an older view, writes `removed` for it. The fold then drops the confirmed row, and a later `added` brings it back
   as `proposed`.
   Fix: (a) `_fold` ignores a `removed` event for a confirmed row; (b) the change and confirm steps take a
   cross-process lock per log file.
2. **Programme changes on non-members do nothing, without saying so** (`programmes.py`, `ProgrammeLog.change`).
   Ending or removing a company that is not a member in the right state returns 200 and writes nothing. Adding and
   ending the same new company writes the add and silently drops the end.
   Fix: every check runs before anything is written. Any refusal writes nothing and returns 422. The checks run
   in this order, and only the first one that fails answers:
   1. unknown programme: 404, as today;
   2. an `add` id outside the house universe: `unknown company: <ids>`, as today;
   3. a company in two of `add`, `remove` and `end`: `A company can only be in one of add, remove and end: <ids>`;
   4. a `remove` id that is a confirmed member: `confirmed members are ended, not removed` (parent AC-118);
   5. any other `remove` id that is not a proposed member: `not a proposed member: <ids>`;
   6. `end` with no reason: `Ending a membership needs a reason` (parent AC-119);
   7. an `end` id that is not a confirmed member: `not a confirmed member: <ids>`.

   `<ids>` lists the refused ids joined with `, ` (comma and space, as in `unknown company:`), each id once, in the
   order it first appears in the request.
   Unchanged: removing a proposed member writes `removed` and returns 200 (AC-25). Adding a company that is already
   proposed or confirmed writes nothing and returns 200 (AC-26).
3. **One damaged log line takes the worklist down** (`ProgrammeLog._fold`, `SelectionLog._fold`). Both read
   `e["issuer_id"]`, `e["event"]` and others directly, so a line that is valid JSON but lacks a key raises `KeyError`
   and `GET /worklist` fails. A line that is valid JSON but not an object (`["x"]`, `null`) raises `TypeError` the
   same way. Fix (owner decision 3): a line is damaged when it is not a JSON object, or lacks a key the fold reads
   (`event`, `issuer_id`, `by`, `at`, and `weights_version` in the selection log; `event`, `programme_id`, `by`,
   `at`, `issuer_id` for member events and `name` for `created` in the programme log). A damaged line is skipped and
   a WARNING goes to the server log: `Skipped damaged line <n> in <path>`. `<n>` is the 1-based line number in the
   file, counting every line, blank and non-JSON lines included. Each (path, line) is logged once per server
   process, not on every read. (A line that is not JSON at all is still skipped by `read_jsonl`, without a
   warning.)
4. **Two parallel programme creates can both succeed** (`programmes.py` `_LOCK` is a `threading.Lock`). Fix: a
   cross-process lock on the programme log.
5. **Notes are appended without a lock** (`notes.py`, `NoteLog.add`). Fix: a cross-process lock on the notes log.

One tool covers 1(b), 4 and 5: `arp/storage/locks.py` `KeyedLock(lock_path=...)`, which takes a thread lock and an
`flock` on a sidecar lock file, already used in 10 places (`arp/decision/overrides.py` is the closest pattern: one
lock per log file, lock file next to it). No new dependency.

## Order and how this fits with Workbench PRs 5 to 7

| PR | Files it changes | When |
|---|---|---|
| #491 (Workbench PR 4) | read path, `worklist.py`, `portfolio_store.py`, `main.py`, the Workbench screen | merges first |
| **Speed PR** | `portfolio_store.py`, `universe.py`, `main.py`, `scripts/e2e_stack.sh`, `routers/stewardship_worklist.py`, `showcase/load.py`, `process.py`; the parent spec's Anti-goals sentence; `worklist.py` docstring | right after #491 |
| Workbench PR 5 (filter builder) | frontend only (`pages/steward/workbench.tsx`, `lib/workbench.ts`, their tests) | after #491; may run alongside the robustness PR |
| **Robustness PR** | `stewardship/worklist.py` (`SelectionLog` only), `stewardship/programmes.py`, `stewardship/notes.py`, their tests | after the speed PR; alongside PR 5 (no shared files) |
| Workbench PR 6 (side panel) | frontend; possibly new read routes in `routers/stewardship_worklist.py` | after the speed PR |
| Workbench PR 7 (commitments, refresh) | `stewardship/worklist.py` (`build`, columns), frontend | after the speed PR; whichever of PR 7 and the robustness PR merges second merges `main` in first |

The speed PR goes first because PRs 5 to 7 sit on the same read path and should be measured against the new budget.
PRs 5 to 7 measure first-rows time the AC-1 way and put the result in their PR description.

## Risk

Both PRs are `risk:normal` under the steward table:

- Speed PR: the compact file is a copy of values the observation files already hold. It changes no database schema,
  migrates nothing, deletes no stored data, and is rebuilt by deleting it. Compression changes no auth and no
  response content. `e2e_stack.sh` is a test script, not a workflow or hook.
- Robustness PR: it changes how two logs are read and refuses some changes that used to do nothing. It deletes or
  rewrites no stored line.

## Left to the builder

- The compact file's inner format (it must hold, per observation file, the modification time, the size, the `as_of`
  date and the observation).
- How the wait for the start-up fill is built, within the 60 s limit.
- How line numbers are kept for the warning (for example a line-numbered variant of `read_jsonl` next to it).
- Thread counts.
- The lock file names (next to the log they guard, never matching `*.jsonl`).

## Acceptance

Words used below:

- **Showcase data:** as in the parent spec (`arp showcase load`, `arp stewardship seed-demo`,
  `arp stewardship load-npx data/voting/npx_urth/`, then `PUT /api/stewardship/universe` `{"source": "portfolio"}`).
  The house then holds 2,581 companies.
- **Fixture W, Q:** as in the parent spec. `<streams>` is `stewardship_streams_dir`.
- **Load time:** with Playwright at 1440 × 900, the time from starting navigation to `#/stewardship/workbench` until
  the first data row of the table is visible. The server is one uvicorn process started by
  `backend/scripts/e2e_stack.sh up`, on the same machine as the browser. These times are for the evaluator's cloud
  container; the bank laptop will differ.
- **Warm:** the page has been opened once since the server started, and the server has then been idle for 15 s.
- **Restart:** `bash backend/scripts/e2e_stack.sh restart-api` (added by the speed PR), then open the page at once:
  the command returns as soon as `GET /api/health` answers 200.

Speed PR (`Rows: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-27, AC-28`):

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Showcase data; server warm | The page is opened 5 times, each a full reload | The median load time is under 3.5 s, and each time the page shows 100 rows and page controls | evaluator |
| AC-2 | Showcase data; `arp showcase load` run after the speed PR is installed | A restart, then the page is opened; done 3 times | The median load time is under 5 s, and each time the page shows 100 rows and page controls | evaluator |
| AC-3 | Showcase data; for one house company X, a `transition_grade` observation with `source` `internal_api`, `value` `B` and `observed_at` the latest holdings snapshot date is appended with `PortfolioStore.append_observation`; then `GET /api/stewardship/worklist` once | A second such observation with `value` `D` is appended; then `GET /worklist`, with no restart | X's `transition_grade.value` is `D` and `transition_grade.simulated` is `false` | holdout |
| AC-4 | A portfolio store with observations and a compact file written from it; then one observation appended to one file | A new process fills the cache from the compact file and asks for that file's latest observation | It returns the appended observation | unit |
| AC-5 | The same store as AC-4, the compact file in turn missing, empty, and holding `{` | The server starts and `GET /worklist` is called | Status 200 in all three cases, with rows equal to those built with a good compact file. Missing: no warning. Empty and `{`: exactly one WARNING whose text contains the compact file's path | unit |
| AC-6 | A fresh data folder | `arp showcase load` finishes | `<portfolios_dir>/observations_latest.json` exists and holds one entry per observation file | unit |
| AC-7 | Showcase data | `GET /api/stewardship/worklist` with `Accept-Encoding: gzip` | The response has `Content-Encoding: gzip`, and its unzipped body equals the body of the same request without `Accept-Encoding` | holdout |
| AC-8 | A store whose compact file is missing | The start-up fill finishes | The compact file exists and holds one entry per observation file | unit |
| AC-9 | Showcase data | `GET /worklist` built with the parallel reads and with the compact file | Equals the response built with neither (same rows, same order, same values) | unit |
| AC-27 | A run with a CSV export | `GET /api/runs/<run_id>/export.csv` with `Accept-Encoding: gzip` | The unzipped body equals the body of the same request without `Accept-Encoding` | unit |
| AC-28 | The start-up fill never finishes (stubbed); the wait constant patched to 1 s | `GET /worklist` | Status 200 within 1 s plus the normal read time, with rows equal to a normal build | unit |
| AC-10 | Fixture W and one `GET /worklist` done | T(`SYN07`, high, `t_new`) is appended (parent spec's trigger run), then `GET /worklist` again, with no restart | The second response has `SYN07`'s `triggers.high` = 1 (parent AC-13 still holds) | holdout |

Robustness PR (no `Rows:` line, last slice):

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-11 | Fixture W; `POST /api/stewardship/selection` `{"cycle": Q, "add": ["SYN03"]}`, then `POST /selection/confirm` `{"cycle": Q}` | The line `{"event": "removed", "issuer_id": "SYN03", "by": "stale", "at": "<now>", "weights_version": 0}` is appended to `<streams>/selection/<Q>/house.jsonl`; then `GET /api/stewardship/selection` | `SYN03` is listed with `status` `confirmed` and its original `confirmed_by` | holdout |
| AC-12 | AC-11 | `POST /selection` `{"cycle": Q, "add": ["SYN03"]}`, then `GET /selection` | `SYN03` is listed once, with `status` `confirmed` | holdout |
| AC-13 | Fixture W; `POST /selection` `{"cycle": Q, "add": ["SYN04"]}` | `POST /selection` `{"cycle": Q, "remove": ["SYN04"]}`, then `GET /selection` | `SYN04` is not listed (removing a proposed row still works) | holdout |
| AC-14 | Fixture W, programme log removed | `POST /api/stewardship/programmes/climate/members` `{"end": ["SYN05"], "reason": "x"}` | Status 422 with detail `not a confirmed member: SYN05`; `GET /programmes/climate` has no members | holdout |
| AC-15 | A fresh selection log for cycle Q; companies C1..C50 each added as `proposed` | Two OS processes in parallel: one calls `SelectionLog.confirm` once; the other calls `SelectionLog.change` removing C1..C50 one at a time | Every company that ends up listed is `confirmed`; no `removed` line in the log follows a `confirmed` line for the same company | unit |
| AC-16 | Fixture W, programme log removed | `POST /programmes/climate/members` `{"remove": ["SYN05"]}` | Status 422 with detail `not a proposed member: SYN05` | holdout |
| AC-17 | Fixture W, programme log removed | `POST /programmes/climate/members` `{"add": ["SYN05"], "end": ["SYN05"], "reason": "x"}` | Status 422 with detail `A company can only be in one of add, remove and end: SYN05`; `GET /programmes/climate` has no members | holdout |
| AC-18 | Fixture W, programme log removed; `POST /programmes/climate/members` `{"add": ["SYN03"]}` | `POST /programmes/climate/members` `{"end": ["SYN03"], "reason": "x"}` | Status 422 with detail `not a confirmed member: SYN03`; `GET /programmes/climate` shows `SYN03` `proposed` | holdout |
| AC-19 | Fixture W, programme log removed; `POST /programmes/climate/members` `{"add": ["SYN03"]}`, then `POST /programmes/climate/confirm` `{}` | `POST /programmes/climate/members` `{"remove": ["SYN03"]}` | Status 422 with detail `confirmed members are ended, not removed` (parent AC-118 unchanged) | holdout |
| AC-20 | Fixture W; `POST /selection` `{"cycle": Q, "add": ["SYN03"]}` | The lines `{"event": "added"}`, `{"issuer_id": "SYN04"}` and `["x"]` are appended to `<streams>/selection/<Q>/house.jsonl`; then `GET /selection` and `GET /api/stewardship/worklist` | Both status 200; the selection lists exactly `SYN03`, `proposed` | holdout |
| AC-21 | Fixture W, programme log removed; `POST /programmes/climate/members` `{"add": ["SYN03"]}` | The lines `{"event": "proposed", "programme_id": "climate"}`, `{"programme_id": "climate"}` and `["x"]` are appended to `<streams>/programmes/events.jsonl`; then `GET /api/stewardship/programmes`, `GET /programmes/climate` and `GET /worklist` | All status 200; `climate` has exactly one member, `SYN03`, `proposed` | holdout |
| AC-22 | A selection log and a programme log, each with line 1 not JSON, line 2 valid, line 3 missing `issuer_id` | Each log is read twice in one process | The server log has exactly one WARNING per log, reading `Skipped damaged line 3 in <path of that log>` | unit |
| AC-23 | An empty programme log | Two OS processes each call `ProgrammeLog.create` with the same 50 names, in parallel | The log holds exactly 50 `created` events, one per name, and each name was refused once with `A programme named <name> exists` or `A programme with id <id> exists` | unit |
| AC-25 | Fixture W, programme log removed; `POST /programmes/climate/members` `{"add": ["SYN03"]}` | `POST /programmes/climate/members` `{"remove": ["SYN03"]}` | Status 200; `GET /programmes/climate` has no members | holdout |
| AC-26 | Fixture W, programme log removed; `POST /programmes/climate/members` `{"add": ["SYN03"]}`, then `POST /programmes/climate/confirm` `{}` | `POST /programmes/climate/members` `{"add": ["SYN03"]}` | Status 200; `GET /programmes/climate` lists `SYN03` once, `confirmed` | holdout |
| AC-29 | Fixture W, programme log removed | `POST /programmes/climate/members` `{"end": ["SYN05"]}` with no `reason` | Status 422 with detail `Ending a membership needs a reason` (check 6 answers before check 7) | holdout |
| AC-24 | An empty notes log | Two OS processes each call `NoteLog.add` 500 times, in parallel | `NoteLog` reads back 1,000 notes, and every line of the file decodes as JSON | unit |

Must not change: the parent spec's acceptance rows, in particular AC-13 (here AC-10), AC-44 (5 s; AC-1 and AC-2 are
stricter), AC-113 to AC-122 for programmes and AC-77 to AC-101 for notes; removing a proposed selection row (AC-13
here) and the 422 for removing a confirmed programme member (AC-19 here).
