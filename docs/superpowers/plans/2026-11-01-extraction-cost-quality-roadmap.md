# Extraction Cost and Quality Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the roadmap's items A1–A3, B1–B4, C1–C3 and D2 as separate small PRs.

**Architecture:** Each task is one PR against `main`, built on a fresh branch from `main`, TDD against the spec's AC rows, with the Stop-hook checks and one fresh review before the PR.

**Tech Stack:** Python 3.13 backend (pydantic, LangGraph, pytest), GitHub Actions, the answer-check sheet artifact's database.

**Spec:** `docs/superpowers/specs/2026-11-01-extraction-cost-quality-roadmap-design.md` (approved 2026-11-01).

## Global Constraints

- One PR per task, `risk:normal`, body says `Spec: extraction-cost-quality-roadmap`.
- B1/B2 merge only after A1 has an approved set (anti-goal: no cheaper setup without a score).
- Defaults never change behaviour for schemas that do not opt in (B1 `always`, B2 only named presets).
- Never weaken a test; list every changed test in the PR.
- D1 and D3 are owner actions, not tasks.

## Review Focus

1. A card approved with an empty answer → export skips it, and the PR says so (A1).
2. A skipped verification on a field that a correction later moves → still `verification_skipped` (B1).
3. A run with a mix of preset and custom schemas → only the preset's run mode applies (B2).
4. Negative or zero prior-year amounts in the change check → `not_applicable`, no division by zero (C1).
5. A universe row listing the same document twice → fetched once (C3).

---

### Task 1 (A1): approved-set export and scorer on main
**Files:** `backend/scripts/answer_check_score.py` (copied from `table-aware-extraction@3d263b6`), new `backend/scripts/answer_check_export.py`, `backend/tests/test_answer_check_score.py` (copied), new `backend/tests/test_answer_check_export.py`.
- [ ] Tests AC-A1, A1c, A1d, A2c, A2f, plus Review Focus 1.
- [ ] `answer_check_export.py --cards <cards dir or JSON> --truth <truth JSON> --out approved.json`: reads the sheet's `cards` and `truth` collections (exported with the ArtifactData tool), keeps `status == "checked"`.
- [ ] PR. Then export once the owner has approved cards (AC-A1b) and commit `approved.json` in a follow-up commit.

### Task 2 (A3): not-found reasons
**Files:** `arp/extraction/field_graph.py` (trace entry), `arp/walkthrough/trace.py`, results page component in `frontend/src/pages/` (count line), tests.
- [ ] Tests AC-A3, A3b, A3d; evaluator row AC-A3c checked with the running app.
- [ ] Regenerate the API contract if the results response changes. PR.

### Task 3 (A2): answer-set CI job
**Files:** `.github/workflows/answer-set.yml` (new; `risk:high` because it touches workflows), Git LFS setup for `backend/tests/golden/answer_check/documents/`, `thresholds.json`.
- [ ] AC-A2, A2b, A2d, A2e. Needs D1's secret to run for real; without it the job warns and passes like the golden set.
- [ ] PR (owner merges, `risk:high`).

### Task 4 (B4): prices
- [ ] `cost_tracker.py` entries; tests AC-B4, B4b, B4c, B4d. PR.

### Task 5 (B1): skip rule
**Files:** `arp/schemas/datapoints.py` (`verify_policy`), `arp/config.py` (`verify_skip_min_confidence`), `arp/extraction/field_graph.py` (`_verify`), `arp/schemas/review.py` (`VERIFICATION_SKIPPED`), routing, trace.
- [ ] Tests AC-B1…B1i, Review Focus 2. API contract if `FieldDefinition` is in a response. PR after A1.

### Task 6 (B2): run mode per schema
**Files:** `arp/schemas/datapoints.py` (`run_mode`), `arp/extraction/steps.py` (`MODES["cheap"]`), run start path, presets.
- [ ] Tests AC-B2, B2b, B2c, B2d, B2f, B2g, B2h; golden AC-B2e after A1. PR.

### Task 7 (B3): batch above 200 companies
- [ ] Tests AC-B3…B3d. PR.

### Task 8 (C1): number cross-checks
- [ ] Tests AC-C1…C1k, Review Focus 4. Green preset field versions +1 where `check_config` changes. PR.

### Task 9 (C2): entity check for user-filed documents
- [ ] Tests AC-C2…C2e. PR.

### Task 10 (C3): several documents per company
- [ ] Tests AC-C3, C3c, Review Focus 5; golden AC-C3b after A1. PR.

### Task 11 (D2): Holdout job runner
- [ ] Inspect `.github/workflows/holdout.yml` runner and concurrency settings; fix; AC-D2 on the next spec PR. PR (`risk:high`).
