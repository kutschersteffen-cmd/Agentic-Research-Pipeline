# Argus step 2 Documents (slice 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step 2 of the Argus flow (`#/argus/<flow_id>/2`) finds or takes the documents for the flow's companies, checks each file (company named, year as expected), lets the user keep or remove each one, and saves that choice on the flow, so the old Extraction screen is no longer needed for documents.

**Architecture:** The flow (`runs_dir/_flows/<id>.json`) gains `reporting_year`, `source`, `discovery_run_id` and `decisions` (file key → `kept` | `removed`). The file list is computed on every read from what is stored for the flow's companies (documents folder and registered documents), each file checked once with the existing `arp.discovery.doc_check.check_document` (result cached by file content hash in the flow folder). Finding documents reuses the discovery run; `Official filings` runs it with web search and crawling off. Uploads reuse the documents folder convention. The frontend adds step 2 to `ArgusFlow.tsx`, with page-1 images from the existing pages endpoint and `SourcePanel` for the side panel.

**Tech Stack:** FastAPI + pydantic (backend), React 19 + TypeScript, `node:test`, pytest + Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` ("Every step", "Step 2: Documents", slice 3). Builds on slice 2 (`arp/argus/flows.py`, `arp/argus/companies.py`, `arp/api/routers/argus.py`, `frontend/src/pages/ArgusFlow.tsx`).

## Global Constraints

- Exact copy: `Reporting year` (default: previous calendar year); sources `I upload them`, `From the import folder`, `Official filings`, `Filings + company websites`; checks `✓ <company name>, <year>`, `Company not found in document`, `Year <found>, expected <reporting year>`, `Year unclear`; buttons `Keep`, `Remove`, `Keep all that pass`, `Remove all`, `Continue with <N> files for <M> companies`; duplicate upload `Duplicate of <file name>, skipped`.
- `From the import folder` is shown but disabled with `Available once the import folder is set up` until slice 9.
- Remove leaves the file out of this flow only: the file stays on the company, so step 1's `Documents on file` does not change.
- A file failing its check is never kept by `Keep all that pass`; it can still be kept one by one.
- Nothing is searched or downloaded until the user picks a find source and clicks `Find documents`.
- Steps 3 to 5 are not built yet: `Continue with N files for M companies` saves `step = 3` and hands the kept companies to the old Extraction screen at its Schema tab, as slice 2 does for step 1 (spec, "Until the new steps exist").
- After the response models change: `cd backend && python scripts/export_openapi.py`, `cd frontend && npm run gen:api`, commit both generated files.
- Delivers AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-74, and AC-9 for step 2. AC-15 to AC-17 still need step 3 (slice 4).

## Review Focus

1. **Company keys from step 1 must be safe ids.** The Argus run found that a company added by name only gets its name as `company_id` (`Siemens AG`), which every documents endpoint rejects (`Invalid company_id`). Task 1 fixes the key; existing flows with such keys are re-keyed when read. Test both.
2. **A PDF with no text, an HTML page, a broken file:** the check reads `Year unclear` or `Company not found in document`, never a 500. HTML files get the name and year check on their text too.
3. **Two companies in the flow sharing a document folder** (same universe id): one file list per company id, no double rows.
4. **The same upload twice:** detected by content hash, not stored again, row reads `Duplicate of <file name>, skipped` (AC-24).
5. **A discovery run still running when the page reloads:** step 2 shows it as running and keeps polling; files appear as the run records them.

---

### Task 1: Safe company keys (bug from the Argus run)

**Files:** Modify `backend/arp/argus/companies.py` (`register`), `backend/arp/argus/flows.py` (re-key on read); Test `backend/tests/test_argus_companies.py`

- [ ] Tests: `register(..., {"name": "Siemens AG"})` returns a `company_id` that passes `safe_id`; a matched company with no universe or own id gets `str(entity_id)`; a flow file holding `company_id: "Siemens AG"` reads back with a safe key and the same name.
- [ ] Fix: the fallback key is `str(entity_id)` when matched, else a slug of the name (`siemens-ag`), never the raw name. Run `cd backend && python3 -m pytest tests/test_argus_companies.py`, expect pass. Commit.

### Task 2: Flow documents model and endpoints

**Files:** Modify `backend/arp/argus/flows.py`; Create `backend/arp/argus/documents.py`; Modify `backend/arp/api/routers/argus.py`; Test `backend/tests/test_argus_documents.py`

**Produces:**
- `ArgusFlow` gains `reporting_year: int | None = None` (None reads as previous calendar year), `source: Literal["upload", "import", "filings", "filings_web"] | None = None`, `discovery_run_id: str | None = None`, `decisions: dict[str, Literal["kept", "removed"]] = {}`.
- `FlowFile`: `key` (`<company_id>/<doc_type>/<filename>`, or `doc:<doc_id>` for registered files without a folder file), `company_id`, `company_name`, `doc_type`, `filename`, `year: int | None`, `source` (`upload` | `filings` | `web`), `check: str`, `passes: bool`, `state: "kept" | "removed" | None`, `page_url: str | None` (page 1 image), `duplicate_of: str | None`.
- `ArgusFlowView` gains `files: list[FlowFile]` and `discovery: {run_id, status} | None`.
- Endpoints (analyst role for writes): `PATCH /api/argus/flows/{id}` also takes `reporting_year`, `source`; `POST /flows/{id}/documents/find` starts one discovery run for the flow's matched companies (web off for `filings`), stores `discovery_run_id`; `POST /flows/{id}/documents/upload` (form: `company_id`, `doc_type`, `file`) stores the file like `/api/documents/upload`, skips a same-content duplicate; `POST /flows/{id}/files` with `{"keys": [...], "state": "kept" | "removed"}`, and `{"all_that_pass": true}` or `{"all": true, "state": "removed"}`.

- [ ] Tests: the check strings for a PDF naming the company and year (pass), naming only another company (AC-20), with year 2023 when 2025 is expected (AC-21), with no year (`Year unclear`); remove one file → absent after reload, folder untouched (AC-18); keep all that pass with 9 files, 2 failing → 7 kept, 2 neither (AC-19); remove all (AC-74); duplicate upload (AC-24); find with `filings` starts a run with web off; unknown flow → 404.
- [ ] Implement; checks cached by content hash under `runs_dir/_flows/_checks/`. Run `python3 -m pytest tests/test_argus_documents.py tests/test_argus_flows.py`, expect pass. Export OpenAPI, regenerate the client. Commit.

### Task 3: Discovery without the web

**Files:** Modify `backend/arp/discovery/pipeline.py` (`execute_discovery_run`, `_discover_for_company`: `web: bool = True`); Test `backend/tests/test_discovery_pipeline.py` (append)

- [ ] Test: with `web=False` the search client and crawler are never called; EDGAR and ESEF still are. Existing discovery tests pass unchanged.
- [ ] Implement, run the discovery tests, commit.

### Task 4: Frontend model for step 2

**Files:** Modify `frontend/src/lib/argusStart.ts`; Test `frontend/tests/argusStart.test.ts` (append)

**Produces:** `continueFilesLabel(files: FlowFile[]): { text: string; disabled: boolean }` (counts kept files and their distinct companies; disabled at 0), `previousYear(today: Date): number`.

- [ ] Tests for 7 kept files over 3 companies (`Continue with 7 files for 3 companies`), 0 kept (disabled), and the previous year. Run `cd frontend && node --test --experimental-strip-types tests/argusStart.test.ts`. Implement, pass, commit.

### Task 5: Step 2 on the flow page

**Files:** Modify `frontend/src/pages/ArgusFlow.tsx` (step 2 view; the step bar links `2 Documents` once step 1 is done), `frontend/src/index.css` (`.argus-files*`); e2e `backend/tests/e2e/test_argus_flow.py` (append a step 2 test with an uploaded PDF)

- [ ] Step 2: `Reporting year` input; the four sources as radio buttons (import folder disabled); `Find documents` for the two find sources, with the run's progress; an upload row per company for `I upload them`; the file table (company, file, type, year, source, check, Keep/Remove), failing rows in the warning style; `Keep all that pass`, `Remove all`; hover on a file name shows the page-1 image; click opens `SourcePanel`; the continue button from `continueFilesLabel`.
- [ ] `cd frontend && npm run lint && npx tsc -b && npm test`, the e2e test, and a Playwright run through steps 1 and 2 with 3 companies, light and dark screenshots in `docs/design-shots/`; `/impeccable:impeccable audit`. Commit, push, PR with `Spec: argus-simplified-pipeline` and `risk:normal`.
