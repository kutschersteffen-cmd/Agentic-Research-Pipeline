# Discovery review queue

Spec slug: `discovery-review-queue`. Gap G3 of the universe-to-documents review
(https://claude.ai/artifact/FH7Q7fWJVUpxTRbjyKLx5a).

Status: approved by the owner, 2026-11-03.

## Why

`arp discover run` checks every downloaded PDF for the company's LEI, ISIN or name
(`arp/discovery/doc_check.py:25-48`). When the check fails, or when a company gets no documents at all, the run
only adds 1 to a review counter (`arp/discovery/pipeline.py:203-210`). No review item is created, so nobody can see
or act on it. A report of the wrong company, or a company with no reports, reaches warm and the theme run unseen.

Identity resolution already queues review items through the shared review queue
(`arp/discovery/identity_pipeline.py:93-102`, `arp/orchestration/review_queue.py:16-28`) and the shared Review
page. Discovery should use the same queue.

## Goals

1. A discovery run queues one review item per document whose PDF check failed, and one per company with no
   documents.
2. A reviewer can keep (approve) or drop (reject) a flagged document. A dropped document is no longer read by warm
   or the theme run, and later discovery runs do not download it again.
3. An approved document is not queued again while its URL and content stay the same.
4. The items appear in the existing Review page and API, like identity items.

## Non-goals

- Recording failed downloads in the run result (`arp/discovery/downloader.py:135-137`). It needs a return-type
  change in `download_documents`, which has 5 callers. Separate gap.
- A CLI for reviewing discovery items. Review happens on the Review page and the review API.
- Adding a missing document by hand from the review item (a URL correction). Add the company's website to the
  universe and re-run instead.
- An in-app PDF preview for these items. The item shows the URL.
- Undoing a decision. A rejected file stays under `_rejected/`, where a person can move it back.
- EDGAR and ESEF documents. They have no PDF check (`company_match` is `None`) and are never queued.

## Anti-goals

- Deleting a document's bytes. Reject moves the working copy; the blob store and capture log are untouched.
- A flagged document dropped without a person deciding it.

## Design

### Item kinds and keys

Two new `ReviewItemKind` values (`arp/schemas/review.py:89-97`):

| Kind | Item key | Queued when | Allowed decisions |
|---|---|---|---|
| `discovered_document` | `discovered:<company_id>:<sha256>` | a document in `documents_found` has `company_match` `none` or `no_text`, and its `review` is not `approved` | approve, reject, escalate |
| `no_documents` | `no_documents:<company_id>` | `documents_found` is empty and the run was started by hand (`triggered_by == "manual"`) | approve, escalate |

Scheduled runs (every 24 h by default) do not queue `no_documents` items, so the same empty company does not
reappear every day. Document items are deduplicated by approval (below), so scheduled runs do queue them.

Reason codes in the payload's `reason_codes` (`ReasonCode`, `arp/schemas/review.py:11-26`):

- `company_match == "none"` → `match_ambiguous` (existing; the PDF does not name the company).
- `company_match == "no_text"` → `check_failed` (existing; the check could not read text).
- no documents → `no_documents` (new value).

Payload of a `discovered_document` item: `company_id`, `name`, `url`, `doc_type`, `local_path`, `sha256`,
`company_match`, `page_count`, `reporting_year`, `reason_codes`. Payload of a `no_documents` item: `company_id`,
`name`, `homepage_used`, `homepage_unreachable`, `crawl_error`, `reason_codes`.

### Queueing

`"discovery"` joins `REVIEWABLE_RUN_TYPES` (`arp/review/items.py:15`), and `_queue_kind` maps the payload to its kind.
In `execute_discovery_run`, `_on_success` (`pipeline.py:203-210`) builds the items above, queues each with
`queue_for_review`, and records `review_delta=len(items)`. So the run's review count is the number of items,
not the number of flagged companies.

`arp discover run` prints `<n> items queued for review (open the Review page)` when n > 0.

### Decisions and their effect

`ALLOWED` and `_check_kind` in `arp/review/decide.py:33-37, 118-139` take the two new kinds. After
`append_decision` (`decide.py:235`), when the item's run type is `discovery`, its kind is `discovered_document`
and its state is in `FINAL_STATES`, a new `arp/discovery/review.py::apply_decision(settings, payload, decision)`
runs:

- **reject**: moves the working copy from `local_path` to
  `<documents_dir>/_rejected/<company_id>/<doc_type>/<file name>`, and sets the manifest entry's `review` to
  `"rejected"`.
- **approve**: sets the manifest entry's `review` to `"approved"`. The file stays.

`_rejected/` sits beside the company folders, not inside one. `LocalFileDocumentSource` reads
`<documents_dir>/<company_id>/`, so warm and the theme run no longer see the file. Inside a company folder an
unknown subfolder would be read as `other` (`arp/ingestion/local_files.py:478-480`).

A decision that still needs a second review changes nothing until the second review finishes.

### Manifest

`DiscoveredDocument` (`arp/schemas/discovery.py:18-33`) gains `review: Literal["approved", "rejected"] | None = None`.
It is stored in the per-company manifest like every other field (`arp/discovery/change_detector.py:50-73`).

- `diff_and_record` keeps the prior entry's `review` when the new document has the same URL and sha256, and
  sets it on the returned document. A new sha256 clears it.
- `download_documents` skips a candidate whose URL is a known entry with `review == "rejected"`: no request.
- A downloaded document whose sha256 equals a rejected known entry's sha256 is not written to the working folder
  and is not returned.

### Writing items with the result, and resume

`execute_discovery_run` passes `run_batch` a `write_result` that stores the company's result row and its review
items in one call to `run_store.record_company_result(run_id, row, observations=[], review_items=items,
company=company)`, as `run_company_batch` does (`arp/orchestration/batch_runner.py:164-180`). A crash can no
longer keep a result while losing its items. `_on_success` then records `review_delta=len(items)`.

Resume (`arp/orchestration/jobs.py:228-241`) keeps the stored `review_count` and skips companies already in the
results, so their items are neither queued nor counted again. `review_count` therefore equals the number of queued
items. No change to `restart_run`; its docstring line about discovery counting without queue rows is updated.

### Seed script for the evaluator

`backend/scripts/seed_discovery_review.py` (new) writes one discovery run into the configured run store, with
no network: run type `discovery`, the two result rows of the AC-9 fixture (C1, C2) and their three review items, plus the
two PDF working copies under `<documents_dir>/C2/10-K/` and matching manifest entries. It prints the run id.

## Left to the builder

Where the item-building helper lives; frontend labels other than those in the Acceptance table; how the
`_rejected` move handles an existing file of the same name (overwrite is acceptable).

## Acceptance

Rows marked `unit` run in-process: discovery with a stand-in search client and an `httpx.MockTransport` (as
`tests/test_known_reports.py` does), and the review API through FastAPI's `TestClient`. The e2e app cannot take
those stand-ins, so these rows cannot be `holdout`. Decisions are posted to
`POST /api/review/runs/{run_id}/items/{item_key}/decision`, with the `etag` from
`GET /api/review/runs/{run_id}/items/{item_key}/context` as `context_etag`. Unless a row says otherwise,
`second_review_sample_rate` is 0.

**Fixture.** C1: no source returns any document. C2: the crawl finds two PDFs at different URLs,
`https://c2.example/report-a.pdf` (bytes B1, sha256 S1) and `https://c2.example/report-b.pdf` (bytes B2, sha256 S2,
B2 ≠ B1); neither names C2 or its LEI/ISIN (`company_match` `none`), both classified `10-K`. C3: one PDF with under
200 characters of text (`company_match` `no_text`), sha256 S3. C4: one PDF at `https://c4.example/annual-report-2025.pdf`,
3 pages, naming C4, PDF title "Annual Report 2025", sha256 S4. C5: only an EDGAR 10-K. All runs are started by hand
unless a row says otherwise.

**DRUN** = first `backend/scripts/e2e_stack.sh up`, then `python backend/scripts/seed_discovery_review.py` run with the
stack's environment, so it writes to the same run store, `documents_dir` and `discovery_state_dir` the app reads.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Universe [C1] | `run_discovery` | The run's review queue holds exactly one item, key `no_documents:C1` | unit |
| AC-2  | Same as AC-1 | `GET /api/review/items?run_id=<run>` | The item `no_documents:C1` has `kind` `no_documents` | unit |
| AC-3  | Same as AC-1 | `GET /api/review/items?run_id=<run>` | The item's `payload.reason_codes` is `["no_documents"]` | unit |
| AC-4  | Universe [C1], `triggered_by="schedule"` | `run_discovery` | The run's review queue is empty | unit |
| AC-5  | Universe [C2] | `run_discovery` | The queue holds items `discovered:C2:S1` and `discovered:C2:S2`, both `kind` `discovered_document` | unit |
| AC-6  | Same as AC-5 | `GET /api/review/items?run_id=<run>` | Item `discovered:C2:S1` has `payload.reason_codes` `["match_ambiguous"]` | unit |
| AC-7  | Universe [C3] | `run_discovery` | The queue holds item `discovered:C3:S3` with `payload.reason_codes` `["check_failed"]` | unit |
| AC-8  | Universe [C4] | `run_discovery` | The queue holds no item whose key starts with `discovered:C4:` | unit |
| AC-9  | Universe [C1, C2] | `run_discovery` | The run manifest's `review_count` is 3 | unit |
| AC-10 | Same stand-ins as AC-9 | `arp discover run --universe <file>` through typer's `CliRunner`, in-process | Output contains the line `3 items queued for review (open the Review page)` | unit |
| AC-11 | Universe [C2] after `run_discovery`, item `discovered:C2:S1` | POST decision `reject`, reason `wrong_entity` | The response's `state` is `final` | unit |
| AC-12 | Same as AC-11 | check the item payload's `local_path` | No file exists there | unit |
| AC-13 | Same as AC-11 | list `<documents_dir>/_rejected/C2/10-K/` | It holds one file, with sha256 S1 | unit |
| AC-14 | Same as AC-11 | read `<discovery_state_dir>/C2.json` | The entry for `https://c2.example/report-a.pdf` has `"review": "rejected"` | unit |
| AC-15 | Same as AC-11 | `LocalFileDocumentSource.fetch(C2)` | No returned document has content sha256 S1 | unit |
| AC-16 | Same as AC-11 | look up key S1 in the blob store after the decision | The blob store holds S1 | unit |
| AC-16b | Same as AC-11 | count lines in `<documents_dir>/_captures.jsonl` (the capture log) before and after the decision | The count is unchanged | unit |
| AC-17 | Same as AC-11; a second run whose crawl finds `https://c2.example/report-a.pdf` again | `run_discovery` | The mock transport receives 0 requests for that URL | unit |
| AC-18 | Same as AC-11; a second run finds bytes B1 at `https://c2.example/copy.pdf` | `run_discovery` | No file with sha256 S1 exists under `<documents_dir>/C2/` | unit |
| AC-19 | Same as AC-18 | read the second run's queue | It holds no item with key `discovered:C2:S1` | unit |
| AC-20 | Universe [C2] after `run_discovery`, item `discovered:C2:S1` | POST decision `approve`, reason `confirmed` | The manifest entry for `https://c2.example/report-a.pdf` has `"review": "approved"` | unit |
| AC-21 | Same as AC-20 | check the item payload's `local_path` | The file exists | unit |
| AC-22 | Same as AC-20; a second run returns the same URL with bytes B1 | `run_discovery` | The second run's queue holds no item with key `discovered:C2:S1` | unit |
| AC-23 | Same as AC-20; a second run returns the same URL with new bytes B3 (sha256 S6) that do not name C2 or its LEI/ISIN (`company_match` `none`) | `run_discovery` | The second run's queue holds item `discovered:C2:S6` | unit |
| AC-24 | Universe [C2] after `run_discovery`, `second_review_sample_rate` 1.0 | POST decision `approve`, reason `confirmed`, for `discovered:C2:S1` (first reviewer) | The response's `state` is `first_done` | unit |
| AC-24b | Same as AC-24 | check the payload's `local_path` | The file exists | unit |
| AC-25 | Same as AC-24 | read `<discovery_state_dir>/C2.json` | The entry for `https://c2.example/report-a.pdf` has `"review": null` | unit |
| AC-26 | Universe [C2] after `run_discovery`, no decision on `discovered:C2:S1` | check the payload's `local_path` | The file exists | unit |
| AC-27 | Same as AC-26 | read `<discovery_state_dir>/C2.json` | The entry for `https://c2.example/report-a.pdf` has `"review": null` | unit |
| AC-28 | Universe [C1] after `run_discovery` | POST decision `reject` for `no_documents:C1` | `422` with detail `reject is not a decision for a no_documents item` | unit |
| AC-29 | Same as AC-28 | POST decision `approve` for `no_documents:C1` | The response's `state` is `final` | unit |
| AC-30 | Same as AC-29 | compare content and mtime of every file under `<documents_dir>` and `<discovery_state_dir>` before and after the decision | None changed | unit |
| AC-31 | DRUN | open the Review page | Three items of the seeded run are listed, each labelled `Document discovery`, two as `Found document` and one as `No documents` | evaluator |
| AC-32 | DRUN | open the `Found document` item for `https://c2.example/report-a.pdf` | The URL `https://c2.example/report-a.pdf` is shown | evaluator |
| AC-32b | Same as AC-32 | look at the item's fields | The company match value `none` is shown | evaluator |
| AC-33 | DRUN | reject that item on the page, then reload | The item shows the state `final` with decision `reject` | evaluator |
| AC-34 | Universe [C5] | `run_discovery` | The queue holds no item | unit |
| AC-35 | Universe [C4] | `run_discovery` | The result row's `documents_found` has one entry with `company_id` `C4`, `doc_type` `10-K`, `url` `https://c4.example/annual-report-2025.pdf`, `sha256` S4, `company_match` `name`, `page_count` 3, `reporting_year` 2025, `alias_of` null, `review` null | unit |
| AC-36 | An identity run for company I1, name `Acme Corp`, with the identity agents stubbed to return verdict `resolved`, not flagged, `resolved_website` `https://acme.example`, `resolved_cik` null | `arp identity enriched-universe <run_id> --out <file>` | `<file>` holds a JSON list of length 1 whose object has `company_id` `I1`, `name` `Acme Corp`, `website` `https://acme.example`, `cik` null | unit |
| AC-39 | Universe [C1, C2]; the run is stopped after C1's result is stored (1 item queued), then resumed with `resume_run` | resume finishes | The run manifest's `review_count` is 3 | unit |
| AC-39b | Same as AC-39 | read the run's review queue | It holds exactly 3 items: `no_documents:C1`, `discovered:C2:S1`, `discovered:C2:S2` | unit |
| AC-37 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |
| AC-38 | The existing frontend checks | `npm run lint && npx tsc -b && npm test` | Exit code 0 | unit |

Must not change: discovery results for documents that pass the check (AC-35), EDGAR/ESEF documents (AC-34),
identity resolution export (AC-36), resume counts (AC-39), the existing suites (AC-37, AC-38).
