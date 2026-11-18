# Discovery Review Queue Implementation Plan

Status: draft, awaiting owner approval, 2026-11-08. Execution: factory implement session (never with the `holdout` repo attached).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A discovery run queues one review item per flagged PDF and per empty company in the existing review queue; a reviewer's reject drops the document from warm and the theme run for good, an approve stops it being queued again.

**Architecture:** Discovery reuses the shared queue (`queue_for_review`, `REVIEWABLE_RUN_TYPES`, `decide`) like identity does. Two new item kinds; the per-company manifest gains a `review` mark that `diff_and_record` and `download_documents` honour; `decide` calls one new function, `arp/discovery/review.py::apply_decision`, when a `discovered_document` item reaches a final state. The result row and its items are written in one `record_company_result` call.

**Tech Stack:** FastAPI, Pydantic, pytest (`httpx.MockTransport`, `TestClient`); React + TypeScript.

**Spec:** `docs/superpowers/specs/2026-11-03-discovery-review-queue-design.md` (AC ids below refer to it).

## Global Constraints

- Kinds and keys: `discovered_document` → `discovered:<company_id>:<sha256>` (decisions approve, reject, escalate); `no_documents` → `no_documents:<company_id>` (decisions approve, escalate).
- `no_documents` is queued only when `triggered_by == "manual"`; document items are queued on every run unless the entry's `review == "approved"`.
- Reason codes: `match_ambiguous` (company_match `none`), `check_failed` (`no_text`), `no_documents` (new `ReasonCode` value). Nothing else is queued (EDGAR/ESEF have `company_match` None).
- Payload keys, `discovered_document`: `company_id, name, url, doc_type, local_path, sha256, company_match, page_count, reporting_year, reason_codes`. `no_documents`: `company_id, name, homepage_used, homepage_unreachable, crawl_error, reason_codes`.
- Reject moves the file to `<documents_dir>/_rejected/<company_id>/<doc_type>/<file name>` (overwrite allowed); blob store and `_captures.jsonl` untouched. Approve leaves the file.
- Nothing happens until the item is in `FINAL_STATES`; the decision applied is the item's *effective* row, not the last row posted.
- CLI line exactly: `<n> items queued for review (open the Review page)`, printed only when n > 0.
- 422 text comes from `_check_kind` unchanged: `reject is not a decision for a no_documents item`.
- After any request/response model change: `cd backend && python scripts/export_openapi.py`, `cd frontend && npm run gen:api`, fix `npx tsc -b`, commit both generated files.
- No new dependencies. No change to `download_documents`' return type (non-goal; 5 callers).
- Test changes: add tests; change none. If an existing test must change, say so in the PR.

## Spec questions (the spec is not changed; owner decides)

1. **AC-33 looks unreachable in the app.** `GET /api/review/items` returns open items only (`list_open_items` drops `FINAL_STATES`, `arp/review/items.py`), and the Review page only calls it. After Reject the item is `final`, so after reload it is no longer listed and nothing on the page shows "state final, decision reject". Options: (a) AC-33 checks the item through `GET /api/review/runs/{run_id}/items/{item_key}/context` (`state` final, decision `reject`) instead of the page; (b) add a "decided" list to the Review page (new scope). The plan builds neither; the page does show the decision right after the click, before any reload (`ReviewControls.tsx:183`).
2. **Flipping a final decision.** The spec says undoing is a non-goal, but `decide` accepts a new round on a final item. Reject then Approve would mark the manifest `approved` while the file sits in `_rejected/`; Approve then Reject would move it. Plan default: `apply_decision` ignores an approve when the entry is already `rejected` (stays dropped) and honours reject after approve. Confirm or say otherwise.
3. **Undecided items come back.** A flagged document nobody has decided is queued again by every scheduled run (about daily), as a new queue row under the same key. The key is the same, so it is one item, but `review_count` grows by one per run. Spec §Queueing says this is intended ("scheduled runs do queue them"); noting it because the Review badge count will rise while nothing is decided.
4. **`run_discovery` has no `transport` parameter.** AC-1..23 say "`run_discovery` with an `httpx.MockTransport`", but only `execute_discovery_run` takes `transport`. Plan: tests use `create_discovery_run` + `execute_discovery_run` as `tests/test_known_reports.py` does (so `triggered_by="schedule"` goes to `create_discovery_run`); AC-10 monkeypatches `arp.cli.discovery.run_discovery` with a wrapper that injects the stand-in client and transport. No product change.

## Review Focus

1. Crash between `record_company_result` and `record_progress`: items queued, `review_count` short by that company's items. Pin in Task 2 (test calls `record_company_result` then lets the run resume; count must be 3 afterwards, AC-39).
2. Decision applied on a missing file (already moved, or working copy deleted): the decision row is already written, so `apply_decision` must still set the manifest mark and not raise. Test in Task 3.
3. Second reviewer disagrees, an approver resolves: the resolution row decides. Test in Task 3 (`state` `final` via `resolution`, effective = resolution).
4. Same bytes at a new URL after a reject (AC-18) and a rejected URL that now serves new bytes: the second is skipped without a request (the URL is rejected). Spec-conformant; test the URL skip with changed bytes so it is visible. Task 1.
5. A company id with `-` or `.` (allowed by `safe_id`) in the item key `discovered:<company_id>:<sha256>`: the decision endpoint, `apply_decision` and the manifest file name must agree on the id. Test in Task 3 with company id `C-2.x`.

---

### Task 1: Manifest `review` mark and download rules

**Files:**
- Modify: `backend/arp/schemas/discovery.py:18-33` (`DiscoveredDocument.review`)
- Modify: `backend/arp/discovery/change_detector.py` (`diff_and_record`; add `set_review`)
- Modify: `backend/arp/discovery/downloader.py` (`download_documents`)
- Test: `backend/tests/test_discovery_review_manifest.py` (new; fixtures and `_Site` style of `tests/test_known_reports.py`)

**Interfaces:**
- Produces:
  - `DiscoveredDocument.review: Literal["approved", "rejected"] | None = None`.
  - `ChangeDetector.diff_and_record` sets `doc.review = prior["review"]` when `prior` has the same URL and sha256; a new sha256 leaves `None`.
  - `ChangeDetector.set_review(company_id: str, url: str, review: Literal["approved", "rejected"]) -> bool` — writes the mark into the manifest entry, returns `False` when the URL is not in the manifest.
  - `download_documents`: a candidate whose URL is a `known` entry with `review == "rejected"` is skipped before any request; a downloaded body whose sha256 equals a rejected known entry's sha256 is neither written to the working folder nor returned (the blob/capture record still happens).

- [ ] **Step 1: Write failing tests** (all `unit`, no network):
  - `test_ac35_passing_document_row`: C4 fixture → one `documents_found` entry with exactly the AC-35 values and `review is None`.
  - `test_review_kept_for_same_url_and_bytes`: manifest entry `review="approved"`, same URL, same bytes → returned doc has `review == "approved"` (AC-22 basis).
  - `test_review_cleared_for_new_bytes` (AC-23 basis).
  - `test_rejected_url_not_requested` (AC-17): known entry rejected → `site.to(url) == []`, same with changed bytes (Review Focus 4).
  - `test_rejected_sha_at_new_url_not_written` (AC-18): bytes B1 at `copy.pdf` → no file with sha S1 under `<documents_dir>/C2/`, not in the returned list.
  - `test_set_review_unknown_url_returns_false`.
- [ ] **Step 2:** `cd backend && ruff check . && python3 -m pytest tests/test_discovery_review_manifest.py -q` → new tests FAIL.
- [ ] **Step 3: Implement.** Field first (the manifest stores it automatically via `model_dump`); `known` already reaches `download_documents`; compute the rejected sha set once from `known`; hash check goes right after `content_key` is computed, before `dest_path.write_bytes`.
- [ ] **Step 4:** the new file plus `tests/test_known_reports.py` PASS (AC-37 slice).
- [ ] **Step 5: Commit** `feat(discovery): manifest review mark, rejected documents are not downloaded again`.

### Task 2: Queue the items, in one write with the result

**Files:**
- Modify: `backend/arp/schemas/review.py:11-26,89-97` (`ReasonCode.NO_DOCUMENTS = "no_documents"`; `ReviewItemKind.DISCOVERED_DOCUMENT`, `NO_DOCUMENTS`)
- Modify: `backend/arp/review/items.py:15,24` (`"discovery"` in `REVIEWABLE_RUN_TYPES`; `_queue_kind` maps by payload: has `url` → `discovered_document`, else `no_documents`)
- Modify: `backend/arp/discovery/pipeline.py:203-210` and the `run_batch` call (`write_result`, `_on_success`)
- Create: `backend/arp/discovery/review.py` (`review_items`, next task adds `apply_decision`)
- Modify: `backend/arp/cli/discovery.py` (`discover_run` prints the line)
- Modify: `backend/arp/orchestration/jobs.py:229-232` (docstring line about discovery only)
- Regenerate: `frontend/src/api/openapi.json`, `schema.gen.ts`
- Test: `backend/tests/test_discovery_review_queue.py` (new)

**Interfaces:**
- Consumes: Task 1's `review` field.
- Produces:
  - `review_items(company: CompanyRef, result: DiscoveryCompanyResult, *, triggered_by: str) -> list[tuple[str, dict]]` in `arp/discovery/review.py` — `(item_key, payload)` pairs per Global Constraints; a document with `review == "approved"` or `company_match` in (`identifier`, `name`, `None`) yields nothing; empty `documents_found` yields `no_documents:<id>` only when `triggered_by == "manual"`.
  - `execute_discovery_run` reads `triggered_by` from `run_store.load_manifest(run_id).params["triggered_by"]` (set by `create_discovery_run`), passes `write_result` calling `run_store.record_company_result(run_id, row, observations=[], review_items=items, company=company)` via `asyncio.to_thread`, and `_on_success` records `completed_delta=1, review_delta=len(items)` (recompute with `review_items` or cache per company id).

- [ ] **Step 1: Write failing tests** (fixtures C1..C5 from the spec; stand-in search client + `MockTransport`; run with `create_discovery_run` + `execute_discovery_run`; API via `TestClient` as `tests/test_review_items.py` does):
  - AC-1 `test_empty_company_queues_no_documents`; AC-2/AC-3 via `GET /api/review/items?run_id=` (`kind`, `payload.reason_codes == ["no_documents"]`).
  - AC-4 `test_scheduled_run_queues_no_empty_company` (`triggered_by="schedule"`, queue empty).
  - AC-5 two items for C2; AC-6 `["match_ambiguous"]`; AC-7 C3 `["check_failed"]`; AC-8 C4 queues nothing; AC-34 C5 (EDGAR only, stub `edgar_source`) queues nothing.
  - AC-9 `review_count == 3` for [C1, C2].
  - AC-10 `CliRunner` on `discover_app` with `arp.cli.discovery.run_discovery` wrapped to inject the stand-ins: output contains `3 items queued for review (open the Review page)`; and a run with no flagged item prints no such line.
  - AC-39 / AC-39b: stop after C1's result (cancel via `request_cancel` once C1 is recorded, or a worker that raises for C2 on the first pass), `resume_run`, then `review_count == 3` and the queue holds exactly the 3 keys.
  - Review Focus 1: result row and its items exist together (`read_results` has C1 ⇔ queue has `no_documents:C1`).
- [ ] **Step 2:** `python3 -m pytest tests/test_discovery_review_queue.py -q` → FAIL.
- [ ] **Step 3: Implement.** CLI reads the count from `run_store.load_manifest(run_id).review_count`. Use `queue_for_review` semantics through `record_company_result` (it takes `review_items=[(key, payload)]` exactly as `run_company_batch` passes them).
- [ ] **Step 4:** new tests PASS; then `tests/test_discovery_pipeline_unreachable.py tests/test_resume_run.py tests/test_jobs.py tests/test_review_items.py tests/test_review_queue.py -q` PASS unchanged (AC-37; the unreachable test's `review_count == 1` still holds: one manual `no_documents` item). `ruff check .`; export OpenAPI, `npm run gen:api`.
- [ ] **Step 5: Commit** `feat(discovery): queue flagged documents and empty companies for review`.

### Task 3: Decisions and their effect

**Files:**
- Modify: `backend/arp/review/decide.py:33-37` (`ALLOWED`: `discovered_document` → `{approve, reject, escalate}`, `no_documents` → `{approve, escalate}`), `_decide_locked` (after `append_decision`, `decide.py:235-248`)
- Modify: `backend/arp/discovery/review.py` (add `apply_decision`)
- Test: `backend/tests/test_discovery_review_decide.py` (new)

**Interfaces:**
- Consumes: Task 1 `ChangeDetector.set_review`; Task 2 items.
- Produces: `apply_decision(settings: Settings, payload: dict, decision: str) -> None`. `reject`: move `payload["local_path"]` into `<documents_dir>/_rejected/<company_id>/<doc_type>/<name>` (create dirs, overwrite) when the file exists, then `set_review(company_id, url, "rejected")`; `approve`: `set_review(..., "approved")` unless the entry is already `rejected` (spec question 2); `escalate`: nothing. Called from `_decide_locked` only when `item.run_type == "discovery"`, `kind == "discovered_document"` and the state after the decision is in `FINAL_STATES`, with `decision` taken from that state's `effective` row (`item_states(...)[item_key].effective["decision"]`). A raising `apply_decision` is logged, never fails the decision (as the gold-case hook does).

- [ ] **Step 1: Write failing tests** (run Task 2's C2 run, then `TestClient` decisions with the context `etag`; helper reused from `tests/test_review_decide.py`):
  - reject S1 with `wrong_entity` (AC-11 `state == "final"`, AC-12 no file at `local_path`, AC-13 one file in `_rejected/C2/10-K/` with sha S1, AC-14 manifest `"review": "rejected"`, AC-15 `LocalFileDocumentSource.fetch(C2)` has no sha-S1 doc, AC-16 blob store still holds S1, AC-16b capture-log line count unchanged).
  - AC-17/18/19 as end-to-end second runs (reuse Task 1 stand-ins): 0 requests for the rejected URL; no S1 file under `C2/`; second queue has no `discovered:C2:S1`.
  - approve S1 `confirmed` (AC-20 `"review": "approved"`, AC-21 file exists); AC-22 same URL and bytes → not queued; AC-23 new bytes B3 → `discovered:C2:S6` queued.
  - `second_review_sample_rate=1.0` (AC-24 `first_done`, AC-24b file exists, AC-25 `"review": null`); AC-26/AC-27 no decision → file exists, `review` null.
  - AC-28 reject on `no_documents:C1` → 422 with the exact detail; AC-29 approve → `final`; AC-30 hash of every file under `documents_dir` and `discovery_state_dir` unchanged.
  - Review Focus 2: reject when the file is already gone → decision `final`, manifest `rejected`, no exception. Review Focus 3: reviewer 1 approve, reviewer 2 reject, approver resolves reject → file moved. Spec question 2: reject then approve → manifest stays `rejected`.
- [ ] **Step 2:** `python3 -m pytest tests/test_discovery_review_decide.py -q` → FAIL.
- [ ] **Step 3: Implement** per the Interfaces. Hook sits in `_decide_locked`, so the bulk path is covered too.
- [ ] **Step 4:** new tests PASS; `tests/test_review_decide.py tests/test_review_state.py tests/test_review_identity.py -q` PASS unchanged; `ruff check .`.
- [ ] **Step 5: Commit** `feat(discovery): a reviewer's decision keeps or drops a flagged document`.

### Task 4: Review page labels

**Files:**
- Modify: `frontend/src/types.ts:68,546` (`ReviewableRunKind` + `"discovery"`; `ReviewItemKind` + the two kinds)
- Modify: `frontend/src/lib/reviewKeys.ts` (`ITEM_KIND_LABEL`: `Found document`, `No documents`; `decisionChoices`: `discovered_document` → approve, reject, escalate; `no_documents` → approve, escalate)
- Modify: `frontend/src/components/RunReviewList.tsx:19-27,59-60` (`REVIEW_KIND_LABEL.discovery = "Document discovery"`; show `url` and `company_match` outside "Full record" for these kinds)
- Modify: `frontend/src/lib/runs.ts:7,70` (`REVIEWABLE_RUN_TYPES`, label)
- Test: `frontend/tests/reviewKeys.test.ts` (add; `node:test`)

**Interfaces:** Consumes the regenerated `schema.gen.ts` from Task 2. `decisionChoices(kind, runType)` keeps its signature.

- [ ] **Step 1: Write failing tests:** `decisionChoices("no_documents")` equals `["approve","escalate"]`; `decisionChoices("discovered_document")` equals `["approve","reject","escalate"]` (neither offers `correct`); `ITEM_KIND_LABEL.discovered_document === "Found document"`, `.no_documents === "No documents"`.
- [ ] **Step 2:** `cd frontend && npm test` → FAIL.
- [ ] **Step 3: Implement.** Let `npx tsc -b` list every `Record<ReviewItemKind, …>` / `Record<ReviewableRunKind, …>` still missing a key. Reason-code display labels (`no_documents`) are added wherever `tsc` or the existing reason map demands one.
- [ ] **Step 4:** `npm run lint && npx tsc -b && npm test` PASS (AC-38). Screenshot the Review page with the seeded run (Task 5) and run `/impeccable:impeccable audit`.
- [ ] **Step 5: Commit** `feat(frontend): discovery items on the Review page`.

### Task 5: Seed script for the evaluator

**Files:**
- Create: `backend/scripts/seed_discovery_review.py`
- Test: `backend/tests/test_seed_discovery_review.py` (new)

**Interfaces:**
- Consumes: Task 2's `review_items`; `JobManager.create_run`, `RunStore.record_company_result`, `ChangeDetector.diff_and_record`/manifest.
- Produces: `main() -> str` (prints and returns the run id): one `discovery` run (`triggered_by` manual) in the configured run store with result rows for C1 and C2 and their three items (`no_documents:C1`, `discovered:C2:<S1>`, `discovered:C2:<S2>`); two small PDFs at `<documents_dir>/C2/10-K/` (bytes written by the script, no `tests` import) and manifest entries for `https://c2.example/report-a.pdf` / `report-b.pdf` with their sha256, `company_match "none"`; no network; run finished.

- [ ] **Step 1: Write failing test:** run `main()` against a tmp `Settings` and run store; the run has 3 queue items with the keys above, both files exist and hash to the keys' shas, `discovery_state_dir/C2.json` has both URLs with `review` null, and `GET /api/review/items?run_id=` lists 3.
- [ ] **Step 2:** `python3 -m pytest tests/test_seed_discovery_review.py -q` → FAIL.
- [ ] **Step 3: Implement** using `get_settings()` and `_run_store()` from `arp/cli/_shared.py`, so it writes where the e2e stack reads (`bash backend/scripts/e2e_stack.sh up`, then `python backend/scripts/seed_discovery_review.py`). Reuse `review_items` for the items so the seed cannot drift from the product.
- [ ] **Step 4:** test PASSes; then run the DRUN by hand: open the Review page, confirm AC-31/32/32b labels and fields, reject the report-a item.
- [ ] **Step 5: Commit** `test(discovery): seed script for the review evaluator`; open the PR with `Spec: discovery-review-queue`, a `risk:` label, every test change listed, and the answer to spec questions 1 and 2.

---

## Acceptance coverage

| Row(s) | Check | Task |
|---|---|---|
| AC-1, 2, 3, 4 | unit | 2 |
| AC-5, 6, 7, 8, 34 | unit | 2 |
| AC-9, 10 | unit | 2 |
| AC-11, 12, 13, 14, 15, 16, 16b | unit | 3 |
| AC-17, 18 | unit | 1 (rules), 3 (end to end) |
| AC-19 | unit | 3 |
| AC-20, 21, 22, 23 | unit | 3 (22, 23 rules also in 1) |
| AC-24, 24b, 25, 26, 27 | unit | 3 |
| AC-28, 29, 30 | unit | 3 |
| AC-31, 32, 32b | evaluator | 5 (seed + DRUN), labels in 4 |
| AC-33 | evaluator | 5, **blocked on spec question 1** |
| AC-35 | unit | 1 |
| AC-36 | unit | 2 step 4 (existing identity export; add `test_ac36_enriched_universe_cli` to `tests/test_discovery_review_queue.py` only if `tests/` has no test for `arp identity enriched-universe`) |
| AC-37 | unit | every task's step 4 runs the neighbouring existing suites; final: `python3 -m pytest backend/tests` |
| AC-38 | unit | 4 |
| AC-39, 39b | unit | 2 |

Holdout rows: 0 (the spec makes every row `unit` or `evaluator`).

After merge: behaviour changed (discovery now queues review items and decisions edit the manifest and move files), so `openwiki/` needs the weekly `/context-refresh`; do not edit it by hand.
