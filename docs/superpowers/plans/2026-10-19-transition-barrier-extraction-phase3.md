# Transition Barriers Phase 3: Fact Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A derivation run fetches each cell's registered source documents, extracts each rule-book fact from them with the existing `extract_one_field` path, checks every value in code, and feeds the counted values to the phase 2 engine. A golden set measures extraction precision and coverage.

**Architecture:**
- **Fetching:** `fetching.py` downloads a source through the SSRF guard and parses it to per-page text (PDF) or one text block (HTML). `store.py` keeps fetched documents in a new `barrier_source_documents` table, so a fetch never touches `documents` or `companies`.
- **Extraction:** `extraction.py` maps a `FactDef` to a `FieldDefinition` and runs `extract_one_field` once per (fact, document). It then applies the spec's checks in their order (quote, number, unit, tier) and returns an `Extraction`.
- **Storage:** extractions go in a new `barrier_extractions` table, keyed so an unchanged document and fact definition are never sent to the model twice. Value ids therefore stay stable, and choices keep working.
- **Golden set:** `golden.py` runs the same extract-and-check path over a cases file.

**Tech Stack:** FastAPI, SQLAlchemy/Postgres (no migrations; `create_all`), httpx with `MockTransport` in tests, pypdf, the existing LangGraph `extract_one_field`, Typer, React/TS.

**Spec:** `docs/superpowers/specs/2026-10-17-transition-barrier-rule-book-design.md`. This plan uses sections 1 (Conversions), 2 (Documents, refresh flag), 3, 7 (`golden`) and 8, and the phase 3 rows:
- AC-9, AC-26–AC-34, AC-148
- AC-116, AC-137
- AC-122, AC-123

## Global Constraints

- The model extracts facts only. It never outputs a rating, a condition outcome or a confidence.
- Precision first: "not rated" is acceptable; a wrong figure that counts is not.
- Tests make no network calls and no model calls. Fetching uses an injected `httpx.MockTransport` and the model a stub LLM client. A DNS lookup counts as a network call.
- `ARP_TRANSITION_BARRIER_REFRESH_ENABLED` gates every request to a source. With it off, a derivation reads stored documents and analyst facts only, and notes `Sources not fetched: refresh is disabled`.
- A cell with no stored documents makes no model call and builds no model client (AC-11 stays green).
- A barrier source document never creates a company row (AC-116) and never writes into the data directory (AC-137).
- The check order and its reason strings are exact, in this order:
  1. `Quote not found in source`
  2. `Number not in quote`
  3. `Unit not convertible: <unit>` or `No <from> to <to> rate for <year> or earlier`
  4. `News cannot ground a fact`
- Display is at most two decimals, rounded half up, with trailing zeros dropped. A converted value shows as `<shown> (<extracted>)`, for example `9.37 USD/tCO2 (66.9 CNY/tCO2)`. Comparisons use the unrounded value.
- Request/response model changes follow the API contract steps in `.claude/CLAUDE.md`.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; `cd frontend && npm run lint && npx tsc -b && npm test`. Postgres tests need `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test`.

## Rulings (the spec leaves these open)

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| R1 | One `extract_one_field` call per (fact, document), not one per fact over all documents. | Two sources that disagree surface as the spec's conflict, instead of the model quietly picking one. "Several values for one fact (two sources, two editions)" needs one value per source. | Up to N× the model calls per fact (N = documents); bounded by R3's reuse and BM25's `require_hit`, which skips documents with no keyword hit. |
| R2 | Fetched documents get their own table `barrier_source_documents`; extractions get `barrier_extractions`. No new columns on phase 2 tables. | The repo has no migrations (`create_all` never alters a table), so new columns would be missing on a database created by phase 2. | Two extra tables. |
| R3 | An extraction is stored and reused, keyed by (code, region, fact, source document id, fact fingerprint). The fingerprint is the sha256 of the `FactDef` JSON plus `PROMPT_VERSION`. A `not_found` result is stored too. | A choice names value ids and holds "until a value appears that wasn't there". Re-extracting on every derivation would mint new ids and void every choice. It also stops a choice's re-derivation from paying for model calls again. | A wrong extraction stays until the document changes, the fact definition changes, or `PROMPT_VERSION` is bumped. |
| R4 | A document's as-of date comes from the HTTP `Last-Modified` header, else the PDF's `/CreationDate`, else the fetch date. A value's own as-of date (the extractor's `period_end`) overrides it, for confidence and for the conversion year. | It is deterministic, needs no model call, and the spec gives no source for "publication date". **Owner decision D1** below. | A server that resets `Last-Modified` makes an old document look fresh, giving `high` confidence where `medium` was right. |
| R5 | PDFs are parsed with pypdf (`facts.pdf_pages`), not Docling's `parse_file_to_text_with_pages`. HTML uses `ingestion.html_text.extract_html_text` and has no pages. | Uploads and fetches then find quote pages the same way, and Docling is heavy in tests and CI. The spec names the function only for "every quote gets a page", and pypdf pages satisfy that. | Complex PDF tables extract worse; Docling can be swapped in behind `fetching.parse` later. |
| R6 | `FieldDefinition.unit` is left None, and the instructions tell the model to give `unit_text` in the fact's unit form with only the currency swapped (`CNY/tCO2`). Code converts with the rule book's `conversions` and ignores `canonical_*`/`fx_rate`. | The spec says code converts "using the `conversions` table". The existing canonicaliser has its own FX and scaling. | A unit written differently (`USD per tonne`) fails as `Unit not convertible`, which is the precision-first outcome. |
| R7 | `seed_keywords` are the fact label's words of 4+ letters, lower-cased. `high_risk` stays False (one extraction plus one verifier call). | BM25 with `require_hit` needs keywords; without them chunks are taken in document order. The verifier already gives a second read. | Missed passages lower coverage; precision is unaffected. |
| R8 | `POST /derive` and the choices endpoint stay synchronous. Inside a run, extractions run concurrently (`asyncio.Semaphore(4)`). The model clients are built lazily through `derivation._llms(settings)`, only when an extraction is actually needed. | `schedule_llm_run` resolves an API key up front, which would break analyst-only derivations (AC-11). TestClient-based tests stay unchanged. | A first derivation over many cells holds the request for a while. A background run belongs with phase 4's 105-cell monthly search. |
| R9 | Fetch limits: 50 MB per document, 30 s timeout; only `application/pdf` and `text/html` are parsed. Anything else, any HTTP error and any SSRF refusal are skipped, with a result note `Not fetched: <source name> (<reason>)`. Sources with `url` None or `manual` true are skipped silently. | The spec says a refused URL is skipped. A failed fetch must not fail the run. | The note wording is mine (the spec leaves wording to the builder). |
| R10 | Golden runs treat the case document as tier `primary`, with the as-of date taken as in R4 from the file (PDF `/CreationDate`, else the run date). The cases file keeps exactly the spec's keys. | Golden measures extraction, not tiering. The builder picks labels whose conversion year cannot change the answer. | A currency label whose year is ambiguous could be scored wrong; the owner's label check catches it. |
| R11 | `precision` is 0 when no value counted. | Avoids dividing by zero, and fails safe. | — |

## Decisions for the owner

- **D1 (R4) — a fetched document's as-of date.** It drives `high` vs `medium` confidence and the conversion year.
  - Recommended: `Last-Modified`, else PDF `/CreationDate`, else the fetch date.
  - Alternative: one more model call per document version, which reads the publication date from the first two pages and is quote-checked like a fact. This is more accurate on republished PDFs, and costs one call per document and about half a day more.
- **D2 — golden set labels.** You check the ~40 labelled values and their pages before this PR merges, using `backend/tests/golden/transition_barrier/LABELS.md` (about two hours). This is already in the spec, restated here so the PR can't merge without it.

## Review Focus

1. **A scanned PDF with no text layer.** Every page extracts as "". Expected: no model call for that document, and a note `Not fetched: <name> (no text layer)`; it must not appear as a stored document with empty pages that the model is asked about. Test in Task 2.
2. **A source document that changes between derivations.** Expected: a new `barrier_source_documents` row; the old extractions are no longer read, the new document is extracted, and a choice made on the old value stops holding because a new value appeared. Test in Task 4.
3. **The same registered source both extracted and entered by an analyst.** Expected: both values count. If they agree, the rating stands. If they disagree, the result is a conflict and the analyst chooses. Test in Task 4.
4. **The model cites a passage it was not shown.** For example, the quote exists in the document but outside the retrieved passages. Expected: `Quote not found in source` (grounding with `passages`). Test in Task 3.
5. **A conversion row with a different target.** For example, CNY→EUR when the fact is in USD. Expected: `Unit not convertible: CNY/tCO2`, never a wrong-currency comparison. Test in Task 1.

---

## File map

| File | Responsibility |
|---|---|
| `backend/arp/transition_barrier/units.py` (new) | `convert`, pure. |
| `backend/arp/transition_barrier/engine.py` | `Value.extracted`; the clause shows `<shown> (<extracted>)`. |
| `backend/arp/transition_barrier/fetching.py` (new) | Fetch through the SSRF guard, parse, as-of. |
| `backend/arp/transition_barrier/extraction.py` (new) | FactDef→FieldDefinition, the per-document extract call, the checks. |
| `backend/arp/transition_barrier/golden.py` (new) | Cases, scoring, report. |
| `backend/arp/db/models.py` | `BarrierSourceDocument`, `BarrierExtraction`. |
| `backend/arp/transition_barrier/store.py` | Save and read fetched documents and extractions; `cell_values` merges extracted values; `add_choice` accepts extracted ids. |
| `backend/arp/transition_barrier/derivation.py` | Fetch (if refresh on), then extract, then derive; `not_counted` in the payload. |
| `backend/arp/cli/transition_barrier.py` | `golden` command. |
| `.github/workflows/golden-set.yml` | Runs `arp transition-barrier golden` on the golden set. |
| `frontend/src/pages/BarrierCellDetail.tsx`, `frontend/src/components/RunReviewList.tsx`, `frontend/src/lib/barrier.ts` | The extracted value in brackets, "extracted from the document", and not-counted reasons on the review item. |
| `backend/tests/transition_barrier_helpers.py` | `FactStub` (the extraction stub), `fetch_stub` (the fetch stub). |
| `backend/tests/golden/transition_barrier/` (new) | `cases.json`, documents, `LABELS.md`. |

---

### Task 1: Unit conversion and converted display

**Files:**
- Create: `backend/arp/transition_barrier/units.py`
- Modify: `backend/arp/transition_barrier/engine.py` (`Value`, `_entry`, the clause rendering)
- Test: `backend/tests/test_tb_units.py`, `backend/tests/test_tb_engine.py` (add one test)

**Interfaces:**
- Produces:
  - `convert(value: float, unit: str, fact_unit: str, year: int, conversions: list[dict]) -> tuple[float | None, str | None]` returns `(converted, None)` or `(None, reason)`.
  - `Value.extracted: str | None = None` is the value as extracted, shown in its source unit, and is set only when a conversion happened.
  - `engine._show` is unchanged.

- [ ] **Step 1: Write the failing tests** (`test_tb_units.py`). `RATES` is RB's conversions, CNY→USD 0.139 (2024) and 0.14 (2025), each with a `source`.

```python
def test_same_unit_passes_through():
    assert convert(72.0, "USD/tCO2", "USD/tCO2", 2026, RATES) == (72.0, None)

def test_latest_earlier_year_applies():          # AC-30
    v, r = convert(66.9, "CNY/tCO2", "USD/tCO2", 2026, RATES)
    assert r is None and math.isclose(v, 66.9 * 0.14)

def test_own_year_rate():                          # AC-32
    v, _ = convert(66.9, "CNY/tCO2", "USD/tCO2", 2024, RATES)
    assert math.isclose(v, 66.9 * 0.139)

def test_no_earlier_rate():                        # AC-33
    assert convert(66.9, "CNY/tCO2", "USD/tCO2", 2023, RATES) == (None, "No CNY to USD rate for 2023 or earlier")

def test_unknown_unit():                           # AC-34
    assert convert(66.9, "KRW/tCO2", "USD/tCO2", 2026, RATES) == (None, "Unit not convertible: KRW/tCO2")

def test_rate_to_another_currency_does_not_apply():  # Review Focus 5
    eur = [{"from": "CNY", "to": "EUR", "rate": 0.13, "year": 2025, "source": {"title": "x", "url": "y"}}]
    assert convert(66.9, "CNY/tCO2", "USD/tCO2", 2026, eur) == (None, "Unit not convertible: CNY/tCO2")

def test_denominator_must_match():
    assert convert(66.9, "CNY/t", "USD/tCO2", 2026, RATES) == (None, "Unit not convertible: CNY/t")
```

Engine test (`test_tb_engine.py::test_converted_value_shows_extracted_in_brackets`): build a `Value` with `value=66.9*0.14`, `unit="USD/tCO2"`, `extracted="66.9 CNY/tCO2"` and the D1 p. 17 citation, and derive with RB. Assert the `price` clause in `H` contains `9.37 USD/tCO2 (66.9 CNY/tCO2)`. Assert the `values[]` entry has `shown` `9.37 USD/tCO2` and `extracted` `66.9 CNY/tCO2`. Also assert that a value with `71.42*0.14` shows `10 USD/tCO2 (71.42 CNY/tCO2)`, and that the `M` condition `price >= p_material` is `fail` (AC-31: the comparison uses the unrounded 9.9988).

- [ ] **Step 2: Run them, expect FAIL** (`ImportError` / missing `extracted`): `cd backend && python3 -m pytest tests/test_tb_units.py tests/test_tb_engine.py -q`
- [ ] **Step 3: Implement `convert`.** Split the unit at the first `/`. The parts after the slash must be equal, and the numerator must match a row's `from` while the fact numerator matches its `to`. Take the row with the greatest `year` ≤ `year`. If rows exist for that pair but none is early enough, give the `No … rate` reason. If no row exists for the pair, give `Unit not convertible`.
- [ ] **Step 4: Engine.** Add `Value.extracted`. `_entry` sets `extracted` to `v.extracted or shown`. Wherever a clause renders a value's shown text, append ` ({v.extracted})` when it is set.
- [ ] **Step 5: Run, expect PASS**, plus the whole `tests/test_tb_engine.py` (no phase 2 row may change).
- [ ] **Step 6: Commit** `feat(tb): unit conversion from the rule book table, converted values shown with the extracted figure`

### Task 2: Fetching and stored source documents

**Files:**
- Create: `backend/arp/transition_barrier/fetching.py`
- Modify: `backend/arp/db/models.py` (add `BarrierSourceDocument`), `backend/arp/transition_barrier/store.py`
- Modify: `backend/tests/transition_barrier_helpers.py` (add `fetch_stub`)
- Test: `backend/tests/test_tb_fetching.py`

**Interfaces:**
- Produces:
  - `BarrierSourceDocument` table `barrier_source_documents`. Columns:
    - `id`
    - `source_key`, `url`
    - `title` (the source's `source_name`), `publisher`, `tier`
    - `as_of: date`, `content_key`, `content_type`
    - `page_texts: JSONB list[str]`, `html: bool`
    - `fetched_at`
  - `@dataclass Fetched(content: bytes, content_type: str, last_modified: date | None)`.
  - `async fetch(url: str, *, client: httpx.AsyncClient) -> Fetched`. It raises `FetchSkipped(reason)` for an SSRF refusal, an HTTP error, a type other than PDF/HTML, a body over 50 MB, or a PDF with no text layer.
  - `parse(fetched: Fetched) -> tuple[list[str], bool]` returns `(page_texts, html)`.
  - `doc_as_of(fetched: Fetched, today: date) -> date` follows R4.
  - `build_client() -> httpx.AsyncClient`, with the SSRF hook, `follow_redirects=True` and a 30 s timeout. Tests monkeypatch it.
  - `assert_safe = net_safety.assert_safe_fetch_target` is a module attribute, so tests can swap in a resolver-free check.
  - `async fetch_sources(sources: list[PrimarySource], today: date) -> list[str]` fetches each source (skipping `url` None and `manual`), saves it, and returns the result notes (R9).
  - `store.save_source_document(*, source_key, url, title, publisher, tier, as_of, content_key, content_type, page_texts, html) -> int` returns the existing id when the latest row for `source_key` has the same `content_key`. That makes a re-fetch of an unchanged document a no-op.
  - `store.latest_source_documents(source_keys: list[str]) -> list[dict]`: one row per key, the newest, in the order given.
- Test helper:
  - `fetch_stub(monkeypatch, served: dict[str, tuple[bytes, str, str | None]]) -> list[str]` installs a `MockTransport` client via `fetching.build_client`. `served` maps a URL to (body, content type, `Last-Modified`). The helper returns the list of requested URLs.
  - It also patches `fetching.assert_safe` to refuse only IP-literal private addresses, with no DNS.
  - D1–D3 are served from `fixture_pdf`, with `Last-Modified` set to their documents-table as-of dates.

- [ ] **Step 1: Write the failing tests** (`test_tb_fetching.py`, Postgres):
  - `test_fetch_stores_pages_and_as_of`: D1 is fetched, and its stored row has `page_texts[11]` containing `The effective carbon price was USD 72/tCO2.`, `as_of` 2026-03-31, tier `primary` and `html` False.
  - `test_refetch_unchanged_is_noop`: fetching twice leaves one row and returns the same id.
  - `test_changed_document_adds_row`: a second body gives two rows, and `latest_source_documents` returns the new one.
  - `test_html_has_one_text_block`: D2 is served as `text/html` with the p. 3 quote. The result is `html` True and `page_texts` has length 1.
  - `test_ssrf_refused_makes_no_request`: a source URL of `http://169.254.169.254/latest` makes no request, stores no row, and gives a note that starts `Not fetched:`.
  - `test_no_text_layer_skipped` (Review Focus 1): a PDF whose pages are all blank stores no row and gives the note `Not fetched: <name> (no text layer)`.
  - `test_fetch_creates_no_company` (AC-116): `select count(*) from companies` is unchanged after fetching D1.
  - `test_fetch_leaves_data_dir_untouched` (AC-137): copy F to tmp_path, point `ARP_TRANSITION_BARRIER_DATA_DIR` at it, fetch, and compare the sha256 of every file before and after.
- [ ] **Step 2: Run them, expect FAIL.**
- [ ] **Step 3: Implement the model, `fetching.py` and the two store functions.** `fetch` calls `assert_safe(url)` and then `client.get`, and streams with the 50 MB cap. The PDF `/CreationDate` comes from `PdfReader(...).metadata.creation_date`. The blob goes to the blob store under its sha256 (`upload_or_fail`).
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(tb): fetch registered sources through the SSRF guard into barrier_source_documents`

### Task 3: Extraction and the fact checks

**Files:**
- Create: `backend/arp/transition_barrier/extraction.py`
- Modify: `backend/tests/transition_barrier_helpers.py` (add `FactStub`)
- Test: `backend/tests/test_tb_extraction.py` (pure, no Postgres)

**Interfaces:**
- Consumes: `units.convert` (Task 1); the stored document dict (Task 2's columns).
- Produces:
  - `PROMPT_VERSION = "tb-extract-1"`.
  - `field_for(fact: FactDef, cell: str) -> FieldDefinition`.
    - `cell` is `"<sector>, <region>, <code>"`, for example `"Steel, European Union, STL-R1"`.
    - Types map number/boolean/enum/date to `FieldDataType` NUMBER/BOOLEAN/ENUM/DATE. `allowed_values` carries over. `seed_keywords` follow R7.
    - `extraction_instructions` = the definition + the R6 unit sentence + `Give the as-of date of the value in period_text when the source states one.`
  - `fingerprint(fact: FactDef) -> str`.
  - `source_document(doc: dict) -> SourceDocument`. `doc_id` is `f"tbsrc_{doc['id']}"`, `full_text` is the pages joined with `"\n"`, and `page_breaks` holds the page start offsets. An HTML document has `page_breaks=[]`.
  - `@dataclass Extraction`. Fields:
    - `value` (the rule-book-unit value, or the raw value when not counted) and `unit`
    - `extracted: str | None` (the source-unit shown text when converted)
    - `quote`, `page: int | None`, `locator: str | None`
    - `as_of: date | None` (the value's own as-of)
    - `counted: bool`, `reason: str | None`
  - `check(fact: FactDef, row: ExtractedField, doc: dict, conversions: list[dict]) -> Extraction | None`. It returns None for `not_found` and `not_applicable`. Otherwise the checks run in the Global Constraints order:
    - The quote is grounded when `row.grounded` and the first grounded citation exist. `page` is that citation's `page`, so the reported page is ignored (AC-148). `locator` is the citation's `location`.
    - The number check uses `arp.checks.numeric.candidates(quote)` on the raw source-unit value.
    - The conversion year is `as_of.year` if the row has `period_end`, else `doc["as_of"].year`.
    - The tier check is `doc["tier"] == "news"`.
  - `async extract(fact: FactDef, cell: str, doc: dict, conversions: list[dict], *, llm, verifier_llm, settings) -> Extraction | None` calls `extract_one_field(cell, field_for(...), documents=[sd], documents_by_id={sd.doc_id: sd}, llm=llm, verifier_llm=verifier_llm, settings=settings, fuzzy_threshold=settings.grounding_fuzzy_threshold, confidence_review_threshold=settings.confidence_review_threshold)` and passes `rows[0]` to `check`.
- Test helper:
  - `FactStub(answers: dict[tuple[str, str], PeriodValue | None])` is an `LLMClient`, the extraction stub.
  - Its `complete_structured` reads the field name (the fact id) and the shown `doc_id`/`passage_id` from the prompt. For `ExtractionDraft` it returns the scripted `PeriodValue` keyed by (fact id, document title), with each citation's `doc_id`/`passage_id` filled from the prompt, or an empty draft. For `VerifierOutput` it returns `agrees=True`.
  - It records `.calls`. A missing key means `not_found`, which is the spec's stub default.

- [ ] **Step 1: Write the failing tests** (`test_tb_extraction.py`). Each test builds the stored-document dict from `fixture_pdf` pages, with no DB, and calls `extract`.
  - `test_counted_value` gives value 72, unit `USD/tCO2`, page 12 and counted True.
  - AC-26: the quote `The effective carbon price was USD 99/tCO2.` appears in no passage. The result has counted False and reason `Quote not found in source`.
  - AC-28: value 72 with the D1 p. 4 quote gives reason `Number not in quote`.
  - AC-29: D4 (tier `news`) with value 72 and the p. 1 quote gives reason `News cannot ground a fact`.
  - AC-148: the p. 12 quote reported with citation `page=5` gives `page` 12.
  - AC-30, AC-32, AC-33, AC-34 (D1 pp. 17, 19; `period_text` `2024-06-30` / `2023-06-30` where the row says so) give `value`/`extracted`/`reason`, with the numbers from Task 1.
  - AC-9: D2 as HTML with `levy` true and citation `location="Art. 36"` gives `page` None, `locator` `Art. 36` and counted True.
  - `test_passage_not_shown` (Review Focus 4): the quote is in the document's text but outside the passages retrieval returned. Pad the document past `evidence_max_chunks` × chunk size with keyword-free text so the quote's chunk is dropped, or patch `field_evidence` to return one chunk without it. The result is `Quote not found in source`.
  - `test_not_found` returns None, and `FactStub.calls` shows one extraction call.
- [ ] **Step 2: Run them, expect FAIL.**
- [ ] **Step 3: Implement `extraction.py`.** First confirm, in `aggregator.build_extracted_fields`, how `unit_text` and `period_text` reach `ExtractedField.unit`/`period_end`, and script `FactStub` to match.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(tb): extract rule-book facts per document through extract_one_field, with code checks`

### Task 4: Derivation reads, fetches and extracts

**Files:**
- Modify: `backend/arp/db/models.py` (add `BarrierExtraction`), `backend/arp/transition_barrier/store.py`, `backend/arp/transition_barrier/derivation.py`
- Test: `backend/tests/test_tb_extraction_runs.py` (Postgres, via the API like `test_tb_derivation.py`)

**Interfaces:**
- Consumes: `fetching.fetch_sources`, `store.latest_source_documents` (Task 2); `extraction.extract`, `extraction.fingerprint`, `Extraction` (Task 3).
- Produces:
  - `BarrierExtraction` table `barrier_extractions`. Columns:
    - `id`
    - `code`, `region`, `fact`, `source_document_id` (FK), `fingerprint`
    - `found: bool`
    - `value` (JSONB), `unit`, `extracted`
    - `quote`, `page`, `locator`, `as_of`
    - `counted`, `reason`
    - `run_id`, `extracted_at`
    - Unique on (code, region, fact, source_document_id, fingerprint).
  - `store.extraction(code, region, fact, doc_id, fingerprint) -> dict | None` and `store.add_extraction(...) -> int`.
  - `store.cell_values` also returns one `Value` per found extraction of the cell's latest source documents. Each has:
    - `id=f"x{row.id}"` and `document=` the source title
    - `machine_checked=True`, `entered_by=None`
    - `confidence=fact_confidence(doc tier, row as_of or doc as_of, max_age_days, today, True)`
    - `counted`, `reason` and `extracted` from the row
  - These sort as registered-source values (registry order, then page).
  - `store.add_choice` accepts `x<id>` ids of counted extractions.
  - `derivation._llms(settings) -> tuple[LLMClient, LLMClient]` builds the clients with `build_llm_client` and `build_verifier_llm_client`. Tests monkeypatch it.
  - `execute_derivation_run` works in this order:
    1. If refresh is on, it fetches the run's distinct registered sources once and adds the fetch notes to the results.
    2. For each cell × fact × latest source document with no stored extraction, it runs `extract` concurrently (R8) and stores the result, building `_llms` only if there is at least one.
    3. It then runs the phase 2 loop unchanged.
  - The review payload gains `not_counted: list[str]`, one entry per uncounted value: `<fact label> = <shown> (<document>): <reason>`.

- [ ] **Step 1: Write the failing tests** (`test_tb_extraction_runs.py`). With refresh on, `fetch_stub` serves D1–D3, and `FactStub` is patched in via `derivation._llms`. Each test derives through `POST /derive` and reads `GET /cells/STL-R1/European Union`.
  - `test_extracted_defaults_rate_h`: `price` 72 (D1 p. 12), `applies` (D1 p. 4) and `levy` (D2 p. 3) extracted give rating `H`. The `H` detail equals AC-7's string.
  - AC-9: D2 is served as HTML and `levy` extracted with `Art. 36`. The `levy` clause is `Border levy in force = Yes (CBAM Regulation 2023/956, Art. 36): pass.`
  - AC-26/AC-27: the `price` value is not counted with `Quote not found in source`, and the rating is `not_rated`.
  - AC-28, AC-29 (D4 registered in a copied F), AC-148: these assert the latest result's `values[]` entry.
  - AC-30 gives rating `L` with the `price` clause containing `9.37 USD/tCO2 (66.9 CNY/tCO2)`. AC-31 gives `10 USD/tCO2 (71.42 CNY/tCO2)`, `M` `fail` and rating `L`. AC-32 gives `9.3 USD/tCO2 (66.9 CNY/tCO2)`. AC-33 and AC-34 assert their reasons.
  - `test_second_derivation_makes_no_model_call`: after one derivation, a second leaves `FactStub.calls` unchanged and keeps the same `x<id>` value ids.
  - `test_refresh_off_reads_stored_documents`: fetch with refresh on, then turn it off and derive. There is no request, the extraction is reused, and the note is `Sources not fetched: refresh is disabled`.
  - `test_no_documents_no_model_client` (AC-11, kept): `_llms` raises if called, and analyst facts alone give rating `H`.
  - `test_changed_document_voids_choice` (Review Focus 2):
    1. D1 and D3 disagree on `price` (72 vs 9), so the result is a conflict.
    2. A choice of the D1 value gives `H`.
    3. D1 is re-served with p. 14's text in place of p. 12's, so the new D1 version extracts 45.
    4. The cell is derived again. The result is a conflict again, because a value appeared that wasn't there.
  - `test_extracted_and_analyst_same_source` (Review Focus 3): an extracted D1 `price` of 72 plus an analyst D1 upload of 72 gives `H`. An analyst value of 30 instead gives a `conflict`.
  - `test_payload_lists_not_counted`: the review item's payload `not_counted` equals `["Effective carbon price = 72 USD/tCO2 (EU ETS Market Report 2026): Number not in quote"]` in AC-28's setup.
- [ ] **Step 2: Run them, expect FAIL.**
- [ ] **Step 3: Implement it.** `execute_derivation_run` stays sync, and runs the async fetch-and-extract step with `asyncio.run`. Update its docstring ("Pure code and database reads") and the `/derive` docstring.
- [ ] **Step 4: Run, expect PASS**, plus every `tests/test_tb_*.py` and `tests/test_api_transition_barrier.py`.
- [ ] **Step 5: API contract.** Run `python scripts/export_openapi.py` then `cd ../frontend && npm run gen:api`, and commit both if they changed.
- [ ] **Step 6: Commit** `feat(tb): derivation fetches sources and counts checked extracted values`

### Task 5: Screens show extracted values and why a value didn't count

**Files:**
- Modify: `frontend/src/pages/BarrierCellDetail.tsx`, `frontend/src/components/RunReviewList.tsx`, `frontend/src/lib/barrier.ts`
- Test: `frontend/tests/barrierCell.test.ts`

**Interfaces:**
- Consumes: `values[].extracted`, `values[].shown`, `values[].machine_checked`, `values[].entered_by`; payload `not_counted` (Task 4).
- Produces:
  - `valueText(v) -> string`, `<shown>` or `<shown> (<extracted>)` when they differ.
  - `sourceText(v) -> string`, which is one of:
    - `extracted from the document`, when machine-checked and `entered_by` is null;
    - `checked in the document`;
    - `entered by <name>`.

- [ ] **Step 1: Failing tests** for `valueText` (converted and plain) and `sourceText` (all three).
- [ ] **Step 2: Run** `cd frontend && npm test`, expect FAIL.
- [ ] **Step 3: Implement.** The cell detail's value cell and source cell use the two helpers. The review list shows a barrier item's `not_counted` lines under its current/proposed ratings, in the existing `error-text` style.
- [ ] **Step 4:** `npm run lint && npx tsc -b && npm test` pass.
- [ ] **Step 5:** Screenshot the cell detail and the review screen with Playwright, using one converted value and one not-counted value, then run `/impeccable:impeccable audit` on them and fix its findings.
- [ ] **Step 6: Commit** `feat(tb-ui): show extracted figures and why a value didn't count`

### Task 6: Golden runner and CLI

**Files:**
- Create: `backend/arp/transition_barrier/golden.py`
- Modify: `backend/arp/cli/transition_barrier.py` (the `golden` command), `.github/workflows/golden-set.yml`
- Test: `backend/tests/test_tb_golden.py` (pure)

**Interfaces:**
- Consumes: `extraction.extract`, `extraction.source_document`, `fetching.parse`, `fetching.doc_as_of` (Tasks 2–3).
- Produces:
  - `@dataclass Case(code, region, fact, document, value, unit, page)`.
  - `load_cases(path: Path) -> list[Case]`.
  - `async score(cases, documents_dir: Path, *, llm, verifier_llm, settings, today: date) -> tuple[float, float]` returns `(precision, coverage)`.
  - Each case:
    - parses its file (`.pdf` / `.html`) as tier `primary` (R10);
    - extracts the fact with the bundled (or `ARP_TRANSITION_BARRIER_DATA_DIR`) rule book;
    - is counted when `Extraction.counted`.
  - A counted value is correct when it matches the label (booleans and enums exactly, dates to the day, numbers at two decimals in the rule book's unit, rounded half up) and its `page` equals the label's `page`.
  - CLI: `arp transition-barrier golden --cases <file> --documents-dir <dir> --min-precision <x> --min-coverage <y>` prints `precision <p>, coverage <c>` (numbers formatted like `engine._show(x, None)`) and exits 0 only when both meet their minimum, else 1. The model clients come from `golden._llms(settings)`, which tests monkeypatch.

- [ ] **Step 1: Failing test, AC-122.**
  1. Write 4 cases on D1 pp. 4, 12, 13 and D2 p. 3 (fixture PDFs written to tmp_path).
  2. Script `FactStub` so 3 match their labels and 1 (`price` from p. 13) has the label value 31. All 4 still count.
  3. Run the CLI with `--min-precision 0.95 --min-coverage 0.5`.
  4. Assert stdout is `precision 0.75, coverage 1` and the exit code is 1.

  Also `test_golden_passes`: all 4 correct gives `precision 1, coverage 1` and exit 0. And `test_wrong_page_is_incorrect`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `golden.py` and the command.
- [ ] **Step 4: CI.** In `golden-set.yml`, add `backend/arp/transition_barrier/extraction.py`, `backend/arp/transition_barrier/golden.py` and `backend/tests/golden/transition_barrier/**` to the trigger paths and to the scope step. Add a step after the existing run: `arp transition-barrier golden --cases tests/golden/transition_barrier/cases.json --documents-dir tests/golden/transition_barrier/documents --min-precision 0.95 --min-coverage 0.5 | tee -a $GITHUB_STEP_SUMMARY`. It is skipped with a warning without `ARP_ANTHROPIC_API_KEY`, like the existing step.
- [ ] **Step 5: Run, expect PASS.**
- [ ] **Step 6: Commit** `feat(tb): golden set runner and arp transition-barrier golden`

### Task 7: Golden set G (labels for the owner to check)

**Files:**
- Create: `backend/tests/golden/transition_barrier/cases.json`, `backend/tests/golden/transition_barrier/documents/*`, `backend/tests/golden/transition_barrier/LABELS.md`

**Interfaces:**
- Consumes: the bundled rule book's facts (`backend/arp/transition_barrier/data/rule_book.json`) and Task 6's case format.

- [ ] **Step 1: Pick at least 12 documents** that the repo may store. Each is under 5 MB and has a text layer:
  - EUR-Lex acts and reports (Commission Decision 2011/833/EU reuse);
  - US federal documents (public domain);
  - UK legislation (OGL);
  - agency reports whose terms allow redistribution.

  Record each document's URL, licence basis and fetch date in `LABELS.md`.
- [ ] **Step 2: Draft at least 40 cases** across at least 12 documents and several criteria. Each case is a bundled rule-book fact for a real cell, with the value in the rule book's unit, and the page where its quote sits.
  - Prefer labels whose unit needs no currency conversion, or whose year is stated next to the figure (R10).
  - Include about 5 cases whose correct answer is absent from the document; they count against coverage only.
- [ ] **Step 3: Write `LABELS.md`**, with one row per case: cell, fact label, value, unit, document, page, and the exact quote. That is the sheet the owner checks (D2).
- [ ] **Step 4: Verify locally.** Every quote appears on its page (`fetching.parse` then a substring check, scripted in the test). Add `test_tb_golden.py::test_golden_set_shape`: at least 40 cases, at least 12 distinct documents, every `fact` exists in the bundled rule book for its `code`, and every document file exists.
- [ ] **Step 5: Commit** `test(tb): golden set G, drafted labels for the owner's check`

---

## Owed in the PR description

- The owner's check of the golden set labels (D2), before merge.
- G moves to the holdout repo once it is attached (spec section 8).
- AC-123 runs only with the `ARP_ANTHROPIC_API_KEY` secret. Without it the golden step warns and passes, so its result is real only when the secret exists.
- `openwiki/` needs a refresh (new extraction flow); `/context-refresh` handles it.
