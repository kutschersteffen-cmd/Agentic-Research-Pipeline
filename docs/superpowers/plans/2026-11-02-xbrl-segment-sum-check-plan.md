# XBRL segment sum check: reconciling items, total members, corporate-only — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sum_matches_total` on segment rows count tagged corporate/elimination amounts, drop total members that double count, and drop a lone corporate/"all other" segment.

**Architecture:** All in `build_segments` (`backend/arp/xbrl_pipeline/segments.py`), inside the existing `kind == "segment"` per-concept loop. The reconciling facts are already there: both callers (`sec_segments` via `parse_ixbrl_dimensional`, `fetch_company_esef` via `dimensional_facts`) pass every dimensional fact, and only `_kept` filters them out. So `build_segments` reads them from its own `dim_facts` argument; no caller or `_kept` change. One new model field.

**Tech Stack:** Python 3, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-xbrl-segment-sum-check-design.md` (approved 2026-11-02).

## Global Constraints

- Scope: `axis_kind == "segment"` rows only. Product/geography grouping, values and `sum_matches_total` unchanged (AC-14).
- `SegmentRow.reconciling: float | None = None`. Segment rows always set a float (0 when none, AC-4); product/geography rows stay `None` so their stored rows and literals do not change (AC-14). Old `segments.jsonl` still reads.
- Reconciling fact: `f.concept == concept`, `int(f.period_end[:4]) == year`, `period_start` set and `_full_year`, `f.dims` is exactly `{"srt:ConsolidationItemsAxis": m}` with `m` in `{us-gaap,srt}:{CorporateNonSegmentMember, SegmentReconcilingItemsMember, ConsolidationEliminationsMember, IntersegmentEliminationMember}`. Elimination members add `-abs(value)`; the other two add `value`. Dedupe by member (`setdefault`, as segment facts are deduped) so a fact printed twice counts once.
- Order per (metric, concept, year): drop at most one total member → corporate-only drop → sum check on what is left.
- Total member: first member (in fact order) with at least one other member and `abs(v - others) <= 0.005 * abs(others)`, where `others` = sum of the remaining members. With `others == 0` only an exact 0 matches.
- Corporate-only: one member left and it is in `{us-gaap,srt}:{CorporateAndOtherMember, CorporateMember, CorporateNonSegmentMember}` or `ifrs-full:AllOtherSegmentsMember` → no rows for that metric; the `break` to the next metric still happens (the concept matched).
- Sum check: `bool(total) and abs(seg_sum + reconciling - total) / abs(total) <= 0.01` (total 0 or missing → false, AC-26).
- `segment_count` already counts stored rows in `store_segments`; nothing to change there.

## What the code gives us

| Need | Existing piece |
|---|---|
| Reconciling facts reach `build_segments` | `dim_facts` from `parse_ixbrl_dimensional` / `esef_json.dimensional_facts` (unfiltered) |
| Full-year test | `ingestion.xbrl._full_year` |
| Per-member dedupe, sum check | `build_segments` inner loop |
| `segment_count` after dropping | `store_segments` |
| SEC fixtures / end-to-end fetch helpers | `tests/segment_fixture.py`, `tests/test_xbrl_fetch_segments.py` |

## Review Focus

1. Reconciling lookup ignores `_kept` (the facts have no segment axis) and must not pick up `_OPERATING`-paired segment facts (`OperatingSegmentsMember` is not in the set).
2. AC-9: Z is dropped even though the total (200) includes it; that is the spec's rule, not a bug.

---

### Task 1: Reconciling amount in the segment sum check

**AC:** AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-26.

**Files:**
- Modify: `backend/arp/xbrl_pipeline/models.py` (`SegmentRow.reconciling: float | None = None`)
- Modify: `backend/arp/xbrl_pipeline/segments.py` (`build_segments`: reconciling sum per concept/year for `kind == "segment"`, new sum check, set `reconciling`)
- Modify: existing tests' whole-row segment literals only, adding `reconciling` (AC-15)
- Test: `backend/tests/test_xbrl_segment_sum_check.py` (new)

- [ ] Step 1: tests end-to-end through the SEC fetch path (inline iXBRL → `segments.jsonl`), using a Fixture K builder with variants: base (AC-1); elimination +1,009 (AC-2); `srt:IntersegmentEliminationMember` (AC-3); no reconciling facts → false, 0 (AC-4); corporate fact also carrying a segment member (AC-5); FY2024 corporate fact (AC-6); `OperatingExpenses` 100/50/−30/120 → `opex` rows (AC-16); `srt:` corporate (AC-17); plus `SegmentReconcilingItemsMember` 10, total 47,951 → −855 (AC-18); `x:CorporateNonSegmentMember` (AC-19); 3-month corporate fact (AC-20); 990/1,000 true (AC-21); 989/1,000 false (AC-22); 10+20, total 0 false (AC-26). Product/geography spec's Fixture P → rows equal that spec's AC-1/AC-2 literals with `reconciling` `None` (AC-14).
- [ ] Step 2: `cd backend && python3 -m pytest tests/test_xbrl_segment_sum_check.py` → FAIL.
- [ ] Step 3: implement per Global Constraints.
- [ ] Step 4: add `reconciling` to whole-row segment literals in the XBRL/ESEF/segment test files only where they now fail; no other edit; list each in the PR. Run `test_xbrl*.py test_esef*.py test_segment*.py` → PASS (AC-15). Commit.

### Task 2: Drop total members and lone corporate members

**AC:** AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-23, AC-24, AC-25.

**Files:**
- Modify: `backend/arp/xbrl_pipeline/segments.py` (`build_segments`: before the sum check, for `kind == "segment"`, drop one total member, then the lone corporate member)
- Test: `backend/tests/test_xbrl_segment_sum_check.py` (append)

- [ ] Step 1: tests: X/Y/`x:TotalSegmentMember` 61,000 → X, Y, both true, `segment_count` 2 (AC-7); P=Q=5,169,784 → 1 row, true (AC-8); X/Y/Z=60/40/100 with total 200 → X, Y false (AC-9), total 100 → X, Y true (AC-10); lone `us-gaap:CorporateAndOtherMember` −26,885,000 → no rows, `segment_count` 0 (AC-11); 20-F lone `ifrs-full:AllOtherSegmentsMember` 0 → no segment rows (AC-12, through `sec_segments`, which also runs the ESEF set); `CorporateMember` 10 + `x:RetailMember` 90 → both kept (AC-13); 600/400/1,005 → 2 rows (AC-23); 600/400/1,006 → 3 rows (AC-24); lone `srt:CorporateNonSegmentMember` 5 → no rows, `segment_count` 0 (AC-25).
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the new file plus all XBRL/ESEF/segment test files → PASS (AC-15 again). Commit.

## AC coverage

| AC | Task |
|---|---|
| 1–6, 14, 16–22, 26 | 1 |
| 7–13, 23–25 | 2 |
| 15 | 1 (literal edits), re-run in 2 |

One PR, `risk:normal`, `Spec: xbrl-segment-sum-check`. If `SegmentRow` is in an API response model, run `export_openapi.py` + `npm run gen:api` and commit both. `openwiki/` needs an update after merge (`reconciling` field, dropped total/corporate members).
