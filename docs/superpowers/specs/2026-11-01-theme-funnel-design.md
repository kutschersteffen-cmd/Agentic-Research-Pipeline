# Theme funnel in front of the Universe Builder (action plan A2)

Spec slug: `theme-funnel`. Parent: `2026-11-01-model-stack-design.md` (approved). Needs `arp/models/` (A1).

Status: approved by the owner, 2026-11-01.

## Why

The Thematic Universe Builder (`arp/research/pipeline.py`, `match_graph.py`) runs the Advocate / Opposing /
Adjudicator debate for every company × activity pair that has evidence. For a 4,000-company universe most
pairs are clear non-matches, so most LLM calls are spent confirming "no". The electrolyser test
(`docs/golden_drafts/electrolyser_funnel_results.md`) showed that three cheap models in a row (embeddings,
cross-encoder, zero-shot NLI with contrast statements) separate makers from non-makers on full annual reports:
core 7/7 and peripheral 5/6 kept, 11/13 non-makers dropped, without an LLM call.

## Goals

1. Before the debate, score each company × activity pair with the funnel and skip the debate for pairs the
   funnel screens out.
2. Use the activity's own definition: `in_scope_description` is the positive statement, `out_of_scope_description`
   plus optional contrast statements are the negatives.
3. Keep the screened-out pairs visible with their scores and best passage, so a person can see why.
4. A CLI that runs only the funnel over a golden set and prints recall per label.

## Non-goals

- Changing the debate, revenue resolver, R&D resolver, indirect-exposure tier or ranking.
- Revenue sizing (B1).
- New document sources; the funnel reads the documents the run already fetches.
- Any UI change beyond what the existing run view shows for an `exclude` verdict.

## Anti-goals

- A pair dropped by the funnel without a stored reason (scores and best passage).
- Thresholds hard-coded in Python.

## Design

### Settings

`ARP_MODELS_UNIVERSE_FUNNEL_ENABLED` (default `false`). When false, nothing in this spec runs.

### Activity schema

`ActivityDefinition` gains one optional field: `contrast_statements: list[str] = []` (for example "The company
buys or operates electrolysers made by another company", "The company supplies components or catalysts for
electrolysers that others build"). Existing taxonomies load unchanged.

### Funnel per company × activity (`arp/research/funnel.py`)

| Step | What | Model (via `arp/models/`) | Kept |
|---|---|---|---|
| 1 | Passages: the run's chunks for the company (`chunk_document`), no keyword filter | – | all |
| 2 | Cosine similarity of each passage to `in_scope_description` | `embed` | top `k1` (default 25) |
| 3 | Fit score of `(in_scope_description, passage)` | `rerank` | top `k2` (default 6) |
| 4 | Entailment of the positive statement and of each negative statement on each of the `k2` passages | `classify` (NLI) | – |
| 5 | **Pass** if best rerank score ≥ `t_rerank` **and** some passage has positive entailment ≥ `t_entail` **and** on that passage the positive is strictly greater than every negative (a tie fails) | – | – |

Negatives = `out_of_scope_description` + `contrast_statements`. Thresholds `k1`, `k2`, `t_rerank` (default 1.5),
`t_entail` (default 0.8) live in `arp/research/data/funnel_thresholds.json`, one entry per theme id with a
`default` entry.

### Integration

In `_match_company`, after documents are fetched and before `match_company_activity`:

- **pass** → the pair goes to the debate as today.
- **screened out** → no LLM call for that pair; the pair gets `MatchVerdict.EXCLUDE` with
  `rationale = "screened out by funnel"` and a `funnel` record:
  `{passed, rerank_max, entail_positive, entail_negatives: {statement: score}, best_passage, best_doc_id, passages_scored, thresholds, models}`
  (models = the provenance from `arp/models/`). `best_passage` is the passage that satisfied step 5; for a
  screened-out pair, the passage with the highest positive entailment. `entail_positive` and `entail_negatives`
  are the scores on `best_passage`.
- No documents → unchanged (`finalize_no_evidence`).

The `funnel` record is stored on `CompanyMatch` (new optional field) and appears in the run JSON for both pass
and screened-out pairs.

### CLI

`arp theme funnel --theme <theme.json> --cases <golden cases.json> --documents-dir <dir> [--out <json>]`:
runs only the funnel (no LLM), prints one line per company (label, scores, pass/screened), then one line per
label in the form `<label>: <kept>/<total>`. Options: `--split tune|holdout|all` (default `all`),
`--min-kept-positive <x>` (exit 1 if core + peripheral kept / total < x), `--max-kept-negative <x>` (exit 1 if
`not` kept / total > x). Golden-set format comes from A3.

`arp theme funnel-compare --theme … --cases … --documents-dir … [--split …] [--max-call-ratio x]
[--max-precision-drop x]`: runs the full theme run on the golden companies twice (setting off, setting on),
prints LLM call counts and the precision of `include` verdicts against the golden labels (core and peripheral
count as positive) for both, and exits 1 if a given limit is broken.

## Left to the builder

Batching across companies; how chunks map to passages if a chunk exceeds the cross-encoder's 512-token limit
(truncation is acceptable).

## Acceptance

`unit` rows use stand-in models for `embed`, `rerank` and `classify` (fixed scores per passage) and a stand-in LLM
that counts calls. Company names A–H refer to fixture companies with one activity each.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Fixture theme, 2 companies; run once with the setting off, once on with stand-ins making both pairs pass | theme run, twice | The LLM stand-in receives the same number of calls in both runs | unit |
| AC-2  | Setting on; company A: rerank 3.0, positive 0.95, negative 0.10 on one passage | theme run | The LLM stand-in receives ≥ 1 call for A | unit |
| AC-3  | Same as AC-2 | theme run | A's `funnel.passed` is `true` | unit |
| AC-4  | Setting on; company B: rerank 0.5, positive 0.99 | theme run | B's verdict is `exclude` | unit |
| AC-5  | Same as AC-4 | theme run | B's rationale is `screened out by funnel` | unit |
| AC-6  | Same as AC-4 | theme run | The LLM stand-in receives 0 calls for B | unit |
| AC-7  | Setting on; company C: rerank 3.0; on its only passage positive 0.95 and a contrast statement 0.97 | theme run | C's verdict is `exclude` | unit |
| AC-8  | Same as AC-7 | theme run | C's `funnel.entail_negatives` maps that contrast statement to 0.97 | unit |
| AC-9  | Setting on; company D: rerank 3.0; passage P1 positive 0.95 with a negative 0.97; passage P2 positive 0.90 with every negative ≤ 0.2 | theme run | The LLM stand-in receives ≥ 1 call for D | unit |
| AC-10 | Same as AC-9 | theme run | D's `funnel.best_passage` equals P2's text | unit |
| AC-11 | Setting on; company E: rerank 3.0; one passage with positive 0.90 and a negative 0.90 (tie) | theme run | E's verdict is `exclude` | unit |
| AC-12 | Setting on; company F screened out; passage P3 has the highest positive entailment (0.70) | theme run | F's `funnel.best_passage` equals P3's text | unit |
| AC-13 | `funnel_thresholds.json` with theme `t1`: `t_rerank` 5.0; company G: rerank 3.0, positive 0.95, negatives ≤ 0.1 | theme run for `t1` | G's verdict is `exclude` | unit |
| AC-14 | `funnel_thresholds.json` without theme `t2` and `default.t_rerank` 5.0; company G as in AC-13 | theme run for `t2` | G's verdict is `exclude` | unit |
| AC-15 | `funnel_thresholds.json` with `default.k2` 1; company H with 10 passages | theme run | H's `funnel.passages_scored` is 1 | unit |
| AC-16 | A theme JSON without `contrast_statements` | load | Loads without error; the activity's `contrast_statements` is `[]` | unit |
| AC-17 | Any screened-out pair | read the run JSON | `funnel` has exactly the keys `passed`, `rerank_max`, `entail_positive`, `entail_negatives`, `best_passage`, `best_doc_id`, `passages_scored`, `thresholds`, `models` | unit |
| AC-18 | Golden cases: 2 core and 1 peripheral that pass, 2 `not` that are screened out (stand-ins) | `arp theme funnel` | The last three output lines are `core: 2/2`, `peripheral: 1/1`, `not: 0/2` | unit |
| AC-19 | Golden cases where core+peripheral kept is 0.90 | `arp theme funnel --min-kept-positive 0.95` | Exit code 1 | unit |
| AC-20 | Golden cases where `not` kept is 0.40 | `arp theme funnel --max-kept-negative 0.30` | Exit code 1 | unit |
| AC-21 | Electrolyser golden set, `holdout` half (A3), real models | `arp theme funnel --split holdout --min-kept-positive 0.95` | Exit code 0 | golden |
| AC-22 | Same | `arp theme funnel --split holdout --max-kept-negative 0.30` | Exit code 0 | golden |
| AC-23 | Electrolyser golden set, `holdout` half, real models and LLM | `arp theme funnel-compare --split holdout --max-call-ratio 0.5` | Exit code 0 (LLM calls with the setting on ≤ 0.5 × calls with it off) | golden |
| AC-24 | Same | `arp theme funnel-compare --split holdout --max-precision-drop 0.02` | Exit code 0 (precision of `include` verdicts against the golden labels, core and peripheral counted as positive, drops by ≤ 0.02 with the setting on) | golden |
| AC-25 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: theme runs with the setting off (AC-1, AC-25).
