# Open minors from the 2026-10-11 architecture review

Small issues that the final review of each PR found and that were left for later. None of them changes facts or loses data. Candidates 1–5 of `architecture-review-20261011-0405.html` are merged as PRs #125–#129.

## #125 Fact ledger

- **Company not stored on an unqueued item.** A decision on a never-queued item whose result has no company stores the item with `company_id` NULL. `main` resolved the company from `payload.company_id`. Facts are unaffected, but the item drops out of the per-company open-review counts (`company_view.summary`).
- **Old link kept.** When a re-queue's payload names no observation that exists, `queue_item` keeps the item's old link.
- **No test** covers an item first queued through `queue_for_review` being linked by its payload target.

## #126 Run lifecycle

- **Failure marking differs between API and CLI.** When a resume fails before it starts (`check_resumable`, `build_llm_client`), the API path through the launcher marks the run `failed`. The CLI path leaves its status unchanged.
- **Theme resume answers 503 before 409.** It builds the LLM client before checking whether the run is busy.
- **A second rapid xbrl Retry gets 200.** Its job then hits `RunBusy` and logs it. Nothing runs twice; only the status code is wrong.
- **No test** checks the "could not mark run … failed" log line.

## #127 Run lease

- **`test_lease_is_held_in_postgres` counts across the whole server.** A lease held in another database on the same server breaks it. Fix: filter by `database = current_database()`.
- **Busy checks need the database.** The checks in `runs.py`, `themes.py` and `xbrl.py` now open a database connection, so they return 500 instead of answering quickly when the database is down.
- **`run_lease` no longer validates the run ID** (it used to through `safe_id`). Every caller looks the run up first, so this has no practical effect.

## #128 Batch write retry

- **Discovery and taxonomy are only partly retried.** Their result and error rows are retried, but not their own `on_success`/`on_error` progress writes or their `finish_run`.
- **The retry warning no longer names the run or company.** Add the first positional argument, the run ID, to the log line.
- **Missing tests:**
  - four failed attempts through `run_company_batch` ending in a failed run
  - an `IntegrityError` not being retried
  - the `queue_for_review` and `finish_run` retries

## #129 Co-sign rule

- **No test** covers the "run without a manifest → `set()`" fallback in `item_states`.
- **Extra manifest lookups.** Loops over all runs (`items.run_items`, `RunHistory.load`, `run_candidates`) now make one extra cheap manifest lookup per run. Not material at current run counts.

## Accepted gaps (marked with `ponytail:` comments in the code)

- **A dropped lease connection frees the lease while the worker keeps running** (`orchestration/jobs.py`). Upgrade path: a heartbeat that stops the worker.
- **A retried write whose commit confirmation was lost lands twice** (`db/session.retrying`): progress is counted twice, or an error row is stored twice. Upgrade path: idempotency keys.

## Waiting on an event

- After every deployment has run `arp db import` and `verify`, delete `db/importer.py`, `RunStore._apply_review`'s delegate and the legacy file store's writers, and rename `db/observations.py` to `fact_ledger.py` (ADR-0001).
- **Candidate #6** (tests that edit database tables directly through `tests/postgres_helpers.py`) is still open. The review rated it low priority.
