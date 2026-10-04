# Step 2: Capture, Document Identity, Intake, Typed Values, Versioned Fields, Grounding Evidence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every collected document has a capture record and a verified stored copy, passes intake checks and carries a document identity, and every extracted value has a value state, a unit, a period and a basis, belongs to a versioned field definition, and is bound to the exact passage and character span it came from.

**Architecture:**
- Capture: the downloader writes the bytes to a blob store before anything else. The store is local by default, with S3 optional. The downloader then reads the bytes back and checks the hash, and only then counts the document as collected.
- Intake and identity: `LocalFileDocumentSource.fetch` is the one point every document passes through, so intake checks and the identity rules run there.
- Extraction: the extractor returns one `PeriodValue` per reported period, as text. Code turns the text into typed values through versioned CSV tables under `arp/normalise/tables/`. Each period becomes its own `ExtractedField` row in the record, with the latest period first.
- Grounding: grounding returns a `Match` carrying the span, and accepts a quote only inside a passage the model was shown.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, stdlib `csv`/`datetime`/`zipfile`/`hashlib`/`unicodedata`, pypdf and reportlab (already dependencies), httpx `MockTransport` for tests; React + TypeScript (Vite), node test runner.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4`. This step covers E26, E27, E28, E6, E8, E30, E43, E44, E46 and E47. Paths are relative to `backend/` unless they start with `frontend/`. It builds on step 1 (`docs/superpowers/plans/2026-10-03-step1-identity-review-keys.md`), which is already on `main`.

## Global Constraints

- No new dependencies, backend or frontend. Use the stdlib plus what `pyproject.toml` and `package.json` already list. PDF checks use `pypdf`. Test PDFs are built with `reportlab` (text) and `pypdf.PdfWriter.add_blank_page` (no text layer).
- No OCR engine is added. A PDF without a text layer goes to state `ocr_needed` and is not parsed.
- **Voting is frozen.** Do not change `arp/api/routers/voting.py`, `arp/voting/`, `arp/cli/voting.py`, `arp/stewardship/voting_feed.py`, `frontend/src/components/BallotReview.tsx`, `ReviewerField.tsx`, `ConfirmDecision.tsx`, the voting pages, or any voting test.
- Old run directories, old `results.jsonl` rows, old `schema.json` snapshots, old `content.db` files and old cached parses must still load. Every new model field has a default. New SQLite columns are added with an idempotent `ALTER TABLE`.
- Identity stays LEI-keyed through `issuer_key()` in `arp/schemas/issuer.py`. Review `item_key` stays `"{issuer_key}:{field_id}:{period}"`.
- Period in the item key is the value's `period_end` as an ISO date (`YYYY-MM-DD`) when resolved, else the literal `unspecified`. Old rows have no `period_end`, so they keep `unspecified`, which is exactly their step-1 key.
- Value states (exact strings): `found`, `not_found`, `not_applicable`, `zero`.
- Field status (exact strings): `draft`, `released`, `retired`.
- `match_method` (exact strings): `exact`, `normalised`, `fuzzy`.
- Intake states (exact strings): `accepted`, `duplicate`, `ocr_needed`, `quarantined`.
- Qualifiers (exact strings): `estimated`, `restated`, `partial_coverage`, `fiscal_year_end_assumed`.
- No new review reason codes. An ambiguous unit, an ambiguous scale, a missing FX rate or a scale conflict uses `check_failed`, with the cause written in `verifier_notes`.
- Exchange-rate policy: `FX_POLICY = "annual_average_of_period_end_year"`. Rates are crossed through USD. The rate used is stored on the field (`fx_rate`, `fx_rate_ref`) next to the original `value` and `unit`.
- `fiscal_year_end` is a `"MM-DD"` string. When it is unknown, code assumes `"12-31"` and adds the `fiscal_year_end_assumed` qualifier.
- Object storage stays optional. The default blob store is local: `Settings.blob_store_dir = REPO_ROOT / "data" / "blobs"`. GCS or cloud storage is not part of this step.
- Backend checks: `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest -q && ruff check arp tests`. The baseline is 45 failures that already exist, from missing optional dependencies (Chromium, pdftoppm, postgres factories, the nltk hardlink sandbox). There must be no new failures.
- Frontend checks: `cd frontend && npm run lint && npm test && npm run build`. The baseline is 0 errors.

## Review Focus

1. **Byte-identical re-download or re-fetch.** It must reuse the stored blob after a hash check, with no second `put`, the same `doc_id`, and no `duplicate` intake flag against its own path. Tests go in Task 1 (`test_upload_or_fail_skips_put_when_present`) and Task 2 (`test_refetch_same_file_is_not_duplicate`).
2. **Scale stated twice.** Example: `raw_value_text="$1.2bn"` with `unit_text="USD millions"`. The scale is applied once. When the two disagree, `canonical_value` is None and the reason is `check_failed`. The value is never multiplied twice. Test in Task 9.
3. **Typographic variants in a quote.** Curly quotes, NBSP, en dash or minus sign, ligatures and a soft hyphen in either the quote or the source still ground as `normalised`, and the offsets still point at the original text. Test in Task 5.
4. **An old run opened after this change.** Rows without `value_state`, `period_end` or citation spans still load, still display, and are still decidable under their `…:unspecified` key, in the backend projection and in the frontend. Tests in Tasks 10 and 11.
5. **Several periods but no known fiscal year end.** `FY2024` and `FY2023` for a company with `fiscal_year_end=None` resolve to calendar years, carry `fiscal_year_end_assumed`, and get distinct item keys. They do not collapse into one `unspecified` key. Test in Task 9.

---

### Task 1: Capture record and mandatory store (E26)

**Files:**
- Modify: `arp/storage/document_blob_store.py`:
  - Add `LocalBlobStore`, `blob_store_for`, `upload_or_fail` and `CaptureStoreError`.
  - Remove `upload_document_if_enabled`.
  - Keep `upload_document`, because `arp/cli/db.py` uses it for backfill.
- Modify: `arp/ingestion/indexing_config.py`: add `blob_store_dir: Path | None = None` and fill it in `from_settings`.
- Modify: `arp/config.py`: add `blob_store_dir: Path = REPO_ROOT / "data" / "blobs"`. Change the `object_store_live_upload_enabled` description to say that this flag picks the object store over the local store, and that an upload failure now fails the document.
- Modify: `arp/schemas/discovery.py`: add `CaptureRecord`, and add `capture_id: str | None = None` to `DiscoveredDocument`.
- Modify: `arp/discovery/downloader.py`. Callers to update:
  - `arp/discovery/pipeline.py:46`
  - `arp/extraction/pre_steps.py:185`
  - the fake `download` in `tests/test_extraction_pre_steps.py:73`, which gets `**kwargs`
- Modify: `arp/ingestion/local_files.py:226-228` and `arp/ingestion/edgar.py:172-176`. Both switch from `upload_document_if_enabled` to `upload_or_fail`.
- Test: `tests/test_capture.py` (new), `tests/test_document_blob_store.py` (extend)

**Interfaces:**
- Produces, in `arp/storage/document_blob_store.py`:
  - `class CaptureStoreError(RuntimeError)`
  - `class LocalBlobStore`:
    - `__init__(self, root: Path)`
    - `put(content_key: str, data: bytes) -> str`: writes `root/<content_key[:2]>/<content_key>` through `arp.storage.atomic_io`, and returns `"file://" + absolute path`
    - `get(content_key: str) -> bytes`
    - `exists(content_key: str) -> bool`
  - `def blob_store_for(config: IndexingConfig) -> LocalBlobStore | DocumentBlobStore`: returns `DocumentBlobStore` when `config.object_store_enabled`, else `LocalBlobStore(config.blob_store_dir)`. Raises `CaptureStoreError` when neither store is configured.
  - `def upload_or_fail(store, content_key: str, data: bytes) -> str`:
    - Checks `sha256(data).hexdigest() == content_key`.
    - Skips `put` when `store.exists(content_key)`.
    - Then re-reads with `store.get` and checks the sha256 again.
    - Returns the URI.
    - Any exception or mismatch raises `CaptureStoreError(f"store failed for {content_key}: …")`.
- Produces, in `arp/schemas/discovery.py`, `class CaptureRecord(BaseModel)`:
  - `capture_id: str = Field(default_factory=lambda: new_id("cap"))`
  - `trigger: str`
  - `url_chain: list[str]`
  - `status: int` (the final HTTP status)
  - `headers: dict[str, str]` (all response headers except `set-cookie`)
  - `content_key: str | None`
  - `storage_uri: str | None`
  - `rights_tag: str`
  - `fetched_at: str = Field(default_factory=now_iso)`
  - `collected: bool = False`
  - `error: str | None = None`
- Produces, in `arp/discovery/downloader.py`:
  - `async def download_documents(company, candidates, documents_dir, user_agent, timeout_seconds=30.0, *, store, trigger: str = "discovery", rights_tag: str = "public_disclosure", transport: httpx.AsyncBaseTransport | None = None) -> list[DiscoveredDocument]`. Order per candidate:
    1. GET.
    2. `content_key = sha256(bytes)`.
    3. `upload_or_fail`.
    4. On success only: write the working copy under `documents_dir`, append `CaptureRecord(collected=True)`, and return a `DiscoveredDocument` with `capture_id` set.
    5. On a failed store: append `CaptureRecord(collected=False, error=…)`, write no working copy, and skip the candidate.
  - `CAPTURE_LOG = "_captures.jsonl"`. The log lives at the `documents_dir` root, next to `_events.jsonl`.
  - `def append_capture(documents_dir: Path, record: CaptureRecord) -> None`
  - `def latest_capture(documents_dir: Path, content_key: str) -> CaptureRecord | None`. This is a linear scan, marked `# ponytail: linear scan of the capture log, index by content_key if it grows past ~100k rows`.
- Callers pass `store=blob_store_for(IndexingConfig.from_settings(settings))` and `trigger="discovery"` or `"extraction_pre_step"`.
- In `local_files._index_and_archive`, a `CaptureStoreError` propagates. `_fetch_one` already catches the exception, so that file is not collected that fetch. `set_storage_uri` is called on success.

- [ ] **Step 1: Write the failing tests.** In `tests/test_capture.py`, monkeypatch `downloader.ssrf_guard_request_hook` to a no-op and pass `transport=httpx.MockTransport(...)`:
  - `test_failed_upload_leaves_document_uncollected`: a store whose `put` raises.
    - The result is `[]`.
    - `documents_dir/<company>/` holds no file.
    - The one row in `_captures.jsonl` has `collected is False` and a non-empty `error`.
  - `test_hash_mismatch_on_reread_fails`: when `store.get` returns other bytes, `upload_or_fail` raises `CaptureStoreError`.
  - `test_capture_record_fields`: a 301 to `/final.pdf`, then a 200 with `application/pdf`.
    - `url_chain == [orig, final]`.
    - `status == 200`.
    - `"set-cookie" not in headers`.
    - `content_key == sha256(body)`.
    - `storage_uri.startswith("file://")`.
    - `trigger == "discovery"`, `rights_tag == "public_disclosure"`, `collected is True`.
    - The returned document's `capture_id` equals the record's.
  - `test_upload_or_fail_skips_put_when_present`: a second call on the same bytes does not call `put`. Count the calls with a wrapper.
  - `test_local_files_skips_file_when_archive_fails`: `LocalFileDocumentSource` with an `indexing_config` whose `blob_store_dir` is a file (so not writable). `fetch` returns `[]`.

  In `tests/test_document_blob_store.py`:
  - `test_local_blob_store_roundtrip`
  - `test_blob_store_for_defaults_to_local`

- [ ] **Step 2: Run** `cd backend && PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_capture.py tests/test_document_blob_store.py -v`. Expect FAIL (`ImportError: LocalBlobStore`).

- [ ] **Step 3: Implement as in Interfaces.** Get the URL chain from `[str(r.url) for r in resp.history] + [str(resp.url)]`. Write capture rows with the `append_jsonl` helper that `RunStore` uses, if there is one (`grep -n "def append" arp/storage/*.py`). Otherwise, open the log in `"a"` mode under `KeyedLock`.

- [ ] **Step 4: Run** the full backend check. Expect no new failures. Update `tests/test_extraction_pre_steps.py:73` so its fake accepts `**kwargs`.

- [ ] **Step 5: Commit** with `feat(capture): capture record and verified store before a document counts (E26)`.

---

### Task 2: Intake checks (E28)

**Files:**
- Create: `arp/ingestion/intake.py`
- Modify: `arp/ingestion/local_files.py` (`fetch`: run intake on every file, in sorted order, before the concurrent parse)
- Test: `tests/test_intake.py`

**Interfaces:**
- Consumes: `DocumentContentStore.content_key_for_file(path)`. When there is no content store, use `hashlib.file_digest`.
- Produces:
  - `class IntakeState(StrEnum)` with the four values from Global Constraints.
  - `@dataclass(frozen=True) class IntakeResult: state: IntakeState; reason: str = ""; duplicate_of: str | None = None`
  - `MIN_TEXT_CHARS_PER_PAGE = 25`, `TEXT_CHECK_PAGES = 5`
  - `def check_intake(path: Path, content_key: str, *, seen: dict[str, str]) -> IntakeResult`. Rules, applied in order:
    1. An empty file is `quarantined` (`"empty"`).
    2. A `content_key` already in `seen` under a different path is `duplicate` (`duplicate_of=seen[key]`). Otherwise record `seen[key] = str(path)`.
    3. A PDF with no `%PDF-` in the first 1024 bytes, or no `%%EOF` in the last 2048 bytes, is `quarantined` (`"truncated"`).
    4. If `pypdf.PdfReader` raises, the file is `quarantined` (`"unreadable: <exc>"`). A PDF that is encrypted and where `decrypt("") == 0` is also `quarantined` (`"password protected"`).
    5. If the text extracted from the first `TEXT_CHECK_PAGES` pages is shorter than `MIN_TEXT_CHARS_PER_PAGE × pages checked`, the file is `ocr_needed`.
    6. An `.xlsx`, `.xlsm` or `.docx` file is `quarantined` when `zipfile.is_zipfile` is false or `testzip()` is not None.
    7. Everything else is `accepted`.
  - `INTAKE_LOG = "_intake.jsonl"`. The log is at the `documents_dir` root.
  - `def append_intake(documents_dir: Path, path: Path, content_key: str, result: IntakeResult) -> None`. Called only for non-accepted results.
- Behaviour in `fetch`: only `accepted` files reach `_parse_and_identify`. Files are never moved or deleted; quarantine is a recorded state. `seen` is per company fetch.

- [ ] **Step 1: Write the failing tests.** Build the PDFs in a fixture:
  - `test_scanned_pdf_goes_to_ocr`: a 2-page `PdfWriter` file with only blank pages gives `ocr_needed`.
  - `test_truncated_pdf_is_quarantined`: a reportlab text PDF cut to half its bytes gives `quarantined` with reason `"truncated"`.
  - `test_text_pdf_accepted`
  - `test_empty_file_quarantined`
  - `test_corrupt_xlsx_quarantined`
  - `test_duplicate_by_content_key`: the same bytes in `10-K/a.pdf` and `other/b.pdf` give `duplicate` for the second file, with `duplicate_of` ending in `a.pdf`.
  - `test_refetch_same_file_is_not_duplicate`: `check_intake` twice on the same path with the same `seen` gives `accepted` both times.
  - `test_fetch_skips_non_accepted_and_logs`: run `LocalFileDocumentSource.fetch` over a directory holding one good txt, one blank PDF and one truncated PDF.
    - One `SourceDocument` comes back.
    - `_intake.jsonl` has 2 rows, with states `{"ocr_needed", "quarantined"}`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_intake.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(ingestion): intake checks route truncated, scanned and duplicate files (E28)`.

---

### Task 3: Document identity (E27)

**Files:**
- Create: `arp/ingestion/doc_identity.py`
- Modify: `arp/schemas/common.py`. `SourceDocument` gains `published_at: str | None = None`, `family_id: str | None = None`, `version: int | None = None`, `supersedes: str | None = None`, `content_key: str | None = None`, `parser_version: str | None = None`.
- Modify: `arp/storage/document_registry.py`:
  - New columns.
  - Replace `ensure_storage_uri_column` with `ensure_columns(conn)`. Keep the old name as an alias, because `tests/test_document_content_store.py` references it.
  - New fields on `StoredDocumentRef`, appended with default `None`, and every `SELECT` extended in the same order.
  - Add `set_identity` and `list_family`.
- Modify: `arp/storage/document_store.py`: add delegating methods.
- Modify: `arp/ingestion/local_files.py`. `_parse_and_identify` returns `dict` of extra `SourceDocument` kwargs instead of the 4-tuple, and assigns identity once per doc (it reuses the stored identity when the row already has a `family_id`). Also set `content_key` and `parser_version` in `arp/ingestion/edgar.py`, where it builds `SourceDocument`.
- Test: `tests/test_doc_identity.py`

**Interfaces:**
- Consumes: `latest_capture` (Task 1).
- Produces:
  - Registry columns: `family_id TEXT`, `version INTEGER`, `supersedes TEXT`, `published_at TEXT`, `identity_confidence REAL`, `identity_review INTEGER`.
  - `DocumentRegistry.set_identity(doc_id, *, family_id, version, supersedes, published_at, confidence: float, needs_review: bool) -> None`
  - `DocumentRegistry.list_family(family_id) -> list[StoredDocumentRef]`
  - `REVIEW_BELOW = 0.6`
  - `CORRECTION_MARKERS = ("corrected", "correction", "amended", "amendment", "revised", "restated", "10-k/a")`
  - `@dataclass(frozen=True) class IdentityDecision: family_id: str; version: int; supersedes: str | None; confidence: float; needs_review: bool; reason: str`
  - `def reporting_year(title: str, text: str) -> int | None`. It looks for a single distinct `20\d\d` in the title, else the first one in `text[:3000]`. Two or more distinct years in the title return `None`.
  - `def family_id_for(company_id: str, doc_type: str, year: int) -> str`, which returns `"fam_" + sha256(f"{company_id}\x00{doc_type}\x00{year}")[:16]`.
  - `def published_at_for(path: Path, capture: CaptureRecord | None) -> str | None`. It tries the PDF `/CreationDate` through pypdf, then the capture's `last-modified` header through `email.utils.parsedate_to_datetime`. Returns an ISO date or None.
  - `def assign_identity(*, doc_id, company_id, doc_type, title, text, published_at, family: Callable[[str], list[StoredDocumentRef]]) -> IdentityDecision`. Rules:
    - No year: own family `f"fam_{doc_id[4:]}"`, `version=1`, `confidence=0.3`, `needs_review=True`.
    - Year found but no other member: `version=1`, `confidence=0.9`.
    - Other members exist: `version = max(member.version) + 1` and `supersedes` = the member with the highest version.
      - `confidence=0.9` when the title holds a correction marker, or both `published_at` dates are known and this one is later.
      - Otherwise `confidence=0.5`, which means review.
  - `needs_review = confidence < REVIEW_BELOW`. No model call is made in this step: ambiguity goes to review (the spec allows "model only for ambiguity").

- [ ] **Step 1: Write the failing tests:**
  - `test_corrected_republication_links_to_first`: fetch `sustainability_report/Sustainability Report 2023.txt`, then add `Sustainability Report 2023 corrected.txt` (different bytes) and fetch again.
    - The second doc has `family_id` equal to the first's, `version == 2`, and `supersedes == first.doc_id`.
    - The first doc still has `version == 1`.
  - `test_no_year_goes_to_review`: `assign_identity(title="Report.pdf", text="no year here", …)` gives `needs_review is True`.
  - `test_same_year_no_marker_no_dates_is_low_confidence`: the confidence is 0.5 and the decision needs review.
  - `test_two_years_in_title_is_ambiguous`: `reporting_year("Report 2022 vs 2023", "")` is None.
  - `test_published_at_from_capture_header`
  - `test_old_content_db_gains_identity_columns`: a `documents` table created with the old schema opens and `resolve_document` returns `family_id is None`.
  - `test_old_source_document_json_loads`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_doc_identity.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** Superseded documents are still fetched and used as evidence in this step; filtering them out is a later decision.

- [ ] **Step 4: Run** the full backend check. Expect no new failures, including the existing `test_local_files_*` and `test_document_content_store` tests.

- [ ] **Step 5: Commit** with `feat(ingestion): document families, versions and supersedes (E27)`.

---

### Task 4: Grounding evidence and passage binding (E43)

**Files:**
- Modify: `arp/schemas/common.py`. Add the new `Citation` fields.
- Modify: `arp/grounding.py`:
  - `_find_match` returns `Match | None`.
  - `ground_citations` and `ground_claim` take `passages`.
  - `is_grounded` keeps its `bool` signature.
- Modify: `arp/extraction/extractor_agent.py`. `format_evidence` adds `passage_id=<chunk_id>` to each block header. The prompt rule says that every citation names the `passage_id` of the block its quote was copied from.
- Modify: `arp/extraction/field_graph.py`. `_aggregate` passes `passages={c.chunk_id: c for c in state["evidence"]}`.
- Modify: `tests/test_grounding.py:139-168`. Update to `_find_match(...) is not None`.
- Test: `tests/test_grounding.py` (extend)

**Interfaces:**
- Produces:
  - New `Citation` fields, all defaulting to `None`:
    - `content_key: str | None`
    - `span_text: str | None`
    - `char_start: int | None`
    - `char_end: int | None`
    - `match_method: Literal["exact", "normalised", "fuzzy"] | None`
    - `match_score: float | None`
    - `passage_id: str | None` (LLM-facing; description "passage_id of the evidence block the quote was copied from")
    - `table_ref: str | None` (always None in this step)
    - `parser_version: str | None`
  - `@dataclass(frozen=True) class Match: char_start: int; char_end: int; method: str; score: float`. Offsets index the original text; `char_end` is exclusive.
  - `def _find_match(quote: str, source_text: str, fuzzy_threshold: float, *, within: list[tuple[int, int]] | None = None, prefer: tuple[int, int] | None = None) -> Match | None`. Search order:
    1. A raw `source_text.find(quote)` gives `exact` with score 1.0.
    2. A normalised find gives `normalised` with score 1.0.
    3. `SequenceMatcher` gives `fuzzy` with score equal to coverage.

    When `within` is given, a match counts only if `[char_start, char_end)` lies inside one of those spans. The match inside `prefer` wins when there is one. The fuzzy search runs per allowed span, not over the whole document.
  - `ground_citations(citations, documents_by_id, fuzzy_threshold=0.92, *, passages: dict[str, DocumentChunk] | None = None) -> list[Citation]`:
    - With `passages`: `within` is the spans of the passages of that doc, and `prefer` is the span of `passages.get(c.passage_id)`.
    - Without `passages`: the whole document, as today. Financials, TNFD, transition plan and segment callers stay unchanged.
    - When grounded, set `content_key=doc.content_key`, `parser_version=doc.parser_version`, `span_text=doc.full_text[s:e]`, `char_start`, `char_end`, `match_method`, `match_score`, and `passage_id` (the passage the match lies in).
    - When ungrounded, clear every verified field. `passage_id` keeps the reported value.
  - `ground_claim(..., *, claim_is_empty, passages=None)` passes `passages` through.

- [ ] **Step 1: Write the failing tests:**
  - `test_grounded_citation_carries_span_and_offsets`:
    - `doc.full_text[c.char_start:c.char_end] == c.span_text`
    - `c.match_method == "exact"`, `c.match_score == 1.0`
    - `c.content_key == doc.content_key`, `c.parser_version == doc.parser_version`
  - `test_quote_from_unseen_passage_is_ungrounded`: the document has two chunks, A and B; only A is in `passages`, and the quote is copied from B. The result is `grounded is False` and `char_start is None`.
  - `test_wrong_passage_id_corrected_to_shown_passage`: the quote is in shown passage A, but the citation says shown passage C. It grounds with `passage_id == A.chunk_id`.
  - `test_without_passages_searches_whole_document`
  - `test_format_evidence_includes_passage_id`
  - `test_old_citation_json_loads`: a citation dict with only the step-1 keys validates.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_grounding.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** The end offset is `offsets[idx + len(norm_quote) - 1] + 1`.

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(grounding): span evidence on citations, quotes bound to shown passages (E43)`.

---

### Task 5: Robust matching (E44)

**Files:**
- Modify: `arp/grounding.py` (`_normalize`, `_normalize_with_offsets`, the short-quote rule)
- Test: `tests/test_grounding.py` (extend)

**Interfaces:**
- Consumes: `Match` and `_find_match` (Task 4).
- Produces. The same normalisation applies to the quote and the source, and every output char still maps to a source offset:
  - Dashes `‐ ‑ ‒ – — −` become `-`.
  - Curly quotes `‘ ’ ‚ ‛` become `'`, and `“ ” „` become `"`.
  - Soft hyphen `­` and zero-width chars `​ ‌ ‍ ﻿` are dropped.
  - Ligatures `ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ` expand through `unicodedata.normalize("NFKC", ch)`. Every expanded char maps to the ligature's offset.
  - Whitespace collapses as today (`str.isspace` already covers NBSP and thin space).
  - PDF hyphenation: `<alnum>-<whitespace containing \n><alnum>` drops the hyphen and the whitespace. So `12,3-\n45` becomes `12,345` and `emis-\nsions` becomes `emissions`.
  - Lowercase, as today.
  - `SHORT_QUOTE_CHARS = 20`. This replaces "under 8 chars returns False". A normalised quote shorter than 20 chars grounds only if it contains a digit and a word of 3 or more letters (`re.search(r"\d", q) and re.search(r"[a-z]{3,}", q)`). A short quote never takes the fuzzy path.

- [ ] **Step 1: Write the failing tests:**
  - `test_hyphen_split_number_grounds`: source `"Scope 1 emissions of 12,3-\n45 tCO2e in 2023"`, quote `"emissions of 12,345 tCO2e"`. It grounds with method `normalised`, and `span_text` starts with `"emissions of 12,3-"`.
  - `test_repeated_quote_picks_cited_passage`: `"Scope 1 emissions: 4,210 tCO2e"` appears in shown passages A and B, and the citation names B. `B.char_start <= c.char_start < B.char_end`.
  - `test_typographic_variants_normalise`: source `"the \ufb03cient \u2013 \u201cnet zero\u201d 2030\u00a0tar\u00adget"` (a ligature, an en dash, curly quotes, an NBSP and a soft hyphen), quote `"the efficient - \"net zero\" 2030 target"`. It grounds with method `normalised`, and `span_text` equals the original slice.
  - `test_short_bare_number_rejected`: quote `"42"`, with `"42"` present in the source, is ungrounded.
  - `test_short_number_with_label_grounds`: quote `"42 MWh"` grounds.
  - `test_short_quote_never_fuzzy`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_grounding.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** `_normalize(quote)` becomes `_normalize_with_offsets(quote)[0]`, so the quote and the source can never drift apart. Keep the `lru_cache`. Fix any existing test fixture whose quote is a bare short number by adding its label to the quote.

- [ ] **Step 4: Run** the full backend check. Expect no new failures, and check `test_news_classifier`, `test_emerging_themes_extraction` and `test_segment_grounding`.

- [ ] **Step 5: Commit** with `feat(grounding): normalise dashes, ligatures, hyphenation; short quotes need number and label (E44)`.

---

### Task 6: Unit and currency normalisation tables (E46)

**Files:**
- Create: `arp/normalise/__init__.py` (empty), `arp/normalise/units.py`, `arp/normalise/fx.py`
- Create: `arp/normalise/tables/units_v1.csv`, `scale_v1.csv`, `fx_v1.csv`
- Modify: `pyproject.toml`. Add package data for `arp/normalise/tables/*.csv`, following how `arp/golden_set/data` is included.
- Test: `tests/test_normalise_units.py`, `tests/test_normalise_fx.py`

**Interfaces:**
- Produces, in `units.py`:
  - `UNITS_TABLE = "units_v1"`, `SCALE_TABLE = "scale_v1"`
  - `@dataclass(frozen=True) class UnitInfo: canonical: str; factor: float; dimension: str; ambiguous: bool`
  - `def lookup_unit(text: str) -> UnitInfo | None`. The lookup is case-insensitive, with whitespace collapsed.
  - `def split_unit(text: str) -> tuple[float, bool, str]` returns `(scale_factor, scale_ambiguous, base_text)`. The scale comes from a leading or trailing scale word (`"thousand tonnes CO2e"` gives `(1000.0, False, "tonnes CO2e")`, `"USD millions"` gives `(1e6, False, "USD")`).
  - `@dataclass(frozen=True) class Conversion: value: float | None; scale_applied: float; from_canonical: str | None; ambiguous: bool; reason: str | None`
  - `def convert(value: float, from_text: str, to_text: str) -> Conversion`:
    - It splits both sides, looks up both base units, and returns `value * from_scale * from_factor / (to_scale * to_factor)`.
    - A dimension mismatch gives `value=None, reason="dimension_mismatch"`.
    - An unknown unit gives `reason="unknown_unit"`.
    - Currency to a different currency gives `reason="needs_fx"`, which `fx.py` handles.
- `units_v1.csv` columns: `alias,canonical,factor,dimension,ambiguous`. Rows must include at least:
  - mass: `t`, `tonne`, `tonnes`, `metric ton`, `kg`=0.001, `kt`=1000, `Mt`=1e6, and `ton` with `ambiguous=1`
  - emissions to `tCO2e`: `tCO2e`, `tCO2-e`, `t CO2e`, `tonnes CO2e`, `tonnes of CO2 equivalent`, `kgCO2e`=0.001, `ktCO2e`=1000, `MtCO2e`=1e6
  - energy to `MWh`: `kWh`=0.001, `MWh`, `GWh`=1000, `TWh`=1e6, `GJ`=0.277778, `TJ`=277.778
  - percentage: `%`, `percent`, `per cent`
  - currency codes as themselves (`USD EUR GBP JPY CHF CAD AUD SEK NOK DKK CNY`)
  - currency symbols `€`→EUR and `£`→GBP, plus `$` (USD) and `¥` (JPY), both with `ambiguous=1`
- `scale_v1.csv` columns: `word,factor,ambiguous`. Rows: `thousand`, `thousands`, `'000`, `k`, `million`, `millions`, `mn`, `mm`, `bn`, `billion`, `billions`, and `m` with `ambiguous=1` (million or metre).
- Produces, in `fx.py`:
  - `FX_TABLE = "fx_v1"`, `FX_POLICY = "annual_average_of_period_end_year"`
  - `@dataclass(frozen=True) class FxRate: rate: float; ref: str`. `ref` looks like `"fx_v1:EUR->USD:2024"`.
  - `def rate(from_ccy: str, to_ccy: str, year: int) -> FxRate | None`, crossed through USD.
  - `def convert_amount(value: float, from_ccy: str, to_ccy: str, year: int) -> tuple[float | None, FxRate | None]`
- `fx_v1.csv` columns: `currency,year,usd_per_unit,source`. Each row holds the annual average for 2019–2025 of each non-USD currency listed above, copied from one named public source (for example Federal Reserve H.10 annual averages), with that source named in the `source` column. Do not invent rates; leave out a year the source lacks.

- [ ] **Step 1: Write the failing tests:**
  - `test_every_unit_row_converts_to_canonical`: parametrized over every row of `units_v1.csv`. For a non-currency row, `convert(1.0, alias, canonical).value == pytest.approx(factor)`. For an ambiguous row, `lookup_unit(alias).ambiguous is True`.
  - `test_every_scale_row`: parametrized. `split_unit(f"{word} tonnes")[0] == factor`, and the ambiguous flag matches the row.
  - `test_every_fx_row`: parametrized.
    - `re.fullmatch("[A-Z]{3}", currency)`.
    - `2019 <= year <= 2025`.
    - `usd_per_unit > 0`.
    - `source` is non-empty.
    - There is no duplicate `(currency, year)`.
    - `rate(currency, "USD", year).rate == usd_per_unit`.
  - `test_thousand_tonnes_to_tco2e`: `convert(1234.0, "thousand tonnes CO2e", "tCO2e")` gives `value == 1_234_000.0` and `scale_applied == 1000.0`.
  - `test_dimension_mismatch`: `convert(1.0, "MWh", "tCO2e").reason == "dimension_mismatch"`.
  - `test_cross_rate_via_usd`: with a fixture table, `rate("EUR", "GBP", y).rate == eur_usd / gbp_usd`.
  - `test_missing_rate_is_none`

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_normalise_units.py tests/test_normalise_fx.py -v`. Expect FAIL.

- [ ] **Step 3: Implement.** Load the tables once with `functools.cache` and `csv.DictReader` over `Path(__file__).parent / "tables"`.

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(normalise): versioned unit, scale and FX tables (E46)`.

---

### Task 7: Period, basis and qualifier normalisation (E47)

**Files:**
- Create: `arp/normalise/period.py`, `arp/normalise/tables/basis_v1.csv`
- Modify: `arp/schemas/common.py`. `CompanyRef` gains `fiscal_year_end: str | None = Field(default=None, pattern=r"^\d{2}-\d{2}$", description="Fiscal year end as MM-DD, e.g. 04-30.")`.
- Test: `tests/test_normalise_period.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ResolvedPeriod: start: date | None; end: date | None; fye_assumed: bool = False`
  - `def resolve_period(text: str | None, *, fiscal_year_end: str | None) -> ResolvedPeriod`. Patterns, case-insensitive, with dates parsed by `datetime.strptime` over `"%d %B %Y"`, `"%B %d, %Y"`, `"%d %b %Y"`, `"%b %d, %Y"` and `"%Y-%m-%d"`:
    - `"<52|53> weeks ended <date>"`: `end=date`, `start = end - (weeks*7 - 1) days`.
    - `"(fiscal )?year ended <date>"`: `end=date`, `start = end - 1 year + 1 day`.
    - `"as (at|of) <date>"`: `start = end = date`.
    - `"FY ?YYYY"` and bare `"YYYY"`: the fiscal year that ends in `YYYY` on `fiscal_year_end`. When the FYE is unknown, use `12-31` with `fye_assumed=True`.
    - `"FY ?YYYY/YY"` or `"YYYY/YY"`: ends in the second year.
    - `"Q[1-4] YYYY"`: a calendar quarter.
    - Anything else gives `ResolvedPeriod(None, None)`.
  - `def normalise_basis(text: str | None) -> str | None`. Lookup in `basis_v1.csv` (`alias,canonical`); an unknown basis returns `None`. Canonicals:
    - `location_based`, `market_based`
    - `operational_control`, `financial_control`, `equity_share`
    - `reported`, `adjusted`, `like_for_like`
  - `class Qualifier(StrEnum)` with the four values from Global Constraints.
  - `def detect_qualifiers(*texts: str | None) -> list[Qualifier]`, keyword-based, in enum order, with no duplicates:
    - `estimated`: `estimate`, `approx`, `approximately`, `~`, `c.`
    - `restated`: `restated`, `re-stated`, `revised`
    - `partial_coverage`: `partial`, `excluding`, `excl.`, `covers`, `% of sites`, `% of operations`
  - `def reported_precision(raw: str | None) -> int | None`: the number of decimals in the first number of `raw` (`"1,234.50"` gives 2, `"1,234"` gives 0, no number gives None).

- [ ] **Step 1: Write the failing tests:**
  - `test_52_week_year`: `resolve_period("52 weeks ended 30 March 2024", fiscal_year_end=None)` gives start `date(2023, 4, 2)` and end `date(2024, 3, 30)`.
  - `test_53_week_year`: `"53 weeks ended 1 April 2023"` gives start `date(2022, 3, 27)`.
  - `test_april_year_end`: `resolve_period("FY2024", fiscal_year_end="04-30")` gives `(date(2023, 5, 1), date(2024, 4, 30))`, with `fye_assumed is False`.
  - `test_split_fiscal_year`: `"FY2023/24"` with `"03-31"` gives `(date(2023, 4, 1), date(2024, 3, 31))`.
  - `test_unknown_fye_assumes_calendar`: `"FY2024"` with None gives `(date(2024, 1, 1), date(2024, 12, 31))`, with `fye_assumed is True`.
  - `test_year_ended_and_as_at`
  - `test_unparseable_period_is_none`
  - `test_every_basis_row`: parametrized over `basis_v1.csv`.
  - `test_qualifiers_kept_as_flags`: `detect_qualifiers("approximately 1,200 (restated)")` equals `[ESTIMATED, RESTATED]`.
  - `test_reported_precision`
  - `test_company_ref_fiscal_year_end_validated`: `"4/30"` raises `ValidationError`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_normalise_period.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(normalise): period, basis and qualifier normalisation (E47)`.

---

### Task 8: Versioned field definitions and schema registry (E8)

**Files:**
- Modify: `arp/schemas/datapoints.py`:
  - `FieldStatus`.
  - New `FieldDefinition` fields.
  - `DataPointSchema.version` and `release_flag`.
  - `FieldDefinition.unit` description becomes "Canonical unit every value of this field is converted to, e.g. 'tCO2e', 'USD millions', '%'."
- Modify: `arp/schemas/common.py`. `ProvenanceInfo` gains `schema_version: str = ""` and `field_version: int | None = None`.
- Create: `arp/storage/schema_registry.py`
- Modify: `arp/config.py`. Add `schema_registry_dir: Path = REPO_ROOT / "schemas"`.
- Modify: `arp/extraction/pipeline.py`:
  - `create_extraction_run` registers the schema and checks release.
  - Add `load_run_schema`.
  - `execute_extraction_run` uses the snapshot.
- Modify: `arp/extraction/field_graph.py`. `extract_one_field` gains a `schema_version: str = ""` kwarg, and `_aggregate` writes it and `field.version` into the provenance.
- Modify: `arp/api/routers/extraction.py`:
  - `RunRequest.trial` and `StartRequest.trial`, passed through.
  - New schema routes.
- Modify: `arp/cli/extraction.py`. `extract_run` gains `--trial`.
- Test: `tests/test_schema_registry.py`, `tests/test_extraction_pipeline.py` (extend)

**Interfaces:**
- Produces:
  - `class FieldStatus(StrEnum)` with `DRAFT="draft"`, `RELEASED="released"`, `RETIRED="retired"`.
  - New `FieldDefinition` fields: `version: int = 1`, `effective_from: str | None = None` (ISO date), `status: FieldStatus = FieldStatus.DRAFT`.
  - New `DataPointSchema` fields: `version: int = 1`, `release_flag: bool = False`.
  - `class UnreleasedFieldError(ValueError)`. Its message lists the offending `field_id`s.
  - `class FieldVersionError(ValueError)`
  - `class SchemaRegistry`, which follows `arp/storage/decision_store.py`'s versioned-file layout and uses `atomic_write_text` and `KeyedLock`:
    - `__init__(self, root: Path)`. Layout: `root/index.json`, which is `[{schema_id, version, name, release_flag, saved_at}]`, and `root/<schema_id>/v<N>.json`.
    - `save(schema: DataPointSchema) -> DataPointSchema`:
      - A schema never seen before is stored as version 1.
      - Otherwise, compare with the latest version. A field that was `released` there and whose content differs must have `version` greater than the old one, else `FieldVersionError`. Content means every field except `status`, `version` and `effective_from`.
      - When nothing differs, return the latest version unchanged.
      - Otherwise write a new version, `latest + 1`, with `release_flag=False`.
    - `get(schema_id: str, version: int | None = None) -> DataPointSchema`. `None` means the latest.
    - `list_index() -> list[dict]`
    - `release(schema_id: str, version: int) -> DataPointSchema`. It sets `release_flag=True`. Every `draft` field becomes `released` with `effective_from = today` when that is unset. It rewrites the same version file, because a status change is not a content change.
  - `def create_extraction_run(schema, companies, settings, run_store, *, trial: bool = False) -> str`:
    - Registers the schema first (`SchemaRegistry(settings.schema_registry_dir).save`).
    - Unless `trial`, it raises `UnreleasedFieldError` when `not registered.release_flag` or any field has a status other than `released`. No run dir is created in that case.
    - Writes the registered schema as `runs/<id>/schema.json` (the snapshot) and adds `trial`, `schema_version` and `schema_id` to the manifest params.
  - `def load_run_schema(run_store: RunStore, run_id: str) -> DataPointSchema | None`
  - `execute_extraction_run` uses `load_run_schema(...) or schema`.
  - `schema_version` is the string `f"{schema.schema_id}:v{schema.version}"`.
  - Routes:
    - `POST /api/extraction/schemas`, body `DataPointSchema`, returns the registered schema.
    - `GET /api/extraction/schemas`, which returns the index.
    - `GET /api/extraction/schemas/{schema_id}?version=`
    - `POST /api/extraction/schemas/{schema_id}/versions/{version}/release`, behind `require_role("approver")`.
  - A `ValueError` already maps to 400 through `arp/api/main.py:137`.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_with_draft_field_is_refused`: `pytest.raises(UnreleasedFieldError, match=field_id)`, and `runs_dir` holds no run dir.
  - `test_trial_run_allows_draft_and_records_trial`: the manifest has `params["trial"] is True`.
  - `test_released_run_allowed`
  - `test_released_field_change_requires_new_version`: save, release, edit `description`, then save raises `FieldVersionError`. With `version=2` the save succeeds and returns schema `version == 2`.
  - `test_resave_unchanged_returns_same_version`
  - `test_snapshot_and_index_written`
  - `test_provenance_records_schema_version`: run `_extract_company` with `FakeLLMClient` through `execute_extraction_run`. The results row field has `provenance.schema_version == f"{sid}:v1"` and `field_version == 1`.
  - `test_old_schema_json_loads`: a dict without `status` or `version` gives `status == "draft"` and `version == 1`.
  - `test_start_unreleased_custom_run_is_400` and `test_release_route_requires_approver`, both through the API test client.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_schema_registry.py tests/test_extraction_pipeline.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.** Existing tests that create extraction runs through the API or `run_extraction` should pass `trial=True`, or use a released schema fixture. The ad hoc schemas in `research/*/resolver.py` and `golden_set/` call `_extract_company` or `extract_one_field` directly, so they are not gated.

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(extraction): versioned field definitions, schema registry, release gate (E8)`.

---

### Task 9: Multi-period typed values in extraction (E30, E6)

**Files:**
- Modify: `arp/schemas/datapoints.py`. Add `ValueState` and the new `ExtractedField` fields, with a before-validator for old rows.
- Modify: `arp/extraction/extractor_agent.py`. Add `PeriodValue`. `ExtractionDraft.values` replaces `value`/`raw_value_text`/`citations`, with a legacy before-validator, and the prompt rules change.
- Modify: `arp/extraction/verifier_agent.py`. The prompt lists every value, and `corrected_value` applies to `values[0]`.
- Create: `arp/normalise/value.py`
- Modify: `arp/extraction/aggregator.py`. `build_extracted_field` becomes `build_extracted_fields`, and `no_evidence_field` changes.
- Modify: `arp/extraction/field_graph.py`. `FieldState.extracted` becomes `list[ExtractedField]`, and `_aggregate` sets the provenance on every entry. `extract_one_field` gains `fiscal_year_end: str | None = None` and returns `(list[ExtractedField], bool, list[LLMUsage])`.
- Modify: `arp/extraction/pipeline.py`. `_extract_company` passes `fiscal_year_end=company.fiscal_year_end` and `schema_version`, and extends `fields` with the list.
- Modify: `arp/golden_set/runner.py`. Compare `fields[0]`.
- Test: `tests/test_aggregator.py` (extend; update the existing `build_extracted_field` calls), `tests/test_normalise_value.py` (new), `tests/test_extraction_pipeline.py` (extend)

**Interfaces:**
- Consumes:
  - `convert`, `split_unit`, `lookup_unit` (Task 6)
  - `convert_amount` (Task 6)
  - `resolve_period`, `normalise_basis`, `detect_qualifiers`, `reported_precision`, `Qualifier` (Task 7)
  - `ground_citations(..., passages=)` (Task 4)
  - `schema_version` (Task 8)
- Produces:
  - `class ValueState(StrEnum)` with `FOUND="found"`, `NOT_FOUND="not_found"`, `NOT_APPLICABLE="not_applicable"`, `ZERO="zero"`.
  - New `ExtractedField` fields:
    - `value_state: ValueState = ValueState.NOT_FOUND`
    - `unit: str | None` (the unit as reported)
    - `canonical_value: float | None`
    - `canonical_unit: str | None`
    - `scale_applied: float | None`
    - `period_text: str | None`
    - `period_start: str | None`, `period_end: str | None` (ISO dates)
    - `basis: str | None`
    - `qualifiers: list[str] = []`
    - `reported_precision: int | None`
    - `fx_rate: float | None`, `fx_rate_ref: str | None`
  - The `ExtractedField` before-validator applies only when `value_state` is absent: `value is None` gives `not_found`, `value == 0` (and not a bool) gives `zero`, anything else gives `found`.
  - `class PeriodValue(BaseModel)`:
    - `value: str | float | bool | None = None`
    - `state: ValueState = ValueState.FOUND`
    - `raw_value_text: str | None = None`
    - `unit_text: str | None = None`
    - `period_text: str | None = None`
    - `basis_text: str | None = None`
    - `citations: list[Citation] = []`
  - `ExtractionDraft` fields: `values: list[PeriodValue] = []`, `confidence`, `conflicting_sources`. The before-validator maps a legacy `{"value", "raw_value_text", "citations"}` input to `values=[]` when `value is None` and there are no citations, else to one `PeriodValue`. Existing tests and fakes therefore keep working.
  - Prompt rules, replacing the "set value to null" and "prefer the most recent" rules:
    - One entry in `values` per reported period, each with its own citations.
    - `unit_text`, `period_text` and `basis_text` are copied verbatim, including a scale word from a table header (for example `"in thousands"`).
    - `state="zero"` only when the document states zero; `state="not_applicable"` only when it states the item does not apply.
    - An empty `values` list means not disclosed.
    - Never convert units or scales yourself.
  - In `arp/normalise/value.py`:
    - `@dataclass(frozen=True) class TypedValue`, with the fields `value`, `value_state`, `unit`, `canonical_value`, `canonical_unit`, `scale_applied`, `period_text`, `period_start`, `period_end`, `basis`, `qualifiers`, `reported_precision`, `fx_rate`, `fx_rate_ref`, plus `reasons: list[ReasonCode]` and `notes: list[str]`.
    - `def typed_value(field: FieldDefinition, pv: PeriodValue, *, fiscal_year_end: str | None) -> TypedValue`. Rules:
      - Numeric data types (`number`, `currency_amount`, `percentage`) with a float `value`:
        - The scale comes from `unit_text`, else from `raw_value_text`. If both state a scale and they differ, `canonical_value=None`, the reason is `check_failed`, and the note is `"scale stated twice and differs"`.
        - An ambiguous unit or scale gives `check_failed` with a note.
        - Currency to a different currency goes through `convert_amount` with `year = period_end.year`. A missing rate gives `canonical_value=None`, `check_failed`, and the note `"no FX rate <ccy> <year> in fx_v1"`.
        - When `field.unit` is None, `canonical_unit` is the base unit from `unit_text` and `canonical_value = value * scale`.
      - `found` with a value equal to 0 becomes `zero`. `zero` with a value of None becomes value `0.0`.
      - A period with `fye_assumed` adds the `fiscal_year_end_assumed` qualifier.
      - Non-numeric types pass through with `canonical_value=None`.
  - `def build_extracted_fields(field, draft, verifier, documents_by_id, fuzzy_threshold, confidence_review_threshold, *, passages: dict[str, DocumentChunk] | None = None, fiscal_year_end: str | None = None) -> list[ExtractedField]`:
    - One field per `PeriodValue`, sorted by `period_end` descending with None last.
    - Grounding, the reason order and the notes stay as today, applied per value. `typed_value` reasons are appended after `low_confidence`.
    - Verifier disagreement replaces the value of the first sorted entry only. That entry loses its citations, as today. Every entry gets `verifier_disagrees`.
    - Entries sharing a period key keep the first; the dropped ones add `conflict` to the kept one.
    - Empty `values` returns `[no_evidence_field(field)[0]]`, with the note `"The extractor found no disclosed value."`.
    - `needs_review` for an entry is `bool(entry.review_reasons)`.
  - `no_evidence_field(field)` returns `value_state=ValueState.NOT_FOUND` (value stays None).
  - `def period_key(f: ExtractedField | dict) -> str` in `arp/schemas/review.py` returns `period_end or "unspecified"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_tonnes_in_thousands_converts_and_keeps_text`: `field.unit="tCO2e"`, `PeriodValue(value=1234.0, raw_value_text="1,234", unit_text="thousand tonnes CO2e", period_text="FY2023")`.
    - `canonical_value == 1_234_000.0`, `canonical_unit == "tCO2e"`, `scale_applied == 1000.0`.
    - `unit == "thousand tonnes CO2e"`, `raw_value_text == "1,234"`.
  - `test_scale_stated_twice_differs_is_check_failed`: `raw_value_text="$1.2bn"`, `unit_text="USD millions"`.
  - `test_currency_converted_with_rate_stored`: with a fixture rate, `fx_rate` and `fx_rate_ref` are set, and `value` and `unit` are unchanged.
  - `test_missing_fx_rate_flags_check_failed`
  - `test_zero_and_not_found_stay_distinct`: a draft with `values=[PeriodValue(value=0, state="zero", citations=[…])]` gives `value_state == "zero"` and `value == 0`. A draft with `values=[]` gives `value_state == "not_found"` and `value is None`.
  - `test_no_evidence_field_is_not_found`
  - `test_multi_period_one_field_each_latest_first`: FY2024 and FY2023 with `fiscal_year_end=None` give 2 fields with `period_end` `["2024-12-31", "2023-12-31"]`, both carrying `fiscal_year_end_assumed`.
  - `test_duplicate_period_values_flag_conflict`
  - `test_legacy_draft_shape_still_validates`: `ExtractionDraft(value=42.0, citations=[…], confidence=0.9)` gives one `PeriodValue`.
  - `test_old_extracted_field_row_loads`: `{"field_id", "field_name", "value": None, "confidence": 0}` gives `not_found`, `value: 3.2` gives `found`, and `value: 0` gives `zero`.
  - `test_zero_and_not_found_end_to_end` in `test_extraction_pipeline.py`: a two-field schema run through `execute_extraction_run` with `FakeLLMClient`. The `results.jsonl` rows show `"zero"` and `"not_found"`.

- [ ] **Step 2: Run** `PATH=/tmp/claude-0/venv/bin:$PATH python -m pytest tests/test_aggregator.py tests/test_normalise_value.py tests/test_extraction_pipeline.py -v`. Expect FAIL.

- [ ] **Step 3: Implement as in Interfaces.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures, including `test_golden_set`, `test_rd_exposure_resolver` and `test_revenue_resolver`, which read `fields[0]`.

- [ ] **Step 5: Commit** with `feat(extraction): per-period values with unit, period, basis and value state (E30, E6)`.

---

### Task 10: Period-keyed review rows and downstream readers (E30)

**Files:**
- Modify: `arp/extraction/pipeline.py`. `_review_items` uses `field_item_key(rec.issuer_key, f.field_id, period_key(f))` and adds `"period_end": f.period_end` to the row.
- Modify: `arp/storage/postgres_company_facts_projection.py:159-175`. Keys are built per field row with `period_key(f)`, not in a dict keyed by `field_id`. An edit is applied to the row it was made on.
- Modify: `arp/decision/sources.py:153`. `by_name` keeps the first row per name (the latest period) instead of the last.
- Modify: `arp/api/routers/runs.py:146-151`. Append the CSV columns `value_state, unit, canonical_value, canonical_unit, period_start, period_end, basis` after the existing ones. Existing column order is unchanged.
- Test: `tests/test_extraction_pipeline.py`, `tests/test_postgres_company_facts_projection.py`, `tests/test_runs_export.py`, `tests/test_decision_sources.py` (extend each)

**Interfaces:**
- Consumes: `period_key` (Task 9), `field_item_key` (step 1).
- Produces:
  - The queue row gains `period_end: str | None`.
  - The key is `"{issuer_key}:{field_id}:{period_end or 'unspecified'}"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_review_key_uses_period_end`: a flagged value with `period_text="FY2024"` gives `item_key` ending in `":2024-12-31"`. An unresolvable period gives a key ending in `":unspecified"`.
  - `test_projection_two_periods_same_field`: a decision on the FY2023 key edits only the FY2023 row.
  - `test_projection_old_rows_without_period_unchanged`: a step-1-style row and its `…:unspecified` decision resolve as before.
  - `test_csv_export_has_value_state_columns`: zero and not_found are distinct in the CSV.
  - `test_decision_source_takes_latest_period`

- [ ] **Step 2: Run** the four test files with `-v`. Expect FAIL.

- [ ] **Step 3: Implement as in Files.**

- [ ] **Step 4: Run** the full backend check. Expect no new failures.

- [ ] **Step 5: Commit** with `feat(review): period-keyed extraction review rows; readers handle multi-period records (E30)`.

---

### Task 11: Frontend: value state, unit/period, span evidence, trial runs

**Files:**
- Modify: `frontend/src/types.ts`:
  - `Citation` gains the optional E43 fields.
  - `ExtractedField` gains the optional Task 9 fields: `value_state` is an optional union of the four states, and `fx_rate_ref` is a string.
- Create: `frontend/src/lib/fieldValue.ts`, `frontend/tests/fieldValue.test.ts`
- Modify: `frontend/src/lib/reviewKeys.ts`. `fieldItemKey(r, f)` takes the field (or `{field_id, period_end}`) instead of a bare `fieldId`. Update its callers in `ExtractionResults.tsx:150,169,181`.
- Modify: `frontend/src/components/ExtractionResults.tsx` (`FieldDetail`):
  - Show `valueLabel(f)`.
  - Show the period, and a "≈ {canonical_value} {canonical_unit}" line when it differs from `value`.
  - Show the qualifiers as small badges.
  - Show the FX ref as a muted line.
- Modify: `frontend/src/components/CitationList.tsx`. Show a muted "fuzzy match {score}" tag when `match_method === "fuzzy"`. Not voting-owned.
- Modify: `frontend/src/pages/Extraction.tsx:145-152`. Send `trial: job.profile === "custom" && !isReleased(job.schema)`.
- Modify: `frontend/tests/reviewKeys.test.ts`

**Interfaces:**
- Produces:
  - `valueLabel(f: ExtractedField): string`:
    - `not_found` gives `"not disclosed"`.
    - `not_applicable` gives `"not applicable"`.
    - `zero` gives `"0"` plus the unit when set.
    - `found` gives the value plus the unit when set.
    - When `value_state` is missing, it falls back to `value == null ? "not disclosed" : String(value)`.
  - `isReleased(schema: { release_flag?: boolean; fields: { status?: string }[] }): boolean`
  - `fieldItemKey(r: { company_id: string; issuer_key?: string | null }, f: { field_id: string; period_end?: string | null }): string`. It returns `${issuer_key}:${field_id}:${period_end ?? "unspecified"}`, or `${company_id}:${field_id}` when there is no `issuer_key`.

- [ ] **Step 1: Write the failing tests:**
  - `valueLabel` returns `"0 tCO2e"` for zero with a unit, `"not disclosed"` for not_found, `"not applicable"` for not_applicable, and handles a legacy field with no `value_state`.
  - `isReleased` is false for a draft field and true when `release_flag` is set and every field is released.
  - `fieldItemKey` with `period_end` gives a key ending in `:2024-12-31`. Without one it ends in `:unspecified`. An old record without `issuer_key` gives `company:field`.

- [ ] **Step 2: Run** `cd frontend && npm test`. Expect FAIL.

- [ ] **Step 3: Implement as in Files.**

- [ ] **Step 4: Run** `cd frontend && npm run lint && npm test && npm run build`. Expect 0 errors.

- [ ] **Step 5: Commit** with `feat(frontend): value state, unit and period, match evidence, trial runs`.
