# Report finding: ESEF first, then search, then a crawl that reaches the reports

## Intent

Discovery should return each company's latest **annual report** and **sustainability report**. A live
test on 10 large European companies (2026-10-18) found them for only 2. A reconnaissance pass over the
same 10 sites (2026-10-19) showed why:

- 5 of 10 sites block every request from a cloud server (Akamai/Cloudflare, by IP, not by user agent).
- On the other 5 the report page is usually 1–2 clicks from the homepage, but the crawl loses it:
  - report pages carry many PDFs (BASF: ~200) and nothing picks the latest annual report;
  - PDFs often sit on another host (Siemens: a CDN; ASML: a brand-asset site), and the crawl drops
    every link off the company's own site;
  - some report pages are linked only from JavaScript menus (Siemens) and appear only in the sitemap.
- Report names vary: "BASF Report 2025", "Siemens Report", "Universal Registration Document 2025",
  "Geschäftsbericht".
- About 8 of 10 now put the sustainability statement inside the annual report (CSRD).
- 4 of 10 have a current ESEF annual filing on filings.xbrl.org (ASML, TotalEnergies, Unilever, Novo).
- DuckDuckGo's free HTML search answers every query from this cloud server with a bot challenge.

The owner decided: check ESEF first; then search for the PDF directly with DuckDuckGo (no paid search
API); keep the site crawl as the route that works on a cloud server. ARP must work fully on a cloud
server without search; search is a bonus where it answers.

## Goals

1. When a company has a current ESEF annual filing, use it as the annual report and don't look for an
   annual-report PDF.
2. Ask DuckDuckGo for the annual-report and sustainability-report PDFs, also when the company's site
   cannot be crawled. A bot challenge or an error never stops the company.
3. Start the crawl from report pages listed in the site's sitemap, not only from the homepage.
4. Keep annual- and sustainability-report PDF links that point to another host.
5. Recognise more annual-report names, and download only the best 2 annual-report and the best 2
   sustainability-report candidates per company (ranking in §5).

## Non-goals

- Fetching pages from sites that block us: no browser automation, no proxies, no residential IPs.
- Paid search APIs (Serper, Brave, Google).
- Back catalogues: only the latest report year (and the year before as a fallback) matters.
- Reducing downloads of other document types (presentations, transcripts, `other` PDFs): they behave
  as today, including that off-site links of those types are still dropped.
- Treating an EDGAR 10-K/20-F as a reason to skip the annual-report search.
- National registries and OCR.

## Anti-goals (a failure even if it works)

- A cloud run depends on DuckDuckGo answering.
- The crawl gets less polite: it ignores robots.txt, skips the request delay, or downloads unbounded
  sitemaps.
- Another company's report is accepted without review: every downloaded PDF still goes through the PDF
  check, and `none`/`no_text` still count toward the review count.
- A company with a current ESEF filing loses its separate sustainability report.

## Current state (what this builds on)

- `arp/discovery/pipeline.py::_discover_for_company`: EDGAR filings by CIK, then the homepage (supplied,
  Wikidata, or search) with the homepage check; if there is no usable homepage it returns early with
  only the EDGAR documents. Otherwise `crawl_for_documents`, `download_documents`, change detector.
- ESEF: `EsefDocumentSource.fetch` (`arp/ingestion/esef.py`) returns the latest filing by `period_end`
  as one `ANNUAL_REPORT_10K` document (it downloads the package). `execute_discovery_run` polls it in
  the worker **after** the crawl via `poll_esef_filings`, only when `settings.esef_enabled`.
- `arp/discovery/crawler.py`: same-site BFS from the root, depth `discovery_max_crawl_depth` (2),
  `discovery_max_pages_per_company` (40) pages, `discovery_request_delay_seconds` (1.0) between
  requests, robots.txt respected, SSRF hook on every request. Links are classified by keyword
  (`_DOC_TYPE_PATTERNS`); links off the root's site are dropped before classification.
- `DuckDuckGoSearchClient.search` returns `[]` and logs a warning on a bot challenge (HTTP 202).
- `download_documents` runs the PDF check on every `.pdf` and handles conditional GET.

## Interface (what the acceptance tests drive)

- Entry point: `execute_discovery_run(run_id, companies, *, settings, run_store, doc_types=None,
  search_client=None, esef_source=None, edgar_source=None, transport=None, today=None, sleep=None)`.
  New keywords: `today: datetime.date | None` (default `date.today()`) and `sleep` (an async callable
  taking seconds, default `asyncio.sleep`), used for every delay this spec adds (search queries,
  sitemap requests) and by the crawler's existing delay.
- `transport` reaches every HTTP request discovery makes: ESEF index and package, sitemaps, crawl,
  downloads. `esef_source=None` builds one from settings with that transport.
- Per-company results are read from `run_store.read_results(run_id)` (one `DiscoveryCompanyResult` JSON
  per company: `documents_found` with `url`, `doc_type`, `company_match`; `homepage_check`); run counts
  from `run_store.load_manifest(run_id)` (`failed_count`, `review_count`).
- Within `documents_found`, documents of each type appear in rank order (§5).

## Design

### Expected report year and matching rules

- `expected_year = today.year - 1`.
- **Year in a text:** a 4-digit number `20xx` not preceded or followed by a digit (so `FY2025`,
  `_2025.pdf` count; `120256` does not).
- **Words:** text is lowercased and split into tokens on every non-alphanumeric character. A demotion
  word matches a whole token (`tax` does not match `taxonomy`); `half-year`/`fact sheet` match the two
  consecutive tokens.
- **"text" of a link** = link text + the URL's filename.

### 1. ESEF first

- When `settings.esef_enabled` and the company has an LEI, the ESEF source is called first, before
  search, homepage resolution and crawl. Its document joins `documents_found` and is recorded by the
  change detector. The separate poll after the crawl is removed: one filings-list request per company
  per run.
- **Current** = `period_end >= today − 548 days` (with `today` 2026-10-19: 2025-04-19 is current,
  2025-04-18 is not).
- With a current filing: no annual-report query is sent and annual-report candidates are not
  downloaded. Sustainability search and candidates run as normal.
- Older filing, no filing, an index error, or no LEI: the ESEF document (if any) is kept; annual-report
  search and candidates run as normal. The ESEF document never counts toward the "best 2" (§5).
- EDGAR (by CIK) runs as today, independent of ESEF.

### 2. DuckDuckGo search

- Runs when a `search_client` is given (the pipeline's default is `DuckDuckGoSearchClient`), after
  ESEF and before homepage resolution, **whether or not the site can be crawled later**.
- Queries, in this order, exactly: `"<company.name>" annual report <expected_year> filetype:pdf`
  (skipped with a current ESEF filing) and `"<company.name>" sustainability report <expected_year>
  filetype:pdf`. Each asks for 5 results; the `.pdf` filter is applied to those 5. A `sleep` of
  `discovery_request_delay_seconds` separates the two queries.
- A result is a candidate when its URL path (query string ignored) ends in `.pdf`, case-insensitive,
  and it contains no demotion word. Its type is the query's; its link text is the result title.
- Any exception or empty list means no candidates (logged at info).
- Search candidates are downloaded even when the homepage is missing, rejected or unreachable. The
  early returns in `_discover_for_company` keep the ESEF document and the downloaded search candidates.

### 3. Sitemap seeding

- Before the BFS: read `Sitemap:` lines from the root's robots.txt (via `_RobotsCache`). Only when
  there is none, try `<root origin>/sitemap.xml`. A sitemap URL whose registrable domain differs from
  the root's is ignored.
- A sitemap index is followed one level: at most 5 child sitemaps; children with an `en` token in their
  path (tokens split on non-alphanumerics, e.g. `/sitemap-en.xml`, `/en/sitemap.xml`; not
  `/sitemap-energy.xml`) first, the rest in listed order. A child that is itself an index is not
  followed.
- Every sitemap request obeys robots.txt and is preceded by a `sleep` of
  `discovery_request_delay_seconds`, goes through the SSRF hook, and does **not** count toward the page
  limit.
- Size cap: 15,000,000 bytes, by `Content-Length` or bytes read (after gzip decompression for `.gz`
  sitemaps). Over the cap or unparseable XML: that sitemap is skipped; the company carries on.
- Seeds: same-site URLs not ending in `.pdf` whose path (lowercased) contains any of `annual-report`,
  `annual_report`, `annualreport`, `/reports`, `reporting`, `/investor`, `sustainab`,
  `integrated-report`, `geschaeftsbericht`, `nachhaltigkeit`. At most 10: shortest path first, ties in
  listed order.
- Seeds enter the BFS queue at depth 1, after the root. They count toward the page limit, obey
  robots.txt and the request delay.

### 4. Report PDFs on other hosts

- A link on a crawled page that points off the root's site is a candidate only when its URL path ends
  in `.pdf` and it classifies as `ANNUAL_REPORT_10K` or `SUSTAINABILITY_REPORT`. It is never queued
  as a page. All other off-site links are dropped as today.

### 5. Annual-report names and ranking

- `_DOC_TYPE_PATTERNS` for `ANNUAL_REPORT_10K` gains the phrases `integrated report`, `universal
  registration document`, `annual review`, `geschäftsbericht`, `geschaeftsbericht`, `rapport annuel`,
  `informe anual`, `jaarverslag`, `årsrapport` (matched as today, on link text + URL).
- **Fallback:** a `.pdf` link that matches no pattern, whose text contains the substring `report` and a
  year from `expected_year − 1` to `expected_year`, is `ANNUAL_REPORT_10K`.
- **Demotion words** (whole tokens): `quarter`, `quarterly`, `q1`, `q2`, `q3`, `q4`, `half-year`,
  `interim`, `factsheet`, `fact sheet`, `presentation`, `transcript`, `remuneration`, `tax`, `summary`,
  `extract`. A link containing one is never typed annual or sustainability by the new phrases, the
  fallback, or search. Matches by the patterns that exist on `main` are unchanged.
- **Ranking** within `ANNUAL_REPORT_10K` and within `SUSTAINABILITY_REPORT` (crawl and search
  candidates together, ESEF excluded), by:
  1. year bucket: `expected_year` in the text → 0; `expected_year − 1` → 1; otherwise 2;
  2. source: same-site crawl → 0; off-site crawl → 1; search → 2;
  3. discovery order.
  Only the first 2 of each type are downloaded; the rest receive no request. Other types are untouched.

## Constraints

- Every new request goes through `ssrf_guard_request_hook`, with the discovery user agent.
- No new settings; limits above are module constants.
- The checks in `.claude/CLAUDE.md` pass. No existing test is deleted or weakened; a test whose
  expectation this spec changes (the poll after the crawl) is listed in the PR.
- Rows are `unit`. If `HOLDOUT_TOKEN` is set when this is built, the anti-goal rows (AC-13, AC-18,
  AC-20, AC-29, AC-41, AC-45) are owed as `holdout`.

## Left to the builder

- Where the ranking and classification live (crawler, or a small `report_rank.py`).
- Sitemap XML parsing (stdlib `xml.etree` with the size cap, or `lxml`).

## Owner decision (2026-10-19)

- `esef_enabled` defaults to **true** (it was `False` on `main`). `ARP_ESEF_ENABLED=false` still turns
  it off. The same setting also adds the ESEF source to the document registry the API and CLI build
  (`arp/api/deps.py`, `arp/cli/_shared.py`), so those now include ESEF by default too.
- `tests/test_esef.py` asserts the old default (`assert settings.esef_enabled is False`); that line
  changes to `True` and is listed in the PR. Any test that relied on ESEF being off by default sets
  `esef_enabled=False` explicitly.

## Acceptance

**Fixtures** (all HTTP through one mock transport; `today` = 2026-10-19 so `expected_year` = 2025;
`esef_enabled` true; `discovery_request_delay_seconds` = 0.2; `sleep` is a recorder that returns at once;
the real SSRF hook is replaced by a no-op except in AC-29):

- Company **W**: `company_id` `w`, name `Testwerke AG`, LEI `5299009TESTWERKE0063`, supplied website
  `https://www.testwerke.de/`, no CIK.
- **ESEF-current**: the index lists one filing for W's LEI, `period_end` `2025-12-31`, package URL
  `https://filings.xbrl.org/w/2025.zip` (a valid ESEF package naming Testwerke AG).
- **ESEF-old**: the same with `period_end` `2024-12-31`, package `https://filings.xbrl.org/w/2024.zip`.
- **ESEF-none**: the index returns an empty list for W's LEI. Rows say which ESEF fixture applies.
- **Search**: a fake search client that records every query; it returns `[]` unless a row scripts it.
- **Site**: `https://www.testwerke.de/` links nothing unless a row says so; robots.txt allows all and
  lists no sitemap; `/sitemap.xml` returns 404.
- PDFs are 3-page PDFs whose page 1 says `Testwerke AG Annual Report 2025`, unless a row says otherwise.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | W; ESEF-current | discovery run | `documents_found` contains a document with `doc_type` `"10-K"` and `url` `https://filings.xbrl.org/w/2025.zip` | unit |
| AC-2  | W; ESEF-current | discovery run | the search client received exactly 1 query, `"Testwerke AG" sustainability report 2025 filetype:pdf` | unit |
| AC-3  | W; ESEF-current; the homepage links `/ar-2025.pdf` with text `Annual Report 2025` | discovery run | `/ar-2025.pdf` receives 0 requests | unit |
| AC-4  | W; ESEF-current; the homepage links `/sustainability-report-2025.pdf` with text `Sustainability Report 2025` | discovery run | `documents_found` contains `https://www.testwerke.de/sustainability-report-2025.pdf` | unit |
| AC-5  | W; ESEF-old | discovery run | `documents_found` contains a document with `url` `https://filings.xbrl.org/w/2024.zip` | unit |
| AC-6  | W; ESEF-current | discovery run | the ESEF index received exactly 1 filings-list request for W's LEI | unit |
| AC-7  | W; the ESEF index returns HTTP 500 | discovery run | manifest `failed_count` is 0 | unit |
| AC-8  | W without LEI | discovery run | the ESEF index receives 0 requests | unit |
| AC-9  | W; ESEF-current; `esef_enabled` false | discovery run | the ESEF index receives 0 requests | unit |
| AC-10 | W; ESEF-none; for the annual query search returns `https://www.testwerke.de/about` and `https://cdn.example.net/files/TW-AR-2025.pdf` | discovery run | `documents_found` contains `https://cdn.example.net/files/TW-AR-2025.pdf` with `doc_type` `"10-K"` | unit |
| AC-11 | W; ESEF-none; the search client raises `httpx.ConnectError` on every query; the homepage links `/ar-2025.pdf` with text `Annual Report 2025` | discovery run | `documents_found` contains `https://www.testwerke.de/ar-2025.pdf` | unit |
| AC-12 | W; ESEF-none; search returns `https://www.testwerke.de/ar-2025.pdf` and the homepage also links it with text `Annual Report 2025` | discovery run | `/ar-2025.pdf` receives exactly 1 request | unit |
| AC-13 | W; ESEF-none; search returns `https://other.example.org/otherco-ar-2025.pdf`, whose text names `Otherco plc` only | discovery run | that document is in `documents_found` with `company_match` `none` | unit |
| AC-14 | W; ESEF-none; robots.txt has `Sitemap: https://www.testwerke.de/sm.xml`, a sitemap listing `/about.html` and `/investors/annual-report.html`; that page links `/ar-2025.pdf` with text `Annual Report 2025` | discovery run | `documents_found` contains `https://www.testwerke.de/ar-2025.pdf` | unit |
| AC-15 | as AC-14, but robots.txt lists no sitemap and `/sitemap.xml` serves that sitemap | discovery run | `documents_found` contains `https://www.testwerke.de/ar-2025.pdf` | unit |
| AC-16 | W; ESEF-none; robots.txt points to an index listing `/sm-1.xml` … `/sm-7.xml` (each an empty urlset) | discovery run | `/sm-1.xml` … `/sm-5.xml` are requested in that order; `/sm-6.xml` and `/sm-7.xml` receive 0 requests | unit |
| AC-17 | W; ESEF-none; robots.txt points to an index listing `/sitemap-de.xml`, `/sitemap-energy.xml`, `/sitemap-en.xml` | discovery run | the child sitemaps are requested in the order `/sitemap-en.xml`, `/sitemap-de.xml`, `/sitemap-energy.xml` | unit |
| AC-18 | W; ESEF-none; robots.txt's sitemap responds with `Content-Length: 20000000` and lists `/reports/a.html` | discovery run | `/reports/a.html` receives 0 requests | unit |
| AC-19 | W; ESEF-none; a sitemap listing `/reports/r1.html` … `/reports/r15.html` in that order | discovery run | `/reports/r1.html` … `/reports/r10.html` are requested; `r11` … `r15` receive 0 requests | unit |
| AC-20 | as AC-14, but robots.txt also has `Disallow: /investors/` | discovery run | `/investors/annual-report.html` receives 0 requests | unit |
| AC-21 | W; ESEF-none; the homepage links `https://assets.cdn.example/r/ar.pdf` with text `Annual Report 2025` | discovery run | that URL is in `documents_found` with `doc_type` `"10-K"` | unit |
| AC-22 | W; ESEF-none; the homepage links `https://partner.example.com/page.html` and `https://partner.example.com/brochure.pdf` with text `Brochure` | discovery run | neither URL receives a request | unit |
| ~~AC-23~~ | — | — | Retired before approval: three behaviours in one row; replaced by AC-48 | — |
| AC-24 | W; ESEF-none; the homepage links, in this order, `/ar-2024.pdf` (`Annual Report 2024`), `/ar-2023.pdf` (`Annual Report 2023`), `/ar-2025.pdf` (`Annual Report 2025`) | discovery run | the `"10-K"` documents in `documents_found` are exactly `/ar-2025.pdf` then `/ar-2024.pdf` | unit |
| AC-25 | as AC-24 | discovery run | `/ar-2023.pdf` receives 0 requests | unit |
| AC-26 | W; ESEF-current; the homepage links `/sr-2023.pdf`, `/sr-2025.pdf`, `/sr-2024.pdf`, each with text `Sustainability Report <year>` | discovery run | the `sustainability_report` documents are exactly `/sr-2025.pdf` then `/sr-2024.pdf` | unit |
| AC-27 | W; ESEF-none; the homepage links `/ip-2023.pdf`, `/ip-2024.pdf`, `/ip-2025.pdf`, each with text `Investor Presentation <year>` | discovery run | all 3 are in `documents_found` with `doc_type` `"investor_presentation"` | unit |
| AC-28 | W; ESEF-none | discovery run | `homepage_check` is `null` | unit |
| AC-29 | W; ESEF-none; real SSRF hook; search returns `http://169.254.169.254/ar-2025.pdf`; robots.txt's sitemap lists `http://169.254.169.254/investors/`; the homepage links `http://169.254.169.254/sr-2025.pdf` with text `Sustainability Report 2025` | discovery run | `failed_count` is 0 and no URL under `http://169.254.169.254/` is in `documents_found` | unit |
| AC-30 | W; ESEF-none | discovery run | the `sleep` recorder holds a call of 0.2 between the two search queries | unit |
| AC-31 | W; ESEF-old | discovery run | the search client received `"Testwerke AG" annual report 2025 filetype:pdf` | unit |
| AC-32 | W; the ESEF index returns HTTP 500 | discovery run | the search client received the annual-report query | unit |
| AC-33 | W; ESEF-current; `esef_enabled` false | discovery run | the search client received the annual-report query | unit |
| AC-34 | as AC-10 | discovery run | `https://www.testwerke.de/about` receives 0 requests | unit |
| AC-35 | as AC-11 | discovery run | `failed_count` is 0 | unit |
| AC-36 | as AC-13 | discovery run | manifest `review_count` is 1 | unit |
| AC-37 | as AC-14 | discovery run | `/about.html` receives 0 requests | unit |
| AC-38 | as AC-18 | discovery run | `failed_count` is 0 | unit |
| AC-39 | W; ESEF-none | discovery run | the search client received exactly 2 queries, in order `"Testwerke AG" annual report 2025 filetype:pdf`, `"Testwerke AG" sustainability report 2025 filetype:pdf` | unit |
| AC-40 | W; ESEF-none; for the annual query search returns 7 results, all `.pdf`, the 6th being `https://x.example/f6.pdf` | discovery run | the search client was asked for 5 results per query (`max_results` 5) and `https://x.example/f6.pdf` receives 0 requests | unit |
| AC-41 | W; ESEF-none; search returns `https://x.example/A.PDF`, `https://x.example/b.pdf?dl=1`, `https://x.example/c.pdf.html` for the annual query | discovery run | `A.PDF` and `b.pdf?dl=1` are requested; `c.pdf.html` receives 0 requests | unit |
| AC-42 | W; ESEF-none; `search_client` none, pipeline built without search | discovery run | `failed_count` is 0 | unit |
| AC-43 | W; ESEF-none; the homepage returns HTTP 403; search returns `https://www.testwerke.de/ar-2025.pdf` for the annual query | discovery run | `documents_found` contains `https://www.testwerke.de/ar-2025.pdf` | unit |
| AC-44 | W; ESEF-current; the homepage returns HTTP 403 | discovery run | `documents_found` contains `https://filings.xbrl.org/w/2025.zip` | unit |
| AC-45 | W; ESEF-none; search returns `https://www.testwerke.de/scan-2025.pdf`, a PDF with no text layer | discovery run | that document has `company_match` `no_text` and manifest `review_count` is 1 | unit |
| AC-46 | W; ESEF filing `period_end` `2025-04-19` | discovery run | the search client received only the sustainability query | unit |
| AC-47 | W; ESEF filing `period_end` `2025-04-18` | discovery run | the search client received the annual-report query | unit |
| AC-48 | W; ESEF-none; nine separate runs, each with one homepage link `/x.pdf` whose text is one of the 9 names in AC-23 | discovery run | each run's `documents_found` contains `/x.pdf` with `doc_type` `"10-K"` | unit |
| AC-49 | W; ESEF-none; the homepage links `/Testwerke_Report_FY2025.pdf` with text `Testwerke Report` | discovery run | it is in `documents_found` with `doc_type` `"10-K"` | unit |
| AC-50 | W; ESEF-none; the homepage links `/Testwerke_Report_2022.pdf` with text `Testwerke Report` | discovery run | it is in `documents_found` with `doc_type` `"other"` | unit |
| AC-51 | W; ESEF-none; sixteen separate runs, each with one homepage link `/r.pdf` whose text is `Report 2025 <word>` for one demotion word | discovery run | in each run `/r.pdf` has a `doc_type` other than `"10-K"` | unit |
| AC-52 | W; ESEF-none; the homepage links `/taxonomy-report-2025.pdf` with text `Taxonomy Report 2025` | discovery run | it has `doc_type` `"10-K"` | unit |
| AC-53 | W; ESEF-none; search returns `https://www.testwerke.de/ar-2024.pdf` for the annual query; the homepage links `/ar-2025.pdf` with text `Annual Report 2025` | discovery run | the `"10-K"` documents are exactly `/ar-2025.pdf` then `/ar-2024.pdf` | unit |
| AC-54 | W; ESEF-none; search returns `https://cdn.example.net/ar-2025.pdf`; the homepage links `/ar-2025-a.pdf` and `/ar-2025-b.pdf`, each with text `Annual Report 2025` | discovery run | the `"10-K"` documents are exactly `/ar-2025-a.pdf` then `/ar-2025-b.pdf`; `https://cdn.example.net/ar-2025.pdf` receives 0 requests | unit |
| AC-55 | W; ESEF-none; robots.txt lists `Sitemap: https://www.testwerke.de/sm.xml` and `/sitemap.xml` also exists | discovery run | `/sitemap.xml` receives 0 requests | unit |
| AC-56 | W; ESEF-none; robots.txt points to an index whose child `/sm-a.xml` is itself an index listing `/sm-a1.xml` | discovery run | `/sm-a1.xml` receives 0 requests | unit |
| AC-57 | W; ESEF-none; robots.txt lists `Sitemap: https://other.example.com/sm.xml` | discovery run | `https://other.example.com/sm.xml` receives 0 requests | unit |
| AC-58 | W; ESEF-none; a sitemap with 10 seed URLs; every page on the site links 5 new same-site pages | discovery run | the site receives exactly 40 page requests (sitemap and robots.txt requests excluded) | unit |
| AC-59 | W; ESEF-none; robots.txt's sitemap is served without `Content-Length` and its body exceeds 15,000,000 bytes | discovery run | no URL it lists is requested and `failed_count` is 0 | unit |
| AC-60 | W; ESEF-none; robots.txt's sitemap body is `not xml` | discovery run | `failed_count` is 0 | unit |
| AC-61 | W; ESEF-none; robots.txt's sitemap is `/sm.xml.gz`, a gzip of a sitemap listing `/investors/annual-report.html` (which links `/ar-2025.pdf`, `Annual Report 2025`) | discovery run | `documents_found` contains `https://www.testwerke.de/ar-2025.pdf` | unit |
| AC-62 | as AC-14 | discovery run | every sitemap request and every seed request is preceded by a `sleep` call of 0.2 in the recorder | unit |
| AC-63 | W; ESEF-current; a second run with the same filing | discovery run | the second run's `new_events` for W is empty | unit |
| AC-64 | W with CIK `123`; ESEF-current; a fake EDGAR source | discovery run | the EDGAR source received one fetch for W | unit |

| AC-65 | — | `Settings()` with no environment override | `esef_enabled` is `True` | unit |

Must not change: other document types are downloaded as today (AC-27); a supplied website is not
checked (AC-28); every PDF still goes through the PDF check and review routing (AC-13, AC-36, AC-45);
robots.txt is respected (AC-20); EDGAR still runs (AC-64); the full backend suite passes.
