# Evidence gate (drop passages that cannot answer the field)

Status: draft, awaiting owner approval. Risk: high (changes the evidence the extractor sees).

## Goal

Cut the extractor's input for each field by dropping retrieved passages that cannot help answer it, without losing
answers. Today every field sends up to `evidence_max_chunks` (12) passages to the extractor
(`extraction/field_graph.py` `field_evidence`); the Walkthrough's retrieval scores (PR #288) show many are near-misses
of keyword matching that say nothing about the field.

Idea taken from RAGFlow's decision gate (`internal/agentic_rag/decision_judge.go`, `decision_breaker.go`): a cheap
judge answers "can this passage help answer the question?" per passage. Two of its rules are copied exactly:
a failed judgement keeps the passage, and after repeated failures a breaker switches the gate off.

## Design

1. **Off by default.** Settings: `evidence_gate_enabled: bool = False`, `evidence_gate_model: str =
   "claude-haiku-5-5"`, `evidence_gate_min_keep: int = 3`, `evidence_gate_breaker: int = 3`, `evidence_gate_timeout_s: float = 20`.
   `evidence_gate_enabled` and `evidence_gate_model` join `input_settings` so a changed gate re-extracts instead of
   reusing old values.
2. **Where.** In `_gather_evidence`, after `field_evidence` and before extraction, for ungrouped fields only. Skipped
   for `high_risk` fields (blind-verified fields keep all evidence), for fields with `min_keep` passages or fewer, and
   for the `unranked` fallback.
3. **One call per field.** `evidence_gate_model` gets the field's name, description and extraction instructions and
   the passages numbered `[1]..[n]` in rank order, and returns `{"keep": [ints], "reason": str}` (structured output,
   prompt in `extraction/evidence_gate.py`). Kept: the passages it names, plus the top `min_keep` by rank whatever it
   says, in their original rank order. Ids outside `1..n` are ignored.
4. **Fail open.** Each of these is a failure and keeps every passage: an exception, no answer within
   `evidence_gate_timeout_s`, output that does not fit the schema, and a `keep` with no id inside `1..n` (empty or
   only out-of-range). A run-wide counter of consecutive failures (reset on a success) switches the gate off for the
   rest of the run once it reaches `evidence_gate_breaker`; exactly one WARNING is logged then, with the text
   `evidence gate breaker open: gate off for the rest of run {run_id}`.
5. **Cost and trace.** The gate call's usage joins the field's usages (run cost) and the walkthrough trace as a
   `gate` call (model, answer, `input_tokens`, `output_tokens`, `cost_usd`). The trace's `retrieval` gains
   `gate: {"kept": k, "of": n, "failed": bool, "skipped": reason | null}` (`skipped` is one of `"high risk"`,
   `"too few passages"`, `"grouped"`, `"unranked"`, `"breaker open"`; when skipped no call is made, `failed` is
   false and `kept == of`). Dropped passages are recorded in the near-miss shape under `gate_dropped`, in rank order.
   The Walkthrough's Find evidence step shows one gate line, checked in this order: skipped → `Gate: off ({reason})`;
   failed → `Gate: failed, kept all {n}`; else `Gate: kept {k} of {n}`; and a collapsed `Dropped by the gate (m)`
   list when m > 0.
6. **Proof before use.** `arp golden-set run --gate on|off` runs the golden set with the gate forced on or off and
   prints one `{case_id}: pass` or `{case_id}: fail` line per case and a last line `extractor input tokens: {int}`, and exits 1 if any case fails. The gate stays off by default; the owner turns it
   on per deployment once the comparison is good.

## Out of scope

Grouped fields, a local distilled judge model, per-passage scores from the judge, tuning `min_keep` automatically,
turning the gate on by default, other pipelines (TNFD, financials, research).

## Acceptance

Fixtures: **F** = an ungrouped, not high-risk field with 10 retrieved passages, `min_keep=3`, and a stub gate LLM
whose usage is 1000 in / 50 out on `claude-haiku-5-5`. **GOLD** = the repo's golden set with the real models in CI
(`ARP_ANTHROPIC_API_KEY`). **GRUN** = the e2e stack (`backend/scripts/e2e_stack.sh up`) started with
`ARP_EVIDENCE_GATE_ENABLED=true` and `ARP_ANTHROPIC_API_KEY` set, then `arp extract run` on a one-company universe
with one uploaded document; without the key AC-25/26 are reported as blocked.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Default settings, F | Field extracted | No gate call is made and the extractor gets the same 10 passages in the same order as with the gate code absent | unit |
| AC-2 | Gate on, F, stub returns `keep: [2, 5, 9]` | Field extracted | Extractor gets passages ranked 1, 2, 3, 5, 9, in that order | unit |
| AC-3 | Gate on, F, stub returns `keep: [0, 11, 4]` | Field extracted | Extractor gets passages ranked 1, 2, 3, 4 | unit |
| AC-4 | Gate on, F, stub returns `keep: [0, 11]` | Field extracted | Extractor gets all 10 passages | unit |
| AC-5 | Gate on, F, stub raises | Field extracted | Extractor gets all 10 passages | unit |
| AC-6 | Gate on, F, stub returns `keep: []` | Field extracted | Extractor gets all 10 passages | unit |
| AC-7 | Gate on, F, stub returns `{"keep": "x"}` | Field extracted | Extractor gets all 10 passages | unit |
| AC-8 | Gate on, F, `evidence_gate_timeout_s=0.05`, stub sleeps 1 s | Field extracted | Extractor gets all 10 passages | unit |
| AC-9 | Any of AC-4 to AC-8 | Trace written | `retrieval.gate == {"kept": 10, "of": 10, "failed": true, "skipped": null}` | unit |
| AC-10 | Gate on, breaker 3, a run of 5 fields whose stub raises every time | Run completes | The stub is called exactly 3 times | unit |
| AC-11 | As AC-10 | Run completes | Fields 4 and 5 trace `gate.skipped == "breaker open"` | unit |
| AC-12 | As AC-10 | Run completes | Exactly 1 WARNING log record containing `evidence gate breaker open` | unit |
| AC-13 | As AC-10 but the 2nd call succeeds | Run completes | The stub is called 5 times | unit |
| AC-14 | Gate on, a `high_risk` field | Field extracted | No gate call; `gate.skipped == "high risk"` | unit |
| AC-15 | Gate on, a field with 3 passages | Field extracted | No gate call; `gate.skipped == "too few passages"` | unit |
| AC-16 | Gate on, a grouped field | Field extracted | No gate call; `gate.skipped == "grouped"` | unit |
| AC-17 | Gate on, unranked fallback | Field extracted | No gate call; `gate.skipped == "unranked"` | unit |
| AC-18 | AC-2 setup | Gate called | The prompt contains the field's name, description and extraction instructions, and `[1]` … `[10]` followed by the passages' text in rank order | unit |
| AC-19 | AC-2 setup | Trace written | `retrieval.gate == {"kept": 5, "of": 10, "failed": false, "skipped": null}` | unit |
| AC-20 | AC-2 setup | Trace written | `gate_dropped` is exactly the passages ranked 4, 6, 7, 8, 10, each with the keys and score values its near-miss entry would have | unit |
| AC-21 | AC-2 setup | Trace written | A `gate` call with `model == "claude-haiku-5-5"`, `input_tokens == 1000`, `output_tokens == 50`, `cost_usd == round(estimate_cost_usd("claude-haiku-5-5", usage), 6)` | unit |
| AC-22 | AC-2 setup in a run | Run completes | The run's recorded cost equals the same run without the gate plus the gate call's `cost_usd` | unit |
| AC-23 | Two runs differing only in `evidence_gate_enabled` | Second run | The field makes 1 extractor call (0 when settings are identical: reused) | unit |
| AC-24 | Two runs differing only in `evidence_gate_model` | Second run | The field makes 1 extractor call | unit |
| AC-25 | GRUN | Reviewer opens a field's Walkthrough, Find evidence | The gate line equals the AC-27 to AC-29 text for the API's `retrieval.gate` | evaluator |
| AC-26 | GRUN, a field with `gate_dropped` non-empty | Same | `Dropped by the gate (m)` is shown collapsed, m = API `gate_dropped` length | evaluator |
| AC-27 | Frontend helper, gate `{kept: 5, of: 10, failed: false, skipped: null}` | Gate line built | `Gate: kept 5 of 10` | unit |
| AC-28 | Frontend helper, gate `{kept: 10, of: 10, failed: false, skipped: "high risk"}` | Gate line built | `Gate: off (high risk)` | unit |
| AC-29 | Frontend helper, gate `{kept: 10, of: 10, failed: true, skipped: null}` | Gate line built | `Gate: failed, kept all 10` | unit |
| AC-30 | Frontend helper, no `gate` in retrieval | Gate line built | null | unit |
| AC-31 | GOLD | `arp golden-set run --gate off` | Exits 0 | golden |
| AC-32 | GOLD | `arp golden-set run --gate on` | Exits 0 | golden |
| ~~AC-33~~ | ~~GOLD, both runs~~ | ~~CI step compares the last lines~~ | ~~`extractor input tokens` with `--gate on` is at least 10% below `--gate off`; the step exits 1 otherwise~~ Retired 2026-11-02 (owner): the golden cases yield 3 passages or fewer, so the gate never filters them (16,595 vs 16,601 tokens). CI keeps AC-31/32 and prints both totals. | golden |
| AC-34 | A 2-case golden set with a stub model, case `c1` passes and `c2` fails | `arp golden-set run --gate on` | Prints `c1: pass`, `c2: fail`, then `extractor input tokens: {int}` as the last line, and exits 1 | unit |
| AC-35 | Existing backend and frontend suites | CI | All existing tests pass unchanged, except exact-key trace assertions extended for `gate`/`gate_dropped` (listed in the PR) | unit |

Must not change: behaviour with default settings (AC-1, AC-31, AC-35), blind-verified fields (AC-14).
