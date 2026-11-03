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
- An existing link changing its classification, unless it was `other` or unclassified before and now contains a new
  sustainability or transition term.

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

to stderr, where `<total>` is `len(companies)` from `--universe`, the same count the unreachable line uses, and
`<cutoff> = (date.today().year - 1) - discovery_report_max_age_years`, computed in
`arp/cli/discovery.py` with the same `date.today()` the run used. The block comes after the unreachable block. One
line per stale company, in the order `run_store.read_results(run_id)` returns the rows (the order the unreachable
block already uses). Nothing is printed when no company is stale.

### Keywords (`arp/discovery/crawler.py`)

The existing `SUSTAINABILITY_REPORT` entry keeps its English terms unchanged. A second `SUSTAINABILITY_REPORT`
entry goes after the investor presentation entry, holding these terms:

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

A new entry `(DocType.TRANSITION_PLAN, (...))` goes **last** in `_DOC_TYPE_PATTERNS`, after the second
sustainability entry, with
`transition plan`, `transitionsplan`, `plan de transition`, `plan de transición`, `plan de transicion`,
`transitieplan`, `piano di transizione`, `omställningsplan`, `omstallningsplan`. Because every existing entry is checked
first, a link that already matched an existing class keeps it: "Sustainability report and transition plan" stays a
sustainability report and "Investor presentation: transition plan" stays an investor presentation, and so does "Investor presentation Nachhaltigkeitsbericht".

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
2. Default age limit 1 (in 2026 a 2024 or 2025 report is current, 2023 is stale), or 0 (only the expected year
   counts: in 2026 a 2025 report is current, 2024 is stale).
3. Read only ISO alpha-2 country codes for the local query (this spec), or also full country names. Either way it
   fires only once G1 keeps `country` in `enriched-universe`.

## Acceptance

All rows are `unit`: they need stand-in transports and a fixed date, which the e2e app cannot be given.

- **Pipeline rows** (AC-1 to AC-13, AC-21 to AC-24, AC-26 to AC-28, AC-30, AC-33) call
  `EdgarDocumentSource.fetch` with a stand-in transport, or `execute_discovery_run(..., search_client=<recording
  stand-in>, edgar_source=<stand-in>, esef_source=<stand-in>, transport=<stand-in>, today=date(2026, 11, 3))`.
  The stand-in transport serves each fixture PDF with the title metadata and first-page text the row gives.
- **CLI rows** (AC-14 to AC-16, AC-34) call `discover_run` in-process (Typer `CliRunner`), with
  `arp.cli.discovery.run_discovery` replaced by a stand-in that records the given `DiscoveryCompanyResult` rows in
  the run store in the given order, a `--universe` file listing exactly those rows' companies in the same order,
  and `date` in `arp.cli.discovery` patched so `date.today()` is 2026-11-03.
- In AC-23 to AC-28 and AC-33 the company is `Muster AG` with a supplied `website` whose stand-in homepage has no
  links, no CIK and no LEI, so the search client is used only for report queries.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Stand-in submissions: latest `10-K` with `reportDate` `2025-12-31`, `filingDate` `2026-02-20` | `EdgarDocumentSource.fetch` | The 10-K `SourceDocument.fiscal_period` is `2025-12-31` | unit |
| AC-2  | Same as AC-1 | `EdgarDocumentSource.fetch` | The 10-K title is `<name> 10-K (2026-02-20)` | unit |
| AC-3  | Latest `10-K` with `reportDate` `""`, `filingDate` `2026-02-20` | `EdgarDocumentSource.fetch` | `fiscal_period` is `2026-02-20` | unit |
| AC-4  | Submissions JSON without a `reportDate` key, latest `10-K` `filingDate` `2026-02-20` | `EdgarDocumentSource.fetch` | `fiscal_period` is `2026-02-20` | unit |
| AC-5  | Company with a CIK, AC-1's submissions | discovery run | The 10-K `DiscoveredDocument.reporting_year` is `2025` | unit |
| AC-6  | Company with an LEI, stand-in ESEF filing with period end `2025-03-31` | discovery run | That document's `reporting_year` is `2025` | unit |
| AC-7  | Company with a CIK and AC-1's submissions; homepage links one same-site PDF whose title metadata and first page read `Sustainability Report 2024` | discovery run | `latest_report_year` is `2025` | unit |
| AC-8  | Same as AC-7 | discovery run | `report_stale` is `false` | unit |
| AC-9  | No CIK, no LEI; search returns nothing; homepage links one same-site PDF whose title metadata and first page read `Sustainability Report 2023`; default setting | discovery run | `report_stale` is `true` | unit |
| AC-10 | Same as AC-9 with `Sustainability Report 2024` | discovery run | `report_stale` is `false` | unit |
| AC-11 | Same as AC-10, with `Settings(discovery_report_max_age_years=0)` passed to the run | discovery run | `report_stale` is `true` | unit |
| AC-12 | No CIK, no LEI; search returns nothing; homepage links `Q3 earnings call transcript` to a PDF whose first page reads `Earnings call transcript 2026`, and `Annual Report` to a PDF with no year in its title metadata or text. `documents_found` is exactly these two | discovery run | `latest_report_year` is `null` | unit |
| AC-13 | Same as AC-12 | discovery run | `report_stale` is `true` | unit |
| AC-14 | Stand-in rows: `acme` stale with latest 2023, then `beta2` current with latest 2025 | `arp discover run` | stderr contains the line `WARNING: 1/2 companies have no annual or sustainability report from 2024 or later:` directly followed by the line `  acme: latest 2023` | unit |
| AC-15 | Stand-in rows: only `beta`, stale, `latest_report_year` `null` | `arp discover run` | stderr contains the line `WARNING: 1/1 companies have no annual or sustainability report from 2024 or later:` directly followed by the line `  beta: latest none` | unit |
| AC-16 | Stand-in rows: two companies, both `report_stale` `false` | `arp discover run` | No stderr line contains `annual or sustainability report` | unit |
| AC-17 | Each term in the *Keywords* sustainability table, as link text `<Term> 2025` on `https://x.example/r.pdf` | `classify_link(url, text)` | Returns `sustainability_report` for every term | unit |
| AC-18 | Link text `Climate Transition Plan 2025`, url `https://x.example/ctp.pdf` | `classify_link` | Returns `transition_plan` | unit |
| AC-19 | Each transition term in *Keywords*, as link text `<Term>` on `https://x.example/t.pdf` | `classify_link` | Returns `transition_plan` for every term | unit |
| AC-20 | Link text `Sustainability report and transition plan`, url `https://x.example/s.pdf` | `classify_link` | Returns `sustainability_report` | unit |
| AC-21 | Homepage `https://acme.example/` with a same-site link `Climate Transition Plan` to `https://acme.example/ctp.pdf` | discovery run | `documents_found` has one document with `doc_type` `transition_plan` and url `https://acme.example/ctp.pdf` | unit |
| AC-22 | Same as AC-21 | discovery run | That document's `local_path` is under `<documents_dir>/<company_id>/transition_plan/` | unit |
| AC-23 | `Muster AG`, `country` `de` | discovery run | The recorded queries are exactly, in order: `"Muster AG" annual report 2025 filetype:pdf`, `"Muster AG" sustainability report 2025 filetype:pdf`, `"Muster AG" Nachhaltigkeitsbericht 2025 filetype:pdf` | unit |
| AC-24 | Same as AC-23; only the third query returns one hit, `https://muster.example/nb-2025.pdf` titled `Nachhaltigkeitsbericht 2025` | discovery run | `documents_found` contains url `https://muster.example/nb-2025.pdf` with `doc_type` `sustainability_report` | unit |
| ~~AC-25~~ | ~~Retired: AC-23 now gives the full ordered query list, which covers it.~~ | | | |
| AC-26 | `Muster AG`, `country` `Germany` | discovery run | The recorded queries are exactly, in order: `"Muster AG" annual report 2025 filetype:pdf`, `"Muster AG" sustainability report 2025 filetype:pdf` | unit |
| AC-27 | `Muster AG`, `country` `US` | discovery run | The recorded queries are exactly, in order: `"Muster AG" annual report 2025 filetype:pdf`, `"Muster AG" sustainability report 2025 filetype:pdf` | unit |
| AC-28 | `Muster AG`, `country` `FR`; the English sustainability query returns `https://x.example/sr-2025.pdf` titled `Sustainability Report 2025`; the local query raises in the stand-in | discovery run | `documents_found` contains url `https://x.example/sr-2025.pdf` with `doc_type` `sustainability_report` | unit |
| AC-29 | Links `Annual Report 2025`, `Sustainability Report 2025`, `Proxy statement`, `Q3 earnings call transcript`, `Investor presentation` | `classify_link` | Returns `10-K`, `sustainability_report`, `DEF-14A`, `earnings_transcript`, `investor_presentation` | unit |
| AC-30 | US company, `country` `US`, website `https://acme.example/`, no CIK, no LEI, default settings. Homepage links `Annual Report 2025` → `https://acme.example/ar-2025.pdf` and `Q3 earnings call transcript` → `https://acme.example/q3.pdf`. The annual query returns nothing; the sustainability query returns `https://cdn.example/acme-sustainability-report-2025.pdf` titled `Acme Sustainability Report 2025` | discovery run on this branch and on `main` | On both, the set of (`url`, `doc_type`) in `documents_found` is exactly {(`https://acme.example/ar-2025.pdf`, `10-K`), (`https://cdn.example/acme-sustainability-report-2025.pdf`, `sustainability_report`), (`https://acme.example/q3.pdf`, `earnings_transcript`)} | unit |
| AC-31 | The existing backend test suite on `main`. A grep of `backend/tests` found no test asserting an EDGAR document's `fiscal_period` or an EDGAR document's index header, so no test is expected to change | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |
| AC-32 | Link text `Investor presentation: transition plan`, url `https://x.example/ip.pdf` | `classify_link` | Returns `investor_presentation` | unit |
| AC-33 | `Muster AG`, `country` given as ` <code> ` (lower case, one space each side) for each code in the *Local-language search* table | discovery run | For each code, the last recorded query is `"Muster AG" <term> 2025 filetype:pdf` with that code's term from the table | unit |
| AC-34 | Stand-in rows in this order: `u` with `homepage_unreachable` `true`, `crawl_error` `timeout`, latest 2025, not stale; `b` stale, latest 2022; `a` stale, latest `null` | `arp discover run` | stderr ends with exactly these five lines in this order: `WARNING: 1/3 companies' homepage could not be reached (not the same as "no documents found"):`, `  u: timeout`, `WARNING: 2/3 companies have no annual or sustainability report from 2024 or later:`, `  b: latest 2022`, `  a: latest none` | unit |
| AC-35 | Link text `Investor presentation Nachhaltigkeitsbericht`, url `https://x.example/ipn.pdf` | `classify_link` | Returns `investor_presentation` | unit |

Must not change: English classifications (AC-29, AC-32, AC-35), US discovery with default settings (AC-30), EDGAR titles
(AC-2), the existing test suite (AC-31).
