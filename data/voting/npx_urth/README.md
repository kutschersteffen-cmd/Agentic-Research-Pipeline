# iShares MSCI World ETF (URTH): N-PX proxy votes

Proxy voting records of iShares MSCI World ETF (ticker URTH, SEC series S000035395, class
C000108746), registrant iShares, Inc. (CIK 930667, file no. 811-09102), from SEC Form N-PX in the
structured XML format. Fetched 2026-11-12 from SEC EDGAR.

| File | Period | Accession | Vote table (source) | Rows | Distinct issuers (CUSIP) |
|---|---|---|---|---|---|
| `urth_npx_2024-06-30.csv` | 07/01/2023-06/30/2024 | 0001021408-24-004974 (filed 2024-08-27) | https://www.sec.gov/Archives/edgar/data/930667/000102140824004974/proxyvote.xml | 22,026 | 1,445 |
| `urth_npx_2025-06-30.csv` | 07/01/2024-06/30/2025 | 0001438934-25-002318 (filed 2025-08-28) | https://www.sec.gov/Archives/edgar/data/930667/000143893425002318/BRDWLB_0000930667_2025.xml | 19,586 | 1,221 |
| `urth_npx_2026-06-30.csv` | 07/01/2025-06/30/2026 | 0001438934-26-002287 (filed 2026-08-28) | https://www.sec.gov/Archives/edgar/data/930667/000143893426002287/BRDWLB_0000930667_2026.xml | 20,529 | 1,287 |

Filing indexes: `https://www.sec.gov/Archives/edgar/data/930667/<accession without dashes>/index.json`.
iShares, Inc. files 3-7 N-PX accessions a year, each covering a group of series; for each year the
accession above is the only one whose `primary_doc.xml` header lists S000035395 / C000108746.

## How the files were made

Each vote table covers 10-41 series. Every `proxyTable` record carries a `voteSeries` element, so
only records tagged `S000035395` were kept (`fetch_npx.py` in this folder re-fetches them). The XML was streamed and not stored. Values are SEC
values as filed, only flattened; no type conversion.

One CSV row per `voteRecord`. A proposal whose shares were split (part FOR, part AGAINST) gives
several rows sharing the proposal fields; a proposal with no `voteRecord` gives one row with the
vote fields empty.

## Columns

| Column | SEC element | Meaning |
|---|---|---|
| period | `periodOfReport` | Reporting year end |
| accession | | N-PX accession number |
| issuer_name | `issuerName` | Company voted on |
| cusip, isin, figi | `cusip`, `isin`, `figi` | Security identifiers (`figi` is never filled in these filings) |
| meeting_date | `meetingDate` | Shareholder meeting date, MM/DD/YYYY |
| vote_description | `voteDescription` | Proposal text |
| other_vote_description | `otherVoteDescription` | Never filled here |
| vote_categories | `voteCategories/voteCategory/categoryType` | SEC category, several joined with `; ` |
| other_vote_category | `otherVoteCategory` | Never filled here |
| vote_source | `voteSource` | `ISSUER` (management proposal) or `SECURITY HOLDER` (shareholder proposal) |
| shares_voted | `proxyTable/sharesVoted` | Shares voted on the proposal in total |
| shares_on_loan | `sharesOnLoan` | Shares on loan, not voted |
| how_voted | `voteRecord/howVoted` | FOR, AGAINST, ABSTAIN, WITHHOLD, or a frequency (`ONE YEAR` / `1 YEAR`) |
| record_shares_voted | `voteRecord/sharesVoted` | Shares behind this `how_voted` |
| management_recommendation | `voteRecord/managementRecommendation` | FOR, AGAINST or NONE |
| for_against_management | *derived, not in the SEC schema* | `FOR` if how_voted equals management_recommendation, else `AGAINST`; empty when the recommendation is NONE or missing, or for frequency votes |
| vote_manager | `voteManager/otherManagers` | Manager serial number (21 = BlackRock Fund Advisors); empty in the 2024 filing |
| vote_series | `voteSeries` | Always S000035395 |

## Votes against management

Share of rows with `for_against_management` filled that are `AGAINST`: 2024 3.83% (827 / 21,576),
2025 4.16% (727 / 17,477), 2026 3.35% (679 / 20,258).

## Caveats

- `for_against_management` is computed here, not filed. Frequency votes (say-on-pay frequency) are
  left empty because their management recommendation is filed as FOR/AGAINST, not as a frequency.
- Rows with no vote record: 245 (2024), 2,020 (2025), 90 (2026). Most have `shares_voted` 0; in
  2025 many show shares but no `voteRecord`, which is how the filing reports them.
- Number formats differ by year as filed (`508531.000000` in 2024, integers later), and frequency
  votes read `ONE YEAR` in 2024 and `1 YEAR` later.
- Distinct issuers are counted by CUSIP; a few issuers appear under two name spellings.
