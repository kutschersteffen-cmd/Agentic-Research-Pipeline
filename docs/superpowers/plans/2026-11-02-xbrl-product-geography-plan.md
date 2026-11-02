# XBRL revenue by product and geography (SEC + ESEF) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the revenue facts on the product/service and geography axes that `build_segments` drops today, as extra rows in the same `segments.jsonl`, and show them via `arp xbrl segments --axis`.

**Architecture:** `build_segments` already filters facts by one axis. Make it run once per axis kind (`segment`, `product`, `geography`), revenue only for the new two, and tag each row with `axis_kind` and `level`. Both fetchers already call `build_segments` + `store_segments`, so no fetch code changes; `store_segments` splits the counts for `meta.json`. The CLI filters stored rows by `axis_kind`.

**Tech Stack:** Python 3, Pydantic, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-xbrl-product-geography-design.md` (approved 2026-11-01).

## Global Constraints

- Axes: SEC `srt:ProductOrServiceAxis` (product), `srt:StatementGeographicalAxis` (geography); ESEF `ifrs-full:ProductsAndServicesAxis`, `ifrs-full:GeographicalAreasAxis`. Neither ESEF name appears in the repo yet: confirm each against the ifrs-full snapshot (`XbrlStore.taxonomy_dir`) before use; a name not found is left out of `AXES` and noted in the PR.
- Kept fact = existing `_kept(f, axis)` unchanged: full-year, the axis alone or plus `_OPERATING`. Segment × product facts fail `_kept` for both axes (AC-10) with no new code.
- Product/geography: `revenue` metric only (first concept in the revenue list with facts on that axis wins, as today).
- `level`: product rows `standard` when the member prefix is `us-gaap`, `srt` or `ifrs-full`, else `company`; segment/geography rows `None`.
- Sum check per (`axis_kind`, `level`, year), same 1 % rule and same `totals`.
- Names: existing `segment_name` already yields `US` from `country:US` (no `Member` suffix, no lower→upper boundary) and `Rest Of World` from `x:RestOfWorldMember`; no code change, test only.
- Segment rows: values, fields and `segment_count` unchanged (AC-3, AC-9, AC-18); default CLI output unchanged (AC-16).

## What the code gives us

| Need | Existing piece |
|---|---|
| Axis filter, full-year, `_OPERATING` pair | `segments.py` `_kept` |
| Per-concept first-wins, dedupe, sum check, row build | `segments.py` `build_segments` inner loop |
| SEC + ESEF wiring | `sec_segments` → `write_segments_sec`; `fetch_esef.py` ~139 — both call `build_segments` and `store_segments` |
| meta counts | `store_segments` → `store.update_meta` |
| CLI rows / key lookup | `cli/xbrl.py` `segments`, `_key_for` |
| Fixture S | `tests/segment_fixture.py` |

## Review Focus

1. Year: computed once per filing from all kept facts of all axes, or per axis? Use one year for the filing (max over segment-axis facts when present, else over all kept) so product and segment rows never disagree; test pins Fixture P → all rows FY2025.
2. Company-level sum check must use only `company` members; Apple-style data (standard true, company false) is pinned by AC-5/AC-6.
3. `axis_kind`/`level` added with defaults (`"segment"`, `None`) so stored `segments.jsonl` from before this change still reads.

---

### Task 1: Product and geography rows in `build_segments`

**AC:** AC-1…AC-13, AC-18, AC-19.

**Files:**
- Modify: `backend/arp/xbrl_pipeline/models.py` (`SegmentRow`: `axis_kind: Literal["segment","product","geography"] = "segment"`, `level: Literal["standard","company"] | None = None`)
- Modify: `backend/arp/xbrl_pipeline/segments.py` (`AXES` → per market `{kind: axis}`; `build_segments` loops over kinds; `store_segments` counts by kind)
- Modify: `backend/tests/segment_fixture.py` (add Fixture P facts) and existing segment tests' expected row literals only (AC-18)
- Test: `backend/tests/test_xbrl_product_geography.py` (new)

**Interfaces:**
- `AXES: dict[Market, dict[str, str]]`, e.g. `AXES["sec"] == {"segment": "us-gaap:StatementBusinessSegmentsAxis", "product": "srt:ProductOrServiceAxis", "geography": "srt:StatementGeographicalAxis"}`. Grep `AXES` callers and update them (fetch_esef imports `NOTE_CONCEPTS` only).
- `build_segments` signature unchanged; returns segment rows first, then product, then geography.
- `store_segments` → `update_meta(segment_count=<segment rows>, product_count=, geography_count=, segment_note_chars=)`.

- [ ] Step 1: tests, end-to-end through `sec_segments` + `store_segments` on Fixture P (iXBRL bytes), and `build_segments` with ESEF `DimFact`s:
  4 product rows 600/300/900/100 (AC-1); 3 geography rows 400/350/250 (AC-2); segment rows equal the segment spec's AC-1 rows plus `axis_kind="segment"`, `level=None` (AC-3); levels company/standard (AC-4); standard sum true (AC-5), company false (AC-6); geography true and `level None` (AC-7); names `US`, `Rest Of World` (AC-8); meta 4/3/3 (AC-9); segment × product fact → counts unchanged (AC-10); product + `_OPERATING` `x:ToolsMember`=50 kept (AC-11); `CostOfRevenue` product fact → only `metric == "revenue"` product rows (AC-12); ESEF 2+2 `ifrs-full:Revenue` facts → 2 product, 2 geography, `market` `esef`, `ifrs-full:` members `standard` (AC-13); plus 1 fact on another axis → still 2+2 (AC-19).
- [ ] Step 2: `cd backend && python3 -m pytest tests/test_xbrl_product_geography.py` → FAIL.
- [ ] Step 3: implement. In `build_segments`, wrap the existing metric loop in `for kind, axis in AXES[market].items()`, using only the revenue entry when `kind != "segment"`. For product, group `by_member` by `level` and run the existing sum check per group. Confirm the two ESEF axis names against the taxonomy snapshot first.
- [ ] Step 4: add `axis_kind`/`level` to the expected row literals in `test_xbrl_segments.py`, `test_xbrl_fetch_segments.py`, `test_xbrl_esef_segments.py`, `test_esef_segments.py` where they compare whole rows; no other edit; list each in the PR (AC-18). Run those + new tests → PASS. Commit.

### Task 2: CLI `--axis`

**AC:** AC-14, AC-15, AC-16, AC-17.

**Files:**
- Modify: `backend/arp/cli/xbrl.py` (`segments`)
- Test: `backend/tests/test_cli_xbrl.py` — append new tests only

- [ ] Step 1: tests on Fixture P stored: `--axis product` → exit 0, header `year  segment  level  metric  value  unit  concept  sum_check`, 4 data lines (AC-14); `--axis geography` → old header, 3 lines (AC-15); no `--axis` → same output as segment spec AC-18, 3 lines (AC-16); `--axis region` → exit 2 (AC-17).
- [ ] Step 2: run → FAIL.
- [ ] Step 3: `axis: Literal["segment", "product", "geography"] = typer.Option("segment", "--axis")` (Typer rejects other values with exit 2; use an `Enum` if the installed Typer lacks `Literal`), filter `r.axis_kind == axis`, insert `r.level` after segment when `axis == "product"`.
- [ ] Step 4: run → PASS, plus the existing CLI tests unedited. Commit.

## AC coverage

| AC | Task |
|---|---|
| 1–13, 19 | 1 |
| 18 | 1 (existing literals only) |
| 14–17 | 2 |

One PR, `risk:normal`, `Spec: xbrl-product-geography`. No OpenAPI change. `openwiki/` needs an update after merge (new row kinds and meta fields).

## Not doing
Other metrics on these axes, segment × product crossings, cross-company taxonomy mapping, history, label linkbases, API/UI. No fetch-code changes (already wired through `build_segments`).
