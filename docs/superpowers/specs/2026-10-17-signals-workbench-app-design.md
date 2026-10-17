# Signals workbench in the app (API and screen)

Date: 2026-10-17
Status: draft for owner approval
Parent: `docs/superpowers/specs/2026-10-14-signals-workbench-design.md` (Component 7, "App screens"). Plans 1 to 4 are merged: registry, evidence, methods, `arp signals run|compare|decide`, the `Lab` notebook library.

## Intent

A Signals screen in the R&D Lab where a person sees every registered experiment and its evidence, compares two of them honestly, records a graduate or shelve decision, and runs a recipe. The screen reads and writes the same registry as the CLI and notebooks, so an experiment registered anywhere appears here.

## Scope

- **API** under `/api/signals`, thin over the existing library (`Registry`, `compare_experiments`, `run_recipe` through `load_inputs`):
  - list experiments;
  - get one experiment;
  - list registered methods;
  - compare two experiments;
  - record a decision;
  - run a recipe.
- **One page**, `#/signals`, linked from the R&D Lab workspace, with four parts:
  - **Experiments** (list);
  - **Evidence** (one experiment);
  - **Compare**;
  - **Run**.
- **A process** on the R&D Lab page, "Research a signal": Run, then Evidence, then Compare, then Decide.

## My calls (owner to confirm with the acceptance table)

1. **Runs from the app are for methods that need no model or paid call.** The app runs `panel`, `price_momentum`, `narrative_attention`, `sestm`, and `transform` or `composite` built from those, synchronously.
   - Methods that call an LLM or a pretrained model (`grounded_llm`, `issuer_first`, `embedding_ridge`, `topic_attention`, `finbert`) are refused by the API with a message that names the CLI command and the notebook to use.
   - Reason: they are slow, cost money, or download models. The CLI already has the cost gate.
   - Their experiments still appear on the screen because the registry is shared.
2. **The experiments list is never ordered by a performance number.** It is ordered by registration time, newest first. Ordering is only ever stated by the Compare result. This is the anti-goal "a signal ranked above another when the data cannot separate them".
3. **Contaminated evidence is labelled where it is shown.** The in-window row is labelled "contaminated (in the model's training window)". A model with no recorded cutoff shows "cutoff unknown: not evidence".
4. **Decisions need the approver role.** The approver is the signed-in user (existing `require_role("approver")`). Graduation keeps the registry's gate (12 or more post-cutoff IC months, unchanged cutoff).
5. **Prices for a run are uploaded with the run** as a wide CSV of calendar month-end dates, the same file the CLI takes. Text comes from the text store. No price data is stored by this feature.

## Not in this spec

- The R&D Lab landing page (overview design, own item).
- Asynchronous jobs for LLM methods.
- Editing or deleting experiments; the registry is append-only.
- Plots beyond what the existing chart components already draw.
- The notebook server.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Two experiments registered at different times | `GET /api/signals/experiments` | 200. JSON list of 2 items, newest `created_at` first. Each item has `experiment_id`, `category`, `method`, `universe`, `window_start`, `window_end`, `cost_bps`, `model`, `cutoff`, `decision`, `n_trials`, `created_at` | holdout |
| AC-2 | Experiment A has a higher post-cutoff IC mean than the newer experiment B | `GET /api/signals/experiments` | B is listed before A. The order follows `created_at` only | holdout |
| AC-3 | A registered experiment `X` | `GET /api/signals/experiments/X` | 200. Body equals the registry record: `recipe`, `evidence.windows` (each with `window`, `periods`, `ic`, `net_long_short`, `series`), `notes`, `decision` | holdout |
| AC-4 | No experiment `nope` | `GET /api/signals/experiments/nope` | 404, `detail` = `unknown experiment 'nope'` | holdout |
| AC-5 | Registered methods | `GET /api/signals/methods` | 200. List of objects `{name, runnable_in_app}`. `runnable_in_app` is true for exactly `panel`, `price_momentum`, `narrative_attention`, `sestm`, `transform`, `composite` | holdout |
| AC-6 | Two comparable experiments with 36 common post-cutoff months where A clearly beats B (the plan-4 test fixture) | `POST /api/signals/compare {"a": A, "b": B}` | 200. `{"verdict": "a_higher", "months": 36, "n_comparisons": 1, ...}` | holdout |
| AC-7 | Two comparable experiments whose series cannot be separated | `POST /api/signals/compare` | 200. `verdict` = `insufficient_data` | holdout |
| AC-8 | Two experiments with different universes | `POST /api/signals/compare` | 422. `detail` starts with `not comparable: universe differs` | holdout |
| AC-9 | A signed-in user with role analyst | `POST /api/signals/experiments/X/decision {"decision": "graduate"}` | 403 | holdout |
| AC-10 | An approver; experiment X with fewer than 12 post-cutoff IC months | `POST .../X/decision {"decision": "graduate"}` | 422. `detail` contains `needs post-cutoff evidence with at least 12 IC months`. The registry still shows `decision` = `none` | holdout |
| AC-11 | An approver; experiment X | `POST .../X/decision {"decision": "shelve"}` | 200. `decision` = `shelve` and `decided_by` = the signed-in user's id. The next `GET` shows the same | holdout |
| AC-12 | A `price_momentum` recipe JSON and a month-end price CSV covering the window | `POST /api/signals/runs` (multipart: `recipe`, `prices`) | 200. Returns an `experiment_id` equal to the one `arp signals run` gives for the same recipe and file. The experiment appears in `GET /api/signals/experiments` | holdout |
| AC-13 | A `grounded_llm` recipe | `POST /api/signals/runs` | 422. `detail` = `grounded_llm runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app`. No LLM call is made and nothing is registered | holdout |
| AC-14 | A recipe whose window lies outside the uploaded price file | `POST /api/signals/runs` | 422. `detail` names the window and the file's date range. Nothing is registered | holdout |
| AC-15 | The same `price_momentum` run posted twice | `POST /api/signals/runs` twice | Both return the same `experiment_id`. `n_trials` does not grow | holdout |
| AC-16 | The app with two registered experiments | Open `#/signals` | An "Experiments" table lists both, newest first. Columns: method, category, universe, window, model, decision, trials. No column is sortable by IC or return | evaluator |
| AC-17 | An experiment whose model has a recorded cutoff | Open it on the Evidence part | Two window rows. The in-window row is labelled `contaminated (in the model's training window)`. The post-cutoff row shows IC mean, t-statistic, months, net long-short and deflated Sharpe | evaluator |
| AC-18 | An experiment whose model has no recorded cutoff | Open it | It shows `cutoff unknown: not evidence`. The Graduate button is disabled with that reason shown | evaluator |
| AC-19 | Two experiments chosen on the Compare part | Press Compare with an `insufficient_data` result | It shows `Insufficient data: these signals cannot be separated` with the month count and the number of comparisons. Neither signal is shown above the other | evaluator |
| AC-20 | A viewer (not approver) on an experiment | Look at the decision controls | The Graduate and Shelve buttons are not shown, or are disabled with `Requires approver` | evaluator |
| AC-21 | The Run part | Choose method `grounded_llm` | The method is listed but not selectable, with `Run from the CLI or a notebook` next to it | evaluator |
| AC-22 | The Run part with a `price_momentum` recipe and a valid CSV | Submit | The new experiment opens on the Evidence part | evaluator |
| AC-23 | The R&D Lab workspace page | Open `#/rdLab` | It lists a "Signals workbench" screen linking to `#/signals`, and a process "Research a signal" with steps Run, Evidence, Compare, Decide | evaluator |
| AC-24 | Existing CLI commands | Run `arp signals list`, `run`, `compare`, `decide` | Output and exit codes unchanged; existing tests pass unchanged | unit |

Must not change: the CLI behaviour (AC-24); experiment ids for the same inputs (AC-12, AC-15); the registry being append-only. Nothing in this feature edits or deletes a row.
