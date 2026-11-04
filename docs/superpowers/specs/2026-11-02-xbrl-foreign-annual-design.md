# XBRL segments for 20-F and 40-F filers

Status: approved by owner 2026-11-02. Builds on the segment and product/geography specs (PRs #302, #303).

## Why

A 200-company random sample of NYSE/Nasdaq filers (2026-11-02) ran through `arp xbrl fetch --market sec`.
48 of the 193 fetched companies had no stored annual report, so they got no segment rows. Of those 48:
27 file a 20-F, 4 a 20-F/A, 4 a 40-F, and 13 have no annual report on EDGAR at all.

The cause is one line: `EdgarDocumentSource.fetch_latest_annual_original` takes only the first `10-K` in the
filing list. The document fetcher in the same file already treats `ANNUAL_FORMS = ("10-K", "20-F", "40-F")` as
annual reports. 20-F and 40-F filings are inline XBRL like a 10-K, so the parser does not change. Foreign
filers mostly report under IFRS, so their facts use `ifrs-full` concepts and axes, which the ESEF path already
knows.

## Decisions

| Topic | Decision |
|---|---|
| Forms | `fetch_latest_annual_original` takes the first filing whose form is `10-K`, `20-F` or `40-F` in EDGAR's recent list (newest first). Amendments (`/A`) are skipped, as today. The stored `ReportMeta.form` is the real form, no longer always `10-K`. |
| Taxonomy per filing | Every 10-K, 20-F and 40-F is read twice: once with the US-GAAP concept lists and axes (as today), once with the ESEF ones (`ESEF_METRICS`, the ESEF segment, product and geography axes). The set with more rows wins; a tie goes to US-GAAP. Rows keep `market: "sec"`. |
| Segment note | The note concept follows the winning set: `ifrs-full:DisclosureOfOperatingSegmentsExplanatory` for the ESEF set, else the US-GAAP one. |
| Rows | Each segment row gets `form` (`10-K`, `20-F` or `40-F`). |
| Unchanged | Companies with a 10-K produce exactly the same rows as before, plus the `form` field. Companies with no annual report keep `segment_count: 0`. |

## Non-goals

- Required rows and `facts.jsonl` from `companyfacts` for IFRS filers (a separate gap: the US-GAAP required tags find nothing for them).
- 6-K interim reports. Amendments. Filers with no annual report on EDGAR.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | EDGAR submissions listing `6-K`, `20-F`, `10-Q` (newest first) and a stored iXBRL 20-F | `arp xbrl fetch` runs | The stored report's meta has `form` `20-F` and the 20-F's accession | unit |
| AC-2 | Submissions listing `20-F/A` then `20-F` | fetch runs | The stored report is the `20-F`, not the amendment | unit |
| AC-3 | Submissions listing `40-F` only | fetch runs | The stored report has `form` `40-F` | unit |
| AC-4 | Submissions listing `10-K` then an older `20-F` | fetch runs | The stored report has `form` `10-K` | unit |
| AC-5 | A 20-F iXBRL fixture with 2 full-year `ifrs-full:Revenue` facts on `ifrs-full:SegmentsAxis` (A=600, B=400) and a non-dimensional `ifrs-full:Revenue` 1000 | fetch runs | `segments.jsonl` has exactly 2 segment revenue rows, values 600 and 400, `market` `sec`, `form` `20-F`, both `sum_matches_total: true` | unit |
| AC-6 | The AC-5 fixture plus 2 `ifrs-full:Revenue` facts on `ifrs-full:GeographicalAreasAxis` | fetch runs | Exactly 2 rows with `axis_kind` `geography`, values 700 and 300 (the fixture's); the 2 segment rows are unchanged from AC-5 | unit |
| AC-7 | The AC-5 fixture plus an `ifrs-full:DisclosureOfOperatingSegmentsExplanatory` text block `Segment A sells ore.` | fetch runs | `segment_note.txt` content equals `Segment A sells ore.` after trimming whitespace | unit |
| AC-8 | A 20-F iXBRL fixture tagged with US-GAAP concepts (segment revenue on `us-gaap:StatementBusinessSegmentsAxis`, 2 members) | fetch runs | Exactly 2 segment revenue rows with `form` `20-F` and a `us-gaap:` concept | unit |
| AC-12 | The AC-8 fixture plus a `us-gaap:SegmentReportingDisclosureTextBlock` `Two segments.` | fetch runs | `segment_note.txt` content equals `Two segments.` after trimming whitespace | unit |
| AC-13 | The AC-8 fixture plus 1 dimensional `ifrs-full:Revenue` fact on `ifrs-full:SegmentsAxis` | fetch runs | Exactly 2 segment revenue rows, both with a `us-gaap:` concept (US-GAAP set has more rows) | unit |
| AC-9 | The segment spec's Fixture S (a 10-K) | fetch runs | The same 3 segment rows as the segment spec's AC-1, each with `form` `10-K` | unit |
| AC-10 | Submissions with no `10-K`, `20-F` or `40-F` | fetch runs | No report is stored; `segment_count` is 0; company status is `ok` | unit |
| AC-11 | The existing XBRL, ESEF and segment test files | run | They pass. The only edits allowed add `form` to expected row literals, and each edit is listed in the PR | unit |

Must not change: 10-K rows apart from the new `form` field (AC-9); the existing test files (AC-11).

`unit` rows are owed as `holdout` once `HOLDOUT_TOKEN` is set.
