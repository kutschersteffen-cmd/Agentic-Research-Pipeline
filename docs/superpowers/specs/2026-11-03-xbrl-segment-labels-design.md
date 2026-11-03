# XBRL segment labels from the filing's label file

Status: approved by owner 2026-11-03. Builds on the segment specs (PRs #302, #303, #312, #317).

## Why

Today `segment` is derived from the member name: `aapl:WearablesHomeandAccessoriesMember` becomes
"Wearables Homeand Accessories", `ko:A.PacificMember` becomes "A.Pacific". Every SEC filing folder also holds
the filer's label linkbase (`<prefix>-<date>_lab.xml`) with the company's own wording. In Apple's FY2025 10-K:
`aapl_WearablesHomeandAccessoriesMember` has the standard label "Wearables, Home and Accessories [Member]".

## Decisions

| Topic | Decision |
|---|---|
| Scope | SEC filings (10-K, 20-F, 40-F). ESEF keeps today's derived names. |
| Fetch | When the annual report is stored, also download the filing folder's `index.json` and the one file ending `_lab.xml`, and store it next to the report as `labels-<accession>.xml`. If the index lists more than one `_lab.xml` file, the first in index order is used. If the index has no such file or the download fails, nothing is stored and the company's status does not change. |
| Which label | The label resource with role `http://www.xbrl.org/2003/role/label` and `xml:lang` starting `en`, linked to the member's concept. An exact `en-US` label wins; otherwise the first `en*` label in file order. |
| Cleaning | Strip a trailing ` [Member]`, then a trailing ` Segment` (case-insensitive), then surrounding whitespace. |
| Field | `segment` holds the cleaned label. A new field `segment_source` is `label` or `derived`. |
| Fallback | Standard members (`us-gaap:`, `srt:`, `ifrs-full:`, `country:`) and any member without a label in the file keep today's derived name with `segment_source: "derived"`. |

## Non-goals

- Labels for ESEF filings.
- Labels in languages other than English. Terse or verbose label roles.
- Labels for standard-taxonomy members (would need the official taxonomy label files).

## Acceptance

Fixture L: Fixture S of the segment spec (members `x:AlphaSegmentMember`, `x:BetaMember`, `x:GammaSegmentMember`),
plus a filing-folder `index.json` listing `x-20251231_lab.xml`, whose standard English labels are
`Alpha, Beta & Co Segment [Member]` for `x_AlphaSegmentMember` and `Beta Products [Member]` for `x_BetaMember`
(no label for Gamma).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture L | `arp xbrl fetch` runs | The Alpha row has `segment` `Alpha, Beta & Co` and `segment_source` `label` | unit |
| AC-2 | Fixture L | fetch runs | The Beta row has `segment` `Beta Products` and `segment_source` `label` | unit |
| AC-3 | Fixture L | fetch runs | The Gamma row has `segment` `Gamma` and `segment_source` `derived` | unit |
| AC-4 | Fixture L | fetch runs | A file `labels-<accession>.xml` is stored in the company's folder | unit |
| AC-5 | Fixture L where the label file also has a German (`de`) label `Alpha DE [Member]` and a terse-role label `Alpha [Member]` for Alpha | fetch runs | The Alpha row's `segment` is still `Alpha, Beta & Co` | unit |
| AC-6 | Fixture L with `index.json` listing no `_lab.xml` file | fetch runs | All 3 rows have `segment_source` `derived`; company status `ok` | unit |
| AC-7 | Fixture L where the label download returns HTTP 404 | fetch runs | All 3 rows have `segment_source` `derived`; company status `ok` | unit |
| AC-8 | Fixture L plus a geography fact on member `country:US`, and the label file has a standard English label `United States [Member]` for `country_US` | fetch runs | That row has `segment` `US` and `segment_source` `derived` | unit |
| AC-9 | An ESEF fixture with segment rows | fetch runs | Every row has `segment_source` `derived` | unit |
| AC-10 | Fixture L stored | `arp xbrl segments s1` | The Alpha line shows `Alpha, Beta & Co` | unit |
| AC-12 | Fixture L where Alpha has an `en` label `Alpha One [Member]` first and an `en-US` label `Alpha Two [Member]` second | fetch runs | The Alpha row's `segment` is `Alpha Two` | unit |
| AC-13 | Fixture L with `index.json` listing `x-20251231_lab.xml` then `y-20251231_lab.xml` (the second has `Alpha Wrong [Member]`) | fetch runs | The Alpha row's `segment` is `Alpha, Beta & Co` | unit |
| AC-14 | Fixture L where Beta's label is `Delta segment [Member]` | fetch runs | The Beta row's `segment` is `Delta` | unit |
| AC-11 | The existing XBRL, ESEF and segment test files | run | They pass. The only edits allowed add `segment_source` to expected row literals, and each edit is listed in the PR | unit |

Must not change: company fetch status when the label file is missing or fails (AC-6, AC-7); existing tests (AC-11).

`unit` rows are owed as `holdout` once `HOLDOUT_TOKEN` is set.
