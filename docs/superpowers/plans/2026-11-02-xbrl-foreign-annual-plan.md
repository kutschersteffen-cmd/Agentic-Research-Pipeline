# XBRL segments for 20-F and 40-F filers — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the latest 20-F or 40-F when a filer has no 10-K, read its segments with whichever taxonomy (US-GAAP or IFRS) yields more rows, and tag every SEC segment row with its `form`.

**Architecture:** One-line form filter change in `fetch_latest_annual_original` (it already returns `form`, and `_fetch_report` already stores `annual.form` in `ReportMeta`). In `sec_segments`, call `build_segments` twice (`market="sec"` and the ESEF concept/axis set), keep the longer list, pick the matching note concept, and stamp `market="sec"` and `form` on the rows. `write_segments_sec` passes `meta.form`.

**Tech Stack:** Python 3, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-xbrl-foreign-annual-design.md` (approved 2026-11-02).

## Global Constraints

- Forms: first of `10-K`, `20-F`, `40-F` (exact match, so `/A` is skipped) in EDGAR's recent list; reuse `ANNUAL_FORMS` from the same file. Return the real form.
- Taxonomy choice: compare `len(rows)` of the two `build_segments` results (all axis kinds); strict `>` for ESEF, so a tie stays US-GAAP. Both run for 10-Ks too (spec), which leaves 10-K rows unchanged unless the ESEF set finds more — Fixture S has no `ifrs-full` facts.
- Rows keep `market: "sec"`; `axis` and `concept` stay whatever the winning set matched (`ifrs-full:SegmentsAxis`, `ifrs-full:Revenue`).
- `SegmentRow.form: str | None = None` — default so stored `segments.jsonl` from before still reads and ESEF rows are untouched.
- `ReportMeta.form` already exists; no model change there.
- 10-K output: same rows plus `form="10-K"` (AC-9); existing tests edited only to add `form` (AC-11).

## What the code gives us

| Need | Existing piece |
|---|---|
| Annual forms list | `ingestion/edgar.py` `ANNUAL_FORMS` |
| Form into stored meta | `xbrl_pipeline/fetch.py` `_fetch_report` (`form=annual.form`) |
| IFRS concepts, axes, note | `segments.py` `ESEF_METRICS`, `AXES["esef"]`, `NOTE_CONCEPTS["esef"]` |
| Row building per market | `build_segments(..., market=)` |
| No report → `segment_count` 0, status `ok` | `write_segments_sec` + `store_segments` (unchanged) |
| Fixture S | `tests/segment_fixture.py` |

## Review Focus

1. `build_segments(market="esef")` sets `market="esef"` on rows; reset with `r.model_copy(update={"market": "sec", "form": form})` rather than adding a parameter.
2. Totals for the ESEF pass come from the same `facts` (`ifrs-full:Revenue` 1000 → AC-5 sum check true).

---

### Task 1: Accept 20-F and 40-F in `fetch_latest_annual_original`

**AC:** AC-1, AC-2, AC-3, AC-4, AC-10.

**Files:**
- Modify: `backend/arp/ingestion/edgar.py` (`fetch_latest_annual_original`: `f in ANNUAL_FORMS`, `form=forms[idx]`, docstring)
- Test: `backend/tests/test_xbrl_foreign_annual.py` (new)

- [ ] Step 1: tests through `fetch_company` with a fake `SecSource`/mocked submissions + stored iXBRL bytes: `6-K, 20-F, 10-Q` → meta `form` `20-F` and its accession (AC-1); `20-F/A, 20-F` → the `20-F` (AC-2); `40-F` only → `40-F` (AC-3); `10-K`, older `20-F` → `10-K` (AC-4); none of the three → no report, `segment_count` 0, status `ok` (AC-10).
- [ ] Step 2: `cd backend && python3 -m pytest tests/test_xbrl_foreign_annual.py` → FAIL.
- [ ] Step 3: implement (two-line change).
- [ ] Step 4: run → PASS. Commit.

### Task 2: IFRS-or-US-GAAP segments and `form` on rows

**AC:** AC-5, AC-6, AC-7, AC-8, AC-9, AC-11, AC-12, AC-13.

**Files:**
- Modify: `backend/arp/xbrl_pipeline/models.py` (`SegmentRow.form: str | None = None`)
- Modify: `backend/arp/xbrl_pipeline/segments.py` (`sec_segments(xhtml, *, company_id, accession, form=None)`; `write_segments_sec` passes `meta.form`)
- Modify: existing tests' expected SEC row literals only, adding `form` (AC-11)
- Test: `backend/tests/test_xbrl_foreign_annual.py` (append)

**Interfaces:**
- `sec_segments(...)` returns `(rows, note)` as today; inside: `us = build_segments(..., market="sec")`, `ifrs = build_segments(..., market="esef")`, `win, rows = ("esef", ifrs) if len(ifrs) > len(us) else ("sec", us)`, note from `texts.get(NOTE_CONCEPTS[win])`, rows copied with `market="sec"`, `form=form`.
- Grep `sec_segments` callers and pass `form` where a meta is at hand.

- [ ] Step 1: tests end-to-end (fetch → `segments.jsonl`, `segment_note.txt`) with small inline 20-F fixtures: IFRS 600/400 on `ifrs-full:SegmentsAxis` + total 1000 → 2 rows, `market` `sec`, `form` `20-F`, both `sum_matches_total` (AC-5); plus geography 700/300 → 2 `geography` rows, segment rows unchanged (AC-6); IFRS note `Segment A sells ore.` (AC-7); US-GAAP-tagged 20-F → 2 rows, `form` `20-F`, `us-gaap:` concept (AC-8); its note `Two segments.` (AC-12); plus 1 IFRS segment fact → still the 2 `us-gaap:` rows (AC-13); Fixture S 10-K → segment spec AC-1's 3 rows with `form` `10-K` (AC-9).
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement per Interfaces.
- [ ] Step 4: add `form` to whole-row SEC literals in `test_xbrl_segments.py`, `test_xbrl_fetch_segments.py`, `test_xbrl_product_geography.py` only where they now fail; no other edit; list each in the PR. Run all XBRL/ESEF/segment test files → PASS (AC-11). Commit.

## AC coverage

| AC | Task |
|---|---|
| 1–4, 10 | 1 |
| 5–9, 12, 13 | 2 |
| 11 | 2 (existing literals only) |

One PR, `risk:normal`, `Spec: xbrl-foreign-annual`. No OpenAPI change unless `SegmentRow` is an API response model — check `export_openapi.py` output and regenerate if it changes. `openwiki/` needs an update after merge (20-F/40-F reports, `form` on rows).

## Not doing
Required rows / `facts.jsonl` for IFRS filers, 6-K, amendments, a `form` field on ESEF rows, a new parameter on `build_segments`.
