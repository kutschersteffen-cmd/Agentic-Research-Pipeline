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

1. **Runs from the app are for methods that need no model or paid call.** The app runs `panel`, `price_momentum`, `narrative_attention`, `sestm`, and `transform` or `composite` specs whose every nested method is one of those, synchronously.
   - A recipe that uses `grounded_llm`, `issuer_first`, `embedding_ridge`, `topic_attention` or `finbert` anywhere in its spec tree is refused, with a message that names the CLI command and the notebook class.
   - Reason: these methods are slow, cost money, or download models, and the CLI already has the cost gate.
   - Experiments made with them in the CLI or a notebook still appear in the app, because the registry is shared.
2. **The experiments list is never ordered by a performance number.** It is ordered by registration time, newest first, and it takes no sort parameter. Ordering between two signals is only ever stated by a Compare result. This is the anti-goal "a signal ranked above another when the data cannot separate them".
3. **Contaminated evidence is labelled where it is shown.**
   - The in-window row is labelled `contaminated (in the model's training window)` and still shows its numbers.
   - An experiment whose model has no recorded cutoff shows `cutoff unknown: not evidence`.
4. **Decisions need the approver role.** The approver is the signed-in user (`require_role("approver")`, recorded as `user_id`).
   - Graduation keeps the registry's gate: at least 12 post-cutoff IC months, and a cutoff unchanged since evaluation.
   - Decisions are appended to the registry's log, never edited in place. The latest decision is the one shown, and a later decision may replace an earlier one.
5. **Prices for a run are uploaded with the run**, as a wide CSV of calendar month-end dates, the same file the CLI takes.
   - Text comes from the text store.
   - The uploaded file is deleted after the run, and nothing in the registry record holds price values.
6. **`#/rdLab` is the existing R&D Lab workspace page.** It gains one screen link and one process. The new R&D Lab landing page (overview design) is a separate item and is not built here.

## Not in this spec

- The new R&D Lab landing page (overview design, own item).
- Asynchronous jobs for LLM methods.
- Editing or deleting experiments.
- Plots beyond what the existing chart components already draw.
- The notebook server.

## Acceptance

Setup notes for the test-writer:
- "Registered with series" means created through the library on `main`: `Registry(RunStore(...)).register(recipe, EvidenceReport(windows=[WindowEvidence(window="post_cutoff", periods=n, ic=IcSummary(...), long_short=None, net_long_short=None, monthly_turnover_pct=None, deflated_sharpe=None, series=[(period_end, value), ...])], ...), data_version=..., model=..., cutoff=...)`.
- "Comparable" means the same `universe`, `window_start`, `window_end` and `cost_bps`.
- Roles come from the existing users file: `viewer` < `analyst` < `approver`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Two experiments registered | `GET /api/signals/experiments` | 200. JSON array of 2 items. Each item has at least the keys `experiment_id`, `category`, `method`, `universe`, `window_start`, `window_end`, `cost_bps`, `model`, `cutoff`, `decision`, `n_trials`, `created_at` | holdout |
| AC-2 | Experiment A registered first, with a higher post-cutoff IC mean than experiment B, registered second | `GET /api/signals/experiments` | B is item 0, A is item 1 | holdout |
| AC-3 | A registered experiment `X` | `GET /api/signals/experiments/X` | 200. Body has at least `experiment_id`, `recipe`, `notes`, `decision`, `decided_by`, `evidence.n_trials`, and `evidence.windows[*]` with `window`, `periods`, `ic.mean`, `ic.t_nw`, `ic.n`, `net_long_short`, `deflated_sharpe`, `series`. Values are equal to `Registry.list_experiments()`'s record for X, serialised with `model_dump(mode="json")` | holdout |
| AC-4 | No experiment `nope` | `GET /api/signals/experiments/nope` | 404, `detail` = `unknown experiment 'nope'` | holdout |
| AC-5 | `main`'s method registry | `GET /api/signals/methods` | 200. The set of `name` values equals the registered method names. `runnable_in_app` is true for exactly `panel`, `price_momentum`, `narrative_attention`, `sestm`, `transform`, `composite`, and false for every other name | holdout |
| AC-6 | A and B comparable and registered with series: 36 post-cutoff months, A's values all `1.0`, B's all `0.0`, same period ends. No other experiment in that scope | `POST /api/signals/compare` with `{"a": "<id of A>", "b": "<id of B>"}` | 200. Body has at least `verdict` = `a_higher`, `months` = 36, `n_comparisons` = 1 | holdout |
| AC-7 | A and B comparable and registered with identical series of 36 post-cutoff months | `POST /api/signals/compare` | 200. `verdict` = `insufficient_data`, `months` = 36 | holdout |
| AC-8 | A and B registered with different `universe` | `POST /api/signals/compare` | 422. `detail` starts with `not comparable: universe differs` | holdout |
| AC-9 | A signed-in `analyst`; experiment X with `decision` = `none` | `POST /api/signals/experiments/X/decision` with `{"decision": "graduate"}` | 403 | holdout |
| AC-10 | An `approver`; experiment X registered with a post-cutoff window whose `ic.n` = 5 | `POST .../X/decision` with `{"decision": "graduate"}` | 422. `detail` contains `needs post-cutoff evidence with at least 12 IC months` | holdout |
| AC-11 | An `approver`; experiment X | `POST .../X/decision` with `{"decision": "shelve"}` | 200. Body has `decision` = `shelve` and `decided_by` = the approver's `user_id` from `GET /api/me` | holdout |
| AC-12 | A `price_momentum` recipe and a month-end price CSV covering its window | `POST /api/signals/runs` (multipart: file part `recipe` holding the recipe JSON, file part `prices` holding the CSV) | 200. Body has `experiment_id`, equal to the id `arp signals run --recipe <same file> --prices <same file>` prints on its `experiment_id:` line | holdout |
| AC-13 | A `grounded_llm` recipe | `POST /api/signals/runs` | 422. `detail` = `grounded_llm runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app` | holdout |
| AC-14 | A recipe whose window is not fully inside the uploaded price file | `POST /api/signals/runs` | 422. `detail` = `recipe window <window_start>..<window_end> is outside the price file <first date>..<last date>` | holdout |
| AC-15 | The same `price_momentum` recipe and CSV | `POST /api/signals/runs` twice | Both 200 with the same `experiment_id`. `GET /api/signals/experiments` holds exactly 1 item with that id, and its `n_trials` equals the value after the first POST | holdout |
| AC-16 | The app with two registered experiments | Open `#/signals` | An "Experiments" table lists both, newest first. Its columns are exactly method, category, universe, window, model, decision, trials | evaluator |
| AC-17 | An experiment whose model has a recorded cutoff before its window end | Open it on the Evidence part | The in-window row carries the label `contaminated (in the model's training window)` | evaluator |
| AC-18 | An experiment whose model has no recorded cutoff | Open it on the Evidence part | The text `cutoff unknown: not evidence` is shown | evaluator |
| AC-19 | AC-7's two experiments chosen on the Compare part | Press Compare | It shows `Insufficient data: these signals cannot be separated (36 months, 1 comparison)`. No text on the result says higher, better or winner | evaluator |
| AC-20 | Signed in as `analyst`, an experiment open | Look at the decision controls | Graduate and Shelve are disabled, with `Requires approver` next to them | evaluator |
| AC-21 | The Run part | Open the method picker | Each of `grounded_llm`, `issuer_first`, `embedding_ridge`, `topic_attention`, `finbert` is listed, disabled, with `Run from the CLI or a notebook` next to it | evaluator |
| AC-22 | The Run part with a `price_momentum` recipe and a valid CSV | Submit | The new experiment opens on the Evidence part | evaluator |
| AC-23 | The existing R&D Lab workspace page | Open `#/rdLab` | Its screen list contains `Signals workbench`, linking to `#/signals` | evaluator |
| AC-24 | The existing signals CLI tests in `backend/tests/` | The full backend suite runs | They pass with no edits to those test files | unit |
| AC-25 | One experiment registered with `arp signals run` and one with `Lab.run` | `GET /api/signals/experiments` | Both ids are in the list | holdout |
| AC-26 | Two registered experiments | `GET /api/signals/experiments?sort=ic` | Same order as without the parameter | holdout |
| AC-27 | A `composite` recipe with one `price_momentum` component and one `grounded_llm` component | `POST /api/signals/runs` | 422. `detail` = `grounded_llm runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app` | holdout |
| AC-28 | Each of `issuer_first`, `embedding_ridge`, `topic_attention`, `finbert` | `POST /api/signals/runs` with a recipe of that method | 422. `detail` = `<method> runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app` | holdout |
| AC-29 | AC-13, AC-14, AC-27 or AC-28 just happened | `GET /api/signals/experiments` | The item count is unchanged from before that request | holdout |
| AC-30 | A comparable pair compared once (AC-6) | The same `POST /api/signals/compare` again | Same `verdict`, `months` and `n_comparisons` as the first time. Comparing does not raise `n_comparisons`; only registering more experiments in the scope does | holdout |
| AC-31 | AC-9 just happened | `GET /api/signals/experiments/X` | `decision` = `none` | holdout |
| AC-32 | An `approver`; experiment X registered with a post-cutoff window whose `ic.n` = 12, and `model` = None | `POST .../X/decision` with `{"decision": "graduate"}` | 200. `decision` = `graduate` | holdout |
| AC-33 | An `approver`; experiment X registered with `model` = `m1`, `cutoff` = `2020-01-31`, while the cutoff table now gives `m1` a different date | `POST .../X/decision` with `{"decision": "graduate"}` | 422. `detail` contains `the cutoff for model 'm1' changed since the experiment was evaluated` | holdout |
| AC-34 | AC-11 just happened | `GET /api/signals/experiments/X` | `decision` = `shelve`, `decided_by` = the approver's `user_id` | holdout |
| AC-35 | X already `shelve` and eligible to graduate | `POST .../X/decision` with `{"decision": "graduate"}` | 200. The next `GET` shows `decision` = `graduate`. The previous decision stays in the registry log (`decide` appends; it never edits) | holdout |
| AC-36 | AC-12 just happened, with a price CSV whose prices are all distinct values above 1000 | `GET /api/signals/experiments/<id>` | No number above 1000 appears anywhere in the response body | holdout |
| AC-37 | A run posted with an uploaded CSV | After the response | The uploaded file is no longer on disk | unit |
| AC-38 | The text store seeded with `arp signals ingest-transcripts` (a transcript CSV naming the price file's issuers), and a `narrative_attention` recipe with `terms` = `["growth"]` | `POST /api/signals/runs` with a covering price CSV | 200 with an `experiment_id` | holdout |
| AC-39 | A `grounded_llm` experiment registered through the library | `GET /api/signals/experiments` | Its id is in the list | holdout |
| AC-40 | AC-6's two experiments on the Compare part | Press Compare | It shows `A is higher (36 months, 1 comparison)` with A named by its method and id | evaluator |
| AC-41 | The Run part | Submit a recipe whose window is outside the CSV | The API's `detail` text is shown on the Run part, and no experiment opens | evaluator |
| AC-42 | An experiment whose model has no recorded cutoff, signed in as `approver` | Look at the Graduate button | It is disabled, with `cutoff unknown: not evidence` next to it | evaluator |
| AC-44 | AC-39's experiment | Open `#/signals` | It is a row of the Experiments table | evaluator |
| AC-43 | The existing R&D Lab workspace page | Open `#/rdLab` | It shows a process `Research a signal` with steps Run, Evidence, Compare, Decide, in that order | evaluator |

Must not change:
- CLI behaviour (AC-24).
- Experiment ids for the same inputs (AC-12, AC-15).
- The registry stays append-only (AC-35).
