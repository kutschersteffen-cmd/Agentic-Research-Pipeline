# Company Website and Report Identification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identify a company's website and reports by identifier first (Wikidata by LEI/ISIN, GLEIF), check every derived homepage and every downloaded PDF against the company, fetch 20-F/40-F, and stop re-downloading or re-announcing reports ARP already has.

**Architecture:** Five small new modules in `arp/discovery/` (`names`, `site_check`, `gleif`, `doc_check`, plus `homepage_from_ids` in `site_finder`), wired into the existing identity graph, discovery pipeline, downloader, change detector and EDGAR source. No new run types, settings or API models. All new network calls take an injectable `transport` and go through `ssrf_guard_request_hook`.

**Tech Stack:** Python 3.13, httpx, BeautifulSoup/lxml, pypdf, langgraph (identity graph), pytest + `httpx.MockTransport`; new: rapidfuzz, cleanco, tldextract. Test PDFs are generated with reportlab (already a dependency).

**Spec:** `docs/superpowers/specs/2026-10-18-company-site-and-report-identification-design.md` (AC-1 to AC-73). Every test named `test_ac_<n>_...` below implements that acceptance row exactly; read the row before writing the test.

## Global Constraints

- New deps in `backend/pyproject.toml` `dependencies`: `"rapidfuzz>=3.14,<4.0"`, `"cleanco>=2.3,<3.0"`, `"tldextract>=5.4,<6.0"`.
- `tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)`, one module-level instance; registrable domain = `.top_domain_under_public_suffix`.
- Every new outbound request: `event_hooks={"request": [ssrf_guard_request_hook]}`, the discovery user agent, imported at module level so tests can monkeypatch it (pattern: `tests/test_capture.py::_no_ssrf`).
- Wikidata, GLEIF and site-check failures never fail a company; they log at info and fall back.
- No new settings. Thresholds and `AGGREGATOR_DOMAINS` are module constants.
- Never delete or weaken an existing test. Test changes this plan requires are listed in Task 10's PR step.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; run `bash .claude/hooks/ensure-deps.sh backend` first.

## Review Focus

1. **Very short or generic names** ("3M", "AB Foods" → "AB"): `token_set_ratio` on a 2-letter name matches almost anything. Names of 3 characters or fewer after cleaning must match exactly. Test in Task 1.
2. **Accents and ligatures** ("Société Générale" vs "Societe Generale"): normalise with `unicodedata` NFKD and drop combining marks before matching. Test in Task 1.
3. **A homepage that isn't HTML** (the URL serves a PDF or an image): don't parse it; return `unclear` with `["fetch_failed"]`. Test in Task 2.
4. **A corrupt or encrypted PDF**: pypdf raises; the document check returns `company_match` `"no_text"` and never fails the download. Test in Task 7.
5. **A `304` for a URL with no manifest entry** (misbehaving server): no stored copy to reuse, so the document is skipped and logged, never emitted with empty fields. Test in Task 9.

---

### Task 1: Dependencies and name matching

**Files:**
- Modify: `backend/pyproject.toml` (dependencies list)
- Create: `backend/arp/discovery/names.py`
- Test: `backend/tests/test_discovery_names.py`

**Interfaces:**
- Produces: `clean_name(name: str) -> str` (cleanco `basename`, NFKD + combining marks dropped, lowercased, punctuation collapsed to single spaces, stripped); `names_match(a: str, b: str) -> bool` (`clean_name` both; if either cleaned side has ≤ 3 characters, exact equality; else `rapidfuzz.fuzz.token_set_ratio >= 90`). `NAME_MATCH_THRESHOLD = 90`.

- [ ] **Step 1: Add the three deps to `pyproject.toml`, then `pip install -e ".[dev]"` in `backend`.**
- [ ] **Step 2: Write the failing tests**

```python
def test_names_match_ignores_legal_suffix_and_case():
    assert names_match("Testwerke AG", "TESTWERKE")
    assert names_match("Testwerke AG", "Testwerke")
def test_names_match_rejects_other_company():
    assert not names_match("Testwerke AG", "Otherco plc")
def test_names_match_accents():
    assert names_match("Société Générale S.A.", "Societe Generale")
def test_names_match_short_names_need_exact():
    assert names_match("3M Company", "3M")
    assert not names_match("AB Foods", "ABB")
```

- [ ] **Step 3: Run** `python3 -m pytest tests/test_discovery_names.py -v` → FAIL (module missing).
- [ ] **Step 4: Implement `names.py`.**
- [ ] **Step 5: Run again** → PASS; `ruff check arp/discovery/names.py`.
- [ ] **Step 6: Commit** `feat(discovery): name matching for site and document checks`.

### Task 2: Homepage ownership check

**Files:**
- Create: `backend/arp/discovery/site_check.py`
- Test: `backend/tests/test_site_check.py`

**Interfaces:**
- Consumes: `names_match` (Task 1); `ssrf_guard_request_hook`, `UnsafeURLError` from `arp.net_safety`.
- Produces:
  - `AGGREGATOR_DOMAINS: frozenset[str]` (the 23 domains in the spec, verbatim).
  - `registrable_domain(url: str) -> str`.
  - `is_aggregator(url: str) -> bool`.
  - `class SiteCheck(BaseModel): verdict: Literal["owned", "unclear", "rejected"]; evidence: list[str]`.
  - `async def check_homepage(url: str, company: CompanyRef, user_agent: str, *, transport: httpx.AsyncBaseTransport | None = None) -> SiteCheck`.

Approach: one `httpx.AsyncClient(follow_redirects=False, timeout=15, headers UA, ssrf hook, transport)`; follow redirects by hand up to 5 hops, checking `is_aggregator` on each `Location` before requesting it. Evidence codes and verdict rule exactly as the spec's "Site check" section; evidence is a de-duplicated list in discovery order. Imprint link regex `impressum|imprint|legal notice|mentions légales|legal information` on link text, same registrable domain as the final URL. JSON-LD: every `<script type="application/ld+json">`, `json.loads`, walk dicts and lists, `@type` containing `Organization` or ending in `Corporation`/`Company`; a parse error skips that block. A non-`text/html` homepage response → `unclear`, `["fetch_failed"]` (Review Focus 3).

- [ ] **Step 1: Write the failing tests** `test_ac_1_owned_by_lei_on_imprint`, `test_ac_2_aggregator_rejected`, `test_ac_3_aggregator_no_request`, `test_ac_4_aggregator_subdomain`, `test_ac_5_other_company_rejected`, `test_ac_6_name_in_title_unclear`, `test_ac_7_title_case_and_suffix`, `test_ac_8_connect_error`, `test_ac_9_no_suffix_list_fetch`, `test_ac_48_imprint_failure_ignored`, `test_ac_49_homepage_404`, `test_ac_52_redirect_followed`, `test_ac_53_imprint_on_subdomain`, `test_ac_54_redirect_to_aggregator_rejected`, `test_ac_55_redirect_to_aggregator_not_requested`, `test_non_html_homepage_is_fetch_failed`. Fixtures W, H1–H4 as module constants built from the spec's fixture list; a `MockTransport` handler that records every request URL. Autouse fixture monkeypatches `site_check.ssrf_guard_request_hook` to a no-op. AC-9 patches `socket.socket.connect` with a recorder that raises, sets `TLDEXTRACT_CACHE` to `tmp_path`, and asserts the recorder's call count is 0.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_site_check.py -v` → FAIL.
- [ ] **Step 3: Implement `site_check.py`.**
- [ ] **Step 4: Run** → PASS; ruff clean.
- [ ] **Step 5: Commit** `feat(discovery): homepage ownership check`.

### Task 3: Wikidata by identifier, search skips aggregators

**Files:**
- Modify: `backend/arp/discovery/site_finder.py` (`homepage_from_cik` → `homepage_from_ids`; `resolve_company_homepage`)
- Modify: `backend/arp/discovery/pipeline.py:10,35` (import and call; full rewiring is Task 8)
- Modify: `backend/tests/test_discovery_pipeline_unreachable.py:107` (monkeypatch target renamed)
- Test: `backend/tests/test_site_finder_ids.py`

**Interfaces:**
- Produces: `async def homepage_from_ids(user_agent: str, *, lei: str | None = None, isin: str | None = None, cik: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> str | None`. Tries P1278 (LEI, if `lei_is_valid(normalise_lei(lei))`), P946 (ISIN, if `normalise_identifier("ISIN", isin)` is truthy), P5531 (CIK, digits only, zero-padded to 10), one request each, in that order, and returns at the first identifier with any P856 result: the shortest URL. `homepage_from_cik` is removed and its caller moves to `homepage_from_ids(..., cik=company.cik)` for now.
- `resolve_company_homepage` drops results where `site_check.is_aggregator(r.url)` before the IR-hint/first-result rule.

- [ ] **Step 1: Failing tests** `test_ac_10_shortest_p856_wins`, `test_ac_11_lei_then_isin`, `test_ac_12_invalid_ids_no_request`, `test_ac_42_single_p1278_query` (assert the decoded `query` param contains `wdt:P1278 "5299009TESTWERKE0063"`), and `test_search_skips_aggregator_results` (search returns `[marketscreener URL, testwerke URL]` → returns the testwerke URL).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement; update the pipeline call and the monkeypatch target in `test_discovery_pipeline_unreachable.py`.**
- [ ] **Step 4: Run** `python3 -m pytest tests/test_site_finder_ids.py tests/test_discovery_pipeline_unreachable.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(discovery): Wikidata homepage by LEI/ISIN/CIK`.

### Task 4: GLEIF client

**Files:**
- Create: `backend/arp/discovery/gleif.py`
- Modify: `backend/arp/schemas/discovery.py` (add `GleifMatch`)
- Test: `backend/tests/test_gleif.py`

**Interfaces:**
- Produces: `class GleifMatch(BaseModel): lei: str; legal_name: str; country: str | None = None` (in `schemas/discovery.py`); `async def lei_for_isin(client: httpx.AsyncClient, isin: str) -> str | None`; `async def name_matches(client: httpx.AsyncClient, name: str, limit: int = 5) -> list[GleifMatch]`; `GLEIF_API = "https://api.gleif.org/api/v1"`. Filters to `attributes.registration.status == "ISSUED"`; `country` from `attributes.entity.legalAddress.country`. Pass query values via `params=` (URL-encoded). Any `httpx.HTTPError`, `ValueError` or `KeyError` → `None` / `[]`, logged at info.

- [ ] **Step 1: Failing tests** `test_lei_for_isin_single_issued`, `test_lei_for_isin_two_records_is_none`, `test_lei_for_isin_lapsed_is_none`, `test_name_matches_issued_only_max_5`, `test_gleif_error_returns_empty`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (check the live API docs for the name-search endpoint; the spec leaves it to you). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(discovery): GLEIF ISIN→LEI and name search`.

### Task 5: Identity run — derived LEI, Wikidata + site check, GLEIF signals, resolved LEI

**Files:**
- Modify: `backend/arp/discovery/identity_graph.py`, `identity_agents.py`, `identity_pipeline.py`
- Modify: `backend/arp/schemas/discovery.py` (`IdentitySignals.gleif_matches: list[GleifMatch] = []`; `IdentityAdjudication.resolved_lei: str | None = None`; `IdentityResolutionResult.derived_lei: str | None = None`, `resolved_lei: str | None = None`)
- Test: `backend/tests/test_identity_lookups.py`

**Interfaces:**
- Consumes: `homepage_from_ids` (T3), `check_homepage`/`SiteCheck` (T2), `lei_for_isin`/`name_matches`/`GleifMatch` (T4).
- Produces: `resolve_company_identity(..., lookup_user_agent: str | None = None, transport: httpx.AsyncBaseTransport | None = None)`. With `lookup_user_agent=None` every new lookup is skipped and behaviour is exactly `main` (keeps existing tests offline and unchanged). `gather_signals(..., gleif_client: httpx.AsyncClient | None = None)`. `execute_identity_run` passes `lookup_user_agent=settings.discovery_user_agent`.

Behaviour (spec "Identity run" section):
1. `_check_known`: no LEI + valid ISIN + lookups on → `lei_for_isin`; store `derived_lei` in state. `_apply_rules` runs the rules on `company.model_copy(update={"lei": derived_lei})`; `identifiers_of` keeps using the supplied company.
2. `_apply_rules` `lookup` case (identifier rule, neither website nor CIK supplied) with lookups on: `homepage_from_ids(lei, isin)` then `check_homepage`. `owned` → finalize `resolved`, unflagged, confidence 1.0, `resolved_website` set; `unclear` → `uncertain`, flagged, `match_ambiguous`, `resolved_website` set; otherwise today's path.
3. `gather_signals` adds `gleif_matches`; `_format_signals` prints `GLEIF matches:` then `  - lei=<lei> name=<legal_name!r> country=<country>` per match, or `GLEIF matches: none found`.
4. `_adjudicate` drops `resolved_lei` not in `{m.lei for m in signals.gleif_matches}` and downgrades to `uncertain`, like CIK.
5. `_finalize`: if `resolved_lei` and no `resolved_website` and lookups on → `homepage_from_ids(lei=…)` + `check_homepage`; `owned`/`unclear` sets `resolved_website`. Verdict, confidence, `match_rule` `ambiguous`, `flagged_for_review` true are unchanged.
6. `enriched_universe`: `lei=result.identifiers.get("lei") or result.derived_lei or result.resolved_lei`.

- [ ] **Step 1: Failing tests** `test_ac_13_isin_to_derived_lei`, `test_ac_14_isin_without_gleif_hit`, `test_ac_15_wikidata_owned_resolves`, `test_ac_16_wikidata_unclear_flags`, `test_ac_17_no_wikidata_hit_as_main`, `test_ac_18_gleif_line_in_prompt`, `test_ac_19_unverified_lei_dropped`, `test_ac_20_resolved_lei_fills_website`, `test_ac_21_enriched_universe_exports_lei` (records an `approve` decision with the review-queue helpers `tests/test_identity_pipeline.py` already uses), `test_ac_22_supplied_values_as_main`, `test_ac_43_owned_path_zero_prompts`, `test_ac_44_supplied_zero_lookups`, `test_ac_45_one_prompt`, `test_ac_47_supplied_cik_as_main`, `test_ac_50_no_hit_zero_prompts`, `test_ac_51_supplied_cik_no_wikidata`. One `MockTransport` routes Wikidata, GLEIF and H1/H4 by host and records requests; use the `fake_llm` fixture (`.prompts`, `.calls`) and the existing `_FakeEdgar`/`_NullSearch` pattern from `tests/test_identity_graph.py`. Monkeypatch the SSRF hook in `site_check`, `site_finder` and `identity_graph` (wherever the GLEIF client is built).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_identity_lookups.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus `tests/test_identity_graph.py tests/test_identity_pipeline.py tests/test_identity_agents.py tests/test_match_rules.py tests/test_review_identity.py` → all PASS, existing ones unchanged.
- [ ] **Step 5: Commit** `feat(identity): identifier-first website lookup and GLEIF signals`.

### Task 6: EDGAR annual forms and ticker gate

**Files:**
- Modify: `backend/arp/ingestion/edgar.py` (`fetch`, around lines 107–124)
- Test: `backend/tests/test_edgar_forms.py`

**Interfaces:**
- Produces: `ANNUAL_FORMS = ("10-K", "20-F", "40-F")`; for the `"10-K"` wanted form, `idx` = first index whose form is in `ANNUAL_FORMS`; title uses `forms[idx]`; `doc_type` stays `DocType.ANNUAL_REPORT_10K`. `_US_COUNTRIES = {"us", "usa", "united states"}`; ticker → CIK only when `not company.country or company.country.strip().lower() in _US_COUNTRIES`.

- [ ] **Step 1: Failing tests** `test_ac_33_20f`, `test_ac_34_40f`, `test_ac_35_amendment_skipped`, `test_ac_36_non_us_ticker_no_request`, `test_ac_37_empty_country_resolves`, `test_ac_38_lowercase_us_resolves`. Follow the fake-HTTP setup in `tests/test_edgar.py`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new file plus `tests/test_edgar.py tests/test_edgar_cache.py tests/test_edgar_annual_original.py` → PASS.
- [ ] **Step 5: Commit** `feat(edgar): 20-F/40-F annual reports, US-only ticker lookup`.

### Task 7: Document check on downloaded PDFs

**Files:**
- Create: `backend/arp/discovery/doc_check.py`
- Modify: `backend/arp/schemas/discovery.py` (`DiscoveredDocument`: `company_match: Literal["identifier", "name", "none", "no_text"] | None = None`, `page_count: int | None = None`, `reporting_year: int | None = None`)
- Modify: `backend/arp/discovery/downloader.py` (run the check after writing a `.pdf`)
- Modify: `backend/arp/discovery/pipeline.py` (`_on_success` review count)
- Create: `backend/tests/pdf_fixtures.py` (reportlab builders for P1–P4)
- Test: `backend/tests/test_doc_check.py`

**Interfaces:**
- Consumes: `names_match`, `clean_name` (T1); `doc_identity.reporting_year`.
- Produces: `class DocCheck(NamedTuple): company_match: str; page_count: int | None; reporting_year: int | None`; `def check_document(path: Path, company: CompanyRef) -> DocCheck`; `PAGES_HEAD = 5`, `PAGES_TAIL = 10`, `MIN_TEXT_CHARS = 200`. Any pypdf exception → `DocCheck("no_text", None, None)` (Review Focus 4). Pipeline: `review_delta = 1 if not result.documents_found or any(d.company_match in ("none", "no_text") for d in result.documents_found) else 0`.
- `tests/pdf_fixtures.py`: `make_pdf(path, pages: list[str], n_pages=30) -> Path` (text per page, blank beyond the list) and `make_image_pdf(path, n_pages=30) -> Path` (one drawn rectangle per page, no text).

- [ ] **Step 1: Failing unit tests** `test_check_identifier`, `test_check_name`, `test_check_none`, `test_check_no_text`, `test_check_corrupt_pdf_is_no_text` against P1–P4 and a truncated file.
- [ ] **Step 2: Failing pipeline tests** `test_ac_27` to `test_ac_32`, `test_ac_39`, `test_ac_40`, `test_ac_41`: run `execute_discovery_run` (needs the `pg` fixture, as in `test_discovery_pipeline_unreachable.py`) for W with supplied website `https://www.testwerke.de/` and a transport serving the homepage and P1–P4 (crawl transport comes from Task 8; until then monkeypatch `pipeline_module.crawl_for_documents` to return the candidate links and pass the transport to `download_documents` through a monkeypatched wrapper).
- [ ] **Step 3: Run** → FAIL. **Step 4: Implement.** **Step 5: Run** the new files plus `tests/test_capture.py tests/test_esef.py tests/test_discovery_pipeline_unreachable.py` → PASS.
- [ ] **Step 6: Commit** `feat(discovery): check downloaded PDFs name the company`.

### Task 8: Discovery pipeline — derived homepages are checked

**Files:**
- Modify: `backend/arp/discovery/pipeline.py` (`_discover_for_company`)
- Modify: `backend/arp/discovery/crawler.py` (`crawl_for_documents(root_url, config, *, transport=None)`)
- Modify: `backend/arp/schemas/discovery.py` (`DiscoveryCompanyResult.homepage_check: SiteCheck | None = None`; import `SiteCheck` from `site_check`, or move the model into `schemas/discovery.py` and re-export it from `site_check` if the import cycles)
- Test: `backend/tests/test_discovery_homepage.py`

**Interfaces:**
- Consumes: `homepage_from_ids` (T3), `check_homepage` (T2).
- Produces: `_discover_for_company(..., transport: httpx.AsyncBaseTransport | None = None)`, passed to `homepage_from_ids`, `check_homepage`, `crawl_for_documents` and `download_documents`. Order: supplied website (no check) → `homepage_from_ids(lei, isin, cik)` → `resolve_company_homepage` → `check_homepage`. `rejected` → `homepage_used=None`, no crawl, `homepage_check` set, `documents_found` = EDGAR filings. Also simplify Task 7's test workaround to pass `transport` directly.

- [ ] **Step 1: Failing tests** `test_ac_23_search_skips_aggregator`, `test_ac_24_rejected_not_crawled`, `test_ac_25_supplied_not_checked`, `test_ac_26_unclear_crawled`, `test_ac_46_supplied_cik_homepage_checked`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new file, Task 7's tests and `tests/test_crawler.py tests/test_crawler_unreachable.py tests/test_discovery_pipeline_unreachable.py` → PASS.
- [ ] **Step 5: Commit** `feat(discovery): check derived homepages before crawling`.

### Task 9: Conditional GET and URL aliases

**Files:**
- Modify: `backend/arp/discovery/change_detector.py` (`known_documents`, alias logic in `diff_and_record`)
- Modify: `backend/arp/discovery/downloader.py` (`download_documents(..., known: dict[str, DiscoveredDocument] | None = None)`)
- Modify: `backend/arp/discovery/pipeline.py` (pass `change_detector.known_documents(company.company_id)`)
- Modify: `backend/arp/schemas/discovery.py` (`DiscoveredDocument.alias_of: str | None = None`)
- Test: `backend/tests/test_known_reports.py`

**Interfaces:**
- Produces: `ChangeDetector.known_documents(company_id: str) -> dict[str, DiscoveredDocument]` (manifest entries parsed with `DiscoveredDocument.model_validate`; unparseable entries skipped).
- Downloader: with a `known[url]`, send `If-None-Match` / `If-Modified-Since` from its `http_etag` / `http_last_modified` (verbatim, only those present). On `304`: if `store.exists(prior.sha256)` and `Path(prior.local_path).exists()`, append `CaptureRecord(trigger, url_chain=[url], status=304, headers, content_key=prior.sha256, storage_uri=store.uri(prior.sha256), rights_tag, collected=True)` and emit `prior.model_copy(update={"capture_id": record.capture_id, "discovered_at": now_iso(), "alias_of": None})`; else re-`GET` with no conditional headers and treat it as a fresh download. A `304` with no `known[url]` → log and skip (Review Focus 5).
- Change detector: before `manifest.get(doc.url)`, for an unknown URL look for an entry with the same `sha256` (iterating the manifest as updated so far this call); if found, set `doc.alias_of = <that url>` on the object (so `documents_found` carries it), write the manifest entry, no event.

- [ ] **Step 1: Failing tests** `test_ac_56` to `test_ac_73` (AC-56–64, 65–67 two-run setup: two `execute_discovery_run` calls sharing `Settings` dirs; AC-61/62/68 delete the blob from the local store between runs; AC-69/70 delete `local_path`; AC-72/73 one run, `/a.pdf` handler sleeps 0.05 s), plus `test_304_without_known_entry_skipped`. Keep the existing `tests/test_change_detector.py` and `tests/test_event_refresh.py` cases untouched.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new file plus `tests/test_change_detector.py tests/test_event_refresh.py tests/test_capture.py tests/test_extraction_pre_steps.py` → PASS.
- [ ] **Step 5: Commit** `feat(discovery): reuse unchanged reports, alias moved URLs`.

### Task 10: Full checks and PR

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest -q` → all pass (the `emerging_themes` extra must be installed for `test_emerging_themes_clustering`).
- [ ] **Step 2:** Mutation check on the changed files: `pip install mutmut==3.8.0 && python scripts/mutation_check.py --base origin/main`; strengthen any test that lets a mutant in the new modules survive.
- [ ] **Step 3:** `/ponytail:ponytail-review` and `/code-review` on the branch; fix findings.
- [ ] **Step 4:** Merge `origin/main` into the branch, push, open the PR against `main` with `Spec: company-site-and-report-identification`, a `risk:` label per `.claude/skills/steward/SKILL.md`, the AC list marked `unit`, and the test changes listed (only the renamed monkeypatch target in `tests/test_discovery_pipeline_unreachable.py`).
