# Theme Radar signal store: keep every fetched item, retry fetches, daily light scan, radar health

Status: Draft, for owner approval
Slug: `theme-radar-signal-store`
Risk: `risk:normal` for slices a, b and c (new Postgres tables, fetchers, a scheduler); `risk:low` for slice d (radar health)
Size: `M`, four slices (R&D Lab plan wave 4, items 22 and 27; Theme Radar spec S1)

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them. Two you may
want to change:

- The daily light scan is **off by default** (default 1), like the weekly scan.
- A full scan reads **at most 1,000 stored items**, newest first (default 12). Without a cap, a weekly full scan
  after 14 days of light scans would extract roughly 14,000 items, one model call each, instead of about 1,000 today.

## Why

The Emerging Themes scan (`backend/arp/emerging_themes/`, main `7e2e955`) fetches GDELT news, SEC EDGAR full-text
search hits and regulator RSS items, extracts tags, clusters them and then forgets the items: they live only in
the run's `mentions.jsonl`. So:

- there is no history to build rolling baselines from (Theme Radar spec S2, momentum flags, needs one);
- re-clustering means fetching again;
- a failed request is logged and dropped: no retry, nothing tells the owner a source went quiet;
- the SEC asks for at most 10 requests per second and a declared User-Agent; the EDGAR fetcher
  is not rate-limited, and the regulator RSS fetcher sends no User-Agent at all to `www.sec.gov`.

This spec adds a signal store in Postgres (the system of record, already required), retries and an SEC rate limit
in the three fetchers, a daily light scan that only fetches and stores, and a "Radar health" block per scan. Later
specs build on the names fixed here: S2 reads the store for baselines, S4 adds research, jobs and GDELT knowledge
graph sources to it, S6 (Source Workbench) queries it per source type.

## What the user can do afterwards that they cannot do today

- Switch on a daily light scan that collects news, filings and regulator items every day without any model call.
- Re-run a full scan on what is already stored, without fetching again (`"fetch": false`).
- See on the Emerging Themes page, under the automatic schedule, how healthy the last scan was: failed requests
  per source, how old the newest item from each source is, and what share of items ended up in no cluster.

## What exists today (main `7e2e955`)

- `ingestion/base.py`: `MentionSource` with `name` and `async fetch(since) -> list[RawMention]`.
- `ingestion/gdelt.py` (`GdeltSource`, name `gdelt`, 4 query terms, `httpx.AsyncClient(timeout=30)`),
  `ingestion/edgar_fts.py` (`EdgarFullTextSearchSource(user_agent, query_terms=None, forms=None)`, name
  `edgar_fts`, 5 terms, host `efts.sec.gov`), `ingestion/regulatory_rss.py` (`RegulatoryRssSource(feed_urls=None)`,
  name `regulatory_rss`, 5 feeds incl. `https://www.sec.gov/news/pressreleases.rss`, no User-Agent). Each request
  failure (`httpx.HTTPError`, bad JSON) is logged and skipped; nothing is retried or counted.
- `schemas/emerging_themes.py`: `MentionSourceType` = `edgar_fts | gdelt | regulatory_rss`; `RawMention`
  (`mention_id` random `mention_…`, `source_type`, `title`, `text`, `url`, `raw_entity_names`, `published_at`,
  `published_at_is_estimated`, `fetched_at`).
- `pipeline.py`: `execute_emerging_themes_run(run_id, companies, *, llm, sources, settings, run_store, topic_store,
  xbrl_source=None)` fetches from every source with `since = now - emerging_themes_lookback_days` (14), writes
  `mentions.jsonl`, extracts with `tag_mention`, clusters with `cluster_tags`, scores, writes candidates.
  `run_emerging_themes(...)` wraps create + execute.
- `scheduler.py`: `default_sources(settings)`; `EmergingThemesScheduler(IntervalScheduler)` with config file
  `<emerging_themes_state_dir>/schedule.json`, off by default, 168 h. `IntervalScheduler` fires its first run 5 s
  after the app starts once enabled.
- `api/routers/emerging_themes.py`: `POST /api/emerging-themes/runs` (`companies` or `universe_path`),
  candidates, promote/reject/disconfirm, `GET/PUT /api/emerging-themes/schedule`.
- `storage/postgres_models.py`: `ChunkEmbeddingModel` (`chunk_embeddings`: `chunk_id`, `embed_model`,
  `embedding vector`), written by `storage/postgres_embeddings.py`. `ensure_schema` (`arp db init-postgres`) creates
  missing tables and adds missing columns.
- `retrieval/embeddings.py`: `embed_texts(texts) -> np.ndarray` (384 dims), `EMBED_MODEL_NAME =
  "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"`.
- UI: `frontend/src/pages/EmergingThemesDetector.tsx`, section "Automatic schedule" (enable checkbox, interval,
  universe path, "Save schedule").

## Goals

- G1. Every item a scan fetches is stored once in Postgres, deduplicated by a content hash, with its embedding
  cached in `chunk_embeddings`.
- G2. A full scan reads its items from the store, so it can run without fetching.
- G3. Fetch requests retry with back-off on transient failures; requests to SEC hosts stay within 10 per second
  and carry the configured User-Agent.
- G4. A daily light scan fetches and stores items and records per-source counts, with no extraction, clustering or
  model call; it is off by default and switched on in the UI.
- G5. Every scan records radar health (failed requests per source, lag since the newest item per source, share of
  items in no cluster), served by an API and shown on the Emerging Themes page.
- G6. The names later specs build on are fixed: tables `signal_items` and `signal_scans`, `SignalSourceType`
  values `news | filings | regulators | research | jobs`, `SignalStore.read_items`.

## Non-goals

- Momentum, burst scores or baseline maths (S2). New sources: OpenAlex, research clusters, job boards, GDELT
  knowledge graph (S4). The Source Workbench or any per-source screen (S6). Renaming the page or any new screen (item 15).
- Caching extracted tags: a full scan still extracts every item it reads, as today.
- Backfilling earlier runs' `mentions.jsonl` into the store; pruning or retention of stored items.
- Embedding again items whose embedding failed; changing what clustering embeds (it still embeds tags).
- Honouring `Retry-After`; rate limits for hosts other than SEC; changing `EdgarDocumentSource` / XBRL fetching.
- Celery, Redis, docker compose or any infrastructure beyond Postgres.
- The observability plan (not approved); radar health appears only in the API and on the page.

## Anti-goals (must stay true)

- A1. The weekly schedule stays off by default with a 168 h interval.
- A2. `execute_emerging_themes_run` and `run_emerging_themes` called without `signal_store` behave as on main: the
  existing tests pass unedited.
- A3. The fetchers' parsing is unchanged: the same stub response gives the same `RawMention` fields as on main
  (except `mention_id` and `fetched_at`).
- A4. A light scan never makes a model call and never creates a run or a topic period.

## Design

### Names (fixed for later specs)

In `backend/arp/schemas/emerging_themes.py`:

```python
class SignalSourceType(StrEnum):
    NEWS = "news"; FILINGS = "filings"; REGULATORS = "regulators"; RESEARCH = "research"; JOBS = "jobs"

SIGNAL_SOURCE_TYPE = {  # MentionSourceType -> SignalSourceType; S4 adds research and jobs entries
    MentionSourceType.GDELT: SignalSourceType.NEWS,
    MentionSourceType.EDGAR_FTS: SignalSourceType.FILINGS,
    MentionSourceType.REGULATORY_RSS: SignalSourceType.REGULATORS,
}

class SignalItem(BaseModel):
    content_hash: str            # 64 lower-case hex chars
    source: MentionSourceType    # the RawMention.source_type it was fetched as
    source_type: SignalSourceType
    title: str
    text: str
    url: str
    raw_entity_names: list[str]
    published_at: str | None
    published_at_is_estimated: bool
    item_at: str                 # published_at if set, else first_seen_at
    first_seen_at: str
    last_seen_at: str

class SignalScan(BaseModel):
    scan_id: str                 # new_id("scan")
    kind: Literal["light", "full"]
    run_id: str | None           # the emerging_themes run for a full scan, None for a light scan
    started_at: str
    finished_at: str
    items_fetched: dict[str, int]       # per source name: items the source returned, before dedupe
    items_new: dict[str, int]           # per source name: items stored for the first time
    fetch_failures: dict[str, int] = {}          # slice d
    lag_hours: dict[str, float | None] = {}      # slice d
    unclustered_share: float | None = None       # slice d
```

Times are ISO 8601 UTC strings as `arp.schemas.common.now_iso()` writes them. Per-source dicts are keyed by each
scan source's `MentionSource.name` and hold every source the scan was given; for the three default sources the
name equals the `MentionSourceType` value they emit (`gdelt`, `edgar_fts`, `regulatory_rss`).

### Tables (`backend/arp/storage/postgres_models.py`, created by `ensure_schema`)

- `signal_items`: `content_hash` (primary key), `source`, `source_type`, `title`, `text`, `url`,
  `raw_entity_names` (JSONB list), `published_at` (timestamptz, null), `published_at_is_estimated` (bool),
  `item_at` (timestamptz, indexed), `first_seen_at` (timestamptz), `last_seen_at` (timestamptz).
- `signal_scans`: `scan_id` (primary key), `kind`, `run_id` (null), `started_at`, `finished_at` (timestamptz,
  indexed), `items_fetched`, `items_new` (JSONB); slice d adds `fetch_failures`, `lag_hours` (JSONB) and
  `unclustered_share` (float, null) through the existing additive column reconciliation.

### Content hash

`sha256(url + "\n" + norm(title) + "\n" + norm(text))` as lower-case hex, UTF-8, where `norm(s) = " ".join(s.split())`
(whitespace runs collapsed to one space, ends trimmed; case kept). `url` is used as given.

### Store (`backend/arp/emerging_themes/signal_store.py`)

`class SignalStore` built with a DSN (`SignalStore(settings.postgres_dsn)`), same pattern as
`PgVectorEmbeddingsStore`:

- `add_items(items: list[RawMention], *, seen_at: datetime | None = None) -> int`. `seen_at` defaults to now (UTC).
  Inserts each item whose hash is new with `first_seen_at = last_seen_at = seen_at`; for a hash already stored it
  only sets `last_seen_at = seen_at`. Duplicates inside one call count once. Returns the number of rows inserted.
  For the inserted items only, it embeds `title + "\n" + text` with `arp.retrieval.embeddings.embed_texts`, looked
  up at call time (a test that patches that attribute replaces it), in one call, and stores each vector in
  `chunk_embeddings` with `chunk_id = "signal:" + content_hash` and `embed_model = EMBED_MODEL_NAME`. An exception
  from embedding is logged and swallowed: the items stay stored, without embeddings.
- `read_items(*, since: datetime, until: datetime | None = None, source_types: list[SignalSourceType] | None = None)
  -> list[SignalItem]`: items with `since <= item_at` and, when given, `item_at < until`, and, when given,
  `source_type` in `source_types`; ordered by `item_at` then `content_hash`, both ascending.
- `record_scan(scan: SignalScan) -> None` and `latest_scans(limit: int = 10) -> list[SignalScan]` (newest
  `finished_at` first).

A stored item becomes a `RawMention` for a scan with `mention_id = content_hash`, `fetched_at = last_seen_at` and
every other field copied. `published_at` is stored as `timestamptz` and returned as `datetime.isoformat()` of the
UTC value (EDGAR's `"2026-11-10"` comes back as `"2026-11-10T00:00:00+00:00"`); a `published_at` that does not parse
as ISO 8601 is stored as null with `published_at_is_estimated = True`.

The app builds one store in `api/deps.py::get_signal_store()` (`lru_cache`d, `SignalStore(get_settings().postgres_dsn)`),
used by `POST /runs`, `GET /health` and both schedulers. The light-scan scheduler dependency reads `get_settings()`
the way `get_emerging_themes_scheduler` does.

### Full scan (`pipeline.py`)

`execute_emerging_themes_run` and `run_emerging_themes` gain keyword arguments `signal_store: SignalStore | None =
None` and `fetch: bool = True`. Without `signal_store` nothing changes (A2). With it:

1. If `fetch`, fetch from every source as today (`since = now - emerging_themes_lookback_days`) and `add_items`
   each source's result. If not `fetch`, no source is called.
2. The scan's mentions are `read_items(since=now - emerging_themes_lookback_days)`, from any source, keeping the
   newest `emerging_themes_full_scan_max_items` (new setting, default 1000) by `item_at` (ties: `content_hash`
   ascending), turned into `RawMention`s. `mentions.jsonl` and everything after are as today.
3. At every `return` after step 2 (including "no mentions", too few tags and missing clustering extras) it records a
   `SignalScan` with `kind="full"` and `run_id` = the run. An exception raised by a later step records nothing.
   With `fetch=False`, `items_fetched` and `items_new` are `0` for every source given.

`tag_mention` and `cluster_tags` stay importable as names of `arp.emerging_themes.pipeline` (tests replace them).
`POST /api/emerging-themes/runs` accepts `"fetch": false` (default `true`) and passes the app's `SignalStore`;
`EmergingThemesScheduler` passes it too.

### Fetchers (`ingestion/`)

- Each of the three fetchers takes a keyword `transport: httpx.AsyncBaseTransport | None = None`, handed to its
  `httpx.AsyncClient`. `default_sources(settings, *, transport=None)` passes `transport` to all three.
  `RegulatoryRssSource` takes `user_agent: str` as first argument; `default_sources` passes
  `settings.edgar_user_agent` to it and to `EdgarFullTextSearchSource`. Both send it as `User-Agent` on every request.
- `MentionSource` gets the class attribute `failed_requests: int = 0` (stub sources that never touch it report 0).
  Each of the three fetchers sets it to 0 at the start of `fetch` and adds 1 for each request that still fails
  after its last attempt.
- Retries: up to 3 attempts per request. Retried: `httpx.TransportError` (connect errors, timeouts), status 429,
  status 500-599. Not retried: any other status >= 400 and, for GDELT and EDGAR, a body that is not JSON; these fail
  at once. For RSS only transport errors and status codes count: a feed `feedparser` cannot read gives 0 entries
  and is not a failure. Waits
  between attempts are `RETRY_DELAYS_SECONDS = (1.0, 2.0)`, a module constant in `ingestion/base.py` that tests may
  patch. A request that fails is skipped and the fetch goes on with the next term or feed, as today.
- SEC rate limit: requests from these fetchers to any host equal to or ending in `.sec.gov` (`sec.gov`,
  `efts.sec.gov`, `www.sec.gov`) start at least 0.1 s apart, process-wide (one limiter shared by all fetchers and
  concurrent fetches), retries included.

### Light scan

- `pipeline.run_light_scan(sources: list[MentionSource], store: SignalStore, settings: Settings) -> SignalScan`:
  fetches from every source with `since = now - emerging_themes_light_scan_lookback_days` (new setting, default 2),
  `add_items` each result, records and returns a `SignalScan` with `kind="light"`, `run_id=None`. No model, no
  universe, no run, no topic period. A source whose `fetch` raises counts `items_fetched = items_new = 0`.
- `scheduler.LightScanScheduler(IntervalScheduler)`, `job_id = "emerging-themes-light-scan"`, config file
  `<emerging_themes_state_dir>/light_scan/schedule.json`, config model `LightScanScheduleConfig(enabled: bool,
  interval_hours: float = 24.0, last_scan_id: str | None = None, next_run_at: str | None = None)`. `enabled`
  defaults to the new setting `emerging_themes_light_scan_enabled` (default `False`). Its run calls
  `run_light_scan(default_sources(settings), …)` and sets `last_scan_id`. Started with the other schedulers.
- `GET /api/emerging-themes/light-scan-schedule` and `PUT` (same shape, `interval_hours <= 0` gives 422 with
  `Interval must be greater than 0 hours.` as the weekly one).
- UI, section "Automatic schedule": a checkbox labelled `Daily light scan: fetch and store new items, no clustering`
  bound to `enabled`. "Save schedule" first PUTs the light-scan config, then the weekly one, and shows the existing
  saved text; if either PUT fails, its `detail` shows in the existing `role="alert"` status and the other stays saved.
  If the weekly schedule could not be loaded, the checkbox is not shown (as the rest of the form today).

### Radar health (slice d)

Every recorded scan (light and full) also holds:

- `fetch_failures[name]` = that source's `failed_requests` after its fetch, or `1` when its `fetch` raised. `0` for
  every source of a full scan with `fetch=False`.
- `lag_hours[name]` = hours from the scan's `finished_at` back to the latest `first_seen_at` of stored items whose
  `source` equals `name`, rounded to 1 decimal; `null` when the store has none.
- `unclustered_share` = for a full scan with N mentions read (N > 0): `(N - C) / N` rounded to 3 decimals, where C
  is the number of mentions with at least one tag in any cluster (`member_tag_ids`); `1.0` when the run stopped
  before clustering. `null` for N = 0 and for light scans.

`GET /api/emerging-themes/health?limit=10` returns `{"scans": [SignalScan, …]}`, newest `finished_at` first,
at most `limit` (1-50, default 10; outside that range 422).

UI, below the "Automatic schedule" section and shown even when the schedule could not be loaded, an `h3`
`Radar health`. All rounding here is half up (`Math.round`):

- No scans: the text `No scans recorded yet.`
- Else the line `Latest scan: <light|full>, finished <YYYY-MM-DD HH:MM> UTC`, then a table with header
  `Source | Failed requests | Newest item` and one row per key of the latest scan's `fetch_failures`, in the
  fixed order `gdelt`, `edgar_fts`, `regulatory_rss`, then any other keys sorted alphabetically. Source labels: `gdelt` → `News (GDELT)`, `edgar_fts` → `Filings (SEC EDGAR)`, `regulatory_rss` →
  `Regulators (RSS)`, any other key as is. Newest item from `lag_hours`: `null` → `none yet`; under 1 → `under 1 h
  ago`; under 48 → `<round(h)> h ago`; else `<round(h / 24)> days ago`.
- Then `Items in no cluster: <round(share × 100)>% (full scan finished <YYYY-MM-DD HH:MM> UTC)` from the newest
  returned scan with a non-null `unclustered_share`, or `Items in no cluster: no full scan yet`.
- If the request fails: `Radar health could not be loaded: <detail>` with `role="alert"`.

## Defaults taken

1. **Light scan off by default.** `IntervalScheduler` fires 5 s after the app starts, so "on" would make every app
   start (CI, the e2e stack, a fresh sandbox) call GDELT and the SEC. One tick of the checkbox turns it on.
2. **Light scan every 24 h, fetching the last 2 days**, so one missed day leaves no gap.
3. **Hash = URL + whitespace-normalised title and text.** The same filing matched by two search terms with different
   highlighted snippets is two items; the same article returned by two GDELT queries is one.
4. **`item_at` = published time, else first seen.** GDELT items have no publish time today.
5. **Lag counts from the newest item stored for the first time**, not from publish times, so it shows when a
   source last gave anything new.
6. **3 attempts, waits 1 s and 2 s**, retrying only connection errors, timeouts, 429 and 5xx. 403 from the SEC
   (its rate-limit block) is not retried.
7. **One SEC limiter per process, 0.1 s between request starts**, covering EDGAR search and the SEC press feed.
8. **Embeddings only for newly stored items**, with the model clustering and retrieval already use; no backfill.
9. **No pruning**: at roughly 1,000 items a day the table stays small.
10. **A full scan reads stored items in its 14-day window**, from any source, including items the light scan
    collected, up to the cap in default 12.
11. **Health endpoint returns the last 10 scans**; the page shows the latest one plus the newest no-cluster share.
12. **A full scan reads at most 1,000 stored items, newest first** (`emerging_themes_full_scan_max_items`), so its
    model calls stay at today's order of magnitude when the light scan is on.

## Acceptance

"Fresh Postgres" means a new, empty Postgres schema created for the test (`CREATE SCHEMA t_<uuid>`, with
`search_path=t_<uuid>,public` set on the DSN, e.g. `?options=-csearch_path%3Dt_<uuid>,public`, so pgvector's type in
`public` stays visible) on `ARP_TEST_POSTGRES_DSN`, or `ARP_POSTGRES_DSN` when that is unset, initialised with
`ensure_schema` as `arp db init-postgres` does, dropped after the test; `store = SignalStore(<that DSN>)`. CLI rows run
`arp db init-postgres` with `ARP_POSTGRES_DSN` set to that DSN. HTTP rows (`GET`/`PUT`) use
`TestClient(arp.api.main.app)` without a `with` block (lifespan not run, so no scheduler starts), after setting
`ARP_EMERGING_THEMES_STATE_DIR=<empty tmp dir>` and `ARP_POSTGRES_DSN=<Fresh Postgres DSN>` and calling
`get_settings.cache_clear()` and `get_signal_store.cache_clear()`; "fresh state dir" is that tmp dir. Unless "Given" says otherwise, `arp.retrieval.embeddings.embed_texts` is patched
to return `np.ones((len(texts), 384), dtype=np.float32)`, `arp.emerging_themes.ingestion.base.RETRY_DELAYS_SECONDS`
is patched to `(0.0, 0.0)`, and fetchers are built with an `httpx.MockTransport` (no live network in any row).
`item(u, t, x, s)` means `RawMention(source_type=s, title=t, text=x, url=u)`, `s` = `GDELT` when omitted. Full-scan
rows use a fake `LLMClient` and replace `arp.emerging_themes.pipeline.tag_mention` and `.cluster_tags` with
stand-ins; no row makes a model call.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Fresh Postgres | `store.add_items([item("https://a.example/1", "T1", "X1"), item("https://a.example/2", "T2", "X2")])` | returns `2`; `store.read_items(since=datetime(2000,1,1,tzinfo=UTC))` returns 2 items whose `content_hash` values equal `sha256("https://a.example/1\nT1\nX1")` and `sha256("https://a.example/2\nT2\nX2")` (hex) | holdout |
| AC-2  | Fresh Postgres; `item("https://a.example/1","T1","X1")` added with `seen_at=2026-11-01T00:00Z` | the same item added again with `seen_at=2026-11-02T00:00Z` | returns `0`; `read_items` returns 1 item with `first_seen_at` 2026-11-01T00:00Z and `last_seen_at` 2026-11-02T00:00Z | holdout |
| AC-3  | Fresh Postgres | `add_items([item(u, "Solar  cell", "A\n b "), item(u, " Solar cell", "A b")])` with the same `u` | returns `1`; `read_items` returns 1 item | holdout |
| AC-4  | Fresh Postgres | `add_items([item(u, "T", "X1"), item(u, "T", "X2")])` with the same `u` | returns `2` | holdout |
| AC-5  | Fresh Postgres | one item each of `GDELT`, `EDGAR_FTS`, `REGULATORY_RSS` added | `read_items` gives them `source_type` `news`, `filings`, `regulators` respectively | holdout |
| AC-5b | — | import `SignalSourceType` from `arp.schemas.emerging_themes` | `{v.value for v in SignalSourceType} == {"news","filings","regulators","research","jobs"}` | holdout |
| AC-6  | Fresh Postgres; items A (`published_at="2026-11-10T00:00:00+00:00"`), B (`published_at=None`, added with `seen_at=2026-11-12T00:00Z`), C (`published_at="2026-11-14T00:00:00+00:00"`, `REGULATORY_RSS`) | `read_items(since=2026-11-10T00:00Z, until=2026-11-14T00:00Z)` | returns `[A, B]` in that order; B's `item_at` is 2026-11-12T00:00Z | holdout |
| AC-6b | AC-6's items | `read_items(since=2026-11-01T00:00Z, source_types=[SignalSourceType.REGULATORS])` | returns `[C]` | holdout |
| AC-7  | Fresh Postgres; `embed_texts` patched to record its input | `add_items([item(u,"T","X")])`, then the same call again | first call embeds `["T\nX"]`; `chunk_embeddings` has one row with `chunk_id = "signal:" + hash` and `embed_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"`; the second call embeds nothing and adds no row | holdout |
| AC-8  | Fresh Postgres; `embed_texts` patched to raise `RuntimeError` | `add_items` of 2 new items | returns `2` without raising; `read_items` returns 2 items; `chunk_embeddings` has no `signal:` row | holdout |
| AC-9  | Fresh Postgres; a source returning 5 distinct items; `signal_store=store` | `execute_emerging_themes_run(…)` | `read_items` returns those 5; each line of the run's `mentions.jsonl` has `mention_id` equal to a stored `content_hash` (5 lines) | holdout |
| AC-10 | Fresh Postgres; 3 items added with `seen_at` 1 day ago, 1 added with `seen_at` 20 days ago (all `published_at=None`); a source that counts its `fetch` calls and would return 1 extra item; `emerging_themes_lookback_days=14` | `execute_emerging_themes_run(…, signal_store=store, fetch=False)` | the source's call count is `0`; `mentions.jsonl` has exactly the 3 recent items' hashes as `mention_id` | holdout |
| AC-10b | Fresh Postgres; 5 items with `published_at` 1, 2, 3, 4 and 5 days ago; `emerging_themes_full_scan_max_items=3` | `execute_emerging_themes_run(…, signal_store=store, fetch=False)` | `mentions.jsonl` has exactly the hashes of the items 1, 2 and 3 days old | holdout |
| AC-11 | App with a `SignalStore` | `POST /api/emerging-themes/runs` with `{"companies": [...], "fetch": false}` | 200 with a `run_id`; the background run calls no source | unit |
| AC-12 | Must not change: no `signal_store` argument | `cd backend && python3 -m pytest tests/test_emerging_themes_pipeline.py` | passes with no test edited | unit |
| AC-13 | Fresh Postgres | `arp db init-postgres` run a second time | exits 0; tables `signal_items` and `signal_scans` exist | holdout |
| AC-14 | `GdeltSource(transport=…)` whose first query term gets 429, then 503, then 200 with 2 articles; other terms 200 with no articles | `await source.fetch(since)` | returns the 2 articles; the transport saw 3 requests for that term; `source.failed_requests == 0` | holdout |
| AC-15 | `GdeltSource` whose first term raises `httpx.ConnectError` on every request; other terms 200 with 1 article each | `fetch` | the transport saw 3 requests for the first term; returns 3 mentions; `failed_requests == 1` | holdout |
| AC-16 | `GdeltSource` whose first term gets 404 | `fetch` | the transport saw 1 request for that term; `failed_requests == 1` | holdout |
| AC-17 | `RETRY_DELAYS_SECONDS` unpatched; first GDELT term gets 503, 503, 200 | `fetch` | the 2nd request starts ≥ 1.0 s after the 1st and the 3rd ≥ 2.0 s after the 2nd | holdout |
| AC-18 | `EdgarFullTextSearchSource("Acme research@acme.example", query_terms=[25 terms], transport=…)`, every request 200 with `{"hits": {"hits": []}}`; the handler records `time.monotonic()` per request | `fetch` | 25 requests; for every i, `t[i+10] - t[i] >= 0.99` s | holdout |
| AC-19 | `h` = a `MockTransport` handler recording request headers, answering EDGAR with `{"hits": {"hits": []}}` and RSS with an empty `<rss version="2.0"><channel></channel></rss>` | `default_sources(Settings(edgar_user_agent="Acme research@acme.example"), transport=MockTransport(h))`; the EDGAR and RSS sources fetch | every request of both carries `User-Agent: Acme research@acme.example` | holdout |
| AC-19b | `EdgarFullTextSearchSource(ua, query_terms=[5 terms], transport=t)` and `RegulatoryRssSource(ua, feed_urls=["https://www.sec.gov/news/pressreleases.rss"] * 5, transport=t)`, one shared handler recording `time.monotonic()` per request, all 200 (empty results) | both fetch concurrently with `asyncio.gather` | 10 requests; sorted by start time, consecutive starts are ≥ 0.099 s apart | holdout |
| AC-20 | Must not change: GDELT stub returns `{"articles":[{"title":"Grid deal","url":"https://n.example/1"},{"title":"","url":"https://n.example/2"}]}` | `GdeltSource(query_terms=["q"], transport=…).fetch(since)` | returns 1 mention: `source_type=gdelt`, `title="Grid deal"`, `text="Grid deal"`, `url="https://n.example/1"`, `published_at=None`, `published_at_is_estimated=True` | holdout |
| AC-20b | Must not change: EDGAR stub returns one hit `{"_source": {"display_names": ["Acme Corp (CIK 0000012345)"], "adsh": "0000012345-26-000001", "ciks": ["0000012345"], "root_forms": ["8-K"], "file_date": "2026-11-10"}, "highlight": {"text": ["new plant"]}}` | `EdgarFullTextSearchSource(ua, query_terms=["q"], transport=…).fetch(since)` | 1 mention: `source_type=edgar_fts`, `title="8-K filed by Acme Corp (CIK 0000012345)"`, `text="new plant"`, `url="https://www.sec.gov/Archives/edgar/data/12345/000001234526000001/0000012345-26-000001-index.htm"`, `raw_entity_names=["Acme Corp"]`, `published_at="2026-11-10"` | holdout |
| AC-20c | Must not change: RSS stub returns `<rss version="2.0"><channel><item><title>Fed statement</title><link>https://r.example/1</link><description>Rates held</description></item></channel></rss>` | `RegulatoryRssSource(ua, feed_urls=["https://r.example/feed"], transport=…).fetch(since)` | 1 mention: `source_type=regulatory_rss`, `title="Fed statement"`, `text="Rates held"`, `url="https://r.example/1"`, `published_at=None`, `published_at_is_estimated=True` | holdout |
| AC-21 | Fresh Postgres; `default_sources(settings, transport=…)` answering 2 GDELT articles per term (the same 2 for all 4 terms), EDGAR `{"hits": {"hits": []}}`, and 1 RSS entry per feed (5 distinct links, no `pubDate`) | `run_light_scan(sources, store, settings)` | returns `kind="light"`, `run_id=None`, `items_fetched == {"edgar_fts": 0, "gdelt": 8, "regulatory_rss": 5}`, `items_new == {"edgar_fts": 0, "gdelt": 2, "regulatory_rss": 5}`; `store.latest_scans(1)` returns that scan | holdout |
| AC-22 | AC-21 done | the same light scan again | `items_new` is `0` for every source; `items_fetched` as in AC-21 | holdout |
| AC-23 | AC-21's setup | `run_light_scan` | `run_store.list_runs("emerging_themes")` and `topic_store.list_periods()` are unchanged | holdout |
| AC-24 | AC-21's setup; `emerging_themes_light_scan_lookback_days=2` | `run_light_scan` | each GDELT request's `startdatetime` is within 5 min of now − 48 h | holdout |
| AC-25 | Fresh state dir | `GET /api/emerging-themes/light-scan-schedule` | 200, `enabled == false`, `interval_hours == 24.0`, `last_scan_id == null` | holdout |
| AC-26 | Fresh state dir | `PUT /api/emerging-themes/light-scan-schedule` `{"enabled": true, "interval_hours": 24}`, then `GET` | both 200; `GET` shows `enabled == true` | holdout |
| AC-27 | Must not change: fresh state dir | `GET /api/emerging-themes/schedule` | `enabled == false`, `interval_hours == 168.0` | holdout |
| AC-28 | Fresh Postgres; light scan enabled; `default_sources` replaced by one stub source returning 1 item | the scheduler's scheduled run fires once | `last_scan_id` in the light-scan schedule equals the recorded scan's `scan_id` | unit |
| AC-29 | Fresh Postgres; a full scan recorded by AC-9's call | `store.latest_scans(1)` | one scan, `kind="full"`, `run_id` = that run's id, `items_new == {<source name>: 5}` | holdout |
| AC-10c | AC-10's setup | the same call | `store.latest_scans(1)[0]` has `kind="full"`, `items_fetched == items_new == {<source name>: 0}` | holdout |
| AC-30 | Running app, Emerging Themes page (the stack may make one live light scan once enabled) | tick `Daily light scan: fetch and store new items, no clustering`, click "Save schedule", reload; then untick and save again to clean up | after the reload the checkbox is ticked | evaluator |
| AC-31 | Fresh Postgres; `default_sources(settings, transport=…)`; every GDELT request 404, EDGAR 200 `{"hits": {"hits": []}}`, RSS 200 `<rss version="2.0"><channel></channel></rss>` | `run_light_scan` | `fetch_failures == {"edgar_fts": 0, "gdelt": 4, "regulatory_rss": 0}` | holdout |
| AC-32 | Fresh Postgres; sources: a `MentionSource` named `boom` whose `fetch` raises `RuntimeError`, and a GDELT source returning 1 item | `run_light_scan` | returns normally; `fetch_failures["boom"] == 1`; `items_new == {"boom": 0, "gdelt": 1}` | holdout |
| AC-33 | Fresh Postgres; R = `item("https://r.example/1", "Fed statement", "Rates held", REGULATORY_RSS)` added with `seen_at` = now − 30 h; `default_sources(settings, transport=…)` with every RSS feed returning `<rss version="2.0"><channel><item><title>Fed statement</title><link>https://r.example/1</link><description>Rates held</description></item></channel></rss>`, GDELT returning 1 new article, EDGAR `{"hits": {"hits": []}}` | `run_light_scan` | `lag_hours == {"edgar_fts": None, "gdelt": 0.0, "regulatory_rss": 30.0}` | holdout |
| AC-34 | Fresh Postgres; a source returning 10 distinct items; `emerging_themes_min_cluster_size=2`; `tag_mention` stub gives 1 tag per item; `cluster_tags` stub returns 1 valid `TopicCluster` (as built in `tests/test_emerging_themes_pipeline.py`) whose `member_tag_ids` are the tags of 6 items; fake LLM yields no candidate | `execute_emerging_themes_run(…, signal_store=store)` | the recorded full scan has `unclustered_share == 0.4` | holdout |
| AC-35 | AC-21 done | `store.latest_scans(1)` | `unclustered_share is None` | holdout |
| AC-36 | Fresh Postgres; 12 scans recorded with distinct `finished_at` | `GET /api/emerging-themes/health`, then `?limit=3`, then `?limit=0` | 10 scans newest first; 3 scans; 422 | holdout |
| AC-37 | Fresh Postgres, no scans | `GET /api/emerging-themes/health` | 200 `{"scans": []}` | holdout |
| AC-38 | Running app; one light scan recorded with `finished_at=2026-11-25T06:00Z`, `fetch_failures={"gdelt":0,"edgar_fts":2,"regulatory_rss":0}`, `lag_hours={"gdelt":0.4,"edgar_fts":30,"regulatory_rss":null}` (seeded with `record_scan`) | open the Emerging Themes page | `Latest scan: light, finished 2026-11-25 06:00 UTC`; rows `News (GDELT) · 0 · under 1 h ago`, `Filings (SEC EDGAR) · 2 · 30 h ago`, `Regulators (RSS) · 0 · none yet` in that order | evaluator |
| AC-39 | AC-38 plus an older full scan with `unclustered_share=0.42`, `finished_at=2026-11-24T09:00Z` | open the page | `Items in no cluster: 42% (full scan finished 2026-11-24 09:00 UTC)` | evaluator |
| AC-39b | only AC-38's scan recorded | open the page | `Items in no cluster: no full scan yet` | evaluator |
| AC-40 | Running app, no scans recorded | open the Emerging Themes page | under the `Radar health` heading the text `No scans recorded yet.` | evaluator |
| AC-41 | a Postgres schema where `signal_scans` was created without `fetch_failures`, `lag_hours`, `unclustered_share` and holds one row | `arp db init-postgres` | exits 0; the three columns exist; `store.latest_scans(1)` returns the old row with `fetch_failures == {}`, `lag_hours == {}`, `unclustered_share is None` | holdout |

Must not change: A1 (AC-27), A2 (AC-12), A3 (AC-20, AC-20b, AC-20c), A4 (AC-23 and `run_light_scan` takes no model client).

Supersedes no earlier spec's rows.

## Slices

Build in order; each slice is one PR with `Spec: theme-radar-signal-store` and a `Rows:` line listing exactly the IDs below, comma-separated (no ranges).

| Slice | Scope | Risk | Rows |
|-------|-------|------|------|
| a | `SignalSourceType`, `SignalItem`, `signal_items` table, `SignalStore.add_items/read_items`, `get_signal_store`, embeddings, full scan reads the store (with the item cap), `fetch` flag (function, API, scheduler) | `risk:normal` | AC-1, AC-2, AC-3, AC-4, AC-5, AC-5b, AC-6, AC-6b, AC-7, AC-8, AC-9, AC-10, AC-10b, AC-11, AC-12, AC-13 |
| b | retries, `failed_requests`, `transport` (fetchers and `default_sources`), SEC limiter, RSS User-Agent | `risk:normal` | AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-19b, AC-20, AC-20b, AC-20c |
| c | `SignalScan` (without the slice-d fields), `signal_scans` table, `record_scan/latest_scans`, full-scan scan rows, `run_light_scan`, `LightScanScheduler`, its API and checkbox | `risk:normal` | AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-10c, AC-30 |
| d | health fields and columns, `GET /health`, the `Radar health` block | `risk:low` | AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-39, AC-39b, AC-40, AC-41 |

Every builder makes the smallest diff with the lowest complexity: no refactors, no new abstractions beyond the
names above, no unrelated cleanup. After slice c and d, `openwiki/` needs the weekly refresh to mention the store.
