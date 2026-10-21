# Consistency Flags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five ACT consistency flags in `GET /api/companies/{ref}/transition` and a Consistency box at
the top of the company page's Transition section.

**Architecture:** A pure `transition_alignment/flags.py` computes the flags from the already built
`TransitionOut` parts plus two indicator facts (`A_ambition_3`, `A_offsetting_13`) read by the router.
The frontend renders one box. No new extraction.

**Tech Stack:** FastAPI, Pydantic v2, pytest, React/TS, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-21-consistency-flags-design.md` (owner approved 2026-10-21),
on top of the phase 1–2 and delivery-checks specs (fixtures C, K, Q, P1, A1–A3, T0/T1, O1).

## Global Constraints

- Code computes every flag; tests make no network or model calls.
- The strings, the decision order, `fact_ids` and the omit-empty-line rule are in spec §1–§4; copy them verbatim.
- Must not change: every earlier result (AC-2 to AC-129).
- DB tests use `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test_impl` (the Stop hook uses `arp_test`).

## Rulings

| # | Ruling | Why |
|---|---|---|
| F1 | Booleans from `transition_plan_indicators` are read as the router reads phase 1's redline booleans (real `bool`; anything else = not counted). | Same mapper; precision first. |
| F2 | The capex RY for flag 1 is phase 1's `capex.reporting_year`. | It already exists in the response; no second rule. |

## Review Focus

1. An action with region `other` covers no region, so a company whose only action is `other` in a two-region footprint raises `regions_left_out`. Test in Task 1.
2. `A_ambition_3` stored as the string `"YES"` instead of a bool → read as not counted, giving `not checked`, never `raised`. Test in Task 1.
3. Several breached redlines → texts joined with `; `, in redline order. Test in Task 1.
4. A company with targets but an out-of-scope sector never reaches flags (`flags` `[]`). This is covered by AC-143 in Task 2.
5. All five flags clear → the header is `Consistency: no check raises a flag`, and the page shows no `Not checked:` line. Test in Tasks 1 and 3.

---

### Task 1: Pure flags

**Files:**
- Create: `backend/arp/transition_alignment/flags.py`
- Modify: `backend/arp/schemas/transition_alignment.py`
- Test: `backend/tests/test_transition_alignment_flags.py`

**Interfaces:**
- Consumes: the built `CapexOut`, `targets`, `coverage`, `phaseouts`, `ActionOut` list, `regions`, and `operates: list[Fact]`; `net_zero: Fact | None`; `offsets: Fact | None`; `sector_has_redlines: bool`.
- Produces: `score_flags(...) -> tuple[list[FlagOut], str]`. `FlagOut(id, title, state: Literal["raised","clear","not checked"], text, cite, fact_ids: list[int])`. `TransitionOut.flags: list[FlagOut] = []`, `flags_header: str | None = None`.

- [ ] **Step 1: Write failing tests.** One test per spec row, using hand-built inputs that mirror C's defaults:
  - AC-130 to AC-134, AC-136, AC-151, AC-137, AC-138, AC-152, AC-139, AC-153, AC-140, AC-141, AC-142, AC-154, AC-155, AC-150
  - AC-158 to AC-162, AC-164 to AC-166 (fact-id rows use the input facts' ids)
  - Review Focus 1, 2, 3, 5
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_transition_alignment_flags.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and `tests/test_transition_alignment_delivery.py`. Expected: PASS.
- [ ] **Step 5: API contract:** run `python scripts/export_openapi.py`, `cd frontend && npm run gen:api && npx tsc -b`. Commit the generated files.
- [ ] **Step 6: Commit** `feat(alignment): consistency flags`.

### Task 2: Endpoint wiring and fixtures

**Files:**
- Modify: `backend/arp/api/routers/transition_alignment.py`, `backend/tests/transition_alignment_helpers.py` (C's `A_ambition_3` Yes on P1 p.25 and `A_offsetting_13` No on P1 p.26; K's `A_ambition_3` only on request)
- Test: `backend/tests/db/test_transition_alignment_api.py`

**Interfaces:**
- Consumes: Task 1 `score_flags`; the counted `A_ambition_3` and `A_offsetting_13` facts (F1); the benchmarks sector redlines.
- Produces: `flags` and `flags_header` for in-scope companies. Out of scope, they stay `[]` and null.

- [ ] **Step 1: Write failing API tests:**
  - `test_ac130_api`
  - `test_ac133_api`
  - `test_ac143_q`
  - `test_ac144_no_model_call`
  - `test_ac145_trail`
  - `test_ac158_api`
  - `test_ac160_k`
  - `test_ac166_api`

  All phase 1–2 and delivery-check API tests must still pass unchanged.
- [ ] **Step 2: Run** the file. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and `tests/test_transition_alignment_flags.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): consistency flags in /transition`.

### Task 3: Consistency box

**Files:**
- Modify: `frontend/src/pages/company/TransitionSection.tsx`, `frontend/src/types.ts`, `backend/tests/e2e/test_transition_section.py`

**Interfaces:**
- Consumes: Task 2's response.
- Produces: a box as the first part of the section, per spec §4. Each raised flag's fact links use `FactButton` (`fact_ids`). Empty lines are omitted.

- [ ] **Step 1: Implement** the box, using existing classes. The warn colour comes from an existing token if one exists; otherwise use the nearest existing alert class.
- [ ] **Step 2: Extend the e2e:**
  - Assert AC-146 (first part), AC-156, AC-147 and AC-148.
  - Add a variant without `A_ambition_3` for AC-157.
  - Add a variant with offsets clear for AC-163.
  - Save the screenshot to the scratchpad and delete `backend/test-results/`.
- [ ] **Step 3: Run** `cd frontend && npm run lint && npx tsc -b && npm test`, then the browser flow. Expected: PASS.
- [ ] **Step 4:** Run `/impeccable:impeccable audit` on the screenshot and fix any findings inside the box.
- [ ] **Step 5: Commit** `feat(alignment): Consistency box`.

### Task 4: Full checks and PR

- [ ] Run `ruff`, the full backend suite on `arp_test_impl`, and the frontend checks. Run the final whole-branch review.
- [ ] Open the PR against `main`:
  - Title: `Transition plan alignment: consistency flags`
  - Body line: `Spec: consistency-flags-design`
  - Label: `risk:normal` (no shared extraction or review code is touched)
  - Body contents: per-row coverage, the test changes, rulings F1–F2, and evaluator rows AC-146 to AC-149, AC-156, AC-157 and AC-163.
