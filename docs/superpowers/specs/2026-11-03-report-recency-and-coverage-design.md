# Report recency and coverage in discovery

Spec slug: `report-recency-and-coverage`. Gaps G6 and G7 of the universe-to-documents review
(https://claude.ai/artifact/FH7Q7fWJVUpxTRbjyKLx5a).

Status: draft.

## Why

Two weaknesses in document discovery reach the theme run unseen.

**Recency (G6).** EDGAR filings are dated by when they were filed, not by the period they cover:
`EdgarDocumentSource.fetch` sets `fiscal_period=filing_date` (`arp/ingestion/edgar.py:144`), so a 10-K for the
year ending 2025-12-31 filed on 2026-02-20 reads as "2026-02-20". SEC's submissions JSON already carries the period
in `filings.recent.reportDate`, unused today. Nothing checks whether a company's newest report is old: discovery
looks for `today.year - 1` (`arp/discovery/pipeline.py:47`) but records no verdict when it only finds an older one.

**Coverage (G7).** The crawler names annual reports in seven languages (`_ANNUAL_EXTRA`, `arp/discovery/crawler.py:37-38`)
but sustainability reports only in English (`crawler.py:29-32`), and the web search query is English only
(`arp/discovery/report_finding.py:26-31`). A German company's "Nachhaltigkeitsbericht 2025" is classified as nothing.
`DocType.TRANSITION_PLAN` exists (`arp/schemas/common.py:40`) but no keyword class produces it.

## Goals

1. An EDGAR document's `fiscal_period` is the period it reports on when SEC gives one.
2. Each discovery company result says the newest reporting year found among annual and sustainability reports,
   and whether that is too old, with the age limit in a setting.
3. `arp discover run` prints the stale companies, the same way it prints unreachable homepages today.
4. The crawler recognises sustainability reports in German, French, Spanish, Dutch, Italian, Swedish, Norwegian,
   Danish and Finnish, and transition plans.
5. For a company whose `country` is one of those languages' countries, the report search adds one query for the
   sustainability report in the local language.

## Non-goals

- Keeping more than the latest annual filing per form from EDGAR (prior-year comparison). See *Owner decisions*.
- `product_page` discovery. It needs a product-catalogue crawler, not report keywords.
- `research_paper` discovery. `arp/discovery/academic_search.py` is an arXiv q-fin client for strategy replication,
  not company research; company papers are a separate feature.
- Local-language queries for annual reports. The crawler already names them; search stays one English query.
- Queueing stale companies for review. That is G3 (`discovery-review-queue`); this spec only records the flag.
- Normalising hyphens, underscores or accents when matching keywords. Terms match exactly as listed, as today.
- Mapping full country names ("Germany") to languages. Only ISO 3166 alpha-2 codes are read.

## Anti-goals

- A change to which documents are downloaded for a US company with default settings, other than new
  `transition_plan` links.
- An existing English link changing its classification.

## Design

### EDGAR period (`arp/ingestion/edgar.py`)

In `fetch`, for the chosen filing index: `period = recent.get("reportDate", [...])[idx]`. `fiscal_period` is
`period` when it is a non-empty string, else `filing_date` (today's value). The title stays
`f"{company.name} {form} ({filing_date})"`. `fetch_latest_annual_original` is not touched.

Known effect: `arp/retrieval/index_text.py:17` puts `fiscal_period` in the index header line, so EDGAR chunks now
show the period end there instead of the filing date. Intended.

### Reporting year on EDGAR and ESEF discovered documents (`arp/discovery/pipeline.py`)

`_edgar_filings` and `_esef_documents` set `DiscoveredDocument.reporting_year = int(fiscal_period[:4])` when
`fiscal_period` starts with four digits, else `None`. Downloaded PDFs keep their `doc_check` year.

### Stale flag

New setting `discovery_report_max_age_years: int = 1` (`ge=0`, env `ARP_DISCOVERY_REPORT_MAX_AGE_YEARS`).

`DiscoveryCompanyResult` gains:

- `latest_report_year: int | None`: the highest `reporting_year` among `documents_found` with `doc_type` in
  {`10-K`, `sustainability_report`}; `None` when none has a year.
- `report_stale: bool`: `True` when `latest_report_year` is `None` or
  `latest_report_year < (today.year - 1) - discovery_report_max_age_years`.

With the default and `today` in 2026: 2024 or later is current, 2023 or no year is stale.

`arp discover run` prints, after the unreachable warning, when at least one company is stale:

```
WARNING: <n>/<total> companies have no annual or sustainability report from <cutoff> or later:
  <company_id>: latest <year or none>
```

to stderr, where `<cutoff> = (today.year - 1) - discovery_report_max_age_years`. One line per stale company, in run
order. Nothing is printed when no company is stale.

### Keywords (`arp/discovery/crawler.py`)

The `SUSTAINABILITY_REPORT` tuple keeps its English terms and adds:

| Language | Terms |
|---|---|
| de | `nachhaltigkeitsbericht`, `nichtfinanzieller bericht`, `nichtfinanzielle erklärung`, `nichtfinanzielle erklaerung` |
| fr | `rapport de durabilité`, `rapport de durabilite`, `rapport développement durable`, `rapport developpement durable`, `déclaration de performance extra-financière`, `declaration de performance extra-financiere` |
| es | `informe de sostenibilidad`, `memoria de sostenibilidad`, `estado de información no financiera`, `estado de informacion no financiera` |
| nl | `duurzaamheidsverslag`, `duurzaamheidsrapport` |
| it | `rapporto di sostenibilità`, `rapporto di sostenibilita`, `bilancio di sostenibilità`, `bilancio di sostenibilita`, `dichiarazione non finanziaria` |
| sv | `hållbarhetsrapport`, `hallbarhetsrapport`, `hållbarhetsredovisning`, `hallbarhetsredovisning` |
| no | `bærekraftsrapport`, `baerekraftsrapport` |
| da | `bæredygtighedsrapport`, `baeredygtighedsrapport` |
| fi | `vastuullisuusraportti`, `kestävyysraportti`, `kestavyysraportti` |

A new entry `(DocType.TRANSITION_PLAN, (...))` goes directly after the sustainability entry, with
`transition plan`, `transitionsplan`, `plan de transition`, `plan de transición`, `plan de transicion`,
`transitieplan`, `piano di transizione`, `omställningsplan`, `omstallningsplan`. Because the sustainability entry is
checked first, "Sustainability report and transition plan" stays a sustainability report.

Transition plans are same-site crawl candidates like earnings transcripts: they are kept by `select_candidates`
as "every other crawled type" (`report_finding.py:79`) and downloaded to `documents_dir/<company>/transition_plan/`.
Off-site links stay limited to annual and sustainability PDFs (`crawler.py:295`).

### Local-language search (`arp/discovery/report_finding.py`)

A map from ISO alpha-2 country (read case-insensitively, after `strip()`) to one local term:

| Countries | Term |
|---|---|
| DE, AT, CH | `Nachhaltigkeitsbericht` |
| FR | `rapport de durabilité` |
| ES | `informe de sostenibilidad` |
| NL | `duurzaamheidsverslag` |
| IT | `rapporto di sostenibilità` |
| SE | `hållbarhetsrapport` |
| NO | `bærekraftsrapport` |
| DK | `bæredygtighedsrapport` |
| FI | `vastuullisuusraportti` |

When `SUSTAINABILITY_REPORT` is searched and `company.country` maps to a term, `search_candidates` runs the English
query, waits `delay`, then runs `"<name>" <term> <expected_year> filetype:pdf`. Hits from both get
`doc_type=sustainability_report` and the same PDF and demotion filters. A failed local query gives no candidates for
that query only. Other countries, `None` and full names run exactly today's queries.

Interaction: identity's `enriched-universe` drops `country` today (G1), so this query only fires for universes that
reach discovery with `country` set until G1 lands.

## Left to the builder

Where the language map lives (a module constant is fine); test fixtures for the stand-in EDGAR, search and crawl
transports.

## Owner decisions

1. Keep only the latest EDGAR annual filing (this spec) or add a setting to keep the last N for prior-year
   comparison (adds one filing fetch per extra year per company).
2. Default age limit 1 year past the expected year (a 2023 report is stale in 2026), or 0 (only the expected year
   or the one before counts).

## Acceptance

`holdout` rows use stand-in HTTP transports for EDGAR, ESEF, search and crawl, and a fixed `today` of 2026-11-03. In rows AC-23 to AC-28 the company has a supplied `website`, no CIK and no LEI,
so the search client is used only for report queries.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Stand-in submissions: latest `10-K` with `reportDate` `2025-12-31`, `filingDate` `2026-02-20` | `EdgarDocumentSource.fetch` | The 10-K `SourceDocument.fiscal_period` is `2025-12-31` | holdout |
| AC-2  | Same as AC-1 | `EdgarDocumentSource.fetch` | The 10-K title is `<name> 10-K (2026-02-20)` | holdout |
| AC-3  | Latest `10-K` with `reportDate` `""`, `filingDate` `2026-02-20` | `EdgarDocumentSource.fetch` | `fiscal_period` is `2026-02-20` | holdout |
| AC-4  | Submissions JSON without a `reportDate` key | `EdgarDocumentSource.fetch` | `fiscal_period` equals the filing's `filingDate` | holdout |
| AC-5  | Company with a CIK, AC-1's submissions | discovery run | The 10-K `DiscoveredDocument.reporting_year` is `2025` | holdout |
| AC-6  | Company with an LEI, stand-in ESEF filing with period end `2025-03-31` | discovery run | That document's `reporting_year` is `2025` | holdout |
| AC-7  | Documents found: a 10-K with year 2025 and a sustainability PDF with year 2024 | discovery run | `latest_report_year` is `2025` | holdout |
| AC-8  | Same as AC-7 | discovery run | `report_stale` is `false` | holdout |
| AC-9  | Only a sustainability PDF with `reporting_year` 2023, default setting | discovery run | `report_stale` is `true` | holdout |
| AC-10 | Only a sustainability PDF with `reporting_year` 2024, default setting | discovery run | `report_stale` is `false` | holdout |
| AC-11 | Same as AC-10, `ARP_DISCOVERY_REPORT_MAX_AGE_YEARS=0` | discovery run | `report_stale` is `true` | holdout |
| AC-12 | Only an earnings transcript, and a 10-K PDF whose `reporting_year` is `None` | discovery run | `latest_report_year` is `null` | holdout |
| AC-13 | Same as AC-12 | discovery run | `report_stale` is `true` | holdout |
| AC-14 | Universe of 2; company `acme` stale with latest 2023, the other current | `arp discover run` | stderr contains the line `WARNING: 1/2 companies have no annual or sustainability report from 2024 or later:` followed by the line `  acme: latest 2023` | holdout |
| AC-15 | Universe of 1; a stale company with no year | `arp discover run` | stderr contains the line `  <company_id>: latest none` | holdout |
| AC-16 | Universe where no company is stale | `arp discover run` | stderr contains no line starting `WARNING:` with `annual or sustainability report` | holdout |
| AC-17 | Each term in the *Keywords* sustainability table, as link text `<Term> 2025` on `https://x.example/r.pdf` | `classify_link(url, text)` | Returns `sustainability_report` for every term | holdout |
| AC-18 | Link text `Climate Transition Plan 2025`, url `https://x.example/ctp.pdf` | `classify_link` | Returns `transition_plan` | holdout |
| AC-19 | Each transition term in *Keywords*, as link text `<Term>` on `https://x.example/t.pdf` | `classify_link` | Returns `transition_plan` for every term | holdout |
| AC-20 | Link text `Sustainability report and transition plan` | `classify_link` | Returns `sustainability_report` | holdout |
| AC-21 | Stand-in homepage with a same-site link `Climate Transition Plan` to a PDF | discovery run | `documents_found` has one document with `doc_type` `transition_plan` | holdout |
| AC-22 | Same as AC-21 | discovery run | That document's `local_path` is under `<documents_dir>/<company_id>/transition_plan/` | holdout |
| AC-23 | Company `country` `de`, name `Muster AG`, stand-in search client recording queries | discovery run | The recorded queries for sustainability are, in order, `"Muster AG" sustainability report 2025 filetype:pdf` and `"Muster AG" Nachhaltigkeitsbericht 2025 filetype:pdf` | holdout |
| AC-24 | Same as AC-23, the local query returns one PDF hit | discovery run | That hit is a candidate with `doc_type` `sustainability_report` | holdout |
| AC-25 | Same as AC-23 | discovery run | Exactly one recorded query contains `annual report` and none contains a local annual term | holdout |
| AC-26 | Company `country` `Germany` | discovery run | Exactly 2 queries are recorded: the English annual and the English sustainability query | holdout |
| AC-27 | Company `country` `US` | discovery run | Exactly 2 queries are recorded: the English annual and the English sustainability query | holdout |
| AC-28 | Company `country` `FR`; the local query raises in the stand-in | discovery run | The English sustainability query's hits are still candidates; the company result has no `crawl_error` from it | holdout |
| AC-29 | Links `Annual Report 2025`, `Sustainability Report 2025`, `Proxy statement`, `Q3 earnings call transcript`, `Investor presentation` | `classify_link` | Returns `10-K`, `sustainability_report`, `DEF-14A`, `earnings_transcript`, `investor_presentation` | holdout |
| AC-30 | Stand-in US company site and search hits with no transition-plan link, default settings | discovery run on this branch and on `main` | Same `documents_found` URLs and doc types | holdout |
| AC-31 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: English classifications (AC-29), US discovery with default settings (AC-30), EDGAR titles (AC-2),
the existing test suite (AC-31).
