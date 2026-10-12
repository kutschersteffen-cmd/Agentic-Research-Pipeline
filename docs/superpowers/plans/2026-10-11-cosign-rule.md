# Item State Co-Sign Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Item state (`GLOSSARY.md`) is computed with one co-sign rule per run type, looked up in one place. No caller can pass, or hard-code, a different one.

**Architecture:** `item_states(run_store, run_id)` and `effective_decisions(run_store, run_id)` in `arp/orchestration/review_queue.py` read the run's type from its manifest and apply `review.items.cosign_rule(run_type)` themselves. The `cosign_required` parameter is removed from both. `item_state(rows, *, cosigned_at, cosign_required)`, the per-item function used by `observations.apply_review` and the importer, keeps its signature.

**Tech Stack:** Python 3, pytest with the `pg` fixture.

**Spec:** candidate 5 in `docs/architecture-reviews/architecture-review-20261011-0405.html`, narrowed by grilling:
- Q1: the functions derive the rule from the run type.
- Q2: the stored `review_items.state` column and the cosign path stay unchanged. The column is written by the same `item_state`, and a cosign that races a new decision is invalidated by design.

## Global Constraints

- A run with no manifest gets `cosign_rule("")`, which is `set()`, the same as any run type not in `LEGACY_COSIGN`.
- `cosign_rule` is imported lazily inside the functions, as `observations.apply_review` already does (`arp.review.items` imports the extraction pipeline).
- `reground.COSIGN_REQUIRED` is deleted. Every production call site stops passing `cosign_required` and drops imports it no longer uses (`cosign_rule`, the local `rule` variables).
- Behaviour is unchanged for every production call site, because each one's hard-coded rule equals `cosign_rule` for the runs it reads (verified: `extraction_runs()` returns only extraction runs, `publish/candidates.run_candidates` checks the run type, identity's `set()` is `cosign_rule("identity")`).

## Review Focus

1. `GET /api/extraction/runs/{run_id}/review-decisions` on a non-extraction run now applies that run's own rule, not extraction's. The UI only calls it for extraction runs. A reasonable person would expect the run's own rule.
2. `item_states` loads the manifest once per call, not once per item.
3. `tests/test_review_state.py` and `tests/test_cosign.py` used to pass rules on a run with no manifest. Their fixtures must now save a manifest of the run type whose rule each test means.

---

### Task 1: The state functions look up the co-sign rule

**Files:**
- Modify: `backend/arp/orchestration/review_queue.py:183-201`
- Modify (call sites, drop the argument): `arp/extraction/history.py:42`, `arp/discovery/identity_pipeline.py:130`, `arp/orchestration/reground.py:27,49`, `arp/checks/effectiveness.py:33`, `arp/review/quality.py:234`, `arp/review/context.py:142-144,196`, `arp/review/items.py:49`, `arp/publish/candidates.py:66,116`, `arp/api/routers/extraction.py:435-440`, `arp/portfolio/issues.py:53`
- Test: `backend/tests/test_review_state.py`, `backend/tests/test_cosign.py`, plus the explicit-rule calls in `tests/test_reground_parser.py` and `tests/test_review_decide.py`

**Interfaces:**
- `item_states(run_store: RunStore, run_id: str) -> dict[str, ItemState]`
- `effective_decisions(run_store: RunStore, run_id: str) -> dict[str, dict]`
- Both derive `cosign_required = cosign_rule(m.run_type if (m := run_store.load_manifest(run_id)) else "")`. `effective_decisions` calls `item_states`, so the manifest is loaded once.

- [ ] **Step 1: Write the failing test** `test_cosign_rule_follows_the_run_type` in `tests/test_review_state.py`: record the same uncosigned `edit` on an `extraction` run and on a `financials` run. `item_states` gives `first_done` for the extraction item (an edit there needs a co-sign) and `final` for the financials item.
- [ ] **Step 2: Run it.** Expected: FAIL with `TypeError` (missing `cosign_required`).
- [ ] **Step 3: Implement** the functions and update every call site listed. In the tests:
  - Save `RunManifest(run_id="r1", run_type="extraction")` in the `rs` / `run_store` fixtures of `test_review_state.py` and `test_cosign.py`.
  - `test_legacy_identity_edit_is_final` records on an `identity` run instead of passing `set()`.
  - Drop `cosign_required=` from the remaining test calls.
- [ ] **Step 4: Run** `python -m pytest tests/test_review_state.py tests/test_cosign.py tests/test_reground_parser.py tests/test_review_decide.py tests/test_review_items.py tests/test_review_context.py tests/test_checks_effectiveness.py tests/test_publish_api.py tests/db -q`. Expected: all pass. Then `python -m ruff check .`, then the full suite **with nothing else using the test database**. Expected: only the 40 known environment failures.
- [ ] **Step 5: Commit** with `refactor(review): item state takes its co-sign rule from the run type`.
