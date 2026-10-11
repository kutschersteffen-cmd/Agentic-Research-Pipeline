# Run Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every run is launched, resumed and marked failed on a crash through one path in `arp/orchestration/jobs.py`. The xbrl router and the theme resume endpoint stop keeping their own copies.

**Architecture:** `hold_run` (the lease every working run already takes) marks the run failed when its outermost holder's body raises. `resume_run` looks the run type up in one dict of resume functions instead of an if-chain, and that dict's keys are the resumable run types. `check_resumable` refuses a completed run only when it reached every company. The xbrl `retry` and theme `resume` endpoints keep their URLs and responses but go through `check_resumable`, `get_job_launcher()` and `resume_run`.

**Tech Stack:** Python 3, FastAPI, pytest with the `pg` fixture (`ARP_TEST_POSTGRES_DSN`).

**Spec:** candidate 2 in `docs/architecture-reviews/architecture-review-20261011-0405.html`, narrowed by grilling decisions Q1–Q7 (below). Glossary terms: Run, Run type, Resume, Lease (`GLOSSARY.md`).

Decisions: Q1 xbrl joins the shared resume path · Q2/Q7 crash → `finish_run(error=…)` in the outermost `hold_run` · Q3 one dict entry per resumable run type, lifecycle only (`to_observations`, `cosign_rule`, `_queue_kind` untouched) · Q4 a completed run is resumable unless `completed_count + failed_count + review_count >= company_count` · Q5 no "needs companies" on the entry · Q6 theme resume endpoint goes through the launcher.

## Global Constraints

- No frontend change. These keep their URL, status codes and response bodies: `POST /api/xbrl/runs`, `POST /api/xbrl/runs/{id}/retry` (`{run_id, company_count}`; 409 while executing; 400 when no companies are stored) and `POST /api/themes/runs/{id}/resume` (`{run_id, status: "resumed"}`; 400 for a run that isn't a theme run).
- The xbrl retry still marks the manifest `running` before it answers (`test_retry_marks_manifest_running_before_the_task_finishes`).
- The crash error text is `f"{type(exc).__name__}: {exc}"`, the format the xbrl router's `_on_done` used.
- `RunBusy` and cancellation (`asyncio.CancelledError`, a `BaseException`) never mark a run failed.
- `RESUMABLE` keeps its name. Its only user is `check_resumable`.

## Review Focus

1. A nested `hold_run` (the launcher holds the lease, then `resume_run` and `run_company_batch` take it again) marks the run failed **once**, from the outermost holder. Test in Task 1.
2. If `finish_run` itself raises (no manifest, database down), the original exception still propagates and the failure is logged. Test in Task 1.
3. A completed extraction run whose remaining companies were all stopped for review is still refused with "already completed". Test in Task 2.
4. A retry of a completed xbrl run that reached every company now returns 400. Before, it re-ran the run; the UI never offers this. Test in Task 3.
5. The xbrl "auto" market still resumes from its stored routing (`test_retry_of_an_auto_run_keeps_routing` stays green). Task 3.

---

### Task 1: `hold_run` marks a crashed run failed

**Files:**
- Modify: `backend/arp/orchestration/jobs.py:49-64` (`hold_run`)
- Test: `backend/tests/test_resume_run.py`

**Interfaces:**
- `hold_run(run_store, run_id)` keeps its signature. In the outermost branch only (the one that takes `run_lease`), an `Exception` from the body runs `JobManager(run_store).finish_run(run_id, error=f"{type(exc).__name__}: {exc}")`, then re-raises the original. A failure inside `finish_run` is logged with `logger.exception` and swallowed, so the original exception still wins. Import `JobManager` inside the function if a module-level import would cycle.

- [ ] **Step 1: Write the failing tests** in `tests/test_resume_run.py`:
  - `test_crash_inside_the_lease_marks_the_run_failed`: create a transition-plan run, then run `with hold_run(store, run_id): raise RuntimeError("boom")` under `pytest.raises(RuntimeError)`. The manifest's `status == "failed"` and `error == "RuntimeError: boom"`.
  - `test_nested_holders_mark_failed_once`: run `with hold_run(...): with hold_run(...): raise RuntimeError("boom")`, with `JobManager.finish_run` wrapped by a counting monkeypatch. It's called exactly once.
  - `test_busy_run_and_cancellation_are_not_failures`: (a) while `run_lease` is held, `hold_run` raises `RunBusy` and the manifest is unchanged; (b) `with hold_run(...): raise asyncio.CancelledError` leaves the status `running`.
  - `test_finish_run_failure_keeps_the_original_error`: monkeypatch `JobManager.finish_run` to raise `OSError`. The `RuntimeError("boom")` still propagates.
- [ ] **Step 2: Run** `python -m pytest tests/test_resume_run.py -k "crash or nested_holders or busy_run or finish_run_failure" -q`. Expected: FAIL (status stays `running`).
- [ ] **Step 3: Implement** it in `hold_run`.
- [ ] **Step 4: Run the same tests.** Expected: PASS. Then run `python -m pytest tests/test_resume_run.py tests/test_batch_runner.py -q`. Expected: all pass.
- [ ] **Step 5: Commit** with `fix(runs): a crash inside a run's lease marks the run failed`.

### Task 2: One resume entry per run type; completed means every company reached

**Files:**
- Modify: `backend/arp/orchestration/jobs.py:119-240` (`RESUMABLE`, `check_resumable`, `resume_run`)
- Test: `backend/tests/test_resume_run.py`

**Interfaces:**
- Produces `_RESUME: dict[str, Callable[..., Awaitable[str]]]`, keyed by run type. Each value is a module-level `async def _resume_<type>(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str`. Each body is the existing branch from `resume_run`, moved unchanged, with lazy imports staying inside the function. Discovery is an explicit `"discovery"` entry, no longer the fall-through.
- `RESUMABLE = frozenset(_RESUME)`.
- `resume_run`'s tail becomes `return await _RESUME[run_type](run_id, manifest, companies, **common, **llms)` inside the existing `hold_run` / `restart_run` block. Its signature is unchanged.
- In `check_resumable`, the completed refusal becomes: `manifest.status == JobStatus.COMPLETED and manifest.completed_count + manifest.failed_count + manifest.review_count >= manifest.company_count` raises `NotResumable("already completed")`.

- [ ] **Step 1: Write the failing tests:**
  - `test_completed_run_that_missed_companies_is_resumable`: a transition-plan run over 2 companies with `record_progress(completed_delta=1)` and then `finish_run`. `check_resumable` returns the manifest.
  - `test_completed_run_whose_rest_stopped_for_review_is_refused`: the same, plus `record_progress(review_delta=1)`. Raises "already completed".
  - Change `test_resume_refuses_completed_run` to add `record_progress(completed_delta=1)` before `finish_run`, so it still describes a run that reached every company.
- [ ] **Step 2: Run** `python -m pytest tests/test_resume_run.py -k "completed" -q`. Expected: the first new test FAILS with "already completed".
- [ ] **Step 3: Implement** `_RESUME`, `RESUMABLE` and the `check_resumable` rule.
- [ ] **Step 4: Run** `python -m pytest tests/test_resume_run.py tests/test_research_pipeline.py -q`. Expected: all pass, including every existing per-type resume test.
- [ ] **Step 5: Commit** with `refactor(runs): one resume entry per run type; completed means every company reached`.

### Task 3: xbrl runs launch and resume through the shared path

**Files:**
- Modify: `backend/arp/orchestration/jobs.py` (`_RESUME["xbrl_fetch"]`)
- Modify: `backend/arp/xbrl_pipeline/fetch.py:224-226` (drop `restart_run` in `execute_xbrl_run`, plus its import if it becomes unused)
- Modify: `backend/arp/api/routers/xbrl.py:59-75, 118-143` and the start-run endpoint that calls `_launch`
- Test: `backend/tests/test_api_xbrl.py`

**Interfaces:**
- Consumes `_RESUME` (Task 2) and the crash handling in `hold_run` (Task 1).
- `_resume_xbrl_fetch(run_id, manifest, companies, *, settings, run_store, **_) -> str` calls `execute_xbrl_run(run_id, companies, settings=settings, run_store=run_store, tags=manifest.params.get("tags"), refresh=bool(manifest.params.get("refresh")), market=manifest.params.get("market", "sec"))`. It builds no LLM clients: add `"xbrl_fetch"` next to `"discovery"` in `resume_run`'s skip-LLM condition.
- In the router:
  - Delete `_tasks`, `_on_done` and `_launch`.
  - Start: `get_job_launcher().launch(run_id, lambda: execute_xbrl_run(...same args as today...), run_store=run_store)`.
  - Retry, in order:
    1. `_manifest` → 404.
    2. No stored companies → 400 (existing message).
    3. `run_lease` probe → 409 `"This run is currently executing."`.
    4. `check_resumable` → 400 with its message.
    5. `JobManager.mark_running`.
    6. `get_job_launcher().launch(run_id, lambda: resume_run(run_id, settings=settings, run_store=run_store, registry=None, lease=False), run_store=run_store)`.
    7. Same response as today.
  - `registry` is unused for xbrl, so pass `None`. Check that `resume_run` doesn't touch it for xbrl.
- Tests: wherever `monkeypatch.setattr(xbrl_router, "execute_xbrl_run", …)` appears, also patch `arp.xbrl_pipeline.fetch.execute_xbrl_run` (the name `_resume_xbrl_fetch` imports lazily). Keep every assertion. In `test_background_failure_is_logged_marks_run_failed_and_releases_task`, replace `xbrl_router._tasks == set()` with `get_job_launcher()._tasks == set()`. The "logged" assertion now matches `jobs`' logger, so widen `caplog` to the root logger.

- [ ] **Step 1: Write the failing test** `test_retry_of_a_completed_run_that_reached_every_company_is_400` (Review Focus 4): `create_xbrl_run`, `record_progress(completed_delta=1)`, `finish_run`. The retry returns 400 and its detail contains "already completed".
- [ ] **Step 2: Run it.** Expected: FAIL (200 today).
- [ ] **Step 3: Implement** the router, `_resume_xbrl_fetch` and the `execute_xbrl_run` change, and update the test patches as described.
- [ ] **Step 4: Run** `python -m pytest tests/test_api_xbrl.py tests/test_xbrl_fetch.py tests/test_xbrl_auto.py tests/test_resume_run.py -q`. Expected: all pass.
- [ ] **Step 5: Commit** with `refactor(xbrl): runs launch and resume through the shared launcher`.

### Task 4: Theme resume endpoint uses the launcher

**Files:**
- Modify: `backend/arp/api/routers/themes.py:199-230`
- Test: the theme API tests (find them with `grep -ln "themes/runs" tests/*.py`; if none exist, add to `tests/test_research_pipeline.py`)

**Interfaces:**
- `asyncio.create_task(_background())` becomes `get_job_launcher().launch(run_id, lambda: resume_run(run_id, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store, lease=False), run_store=run_store)`. Add a `run_lease` probe before it that turns `RunBusy` into a 409, as `runs.py`'s resume endpoint does. Remove the `asyncio` import if nothing else uses it.

- [ ] **Step 1: Write the failing test** `test_theme_resume_endpoint_crash_marks_run_failed`: monkeypatch `arp.api.routers.themes.resume_run` with an async function that raises `RuntimeError("boom")`. POST the resume of a stored, resumable theme run, then drain the launcher (`client.portal.call(asyncio.sleep, 0.05)` inside `with client`). The manifest's status is `failed`.
- [ ] **Step 2: Run it.** Expected: FAIL (the status stays as before, because the bare task swallows the error).
- [ ] **Step 3: Implement** the change.
- [ ] **Step 4: Run** the theme API tests plus `tests/test_resume_run.py`. Expected: all pass. Then run `python -m ruff check .` and the full `python -m pytest -q`. Expected: no failures beyond the 40 known environment failures (reporting and stewardship deck rendering, the blob store, theme clustering).
- [ ] **Step 5: Commit** with `refactor(themes): resume launches through the shared launcher`.
