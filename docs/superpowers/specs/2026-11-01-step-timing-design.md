# Step timing (time, tokens and cost per Walkthrough step)

Status: draft, awaiting owner approval.

## Goal

Show where a field's time and money go. The Argus Walkthrough already lists a data-point field's steps with what
each found (`frontend/src/lib/walkthrough.ts` `steps()`), and `orchestration/step_tally.run_graph` already times
every graph node, but only summed per run and per company (`step_counts.json`). Missing per field: how long each
step took and what each model call used.

Idea taken from RAGFlow's agent log (`web/src/pages/agent/log-sheet/workflow-timeline.tsx`), which lists each step
with its elapsed time. Improved on: RAGFlow hides tokens and cost until a row is expanded; here they are on the line.

## Design

1. **Record time per node.** `run_graph` times each node of a field's graph in the trace when the state carries a
   walkthrough sink (`state["seen"]` is a dict), whether or not a run tally is open, and stores
   `seen["seconds"][node]` (seconds, summed if a node runs twice). The run tally is fed exactly as today.
2. **Record usage per call.** `trace.call` and `trace.verifier_call` add `input_tokens`, `output_tokens` and
   `cost_usd` (`estimate_cost_usd(model, usage)`, 6 dp) when a usage is given. `trace.field_entry` adds `seconds`
   (node → seconds, 2 dp), `{}` when not recorded.
3. **API.** `build_walkthrough` passes `seconds` through (`{}` for old traces); calls already pass through whole.
4. **UI.** For data-point fields (not Financials/TNFD, not plan rows):
   - each step that maps to a graph node shows, after its label, ` · {time}`: `Tagged data first` → `try_tagged`,
     `Find evidence` → `gather_evidence`, `Extract` → `extract`, `Verify` / `Verify, blind` → `verify`,
     `Adjudicate` → `adjudicate`, `Ground every quote` → `aggregate` (grounding runs there). Time format:
     `< 0.01 s` under 0.01, else `{s, 2 dp} s` under 10, else `{s, 1 dp} s`. Steps without a node (corrections,
     checks, route, combine) show no time.
   - each model step with recorded usage also shows ` · {in} → {out} tokens · ${cost}` (thousands separators;
     cost with 4 dp; a cost that rounds to `$0.0000` shows as `cached`) when `input_tokens` is present and above 0.
   - one mono line under the step list header: `{total time} · {total tokens} tokens · ${total cost}` over the
     recorded nodes and calls; absent when `seconds` is `{}`.
   - old traces: no time, token or total parts (no extra note).
5. **Seeded known-answer items** (owner decision during implementation): they must look like real items, so a
   seeded item borrows the step seconds and token counts of a real data-point field from the latest 10 non-trial
   extraction runs (`review/quality.py` `_recent_timings`), or typical values when none exist; its
   `gather_evidence` time is measured for real. Cost follows from the borrowed tokens.
   Signal Room rules: mono, ink, tabular figures; no colour for slow or costly steps.

## Out of scope

Financials/TNFD/plan walkthroughs, Run History changes, timing outside the field graph, alerts on slow steps, live
updates while a run is going.

## Acceptance

Fixtures: **DOCS** = the fixture document and stub LLM of `tests/test_walkthrough_field_graph.py`, with stub usages
`input_tokens=1200, output_tokens=80, model="claude-sonnet-5-5"` for every call; DOCS's field agrees, so it is not
adjudicated. **RUN** = an extraction run started against the e2e stack with `ARP_ANTHROPIC_API_KEY` set:
`arp extract run --schema <any installed preset schema> --universe <a one-company universe with one uploaded
document>`, then the Walkthrough of one of its data-point rows. Seeded known-answer items are built without the graph
and carry no timing, so they cannot serve. If the key is unset, AC-20 to AC-24 are reported as blocked, not passed.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | DOCS, one field, trace sink, no run tally | Field extracted | Trace entry `seconds` keys are exactly `try_tagged`, `gather_evidence`, `extract`, `verify`, `aggregate`; each value a float ≥ 0 with at most 2 dp | unit |
| AC-2 | As AC-1 inside an open run tally | Field extracted | The tally's per-company node counts equal those of the same call made with `state["seen"]` None | unit |
| AC-3 | As AC-1 | Trace entry written | `extractor.input_tokens == 1200` and `extractor.output_tokens == 80` | unit |
| AC-4 | As AC-1 | Trace entry written | `extractor.cost_usd == round(estimate_cost_usd("claude-sonnet-5-5", usage), 6)` | unit |
| AC-5 | As AC-1 | Trace entry written | `verifier.input_tokens == 1200`, `verifier.output_tokens == 80`, `verifier.cost_usd` as in AC-4 | unit |
| AC-6 | No trace sink | Field extracted | Extracted values equal those of the same call with a sink | unit |
| AC-7 | Trace written by new code | `GET` walkthrough | Response `seconds` equals the trace's `seconds` | unit |
| AC-8 | Trace written before this change | `GET` walkthrough | Response `seconds == {}` | unit |
| AC-9 | Frontend helper, seconds 0.004 / 1.234 / 12.34 | Time is formatted | `< 0.01 s` / `1.23 s` / `12.3 s` | unit |
| AC-10 | Frontend helper, call with 3410 in, 212 out, cost 0.01234 | Usage is formatted | `3,410 → 212 tokens · $0.0123` | unit |
| AC-11 | Frontend helper, calls with cost 0 and cost 0.00004 | Usage is formatted | Both end with `· cached` | unit |
| AC-12 | Frontend helper, walkthrough with seconds `{extract: 1.5, verify: 0.5}` and two calls of 1000+100 tokens, $0.01 each | Total is built | `2.00 s · 2,200 tokens · $0.0200` | unit |
| AC-13 | Frontend helper, walkthrough with `seconds == {}` | Total is built | null | unit |
| AC-14 | Frontend helper, step `Find evidence`, seconds `{gather_evidence: 0.2}` | Step time is looked up | `0.20 s` | unit |
| AC-15 | Frontend helper, every step label | Node is looked up | `Tagged data first`→`try_tagged`, `Find evidence`→`gather_evidence`, `Extract`→`extract`, `Verify`/`Verify, blind`→`verify`, `Adjudicate`→`adjudicate`, `Ground every quote`→`aggregate`; `Auto-corrections`, `Checks`, `Route`, `Combine into one record` → null | unit |
| AC-16 | Frontend helper, a call without `input_tokens`, and one with `input_tokens == 0` | Usage is formatted | null for both | unit |
| AC-17 | Frontend helper, an old walkthrough (`seconds == {}`, calls without usage) | Step suffixes are built for every step | All empty | unit |
| AC-18 | Frontend helper, a `financials` walkthrough with `seconds` set | Step suffixes and total are built | All empty and total null | unit |
| AC-19 | Two runs of the same node, 0.3 s and 0.4 s (stub clock) | Node seconds recorded | `seen["seconds"][node] == pytest.approx(0.7)` and the trace entry's `seconds[node] == 0.7` | unit |
| AC-20 | RUN, a recorded data-point field | Reviewer opens its Walkthrough | The Find evidence line ends with ` · ` + the AC-9 format of the API's `gather_evidence` | evaluator |
| AC-21 | As AC-20 | Same | A total line appears directly under the step list header | evaluator |
| AC-22 | As AC-20 | Same | The total line's time text equals the AC-9 format of the sum of the API's raw `seconds` values | evaluator |
| AC-23 | As AC-20, Graphite and Night | Same | Time and token text ≥ 13px and ≥ 4.5:1 contrast | evaluator |
| AC-24 | As AC-20 | Same | Time and token text is not the signal colour (`--hi`) and has `font-variant-numeric: tabular-nums` | evaluator |
| AC-25 | Existing backend and frontend suites | CI | All existing tests pass unchanged, except exact-key assertions on trace entries extended for `seconds` and the call keys (listed in the PR) | unit |

Must not change: extracted values (AC-6), the run tally (AC-2), old traces (AC-8, AC-17), Financials/TNFD
walkthroughs (AC-18).
