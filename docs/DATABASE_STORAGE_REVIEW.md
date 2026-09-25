# Review: database & storage approach

A review of how this system persists state, as of `main`
(`e3b6df0`). Scope: `backend/arp/storage/` in full, plus every call site
that reads or writes through it (`api/deps.py`, `cli/db.py`,
`portfolio/`, `orchestration/`, `ingestion/`, `retrieval/`).

The headline: **the file-based default path is well built and the
reasoning behind it holds up. The opt-in Postgres path is where the
problems are.** Three of its four read-model projections cannot insert a
single row; the holdings backend silently answers a different question
than the file store it claims to be a drop-in for; and the SQL join the
whole relational backend was justified by has no callers. Separately,
the file-based `PortfolioStore` and `TaxonomyStore` are missing the
concurrency protections their sibling stores (`RunStore`,
`EngagementStore`) already have, and lose writes under concurrent API
traffic.

Every finding below was verified by running it against a live Postgres,
not by reading alone — see [How this was verified](#how-this-was-verified)
for the setup, and [the summary table](#3-findings-summary) for all
fifteen at a glance.

> **Update — all fifteen findings are fixed.** Each finding below now ends
> with a **Fixed** note naming what changed and the test that pins it; the
> summary table carries the same. Two things came out of the
> implementation that the review itself had not found:
>
> - **F16 (high), new:** the engagement projection could never store a
>   commitment. `EngagementCommitmentModel` has a plain `ForeignKey` column
>   but no ORM `relationship()`, and SQLAlchemy derives flush ordering from
>   relationships — with none declared it flushed `engagement_commitments`
>   before `engagement_issues`, so every save of an issue carrying a
>   commitment raised `ForeignKeyViolation` into the best-effort hook that
>   swallows it. Found by the integration test written for F2, which is
>   the coverage gap §5 named. Fixed by inserting issues and flushing
>   before adding commitments.
> - **F11 was fixed differently than proposed.** Making
>   `build_hybrid_content_store` raise would have been worse than the
>   silence: it is called per field per company inside the retrieval
>   graph, so it would fail runs mid-flight over a configuration typo, and
>   the original fallback's rationale (hybrid retrieval is a cache; the
>   answer is the same either way) is sound. The misconfiguration is now
>   rejected when `Settings` is constructed — at startup, in the API and
>   the CLI alike — and the factory keeps its fallback with a warning.
>
> The default file-based path gained 10 concurrency tests, and the Postgres
> path gained 34 integration tests across parity, projections and schema
> evolution; the suite is 1013 passing with a scratch database configured,
> 954 without one.

---

## 1. The approach, as designed

Four tiers, each with an explicit rationale in
[`docs/METHODOLOGY.md`](METHODOLOGY.md) and in the module docstrings:

| Tier | Holds | Written by | Authoritative? |
| --- | --- | --- | --- |
| **JSON / JSONL files** | run manifests, results, review queue + decisions, engagement records and audit trail, taxonomies, portfolios/holdings, observations, alerts, governance events, reports | `RunStore`, `EngagementStore`, `TaxonomyStore`, `PortfolioStore`, `ReportingStore`, `TopicStateStore` | **yes** |
| **SQLite** (`content.db`) | parsed document text, file-identity fast path, doc registry, chunk embeddings | `DocumentContentStore` + its three collaborators | yes, but **derived** — deleting it costs re-parsing only |
| **Postgres / pgvector** (opt-in) | holdings dual-write; embeddings cache; four read-model projections | `PostgresPortfolioStore`, `PgVectorEmbeddingsStore`, `postgres_*_projection.py` | no — mirrors of the above |
| **OpenSearch / S3** (opt-in) | search index; immutable source bytes | `search_indexer`, `document_blob_store` | no |

### What is genuinely good here

This is not a codebase that reached for a database because databases are
what serious systems have. The decisions are argued, and the arguments
are mostly right:

- **Append-only JSONL for audit state is the correct call.** A review
  decision log, a run's results, an engagement's event trail — these are
  read whole, never updated in place, and need to be diffable and
  inspectable years later. A table with `UPDATE`s would be strictly worse
  for this, and the docstrings say so.
- **`safe_path.safe_id()` is applied consistently.** Every
  client-supplied id that becomes a path segment (`run_id`, `company_id`,
  `portfolio_id`, `as_of_date`, `scope_id`, …) is validated through one
  choke point with a whitelist regex. Path traversal via the API is
  closed off, and the two places where an id can't pass `safe_id` (a
  `"{company_id}:{field_id}"` governance key, a `"portfolio:<id>"` alert
  scope) are handled explicitly rather than by loosening the rule.
- **`RunStore.save_manifest` and `EngagementStore._save` get durability
  right** — `mkstemp` + write + `os.replace`, with the temp file cleaned
  up on `BaseException`. A reader sees the old file or the new one, never
  a half-written one.
- **`KeyedLock` is correctly motivated and correctly built.** The
  docstring's reasoning — sync FastAPI handlers run on worker threads and
  genuinely race the event loop's own batch progress writes — is accurate,
  and `RLock` (not `Lock`) is the right choice for mutators that nest.
- **The SQLite store's "no lock here, deliberately" argument is sound.**
  Every write is an idempotent content-addressed insert; a lost race
  costs one re-parse, not a lost update. Per-operation connections closed
  in `finally` sidestep `check_same_thread` honestly rather than by
  passing `check_same_thread=False` and hoping. WAL + `busy_timeout` +
  the NFS caveat are all noted.
- **Optionality is real.** `postgres.py` imports SQLAlchemy lazily and
  raises a genuinely helpful error (`PostgresExtraNotInstalled`) rather than an `ImportError`; `get_engine` is
  `lru_cache`d per DSN, which is the documented SQLAlchemy pattern. A
  deployment that never sets `ARP_POSTGRES_DSN` never pays for any of it.

So the critique below is not "this should have been Postgres from the
start." It's that the Postgres path that *does* exist was never exercised
end to end, and the file path has one store that didn't get the
treatment the others did.

---

## 2. Findings

Severity is about user-visible consequence: **high** = silently wrong
numbers or a broken feature, **medium** = breaks under normal
concurrent use or blocks a documented workflow, **low** = correctness of
reporting, dead code, or ergonomics.

### F1 (high) — `ARP_PORTFOLIO_BACKEND=postgres` silently changes holdings semantics, producing wrong aggregates

`PortfolioStore.load_holdings_as_of` is documented and unit-tested as
*"each portfolio's most recent snapshot on or before `as_of_date`"* —
precisely because *"portfolios can be pulled/refreshed on independent
schedules"* (`portfolio_store.py:172-182`, `tests/test_portfolio_store.py:24`).

`PostgresPortfolioStore.load_holdings_as_of` does an **exact date match**
(`postgres_portfolio_store.py:313`, `.where(HoldingModel.as_of_date ==
as_of_date)`). There is no `<=` and no per-portfolio latest-date
resolution. `aggregate_market_value_eur` — the join the whole backend
exists for — has the same exact-match filter.

Observed, same data written through both stores (`p1` pulled monthly,
`p2` only in January):

```
file      as_of=2026-02-28  holdings=2  total_eur=610.0
postgres  as_of=2026-02-28  holdings=1  total_eur=110.0
as_of='2026-02-15' (between snapshots):   file=600.0   postgres=0
```

This is not an edge case. `analytics.py:47` (every saved analytic and
pivot), `analytics.py:74` (trend mode, one query per date in range),
`api/routers/climate.py:46,59,71`, `cli/climate.py:26,45` and
`monitoring/evaluator.py:162,207` all call `load_holdings_as_of`, and the
default path resolves `as_of` to `all_snapshot_dates()[-1]` — the union
across portfolios. So **the default query silently drops every portfolio
that wasn't pulled on that exact date**, and an alert rule or analytic
with an explicit `as_of` that isn't a snapshot date returns zero
holdings. Portfolio exposure totals, concentration breaches and climate
coverage percentages are all wrong, with no error and no warning.

*Fix:* implement the same semantics in SQL — a window function or a
lateral `max(as_of_date) <= :as_of` per `portfolio_id` — and add a parity
test that runs the same assertions against both stores (see F8).

**Fixed.** `_latest_snapshot_per_portfolio` (a grouped subquery joined back
to `holdings`) now resolves the date per portfolio, shared by
`load_holdings_as_of` and `aggregate_market_value_eur`/
`aggregate_holdings_by`. `load_snapshot` was untangled from it and stays
exact-date. Pinned by `tests/test_portfolio_store_parity.py`, which fails
against the old query.

### F2 (high) — three of the four Postgres projections cannot insert a single row

`CompanyRecordModel.company_id`, `CompanyFactModel.company_id` and
`EngagementIssueModel.company_id` are all
`ForeignKey("companies.company_id")` (`postgres_models.py:200,241,279`).
Nothing populates `companies` except `PostgresPortfolioStore.save_company`,
whose only non-test caller is the demo seeder
(`portfolio/mock_data.py:219`). Real run companies come from a
user-supplied universe file (`universe.py::load_company_universe`) and
are never written to that table.

Observed:

```
save_manifest(COMPLETED), company_records_projection_enabled:  rows = 0
explicit sync_run(...):        IntegrityError: ForeignKeyViolation on company_records_company_id_fkey
arp db reindex company-facts:  IntegrityError: ForeignKeyViolation on company_facts
arp db reindex engagement:     IntegrityError: ForeignKeyViolation on engagement_issues
(after manually inserting the company into `companies`: 1 row inserted, as designed)
```

The live hooks are `try/except Exception: logger.warning(...)` by design
("best-effort, never blocks the real write"). That contract is right, but
combined with the FK it means **enabling these projections does nothing
at all, silently** — the operator gets an empty table and one warning per
run buried in the log. The CLI backfills at least fail loudly.

*Fix:* pick one. Either drop the FK on the projection tables (they are
read models of a store that itself enforces no referential integrity —
the same argument `SecurityResolutionModel`'s docstring already makes for
*not* having an FK), or upsert the company row as part of the projection
sync. Dropping the FK is the smaller and more consistent change.

**Fixed.** The three FKs are gone, and the rule is stated once in
`postgres_models.py`'s module docstring (FKs stay only where both sides are
written by the same code path). Existing databases are migrated by schema
step `0001_drop_projection_company_fks` (F6).
`tests/test_postgres_projections_integration.py` inserts for a company that
exists only in a universe file — 13 tests where there were none.

### F3 (high) — `PortfolioStore`'s registry files lose writes and can be read mid-truncation

`PortfolioStore` is the one file store with **neither** a lock **nor**
atomic writes. `save_portfolio`, `save_security`, `save_company`,
`save_resolution`, `save_analytic` and `save_rule` are all
read-whole-file → mutate dict → `path.write_text(...)`
(`portfolio_store.py:44-47`), and `get_portfolio_store()` is an
`lru_cache`d singleton shared by every request thread.

Observed, 50 concurrent `save_security` calls:

```
securities.json holds: 19 of 50   (a second run of the same script: 15 of 50)
plus many threads dying on: json.decoder.JSONDecodeError: Expecting value: line 1 column 1
```

Two distinct defects in one: **lost updates** (last writer wins over the
whole file), and **readers observing a truncated file** — `write_text`
truncates before writing, so a concurrent reader gets zero or partial
bytes and `json.loads` raises. In the API that surfaces as a 500 on an
unrelated read.

This matters wherever a request writes these files — `governance.py:96-99`
(an override writes a resolution *and* a security), the monitoring
evaluator's rule saves, `save_analytic` from the analytics builder — and
it also makes ingesting a large security master O(n²) in file rewrites.

*Fix:* reuse what's already in this codebase — give `PortfolioStore` a
`KeyedLock` (keyed per registry file) and route every write through the
same `mkstemp`/`os.replace` helper `ReportingStore._atomic_write` already
generalizes. That is a ~30-line change, no new dependency, no schema
change.

**Fixed.** Every registry write goes through `_put_json_entry` (per-file
`KeyedLock` + atomic write), snapshots are written atomically too, and the
write-then-rename duplicated across `RunStore`/`EngagementStore`/
`ReportingStore` now lives in one place (`arp/storage/atomic_io.py`).
`tests/test_file_store_concurrency.py` asserts all 50 concurrent writes
survive and that concurrent readers never observe a truncated file.

### F4 (medium) — `PostgresPortfolioStore` is not the drop-in it claims to be

Its docstring promises *"a genuine drop-in … every caller of
`get_portfolio_store()` keeps working unmodified."* It is missing six
public methods the file store has, one of which is called on a live
request path:

```
missing: list_observation_keys, registry_path, securities_path,
         companies_path, resolutions_path, snapshot_path
```

`datapoint_mapping.list_conflicting_observations` calls
`store.list_observation_keys()` (`datapoint_mapping.py:65`), reached from
`GET /api/portfolio/climate-conflicts` (`api/routers/portfolio.py:75`)
and from the governance queue (`portfolio/governance.py:51`). Observed:

```
AttributeError: 'PostgresPortfolioStore' object has no attribute 'list_observation_keys'
```

So under `ARP_PORTFOLIO_BACKEND=postgres`, the climate-conflict
governance surface 500s. The irony is that observations *are* delegated
to the wrapped file store — only this one listing method was forgotten.

*Fix:* delegate the missing six to `self._files` (they're all
file-backed concerns anyway), and add a test asserting the two stores
expose the same public surface — that single test would have caught this
and would catch the next one.

**Fixed, with one correction to the recommendation.** Only
`list_observation_keys` is delegated: the five `*_path()` accessors name a
file that does not exist under this backend, so returning the wrapped
store's path would hand a caller an empty file and call it the data. They
are declared in `FILE_ONLY_METHODS` in the parity suite, which asserts every
*other* public method exists on both — so adding a method to
`PortfolioStore` now fails a test unless it is implemented or deliberately
classified.

### F5 (medium) — `TaxonomyStore` can overwrite "immutable" versions

`new_version` reads the current version, then writes `version + 1`
(`taxonomy_store.py:51-72`) with no lock and a plain `write_text`. Two
concurrent edits both read v1 and both write `v2.json`.

Observed, 8 concurrent `new_version` calls on one taxonomy:

```
version files on disk: ['v1.json', 'v2.json']     latest pointer: 2
```

Seven edits were lost, and — worse for a store whose whole premise is
*"editing a taxonomy creates a new version rather than overwriting
history"* — they were lost by **overwriting an already-written version
file**. `ratify()` has the same shape: it rewrites a version file
non-atomically, so a crash mid-write leaves an unparseable ratified
version (`list_versions` then silently skips it).

*Fix:* `KeyedLock` on `taxonomy_id`, atomic writes, and open version
files with `"x"` (exclusive create) so a version collision fails loudly
instead of silently overwriting.

**Fixed.** All three, plus a bounded re-read-and-bump loop so the
cross-process case (a CLI edit racing an API request) produces v3 rather
than an error, and `TaxonomyVersionConflict` if it cannot claim a version at
all. `ratify` is the one write that legitimately replaces a version file,
and is atomic. Eight concurrent edits now produce v2–v9 with every note
intact.

### F6 (medium) — no migration path for Postgres

`ensure_schema` is `CREATE EXTENSION` + `Base.metadata.create_all`
(`postgres.py:52-60`). `create_all` never alters an existing table, there is
no Alembic (or any migrations directory) in the repo, and `arp db
init-postgres` is documented as "run once per fresh database". So adding
or widening a column on any of the ten models is a manual `ALTER TABLE`
on every deployment, with no version tracking and no way to tell whether
a given database is current.

The SQLite side shows the team already hit this and solved it ad hoc —
`document_registry.ensure_storage_uri_column` is a hand-written idempotent
`ALTER TABLE` for exactly this reason. That approach doesn't scale to ten
tables.

*Fix:* while the Postgres path is opt-in and additive, either add Alembic
(the conventional answer, ~1 hour of setup for the initial revision) or
state the constraint in the docs and in `init-postgres --help`:
"schema changes require dropping and recreating these tables." Right now
neither is true and an operator finds out by getting a
`UndefinedColumn` error.

**Fixed, without Alembic.** `arp/storage/postgres_schema.py` does three
things idempotently: `create_all` for new tables, model-driven
`ALTER TABLE ADD COLUMN` for columns an older database lacks (generalizing
the hand-written `ensure_storage_uri_column`), and run-once `SCHEMA_STEPS`
for what reconciliation cannot infer — recorded in a `schema_migrations`
table, so "what has this database had applied?" is answerable. Destructive
divergence (a column the models dropped, a nullability mismatch) is
*reported*, never acted on. New `arp db check-postgres` prints that report
and exits non-zero when a database is behind, so it can gate a deploy.
Alembic was rejected as disproportionate here: a dependency plus a
hand-written baseline revision duplicating the models, for a schema with one
pending change. Six tests in `tests/test_postgres_schema.py` cover the
behind-database cases.

### F7 (medium) — the join the relational backend exists for has no callers

`aggregate_market_value_eur` is described in `METHODOLOGY.md` and in its
own docstring as *"the payoff … the concrete case the architecture-review
gap analysis names as where a relational store actually earns its cost."*
It has **zero call sites** outside its own tests. Every aggregation the
app actually serves still goes through `portfolio/analytics.py`, which
loads JSONL snapshots and groups in Python — regardless of
`portfolio_backend`.

Combined with F1, the current net effect of opting into the Postgres
portfolio backend is: no faster aggregation, plus silently wrong
holdings resolution. That's a negative-value switch today.

*Fix:* either wire `analytics.py`'s `market_value_sum` path to use the
SQL aggregation when the store offers it (`hasattr` / a small protocol
check, once F1 is fixed), or mark the method explicitly as a
not-yet-wired capability so the docs stop claiming a payoff that isn't
collected.

**Fixed — wired.** New `aggregate_holdings_by` returns everything
`aggregation.aggregate` needs for `market_value_sum` (grouped sums, holding
counts, grand total) across all seven of `aggregation.DIMENSIONS`, with
security filters, and `analytics._try_aggregate_in_sql` routes through it
behind a `hasattr` capability check — so nothing changes with the default
file backend or without the extra installed. 15 tests in
`tests/test_analytics_sql_parity.py` hold the two paths to identical rows,
counts, totals, ordering and `(unresolved)` bucketing, which is how the one
real divergence found during this work (NULL groups sort last in Postgres,
first in Python) surfaced. `weighted_avg_datapoint` and `count` stay in
Python deliberately: the former needs the file-based observation cascade.

### F8 (medium) — schema↔ORM mapping is hand-written field by field, with no parity test

Every conversion between a Pydantic schema and its ORM model is written
out by hand in both directions (`postgres_portfolio_store.py:129-260`
for the writes, `:382-402` for the reads). Each is currently *correct* —
verified field by field against `Portfolio`/`SecurityRef`/`CompanyRef`/
`SecurityResolution`/`Holding` — but it is silently lossy by construction: add a field to `Portfolio`,
`SecurityRef`, `CompanyRef` or `Holding` and the file store persists it
while the Postgres store drops it, with nothing failing.

The test suite can't catch this: `tests/test_postgres_portfolio_store.py`
asserts against the Postgres store alone (and is skipped unless
`ARP_TEST_POSTGRES_DSN` is set), and no test runs the same assertions
against both backends.

*Fix:* one parametrized fixture yielding both stores, and move the
existing round-trip tests under it. That single change pins F1, F4 and
F8 at once, which is why it heads the recommended order below.

**Fixed.** `tests/test_portfolio_store_parity.py`: 19 assertions over a
`store` fixture parametrized across both backends (the Postgres half skips
without `ARP_TEST_POSTGRES_DSN`, so the file half still runs in the default
configuration), covering as-of resolution, every round-trip including
`Holding`'s optional fields, upsert semantics, and the public-surface
comparison. A field added to a schema and forgotten in the ORM mapping now
fails a test.

### F9 (low) — `sync_run` reports a row count it cannot know

`sync_run`'s docstring promises *"Returns the number of rows actually
inserted (0 on a repeat sync)"*, and `arp db reindex company-records`
prints it. `result.rowcount` after an `insert(...).values([...])
.on_conflict_do_nothing()` through SQLAlchemy's insertmanyvalues path is
`-1`. Observed:

```
first sync (2 genuinely new rows):  -1       (both rows did land)
re-sync (all duplicates):           -1
```

So the CLI prints `rows_inserted=-1` in both cases, and an operator can't
distinguish "backfilled" from "no-op". *Fix:* add `.returning(...)` and
count the returned rows, or drop the claim.

**Fixed.** `.returning(CompanyRecordModel.id)`, counted. The CLI prints
real numbers now, and both the insert count and the no-op re-sync count are
asserted.

### F10 (low) — dead schema and unimplemented incremental reindex

- `IndexCheckpointModel` ("per-projector high-water mark so `arp db
  reindex …` without `--full` only rescans what's new") is never
  imported or written anywhere.
- `sync_all(..., since=)` / `materialize_all(..., since=)` exist and are
  never passed a value; no reindex command takes `--since` or `--full`.
- `CompanyFactModel.confidence` and `.citations` are declared and
  documented but never populated by `materialize_run`.

These are all "documented in a docstring, absent in code" — the most
expensive kind of dead code, because the docstrings read as description.

**Fixed — implemented, all three.** `arp/storage/postgres_checkpoints.py`
reads and writes `IndexCheckpointModel`; `arp db reindex company-records` /
`company-facts` are incremental by default with a new `--full` flag; and
`CompanyFactModel.confidence`/`.citations` are populated by
`fact_confidence`/`fact_citations`, which handle each verified row shape (a
match's own `confidence`, a record's `overall_confidence`, an extraction's
per-field citations concatenated in field order).

### F11 (low) — misconfiguration is silent in one factory and loud in the other

`build_portfolio_store` raises a clear `RuntimeError` when
`portfolio_backend == "postgres"` without a DSN. `build_hybrid_content_store`
in the same situation silently falls back to SQLite
(`content_store_factory.py:30-32`). Both `portfolio_backend` and
`embeddings_backend` are plain `str`, not `Literal["file", "postgres"]`,
so `ARP_PORTFOLIO_BACKEND=postgress` is a silent no-op too. *Fix:*
`Literal` types on both settings, and make the embeddings factory raise
like its sibling.

**Fixed, differently.** The `Literal` types are in — a typo now fails at
startup naming the allowed values. Making the factory raise would have been
worse than the silence, though: it runs per field per company inside the
retrieval graph, so it would fail runs mid-flight, and the original
fallback's reasoning (hybrid retrieval is a cache; the answer is the same
either way) is sound. Instead a `Settings` model validator refuses to
construct any backend selection missing its connection —
`portfolio_backend`, `embeddings_backend` and `retrieval_backend` alike, at
startup, in the API and the CLI both — and the factory keeps its fallback
with a warning for a `Settings` built around validation.

### F12 (low) — projection hooks are synchronous on the caller's thread

`RunStore.save_manifest` fires the record + fact projections inline on
every terminal-status save; `EngagementStore._save` fires the engagement
projection inline on **every** mutation (every status change, every
correspondence entry). `materialize_run` additionally issues one `SELECT`
per fact candidate (`postgres_company_facts_projection.py:138-145`) — N+1 for
a run with hundreds of companies × matches.

The file write is already durable before the hook runs, so nothing is
lost; but a slow or unreachable Postgres stalls run completion and every
engagement edit for the connect timeout. `pool_pre_ping=True` helps with
stale connections, not with a hung server. *Fix:* at minimum set a
`connect_timeout` in the DSN/`connect_args`; better, batch the fact
lookup into one query keyed by `(company_id, fact_key)`.

**Fixed, both.** `get_engine` sets a 10s `connect_timeout` (unless the DSN
names one, in which case the caller was explicit), and `materialize_run`
issues one `SELECT ... WHERE fact_key IN (...)` for the whole run instead of
one per candidate.

### F13 (low) — inconsistent tolerance for a corrupt JSONL line

`RunStore.read_jsonl` skips undecodable lines; `PortfolioStore._read_jsonl`
does not (`portfolio_store.py:49-58`), so one truncated line in
`news/items.jsonl` or an observations file breaks the whole read. Given
appends are unlocked (F3), a partially-written line is possible. Use the
tolerant reader in both places, or neither.

**Fixed.** Both go through `arp/storage/jsonl_io.py`, which skips an
undecodable line and documents why that is right for an append-only log: a
torn tail is not a record, and discarding the intact records in front of it
is the worse failure. (Those appends are no longer unlocked either — see
F3/F14.)

### F14 (informational) — the single-writer assumption should be written down

`KeyedLock` is a per-process registry of `threading.RLock`s. Today that's
sufficient: the API runs single-worker (`backend/Dockerfile:82`,
`uvicorn arp.api.main:app` with no `--workers`). But **the CLI and the
schedulers are separate processes writing the same files**, and
`uvicorn --workers 2` would quietly void every lock in the system. The
locking docstrings explain the thread race precisely and say nothing
about the process boundary. Either note the constraint next to
`KeyedLock`, or move to an OS-level advisory lock (`fcntl.flock` on a
sidecar lockfile) — which would also cover the CLI-vs-API case that
exists now.

**Fixed — the lock, not just the note.** `KeyedLock` takes an optional
`lock_path`, and each acquisition then also takes an advisory `fcntl.flock`
on a sidecar file, reentrantly (an inner `with` no longer releases what an
outer one still holds). All four stores pass one, so the CLI, the schedulers
and any number of uvicorn workers serialize against each other on the same
record. Degrades to thread-only where `fcntl` is absent. A subprocess test
asserts two processes' hold windows never overlap — and that the lock files
stay out of every listing glob.

### F15 (informational) — the document projection invents its own timestamps

`DocumentRegistryModel.first_seen_at` / `last_seen_at` are set to
`now_iso()` at sync time (`postgres_document_projection.py:44-45,59`), not
copied from the authoritative SQLite `documents` row — which has both
columns. `StoredDocumentRef` doesn't expose them, so the projection
can't. A "mirror" whose timestamps mean something different from the
source's is a trap for whoever queries it first. Add the two fields to
`StoredDocumentRef` and carry them through.

**Fixed.** `StoredDocumentRef` carries both (optional, so a hand-built ref
still works), every registry `SELECT` reads them, and the projection copies
them instead of stamping its own time — falling back to the sync time only
when they are genuinely unknown.

---

## 3. Findings summary

All fifteen are fixed; "Fixed by" names the change, and each finding above
carries the detail.

| # | Sev | Finding | Fixed by |
| --- | --- | --- | --- |
| F1 | high | Postgres holdings use exact-date match, not "latest on or before" → wrong aggregates | `_latest_snapshot_per_portfolio` + parity suite |
| F2 | high | `company_records` / `company_facts` / `engagement_issues` FK to an unpopulated `companies` → projections silently insert nothing | FKs dropped + schema step `0001` |
| F3 | high | `PortfolioStore` registry writes: no lock, non-atomic → lost updates + truncated reads | `_put_json_entry` + `atomic_io.py` |
| F4 | medium | `PostgresPortfolioStore` missing 6 methods; `/climate-conflicts` 500s | `list_observation_keys` + surface test |
| F5 | medium | `TaxonomyStore.new_version` races overwrite "immutable" versions | lock + O_EXCL + bounded re-bump |
| F6 | medium | No Postgres migrations — `create_all` only, no Alembic | `postgres_schema.py` + `arp db check-postgres` |
| F7 | medium | `aggregate_market_value_eur` (the stated payoff) has no callers | `aggregate_holdings_by` wired into `analytics.execute` |
| F8 | medium | Hand-written schema↔ORM mapping, no cross-backend parity test | `tests/test_portfolio_store_parity.py` |
| F9 | low | `sync_run` returns `-1`; CLI prints `rows_inserted=-1` | `.returning(...)`, counted |
| F10 | low | `IndexCheckpointModel`, `since=`, `confidence`/`citations` all dead | `postgres_checkpoints.py`, `--full`, `fact_confidence` |
| F11 | low | Silent fallback + non-`Literal` backend settings | `Literal` types + `Settings` validator (not the factory) |
| F12 | low | Inline projection hooks; N+1 in the facts projection | `connect_timeout` + one batched `SELECT` |
| F13 | low | Inconsistent corrupt-line tolerance in JSONL readers | shared `jsonl_io.py` |
| F14 | info | In-process locks only; CLI/API and multi-worker unprotected | `fcntl.flock` sidecar in `KeyedLock` |
| F15 | info | Document projection timestamps ≠ source timestamps | timestamps carried on `StoredDocumentRef` |
| F16 | high | Engagement projection flushed commitments before their issue → no commitment could ever be stored | explicit `flush()` between the two inserts |

## 4. Order of work (as carried out)

1. **F3 + F5** — file-store concurrency. Smallest diff, affects the
   default path everyone runs, and the tools (`KeyedLock`,
   `_atomic_write`) already existed in the repo.
2. **F8's parity fixture, then F1 and F4** — the cross-backend test was
   written first and confirmed failing against the old query; it pins all
   three and every future divergence.
3. **F2** — the FKs dropped on the projection tables (consistent with
   `SecurityResolutionModel`'s own documented reasoning), plus the
   integration tests that proved the projections now store rows — and
   that surfaced **F16**.
4. **F6** — the migration story, before anyone runs this Postgres path on
   data they care about.
5. **F7, F9–F13, F15** — cleanup, each small and independent.

Two items were resolved differently from the recommendation above, both
noted in full at their finding: **F4** (five of the six methods are
deliberately *not* delegated) and **F11** (validated at startup rather than
raised from a hot inner path).

## 5. Test-coverage gaps (all three closed)

- **Every Postgres write path except the portfolio store and the
  embeddings cache was untested.** The record/fact/engagement/document
  projections had unit tests for their *pure mapping functions* only
  (`test_postgres_company_records_projection.py` said so explicitly); no
  test ever inserted a row. That is exactly why F2 shipped — and why F16
  shipped alongside it.
  → `tests/test_postgres_projections_integration.py` (13 tests) asserts on
  rows actually in Postgres, including the disabled-projection case.
- **No cross-backend parity test** — the file and Postgres stores were
  asserted against separately, so a semantic divergence like F1 was
  invisible to the suite.
  → `tests/test_portfolio_store_parity.py` (19) and
  `tests/test_analytics_sql_parity.py` (15).
- **No concurrency test for `PortfolioStore` or `TaxonomyStore`**, though
  `tests/test_run_store_locking.py` showed the pattern for exactly this
  and passed for `RunStore`.
  → `tests/test_file_store_concurrency.py` (10), including a subprocess
  test for the cross-process lock.

Also new: `tests/test_postgres_schema.py` (6) for schema evolution against
a database that is behind. The suite runs 954 passing in the default
network- and database-free configuration, 1013 with a scratch Postgres
configured. (Two tests fail in either mode in this container for missing
optional extras — `hdbscan` and `docling` — unrelated to storage.)

## How this was verified

A real Postgres 16 + pgvector instance, the repo's own `ensure_schema`,
and the repo's own stores driven directly:

```
initdb + postgres -p 5439; createdb arp_test; CREATE EXTENSION vector;
pip install "sqlalchemy>=2.0" "psycopg[binary]" pgvector
ARP_TEST_POSTGRES_DSN=postgresql+psycopg://postgres@127.0.0.1:5439/arp_test \
  pytest tests/test_postgres_portfolio_store.py tests/test_portfolio_store.py
  -> 21 passed
```

The existing opt-in integration suite passes against that instance, so
the environment is sound and the findings above are real behaviour, not
setup artifacts. F1, F2, F4, F5 and F9 were then each reproduced
directly against the same instance; F3 and F5 were reproduced with
concurrent threads against the file stores. The numbers quoted in each
finding are that run's output (thread-interleaving counts in F3 vary run
to run; both observed runs lost more than half the writes).
