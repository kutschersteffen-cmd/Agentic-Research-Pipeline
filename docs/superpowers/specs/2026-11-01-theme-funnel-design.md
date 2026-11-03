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
| 2 | Cosine similarity of each passage to `in_scope_description` (`funnel.query` with amendment B) | `embed` | top `k1` (default 25) |
| 3 | Fit score of `(in_scope_description, passage)` (`funnel.rerank_query` with amendment B) | `rerank` | top `k2` (default 6) |
| 4 | Entailment of the positive statement and of each negative statement on each of the `k2` passages | `classify` (NLI) | – |
| 5 | **Pass** if best rerank score ≥ `t_rerank` **and** some passage has positive entailment ≥ `t_entail` **and** on that passage the positive is strictly greater than every negative (a tie fails) | – | – |

Negatives = `out_of_scope_description` + `contrast_statements`. Thresholds `k1`, `k2`, `t_rerank` (default 1.5),
`t_entail` (default 0.8) live in `arp/research/data/funnel_thresholds.json`, one entry per theme id with a
`default` entry.

### Integration

In `match_company_activity`'s graph (`arp/research/match_graph.py`), as a node between `gather_evidence` and `run_advocate` (amended 2026-11-03, owner): revenue-resolved and no-evidence pairs never reach it.

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

`arp theme funnel --taxonomy <id> [--taxonomy-version N] [--taxonomies-dir <dir>] --cases <golden cases.json> --documents-dir <dir> [--out <json>]`:
runs only the funnel (no LLM), prints one line per company (label, scores, pass/screened), then one line per
label in the form `<label>: <kept>/<total>`. Options: `--split tune|holdout|all` (default `all`),
`--min-kept-positive <x>` (exit 1 if core + peripheral kept / total < x), `--max-kept-negative <x>` (exit 1 if
`not` kept / total > x). Golden-set format comes from A3.

`arp theme funnel-compare --taxonomy … [--taxonomy-version …] [--taxonomies-dir …] --cases … --documents-dir … [--split …] [--negatives-only] [--max-call-ratio x]
[--max-precision-drop x]`: runs the full theme run on the golden companies twice (setting off, setting on),
prints LLM call counts and the precision of `include` verdicts against the golden labels (core and peripheral
count as positive) for both, and exits 1 if a given limit is broken.

### Contrast statements come from a taxonomy version (amended 2026-11-03, owner)

Both commands read the activity, including `contrast_statements`, from a saved taxonomy version
(`TaxonomyStore`, `--taxonomies-dir` defaults to the configured store). `--theme` is refused with the same message
as `arp theme run`. A draft version is accepted: the commands evaluate, they publish nothing.

### Narrowing the universe (amended 2026-11-03, owner)

`arp universe narrow --universe <in> --taxonomy <id> [--taxonomy-version N] [--taxonomies-dir <dir>] --out <universe.json>
[--keep <company_id> ...] [--cases <golden cases.json>]` writes a universe reduced to companies whose `isic_code` or
`nace_code` shares an ISIC division (first 2 digits) with any activity's `core_isic_codes` or ISIC/NACE `sector_codes`.
Companies without a known ISIC/NACE code are kept. Every dropped company is written to `<out stem>.dropped.json`
with its codes and reason; `--keep` overrides a drop. Discovery, `documents warm` and the theme run then work on the
smaller list; the theme run and the funnel do not narrow.

### Precomputing chunk embeddings (amended 2026-11-03, owner)

The funnel reads passage vectors from the `chunk_embeddings` store (key `chunk_id`, the hybrid-retrieval embedding
model) and stores the ones it computes. `arp documents warm --embed` fills the store for every chunk of every
fetched document, so a run only embeds the activity statements.

### The whole taxonomy version feeds the funnel (amendment B, 2026-11-03, owner; awaiting approval)

Why: the funnel must not drop early-stage evidence (research programmes, pilot plants, demonstrators, capex,
R&D) before extraction. So every part of the taxonomy version, and the extraction schema generated from it, feeds
the funnel. All of this applies only with `ARP_MODELS_UNIVERSE_FUNNEL_ENABLED` on.

**Schema fields of an activity** = the fields `build_taxonomy_schema` generates for that activity (today four:
revenue share, CapEx share, OpEx share, R&D intensity). The funnel reads them through the same field list
`build_taxonomy_schema` returns, without requiring a ratified version, so fields added to the generated schema
later (the planned stage-evidence fields) reach the funnel with no funnel change.

1. **Keyword step.** `gather_evidence` selects evidence with the union of: the activity's `seed_keywords`; the
   `seed_keywords` of every schema field of the activity (today the activity's own keywords plus `revenue`,
   `capex`, `opex`, `research and development`, `R&D`); and these stage words, exactly:
   - ideation: `research programme`, `prototype`, `lab-scale`, `proof of concept`
   - innovation: `pilot plant`, `demonstrator`, `first commercial`, `pre-series`, `order`, `FID`
   - commercial: `segment revenue`, `capacity`, `backlog`, `market share`

   Keywords match as they do today: case-insensitive substring (`order` also matches `border`; that only lets a
   pair reach the funnel, which then decides). This keyword step decides only whether a pair has evidence (no
   evidence → `finalize_no_evidence`) and which chunks the debate sees: the same selection is the debate's evidence
   (one selection, not two). The funnel itself still scores all of the pair's chunks, with no keyword filter
   (step 1 of the table). With the setting off, `gather_evidence` uses `seed_keywords` only, as today.
2. **Embedding query** (`funnel.query`): these parts, each on its own line, empty parts left out:
   `<activity name>: <in_scope_description>`; the theme's `description`; `Technologies: <names, comma-separated>`;
   `Definitions: <term>: <text>; <term>: <text>`. `technologies` and `definitions` are the `ThemeDefinition` fields
   from PR #325. Until that merges, or when they are empty, their lines are left out.
3. **Rerank query** (`funnel.rerank_query`): the embedding query plus one more line,
   `Evidence: <field name>; <field name>; …` (the `name` of every schema field of the activity, in schema order). One rerank call per
   pair scores each passage against this combined query; `t_rerank` applies to that score.
4. **NLI.** Negatives are unchanged (`out_of_scope_description` + `contrast_statements`). The positive statement
   (`funnel.positive`) is `The company researches, develops, pilots, manufactures or sells <activity name>.`
   The pass rule is unchanged, with this positive in place of `in_scope_description`.

The `funnel` record gains three keys: `query`, `rerank_query`, `positive` (AC-17 amended). Steps 2 and 3 of the
table above use `funnel.query` and `funnel.rerank_query` in place of `in_scope_description`. `arp theme funnel
--out` writes, per case, the `funnel` record of its best activity under the key `funnel`.

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
| AC-17 | Any screened-out pair | read the run JSON | `funnel` has exactly the keys `passed`, `rerank_max`, `entail_positive`, `entail_negatives`, `best_passage`, `best_doc_id`, `passages_scored`, `thresholds`, `models`, `query`, `rerank_query`, `positive` (last three added by amendment B) | unit |
| AC-18 | Golden cases: 2 core and 1 peripheral that pass, 2 `not` that are screened out (stand-ins) | `arp theme funnel` | The last three output lines are `core: 2/2`, `peripheral: 1/1`, `not: 0/2` | unit |
| AC-19 | Golden cases where core+peripheral kept is 0.90 | `arp theme funnel --min-kept-positive 0.95` | Exit code 1 | unit |
| AC-20 | Golden cases where `not` kept is 0.40 | `arp theme funnel --max-kept-negative 0.30` | Exit code 1 | unit |
| AC-21 | Electrolyser golden set, `holdout` half (A3), real models | `arp theme funnel --split holdout --min-kept-positive 0.95` | Exit code 0 | golden |
| AC-22 | Same | `arp theme funnel --split holdout --max-kept-negative 0.30` | Exit code 0 | golden |
| AC-23 | Electrolyser golden set, `holdout` half, real models and LLM | `arp theme funnel-compare --split holdout --max-call-ratio 0.5` | Exit code 0 (LLM calls on `not` cases with the setting on ≤ 0.5 × calls on `not` cases with it off; `--negatives-only`; amended 2026-11-03, owner) | golden |
| AC-24 | Same | `arp theme funnel-compare --split holdout --max-precision-drop 0.02` | Exit code 0 (precision of `include` verdicts against the golden labels, core and peripheral counted as positive, drops by ≤ 0.02 with the setting on) | golden |
| AC-25 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

| AC-26 | Taxonomy with one activity, codes `["2790"]`; universe with company X `isic_code "2610"` | `arp universe narrow` | X is not in `--out`; `<out stem>.dropped.json` has X with reason `no sector match (company 26, taxonomy 27)` | unit |
| AC-27 | Company with no known ISIC/NACE code | `arp universe narrow` | Kept in `--out` | unit |
| AC-28 | Activity `"2790"`, company `"2711"` | `arp universe narrow` | Kept (division width) | unit |
| AC-29 | Taxonomy whose activities have no codes | `arp universe narrow` | `--out` equals the input universe; prints `Taxonomy has no sector codes; nothing narrowed.` | unit |
| AC-30 | `arp documents warm --embed` ran over the universe | theme run, setting on | 1 `embed` call per activity, none for passages | unit |
| AC-31 | X dropped as in AC-26 | `arp universe narrow --keep X` | X is in `--out` and not in the dropped file | unit |
| AC-32 | Electrolyser golden set, `holdout` half, `nace_code` per case | `arp universe narrow --cases …` | Prints `core dropped: <n>/9`; the PR states n | golden |

| AC-33 | Setting on; activity `seed_keywords` `["electrolyser"]`; the company's only document is `Our pilot plant started in May.` | theme run | The match has a `funnel` record (not null) | unit |
| AC-34 | Setting off; same activity and document as AC-33 | theme run | The match's rationale starts with `No evidence of this activity` | unit |
| AC-35 | Setting on; activity `seed_keywords` `["electrolyser"]` (so the generated CapEx field's `seed_keywords` are `["electrolyser", "capex"]`); the company's only document is `Capex rose to EUR 40m.` | theme run | The match has a `funnel` record (not null) | unit |
| AC-36 | Activity name `Electrolysers`, `in_scope_description` `Makes stacks.`, `out_of_scope_description` `Buys power.`; theme `description` `Green hydrogen.`; no technologies or definitions | theme run, setting on, a pair with evidence | `funnel.query` is `Electrolysers: Makes stacks.\nGreen hydrogen.` | unit |
| AC-37 | Same as AC-36 | theme run, setting on | `funnel.rerank_query` is `funnel.query` + `\nEvidence: Electrolysers: revenue share; Electrolysers: CapEx share; Electrolysers: OpEx share; Electrolysers: R&D intensity` | unit |
| AC-38 | Same as AC-36 | theme run, setting on | `funnel.positive` is `The company researches, develops, pilots, manufactures or sells Electrolysers.` | unit |
| AC-39 | Same as AC-36 with contrast statement `Buys stacks.` | theme run, setting on | `funnel.entail_negatives` has exactly the keys `Buys power.` and `Buys stacks.` | unit |
| AC-40 | A draft (not ratified) taxonomy version, a golden set with one case and its document | `arp theme funnel --taxonomy …` | Exit code 0 | unit |
| AC-42 | Draft taxonomy version with the AC-36 activity; one golden case with a document | `arp theme funnel --taxonomy … --out rows.json` | The case's `funnel.rerank_query` in `rows.json` equals the AC-37 string | unit |
| AC-43 | Setting on; AC-33's activity; two documents, `Our pilot plant started in May.` and `Weather was mild.` | theme run, stand-ins making the pair pass | `funnel.passages_scored` is 2 | unit |
| AC-44 | Setting on; AC-33's fixture; stand-ins make the pair pass | theme run | The Advocate stand-in's prompt contains `Our pilot plant started in May.` | unit |
| AC-45 | Setting on; theme with technology `PEM` and definition term `stack`, text `cell assembly` (fields from PR #325; owed until it merges) | theme run, a pair with evidence | `funnel.query` contains the lines `Technologies: PEM` and `Definitions: stack: cell assembly` | unit |
| AC-46 | Any pair the funnel passes | read the run JSON | `funnel` has exactly the 12 keys listed in AC-17 | unit |
| AC-47 | Setting off; activity `seed_keywords` `["electrolyser"]`; only document `Capex rose to EUR 40m.` | theme run | The match's rationale starts with `No evidence of this activity` | unit |
| AC-41 | Electrolyser golden set, case `h2pro` (its only document describes a pilot / demonstration project, no manufacturing or sales), real models | `arp theme funnel --split tune` | The `h2pro` line ends with `pass` (a one-case smoke check on the tune split, asked for by the owner) | golden |

Must not change: theme runs with the setting off (AC-1, AC-25).
