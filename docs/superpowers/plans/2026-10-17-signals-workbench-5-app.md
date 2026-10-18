# Signals workbench 5: app screen and API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An `/api/signals` API and a `#/signals` page in the R&D Lab that list, show, compare, decide on and run Signals experiments over the shared registry.

**Architecture:** One FastAPI router, `arp/api/routers/signals.py`, thin over the existing library (`Registry`, `compare_experiments`, `run_recipe`, `load_inputs`, `load_cutoff_table`). The router never re-implements evidence or comparison logic, and it maps `ValueError` to 404/422 itself, because the app-wide handler answers 400. On the frontend there is one page component, plus pure label and message helpers in `src/lib/signals.ts` that carry every exact string the spec fixes, so vitest can pin them.

**Tech Stack:** FastAPI, pydantic v2, pytest with `fastapi.testclient.TestClient`; React and TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-17-signals-workbench-app-design.md` (owner-approved 2026-10-17). Every PR body says `Spec: signals-workbench-app`.

## Global Constraints

- Refusal message, verbatim: `<method> runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app`.
- App-runnable methods, exactly: `panel`, `price_momentum`, `narrative_attention`, `sestm`, `transform`, `composite`. Every other registered method, at any depth of the spec tree, is refused.
- Labels, verbatim:
  - `contaminated (in the model's training window)`
  - `cutoff unknown: not evidence`
  - `Requires approver`
  - `Run from the CLI or a notebook`
- Compare messages, verbatim:
  - `Insufficient data: these signals cannot be separated (<n> months, <k> comparison[s])`
  - `<A's method> <A's experiment_id> is higher (<n> months, <k> comparison[s])`
  - Use the singular `comparison` or `month` when the count is 1.
  - No result text says higher, better or winner when the verdict is `insufficient_data`.
- The experiments list is the registry's append order reversed and takes no sort parameter; an unknown query parameter is ignored.
- Roles: reads and compare need any signed-in user (`current_user`); `POST /runs` needs `require_role("analyst")`; decisions need `require_role("approver")`, with `decided_by` = `user_id`.
- The router is included with `dependencies=[Depends(current_user)]`, **not** `authorize`: `authorize` would demand `analyst` for `POST /compare`.
- Uploaded files go into a `tempfile.TemporaryDirectory()` that is gone when the request returns, whether the run was accepted or refused. No price value is written to the registry.
- The cutoff table is loaded from `get_settings().training_cutoffs_path` on every request that needs it, never cached at startup.
- No edits to existing tests under `backend/tests/` for `arp signals` or `arp.signal_lab` (AC-24). The registry stays append-only.
- `#/rdLab` keeps every screen and process it has on `main` (AC-54).
- Checks: `cd backend && ruff check . && python3 -m pytest tests/test_api_signals.py`; `cd frontend && npm run lint && npx tsc -b && npm test`.

## Review Focus

1. **Malformed uploads** (bad recipe JSON, a recipe that fails validation, a CSV that is not month-end): 422 with the library's message, never 500. Test in Task 3.
2. **A method failing inside the run** (for example a `panel` recipe without its `panel_<name>` part gives `missing panel 'p1'; available: none`): 422 with that message, and the temp directory is still removed. Test in Task 3.
3. **Old registry rows without series** in compare: 422 `... was registered before series were stored; re-run it`, not 500. Test in Task 1.
4. **A malformed cutoff table file** at decision time: 422 carrying `load_cutoff_table`'s message. Test in Task 2.
5. **Comparing an experiment with itself, or naming an unknown id**: 422 with the library's message, shown on the Compare part. Test in Task 1.

---

### Task 1: Read API (list, detail, methods, compare)

**Files:**
- Create: `backend/arp/api/routers/signals.py`
- Modify: `backend/arp/api/main.py` (import `signals` in the `from arp.api.routers import (...)` list and include the router)
- Modify: `backend/arp/signal_lab/methods/base.py` (add `method_names()`)
- Test: `backend/tests/test_api_signals.py`

**Interfaces:**
- Produces, in `arp/signal_lab/methods/base.py`: `def method_names() -> list[str]`, the sorted keys of `_METHODS`. Importing `arp.signal_lab.methods` registers every method.
- Produces, in `signals.py`:
  - `router = APIRouter(prefix="/api/signals", tags=["signals"])`
  - `APP_RUNNABLE: frozenset[str]`, holding the six names above.
  - `CutoffStatus = Literal["none", "recorded", "unknown"]`
  - `def _cutoff_status(record: ExperimentRecord, cutoffs: CutoffTable) -> CutoffStatus`:
    - `none` when `record.model is None`;
    - `unknown` when `cutoffs.cutoff_for(record.model) is None`;
    - otherwise `recorded`.
  - `def _http(exc: ValueError) -> HTTPException`: 404 when `str(exc)` starts with `unknown experiment`, otherwise 422, always with `detail=str(exc)`.
  - `def _registry() -> Registry`, which is `Registry(get_run_store())`. Tests override `get_run_store`.
  - `class ExperimentSummary(BaseModel)` with these fields:
    - `experiment_id`, `category`, `method`, `universe`, `window_start`, `window_end`: `str`;
    - `cost_bps: float`;
    - `model`, `cutoff`: `str | None`;
    - `decision: Literal["none", "graduate", "shelve"]`;
    - `n_trials: int`;
    - `created_at: str`;
    - `cutoff_status: CutoffStatus`.
  - `class ExperimentDetail(ExperimentRecord)` adds `cutoff_status: CutoffStatus`. Its other fields dump exactly as the record does (AC-3).
  - `class MethodInfo(BaseModel)`: `name: str`, `runnable_in_app: bool`.
  - `class CompareRequest(BaseModel)`: `a: str`, `b: str`.
  - `def _detail(record, cutoffs) -> ExperimentDetail`, reused by Tasks 2 and 3.
  - Routes:
    - `GET /experiments -> list[ExperimentSummary]`
    - `GET /experiments/{experiment_id} -> ExperimentDetail`
    - `GET /methods -> list[MethodInfo]`
    - `POST /compare -> Comparison` (the existing model in `arp/signal_lab/compare.py`)

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_api_signals.py`. Use a `client` fixture that does the following:
  - takes `pg` and `tmp_path`;
  - sets `ARP_RUNS_DIR` and `ARP_TRAINING_CUTOFFS_PATH` (a `tmp_path` JSON file), then calls `get_settings.cache_clear()`;
  - yields `TestClient(app)`.

  Add an `as_role(role)` helper that sets `app.dependency_overrides[current_user]` to a `Principal(user_id=f"u_{role}", name=role, role=role)`. Register through `Registry(_run_store())` with `_recipe`, `_evidence`, `_months` and `_pair` copied from `tests/test_signal_lab_compare.py`; copy them, don't import them, so this file never edits that one. The tests:
  - `test_list_is_newest_first_and_ignores_sort`: register A (post-cutoff `ic.mean` 0.20), then B (0.01). Then:
    - `GET /api/signals/experiments` returns ids `[B, A]`;
    - `?sort=ic` returns `[B, A]`;
    - item 0 has every AC-1 key plus `cutoff_status`;
    - `n_trials` equals `evidence.n_trials`.
  - `test_detail_matches_registry_record`: for each key in AC-3, `body[key] == record.model_dump(mode="json")[key]`, and `body["decision"] == "none"`.
  - `test_detail_unknown_is_404`: status 404, `detail == "unknown experiment 'nope'"`.
  - `test_cutoff_status`: three experiments:
    - `model=None` gives `none`;
    - `model="m1"` with `m1` in the table gives `recorded`;
    - `model="m_unknown"` gives `unknown`.
  - `test_methods_marks_app_runnable`: the set of names equals `set(method_names())`, and `{n for n, r in ... if r} == APP_RUNNABLE`.
  - `test_compare_a_higher`: AC-6's series give `verdict == "a_higher"`, `months == 36`, `n_comparisons == 1`. A second POST returns the same values (AC-30).
  - `test_compare_identical_is_insufficient`: AC-7's series give `insufficient_data` with 36 months.
  - `test_compare_three_in_scope_counts_three`: add C (AC-47), giving `n_comparisons == 3`.
  - `test_compare_not_comparable_is_422`: a different `universe` gives 422, and `detail` starts with `not comparable: universe differs`.
  - `test_compare_errors_are_422` (Review Focus 3 and 5): a row registered with `series=[]` gives 422 containing `re-run it`; the same id twice gives 422 containing `itself`; `b="nope"` gives 422 containing `unknown experiment 'nope'`.
  - `test_viewer_can_read_and_compare`: under `as_role("viewer")`, list, methods and compare each return 200.
  - `test_no_token_is_401`: clear the `current_user` override, set `ARP_AUTH_MODE=local` and clear the settings cache. Each of the three endpoints returns 401 with `detail == "Missing or invalid bearer token"`.
  - `test_library_registered_llm_experiment_is_listed` (AC-39, AC-25): register a recipe with `method="grounded_llm"` through `Registry.register`; its id is in the list.

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `cd backend && python3 -m pytest tests/test_api_signals.py -q`
Expected: FAIL (404 for `/api/signals/...`, ImportError for `method_names`).

- [ ] **Step 3: Implement the router, `method_names` and the `main.py` include.**
  - `app.include_router(signals.router, dependencies=[Depends(current_user)])`, next to the replication router.
  - List: build `ExperimentSummary` from each record of `list(reversed(registry.list_experiments()))`.
  - Compare: `compare_experiments(req.a, req.b, registry)`. Every `ValueError` becomes a 422 with `detail=str(exc)`, unknown ids included; `_http`'s 404 is for the experiment named in the path only.
  - Load the cutoff table per request with `load_cutoff_table(get_settings().training_cutoffs_path)`.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `cd backend && ruff check . && python3 -m pytest tests/test_api_signals.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/arp/api/routers/signals.py backend/arp/api/main.py backend/arp/signal_lab/methods/base.py backend/tests/test_api_signals.py
git commit -m "feat(signals): read API for experiments, methods and compare"
```

### Task 2: Decisions

**Files:**
- Modify: `backend/arp/api/routers/signals.py`
- Test: `backend/tests/test_api_signals.py`

**Interfaces:**
- Consumes: `_registry`, `_http`, `_detail` and `_cutoff_status` from Task 1, and `Registry.decide(experiment_id, decision, *, approver, cutoffs)`.
- Produces:
  - `class DecisionRequest(BaseModel)`: `decision: Literal["graduate", "shelve"]`.
  - `POST /experiments/{experiment_id}/decision -> ExperimentDetail`, guarded by `principal: Principal = Depends(require_role("approver"))`.

- [ ] **Step 1: Write the failing tests**
  - `test_analyst_cannot_decide`: under `as_role("analyst")` the POST returns 403, and a following GET shows `decision == "none"` (AC-9, AC-31).
  - `test_shelve_records_approver`: under `as_role("approver")`, `shelve` returns 200 with `decision == "shelve"` and `decided_by == "u_approver"`. GET then shows the same (AC-11, AC-34).
  - `test_graduate_needs_12_months`: `ic.n=5` with `model=None` gives 422 containing `needs post-cutoff evidence with at least 12 IC months`.
  - `test_graduate_12_months_no_model`: `ic.n=12` gives 200 with `graduate` (AC-32).
  - `test_graduate_after_shelve_appends`: shelve, then graduate (both 200). GET shows `graduate`. `read_results("signal_registry")` holds exactly two rows with `type == "decision"` for X, with decisions `["shelve", "graduate"]` (AC-35, AC-48, AC-49).
  - `test_graduate_refused_when_cutoff_changed`: register with `model="m1"` and `cutoff="2020-01-31"`, with the table holding `2020-01-31`. Rewrite the table file to `2021-01-31` without restarting the client. The POST gives 422 containing `the cutoff for model 'm1' changed since the experiment was evaluated` (AC-33).
  - `test_graduate_refused_when_cutoff_unknown`: `model="m_unknown"`, absent from the table, `ic.n=12`, gives 422 containing `cutoff unknown: not evidence`, and no decision row is appended (AC-50).
  - `test_malformed_cutoff_table_is_422` (Review Focus 4): the table file holds `{not json`. Graduate gives 422 containing `malformed JSON`.

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `cd backend && python3 -m pytest tests/test_api_signals.py -q -k "decide or shelve or graduate or cutoff_table"`
Expected: FAIL (405 or 404 on the route).

- [ ] **Step 3: Implement the route.** For `graduate`, look up the record first. When `_cutoff_status` is `unknown`, raise 422 with `detail = f"cannot graduate {experiment_id}: model {record.model!r} has no recorded training cutoff (cutoff unknown: not evidence)"`. Otherwise call `registry.decide(..., approver=principal.user_id, cutoffs=cutoffs)`, map `ValueError` with `_http`, and return `_detail(...)`.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `cd backend && ruff check . && python3 -m pytest tests/test_api_signals.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** with message `feat(signals): approver decisions through the API`.

### Task 3: Runs

**Files:**
- Modify: `backend/arp/signal_lab/methods/base.py` (move `spec_nodes` and `TEXTLESS_METHODS` here)
- Modify: `backend/arp/cli/signal_lab.py` (import them in place of `_spec_nodes` and `_TEXTLESS`; no behaviour change)
- Modify: `backend/arp/api/routers/signals.py`
- Test: `backend/tests/test_api_signals.py`

**Interfaces:**
- Produces, in `methods/base.py`:
  - `def spec_nodes(spec: dict) -> Iterator[dict]`, the body of the CLI's `_spec_nodes`, moved unchanged;
  - `TEXTLESS_METHODS = frozenset({"panel", "price_momentum", "transform", "composite"})`.
- Produces, in `signals.py`: `POST /runs -> ExperimentDetail`, guarded by `Depends(require_role("analyst"))`, taking multipart `recipe: UploadFile`, `prices: UploadFile` and any number of extra file parts named `panel_<name>`. Read them from `await request.form()`, because FastAPI can't declare a variable set of part names.
- Order of checks. The first failure wins, and every failure is 422 with `detail` = the message:
  1. Parse the recipe with `Recipe.model_validate_json(bytes)`. A `ValidationError` gives `invalid recipe: <loc>: <msg>; ...`, in the same format as `load_recipe` but without a path.
  2. Call `get_method` on every `spec_nodes` node, which gives the library's `unknown method ...` message.
  3. Refuse the first node whose method is not in `APP_RUNNABLE`, with the refusal message.
  4. Write the prices and each panel into a `TemporaryDirectory`, as `prices.csv` and `panel_<name>.csv`.
  5. Texts are `[]` when the methods are a subset of `TEXTLESS_METHODS`, otherwise `TextStore(require_dsn(settings)).items()`.
  6. `load_inputs(recipe, prices_path, panels=..., texts=...)`.
  7. `run_recipe(recipe, inp, registry=..., cutoffs=..., data_version=...)`. `inp.resources` stays empty, because no app-runnable method needs one.

  Any other exception gives 500 with the plain message `Run failed: <type>`, so no stack trace leaks.

- [ ] **Step 1: Write the failing tests.** Add a `prices_csv(path, months, start)` helper. It writes a wide CSV on calendar month-ends with 30 issuers and seeded random-walk prices above 1000, distinct to 2 decimals; reuse the shape of `tests.test_signal_methods_base._prices` if it writes one. The tests:
  - `test_run_matches_cli_id`: a `price_momentum` recipe file and the CSV. `POST /api/signals/runs` gives 200, and its `experiment_id` equals the id parsed from `CliRunner().invoke(app_cli, ["signals", "run", "--recipe", r, "--prices", p])` on its `experiment_id:` line (AC-12).
  - `test_run_twice_same_id_one_row`: two POSTs give the same id. The list has exactly 1 item with that id, and its `n_trials` is unchanged after the second POST (AC-15, AC-45).
  - `test_run_refuses_llm_and_model_methods`: parametrize over `grounded_llm`, `issuer_first`, `embedding_ridge`, `topic_attention`, `finbert`, plus a `composite` of `price_momentum` and `grounded_llm`. Each gives 422 with `detail == f"{m} runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app"` (`m` = `grounded_llm` for the composite), and the list count is unchanged (AC-13, AC-27, AC-28, AC-29).
  - `test_run_window_outside_prices`: the AC-14 recipe and CSV give 422 with the exact AC-14 `detail`.
  - `test_run_needs_analyst`: under `as_role("viewer")` the POST gives 403 and the count is unchanged (AC-56).
  - `test_run_stores_no_prices`: after a run, no JSON number in the detail body, and none in any `read_results("signal_registry")` row for the id, equals any CSV price (AC-36). Walk the JSON recursively.
  - `test_upload_dir_removed`: monkeypatch `tempfile.TemporaryDirectory` in `signals.py` with a subclass that records `.name`. After one accepted and one refused (AC-14) POST, neither path exists (AC-37).
  - `test_run_narrative_attention_matches_cli`: seed the text store with `arp signals ingest-transcripts` on a CSV naming the price file's issuers. A `narrative_attention` recipe with `terms=["growth"]` gives the same id from the API and from the CLI (AC-38).
  - `test_run_app_runnable_methods`: parametrize over:
    - `panel` (`params.name="p1"`, panel CSV sent as part `panel_p1`);
    - `sestm` (text store seeded as above);
    - `transform` over `price_momentum`;
    - `composite` of two `price_momentum`.

    Each gives 200 with an `experiment_id` (AC-51). For the `panel` case, the part follows the `build-panel` CSV shape the CLI's `--panel` takes.
  - `test_run_malformed_inputs_are_422` (Review Focus 1):
    - a recipe of `{` gives 422 starting with `invalid recipe`;
    - a recipe missing `universe` gives 422 containing `universe`.
  - `test_run_method_failure_is_422` (Review Focus 2): a `panel` recipe without its panel part gives 422 with `detail == "missing panel 'p1'; available: none"`, and the temp directory is gone.

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `cd backend && python3 -m pytest tests/test_api_signals.py -q -k run`
Expected: FAIL (404 or 405 on `/api/signals/runs`).

- [ ] **Step 3: Move `spec_nodes` and `TEXTLESS_METHODS`, and implement the route.** Then run `python3 -m pytest tests/test_signal_lab_cli.py tests/test_signal_methods_base.py -q`, or whatever files `grep -l "signals\", \"run\"" tests/` lists, to show that the CLI is unchanged.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `cd backend && ruff check . && python3 -m pytest tests/test_api_signals.py tests/ -q -k "signal"`
Expected: all pass, with no edits to existing signal test files (AC-24).

- [ ] **Step 5: Commit** with message `feat(signals): run app-runnable recipes from uploads`.

### Task 4: API contract, client and label helpers

**Files:**
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`
- Modify: `frontend/src/types.ts`, `frontend/src/api/client.ts`, `frontend/src/api/contract.ts`
- Create: `frontend/src/lib/signals.ts`
- Test: `frontend/tests/signals.test.ts`

**Interfaces:**
- Consumes: the Task 1–3 response models.
- Produces, in `types.ts`:
  - `SignalExperimentSummary`, `SignalExperimentDetail`, `SignalMethod` and `SignalComparison`, typed only with the fields the page reads.
  - `SignalWindow`: `{ window: "in_window" | "post_cutoff"; periods: number; ic: { n: number; mean: number | null; t_nw: number | null; hit_rate: number | null } }`. Check the nullability against `schema.gen.ts`.
  - `CutoffStatus`: `"none" | "recorded" | "unknown"`.
- Produces, in `client.ts` (on `api`):
  - `signalExperiments()`
  - `signalExperiment(id)`
  - `signalMethods()`
  - `signalCompare(a, b)`
  - `signalDecide(id, decision)`
  - `signalRun({ recipe, prices, panels }: { recipe: File; prices: File; panels: Record<string, File> })`, which builds `FormData` with `recipe`, `prices` and `panel_<name>`.
- Produces, in `lib/signals.ts`:
  - `windowLabel(window: SignalWindow["window"], status: CutoffStatus): string | null`: `contaminated (in the model's training window)` only for `in_window` with `recorded`, otherwise null.
  - `cutoffNotice(status: CutoffStatus): string | null`: `cutoff unknown: not evidence` only for `unknown`.
  - `decisionBlocks(role: Me["role"] | null, status: CutoffStatus): { graduate: string | null; shelve: string | null }`:
    - a non-approver or a null role gives `Requires approver` for both;
    - an approver with `unknown` gives `graduate` = `cutoff unknown: not evidence` and `shelve` = null;
    - otherwise both are null.
  - `methodNote(m: SignalMethod): string | null`: `Run from the CLI or a notebook` when `!m.runnable_in_app`.
  - `compareMessage(c: SignalComparison, methodOf: (id: string) => string): string`, using the Global Constraints wording. Append `c.reason` after a space when it is set.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/signals.test.ts`, one `test` per helper, with the exact strings:
  - `compareMessage({verdict: "insufficient_data", months: 36, n_comparisons: 1, ...})` gives `Insufficient data: these signals cannot be separated (36 months, 1 comparison)`, and the result has no match for `/higher|better|winner/i`.
  - `a_higher` with `n_comparisons: 3` gives `price_momentum abc123 is higher (36 months, 3 comparisons)`.
  - `b_higher` names B.
  - `windowLabel`: four cases. `decisionBlocks`: three roles times two statuses.

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `cd frontend && npm test -- signals`
Expected: FAIL (module not found).

- [ ] **Step 3: Regenerate the contract, then implement the types, client and helpers.**
  - Run `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`.
  - Add one `Satisfies<Served<S["..."]>, ...>` line per new typed `request<T>()` in `contract.ts`: `ExperimentSummary`, `ExperimentDetail`, `MethodInfo` and `Comparison`.

- [ ] **Step 4: Run the checks to make sure they pass**

Run: `cd frontend && npm run lint && npx tsc -b && npm test`
Expected: all pass.

- [ ] **Step 5: Commit** both generated files with the rest, message `feat(signals): API contract, client calls and label helpers`.

### Task 5: The `#/signals` page and the R&D Lab entries

**Files:**
- Create: `frontend/src/pages/SignalsWorkbench.tsx`
- Modify: `frontend/src/App.tsx` (a `TABS` entry `{ id: "signals", label: "Signals workbench" }`, a lazy import, a render line, and `"signals"` in the "All screens" ids)
- Modify: `frontend/src/lib/processes.ts` (rdLab screen and process)
- Test: `frontend/tests/processes.test.ts` (add a test; edit none)

**Interfaces:**
- Consumes: everything Task 4 produces, plus `useMe()` from `src/lib/reviewer.ts`.
- Produces:
  - `export function SignalsWorkbench(): JSX.Element`.
  - In `processes.ts`, rdLab `screens` gains `["#/signals", "Signals workbench"]` after `Strategy Replication`.
  - rdLab `processes` gains `{ id: "signal", title: "Research a signal", cadence: "Per signal idea", outcome: "A signal with post-cutoff evidence, compared honestly, graduated or shelved.", steps: [...] }`. It has four steps, all with `tab: "signals"`, labelled `Run`, `Evidence`, `Compare` and `Decide` in that order, each with a one-line `does`.

- [ ] **Step 1: Write the failing test** in `processes.test.ts`, `test("R&D Lab gains the Signals workbench and keeps what it had", ...)`:
  - rdLab screens include every pair it has on `main` (list the six pairs literally) plus `["#/signals", "Signals workbench"]`;
  - the processes include `thematic`, `strategy` and `signal`;
  - `signal`'s step labels equal `["Run", "Evidence", "Compare", "Decide"]`.

- [ ] **Step 2: Run the test to make sure it fails**

Run: `cd frontend && npm test -- processes`
Expected: FAIL on the missing screen.

- [ ] **Step 3: Implement the page and the entries.** The page has four parts on one screen; use the existing tab-strip or section components the other R&D Lab pages use.
  - **Experiments:** a table whose columns are exactly method, category, universe, window (`window_start..window_end`), model, decision, trials, in API order. A row click opens Evidence.
  - **Evidence:** one row per window, showing `window`, `periods`, `ic.mean`, `ic.t_nw` and `ic.n`, with `windowLabel(...)` beside the row when it is non-null. `cutoffNotice(...)` shows above the table when it is non-null. Below are Graduate and Shelve buttons, each disabled with its `decisionBlocks(...)` text beside it when that is non-null. A decision re-fetches the detail and shows `decision` and `decided_by`. When `evidence.windows` is empty, show `No evidence windows`.
  - **Compare:** two selects over experiment ids (labelled by method and id) and a Compare button. Show the result as `compareMessage(...)`, and show a 422's `detail` on error.
  - **Run:** recipe and prices file inputs, an optional repeatable panel row (name and file), and Submit. On 200, open the returned experiment in Evidence and reload the list. On error, show `detail` and open nothing. Next to the inputs, list every method from `signalMethods()` with `methodNote(...)` beside it when that is non-null.

- [ ] **Step 4: Run the checks, then a UI check**

Run: `cd frontend && npm run lint && npx tsc -b && npm test`
Expected: all pass. Then start the stack (`bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`), register two experiments through the library, screenshot `#/signals` with Playwright at 1280 px and 400 px, and run `/impeccable:impeccable audit`. Fix what it flags within this page only, and stop the stack with `e2e_stack.sh down`.

- [ ] **Step 5: Commit** with message `feat(signals): Signals workbench page and R&D Lab process`.

---

## After the last task

- Open one PR against `main` with `Spec: signals-workbench-app`, the label `risk:medium`, and every test file change listed. CI runs the holdout acceptance job on it.
- Once CI is green, the `evaluator` skill, in a fresh session, checks the evaluator rows: AC-16 to AC-23, AC-40 to AC-44, AC-46, AC-52 to AC-55, AC-58 and AC-59.
