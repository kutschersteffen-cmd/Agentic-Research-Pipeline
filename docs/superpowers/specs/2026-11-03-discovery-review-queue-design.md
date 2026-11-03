# Discovery review queue

Spec slug: `discovery-review-queue`. Gap G3 of the universe-to-documents review
(https://claude.ai/artifact/FH7Q7fWJVUpxTRbjyKLx5a).

Status: draft.

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

## Left to the builder

Where the item-building helper lives; frontend labels other than those in the Acceptance table; how the
`_rejected` move handles an existing file of the same name (overwrite is acceptable).

## Acceptance

`holdout` rows run discovery with a stand-in search client and an `httpx.MockTransport` (as
`tests/test_known_reports.py` does) and read the run store, the manifest and the documents folder.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Universe with company C1; no source returns any document; run started by hand | `run_discovery` | The run's review queue holds exactly one item for C1, key `no_documents:C1` | holdout |
| AC-2  | Same as AC-1 | read item `no_documents:C1` via `GET /api/review/items?run_id=<run>` | Its `kind` is `no_documents` | holdout |
| AC-3  | Same as AC-1 | read the item's payload | `reason_codes` is `["no_documents"]` | holdout |
| AC-4  | Same as AC-1, but `triggered_by="schedule"` | `run_discovery` | The run's review queue is empty | holdout |
| AC-5  | Company C2; the crawl downloads one PDF whose text names neither C2 nor its LEI/ISIN (`company_match` `none`), sha256 S | `run_discovery` | The queue holds item `discovered:C2:S` with `kind` `discovered_document` | holdout |
| AC-6  | Same as AC-5 | read the item's payload | `reason_codes` is `["match_ambiguous"]` | holdout |
| AC-7  | Company C3; one downloaded PDF with under 200 characters of text (`company_match` `no_text`) | `run_discovery` | That document's item has `reason_codes` `["check_failed"]` | holdout |
| AC-8  | Company C4; one downloaded PDF that names C4 (`company_match` `name`) | `run_discovery` | The queue holds no item whose key starts with `discovered:C4:` | holdout |
| AC-9  | Universe: C1 as in AC-1 and C2 with two failing PDFs; run by hand | `run_discovery` | The run manifest's `review_count` is 3 | holdout |
| AC-10 | Same as AC-9 | `arp discover run --universe <file>` | Output contains the line `3 items queued for review (open the Review page)` | holdout |
| AC-11 | Item `discovered:C2:S` from AC-5 | `reject` with reason `wrong_entity`, reaching a final state | The file at the payload's `local_path` no longer exists | holdout |
| AC-12 | Same as AC-11 | list `<documents_dir>/_rejected/C2/<doc_type>/` | It contains a file with the same name and sha256 S | holdout |
| AC-13 | Same as AC-11 | read `<discovery_state_dir>/C2.json` | The entry for the document's URL has `"review": "rejected"` | holdout |
| AC-14 | Same as AC-11 | `LocalFileDocumentSource.fetch(C2)` | Returns no document with sha256 S | holdout |
| AC-15 | Same as AC-11; a second run whose crawl finds the same URL | `run_discovery` | The mock transport receives 0 requests for that URL | holdout |
| AC-16 | Same as AC-11; a second run finds the same bytes (S) at a new URL | `run_discovery` | No file with sha256 S exists under `<documents_dir>/C2/` | holdout |
| AC-17 | Same as AC-16 | read the second run's queue | It holds no item `discovered:C2:S` | holdout |
| AC-18 | Item `discovered:C2:S` | `approve`, reaching a final state | The manifest entry for its URL has `"review": "approved"` | holdout |
| AC-19 | Same as AC-18 | check the payload's `local_path` | The file still exists | holdout |
| AC-20 | Same as AC-18; a second run returns the same URL with the same bytes | `run_discovery` | The second run's queue holds no item for that document | holdout |
| AC-21 | Same as AC-18; a second run returns the same URL with new bytes (sha256 T) | `run_discovery` | The second run's queue holds item `discovered:C2:T` | holdout |
| AC-22 | Item `discovered:C2:S` with the second-review sample rate set to 1.0 | first reviewer rejects | The file at `local_path` still exists and the manifest entry has no `review` key, or `"review": null` | holdout |
| AC-23 | Item `no_documents:C1` | `reject` | `422` with message `reject is not a decision for a no_documents item` | holdout |
| AC-24 | Item `no_documents:C1` | `approve` | State is final; no file under `<documents_dir>` or `<discovery_state_dir>` changes | holdout |
| AC-25 | A discovery run with items from AC-9, the app running | open the Review page | The three items are listed, each labelled `Document discovery`, two as `Found document` and one as `No documents` | evaluator |
| AC-26 | Same as AC-25 | open a `Found document` item | Its URL and `company_match` value are shown | evaluator |
| AC-27 | Same as AC-25 | reject a `Found document` item on the page | The item shows a final rejected state after reload | evaluator |
| AC-28 | Company C5 whose only document is an EDGAR 10-K | `run_discovery` | The queue holds no item for C5 | holdout |
| AC-29 | A run where every company gets documents that name it | `run_discovery` | Each result row's `documents_found` equals the same run on `main`, apart from the new `review` field being `null` | holdout |
| AC-30 | Identity run with one flagged company | `arp identity review` approve, then `enriched-universe` | Same output as on `main` | holdout |
| AC-31 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |
| AC-32 | The existing frontend checks | `npm run lint && npx tsc -b && npm test` | Exit code 0 | unit |

Must not change: discovery results for documents that pass the check (AC-29), EDGAR/ESEF documents (AC-28),
identity review (AC-30), the existing suites (AC-31, AC-32).
