# XBRL segment labels from the filing's label file — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SEC segment rows take the filer's standard English label (cleaned) as `segment`, with a new `segment_source` of `label` or `derived`.

**Architecture:** `fetch_latest_annual_original` already has the client and the filing folder; it also fetches `index.json` and the first `_lab.xml` and returns the bytes on `AnnualOriginal.labels` (None on any failure). `_fetch_report` stores them as `labels-<accession>.xml`. `write_segments_sec` reads that file, builds a member → label map, and `sec_segments` overrides `segment` on matching rows. `build_segments` and the ESEF path are untouched, so ESEF rows keep the default `derived`.

**Tech Stack:** Python 3, Pydantic, httpx, `xml.etree.ElementTree` (stdlib), pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-xbrl-segment-labels-design.md` (approved 2026-11-03).

## Global Constraints

- `SegmentRow.segment_source: Literal["label", "derived"] = "derived"`. Old `segments.jsonl` still reads; existing literals compare equal unless they spell out every field (AC-11).
- Index URL: `https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/index.json`; files are `directory.item[].name`. First name ending `_lab.xml` in index order (AC-13). No such file, a non-2xx, or a parse error → `labels=None`, logged; the annual report itself is still returned (AC-6, AC-7).
- Label file stored only in `_fetch_report`'s `stored` branch, via a new `XbrlStore.save_labels(cik10, accession, content)` writing `labels-<accession>.xml` in `company_dir` (AC-4). `XbrlStore.file_path(key, "labels")` finds it from `report_meta().accession`.
- Label map (`segments.label_map(xml: bytes) -> dict[str, str]`): `loc` `xlink:label` → concept from the `href` fragment (`x_AlphaSegmentMember` → `x:AlphaSegmentMember`, split on the first `_`); `labelArc` from → to; `label` resources with role `http://www.xbrl.org/2003/role/label` and `xml:lang` starting `en`. Exact `en-US` wins, else first `en*` in file order (AC-5, AC-12).
- Cleaning: strip trailing ` [Member]`, then trailing ` Segment` (case-insensitive), then whitespace (AC-1, AC-14).
- Members with prefix `us-gaap:`, `srt:`, `ifrs-full:`, `country:` never take a label (AC-8).
- Applied in `sec_segments` (new `labels: dict[str, str] | None = None` arg) inside its existing `model_copy`, for every axis kind.

## What the code gives us

| Need | Existing piece |
|---|---|
| Filing folder, client, headers, delay | `EdgarDocumentSource.fetch_latest_annual_original` |
| "Never changes company status" | `_fetch_report`'s `except` returns `"error"`; labels failure is caught earlier and returns None |
| Store next to report | `XbrlStore.company_dir`, `atomic_write_bytes` |
| Row post-processing hook | `sec_segments`' `model_copy(update=...)` |
| End-to-end fetch fixtures | `tests/segment_fixture.py` (Fixture S), `tests/test_xbrl_fetch_segments.py`, `tests/test_edgar_annual_original.py` (httpx mock) |
| CLI line | `arp xbrl segments` prints `r.segment` already (AC-10 needs no CLI change) |

## Review Focus

1. A label failure must not turn into `"error"` for the report: catch inside the edgar method, not by raising.
2. Companies whose report is `unchanged` get no label file until their next filing (spec says labels are fetched "when the annual report is stored").

---

### Task 1: Download and store the label file

**AC:** AC-4, AC-6, AC-7, AC-13.

**Files:**
- Modify: `backend/arp/ingestion/edgar.py` (`AnnualOriginal.labels: bytes | None = None`; index + label fetch in `fetch_latest_annual_original`)
- Modify: `backend/arp/xbrl_pipeline/store.py` (`save_labels`; `file_path` kind `labels`)
- Modify: `backend/arp/xbrl_pipeline/fetch.py` (`_fetch_report`: `if annual.labels: store.save_labels(...)`)
- Test: `backend/tests/test_xbrl_segment_labels.py` (new)

- [ ] Step 1: tests through the SEC fetch with a mocked transport serving Fixture L: `labels-<accession>.xml` exists in the company folder (AC-4); index with two `_lab.xml` names → stored file is the first (AC-13); index without `_lab.xml` → no file, status `ok` (AC-6); label URL 404 → no file, status `ok` (AC-7).
- [ ] Step 2: `cd backend && python3 -m pytest tests/test_xbrl_segment_labels.py` → FAIL.
- [ ] Step 3: implement per Global Constraints.
- [ ] Step 4: run → PASS. Commit.

### Task 2: Use labels for segment names

**AC:** AC-1, AC-2, AC-3, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14.

**Files:**
- Modify: `backend/arp/xbrl_pipeline/models.py` (`SegmentRow.segment_source`)
- Modify: `backend/arp/xbrl_pipeline/segments.py` (`label_map`, `_clean_label`; `sec_segments(labels=...)`; `write_segments_sec` reads the label file)
- Modify: existing tests' whole-row segment literals only where they now fail, adding `segment_source` (AC-11)
- Test: `backend/tests/test_xbrl_segment_labels.py` (append)

- [ ] Step 1: tests end-to-end through fetch → `segments.jsonl`: Alpha `Alpha, Beta & Co`/`label` (AC-1); Beta `Beta Products`/`label` (AC-2); Gamma `Gamma`/`derived` (AC-3); extra `de` + terse labels → still `Alpha, Beta & Co` (AC-5); `en` then `en-US` → `Alpha Two` (AC-12); `Delta segment [Member]` → `Delta` (AC-14); `country:US` geography fact with label → `US`/`derived` (AC-8); Task 1's AC-6/AC-7/AC-13 cases now also assert all rows `derived` / Alpha `Alpha, Beta & Co`; ESEF fixture with segment rows → all `derived` (AC-9); CliRunner `arp xbrl segments s1` output contains `Alpha, Beta & Co` (AC-10).
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement per Global Constraints.
- [ ] Step 4: add `segment_source` to whole-row literals in the XBRL/ESEF/segment test files only where they now fail; no other edit; list each in the PR. Run `test_xbrl*.py test_esef*.py test_segment*.py test_edgar*.py` → PASS (AC-11). Commit.

## AC coverage

| AC | Task |
|---|---|
| 4 | 1 |
| 6, 7, 13 | 1 (file, status), 2 (rows) |
| 1–3, 5, 8–12, 14 | 2 |

One PR, `risk:normal`, `Spec: xbrl-segment-labels`. If `SegmentRow` is in an API response model, run `export_openapi.py` + `npm run gen:api` and commit both. `openwiki/` needs an update after merge (`segment_source`, label file).
