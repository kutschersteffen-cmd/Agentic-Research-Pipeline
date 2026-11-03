# Document provenance and warm failures

Spec slug: `document-provenance-warm-failures`. Gaps G4 and G5 of the universe-to-documents review
(https://claude.ai/artifact/FH7Q7fWJVUpxTRbjyKLx5a).

Status: draft.

## Why

`arp documents warm` (`backend/arp/cli/documents.py:16-51`) says it "surfaces any file that fails to parse now
instead of mid-run". It does not. `LocalFileDocumentSource.fetch` logs a parse error and drops the file
(`ingestion/local_files.py:493-495`). It also drops a file whose parsed text is empty (`:496-497`).
`DocumentSourceRegistry.fetch_all` logs a failing source and skips it (`ingestion/registry.py:35-37`). Warm only
catches exceptions that escape `fetch_all`, so its failure list stays empty. An unparseable annual report then
looks like "no evidence" in the theme run.

Discovery knows where each file came from. The per-company manifest
(`discovery_state_dir/<company_id>.json`, `discovery/change_detector.py:50-73`) maps each URL to a
`DiscoveredDocument` with `local_path` and `reporting_year`. The local file source ignores it and registers every
file with `source_url=None` (`local_files.py:336`). The returned `SourceDocument` has no source URL and no year.
Citations cannot link to the page the report came from, and the theme run cannot tell a 2019 report from a 2025
one.

## Goals

1. Warm prints every file that failed to parse, every file with no text, and every source that raised, then
   exits 1 when there was at least one.
2. A file that discovery downloaded gets its discovery URL as `source_url`, both on the returned
   `SourceDocument` and on the stored document row.
3. The same file gets discovery's `reporting_year` on the returned `SourceDocument`.

## Non-goals

- Changing what `fetch_all` returns to any caller (theme run, extraction, API).
- Reporting files that intake quarantined. They are already recorded in `_intake.jsonl`.
- Carrying `company_match` or `page_count` from the manifest. The discovery review queue (G3) owns those.
- Computing chunk embeddings in warm. Precomputing embeddings is owned by the A2 theme funnel session.
- Changing EDGAR or ESEF sources. They already set `source_url`.

## Anti-goals

- A changed `doc_id` for any existing document. `derive_doc_id` stays a function of company, doc_type and bytes.
- A changed index text or ranking. `reporting_year` must not reach `index_text` (`retrieval/index_text.py:17`).
- A stored `source_url` overwritten with null.

## Design

### Warm failures (G4)

Smallest seam: each object records what it dropped on an instance list. Return values stay the same.

- `LocalFileDocumentSource` gets `self.failures: list[str] = []`. `_fetch_one` appends
  `"<company_id>: <file_path>: <ExceptionType>: <message>"` in its existing `except`, and
  `"<company_id>: <file_path>: no text extracted"` where it returns `None` for empty text. Logging stays.
- `DocumentSourceRegistry` gets `self.failures: list[str] = []`. The existing per-source `except` in `fetch_all`
  appends `"<company_id>: source <source.name>: <ExceptionType>: <message>"`. Logging stays.
- `documents_warm`, after the run, collects its own whole-company failures (unchanged text
  `"<company_id>: <exc>"`), then `registry.failures`, then the `failures` of every source that has the attribute.
  It prints `Warmed N documents across M companies.` to stdout as today. When the combined list is not empty it
  prints `K failures:` to stderr, one indented line per failure, and exits with code 1. With no failures it exits 0
  and prints nothing to stderr.

The lists grow for the life of the object. API and theme-run registries never read them. Note this with a
`shortcut:` comment.

### Provenance from the discovery manifest (G5)

- `SourceDocument` gets one optional field: `reporting_year: int | None = None`. `fiscal_period` is left alone:
  EDGAR fills it with a filing date and ESEF with a period end, `discovery/pipeline.py:124` parses it as an ISO
  date, and `index_text` prints it, so a bare year there would mix formats and change ranking.
- `LocalFileDocumentSource.__init__` takes `discovery_state_dir: Path | None = None`. The two app constructors
  (`cli/_shared.py:69`, `api/deps.py:123`) pass `settings.discovery_state_dir`. The golden-set constructors
  (`golden_set/precision.py:62`, `golden_set/retrieval.py:81`) pass nothing, so they behave as today.
- At the start of `fetch`, when `discovery_state_dir` is set, read `<discovery_state_dir>/<company_id>.json`
  once. Read it directly as JSON (as `ChangeDetector._load_manifest` does), so the source never creates the
  directory. A missing or unreadable file means no entries. Build `local_path -> (url, reporting_year)` from
  entries with `alias_of` null. When two entries share a `local_path`, the one with the later `discovered_at` wins.
- Match a file by `str(file_path)` against the manifest `local_path`. A match passes `source_url=url` to
  `register_document` and puts `source_url` and `reporting_year` on the returned `SourceDocument`. No match keeps
  today's `source_url=None` and `reporting_year=None`. Manual uploads therefore stay as they are.
- `DocumentRegistry.register_document` (`db/documents.py:91-125`) today does not update `source_url` on conflict.
  Add it to the `on_conflict_do_update` set as `coalesce(excluded.source_url, documents.source_url)`. A document
  registered before this change gets its URL on its next fetch. A later fetch without a URL never clears it.

`doc_id`, the parsed-content cache key and `parser_version` are untouched, so no re-parse happens.

## Left to the builder

Where the manifest lookup lives (a small function in `local_files.py` or in `change_detector.py`). Whether
`reporting_year` is threaded through `_parse_and_identify` or set when building the `SourceDocument` in `_fetch_one`.

## Acceptance

Rows use a temporary `documents_dir` and `discovery_state_dir`. Company `acme` has
`documents_dir/acme/sustainability_report/report.pdf` (parses, has text) unless a row says otherwise. Manifest M
is `discovery_state_dir/acme.json` with one entry: url `https://acme.example/r.pdf`,
`local_path` = that file's path, `reporting_year` 2025, `alias_of` null.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Universe with `acme`; `documents_dir/acme/10-K/bad.pdf` makes the parser raise `ValueError("boom")` | `arp documents warm --universe u.json` | Exit code 1 | holdout |
| AC-2  | Same as AC-1 | same | stderr contains the line `  acme: <path of bad.pdf>: ValueError: boom` | holdout |
| AC-3  | Same as AC-1 | same | stderr contains the line `1 failures:` | holdout |
| AC-4  | `documents_dir/acme/10-K/empty.pdf` parses to whitespace only | `arp documents warm --universe u.json` | stderr contains `  acme: <path of empty.pdf>: no text extracted`; exit code 1 | holdout |
| AC-5  | A registry source named `edgar` whose `fetch` raises `RuntimeError("down")` for `acme` | `arp documents warm --universe u.json` | stderr contains `  acme: source edgar: RuntimeError: down`; exit code 1 | unit |
| AC-6  | Only `report.pdf`, which parses; no source raises | `arp documents warm --universe u.json` | Exit code 0, stderr empty, stdout ends with `Warmed 1 documents across 1 companies.` | holdout |
| AC-7  | Same as AC-1 | `registry.fetch_all(acme)` | Returns the same list of documents (by `doc_id`) as on `main` for the same files | unit |
| AC-8  | `report.pdf` and manifest M; source built with `discovery_state_dir` | `LocalFileDocumentSource.fetch(acme)` | The returned document's `source_url` is `https://acme.example/r.pdf` | holdout |
| AC-9  | Same as AC-8 | same | The returned document's `reporting_year` is `2025` | holdout |
| AC-10 | Same as AC-8, content store on Postgres | same, then `resolve_document(doc_id)` | The stored row's `source_url` is `https://acme.example/r.pdf` | holdout |
| AC-11 | `report.pdf`, no manifest file | `fetch(acme)` | `source_url` is `None` and `reporting_year` is `None`; no file is created under `discovery_state_dir` | holdout |
| AC-12 | Manifest file with invalid JSON | `fetch(acme)` | Returns the document with `source_url` `None`; no exception | unit |
| AC-13 | Manifest with two entries for the same `local_path`: url U1 `discovered_at` 2026-01-01, url U2 `discovered_at` 2026-06-01 | `fetch(acme)` | `source_url` is U2 | unit |
| AC-14 | Manifest with an entry for the file that has `alias_of` set and no other entry | `fetch(acme)` | `source_url` is `None` | unit |
| AC-15 | A row for `report.pdf` already stored with `source_url` NULL (registered before this change); manifest M | `fetch(acme)` | The stored row's `source_url` becomes `https://acme.example/r.pdf` | holdout |
| AC-16 | Stored row with `source_url` `https://acme.example/r.pdf`; manifest file deleted | `fetch(acme)` | The stored row's `source_url` is still `https://acme.example/r.pdf` | holdout |
| AC-17 | Same files, fetched on `main` and on this branch | `fetch(acme)` | `doc_id` is identical | holdout |
| AC-18 | Same as AC-8, `context_headers_enabled` on | `index_text` for a chunk of the document | Identical to the result on `main` (no `2025` added) | unit |
| AC-19 | Source built without `discovery_state_dir` (golden-set path); manifest M present | `fetch(acme)` | `source_url` is `None` | unit |
| AC-20 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: what `fetch_all` returns (AC-7), `doc_id` (AC-17), index text (AC-18), golden-set fetches
(AC-19), warm's exit code and output when nothing fails (AC-6), the rest of the suite (AC-20).
