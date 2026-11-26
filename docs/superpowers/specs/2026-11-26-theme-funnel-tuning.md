# Theme funnel tuning and funnel on by default

Status: approved by the owner, 2026-11-26
Slug: `theme-funnel-tuning`
Risk: `risk:normal` (one CLI command, one setting's default, one fallback; no auth, money or `risk:high` path)
Size: `M`, two slices (see `## Slices`). R&D Lab plan item 4, fixes finding P4.
Amends: `2026-11-01-theme-funnel-design.md` (approved). Its design and every row there stay; this spec replaces only
its "Settings" paragraph (the default) and adds a tune command, per-theme gating and a fallback. No earlier row is
retired.

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them.

## Why

- **P4, the pre-filter is off and untuned.** `Settings.models_universe_funnel_enabled` defaults to `False`, and
  `backend/arp/research/data/funnel_thresholds.json` holds one global entry (`default`: `k1` 25, `k2` 6, `t_rerank`
  1.5, `t_entail` 0.8) that nobody fitted. With the funnel off, every company × activity pair with a keyword hit
  goes to three LLM calls: 500 companies × 8 activities is up to 12,000 calls.
- Nothing fits thresholds per theme, and nothing checks that a fit keeps the real exposed companies on companies it
  was not fitted on. Turning the funnel on blind could drop real makers before the agents ever read them.
- Steffen's sandbox has no `docker run`, so the funnel must work without the `arp-compute` container.

## What the user can do afterwards that they cannot do today

1. Run `arp golden-set funnel-tune --set electrolyser_makers`: it fits `t_rerank` and `t_entail` for that theme on the
   set's `tune` half, checks them on the `holdout` half (the funnel must keep at least 95% of the real exposed
   companies), and only then writes them for that theme.
2. From then on, every theme run of that theme uses the funnel, with no setting to change. A theme that has not
   passed the check runs exactly as today.
3. Run theme runs in the sandbox with no models service: the funnel runs its models inside the backend process, and
   when those models cannot load, each pair goes to the debate as if the funnel were off.

## What exists today (main `e4cb8c3`)

- `backend/arp/research/funnel.py`: `score_pair(documents, activity, thresholds, content_store, query)` returns a
  `FunnelRecord`. It scores every passage of the pair's documents: top `k1` by embedding cosine, top `k2` of those by
  rerank score, then NLI of the two positive statements (`FunnelQuery.positives`) and the negatives
  (`out_of_scope_description` + `contrast_statements`) on each kept passage. Pass rule: `rerank_max ≥ t_rerank` and
  some kept passage has a positive with entailment `≥ t_entail` that is strictly greater than every negative there;
  `rerank_max` is `None` (cloud rerank failed) → pass.
- It calls the models through `arp.models.embed`, `arp.models.rerank` and `arp.models.classify`
  (`backend/arp/models/capabilities.py`). With `compute_models_url` unset they run in the calling process
  (`arp/models/local.py`: fastembed for embed and rerank, which the base install has; `transformers` for NLI, which
  needs the `models` extra, `pip install -e ".[models]"`). Without the extra, `classify` raises `ImportError`, and
  today that error ends the company's match.
- `backend/arp/research/funnel_thresholds.py`: `thresholds_for(theme_id, path=None)` returns the theme's entry over
  `default`, key by key, from `_DEFAULT_PATH` (the JSON above).
- `backend/arp/research/pipeline.py` (`_match_company`): `funnel_thresholds = thresholds_for(theme.theme_id) if
  settings.models_universe_funnel_enabled else None`; `None` means no funnel node for any pair.
- `arp theme funnel` and `arp theme funnel-compare` (`backend/arp/cli/theme.py`) evaluate the funnel on a golden set
  with fixed thresholds; `funnel-compare` sets the setting to `True` and `False` explicitly.
- Spec `theme-precision-scorecard` (merged, slice 1 being built): `arp golden-set theme --set …` resolves a set
  (`Golden set not found: …`, `Risk sets can't be scored yet: …`), its taxonomy (`tax_<set_id>` from
  `<set dir>/taxonomies`, or `--taxonomy` / `--taxonomy-version` / `--taxonomies-dir`; `Taxonomy not found: …`), and
  each case's documents (`--documents-dir` layout `<dir>/<case_id>/<doc_type>/<file>`, else the app's document
  sources). A case with no documents is "not assessed".

## Goals

- G1 `arp golden-set funnel-tune` fits `t_rerank` and `t_entail` for one theme on a golden set's `tune` half, with no
  LLM call.
- G2 It checks the fit on the `holdout` half: the share of assessed `core` and `peripheral` companies the funnel keeps
  must be at least `--min-recall` (default 0.95).
- G3 Only a fit that passes is written, as the theme's entry in the thresholds file, marked as tuned.
- G4 With the setting left at its new default, a theme run uses the funnel for exactly the themes with a tuned entry.
- G5 `true` and `false` keep today's meaning: `true` funnels every theme (theme entry over `default`), `false` none.
- G6 Without a models service, the funnel runs in the backend process; when its models fail, the pair goes to the
  debate and the run goes on.

## Non-goals

- Fitting `k1` or `k2`, or changing the pass rule, the queries, the statements or the `FunnelRecord` keys
  (theme-funnel AC-17 and AC-46 stand).
- Committing tuned values for the golden sets. That needs the documents and the real models; see "Afterwards".
- Any UI. Mock-up screen 4's "Pre-filter: on, tuned on 33 checked companies" line belongs to a later screen item.
- Changing the matcher's evidence or record keys (spec `matcher-shared-retrieval`).
- Scoring precision (spec `theme-precision-scorecard` does that) or a golden-set merge gate in CI.
- Water scarcity (risk sets are refused, as in the scorecard).

## Anti-goals (must stay true)

- No theme loses pairs to the funnel unless its thresholds passed the holdout check, or the owner set the setting to
  `true`.
- Thresholds are fitted on `tune` cases only; `holdout` cases only check.
- A failing check writes nothing.
- A model failure in the funnel never ends a company's match.
- No real model call (LLM or local model) in any `holdout` or `unit` row.

## Design

### Slice 1: the gate, the default and the fallback

**Setting.** `models_universe_funnel_enabled: bool | None = None` (`ARP_MODELS_UNIVERSE_FUNNEL_ENABLED`; unset means
`None`). In `_match_company`:

| Setting | Funnel thresholds for the theme |
|---|---|
| `None` (new default) | the theme's own entry, if the file has one with a `tuned` object (merged over `default` key by key as today); otherwise `None` (no funnel) |
| `True` | `thresholds_for(theme_id)` as today (theme entry over `default`, or `default` alone) |
| `False` | `None` |

**Thresholds file.** New setting `funnel_thresholds_path: Path | None = None` (`ARP_FUNNEL_THRESHOLDS_PATH`); `None`
means the package file (`_DEFAULT_PATH`). Every reader (`_match_company`, `arp theme funnel`, `funnel-compare`,
`funnel-tune`) reads that path. A theme entry may hold a `tuned` object (written by slice 2) next to its numbers. The
thresholds a run uses, and so `FunnelRecord.thresholds`, have exactly the keys `k1`, `k2`, `t_rerank`, `t_entail`:
`tuned` is never passed on.

**Fallback.** In the funnel node (`_funnel` in `match_graph.py`): when `score_pair` raises, the pair goes on to
`run_advocate` as if the funnel were off for it, `funnel` stays `null` on the match, and one WARNING is logged:
`Funnel could not run for <company_id> / <activity_id>: <error>; sent to the debate.` Every pair tries again (no
memory across pairs).

**Existing test changed.** `backend/tests/test_funnel_thresholds.py::test_setting_defaults_off` asserts
`Settings().models_universe_funnel_enabled is False`; slice 1 changes it to assert `is None`. It is the only existing
test this spec changes; the PR lists it.

**Where the models run.** Nothing new: with `compute_models_url` unset the funnel's models run inside the backend
process (no container, no service); `uvicorn arp.compute.server:app` as a plain process is optional, as today. The
`models` extra makes NLI work; without it the fallback above applies. Slice 1 updates the setting's description and adds
a short paragraph "Theme funnel" to `docs/INSTALLATION.md` right after the `ARP_COMPUTE_MODELS_URL` lines under
"Bank Jupyter (Vertex)": models run in-process, the `models` extra is needed for NLI, without it each pair goes to the
debate.

### Slice 2: `arp golden-set funnel-tune`

```
arp golden-set funnel-tune --set <name or dir> [--documents-dir <dir>] [--taxonomy <id> [--taxonomy-version N]
                           [--taxonomies-dir <dir>]] [--min-recall x]
```

- **Set, taxonomy, documents**: resolved exactly as `arp golden-set theme` does, with its messages and exit codes.
  `--min-recall` defaults to 0.95.
- **Scores.** For each assessed case of both halves and each activity of the taxonomy's theme: the pair's passages,
  queries and statements as `score_pair` builds them (`funnel_query(theme, activity)`), with `k1` and `k2` from the
  thresholds file for the theme (theme entry over `default`), and the models called through `arp.models.embed`,
  `arp.models.rerank` and `arp.models.classify`, looked up when called. Per pair it keeps two numbers:
  - `R` = the best rerank score (`rerank_max`; `None` when rerank returned `None`);
  - `D` = the highest entailment of a positive statement on a kept passage where that positive is strictly greater
    than every negative on that passage; none when no kept passage has one.
- **Kept.** At thresholds `(tr, te)` a case is kept when any of its pairs has `R` `None`, or `R ≥ tr` and `D` is not
  none and `D ≥ te` (the funnel's own pass rule).
- **Fit (tune half only).** Candidates: `tr` from the distinct non-`None` `R` of all tune pairs, `te` from the distinct
  `D` of all tune pairs. Tune recall = kept `core` + `peripheral` cases / assessed `core` + `peripheral` cases. Among
  candidate pairs with tune recall ≥ `--min-recall`, pick the one that keeps the fewest assessed tune `not` cases;
  ties go to the most kept tune positives, then the lowest `te`, then the lowest `tr`. None qualifies (or no
  candidates): print `No thresholds keep <min-recall> of tune positives; thresholds not written.` and exit 1, with no
  holdout block.
- **Check (holdout half).** Holdout recall = kept assessed holdout positives / assessed holdout positives at the fitted
  thresholds; with no assessed holdout positive it is `n/a` and fails.
- **Rounding.** Tune and holdout recall are compared to `--min-recall` unrounded. Rounding to 3 decimals is only for
  the printed lines and the `tuned` object.
- **Output**, exactly these lines (values as computed; ratios 3 decimals; `<min-recall>` as given):

```
tune: assessed positives 3, assessed not 3, not assessed 1
fitted: t_rerank 2.000, t_entail 0.700, k1 25, k2 6
tune recall: 1.000 (3/3)
tune not kept: 0.000 (0/3)
holdout: assessed positives 2, assessed not 1, not assessed 0
holdout recall: 0.500 (1/2)
holdout not kept: 0.000 (0/1)
Holdout recall 0.500 is below 0.95; thresholds not written.
```

  On a pass the last line is `Holdout recall <v> meets <min-recall>; wrote <theme_id> to <thresholds path>.` and the
  exit code is 0; on a fail, exit 1.
- **Write (pass only).** The thresholds file keeps every other entry and gets, for the theme id:
  `{"k1", "k2", "t_rerank", "t_entail", "tuned"}`, the thresholds as fitted (the observed floats, not rounded), and
  `tuned` = `{"set_id", "taxonomy_id", "taxonomy_version", "created_at", "min_recall", "tune_recall",
  "holdout_recall", "holdout_positives"}` (recalls rounded to 3 decimals; `holdout_positives` = assessed holdout
  positives).
- **Model failure.** Any exception from a model call: print `The funnel models could not run: <error>`, exit 1, write
  nothing.
- No LLM is built or called.

## Defaults taken

1. **New default is "tuned themes only", not plain `true`.** The setting becomes `None` by default; explicit `true`
   and `false` keep their meaning, so `funnel-compare` and every earlier row behave as before. Today's file has no
   tuned entry, so nothing changes on `main` until a fit passes.
2. **The gate is the `tuned` object.** Only `funnel-tune` writes it, only on a pass. A hand-written theme entry works
   only with the setting `true`, as today.
3. **Fit `t_rerank` and `t_entail` only.** `k1` and `k2` stay as the file says; fitting them would mean re-scoring
   the set for every value.
4. **Candidates are the observed scores**, so the fit is exact and repeatable; the tie-breaks prefer the loosest
   thresholds, which keeps the most recall for the holdout half.
5. **Recall counts assessed companies only.** A company without reports is not the funnel's miss; "not assessed" is
   printed on its own. `core` and `peripheral` both count as positive, as in `arp theme funnel`.
6. **One entry per theme id, used by every taxonomy version of that theme.** The `tuned` object records which version
   was fitted; re-run `funnel-tune` after changing the theme's activities.
7. **Models in-process, fallback per pair.** No new service. Without the `models` extra, `classify` fails at import,
   which is instant, so retrying per pair costs nothing worth a memory that tests could leak.
8. **Rerank `None` keeps the pair**, as the funnel does; such pairs give no `tr` candidate.
9. **The package file is the default target**, so a passing fit shows up as a reviewable diff;
   `ARP_FUNNEL_THRESHOLDS_PATH` points elsewhere.

## Afterwards (not rows)

Once slice 2 merges, run `arp golden-set funnel-tune --set electrolyser_makers` and `--set ai_datacentre_operators`
with the real local models (no LLM credit needed) and commit the passing entries through the factory as a data-only
PR. Until then the funnel stays off for every theme.

## Acceptance

**Set T** is a directory `T/` with `cases.json` (`set_id` `fixture_tune`, `kind` `activity`, `labels`
`["core", "peripheral", "not"]`, valid per `arp golden-set exposure validate`) and `T/taxonomies/tax_fixture_tune/`
holding version 1 (`latest.json` → 1, `v1.json`) of a taxonomy whose theme has `theme_id` `theme_fixture_tune`,
`description` empty, and one activity: name `Electrolysers`, in scope `Makes electrolysers.`, out of scope
`Buys electrolysers.`, seed keyword `electrolyser`, no contrast statements. Its positives are therefore
`The company researches, develops, pilots, manufactures or sells Electrolysers.` (P1) and
`The company researches, develops, pilots, manufactures or sells the following: Makes electrolysers.` (P2); its only
negative is `Buys electrolysers.` (N).

Cases, in this `cases.json` order. Each assessed case has one file `<docs>/<case>/annual_report/<case>.txt` holding
exactly `Electrolyser passage <case>.` with no trailing newline, so one passage. Stand-ins return `0.0` (rerank and
every statement) for any text not in the table.

| case | split | label | rerank | P1 | N | (D) |
|---|---|---|---|---|---|---|
| t1 | tune | core | 3.0 | 0.95 | 0.10 | 0.95 |
| t2 | tune | core | 2.0 | 0.85 | 0.10 | 0.85 |
| t3 | tune | peripheral | 2.5 | 0.70 | 0.20 | 0.70 |
| t4 | tune | not | 1.0 | 0.90 | 0.10 | 0.90 |
| t5 | tune | not | 2.8 | 0.60 | 0.10 | 0.60 |
| t6 | tune | not | 3.0 | 0.95 | 0.97 | none |
| t7 | tune | core | no file | | | |
| h1 | holdout | core | 3.0 | 0.75 | 0.10 | 0.75 |
| h2 | holdout | peripheral | 1.5 | 0.90 | 0.10 | 0.90 |
| h3 | holdout | not | 2.5 | 0.65 | 0.10 | 0.65 |

**Model stand-ins** replace the attributes `embed`, `rerank` and `classify` of the module `arp.models`: `embed`
returns `[1.0, 0.0]` for every text; `rerank` returns the table's rerank value per passage text; `classify` returns,
per passage, the table's P1 for P1, `0.0` for P2 and the table's N for N. Each returns provenance
`{"model": <name>, "revision": "x", "where": "local"}`. Every CLI row runs in-process (Typer `CliRunner` on
`arp.cli.app`) so the stand-ins apply. **Thresholds file**: `ARP_FUNNEL_THRESHOLDS_PATH` = a
temporary file F0 holding `{"default": {"k1": 25, "k2": 6, "t_rerank": 1.5, "t_entail": 0.8}}` unless a row says
otherwise. `ARP_STANDINS_DIR` = an empty temporary folder in every row; `ARP_HYBRID_RETRIEVAL_ENABLED=false`.
"Tune T" = `arp golden-set funnel-tune --set T/ --documents-dir <docs>`. "Output contains" means stdout and stderr
combined. A row whose "Then" lists several outcomes passes only when all of them hold.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Set T, stand-ins | Tune T | Exit code 1; the output contains, in this order, the 8 lines of the block under "Slice 2" (`tune: assessed positives 3, …` to `Holdout recall 0.500 is below 0.95; thresholds not written.`) | holdout |
| AC-2 | Set T, stand-ins | Tune T | F0 is byte-for-byte unchanged | holdout |
| AC-3 | Set T, stand-ins | Tune T with `--min-recall 0.5` | Exit code 0; the output contains `fitted: t_rerank 2.000, t_entail 0.700, k1 25, k2 6` and `Holdout recall 0.500 meets 0.5; wrote theme_fixture_tune to <F0 path>.` | holdout |
| AC-4 | As AC-3 | Same | F0 has keys exactly `default` (unchanged) and `theme_fixture_tune`; the latter has keys exactly `k1`, `k2`, `t_rerank`, `t_entail`, `tuned` with `k1` 25, `k2` 6, `t_rerank` 2.0, `t_entail` 0.7 | holdout |
| AC-5 | As AC-3 | Same | F0's `theme_fixture_tune.tuned` has keys exactly `set_id`, `taxonomy_id`, `taxonomy_version`, `created_at`, `min_recall`, `tune_recall`, `holdout_recall`, `holdout_positives`, with `fixture_tune`, `tax_fixture_tune`, 1, (any), 0.5, 1.0, 0.5, 2 | holdout |
| AC-6 | Set T with t3's N stand-in value 0.80 (so t3 has no D) | Tune T | Exit code 1; the output contains `No thresholds keep 0.95 of tune positives; thresholds not written.` and no line starting `holdout:`; F0 unchanged | holdout |
| AC-7 | Set T; the `classify` stand-in raises `RuntimeError("models missing")` | Tune T | Exit code 1; the output contains `The funnel models could not run: models missing`; F0 unchanged | holdout |
| AC-8 | Set T, stand-ins | Tune T with `--min-recall 0.5` | `calls.jsonl` in the stand-in folder has no line with `"kind": "model"` (or does not exist) | holdout |
| AC-9 | The repository | `arp golden-set funnel-tune --set water_scarcity_exposed --documents-dir <empty dir>` | Exit code 1; output contains `Risk sets can't be scored yet: water_scarcity_exposed` | holdout |
| AC-10 | The repository | `arp golden-set funnel-tune --set no_such_set` | Exit code 1; output contains `Golden set not found: no_such_set` | holdout |

Rows AC-11 to AC-18 call `arp.research.pipeline._match_company(CompanyRef(company_id="c1", name="Co"), theme,
registry=<a DocumentSourceRegistry with one source whose fetch returns D1>, llm=<build_llm_client under
ARP_STANDINS_DIR>, settings=<get_settings()>)`, with `theme` = set T's theme and `D1` = one `SourceDocument` for
`c1`, `doc_type` `other`, `title` `d1.txt`, text `Electrolyser passage t1.` (t1's stand-in scores: rerank 3.0, P1 0.95, N 0.10).
The stand-in folder holds `model/AgentOpinion.json` (`{"output": {"stance": "s", "rationale": "r", "citations": [],
"exposure_estimate": "pure_play"}}`) and `model/AdjudicatorOutput.json` (`{"output": {"verdict": "include",
"exposure_estimate": "pure_play", "confidence": 0.9, "adjudicator_rationale": "r", "citations": []}}`). "Tuned entry
with `t_rerank` x" = F0 plus `"theme_fixture_tune": {"t_rerank": x, "tuned": <AC-5's object>}`. "Adjudicator calls" =
lines of `calls.jsonl` with `"name": "AdjudicatorOutput"`. "Then" reads the one returned match.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-11 | `ARP_MODELS_UNIVERSE_FUNNEL_ENABLED` unset; tuned entry with `t_rerank` 5.0; model stand-ins | Call it | `verdict` `exclude`; `adjudicator_rationale` `screened out by funnel`; 0 adjudicator calls | holdout |
| AC-12 | Setting unset; tuned entry with `t_rerank` 1.0; model stand-ins | Call it | `funnel.passed` true; `funnel.thresholds` equals `{"k1": 25, "k2": 6, "t_rerank": 1.0, "t_entail": 0.8}`; 1 adjudicator call | holdout |
| AC-13 | Setting unset; F0 plus `"theme_fixture_tune": {"t_rerank": 5.0}` (no `tuned`); model stand-ins | Call it | `funnel` null; 1 adjudicator call | holdout |
| AC-14 | Setting unset; F0 only; model stand-ins | Call it | `funnel` null; 1 adjudicator call | holdout |
| AC-15 | `ARP_MODELS_UNIVERSE_FUNNEL_ENABLED=false`; tuned entry with `t_rerank` 5.0; model stand-ins | Call it | `funnel` null; 1 adjudicator call | holdout |
| AC-16 | `ARP_MODELS_UNIVERSE_FUNNEL_ENABLED=true`; F0 with `default.t_rerank` 5.0, no theme entry; model stand-ins | Call it | `verdict` `exclude`; `adjudicator_rationale` `screened out by funnel` (today's behaviour) | holdout |
| AC-17 | Setting unset; tuned entry with `t_rerank` 1.0; stand-ins as above except `classify` raises `RuntimeError("models missing")` | Call it | The call returns; `funnel` null; `verdict` `include`; 1 adjudicator call; a WARNING log record contains `Funnel could not run for c1` and `models missing` | holdout |
| AC-18 | Setting unset; tuned entry with `t_rerank` 1.0; `ARP_COMPUTE_MODELS_URL` unset; `ARP_CACHE_DIR` an empty temporary folder; in `arp.models.local`, `text_embedding` returns an object whose `.embed(texts)` yields `[1.0, 0.0]` per text, `cross_encoder` returns an object whose `.rerank(query, texts)` yields 3.0 per text, `nli_scores` returns per text P1 0.95, P2 0.0, N 0.10 (`arp.models.*` itself not replaced) | Call it | `funnel.passed` true; `funnel.models` has 3 entries and each has `where` `local` | holdout |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-19 | The existing funnel tests (`backend/tests/test_funnel.py`, `test_funnel_integration.py`, `test_funnel_cli.py`, `test_funnel_thresholds.py`) | Run them on this branch | All pass unchanged, except `test_setting_defaults_off`, which asserts `is None` | unit |
| AC-20 | The existing backend test suite on `main` | Run on this branch, excluding files added by this change and `test_setting_defaults_off` | Same pass/fail result per test as on `main` | unit |

## Slices

Two PRs, each `risk:normal` with `Spec: theme-funnel-tuning` and its `Rows:` line. Order: 1, then 2. Slice 2 needs the
merged slice 1 (the `funnel_thresholds_path` setting) and the merged slice 1 of `theme-precision-scorecard` (set,
taxonomy and document loading of `arp golden-set theme`).

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | S | Setting default `None` and the table above in `_match_company`, `funnel_thresholds_path`, `tuned` never passed on, the fallback in `_funnel`, setting description and `docs/INSTALLATION.md` lines, tests | AC-11 to AC-20 |
| 2 | M | `arp golden-set funnel-tune` in `backend/arp/cli/golden_set.py` (reusing the scorecard's loading), the `R`/`D` scoring next to `score_pair` without changing its record, fit, check, write, tests | AC-1 to AC-10, AC-19, AC-20 |
