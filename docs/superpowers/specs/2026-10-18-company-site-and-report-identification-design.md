# Company website and report identification: identifiers first, checked before trusted

## Intent

Discovery finds a company's website and crawls it for reports. Today the website comes from the universe
file, from Wikidata by CIK, or from the first DuckDuckGo hit, and nothing checks that the site or the
downloaded files belong to the company. For EU companies with no CIK this means the first search result
decides everything, and a wrong homepage silently fills the run with another company's reports.

This spec brings in the good ideas from an outside script (`report_harvester.py`, reviewed 2026-10-18) and
fixes what it got wrong. The approach: look things up by identifier (LEI, ISIN, CIK) before searching by
name, check every website that came from a search, and check that each downloaded PDF names the company.
The LLM keeps its single adjudicate call. This adds no agent loop.

## Goals

1. Find the website from LEI or ISIN, not only from CIK.
2. Fill in a missing LEI from the ISIN (GLEIF), so ISIN-only companies resolve by identifier.
3. Give the identity adjudicator GLEIF name matches as well as EDGAR ones, so EU companies known only by
   name can resolve to an LEI.
4. Score a homepage before crawling it: reject aggregator sites and other companies' sites.
5. Mark each downloaded PDF with whether it names the company, and send the ones that don't to review.
6. Fetch 20-F and 40-F annual reports for foreign SEC filers. Stop a non-US ticker from resolving to a
   US company's CIK.
7. Don't download an unchanged report again: send the stored ETag and Last-Modified back, and reuse the
   stored copy on `304 Not Modified`.
8. Don't announce a known file as new just because its URL changed: the same bytes at a new URL are
   recorded as an alias, with no "new document" event.

## Non-goals

- An agent loop for the companies that still have no website or report. That is a follow-up spec, once
  this one's results show how many are left.
- OCR or an image model for PDFs without a text layer (they go to review instead).
- National registries (Unternehmensregister, the FCA's National Storage Mechanism, EDINET), the planned
  EU access point ESAP, and OpenFIGI.
- Picking reports by fiscal year. Discovery keeps fetching the latest filing.
- An LLM check of downloaded documents. The checks here are deterministic.
- Checking HTML, XHTML or ZIP downloads. Only PDFs get the document check.
- Paid search APIs (Serper and similar).
- Recognising the same report in different bytes (language editions, web vs print, re-saved PDFs).
  `doc_identity`'s report-year grouping keeps handling those as versions, as on `main`.

## Anti-goals (a failure even if it works)

- A real report gets dropped. A document that fails the check is kept, stored and listed. It is only
  flagged.
- A supplied website or CIK gets second-guessed. A supplied website is never checked or replaced, and
  a supplied CIK is never replaced. In the identity run, a company with a supplied website or CIK makes
  no Wikidata request. A homepage that discovery *derives* (Wikidata, search) is always checked, even
  when the company has a supplied CIK.
- An adjudicated identity skips review. The LLM's answer stays a suggestion for the reviewer
  (`flagged_for_review` true), as on `main`.
- The identity run costs more LLM calls than today for any company.
- Website or report checks depend on a network call made only for the check's own setup (e.g.
  `tldextract` fetching the public suffix list).

## Current state (what this builds on)

- `arp/discovery/site_finder.py`: `homepage_from_cik` (Wikidata P5531 → P856, shortest URL wins) and
  `resolve_company_homepage` (DuckDuckGo; first result with an IR hint, else `results[0]`).
- `arp/discovery/pipeline.py::_discover_for_company`: homepage = supplied website, else Wikidata by
  CIK, else search; then `crawl_for_documents` and `download_documents`.
- `arp/discovery/identity_graph.py`: identifier rules (`match_rules.py`), then EDGAR name lookup + web
  search signals, then one adjudicate LLM call whose website/CIK are checked against the signals by code.
  `_check_known` is an empty node.
- `arp/ingestion/edgar.py::EdgarDocumentSource.fetch`: newest `10-K` in `filings.recent`; CIK from
  `company.cik` or from the SEC ticker map by `company.ticker`, whatever the company's country.
- `arp/ingestion/doc_identity.py::reporting_year` finds the year in a title or text.
- `arp/discovery/downloader.py::download_documents` sends a plain GET for every candidate on every run
  and records the response's ETag and Last-Modified on the `DiscoveredDocument`, but never sends them
  back.
- `arp/discovery/change_detector.py::ChangeDetector.diff_and_record` keeps one manifest per company,
  keyed by URL. An unknown URL is a `new_document` event, a known URL with a new hash an
  `updated_document` event; events go to the global feed, the webhook and `on_events` (refresh).
- The file store (`upload_or_fail`) and the document registry (`derive_doc_id`) are keyed by content
  hash, so the same bytes are stored and registered once already.
- ESEF fetching by LEI already exists (`arp/xbrl_pipeline/fetch_esef.py`, `poll_esef_filings`) and is
  not changed.

## Design

### New dependencies

Added to `backend/pyproject.toml` with the file's upper-bound convention:

- `rapidfuzz>=3.14,<4.0`: fuzzy name matching.
- `cleanco>=2.3,<3.0`: strips legal suffixes (AG, SE, plc, S.A., GmbH) before matching.
- `tldextract>=5.4,<6.0`: reduces a host to its registrable domain (`ir.basf.com` → `basf.com`,
  `x.co.uk` handled). Built with `suffix_list_urls=()` and no cache dir, so it uses the bundled snapshot
  and never fetches.

Not added: `extruct` (JSON-LD is read with BeautifulSoup + `json`), `edgartools` (ARP has its own
EDGAR client).

### Name matching (`arp/discovery/names.py`)

`names_match(a, b) -> bool`: both sides lowercased, legal suffixes removed with `cleanco`, punctuation
collapsed, then `rapidfuzz.fuzz.token_set_ratio >= 90`. One function, used by the site check and the
document check.

### Wikidata by identifier (`site_finder.py`)

`homepage_from_ids(user_agent, *, lei=None, isin=None, cik=None) -> str | None` replaces
`homepage_from_cik` (callers updated). It tries LEI (P1278), then ISIN (P946), then CIK (P5531), and
returns the first identifier's shortest P856 URL. An identifier is only put into the query if it passes
validation (`lei_is_valid`, the ISIN check digit, digits-only CIK). An invalid one is skipped without a
request.

### GLEIF (`arp/discovery/gleif.py`)

- `lei_for_isin(client, isin) -> str | None`: GLEIF's ISIN filter; the LEI only when exactly one record
  comes back with registration status `ISSUED`.
- `name_matches(client, name, limit=5) -> list[GleifMatch]`: GLEIF's name search (the builder picks
  fuzzy completions or the full-text filter); only `ISSUED` records, at most 5. `GleifMatch` has `lei`,
  `legal_name`, `country`.
- Errors and timeouts return `None` / `[]` and log at info, like `homepage_from_cik`.

### Site check (`arp/discovery/site_check.py`)

`check_homepage(url, company, user_agent, *, identifier_source=False, transport=None) -> SiteCheck`, with
`SiteCheck(verdict: "owned" | "unclear" | "rejected", evidence: list[str])`.

1. If the URL's registrable domain is on `AGGREGATOR_DOMAINS` → `rejected`, evidence
   `["blocklisted_domain"]`, no request sent. The list: wikipedia.org, linkedin.com, bloomberg.com,
   reuters.com, yahoo.com, marketscreener.com, zonebourse.com, morningstar.com, finanzen.net, onvista.de,
   ariva.de, crunchbase.com, dnb.com, annualreports.com, responsibilityreports.com, sec.gov, xbrl.org,
   gleif.org, facebook.com, x.com, twitter.com, youtube.com, glassdoor.com.
2. Fetch the page (SSRF hook, as in `crawler.py`). Redirects are followed, at most 5 hops, each through
   the SSRF hook; evidence is read from the final page. If a redirect points to a URL whose registrable domain is on
   `AGGREGATOR_DOMAINS`, the result is `rejected` with evidence exactly `["blocklisted_domain"]` and that
   URL is not requested. "Same-site" below means the same registrable
   domain (`tldextract`) as the final URL, so `legal.testwerke.de` is same-site as `www.testwerke.de`.
   Collect evidence, each code at most once:
   - `name_in_title`: `<title>` matches the company name (`names_match`, also on each part when the title
     is split on `|`, `-`, `–`, `:`).
   - `name_in_site_name`: `og:site_name` matches.
   - `name_in_jsonld`: a JSON-LD `Organization` (or subtype) `name` or `legalName` matches.
   - `lei_on_page`, `isin_on_page`: the company's LEI or ISIN appears in the page text or JSON-LD
     (`leiCode`).
   - Imprint: the first same-site link whose text matches `impressum|imprint|legal notice|mentions
     légales|legal information` (case-insensitive) is fetched, giving `name_on_imprint`,
     `lei_on_imprint`, `isin_on_imprint`.
3. Verdict: any `lei_*`/`isin_*` evidence → `owned`; `name_on_imprint` plus one homepage name signal →
   `owned`; with `identifier_source=True`, any one name signal (homepage or imprint) → `owned`; any
   other evidence → `unclear`; none → `rejected`. Whenever `identifier_source=True` and the verdict is
   `owned` (by any rule), `identifier_source` is appended as the last evidence code.
   `identifier_source=True` means the URL came from Wikidata by identifier (`homepage_from_ids`): an
   exact, identifier-keyed source that only needs the page to agree on the name. (Added 2026-10-18 after
   the live test: large companies print no LEI on their homepage or imprint, so without it no homepage
   was ever `owned`.) It changes nothing for blocklisted URLs or fetch errors.
4. Errors: if the homepage request raises (`httpx.HTTPError`, `UnsafeURLError`) or returns HTTP ≥ 400,
   the result is `unclear` with evidence exactly `["fetch_failed"]`; an unreachable site is the
   crawler's call, not this check's. A failed imprint request (error or ≥ 400) is ignored: the
   homepage evidence stands and no imprint evidence is added.

### Discovery pipeline

- `resolve_company_homepage` skips results whose registrable domain is on `AGGREGATOR_DOMAINS` before
  applying its IR-hint and first-result rules.
- `_discover_for_company`: a supplied `company.website` is used as today, unchecked. Otherwise the
  homepage comes from `homepage_from_ids` (with the company's LEI, ISIN and CIK, supplied or not),
  then search, and is passed through `check_homepage` (with `identifier_source=True` only when this URL
  was returned by `homepage_from_ids`; a search-found URL never gets it, whatever identifiers the
  company has). Search runs only when `homepage_from_ids` returns `None`; a `rejected` Wikidata
  homepage is not replaced by a search result. A
  `rejected` homepage is not crawled: `homepage_used` is `None` and the new
  `DiscoveryCompanyResult.homepage_check` holds the `SiteCheck`. `owned` and `unclear` are crawled, with
  `homepage_check` set.
- `DiscoveryCompanyResult.homepage_check: SiteCheck | None = None` (None when the website was
  supplied or no homepage was found).

### Document check (`arp/discovery/doc_check.py`)

After `download_documents`, each `.pdf` gets `check_document(path, company) -> DocCheck` using
`pypdf`, reading the first 5 and last 10 pages:

- `page_count`: total pages.
- `reporting_year`: `doc_identity.reporting_year(title, first-page text)`, title from PDF metadata.
- `company_match`: `"identifier"` if the LEI or ISIN appears; else `"name"` if any line on the
  pages read matches the company name with `names_match`, or the text contains the company name with
  its legal suffix removed (case-insensitive); else `"no_text"` if the pages read have under 200
  characters of text; else `"none"`.

`DiscoveredDocument` gets `company_match`, `page_count`, `reporting_year`, all optional and `None`
for non-PDF documents and for EDGAR and ESEF documents. A company whose documents include one with
`company_match` `"none"` or `"no_text"` counts toward the run's review count, the same way a company
with zero documents does today. Nothing is deleted or left out of `documents_found`.

### Identity run

- `_check_known` (the existing empty node): when the company has no LEI and a valid ISIN, call
  `lei_for_isin`. A hit is used as the company's LEI for the identifier rules and stored in the new
  `IdentityResolutionResult.derived_lei`. `identifiers` keeps only the supplied values, so
  `needs_recheck` stays consistent.
- Resolved by identifier (`exact_lei` / `identifier_map`) with neither a website nor a CIK supplied
  (the existing `lookup` condition in `_apply_rules`): call
  `homepage_from_ids`, then `check_homepage(..., identifier_source=True)`. `owned` → verdict `resolved`, not flagged,
  `resolved_website` set, confidence 1.0. `unclear` → verdict `uncertain`, flagged, reason
  `match_ambiguous`, `resolved_website` set. `rejected` or no Wikidata hit → today's behaviour (EDGAR
  name lookup, flagged).
- `IdentitySignals.gleif_matches: list[GleifMatch]` is filled by `gather_signals` (one `name_matches`
  call) and listed in the adjudicate prompt under `GLEIF matches:` as
  `  - lei=<lei> name=<legal_name!r> country=<country>`, or `GLEIF matches: none found`.
- `IdentityAdjudication.resolved_lei` and `IdentityResolutionResult.resolved_lei` (both `str | None`).
  Code keeps it only if it equals one of `signals.gleif_matches[*].lei`, the same rule as for CIK.
  A dropped LEI makes the result `uncertain` and flagged.
- After adjudication, if `resolved_lei` is set and `resolved_website` is not, `homepage_from_ids(lei=…)`
  plus `check_homepage(..., identifier_source=True)` run. `owned` or `unclear` sets `resolved_website`; `rejected` leaves it empty.
  Verdict, confidence, `match_rule` (`ambiguous`) and `flagged_for_review` (true) stay as the
  adjudicate path sets them on `main`: the site check only fills in the website for the reviewer.
  The run still makes exactly one LLM call for this company.
- `enriched_universe` exports `lei` as the supplied LEI, else `derived_lei`, else `resolved_lei`.

### EDGAR

- For `DocType.ANNUAL_REPORT_10K`, `fetch` takes the newest filing whose form is `10-K`, `20-F` or
  `40-F`. The document's `doc_type` stays `"10-K"`. Its title shows the real form
  (`"<name> 20-F (<date>)"`). Amendments (`/A`) are not picked, as today.
- Ticker → CIK only runs when `company.country` is empty or one of `US`, `USA`, `United States`
  (case-insensitive). Otherwise a missing CIK means no EDGAR fetch.

### Not downloading again (conditional GET)

- `ChangeDetector` gets a public read of a company's manifest (builder names it), and
  `_discover_for_company` passes the entries to `download_documents`.
- For a candidate URL that is in the manifest, the request carries `If-None-Match: <http_etag>` when an
  ETag was stored and `If-Modified-Since: <http_last_modified>` when a Last-Modified was stored, copied
  as stored. With neither stored, the request is a plain GET, as on `main`.
- On `304`: the stored blob is checked with `store.exists(sha256)` and the stored `local_path` with a
  file-exists check. If both are there, the `DiscoveredDocument` is the manifest entry (same `sha256`,
  `local_path`, `http_etag`, `http_last_modified`, `company_match`, `page_count`, `reporting_year`), the
  document check does not run again, and a `CaptureRecord` with `status` 304, `content_key` = the stored
  `sha256`, `collected` true is appended to the discovery capture log
  (`<documents_dir>/_captures.jsonl`, `downloader.CAPTURE_LOG`), with `url_chain` ending in the URL. If either is missing, the URL is fetched again with a plain
  GET and handled as a new download.
- A `200` is handled exactly as on `main`, conditional headers or not.

### Same file, new URL (alias)

- In `diff_and_record`, a document whose URL is not in the manifest but whose `sha256` equals the
  `sha256` of an entry under another URL raises no event. Its manifest entry is written as usual plus
  `"alias_of": "<that other URL>"` (the first such URL in manifest order). The comparison is against the
  manifest as it stands at that point in the run, entries written earlier in the same run included, so
  when one run finds the same bytes at two URLs, the first is `new_document` and the second an alias.
  Documents go to `diff_and_record` in `documents_found` order, which is the order the crawl found their
  links, whatever order the downloads finish in.
- `DiscoveredDocument` gets `alias_of: str | None = None`; the alias's entry in `documents_found`
  carries it.
- Everything else in `diff_and_record` is unchanged, including for ESEF polling.

## Constraints

- Every new outbound request goes through `ssrf_guard_request_hook`, with the discovery user agent.
- Wikidata, GLEIF and site-check failures never fail a company's run. They degrade to today's path.
- No new settings. Thresholds and the blocklist are module constants.
- The checks in "Checks" in `.claude/CLAUDE.md` pass. No existing test is deleted or weakened.

## Left to the builder

- Which GLEIF name-search endpoint to use, and its exact query parameters.
- Whether `homepage_from_cik` stays as a thin alias or every caller moves to `homepage_from_ids`.
- Test fixture layout (httpx `MockTransport` is the house pattern).

## Acceptance

**Fixtures** (all HTTP served by a mock transport; no test touches the network):

- Company **W**: `company_id` `w`, name `Testwerke AG`, LEI `5299009TESTWERKE0063`, ISIN
  `DE000TST0006`, country `DE`, no website, no CIK, no ticker unless a row says so.
- Company **O**: name `Otherco plc`, LEI `5299009OTHERCO000060`.
- **H1** `https://www.testwerke.de/`: title `Testwerke – Startseite`, a link `Impressum` to
  `/impressum`, whose text contains `Testwerke AG` and `LEI: 5299009TESTWERKE0063`.
- **H2** `https://www.marketscreener.com/quote/stock/TESTWERKE-AG-1/`.
- **H3** `https://www.otherco.co.uk/`: title `Otherco plc | Home`, no imprint link, no identifiers.
- **H4** `https://www.testwerke.de/` variant: title `Testwerke AG`, no imprint link, no identifiers.
- **P1** PDF, 30 pages: page 1 text `Testwerke AG Geschäftsbericht 2025`, page 28 text contains
  `5299009TESTWERKE0063`.
- **P2** PDF, 30 pages: page 1 text `Testwerke AG Annual Report 2025`, no identifiers.
- **P3** PDF, 30 pages: page 1 text `Otherco plc Annual Report 2025`, no mention of Testwerke.
- **P4** PDF, 30 pages, image-only (no text layer).
- P1–P3 also carry at least 200 characters of neutral filler text (no company name, no identifier, no year)
  on page 2, so the `no_text` rule (under 200 characters on the pages read) does not apply to them.
- **Two-run setup** (rows AC-56 to AC-66): W with supplied website `https://www.testwerke.de/`, one
  `ChangeDetector` state dir and one file store shared by both runs. Run 1: the homepage links only to
  `https://www.testwerke.de/gb2025.pdf`, which returns P1 with `ETag: "v1"` and
  `Last-Modified: Wed, 01 Apr 2026 08:00:00 GMT`. Run 2 follows; each row says what changes.
- **Fake LLM**: records each prompt it receives and returns a fixed `IdentityAdjudication`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | W, H1 | `check_homepage(H1, W)` | verdict `owned`; evidence contains `lei_on_imprint` | unit |
| AC-2  | W, H2 | `check_homepage(H2, W)` | verdict `rejected`, evidence exactly `["blocklisted_domain"]` | unit |
| AC-3  | W, H2 | `check_homepage(H2, W)` | the mock transport receives 0 requests | unit |
| AC-4  | W, H2 with host `de.marketscreener.com` | `check_homepage` | verdict `rejected`, evidence exactly `["blocklisted_domain"]` | unit |
| AC-5  | W, H3 | `check_homepage(H3, W)` | verdict `rejected`, evidence `[]` | unit |
| AC-6  | W, H4 | `check_homepage(H4, W)` | verdict `unclear`, evidence exactly `["name_in_title"]` | unit |
| AC-7  | W, H4 with title `TESTWERKE` | `check_homepage` | evidence exactly `["name_in_title"]` | unit |
| AC-8  | W, H1 URL whose homepage request raises `httpx.ConnectError` | `check_homepage` | verdict `unclear`, evidence exactly `["fetch_failed"]` | unit |
| AC-9  | W, H2; `socket.socket.connect` patched to record each call and raise; `TLDEXTRACT_CACHE` set to an empty temp dir | `check_homepage(H2, W)` | `socket.socket.connect` was called 0 times | unit |
| AC-10 | Wikidata returns `https://www.testwerke.de/` and `https://www.testwerke.de/en/` for P1278 `5299009TESTWERKE0063` | `homepage_from_ids(lei=W.lei)` | returns `https://www.testwerke.de/` | unit |
| AC-11 | Wikidata returns nothing for W's LEI and `https://www.testwerke.de/` for P946 `DE000TST0006` | `homepage_from_ids(lei=W.lei, isin=W.isin)` | returns `https://www.testwerke.de/`; exactly 2 requests, P1278 first, P946 second | unit |
| AC-12 | — | `homepage_from_ids(lei="NOT-A-LEI", isin="XX123")` | returns `None`; 0 requests sent | unit |
| AC-13 | W without LEI; GLEIF ISIN filter for `DE000TST0006` returns one `ISSUED` record with W's LEI; Wikidata empty | identity run | result `derived_lei` = `5299009TESTWERKE0063`, `match_rule` = `exact_lei`, `resolved_issuer_key` = `5299009TESTWERKE0063`, `identifiers` = `{"isin": "DE000TST0006"}` | unit |
| AC-14 | W without LEI; GLEIF returns no record for the ISIN; EDGAR name search and GLEIF name search return nothing; web search returns nothing; Fake LLM returns verdict `unresolved`, confidence 0.0 | identity run | `derived_lei` `null`, `match_rule` `ambiguous`, verdict `unresolved`, `flagged_for_review` true (as on `main`) | unit |
| AC-15 | W; Wikidata P1278 → H1; H1 as fixture | identity run | verdict `resolved`, `flagged_for_review` false, `resolved_website` `https://www.testwerke.de/`, confidence 1.0 | unit |
| ~~AC-16~~ | ~~W; Wikidata P1278 → H4~~ | ~~identity run~~ | Retired 2026-10-18: with `identifier_source`, H4 is now `owned` (AC-74). Was: verdict `uncertain`, `flagged_for_review` true, `reason_codes` `["match_ambiguous"]`, `resolved_website` `https://www.testwerke.de/` | unit |
| AC-17 | W; Wikidata empty for all identifiers; EDGAR name search returns no matches; web search returns nothing | identity run | verdict `uncertain`, `flagged_for_review` true, `reason_codes` `["match_ambiguous"]`, `match_rule` `exact_lei`, `resolved_website` `null`, `resolved_cik` `null` (as on `main`) | unit |
| AC-18 | Company named `Testwerke AG`, no identifiers, no website; EDGAR no matches; web search returns nothing; GLEIF name search returns W's record | identity run | the Fake LLM's prompt contains the line `  - lei=5299009TESTWERKE0063 name='Testwerke AG' country=DE` | unit |
| AC-19 | as AC-18; Fake LLM returns verdict `resolved`, confidence 0.95, `resolved_lei` `5299009OTHERCO000060`, `resolved_website` `null`, `resolved_cik` `null` | identity run | result `resolved_lei` `null`, verdict `uncertain`, `flagged_for_review` true | unit |
| AC-20 | as AC-18; Fake LLM returns verdict `resolved`, confidence 0.95, `resolved_lei` `5299009TESTWERKE0063`, `resolved_website` `null`, `resolved_cik` `null`; Wikidata P1278 → H1 | identity run | result `resolved_lei` `5299009TESTWERKE0063`, `resolved_website` `https://www.testwerke.de/`, verdict `resolved`, confidence 0.95, `match_rule` `ambiguous`, `flagged_for_review` true | unit |
| AC-21 | the run of AC-20 plus an `approve` review decision for that company | `enriched_universe(run)` | one company, `lei` `5299009TESTWERKE0063`, `website` `https://www.testwerke.de/` | unit |
| AC-22 | W with supplied website `https://www.testwerke.de/` and CIK `123` | identity run | `match_rule` `exact_lei`, verdict `resolved`, `resolved_website` `https://www.testwerke.de/`, `resolved_cik` `123` (as on `main`) | unit |
| AC-23 | Company named `Testwerke AG`, no identifiers; search returns [H2 URL, H1 URL]; H1 fixture | discovery run | result `homepage_used` `https://www.testwerke.de/` | unit |
| AC-24 | Company named `Testwerke AG`, no identifiers; search returns only H3 | discovery run | `homepage_used` `null`, `homepage_check.verdict` `rejected`; H3 receives exactly 1 request (the check), and no request for any other H3 path | unit |
| AC-25 | W with supplied website H3 (page links to nothing) | discovery run | `homepage_used` `https://www.otherco.co.uk/`, `homepage_check` `null`; H3 receives exactly 1 request for path `/` | unit |
| ~~AC-26~~ | ~~W; Wikidata P1278 → H4~~ | ~~discovery run~~ | Retired 2026-10-18: now `owned` (AC-76). Was: `homepage_used` `https://www.testwerke.de/`, `homepage_check.verdict` `unclear`; the crawl fetches H4 | unit |
| AC-27 | W with supplied website `https://www.testwerke.de/`, whose page links only to P1 | discovery run | the document's `company_match` `identifier`, `page_count` 30, `reporting_year` 2025 | unit |
| AC-28 | W with supplied website `https://www.testwerke.de/`, whose page links only to P2 | discovery run | the document's `company_match` `name` | unit |
| AC-29 | W with supplied website `https://www.testwerke.de/`, whose page links only to P3 | discovery run | the document's `company_match` `none` | unit |
| AC-30 | as AC-29 | discovery run | P3 is in `documents_found` with a `local_path` that exists on disk | unit |
| AC-31 | W with supplied website `https://www.testwerke.de/`, whose page links only to P4 | discovery run | the document's `company_match` `no_text` | unit |
| AC-32 | W with supplied website `https://www.testwerke.de/`, whose page links only to P1 and to `/annual-report-2025.html` with link text `Annual Report 2025` (served as `text/html`) | discovery run | `documents_found` has 2 entries; the HTML one has `company_match`, `page_count`, `reporting_year` all `null` | unit |
| AC-33 | Submissions with `form` `["6-K", "20-F"]`, company with CIK | `EdgarDocumentSource.fetch(company, [ANNUAL_REPORT_10K])` | 1 document, `doc_type` `"10-K"`, title contains `20-F` | unit |
| AC-34 | Submissions with `form` `["40-F"]` | as AC-33 | 1 document, title contains `40-F` | unit |
| AC-35 | Submissions with `form` `["10-K/A", "10-K"]` | as AC-33 | 1 document, title contains `10-K (` and not `10-K/A` | unit |
| AC-36 | Ticker map has `TSTW` → CIK 123; company ticker `TSTW`, country `DE`, no CIK | `fetch` | returns `[]`; 0 requests to `data.sec.gov` | unit |
| AC-37 | Same ticker map; company ticker `TSTW`, country empty, no CIK | `fetch` | requests `https://data.sec.gov/submissions/CIK0000000123.json` (as on `main`) | unit |
| AC-38 | Same ticker map; company ticker `TSTW`, country `us`, no CIK | `fetch` | requests `https://data.sec.gov/submissions/CIK0000000123.json` | unit |
| AC-39 | as AC-29 | discovery run | the run manifest's review count is 1 | unit |
| AC-40 | as AC-31 | discovery run | the run manifest's review count is 1 | unit |
| AC-41 | as AC-27 | discovery run | the run manifest's review count is 0 | unit |
| AC-42 | as AC-10 | `homepage_from_ids(lei=W.lei)` | exactly 1 request; its SPARQL text contains `wdt:P1278 "5299009TESTWERKE0063"` | unit |
| AC-43 | as AC-15 | identity run | the Fake LLM received 0 prompts | unit |
| AC-44 | as AC-22 | identity run | Wikidata, GLEIF and `https://www.testwerke.de/` receive 0 requests | unit |
| AC-45 | as AC-20 | identity run | the Fake LLM received exactly 1 prompt | unit |
| ~~AC-46~~ | ~~W with supplied CIK `123`, no website; Wikidata P1278 → H4~~ | ~~discovery run~~ | Retired 2026-10-18: now `owned` (AC-80). Was: `homepage_used` `https://www.testwerke.de/`, `homepage_check.verdict` `unclear` | unit |
| AC-47 | W with supplied CIK `123`, no website | identity run | `match_rule` `exact_lei`, verdict `resolved`, `resolved_website` `null` (as on `main`) | unit |
| AC-48 | W, H1 whose `/impressum` request raises `httpx.ConnectError` | `check_homepage(H1, W)` | verdict `unclear`, evidence exactly `["name_in_title"]` | unit |
| AC-49 | W, H1 URL returning HTTP 404 | `check_homepage` | verdict `unclear`, evidence exactly `["fetch_failed"]` | unit |
| AC-50 | as AC-17 | identity run | the Fake LLM received 0 prompts | unit |
| AC-51 | as AC-47 | identity run | Wikidata receives 0 requests | unit |
| AC-52 | W; `https://testwerke.de/` returns 301 to `https://www.testwerke.de/` (H1) | `check_homepage("https://testwerke.de/", W)` | verdict `owned`; evidence contains `lei_on_imprint` | unit |
| AC-53 | W, H1 whose `Impressum` link points to `https://legal.testwerke.de/impressum` (same text as H1's imprint) | `check_homepage(H1, W)` | verdict `owned`; evidence, compared as a set, exactly `{"name_in_title", "name_on_imprint", "lei_on_imprint"}` | unit |
| AC-54 | W; `https://testwerke.de/` returns 301 to `https://www.linkedin.com/company/testwerke/` | `check_homepage("https://testwerke.de/", W)` | verdict `rejected`, evidence exactly `["blocklisted_domain"]` | unit |
| AC-55 | as AC-54 | `check_homepage("https://testwerke.de/", W)` | `www.linkedin.com` receives 0 requests | unit |
| AC-56 | Two-run setup; in run 2 the PDF URL returns `304` | run 2 | the run-2 request for `gb2025.pdf` carries `If-None-Match: "v1"` | unit |
| AC-57 | as AC-56 | run 2 | the run-2 request for `gb2025.pdf` carries `If-Modified-Since: Wed, 01 Apr 2026 08:00:00 GMT` | unit |
| AC-58 | as AC-56 | run 2 | the run-2 document has the same `sha256` and `local_path` as in run 1, `company_match` `identifier`, `page_count` 30, `reporting_year` 2025 | unit |
| AC-59 | as AC-56 | run 2 | the global events feed has the same number of lines after run 2 as after run 1 | unit |
| AC-60 | as AC-56 | run 2 | exactly one record whose `url_chain` ends in `https://www.testwerke.de/gb2025.pdf` is appended to `<documents_dir>/_captures.jsonl` in run 2, with `status` 304, `content_key` = P1's sha256, `collected` true | unit |
| AC-61 | as AC-56, but P1's blob is deleted from the file store before run 2; the URL returns P1 with `200` to a request without conditional headers | run 2 | `gb2025.pdf` receives 2 requests in run 2; the second has neither `If-None-Match` nor `If-Modified-Since` | unit |
| AC-62 | as AC-61 | run 2 | the file store has P1's blob again (`store.exists(<P1 sha256>)` is true) | unit |
| AC-63 | Two-run setup; in run 2 the PDF URL ignores the conditional headers and returns P2 with `200` | run 2 | exactly 1 event, type `updated_document`, for `https://www.testwerke.de/gb2025.pdf` (as on `main`) | unit |
| AC-64 | Two-run setup, but in run 1 the PDF response has no `ETag` and no `Last-Modified` | run 2 | the run-2 request for `gb2025.pdf` has neither `If-None-Match` nor `If-Modified-Since` (as on `main`) | unit |
| AC-65 | Two-run setup; in run 2 the homepage links only to `https://www.testwerke.de/gb2025.pdf?v=2`, which returns P1 with `200` | run 2 | the global events feed has the same number of lines after run 2 as after run 1 | unit |
| AC-66 | as AC-65 | run 2 | the company's manifest entry for `https://www.testwerke.de/gb2025.pdf?v=2` has `alias_of` `https://www.testwerke.de/gb2025.pdf` | unit |
| AC-67 | as AC-65, but `?v=2` returns P2 | run 2 | exactly 1 event, type `new_document`, for `https://www.testwerke.de/gb2025.pdf?v=2` (as on `main`) | unit |
| AC-68 | as AC-61 | run 2 | the run-2 document's `sha256` is P1's sha256 | unit |
| AC-69 | as AC-56, but the run-1 `local_path` file is deleted before run 2; the URL returns P1 with `200` to a request without conditional headers | run 2 | `gb2025.pdf` receives 2 requests in run 2; the second has neither `If-None-Match` nor `If-Modified-Since` | unit |
| AC-70 | as AC-69 | run 2 | the run-2 document's `local_path` exists on disk | unit |
| AC-71 | as AC-65 | run 2 | `documents_found` has one entry for `https://www.testwerke.de/gb2025.pdf?v=2`, with `alias_of` `https://www.testwerke.de/gb2025.pdf` | unit |
| AC-72 | W with supplied website `https://www.testwerke.de/`, empty state dir; the homepage links only to `/a.pdf` and then `/b.pdf`, both returning P1; `/a.pdf`'s response is delayed so that `/b.pdf` finishes downloading first | discovery run | the global events feed gains exactly 1 line, a `new_document` for `https://www.testwerke.de/a.pdf` | unit |
| AC-73 | as AC-72 | discovery run | the manifest entry for `https://www.testwerke.de/b.pdf` has `alias_of` `https://www.testwerke.de/a.pdf` | unit |
| AC-74 | W; Wikidata P1278 → H4 | identity run | verdict `resolved`, `flagged_for_review` false, `resolved_website` `https://www.testwerke.de/`, confidence 1.0 | unit |
| AC-75 | W; Wikidata P1278 → `https://www.testwerke.de/`, which returns HTTP 404 | identity run | verdict `uncertain`, `flagged_for_review` true, `reason_codes` `["match_ambiguous"]`, `resolved_website` `https://www.testwerke.de/` | unit |
| AC-76 | W; Wikidata P1278 → H4 | discovery run | `homepage_used` `https://www.testwerke.de/`, `homepage_check.verdict` `owned`, `homepage_check.evidence` exactly `["name_in_title", "identifier_source"]`; H4 receives exactly 2 requests for path `/` (check, then crawl) | unit |
| AC-77 | Company named `Testwerke AG`, no identifiers; search returns only the H4 URL | discovery run | `homepage_used` `https://www.testwerke.de/`, `homepage_check.verdict` `unclear`, `homepage_check.evidence` exactly `["name_in_title"]`; H4 receives exactly 2 requests for path `/` | unit |
| AC-78 | W, H4 | `check_homepage(H4, W, identifier_source=True)` | verdict `owned`, evidence exactly `["name_in_title", "identifier_source"]` | unit |
| AC-79 | W, H2 | `check_homepage(H2, W, identifier_source=True)` | verdict `rejected`, evidence exactly `["blocklisted_domain"]` | unit |
| AC-80 | W with supplied CIK `123`, no website; Wikidata P1278 → H4 | discovery run | `homepage_used` `https://www.testwerke.de/`, `homepage_check.verdict` `owned` | unit |
| AC-81 | W, H3 | `check_homepage(H3, W, identifier_source=True)` | verdict `rejected`, evidence `[]` | unit |
| AC-82 | W, H4 plus a link `Impressum` to `/impressum` whose text contains `Testwerke AG` and no identifier | `check_homepage(that URL, W)` (flag off) | verdict `owned`, evidence, compared as a set, exactly `{"name_in_title", "name_on_imprint"}` | unit |
| AC-83 | W, H1 | `check_homepage(H1, W, identifier_source=True)` | verdict `owned`, evidence, compared as a set, exactly `{"name_in_title", "name_on_imprint", "lei_on_imprint", "identifier_source"}` | unit |
| AC-84 | W; Wikidata returns nothing for all identifiers; search returns only the H4 URL | discovery run | `homepage_check.verdict` `unclear`, `homepage_check.evidence` exactly `["name_in_title"]` | unit |
| AC-85 | W, H1 URL returning HTTP 404 | `check_homepage(H1 URL, W, identifier_source=True)` | verdict `unclear`, evidence exactly `["fetch_failed"]` | unit |
| AC-86 | W; `https://www.testwerke.de/` has title `Willkommen` and a link `Impressum` to `/impressum` whose text contains `Testwerke AG` and no identifier | `check_homepage(that URL, W, identifier_source=True)` | verdict `owned`, evidence exactly `["name_on_imprint", "identifier_source"]` | unit |
| AC-87 | W; Wikidata P1278 → H3; EDGAR name search returns no matches; web search returns nothing | identity run | verdict `uncertain`, `flagged_for_review` true, `reason_codes` `["match_ambiguous"]`, `resolved_website` `null` | unit |
| AC-88 | as AC-20, but Wikidata P1278 → H4 | identity run | `resolved_website` `https://www.testwerke.de/`, verdict `resolved`, confidence 0.95, `match_rule` `ambiguous`, `flagged_for_review` true | unit |
| AC-89 | W; Wikidata P1278 → H3; the search client would return the H1 URL | discovery run | `homepage_used` `null`, `homepage_check.verdict` `rejected`; the search client receives 0 queries | unit |

Must not change: a supplied website is never checked (AC-25) and a company with a supplied website or
CIK makes no new identity lookup (AC-22, AC-44, AC-47, AC-51); the identifier-rule path without a Wikidata hit
(AC-17); an ISIN-only company with no GLEIF hit (AC-14); adjudicated results stay flagged (AC-20);
amendment filings are not picked (AC-35); a `200` with new bytes is still an update (AC-63); no stored
headers means a plain GET (AC-64); new bytes at a new URL are still new (AC-67); US ticker resolution (AC-37); no downloaded document is
dropped (AC-30); a search-found homepage with a single name signal is `unclear`, not `owned` (AC-77, AC-84); the full backend suite passes.
