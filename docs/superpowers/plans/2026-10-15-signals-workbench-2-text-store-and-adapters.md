# Signals workbench, plan 2: point-in-time text store and vendor adapters

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store text with event time and knowledge time, load it from Thomson Reuters news (full text), documents and transcripts, build fundamentals and analyst-revision panels as of the right date, and turn all of it into the inputs `arp signals evaluate` already takes.

**Architecture:** One insert-only Postgres table `text_items` behind `TextStore`. Vendor data enters through small adapter classes with a CSV implementation first, so a missing vendor blocks nothing. Everything is keyed by the issuer key the identifier map already uses. Panels are built on the same month grid as the price panel.

**Tech Stack:** Python 3.11, SQLAlchemy (existing `Base` and `transaction`), pydantic v2, typer. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-14-signals-workbench-design.md` (approved; see Components 2 and the Data sections). Plan 1 (merged, PR #146) is the base: `docs/superpowers/plans/2026-10-14-signals-workbench-1-evidence-and-registry.md`.

## Roadmap (plan 2 of 5)

1. Evidence core and registry (done, PR #146).
2. **This plan.**
3. Methods interface and methods.
4. Notebook library.
5. App screens and API.

Not in this plan: wiring `EdgarDocumentSource.fetch` into the text store automatically (the mapping function exists, the CLI call does not), historical 8-K/10-Q backfill (Thomson Reuters news is the chosen corpus), any real vendor adapter beyond CSV, changing `documents.published_at` from a date to a timestamp, any UI.

## Global Constraints

- Python `>=3.11`; every module starts with `from __future__ import annotations`; no new dependencies.
- **Issuer key** (the identifier map's `issuer_key`, also `company_id` everywhere in this plan) is the one identity: text records, panels and the CSV price columns all use it. Tickers are never an identity (`arp/db/companies.py` says why).
- **Canonical time string** is UTC to the second: `YYYY-MM-DDTHH:MM:SSZ`. Sub-seconds are dropped. A value with an offset is converted to UTC. A value with no offset and a time of day is ambiguous and raises `ValueError`. A date-only value means end of that day: `YYYY-MM-DDT23:59:59Z` (conservative: the market could not have read it earlier).
- **Event time** is when the market could first read the text (Thomson Reuters `firstCreated`, EDGAR `acceptanceDateTime`, the call time of a transcript). **Knowledge time** is when this system first stored that content. Backtests use event time only.
- A month's as-of moment is the last second of its calendar month (`month_end_time`). A score at grid index `i` may use only data with time `<=` that moment.
- `text_items` is insert-only: no updates, no deletes. A correction is a new row (new content hash) with the same `source_item_id`.
- Thomson Reuters response shapes follow the vendor documentation and are **unverified against the live service**; only the small parse functions named in Task 4 may change when a live response differs. Tests use fakes.
- Backend checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`. Tests that touch Postgres need `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test` (`pg` fixture in `tests/conftest.py`; if Postgres is down: `bash .claude/hooks/ensure-deps.sh postgres`).
- Never delete or weaken an existing test. Comments only for the why. Do not touch adjacent code. PRs target `main`.

## Review Focus

1. A date-only time becomes end of day, and a naive datetime raises (never silently UTC). (Task 1)
2. A corrected story keeps its event time; a read "known by" a moment before the correction returns the old text, after it the new text. (Task 2)
3. Re-adding identical content, or re-running a pull, adds nothing. (Tasks 2, 4)
4. A value restated after a month ended never appears in that month's fundamentals; a month with no revisions is `None`, never 0. (Tasks 6, 7)
5. A story naming two issuers gives one record per issuer; one naming none gives one record with no issuer, which the manifest skips. (Tasks 4, 8)

## File structure

| File | Responsibility |
|---|---|
| `backend/arp/signal_lab/times.py` | canonical time, month end, content hash |
| `backend/arp/db/models.py` | modify: `TextItem` table model |
| `backend/arp/signal_lab/text_store.py` | `TextRecord`, `TextStore` |
| `backend/arp/signal_lab/documents.py` | `SourceDocument` to `TextRecord` |
| `backend/arp/portfolio/news/api_source.py` | modify: `_stories` also returns the revision time |
| `backend/arp/portfolio/news/text_pull.py` | Thomson Reuters headlines plus full text into the store |
| `backend/arp/signal_lab/adapters/__init__.py`, `transcripts.py`, `revisions.py`, `fundamentals.py` | CSV adapters |
| `backend/arp/signal_lab/text_panel.py` | manifest for `arp replicate score-sentiment` from the store |
| `backend/arp/cli/signal_lab.py` | modify: four new commands |
| `backend/tests/test_signal_lab_*.py`, `backend/tests/test_news_text_pull.py` | tests |

---

### Task 1: Time and hash helpers

**Files:**
- Create: `backend/arp/signal_lab/times.py`
- Test: `backend/tests/test_signal_lab_times.py`

**Interfaces:**
- Produces: `normalise_time(value: str) -> str`; `month_end_time(period_end: str) -> str` (the last second of the month containing the ISO date); `content_hash_of(title: str, body: str) -> str` (SHA-256 hex of `f"{len(title)}:{title}\n{body}"`: length-prefixed, so a newline inside a title cannot make two different texts collide).

- [ ] **Step 1: Write the failing tests**
  - `test_date_only_is_end_of_day` (Review Focus 1): `normalise_time("2020-01-31") == "2020-01-31T23:59:59Z"`.
  - `test_zulu_and_millis`: `"2020-01-31T23:10:00.123Z"` becomes `"2020-01-31T23:10:00Z"`.
  - `test_offset_converted_to_utc`: `"2020-02-01T01:30:00+02:00"` becomes `"2020-01-31T23:30:00Z"`.
  - `test_naive_datetime_raises`: `"2020-01-31T23:10:00"` raises `ValueError`; so does `"31 Jan 2020"`.
  - `test_month_end_time`: `"2020-02-01"` gives `"2020-02-29T23:59:59Z"`; `"2021-12-15"` gives `"2021-12-31T23:59:59Z"`.
  - `test_content_hash_stable_and_sensitive`: same inputs equal; changing body or title changes it.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_signal_lab_times.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the three functions in `times.py` with `datetime`/`calendar` only.
- [ ] **Step 4: Run tests and `ruff check .`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): canonical time and content hash helpers`.

### Task 2: Text store

**Files:**
- Modify: `backend/arp/db/models.py` (add `TextItem`; follow the `Document` model's style, `Base` from `arp.storage.postgres_models`; no foreign key, `company_id` is a plain issuer key)
- Create: `backend/arp/signal_lab/text_store.py`
- Test: `backend/tests/test_signal_lab_text_store.py` (uses `pg`)

**Interfaces:**
- Consumes: `normalise_time`, `content_hash_of` (Task 1); `transaction(dsn)` from `arp.db.session`.
- Produces:
  - `class TextRecord(BaseModel)`: `item_id: str`, `source: str` (`"tr_news" | "edgar" | "transcript"` by convention), `source_item_id: str`, `company_id: str | None`, `event_time: str`, `knowledge_time: str`, `revision_time: str | None`, `content_hash: str`, `title: str`, `body: str`, `source_url: str | None`.
  - `make_record(*, source, source_item_id, company_id, event_time, knowledge_time, title, body, revision_time=None, source_url=None) -> TextRecord` (normalises all three times, computes `content_hash` and `item_id = "txt_" + sha256(f"{source}|{source_item_id}|{content_hash}")[:16]`).
  - `class TextStore`: `__init__(self, dsn: str)`; `add(rec: TextRecord) -> bool` (False if that `(source, source_item_id, content_hash)` already exists); `items(*, company_id: str | None = None, event_from: str | None = None, event_to: str | None = None, known_by: str | None = None) -> list[TextRecord]`; `latest_revision_time(source: str, source_item_id: str) -> str | None`.
  - `items` returns, per `(source, source_item_id)`, only the latest version with `knowledge_time <= known_by` (latest overall when `known_by` is None), inside the inclusive event window (bounds normalised), ordered by `(event_time, item_id)`.

- [ ] **Step 1: Write the failing tests** (real `TextStore(pg)`):
  - `test_add_is_idempotent` (Review Focus 3): adding the same record twice returns True then False; `items()` has one row.
  - `test_correction_keeps_event_time_and_is_visible_by_knowledge_time` (Review Focus 2): version 1 at knowledge `2020-02-01T00:00:00Z`, version 2 (different body, same `source_item_id`, same event time) at `2020-03-01T00:00:00Z`; `items(known_by="2020-02-15T00:00:00Z")` returns version 1 only, `items(known_by="2020-03-02T00:00:00Z")` returns version 2 only, `items()` returns version 2 only.
  - `test_event_window_and_company_filter`: records for two issuers across three days; filters return the expected ids; bounds are inclusive.
  - `test_null_company_is_stored_and_filterable`: `company_id=None` round trips; `items(company_id=None)` returns everything including it (None means no filter).
  - `test_latest_revision_time`: returns the maximum stored `revision_time` for the pair, `None` when none.
- [ ] **Step 2: Run** `ARP_TEST_POSTGRES_DSN=... python3 -m pytest tests/test_signal_lab_text_store.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the model (unique constraint on `(source, source_item_id, content_hash)`, index on `(company_id, event_time)` and on `(source, source_item_id, knowledge_time)`, timestamps `DateTime(timezone=True)`) and the store (`insert ... on conflict do nothing`; the latest-version rule via a window function or a correlated subquery). The `pg` fixture truncates every model table, so no helper change is needed; confirm by running the test twice in one session.
- [ ] **Step 4: Run tests and `ruff check .`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): insert-only point-in-time text store`.

### Task 3: Documents into the store

**Files:**
- Create: `backend/arp/signal_lab/documents.py`
- Test: `backend/tests/test_signal_lab_documents.py`

**Interfaces:**
- Consumes: `SourceDocument` (`backend/arp/schemas/common.py`), `make_record` (Task 2).
- Produces: `records_from_documents(docs: list[SourceDocument], *, knowledge_time: str) -> list[TextRecord]`. Mapping: `source="edgar"` for `DocType.ANNUAL_REPORT_10K` and `DocType.PROXY_DEF14A`, `"transcript"` for `DocType.EARNINGS_TRANSCRIPT`, `"document"` otherwise; `source_item_id = doc.doc_id`; `company_id = doc.company_id`; `event_time = doc.published_at`; `title`, `body = doc.full_text`, `source_url = doc.source_url`. A document with no `published_at` is skipped (no event time, no evidence).

- [ ] **Step 1: Write the failing tests:** an EDGAR-style doc with `published_at="2023-02-03T16:05:23.000Z"` maps to event time `2023-02-03T16:05:23Z` and source `edgar`; a date-only `published_at` becomes end of day; a doc without `published_at` is skipped; a transcript doc maps to source `transcript`.
- [ ] **Step 2: Run** and confirm FAIL.
- [ ] **Step 3: Implement** `records_from_documents`.
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): map source documents to text records`.

### Task 4: Thomson Reuters headlines and full text into the store

**Files:**
- Modify: `backend/arp/portfolio/news/api_source.py` (`_stories` also returns `revised_at`: the story's `versionCreated`; keep every existing key and behavior; `pull_news` is unchanged)
- Create: `backend/arp/portfolio/news/text_pull.py`
- Test: `backend/tests/test_news_text_pull.py` (uses `pg`; extend `tests/test_news_api_source.py`'s fake-fetcher style, read it first)

**Interfaces:**
- Consumes: `_token`, `_stories`, `Fetcher`, `PERMIDS_PER_QUERY`, `MAX_PAGES` from `api_source`; `IdentifierMapStore.resolve`; `extract_html_text` (`arp/ingestion/html_text.py`); `TextStore`, `make_record`.
- Produces: `pull_news_text(store: TextStore, settings: Settings, idmap: IdentifierMapStore, *, since: str | None = None, fetcher: Fetcher | None = None, now: str | None = None) -> dict` returning `{"stories": int, "records": int, "unmatched": int}`; `_story_body(data: bytes) -> str` (parse the story response: HTML to text; `ValueError("unexpected Refinitiv story response")` for any other shape). The story request is `GET {news_api_url}/data/news/v1/stories/{storyId}` with the same bearer token. Response shape assumed: `{"newsItem": {"contentSet": {"inlineXML": [{"$": "<html fragment>"}]}}}` (documentation-based, unverified).

Rules: for each story and each uniquely PermID-matched issuer, one record with `source="tr_news"`, `source_item_id=f"{storyId}:{issuer}"`; a story with no matched issuer gets one record with `company_id=None` and `source_item_id=storyId`. `event_time` is `published_at` (`firstCreated`), `revision_time` is `revised_at`, `knowledge_time` is `now` (default: current UTC). A story is fetched only if `store.latest_revision_time(...)` is `None` or earlier than its `revised_at`; otherwise skipped (no body fetch). Credentials and PermID checks behave like `pull_news` (same `ValueError` messages for missing credentials or no PermIDs; no secret in any message).

- [ ] **Step 1: Write the failing tests** (fake fetcher, fake idmap rows with PermIDs):
  - `test_story_with_two_issuers_gives_two_records` and `test_story_with_no_issuer_gives_one_unlinked_record` (Review Focus 5).
  - `test_rerun_adds_nothing_and_fetches_no_body` (Review Focus 3): the second pull makes no `/stories/` request (count them in the fake) and adds no row.
  - `test_revised_story_is_a_new_version`: second pull where `versionCreated` is later and the body differs: a new row, same `event_time`, and `items(known_by=<between the two pulls>)` returns the old text.
  - `test_html_body_becomes_text`; `test_unexpected_story_shape_raises_value_error`.
  - `test_missing_credentials_raises_without_leaking`: the message contains neither the client id nor the secret.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_news_text_pull.py tests/test_news_api_source.py -v`. Expected: FAIL (new tests); the existing news tests must still pass after Step 3.
- [ ] **Step 3: Implement** `_stories`' extra key and `text_pull.py`.
- [ ] **Step 4: Run both test files and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(news): Thomson Reuters full text into the point-in-time store`.

### Task 5: Transcript adapter (CSV)

**Files:**
- Create: `backend/arp/signal_lab/adapters/__init__.py` (empty), `backend/arp/signal_lab/adapters/transcripts.py`
- Test: `backend/tests/test_signal_lab_adapter_transcripts.py`

**Interfaces:**
- Consumes: `make_record`, `TextRecord`.
- Produces: `class TranscriptSource(Protocol)` with `records(self) -> list[TextRecord]`; `class CsvTranscriptSource(path: Path, *, now: str | None = None)` implementing it. CSV columns: `issuer_key,event_time,title,text` plus optional `source_item_id` (default: first 16 hex of SHA-256 of `issuer_key|event_time|title`) and optional `knowledge_time` (default: `now`, else current UTC). `source="transcript"`. A missing required column or an empty `issuer_key`/`event_time` raises `ValueError` naming the file and row number.

- [ ] **Step 1: Write the failing tests:** two rows give two records with source `transcript`; naive `event_time` raises `ValueError` naming the row; a missing `text` column raises; an explicit `knowledge_time` column is honored; default `source_item_id` is stable across two reads.
- [ ] **Step 2: Run** and confirm FAIL.
- [ ] **Step 3: Implement** with the `csv` module.
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): CSV transcript adapter`.

### Task 6: Analyst-revision adapter (CSV)

**Files:**
- Create: `backend/arp/signal_lab/adapters/revisions.py`
- Test: `backend/tests/test_signal_lab_adapter_revisions.py`

**Interfaces:**
- Consumes: `normalise_time`, `month_end_time`; `CharacteristicPanel` (`backend/arp/replication/characteristics_data.py`).
- Produces: `class RevisionSource(Protocol)` with `get_panel(self, issuer_keys: list[str], period_ends: list[str], *, window_months: int = 3) -> CharacteristicPanel`; `class CsvRevisionSource(path: Path)`. CSV columns `issuer_key,event_time,direction` with `direction` in `up` or `down` (EPS estimate revisions). The value at grid index `i` is `(up - down) / (up + down)` over revisions whose event time lies in the `window_months` calendar months ending at month `i` (from the first second of month `i - window_months + 1` through `month_end_time(period_ends[i])`); `None` when `up + down == 0`. `source="analyst_revisions"`. Defined as net ratio in `[-1, 1]` instead of the raw upgrades-to-downgrades ratio so it is bounded and defined with zero downgrades (a builder call, flagged for the owner).

- [ ] **Step 1: Write the failing tests:** 3 up and 1 down in the window give `0.5`; a month with no revisions is `None`, not 0 (Review Focus 4); a revision dated after `month_end_time` of month `i` does not count at `i` but does at `i+1`; a revision older than the window does not count; an unknown direction raises `ValueError` naming the row; issuers absent from the file get an all-`None` column; `window_months=1` changes the result as expected.
- [ ] **Step 2: Run** and confirm FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): CSV analyst-revision adapter`.

### Task 7: Fundamentals adapter (CSV, as-reported)

**Files:**
- Create: `backend/arp/signal_lab/adapters/fundamentals.py`
- Test: `backend/tests/test_signal_lab_adapter_fundamentals.py`

**Interfaces:**
- Consumes: `normalise_time`, `month_end_time`; `CharacteristicPanel`.
- Produces: `class FundamentalSource(Protocol)` with `get_panel(self, metric: str, issuer_keys: list[str], period_ends: list[str]) -> CharacteristicPanel`; `class CsvFundamentalSource(path: Path)`. CSV columns `issuer_key,metric,fiscal_period_end,available_time,value`. At grid index `i`, an issuer's value is the `value` of the row for that metric with `available_time <= month_end_time(period_ends[i])`, choosing the greatest `fiscal_period_end`, then the greatest `available_time` (so a restatement counts only from the moment it was published). `None` when no row is available. `source=f"fundamentals:{metric}"`. A non-numeric `value`, a naive time or a missing column raises `ValueError` naming file and row.

- [ ] **Step 1: Write the failing tests:** a value available in March is `None` for January and February and present from March; a restatement published in June for the March period replaces it from June only, so the March, April and May columns still hold the original (Review Focus 4); a newer fiscal period beats an older one that was restated later; unknown metric gives all `None`; non-numeric value raises with the row number.
- [ ] **Step 2: Run** and confirm FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): CSV as-reported fundamentals adapter`.

### Task 8: Manifest from the store, CLI commands, docs

**Files:**
- Create: `backend/arp/signal_lab/text_panel.py`
- Modify: `backend/arp/cli/signal_lab.py`, `docs/TECHNICAL_REFERENCE.md` (the `arp signals` entry added in plan 1)
- Test: `backend/tests/test_signal_lab_text_panel.py`, `backend/tests/test_signal_lab_cli_text.py` (use `pg`; read `tests/test_signal_lab_cli.py` for the CLI test setup)

**Interfaces:**
- Consumes: `TextStore`, `TextRecord`; the adapters; `pull_news_text`; `CsvPriceSource`/`read_wide_csv` for the price grid.
- Produces: `manifest_from_text_items(items: list[TextRecord]) -> list[dict]` (entries `{ticker, period_end, published_at, doc_id, text}`, the shape `arp replicate score-sentiment` reads; `ticker` is the issuer key; `period_end` is the first day of the event time's UTC month; `published_at` is the event time; `doc_id` is the item id; `text` is title, blank line, body; items with `company_id is None` are skipped). Commands:
  - `arp signals pull-news-text [--since ISO]`: runs `pull_news_text` with the portfolio's identifier map (see `arp/cli/portfolio.py` around line 265 for how `pull_news` is wired) and prints the counts.
  - `arp signals text-manifest --out m.json [--event-from ISO] [--event-to ISO] [--known-by ISO]`: writes the manifest.
  - `arp signals ingest-transcripts --csv t.csv`: adds the records and prints how many were new.
  - `arp signals build-panel --kind fundamentals|revisions --csv f.csv --prices p.csv --out panel.csv [--metric NAME] [--window-months 3]`: builds the panel on the price CSV's date grid and issuers (the CSV's columns) and writes a wide CSV (`date` plus one column per issuer, empty for `None`) that `arp signals evaluate --scores` reads. `--metric` is required for `fundamentals`.
  - All commands exit 1 with the library's `ValueError` message on stderr.

- [ ] **Step 1: Write the failing tests:** `test_manifest_skips_unlinked_and_buckets_by_event_month` (Review Focus 5; an item at `2020-01-31T23:10:00Z` lands in `2020-01-01`); `test_manifest_text_is_title_blank_line_body`; CLI: `ingest-transcripts` then `text-manifest` round trip yields the transcript with its month; a second `ingest-transcripts` of the same file reports 0 new; `text-manifest --known-by` earlier than the ingestion excludes the record; `build-panel --kind fundamentals` output has the price CSV's dates as its first column and feeds `arp signals evaluate --scores` without a grid error (use plan 1's synthetic CSV helpers from `tests/test_signal_lab_cli.py`); `build-panel --kind fundamentals` without `--metric` exits 1; `pull-news-text` with missing credentials exits 1 without leaking the secret.
- [ ] **Step 2: Run** and confirm FAIL.
- [ ] **Step 3: Implement** `manifest_from_text_items` and the four commands; add the commands and a one-line description each to the `arp signals` entry in `docs/TECHNICAL_REFERENCE.md`.
- [ ] **Step 4: Run** the new tests, then `python3 -m pytest tests -q -k "signal_lab or news or replication"` and `ruff check .`, then `python3 -c "import arp.cli"`. Expected: PASS (one known browser-dependent reporting test and one known flaky extraction test may fail; they are unrelated).
- [ ] **Step 5: Commit** `feat(signal-lab): text manifest and ingestion commands`.

---

## Self-review

- **Spec coverage:** point-in-time text store with event and knowledge time, hash, entity link (Tasks 1, 2); sources Thomson Reuters full text (Task 4), EDGAR with acceptance time (Task 3 mapping), transcripts (Task 5); vendor adapters for analyst revisions and fundamentals behind interfaces with CSV first and restatement-aware as-of handling (Tasks 6, 7); inputs for evaluation (Task 8). Left out on purpose: automatic EDGAR wiring, real vendor adapters, `documents.published_at` migration.
- **Step scan:** every step names a signature, test or command.
- **Type consistency:** `TextRecord`, `make_record`, `TextStore.items`, `latest_revision_time`, `normalise_time`, `month_end_time`, `CharacteristicPanel` are defined once and reused with the same names.
- **Proportion:** about the length of plan 1, no function bodies.
- **Owner flags:** the net revision ratio definition; the unverified Thomson Reuters story shape; `known_by` is only meaningful for data ingested live (a historical backfill carries its backfill time as knowledge time, so apply `--known-by` only to live-ingested items).
