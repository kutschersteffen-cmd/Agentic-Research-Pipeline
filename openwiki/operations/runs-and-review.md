---
type: operations
title: Runs, persistence and review
description: How batch runs are created, executed, checkpointed per company in Postgres, resumed and cancelled; what the RunStore keeps in tables versus side files; how the fact ledger turns observations and review decisions into current company facts; and the review workflow with second review, resolution and grounded corrections.
tags: [runs, batch, postgres, run-store, fact-ledger, review, resume, cancel]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-c4a3e84ce5a9dfead5e01f63
    resource: repo://backend/arp/api/routers/runs.py
  - id: openwiki-source-9b81bb4949dbc7ba7a019c5c
    resource: repo://backend/arp/db/models.py
  - id: openwiki-source-df85c6c0a076c4c0b6b761a3
    resource: repo://backend/arp/db/observations.py
  - id: openwiki-source-5f3fcfb2040b636f88345e57
    resource: repo://backend/arp/db/runs.py
  - id: openwiki-source-f74b8e52a604e5aa1c5c5497
    resource: repo://backend/arp/orchestration/batch_runner.py
  - id: openwiki-source-e2e6762a9b4d440bab916d10
    resource: repo://backend/arp/orchestration/review_queue.py
  - id: openwiki-source-e0e292b4a39818ec11b2f2ff
    resource: repo://backend/arp/review/decide.py
  - id: openwiki-source-9abf1b6c9198947f90e756df
    resource: repo://backend/arp/storage/run_store.py
  - id: openwiki-source-9b3ec3ea0ae72f1d91326648
    resource: repo://docs/adr/0001-importer-keeps-own-rules-until-cutover.md
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# Runs, persistence and review

Every batch pipeline (extraction, financials, TNFD, themes, identity, ...) shares the same run machinery: a manifest,
the batch runner, the Postgres `RunStore`, the fact ledger and the review queue. This page covers that machinery. For
<!-- openwiki: broken internal link [/openwiki/architecture/data-flow.md] link "/openwiki/architecture/data-flow.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
where it sits in the overall flow, see [Data flow: documents to UI](/openwiki/architecture/data-flow.md).

## Run lifecycle

`JobManager` (`backend/arp/orchestration/job_manager.py`) owns the manifest: `create_run`, `mark_running`,
`record_progress` (completed, review and failed deltas, tokens, cost), `finish_run` and `request_cancel`. Each change
is a read-modify-write under `RunStore.lock(run_id)`.

An API endpoint creates the run and launches it in the background with `schedule_llm_run`, which hands it to
`LocalJobLauncher` (`backend/arp/orchestration/jobs.py`). The launcher runs the job inside a run lease (`hold_run`).
A second worker on the same run gets `RunBusy`.

### The batch runner

`run_batch` and `run_company_batch` (`backend/arp/orchestration/batch_runner.py`) provide five guarantees that every
pipeline relies on:

- **Checkpointing.** Each item's result is written as soon as it finishes.
- **Resumability.** Keys already stored (`done_keys`, which also includes error rows a worker stopped for review) are
  skipped on the next invocation.
- **Failure isolation.** One item's exception becomes an error row and affects no other item. A `ReviewRequired`
  exception goes to the run's review queue instead of counting as a failure.
- **Bounded concurrency.** An `asyncio.Semaphore` caps in-flight work.
- **Cooperative cancellation.** `cancel_check` reads the manifest's `cancel_requested` before each new item. Items
  already in flight finish and checkpoint normally.

For company batches, `run_company_batch` uses the run's stored, resolved companies, so a fresh run and a resume see the
same set. It commits each company with `RunStore.record_company_result` in **one transaction**: the result row,
observations, fact updates, held documents and review items. Database writes are retried while Postgres is unreachable
(`retrying` in `backend/arp/db/session.py`), and progress is recorded after the commit. When the batch is done, an
attached Decision Studio framework scores the run (`score_run`). Any failure there is logged, the run still finishes,
and its extracted results stand.

### Cancel and resume

- `POST /api/runs/{run_id}/cancel` (`backend/arp/api/routers/runs.py`) sets `cancel_requested` for a running or
  pending run. The CLI equivalent is `arp runs cancel`.
- `POST /api/runs/{run_id}/resume` needs the analyst role. It returns 409 if the run lease is held and 400 if
  `check_resumable` says the run cannot continue. Otherwise it relaunches `resume_run` in the background, which skips
  every stored key.

## What the RunStore keeps

`RunStore` (`backend/arp/db/runs.py`) is the Postgres store in use. `backend/arp/storage/run_store.py` still holds
`LegacyRunStore`, the file-era store under `runs/<run_id>/`. It is kept only to read old run directories and to serve
the side files below. Importing `arp.storage.run_store.RunStore` resolves lazily to the Postgres class.

| In tables | As side files under `runs_dir/<run_id>/` |
|---|---|
| `runs` (manifest), `run_companies`, `run_results` (unique `_key` per run), `run_errors`, `run_held_documents`, `review_items`, `review_decisions`, `review_cosigns`, plus the ledger tables below | `schema.json` (the registered schema snapshot), `step_settings.json`, `start_request.json`, snapshots, events, restatement candidates, `regrounds.jsonl` |

`append_result` is idempotent per `_key` (`ON CONFLICT DO NOTHING`), which is what makes resume and retried commits
safe. `RunStore.lock(run_id)` holds `SELECT ... FOR UPDATE` on the `runs` row, so it serialises across processes, and it
is re-entrant per thread. While a thread holds the lock, every store call that thread makes for the run reuses the
lock's transaction. Writing the same run through a *different* `RunStore` instance on that thread would wait on the row
lock forever, so callers must use one instance.

## The fact ledger

`backend/arp/db/observations.py` is the fact ledger. It is the only writer of the current-fact table.

- `field_observations` is insert-only. There is one row per extracted value, with `value_citations` attached. A value
  that does not fit its field's data type, or a citation to an unregistered document, is left out and reported in
  `run_errors`.
- `company_facts` is the current-fact layer. It is unique per (company, field, period_end, basis) while
  `valid_to IS NULL` (`backend/arp/db/models.py`), and rows are only ever closed, never edited.
- `decide(current, value, status, value_state)` is the single rule for whether an observation changes the current fact.
  A not-found value never removes a fact. A pending-review value never displaces one. A held value never displaces an
  accepted fact (auto-accepted, approved or edited). An identical value and status changes nothing. Anything else
  supersedes the current fact.
- An observation's status comes from its route: `hold` → held, `review` → pending review, otherwise auto-accepted.
  Trial-run observations are recorded but never make facts.
- `apply_decision` applies a final review decision to the item's linked observations. Approve, edit or correct set
  the fact to approved or edited, and hold sets it to held. Reject retires a pending fact that the rejected observation
  had made current. Escalate does nothing.

`docs/adr/0001-importer-keeps-own-rules-until-cutover.md` records that the one-time file-era importer
(`backend/arp/db/importer.py`) keeps its own copy of these rules until every deployment has cut over, and that
`RunStore._apply_review` is a delegate to be deleted with it.

## Review workflow

<!-- openwiki: broken internal link [/openwiki/pipeline/extraction.md] link "/openwiki/pipeline/extraction.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
Rows routed to `review` by the extraction routing (see [Data-point extraction engine](/openwiki/pipeline/extraction.md))
become `review_items`. The UI lists them with `GET /api/review/items` and posts decisions to
`POST /api/review/runs/{run_id}/items/{item_key}/decision` (`backend/arp/api/routers/review.py`). The rules live in
`backend/arp/review/decide.py`, which runs under the run lock:

- **Decisions are append-only.** `review_decisions` keeps every row. An item's state is folded from its rows, oldest
  first, by `item_state` in `backend/arp/orchestration/review_queue.py`. The states are `pending`, `first_done`,
  `disagreed`, `second_done` and `final`. Only `second_done` and `final` count as final (`FINAL_STATES`), and
  `effective_decisions` returns the effective row of each final item.
- **Second review.** A first decision needs a second reviewer when any of these reasons applies
  (`second_review_reasons`): it is a correction, the field is high-risk, it would change a published or prior value
  (or the item is a restatement candidate), the field's first audit has not passed, or it is an approval picked by a
  deterministic hash sample. The second reviewer must be a different person. If the two disagree, only an approver who
  reviewed neither side may resolve it. Escalated items and items an approver resolved are decided again only by an
  approver.
- **Corrections must be grounded.** A `correct` on a value needs a correction citation. The server grounds it against
  the stored text of one of the item's documents with `backend/arp/grounding.py` and discards any offsets the client
  sent. For numeric fields, the corrected number must also appear in the cited span. Otherwise the request fails with
  422.

Final decisions are what publishing reads: `run_candidates` in `backend/arp/publish/candidates.py` uses
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
`effective_decisions` and the item states. See [Publishing facts](/openwiki/pipeline/publish.md).
