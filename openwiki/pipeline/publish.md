---
type: pipeline subsystem
title: Publishing facts
description: How backend/arp/publish turns a finished extraction run into versioned, effective-dated published facts. Covers candidate selection from routes and final review decisions, the lineage gate on archived originals, one release per document, the version plan (insert, reconfirm, older), the outbox of fact events, withdrawal that restores earlier values, as-of reads, the internal_only licence refusal, the daily re-grounding job, and the API and CLI.
tags: [publish, facts, releases, versioning, lineage, outbox, withdrawal, as-of]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-0a0878f7a78cfb8cf6cb9434
    resource: repo://backend/arp/api/routers/publish.py
  - id: openwiki-source-e9ec1b175f3cec9ce4b63600
    resource: repo://backend/arp/cli/publish.py
  - id: openwiki-source-07e1021d4b7b6b7207c06144
    resource: repo://backend/arp/config.py
  - id: openwiki-source-c59382b84325fa1bdf1cbe11
    resource: repo://backend/arp/publish/candidates.py
  - id: openwiki-source-9c6b3dea4901bc39f8dd32fa
    resource: repo://backend/arp/publish/facts.py
  - id: openwiki-source-953fdbd214da2cf081497d9b
    resource: repo://backend/arp/publish/gate.py
  - id: openwiki-source-73c3a1eca18759aaafb86409
    resource: repo://backend/arp/publish/reader.py
  - id: openwiki-source-3bd6a8ce5544c04314769d06
    resource: repo://backend/arp/publish/release.py
  - id: openwiki-source-f464a1d0f6d1706855c4c2a0
    resource: repo://backend/arp/publish/scheduler.py
  - id: openwiki-source-b0892b4370c49b041fcdd02c
    resource: repo://backend/arp/storage/postgres_models.py
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# Publishing facts

Extraction and review produce **current facts** for analysts (`company_facts`, see
<!-- openwiki: broken internal link [/openwiki/operations/runs-and-review.md] link "/openwiki/operations/runs-and-review.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Runs, persistence and review](/openwiki/operations/runs-and-review.md)). **Publishing** is a separate, explicit act. It
copies the final values of one extraction run into an append-only, versioned table (`published_facts`) that downstream
consumers read as of a point in time. Each published value is tied to an archived original document whose hash still
matches. The code lives in `backend/arp/publish/`, and the docstrings cite spec items E72 to E77.

## Who publishes

- API: `POST /api/publish/runs/{run_id}` and `POST /api/publish/releases/{release_id}/withdraw`
  (`backend/arp/api/routers/publish.py`). Both require the **approver** role. A concurrent conflict returns 409, and a
  withdrawal without a reason returns 422.
- CLI: `arp publish run --run-id`, `arp publish withdraw --release-id --reason` (approver only, through
  `cli_principal`), and `arp publish backfill` (`backend/arp/cli/publish.py`). `backfill` publishes every non-trial
  extraction run as the system, oldest first. Running it again is safe because unchanged values only reconfirm.
- The frontend source has no call to the publish endpoints.

## Step 1: candidates (`backend/arp/publish/candidates.py`)

`run_candidates(run_store, run_id)` reads the run's result rows and decides, per item key
(`issuer_key:field_id:period`), whether a value may be published:

| Situation | Outcome |
|---|---|
| Run is not `extraction`, or is a trial | nothing (trial: `Skip("*", "trial_run")`) |
| No decision, route `auto_accept` | candidate, state `auto_accepted` |
| No decision, route `review` or still in review | skip `not_final` |
| Route `hold` | skip `held` |
| Final decision `approve` | candidate, state `approved`, with the field's first grounded citation |
| Final decision `correct` or `edit` | candidate, state `edited`, with the edit merged over the field and the **correction's own grounded citation** (never the field's old citation, which supports the old value) |
| `reject` | skip `rejected` |
| Restatement candidate | publishes only after the workbench's second review or an approver's resolution; otherwise `restatement_pending` |
| No value or no period | skip `no_value` / `no_period` |

"Final" means the item state from `effective_decisions` and `item_states` in
`backend/arp/orchestration/review_queue.py`, so a first decision that still needs a second reviewer does not publish.

## Step 2: the gate (`backend/arp/publish/gate.py`, `backend/arp/publish/release.py`)

`publish_run` then:

1. drops duplicate fact keys (`duplicate_key`), because a repeated key would hit the version unique constraint on
   every retry;
2. drops facts whose current company value comes from an `internal_only` provider source (`internal_only`). Only
   provider fields (`prov:`) are checked;
3. groups candidates by (issuer, cited document) and blocks a whole group when that document's release in this run was
   withdrawn, or when the first citation fails `lineage_error`. The lineage reasons are:
   - `no_grounded_citation`: the citation is missing, not grounded, or has no `content_key`;
   - `original_missing`: the blob store has no original, or returns something other than bytes;
   - `hash_mismatch`: the sha256 of the stored bytes differs from the blob key.

   `blob_key` resolves the key through the document registry's `storage_uri`, because EDGAR documents are stored under
   the sha256 of their raw bytes rather than their `content_key`. An unmapped EDGAR document therefore fails closed as
   `original_missing`.

Blocked groups are returned in `blocked` with their item keys. They are not errors.

## Step 3: versions and releases (`backend/arp/publish/facts.py`)

A fact key is `(issuer_key, field_id, period_end, basis)`. For each candidate, `plan_version` compares it with the key's
current fact:

- **reconfirm**: same value, unit and canonical unit. The current row only gets `reconfirmed_at`, and no new version
  is created.
- **older**: the candidate was observed before the current fact. It is skipped as `older_than_published`.
- **insert**: a new version (`version = current + 1`, `valid_from = now`). The previous row is closed with
  `valid_to = now` and `superseded_by = <new fact_id>`.

A group with at least one insert becomes one `Release` (doc, content key, storage URI, issuer, run, publisher and
role), and each insert emits a `published` event, or `restated` for a restatement. `PublishStore.current` also follows
a company's chain across issuer keys, so an LEI-keyed fact from before an identifier cut-over is treated as the current
version of the UUID-keyed key.

`PublishStore.save_release` writes everything in one transaction. Rows are sorted by key so that overlapping publishes
lock in the same order. The internal_only check runs again, and a hit raises `LicenceRefused`. Closing a row that is no
longer current, or hitting an integrity or serialisation error, raises `ConcurrentPublish`. Outbox rows (`fact_events`)
are committed under one global advisory lock (`EVENT_LOCK`), so `event_id` follows commit order and a consumer reading
by `event_id` can never skip an event that commits late. `published_facts` is unique on (key, version).

## Withdrawal and restore

`withdraw(store, release_id, reason, principal)` requires a non-empty reason and refuses an already withdrawn release.
For every still-current fact of the release, it walks back through `previous_version` past any version from a withdrawn
release, including this one. It then closes the fact (`withdrawn` event) and, if an earlier valid value exists,
inserts a **copy** of it as a new version with `restored_from` set (`restored` event, whose `release_id` is the source
release). If there is no earlier value, the key has no current fact. `save_withdrawal` takes a per-issuer advisory lock
and re-checks under it that nothing changed since planning.

## Reading published facts (`backend/arp/publish/reader.py`)

A fact is visible as of `b` when `valid_from <= b` and (`valid_to` is null or `> b`). If several versions are visible,
the highest one wins. `as_of` accepts a date (meaning end of that day, UTC) or an ISO datetime (naive means UTC). All
timestamps are fixed-width UTC strings, so comparing them as strings orders them correctly.

| Endpoint | Returns |
|---|---|
| `GET /api/publish/facts?as_of=&issuer_key=&field_id=` | as-of facts |
| `GET /api/publish/versions?issuer_key=&field_id=&period_end=&basis=` | every version of a key |
| `GET /api/publish/facts/{fact_id}/lineage` | fact, citation, release, document and `content_key` (the server-side `storage_uri` is removed) |
| `GET /api/publish/releases?doc_id=&run_id=` | releases, without publisher identities |
| `GET /api/publish/events?after_id=&limit=` | the outbox, by `event_id` cursor |

Published values also feed back into extraction as one of the cross-source references in the record checks
(`_published_values` in `backend/arp/extraction/pipeline.py`). Monthly holdings snapshots read them through
`facts_as_of` (`backend/arp/snapshots/build.py`). `PublishStore.referenced` lists the runs and content keys that
the retention command (`backend/arp/cli/retention.py`) must never delete.

## The daily publishing job (`backend/arp/publish/scheduler.py`)

`PublishingScheduler` is started with the API (`backend/arp/api/main.py`). It is off unless
`publishing_schedule_enabled` is set. On each tick it:

- runs `reground_if_parser_changed` (`backend/arp/orchestration/reground.py`), which re-grounds stored citations after a
  parser upgrade and does nothing otherwise;
- once a day, re-grounds a deterministic, date-seeded sample (`reground_sample_size`) of current published facts with
<!-- openwiki: broken internal link [/openwiki/pipeline/grounding.md] link "/openwiki/pipeline/grounding.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
  `reground` (see [Citation grounding](/openwiki/pipeline/grounding.md)), logs any outcome other than `ok` as drift,
  and appends every result to `reground.jsonl`;
- pulls due holdings from the holdings API, freezes the previous month's snapshot after the configured business day,
  and builds corrections for the last 24 frozen months from fact events.

A failure in one job never stops the others.

## Tests

`backend/tests/test_publish_candidates.py`, `backend/tests/test_publish_gate.py`,
`backend/tests/test_publish_release.py` (one release per document, unchanged republish creates no release, a missing
original blocks the whole document, withdrawal restores the previous fact), `backend/tests/test_publish_facts.py`,
`backend/tests/test_publish_reader.py` and the Postgres-backed `*_pg.py` variants, `backend/tests/test_publish_api.py`
and `backend/tests/test_publishing_scheduler.py`.
