# XBRL segment financials (SEC + ESEF) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write `segments.jsonl` + `segment_note.txt` per company from the dimensional XBRL facts the pipeline already downloads, and expose them via `arp xbrl segments` / `arp xbrl segment-note`.

**Architecture:** One new pure module `arp/xbrl_pipeline/segments.py` turns a flat list of "dimensional facts" (concept, axis, member, value, unit, start, end, extra-dims count) plus the non-dimensional totals into `SegmentRow`s. SEC feeds it from an opt-in extension of `parse_ixbrl`; ESEF feeds it from the xBRL-JSON facts that `flatten_xbrl_json` skips today. Both fetchers call it after their existing writes, inside a `try` that never changes the company status.

**Tech Stack:** Python 3, lxml, Pydantic, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-xbrl-segment-revenue-design.md` (approved 2026-11-01).

## Global Constraints

- Segment axes: SEC `us-gaap:StatementBusinessSegmentsAxis`, ESEF `ifrs-full:SegmentsAxis`. Kept fact = full-year (`_full_year`, 350–380 days), numeric, exactly one explicit dimension and it is the segment axis.
- Only the filing's own fiscal year; per metric the first concept in its list with segment facts wins.
- `sum_matches_total`: `abs(sum - total) / total <= 0.01`; no total → `false`.
- Segment name: local name, strip trailing `Member`, then `Segment`, split CamelCase.
- `meta.json` gains `segment_count` and `segment_note_chars` (0 when absent). No `segment_note.txt` when absent.
- Default `parse_ixbrl` output, non-dimensional facts, required rows, `skipped_dimensional`, and company status must not change (AC-16, AC-17, AC-20, AC-21). Existing tests are not edited.
- New concept names are checked against the stored US-GAAP / IFRS taxonomy snapshots; a name not in the schema is dropped.

## What the code gives us

| Need | Existing piece |
|---|---|
| iXBRL contexts/units/numbers/visible text | `arp/ingestion/esef.py` `_contexts`, `_units`, `_number`, `_visible_text`, `parse_ixbrl` |
| Full-year test | `arp/ingestion/xbrl.py` `_full_year` |
| SEC concept lists | `REVENUE_TAGS`, `CAPEX_TAGS`, `RND_TAGS` (bare names → prefix `us-gaap:`) |
| ESEF concept lists | `arp/xbrl_pipeline/required.py` `IFRS_REVENUE_TAGS`, `IFRS_CAPEX_TAGS` |
| Stored 10-K | `XbrlStore.report_meta(key)` + `file_path(key, "report")`, `ReportMeta.inline_xbrl` |
| xBRL-JSON period parsing | `esef_json.parse_period` |
| JSONL write | `XbrlStore._write` / `_FILES` |

Consequence: `set_meta` rewrites the whole `meta.json`, so segment fields are added by a small `XbrlStore.update_meta(key, **fields)` after `set_meta` (and after the SEC report step, which runs later).

## Review Focus

1. 10-K stored but `report` is `unchanged` on a re-fetch → segment files must still exist (they were written on the first run; the segment step reruns only when facts or report changed, never deletes).
2. iXBRL text blocks split with `ix:continuation` → follow the `continuedAt` chain and join the head and every continuation in order (segment notes in 10-Ks often span pages, so the head alone would cut the note short); test pins a two-part block yielding both parts.
3. Segment facts in thousands (`scale="3"`) → value scaled like `parse_ixbrl` does; one test with `scale="6"`.
4. Duplicate facts (same concept/member/period printed twice in the 10-K) → one row, not two; test in Task 2.
5. Total = 0 → `sum_matches_total: false`, no ZeroDivisionError; test in Task 2.

---

### Task 1: Dimensional facts and text blocks from iXBRL

**AC:** AC-17, AC-21 (and feeds AC-1…AC-12, AC-22…AC-30, AC-34…AC-36).

**Files:**
- Modify: `backend/arp/ingestion/esef.py` (`_contexts` ~154, `parse_ixbrl` ~180)
- Test: `backend/tests/test_esef_segments.py` (new)

**Interfaces:**
- Produces: `DimFact` (dataclass in `esef.py`): `concept: str, value: float, unit: str|None, period_start: str|None, period_end: str, dims: dict[str, str]` (axis QName → member QName, explicit only).
- Produces: `parse_ixbrl_dimensional(xhtml: bytes) -> tuple[list[EsefFact], list[DimFact], dict[str, str]]` — non-dimensional facts exactly as `parse_ixbrl`, dimensional numeric facts, and `ix:nonNumeric` name → visible text (block breaks kept, same rendering as `_visible_text`).

- [ ] Step 1: tests — `test_explicit_member_parsed` (dims == `{"us-gaap:StatementBusinessSegmentsAxis": "x:AlphaSegmentMember"}`, value 300); `test_member_without_dimension_skipped` (no crash, fact absent — AC-17); `test_typed_member_counts_as_extra_dim` (fact has a `typedMember` → `dims` holds it so Task 2 rejects it); `test_scale_applied` (`scale="6"`); `test_text_block` (`us-gaap:SegmentReportingDisclosureTextBlock` → `"Alpha sells widgets. Beta sells gadgets."`); `test_parse_ixbrl_unchanged` (same output as before for a doc with dimensional contexts).
- [ ] Step 2: run `cd backend && python3 -m pytest tests/test_esef_segments.py` → FAIL.
- [ ] Step 3: implement. `_contexts(root, dimensional=False)`; with `True` it returns `id -> (start, end, dims)` for contexts with segment/scenario. A `typedMember` adds key `typed:<dimension>`; an `explicitMember` without `dimension` adds `invalid:` so it is never kept. `parse_ixbrl` keeps calling the default; `parse_ixbrl_dimensional` reuses the same loop body (extract the per-element number step into a helper, no behaviour change).
- [ ] Step 4: run new tests + `tests/test_esef.py` unedited → PASS (AC-21).
- [ ] Step 5: commit.

### Task 2: Segment row builder

**AC:** AC-3…AC-12, AC-22…AC-26, AC-34…AC-38 (pure-function level; end-to-end in Tasks 3–4).

**Files:**
- Create: `backend/arp/xbrl_pipeline/segments.py`
- Modify: `backend/arp/xbrl_pipeline/models.py` (add `SegmentRow`)
- Test: `backend/tests/test_xbrl_segments.py` (new)

**Interfaces:**
- Produces: `SegmentRow(BaseModel)` with exactly the spec's row-format fields.
- Produces: `SEC_METRICS` / `ESEF_METRICS: list[tuple[str, list[str]]]` (metric → prefixed concepts, order per spec; ESEF has no `opex`, AC-38).
- Produces: `segment_name(member: str) -> str`.
- Produces: `build_segments(dim_facts: list[DimFact], totals: dict[tuple[str, int], float], *, market: str, company_id: str, accession: str|None, fiscal_year: int|None) -> list[SegmentRow]` where `totals` maps `(concept, fiscal_year)` to the non-dimensional full-year value.

- [ ] Step 1: tests with Fixture S as `DimFact`s: 3 rows; extra `srt:ConsolidationItemsAxis` dropped (AC-3); `srt:ProductOrServiceAxis` dropped (AC-4); 3-month dropped (AC-5); FY2024 dropped (AC-6); `us-gaap:Revenues` loses to the first concept (AC-7); sum 995/975/1020/no total → true/false/false/false (AC-8…AC-11); names Alpha/Beta/Gamma and `Cloud Services` (AC-12, AC-34); capex 50/70, rnd 20/30, opex 100/120, cost_of_revenue 150, sga 60 (AC-22…AC-26); `CostsAndExpenses` loses to `OperatingExpenses` (AC-35); opex total 300 → opex false, revenue true (AC-36); ESEF additions concept used when no `IFRS_CAPEX_TAGS` facts (AC-37); no ESEF opex (AC-38); duplicate fact → one row; total 0 → false.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement. Fiscal year = passed `fiscal_year`, else the max `period_end[:4]` among kept full-year segment facts. Concepts are from the spec Decisions table; before committing, check each new name against the stored taxonomy snapshots (`XbrlStore.taxonomy_dir`) and drop any not found, noting it in the PR.
- [ ] Step 4: run → PASS. Commit.

### Task 3: SEC fetch writes segments and the note

**AC:** AC-1, AC-2, AC-14, AC-15, AC-16, AC-17, AC-27, AC-29, AC-30, AC-20.

**Files:**
- Modify: `backend/arp/xbrl_pipeline/fetch.py` (`fetch_company` ~115)
- Modify: `backend/arp/xbrl_pipeline/store.py` (`_FILES["segments"] = "segments.jsonl"`, `write_segments`, `read_segments`, `write_segment_note(key, text|None)` that deletes the file on `None`, `read_segment_note`, `update_meta`)
- Test: `backend/tests/test_xbrl_fetch_segments.py` (new; fake `SecSource` as in `tests/test_xbrl_fetch.py`)

**Interfaces:**
- Consumes: Task 1 `parse_ixbrl_dimensional`, Task 2 `build_segments`, `SEC_METRICS`.
- Produces: `write_segments_sec(key: str, store: XbrlStore, company_id: str) -> None` in `segments.py`: reads the stored report; not iXBRL or missing → 0 rows, note `None`; writes `segments.jsonl`, `segment_note.txt`, and `update_meta(segment_count=, segment_note_chars=)`.

- [ ] Step 1: tests: Fixture S → 3 rows, `market` `sec`, `segment_count` 3 (AC-1, AC-2); plus CapEx → 5 (AC-27); non-iXBRL 10-K → empty file, count 0, status `ok` (AC-14…AC-16); bad member → status `ok`, 3 rows (AC-17); note 40 chars (AC-29); no note → no file, 0 (AC-30); `write_segments_sec` raising → status unchanged.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: call it in `fetch_company` after `_fetch_report`, when `result == "ok"` or `report == "stored"`, inside `try/except Exception` logging a warning (same pattern as `_fetch_report`).
- [ ] Step 4: run new tests and `tests/test_xbrl_fetch.py tests/test_xbrl_store.py` unedited → PASS. Commit.

### Task 4: ESEF fetch writes segments and the note

**AC:** AC-13, AC-28, AC-31, AC-37, AC-38, AC-20.

**Files:**
- Modify: `backend/arp/xbrl_pipeline/esef_json.py` (add `dimensional_facts(doc) -> tuple[list[DimFact], dict[str, str]]`; `flatten_xbrl_json` untouched)
- Modify: `backend/arp/xbrl_pipeline/fetch_esef.py` (`fetch_company_esef` ~106)
- Test: `backend/tests/test_xbrl_esef_segments.py` (new)

**Interfaces:**
- Consumes: Task 2 `build_segments`, `ESEF_METRICS`; Task 3 store methods.
- Produces: `dimensional_facts` returns numeric facts with extra dimensions (period via `parse_period`) and string facts by concept; text-block values are HTML, rendered to visible text via `esef._visible_text` on the parsed fragment.

- [ ] Step 1: tests: 2 `ifrs-full:Revenue` segment facts → 2 rows `market` `esef`, count 2 (AC-13); R&D → 2 `rnd` rows (AC-28); note `Segment A makes steel.` (AC-31); additions-only capex → 2 rows with that concept (AC-37); no `opex` rows in any (AC-38); `skipped_dimensional` unchanged.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: in the `else` branch after `set_meta`, build totals from `rows` (`fiscal_period == "FY"`), call `build_segments`, write segments/note, `update_meta`; whole step in `try/except` that logs.
- [ ] Step 4: run new tests + `tests/test_xbrl_esef_json.py tests/test_xbrl_esef_fetch.py` unedited → PASS. Commit.

### Task 5: CLI `segments` and `segment-note`

**AC:** AC-18, AC-19, AC-32, AC-33.

**Files:**
- Modify: `backend/arp/cli/xbrl.py`
- Test: `backend/tests/test_cli_xbrl.py` — append new tests only

**Interfaces:**
- Consumes: Task 3 `read_segments`, `read_segment_note`; key lookup = first `k in store.ciks()` with `company_id in store.company_ids(k)`.

- [ ] Step 1: tests: `segments s1` → exit 0, header `year  segment  metric  value  unit  concept  sum_check`, first line contains `2025`, `Alpha`, `revenue`, `300`, `USD`, `true` (AC-18); `segments zz` → exit 1, `No XBRL data for zz` (AC-19); `segment-note s1` prints note (AC-32); no note → exit 1, `No segment note for s1` (AC-33).
- [ ] Step 2: run → FAIL. Step 3: implement two commands, two-space joined columns, value printed as int when whole. Step 4: run → PASS. Commit.

## AC coverage

| AC | Task |
|---|---|
| 1, 2, 14, 15, 16, 27, 29, 30 | 3 |
| 3–12, 22–26, 34–36 | 2 (+3 end-to-end via fixture) |
| 13, 28, 31, 37, 38 | 4 (37, 38 also 2) |
| 17 | 1, 3 |
| 18, 19, 32, 33 | 5 |
| 20 | 3, 4 (existing suites unedited) |
| 21 | 1 |

One PR, `risk:normal`, `Spec: xbrl-segment-revenue`. No OpenAPI change (no API models touched). `openwiki/` needs an update after merge (new store files).

## Not doing
LLM wiring, label linkbases, product/geography axes, history, API endpoints or UI for segments.
