# Research Orchestrator (code mode) — implementation plan

Spec: `docs/superpowers/specs/2026-11-01-research-orchestrator-design.md` (approved, commit `8efd7e6`).
TDD per task: the acceptance rows named in each task are written as failing tests first.

## What the codebase gives us (and where it differs from the spec)

| Step kind | Existing entry point | Shape |
|---|---|---|
| `document_discovery` | `create_discovery_run` / `execute_discovery_run` (`discovery/pipeline.py:141`) | background run |
| `extraction` | `create_extraction_run` / `execute_extraction_run` (`extraction/pipeline.py:439`), schema must be released | background run, item review |
| `financials_extraction` | `create_financials_extraction_run` (`extraction/financials_pipeline.py:113`) | background run, item review |
| `xbrl_facts` | `create_xbrl_run` / `execute_xbrl_run` (`xbrl_pipeline/fetch.py:162`) | background run |
| `universe_build` | `/universe/*` endpoints, `load_company_universe` (`universe.py:10`) | **synchronous, no run id** |
| `decision_score` | `_apply` behind `POST /decision/score` (`api/routers/decision.py:438`) | **synchronous, no run id** |
| `index_construct` | `run_review` (`index/pipeline.py:32`) | **synchronous, keyed by index_id + date** |
| `report_render` | `POST /reporting` → storyline approve (human gate) → `render_report` | **sync + its own gate** |

Consequences, handled in the plan rather than by changing the spec:
- Synchronous kinds complete inline: the call row gets `status: done` at once and a stored `result_ref`
  (e.g. `index:<id>@<date>`) instead of a run id. Only background kinds get a `run_id`.
- "Review gate" = the run finished **and** has pending review items (`read_review_queue` minus
  `latest_decisions`). There is no run-level "reviewed" flag; the executor polls this.
- `report_render` is a review gate too: it pauses at storyline approval, resumes when it is approved.
- **AC-35 needs a decision:** the Runs list has no per-run URL; it opens reviews via a callback. Plan: link
  each `done` background step to `#/history` with the run preselected (new `#/history/<run_id>` hash param,
  ~10 lines in `RunHistory.tsx`). Sync steps link to their own page (`#/index/...`, `#/reporting/<id>`).

## Tasks

1. **Step API + adapters** — `arp/orchestration/plan_api.py`: one Pydantic input model + one adapter per
   kind, wrapping the entry points above. Output: `StepResult{kind, run_id|None, result_ref|None, companies:
   [{id, exposure, has_xbrl}]}`. Also emits the Python stubs the planner prompt sees. ~1 day.
2. **Checker** — `arp/orchestration/plan_check.py`: `ast` walk over the allowed subset; per-arg validation
   against the input models; line limit. Rows AC-1…AC-7. ~0.5 day.
3. **Interpreter** — `arp/orchestration/plan_interp.py`: tree-walking evaluator of the checked subset
   (no `exec`), with pluggable step functions; step-limit counter. ~1 day.
4. **Dry run** — placeholder step functions with unknown values and `depends_on` tracking. AC-8…AC-10. ~0.5 day.
5. **Storage** — SQLAlchemy models `research_plans` (brief, script, dry_run JSON, status, approved_by/at)
   and `research_plan_calls` (seq, kind, params, run_id, result_ref, status, started_at); registered in
   `db/models.py` like `authoritative.models`; `ensure_schema` creates them. ~0.5 day.
6. **Planner** — `draft_plan(brief)` via `complete_structured(output_model=PlanScript)`, one retry with
   checker errors. AC-11, AC-12, tested with `FakeLLMClient`. ~0.5 day.
7. **Executor** — runs the interpreter with real adapters under `run_lease(plan_id)`; review-gate polling;
   cancel (current step finishes, no next step); resume by `(seq, kind, params)` match. AC-18…AC-32. ~1.5 days.
8. **CLI + API** — `arp plan …` Typer group in `cli/`, `routers/plans.py` with the six endpoints, launched
   through `get_job_launcher().launch`. AC-13…AC-17, AC-30, AC-31. Export OpenAPI + `npm run gen:api`. ~1 day.
9. **Plans page + seed** — `TABS` entry `plans`, lazy `Plans.tsx`: brief box, read-only script, dry-run
   list, Approve/Run, live status with links; `arp plan seed-demo`; `#/history/<run_id>` preselect.
   Playwright screenshot + `/impeccable:impeccable audit`. AC-33…AC-35. ~1.5 days.
10. **Golden set** — `tests/golden/plans.jsonl` (10 briefs) + `arp plan golden`. AC-36. ~0.5 day.

Total ≈ 8.5 working days. One PR per pair (1–4, 5–7, 8, 9–10) to keep diffs reviewable; `risk:high` on the
executor PR (it starts real runs).

## Not doing
Changing any existing run type (AC-37), a generic `/runs/<id>` page, parallel steps, re-planning.
