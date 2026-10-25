# Test stand-ins: fixed web search, fetch and model answers for the running app

Status: approved by the owner, 2026-10-25.

## Intent

Hidden acceptance tests (the `holdout` repo) and the evaluator drive the **running app** over HTTP and the
browser (`backend/scripts/e2e_stack.sh`). They cannot replace a FastAPI dependency the way unit tests do. On
`main` today:

- web search is hard-wired to DuckDuckGo (`deps.get_web_search_client` and direct `DuckDuckGoSearchClient(...)`
  calls);
- `fetch_source_text` and `fetch_source_original` fetch real URLs, and their SSRF guard resolves real DNS;
- the model can only be redirected through `ANTHROPIC_BASE_URL`, and a fake server there would have to know
  each feature's prompts and tool schemas.

So any row that needs "the search returns these 4 results" or "the model returns this note" cannot be tested
against the running app. 54 of the 62 holdout rows of `theme-research-note` are blocked on this.

The owner wants a switch that makes the running app read fixed answers from fixture files instead of the web
and the model: off by default, and impossible to switch on by accident in production.

## Owner decisions (2026-10-25)

1. Build the switch first, as its own small feature; `theme-research-note` is built after it.
2. **Fixture folder** (approach A below). `ARP_STANDINS_DIR` points at a folder; the app reads it fresh on every
   call, so a test changes a file between requests.
3. **Production guard:** with `ARP_STANDINS_DIR` set, the app (and the `arp` CLI) refuses to start if a model
   API key (`ARP_ANTHROPIC_API_KEY` or `ARP_GEMINI_API_KEY`) is set. Production always has a key, so a stray
   `ARP_STANDINS_DIR` there stops the app loudly instead of quietly serving fake answers.
4. In the same PR, `theme-research-note` gets fixed, named model-call contracts. Nothing else in it changes.
5. Other specs (Ask ARP, `theme-context-brief`, `theme-position-standards`) can use the same contract; they are
   not amended here.

## Goals

- With `ARP_STANDINS_DIR` set, every DuckDuckGo web search, every fetch through `fetch_source_text` or
  `fetch_source_original`, and every model call from a client built by `arp/llm/factory.py` is answered from
  the folder, with no network access for them. Other fetches (e.g. company homepages in `arp/discovery`) stay
  real; they are outside this feature.
- A model call is answered by the fixture named after its `output_model` class, so any feature that names its
  output classes in its spec has a contract a fixture can answer, with no change to the call site.
- A fixture can return an answer, raise an error, or wait first ("slow" stand-ins).
- Every call is recorded, so a test can check what the app asked (a prompt, a query, a URL) or that it asked
  nothing.
- With `ARP_STANDINS_DIR` unset, nothing changes.

## Non-goals

- Stand-ins for other outside services: EDGAR, XBRL, arXiv, Semantic Scholar, ESG provider, Superset,
  OpenSearch, Neo4j, embeddings, the cloud compute services. Add them when a spec needs them.
- Matching a model answer to its prompt (one fixture per output class, the same answer on every call).
- A UI banner. The response header and `/api/health` say stand-ins are on.
- Amending the Ask ARP, `theme-context-brief` or `theme-position-standards` specs.

## Anti-goals

- Production serving fixture answers.
- A stand-in call that silently falls through to the real web or the real model.
- Any behaviour change with the switch off.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Fixture folder**, model fixtures keyed by the call's `output_model` class name, read fresh per call. | No change to call sites or to the `LLMClient` protocol; `theme-position-standards` already names its classes (`PositionDraft`, `StandardsDraft`). Two call sites sharing one output class share one fixture. | **Chosen by the owner** |
| B | Add a `call_name` argument to every model call; key fixtures by it. | Explicit, but touches every existing call site and the protocol. | Rejected |
| C | Hidden test-control endpoint (`/api/_standins`) that loads fixtures. | No files, but adds an API that would be dangerous if ever reachable in production. | Rejected |

## The switch

New setting `standins_dir: Path | None` (env `ARP_STANDINS_DIR`, default unset). When set:

- Settings validation fails, so the API and every `arp` command exit non-zero, with:
  - `ARP_STANDINS_DIR is set together with a model API key; stand-ins are for tests only. Unset one of them.`
    when `anthropic_api_key` or `gemini_api_key` is set (a `.env` file counts, as it does for every setting);
  - `ARP_STANDINS_DIR <path> is not a directory.` when the path does not exist or is not a directory.
- The API logs one warning at startup: `Test stand-ins are ON: web search, fetch and model answers come from
  <path>`.
- Every API response carries the header `X-ARP-Stand-ins: on`; `GET /api/health` returns
  `{"status": "ok", "stand_ins": true}`.

When unset: no header, `GET /api/health` returns `{"status": "ok"}` exactly as today.

## Fixture folder

All files are UTF-8 JSON, read on every call (no caching), so a test may rewrite them between requests.

### Model: `model/<ClassName>.json`

`<ClassName>` is `output_model.__name__` of the `complete_structured` call, e.g. `model/PositionDraft.json`,
`model/_AssessmentList.json`. The file holds one of:

```
{"output": { ...an instance of the output model... }, "delay_seconds": 30}
{"error": "<message>", "delay_seconds": 30}
```

`delay_seconds` is optional (default 0) and applies before answering or raising.

- `output`: validated with `output_model.model_validate`; returned with an `LLMUsage` whose `provider` and
  `model` are `stand-in` and whose token counts are 0.
- `error`, a missing file, unreadable JSON, or an `output` that fails validation: the call raises
  `RuntimeError` with, respectively, `<message>`, `no stand-in for <ClassName>`, `stand-in model/<ClassName>.json
  is not valid JSON`, `stand-in model/<ClassName>.json does not match <ClassName>: <first validation error>`.
  `RuntimeError` is what callers already see when no model is configured, so existing "no model" fallbacks
  (e.g. unranked discovery results) behave the same.
- There are no retries, no disk cache and no batching for a stand-in call; `images`, `temperature` and
  `max_tokens` are ignored.

Every client built by `arp/llm/factory.py` (`build_llm_client`, `build_verifier_llm_client`, batch or not,
Anthropic or Gemini model) is the stand-in while the switch is on, and building it needs no API key.

### Web search: `search.json`

```
{"results": [{"title": "...", "url": "...", "snippet": "..."}], "delay_seconds": 30}
{"error": "<message>", "delay_seconds": 30}
```

The same `results`, in file order, answer **every** query; `snippet` is optional (default `""`).
`max_results` is ignored, so a fixture can hold more results than one query would ask for. `error` or a
missing file raises `RuntimeError` (`<message>`, or `no stand-in for web search`). This replaces every
`DuckDuckGoSearchClient` the app or CLI builds, including `deps.get_web_search_client`: all of them are built
by one factory function, which takes `user_agent` and an optional `transport` (as `arp/discovery/pipeline.py`
passes one), so `DuckDuckGoSearchClient(` appears nowhere else in `backend/arp`.

### Fetch: `fetch.json`

An object keyed by exact URL:

```
{"https://iea.org/weo": {"text": "Grid investment must double by 2030."},
 "https://doi.org/10.1/x": {"error": "timeout"},
 "https://slow.example/a": {"text": "...", "delay_seconds": 30}}
```

- `fetch_source_text(url, ...)`: a `text` entry returns that text, cut to the existing 60,000 characters; a
  `text` of `""` is a page with no extractable text. An `error` entry, a URL not in the file, or a missing
  file is a failed fetch. Each behaves exactly as the real function does for that outcome today, so callers
  need no change. No SSRF check and no DNS lookup run for a stand-in fetch.
- `fetch_source_original(url, ...)`: a `text` entry returns `(text encoded as UTF-8, "text/plain")`, neither
  read from nor written to its disk cache; anything else returns `None` as a failed fetch does today.

### Call log: `calls.jsonl`

The app appends one JSON line per stand-in call, before answering, in call order:

```
{"kind": "model", "name": "<ClassName>", "system": "<system>", "prompt": "<prompt>"}
{"kind": "search", "query": "<query>"}
{"kind": "fetch", "url": "<url>"}
```

The app creates the file when absent and never truncates it; a test deletes it to start a fresh log.

## Running it

- `backend/scripts/e2e_stack.sh up` creates `$ARP_STANDINS_DIR` when the variable is set, and passes it to
  the API like any other `ARP_*` variable.
- `.github/workflows/holdout.yml` sets `ARP_STANDINS_DIR: ${{ runner.temp }}/standins` in the job's `env`, so
  the app and the hidden tests share one folder. That job sets no model key, so the guard does not trip.
- The `evaluator` skill gets one line: when a spec's acceptance fixture says the evaluator's app uses
  stand-ins, start the stack with `ARP_STANDINS_DIR` set and no model key in the environment or
  `backend/.env`, and write the fixture files before each row.

## How other specs use it

A spec whose rows need stand-ins names, for each model call, the `output_model` class and its fields. That is
the whole contract: the fixture file is `model/<ClassName>.json`.

- `theme-position-standards` already does (`PositionDraft`, `StandardsDraft`; "the stand-in received no call"
  and "the stand-in's recorded prompt" read `calls.jsonl`).
- `theme-research-note` gets its two contracts in this PR (below).
- Ask ARP and `theme-context-brief` can add theirs when their tests are written; not amended here.

### Amendment to `theme-research-note` (this PR)

Adds a section **Model calls and web search (stand-in contract)** and points its Constraints bullet on
stand-ins at this spec:

- Search results from all queries are merged in query order and de-duplicated by URL (first occurrence kept)
  before classification. With the stand-in every query returns the same list, so the 4 fixture results stay 4.
- **Classification**: exactly one `complete_structured` call per propose run, `output_model`
  `SourceClassificationDraft` = `{sources: [{url: str, category: "intergovernmental" | "official_statistics" |
  "central_bank_regulator" | "academic" | "none", publisher: str, why: str, how: str}]}`. Entries are matched
  to search results by exact `url`; a search result with no entry counts as `none`; an entry whose `url` is
  not a search result is ignored. `title` comes from the search result. Order is search order.
- **Note**: exactly one call per write run, `output_model` `ResearchNoteDraft` = `{risks, opportunities,
  financial_relevance, growth_potential, transmission_channels}`, each a list (default `[]`) of
  `{title: str, text: str, channel: "economic" | "financial" | null, citations: [{source_id: str, quote: str}]}`.

## My calls (owner to confirm with the acceptance table)

1. **One answer per output class**, the same on every call, re-read per call. A test that needs two different
   answers rewrites the file between requests.
2. **Errors are `RuntimeError`**, matching "no model configured", so existing fallbacks keep working.
3. **`max_results` ignored** by the search stand-in, so a fixture can exceed one query's page size
   (research-note AC-69 needs 14).
4. **Fetch fixtures are text only.** A PDF from a URL is not needed by any spec yet; uploads cover PDFs.
5. **Header plus health field, no UI banner.**
6. **No holdout row for a successful model answer in the running app on `main`.** The only API path on
   `main` with a stand-in-answerable model call (`discover-sources` ranking) keys its answer on ids generated
   during the request, so a fixture cannot name them. AC-13 (unit) covers it now; `theme-research-note`'s rows
   cover it in the running app once that feature is built.
7. **AC-33 checks source text**, not behaviour. It is the one practical check that all ~16 search call sites go
   through the stand-in; accept it knowingly.
8. **Holdout job always runs with stand-ins on.** That job has no model key, so model calls failed there
   before too. Risk: a regression holdout test that expects the old "API key is not set" message or real web
   results would now see the stand-in message or an empty search. The test-writer adjusts such a test.

## Constraints

- Repo checks. No API model change, so no OpenAPI or frontend regeneration.
- Golden-set CI: the change touches `arp/llm` (the factory), so the golden-set check runs; with the switch off
  it must pass unchanged.
- The SSRF guard and `net_safety` stay as they are; only the stand-in path skips them.

## Left to the builder

Where the stand-in classes live, how the header is added, and file locking for `calls.jsonl`
(appends from concurrent requests must not interleave within a line).

## Acceptance

Fixture: the stack started with `ARP_STANDINS_DIR=<dir>` (an existing empty folder), no model key in the
environment or `backend/.env`, unless a row says otherwise. "Start the API" means
`uvicorn arp.api.main:app` from `backend/`. `POST /api/taxonomies/discover-sources {"name": "Grid storage"}`
runs 7 web searches (4 authority, 3 fund queries) and, when it finds any result, 1 ranking model call with
`output_model` `_AssessmentList`. "Contains" means a substring; "equals" means the whole message.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `ARP_STANDINS_DIR=<dir>` and `ARP_ANTHROPIC_API_KEY=x` in the environment | start the API | exits non-zero; output contains `ARP_STANDINS_DIR is set together with a model API key; stand-ins are for tests only. Unset one of them.` | holdout |
| AC-2 | `ARP_STANDINS_DIR=<dir>` and `ARP_GEMINI_API_KEY=x` | run `arp runs list` | exits non-zero; output contains the AC-1 message | holdout |
| AC-3 | `ARP_STANDINS_DIR=/nonexistent/x`, no key | start the API | exits non-zero; output contains `ARP_STANDINS_DIR /nonexistent/x is not a directory.` | holdout |
| AC-20 | `ARP_STANDINS_DIR=<dir>` in the environment, `ARP_ANTHROPIC_API_KEY=x` only in `backend/.env` | start the API | exits non-zero; output contains the AC-1 message | holdout |
| AC-21 | the fixture | start the API | its log output contains `Test stand-ins are ON: web search, fetch and model answers come from <dir>` exactly once | holdout |
| AC-4 | the fixture | `GET /api/health` | 200; body `{"status": "ok", "stand_ins": true}`; header `X-ARP-Stand-ins: on` | holdout |
| AC-22 | the fixture | `POST /api/taxonomies/discover-sources {}` | 422 with header `X-ARP-Stand-ins: on` | holdout |
| AC-5 | `search.json` with results A (`https://a.example/1`) and B (`https://b.example/2`), no model fixture | `POST /api/taxonomies/discover-sources {"name": "Grid storage"}` | 200; `authority_sources` URLs exactly A, B in that order, each `authority_score` null; `thematic_funds` URLs exactly A, B | holdout |
| AC-6 | AC-5, `calls.jsonl` deleted before the request | read `calls.jsonl` | exactly 8 lines: 7 `search` lines, each `query` containing `Grid storage`, then 1 `model` line with `name` `_AssessmentList`, a non-empty `system`, and a `prompt` containing `https://a.example/1` and `https://b.example/2` | holdout |
| AC-23 | AC-6 | send the AC-5 request again | `calls.jsonl` has 16 lines | holdout |
| AC-7 | AC-5 plus `model/_AssessmentList.json` `{"error": "down"}` | `POST /api/taxonomies/discover-sources {"name": "Grid storage"}` | 200; same body as AC-5 apart from `candidate_id`s | holdout |
| AC-8 | `search.json` `{"error": "down"}` | `POST /api/taxonomies/discover-sources {"name": "Grid storage"}` | 200; `authority_sources` `[]`; `thematic_funds` `[]` | holdout |
| AC-24 | the fixture (no `search.json`), `calls.jsonl` deleted | `POST /api/taxonomies/discover-sources {"name": "Grid storage"}` | 200; `authority_sources` `[]`; `thematic_funds` `[]`; `calls.jsonl` has exactly 7 lines, all `search` | holdout |
| AC-25 | AC-5, then `search.json` rewritten to hold only C (`https://c.example/3`) | `POST /api/taxonomies/discover-sources {"name": "Grid storage"}` | `authority_sources` URLs exactly C | holdout |
| AC-9 | `search.json` with A and `"delay_seconds": 3` | `POST /api/taxonomies/discover-sources {"name": "Grid storage"}` | 200, received no sooner than 3 s after sending | holdout |
| AC-10 | `fetch.json` `{"https://a.example/1": {"text": "Hello grid."}}` | `GET /api/taxonomies/sources/inspect?url=https://a.example/1` | 200; body `Hello grid.`; `Content-Type` starts `text/plain` | holdout |
| AC-26 | AC-10, `calls.jsonl` deleted before the request | read `calls.jsonl` | exactly 1 line: `{"kind": "fetch", "url": "https://a.example/1"}` | holdout |
| AC-27 | AC-10, then `fetch.json` rewritten so A → `{"text": "two"}` | `GET /api/taxonomies/sources/inspect?url=https://a.example/1` | 200; body `two` | holdout |
| AC-11 | AC-10 | `GET /api/taxonomies/sources/inspect?url=https://b.example/2` (not in the file) | 502, detail `Could not fetch source: https://b.example/2`, header `X-ARP-Stand-ins: on` | holdout |
| AC-12 | `fetch.json` with `http://127.0.0.1:9/x` → `{"text": "local"}` | `GET /api/taxonomies/sources/inspect?url=http://127.0.0.1:9/x` | 200; body `local` | holdout |
| AC-13 | switch on, no key; `model/X.json` `{"output": <valid X>}` | `complete_structured(output_model=X)` on clients from `build_llm_client` and `build_verifier_llm_client`, each with an Anthropic and a Gemini model, with plain settings and with `batch_settings(settings, True)` | every call returns that instance; usage `provider` and `model` `stand-in`, `input_tokens` and `output_tokens` 0 | unit |
| AC-14 | switch on; `model/X.json` missing | `complete_structured(output_model=X)` | `RuntimeError` whose message equals `no stand-in for X` | unit |
| AC-28 | switch on; `model/X.json` `{"error": "down"}` | as AC-14 | `RuntimeError` whose message equals `down` | unit |
| AC-29 | switch on; `model/X.json` holds `{not json` | as AC-14 | `RuntimeError` whose message equals `stand-in model/X.json is not valid JSON` | unit |
| AC-30 | switch on; `model/X.json` `{"output": {}}`, X has a required field | as AC-14 | `RuntimeError` whose message starts `stand-in model/X.json does not match X:` | unit |
| AC-31 | switch on; `model/X.json` with `"delay_seconds": 1`; a `fetch.json` entry with `"delay_seconds": 1` | one model call; one `fetch_source_text` call | each returns no sooner than 1 s after it starts | unit |
| AC-15 | switch on; `fetch.json` maps U → `{"text": ""}`, V → `{"error": "e"}`, W → a 70,000-character text | `fetch_source_text` for U, V, W, and an unlisted URL | `None`, `None`, a string equal to W's first 60,000 characters, `None`; no HTTP request is sent | unit |
| AC-16 | switch on; `search.json` with 14 results, the first without `snippet` | `search("q", max_results=5)` on the client from `deps.get_web_search_client` | 14 results in file order; the first has `snippet` `""` | unit |
| AC-32 | switch on | 50 concurrent stand-in search calls | `calls.jsonl` has 50 lines, each valid JSON | unit |
| AC-33 | the repo | search `backend/arp` for `DuckDuckGoSearchClient(` | it appears only in the class definition's module and the one search-client factory | unit |
| AC-34 | `ARP_STANDINS_DIR=<path that does not exist yet>`, no key | `bash backend/scripts/e2e_stack.sh up`, then `GET /api/health` | the directory exists; body `stand_ins` true | unit (a script, not pytest: it needs the stack) |

Must not change:
- AC-17: with `ARP_STANDINS_DIR` unset, `GET /api/health` returns exactly `{"status": "ok"}`, and neither it nor
  the 502 from `GET /api/taxonomies/sources/inspect?url=https://b.example/2` carries `X-ARP-Stand-ins`.
  Checked by: holdout.
- AC-18: with `ARP_STANDINS_DIR` unset, `build_llm_client` returns the same client class as before for an
  Anthropic and a Gemini model, and raises the same `ARP_ANTHROPIC_API_KEY is not set` error when no key is
  set. Checked by: unit.
- AC-19: with `ARP_STANDINS_DIR` unset, `fetch_source_text("http://127.0.0.1/x", ...)` returns `None` through the
  SSRF guard. Checked by: unit.
