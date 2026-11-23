# Review and export correctness: conflicts held back, counted and shown; three wrong status codes

Status: Draft, for owner approval
Slug: `review-export-correctness`
Risk: `risk:normal` (backend only; no auth, schema, money or workflow path)
Size: two slices, each `S`

## Decisions for the owner

None. Nothing open here would change an acceptance row. The choices taken are listed under
"Defaults taken"; approving the spec approves them.

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`, IDs A6, A7, A9,
B9, A10, A11, A13; bug-list item 2) confirmed six faults on `main` at `0ce947d`. Three of them break the
app's promise that no value leaves the app, or is counted as approved, while a person still has to
decide on it. Three return the wrong answer when something is missing.

## What the user can do afterwards that they cannot do today

- Trust an extraction CSV export: a value whose conflict with an accepted fact is still open is blank
  and marked `awaiting review`. Once a person decides "keep the accepted fact", the export carries the
  accepted value, not the run's new value and not a blank.
- Trust the "approved" number Argus shows for a company's last extraction: it no longer counts values
  whose review is still open, and it counts decided values of older rows that carry no `issuer_key`.
- Open a conflict in the review queue and see the new value, its quote and its confidence next to the
  accepted value, instead of an empty card.
- Read why a Signals run could not start (503 with the reason) instead of "Run failed: NotConfigured".
- Get a 422 that names the missing `file` part when an upload is sent without a file, instead of a 500.
- Retry a company again after a Retry whose job could not be launched; the run no longer keeps the
  company marked as retrying.

## Three versions

- Safe: the six fixes as the Antigravity patch has them. It blanks a conflict decided "keep accepted"
  and its conflict test passes on `main` without the fix.
- Strong (specified here): the six fixes with one rule for "may this value leave the app", used by the
  export and matched by the Argus count; a kept conflict exports the accepted value; a person's later
  decision on an auto-accepted value is honoured by the export; the conflict card carries value,
  evidence and confidence; every row uses a real conflict payload.
- Most ambitious: the strong version plus a review card that shows accepted and new value side by
  side with both sources, and an export column that names the conflict. Not specified: the intake set
  this item to backend only, and the card layout needs a design the owner has not seen.

Next step up would need: a frontend slice with an approved mock of the conflict card, and `evaluator`
rows that seed a real conflict in the running app.

## What exists today

- `backend/arp/db/runs.py` `record_company_result` queues one review item of kind `conflict` when a
  run's new value differs from an accepted fact. `_conflict_target` keys it on the field's own item key
  `field_item_key(issuer_key, field_id, period_key(f))`, so a value routed to review and its conflict are
  one item. The queue row carries `"kind": "conflict"`, `"new_value"`, `"field"` (the results field) and
  `"accepted": {"value", "fact_id", "status", "observation_id"}`.
- `backend/arp/review/items.py` `_queue_kind`: a queue row is `ReviewItemKind.CONFLICT` only if it has
  `kind == "conflict"` and the key `accepted`. Without `accepted` an extraction row is a `VALUE` item.
- `backend/arp/review/decide.py`: a conflict takes `approve` (accept the new value), `reject` (keep the
  accepted fact) or `escalate`.
- `backend/arp/api/routers/runs.py` `_reviewed_value` and `export_run_csv`: the extraction branch holds a
  field back only when its `route` is `review` or `hold`. An auto-accepted field is written as stored,
  whatever the queue or the decisions say.
- `backend/arp/argus/rows.py` `_prior_runs`: `approved` counts a field with no decision and route
  `auto_accept`, or a latest decision of `approve`, `edit` or `correct`. The key is always
  `field_item_key(row.get("issuer_key", ""), ...)`.
- `backend/arp/review/context.py` `_value`: returns a value for `VALUE` and `RESTATEMENT_CANDIDATE` items
  only, so a conflict's bundle has `value: null`, `evidence: []`, `confidence: null`, `conflict: null`.
- `backend/arp/api/routers/signals.py` `run`: `except Exception` turns every error but `ValueError` into
  `500 "Run failed: <type>"`. `arp.errors.NotConfigured` is mapped to 503 with its message by the app
  (`backend/arp/api/main.py`) everywhere else.
- `backend/arp/api/routers/documents.py` `upload_document`: `file: UploadFile = None`, then
  `file.filename`.
- `backend/arp/api/routers/argus.py` `retry_company`: when `get_job_launcher().launch(...)` raises, the
  rollback restores `status` but leaves `params["retrying"]`.

## Goals

1. The extraction CSV export never carries a run's value while a review item on that field is open, and
   follows the final decision once there is one.
2. A conflict decided `reject` exports the accepted value.
3. Argus `approved` leaves out fields with an open review item and finds decisions of rows without
   `issuer_key`.
4. A conflict's context bundle carries the queued field as `value`, with evidence and confidence.
5. A Signals run that fails with `NotConfigured` answers 503 with the reason.
6. `POST /api/documents/upload` without a file answers 422.
7. A Retry whose launch fails leaves the run as it was before the Retry.

## Non-goals

- No frontend change. The generated API files change with goal 6 only.
- No change to other export branches (theme, financials, transition plan, barrier, XLSX) or to TNFD.
- No change to how conflicts are raised, keyed or decided, and no change to facts.
- Strategy Replication (item 1), path confinement and upload size caps (item 3).
- Conflict items keyed `conflict:<company>:<field>:<period>:<basis>` (a conflict on a value that is not
  a field of the run's results row): they have no export row and no field to show.

## Anti-goals

- An export that shows a blank where an accepted, person-approved value exists.
- A test that queues a "conflict" without `accepted`: it is a value item and passes on `main`.
- A Signals 500 that starts to leak error messages: only `NotConfigured` messages are passed on.

## Design

### One rule for the export (goals 1 and 2)

For each field `f` of each results record, in `export_run_csv`'s extraction branch:

- Key `K` = `field_item_key(issuer_key, f.field_id, period_key(f))` when the record has an `issuer_key`,
  else `"<company_id>:<field_id>"` (as today).
- `f` is **gated** when its `route` is `review` or `hold` (as today), or the run's review queue holds a
  row with `item_key == K`, or the run has at least one decision row with `item_key == K`.
- `f` is a **conflict** when the queue row with key `K` has `kind == "conflict"` and the key `accepted`.
- The final decision is `effective_decisions(run_store, run_id).get(K)` (as today).

| Case | `value` | `canonical_value` | `review_status` |
|------|---------|-------------------|-----------------|
| not gated | as stored | as stored | empty |
| gated, no final decision | empty | empty | `awaiting review` |
| gated, final `approve` | as stored | as stored | `approve` |
| gated, final `correct` or `edit` | the corrected value | empty | `correct` or `edit` |
| gated, conflict, final `reject` | the queue row's `accepted.value` | empty | `reject` |
| gated, any other final decision | empty | empty | the decision |

All other columns are unchanged.

### The Argus count (goal 3)

In `_prior_runs`, a field counts as approved when both hold:

- its key `K` (the export's key, with the same fallback for a record without `issuer_key`) is not the
  `item_key` of an open review item of that run (`list_open_items`), and
- its final decision (`effective_decisions`) is `approve`, `edit` or `correct`; or it has no decision
  row at all and its `route` is `auto_accept`.

`waiting` is unchanged.

### The conflict card (goal 4)

`_value` returns `item.payload["field"]` for a `CONFLICT` item, as it does for a `VALUE` item; `null` when
the payload has no `field`. Everything `build_context` derives from the value (`evidence`, `documents`,
`failed_checks`, `route_reasons`, `conflict`, `suggested_correction`, `prior_period`, `confidence`) then
fills in the same way as for a value item. The accepted value stays where it is, in
`item.payload.accepted`. The bundle's keys do not change.

### Status codes (goals 5 and 6)

- `signals.run`: an `HTTPException` or `NotConfigured` raised inside the run is re-raised before the
  catch-all, so the app's handler answers `503 {"detail": "<message>"}`. Every other exception still
  answers `500 {"detail": "Run failed: <type>"}` and is logged.
- `documents.upload_document`: `file: UploadFile = File(...)`. The request then fails validation with the
  app's 422 body. Regenerate `frontend/src/api/openapi.json` and `frontend/src/api/schema.gen.ts`
  (`.claude/CLAUDE.md`, API contract) and commit both.

### Retry rollback (goal 7)

In `retry_company`'s `except` around `launch`, remove `retrying` from `params` in the same locked write
that restores `status`. The error still propagates.

## Fixtures

**Fixture E** (export, count, card). Extraction run `R`, created `2026-11-01T09:00:00+00:00`, manifest
params `{"schema_name": "S", "schema_version": "s:v2"}`. One results record: `company_id` `c1`,
`issuer_key` `ISS`, `name` `N`, `ticker` `T`, `needs_review` true. Each field has `field_name` equal to its
`field_id`, `period_end` `2024-12-31`, `confidence` 0.9, `grounded` true, `unit` `USD`, `canonical_unit`
`USD`, `value_state` `found`, `canonical_value` equal to `value`, no `basis`, and
`citations: [{"doc_id": "d1", "doc_type": "10-K", "quote": "Revenue was <value>", "char_start": 10, "char_end": 25, "grounded": true}]`.

| `field_id` | `value` | `route` | queue row | decision rows (oldest first) |
|------------|---------|---------|-----------|------------------------------|
| `plain` | 1.0 | `auto_accept` | none | none |
| `open` | 2.0 | `auto_accept` | conflict, `accepted.value` 20.0 | none |
| `taken` | 3.0 | `auto_accept` | conflict, `accepted.value` 30.0 | `approve` |
| `kept` | 4.0 | `auto_accept` | conflict, `accepted.value` 40.0 | `reject` |
| `rkept` | 5.0 | `review` | conflict, `accepted.value` 50.0 | `reject` |
| `undone` | 6.0 | `auto_accept` | none | `reject` |
| `fixed` | 7.0 | `auto_accept` | none | `correct` with `corrected_value: {"value": 70.0}` |
| `esc` | 8.0 | `auto_accept` | conflict, `accepted.value` 80.0 | `escalate` |

A conflict queue row is: `{"item_key": "ISS:<field_id>:2024-12-31", "issuer_key": "ISS", "company_id": "c1",
"name": "N", "field_id": "<field_id>", "period_end": "2024-12-31", "basis": "", "field": <the results field>,
"kind": "conflict", "new_value": <value>, "accepted": {"value": <accepted.value>, "fact_id": 1, "status":
"approved", "observation_id": 1}}`. A decision row is `{"item_key": "ISS:<field_id>:2024-12-31", "decision":
..., "decided_at": ..., "user_id": "x"}` with no `step`, so `approve`, `reject` and `correct` are final and
`escalate` leaves the item open. No run schema is stored.

**Fixture N** (no issuer key). Extraction run `RN`, same manifest params, one record: `company_id` `c2`,
`name` `N2`, no `issuer_key`, two fields built like Fixture E's: `n1` (value 1.0, route `auto_accept`, no
queue row, no decision) and `n2` (value 2.0, route `review`, no queue row, one decision row
`{"item_key": "c2:n2", "decision": "approve", ...}`).

## Defaults taken

- A kept conflict's `review_status` is the decision word `reject`, like every other status in that
  column. Its `canonical_value` is empty: the queue row holds the accepted value only, not its canonical
  form (same rule as a corrected value today).
- A person's decision on an auto-accepted value that had no conflict now counts in the export
  (`undone`, `fixed`). On `main` the export ignores it.
- A kept conflict is not counted as approved by Argus: the run's value was turned down. The count is
  about the run's values, the export about what may leave the app.
- The Argus count reads final decisions (`effective_decisions`), as the export does, not the latest row.
- The Signals and Retry rows are `unit`: they need a launcher or a run that fails on purpose, which a
  hidden test could only do by patching names inside the builder's code.
- A conflict on a high-risk field is still not marked `high_risk` (`review/items.py`); not in this item.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture E | `GET /api/runs/R/export.csv` | the `open` row has `value` empty, `canonical_value` empty, `review_status` `awaiting review` | holdout |
| AC-2 | Fixture E | `GET /api/runs/R/export.csv` | the `taken` row has `value` `3.0`, `canonical_value` `3.0`, `review_status` `approve` | holdout |
| AC-3 | Fixture E | `GET /api/runs/R/export.csv` | the `kept` row has `value` `40.0`, `canonical_value` empty, `review_status` `reject` | holdout |
| AC-4 | Fixture E | `GET /api/runs/R/export.csv` | the `rkept` row has `value` `50.0`, `canonical_value` empty, `review_status` `reject` | holdout |
| AC-5 | Fixture E | `GET /api/runs/R/export.csv` | the `undone` row has `value` empty, `canonical_value` empty, `review_status` `reject` | holdout |
| AC-6 | Fixture E | `GET /api/runs/R/export.csv` | the `fixed` row has `value` `70.0`, `canonical_value` empty, `review_status` `correct` | holdout |
| AC-7 | Fixture E | `GET /api/runs/R/export.csv` | the `esc` row has `value` empty, `canonical_value` empty, `review_status` `awaiting review` | holdout |
| AC-8 | Must not change. Fixture E | `GET /api/runs/R/export.csv` | the `plain` row has `value` `1.0`, `canonical_value` `1.0`, `review_status` empty | holdout |
| AC-9 | Must not change. Fixture E | `GET /api/runs/R/export.csv` | the body has 9 lines: the header of `main` (17 columns, `company_id` first, `review_status` last) and one line per field in fixture order | holdout |
| AC-10 | Must not change. Run `R2` like Fixture E's but with no queue rows, one record with `issuer_key` `ISS` and four fields: `w` (route `review`, no decision), `a` (route `review`, decision `approve`), `h` (route `hold`, decision `reject`), `o` (no `route` key, no decision); values 1.0 to 4.0 | `GET /api/runs/R2/export.csv` | `(value, review_status)` per row is `w`: (empty, `awaiting review`); `a`: (`2.0`, `approve`); `h`: (empty, `reject`); `o`: (`4.0`, empty) | holdout |
| AC-11 | Fixture E; a flow whose company list is `c1` (`CompanyRef(company_id="c1", name="N")`), `R` being `c1`'s newest extraction run | the flow's rows are built (`arp.argus.rows.flow_rows`, the `rows` of `GET /api/argus/flows/{flow_id}`) | `c1`'s `extracted_before.approved` is 3 (`plain`, `taken`, `fixed`) | holdout |
| AC-12 | Must not change. As AC-11 | the same read | `c1`'s `extracted_before.waiting` is 2 (`open`, `esc`) and `label` is `S v2`, `date` is `2026-11-01` | holdout |
| AC-13 | Fixture N; a flow whose company list is `c2`, `RN` being `c2`'s newest extraction run | the flow's rows are built as in AC-11 | `c2`'s `extracted_before.approved` is 2 | holdout |
| AC-14 | Fixture E | `GET /api/review/runs/R/items/ISS:open:2024-12-31/context` as a signed-in user who may read review items | 200; `item.kind` is `conflict`; `value.value` is 2.0 and `value.field_id` is `open` | holdout |
| AC-15 | The response of AC-14 | `evidence` is read | it has exactly one entry, with `doc_id` `d1`, `quote` `Revenue was 2.0`, `char_start` 10 | holdout |
| AC-16 | The response of AC-14 | `confidence` is read | `confidence.final` is 0.9 and `confidence.grounded` is true | holdout |
| AC-17 | The response of AC-14 | `item.payload.accepted` and `conflict` are read | `item.payload.accepted.value` is 20.0; `conflict` is `{"conflicting_sources": false, "alternatives": []}` | holdout |
| AC-18 | Must not change. Run `R2` of AC-10 with a queue row for `w` that has `field` set and no `kind` and no `accepted` | `GET /api/review/runs/R2/items/ISS:w:2024-12-31/context` | 200; `item.kind` is `value`; `value.value` is 1.0 | holdout |
| AC-19 | A valid Signals run request (recipe and prices parts as in `backend/tests/test_api_signals.py`), with `arp.api.routers.signals.run_recipe` replaced by a function that raises `arp.errors.NotConfigured("ARP_GEMINI_API_KEY is not set")` | `POST /api/signals/runs` as an analyst | 503 with body `{"detail": "ARP_GEMINI_API_KEY is not set"}` | unit |
| AC-20 | Must not change. As AC-19, but the function raises `RuntimeError("secret detail")` | `POST /api/signals/runs` | 500 with `detail` `Run failed: RuntimeError`; the body does not contain `secret detail` | unit |
| AC-21 | Must not change. A Signals run request without the `prices` part | `POST /api/signals/runs` as an analyst | 422 with `detail` `missing file part 'prices'` | holdout |
| AC-22 | The app; form fields `company_id=acme`, `doc_type=other`, and no `file` part | `POST /api/documents/upload` as a user allowed to upload | 422; `detail` is a list holding one entry with `type` `missing` and `loc` `["body", "file"]` | holdout |
| AC-23 | The request of AC-22 | the documents directory is read afterwards | no directory `acme` exists under `documents_dir` | holdout |
| AC-24 | Must not change. The same form fields with a file part `r.pdf` (3 bytes) | `POST /api/documents/upload` | 200, and `documents_dir/acme/other/r.pdf` holds those 3 bytes | holdout |
| AC-25 | The committed `frontend/src/api/openapi.json` | the request body schema of `POST /api/documents/upload` is read | its `required` list holds `file`, `company_id` and `doc_type` | unit |
| AC-26 | A started flow whose run has status `partially_completed`, company `aapl` failed, one kept file for `aapl` (the fixture of `backend/tests/test_argus_retry.py`); the job launcher's `launch` raises `RuntimeError` | `POST /api/argus/flows/{flow_id}/companies/aapl/retry` as an analyst | the request does not succeed (a 500 response, or the `RuntimeError` raised by a test client that re-raises server errors), and afterwards the run manifest's `params` has no key `retrying` | unit |
| AC-27 | The state after AC-26 | the run manifest is read | `status` is `partially_completed` | unit |
| AC-28 | The state after AC-26, with a launcher that works again | the same `POST` is sent again | 200, and `aapl`'s status in the response is `Waiting` | unit |

Must not change: the export of values with no review item (AC-8), the export's shape (AC-9), today's
handling of values routed to review or hold (AC-10), the Argus `waiting` number and run label (AC-12), the
context of a value item (AC-18), Signals' 500 for other errors (AC-20) and its 422s (AC-21), an upload
with a file (AC-24).

## Slices

1. `S`: export rule, Argus count, conflict card. Rows: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8,
   AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18.
2. `S`: status codes and Retry rollback, with the regenerated API files. Rows: AC-19, AC-20, AC-21,
   AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28. Item 3 (upload caps) may touch
   `documents.upload_document` too; whichever merges second merges `origin/main` first.

## Wiki

After slice 1, check whether `openwiki/` describes when the export holds a value back or how Argus
counts approved values; if it does, the weekly `/context-refresh` regenerates it.
