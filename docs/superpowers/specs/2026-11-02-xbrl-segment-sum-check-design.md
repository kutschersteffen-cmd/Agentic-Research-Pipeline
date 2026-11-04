# XBRL segment sum check: reconciling items, total members, corporate-only

Status: approved by owner 2026-11-02. Builds on the segment specs (PRs #302, #303, #312).

## Why

On the 200-company sample (2026-11-02), 86 companies had segment revenue rows and 22 of them failed the sum
check. Reading those 22 filings showed three fixable causes:

1. **Reconciling items (6 companies).** The segments add up to the total only after corporate revenue and
   eliminations, which filers tag on `srt:ConsolidationItemsAxis` alone. Coca-Cola FY2025: segments 48,806 +
   `CorporateNonSegmentMember` 144 + `ConsolidationEliminationsMember` −1,009 = 47,941, the reported total.
   Some filers tag eliminations as a positive amount (Franklin Electric: +124.8, subtracted in the table).
2. **Total members (3 companies).** A member that is the sum of the others is tagged as a segment
   (`VVPR:TotalSegmentMember`, `CIK0002027815:TotalMember`, and in one filing a duplicate member with the same
   value as the only other one). The rows double count.
3. **Corporate-only (3 companies).** The only segment row is a corporate or "all other" member
   (`us-gaap:CorporateAndOtherMember`, `us-gaap:CorporateMember`, `ifrs-full:AllOtherSegmentsMember`), with value
   0 or a small negative number. The company is really single-segment.

The other 10 failures are unallocated revenue that the filer did not tag. They stay `false`.

## Decisions

| Topic | Decision |
|---|---|
| Scope | Rows with `axis_kind` `segment`, every metric. Product and geography rows are unchanged. |
| Reconciling facts | A fact counts as reconciling when it has the row's concept and fiscal year, is full-year, and its only explicit dimension is `srt:ConsolidationItemsAxis` with member `CorporateNonSegmentMember`, `SegmentReconcilingItemsMember`, `ConsolidationEliminationsMember` or `IntersegmentEliminationMember`, with prefix `us-gaap` or `srt`. |
| Sign | Corporate and reconciling members add their value as tagged. The two elimination members always subtract their absolute value. |
| Sum check | `sum_matches_total` is true when `abs(segments + reconciling − total) / total <= 0.01`. Each segment row gets `reconciling`: the reconciling amount it was checked with (0 when none). A total of 0, or no total, gives `false`. |
| Total members | Before the sum check, a segment member whose value equals the sum of all other segment members of the same metric and year (within 0.5%), with at least one other member, is dropped. At most one member is dropped per metric and year. |
| Corporate-only | If the only segment member left for a metric and year is `CorporateAndOtherMember`, `CorporateMember`, `CorporateNonSegmentMember` (`us-gaap` or `srt` prefix) or `ifrs-full:AllOtherSegmentsMember`, that row is dropped. |
| Meta | `segment_count` counts the rows after dropping. |

## Non-goals

- Untagged unallocated revenue (the remaining 10).
- Choosing a different total concept when the segment concept has no total.
- Product and geography rows.

## Acceptance

Fixture K (SEC iXBRL 10-K, FY2025, USD, concept `us-gaap:Revenues`): non-dimensional total 47,941; segment
members A=19,586, B=11,513, C=6,334, D=5,638, E=5,735 (sum 48,806); `srt:ConsolidationItemsAxis` facts
`us-gaap:CorporateNonSegmentMember`=144 and `us-gaap:ConsolidationEliminationsMember`=−1,009.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture K | `arp xbrl fetch` runs | Exactly 5 segment revenue rows, each with `sum_matches_total: true` and `reconciling` −865 | unit |
| AC-2 | Fixture K with the elimination tagged as +1,009 | fetch runs | Each segment revenue row has `sum_matches_total: true` and `reconciling` −865 | unit |
| AC-3 | Fixture K with the elimination tagged as `srt:IntersegmentEliminationMember` −1,009 | fetch runs | Each row has `sum_matches_total: true` | unit |
| AC-4 | Fixture K with both reconciling facts removed | fetch runs | Each row has `sum_matches_total: false` and `reconciling` 0 | unit |
| AC-5 | Fixture K plus a corporate fact that also carries a segment member | fetch runs | `reconciling` is still −865 | unit |
| AC-6 | Fixture K plus a corporate fact for fiscal year 2024 | fetch runs | `reconciling` is still −865 | unit |
| AC-7 | Segment members X=53,000, Y=8,000, `x:TotalSegmentMember`=61,000; total 61,000 | fetch runs | Exactly 2 segment revenue rows (X, Y), both `sum_matches_total: true`; `segment_count` 2 | unit |
| AC-8 | Segment members P=5,169,784 and Q=5,169,784; total 5,169,784 | fetch runs | Exactly 1 segment revenue row with value 5,169,784 and `sum_matches_total: true` | unit |
| AC-9 | Segment members X=60, Y=40, Z=100; total 200 | fetch runs | Exactly 2 rows (X, Y): Z equals the sum of the others and is dropped whatever the total; both rows have `sum_matches_total: false` | unit |
| AC-10 | Segment members X=60, Y=40, Z=100; total 100 | fetch runs | Exactly 2 rows (X, Y), both `sum_matches_total: true` | unit |
| AC-11 | The only segment member is `us-gaap:CorporateAndOtherMember` = −26,885,000 | fetch runs | No segment revenue rows; `segment_count` 0 | unit |
| AC-12 | The only segment member is `ifrs-full:AllOtherSegmentsMember` = 0 (a 20-F) | fetch runs | No segment revenue rows | unit |
| AC-13 | Segment members `us-gaap:CorporateMember`=10 and `x:RetailMember`=90 | fetch runs | Both rows are kept | unit |
| AC-14 | The product/geography spec's Fixture P | fetch runs | Product and geography rows are identical to that spec's AC-1 and AC-2 | unit |
| AC-16 | Fixture K's pattern on `us-gaap:OperatingExpenses`: segments 100 and 50, `CorporateNonSegmentMember` −30, total 120 | fetch runs | Both segment `opex` rows have `sum_matches_total: true` and `reconciling` −30 | unit |
| AC-17 | Fixture K with the corporate fact on `srt:CorporateNonSegmentMember` instead of `us-gaap:` | fetch runs | `reconciling` is −865 | unit |
| AC-18 | Fixture K plus `us-gaap:SegmentReconcilingItemsMember` = 10, total 47,951 | fetch runs | `reconciling` is −855 and rows have `sum_matches_total: true` | unit |
| AC-19 | Fixture K plus `x:CorporateNonSegmentMember` = 500 | fetch runs | `reconciling` is still −865 | unit |
| AC-20 | Fixture K plus a 3-month `us-gaap:CorporateNonSegmentMember` fact = 50 | fetch runs | `reconciling` is still −865 | unit |
| AC-21 | Segments 990, total 1,000 (1.0% off), no reconciling facts | fetch runs | `sum_matches_total: true` | unit |
| AC-22 | Segments 989, total 1,000 (1.1% off) | fetch runs | `sum_matches_total: false` | unit |
| AC-23 | Segments X=600, Y=400, Z=1,005 (0.5% off X+Y) | fetch runs | Z is dropped: exactly 2 rows | unit |
| AC-24 | Segments X=600, Y=400, Z=1,006 (0.6% off X+Y) | fetch runs | Z is kept: exactly 3 rows | unit |
| AC-25 | The only segment member is `srt:CorporateNonSegmentMember` = 5 | fetch runs | No segment revenue rows; `segment_count` 0 | unit |
| AC-26 | Segments 10 and 20, non-dimensional total 0 | fetch runs | Both rows have `sum_matches_total: false` | unit |
| AC-15 | The existing XBRL, ESEF and segment test files | run | They pass. The only edits allowed add `reconciling` to expected row literals, and each edit is listed in the PR | unit |

Must not change: product and geography rows (AC-14); segment rows that already passed, apart from the new
`reconciling` field (AC-15).

`unit` rows are owed as `holdout` once `HOLDOUT_TOKEN` is set.
