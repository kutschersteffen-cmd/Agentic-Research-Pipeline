# LLM Gemini fallback

Date: 2026-11-11. Status: draft, awaiting owner approval. Slug: `llm-gemini-fallback`.

## Why

The owner asked: use Gemini if no Anthropic API key is available, or in case of no credit. Today
`build_llm_client` (`backend/arp/llm/factory.py`) picks the provider from the model name only. A `claude-*`
model with no `ARP_ANTHROPIC_API_KEY` raises `RuntimeError` (the API turns every `RuntimeError` into a 503,
`arp/api/main.py`), and an out-of-credit or invalid-key error during a call is not handled at all: the
Anthropic SDK retries network errors 4 times, then the call fails and so does the run.

## Scope

Runtime fallback in the app (`arp/llm`, `arp/config.py`) only. Not in scope: CI workflows (the golden-set job
already runs on Gemini when `ARP_GEMINI_API_KEY` is set), `.claude/`, a Gemini batch client, review-queue
changes, changes to how provenance is stored.

Callers: all 60-odd callers of `build_llm_client` / `build_verifier_llm_client` (CLI, API `deps.py` and
`run_scheduling.py`, `orchestration/`, `evidence_gate.py`, `doc_tree.py`) go through the two factory
functions, so the change lives in the factory and one new wrapper; no caller changes. No caller catches the
"key not set" `RuntimeError`; it still reaches `runtime_error_handler` (503) unchanged.

## Decisions (owner answers, 2026-11-11)

1. **Models.** Two new settings: `gemini_fallback_model` (default `gemini-3.8-flash`) replaces every
   Claude model built through `build_llm_client` (extractor, evidence gate, tree summary: my call, they pass
   `model=`); `gemini_fallback_verifier_model` (default `gemini-3.8-flash`) replaces `llm_verifier_model`
   in `build_verifier_llm_client`. If the two are equal the run proceeds, verifier independence is
   relaxed, and the verifier client's switch WARNING (the one record it logs, not a second one) contains
   `verifier independence` (AC-17, AC-18). "Equal" compares the two settings, whatever the extractor
   currently runs on. The defaults are equal, so by default independence is relaxed. The default value is taken from `.github/workflows/golden-set.yml`.
2. **Triggers.** (a) `anthropic_api_key` unset and `gemini_api_key` set: the client is built on Gemini.
   (b) A per-call Anthropic credit or auth error, defined as `anthropic.AuthenticationError` (401),
   `anthropic.PermissionDeniedError` (403), or `anthropic.BadRequestError` (400) whose message contains
   `credit balance` (matched case-insensitively on `str(error)`): that call is retried on Gemini, and the client serves every later call on Gemini too (a
   key or balance does not recover mid-run; "client" = one object returned by the factory). Rate-limit (429),
   overload (529), other 400s and every other error keep today's behaviour. The fallback exists only when
   `gemini_api_key` is set; without it nothing changes. Only `claude-*` models fall back: a `gemini-*` model
   in `llm_model` behaves as today.
3. **Visibility.** `LLMUsage` gets `fallback_from: str = ""`, the Claude model id the call would have used;
   empty when no fallback happened. Provenance already copies `usage.provider` and `usage.model` into each
   value (existing behaviour, not changed and so no row), so a reviewer sees `google` + the Gemini model
   there; the new field is on the usage object, not a new review reason. One WARNING per client when it starts serving on Gemini, logger `arp.llm.fallback_client`.
   It names the Claude model and the Gemini model, never a key.
4. **Batch and cache.** In a batch run (`llm_batch`) a fallback client is the plain unbatched Gemini client
   (as an explicit `gemini-*` model already is): `usage.batch` is `False`. With both keys, the
   `BatchingLLMClient` is the primary inside `FallbackLLMClient`; a credit error from it surfaces from its
   `complete_structured` like any other Anthropic call.
5. **Gemini fails after fallback.** The Gemini error propagates; the original Anthropic error is not re-raised. Cache keys include the model id,
   so Gemini and Anthropic entries never collide; unchanged.

## Design

- `GeminiClient` gets an optional `fallback_from: str = ""` constructor argument; every usage it returns,
  cached hits included, carries it. Cache entries do not store it (usage written to the cache is unchanged).
- New `arp/llm/fallback_client.py`: `FallbackLLMClient(primary, make_gemini)` wraps the Anthropic client,
  catches the credit/auth errors of decision 2, logs the WARNING once, builds the Gemini client lazily and
  serves the call and all later calls from it.
- `factory.py`: for a `claude-*` model: no Anthropic key and a Gemini key → `GeminiClient` on the fallback
  model with `fallback_from=<claude model>` and the WARNING; both keys → the Anthropic client wrapped in
  `FallbackLLMClient`; Anthropic key only → exactly as today; no key at all → the existing `RuntimeError`,
  message unchanged. `build_verifier_llm_client` passes the verifier fallback model.
- `config.py`: the two settings; the `anthropic_api_key or gemini_api_key` validator is untouched.
- `StandInLLMClient` (`settings.standins_dir`) returns before any of this.

## Order of work

The implementation starts only after PR #393 (spec `llm-keep-period-values`, touching `langchain_client.py`
and `gemini_client.py`) merges, to avoid conflicts in the same files.

## Checks

Implementing PR: `risk:normal`. It touches `arp/llm`, so CI runs `arp golden-set run`: that needs the
`ARP_ANTHROPIC_API_KEY` repo secret (without it the check warns and passes), and with
`ARP_GEMINI_API_KEY` set it runs on Gemini. No test calls a real model; tests use fake clients. No key is
logged or printed anywhere.

## Acceptance

Conventions: fake keys `sk-ant-test-key` (Anthropic) and `g-test-key` (Gemini); default settings otherwise
(`llm_model` `claude-sonnet-5-5`, `llm_verifier_model` `claude-opus-5-5`, both fallback models
`gemini-3.8-flash`). "Fake Anthropic" replaces `LangChainAnthropicClient._send`, "fake Gemini" replaces
`GeminiClient._send`; "calls" = requests the fake received. "Credit error" = `anthropic.BadRequestError`
with message `Your credit balance is too low to access the Anthropic API.` "The call" = one
`complete_structured` on the client the factory returns, whose answer is valid. "WARNING record" = level
WARNING on logger `arp.llm.fallback_client`; INFO is ignored.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | no Anthropic key, Gemini key | `build_llm_client(settings)`, then the call | a `GeminiClient`; 1 Gemini call; `usage.provider == "google"`, `usage.model == "gemini-3.8-flash"`, `usage.fallback_from == "claude-sonnet-5-5"` | unit |
| AC-2 | AC-1 with `gemini_fallback_model="gemini-3.8-pro"` | the call | `usage.model == "gemini-3.8-pro"`; `usage.fallback_from == "claude-sonnet-5-5"` | unit |
| AC-3 | AC-1 | `build_llm_client(settings)` is called | exactly 1 WARNING record, containing `claude-sonnet-5-5` and `gemini-3.8-flash` | unit |
| AC-4 | neither key set | `build_llm_client(settings)` | raises `RuntimeError`, message exactly `ARP_ANTHROPIC_API_KEY is not set. Provide an Anthropic API key via environment variable or a .env file before running any agent pipeline.` | unit |
| AC-5 | neither key set; the API app via `TestClient`; an endpoint that builds an LLM client | the request is made | status 503; `detail` is the AC-4 message | unit |
| AC-6 | both keys set | the call | 1 Anthropic call, 0 Gemini calls; `usage.provider == "anthropic"`; `usage.fallback_from == ""`; no WARNING record | unit |
| AC-7 | both keys set | `build_verifier_llm_client(settings)`, then the call | `usage.provider == "anthropic"`, `usage.model == "claude-opus-5-5"`, `usage.fallback_from == ""`; no WARNING record | unit |
| AC-8 | only `anthropic_api_key` set; fake Anthropic raises a credit error | the call | the `BadRequestError` propagates; the factory returned a `LangChainAnthropicClient`; 0 Gemini calls | unit |
| AC-9 | both keys; fake Anthropic raises a credit error on every call | the call | 1 Anthropic call, 1 Gemini call; the answer is the Gemini one; `usage.provider == "google"`, `usage.model == "gemini-3.8-flash"`, `usage.fallback_from == "claude-sonnet-5-5"` | unit |
| AC-10 | AC-9 with `anthropic.AuthenticationError` (401) | the call | same as AC-9 | unit |
| AC-11 | AC-9 with `anthropic.PermissionDeniedError` (403) | the call | same as AC-9 | unit |
| AC-12 | AC-9 with a 400 `BadRequestError` whose message is `Credit Balance too low` | the call | same as AC-9 (case-insensitive match) | unit |
| AC-13 | AC-9 | a second call on the same client | Anthropic calls stay at 1 in total; Gemini calls are 2; the second result has `usage.fallback_from == "claude-sonnet-5-5"` | unit |
| AC-14 | AC-9 | the call | exactly 1 WARNING record, containing `claude-sonnet-5-5` and `gemini-3.8-flash` | unit |
| AC-15 | AC-9 | a second call | the number of WARNING records stays 1 | unit |
| AC-16 | AC-9, and the AC-3 build | both the calls, with log records captured at every level and stdout/stderr captured | none of the captured text contains `sk-ant-test-key` or `g-test-key` | unit |
| AC-17 | AC-9 with the fake Gemini raising `RuntimeError("gemini down")` | the call | raises that `RuntimeError`; 1 Anthropic call, 1 Gemini call | unit |
| AC-18 | both keys; fake Anthropic raises `anthropic.RateLimitError` (429) | the call | the `RateLimitError` propagates; 0 Gemini calls; no WARNING record | unit |
| AC-19 | both keys; fake Anthropic raises `anthropic.InternalServerError` status 529 | the call | that error propagates; 0 Gemini calls; no WARNING record | unit |
| AC-20 | both keys; fake Anthropic raises a `BadRequestError` with message `max_tokens too large` | the call | that error propagates; 0 Gemini calls; no WARNING record | unit |
| AC-21 | no Anthropic key, Gemini key | `build_verifier_llm_client(settings)`, then the call | `usage.model == "gemini-3.8-flash"`; `usage.fallback_from == "claude-opus-5-5"` | unit |
| AC-22 | AC-21 with `gemini_fallback_verifier_model="gemini-3.8-pro"` | the call | `usage.model == "gemini-3.8-pro"`; no WARNING record contains `verifier independence` | unit |
| AC-23 | AC-21 (both fallback models equal) | `build_verifier_llm_client` is called | exactly 1 WARNING record in total, and it contains `verifier independence` | unit |
| AC-24 | both keys; fake Anthropic raises a credit error; both fallback models equal; the verifier client | the call | `usage.model == "gemini-3.8-flash"`; `usage.fallback_from == "claude-opus-5-5"`; exactly 1 WARNING record, containing `verifier independence` | unit |
| AC-25 | AC-24 but the fallback models differ and the extractor client stays on Anthropic | the verifier client falls back | its WARNING record does not contain `verifier independence` | unit |
| AC-26 | `llm_model="gemini-3.8-flash"`, no Anthropic key, Gemini key | `build_llm_client(settings)`, then the call | `usage.fallback_from == ""`; no WARNING record | unit |
| AC-27 | `llm_model="gemini-3.8-flash"`, no Gemini key | `build_llm_client(settings)` | raises `RuntimeError`, message exactly `ARP_GEMINI_API_KEY is not set, and the run uses the Gemini model gemini-3.8-flash.` | unit |
| AC-28 | no Anthropic key, Gemini key, `llm_batch=True` | `build_llm_client(settings)`, then the call | a `GeminiClient` (not a `BatchingLLMClient`); `usage.batch is False`; `usage.fallback_from == "claude-sonnet-5-5"` | unit |
| AC-29 | both keys, `llm_batch=True`; the `BatchingLLMClient`'s `_send` raises a credit error | the call | served by the fake Gemini; `usage.batch is False`; `usage.provider == "google"`; `usage.fallback_from == "claude-sonnet-5-5"` | unit |
| AC-30 | `build_llm_client(settings, model="claude-haiku-5-5")` (evidence gate), no Anthropic key, Gemini key | the call | `usage.model == "gemini-3.8-flash"`; `usage.fallback_from == "claude-haiku-5-5"` | unit |
| AC-31 | `cache_enabled=True`, one shared cache dir; the fake Anthropic answers a call | a fallback `GeminiClient` makes the same call (same system, prompt, schema) | the fake Gemini receives 1 call; `usage.cached is False` | unit |
| AC-32 | AC-1; the same call made twice, `cache_enabled=True` | the second call | 1 Gemini call in total; the second result has `usage.cached is True` and `usage.fallback_from == "claude-sonnet-5-5"` | unit |
| AC-33 | `standins_dir` set, no key | `build_llm_client(settings)`, then the call | no error; a `StandInLLMClient`; the stand-in answer is returned; 0 calls to the fake Anthropic and fake Gemini | unit |
| AC-34 | `Settings()` with defaults | read | `gemini_fallback_model == "gemini-3.8-flash"` | unit |
| AC-35 | `Settings()` with defaults | read | `gemini_fallback_verifier_model == "gemini-3.8-flash"` | unit |
| AC-36 | `LLMUsage()` | read | `fallback_from == ""` | unit |
| AC-37 | a usage dict without `fallback_from` (a stored cache entry) | `LLMUsage.model_validate(d)` | succeeds; `fallback_from == ""` | unit |

Checked by: every row is `unit` with fake clients; no real model call, ever. `HOLDOUT_TOKEN` status is not
known to this spec: until it is set the rows stay `unit` and are listed as owed in the implementing PR. No
row is `evaluator`: the e2e stack never calls a model. The golden-set CI check is only a regression guard.

Must not change: both keys set and no error → Anthropic serves, nothing marked (AC-6, AC-7); Anthropic key
only → no fallback, errors propagate (AC-8); no key → the same `RuntimeError` text and the same 503 (AC-4,
AC-5); rate-limit, overload and other errors are not retried on Gemini (AC-18, AC-19, AC-20); an
explicit `gemini-*` model behaves as today (AC-26, AC-27); stand-ins bypass everything (AC-33); cache
entries of the two providers do not collide (AC-31).

Changes deliberately: a claude model with no Anthropic key but a Gemini key now runs on Gemini instead of
failing (AC-1); by default the verifier then runs on the same model as the extractor, so independence is
relaxed and warned about (AC-23).
