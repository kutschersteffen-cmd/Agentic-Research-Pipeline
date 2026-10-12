# Precision-first extraction for metrics and criteria

Date: 2026-10-12
Status: draft for approval

## Intent

Two kinds of questions get asked of company reports (sustainability reports, annual reports,
filings), and more schemas of both kinds will follow:

1. **Metrics**: a specific number with unit, scale, period and definition. Example: green capex
   (`green_capex_total`, `green_capex_eu_aligned` and siblings in `presets/green.py`; the
   meaning of each existing field stays as defined there).
2. **Criteria**: a yes/no verdict against a written criterion, backed by evidence. Example: the 64
   transition-plan indicators (`transition_plan/data/indicators.json`). This is one criteria set
   among many.

The owner wants production-grade quality end to end. **Precision comes first**: a wrong value or
verdict that goes out unreviewed is the worst outcome, and "needs review" is an acceptable answer.
**Pipeline run time comes second**. A run is 20–100 reports.

Today the repo answers these questions with three separate engines:

- the financials path (`extraction/financials_*`),
- the generic field pipeline (`extraction/pipeline.py` → `field_graph.py`),
- the transition-plan path (`transition_plan/`).

Each has its own precision gaps (see "Audit findings" at the end). This design puts both
kinds of question on **one engine, driven by schemas**: the generic field pipeline, which is
already the strictest of the three and already supports `boolean`/`enum` fields.

## Goals

1. Any `DataPointSchema` preset, metric or criteria, runs through the same engine and gets the
   same precision guarantees. Adding a schema means adding a preset file, never a new pipeline.
2. A value is auto-accepted only when all of the following hold:
   - its quote is grounded in the passages the model was shown;
   - for metrics, the number appears in that quote and passes the numeric, unit, scale and
     period checks;
   - a blind second extraction agrees with it.

   Every other value goes to review.
3. Absence of evidence is an explicit outcome (`not_found`). It is never a silent NA, and never
   a guess.
4. A company-level yes/no (for example "has a decarbonization strategy") is computed by a
   deterministic rule over criterion fields. The rule lives in the schema.
5. Fields within a company run concurrently. A 100-report run gets several times faster than
   today's one-field-at-a-time loop, with the same precision.
6. An eval harness reports **precision of auto-accepted values** and **review rate** per schema
   against hand-checked answers. Reviewer decisions feed that labelled set.

## Non-goals

- Deleting or rewriting the financials path or `transition_plan/`. Both stay in place. They are
  simply no longer the route for these jobs. Retiring them is a separate change.
- New UI. The existing review queue and routes are used as they are.
- Writing the company-level rule for "has a decarbonization strategy". This design provides
  the mechanism; the owner defines the rule content.
- Moving the current consumers of transition-plan runs onto the new preset:
  - `decision/sources.py` `from_transition_plan_run` and the "transition_plan" decision
    template;
  - stewardship's `issuer.score.transition_plan` and `min_plan_score`;
  - `universe_workbench/availability.py`.

  They keep reading old-engine runs. An adapter is a later change.
- Changing what any existing green or EU-taxonomy field means.
- Labelling reports. A person has to do this; the design only makes it fast.
- Swapping the LLM provider or models. The extractor stays on `claude-sonnet-5-5` and the
  verifier on `claude-opus-5-5` (`config.py:18-20`).

## Anti-goals (a failure even if it "works")

- A wrong number or verdict auto-accepted because one fuzzy quote matched somewhere in the
  document.
- An "NA" or "not found" accepted without anything showing the evidence is really absent.
- A separate pipeline per schema creeping back in.
- A run that turns into hours because every field is verified three times in series.

## Design

### 1. Field kinds come from `data_type`; no new concept

- **Metric fields**: `number`, `currency_amount`, `percentage`.
- **Criterion fields**: `boolean`, `enum`.

`FieldDefinition` (`schemas/datapoints.py:100`) already carries everything a criterion needs:

| Criterion part | Where it goes |
|---|---|
| the question | `description` |
| the guideline | `extraction_guidance` |
| retrieval terms | `seed_keywords` |
| preferred sources | `source_doc_types` |

No `kind` attribute is added.

Criterion values map onto the existing `ValueState`:

| Verdict | Stored as | Condition |
|---|---|---|
| YES | `value=True`, `value_state=found` | A supporting quote is required. |
| NO | `value=False`, `value_state=found` | Requires a quote showing the criterion is explicitly not met. |
| NOT DISCLOSED | `value_state=not_found` | Nothing relevant in the report. |

The extractor prompt for boolean fields must say plainly that "no evidence" is `not_found`,
never `False`.

**Owner's decision: three outcomes.**
- Indicator guidelines that say "YES if …, NO otherwise" are read as follows. NO applies
  when the report addresses the topic but doesn't meet the criterion. For example, only
  intensity targets are reported where an absolute target is asked for, so the quote shows
  the intensity target.
- NOT DISCLOSED applies when nothing relevant is found.
- The guideline texts stay unchanged. The boolean prompt adds this rule on top of them.

### 2. The 64 indicators become a preset

Add `presets/transition_plan.py`, built from `transition_plan/data/indicators.json`:

- one boolean field per indicator;
- `seed_keywords` written per indicator, not just the raw question text;
- `high_risk=True`.

The `transition_plan/` module stays as the paper replication. It is no longer the production
route.

### 3. Precision changes in the shared engine

1. **Blind verification for every field in these presets.** Set `high_risk=True` on every
   field in `presets/green.py`, `presets/eu_taxonomy.py` and the new transition-plan preset.
   - `field_graph._verify` calls *either* `blind_verify` or `verify_extraction`, so this
     swaps the verifier mode and adds no LLM call.
   - Any disagreement goes to the adjudicator, which already exists. An unresolved
     disagreement goes to review.
2. **Not-found needs agreement.**
   - **Keyword miss.** For a high-risk field, a keyword miss no longer short-circuits to
     `_finalize_no_evidence`. Retrieval falls back to the top reranked passages over all
     chunks (`fallback_to_all=True`), so the extractor and the blind verifier both run.
   - **Auto-accept rule.** A `not_found` on a high-risk field is auto-accepted only when both
     passes return `not_found`. Otherwise it goes to review.
   - **Routing change.** `routing.py:46` currently sends every high-risk `not_found` to
     review. Change it to accept a not-found both passes agree on. Without this the
     64-indicator preset floods the review queue.
   - Non-high-risk fields keep today's short-circuit.
3. **Strict digits in grounding.** In `grounding.py`'s fuzzy path (`grounding.py:141-148`),
   a quote only matches if its digit sequence equals the digit sequence of the matched source
   text. This blocks "one changed digit in a long quote" matches. Exact matches are
   unaffected.
4. **Green-capex "subtract gas/nuclear" guidance stays as it is.**
   - `presets/green.py:88-90` asks for a computed figure, which conflicts with the extractor's
     no-computing rule.
   - A subtracted value fails the in-span check and goes to review. That is safe, and rare
     (it only happens when gas/nuclear is quantified).
   - Changing it would change what `green_capex_total` means for `green_summary`, so it is
     left alone.
5. **A reranker after hybrid retrieval.** In `select_relevant_chunks`:
   - take the top 40 fused (RRF) candidates;
   - rerank them with a local multilingual cross-encoder;
   - keep the top N.

   Retrieval stays free, offline and deterministic, matching the existing embedding choice
   (`retrieval/embeddings.py`). It is controlled by a setting, on by default. If no
   cross-encoder is available offline, it falls back to the RRF order and logs once.
6. **Evidence per field.** Raise the default from 10 to a value the eval harness justifies.
   The starting point is 12 reranked passages, and each table passage is kept whole.
7. **Show the table's unit note.** Add `unit_note` to the evidence header
   (`extractor_agent.py:37-45`), so "in € millions" captions reach the model.

### 4. Company-level rule (derived criterion)

Add an optional `derived_rule` to `FieldDefinition` for a boolean field that is computed, not
extracted:

```
{"all_of": [field_ids], "any_of": [field_ids], "min_true": n}
```

- Every part present must hold: `all_of` all True, `any_of` at least one True, at least
  `min_true` True across all listed inputs.
- It is evaluated after extraction, with no LLM call.
- Logic is three-valued:
  - The result is `False` as soon as one part is already decided false (an `all_of` input
    is False).
  - The result is `True` only when every part is satisfied by True inputs.
  - Otherwise the result is `not_found`. A `not_found` input never counts as False.
- It is routed to review if any input field it depends on is in review.
- Its citations are the union of its inputs' citations.
- It is recomputed on the next run, not when a reviewer corrects an input. Live recompute
  in the review flow is out of scope.

### 5. Run time

1. **Fields within a company run concurrently**, not in the serial loop at
   `extraction/pipeline.py:197`.
2. **One shared semaphore caps in-flight LLM calls across the whole run**, sized by
   `max_concurrent_llm_calls`. The current per-company semaphore (`batch_runner.py:94`) is
   replaced or nested so the real cap is on LLM calls.
3. **The history reuse check** (`pipeline.py:198-215`) stays per field and runs before
   scheduling.
4. **The target** is a 100-report run of one preset within about an hour. That figure is
   bounded by API rate limits and must be measured, not assumed.

### 6. Eval harness

Extend `golden_set/` so a case can be a real document plus a list of
`{field_id, expected value or value_state}`.

The runner calls the full `extract_company` path, including checks and routing, and reports
per schema:

- **precision of auto-accepted values** (the headline metric);
- **review rate**;
- **coverage** (auto-accepted / all);
- **wrong-but-auto-accepted cases**, each listed in full.

**Labels.** They come from **trial runs**. `routing.route(trial=True)` already sends every row
to review, auto-accept candidates included, so each value gets a human decision.
- A small export command turns those decisions in `review_decisions.jsonl` into golden cases.
- The first set is 20–30 reports labelled this way.
- When a reviewer confirms a `not_found`, that's a confirmation that the reviewer looked for it.

**Gates.** The harness computes each row's route as if its field were released and audited,
ignoring `unreleased_version` and `first_audit_pending`. Otherwise new presets would measure
0% auto-accept. In production, the presets go through the existing release and first-audit
flow unchanged.

## Decided by the owner

- One engine for both kinds; schemas define the questions.
- Criteria have three outcomes: YES / NO (topic addressed, criterion not met) / NOT DISCLOSED.
- Precision over coverage; "needs review" is acceptable.
- Run time matters secondarily. Runs are 20–100 reports.
- The 64 indicators and green capex are examples; other schemas of both kinds will follow.

## My calls (owner can override)

- The generic field pipeline is the engine. The financials and transition-plan paths are left
  in place, unused for these jobs.
- Blind verification on all fields of these presets.
- A not-found both passes agree on is auto-accepted. High-risk keyword misses still get both
  LLM passes.
- `derived_rule` uses three-valued logic and recomputes per run only.
- Golden labels come from trial runs. The harness ignores release and audit gates.
- Existing transition-plan consumers stay on the old engine.
- The green "subtract gas/nuclear" guidance stays; it routes to review.
- Local cross-encoder reranker, top 40 candidates reranked to 12.
- Target auto-accept precision is **≥ 97%** on the golden set. Below that, tighten routing
  before adding anything else.

## Left to the builder

- Which cross-encoder model. It must be multilingual (EN/DE), run offline via the installed
  `fastembed` (`pyproject.toml:32`), and be small enough for CPU. Check the installed version
  supports `TextCrossEncoder`.
- Whether the embedding model truncates 3500-character chunks. If it does, decide between
  embedding a chunk's first N tokens (today's behaviour) and smaller chunks for embedding only.
  Measure it on the harness; don't guess.
- Concurrency primitive and where the LLM-call semaphore lives (LLM client vs. batch runner).
- Seed keywords per indicator for the transition-plan preset.

## Audit findings this design answers

| Finding | Where | Addressed by |
|---|---|---|
| Financials path never checks the number against its quote | `spend_aggregator.py:94-102` | §1 (use generic engine) |
| Fuzzy grounding accepts a changed digit | `grounding.py:141-148` | §3.3 |
| Green/taxonomy fields never blind-verified | `green.py:60-65`, `eu_taxonomy.py:27-33` | §3.1 |
| Green-capex guidance asks the model to compute | `green.py:88-90` | §3.4 (kept; routes to review) |
| No reranker; top-k 10; small embedder | `select_evidence.py` | §3.5, §3.6 |
| Transition-plan NA auto-accepted unreviewed | `transition_plan/aggregator.py:39-40` | §1, §2 (not_found semantics) |
| Transition-plan retrieval always returns 8 passages | `transition_plan/indicator_graph.py:67-68` | §2 (generic engine uses `require_hit=True`) |
| One quote anywhere in the document grounds a verdict | `transition_plan/aggregator.py:31,37` | §2 (generic aggregator grounds against shown passages) |
| No company-level yes/no rule | `transition_plan/company_assessment.py` | §4 |
| Fields and indicators run in series | `pipeline.py:197`, `company_assessment.py:100` | §5 |
| No precision measurement | `golden_set/runner.py` | §6 |
