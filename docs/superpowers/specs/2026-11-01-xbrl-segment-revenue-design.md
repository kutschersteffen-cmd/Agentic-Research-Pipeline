# XBRL segment financials (SEC + ESEF)

Status: approved by owner 2026-11-01.

## Why

Segment revenue is extracted today only by the LLM (`arp/extraction/segment_extractor_agent.py`).
For all listed US companies that costs roughly $100–1,000 per year of filings (extractor plus
verifier). Most filers already tag segment revenue as dimensional XBRL facts, and the XBRL pipeline
already downloads the files that contain them. It just throws the dimensional facts away:

- **SEC:** `companyfacts` has no dimensions, but `xbrl fetch` already stores each company's latest
  10-K as filed (`annual-<accession>.htm`, `inline_xbrl: true` for iXBRL filers). Nothing parses it.
- **ESEF:** `flatten_xbrl_json` (`arp/xbrl_pipeline/esef_json.py`) skips every fact with a dimension
  key beyond concept/entity/period/unit and only counts them (`meta.json` `skipped_dimensional`).
- `arp/ingestion/esef.py` `_contexts` drops contexts with `xbrli:segment`/`scenario` on purpose
  (comment: "carry dimensions if a field needs them").

The earlier specs (`2026-10-09-xbrl-pipeline-design.md`, `2026-10-09-xbrl-esef-design.md`) left this as
"per-filing iXBRL parsing later". This spec is that later step, for revenue, CapEx, operating expenses and R&D by segment.

## Decisions

| Topic | Decision |
|---|---|
| Scope | Revenue, CapEx, operating expenses (total, cost of revenue, SG&A) and R&D by reportable/operating segment, both markets. Only the latest annual filing, and only its own fiscal year (prior-year comparatives in it are not kept). |
| Metrics and concepts | Each row has a `metric`. Per metric, the first concept in the list that has segment facts wins, per company. |
| `revenue` | SEC: existing `REVENUE_TAGS`. ESEF: existing IFRS revenue candidates. |
| `capex` | SEC: existing `CAPEX_TAGS` (segment notes usually use `PaymentsToAcquireProductiveAssets`). ESEF: existing `IFRS_CAPEX_TAGS`, then `ifrs-full:AdditionsToNoncurrentAssets` (IFRS 8 additions). |
| `rnd` | SEC: existing `RND_TAGS`. ESEF: `ifrs-full:ResearchAndDevelopmentExpense`. |
| `opex` | SEC: `us-gaap:OperatingExpenses`, `us-gaap:CostsAndExpenses`. ESEF: none. IFRS has no single total-operating-expense concept, so ESEF `opex` rows are not produced. |
| `cost_of_revenue` | SEC: `us-gaap:CostOfRevenue`, `us-gaap:CostOfGoodsAndServicesSold`. ESEF: `ifrs-full:CostOfSales`. |
| `sga` | SEC: `us-gaap:SellingGeneralAndAdministrativeExpense`. ESEF: `ifrs-full:SellingGeneralAndAdministrativeExpense`. |
| Concept names | New names (not already in the code) are confirmed against the stored US-GAAP / IFRS taxonomy snapshots before use; a name not in the schema is dropped, not guessed (as in the ESEF spec). |
| Segment axes | SEC: `us-gaap:StatementBusinessSegmentsAxis`. ESEF: `ifrs-full:SegmentsAxis`. Product (`srt:ProductOrServiceAxis`) and geography (`srt:StatementGeographicalAxis`) are non-goals. |
| Fact shape kept | Full-year duration (350–380 days, as `_full_year`), numeric, and its explicit dimensions are the segment axis alone, or the segment axis plus `srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember` (Apple's 10-K tags every segment fact this way). Facts with a second dimension (e.g. `srt:ConsolidationItemsAxis`) are not kept, so intersegment eliminations and subtotals never appear as segments. |
| Segment name | The member QName (e.g. `aapl:AmericasSegmentMember`) and a readable name derived from it: local name, trailing `Member` removed, then trailing `Segment` removed, CamelCase split (`AmericasSegmentMember` → `Americas`, `CloudServicesMember` → `Cloud Services`). Label linkbases are not read. |
| Sum check | Each row carries `sum_matches_total`: true when `abs(sum - total) / total <= 0.01`, where `sum` is that year's segment values of one metric and `total` the non-dimensional fact of the same concept and year. No total fact gives `false`. For expense metrics `false` is common (unallocated corporate costs); it is information, not an error. |
| Output | New file `segments.jsonl` per company in the existing XBRL store, one row per segment per metric. `meta.json` gets `segment_count`. |
| SEC parsing | Extend `arp/ingestion/esef.py` iXBRL parsing (10-K inline XBRL is the same format) to optionally return facts whose context has explicit members, with axis and member. The default behaviour of `parse_ixbrl` does not change. |
| CLI | `arp xbrl segments <company_id>` prints a header `year  segment  metric  value  unit  concept  sum_check` and one line per row. `arp xbrl segment-note <company_id>` prints `segment_note.txt`; with no note it exits 1 with `No segment note for <company_id>`. |
| Segment note text | SEC: the `ix:nonNumeric` fact `us-gaap:SegmentReportingDisclosureTextBlock`. ESEF: `ifrs-full:DisclosureOfOperatingSegmentsExplanatory`. Its visible text (tags stripped, block breaks kept, as `parse_ixbrl` renders text) is stored as `segment_note.txt` per company. `meta.json` gets `segment_note_chars` (0 when absent). It is the evidence the LLM reads for qualitative segment descriptions, replacing a keyword search over the whole filing. |
| LLM fallback | Out of scope here. A follow-up wires the financials pipeline to use `segments.jsonl` and call the LLM only for companies with zero rows or `sum_matches_total: false`. |

## Row format (`segments.jsonl`)

```json
{"company_id": "apple", "market": "sec", "fiscal_year": 2025, "metric": "revenue", "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
 "axis": "us-gaap:StatementBusinessSegmentsAxis", "member": "aapl:AmericasSegmentMember", "segment": "Americas",
 "value": 167045000000, "unit": "USD", "period_start": "2024-09-29", "period_end": "2025-09-27",
 "accession": "0000320193-25-000079", "sum_matches_total": true}
```

## Non-goals

- Product, geography and other axes. Segment income, assets.
- Changing the LLM prompt or the description fields. Wiring `segment_note.txt` into the financials pipeline as evidence is part of the follow-up spec named under "LLM fallback".
- History beyond the latest annual filing.
- Label linkbase lookup for display names.
- Wiring into the financials/LLM pipeline (follow-up spec).
- Non-iXBRL (plain HTML) 10-Ks: they yield zero rows.

## Acceptance

Fixture S (SEC iXBRL 10-K, FY2025, USD), revenue concept `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` unless a row says otherwise:
non-dimensional total 1000; segment axis members `x:AlphaSegmentMember`=300, `x:BetaMember`=400, `x:GammaSegmentMember`=295.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture S stored for company `s1` | `arp xbrl fetch` runs for `s1` | `segments.jsonl` has exactly 3 rows: `member`/`value` = `x:AlphaSegmentMember`/300, `x:BetaMember`/400, `x:GammaSegmentMember`/295, each `unit` `USD`, `fiscal_year` 2025, `market` `sec` | unit |
| AC-2 | AC-1 done | read `meta.json` | `segment_count` is 3 | unit |
| AC-3 | Fixture S plus one fact with the segment axis and `srt:ConsolidationItemsAxis=us-gaap:IntersegmentEliminationMember` | fetch runs | Row count is 3 | unit |
| AC-4 | Fixture S plus one fact on `srt:ProductOrServiceAxis` only | fetch runs | Row count is 3 and no row has `axis` `srt:ProductOrServiceAxis` | unit |
| AC-5 | Fixture S plus one 3-month segment fact (member `x:AlphaSegmentMember`) | fetch runs | Row count is 3; the Alpha row's `value` is 300 | unit |
| AC-6 | Fixture S plus FY2024 segment facts for the same members | fetch runs | Row count is 3; every row has `fiscal_year` 2025 | unit |
| AC-7 | Fixture S plus segment facts for `us-gaap:Revenues` | fetch runs | Every row has `concept` `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | unit |
| AC-8 | Fixture S (sum 995, total 1000) | fetch runs | Every row has `sum_matches_total: true` | unit |
| AC-9 | Fixture S with Gamma = 275 (sum 975) | fetch runs | Every row has `sum_matches_total: false` | unit |
| AC-10 | Fixture S with Gamma = 320 (sum 1020) | fetch runs | Every row has `sum_matches_total: false` | unit |
| AC-11 | Fixture S without the non-dimensional total | fetch runs | Every row has `sum_matches_total: false` | unit |
| AC-12 | Fixture S | rows written | `segment` values are `Alpha`, `Beta`, `Gamma` | unit |
| AC-13 | ESEF xBRL-JSON fixture with 2 full-year `ifrs-full:Revenue` facts on `ifrs-full:SegmentsAxis` | `arp xbrl fetch` runs for that LEI company | `segments.jsonl` has exactly 2 rows with `market` `esef`; `meta.json` `segment_count` is 2 | unit |
| AC-14 | A company whose stored 10-K is not iXBRL | fetch runs | `segments.jsonl` exists with 0 lines | unit |
| AC-15 | Same as AC-14 | read `meta.json` | `segment_count` is 0 | unit |
| AC-16 | Same as AC-14 | fetch runs | The company's fetch status is `ok` (the value it gets today) | unit |
| AC-17 | Fixture S plus one revenue fact whose context has an explicit member with no `dimension` attribute | fetch runs | Exit code 0; company status `ok`; `segments.jsonl` has exactly the 3 Fixture S rows | unit |
| AC-18 | AC-1 done | `arp xbrl segments s1` | Exit code 0; header `year  segment  metric  value  unit  concept  sum_check`; 3 lines, the first containing `2025`, `Alpha`, `revenue`, `300`, `USD`, `true` | unit |
| AC-19 | No company `zz` in the store | `arp xbrl segments zz` | Exit code 1, message `No XBRL data for zz` | unit |
| AC-20 | The existing tests under `backend/tests/` for `esef_json`, `fetch_esef` and `xbrl_pipeline` | run | They pass with no edits to them | unit |
| AC-21 | The existing `parse_ixbrl` tests | run | They pass with no edits to them | unit |
| AC-22 | Fixture S plus `us-gaap:PaymentsToAcquireProductiveAssets` segment facts Alpha=50, Beta=70 | fetch runs | 2 rows with `metric` `capex`, values 50 and 70; the 3 revenue rows are unchanged | unit |
| AC-23 | Fixture S plus `us-gaap:ResearchAndDevelopmentExpense` segment facts Alpha=20, Beta=30 | fetch runs | 2 rows with `metric` `rnd`, values 20 and 30 | unit |
| AC-24 | Fixture S plus `us-gaap:OperatingExpenses` segment facts Alpha=100, Beta=120 | fetch runs | 2 rows with `metric` `opex`, values 100 and 120 | unit |
| AC-25 | Fixture S plus `us-gaap:CostOfRevenue` segment fact Alpha=150 | fetch runs | 1 row with `metric` `cost_of_revenue`, value 150 | unit |
| AC-26 | Fixture S plus `us-gaap:SellingGeneralAndAdministrativeExpense` segment fact Beta=60 | fetch runs | 1 row with `metric` `sga`, value 60 | unit |
| AC-27 | Fixture S plus AC-22's CapEx facts | read `meta.json` | `segment_count` is 5 (rows across all metrics) | unit |
| AC-28 | ESEF fixture with 2 `ifrs-full:ResearchAndDevelopmentExpense` facts on `ifrs-full:SegmentsAxis` | fetch runs | 2 rows with `metric` `rnd` and `market` `esef` | unit |
| AC-29 | Fixture S with a `us-gaap:SegmentReportingDisclosureTextBlock` whose visible text is `Alpha sells widgets. Beta sells gadgets.` | fetch runs | `segment_note.txt` contains exactly that text, and `meta.json` `segment_note_chars` is 40 | unit |
| AC-30 | Fixture S without that text block | fetch runs | No `segment_note.txt` exists and `segment_note_chars` is 0 | unit |
| AC-31 | An ESEF fixture with `ifrs-full:DisclosureOfOperatingSegmentsExplanatory` text `Segment A makes steel.` | fetch runs | `segment_note.txt` contains exactly `Segment A makes steel.` | unit |
| AC-32 | AC-29 done | `arp xbrl segment-note s1` | Exit code 0, prints `Alpha sells widgets. Beta sells gadgets.` | unit |
| AC-33 | AC-30 done | `arp xbrl segment-note s1` | Exit code 1, message `No segment note for s1` | unit |
| AC-34 | Fixture S plus a revenue segment fact on member `x:CloudServicesMember` | fetch runs | That row's `segment` is `Cloud Services` | unit |
| AC-35 | AC-24's facts plus `us-gaap:CostsAndExpenses` segment facts Alpha=110, Beta=130 | fetch runs | Every `opex` row has `concept` `us-gaap:OperatingExpenses` | unit |
| AC-36 | AC-24's facts plus a non-dimensional `us-gaap:OperatingExpenses` total of 300 | fetch runs | Every `opex` row has `sum_matches_total: false`; every revenue row has `sum_matches_total: true` | unit |
| AC-37 | ESEF fixture with only IFRS 8 additions segment facts (2 members), no `IFRS_CAPEX_TAGS` segment facts | fetch runs | 2 rows with `metric` `capex` and that additions concept | unit |
| AC-38 | Any ESEF fixture (AC-13, AC-28, AC-37) | fetch runs | No row has `metric` `opex` and `market` `esef` | unit |
| AC-39 | Fixture S where each segment fact also carries `srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember` | fetch runs | `segments.jsonl` has the same 3 revenue rows as AC-1 | unit |

Must not change: non-dimensional facts, required rows, `skipped_dimensional` (AC-20); default `parse_ixbrl`
output (AC-21); company fetch status when the segment step finds nothing or fails (AC-16, AC-17).

`unit` rows are owed as `holdout` once `HOLDOUT_TOKEN` is set.
