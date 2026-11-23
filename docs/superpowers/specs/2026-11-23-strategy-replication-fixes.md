# Strategy Replication fixes: approve works, edits survive, data files are checked

Status: **draft, waiting for the owner's approval**
Slug: `strategy-replication-fixes`
Risk: this spec PR is `risk:low`. The build is 3 PRs, each `risk:normal` (no `risk:high` path is touched).
Size: M, delivered as three slices of size S (see `## Slices`).
Checked against `origin/main` `0ce947d`.
Source: bug-list item 1 (`H1`, `H2`, `M9`, `M29`, `LM4`, the replication part of `M2`).

## Decisions for the owner

Approving this spec accepts both as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | **The server never shows or accepts its own file paths on this screen.** Today an upload answers with the full server path of the stored file (`/…/runs/<id>/prices.csv`), and the backtest reads whatever path the request names, so a signed-in user can point it at any file on the server. After this change an upload answers with a file name (`prices.csv`), and a backtest only reads files uploaded for that same spec. This was not on the bug list; the code reading for this spec found it. | Yes (AC-14 to AC-18, AC-34 to AC-37, AC-60, AC-61) | Uploads keep answering with the full path and the backtest keeps reading any path. AC-14 to AC-18 then expect `ref` to be a path ending in the stated file name, AC-37 expects a detail ending in `prices.csv: no column(s) for ['ZZZ']`, AC-35, AC-36 and AC-61 are struck, and the wider fix moves to bug-list item 3 (server file paths, `risk:high`). |
| D2 | **A data file is checked when it is uploaded, and the screen says what arrived.** Today the screen shows "Uploaded." for any file, and a broken file only fails later, at the backtest, with a raw parser message. After this change a file that cannot be used is refused at upload with the reason and the row, a good file is confirmed as "Uploaded prices.csv: 15 tickers, 48 rows, 1965-01-01 to 1968-12-01.", and an empty tickers box is filled with the tickers from the file. | Yes (AC-15, AC-25 to AC-33, AC-63, AC-44, AC-45, AC-47) | Files are stored unchecked as today. AC-15, AC-25 to AC-33, AC-63, AC-45 and AC-47 are struck, and AC-44 expects `Uploaded p48.csv.` |

## Why

The antigravity patch review (23 Nov 2026) found that Strategy Replication cannot be demonstrated on `main`:

- **H1.** "Approve spec" always fails with 422. The screen sends no body, the route requires one. Nothing after
  the approval can be reached.
- **H2.** Approving a spec throws the user's edits away. The current spec is read from the latest decision only,
  and an approval carries no spec, so the screen falls back to the first draft and the backtest runs on it.
- **M9.** A backtest whose data file is missing is a 500.
- **M29.** A failed upload is an unhandled error: nothing is shown. Loading another spec keeps the previous
  spec's editor text, uploads and results. The drawdown chart shows `NaN%` when the first period loses 100%.
- **LM4.** The patch's fix for characteristic names refuses names with spaces, which model-drafted specs use
  ("book to market"). A name with a slash ("B/M") cannot be uploaded even today: the route answers 404.
- **M2 (replication part).** The two data uploads read a file of any size into memory.

## What the user can do afterwards that they cannot do today

- Approve a spec sheet and reach the backtest.
- Edit a spec, by hand or by instruction, approve it, and backtest exactly the edited spec.
- See why an upload failed, next to the file input, and try again without reloading the page.
- See what a data file holds the moment it is uploaded, and get its tickers filled in.
- Upload a characteristic file whatever the characteristic is called, including "book to market" and "B/M".
- Load another spec and get a clean screen for it.
- Read every error on this screen without a server path in it.

## Three versions

1. Safe: the six listed fixes and nothing else. Approve answers 200, the last edit survives, a missing file is a
   400, uploads are capped, names are slugged, the screen catches upload errors and resets on a spec change.
2. Strong: plus D1. No server path leaves or enters through this screen, and a backtest reads only its own
   spec's uploads.
3. Most ambitious, specified here: plus D2. Files are checked on arrival, the screen reports what arrived and
   fills in the tickers.

The next step up is an approval that names the exact revision it approved, with a diff between revisions in the
history. It needs a decision on revision ids in the review store, which five other routers share.

## What exists today

- Routes in `backend/arp/api/routers/replication.py`, all under `/api/replication`:
  `POST /specs`, `GET` and `PUT /specs/{id}`, `POST /specs/{id}/revise`, `POST /specs/{id}/approve`,
  `POST /specs/{id}/datasets/prices`, `POST /specs/{id}/datasets/characteristics/{name}`,
  `POST /specs/{id}/backtest`, `GET /runs/{run_id}`.
- A spec draft is a run of type `strategy_replication_spec` with one `draft` result row. Edits (`PUT`, `revise`)
  and approvals are decision rows for item key `spec` in the review store; edits carry the whole spec as
  `edited_value`, approvals carry none. `_current_spec` reads only the latest decision.
- Uploads write `prices.csv` and `characteristics_<name>.csv` into the spec's run folder
  (`run_store.run_dir(spec_run_id)`) and answer `{"ref": "<absolute path>"}`. The backtest opens
  `Path(prices_ref)` and each path in `characteristics_refs` as given.
- `settings.max_upload_bytes` (default 100,000,000) and the 413 text
  `File is larger than the <n> MB upload limit.` are used by `routers/documents.py` and five other routers.
- The screen is `frontend/src/pages/StrategyReplication.tsx` (`#/strategyReplication`): `ProposeStage`,
  `ReviewStage`, `BacktestStage`, `ResultsView`. The client calls are in `frontend/src/api/client.ts`
  (`approveSpecDraft` sends no body). API errors reach the screen as `<status>: <detail>`.
- The CLI (`arp replicate …`) does not use these routes and does not change.

## Goals

1. Approve works from the screen and from any client, with or without a body (AC-1 to AC-4, AC-39, AC-41).
2. The current spec is always the last edit, whatever was decided after it (AC-5 to AC-10, AC-40, AC-59, AC-62).
3. The two data uploads are capped at `max_upload_bytes` (AC-19 to AC-22).
4. Any characteristic name of 1 to 100 characters can be uploaded; only the stored file name is slugged
   (AC-16 to AC-18, AC-23, AC-24, AC-38, AC-64).
5. No server path in any answer of the upload and backtest routes, and no file outside the spec's own uploads
   is read (D1: AC-14, AC-34 to AC-37, AC-60, AC-61).
6. A file the backtest cannot use is refused at upload with a reason (D2: AC-25 to AC-33, AC-63).
7. The screen shows upload progress, success and failure, and never stays stuck (AC-42 to AC-51, AC-65 to AC-69, AC-73, AC-78, AC-79).
8. Loading or drafting another spec resets the review and backtest parts (AC-52 to AC-55, AC-70 to AC-72, AC-74, AC-75, AC-77).
9. The drawdown chart never shows `NaN` (AC-56 to AC-58).

## Non-goals

- The app-wide upload cap and `universe_path` confinement (bug-list item 3), and every other bug-list item.
- Backtest maths, spec extraction, paper discovery, the sanity check and the regime report.
- The CLI, and the `strategy_spec` / `strategy_backtest` plan steps of the `agent-research-examples` spec.
- A redesign of the screen. Only the parts named under Design change.
- Uploads for the components of a composite spec. The screen keeps offering one characteristic file.

## Anti-goals

- Approving must never change the spec (AC-5, AC-11).
- A characteristic name must never be refused for the characters it contains (AC-16, AC-17).
- A refused upload must never replace or remove a file stored earlier (AC-22, AC-32).

## Design

### Approve (H1)

`POST /specs/{id}/approve` takes an optional body. No body, `{}` and a body with unknown keys all approve; the
reviewer is always the signed-in user. The client sends `{}`. `frontend/src/api/openapi.json` and
`schema.gen.ts` are regenerated (`.claude/CLAUDE.md`, API contract).

### Current spec (H2)

The current spec of a draft is the `edited_value` of the newest decision for item `spec` that has one. With no
such decision it is the `draft` row. "Approved" stays what it is today: the latest decision is `approve`.
This covers `GET`, the answer of `PUT`, `revise` and `approve`, the input of `revise`, and the backtest.

### Uploads (M2, LM4, D1, D2)

Both upload routes, in this order:

1. **Name** (characteristics only). The route takes the rest of the path as the name, so a name may hold `/`.
   An empty name is a 400 `Characteristic name is empty.` A name longer than 100 characters is a 400
   `Characteristic name is longer than 100 characters.`
   The stored file is `characteristics_<slug>.csv`, where the slug is the name with every character outside
   `A-Z a-z 0-9 _ -` replaced by `_`. The name itself is not changed or stored.
2. **Size.** More than `settings.max_upload_bytes` bytes is a 413 with the house text
   `File is larger than the <max_upload_bytes // 1,000,000> MB upload limit.`
3. **Content (D2).** The file must be UTF-8 text (a leading byte order mark is accepted) in the wide layout the
   backtest reads: a header row, the first column the date, one further column per ticker, one row per period.
   The first failure, reading top to bottom and left to right, is a 400 whose detail is `Not a usable CSV: `
   followed by one of:

   | Failure | Rest of the detail |
   |---|---|
   | not UTF-8 | `not UTF-8 text.` |
   | zero bytes, or no header row | `the file is empty.` |
   | the header has fewer than two non-empty names | `needs a date column and at least one ticker column.` |
   | no row after the header | `no data rows.` |
   | the first 10 characters of a date are not a calendar date `YYYY-MM-DD` | `row <r>: date "<value>" does not start with YYYY-MM-DD.` |
   | a non-blank cell that Python's `float()` refuses | `row <r>, column <ticker>: "<value>" is not a number.` |

   `<r>` is the line number in the file, counted from 1, so with no empty lines the header is row 1 and the
   first data row is row 2. Empty lines are skipped and not counted in `rows`. A file with no non-empty line
   is `the file is empty.` Columns with an empty header name, and cells beyond the header's width, are ignored
   and not checked. A blank cell means "no data" and is accepted, as today. A date may carry more after its
   first 10 characters (`1965-01-31 00:00:00`).
4. **Store and answer.** Only now is the file written, replacing an earlier upload of the same file name. The
   answer is 200:

   ```json
   {"ref": "prices.csv", "tickers": ["T0", "T1"], "rows": 48, "first_date": "1965-01-01", "last_date": "1968-12-01"}
   ```

   `ref` is the stored file name (D1). `tickers` are the header's ticker names in file order, `rows` the number
   of data rows, `first_date` and `last_date` the first and last row's date, first 10 characters (D2). Both
   routes get a response model, and a line in `frontend/src/api/contract.ts`.

### Backtest (M9, D1)

The route checks the approval first (403, as today), then the files. `prices_ref` and each value of
`characteristics_refs` must be the `ref` an upload for this spec returned:
exactly `prices.csv`, or a `characteristics_<slug>.csv`, with the file present in the spec's run folder. Any
other value (another name, a path with a separator, an absolute path, a file that is not there) is a 400
`Data file not found: <name>`, where `<name>` is the text after the last `/` of the value sent. The same
answer for "missing" and "not allowed" tells a caller nothing about which files exist on the server.

Every other 400 of this route that names a data file names it by file name only, for example
`prices.csv: no column(s) for ['ZZZ']`.

If the `strategy_backtest` plan step (`agent-research-examples`, slice 2) is on `main` when slice 2 of this
spec is built, it resolves its `prices_ref` the same way. None of that spec's rows change: they stub the
backtest.

### Screen (M29)

All in `frontend/src/pages/StrategyReplication.tsx`.

- **Upload state, per file input.** Under each file input sits one status line,
  `[data-upload-status="prices"]` or `[data-upload-status="characteristics"]`, and, after a failure, one alert
  `[role="alert"][data-upload-error="prices"]` or `[…="characteristics"]`. A status line is always in the page
  while its file input is shown, with empty text when there is nothing to report.
  - While the request runs: the status line reads `Uploading <file name>…`, and both file inputs and "Run
    backtest" are disabled.
  - On success: `Uploaded <file name>: <n> tickers, <m> rows, <first_date> to <last_date>.` (`1 ticker`,
    `1 row` in the singular). The alert of that input is removed.
  - On failure: the status line of that input is empty and the inputs are enabled again. For a non-2xx answer
    the alert shows the error text as the client reports it
    (`413: File is larger than the 100 MB upload limit.`); with no answer it reads
    `Upload failed: no answer from the server.`
  - A failed price upload drops the price file the screen held: "Run backtest" is disabled until a price
    upload succeeds. A failed characteristics upload drops only the characteristics file: "Run backtest" stays
    enabled if a price file is held, and the backtest is then sent without a characteristics ref.
  - After every upload attempt the file input's value is cleared, so the same file can be picked again.
  - `<file name>` is the name of the file the user picked.
- **Tickers.** After a successful price upload, a tickers box that is empty or holds only white space is set to
  the answer's tickers joined by `, `. A box with text is left alone (D2).
- **Another spec.** When the spec shown changes to one with a different `spec_run_id` ("Resume", or "Draft spec
  sheet"), the review part and the backtest part start fresh: the JSON editor holds the new spec, the
  instruction box is empty, no error of the previous spec is shown, no upload is shown, the tickers, benchmark
  and out-of-sample boxes are empty, and no result is shown. "Resume" with the id already shown reloads the
  JSON editor from the answer and leaves the backtest part as it is.
- **Drawdown.** Depth at a period is `(1 - index / peak) × 100`, where `peak` is the highest index so far. While
  `peak` is 0 or below, depth is 0.

After the UI change the builder screenshots the page and runs `/impeccable:impeccable audit`
(`.claude/CLAUDE.md`).

## Supersedes

No row of an earlier spec is retired. The rows of `agent-research-examples` that name `prices_ref` (AC-20,
AC-22, AC-24) pass a bare file name and stub the backtest.

Existing tests the builder has to change, and list in the PR: in `backend/tests/test_api_replication.py`,
`test_full_flow_backtest_then_results_then_regime_report` and
`test_trigger_sanity_check_appends_and_is_returned_on_next_fetch` pass a `prices_ref` outside the spec's run
folder. They upload the file through the route instead (D1). No assertion is removed.

## Acceptance

API rows (AC-1 to AC-38, AC-59 to AC-64) send HTTP requests to the app started by `backend/scripts/e2e_stack.sh up` with
`ARP_STANDINS_DIR` set (dev auth, signed in, role `approver`), unless "Checked by" is `unit`. Screen rows
(AC-39 to AC-58, AC-65 to AC-79) run in headless Chromium at 1440 × 900 on `#/strategyReplication`.

Terms used in the rows:

- All routes are under `/api/replication`. **`<id>`** is the `spec_run_id` of the row's spec.
- **Draft D** is a fresh spec draft from `POST /specs`, with the model calls answered by the stand-ins
  `model/StrategySpecDraft.json` and `model/SpecVerifierOutput.json` (`agrees: true`). D has `strategy_name`
  `Draft D`, `signal_type` `momentum`, `holding_period_months` 1 and `rebalance_frequency` `monthly`. Not edited,
  not approved.
- **Spec M** is draft D after a `PUT /specs/<id>` of D's own spec with these fields set: `signal_type`
  `momentum`, `formation_period_months` 6, `holding_period_months` 6, `rebalance_frequency` `monthly`,
  `num_portfolios` 4, `long_leg_portfolio` 1, `short_leg_portfolio` 4, `weighting` `equal`,
  `sample_period_start` `1965-01-01`, `sample_period_end` `1969-12-31`, `characteristic_name` null.
  **Approved M** is spec M after `POST /specs/<id>/approve`.
- **Approved V** is draft D after a `PUT` of the spec `_value_spec()` of
  `backend/tests/test_replication_pipeline.py` with `characteristic_name` `book to market`, then approve.
- **P48** is a price file named `p48.csv` as `_write_price_csv` of `backend/tests/test_api_replication.py`
  writes it: header `date,T0,…,T14`, 48 monthly rows from `1965-01-01` to `1968-12-01`, positive prices.
  **PV** and **CV** are the price file and the characteristics file of
  `test_run_replication_value_strategy_end_to_end` in `backend/tests/test_replication_pipeline.py`: PV has the
  header `date,WIN1,WIN2,LOSE1,LOSE2,BENCH` and 48 monthly rows from `1998-01-01`; CV has the header
  `date,WIN1,WIN2,LOSE1,LOSE2` and the same 48 dates.
- **Upload X to prices** is `POST /specs/<id>/datasets/prices` with X as the multipart field `file`.
  **Upload X as `<name>`** is `POST /specs/<id>/datasets/characteristics/<name, percent-encoded>`.
- **Backtest(ref, tickers)** is `POST /specs/<id>/backtest` with `{"tickers": tickers, "prices_ref": ref}`.
  "All tickers" are the file's 15.
- **detail** is the `detail` string of the JSON error body.
- **Stubbed screen** means the test answers every request to `/api/replication/**` itself:
  - `GET /specs/run_a` and `GET /specs/run_b` answer `{spec_run_id, spec, approved, history: []}` with spec M
    under `strategy_name` `Alpha` for `run_a` and `Beta` for `run_b`, both `approved: true` unless the row says
    otherwise. In rows that name a characteristic, the spec also has `signal_type` `value` and
    `characteristic_name` `book to market`.
  - `POST /specs/<id>/approve` answers `{spec_run_id, spec, approved: true}` for that spec.
  - A successful upload answers
    `{"ref": "prices.csv", "tickers": ["T0", "T1", "T2"], "rows": 24, "first_date": "1965-01-01", "last_date": "1966-12-01"}`.
  - `POST /specs/<id>/backtest` answers `{"run_id": "run_r", "verdict": "replicated"}`, and `GET /runs/run_r` a
    valid `ReplicationRunDetail` whose in-sample periods have `long_return_pct` 0, `short_return_pct` 0 and the
    `long_short_return_pct` values `[10, -50, 20]` unless the row gives others.
  - **Load A** (or B): type `run_a` into "spec draft run ID" and press "Resume".
  - **Pick f.csv** is choosing a file named `f.csv` in the price file input. **Run** is: type `T0` into the
    tickers box if it is empty, then press "Run backtest".
  - **Ready A** is: A loaded, `T0` typed into the tickers box, then `f.csv` picked with a successful upload
    (the box stays `T0`), so "Run backtest" is enabled.
- **The backtest card** is the section headed "3. Run the backtest & review results"; **the review section**
  is the section headed "2. Review the spec sheet".

### Approve

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | draft D | `POST /specs/<id>/approve` with no body and no `Content-Type` | 200, `approved` is `true` | holdout |
| AC-2 | draft D | `POST /specs/<id>/approve` with body `{}` | 200, `approved` is `true` (must not change) | holdout |
| AC-3 | draft D | `POST /specs/<id>/approve` with body `{"reviewer": "mallory"}` | 200, `approved` is `true` (must not change) | holdout |
| AC-4 | spec M (one edit row in the history), then the approve of AC-3 | `GET /specs/<id>` | the last `history` row has `decision` `approve` and the same `reviewer` as the edit row before it (must not change) | holdout |

### Edits survive

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-5 | spec M with `holding_period_months` set to 12 by a second `PUT` | `POST /specs/<id>/approve` | the answer's `spec.holding_period_months` is 12 | holdout |
| AC-6 | after AC-5 | `GET /specs/<id>` | `spec.holding_period_months` is 12 and `approved` is `true` | holdout |
| AC-7 | after AC-5, approved with no body | `POST /specs/<id>/approve` again, with no body | the answer's `spec.holding_period_months` is 12 | holdout |
| AC-59 | after AC-7 | `GET /specs/<id>` | `history` has 4 rows | holdout |
| AC-8 | after AC-5 | `PUT` with `holding_period_months` 9, then approve | the approve answer's `spec.holding_period_months` is 9 | holdout |
| AC-9 | draft D; stand-in `model/StrategySpecRevisionDraft.json` whose output is D's spec with `rebalance_frequency` `quarterly`; `POST /specs/<id>/revise` with any instruction; approve | `GET /specs/<id>` | `spec.rebalance_frequency` is `quarterly` | holdout |
| AC-62 | approved M with `holding_period_months` 12 (AC-5); the stand-in of AC-9 | `POST /specs/<id>/revise` with any instruction | the last entry of the stand-ins' `calls.jsonl` with `name` `StrategySpecRevisionDraft` has a `prompt` containing `"holding_period_months": 12` | holdout |
| AC-10 | approved M with `holding_period_months` 12 (AC-5), P48 uploaded to prices | Backtest(the upload's `ref`, all tickers), then `GET /runs/<run_id>` | `spec.holding_period_months` is 12 | holdout |
| AC-11 | draft D, its spec read with `GET` | approve, then `GET` | `spec` equals the spec read before (must not change) | holdout |
| AC-12 | approved M | `PUT` with `holding_period_months` 3 | `approved` is `false` and `spec.holding_period_months` is 3 (must not change) | holdout |
| AC-13 | spec M, not approved | Backtest(`prices.csv`, all tickers) | 403 with detail `Spec is not approved -- approve it before running a backtest.` (must not change) | holdout |

### Uploads: names, size, answer

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-14 | spec M | upload P48 to prices | 200, `ref` is `prices.csv` | holdout |
| AC-15 | spec M | upload P48 to prices | the answer body is exactly `{"ref": "prices.csv", "tickers": ["T0", …, "T14"], "rows": 48, "first_date": "1965-01-01", "last_date": "1968-12-01"}`, tickers in file order | holdout |
| AC-16 | spec M | upload CV as `book to market` | 200, `ref` is `characteristics_book_to_market.csv` | holdout |
| AC-17 | spec M | upload CV as `B/M` (sent as `B%2FM`) | 200, `ref` is `characteristics_B_M.csv` | holdout |
| AC-18 | spec M | upload CV as `../../x` (sent as `..%2F..%2Fx`) | 200, `ref` is `characteristics_` + `______x` (six underscores, then `x`) + `.csv` | holdout |
| AC-19 | `max_upload_bytes` set to 1,000,000; spec M | upload a file of 1,000,001 bytes to prices | 413 with detail `File is larger than the 1 MB upload limit.` | unit |
| AC-20 | `max_upload_bytes` set to 1,000,000; spec M | upload a file of 1,000,001 bytes as `x` | 413 with detail `File is larger than the 1 MB upload limit.` | unit |
| AC-21 | `max_upload_bytes` set to 1,000,000; spec M | upload a valid price file of exactly 1,000,000 bytes to prices | 200 | unit |
| AC-22 | `max_upload_bytes` set to 1,000,000; approved M with P48 uploaded; then 1,000,001 bytes of the letter `x` uploaded to prices (413) | Backtest(the first upload's `ref`, all tickers) | 200 | unit |
| AC-23 | spec M | upload CV under a name of 101 letters `a` | 400 with detail `Characteristic name is longer than 100 characters.` | holdout |
| AC-24 | spec M | upload CV under a name of 100 letters `a` | 200 (must not change) | holdout |
| AC-64 | spec M | `POST /specs/<id>/datasets/characteristics/` (empty name) with CV | 400 with detail `Characteristic name is empty.` | holdout |

### Uploads: content (D2)

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-25 | spec M | upload a file of 0 bytes to prices | 400 with detail `Not a usable CSV: the file is empty.` | holdout |
| AC-26 | spec M | upload `date,T0\n` to prices | 400 with detail `Not a usable CSV: no data rows.` | holdout |
| AC-27 | spec M | upload `date\n1965-01-01\n` to prices | 400 with detail `Not a usable CSV: needs a date column and at least one ticker column.` | holdout |
| AC-28 | spec M | upload `date,T0\n1965-01-01,1.5\n1965-02-01,abc\n` to prices | 400 with detail `Not a usable CSV: row 3, column T0: "abc" is not a number.` | holdout |
| AC-29 | spec M | upload `date,T0\n01/31/1965,1.5\n` to prices | 400 with detail `Not a usable CSV: row 2: date "01/31/1965" does not start with YYYY-MM-DD.` | holdout |
| AC-30 | spec M | upload the three bytes `FF FE 00` to prices | 400 with detail `Not a usable CSV: not UTF-8 text.` | holdout |
| AC-31 | spec M | upload `date,T0\n1965-01-01,abc\n` as `book to market` | 400 with detail `Not a usable CSV: row 2, column T0: "abc" is not a number.` | holdout |
| AC-32 | approved M with P48 uploaded; then the file of AC-28 uploaded to prices (400) | Backtest(the first upload's `ref`, all tickers) | 200 | holdout |
| AC-33 | spec M | upload `date,T0,T1\n1965-01-31 00:00:00,1.5,\n1965-02-28 00:00:00,,2\n` to prices | 200 with `rows` 2, `first_date` `1965-01-31`, `last_date` `1965-02-28` (blank cells and longer dates stay accepted) | holdout |
| AC-63 | spec M | upload `date,T0\n\n1965-01-01,abc\n` to prices | 400 with detail `Not a usable CSV: row 3, column T0: "abc" is not a number.` | holdout |

### Backtest: data files

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-34 | approved M, nothing uploaded | Backtest(`prices.csv`, all tickers) | 400 with detail `Data file not found: prices.csv` | holdout |
| AC-35 | approved M with P48 uploaded | Backtest(`/etc/passwd`, all tickers) | 400 with detail `Data file not found: passwd` | holdout |
| AC-36 | approved M with nothing uploaded; a second spec with id `<other>` that has P48 uploaded | Backtest(`../<other>/prices.csv`, all tickers) on the first spec | 400 with detail `Data file not found: prices.csv` | holdout |
| AC-37 | approved M with P48 uploaded | Backtest(the upload's `ref`, `["ZZZ"]`) | 400 with detail `prices.csv: no column(s) for ['ZZZ']` | holdout |
| AC-38 | approved V; PV uploaded to prices; CV uploaded as `book to market` | `POST /specs/<id>/backtest` with `tickers` `["WIN1", "WIN2", "LOSE1", "LOSE2"]`, `prices_ref` and `characteristics_refs: {"book to market": <ref>}` from the two uploads | 200 with a `run_id` and a `verdict` (must not change) | holdout |
| AC-60 | approved V; PV uploaded to prices; no characteristics file uploaded | the request of AC-38 with `characteristics_refs: {"book to market": "characteristics_book_to_market.csv"}` | 400 with detail `Data file not found: characteristics_book_to_market.csv` | holdout |
| AC-61 | approved V; PV uploaded to prices | the request of AC-38 with `characteristics_refs: {"book to market": "/etc/passwd"}` | 400 with detail `Data file not found: passwd` | holdout |

### Screen: approve and edit, on the real app

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-39 | spec M, loaded by its id with "Resume" | press "Approve spec" | the badge beside "2. Review the spec sheet" reads "Approved" and the backtest card is visible | holdout |
| AC-40 | spec M, loaded by its id | change `holding_period_months` to 12 in the JSON editor, press "Save direct edit", then "Approve spec" | the text under the heading contains `12-month holding period` and the badge reads "Approved" | holdout |
| AC-41 | stubbed screen, A loaded with `approved: false` | press "Approve spec" | the request to `/specs/run_a/approve` has the body `{}` | holdout |

### Screen: uploads

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-42 | stubbed screen, A loaded; the upload request is held open | pick `f.csv` | `[data-upload-status="prices"]` reads `Uploading f.csv…` | holdout |
| AC-43 | stubbed screen, ready A; the next upload request is held open | pick `g.csv` | "Run backtest" is disabled | holdout |
| AC-78 | as AC-43 | pick `g.csv` | the price file input is disabled | holdout |
| AC-44 | stubbed screen, A loaded | pick `p48.csv` | `[data-upload-status="prices"]` reads `Uploaded p48.csv: 3 tickers, 24 rows, 1965-01-01 to 1966-12-01.` | holdout |
| AC-45 | stubbed screen, A loaded, tickers box empty | pick `f.csv` | the tickers box holds `T0, T1, T2` | holdout |
| AC-46 | stubbed screen, A loaded | pick `f.csv`, and type `T0` into the tickers box if it is empty | "Run backtest" is enabled (must not change) | holdout |
| AC-47 | stubbed screen, A loaded, tickers box holds `T1` | pick `f.csv` | the tickers box holds `T1` (must not change) | holdout |
| AC-48 | stubbed screen, ready A; the next upload answers 413 with detail `File is larger than the 100 MB upload limit.` | pick `g.csv` | `[data-upload-error="prices"]` reads `413: File is larger than the 100 MB upload limit.` | holdout |
| AC-65 | as AC-48 | pick `g.csv` | `[data-upload-status="prices"]` is in the page and its text is the empty string | holdout |
| AC-66 | as AC-48 | pick `g.csv` | "Run backtest" is disabled | holdout |
| AC-67 | as AC-48, but the request is first held open until the price file input is seen disabled (AC-78), then answered 413 | pick `g.csv` | the price file input is enabled | holdout |
| AC-69 | as AC-48 | pick `g.csv` | the price file input's `value` is the empty string | holdout |
| AC-49 | stubbed screen, A loaded; the upload request is aborted (no answer) | pick `f.csv` | `[data-upload-error="prices"]` reads `Upload failed: no answer from the server.` | holdout |
| AC-68 | as AC-49, but the request is first held open until the price file input is seen disabled, then aborted | pick `f.csv` | the price file input is enabled | holdout |
| AC-50 | after AC-48; the upload now answers 200 | pick `g.csv` again | no `[data-upload-error="prices"]` is in the page | holdout |
| AC-79 | as AC-50 | pick `g.csv` again | `[data-upload-status="prices"]` starts `Uploaded g.csv` | holdout |
| AC-51 | stubbed screen, A loaded with the characteristic; the characteristics upload answers 400 with detail `Not a usable CSV: no data rows.` | choose `c.csv` in the "book to market characteristics CSV" input | `[data-upload-error="characteristics"]` reads `400: Not a usable CSV: no data rows.` | holdout |
| AC-73 | stubbed screen, ready A with the characteristic; the characteristics upload answers 400 | choose `c.csv` in the "book to market characteristics CSV" input | "Run backtest" is enabled (must not change) | holdout |

### Screen: another spec

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-52 | stubbed screen, A loaded | load B | the JSON editor's text parses to a spec whose `strategy_name` is `Beta` | holdout |
| AC-53 | stubbed screen, ready A, Run, the verdict tile shown | load B | the backtest card is visible and holds no element with the text `Verdict` | holdout |
| AC-70 | as AC-53 | load B | `[data-upload-status="prices"]` is in the page and its text is the empty string | holdout |
| AC-71 | as AC-53 | load B | the tickers box is empty | holdout |
| AC-72 | as AC-53 | load B | "Run backtest" is disabled | holdout |
| AC-54 | stubbed screen, A loaded, `abc` typed into "Give an instruction in natural language" | load B | the instruction box is empty | holdout |
| AC-77 | stubbed screen, A loaded, "Save direct edit" pressed with the editor text `{` so an alert shows in the review section | load B | the review section holds no alert | holdout |
| AC-74 | stubbed screen, A loaded, the editor text replaced by `{` | load A again | the JSON editor's text parses to a spec whose `strategy_name` is `Alpha` | holdout |
| AC-75 | stubbed screen, ready A | load A again | `[data-upload-status="prices"]` starts `Uploaded f.csv` | holdout |
| AC-55 | stubbed screen, A loaded; `POST /specs` answers `{"spec_run_id": "run_b", "spec": <Beta>, "approved": false}` | fill "Paper citation" and the paper text, press "Draft spec sheet" | the JSON editor's text parses to a spec whose `strategy_name` is `Beta` | holdout |

### Screen: drawdown

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-56 | stubbed screen, A loaded; in-sample `long_short_return_pct` values `[-100, 10]` | pick `f.csv`, Run | the chart under "Drawdown depth (long-short, 0 = at a new high)" has an `aria-label` ending `Latest: Long-short drawdown depth 0.0%` | holdout |
| AC-57 | as AC-56 | as AC-56 | neither the backtest card's text nor any attribute of that chart's `svg` elements contains `NaN` | holdout |
| AC-58 | stubbed screen, A loaded; values `[10, -50, 20]` | pick `f.csv`, Run | the same `aria-label` ends `Latest: Long-short drawdown depth 40.0%` (must not change) | holdout |

Must not change: an unedited spec is approved as drafted (AC-11); an edit after an approval un-approves
(AC-12); an unapproved spec cannot be backtested (AC-13); approve with a body works and records the signed-in
user (AC-2 to AC-4); a 100-character name and a name with spaces work end to end (AC-24, AC-38); "Run backtest"
enables with a price file and a ticker, also after a failed characteristics upload (AC-46, AC-73); a filled
tickers box is left alone (AC-47); blank cells and dates with a time part are accepted
(AC-33); a drawdown after a positive peak reads as today (AC-58).

## Slices

Three PRs, each `risk:normal`, each with `Spec: strategy-replication-fixes` and its `Rows:` line in the
description, and every test it changes listed. They are built in order: slice 2 starts after slice 1 has
merged (its rows backtest an edited, approved spec), slice 3 after slice 2.

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | S | Approve with an optional body, the client sends `{}`, the current spec is the last edit; regenerated OpenAPI files | AC-1 to AC-13, AC-39 to AC-41, AC-59, AC-62 |
| 2 | S | Uploads: slug, size cap, content check, the new answer and its response model; backtest reads only the spec's own files and names files by name; the two changed tests | AC-14 to AC-38, AC-60, AC-61, AC-63, AC-64 |
| 3 | S | Screen: upload states, tickers fill, reset on another spec, drawdown | AC-42 to AC-58, AC-65 to AC-75, AC-77 to AC-79 |

After slice 2 and before slice 3 the screen keeps working: it passes the `ref` it received back unchanged and
ignores the new fields.

## Defaults decided without the owner

- The cap is the existing `max_upload_bytes` setting (100 MB by default) with the house 413 text, as the brief
  asks. No separate limit for data files.
- A name with a slash works (`B/M`), because "B/M" is the usual way to write book-to-market. Today it is a 404.
- Two names that slug to the same file name (`book to market`, `book_to_market`) share one stored file; the
  later upload replaces the earlier one. A spec has one characteristic, so this does not happen in the screen.
- A ref in the old absolute form is not accepted after D1, also when it points at the spec's own file. A page
  left open across the deploy has to upload again.
- The content check accepts whatever Python's `float()` accepts, including `nan`. It does not check that dates
  ascend or repeat.
- A failed upload clears what the screen showed for that input, even though the server still holds the file of
  an earlier successful upload. The user uploads again.
- No `evaluator` rows: the screen rows run in a browser as hidden tests, and the e2e app has no model key for
  an evaluator to draft a spec with. The UI review of the slice 3 PR covers how it looks.
- The size rows (AC-19 to AC-22) are `unit`, because they need a setting the e2e app is not started with.
- IDs are not in reading order in places (AC-59 to AC-79 were added after the first critic round; there is no
  AC-76).
- spec-critic ran twice (16 findings, then 6); all are fixed in this text.
- After this change the wiki needs an update: the `openwiki/` page that covers Strategy Replication. The weekly
  `/context-refresh` regenerates it.

## Later (own specs)

- An approval that names the revision it approved, and a diff between revisions.
- Characteristic uploads for the components of a composite spec.
- "Run backtest" stays disabled while a spec that needs a characteristic file has none.
- The same path and size rules for every other upload and `universe_path` (bug-list item 3).
