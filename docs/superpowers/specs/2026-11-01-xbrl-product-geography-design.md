# XBRL revenue by product and geography (SEC + ESEF)

Status: approved by owner 2026-11-01. Builds on `2026-11-01-xbrl-segment-revenue-design.md` (PR #302).

## Why

The segment spec reads only the segment axis. The same filings also tag revenue by product line and by
country. Apple's FY2025 10-K, for example: iPhone 209,586, Mac 33,708, iPad 28,023, Wearables 35,686,
Services 109,158 ($m) on `srt:ProductOrServiceAxis`, and US 151,790, China 64,377, other countries 199,994
on `srt:StatementGeographicalAxis`. The pipeline already parses these facts in `parse_ixbrl_dimensional`
and `flatten_xbrl_json`, then drops them because the axis is not the segment axis. This spec keeps them.

## Decisions

| Topic | Decision |
|---|---|
| Scope | Revenue only, by product/service and by geography, both markets, same filing and year rule as the segment spec. |
| Axes | SEC: `srt:ProductOrServiceAxis` (`product`), `srt:StatementGeographicalAxis` (`geography`). ESEF: `ifrs-full:ProductsAndServicesAxis`, `ifrs-full:GeographicalAreasAxis`. ESEF axis names are confirmed against the ifrs-full schema before use; a name not in it is dropped, not guessed. |
| Fact shape kept | Same as segment facts: full-year, numeric, the axis alone or the axis plus `srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember`. A fact with both a segment member and a product member (segment × product) is not kept. |
| Output | Same `segments.jsonl`. Each row gets `axis_kind`: `segment`, `product` or `geography`. Existing segment rows get `axis_kind: "segment"` and `level: null`; no other field of theirs changes. |
| Level (product only) | Filers often tag a standard rollup (`us-gaap:ProductMember`, `us-gaap:ServiceMember`, `us-gaap:ServiceOtherMember`) next to their own product lines, so the members overlap. Product rows get `level`: `standard` when the member's prefix is `us-gaap`, `srt` or `ifrs-full`, else `company`. Geography and segment rows have `level: null`. |
| Sum check | Computed per (`axis_kind`, `level`, year) with the segment spec's rule. So Apple's standard product level (Product + Service = 416,161) is `true`, and its company level (product lines only, 307,003) is `false`. `false` is information, not an error. |
| Names | Segment spec's name rule, plus: `country:XX` gives `XX` (e.g. `country:US` → `US`). |
| Meta | `meta.json` gets `product_count` and `geography_count`; `segment_count` keeps counting segment rows only. |
| CLI | `arp xbrl segments <company_id> --axis segment|product|geography`, default `segment`. Output columns unchanged; `--axis product` adds a `level` column after `segment`. |

## Non-goals

- Metrics other than revenue on these axes; long-lived assets by country.
- Segment × product or segment × geography crossings.
- Mapping members to a shared product or country taxonomy across companies.
- History beyond the latest annual filing. Label linkbases.

## Acceptance

Fixture P (SEC iXBRL 10-K, FY2025, USD, revenue concept `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`):
non-dimensional total 1000; segment facts as Fixture S of the segment spec; on `srt:ProductOrServiceAxis`
`x:WidgetsMember`=600, `x:GadgetsMember`=300, `us-gaap:ProductMember`=900, `us-gaap:ServiceMember`=100;
on `srt:StatementGeographicalAxis` `country:US`=400, `country:DE`=350, `x:RestOfWorldMember`=250.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture P | `arp xbrl fetch` runs | `segments.jsonl` has exactly 4 rows with `axis_kind` `product`, values 600, 300, 900, 100 | unit |
| AC-2 | Fixture P | fetch runs | Exactly 3 rows with `axis_kind` `geography`, values 400, 350, 250 | unit |
| AC-3 | Fixture P | fetch runs | The 3 segment rows have exactly the segment spec's AC-1 fields and values, plus `axis_kind` `segment` and `level` `null` | unit |
| AC-4 | Fixture P | fetch runs | `x:WidgetsMember` and `x:GadgetsMember` rows have `level` `company`; `us-gaap:ProductMember` and `us-gaap:ServiceMember` rows have `level` `standard` | unit |
| AC-5 | Fixture P | fetch runs | Both `standard` product rows have `sum_matches_total: true` | unit |
| AC-6 | Fixture P | fetch runs | Both `company` product rows have `sum_matches_total: false` | unit |
| AC-7 | Fixture P | fetch runs | All 3 geography rows have `sum_matches_total: true` and `level: null` | unit |
| AC-8 | Fixture P | rows written | The `country:US` row has `segment` `US`; the `x:RestOfWorldMember` row has `segment` `Rest Of World` | unit |
| AC-9 | Fixture P | read `meta.json` | `product_count` 4, `geography_count` 3, `segment_count` 3 | unit |
| AC-10 | Fixture P plus one revenue fact with both `us-gaap:StatementBusinessSegmentsAxis` and `srt:ProductOrServiceAxis` members | fetch runs | Row counts stay 3 segment, 4 product, 3 geography | unit |
| AC-11 | Fixture P plus a product fact that also carries `srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember` (member `x:ToolsMember`=50) | fetch runs | A product row for `x:ToolsMember` with value 50 exists | unit |
| AC-12 | Fixture P plus a `srt:ProductOrServiceAxis` fact for `us-gaap:CostOfRevenue` | fetch runs | No product row has `metric` other than `revenue` | unit |
| AC-13 | ESEF fixture with 2 full-year `ifrs-full:Revenue` facts on the ESEF product axis and 2 on the ESEF geography axis | fetch runs | 2 rows `axis_kind` `product` and 2 rows `axis_kind` `geography`, all `market` `esef`; each row whose member starts with `ifrs-full:` has `level` `standard` | unit |
| AC-14 | Fixture P stored | `arp xbrl segments s1 --axis product` | Exit code 0; header `year  segment  level  metric  value  unit  concept  sum_check`, then exactly 4 data lines | unit |
| AC-15 | Fixture P stored | `arp xbrl segments s1 --axis geography` | Exit code 0; the header used without `--axis`, then exactly 3 data lines | unit |
| AC-16 | Fixture P stored | `arp xbrl segments s1` (no `--axis`) | Same output as the segment spec's AC-18 for the 3 segment rows | unit |
| AC-17 | Fixture P stored | `arp xbrl segments s1 --axis region` | Exit code 2 (invalid option value) | unit |
| AC-18 | The segment spec's tests (`test_ac_1` … `test_ac_39`) | run | They pass. The only edits are adding `axis_kind` and `level` to expected row literals, and each edit is listed in the PR | unit |
| AC-19 | AC-13's ESEF fixture plus 1 revenue fact on an axis that is neither the ESEF product, geography nor segment axis | fetch runs | Still exactly 2 product and 2 geography rows | unit |

Must not change: segment rows' values and `segment_count` (AC-3, AC-9, AC-18); default CLI output (AC-16).

`unit` rows are owed as `holdout` once `HOLDOUT_TOKEN` is set.
