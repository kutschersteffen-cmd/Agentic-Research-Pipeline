# Argus start page (slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 9-card Argus hub on `#/argus` with the start page: a live five-step process flow, the team's runs, what is waiting, and a `Start new extraction` button.

**Architecture:** Runs record who started them (`params.started_by`, set once by the shared `schedule_llm_run`). The frontend derives everything else from `/api/runs` and `/api/review/items` in one pure module (`lib/argusStart.ts`) that a thin page (`pages/ArgusStart.tsx`) renders. Steps 1 to 3 hold no runs until drafts arrive in slice 2; until each new step exists, links open the old screens.

**Tech Stack:** FastAPI + pydantic (backend), React 19 + Vite + TypeScript, `node:test` for frontend unit tests, pytest + Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` (section "Start page", slice 1). Later slices get their own plan when they start.

## Global Constraints

- Exact UI copy from the spec: `Start new extraction`, region `Process`, tiles `1 Companies`, `2 Documents`, `3 Schema`, `4 Extract`, `5 Results`, table `Runs`, region `Waiting for you`, switch `Only mine`.
- Run statuses shown: exactly one of `Draft`, `Running`, `Needs you`, `Stopped`, `Failed`, `Finished`.
- Waiting-for-you groups: `Conflicts`, `Values to review`, `Documents to check`, `Errors`; non-Argus items are never counted.
- `Only mine` is off by default and filters both Runs and Waiting for you.
- Old screens stay untouched in this slice (approach B). No removed routes yet.
- Colours: warning style uses the existing `--await` / `--await-edge` tokens (orange only when a person must act, `DESIGN.md`).
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; `cd frontend && npm run lint && npx tsc -b && npm test`.
- This slice covers AC-1, AC-2, AC-4, AC-5, AC-6, AC-7. AC-3, AC-8 and AC-73 need steps that arrive in slices 2 and 5; the PR lists them as not yet applicable.

## Review Focus

1. **Runs started before this change** have no `started_by`: the row shows `—` for the starter, and `Only mine` hides them. Test in Task 2.
2. **Old `transition_plan` runs** (read-only type) still list, labelled `Transition Plan`. Test in Task 2.
3. **A run with review items but status `running`** (items arrive while it runs) shows `Running` and step `4 Extract`, and its items still count in Waiting for you. Test in Task 2.
4. **Review items whose run is not an Argus run** (StewardIQ, themes) are never counted, even with `Only mine` off. Test in Task 2.
5. **Empty state:** no Argus runs → Runs shows `No runs yet. Start a new extraction.` and all tiles read `0`. Test in Task 2.

---

### Task 1: Runs record who started them

**Files:**
- Modify: `backend/arp/orchestration/job_manager.py` (add `set_started_by`)
- Modify: `backend/arp/api/run_scheduling.py` (`schedule_llm_run` gains `started_by`)
- Modify: `backend/arp/api/routers/extraction.py` (`POST /start` and `POST /runs`), `backend/arp/api/routers/financials.py`, `backend/arp/api/routers/tnfd.py`, and the identity and discovery start endpoints: add `principal: Principal = Depends(current_user)` and pass `started_by=principal.user_id`
- Test: `backend/tests/test_run_started_by.py`

**Interfaces:**
- Produces: `JobManager.set_started_by(run_id: str, user_id: str) -> RunManifest` (writes `params["started_by"]` under the run lock, via `_update`); `schedule_llm_run(*, create_fn, run, settings=None, run_store=None, started_by: str | None = None) -> str`, calling `set_started_by` right after `create_fn()` when `started_by` is set. `/api/runs` then returns `params.started_by` with no schema change (params is already a free dict).

- [ ] **Step 1: Write the failing tests**

```python
def test_set_started_by_writes_params(run_store):
    jm = JobManager(run_store)
    m = jm.create_run("extraction", {"schema_name": "S"}, 1)
    jm.set_started_by(m.run_id, "alice")
    assert run_store.load_manifest(m.run_id).params == {"schema_name": "S", "started_by": "alice"}

def test_extraction_start_records_the_signed_in_user(client_with_fake_llm):
    # dev auth signs in as settings.dev_user
    r = client_with_fake_llm.post("/api/extraction/runs", json=<one released schema, one company>)
    run = client_with_fake_llm.get(f"/api/runs/{r.json()['run_id']}").json()
    assert run["params"]["started_by"] == "dev"
```

Use the fixtures the existing run-endpoint tests use (`grep -l schedule_llm_run backend/tests`).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_run_started_by.py -v`
Expected: FAIL (`AttributeError: 'JobManager' object has no attribute 'set_started_by'`)

- [ ] **Step 3: Implement `set_started_by` and the `started_by` parameter, then pass it from each Argus start endpoint**

- [ ] **Step 4: Run the tests, then ruff**

Run: `cd backend && python3 -m pytest tests/test_run_started_by.py -v && ruff check .`
Expected: PASS, no ruff findings

- [ ] **Step 5: Commit**

```bash
git add backend/arp/orchestration/job_manager.py backend/arp/api/run_scheduling.py backend/arp/api/routers backend/tests/test_run_started_by.py
git commit -m "Runs record who started them (params.started_by)"
```

### Task 2: Start-page model (pure functions)

**Files:**
- Create: `frontend/src/lib/argusStart.ts`
- Test: `frontend/tests/argusStart.test.ts`

**Interfaces:**
- Consumes: run rows from `api.listRuns()` (`run_id`, `run_type`, `status`, `params`, `company_count`, `review_count`, `failed_count`, `created_at`), review items from `api.listReviewItems()` (each has `run_id`).
- Produces:
  - `type ArgusStatus = "Draft" | "Running" | "Needs you" | "Stopped" | "Failed" | "Finished"`
  - `type ArgusRow = { runId: string; label: string; companies: number; step: 1|2|3|4|5; status: ArgusStatus; startedBy: string | null; createdAt: string; openHref: string }`
  - `ARGUS_RUN_TYPES = ["extraction", "financials", "tnfd", "transition_plan"]`
  - `STEPS = ["Companies", "Documents", "Schema", "Extract", "Results"]`
  - `argusRows(runs: Run[]): ArgusRow[]` (Argus types only, newest first)
  - `filterRows(rows: ArgusRow[], f: { step: number | null; mineOf: string | null }): ArgusRow[]`
  - `waiting(rows: ArgusRow[], items: ReviewItem[]): { total: number; groups: { label: string; count: number }[] }` (groups with count 0 left out; values to review = items whose `run_id` is in `rows`; errors = rows with status `Failed`)
  - `tiles(rows: ArgusRow[], items: ReviewItem[]): { step: number; label: string; count: number; needs: string | null }[]` (five entries; `needs` for step 5 is `"<n> values need you"`, for step 4 `"<n> failed"`, else null)

Mapping the spec fixes:
- label: `extraction` → `<params.schema_name> v<n>` where `n` comes from `params.schema_version` (`"<id>:v<n>"`); `financials` → `Financials`; `tnfd` → `TNFD`; `transition_plan` → `Transition Plan`.
- step and status: `pending`/`running` → 4, `Running`; `cancelled` → 4, `Stopped`; `failed` → 4, `Failed`; `completed`/`partially_completed` → 5, `Needs you` when `review_count > 0`, else `Finished`.
- `openHref` until slice 5: step 4 → `#/extraction/extract`, step 5 → `#/review`.

- [ ] **Step 1: Write the failing tests** (node:test, like `frontend/tests/processes.test.ts`)

```ts
test("rows are Argus runs only, newest first, labelled and stepped", () => {
  const rows = argusRows([
    run({ run_id: "r1", run_type: "extraction", status: "running", created_at: "2026-10-01", params: { schema_name: "Green capex", schema_version: "s1:v2", started_by: "alice" } }),
    run({ run_id: "r2", run_type: "financials", status: "completed", review_count: 2, created_at: "2026-10-02", params: { started_by: "bob" } }),
    run({ run_id: "t", run_type: "theme", status: "completed", created_at: "2026-10-03" }),
  ]);
  assert.deepEqual(rows.map((r) => [r.runId, r.label, r.step, r.status, r.startedBy]), [
    ["r2", "Financials", 5, "Needs you", "bob"],
    ["r1", "Green capex v2", 4, "Running", "alice"],
  ]);
});
test("cancelled is Stopped, failed is Failed, finished without review is Finished; old transition_plan runs list", ...);
test("a run without started_by shows null and is hidden by Only mine", ...);
test("filterRows by step and by mine", ...);
test("waiting counts only items of Argus rows and leaves empty groups out", () => {
  const w = waiting(rows, [item("r2"), item("r2"), item("stewardiq_run")]);
  assert.deepEqual(w, { total: 2, groups: [{ label: "Values to review", count: 2 }] });
});
test("tiles: five steps, step 5 reads '2 values need you', others null; empty input gives five zeros", ...);
test("a running run with review items stays Running at step 4 and its items still count", ...);
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL (cannot find `../src/lib/argusStart.ts`)

- [ ] **Step 3: Implement `lib/argusStart.ts` with the signatures above**

- [ ] **Step 4: Run tests, lint, typecheck**

Run: `cd frontend && npm run lint && npx tsc -b && npm test`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/argusStart.ts frontend/tests/argusStart.test.ts
git commit -m "Argus start page model: rows, filters, waiting counts, tiles"
```

### Task 3: Start page on `#/argus`

**Files:**
- Create: `frontend/src/pages/ArgusStart.tsx`
- Modify: `frontend/src/App.tsx:385` (render `ArgusStart` when `active === "argus"`; other workspaces keep `WorkspaceOverview`)
- Modify: `frontend/src/index.css` only if an existing class can't express the tile grid (reuse `card`, `await-text` first)
- Test: `backend/tests/e2e/test_argus_start.py`

**Interfaces:**
- Consumes: everything Task 2 produces; `api.listRuns()`, `api.listReviewItems()`, `api.getMe()` (for `Only mine`), the same polling interval `ProcessHub` uses for run status.
- Produces: the page. Markup the evaluator checks:
  - `<button>Start new extraction</button>` linking to `#/extraction/companies` until slice 2
  - `<section aria-label="Process">` with exactly 5 `<a>` tiles; text starts `1 Companies` … `5 Results`, then the count, then `needs` when set; a tile with `needs` gets the warning style; clicking toggles the step filter (`aria-pressed`)
  - `<table aria-label="Runs">` columns Run (label, then `<startedBy or —> · <date>`), Companies (`<N> companies`), Step (`<n> <Step>`), Status, and an `Open` link to `openHref`
  - `<input type="checkbox" id="argus-only-mine">` labelled `Only mine`, unchecked on load
  - `<aside aria-label="Waiting for you">` with the total, one line per group (`Values to review: 2`), and `<a href="#/review">`
  - a link `XBRL Facts` to `#/xbrl`
  - empty Runs: `No runs yet. Start a new extraction.`

- [ ] **Step 1: Write the failing e2e test**

```python
def test_argus_start_page_shows_flow_runs_and_waiting(page):
    page.goto(URL + "/#/argus")
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("button", name="Start new extraction").is_visible()
    tiles = page.get_by_role("region", name="Process").get_by_role("link")
    assert tiles.count() == 5
    assert [t.inner_text().split("\n")[0] for t in tiles.all()] == ["1 Companies", "2 Documents", "3 Schema", "4 Extract", "5 Results"]
    assert page.get_by_role("table", name="Runs").is_visible()
    assert page.get_by_role("complementary", name="Waiting for you").is_visible()
    assert not page.get_by_label("Only mine").is_checked()
    assert page.console_errors == []
```

- [ ] **Step 2: Run it against the stack to verify it fails**

Run: `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`, then
`cd backend && ARP_E2E_URL=http://localhost:5173 ARP_CHROMIUM_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1) pytest -m e2e tests/e2e/test_argus_start.py -v`
Expected: FAIL (no button `Start new extraction`)

- [ ] **Step 3: Implement `ArgusStart.tsx` and the `App.tsx` switch**

Copy from `DESIGN.md` and the mockup's start board (https://claude.ai/artifact/PTXrSNwBokToBVfSnfWw4P). Tiles: a 5-column grid that stacks at phone width.

- [ ] **Step 4: Run the e2e test, the frontend checks, then screenshot and audit**

Run the Step 2 pytest command (expected PASS), `cd frontend && npm run lint && npx tsc -b && npm test` (expected PASS). Then a Playwright screenshot of `#/argus` at 1440 and 390 px, light and dark, and `/impeccable:impeccable audit` on it (CLAUDE.md). `e2e_stack.sh down` when done.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ArgusStart.tsx frontend/src/App.tsx backend/tests/e2e/test_argus_start.py
git commit -m "Argus start page: process flow, runs, waiting for you"
```

## Later slices

Slices 2 to 10 each get a plan like this one when they start, written from the same spec. Order and scope are in the spec's "Slices" section.
