# Argus step 1 Companies, draft flows (slice 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Start new extraction` opens step 1 of a new draft flow at `#/argus/<flow_id>/1`, where the user builds the company list and sees, per company, what is already stored; the flow is saved on the server, so a reload or a teammate's link shows the same list, and the start page lists the draft.

**Architecture:** A draft flow is a JSON file `runs_dir/_flows/<flow_id>.json` (pydantic `ArgusFlow`), not a run: no worker, Run History or review code ever sees it. Its company list is `CompanyRef`s with `entity_id` set to the central `companies.id` once matched. Adding companies registers them in `companies`/`company_identifiers` (LEI, ISIN, CIK, plus the list's own id as scheme `USER`); the per-company view (identifiers, extracted before, documents on file) is computed on every read, never stored. The frontend gets one page (`ArgusFlow.tsx`) with the step bar and step 1, and the start page lists drafts next to runs.

**Tech Stack:** FastAPI + pydantic + SQLAlchemy (backend), React 19 + Vite + TypeScript, `node:test`, pytest + Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` (sections "Every step", "Step 1: Companies", "Calls made by the spec author" on drafts, slice 2). Builds on slice 1's `frontend/src/lib/argusStart.ts` and `frontend/src/pages/ArgusStart.tsx`.

## Global Constraints

- Exact copy: step bar items `1 Companies`, `2 Documents`, `3 Schema`, `4 Extract`, `5 Results`, finished ones with `✓`; `No identifier: add an ISIN, LEI or CIK`; `Resolve identities`; `Continue with <N> companies`; `Extracted before` as `<schema> v<n> · <YYYY-MM-DD> · <a> approved · <w> waiting` or `Never`; `Documents on file` as `<count> (<types, comma separated>)` or `None`; start-page status `Draft`.
- Document type words in `Documents on file` (the import-folder names of spec data rule 3): `10-K` → `annual`, `sustainability_report` → `sustainability`, `DEF-14A` → `proxy`, `earnings_transcript` → `transcript`, `investor_presentation` → `presentation`, `transition_plan` → `transition-plan`, anything else → `other`. Unique, in that order.
- A `company_id` column becomes scheme `USER` on the matched company and never creates a second company. Tickers never match (as `identifiers_of` already rules).
- Nothing runs before **Resolve identities** is clicked; the click starts exactly one identity run with the unmatched companies only.
- No `role="tablist"` on the flow page; exactly one step bar.
- Any signed-in analyst can open and change any draft (mutating endpoints use `require_role("analyst")`; reads use `current_user`).
- Old screens stay; steps 2 to 5 are not built yet: their step-bar items are not links, and **Continue with N companies** hands the list to the old Extraction screen (`sendUniverse(...)("extraction", path, count)`, as `ArgusUniverse` does), so nothing dead-ends (spec, "Until the new steps exist").
- After the response models change: `cd backend && python scripts/export_openapi.py`, `cd frontend && npm run gen:api`, commit `openapi.json` and `schema.gen.ts`.
- This slice delivers AC-8, AC-10, AC-11, AC-12, AC-13, AC-14, AC-73, and AC-9 for step 1. AC-15 to AC-17 need steps 2 and 3 (slices 3, 4); the PR lists them as waiting.

## Review Focus

1. **A list with no `company_id` column, or a name-only row** (AC-10's Acme): parsed, not a 500; the row is unmatched and shows the warning. Test in Task 2.
2. **The same list uploaded twice, or two lists that overlap:** one row per company (dedup by central id, else by list id), not duplicates. Test in Task 2.
3. **A `USER` id already on another company** (two teams both use `company_id` `1`): the company still matches by its LEI/ISIN/CIK, the `USER` id is not moved or added, nothing raises. Test in Task 2.
4. **Identifiers that point to two different companies** (LEI on one, ISIN on another): nothing is created or attached; the row is unmatched and reads `Identifiers match more than one company`. Test in Task 2.
5. **An unknown flow id in the URL** (deleted, mistyped): the page says `This extraction does not exist.` with a link to `#/argus`, not a blank page or a console error. Test in Task 5.

---

### Task 1: Draft flow store and endpoints

**Files:**
- Create: `backend/arp/argus/__init__.py` (empty), `backend/arp/argus/flows.py`
- Create: `backend/arp/api/routers/argus.py`; Modify: `backend/arp/api/main.py` (include the router like the others)
- Test: `backend/tests/test_argus_flows.py`

**Interfaces:**
- Produces (`arp/argus/flows.py`):
  - `class ArgusFlow(BaseModel)`: `flow_id: str`, `created_at: str`, `updated_at: str`, `started_by: str`, `started_by_name: str`, `step: int = 1` (1..5, the furthest step reached), `companies: list[CompanyRef] = []`, `identity_run_id: str | None = None`
  - `class FlowStore`: `__init__(self, flows_dir: Path)`; `create(self, principal: Principal) -> ArgusFlow`; `get(self, flow_id: str) -> ArgusFlow | None`; `save(self, flow: ArgusFlow) -> ArgusFlow` (sets `updated_at`, `atomic_write_text`); `list(self) -> list[ArgusFlow]` (newest first); `update(self, flow_id: str, fn: Callable[[ArgusFlow], None]) -> ArgusFlow | None` (read-modify-write under a `KeyedLock` on `flow_id`). Ids are `uuid4().hex`; `get` passes the id through `safe_id` and returns None for an unsafe or missing one.
  - Dependency `get_flow_store(settings=Depends(settings_dep)) -> FlowStore` with `flows_dir = settings.runs_dir / "_flows"`.
- Produces (router, prefix `/api/argus`):
  - `POST /flows` → `ArgusFlow` (step 1, empty list, starter from the principal)
  - `GET /flows` → `{"flows": list[ArgusFlow]}`
  - `GET /flows/{flow_id}` → `ArgusFlowView` (Task 2 adds `rows`; in this task `ArgusFlowView = ArgusFlow` plus `rows: list = []`), 404 `Extraction not found` when missing
  - `PATCH /flows/{flow_id}` with `FlowPatch(identity_run_id: str | None = None)` → `ArgusFlowView`

- [ ] **Step 1: Write the failing tests**

```python
def test_create_get_list_and_patch(client):
    f = client.post("/api/argus/flows").json()
    assert (f["step"], f["companies"], f["started_by"]) == (1, [], "dev")
    assert client.get(f"/api/argus/flows/{f['flow_id']}").json()["flow_id"] == f["flow_id"]
    assert [x["flow_id"] for x in client.get("/api/argus/flows").json()["flows"]] == [f["flow_id"]]
    p = client.patch(f"/api/argus/flows/{f['flow_id']}", json={"identity_run_id": "r9"}).json()
    assert p["identity_run_id"] == "r9"

def test_unknown_or_unsafe_flow_is_404(client):
    assert client.get("/api/argus/flows/nope").status_code == 404
    assert client.get("/api/argus/flows/..%2Fx").status_code == 404

def test_viewer_cannot_create(viewer_client):
    assert viewer_client.post("/api/argus/flows").status_code == 403
```

The `client` fixture builds a `FastAPI()` with the `argus` router and `settings_dep` overridden to a `Settings(runs_dir=tmp_path / "runs", ...)` on the `pg` DSN, as `tests/test_run_started_by.py` does; `viewer_client` overrides `current_user` with a `Principal(role="viewer")`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_argus_flows.py -v`
Expected: FAIL (`ModuleNotFoundError: arp.argus`)

- [ ] **Step 3: Implement `arp/argus/flows.py` and the router**

- [ ] **Step 4: Run the tests, then ruff**

Run: `cd backend && python3 -m pytest tests/test_argus_flows.py -v && ruff check .`
Expected: PASS, no findings

- [ ] **Step 5: Commit**

```bash
git add backend/arp/argus backend/arp/api/routers/argus.py backend/arp/api/main.py backend/tests/test_argus_flows.py
git commit -m "Argus draft flows: file store and /api/argus/flows"
```

### Task 2: Adding companies to a flow (registration with USER ids)

**Files:**
- Create: `backend/arp/argus/companies.py`
- Modify: `backend/arp/db/models.py` (`IdScheme.USER = "USER"`; the column is a CHECKed string, no migration), `backend/arp/api/routers/argus.py`
- Test: `backend/tests/test_argus_companies.py`

**Interfaces:**
- Consumes: `FlowStore.update` (Task 1); `arp.db.companies.resolve`, `lookup`, `normalise_identifier`.
- Produces (`arp/argus/companies.py`):
  - `parse_rows(path: Path) -> list[dict]` — CSV or JSON rows with empty strings as None; unlike `load_company_universe`, `company_id` may be missing.
  - `register(session: Session, row: dict) -> tuple[CompanyRef, str | None]` — the company and its problem (`None`, `"No identifier: add an ISIN, LEI or CIK"`, or `"Identifiers match more than one company"`). Rule:
    1. ids = the row's LEI, ISIN, CIK (normalised). If any: `resolve(session, ids, name=..., allow_create=True, attrs={sector, country})`. A conflict → unmatched with the second message, nothing written.
    2. No ids: `lookup` the row's `company_id` as `USER`, then as `UNIVERSE`; found → matched; else unmatched with the first message, nothing written.
    3. Matched and the row has a `company_id` not active as `USER` anywhere: add `CompanyIdentifier(scheme="USER", value=normalised)` on the match. Active on another company: leave it.
    4. The returned `CompanyRef` has `entity_id` = the match, and `company_id` = the row's `company_id`, else `str(entity_id)`, else the name.
  - `add_companies(flow: ArgusFlow, companies: list[CompanyRef]) -> None` — appends, skipping a company whose `entity_id` (or, unmatched, `company_id`) is already in the list.
  - Unmatched rows are kept in the flow (they are what **Resolve identities** works on); their problem is recomputed on read (Task 3), so it is not stored.
- Produces (router):
  - `POST /flows/{flow_id}/companies/upload` (multipart `file`, `.csv` or `.json`, at most `MAX_COMPANIES` from `universe_workbench`) → `ArgusFlowView`
  - `POST /flows/{flow_id}/companies` with `AddCompanies(universe_path: str | None = None, company: CompanyInput | None = None)` → `ArgusFlowView`; `CompanyInput` = `name: str`, `ticker`, `isin`, `lei`, `cik: str | None`. `universe_path` is checked to lie under `runs_dir/_universes` as `universe_workbench.workbench` does (400 otherwise).

- [ ] **Step 1: Write the failing tests** (`pg` fixture; API through the Task 1 `client`)

```python
CSV = ("name,lei,isin,cik,sector,country,company_id\n"
       "Apple,HWUPKR0MPOU8FGXBT394,US0378331005,0000320193,Information Technology,US,AAPL-X\n"
       "Microsoft,,US5949181045,,Information Technology,US,\n"
       "SAP,529900D6BF99LW9R2E68,,,Information Technology,DE,\n"
       "Acme,,,,,,\n")

def test_upload_registers_matched_rows_and_keeps_acme_unmatched(client, pg):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    flow = client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", CSV)}).json()
    assert [c["name"] for c in flow["companies"]] == ["Apple", "Microsoft", "SAP", "Acme"]
    assert [c["entity_id"] is not None for c in flow["companies"]] == [True, True, True, False]
    assert count(pg, "companies") == 3

def test_user_id_attaches_to_the_existing_company(client, pg):
    # Apple already registered with its LEI (AC-11)
    seed_company(pg, "Apple", lei="HWUPKR0MPOU8FGXBT394")
    before = count(pg, "companies")
    upload(client, "name,lei,company_id\nApple,HWUPKR0MPOU8FGXBT394,AAPL-X\n")
    assert count(pg, "companies") == before
    assert identifiers(pg, apple_id) >= {("USER", "AAPL-X"), ("LEI", "HWUPKR0MPOU8FGXBT394")}

def test_same_list_twice_gives_one_row_each(client): ...            # Review Focus 2
def test_user_id_owned_by_another_company_is_left_alone(client, pg): ...  # Review Focus 3: matches by ISIN, USER stays on the first owner
def test_conflicting_identifiers_create_nothing(client, pg): ...    # Review Focus 4: message, count unchanged
def test_add_one_company_and_saved_universe(client): ...            # `company` body; `universe_path` outside _universes is 400
```

`count`, `seed_company`, `identifiers` are small helpers in the test file over `Session(create_engine(pg))`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_argus_companies.py -v`
Expected: FAIL (404 on `/companies/upload`)

- [ ] **Step 3: Implement `arp/argus/companies.py`, `IdScheme.USER` and the two endpoints** (one session per request, committed once after all rows)

- [ ] **Step 4: Run the tests, then ruff**

Run: `cd backend && python3 -m pytest tests/test_argus_companies.py tests/test_argus_flows.py -v && ruff check .`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/arp/argus/companies.py backend/arp/db/models.py backend/arp/api/routers/argus.py backend/tests/test_argus_companies.py
git commit -m "Argus step 1: add companies to a flow, user ids as USER identifiers"
```

### Task 3: What each company already has (the step 1 rows)

**Files:**
- Create: `backend/arp/argus/rows.py`
- Modify: `backend/arp/api/routers/argus.py` (`ArgusFlowView.rows` filled on every flow response)
- Test: `backend/tests/test_argus_rows.py`

**Interfaces:**
- Consumes: `availability()` from `arp/universe_workbench/availability.py` (its `extraction.last_run_id` and `documents`), `list_open_items(run_store, principal, run_id=...)`, `latest_decisions(run_store, run_id)`, `field_item_key`/`period_key` (as `review_items` in `extraction/pipeline.py` uses them), `MasterIndex.build(idmap)` + `map_company`.
- Produces:
  - `class PriorRun(BaseModel)`: `label: str` (as the start page labels runs: `<schema_name> v<n>`, `Financials`, `TNFD`, `Transition Plan`), `date: str` (`created_at[:10]`), `approved: int`, `waiting: int`
  - `class FlowRow(BaseModel)`: `company_id: str`, `central_id: UUID | None`, `name: str`, `identifiers: dict[str, list[str]]` (active `company_identifiers` of the central id, schemes `LEI`, `ISIN`, `CIK`, `USER`, `TICKER`; plus the list's own values when unmatched), `master_identifiers: dict[str, list[str]]` (from the security master, spec "Left out"), `sector: str | None`, `country: str | None` (the `companies` row, else the list), `problem: str | None`, `extracted_before: PriorRun | None`, `documents: int`, `document_types: list[str]` (Global Constraints mapping)
  - `flow_rows(flow: ArgusFlow, *, session, run_store, content_store, xbrl_store, idmap, principal, documents_dir) -> list[FlowRow]`
  - For the company's newest Argus-type run: `approved` = its fields in that run routed `auto_accept` with no decision, plus fields whose latest decision is `approve` or `edit`; `waiting` = its open items in that run (`payload.company_id` equal).
  - `problem` for an unmatched row is recomputed by `register`'s rule without writing (a `dry_run` flag on `register`, or a read-only `problem_of(session, company)` sharing its lookup).

- [ ] **Step 1: Write the failing tests**

```python
def test_prior_run_and_documents(rows_for):
    # an extraction run of S v2 on 2026-10-01: 4 fields for c1, 2 auto_accept, 1 review decided approve, 1 review open;
    # 2 registered documents for c1: 10-K and sustainability_report
    [row] = rows_for(company_id="c1")
    assert row.extracted_before == PriorRun(label="S v2", date="2026-10-01", approved=3, waiting=1)
    assert (row.documents, row.document_types) == (2, ["annual", "sustainability"])

def test_never_and_none(rows_for):
    [row] = rows_for(company_id="fresh")
    assert (row.extracted_before, row.documents, row.document_types) == (None, 0, [])

def test_identifiers_sector_country_and_problem(rows_for_flow): ...  # Apple: LEI/ISIN/CIK/USER, IT, US; Acme: problem message
```

Seed the run with `JobManager(run_store).create_run("extraction", {"schema_name": "S", "schema_version": "s:v2"}, 1)`, then `run_store.append_result`, `append_review_item`, `append_decision_row` with the shapes `tests/test_review_items.py` uses (`grep -l append_decision_row backend/tests`).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_argus_rows.py -v`
Expected: FAIL (`ModuleNotFoundError: arp.argus.rows`)

- [ ] **Step 3: Implement `rows.py` and wire `rows` into every flow response**

- [ ] **Step 4: Run all Argus tests, ruff, then regenerate the API contract**

Run: `cd backend && python3 -m pytest tests/test_argus_*.py -v && ruff check . && python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b`
Expected: PASS; `openapi.json` and `schema.gen.ts` show the `ArgusFlow*` and `FlowRow` schemas

- [ ] **Step 5: Commit**

```bash
git add backend/arp/argus/rows.py backend/arp/api/routers/argus.py backend/tests/test_argus_rows.py frontend/src/api/openapi.json frontend/src/api/schema.gen.ts
git commit -m "Argus step 1 rows: identifiers, extracted before, documents on file"
```

### Task 4: Frontend model: step 1 text, draft rows on the start page

**Files:**
- Create: `frontend/src/lib/argusFlow.ts`
- Modify: `frontend/src/lib/argusStart.ts` (`argusRows` takes drafts), `frontend/src/types.ts` (`ArgusFlow = Served<S["ArgusFlowView"]>`, `FlowRow = Served<S["FlowRow"]>`), `frontend/src/api/client.ts` (`createArgusFlow`, `listArgusFlows`, `getArgusFlow`, `patchArgusFlow`, `uploadFlowCompanies`, `addFlowCompanies`)
- Test: `frontend/tests/argusFlow.test.ts`, `frontend/tests/argusStart.test.ts` (new cases only; no existing case changes)

**Interfaces:**
- Produces (`lib/argusFlow.ts`):
  - `flowHref(flowId: string, step: number): string` → `#/argus/<flowId>/<step>`
  - `extractedBeforeText(p: PriorRun | null): string` → `S v2 · 2026-10-01 · 3 approved · 1 waiting` or `Never`
  - `documentsText(count: number, types: string[]): string` → `2 (annual, sustainability)` or `None`
  - `identifierList(r: FlowRow): string[]` → `["LEI HWUPKR0MPOU8FGXBT394", "ISIN …", "CIK …", "USER AAPL-X"]`, master ones not already shown appended
  - `continueLabel(n: number): string` → `Continue with 4 companies` (`1 company` singular)
- Changes `argusRows(runs, items, flows: ArgusFlow[] = [])`: each flow becomes `{ label: "New extraction", companies: flow.companies.length, step: flow.step, status: "Draft", startedBy, starterName, createdAt, openHref: flowHref(id, step) }`, sorted with the runs.

- [ ] **Step 1: Write the failing tests**

```ts
test("extracted before and documents read as the spec writes them", () => {
  assert.equal(extractedBeforeText({ label: "S v2", date: "2026-10-01", approved: 3, waiting: 1 }), "S v2 · 2026-10-01 · 3 approved · 1 waiting");
  assert.equal(extractedBeforeText(null), "Never");
  assert.equal(documentsText(2, ["annual", "sustainability"]), "2 (annual, sustainability)");
  assert.equal(documentsText(0, []), "None");
});
test("continue label", () => assert.deepEqual([continueLabel(1), continueLabel(4)], ["Continue with 1 company", "Continue with 4 companies"]));
test("a draft lists as Draft at its step, newest first, opening the flow", () => {
  const rows = argusRows([R1], [], [flow({ flow_id: "f1", step: 1, created_at: "2026-10-05", companies: [] })]);
  assert.deepEqual(rows.map((r) => [r.runId, r.status, r.step, r.openHref]), [["f1", "Draft", 1, "#/argus/f1/1"], ["r1", "Running", 4, "#/extraction/extract"]]);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL (cannot find `../src/lib/argusFlow.ts`)

- [ ] **Step 3: Implement `argusFlow.ts`, the `argusRows` change, the types and client calls**

- [ ] **Step 4: Run lint, typecheck, tests**

Run: `cd frontend && npm run lint && npx tsc -b && npm test`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/argusFlow.ts frontend/src/lib/argusStart.ts frontend/src/types.ts frontend/src/api/client.ts frontend/tests/argusFlow.test.ts frontend/tests/argusStart.test.ts
git commit -m "Argus flow model: step 1 text, drafts on the start page"
```

### Task 5: The flow page with step 1, and the start page wiring

**Files:**
- Create: `frontend/src/pages/ArgusFlow.tsx`, `frontend/src/components/StepBar.tsx`
- Modify: `frontend/src/App.tsx` (`active === "argus"`: `route.params[0]` set → `<ArgusFlow key={params[0]} flowId={params[0]} step={Number(params[1] ?? 1)} onSendUniverse={sendUniverse("Argus")} />`, else `<ArgusStart />`; check the `ProcessBar` above `<main>` draws no second step bar for this route and hide it there if it does), `frontend/src/pages/ArgusStart.tsx` (button creates a flow and opens `flowHref(id, 1)`; loads `listArgusFlows()` with the runs and passes them to `argusRows`), `frontend/src/index.css` only for the step bar, reusing tokens
- Test: `backend/tests/e2e/test_argus_step1.py`

**Interfaces:**
- Consumes: Task 4's model and client calls; `InputPicker kind="universe"` for saved universes (as `UniversePicker` does); `api.startIdentityRun({ companies })`; `api.universeFromCompanies(companies, "argus")`.
- `StepBar({ flowId, current, reached }: { flowId: string; current: number; reached: number })`: `<nav aria-label="Steps"><ol>` of 5 items `<n> <Step>`; `aria-current="step"` on `current`; items `< reached` get `✓` and are links to `flowHref`; items not built yet (2 to 5 in this slice) are plain text. Steps beyond 1 rendered by `ArgusFlow` show a one-line note and a link back to step 1 (they cannot be reached in this slice).
- Step 1 markup the evaluator checks:
  - one `<input type="file" accept=".csv,.json">` labelled `Upload a list`; the saved-universe picker; an `Add one company` form (`Name`, `Ticker`, `ISIN`, `LEI`, `CIK`, button `Add`)
  - `<table aria-label="Companies">` columns `Company` (name, then central ID in `mono`), `Identifiers`, `Sector`, `Country`, `Extracted before`, `Documents on file`; a row with `problem` gets class `await-row` and shows the problem
  - **Resolve identities** only when an unmatched row exists and `identity_run_id` is unset; on click: `startIdentityRun({ companies: unmatched })`, then `patchArgusFlow(id, { identity_run_id })`; disabled while busy; afterwards a line `Identity run started` with a link to `#/identity`
  - **Continue with N companies** (disabled at 0): `universeFromCompanies(flow.companies, "argus")`, then `onSendUniverse("extraction", path, count)` (old Documents screen until slice 3)
  - Unknown flow (404): `This extraction does not exist.` and a link `Back to Argus` to `#/argus`

- [ ] **Step 1: Write the failing e2e tests**

```python
def test_start_new_extraction_opens_empty_step_1_and_lists_a_draft(page):  # AC-8, AC-9, AC-73
    page.goto(URL + "/#/argus"); page.get_by_role("button", name="Start new extraction").click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/1$"))
    bar = page.get_by_role("navigation", name="Steps").get_by_role("listitem")
    assert [i.inner_text() for i in bar.all()] == ["1 Companies", "2 Documents", "3 Schema", "4 Extract", "5 Results"]
    assert bar.nth(0).get_attribute("aria-current") == "step"
    assert page.get_by_role("table", name="Companies").get_by_role("row").count() == 1  # header only
    assert page.locator('[role="tablist"]').count() == 0
    page.goto(URL + "/#/argus")
    row = page.get_by_role("table", name="Runs").get_by_role("row").nth(1)
    assert "Draft" in row.inner_text() and "1 Companies" in row.inner_text()

def test_upload_shows_rows_and_survives_reload(page, tmp_path):  # AC-10, AC-14
    ...  # upload the Task 2 CSV; 4 rows; Acme row has class await-row and the exact message; reload → same 4 names

def test_resolve_identities_starts_one_run_for_the_unmatched(page, api):  # AC-13 (route-stubbed POST /api/identity/runs, count calls)
    ...

def test_unknown_flow_says_so(page):  # Review Focus 5
    page.goto(URL + "/#/argus/" + "0" * 32 + "/1")
    assert page.get_by_text("This extraction does not exist.").is_visible()
    assert page.console_errors == []
```

- [ ] **Step 2: Run them against the stack to verify they fail**

Run: `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`, then
`cd backend && ARP_E2E_URL=http://localhost:5173 ARP_CHROMIUM_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1) pytest -m e2e tests/e2e/test_argus_step1.py tests/e2e/test_argus_start.py -v`
Expected: the new tests FAIL (no `Steps` navigation); `test_argus_start.py` still passes

- [ ] **Step 3: Implement `StepBar`, `ArgusFlow`, the `App.tsx` route and the `ArgusStart` changes**

Layout from the mockup's step 1 (https://claude.ai/artifact/PTXrSNwBokToBVfSnfWw4P) and `DESIGN.md`; reuse `ArgusUniverse`'s table classes (`data-table stack-on-phone`, `xbrl-sub`, `mono`).

- [ ] **Step 4: Run the e2e tests, the frontend checks, then screenshot and audit**

Run the Step 2 pytest command (expected PASS) and `cd frontend && npm run lint && npx tsc -b && npm test` (expected PASS). Screenshot `#/argus/<id>/1` with 4 companies at 1440 and 390 px, light and dark, and run `/impeccable:impeccable audit` on it. `e2e_stack.sh down` when done.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ArgusFlow.tsx frontend/src/components/StepBar.tsx frontend/src/App.tsx frontend/src/pages/ArgusStart.tsx frontend/src/index.css backend/tests/e2e/test_argus_step1.py
git commit -m "Argus step 1 Companies with step bar; Start new extraction opens a draft"
```

## Left for later slices

- Step 2 to 5 content; until slice 3, **Continue** hands the list to the old Extraction screen and the flow stays at step 1.
- Removing a company from the list (the spec has no control for it).
- Applying a finished identity run's results back onto the unmatched rows (the run is linked; the user re-adds the resolved identifiers for now).
- The start page's **Open** for runs at steps 4 and 5 (slice 5).
