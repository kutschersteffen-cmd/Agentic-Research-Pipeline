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
- A stored `source_url` overwritten, with null or with another URL.

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
  directory. A missing or unreadable file means no entries. Build `resolved local_path -> (url, reporting_year)`
  from entries with `alias_of` null. When two entries share a resolved `local_path`, the one whose `discovered_at`
  parses (`datetime.fromisoformat`) to the later instant wins; on an exact tie, the URL that sorts first wins. An
  entry whose `discovered_at` does not parse loses to any entry whose does.
- Match a file by `file_path.resolve()` against `Path(local_path).resolve()`, so a relative `documents_dir`
  matches the absolute path discovery wrote. A match passes `source_url=url` to
  `register_document` and puts `source_url` and `reporting_year` on the returned `SourceDocument`. No match keeps
  today's `source_url=None` and `reporting_year=None`. Manual uploads therefore stay as they are.
- `DocumentRegistry.register_document` (`db/documents.py:91-125`) today does not update `source_url` on conflict.
  Add it to the `on_conflict_do_update` set as `coalesce(documents.source_url, excluded.source_url)`. A stored URL
  is never replaced, so EDGAR and ESEF rows behave as today. Only a NULL URL gets filled: a document registered
  before this change gets its URL on its next fetch, and a later fetch without a URL never clears it.

`doc_id`, the parsed-content cache key and `parser_version` are untouched, so no re-parse happens.

## Left to the builder

Where the manifest lookup lives (a small function in `local_files.py` or in `change_detector.py`). Whether
`reporting_year` is threaded through `_parse_and_identify` or set when building the `SourceDocument` in `_fetch_one`.

## Acceptance

Shared fixtures:

- `u.json`: `[{"company_id": "acme", "name": "Acme AG", "country": "DE"}]`. With no CIK and a non-US country,
  EDGAR skips the network CIK lookup and returns no documents (`ingestion/edgar.py:111-115`).
- Environment for every `arp documents warm` row: `ARP_ESEF_ENABLED=false`, `ARP_DOCUMENTS_DIR=<tmp>/docs`,
  `ARP_DISCOVERY_STATE_DIR=<tmp>/state`, `ARP_POSTGRES_DSN` set to the test database and `ARP_DOCUMENT_CACHE_ENABLED=true`
  (the default), so the content store registers rows in Postgres. `get_settings()` creates `<tmp>/state`, so warm
  rows always run with an existing state directory.
- AC-6 to AC-9 call warm's command function with `arp.cli._shared._registry` (as imported by `arp.cli.documents`)
  patched to return the stand-in registry.
- `report.txt`: `<tmp>/docs/acme/sustainability_report/report.txt` with the text `Acme AG sustainability report.`
  Present in every row unless the row says otherwise.
- `bad.xyz`: `<tmp>/docs/acme/10-K/bad.xyz` with the bytes `not a document`. Intake accepts it; the parser raises
  `ValueError: Unsupported document file type: .xyz`.
- `blank.txt`: `<tmp>/docs/acme/10-K/blank.txt` containing only `   \n`.
- Manifest M: `<tmp>/state/acme.json` with one entry keyed `https://acme.example/r.txt`: `company_id` `acme`,
  `doc_type` `sustainability_report`, `url` `https://acme.example/r.txt`, `local_path` = absolute path of
  `report.txt`, `reporting_year` 2025, `alias_of` null, `discovered_at` `2026-06-01T00:00:00+00:00`.
- `K` = sha256 hex of the bytes of `report.txt`. `D` = `derive_doc_id("acme", "sustainability_report", K)`.
- "The stored row" = the `documents` row with `doc_id` = D.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | `report.txt` and `bad.xyz` | `arp documents warm --universe u.json` | Exit code 1 | holdout |
| AC-2  | Same as AC-1 | same | stderr contains the line `  acme: <absolute path of bad.xyz>: ValueError: Unsupported document file type: .xyz` | holdout |
| AC-3  | Same as AC-1 | same | stderr contains the line `1 failures:` | holdout |
| AC-4  | `report.txt` and `blank.txt` | `arp documents warm --universe u.json` | stderr contains the line `  acme: <absolute path of blank.txt>: no text extracted` | holdout |
| AC-5  | Same as AC-4 | same | Exit code 1 | holdout |
| AC-6  | A registry whose second source is a stand-in named `edgar` whose `fetch` raises `RuntimeError("down")` for `acme` | warm's command function with that registry | stderr contains the line `  acme: source edgar: RuntimeError: down` | unit |
| AC-7  | Same as AC-6 | same | Exit code 1 | unit |
| AC-8  | A registry whose `fetch_all` raises `RuntimeError("x")` for `acme` | warm's command function with that registry | stderr contains the line `  acme: x` | unit |
| AC-9  | Same as AC-8 | same | Exit code 1 | unit |
| AC-10 | Only `report.txt` | `arp documents warm --universe u.json` | Exit code 0 | holdout |
| AC-11 | Same as AC-10 | same | The last stdout line is `Warmed 1 documents across 1 companies.` | holdout |
| AC-12 | Same as AC-10 | same | stderr has no line ending in `failures:` and no line starting with two spaces | holdout |
| AC-13 | `report.txt` and `bad.xyz`, a stand-in source list of [local files] | `registry.fetch_all(acme)` | Returns exactly one document, with `doc_id` D | unit |
| AC-14 | `report.txt` and manifest M | `arp documents warm --universe u.json` | The stored row's `source_url` is `https://acme.example/r.txt` | holdout |
| AC-15 | `report.txt` and manifest M, source built with `discovery_state_dir` | `LocalFileDocumentSource.fetch(acme)` | The returned document's `reporting_year` is `2025` | unit |
| AC-16 | Same as AC-15 | same | The returned document's `source_url` is `https://acme.example/r.txt` | unit |
| AC-17 | `report.txt`; no `<tmp>/state/acme.json` | `arp documents warm --universe u.json` | The stored row's `source_url` is NULL | holdout |
| AC-18 | `report.txt`; source built with `discovery_state_dir=<tmp>/state`, which does not exist | `LocalFileDocumentSource.fetch(acme)` | `<tmp>/state` does not exist after the call | unit |
| AC-19 | `report.txt`; `<tmp>/state/acme.json` contains `{not json` | `arp documents warm --universe u.json` | Exit code 0 | holdout |
| AC-20 | Manifest with two entries for `report.txt`: U1 `https://acme.example/1.txt` with `discovered_at` `2026-06-01T00:00:00+00:00`, U2 `https://acme.example/2.txt` with `discovered_at` `2026-06-01T01:00:00+01:00` | `arp documents warm --universe u.json` | The stored row's `source_url` is U1 (U2 is the same instant; U1 sorts first) | holdout |
| AC-21 | As AC-20, U2's `discovered_at` is `2026-06-01T00:00:01+00:00` | same | The stored row's `source_url` is U2 | holdout |
| AC-22 | Manifest whose only entry for `report.txt` has `alias_of` `https://acme.example/other.txt` | same | The stored row's `source_url` is NULL | holdout |
| AC-23 | `ARP_DOCUMENTS_DIR` set to the relative path `docs` (cwd = `<tmp>`); manifest M with the absolute `local_path` | same, run from `<tmp>` | The stored row's `source_url` is `https://acme.example/r.txt` | holdout |
| AC-24 | Stored row for D with `source_url` NULL (inserted before the run); manifest M | same | The stored row's `source_url` is `https://acme.example/r.txt` | holdout |
| AC-25 | Stored row for D with `source_url` `https://acme.example/r.txt`; no manifest file | same | The stored row's `source_url` is `https://acme.example/r.txt` | holdout |
| AC-26 | Stored row for D with `source_url` `https://a.example/A`; manifest M (URL `https://acme.example/r.txt`) | same | The stored row's `source_url` is `https://a.example/A` | holdout |
| AC-27 | `report.txt` and manifest M | same | A `documents` row with `doc_id` D exists and no other row has `universe_id` `acme` | holdout |
| AC-28 | A `SourceDocument` S with title `report.txt`, `fiscal_period` None, a chunk C; `context_headers_enabled` on | `index_text(C, S with reporting_year 2025)` and `index_text(C, S with reporting_year None)` | The two strings are equal | unit |
| AC-29 | Manifest M; source built without `discovery_state_dir` (golden-set path) | `LocalFileDocumentSource.fetch(acme)` | The returned document's `source_url` is `None` | unit |
| AC-31 | Same as AC-19 | same | The stored row's `source_url` is NULL | holdout |
| AC-30 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: what `fetch_all` returns (AC-13), `doc_id` (AC-27), a stored URL (AC-25, AC-26), index text
(AC-28), golden-set fetches (AC-29), warm's exit code and output when nothing fails (AC-10 to AC-12), the rest of the
suite (AC-30).
