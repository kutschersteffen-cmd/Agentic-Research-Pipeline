# Stewardship pages in a few seconds: build the held-company list once, rebuild it when an input changes

Slug: stewardship-house-universe-cache

Risk of the build: `risk:normal` (see "Risk"). Size S, 1 PR. The build starts from `main` after #544 (speed) and
#548 (robustness) of `workbench-review-fixes` have merged.

Status: draft, for the owner's approval.

## Owner decision

16 Nov 2026, in the factory dispatcher's session (option 2 of 3): "Build the held-company list once and reuse it until
an input changes. A changed holdings file, a changed data file or a changed setting rebuilds it." This lifts owner
decision 1 of `workbench-review-fixes` (no second cache next to the observation cache) for this list only, and asks
for a row that checks nothing stale is ever shown.

## Why

Every StewardIQ request builds the house universe again: the 2,566 held companies with their portfolio values. A page
sends four to six such requests at once into one server process, which runs Python one step at a time, so the waits
add up: the Selection page takes 11.6 s. The showcase to senior management is on about 27 Nov 2026 on a bank
JupyterLab, one server process.

## Measurements

16 Nov 2026, `main` a59fb56 with #544 and #548 merged in, showcase data (2,566 house companies, 81,216 observation
files, 21,628 holdings rows), one uvicorn process, warm, best of three. Machine: cloud container, 4 vCPU Intel Xeon
@ 2.1 GHz, 15 GB. "Prototype" is a throwaway version of this design (kept list, the shared input check below, one
check per request), measured the same way and then removed.

One universe build today: observation check 0.38 s (listing 81,216 files, then each file's identity, size and times),
holdings, securities, companies and resolutions read and merged 0.28 s, together 0.67 s. The vote ledger then reads
holdings again for the held ISINs (inside `vote_items`, 0.43 s). `load_sample()` in all: 1.44 s. The input check
the prototype used costs 0.44 s (observation check 0.41 s, database query 0.06 s at most); the one-pass walk this
spec settles on measured 0.25 s for the observation part, so the targets below carry that margin too.

| Page (page time, defined in Acceptance) | Today | Prototype | Target |
|---|---|---|---|
| Monitoring, opened alone | 9.9 s | 5.1 s | 6 s |
| Selection, opened alone | 11.6 s | 5.5 s | 6.5 s |
| Checkpoint, opened alone | 7.0 s | 5.4 s | 6.5 s |
| Drafting, Voting, Tracking, Client policy, Reporting, each opened alone | 3.3 to 4.2 s | 2.6 to 3.1 s | 4 s |
| Workbench, first data row visible | 3.3 s | 2.8 s | 3 s (the owner's Workbench target) |
| Workbench, all its requests answered | 11.9 s | 6.0 s | 7 s |
| Cockpit, opened alone | 1.1 s | 1.1 s | 1.5 s |
| Selection, clicked 2 s after the Workbench's rows appear | 15.9 s | 2.9 s | 3.5 s |
| Monitoring, clicked 2 s after the Workbench's rows appear | 12.3 s | 3.4 s | 4 s |
| Cockpit, opened 2 s after the Workbench's rows appear | 4.1 s | 1.6 s | 2 s |

| Request alone | Today | Prototype |
|---|---|---|
| `GET /worklist` | 2.5 s | 2.0 s |
| `GET /worklist/scopes` | 0.9 s | 0.6 s |
| `GET /selection` | 0.7 s | 0.4 s |
| `GET /streams/house/flow` | 3.1 s | 2.3 s |
| `GET /tiers` | 1.9 s | 1.3 s |
| `GET /decision-inputs` | 1.2 s | 0.6 s |
| `GET /studio/coverage/inputs` | 1.5 s | 1.1 s |
| `GET /studio/monitoring/triggers` | 2.0 s | 1.5 s |

Without any input check the same prototype reached 3.8 s for Selection and 3.9 s for Monitoring: the never-stale
check costs about 1.5 s of each page. The rest of each page is the stage's own work (flow, tiers, triggers), which
this spec does not touch.

## Goals

1. The stage pages and the cockpit meet the targets above (AC-1 to AC-10), without memory growing per request (AC-29) and without
   slowing the Workbench after a restart (AC-34, AC-35).
2. Nothing stale is ever shown: after a change to any input of the list, made by this server or by another process,
   the next request shows the new data (AC-11 to AC-19, AC-23, AC-30 to AC-32, AC-36, AC-37).
3. Requests that need the list at the same time wait for one build; a failed build is not kept; one request checks once (AC-20 to AC-22, AC-24, AC-28).
4. The anti-goals hold: no request sees another's changes (AC-25), nothing is stored (AC-33), #544's compact file stays valid
   (AC-39), answers are unchanged (AC-26, AC-38),
   the sample source is copied too (AC-40), the monthly run is unchanged (AC-41).

## Non-goals

- Building the list at server start-up. The first request after a restart builds it (0.7 s), as today.
- Reusing anything else across requests: decisions, votes, alerts, tiers, picks, triggers, engagements, selections,
  notes, programmes and policies stay read fresh on every request.
- Making each stage's own work faster (flow, tiers, triggers, worklist rows).
- The Workbench's smaller follow-on requests (selection and scopes reading only ids and names, the flow read only when
  a stage tab opens). With the list reused, Selection clicked after the Workbench drops from 15.9 s to 2.9 s, so they
  are not needed.
- The monthly run (`portfolio/monthly_run.py`), which builds the list for a past month: it stays as it is.

## Anti-goals

- A page showing a value that a server started after the change would not show (stale data).
- A request seeing changes another request made to its own copy of the list.
- A third caching mechanism: no new stored file, no new lock file, no change to how the observation cache (#491,
  #544) decides when to read a file again, nor to its compact file.

## Approaches considered

1. **Keep the last build per server process, checked against a version of its inputs on every request (chosen).**
   Needs nothing stored; costs a 0.3 s check, shared between parallel requests.
2. Keep it until something in the app writes one of its inputs (a marker file). About 1.5 s faster per page, but a
   file copied in or restored outside the app, or a holdings change made in the database by another tool, would be
   missed: ruled out by the owner's never-stale rule.
3. Cache the whole `load_sample()` result, overlays included. Votes, decisions and alerts change with clicks in the
   stage pages and live in many tables and folders: more ways to show stale data, for speed the prototype shows is
   not needed.

## Design

### What is kept

`process.house_universe()` stays the one function that returns the held-company list. Per server process it keeps its
last build, made of three parts built together from the same inputs:

- the universe (`from_portfolio(store)` for source `portfolio`, the sample file for source `sample`);
- the held ISIN map (`held_isins`, ISIN to issuer id), which the vote ledger needs;
- the latest observations (`universe.latest_observations(store)`), which the Workbench columns need.

Code that builds these itself today takes them from `house_universe()`: `routers/stewardship_worklist._load`,
`process.house_isins` (used by `vote_ledger_feed`) and `process.flow`. **One request checks the inputs once**: a
caller that already holds the request's build passes its parts on (as `load_sample` passes `held` to `vote_items`
today when it builds the universe itself), instead of asking `house_universe()` a second time. `monthly_run` keeps
calling `from_portfolio` with its own date.

Each call gets its own copy: new issuer dicts with their own `fields` and `holding` dicts (0.01 s on the showcase;
`copy.deepcopy` takes 0.08 s). The kept build is never handed out, so what `load_sample()` writes into `fields`
never reaches another request. The builder checks every caller for other in-place changes and copies deeper if one
exists. The observations are shared, not copied: they are already shared read-only objects of the observation cache.

Source `sample`: the version is the setting file and the sample file only (no database query, no observation
check); the kept build is the sample's universe, with no held-ISIN or observations part, and `_load` keeps its
current sample path for the Workbench columns.

The build logs one INFO line when it succeeds: `House universe built: <n> companies in <t> s`. A build that raises
logs none.

### The inputs and how each is checked

Before using the kept build, a call works out the version of its inputs. Same version: a copy of the kept build.
Different: build again, keep it, return a copy.

| Input | Where it lives | Check | Cost on the showcase |
|---|---|---|---|
| App settings | `portfolios_dir`, `stewardship_streams_dir`, `identifier_map_path`, the Postgres DSN | compared for equality | none |
| Universe setting | `<stewardship_streams_dir>/house/universe.json` | the file's inode, ctime, mtime and size (missing counts as its own value) | under 1 ms |
| Sample file (source `sample` only) | `arp/stewardship/data/examples/sample_meetings.json` | as above | under 1 ms |
| Holdings, securities, companies, resolutions, portfolios | Postgres tables `holdings`, `securities`, `legacy_companies`, `security_resolutions`, `portfolios` | one read-only query: per table, `count(*)` and `sum(hashtextextended(t::text, 0))` over its rows | 64 ms |
| Sector master | `issuer_sectors.json` beside `identifier_map_path` | as the setting file | under 1 ms |
| Observation files | `<portfolios_dir>/datapoints/**` | one walk of the folders: every file's name and its inode, ctime, mtime and size (the identity #491 compares). The kept build stores the walk **of the check that preceded it** (never one taken after the build); any file added, removed or differing means a rebuild. It does not depend on who else reads the observation cache, and it does not change `PortfolioStore.latest_observation`, whose source #544's compact-file format id hashes | 0.25 s |

**The check is shared.** One check runs at a time. A request that arrives while one runs waits for the next one, which
starts when the running one ends; every request waiting for it uses its result. So a change finished before a request
arrived is always seen, and a burst of parallel requests costs at most two checks.

A file that changes between the check and the build's read of it is read new by the build but stored with its older
identity, so the next check rebuilds once more: never stale, at most one extra build.

The check logs one DEBUG line per run: `Input check: <n> observation files in <t> s`.

A file restored with its old modification time is still caught: replacing a file changes its inode or ctime, which
the check compares (as #491 does). A database change is caught by the row hashes, whichever program made it.

### Builds

One build at a time: a request that needs the build being made waits for it. A build that raises is not kept; every
request waiting for it gets the same error (status 500, as today), and the next request builds again.

### Memory

The kept universe is 9.6 MB of Python objects on the showcase house (2,566 companies, 28.5 fields each, measured with
`tracemalloc`); the held ISIN map is a few hundred kB; the observations are references to objects the observation
cache already holds. One build is kept per process; the previous one is freed when a new one replaces it. Each
request's copy lives only as long as the request.

### How this sits on #491, #544 and #548

- Observation values still come only from the per-file observation cache (#491), filled at start-up from
  `observations_latest.json` (#544). The kept build holds that cache's objects; the build asks that cache for every
  file, so a changed file is read again by the cache's own rule. `latest_observation`'s code is not changed, so the
  compact file written before the upgrade stays valid (AC-39).
- #548's cross-process locks guard selections, programmes and notes, which stay read fresh; this change takes none of
  those locks and adds none.
- Several server processes each keep their own build; each finds another process's changes through the same check.
- If the `workbench-review-fixes-shared-reads` branch (one Workbench request reads holdings once) merges first, its
  `reads_out` path in `_load` goes through the kept build; if it has not merged, this change replaces it.

## Risk

`risk:normal`: an in-memory cache of derived data, no stored format, no schema change, no migration, one read-only
query. Weights are computed by the same code as today (AC-38 checks every answer equals `main`'s). Nothing in the
steward table's `risk:high` row is touched. This spec PR is `risk:low` (docs only).

## Left to the builder

- Where the check and the kept build live (`process.py` or `universe.py`), and how the walk's result is stored.
- The thread primitives for "one check at a time" and "one build at a time", and how the kept build is cleared for
  tests (AC-26, AC-31).

## The build PR

Its description carries `Spec: stewardship-house-universe-cache` and a line `Holdout: full`, so the hidden tests of
`workbench-review-fixes` (AC-3, AC-7, AC-10) and the other specs run on it too. Their unit rows (AC-4, AC-5, AC-8)
stay in the repo's own tests, which CI runs on every PR.

## Acceptance

Words used below:

- **Showcase data:** `arp showcase load`, `arp stewardship seed-demo`, `arp stewardship load-npx data/voting/npx_urth/`,
  then `PUT /api/stewardship/universe` `{"source": "portfolio"}` (as in `workbench-review-fixes`). The house then
  holds about 2,570 companies (2,566 in this spec's measurements); rows count relative to the first answer.
- **Page time:** with Playwright at 1440 × 900, the time from starting navigation (or the click) until the last
  `/api/` request the page started has answered, once no new `/api/` request has started for 1 s. The server is one
  uvicorn process started by `backend/scripts/e2e_stack.sh up`, on the same machine as the browser. **Best of three.**
  Times are for the evaluator's cloud container (4 vCPU Intel Xeon @ 2.1 GHz class); the bank machine will differ.
- **Warm:** the page has been opened once since the server started, then the server has been idle for 15 s.
- **After the Workbench:** `#/stewardship/workbench` is opened, its first data row appears, 2 s pass, then the named
  stage tab is clicked (for the cockpit: `#/stewardiq/cockpit` is opened in the same tab); page time counts from the
  click.
- **X and F:** the showcase's observations are all `simulated`. Before its first request the test picks a house
  company X with `aum_held_eur_m` of at least 1.0 in `GET /worklist?scope=house` and a numeric field F that appears in
  `GET /api/stewardship/studio/coverage/inputs` as `issuer.portfolio.F`, and appends an observation of F for X with
  `source` `internal_api`, dated the latest holdings snapshot date (as `workbench-review-fixes` AC-3 does), so X's F
  is a real value.
- **Restart answer:** the same request made after `bash backend/scripts/e2e_stack.sh restart-api`, once the answer
  under test has been recorded.
- **Another process:** a process other than the API server, for example the test itself.
- Each holdout row puts back what it changed (files, rows, settings) when it ends, so rows run in any order.
- **Build line:** the INFO log line `House universe built: <n> companies in <t> s`. **Check line:** the DEBUG log line
  `Input check: <n> observation files in <t> s`.
- **Store S:** a portfolio store with 2 held companies and 2 observation files, source `portfolio`, for unit rows.
- **Cleared:** the kept build is dropped, so the next call builds (the builder adds the means, for tests only).
- **`main` answers:** the answers `main` (with #544 and #548) gives for the same store and request, recorded as test
  fixtures before the build starts; fields holding the current time are left out of the comparison.
- **The eight endpoints:** `GET /api/stewardship/worklist?scope=house`, `/worklist/scopes`, `/selection`, `/tiers`,
  `/decision-inputs`, `/studio/coverage/inputs`, `/studio/monitoring/triggers` and `/streams/house/flow`.

Out of scope for the speed rows: `#/stewardship/program` (Client program, a client stream's page; not measured).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Showcase data; warm | `#/stewardship/monitoring` is opened alone | Page time under 6 s | evaluator |
| AC-2 | Showcase data; warm | `#/stewardship/selection` is opened alone | Page time under 6.5 s | evaluator |
| AC-3 | Showcase data; warm | `#/stewardship/checkpoint` is opened alone | Page time under 6.5 s | evaluator |
| AC-4 | Showcase data; warm | Each of `#/stewardship/drafting`, `#/stewardship/voting`, `#/stewardship/tracking`, `#/stewardship/client_policy` and `#/stewardship/reporting` is opened alone | Each page time is under 4 s | evaluator |
| AC-5 | Showcase data; warm | `#/stewardship/workbench` is opened alone | The best of three times from starting navigation until the first data row is visible is under 3 s | evaluator |
| AC-6 | Showcase data; warm | `#/stewardship/workbench` is opened alone | Page time under 7 s | evaluator |
| AC-7 | Showcase data; warm | `#/stewardiq/cockpit` is opened alone | Page time under 1.5 s | evaluator |
| AC-8 | Showcase data; warm | Selection is clicked after the Workbench | Page time under 3.5 s | evaluator |
| AC-9 | Showcase data; warm | Monitoring is clicked after the Workbench | Page time under 4 s | evaluator |
| AC-10 | Showcase data; warm | The cockpit is opened after the Workbench | Page time under 2 s | evaluator |
| AC-11 | Showcase data; `GET /api/stewardship/studio/coverage/inputs` called once | Another process appends an observation of F for X with a different value, `source` `internal_api`, dated the latest holdings snapshot date (`PortfolioStore.append_observation`); then the same GET | X's `issuer.portfolio.F` equals the appended value | holdout |
| AC-12 | As AC-11, before the append | Another process writes a copy of X's F file in which the `value` of the observation that X's `issuer.portfolio.F` showed in the first answer is changed to a different value of the same length, gives the copy the old file's mtime with `os.utime`, and moves it over the old file with `os.replace`; then the same GET | X's `issuer.portfolio.F` equals the changed value | holdout |
| AC-13 | Showcase data; `GET /api/stewardship/universe` called once | Another process takes one portfolio P's latest snapshot, adds one holding (`market_value_eur` 1,000,000) of a security whose `company_id` is C, a `legacy_companies` company not held before (if none exists, the test first adds one company and one security with `save_company` and `save_security`, before the first GET), and saves it for P dated one day after P's latest date (`PostgresPortfolioStore.save_snapshot`); then `GET /universe` | `issuers` is the first answer's `issuers` plus 1 | holdout |
| AC-14 | As AC-13 | The same change; then `GET /api/stewardship/worklist?scope=house` | One row has `issuer_id` C | holdout |
| AC-15 | Showcase data; `GET /api/stewardship/worklist?scope=house` called once | Another process doubles `market_value_eur` of every `holdings` row of X's securities in each portfolio's latest snapshot, with SQL `UPDATE`; then the same GET | X's `aum_held_eur_m` differs from the first answer and equals the restart answer | holdout |
| AC-16 | As AC-15 | Another process sets X's `name` in `legacy_companies` to `Renamed Test Co` with SQL `UPDATE`; then the same GET | X's `company` is `Renamed Test Co` | holdout |
| AC-17 | Showcase data; `GET /api/stewardship/studio/coverage/inputs` called once | Another process sets X's entry in `issuer_sectors.json` to `{"sector": "Test Sector"}`, keeping every other entry (a missing file counts as `{}`), written to a temporary file, then `os.replace`; then the same GET | X's `issuer.sector` is `Test Sector` | holdout |
| AC-18 | Showcase data; `GET /api/stewardship/universe` called once | Another process replaces `<stewardship_streams_dir>/house/universe.json` with `{"source": "sample", "set_by": "test", "set_at": null}` (`os.replace`); then `GET /universe` | `source` is `sample`, and `issuers` equals the number of issuers in `sample_meetings.json` | holdout |
| AC-19 | Showcase data; `GET /api/stewardship/universe` called once | `PUT /api/stewardship/universe` `{"source": "sample"}`; then `GET /universe` | `issuers` equals the number of issuers in `sample_meetings.json` | holdout |
| AC-20 | Store S; one `house_universe()` call done | `house_universe()` again, nothing changed | Exactly one build line in the log over both calls | unit |
| AC-21 | Store S, nothing built yet; the build slowed by 1 s with a stub | 8 threads call `house_universe()` at once | Exactly one build line; the 8 results are equal | unit |
| AC-22 | Store S; the build slowed by 1 s with a stub and made to raise `RuntimeError("boom")` the first time | 4 threads call `house_universe()` at once; after they return, one more call | Each of the 4 calls raises `RuntimeError("boom")`; the later call returns 2 issuers; exactly one build line | unit |
| AC-23 | Store S; the observation check stubbed to wait 1 s after it has read every file's stat, before it returns | Thread A calls `house_universe()`; 0.5 s later, while A's check waits, an observation with a new value is appended to one file, then thread B calls `house_universe()` | B's result shows the appended value | unit |
| AC-24 | Store S; one call done | 6 threads call `house_universe()` at once, nothing changed | At most 2 check lines are logged during the 6 calls | unit |
| AC-25 | Store S | A caller sets `fields["probe"] = 1` on the first issuer of its result; then `house_universe()` again | The new result's first issuer has no `probe` key | unit |
| AC-26 | Store S (source `portfolio`); then, separately, Fixture W of the parent spec `2026-11-13-stewardship-priority-worklist-design.md` (source `sample`) | Each of the eight endpoints is called once right after the kept build is cleared, then once more with nothing changed | Each pair of answers is equal (same rows, same order, same values) | unit |
| AC-27 | Store S; `house_universe()` called once | A decision snapshot covering issuer I is published to the decision store; then `load_sample()` | I's `fields` has that snapshot's `decision.<framework_id>.tier` | unit |
| AC-28 | Store S; one `house_universe()` call done | Each of the eight endpoints is called once, one after the other | Exactly one check line is logged per request | unit |
| AC-29 | Showcase data; warm | `#/stewardship/monitoring`, `selection`, `checkpoint`, `drafting`, `voting`, `tracking`, `client_policy`, `reporting`, `workbench` and `#/stewardiq/cockpit` are opened in that order, 3 rounds | The API process's `VmRSS` (from `/proc/<pid>/status`) after the third round is at most 50 MB above its value after the first round | evaluator |
| AC-30 | Store S; `house_universe()` called once | An observation with a new value is appended to one file; `store.latest_observation` is called for that file directly (as the Workbench columns do); then `house_universe()` | The result shows the appended value | unit |
| AC-31 | Store S; `house_universe()` called once | Another process changes one row of each in turn of `securities`, `security_resolutions` and `portfolios`; adds an observation file; removes one; each followed by `house_universe()` | After each change: one more build line, and the result equals a build made after the kept build is cleared | unit |
| AC-32 | Store S with source `sample`; `house_universe()` called once | Another process rewrites the sample file with one issuer fewer (`os.replace`), then `house_universe()` | The result has one issuer fewer than the first | unit |
| AC-33 | Store S | `house_universe()`, then a change to one observation file, then `house_universe()` (a rebuild) | No file under `<portfolios_dir>`, `<stewardship_streams_dir>` or the folder of `identifier_map_path` was created or changed by the two calls (modification times and listing compared before and after, the observation file the test changed excepted) | unit |
| AC-34 | Showcase data; `arp showcase load` run with the build installed | A restart (`e2e_stack.sh restart-api`), then `#/stewardship/workbench` is opened; done 3 times (`workbench-review-fixes` AC-2) | The median time until the first data row is visible is under 5 s | evaluator |
| AC-35 | Showcase data; warm | `#/stewardship/workbench` is opened 5 times, each a full reload (`workbench-review-fixes` AC-1) | The median time until the first data row is visible is under 3.5 s, and each time the page shows 100 rows and page controls | evaluator |
| AC-36 | Store S, nothing built yet; the build stubbed to pause 1 s after the check | Call 1 builds; during its pause an observation with a new value is appended to one file; after call 1 returns, call 2 runs with no further change | Call 2 logs one more build line (2 in all), and its result shows the appended value | unit |
| AC-37 | Store S built | `portfolios_dir`, `stewardship_streams_dir` and `identifier_map_path` are pointed at new folders (database unchanged; S's observation files copied there), the new `issuer_sectors.json` giving one of S's companies `{"sector": "S2 Sector"}`; then `house_universe()` | One more build line; that company's `sector` is `S2 Sector` | unit |
| AC-38 | Store S (source `portfolio`) and Fixture W (source `sample`) | Each of the eight endpoints is called once, with the build installed | Each answer equals the `main` answer | unit |
| AC-39 | Store S; `observations_latest.json` written in the test by `save_latest_observations` after Store S's files exist; its `format` field set to the value `main`'s (with #544) `_latest_format()` returns, recorded as a fixture before the build starts | The server starts with the build installed | When the start-up fill has finished, `observations_latest.json` has the same content and mtime as before the start (the fill took it as valid and did not write it again) | unit |
| AC-40 | Store S with source `sample`; one `house_universe()` call done | A caller sets `fields["probe"] = 1` on the first issuer of its result; then `house_universe()` again | The new result's first issuer has no `probe` key | unit |
| AC-41 | Store S with two holdings snapshot dates; `house_universe()` called once (a kept build of the latest date exists) | The monthly run (`portfolio/monthly_run.py`) for the earlier month | The universe and held ISIN map it uses equal the `main` answers for that month | unit |

Must not change: `workbench-review-fixes` AC-1 to AC-10 (Workbench speed and the observation cache's freshness): its
hidden rows run through `Holdout: full`, its unit rows in CI, its warm row is AC-35 here and its restart row AC-34.
Every answer equals `main`'s (AC-38) and a reused answer equals a fresh one (AC-26); overlays stay read fresh (AC-27);
the monthly run is unchanged (AC-41).

Delivered by one PR, `stewardship-house-universe-cache` (no `Rows:` line).
