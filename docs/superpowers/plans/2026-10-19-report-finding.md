# Report finding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discovery returns each company's latest annual report and sustainability report: ESEF first, then a
DuckDuckGo PDF search, then a crawl that starts from sitemap report pages, keeps off-site report PDFs, knows
more report names and downloads only the best 2 per type.

**Architecture:** `_discover_for_company` becomes one straight path: EDGAR → ESEF → report search → homepage →
crawl (sitemap seeds + BFS) → `select_candidates` (rank, dedupe, top 2) → download → one `diff_and_record`. Link
classification, sitemap seeding and the off-site rule live in `crawler.py`; search queries and ranking live in a
new `report_finding.py`. No new settings.

**Tech Stack:** Python 3.13, httpx (`MockTransport` in tests), lxml (sitemap XML), pytest (asyncio auto, `pg`
fixture), ruff.

**Spec:** `docs/superpowers/specs/2026-10-19-report-finding-design.md` (AC-1..AC-98; AC-23, 29, 42, 67 retired).

## Global Constraints

- `expected_year = today.year - 1`; ESEF current = `period_end >= today − 548 days`.
- Year in a text: `(?<!\d)20\d{2}(?!\d)`. Words: lowercase, split on every non-alphanumeric; demotion words match
  whole tokens, `half-year` / `fact sheet` match two consecutive tokens. Link "text" = link text + URL filename.
- Every new request goes through `ssrf_guard_request_hook` with the discovery user agent.
- No new settings; limits are module constants: 5 search results, top 2 per type, 3 robots sitemaps, 5 child
  sitemaps, 10 seeds, 15,000,000 sitemap bytes.
- `esef_enabled` defaults to `True`; `ARP_ESEF_ENABLED=false` turns it off.
- No existing test deleted or weakened. Exactly these existing tests change, and the PR lists them:
  `tests/test_esef.py::test_source_off_by_default` (default assertion → `True`, the "off" registry built with
  `esef_enabled=False`) and `tests/test_event_refresh.py::test_esef_poll_off_by_default` (sets
  `esef_enabled=False`). Any other existing test that fails is a bug in the change, not in the test.
- `_discover_for_company`'s existing keyword arguments keep working (`tests/test_discovery_pipeline_unreachable.py`
  calls it with only `settings, search_client, change_detector, doc_types`); new ones have defaults.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; Postgres via
  `bash .claude/hooks/ensure-deps.sh postgres`, `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test`.

## Review Focus

1. An ESEF filing whose `period_end` is missing or malformed (`"2025"`, `null`) → not current, the annual query
   still runs, the company does not fail. Test in Task 1.
2. A `.gz` sitemap that is not valid gzip → that sitemap is skipped, the crawl still runs. Test in Task 4.
3. A sitemap without the sitemaps.org namespace, `<loc>` values padded with whitespace/newlines → still read
   (match elements by local name, strip text). Test in Task 4.
4. A run with `doc_types=[DocType.ANNUAL_REPORT_10K]` → no sustainability query is sent (a query for a type that
   will be discarded only spends DuckDuckGo's patience). Test in Task 3.
5. A company name containing `"` (`Foo "Bar" AG`) → the quotes are removed from the name inside the query, so
   the phrase stays one phrase: `"Foo Bar AG" annual report 2025 filetype:pdf`. Test in Task 3.

---

## File structure

| File | Change | Responsibility |
|------|--------|----------------|
| `backend/arp/config.py` | modify | `esef_enabled` default `True`, description updated |
| `backend/arp/ingestion/esef.py` | modify | `EsefDocumentSource(..., transport=None)` reaches its own client |
| `backend/arp/discovery/site_finder.py` | modify | `DuckDuckGoSearchClient(..., transport=None)` |
| `backend/arp/discovery/pipeline.py` | modify | ESEF first, search, single exit, `today`/`sleep`, poll removed |
| `backend/arp/discovery/crawler.py` | modify | new phrases, fallback, demotion, off-site PDFs, sitemap seeds, `sleep` |
| `backend/arp/discovery/report_finding.py` | create | search queries + candidates, ranking/dedupe/top-2 |
| `backend/tests/report_finding_fixtures.py` | create | shared harness for the AC tests (like `pdf_fixtures.py`) |
| `backend/tests/test_report_finding_esef.py` | create | Task 1 ACs |
| `backend/tests/test_report_finding_links.py` | create | Task 2 ACs |
| `backend/tests/test_report_finding_search.py` | create | Task 3 ACs |
| `backend/tests/test_report_finding_sitemap.py` | create | Task 4 ACs |
| `backend/tests/test_esef.py`, `backend/tests/test_event_refresh.py` | modify | the two listed lines |

`poll_esef_filings` (`change_detector.py`) stays: the pipeline stops calling it, but
`tests/test_event_refresh.py::test_esef_poll_error_never_raises` tests it directly and must not be deleted. Name
it in the PR as now unused by the pipeline.

---

### Task 1: ESEF first, shared harness, default on

**Files:**
- Create: `backend/tests/report_finding_fixtures.py`, `backend/tests/test_report_finding_esef.py`
- Modify: `backend/arp/config.py:224-228`, `backend/arp/ingestion/esef.py` (`EsefDocumentSource.__init__`, `fetch`),
  `backend/arp/discovery/site_finder.py` (`DuckDuckGoSearchClient`), `backend/arp/discovery/pipeline.py`,
  `backend/arp/discovery/crawler.py` (`crawl_for_documents` signature only),
  `backend/tests/test_esef.py:165-176`, `backend/tests/test_event_refresh.py` (`test_esef_poll_off_by_default`)

**Interfaces:**
- Produces (harness, `tests/report_finding_fixtures.py`):
  - `W: CompanyRef` (`company_id="w"`, `name="Testwerke AG"`, `lei="5299009TESTWERKE0063"`, `website="https://www.testwerke.de/"`)
  - `SITE = "https://www.testwerke.de"`, `TODAY = date(2026, 10, 19)`,
    `ANNUAL_Q = '"Testwerke AG" annual report 2025 filetype:pdf'`, `SUST_Q = '"Testwerke AG" sustainability report 2025 filetype:pdf'`,
    `INDEX_URL = "https://filings.xbrl.org/api/entities/5299009TESTWERKE0063/filings"`
  - `page(*links: tuple[str, str]) -> httpx.Response` — HTML whose anchors are `(href, text)`.
  - `pdf_response(tmp_path, first_page: str = "Testwerke AG Annual Report 2025") -> httpx.Response` (3 pages,
    `make_pdf(..., n_pages=3)`); `image_pdf_response(tmp_path) -> httpx.Response` (`make_image_pdf(..., n_pages=3)`).
  - `class FakeSearch(WebSearchClient)`: `__init__(self, log: list[str], results: dict[str, list[str | tuple[str, str]]] | None = None, error: Exception | None = None)`;
    each `search(query, max_results)` appends `query <query>` to `log` and `(query, max_results)` to `self.calls`,
    raises `error` if set, else returns `results.get(query, [])` as `SearchResult(title=title or url, url=url)`.
  - `class FakeEdgar`: `fetch(company, doc_types=None)` records `company.company_id` in `self.asked`, returns its `docs`.
  - `@dataclass Run`: `row: dict`, `manifest`, `log: list[str]`, `search: FakeSearch | None`, `edgar: FakeEdgar`;
    `count(url) -> int` (log entries exactly `request <url>`), `host_count(host) -> int`,
    `docs(doc_type: str | None = None) -> list[str]` (urls of `documents_found` in order, optionally one type),
    `doc(url) -> dict`, `queries -> list[str]`.
  - `async discover(tmp_path, pg, monkeypatch, *, company=W, esef: str | tuple[str, str] = "none", routes: dict | None = None, fallback=None, search: dict | Exception | None = None, default_search: bool = False, wikidata: str | None = None, edgar: FakeEdgar | None = None, **settings) -> Run`
- Produces (code): `_discover_for_company(company, *, settings, search_client, change_detector, doc_types, edgar=None, esef: EsefDocumentSource | None = None, transport=None, today: date | None = None, sleep=asyncio.sleep)`;
  `execute_discovery_run(..., transport=None, today: date | None = None, sleep=None)`;
  `EsefDocumentSource(index_url, cache_dir, *, client=None, transport=None, ...)`;
  `DuckDuckGoSearchClient(user_agent, timeout=15.0, *, transport=None)`;
  `crawl_for_documents(root_url, config, *, transport=None, sleep=asyncio.sleep)`.

Harness rules (decisions the tests rely on):
- Settings: every dir under `tmp_path` (`documents_dir`, `discovery_state_dir`, `runs_dir`, `cache_dir`,
  `blob_store_dir`), `discovery_request_delay_seconds=0.2`, `esef_enabled=True`, then `**settings` overrides.
  Two `discover` calls with the same `tmp_path` share state (AC-63).
- `sleep` recorder appends `f"sleep {seconds}"`; the transport appends `f"request {request.url}"` before answering.
- Answer order: `routes[str(url)]` (a `Response`, or a callable `request -> Response` for repeated or streamed
  bodies) → `fallback(request)` if given and it returns a response → ESEF (`INDEX_URL`: per `esef`; the package
  URL: `tests/fixtures/esef/beispiel-2024.zip` bytes) → `query.wikidata.org`: one binding `wikidata` or none →
  any `/robots.txt`: `User-agent: *\nAllow: /\n` → `SITE + "/"`: `page()` → any path ending `.pdf`
  (case-insensitive): `pdf_response` → `html.duckduckgo.com`: 202 → else 404.
- `esef`: `"current"` = one filing `period_end` `2025-12-31`, `package_url` `https://filings.xbrl.org/w/2025.zip`;
  `"old"` = `2024-12-31`, `.../w/2024.zip`; `"none"` = `{"data": []}`; `"error"` = HTTP 500; a tuple
  `(period_end, package_url)` = that one filing. JSON:API shape as in `tests/test_event_refresh.py::_esef_source`.
  (The package is the existing Beispiel AG fixture: the ESEF source never checks the name.)
- SSRF: always `monkeypatch.setattr("arp.net_safety.socket.getaddrinfo", resolver)`, `resolver` mapping
  `metadata.example.net` → `169.254.169.254`, `internal.testwerke.de` → `10.0.0.5`, every other host →
  `93.184.216.34`, returned as `[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]`. The real hook then
  passes every fixture host except those two, which is the spec's no-op in all rows that don't use them.
- `search_client`: `None` when `default_search`, else `FakeSearch(log, search)` (or `error=search` when
  `search` is an exception). `edgar_source`: `edgar or FakeEdgar()`. `today=TODAY`.

- [ ] **Step 1: Write the harness and the failing tests** (`tests/test_report_finding_esef.py`)

```python
async def test_ac_1(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current")
    assert "https://filings.xbrl.org/w/2025.zip" in run.docs("10-K")

async def test_ac_5(...):    # esef="old"
    assert "https://filings.xbrl.org/w/2024.zip" in run.docs()

async def test_ac_6(...):    # esef="current"
    assert run.count(INDEX_URL) == 1

async def test_ac_7(...):    # esef="error"
    assert run.manifest.failed_count == 0

async def test_ac_8(...):    # company=W.model_copy(update={"lei": None}), esef="current"
    assert run.host_count("filings.xbrl.org") == 0

async def test_ac_9(...):    # esef="current", esef_enabled=False
    assert run.host_count("filings.xbrl.org") == 0

async def test_ac_28(...):   # esef="none"
    assert run.row["homepage_check"] is None

async def test_ac_44(...):   # esef="current", routes={SITE + "/": httpx.Response(403)}
    assert "https://filings.xbrl.org/w/2025.zip" in run.docs()

async def test_ac_63_and_90(...):   # esef="current", two runs, same tmp_path
    first = await discover(...); second = await discover(...)
    assert [e["document"]["url"] for e in first.row["new_events"]] == ["https://filings.xbrl.org/w/2025.zip"]  # AC-90
    assert second.row["new_events"] == []                                                                     # AC-63

async def test_ac_64(...):   # company=W with cik="123", esef="current"
    assert run.edgar.asked == ["w"]

def test_ac_65():
    assert Settings().esef_enabled is True        # clear ARP_ESEF_ENABLED with monkeypatch.delenv(raising=False)

def test_ac_86(monkeypatch):
    monkeypatch.setenv("ARP_ESEF_ENABLED", "false")
    assert Settings().esef_enabled is False

def test_ac_87(tmp_path):    # store = DocumentContentStore(tmp_path / "store", dsn=pg_dsn()), as in test_esef.py
    assert any(isinstance(s, EsefDocumentSource) for s in build_registry(Settings(), store).sources)

def test_ac_94(monkeypatch):  # point the CLI's settings dirs at tmp_path the way other tests of arp.cli._shared do
    assert any(isinstance(s, EsefDocumentSource) for s in _registry().sources)

async def test_malformed_period_end_is_not_current(...):   # Review Focus 1: esef=("2025", "https://filings.xbrl.org/w/x.zip")
    assert run.manifest.failed_count == 0
```

- [ ] **Step 2: Run, expect failures**

Run: `cd backend && python3 -m pytest tests/test_report_finding_esef.py -q`
Expected: FAIL — `execute_discovery_run() got an unexpected keyword argument 'today'`, AC-65 `False is not True`.

- [ ] **Step 3: Thread `transport` and `sleep`**

- `EsefDocumentSource.__init__` gains `transport: httpx.AsyncBaseTransport | None = None`, passed to the client
  `fetch` builds when `client` is `None`.
- `DuckDuckGoSearchClient.__init__` gains keyword `transport=None`, passed to its `AsyncClient`.
- `crawl_for_documents` gains keyword `sleep=asyncio.sleep` and awaits it instead of `asyncio.sleep`.

- [ ] **Step 4: ESEF first and a single exit in `pipeline.py`**

- New `_esef_documents(company, source, doc_types, today) -> tuple[list[DiscoveredDocument], bool]`: `fetch` in a
  `try` (any exception → `logger.warning`, `([], False)`), each doc → `DiscoveredDocument(company_id, doc_type,
  url=source_url, local_path, sha256=content_key or sha256)` as in `poll_esef_filings`; the bool is "current":
  `date.fromisoformat(fiscal_period[:10]) >= today - timedelta(days=_ESEF_CURRENT_DAYS)` (`_ESEF_CURRENT_DAYS = 548`),
  `ValueError`/`TypeError` → not current.
- `_discover_for_company`: EDGAR → `_esef_documents` (when `esef` given) → homepage resolution unchanged →
  crawl only when there is a homepage (`HomepageUnreachableError` sets `homepage_unreachable`/`crawl_error` and
  leaves no crawl candidates) → `doc_types` filter → `download_documents` → one
  `diff_and_record(company, esef_docs + downloaded)` → `documents_found = filings + esef_docs + downloaded`.
  No early returns. Pass `sleep=sleep` to `crawl_for_documents`. `today = today or date.today()`.
- `execute_discovery_run`: new keywords; `DuckDuckGoSearchClient(settings.discovery_user_agent, transport=transport)`;
  `EsefDocumentSource(settings.esef_index_url, settings.cache_dir, transport=transport)`; pass `esef`, `today`,
  `sleep or asyncio.sleep` to `_discover_for_company`; delete the `poll_esef_filings` call and import; update the
  docstring sentence about polling.

- [ ] **Step 5: Default on**

`config.py`: `esef_enabled` `default=True`; description: drop "Off by default: a network source.", add "On by
default; ARP_ESEF_ENABLED=false turns it off." `tests/test_esef.py::test_source_off_by_default`: line 172 becomes
`assert settings.esef_enabled is True`, and the "off" half builds its registry from
`_settings(tmp_path, esef_enabled=False)` (keep the no-network patch and both assertions).
`tests/test_event_refresh.py::test_esef_poll_off_by_default`: `_settings(tmp_path, esef_enabled=False)`.

- [ ] **Step 6: Run**

Run: `cd backend && ruff check . && python3 -m pytest tests/test_report_finding_esef.py tests/test_esef.py tests/test_event_refresh.py tests/test_doc_check.py tests/test_known_reports.py tests/test_discovery_homepage.py tests/test_discovery_pipeline_unreachable.py tests/test_jobs.py -q`
Expected: all pass.

- [ ] **Step 7: Commit** — `git commit -m "Discovery: ESEF first, one exit path, esef_enabled on by default"`

---

### Task 2: Report names, fallback, demotion, off-site report PDFs

**Files:**
- Modify: `backend/arp/discovery/crawler.py`, `backend/arp/discovery/pipeline.py` (pass `expected_year`)
- Create: `backend/tests/test_report_finding_links.py`

**Interfaces:**
- Consumes: the Task 1 harness.
- Produces (`crawler.py`):
  - `report_text(url: str, link_text: str) -> str` — `f"{link_text} {filename}".lower()`, filename =
    last segment of the URL path.
  - `years_in(text: str) -> set[int]`; `is_demoted(text: str) -> bool`; `is_pdf(url: str) -> bool` (URL path,
    query ignored, ends `.pdf` case-insensitive).
  - `classify_link(url, link_text, expected_year: int | None = None) -> DocType | None`
  - `CrawlConfig.expected_year: int | None = None`

- [ ] **Step 1: Write the failing tests**

```python
PHRASES = ["Integrated Report", "Universal Registration Document", "Annual Review", "Geschäftsbericht",
           "Geschaeftsbericht", "Rapport annuel", "Informe anual", "Jaarverslag", "Årsrapport"]
DEMOTION = ["quarter", "quarterly", "q1", "q2", "q3", "q4", "half-year", "interim", "factsheet", "fact sheet",
            "presentation", "transcript", "remuneration", "tax", "summary", "extract"]

def home(*links):  # routes for the homepage
    return {SITE + "/": page(*links)}

@pytest.mark.parametrize("phrase", PHRASES)                      # AC-48a–i
async def test_ac_48(phrase, ...):   # home(("/x.pdf", f"{phrase} 2022"))
    assert run.doc(SITE + "/x.pdf")["doc_type"] == "10-K"

async def test_ac_49(...):   # home(("/Testwerke_Report_FY2025.pdf", "Testwerke Report"))  -> "10-K"
async def test_ac_50(...):   # home(("/Testwerke_Report_2022.pdf", "Testwerke Report"))    -> "other"

@pytest.mark.parametrize("word", DEMOTION)                       # AC-51
async def test_ac_51(word, ...):     # home(("/r.pdf", f"Report 2025 {word}"))
    assert run.doc(SITE + "/r.pdf")["doc_type"] != "10-K"

async def test_ac_52(...):   # home(("/taxonomy-report-2025.pdf", "Taxonomy Report 2025")) -> "10-K"
async def test_ac_81(...):   # home(("/irs.pdf", "Integrated Report 2025 Summary"))         -> != "10-K"
async def test_ac_83(...):   # home(("/ars.pdf", "Annual Report 2025 Summary"))             -> "10-K"
async def test_ac_21(...):   # home(("https://assets.cdn.example/r/ar.pdf", "Annual Report 2025")) -> "10-K"
async def test_ac_84(...):   # home(("https://assets.cdn.example/r/sr.pdf", "Sustainability Report 2025")) -> "sustainability_report"
async def test_ac_71(...):   # home(("https://reports.testwerke.de/ar-2025.pdf", "Annual Report 2025")) -> "10-K"

async def test_ac_22(...):   # home(("https://partner.example.com/page.html", "Partner"), ("https://partner.example.com/brochure.pdf", "Brochure"))
    assert run.count("https://partner.example.com/page.html") == 0
    assert run.count("https://partner.example.com/brochure.pdf") == 0

async def test_ac_89(...):   # home(("https://reports.testwerke.de/page.html", "Reports"))
    assert run.count("https://reports.testwerke.de/page.html") == 0

async def test_ac_68(...):   # home(("http://metadata.example.net/sr-2025.pdf", "Sustainability Report 2025"))
    assert run.host_count("metadata.example.net") == 0
```

(All rows `esef="none"`. `run.doc(url)` fails the test with a clear message when the URL is absent.)

- [ ] **Step 2: Run, expect failures** — `python3 -m pytest tests/test_report_finding_links.py -q`; AC-48, 49,
  21, 84, 71 fail (no phrase / off-site dropped).

- [ ] **Step 3: Implement in `crawler.py`**

- `_ANNUAL_EXTRA = ("integrated report", "universal registration document", "annual review", "geschäftsbericht",
  "geschaeftsbericht", "rapport annuel", "informe anual", "jaarverslag", "årsrapport")` and `_DEMOTION_WORDS`
  (the 16 above). Tokens: `re.findall(r"[^\W_]+", text.lower())`; a two-word demotion entry (`half-year`,
  `fact sheet`) matches consecutive tokens.
- `classify_link`: in the pattern loop, a `_DOC_TYPE_PATTERNS` match returns as today; at the
  `ANNUAL_REPORT_10K` entry, if none of its existing keywords match, an `_ANNUAL_EXTRA` phrase in the haystack
  returns `ANNUAL_REPORT_10K` unless `is_demoted(report_text(url, link_text))`. After the loop, before `OTHER`:
  when `expected_year` is given, `is_pdf(url)`, `"report"` in `report_text`, `years_in(report_text) & {expected_year - 1, expected_year}`
  and not demoted → `ANNUAL_REPORT_10K`.
- In `crawl_for_documents`, pass `config.expected_year`; an off-site href is kept only when
  `is_pdf(href) and classify_link(...) in (ANNUAL_REPORT_10K, SUSTAINABILITY_REPORT)` (`found.setdefault`), and is
  never queued; every other off-site href is dropped as today. Update the docstring ("never leaves the site"
  → its pages; report PDFs may be off-site).
- `pipeline.py`: `CrawlConfig(..., expected_year=today.year - 1)`.

- [ ] **Step 4: Run** — `ruff check . && python3 -m pytest tests/test_report_finding_links.py tests/test_crawler.py tests/test_crawler_unreachable.py tests/test_esef.py tests/test_doc_check.py -q` → all pass.

- [ ] **Step 5: Commit** — `git commit -m "Discovery: more annual-report names, year fallback, demotion words, off-site report PDFs"`

---

### Task 3: Report search and ranking

**Files:**
- Create: `backend/arp/discovery/report_finding.py`, `backend/tests/test_report_finding_search.py`
- Modify: `backend/arp/discovery/pipeline.py`

**Interfaces:**
- Consumes: `report_text`, `years_in`, `is_demoted`, `is_pdf`, `_same_site`, `CandidateDocumentLink` (crawler);
  `_esef_documents`'s current flag (Task 1).
- Produces (`report_finding.py`):
  - `SEARCH_MAX_RESULTS = 5`, `TOP_PER_TYPE = 2`
  - `report_query(name: str, doc_type: DocType, expected_year: int) -> str` — `'"{name}" annual report {y} filetype:pdf'`
    / `'"{name}" sustainability report {y} filetype:pdf'`, with `"` removed from `name`.
  - `async search_candidates(company: CompanyRef, client: WebSearchClient, expected_year: int, doc_types: list[DocType], *, delay: float, sleep) -> list[CandidateDocumentLink]`
  - `select_candidates(crawl: list[CandidateDocumentLink], search: list[CandidateDocumentLink], root_url: str | None, expected_year: int, *, skip_annual: bool) -> list[CandidateDocumentLink]`

- [ ] **Step 1: Write the failing tests** (all `esef="none"` unless noted; `A = ANNUAL_Q`, `S = SUST_Q`)

```python
async def test_ac_2(...):   # esef="current"
    assert run.queries == [S]
async def test_ac_3(...):   # esef="current", home(("/ar-2025.pdf", "Annual Report 2025"))
    assert run.count(SITE + "/ar-2025.pdf") == 0
async def test_ac_4(...):   # esef="current", home(("/sustainability-report-2025.pdf", "Sustainability Report 2025"))
    assert SITE + "/sustainability-report-2025.pdf" in run.docs()
async def test_ac_10_and_34(...):  # search={A: ["https://www.testwerke.de/about", "https://cdn.example.net/files/TW-AR-2025.pdf"]}
    assert run.doc("https://cdn.example.net/files/TW-AR-2025.pdf")["doc_type"] == "10-K"
    assert run.count("https://www.testwerke.de/about") == 0
async def test_ac_11_and_35(...):  # search=httpx.ConnectError("down"), home(("/ar-2025.pdf", "Annual Report 2025"))
    assert SITE + "/ar-2025.pdf" in run.docs() and run.manifest.failed_count == 0
async def test_ac_12(...):  # search={A: [SITE + "/ar-2025.pdf"]}, home(("/ar-2025.pdf", "Annual Report 2025"))
    assert run.count(SITE + "/ar-2025.pdf") == 1
async def test_ac_13_and_36(...):  # search={A: ["https://other.example.org/otherco-ar-2025.pdf"]},
                                   # routes: that URL -> pdf_response(tmp_path, "Otherco plc Annual Report 2025")
    assert run.doc("https://other.example.org/otherco-ar-2025.pdf")["company_match"] == "none"
    assert run.manifest.review_count == 1
async def test_ac_24_and_25(...):  # home(("/ar-2024.pdf","Annual Report 2024"), ("/ar-2023.pdf","Annual Report 2023"), ("/ar-2025.pdf","Annual Report 2025"))
    assert run.docs("10-K") == [SITE + "/ar-2025.pdf", SITE + "/ar-2024.pdf"]
    assert run.count(SITE + "/ar-2023.pdf") == 0
async def test_ac_26(...):  # esef="current", /sr-2023, /sr-2025, /sr-2024 "Sustainability Report <year>"
    assert run.docs("sustainability_report") == [SITE + "/sr-2025.pdf", SITE + "/sr-2024.pdf"]
async def test_ac_27(...):  # /ip-2023, /ip-2024, /ip-2025 "Investor Presentation <year>"
    assert sorted(run.docs("investor_presentation")) == [SITE + f"/ip-{y}.pdf" for y in (2023, 2024, 2025)]
async def test_ac_30(...):
    i = run.log.index(f"query {A}")
    assert run.log[i:i + 3] == [f"query {A}", "sleep 0.2", f"query {S}"]
async def test_ac_31(...):  # esef="old"            -> A in run.queries
async def test_ac_32(...):  # esef="error"          -> A in run.queries
async def test_ac_33(...):  # esef="current", esef_enabled=False -> A in run.queries
async def test_ac_39(...):  assert run.queries == [A, S]
async def test_ac_40_and_70(...):  # search={A: [f"https://x.example/f{i}.pdf" for i in 1..5] + ["https://x.example/f6-2025.pdf", "https://x.example/f7-2025.pdf"]}
    assert run.count("https://x.example/f1.pdf") == 1 and run.count("https://x.example/f2.pdf") == 1
    assert run.count("https://x.example/f6-2025.pdf") == 0 and run.count("https://x.example/f7-2025.pdf") == 0
    assert {m for _, m in run.search.calls} == {5}
async def test_ac_41(...):  # search={A: ["https://x.example/A.PDF", "https://x.example/b.pdf?dl=1", "https://x.example/c.pdf.html"]}
    assert run.count("https://x.example/A.PDF") == 1 and run.count("https://x.example/b.pdf?dl=1") == 1
    assert run.count("https://x.example/c.pdf.html") == 0
async def test_ac_43(...):  # routes={SITE + "/": httpx.Response(403)}, search={A: [SITE + "/ar-2025.pdf"]}
    assert SITE + "/ar-2025.pdf" in run.docs()
async def test_ac_45(...):  # search={A: [SITE + "/scan-2025.pdf"]}, routes: that URL -> image_pdf_response(tmp_path)
    assert run.doc(SITE + "/scan-2025.pdf")["company_match"] == "no_text" and run.manifest.review_count == 1
async def test_ac_46(...):  # esef=("2025-04-19", "https://filings.xbrl.org/w/edge-in.zip")  -> run.queries == [S]
async def test_ac_47(...):  # esef=("2025-04-18", "https://filings.xbrl.org/w/edge-out.zip") -> A in run.queries
async def test_ac_53(...):  # search={A: [SITE + "/ar-2024.pdf"]}, home(("/ar-2025.pdf", "Annual Report 2025"))
    assert run.docs("10-K") == [SITE + "/ar-2025.pdf", SITE + "/ar-2024.pdf"]
async def test_ac_54(...):  # search={A: ["https://cdn.example.net/ar-2025.pdf"]}, home /ar-2025-a.pdf, /ar-2025-b.pdf
    assert run.docs("10-K") == [SITE + "/ar-2025-a.pdf", SITE + "/ar-2025-b.pdf"]
    assert run.count("https://cdn.example.net/ar-2025.pdf") == 0
async def test_ac_66(...):  # search={A: ["http://metadata.example.net/ar-2025.pdf"]}
    assert run.host_count("metadata.example.net") == 0
async def test_ac_69(...):  # AC-66 search + home(("http://metadata.example.net/sr-2025.pdf", "Sustainability Report 2025"), ("/ar-2025.pdf", "Annual Report 2025"))
    assert SITE + "/ar-2025.pdf" in run.docs()
async def test_ac_72(...):  # company=W without website, wikidata=None, search={A: ["https://other.example/ar-2025.pdf"]}
    assert "https://other.example/ar-2025.pdf" in run.docs()
async def test_ac_73(...):  # company=W without website, wikidata="https://www.otherco.co.uk/",
                            # routes={"https://www.otherco.co.uk/": <html title "Otherco plc">}, search={A: [SITE + "/ar-2025.pdf"]}
    assert SITE + "/ar-2025.pdf" in run.docs()
async def test_ac_74(...):  # esef="old", home /ar-2025.pdf, /ar-2024.pdf
    assert run.docs("10-K") == ["https://filings.xbrl.org/w/2024.zip", SITE + "/ar-2025.pdf", SITE + "/ar-2024.pdf"]
async def test_ac_79_and_88(...):  # home(("/ar-2025.pdf", ...), ("https://cdn.example.net/ar-2025-cdn.pdf", ...)), search={A: ["https://search.example/ar-2025-s.pdf"]}
    assert run.docs("10-K") == [SITE + "/ar-2025.pdf", "https://cdn.example.net/ar-2025-cdn.pdf"]
    assert run.count("https://search.example/ar-2025-s.pdf") == 0
async def test_ac_80(...):  # home only cdn; search={A: [".../ar-2025-s.pdf", ".../ar-2025-t.pdf"]}
    assert run.docs("10-K") == ["https://cdn.example.net/ar-2025-cdn.pdf", "https://search.example/ar-2025-s.pdf"]
async def test_ac_82(...):  # search={A: [("https://x.example/ar-2025-summary.pdf", "Annual Report 2025 Summary")]}
    assert run.count("https://x.example/ar-2025-summary.pdf") == 0
async def test_ac_85(...):  # company cik="123", edgar=FakeEdgar(docs=[one 10-K SourceDocument])
    assert A in run.queries
async def test_ac_95(...):  # default_search=True, home(("/ar-2025.pdf", "Annual Report 2025"))
    assert SITE + "/ar-2025.pdf" in run.docs()
async def test_ac_96(...):  # esef="current", search={S: [SITE + "/sr-2025.pdf"]}
    assert run.doc(SITE + "/sr-2025.pdf")["doc_type"] == "sustainability_report"
async def test_only_requested_types_are_queried(...):   # Review Focus 4: doc_types=[DocType.ANNUAL_REPORT_10K]
    assert run.queries == [A]
def test_quotes_removed_from_query_name():               # Review Focus 5
    assert report_query('Foo "Bar" AG', DocType.ANNUAL_REPORT_10K, 2025) == '"Foo Bar AG" annual report 2025 filetype:pdf'
```

The harness `discover` needs a `doc_types` keyword for Review Focus 4 (pass-through to `execute_discovery_run`
and `create_discovery_run`).

- [ ] **Step 2: Run, expect failures** — `python3 -m pytest tests/test_report_finding_search.py -q`.

- [ ] **Step 3: Implement `report_finding.py`**

- `search_candidates`: for each type in `doc_types` (in the given order), `await sleep(delay)` before every query
  but the first; `results = (await client.search(query, max_results=SEARCH_MAX_RESULTS))[:SEARCH_MAX_RESULTS]`
  (the slice is what keeps AC-40's results 6–7 out when a client returns more); any exception → `logger.info`,
  no candidates for that query. A result is a candidate when `is_pdf(url)` and not
  `is_demoted(report_text(url, title))`; type = the query's, `link_text` = title.
- `select_candidates`: source rank crawl same-site (`_same_site(url, netloc of root_url)`) 0, crawl off-site 1,
  search 2. One entry per URL: the lowest source rank wins (its candidate, type included). Annual and
  sustainability each sorted by `(year bucket, source rank, discovery index)` and cut to `TOP_PER_TYPE`;
  year bucket from `years_in(report_text(url, link_text))`: `expected_year` → 0, `expected_year − 1` → 1, else 2.
  `skip_annual` drops every annual candidate. Return ranked annual + ranked sustainability + all other types in
  crawl order (unranked, uncut).

- [ ] **Step 4: Wire into `pipeline.py`**

After ESEF and before homepage resolution: `types = [t for t in (ANNUAL_REPORT_10K, SUSTAINABILITY_REPORT) if not doc_types or t in doc_types]`,
minus annual when ESEF is current; `search_cands = await search_candidates(company, search_client, expected_year, types, delay=settings.discovery_request_delay_seconds, sleep=sleep)`.
Replace the candidate list fed to the `doc_types` filter with
`select_candidates(crawl_cands, search_cands, homepage, expected_year, skip_annual=esef_current)`.

- [ ] **Step 5: Run** — `ruff check . && python3 -m pytest tests/test_report_finding_search.py tests/test_report_finding_esef.py tests/test_report_finding_links.py tests/test_discovery_homepage.py tests/test_known_reports.py tests/test_doc_check.py tests/test_discovery_pipeline_unreachable.py -q` → all pass.

- [ ] **Step 6: Commit** — `git commit -m "Discovery: DuckDuckGo report-PDF search, ranking and best-2 download"`

---

### Task 4: Sitemap seeding

**Files:**
- Modify: `backend/arp/discovery/crawler.py`
- Create: `backend/tests/test_report_finding_sitemap.py`

**Interfaces:**
- Consumes: `registrable_domain` (`arp.discovery.site_check`; no import cycle: site_check does not import crawler),
  `is_pdf`, `_same_site`, the `sleep` parameter (Task 1).
- Produces (`crawler.py`): `_RobotsCache.sitemaps(client, url, user_agent) -> list[str]` (the root origin's
  `RobotFileParser.site_maps()` or `[]`, fetching robots.txt if not yet cached);
  `async _sitemap_seeds(client, robots, root_url, config, sleep) -> list[str]`. Constants `_MAX_SITEMAPS = 3`,
  `_MAX_CHILD_SITEMAPS = 5`, `_MAX_SEEDS = 10`, `_MAX_SITEMAP_BYTES = 15_000_000`, `_SEED_HINTS` (the 10 strings
  of spec §3).

- [ ] **Step 1: Write the failing tests** (all `esef="none"`; `robots(*lines)` → `httpx.Response(200, text=...)`
  with `User-agent: *` plus the lines; `urlset(*paths)` / `index(*paths)` → sitemap XML with
  `xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"`, paths made absolute on `SITE`)

```python
AR_PAGE = page(("/ar-2025.pdf", "Annual Report 2025"))
SM14 = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/sm.xml"),
        SITE + "/sm.xml": urlset("/about.html", "/investors/annual-report.html"),
        SITE + "/investors/annual-report.html": AR_PAGE}

async def test_ac_14_and_37(...):  # routes=SM14
    assert SITE + "/ar-2025.pdf" in run.docs() and run.count(SITE + "/about.html") == 0
async def test_ac_15(...):  # robots without Sitemap; SITE + "/sitemap.xml" serves SM14's urlset  -> ar-2025 in docs
async def test_ac_16(...):  # index /sm-1.xml … /sm-7.xml, each urlset()
    reqs = [e for e in run.log if e.startswith(f"request {SITE}/sm-")]
    assert reqs == [f"request {SITE}/sm-{i}.xml" for i in range(1, 6)]
async def test_ac_17(...):  # index /sitemap-de.xml, /sitemap-energy.xml, /sitemap-en.xml
    -> child requests in order /sitemap-en.xml, /sitemap-de.xml, /sitemap-energy.xml
async def test_ac_18_and_38(...):  # sitemap Response(200, content=urlset bytes for /reports/a.html, headers={"Content-Length": "20000000"}); homepage AR_PAGE
    assert run.count(SITE + "/reports/a.html") == 0 and SITE + "/ar-2025.pdf" in run.docs()
async def test_ac_19(...):  # urlset /reports/r1.html … /reports/r15.html
    -> r1…r10 each count 1; r11…r15 count 0
async def test_ac_20(...):  # SM14 with robots also "Disallow: /investors/" -> count(/investors/annual-report.html) == 0
async def test_ac_55(...):  # robots Sitemap sm.xml and /sitemap.xml also served -> count(SITE + "/sitemap.xml") == 0
async def test_ac_56(...):  # index -> /sm-a.xml, which is index(/sm-a1.xml) -> count(/sm-a1.xml) == 0
async def test_ac_57(...):  # robots "Sitemap: https://other.example.com/sm.xml" -> count == 0
async def test_ac_58(...):  # urlset of 10 seeds /reports/s0.html…/reports/s9.html; fallback: SITE + "/" and every SITE
                            # path ending .html links 5 new unique /p/<n>.html pages (link text "More"); None otherwise
    pages = [e for e in run.log if e.startswith(f"request {SITE}/") and not e.endswith(("/robots.txt", "/sm.xml"))]
    assert len(pages) == 40
async def test_ac_59(...):  # sitemap body streamed without Content-Length (async generator, 16 × 1,000,000 bytes,
                            # the first chunk starting a urlset that lists /reports/a.html)  -> count == 0
async def test_ac_60(...):  # sitemap body "not xml", homepage AR_PAGE -> ar-2025 in docs
async def test_ac_61(...):  # robots "Sitemap: …/sm.xml.gz", gzip.compress(urlset("/investors/annual-report.html")), page links ar-2025 -> in docs
async def test_ac_62(...):  # routes=SM14
    for i, e in enumerate(run.log):
        if e in (f"request {SITE}/sm.xml", f"request {SITE}/investors/annual-report.html"):
            assert run.log[i - 1] == "sleep 0.2"
@pytest.mark.parametrize("hint", ["annual-report", "annual_report", "annualreport", "reports", "reporting",
                                  "investor", "sustainab", "integrated-report", "geschaeftsbericht", "nachhaltigkeit"])
async def test_ac_75(hint, ...):  # urlset(f"/x/{hint}/p.html") -> count(SITE + f"/x/{hint}/p.html") == 1
async def test_ac_76(...):  # urlset("/Investors/Annual-Report.html") -> count == 1
async def test_ac_77(...):  # robots sm-a.xml then sm-b.xml -> both requested, sm-a first
async def test_ac_78(...):  # robots "Disallow: /sm.xml" + "Sitemap: …/sm.xml" -> count(/sm.xml) == 0
async def test_ac_91(...):  # robots sm-1…sm-4 (empty urlsets) -> count(/sm-4.xml) == 0
async def test_ac_92(...):  # robots idx-a (a1,a2,a3) then idx-b (b1,b2,b3) -> a1,a2,a3,b1,b2 count 1; b3 count 0
async def test_ac_93(...):  # urlset /reports/1.html … /reports/9.html, /reports/aaaaaaaaaa.html, /reports/a/b.html
    assert run.count(SITE + "/reports/a/b.html") == 1 and run.count(SITE + "/reports/aaaaaaaaaa.html") == 0
async def test_ac_97_and_98(...):  # robots "Sitemap: https://internal.testwerke.de/sm.xml", homepage AR_PAGE
    assert run.host_count("internal.testwerke.de") == 0 and SITE + "/ar-2025.pdf" in run.docs()
async def test_corrupt_gzip_sitemap_is_skipped(...):     # Review Focus 2: sm.xml.gz body b"not gzip", homepage AR_PAGE -> ar-2025 in docs
async def test_sitemap_without_namespace_and_padded_loc(...):  # Review Focus 3:
    # "<urlset><url><loc>\n  https://www.testwerke.de/investors/annual-report.html\n</loc></url></urlset>" -> ar-2025 in docs
```

- [ ] **Step 2: Run, expect failures** — `python3 -m pytest tests/test_report_finding_sitemap.py -q`.

- [ ] **Step 3: Implement**

- `_fetch_sitemap(client, url, robots, config, sleep) -> bytes | None`: robots-disallowed → `None`; then
  `await sleep(config.request_delay_seconds)`; streamed GET; non-200 → `None`; `Content-Length` over
  `_MAX_SITEMAP_BYTES` → `None` before reading; stop and return `None` once bytes read pass the cap; a path ending
  `.gz` is decompressed with `gzip.GzipFile(...).read(_MAX_SITEMAP_BYTES + 1)` and over the cap → `None`.
  `httpx.HTTPError`, `UnsafeURLError`, `OSError`, `EOFError` → `None`.
- Parse with `etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))`; root local
  name `sitemapindex` = index; `<loc>` elements by local name, text stripped; `etree.XMLSyntaxError` → skip.
- `_sitemap_seeds`: top-level = `(await robots.sitemaps(...))[:_MAX_SITEMAPS]`, or `[origin + "/sitemap.xml"]`
  when robots lists none; drop any sitemap URL (top-level or child) whose `registrable_domain` differs from the
  root's. Fetch all top-level first; gather children of every index in order, stable-sort `en`-token paths first
  (tokens as in Global Constraints), fetch the first `_MAX_CHILD_SITEMAPS`; a child that parses as an index
  contributes nothing. Seeds: page URLs that are `_same_site`, not `is_pdf`, and whose lowercased path contains a
  `_SEED_HINTS` entry; deduped, stable-sorted by `len(path)`, first `_MAX_SEEDS`.
- `crawl_for_documents`: inside the client, before the loop, `queue = [(root_url, 0)] + [(s, 1) for s in seeds if s != root_url]`.
  Sitemap requests never touch `visited`.

- [ ] **Step 4: Run** — `ruff check . && python3 -m pytest tests/test_report_finding_sitemap.py tests/test_report_finding_links.py tests/test_report_finding_search.py tests/test_crawler.py tests/test_crawler_unreachable.py -q` → all pass.

- [ ] **Step 5: Commit** — `git commit -m "Discovery: seed the crawl from sitemap report pages"`

---

### Task 5: Whole-suite check and PR

**Files:** none new.

- [ ] **Step 1: Full backend suite** — `cd backend && ruff check . && python3 -m pytest -q -x` (Postgres up). Expected: all pass.
- [ ] **Step 2: Mutation check on the new code** — `python scripts/mutation_check.py --base origin/main`; any
  surviving mutant in `report_finding.py` or the new `crawler.py` code gets a test, or a line in the PR saying why not.
- [ ] **Step 3: Reviews** — `/ponytail:ponytail-review` and `/code-review` on the branch diff; fix findings.
- [ ] **Step 4: Push and open the PR against `main`** — title "Report finding: ESEF first, PDF search, sitemap
  seeds, best-2 ranking"; body has `Spec: report-finding-design`, label `risk:normal`, the two changed tests and
  why, `poll_esef_filings` now unused by the pipeline, and "openwiki/ needs an update (discovery flow and ESEF
  default)".
