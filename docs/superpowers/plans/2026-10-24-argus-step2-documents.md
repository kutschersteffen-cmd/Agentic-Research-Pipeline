# Argus step 2 Documents (slice 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step 1's **Continue with N companies** opens step 2 of the same flow (`#/argus/<flow_id>/2`), where the user sets the reporting year, gathers files (upload, official filings, filings plus company websites), sees each file's check, keeps or removes files one by one or as a set, previews a PDF's first page on hover and opens a file in the side panel; all of it is saved on the flow.

**Architecture:** The flow JSON (`ArgusFlow`, slice 2) gains `reporting_year`, `doc_source`, `uploads` (files uploaded in this flow), `discovery_run_id` and `decisions` (file key → `kept`/`removed`). Filings and web files are not copied into the flow: every read builds the file list from `uploads` plus the flow's discovery run results, and computes each file's check text from its stored year and company match against the current reporting year. Removing only writes a decision; no file is ever deleted, so step 1's **Documents on file** is unchanged. Official filings reuse the discovery run with its web search and crawl switched off (`include_web=False`); uploads reuse `check_document` from `arp/discovery/doc_check.py`. The frontend adds step 2 to `ArgusFlow.tsx`, reusing `SourcePanel`, `FileImg` and the document page endpoint.

**Tech Stack:** FastAPI + pydantic (backend), React 19 + Vite + TypeScript, `node:test`, pytest (+ reportlab PDFs from `tests/pdf_fixtures.py`) and Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` (sections "Every step", "Step 2: Documents", "Calls made by the spec author" on the reporting year, data rule 3 on duplicates, slice 3). Builds on slice 2's `backend/arp/argus/flows.py`, `backend/arp/api/routers/argus.py` and `frontend/src/pages/ArgusFlow.tsx`.

## Global Constraints

- Exact copy: `Reporting year`; sources `I upload them`, `Official filings`, `Filings + company websites`; checks `✓ name, year`, `Company not found in document`, `Year <found>, expected <reporting year>`, `Year unclear`, `Duplicate of <file name>, skipped`; buttons `Keep`, `Remove`, `Keep all that pass`, `Remove all`; states `Kept`, `Removed`; `Continue with <N> files for <M> companies` (`1 file`, `1 company` singular).
- `From the import folder` comes in slice 9: **shown, disabled**, with the hint `Comes with the shared import folder`, so the four sources read as the spec lists them.
- `Reporting year` defaults to the previous calendar year when the flow is created; flows saved before this slice read the same default.
- Check order (first that applies): duplicate → `Company not found in document` (doc check `none` or `no_text`) → `Year unclear` (no year) → `Year <y>, expected <r>` → `✓ name, year`. Official filings (EDGAR, ESEF) count as a company match: they are fetched by the company's own CIK or LEI.
- Year of a file: a leading `<20xx>_` in the file name, else the year `check_document` reads from the PDF, else none. EDGAR: `reporting_year("", text)`; ESEF: the year of `period_end`.
- Remove never deletes a file or a registry row. No source button deletes anything.
- No `role="tablist"` on step 2 (the source choice is a radio group); exactly one step bar. Step bar items 1 and 2 are links once reached; 3 to 5 stay plain text.
- Any signed-in analyst can change any draft (`require_role("analyst")` on writes, `current_user` on reads).
- After the response models change: `cd backend && python scripts/export_openapi.py`, `cd frontend && npm run gen:api`, commit `openapi.json` and `schema.gen.ts`.
- This slice delivers AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-74, and AC-9 for step 2. AC-15 to AC-17 need step 3 (slice 4); AC-58 needs the import folder (slice 9). The PR lists them as waiting.

## Calls I made (owner to check)

1. **Files that pass their check start as `Kept`; failing files start undecided** (neither word, both buttons). The continue button counts `Kept` files only. This is the one reading under which AC-18 (removing a file lowers the count by 1) and AC-19 (after **Keep all that pass**, 7 kept and a count of 7) both hold.
2. **Step 2 uploads take PDFs only** (`accept=".pdf"`, 400 `Upload a PDF` otherwise): the name and year checks read PDF text. The old Documents screen keeps accepting any type.
3. **An identical upload** is never stored twice: `/api/documents/upload` (the old screen too) returns the existing file as `duplicate_of` and writes nothing. In step 2 the row reads `Duplicate of <file name>, skipped` when that file is already in the flow; when it is on the company but not yet in this flow, the existing file is added to the flow instead.
4. **SEC filings have no file in the app's folder**, so they get no hover image; their name opens the SEC page in a new tab instead of the side panel.
5. **Continue with N files** saves step 3 as reached and, until slice 4 builds step 3, hands the company list to the old Extraction screen, as step 1's button did in slice 2 (shortcut, noted in code). That screen does not yet honour **Remove**.

## Review Focus

1. **Changing the reporting year after files are checked** (2025 → 2023): every check is recomputed on the next read, so `Year 2023, expected 2025` turns into `✓ name, year`; a stored check text would go stale. Test in Task 2.
2. **The same PDF uploaded twice** (AC-24) and **the same PDF uploaded for two companies:** one stored file per company, the duplicate row for the first case, two independent files for the second. Test in Task 2.
3. **A finished filings run, then a second click on `Official filings`:** no second discovery run while one is running (409 `Already looking for files`); after it finished, a new run replaces the link and decisions on files it finds again are kept (same key). Test in Task 3.
4. **A file key from an old or forged request** in a decision (`../x`, a key not in the flow): ignored with 400 `Unknown file`, nothing written. Test in Task 2.
5. **A flow saved by slice 2** (no `reporting_year`, `uploads`, `decisions` keys) opens on step 2 with the default year and no files, not a 500. Test in Task 1.

---

### Task 1: Flow fields, PATCH and the step 1 → step 2 hand-off

**Files:**
- Modify: `backend/arp/argus/flows.py`, `backend/arp/api/routers/argus.py`
- Test: `backend/tests/test_argus_flows.py` (new cases only)

**Interfaces:**
- Produces (`flows.py`):
  - `class FlowFile(BaseModel)`: `key: str` (`<company_id>/<doc_type>/<file name>` for a file under `documents_dir`, else the source URL), `company_id: str`, `doc_type: DocType`, `file_name: str`, `source: Literal["upload", "filing", "web"]`, `on_disk: bool`, `url: str | None = None`, `year: int | None = None`, `company_match: str | None = None` (doc check value; None = official filing), `duplicate_of: str | None = None`
  - `ArgusFlow` gains `reporting_year: int = Field(default_factory=lambda: date.today().year - 1)`, `doc_source: Literal["upload", "import", "filings", "web"] | None = None`, `uploads: list[FlowFile] = []`, `discovery_run_id: str | None = None`, `decisions: dict[str, Literal["kept", "removed"]] = {}`
- Produces (router): `FlowPatch` gains `step: int | None` (1..5; stored as `max(flow.step, step)`), `reporting_year: int | None` (`ge=1990, le=2100`), `doc_source`, `decisions: dict[str, Literal["kept","removed"]] | None` (merged into `flow.decisions`; a key not in the flow's files → 400 `Unknown file`). `patch_flow` applies these explicitly instead of `setattr` for every field.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_flow_has_previous_year_and_no_files(client):
    f = client.post("/api/argus/flows").json()
    assert (f["reporting_year"], f["files"], f["decisions"]) == (date.today().year - 1, [], {})

def test_step_never_goes_back(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.patch(f"/api/argus/flows/{fid}", json={"step": 2}).json()["step"] == 2
    assert client.patch(f"/api/argus/flows/{fid}", json={"step": 1}).json()["step"] == 2

def test_reporting_year_bounds(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2023}).json()["reporting_year"] == 2023
    assert client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 23}).status_code == 422

def test_slice_2_flow_file_still_opens(client, flows_dir):  # Review Focus 5
    write_old_flow(flows_dir, "a" * 32)  # the slice-2 JSON keys only
    assert client.get(f"/api/argus/flows/{'a' * 32}").json()["reporting_year"] == date.today().year - 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_argus_flows.py -v`
Expected: FAIL (`KeyError: 'reporting_year'`)

- [ ] **Step 3: Implement the fields, `FlowPatch` and `ArgusFlowView.files: list[FlowFileView] = []`** (Task 2 fills it)

- [ ] **Step 4: Run the tests, then ruff**

Run: `cd backend && python3 -m pytest tests/test_argus_flows.py -v && ruff check .`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/arp/argus/flows.py backend/arp/api/routers/argus.py backend/tests/test_argus_flows.py
git commit -m "Argus flows: reporting year, files, decisions, step reached"
```

### Task 2: Uploads with checks, the file list, duplicates

**Files:**
- Create: `backend/arp/argus/documents.py`
- Modify: `backend/arp/api/routers/documents.py` (`upload_document` uses `save_upload`), `backend/arp/api/routers/argus.py`
- Test: `backend/tests/test_argus_documents.py`, `backend/tests/test_documents_router.py` (new case only; `test_upload_keeps_both_files_with_the_same_name` is unchanged)

**Interfaces:**
- Consumes: `check_document(path, company) -> DocCheck` (`arp/discovery/doc_check.py`); `safe_id`, `safe_filename`.
- Produces (`documents.py`):
  - `save_upload(documents_dir: Path, company_id: str, doc_type: DocType, filename: str, data: bytes) -> tuple[Path, str | None]` — the stored path and, for content identical (sha256) to a file already anywhere under `documents_dir/<company_id>/`, that file's path and its name as `duplicate_of` with nothing written. Otherwise today's `-2`, `-3` naming. Raises `UnsafeIdentifierError`.
  - `file_year(file_name: str, read: int | None) -> int | None` — leading `20xx_` wins, else `read`.
  - `check_text(f: FlowFile, reporting_year: int) -> str | None` — the Global Constraints order; `None` means passed, which the view writes as `✓ name, year`.
  - `class FlowFileView(FlowFile)`: `check: str` (the text shown), `passed: bool`, `state: Literal["kept", "removed"] | None` (the decision, else `kept` when passed and not a duplicate, else None)
  - `file_views(flow: ArgusFlow, discovered: list[FlowFile]) -> list[FlowFileView]` — uploads then discovered, one per key (a later duplicate key is dropped), in that order.
- Produces (router): `POST /api/argus/flows/{flow_id}/documents/upload` (multipart `company_id` (one of the flow's companies, else 400 `Not in this extraction`), `doc_type: DocType`, `file`) → `ArgusFlowView`. Non-PDF → 400 `Upload a PDF`; over `max_upload_bytes` → 413 as today. `doc_source` is set to `upload`.
- `/api/documents/upload` response gains `duplicate_of: str | None`.

- [ ] **Step 1: Write the failing tests** (PDFs from `tests/pdf_fixtures.make_pdf`; the Task 1 `client` with a flow holding Apple (LEI HWUPKR0MPOU8FGXBT394) and Microsoft)

```python
def test_pdf_naming_apple_and_the_year_passes(flow_client):  # reporting year 2025
    f = upload(flow_client, "apple", "2025_10-K.pdf", ["Apple Inc. Annual Report 2025"])
    [row] = f["files"]
    assert (row["check"], row["passed"], row["state"], row["year"], row["source"]) == ("✓ name, year", True, "kept", 2025, "upload")

def test_pdf_naming_only_microsoft(flow_client):  # AC-20
    [row] = upload(flow_client, "apple", "2025_r.pdf", ["Microsoft Corporation Annual Report 2025"])["files"]
    assert (row["check"], row["passed"], row["state"]) == ("Company not found in document", False, None)

def test_wrong_year_then_year_changed(flow_client):  # AC-21, Review Focus 1
    [row] = upload(flow_client, "apple", "2023_report.pdf", ["Apple Inc. Report 2023"])["files"]
    assert row["check"] == "Year 2023, expected 2025"
    assert patch(flow_client, reporting_year=2023)["files"][0]["check"] == "✓ name, year"

def test_no_year_is_unclear(flow_client): ...                # "report.pdf", text without a 20xx → "Year unclear"

def test_same_pdf_twice_is_stored_once(flow_client, docs_dir):  # AC-24, Review Focus 2
    upload(flow_client, "apple", "a.pdf", APPLE_2025); f = upload(flow_client, "apple", "a-copy.pdf", APPLE_2025)
    assert [r["check"] for r in f["files"]] == ["✓ name, year", "Duplicate of a.pdf, skipped"]
    assert len(flow_client.get("/api/documents/apple").json()["documents"]) == 1

def test_same_pdf_for_two_companies_is_two_files(flow_client): ...
def test_remove_keeps_the_file_on_disk(flow_client, docs_dir): ...  # decision removed → state "removed", file still exists
def test_unknown_file_key_is_400(flow_client): ...              # Review Focus 4: {"decisions": {"../x": "kept"}}
def test_non_pdf_and_foreign_company_are_400(flow_client): ...

async def test_upload_skips_identical_content(tmp_path):     # documents router
    first = await upload_document("acme", DocType.OTHER, UploadFile(io.BytesIO(b"one"), filename="r.pdf"), settings)
    second = await upload_document("acme", DocType.OTHER, UploadFile(io.BytesIO(b"one"), filename="s.pdf"), settings)
    assert (second["path"], second["duplicate_of"]) == (first["path"], "r.pdf")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_argus_documents.py -v`
Expected: FAIL (404 on `/documents/upload`)

- [ ] **Step 3: Implement `documents.py`, the endpoint, and fill `ArgusFlowView.files` with `file_views(flow, [])`** (`check_document` runs in `asyncio.to_thread`; `CompanyRef` comes from `flow.companies`)

- [ ] **Step 4: Run the tests, the existing documents tests, ruff**

Run: `cd backend && python3 -m pytest tests/test_argus_documents.py tests/test_argus_flows.py tests/test_documents_router.py -v && ruff check .`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/arp/argus/documents.py backend/arp/api/routers/documents.py backend/arp/api/routers/argus.py backend/tests/test_argus_documents.py backend/tests/test_documents_router.py
git commit -m "Argus step 2: uploads with name and year checks, duplicates skipped"
```

### Task 3: Official filings and filings + company websites

**Files:**
- Modify: `backend/arp/discovery/pipeline.py` (`include_web: bool = True` on `execute_discovery_run` and `_discover_for_company`: false skips search, homepage and crawl; `_edgar_filings` and `_esef_documents` set `reporting_year`), `backend/arp/api/routers/argus.py`, `backend/arp/argus/documents.py`
- Test: `backend/tests/test_argus_documents.py`, `backend/tests/test_discovery_pipeline_unreachable.py` (new case only)

**Interfaces:**
- Consumes: `create_discovery_run`, `execute_discovery_run` (as `routers/discovery.py` starts them, with `set_started_by`); `run_store.read_results(run_id)` rows = `DiscoveryCompanyResult` dumps; `run_store` manifest for status and counts.
- Produces:
  - `discovered_files(rows: list[dict], documents_dir: Path) -> list[FlowFile]` — one per `documents_found` entry: a `local_path` under `documents_dir` → `on_disk=True`, key `<company_id>/<doc_type>/<name>`, source `web`; else key = `url`, `on_disk=False`, source `filing`, `file_name` = last URL segment; `year` = `reporting_year`; `company_match` from the entry (None for EDGAR/ESEF). Entries with `alias_of` are skipped.
  - `POST /api/argus/flows/{flow_id}/documents/find` with `FindFiles(include_web: bool)` → `ArgusFlowView`; starts one discovery run for the flow's matched companies, stores `discovery_run_id` and `doc_source` (`filings` or `web`). While the linked run is `queued`/`running` → 409 `Already looking for files`. No matched company → 400 `No matched companies`.
  - `ArgusFlowView.discovery: DiscoveryState | None` = `{run_id, status, done, total}` from the manifest.

- [ ] **Step 1: Write the failing tests**

```python
async def test_filings_only_never_searches_or_crawls(...):  # test_discovery_pipeline_unreachable.py: stub search/crawl raise if called
    result = await _discover_for_company(apple, ..., include_web=False, edgar=stub_edgar)
    assert [d.url for d in result.documents_found] == [EDGAR_URL] and result.documents_found[0].reporting_year == 2025

def test_discovered_files_from_run_rows(tmp_path):
    rows = [{"company_id": "apple", "documents_found": [edgar_entry, web_pdf_entry(tmp_path), alias_entry]}]
    files = discovered_files(rows, tmp_path)
    assert [(f.source, f.on_disk) for f in files] == [("filing", False), ("web", True)]

def test_find_links_one_run_and_refuses_a_second_while_running(flow_client, monkeypatch):  # Review Focus 3
    monkeypatch.setattr(argus_router, "execute_discovery_run", noop)
    f = flow_client.post(f"/api/argus/flows/{fid}/documents/find", json={"include_web": False}).json()
    assert f["doc_source"] == "filings" and f["discovery"]["status"] in ("queued", "running")
    assert flow_client.post(f"/api/argus/flows/{fid}/documents/find", json={"include_web": True}).status_code == 409

def test_filing_rows_pass_and_merge_with_uploads(flow_client, seeded_run): ...  # an EDGAR entry year 2025 → "✓ name, year", kept
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_argus_documents.py tests/test_discovery_pipeline_unreachable.py -v`
Expected: the new tests FAIL

- [ ] **Step 3: Implement `include_web`, the years, `discovered_files`, `/documents/find` and `discovery` on the view**

- [ ] **Step 4: Run all Argus and discovery tests, ruff, then regenerate the API contract**

Run: `cd backend && python3 -m pytest tests/test_argus_*.py tests/test_discovery*.py -v && ruff check . && python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b`
Expected: PASS; `openapi.json` and `schema.gen.ts` show `FlowFileView`, `DiscoveryState`, `FindFiles`

- [ ] **Step 5: Commit**

```bash
git add backend/arp/discovery/pipeline.py backend/arp/argus backend/arp/api/routers/argus.py backend/tests frontend/src/api/openapi.json frontend/src/api/schema.gen.ts
git commit -m "Argus step 2: official filings and filings plus company websites"
```

### Task 4: Frontend model for step 2

**Files:**
- Modify: `frontend/src/lib/argusFlow.ts`, `frontend/src/types.ts` (`FlowFile = Served<S["FlowFileView"]>`), `frontend/src/api/client.ts` (`patchArgusFlow` body widened; `uploadFlowDocument(flowId, companyId, docType, file)`, `findFlowFiles(flowId, includeWeb)`; contract lines in `frontend/src/api/contract.ts`), `frontend/src/components/StepBar.tsx` (`BUILT = 2`)
- Test: `frontend/tests/argusFlow.test.ts` (new cases only)

**Interfaces:**
- Produces (`lib/argusFlow.ts`):
  - `filesLabel(files: FlowFile[]): string` → `Continue with 7 files for 3 companies` from `state === "kept"` files (`1 file`, `1 company`)
  - `keepPassing(files: FlowFile[]): Record<string, "kept">` — every passing, non-duplicate file
  - `removeAll(files: FlowFile[]): Record<string, "removed">` — every non-duplicate file
  - `fileRawUrl(f: FlowFile): string | null` — `api.documentRawUrl(...)` from the key when `on_disk`, else null
  - `SOURCES: [value, label, enabled][]` = `upload`/`I upload them`, `import`/`From the import folder` (disabled), `filings`/`Official filings`, `web`/`Filings + company websites`

- [ ] **Step 1: Write the failing tests**

```ts
test("continue counts kept files and their companies", () => {
  const fs = [file("a", "apple", "kept"), file("b", "apple", "kept"), file("c", "msft", null), file("d", "sap", "removed")];
  assert.equal(filesLabel(fs), "Continue with 2 files for 1 company");
});
test("keep all that pass leaves failing and duplicate files alone", () => {
  assert.deepEqual(keepPassing([pass("a"), fail("b"), dup("c")]), { a: "kept" });
});
test("remove all covers everything but duplicates", () => assert.deepEqual(removeAll([pass("a"), fail("b"), dup("c")]), { a: "removed", b: "removed" }));
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL (`filesLabel` is not exported)

- [ ] **Step 3: Implement the helpers, types, client calls and `BUILT = 2`**

- [ ] **Step 4: Run lint, typecheck, tests**

Run: `cd frontend && npm run lint && npx tsc -b && npm test`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/argusFlow.ts frontend/src/types.ts frontend/src/api/client.ts frontend/src/api/contract.ts frontend/src/components/StepBar.tsx frontend/tests/argusFlow.test.ts
git commit -m "Argus flow model: step 2 files, continue label, set actions"
```

### Task 5: The step 2 page

**Files:**
- Create: `frontend/src/pages/ArgusDocuments.tsx` (step 2's body; `ArgusFlow.tsx` renders it for `step === 2` and passes `flow`, `act`, `onSendUniverse`)
- Modify: `frontend/src/pages/ArgusFlow.tsx` (step 1's Continue: `patchArgusFlow(id, { step: 2 })`, then `location.hash = flowHref(id, 2)`; the slice 2 hand-over moves to step 2's Continue), `frontend/src/index.css` (step 2 layout and hover image only, existing tokens), `frontend/src/components/DocumentUpload.tsx` (export `TYPES`, no behaviour change)
- Test: `backend/tests/e2e/test_argus_step2.py`; `backend/tests/e2e/test_argus_step1.py` (the Continue case now expects `#/argus/<id>/2`; listed in the PR)

**Interfaces:**
- Consumes: Task 4's helpers and client calls; `SourcePanel`/`ActiveSource`, `FileImg`, `api.documentPageUrl(raw, 1)`.
- Markup the evaluator checks:
  - `<label>Reporting year <input type="number">` saved on blur/Enter with `patchArgusFlow(id, { reporting_year })`
  - `<fieldset><legend>Where do the documents come from?</legend>` four radios with the `SOURCES` labels; the import one `disabled` with the hint
  - `I upload them`: `Company` select (flow companies), `Type` select (`TYPES`), `<input type="file" accept=".pdf" multiple>` labelled `Upload PDFs`; files upload one by one
  - `Official filings` / `Filings + company websites`: a button `Find filings` / `Find filings and website documents`; while the run is going, `Looking for files: <done> of <total> companies` and the page re-reads the flow every 3 s until the status is final
  - `<table aria-label="Files">` columns `File`, `Company`, `Type`, `Year`, `Source`, `Check`, `Decision`; a row whose `passed` is false gets `argus-row-await`; the Decision cell shows `Kept` / `Removed` when decided and the `Keep` and `Remove` buttons (the current one `aria-pressed="true"`); duplicate rows show no buttons
  - File name: an `on_disk` PDF is a button; `mouseenter`/`focus` shows `<FileImg url={documentPageUrl(raw, 1)} alt="First page of <name>">` in a `role="tooltip"` popover, `mouseleave`/`blur` hides it; click opens `SourcePanel` beside the table with `{ title: file_name, src: raw }`. A filing is `<a href={url} target="_blank" rel="noreferrer">`
  - `Keep all that pass`, `Remove all` (PATCH `decisions`), and the continue button with `filesLabel`, disabled at 0 kept; on click `patchArgusFlow(id, { step: 3 })`, then the slice 2 hand-over to the old Extraction screen

- [ ] **Step 1: Write the failing e2e tests** (the flow seeded through the API: 3 companies; PDFs written with `make_pdf`)

```python
def test_continue_opens_step_2_with_previous_year(page, flow_with_companies):
    page.get_by_role("button", name=re.compile(r"^Continue with 3 companies")).click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/2$"))
    assert page.get_by_label("Reporting year").input_value() == str(date.today().year - 1)
    assert page.locator('[role="tablist"]').count() == 0 and page.get_by_role("navigation", name="Steps").count() == 1  # AC-9
    assert page.get_by_role("radio", name="From the import folder").is_disabled()

def test_keep_all_that_pass_and_remove_all(page, flow_with_9_files_2_failing):  # AC-19, AC-74
    page.get_by_role("button", name="Remove all").click()
    assert cells(page, "Decision") == ["Removed"] * 9 and continue_button(page).is_disabled()
    page.get_by_role("button", name="Keep all that pass").click()
    assert cells(page, "Decision").count("Kept") == 7
    assert continue_button(page).inner_text().startswith("Continue with 7 files for ")
    page.goto(flow_url(1)); assert docs_on_file_column(page) == before  # step 1 unchanged

def test_remove_one_survives_reload(page, flow_with_files): ...      # AC-18: count -1, still Removed after reload, step 1 unchanged
def test_checks_in_warning_style(page, flow): ...                    # AC-20, AC-21 via the upload input; rows have argus-row-await
def test_hover_shows_first_page_and_click_opens_side_panel(page, flow_with_pdf):  # AC-22, AC-23
    page.get_by_role("button", name="2025_10-K.pdf").hover()
    expect(page.get_by_role("img", name="First page of 2025_10-K.pdf")).to_be_visible()
    page.get_by_role("button", name="2025_10-K.pdf").click()
    expect(page.locator(".source-panel h3")).to_have_text("2025_10-K.pdf")
def test_duplicate_upload_row(page, flow): ...                       # AC-24 UI part
```

- [ ] **Step 2: Run them against the stack to verify they fail**

Run: `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`, then
`cd backend && ARP_E2E_URL=http://localhost:5173 ARP_CHROMIUM_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1) pytest -m e2e tests/e2e/test_argus_step2.py tests/e2e/test_argus_step1.py tests/e2e/test_argus_start.py -v`
Expected: the step 2 tests FAIL; start-page tests pass

- [ ] **Step 3: Implement `ArgusDocuments.tsx` and the `ArgusFlow.tsx` changes**

Layout from the mockup's step 2 (https://claude.ai/artifact/PTXrSNwBokToBVfSnfWw4P) and `DESIGN.md`; table classes as step 1 (`data-table stack-on-phone`, `mono`), the side panel as `Extraction.tsx` places it.

- [ ] **Step 4: Run the e2e tests and the frontend checks, then screenshot and audit**

Run the Step 2 pytest command (expected PASS) and `cd frontend && npm run lint && npx tsc -b && npm test` (expected PASS). Screenshot `#/argus/<id>/2` with 9 files at 1440 and 390 px, light and dark, with the hover image and the side panel open, and run `/impeccable:impeccable audit`. `e2e_stack.sh down` when done.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ArgusDocuments.tsx frontend/src/pages/ArgusFlow.tsx frontend/src/index.css frontend/src/components/DocumentUpload.tsx backend/tests/e2e/test_argus_step2.py backend/tests/e2e/test_argus_step1.py
git commit -m "Argus step 2 Documents: sources, checks, keep/remove, preview and side panel"
```

## Left for later slices

- Step 3 and the run honouring **Remove** (slice 4); until then step 2's Continue hands the list to the old Extraction screen.
- `From the import folder` (slice 9): the radio is there, disabled.
- **Replace file** for a failed document (slice 5).
- A hover image for SEC filings (they have no file in the app's folder).
