# Showcase load: read each observation file once per run

Slug: showcase-load-read-once

Risk: `risk:normal`. Size S, 1 PR. No stored data format changes: no file or table is written differently.

Status: **waiting for the owner's approval** (16 Nov 2026).

## Why

One `arp showcase load` takes about 142 s, and the showcase database must be rebuilt before the demo on about
27 Nov 2026 (`demo/showcase/README.md`, "Rebuild"). Two CI tests in `backend/tests/test_demo_seed_curated_keys.py`
each run a full load (about 630 s together in CI), which keeps the backend check near its time target.

Most of that time is spent reading the same small files again and again.

## What was measured

On `main` at `db0fe3b`, in a cloud container, one load into an empty test database and an empty data folder:

| | Result |
|---|---|
| Three loads, no profiler | 146.8 s, 148.3 s, 142.2 s (best: **142.2 s**) |
| Observation files written | 81,216 |
| Times an observation file is opened and parsed | 1,512,024 (each file about 19 times) |
| Share of the load spent in the six monthly runs | 69 % |
| Share spent appending the observations (`_append_new`) | 15 % |

Inside a monthly run, three steps read every file: the climate rows (`bi/published.py` `climate_metric_rows`), the
company profile rows (`profile_rows`) and the stewardship universe (`stewardship/universe.py` `from_portfolio`).

Two throwaway trials, both reverted, both with outputs identical to `main`:

| Trial | One load | API server after its start-up fill |
|---|---|---|
| A. Keep every parsed file in the server-wide cache of #491 | 94.5 s (66 %) | 516 MB instead of 308 MB; start-up fill 6.4 to 6.9 s instead of 4.8 s; the Workbench's house-universe step, warm, median 1.2 s instead of 0.9 s |
| B. Read each file once per run, keep nothing afterwards | **78.8 s (55 %)** | unchanged (the code the server runs is not touched) |

## Goals

1. One showcase load is faster: the best of three is at most 70 % of `main`'s best of three (AC-2).
2. The outputs of a load are identical before and after (AC-1).
3. A monthly run never shows a value older than its file at the start of the run; inside `arp showcase load`, at
   the point the load wraps its store, which is after its last observation is written (AC-3, AC-5).

## Non-goals

- Faster appends. The load appends 170,046 observations one locked write at a time (15 % of a load). Follow-up.
- Faster Postgres writes in the import and in `publish_rows` (about a quarter of what is left). Follow-up.
- Any change to the Workbench, its cache or its compact file `observations_latest.json`.
- Moving observations into the database (owner decision of 15 Nov 2026 in `workbench-review-fixes`: not before 27 Nov).

## Anti-goals

- A computed value that differs from `main` (AC-1).
- A slower or larger API server outside a running "Run now" request (AC-6: the files the server's read path lives
  in are not edited). During such a request the server holds the parsed files, about 110 MB on the showcase data,
  and releases them when the request ends.
- A collision with the Workbench speed PR of `workbench-review-fixes`, which is being built and edits
  `portfolio_store.py`, `universe.py`, `api/main.py`, `process.py` and `showcase/load.py` (AC-6).
- A weakened or deleted test (AC-7).

## Approaches considered

- **A. Widen the cache of #491 so it keeps each file's whole history, for the life of the process.** This is the
  reuse the item asked for, and every reader would benefit without a change. Not chosen, on the measurements above:
  the cache of #491 keeps one latest value per file for one date; the monthly run needs each file's full history,
  for six different dates and with a second rule (source priority). Keeping whole files in the server costs about
  210 MB, slows the Workbench step that the speed PR is trying to bring under 3.5 s, and edits the same function
  that PR is editing.
- **B. A read-once view of the store for the length of a run (chosen).** `run_month` reads through a thin wrapper
  that remembers each observation file the first time it is read. `arp showcase load` creates one wrapper for its
  six monthly runs, so each file is parsed once per load. When the run ends the wrapper is dropped and nothing stays
  in memory. It is the fastest of the two, it cannot go stale across runs, and it touches none of the server's read
  path.
- **C. The compact file `observations_latest.json`.** It will hold one latest value per file as of one date. The
  monthly run needs other dates and the source-priority rule, so it cannot be answered from that file. Not usable.
- **D. Only stop the climate rows from resolving the same values once per portfolio.** Cuts 1.5 million reads to
  about 1.1 million. Not enough on its own, and not needed once B is in.

B adds a small new piece, where the item asked for reuse. The owner decides this with the approval; if A is wanted
instead, see "If the owner picks A" at the end.

## Design (approach B)

1. A class `ObservationsReadOnce` in `backend/arp/portfolio/monthly_run.py`. It wraps a portfolio store and passes
   every call through, except:
   - `load_observations(company_id, field_id)`: the first call reads the file through the wrapped store; later calls
     return a new list of the same observations.
   - `latest_observation(company_id, field_id, as_of)`: answered from the remembered file with the rule of
     `PortfolioStore.latest_observation` (on or before `as_of`; a real value before a simulated one; the last such
     row). The rule is written a second time here on purpose, so `portfolio_store.py` stays untouched while the
     Workbench speed PR is open; AC-4 keeps the two equal. Merging them into one function is a follow-up for after
     that PR.
   - `append_observation(obs)`: appends through the wrapped store and forgets that file, so the next read sees it.
2. `run_month` wraps the store it is given, unless it is already an `ObservationsReadOnce`. A blocked run reads no
   observation and is unchanged.
3. `showcase.load.load` wraps its store once, just before the six monthly runs (after the `esg` and `scores` steps
   have written the observations).
4. A script `backend/scripts/showcase_load_check.py` that the builder and any reviewer use for AC-1 and AC-2:
   - `run <outdir>`: refuses to start unless `ARP_TEST_POSTGRES_DSN` is set. Before it imports the settings it sets
     `ARP_POSTGRES_DSN` to that test DSN and `ARP_BLOB_STORE_DIR` to `<outdir>/blobs`, as the `pg` fixture in
     `backend/tests/conftest.py` does, so the load's company registration also goes to the test database. It
     empties that database's tables, runs one load the way the `pg_store` fixture of
     `test_demo_seed_curated_keys.py` does with its data folders under `<outdir>/data`, prints
     `load seconds: <n>` (timed around the `load()` call only, not the emptying or the dump), and writes every
     output to `<outdir>/dump.json`.
   - `compare <outdirA> <outdirB>`: prints one line per table and file and a last line `RESULT: IDENTICAL` or
     `RESULT: DIFFERENT`; exit code 0 or 1.

Callers that are not changed and get the faster run through `run_month`: `POST /api/portfolio/monthly-run`,
`arp portfolio` monthly run, the monitoring scheduler.

Cost: the load process peaks at about 896 MB instead of 788 MB while it runs. The API server holds the wrapper, and
with it about 110 MB of parsed files on the showcase data, only while a "Run now" request is running.

## Order with the Workbench speed PR

This PR edits `monthly_run.py` (adds the class and the wrap in `run_month`) and two lines of `showcase/load.py`
(an import and the wrap). The speed PR also edits `showcase/load.py`
(it writes the compact file when the load finishes). Whichever merges second merges `main` in first; the two edits
are in different places of the function.

## Left to the builder

- The inner layout of `dump.json`.
- Test names and where the new unit tests live.

## Acceptance

Words used below:

- **A load:** `arp.showcase.load.load` on a `PostgresPortfolioStore` over an emptied test database and empty data
  folders, with `data/holdings` and `data/simulated/esg_simulated.csv`, as `showcase_load_check.py run` does it.
- **Outputs of a load:** the lines the load echoes, every row of every Postgres table, and every file under the
  data folders.
- **Noise fields:** what two loads of the same commit already differ in, and the only fields left out of a
  comparison: `companies.id`, `companies.created_at`, `company_identifiers.id`, `company_identifiers.company_id`,
  `securities.company_uuid`, `holdings.id`, and the `at` field of each line in `governance/events.jsonl` and
  `triggers/events.jsonl`. `bi_published` is compared on (`dataset`, `month`, `row`). The list was confirmed on
  three loads of `main` at `db0fe3b`; `holdings.company_id` is empty in a showcase load and is compared.
- **Demo store:** the `store` and `settings` fixtures of `backend/tests/test_monthly_run.py` (the seeded demo
  dataset on a file `PortfolioStore`), with the holdings loads and the `default` ESG load of `2026-09` recorded `ok`.
- **`unit` with pasted output:** AC-1, AC-2, AC-6 and AC-7 compare two commits, which the app started by
  `e2e_stack.sh up` cannot do, so they are `unit` rows. For these four the builder runs the command in the row and
  pastes its full output in the PR description (for AC-2: the six `load seconds` values); a reviewer can run the
  same command again.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | One load on `main` and one on the PR head, same machine, each with `showcase_load_check.py run` (the script file copied from the PR head for the `main` run) | `showcase_load_check.py compare <main outdir> <PR outdir>` | Last line `RESULT: IDENTICAL`, exit code 0: all 81,216 observation files are byte-equal, the 174,492 `bi_published` rows are equal, and every other table, file and echoed line is equal outside the noise fields | unit |
| AC-2 | Three loads on `main`, then three on the PR head, same machine, one after the other, nothing else running | The six `load seconds` values printed by `showcase_load_check.py run` are compared | The smallest of the PR's three is at most 70 % of the smallest of `main`'s three | unit |
| AC-3 | Demo store; `run_month` for `2026-09` has run once | For one seeded company X an observation of `climate_carbon_intensity` with `source` `internal_api`, `value` `987654.5`, `observed_at` `2026-09-30T23:59:59+00:00` is appended with `store.append_observation`; then `run_month` for `2026-09` runs again in the same process | The `rows` the second run passes to `publish_rows("company_profile", "2026-09", rows)`, captured as `_spy` in `test_monthly_run.py` does, hold `value` `987654.5` in the row for X and `climate_carbon_intensity` | unit |
| AC-4 | A file `PortfolioStore` and an `ObservationsReadOnce` over it; five observation files: (a) only simulated rows, (b) a real row followed by a later simulated row, (c) two real rows, (d) one row dated after the `as_of` asked for, (e) no file | `latest_observation` is called on both for each file, once with `as_of` `2026-09-30` and once with no `as_of` | The two return equal observations in all ten calls (`None` for (e), and for (d) with the `as_of`) | unit |
| AC-5 | An `ObservationsReadOnce` over a file `PortfolioStore`; `load_observations` for (X, F) has returned one observation | A second observation for (X, F) is appended through the `ObservationsReadOnce`; then `load_observations` for (X, F) is called on it | It returns two observations, the appended one last | unit |
| AC-6 | The PR's diff against `main` | `git diff --stat origin/main...HEAD -- backend/arp/storage backend/arp/stewardship backend/arp/api backend/arp/bi backend/arp/portfolio/datapoint_mapping.py backend/arp/portfolio/climate` | No output: none of these paths is changed | unit |
| AC-7 | The PR's diff against `main` | `git diff --numstat origin/main...HEAD -- backend/tests` | The deletions column (the second number) is 0 on every line | unit |
| AC-8 | An `ObservationsReadOnce` over a file `PortfolioStore`; `load_observations` for (X, F) has returned a list | The caller appends an item to that list; then `load_observations` for (X, F) is called again | It returns the file's observations without the item the caller added | unit |

Must not change: every existing test in `backend/tests` passes with no edit (AC-7), in particular
`test_monthly_run.py`, `test_showcase_load.py` (a second load changes nothing; a real value beats a simulated one)
and `test_demo_seed_curated_keys.py`; what a load computes (AC-1); the readers of `PortfolioStore` and the Workbench
read path (AC-6).

Reported in the PR, not a pass/fail row: the CI durations of the two full-load tests in
`test_demo_seed_curated_keys.py`, before and after.

## If the owner picks A

The design becomes: `PortfolioStore.load_observations` keeps each parsed file per process and reads it again when
the file's inode, ctime, mtime or size changes; `latest_observation` reads through it. Then AC-2's limit is 75 %,
AC-4, AC-5 and AC-8 are asked of `PortfolioStore` itself, AC-6 is dropped, and a new row states the server cost
(about 210 MB more after the start-up fill). The PR must then wait for the Workbench speed PR, because both edit
`latest_observation`.
