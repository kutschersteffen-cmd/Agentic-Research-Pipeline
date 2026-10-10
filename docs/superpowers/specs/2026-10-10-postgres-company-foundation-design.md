# Postgres company foundation — phase 1 design

Status: approved in brainstorming, 2026-10-10. Next: implementation plan.

## 1. Goal

**One company view**: everything the system knows about a company — extracted values, provider
data, XBRL facts, documents, runs, review state, holdings — answerable with one query against one
stable company key.

Decisions taken:

| Question | Decision |
|---|---|
| What is the foundation? | Postgres + pgvector becomes **required** and **authoritative**. |
| What identifies a company? | A database-assigned UUID. LEI, ISIN, CIK, ticker, universe id and provider issuer ids are aliases in `company_identifiers`. |
| File stores? | Replaced in phases. Phase 1 moves companies, fields, runs, review and facts. No dual-write period, no parallel file backend. |
| Provider metrics (e.g. ESG API)? | Stored as their **own** fields with stable ids. Never mapped automatically onto extracted fields. |

Why: today a company is identified three ways (universe `company_id`, a recomputed `issuer_key`,
and `cik`, which sometimes holds an LEI). The run results that describe a company sit in one JSONL
file per run, so a company view means loading every run into Python
(`backend/arp/api/company_results.py`). The opt-in Postgres projections that tried to fix this
carry their own bugs (see §8).

## 2. Data model

Conventions for every table below:

- Dates are `date`, timestamps are `timestamptz`. No date-as-string columns.
- Status and kind columns are Postgres enums.
- `company_id` is `uuid` with a foreign key to `companies` everywhere it appears.
- Insert-only tables are never `UPDATE`d except for closing a validity range (`valid_to`,
  `superseded_by`).

### 2.1 Companies

```
companies             id uuid PK · name · country · sector · isic_code
                      · fiscal_year_end (MM-DD, CHECK) · regimes text[] · created_at

company_identifiers   company_id FK · scheme enum (LEI, ISIN, CIK, TICKER, UNIVERSE, INTERNAL,
                      <provider schemes>) · value · valid_from date · valid_to date NULL
                      UNIQUE (scheme, value) WHERE valid_to IS NULL
```

Resolution of an incoming row (universe file, provider record):

1. Look up its identifiers in order LEI → ISIN → CIK → UNIVERSE (→ provider id for provider rows).
2. All matches point at one company → attach; add any identifiers not yet recorded.
3. No match → universe rows create a new company with all identifiers; **provider rows never
   create companies** — they go to the review list.
4. Matches point at different companies → nothing is created or attached; the row goes to the
   Identity Resolution page as an identity conflict.

`issuer_key()` becomes a lookup of this table, not a per-run computation. A security-master upload
adds identifiers; it never changes a company's key.

Merging duplicates (`arp db companies merge <keep> <drop>`) moves identifiers and every FK row from
`drop` to `keep` in one transaction and records the merge as a `MERGED_INTO` identifier on `drop`'s
former aliases. Phase 1 ships the CLI only.

### 2.2 Fields

```
fields                field_id PK · kind enum (extracted, provider) · source_id FK NULL
                      · created_at · retired_at NULL
                      CHECK field_id ~ '^(fld_[a-z0-9]+|prov:[a-z0-9_]+:[a-z0-9_]+)$'

field_definitions     field_id FK · version · name · data_type · unit
                      · definition jsonb (the full FieldDefinition) · effective_from date
                      PK (field_id, version)

data_schemas          schema_id · version · name · released_at · released_by
                      PK (schema_id, version)
data_schema_fields    schema_id/version FK · field_id/version FK

provider_metric_codes source_id FK · provider_code · field_id FK
                      UNIQUE (source_id, provider_code)
```

Field id rules:

- Extracted fields keep today's `fld_<random>` ids (`new_id("fld")`), so imported history keeps
  its ids.
- Provider fields are `prov:<source_slug>:<metric_code>`. `metric_code` is the provider's code
  (not its display name), lowercased, non-alphanumerics replaced by `_`.
- A field id is never reused: `fields` rows are retired (`retired_at`), never deleted.
- `data_sources.slug` is immutable after creation.
- A provider renaming a code: an admin adds a `provider_metric_codes` row pointing the new code at
  the existing `field_id`.
- A changed definition (unit, methodology) is a new `field_definitions` version, same `field_id`.
- Two provider codes normalising to the same id: that metric is not ingested and is listed for
  review.

`SchemaRegistry` (`backend/arp/storage/schema_registry.py`) moves onto these tables, keeping its
current methods (`get`, `save`, `release`, `quality`, `record_first_audit`).

### 2.3 Runs

```
runs                  run_id PK · run_type · status enum · params jsonb · company_count
                      · completed_count · failed_count · review_count · input_tokens
                      · output_tokens · estimated_cost_usd numeric · model · verifier_model
                      · error · cancel_requested · created_at · updated_at
run_companies         run_id FK · company_id FK                       PK (run_id, company_id)
run_results           id · run_id FK · company_id FK · result jsonb · created_at
                      UNIQUE (run_id, company_id)
run_errors            id · run_id FK · company_id FK NULL · error jsonb · created_at
run_held_documents    run_id FK · company_id FK · doc_id FK · reason · created_at
```

`run_results.result` keeps each run type's Pydantic model as JSONB; per-field values are
additionally written as observations (§2.5).

### 2.4 Sources

```
documents             doc_id PK · company_id FK · doc_type · title · content_key
                      · storage_uri · source_url · local_path · published_at · family_id
                      · version · supersedes FK NULL · first_seen_at · last_seen_at
                      · identity_confidence · identity_review
chunk_embeddings      chunk_id · embed_model · embedding vector(EMBED_DIM)   (unchanged)

data_sources          source_id PK · slug (immutable, unique) · name · kind enum (api, file)
                      · licence enum (internal_only, redistributable) · id_scheme
source_loads          load_id PK · source_id FK · fetched_at · as_of date · request jsonb
                      · payload_uri · payload_sha · status enum (fetched, ingested, failed)
                      UNIQUE (source_id, payload_sha)
```

`documents` is today's `document_registry`, now authoritative and with a company FK. Existing
`doc_id`s are kept on import. New ids use the existing `derive_doc_id` formula with the company's
`UNIVERSE` alias, so the formula does not change.

Raw provider payloads are written to object storage before parsing; a failed ingest is retried
from `payload_uri` without calling the provider again. A load with an already-seen `payload_sha` is
recorded as unchanged and not re-ingested.

### 2.5 Values

```
field_observations    id · company_id FK · field_id · field_version  (FK field_definitions)
                      · source_kind enum (extraction, provider, xbrl, manual)
                      · run_id FK NULL · source_id FK NULL · load_id FK NULL
                      · period_start date · period_end date · basis (default '')
                      · value jsonb · value_state enum (found, zero, not_found, not_applicable)
                      · unit · canonical_value numeric · canonical_unit · scale_applied · fx_rate
                      · confidence · checks jsonb · route enum NULL · method · created_at
                      insert-only

value_citations       id · observation_id FK · doc_id FK · content_key · page · sheet
                      · location · quote · span_text · char_start · char_end · table_ref jsonb
                      · passage_id · grounded bool · match_method · match_score
                      · role enum (primary, corroborating, alternative)
```

- One `ExtractedField` becomes one observation; each of its `Citation`s becomes a citation row.
  `alternatives` with their own citations become `role = alternative` rows.
- `content_key` pins the exact bytes read, even if the document is later replaced.
- `passage_id` links to the chunk whose embedding lives in `chunk_embeddings`.
- Provider observations carry `source_id` and `load_id` instead of citations.
- Non-extraction run types write observations with these field ids: theme → `theme:<activity_id>`,
  voting → `vote:<meeting_id>:<proposal_number>`, financials → the financials template's fields.
  These are registered in `fields` as `kind = extracted`.

### 2.6 Review

```
review_items          id · run_id FK · company_id FK · observation_id FK NULL · payload jsonb
                      · state enum · queued_at
review_decisions      id · review_item_id FK · decision enum (approve, edit, correct, reject,
                      escalate, hold) · reviewer · user_id · role · edited_value jsonb
                      · comment · decided_at                                  insert-only
review_cosigns        id · review_item_id FK · reviewer · user_id · role · decided_at
                                                                              insert-only
```

These replace `review_queue.jsonl`, `review_decisions.jsonl`, `review_cosigns.jsonl` and the
`"{key}:{field}:{period}"` item-key strings. An unknown decision value is rejected by the enum, not
coerced to "rejected".

### 2.7 Facts

```
company_facts         id · company_id FK · field_id · period_end date · basis
                      · value jsonb · canonical_value numeric · canonical_unit
                      · status enum (auto_accepted, approved, edited, pending_review, held)
                      · observation_id FK · decision_id FK NULL · conflicting_sources bool
                      · valid_from · valid_to NULL · superseded_by FK NULL
                      UNIQUE (company_id, field_id, period_end, basis) WHERE valid_to IS NULL
```

The current-fact rules, applied by one function (`arp/db/observations.record`):

| Incoming | Effect on `company_facts` |
|---|---|
| New (field, period, basis) | Insert a current fact. Other periods are untouched (time series). |
| Same key, same value and status | No change; only the observation is kept. |
| Same key, different value, accepted (auto-accept or review decision) | Close the current fact (`valid_to`, `superseded_by`) and insert the new one. |
| Same key, value pending review | Current fact stays; the pending observation is visible next to it. |
| `value_state = not_found` | Observation only. A miss never removes an existing fact. |
| Restatement | Same as "different value, accepted"; the observation's citation names the restating document. |
| Documents cover another entity | Fact status `held`; never published. |
| Trial run (draft schema fields) | Observations only; no facts. |

### 2.8 Re-keyed, otherwise unchanged

`holdings`, `securities`, `security_resolutions`, `published_facts`, `releases`, `fact_events` and
`bi_published` keep their current shape. Columns holding a company identity (`company_id`,
`issuer_key`/`issuer_scheme`) become `company_id uuid FK`. `published_facts.citation` becomes a
reference to `value_citations` rows. `published_facts` and `company_facts` share the key
`(company_id, field_id, period_end, basis)`; merging them is out of scope.

Facts from an `internal_only` source are refused by `published_facts` and excluded from BI
exports (enforced in the publish path and by a check against `data_sources.licence`).

## 3. Code structure

```
backend/arp/db/session.py       engine, transaction() context manager, startup check
backend/arp/db/companies.py     resolve(row) → company_id | conflict · register · merge
backend/arp/db/fields.py        register_provider_field · get_definition · SchemaRegistry
backend/arp/db/runs.py          RunStore (same public method names), table-backed
backend/arp/db/observations.py  record(observations, citations) — the only writer of company_facts
backend/arp/db/review.py        queue · decide · cosign
backend/arp/db/providers.py     record_load · ingest_rows
```

- Pydantic models in `backend/arp/schemas/` remain the API contract. Rows convert to them at the
  `arp/db` boundary. Existing API response shapes do not change.
- Sessions are synchronous (as in the existing Postgres code); pipeline code calls writes through
  `asyncio.to_thread`.
- `get_run_store` and the other stores in `api/deps.py` return the table-backed implementations.

### 3.1 Write path

`orchestration/batch_runner.run_company_batch._on_success` is the one place every pipeline's
result passes through. In one transaction per company it writes:

1. `run_results` row,
2. observations from the run type's pure `to_observations(company_id, result)` function,
3. their citations,
4. review items for routed observations,
5. fact updates via `observations.record`.

`orchestration/review_queue.record_review_decision` writes the decision and calls
`observations.record` in the same transaction.

### 3.2 Concurrency

`observations.record` takes `SELECT … FOR UPDATE` on the current fact row. A race on the first
insert for a key is caught by the partial unique index; the transaction retries once. This replaces
`KeyedLock` for run state and makes multiple API workers safe.

## 4. Company view

### 4.1 API

| Endpoint | Returns |
|---|---|
| `GET /api/companies?q=` | Search by name or any identifier. |
| `GET /api/companies/{id}` | Identity, identifiers, counts (facts by status, open review items, documents, runs), portfolios/indices holding it as of today. |
| `GET /api/companies/{id}/facts?as_of=&kind=&field_id=&period_end=` | Current (or as-of) facts, one row per (field, period, basis): value, canonical value/unit, status, source kind, one-line source, licence, conflict flag. Paged. |
| `GET /api/facts/{fact_id}/trail` | Every version, the observations behind each, citations to page/offset/chunk, provider load, review decisions. |

`{id}` accepts the UUID or an alias (`LEI:…`, `UNIVERSE:…`).

As-of: `valid_from <= $as_of AND (valid_to IS NULL OR valid_to > $as_of)`.

Existing endpoints `extraction/companies/{id}/results`, `financials/companies/{id}/results` and
`runs/known-companies` keep their response shapes and become queries; `api/company_results.py` is
deleted.

### 4.2 Frontend

One new **Company** page: header (identity, identifiers), facts table (filters: kind, field,
period; as-of date picker), side panel with a fact's trail; a citation opens the document page, a
provider value shows its load. Company names elsewhere link to it. Built with the impeccable and
ui-ux-pro-max skills against `DESIGN.md`. `frontend/src/types.ts` gains the matching types.

## 5. Error handling

| Situation | Behaviour |
|---|---|
| Postgres unreachable at startup | API and CLI refuse to start, naming the DSN tried. No file fallback. |
| Database lost mid-run | Per-company transaction retried 3× with backoff; then the run is `failed` and resumable (committed companies are skipped). |
| Identity conflict | Row not attached; listed on Identity Resolution; run records `identity_conflict`. |
| Value violates field data type | Rejected to `run_errors` with the raw value; facts untouched. |
| Provider ingest failure | Payload already stored; retry re-parses it. Unmatched issuers and colliding codes go to review. |
| Concurrent fact update | Row lock → unique index → one retry. |

No best-effort hooks remain: a failed write fails the operation visibly.

## 6. Migration order

Each step merges with the suite green.

1. **Methods instead of paths (file-backed).** Add `read_results`, `append_result`, `read_errors`,
   `read_review_queue`, `read_decisions`, `read_cosigns`, etc. to `RunStore`. Move every
   `run_store.*_path(` caller onto them (68 `results_path` sites, ~100 in total). Add a test that
   fails on new `*_path(` usage outside `RunStore`.
2. **Schema.** Add the §2 tables via `postgres_schema.ensure_schema` (create_all + recorded
   `SCHEMA_STEPS`); FK/enum/partial-index DDL that `create_all` cannot infer goes into steps.
3. **Company and field registries.** `arp/db/companies.py`, `arp/db/fields.py`; universe loading
   and `issuer_key()` resolve through them.
4. **Table-backed RunStore and review.** `arp/db/runs.py`, `arp/db/review.py`; `api/deps` returns
   them; the suite runs against Postgres.
5. **Observations and facts.** `to_observations` per run type; `observations.record`; write path
   in `run_company_batch` and `record_review_decision`.
6. **Provider source tables.** `arp/db/providers.py`; the existing ESG file intake
   (`portfolio/climate/esg_intake.py`) writes through it as a `kind = file` source.
7. **Company API and page.**
8. **Import and verify.** `arp db import [--dry-run]` replays runs, universe files, identifier map,
   schema registry and `content.db` **oldest first**, idempotent by natural keys.
   `arp db verify` compares file and database (rows per run, current fact per company/field).
9. **Delete.** File `RunStore` internals and run JSONL helpers; `postgres_company_records_projection.py`,
   `postgres_company_facts_projection.py`, `postgres_document_projection.py` and their hooks;
   `index_checkpoints`; settings `portfolio_backend`, `embeddings_backend`,
   `*_projection_enabled`; the SQLite embeddings cache; optional-Postgres branches. Update
   `docs/METHODOLOGY.md` and `docs/INSTALLATION.md` (Postgres is required).

## 7. Cut-over

1. `arp db import --dry-run`: counts per area, unresolved identities, identifier and fact
   conflicts. Writes nothing.
2. `arp db import`.
3. `arp db verify` must report zero differences before the API starts.
4. Files remain on disk, read-only, for one release; the code never deletes them.
5. Rollback = redeploy the previous release (which reads the files). Data written after cut-over
   is not in the files; release notes say so.

## 8. Review findings closed by phase 1

From the 2026-10-10 data-model review:

- Full `company_facts` reindex leaves the oldest run's value current (replay is oldest first).
- Run types overwrite each other's facts (fact key includes `field_id`, period and basis).
- Two current facts possible under concurrency (partial unique index + row lock).
- Company identified three ways; `issuer_key` recomputed per run (UUID + identifiers).
- Postgres `companies` drops `lei`, `isin`, `regimes`, `fiscal_year_end`.
- `company_records.needs_review` / `overall_confidence` NULL for theme and voting (table removed).
- Unknown review decision stored as "rejected" (enum).
- `held_documents: list[dict]` (`run_held_documents`).
- Dates stored as strings in the database (typed columns).

Not closed here: `DecisionStore` can overwrite a ratified version, and ratification fields are
client-writable. Those stores move in phase 3; fix them separately now.

## 9. Testing

- **No database:** `to_observations` per run type; the §2.7 fact rules; field-id normalisation and
  collision detection; identifier resolution order.
- **Postgres** (CI service exists, `ARP_TEST_POSTGRES_DSN`): import is idempotent and replays
  oldest first; two concurrent writers leave one current fact; document → citation → fact round
  trip; as-of query returns the historical value; `internal_only` facts refused by publish.
- **Guard:** test fails on `run_store.*_path(` outside `RunStore`.

## 10. Out of scope

- ESG provider API client (phase 1b; needs the provider choice).
- Engagement and voting (phase 2), decision frameworks and index (phase 3), portfolio files,
  taxonomy and reporting (phase 4).
- Linking provider fields to extracted fields (a hand-curated `field_links` table if ever needed).
- Merging `published_facts` into `company_facts`.
- Company-level embeddings / similarity search.
- Async database engine.
- Company comparison, charts, saved views.

Estimate: 2–3 weeks.
