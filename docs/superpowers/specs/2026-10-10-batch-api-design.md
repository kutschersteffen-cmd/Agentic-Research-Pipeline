# Batch API for background pipeline runs: design

Status: approved in brainstorming on 2026-10-10. Next step: implementation plan.

## Goal

Cut the LLM cost of unattended pipeline runs by about 50% using Anthropic's Message Batches API, without changing what any pipeline produces. Interactive screens (drafting, smart search, portfolio Q&A, schema drafting, BI planner, reporting) stay real-time.

Success:
- A run started in batch mode produces the same records as the same run in real-time mode.
- Its estimated cost is half, shown on the run.
- While it waits on a batch, the run says so; it never looks stuck.
- A crash mid-run resumes without paying for already-submitted requests twice.

## Decisions taken

- **Who chooses batch mode:** manual runs get a "Batch (50% cheaper, slower)" switch, off by default; scheduled runs use batch by default for the run types listed in a setting.
- **Approach:** one batching LLM client that the pipelines do not notice, rather than rewriting each pipeline into explicit submit/wait stages.
- **Rollout:** available to every pipeline that takes `llm` from the factory; switched on by default only where it pays (below).

## Architecture

### `BatchingLLMClient` (new file `arp/llm/batching_client.py`)

- `LangChainAnthropicClient.complete_structured` keeps its disk cache, validation-retry loop, prompt caching and usage accounting, but its one API call moves into `async def _send(self, params: dict) -> Message`. The real-time client's `_send` calls `messages.create(**params)` exactly as today.
- `BatchingLLMClient(LangChainAnthropicClient)` overrides only `_send`. It enqueues `(custom_id, params, future)` and awaits the future.
  - `custom_id` is a hash of the canonical JSON of `params` (truncated to the API's 64-character limit).
- **Flush rule:** the queue is submitted as one Message Batch when no new call has arrived for 2 seconds, or when it reaches 10,000 requests, whichever comes first.
- **Polling:** a background task calls `messages.batches.retrieve(id)` every 30 seconds until `processing_status == "ended"`. It then streams `messages.batches.results(id)` and resolves each future by `custom_id`. Results arrive in any order, so they are never matched by position.
- **Rounds:** the chained steps (extract → verify → adjudicate) create the rounds on their own. All companies wait on round 1, then their next calls fill round 2. Validation retries join whichever round is next.

### Restart safety

- Each submitted batch is appended to one log, `<cache_dir>/llm_batches.jsonl`, as `{batch_id, custom_ids, submitted_at, run_id}` (`run_id` is null for a call made outside a run).
- On its first call (including after `resume_run`), the client reads the rows whose `run_id` equals its own run's (null rows only when it runs outside a run). A re-issued request whose `custom_id` is in one of those rows reattaches to that batch instead of being resubmitted: an ended batch answers from its results, one still in progress is waited on.
- A run never reattaches to, waits on, or cancels a batch another run submitted, even for identical requests.

### Enabling batch mode

- `RunManifest.params["batch"]: bool` records the choice per run.
- **Manual runs:**
  - API: run-creation requests for the supported run types accept `batch: bool`, default false.
  - CLI: run commands accept `--batch`.
  - UI: the start screens show a "Batch (50% cheaper, slower)" switch.
- **Scheduled runs:** a new setting, `batch_scheduled_run_types: list[str]`, defaults to `[]`: scheduled batch is opt-in by config. Only emerging_themes is wired to it, and it is a poor batch candidate (it runs outside `run_company_batch`, and its serial synthesis/role stages would become batches of one), so it is left off by default.
  - No extraction-family run is scheduled today; their savings come through the per-run switch.
  - The taxonomy researcher is excluded: it runs one item at a time (`concurrency=1`), so every batch would hold a single request.
- **Factory:** `build_llm_client` / `build_verifier_llm_client` take `run_id` and `batch`. In batch mode they return a `BatchingLLMClient` bound to that run's directory.
- **Concurrency:** in batch mode, pipelines use a new setting, `batch_concurrency` (default 1,000), in place of `max_concurrent_llm_calls` (8). That way each round gathers enough calls to be worth a batch.
- **Supported run types:** the ones whose pipelines take `llm` from the factory and run companies concurrently through `run_batch` / `run_company_batch`:
  - extraction, financials, tnfd, transition_plan
  - theme/research, identity, voting, replication
  - Not emerging_themes: it runs outside `run_company_batch`, so it has no per-run switch (see Scheduled runs).

## Cost and visibility

- `LLMUsage` gets `batch: bool`. `estimate_cost_usd` multiplies every token category by 0.5 when it is set. The batch discount stacks with prompt-cache pricing.
- `RunManifest` gets:
  - `batch_saved_usd`: the real-time cost of the same tokens minus the batch cost.
  - `batch_wait`: `{batch_id, request_count, submitted_at, status}` while a batch is open, `null` otherwise.
- `RunProgress` shows the wait, e.g. "Waiting on batch round 2 · 38,412 requests · submitted 14:02 · Anthropic usually finishes within an hour".
- Run History marks batch runs with a "batch" label next to the run type.

## Failure handling

| Case | Behaviour |
|---|---|
| One request `errored` or `expired` | Its future raises. That company fails through `run_batch`'s existing error isolation, and `resume_run` retries it. |
| Batch submission fails (network, 4xx) | Every future in that flush raises. The run fails cleanly, and resume resubmits. |
| Run cancelled | The client calls `messages.batches.cancel` on its open batches. Requests that already finished are still billed, as the API does. |
| 24-hour expiry | Same as `expired`: those companies count as failed, and resume resubmits them. |
| `stop_reason: refusal` | Same as real time; the result shape is identical. |

Out of scope:
- falling back to real time when a batch is slow;
- mixing real-time and batch calls inside one run;
- batching interactive routes.

## Testing

All tests use a fake batches API; none make real API calls.
- **Flush:** idle-timeout flush, and the 10,000-request cap.
- **Results:** out-of-order results reach the right future; an errored or expired request fails only its own caller.
- **Restart:** a restarted client reuses a submitted batch from `batches.jsonl` and submits nothing new.
- **Cancel:** cancelling the run cancels its open batches.
- **Cost:** `estimate_cost_usd` with `batch=True` gives half the cost. `batch_saved_usd` and `batch_wait` are written to the manifest.
- **End to end:** one existing pipeline test (financials or transition_plan) runs in batch mode against the fake. It must give the same records as real-time mode at half the estimated cost.

## Rollout

1. Merge. Nothing changes until someone ticks the switch or adds a run type to `batch_scheduled_run_types` (empty by default).
2. One real trial: an extraction of about 20 companies with `--batch`. It spends real API money, so it runs only with the user's approval. It checks the rounds, the cost and the progress display against the live API.
3. Use the switch for large manual runs. Add run types to `batch_scheduled_run_types` once those pipelines are scheduled.
