# Theme precision scorecard and calibrated confidence

Status: Draft, for owner approval
Slug: `theme-precision-scorecard`
Risk: `risk:normal` (CLI, matcher routing, one API endpoint, one results box; no auth, money or `risk:high` path)
Size: `M`, three slices (see `## Slices`). R&D Lab plan items 1 and 5, fixes findings P1 and P3.

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them.

## Why

R&D Lab matches companies to themes with three LLM agents, but nobody knows how often it is right.

- **P1, precision is never measured.** Three exposure golden sets hold 197 labelled companies
  (`backend/tests/golden/exposure/`: `electrolyser_makers` 66, `ai_datacentre_operators` 64,
  `water_scarcity_exposed` 67), each split into `tune` and `holdout`. No command runs the theme matching on them
  and reports precision and recall. `arp theme funnel-compare` (`backend/arp/cli/theme.py`) runs the matching on a
  set but prints only the precision of `include` verdicts, for the funnel comparison.
- **P3, confidence is the model's own guess.** The adjudicator's self-reported `confidence`
  (`AdjudicatorOutput.confidence`, `backend/arp/research/matcher_agents.py`) routes a match to review when it is
  below `Settings.confidence_review_threshold` (0.6, `_run_adjudicator_node` in
  `backend/arp/research/match_graph.py`) and orders the results. It has never been checked against how often calls
  at that confidence are right.

## What the user can do afterwards that they cannot do today

1. Run `arp golden-set theme --set electrolyser_makers` and read precision, recall (core, peripheral), the share of
   quotes found in the source and a confidence-vs-correct table, for the tune and the holdout half.
2. Gate a taxonomy on the holdout half (`--min-precision`, `--min-recall-core`) and keep a JSON report.
3. Turn the tune tables into a calibration file; from then on review routing, the confidence column and the
   confidence sorts use "how often calls at this level were right", and a match says "correct 9 in 10 at this level".
4. See a "Run quality" box on theme results when the run's taxonomy version has been scored on a holdout half.

## What exists today (main `811a92e`)

- `backend/arp/golden_set/exposure.py`: `load_set`, `ExposureSet`, `ExposureCase` (labels `core`, `peripheral`,
  `not` for activity sets; `split` is `tune` or `holdout`). No case stores a document file; every document is a URL.
- `backend/tests/golden/exposure/electrolyser_makers/taxonomies/tax_electrolyser_makers/` holds a one-activity
  taxonomy (`latest.json`, `v1.json`), read with `TaxonomyStore`. `ai_datacentre_operators` has no taxonomy.
- `backend/arp/cli/theme.py`: `_case_documents(documents_dir, case_id)` reads `<documents_dir>/<case_id>/<doc_type>/<file>`
  into `SourceDocument`s with `doc_id = <case_id>_<first 16 hex chars of sha256(file bytes)>`; `_CaseFiles` wraps it as
  a document source; `_compare_arm` runs `pipeline._match_company` per case.
- A company with no documents gets `verdict: uncertain`, `confidence: 0.0` ("not assessed"); a company with documents
  but no keyword hit gets `verdict: exclude`, `confidence: 1.0`, advocate stance `No evidence found`, and no LLM call.
- `ARP_STANDINS_DIR` (`backend/arp/standins.py`): every model call is answered from `model/<OutputClass>.json`; a JSON
  list answers call *i* with entry *i*, then the last entry.
- Theme results UI: `frontend/src/pages/ThemeBuilder.tsx`, route `#/theme/<run_id>`, results from
  `GET /api/themes/runs/{run_id}/results`. Spec `thematic-universe-quick-fixes` (PR #737) changes the default sort to
  exposure tier, then confidence, then name.

## Goals

- G1 `arp golden-set theme` scores the theme matching on an activity golden set, per split, as text and JSON.
- G2 A holdout gate: thresholds on the holdout half set the exit code; every holdout run stores its report.
- G3 `ai_datacentre_operators` gets a taxonomy so both activity sets can be scored.
- G4 A risk set is refused with a plain message until risk themes exist (plan item 10).
- G5 `arp golden-set calibrate` turns tune tables into one calibration file.
- G6 With a calibration file, each adjudicated match stores a calibrated confidence, and review routing uses it.
- G7 The results screen shows the calibrated value, sorts by it, and says "correct N in 10 at this level".
- G8 `GET /api/themes/runs/{run_id}/quality` and a "Run quality" box show the stored holdout scorecard.

## Non-goals

- Scoring `water_scarcity_exposed` (needs risk themes, plan item 10, slice c).
- Downloading the golden documents into a folder. Without `--documents-dir` the app's own document sources fetch them.
- Tuning anything (thresholds, prompts, funnel): plan item 4 reuses this runner later.
- Changing what the adjudicator reads or returns (plan item 2, spec `matcher-shared-retrieval`).
- The rest of mock-up screen 9: confidence bar chart, "what it got wrong" list, "vs last run", "apply the fixes",
  download button. They belong to the Theme Workbench (plan item 13).
- A golden-set merge gate in CI. The owner has switched golden checks off as a gate; no workflow changes.
- Calibration per theme (see "Defaults taken").

## Anti-goals (must stay true)

- No calibration file: matching, routing, results and the UI behave exactly as today.
- The raw `confidence` the adjudicator reported is kept unchanged on every match.
- Calibration is fitted on `tune` tables only, never on `holdout`.
- No real model call in any `holdout` or `unit` row.

## Design

### Slice 1: `arp golden-set theme` (items 1a, 1b)

```
arp golden-set theme --set <name or dir> [--documents-dir <dir>] [--taxonomy <id> [--taxonomy-version N]
                     [--taxonomies-dir <dir>]] [--split tune|holdout|both] [--min-precision x]
                     [--min-recall-core x] [--out <file.json>]
```

- **Set.** `--set` is a set id under `backend/tests/golden/exposure/` or a directory holding `cases.json`. If it
  is neither, exit 1 with `Golden set not found: <value>`. A set whose `kind` is `risk` exits 1, before any model
  call, with `Risk sets can't be scored yet: <set_id>`.
- **Taxonomy.** Without `--taxonomy`: `tax_<set_id>`, latest version, from `<set dir>/taxonomies`. With `--taxonomy`:
  that id (and `--taxonomy-version`, default latest) from `--taxonomies-dir`, default `Settings.taxonomies_dir`. Not
  found: exit 1 with `Taxonomy not found: <id>`. A draft taxonomy version is accepted.
- **New taxonomy** `backend/tests/golden/exposure/ai_datacentre_operators/taxonomies/tax_ai_datacentre_operators/`
  (`latest.json` → version 1, `v1.json`), same shape as the electrolyser one, one activity:
  name `AI data-centre operation`; in scope = the set's `subject`; out of scope `Supplies chips, servers, cooling
  or power to data centres that others own or operate; buys cloud capacity without owning or operating the data
  centres`; seed keywords `data center`, `data centre`, `colocation`, `hyperscale`, `GPU`, `AI infrastructure`;
  contrast statements `The company supplies equipment, chips or power to data centres run by others.` and `The company
  rents cloud capacity from others.`; `tier: core`.
- **Documents.** With `--documents-dir`: the `_case_documents` layout, `<dir>/<case_id>/<doc_type>/<file>`. A case
  without files there is not assessed (no model call). Without `--documents-dir`: the app's document sources (the
  registry `arp theme run` uses), with `CompanyRef(company_id=case_id, name=company, isin=isin)`.
- **Matching.** Each case of the chosen split(s) runs through `pipeline._match_company` with the taxonomy's theme and
  the current settings, called as `_compare_arm` does (no indirect, revenue or R&D resolver, each `None`), **one company at a time, in `cases.json` order**, tune cases before holdout cases. Writes no run.
- **Per company** (every match of that company for the theme's activities):
  - *assessed*: the company has at least one document.
  - *put in*: at least one match has `verdict: include`.
  - *belongs*: label `core` or `peripheral`.
  - *adjudicated match*: a match whose `advocate` is set and whose advocate stance is not `No evidence found`
    (so not the no-evidence, funnel-screened-out or revenue-resolved path).
  - *deciding match*: among the company's adjudicated matches, the `include` one with the highest raw `confidence`;
    if none is `include`, the one with the highest raw `confidence`. A company with no adjudicated match has none.
  - *correct*: the deciding match is `include` and the company belongs, or it is not `include` and the label is `not`.
- **Metrics per split** (rounded to 3 decimals; `n/a` in text and `null` in JSON when the denominator is 0):
  - `precision` = put in and belongs / put in.
  - `recall core` = put in among `core` / all `core` cases. `recall peripheral` likewise. Not-assessed cases count as
    not put in.
  - `quotes found in source` = citations with `grounded: true` / all citations, over the `include` matches.
  - Confidence table over deciding matches, four bins by raw `confidence`: `0.90-1.00` (c ≥ 0.9), `0.70-0.90`
    (0.7 ≤ c < 0.9), `0.50-0.70` (0.5 ≤ c < 0.7), `0.00-0.50` (c < 0.5), in that order. Per bin: calls, correct,
    rate = correct / calls.
- **Text output**, one block per split, exactly these lines (values as computed):

```
split: tune
companies: 7 (core 2, peripheral 2, not 3)
not assessed: 1
put in: 3
precision: 0.667
recall core: 0.500
recall peripheral: 0.500
quotes found in source: 0.500
confidence 0.90-1.00: calls 2, correct 2, rate 1.000
confidence 0.70-0.90: calls 1, correct 1, rate 1.000
confidence 0.50-0.70: calls 2, correct 0, rate 0.000
confidence 0.00-0.50: calls 0, correct 0, rate n/a
```

  The `companies` line lists the set's `labels` in their order. With `--split both` (default) the tune block comes
  first, then the holdout block.
- **JSON report** (`--out`, and the stored scorecard below), one object:
  `{"set_id", "taxonomy_id", "taxonomy_version", "created_at", "splits"}`. `splits` maps each run split to
  `{"companies", "labels", "not_assessed", "put_in", "precision", "recall_core", "recall_peripheral", "quotes_found",
  "confidence", "cases"}`: `labels` = `{label: count}`; `confidence` = list of four
  `{"low", "high", "calls", "correct", "rate"}` in the bin order above (`low`/`high` 0.9/1.0, 0.7/0.9, 0.5/0.7,
  0.0/0.5); `cases` = one `{"case_id", "label", "assessed", "put_in", "confidence", "correct"}` per case in run order
  (`confidence` = the deciding match's raw confidence, `correct` its correctness; both `null` without one).
- **Gate.** `--min-precision x` / `--min-recall-core x` compare the holdout block's value as printed (rounded to
  3 decimals); below the threshold (or
  `n/a`) prints `Holdout precision <v> is below <x>.` / `Holdout recall core <v> is below <x>.` (`<v>` as in the
  block) and exits 1, after printing all blocks. A threshold with `--split tune` exits 1 with
  `The gate needs the holdout split.` before any model call. Otherwise exit 0.
- **Stored scorecard.** Every run that includes the holdout split writes the JSON report to
  `<Settings.scorecards_dir>/<taxonomy_id>_v<taxonomy_version>.json` (overwriting), gate passed or not. New setting
  `scorecards_dir: Path = REPO_ROOT / "scorecards"` (`ARP_SCORECARDS_DIR`); `scorecards/*` goes into `.gitignore`
  like `runs/*`.

### Slice 2: calibrated confidence (item 5, backend)

```
arp golden-set calibrate --report <file.json> [--report <file.json> ...]
```

- Reads only the `splits.tune.confidence` bins of each report (a holdout split in the same report is ignored) and adds calls and correct per bin across reports. A report
  without a tune split exits 1 with `<file> has no tune split.` and writes nothing.
- Writes `Settings.confidence_calibration_path` (new setting, default `<scorecards_dir>/confidence_calibration.json`,
  `ARP_CONFIDENCE_CALIBRATION_PATH`):
  `{"created_at", "reports": [<file names as given>], "bins": [{"low", "high", "calls", "correct", "rate"}]}`, the four
  bins in the order above, `rate` = correct / calls rounded to 3 decimals, `null` when calls < 5.
- Prints one line per bin: `0.90-1.00: rate 0.927 from 41 calls` or `0.50-0.70: 3 calls, too few; raw confidence kept`.
- `CompanyMatch` gets `calibrated_confidence: float | None = None`. In `_run_adjudicator_node`, when the calibration
  file exists and the bin of the adjudicator's raw confidence has a `rate`, `calibrated_confidence` = that rate;
  otherwise `null`. Only adjudicated matches get one.
- Review routing: the confidence test in `_run_adjudicator_node` uses `calibrated_confidence` when it is set, else the
  raw `confidence`, against `confidence_review_threshold` (unchanged, 0.6). The other flag reasons are unchanged.
- The file is read when a match is adjudicated; a missing or unreadable file means no calibration (a warning in the log
  for an unreadable one).

### Slice 3: results screen (items 1c and 5, UI)

- `GET /api/themes/runs/{run_id}/quality`: reads `params.taxonomy_id` and `params.taxonomy_version` of the run's
  manifest from the app's run store (any `run_type`; a missing key counts as no taxonomy); if
  `<scorecards_dir>/<taxonomy_id>_v<taxonomy_version>.json` exists and has a holdout split, 200 with
  `{"set_id", "taxonomy_id", "taxonomy_version", "created_at", "holdout_companies", "precision", "recall_core",
  "recall_peripheral", "quotes_found"}` (values from `splits.holdout`; `holdout_companies` = its `companies`).
  Otherwise (unknown run, no taxonomy, no file, no holdout split) 404 with detail `No holdout scorecard for this run.`
  Regenerate the OpenAPI types and add the contract line (`.claude/CLAUDE.md`, Checks).
- **Run quality box** on `#/theme/<run_id>`, in the results card above the filters, a region labelled `Run quality`
  with heading `Run quality` and four tiles, label then value:
  `Precision` `0.91` (2 decimals), `Recall, core` `0.95` (2 decimals), `Quotes found in source` `100%` (whole percent),
  `Checked on` `33 holdout companies`. A `null` value shows `n/a`. On 404 the region holds only the heading and
  `Not measured on a golden set yet.` Any other error: the region holds the heading and `Run quality could not be loaded.`
- **Calibrated confidence in the table.** The Confidence cell shows `calibrated_confidence` when set, else
  `confidence`, with the existing badge. Every sort that uses confidence (the two confidence sorts, and the confidence
  key of whatever default sort is on `main` when slice 3 is built; `thematic-universe-quick-fixes`, PR #737, makes it
  exposure tier, then confidence, then name) uses the same value.
- The expanded detail row gets a line `Confidence: correct N in 10 at this level`, N = `round(calibrated_confidence × 10)`,
  only when `calibrated_confidence` is set.

## Defaults taken

1. **One global calibration, not per theme.** A split of one set gives about 30 adjudicated calls, so a per-theme bin
   would hold 5 to 10 calls and swing with one company. Pooling the tune tables of both activity sets gives about 60
   calls. Per-theme calibration can follow once more sets exist.
2. **Four confidence bins** as in mock-up screen 9 (90–100, 70–90, 50–70, below 50); a bin needs 5 calls to count.
3. **Peripheral belongs.** Precision counts `core` and `peripheral` as right, as `funnel-compare` already does; recall
   is shown separately for each.
4. **Not assessed counts as a miss**, as screen 9 says, and is reported on its own line.
5. **Company-level scoring**: the golden labels are per company, so a company is "put in" when any activity includes it.
6. **The table counts adjudicated calls only.** No-evidence excludes carry a fixed confidence 1.0 that the model never
   stated; mixing them in would make the top bin look better than the model is.
7. **Holdout runs always store their report**, so the box can show it; tune runs never do.
8. **Water scarcity** is refused until plan item 10 builds risk themes; its labels (`exposed_disclosed`, …) have no
   matching verdict today.
9. **Review threshold stays 0.6**; screen 9's "below 70%" was an illustration.
10. **No document download**: without `--documents-dir` the command uses the same document sources as a theme run.

## Acceptance

Fixtures. **Set F** is a directory `F/` with `cases.json` (`set_id` `fixture_set`, `kind` `activity`, `labels`
`["core", "peripheral", "not"]`, valid per `arp golden-set exposure validate`) and `F/taxonomies/tax_fixture_set/`
holding a one-activity taxonomy, version 1 (`latest.json` → 1, `v1.json`), seed keyword `electrolyser`. Its cases, in this `cases.json` order, all `split: tune`
unless a row says otherwise:

| case | label | documents dir has | stand-in `AdjudicatorOutput` |
|---|---|---|---|
| a | core | `a/annual_report/a.txt`: `We manufacture electrolyser stacks.` | include, 0.95, one citation: `doc_id` = a's doc id, quote `We manufacture electrolyser stacks.` |
| b | core | `b/annual_report/b.txt`: `Our electrolyser unit is small.` | exclude, 0.55, no citation |
| c | peripheral | `c/annual_report/c.txt`: `An electrolyser line opened.` | include, 0.80, one citation: c's doc id, quote `This sentence is not in the file.` |
| d | peripheral | nothing | (no call) |
| e | not | `e/annual_report/e.txt`: `We buy electrolyser systems.` | include, 0.60, no citation |
| f | not | `f/annual_report/f.txt`: `We operate an electrolyser plant.` | exclude, 0.92, no citation |
| g | not | `g/annual_report/g.txt`: `We make cement.` | (no call: no keyword hit) |

A doc id is `<case_id>_<first 16 hex chars of sha256 of the file bytes>`. Stand-ins: `ARP_STANDINS_DIR` with
every entry wrapped as `{"output": …}`; `model/AgentOpinion.json` = one entry (`stance` `s`, `rationale` `r`, no citations, `exposure_estimate` `pure_play`)
and `model/AdjudicatorOutput.json` = a list with the entries for a, b, c, e, f in that order
(`exposure_estimate` `pure_play` for include, `none` for exclude; `adjudicator_rationale` `r`; every citation has
`doc_type` `annual_report`). If a later spec renames or reshapes
`AdjudicatorOutput`, that spec updates these fixtures. "Run F" = `arp golden-set theme --set F/ --documents-dir <docs>
--split tune` with these stand-ins and with `ARP_HYBRID_RETRIEVAL_ENABLED=false` and
`ARP_MODELS_UNIVERSE_FUNNEL_ENABLED=false` (keyword-only evidence, so case g gets no evidence and no model call).
Every CLI row in this table runs with those two settings. "Output contains" means stdout and stderr combined.
`ARP_SCORECARDS_DIR` is an empty temporary directory S in every CLI row unless the row says otherwise. **Set H** = a directory `H/` that is set F with every `split` set to `holdout` (same taxonomy, documents and stand-ins).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Set F | Run F | Exit code 0; the output contains, in this order, the 12 lines of the text block shown under "Slice 1" (`split: tune` … `confidence 0.00-0.50: calls 0, correct 0, rate n/a`) | holdout |
| AC-2 | Set F | Run F | `calls.jsonl` in the stand-in folder has exactly 5 lines with `"name": "AdjudicatorOutput"` | holdout |
| AC-3 | Set F | Run F with `--out r.json` | `r.json` has top-level keys exactly `set_id`, `taxonomy_id`, `taxonomy_version`, `created_at`, `splits`; `set_id` `fixture_set`; `taxonomy_id` `tax_fixture_set`; `splits` has only the key `tune` | holdout |
| AC-4 | Set F | Run F with `--out r.json` | `splits.tune` has keys exactly `companies`, `labels`, `not_assessed`, `put_in`, `precision`, `recall_core`, `recall_peripheral`, `quotes_found`, `confidence`, `cases`, with `companies` 7, `labels` `{"core": 2, "peripheral": 2, "not": 3}`, `not_assessed` 1, `put_in` 3, `precision` 0.667, `recall_core` 0.5, `recall_peripheral` 0.5, `quotes_found` 0.5 | holdout |
| AC-5 | Set F | Run F with `--out r.json` | `splits.tune.confidence` equals `[{"low":0.9,"high":1.0,"calls":2,"correct":2,"rate":1.0},{"low":0.7,"high":0.9,"calls":1,"correct":1,"rate":1.0},{"low":0.5,"high":0.7,"calls":2,"correct":0,"rate":0.0},{"low":0.0,"high":0.5,"calls":0,"correct":0,"rate":null}]` | holdout |
| AC-6 | Set F | Run F with `--out r.json` | `splits.tune.cases` lists case ids `a`–`g` in that order; `d` is `{"case_id":"d","label":"peripheral","assessed":false,"put_in":false,"confidence":null,"correct":null}`; `g` has `assessed` true, `put_in` false, `confidence` null; `e` has `put_in` true, `confidence` 0.6, `correct` false | holdout |
| AC-7 | Set F with case a's split changed to `holdout` | `arp golden-set theme --set F/ --documents-dir <docs>` (split default) | (Stand-in entries are used in run order and not checked here.) Output has `split: tune` before `split: holdout`; the tune block's `companies` line is `companies: 6 (core 1, peripheral 2, not 3)` and the holdout block's is `companies: 1 (core 1, peripheral 0, not 0)` | holdout |
| AC-8 | Set H | `arp golden-set theme --set H/ --documents-dir <docs> --split holdout --min-precision 0.7` | Exit code 1; output contains `Holdout precision 0.667 is below 0.7.` | holdout |
| AC-9 | Set H | Same with `--min-precision 0.6 --min-recall-core 0.5` | Exit code 0 | holdout |
| AC-10 | Set H | Same with `--min-recall-core 0.6` | Exit code 1; output contains `Holdout recall core 0.500 is below 0.6.` | holdout |
| AC-11 | Set H | The AC-8 command | `S/tax_fixture_set_v1.json` exists and its `splits.holdout.precision` is 0.667 | holdout |
| AC-12 | Set F | Run F | S is still empty | holdout |
| AC-13 | Set F | Run F with `--min-precision 0.5` | Exit code 1; output contains `The gate needs the holdout split.` | holdout |
| AC-13b | Set F | Run F with `--min-precision 0.5` | `calls.jsonl` in the stand-in folder has no line with `"name": "AdjudicatorOutput"` | holdout |
| AC-14 | The repository | `arp golden-set theme --set water_scarcity_exposed --documents-dir <empty dir>` | Exit code 1; output contains `Risk sets can't be scored yet: water_scarcity_exposed` | holdout |
| AC-15 | The repository | `arp golden-set theme --set no_such_set` | Exit code 1; output contains `Golden set not found: no_such_set` | holdout |
| AC-16 | The repository, empty documents dir, stand-in folder with no model files | `arp golden-set theme --set electrolyser_makers --documents-dir <empty> --split tune` | Exit code 0; output contains `companies: 33 (core 9, peripheral 10, not 14)`, `not assessed: 33`, `put in: 0`, `precision: n/a`, `recall core: 0.000` | holdout |
| AC-17 | Same as AC-16 | `arp golden-set theme --set ai_datacentre_operators --documents-dir <empty> --split tune --out r.json` | Exit code 0; output contains `companies: 31 (core 9, peripheral 10, not 12)`; `r.json` has `taxonomy_id` `tax_ai_datacentre_operators` and `taxonomy_version` 1 | holdout |
| AC-18 | The repository | load `tax_ai_datacentre_operators` latest from `backend/tests/golden/exposure/ai_datacentre_operators/taxonomies` with `TaxonomyStore` | One activity, named `AI data-centre operation`, with 6 seed keywords and 2 contrast statements | unit |
| AC-19 | Set F | Run F with `--taxonomy tax_nope` | Exit code 1; output contains `Taxonomy not found: tax_nope` | holdout |
| AC-20 | `ARP_CONFIDENCE_CALIBRATION_PATH` = `S/cal.json`; report R1 whose `splits.tune.confidence` is AC-5's list, report R2 whose tune bins are 0.90-1.00 calls 4 correct 3, 0.70-0.90 calls 4 correct 3, 0.50-0.70 calls 3 correct 1, 0.00-0.50 calls 0 | `arp golden-set calibrate --report R1 --report R2` | Exit code 0; the calibration file's `bins` is `[{"low":0.9,"high":1.0,"calls":6,"correct":5,"rate":0.833},{"low":0.7,"high":0.9,"calls":5,"correct":4,"rate":0.8},{"low":0.5,"high":0.7,"calls":5,"correct":1,"rate":0.2},{"low":0.0,"high":0.5,"calls":0,"correct":0,"rate":null}]` | holdout |
| AC-21 | As AC-20 | Same | Output has the lines `0.90-1.00: rate 0.833 from 6 calls` and `0.00-0.50: 0 calls, too few; raw confidence kept` | holdout |
| AC-22 | `ARP_CONFIDENCE_CALIBRATION_PATH` = `S/cal.json`; a report with only a holdout split, file `h.json` | `arp golden-set calibrate --report h.json` | Exit code 1; output contains `h.json has no tune split.`; `S/cal.json` does not exist | holdout |
| AC-22b | `ARP_CONFIDENCE_CALIBRATION_PATH` = `S/cal.json`; report R3 whose tune bins are AC-5's list and whose holdout bins are all calls 10, correct 0 | `arp golden-set calibrate --report R3` | `S/cal.json` `bins` calls are 2, 1, 2, 0 (tune only) and every `rate` is `null` | holdout |

Rows AC-23 to AC-27 call `arp.research.match_graph.match_company_activity` directly for one company and one
activity (seed keyword `electrolyser`), with the default settings except `confidence_calibration_path` and `hybrid_retrieval_enabled=False`, an LLM built
by `build_llm_client` under `ARP_STANDINS_DIR`, and one document `doc_1` with text `We manufacture electrolyser
stacks.` (`documents_by_id` = `{"doc_1": <it>}`). The stand-in `AgentOpinion` is as above; the stand-in
`AdjudicatorOutput` is as the row says, always with `exposure_estimate` `pure_play`. "One grounded citation" =
`doc_id` `doc_1`, `doc_type` `annual_report`, quote `We manufacture electrolyser stacks.` "Then" reads the returned match.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-23 | Calibration file from AC-20; stand-in adjudicator: include, 0.95, one grounded citation | Call it | `confidence` 0.95, `calibrated_confidence` 0.833, `flagged_for_review` false | holdout |
| AC-24 | Calibration file from AC-20; stand-in adjudicator: include, 0.65, one grounded citation | Call it | `calibrated_confidence` 0.2; `flagged_for_review` true | holdout |
| AC-25 | Calibration file from AC-20; stand-in adjudicator: include, 0.40, one grounded citation | Call it | `calibrated_confidence` null; `flagged_for_review` true (raw 0.40 < 0.6) | holdout |
| AC-26 | `confidence_calibration_path` points to a file that does not exist; stand-in adjudicator: include, 0.65, one grounded citation | Call it | `calibrated_confidence` null; `flagged_for_review` false (raw 0.65 ≥ 0.6, as today) | holdout |
| AC-27 | Calibration file from AC-20; the document's text is `We make cement.` | Call it | `verdict` exclude; `confidence` 1.0; `calibrated_confidence` null | holdout |
| AC-27b | `confidence_calibration_path` points to a file holding `not json`; stand-in adjudicator: include, 0.65, one grounded citation | Call it | `calibrated_confidence` null; `flagged_for_review` false; a WARNING log record contains the path | unit |
| AC-28 | `run_q` created in the app's run store (`RunStore` on the e2e stack's `ARP_POSTGRES_DSN`) with `run_type` `theme`, status `completed`, `params` `{"taxonomy_id": "tax_x", "taxonomy_version": 2}`; in the app's `ARP_SCORECARDS_DIR` (e2e default `<repo>/scorecards`), `tax_x_v2.json` = a report whose holdout split has `companies` 33, `precision` 0.912, `recall_core` 0.95, `recall_peripheral` 0.7, `quotes_found` 1.0, `set_id` `electrolyser_makers` | `GET /api/themes/runs/run_q/quality` | 200; body keys exactly `set_id`, `taxonomy_id`, `taxonomy_version`, `created_at`, `holdout_companies`, `precision`, `recall_core`, `recall_peripheral`, `quotes_found`, with `holdout_companies` 33, `precision` 0.912, `quotes_found` 1.0 | holdout |
| AC-29 | As AC-28 but the file is `tax_x_v1.json` | Same | 404; detail `No holdout scorecard for this run.` | holdout |
| AC-30 | As AC-28 but the report has only a tune split | Same | 404; detail `No holdout scorecard for this run.` | holdout |

UI rows run `#/theme/run_t` with Playwright routes, as in `thematic-universe-quick-fixes`: `**/api/runs/run_t`
returns a completed theme-run manifest, `**/api/themes/runs/run_t/results*` the stated matches (each `verdict`
`include`, one activity, distinct `company_id`), `**/api/themes/runs/run_t/layers*` an empty layers result,
`**/api/themes/runs/run_t/quality` the stated response. No model call.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-31 | Quality returns AC-28's body | Page loaded | Region `Run quality` shows tiles `Precision` `0.91`, `Recall, core` `0.95`, `Quotes found in source` `100%`, `Checked on` `33 holdout companies` | holdout |
| AC-32 | Quality returns AC-28's body with `precision` null | Page loaded | The `Precision` tile shows `n/a` | holdout |
| AC-33 | Quality returns 404 with AC-29's detail | Page loaded | Region `Run quality` contains `Not measured on a golden set yet.` and no tile | holdout |
| AC-34 | Quality returns 500 | Page loaded | Region `Run quality` contains `Run quality could not be loaded.`; the results table still shows | holdout |
| AC-35 | Results: `P Co` confidence 0.95 calibrated 0.60; `Q Co` confidence 0.70 calibrated 0.90; `R Co` confidence 0.80, no `calibrated_confidence` | User picks `Sort: confidence (high to low)` | Company column reads `Q Co`, `R Co`, `P Co` | holdout |
| AC-36 | As AC-35 | Page loaded | The Confidence cells read `P Co` `60%`, `Q Co` `90%`, `R Co` `80%` | holdout |
| AC-37 | As AC-35 | User expands `Q Co` | The detail row contains `Confidence: correct 9 in 10 at this level` | holdout |
| AC-38 | As AC-35 | User expands `R Co` | The detail row contains no text `in 10 at this level` | holdout |
| AC-39 | As AC-35, all three with the same `exposure_estimate` `pure_play`; `thematic-universe-quick-fixes` merged | Page loaded, sort untouched | Company column reads `Q Co`, `R Co`, `P Co` (default sort's confidence tie-break uses the calibrated value) | holdout |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-40 | No calibration file | Any theme run | Every match has `calibrated_confidence` null and the same `flagged_for_review` as on `main` (AC-26 is the concrete case) | unit |
| AC-41 | The existing `arp theme funnel` and `arp theme funnel-compare` tests (`backend/tests/test_funnel_cli.py`) | Run them on this branch | All pass unchanged | unit |
| AC-42 | The existing backend and frontend test suites on `main` | Run on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

## Slices

Three PRs, each `risk:normal` with `Spec: theme-precision-scorecard` and its `Rows:` line. Order: 1, then 2, then 3
(slice 3 needs slice 1's `scorecards_dir`, slice 2's `calibrated_confidence` field, and the merged build of
`thematic-universe-quick-fixes` for AC-39). Slice 2 touches
`match_graph.py` and `schemas/thematic.py`, which `matcher-shared-retrieval` also changes: whichever merges second
merges `origin/main` first.

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | M | `arp golden-set theme` in `backend/arp/cli/golden_set.py` (reusing `_case_documents` / `_CaseFiles` / `_match_company`), scoring code, `scorecards_dir` setting, `.gitignore`, the AI data-centre taxonomy, tests | AC-1 to AC-19 (with AC-13b), AC-41, AC-42 |
| 2 | S | `arp golden-set calibrate`, `confidence_calibration_path` setting, `CompanyMatch.calibrated_confidence`, routing in `_run_adjudicator_node`, OpenAPI + generated types, tests | AC-20 to AC-27b, AC-40, AC-42 |
| 3 | S | `GET /api/themes/runs/{run_id}/quality`, Run quality box, calibrated value in cell, sorts and detail row in `ThemeBuilder.tsx`, contract line, tests. Needs `UI review (factory)` | AC-28 to AC-39, AC-42 |
