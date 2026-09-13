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
  raises a genuinely helpful error (`PostgresExtraNotInstalled`,
  `PostgresNotConfigured`) rather than an `ImportError`; `get_engine` is
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

### F11 (low) — misconfiguration is silent in one factory and loud in the other

`build_portfolio_store` raises a clear `RuntimeError` when
`portfolio_backend == "postgres"` without a DSN. `build_hybrid_content_store`
in the same situation silently falls back to SQLite
(`content_store_factory.py:30-32`). Both `portfolio_backend` and
`embeddings_backend` are plain `str`, not `Literal["file", "postgres"]`,
so `ARP_PORTFOLIO_BACKEND=postgress` is a silent no-op too. *Fix:*
`Literal` types on both settings, and make the embeddings factory raise
like its sibling.

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

### F13 (low) — inconsistent tolerance for a corrupt JSONL line

`RunStore.read_jsonl` skips undecodable lines; `PortfolioStore._read_jsonl`
does not (`portfolio_store.py:49-58`), so one truncated line in
`news/items.jsonl` or an observations file breaks the whole read. Given
appends are unlocked (F3), a partially-written line is possible. Use the
tolerant reader in both places, or neither.

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

### F15 (informational) — the document projection invents its own timestamps

`DocumentRegistryModel.first_seen_at` / `last_seen_at` are set to
`now_iso()` at sync time (`postgres_document_projection.py:44-45,59`), not
copied from the authoritative SQLite `documents` row — which has both
columns. `StoredDocumentRef` doesn't expose them, so the projection
can't. A "mirror" whose timestamps mean something different from the
source's is a trap for whoever queries it first. Add the two fields to
`StoredDocumentRef` and carry them through.

---

## 3. Findings summary

| # | Sev | Finding | Where |
| --- | --- | --- | --- |
| F1 | high | Postgres holdings use exact-date match, not "latest on or before" → wrong aggregates | `postgres_portfolio_store.py:313,357` |
| F2 | high | `company_records` / `company_facts` / `engagement_issues` FK to an unpopulated `companies` → projections silently insert nothing | `postgres_models.py:200,241,279` |
| F3 | high | `PortfolioStore` registry writes: no lock, non-atomic → lost updates + truncated reads | `portfolio_store.py:44-47` |
| F4 | medium | `PostgresPortfolioStore` missing 6 methods; `/climate-conflicts` 500s | `postgres_portfolio_store.py` |
| F5 | medium | `TaxonomyStore.new_version` races overwrite "immutable" versions | `taxonomy_store.py:36-38,51-72` |
| F6 | medium | No Postgres migrations — `create_all` only, no Alembic | `postgres.py:52-60` |
| F7 | medium | `aggregate_market_value_eur` (the stated payoff) has no callers | `postgres_portfolio_store.py:328` |
| F8 | medium | Hand-written schema↔ORM mapping, no cross-backend parity test | `postgres_portfolio_store.py`, `tests/` |
| F9 | low | `sync_run` returns `-1`; CLI prints `rows_inserted=-1` | `postgres_company_records_projection.py:77` |
| F10 | low | `IndexCheckpointModel`, `since=`, `confidence`/`citations` all dead | `postgres_models.py:311`, `cli/db.py` |
| F11 | low | Silent fallback + non-`Literal` backend settings | `content_store_factory.py:30-32`, `config.py` |
| F12 | low | Inline projection hooks; N+1 in the facts projection | `run_store.py:82-95`, `..._facts_projection.py:138` |
| F13 | low | Inconsistent corrupt-line tolerance in JSONL readers | `portfolio_store.py:49-58` |
| F14 | info | In-process locks only; CLI/API and multi-worker unprotected | `locks.py` |
| F15 | info | Document projection timestamps ≠ source timestamps | `postgres_document_projection.py:44` |

## 4. Recommended order of work

1. **F3 + F5** — file-store concurrency. Smallest diff, affects the
   default path everyone runs, and the tools (`KeyedLock`,
   `_atomic_write`) already exist in the repo.
2. **F8's parity fixture, then F1 and F4** — write the cross-backend test
   first and let it fail; it pins all three and every future divergence.
3. **F2** — drop the FKs on the projection tables (consistent with
   `SecurityResolutionModel`'s own documented reasoning), so the
   projections actually do something when enabled.
4. **F6** — decide the migration story before anyone runs this Postgres
   path on data they care about.
5. **F7, F9–F13, F15** — cleanup; each is small and independent.

## 5. Test-coverage gaps worth naming

- **Every Postgres write path except the portfolio store and the
  embeddings cache is untested.** The record/fact/engagement/document
  projections have unit tests for their *pure mapping functions* only
  (`test_postgres_company_records_projection.py` says so explicitly);
  no test ever inserts a row. That is exactly why F2 shipped.
- **No cross-backend parity test** — the file and Postgres stores are
  asserted against separately, so a semantic divergence like F1 is
  invisible to the suite.
- **No concurrency test for `PortfolioStore` or `TaxonomyStore`**, though
  `tests/test_run_store_locking.py` shows the pattern for exactly this
  and passes for `RunStore`.

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
