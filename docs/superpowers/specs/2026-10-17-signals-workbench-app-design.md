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
   - "No recorded cutoff" means the experiment names a `model` that is absent from the cutoff table. Such an experiment shows `cutoff unknown: not evidence`, and the API refuses to graduate it. An experiment with `model` = None used no trained model and shows no cutoff label.
4. **Decisions need the approver role.** The approver is the signed-in user (`require_role("approver")`, recorded as `user_id`).
   - Graduation keeps the registry's gate: at least 12 post-cutoff IC months, and a cutoff unchanged since evaluation.
   - Starting a run needs `analyst`, because it writes to the registry. Reading, listing and comparing need any signed-in user.
   - Decisions are appended to the registry's log, never edited in place. The latest decision is the one shown, and a later decision may replace an earlier one.
5. **The Run part takes a recipe JSON upload and a prices CSV upload.** A method list next to them shows which methods the app can run. **Prices are uploaded with the run**, as a wide CSV of calendar month-end dates, the same file the CLI takes.
   - Text comes from the text store.
   - The uploaded file is deleted after every run, accepted or refused, and nothing in the registry record holds price values.
6. **`#/rdLab` is the existing R&D Lab workspace page.** It gains one screen link and one process. The new R&D Lab landing page (overview design) is a separate item and is not built here.

## Not in this spec

- The new R&D Lab landing page (overview design, own item).
- Asynchronous jobs for LLM methods.
- Editing or deleting experiments.
- Plots beyond what the existing chart components already draw.
- The notebook server.

## Acceptance

Setup notes for the test-writer:
- The API, `arp signals` and `Lab` all read and write the same registry: the run store built from the `ARP_POSTGRES_DSN` and `ARP_RUNS_DIR` settings on `main` (`RunStore(dsn, runs_dir)`), plus the cutoff table at `ARP_TRAINING_CUTOFFS_PATH` (JSON mapping a model name to `{"cutoff": "YYYY-MM-DD", "source": "..."}`). Tests set these environment variables, register through the library, and start the app with the same values.
- "Registered with series" means `Registry(RunStore(dsn, runs_dir)).register(recipe, EvidenceReport(windows=[WindowEvidence(window="post_cutoff", periods=n, ic=IcSummary(n=..., mean=..., t_nw=..., hit_rate=...), long_short=None, net_long_short=None, monthly_turnover_pct=None, deflated_sharpe=None, series=[(period_end, value), ...])], contamination_gap_ic=None, overlap={}, n_trials=1), data_version=..., model=..., cutoff=...)`.
- "Comparable" means the same `universe`, `window_start`, `window_end` and `cost_bps`. The comparison scope of an experiment is every registered experiment comparable to it.
- Roles come from the existing users file: `viewer` < `analyst` < `approver`. Listing, reading, the method list and compare accept any signed-in user (`viewer` and up); `POST /api/signals/runs` needs `analyst`; decisions need `approver`. Holdout tests call reads as `viewer` and runs as `analyst`.
- The text store is `TextStore(dsn)` on the same `ARP_POSTGRES_DSN` that the API and `arp signals` read; seeding it with `arp signals ingest-transcripts` under that DSN makes the texts visible to both.
- Dates are `YYYY-MM-DD` throughout.
- A price CSV *covers* a recipe when its earliest date ≤ `window_start` and its latest date ≥ `window_end`. The range in AC-14's message is the CSV's earliest..latest date. The app adds no lookback requirement of its own. A *runnable* price CSV for a recipe is one that covers it and for which `arp signals run --recipe <file> --prices <file>` (plus any `--panel name=<file>` arguments and the text store the row names) exits 0 and prints an `experiment_id:` line; every row that expects a 200 from `POST /api/signals/runs` uses a runnable CSV.
- Holdout tests run the app with `ARP_AUTH_MODE=local` (not `dev`) and sign in with a bearer token from the users file.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Two experiments registered | `GET /api/signals/experiments` | 200. JSON array of 2 items. Each item has at least the keys `experiment_id`, `category`, `method`, `universe`, `window_start`, `window_end`, `cost_bps`, `model`, `cutoff`, `decision`, `n_trials`, `created_at` | holdout |
| AC-2 | Experiment A registered first, with post-cutoff `ic.mean` = 0.20; experiment B registered after it, with `ic.mean` = 0.01 | `GET /api/signals/experiments` | B is item 0, A is item 1, also when A and B have the same `created_at`. Order is the reverse of registration order | holdout |
| AC-3 | A registered experiment `X` | `GET /api/signals/experiments/X` | 200. Body has the keys `experiment_id`, `recipe`, `notes`, `model`, `cutoff`, `decision`, `decided_by`, `evidence`. Each equals the same key of `model_dump(mode="json")` of X's record in `Registry.list_experiments()` (`decision` = the JSON string `"none"` and `decided_by` = null when undecided) | holdout |
| AC-4 | No experiment `nope` | `GET /api/signals/experiments/nope` | 404, `detail` = `unknown experiment 'nope'` | holdout |
| AC-5 | `main`'s method registry | `GET /api/signals/methods` | 200. The set of `name` values equals the registered method names. `runnable_in_app` is true for exactly `panel`, `price_momentum`, `narrative_attention`, `sestm`, `transform`, `composite`, and false for every other name | holdout |
| AC-6 | A and B comparable and registered with series over the same 36 post-cutoff period ends: A's month i = `0.10 + 0.01 * (-1)**i`, B's month i = `0.01 * (-1)**(i + 1)`. No other experiment comparable to A is registered | `POST /api/signals/compare` with `{"a": "<id of A>", "b": "<id of B>"}` | 200. Body has `verdict` = `a_higher`, `months` = 36, `n_comparisons` = 1 | holdout |
| AC-7 | No other experiment comparable to A registered; A and B comparable and registered with identical series over 36 post-cutoff period ends (month i = `0.01 * (-1)**i`) | `POST /api/signals/compare` | 200. `verdict` = `insufficient_data`, `months` = 36 | holdout |
| AC-8 | A and B registered with different `universe` | `POST /api/signals/compare` | 422. `detail` starts with `not comparable: universe differs` | holdout |
| AC-9 | A signed-in `analyst`; experiment X with `decision` = `none` | `POST /api/signals/experiments/X/decision` with `{"decision": "graduate"}` | 403 | holdout |
| AC-10 | An `approver`; X registered with a post-cutoff window whose `ic.n` = 5 and `model` = None | `POST .../X/decision` with `{"decision": "graduate"}` | 422. `detail` contains `needs post-cutoff evidence with at least 12 IC months` | holdout |
| AC-11 | An `approver`; experiment X | `POST .../X/decision` with `{"decision": "shelve"}` | 200. Body has `decision` = `shelve` and `decided_by` = the approver's `user_id` from `GET /api/me` | holdout |
| AC-12 | A `price_momentum` recipe and a runnable month-end price CSV | `POST /api/signals/runs` (multipart: file part `recipe` holding the recipe JSON, file part `prices` holding the CSV) | 200. Body has `experiment_id`, equal to the id `arp signals run --recipe <same file> --prices <same file>` prints on its `experiment_id:` line | holdout |
| AC-13 | A `grounded_llm` recipe | `POST /api/signals/runs`, multipart with `recipe` and a covering `prices` CSV | 422. `detail` = `grounded_llm runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app` | holdout |
| AC-14 | A `price_momentum` recipe with window 2019-01-31..2021-12-31 and a month-end price CSV whose earliest date is 2020-01-31 and latest date is 2022-12-31 | `POST /api/signals/runs` | 422. `detail` = `recipe window 2019-01-31..2021-12-31 is outside the price file 2020-01-31..2022-12-31` | holdout |
| AC-15 | The same `price_momentum` recipe and CSV | `POST /api/signals/runs` twice | Both 200 with the same `experiment_id` | holdout |
| AC-16 | The app with two registered experiments | Open `#/signals` | The "Experiments" table lists both, newest first | evaluator |
| AC-17 | An experiment with `model` = `m1`, where `m1` is in the cutoff table with cutoff `2020-01-31`, registered with two windows, `WindowEvidence(window="in_window", ...)` and `WindowEvidence(window="post_cutoff", ...)` | Open it on the Evidence part | The `in_window` row carries the label `contaminated (in the model's training window)` | evaluator |
| AC-18 | An experiment with `model` = `m_unknown`, absent from the cutoff table | Open it on the Evidence part | The text `cutoff unknown: not evidence` is shown | evaluator |
| AC-19 | AC-7's two experiments chosen on the Compare part, and no other experiment comparable to A registered | Press Compare | It shows `Insufficient data: these signals cannot be separated (36 months, 1 comparison)`. No text on the result says higher, better or winner | evaluator |
| AC-20 | Signed in as `analyst`, an experiment open | Look at the decision controls | Graduate and Shelve are disabled, with `Requires approver` next to them | evaluator |
| AC-21 | The Run part | Look at its method list | Each of `grounded_llm`, `issuer_first`, `embedding_ridge`, `topic_attention`, `finbert` is listed, marked `Run from the CLI or a notebook` | evaluator |
| AC-22 | The Run part, a `price_momentum` recipe JSON file and a runnable CSV uploaded | Submit | The new experiment opens on the Evidence part | evaluator |
| AC-23 | The existing R&D Lab workspace page | Open `#/rdLab` | Its screen list contains `Signals workbench`, linking to `#/signals` | evaluator |
| AC-24 | The existing tests for `arp signals` and `arp.signal_lab` in `backend/tests/` | The full backend suite runs | They pass with no edits to those test files | unit |
| AC-25 | One experiment registered with `arp signals run` and one with `Lab.run` | `GET /api/signals/experiments` | Both ids are in the list | holdout |
| AC-26 | AC-2's A and B (A registered first with post-cutoff `ic.mean` = 0.20, B after it with 0.01) | `GET /api/signals/experiments?sort=ic` | 200. The `experiment_id` order is B, A | holdout |
| AC-27 | A `composite` recipe with one `price_momentum` component and one `grounded_llm` component | `POST /api/signals/runs`, multipart with `recipe` and a covering `prices` CSV | 422. `detail` = `grounded_llm runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app` | holdout |
| AC-28 | Each of `issuer_first`, `embedding_ridge`, `topic_attention`, `finbert` | `POST /api/signals/runs`, multipart with a recipe of that method and a covering `prices` CSV | 422. `detail` = `<method> runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app` | holdout |
| AC-29 | AC-13, AC-14, AC-27 or AC-28 just happened | `GET /api/signals/experiments` | The item count is unchanged from before that request | holdout |
| AC-30 | AC-6 done once | The same `POST /api/signals/compare` again | Same `verdict`, `months` and `n_comparisons` as the first time | holdout |
| AC-31 | AC-9 just happened | `GET /api/signals/experiments/X` | `decision` = the JSON string `"none"` | holdout |
| AC-32 | An `approver`; X registered with a post-cutoff window whose `ic.n` = 12, and `model` = None | `POST .../X/decision` with `{"decision": "graduate"}` | 200. `decision` = `graduate` | holdout |
| AC-33 | An `approver`; X registered with a post-cutoff window whose `ic.n` = 12, `model` = `m1`, `cutoff` = `2020-01-31`; the cutoff table file is then rewritten, while the app is running, to give `m1` the cutoff `2021-01-31` (the app reads `ARP_TRAINING_CUTOFFS_PATH` on each decision request) | `POST .../X/decision` with `{"decision": "graduate"}` | 422. `detail` contains `the cutoff for model 'm1' changed since the experiment was evaluated` | holdout |
| AC-34 | AC-11 just happened | `GET /api/signals/experiments/X` | `decision` = `shelve`, `decided_by` = the approver's `user_id` | holdout |
| AC-35 | An `approver`; X already `shelve`, with a post-cutoff window whose `ic.n` = 12 and `model` = None | `POST .../X/decision` with `{"decision": "graduate"}` | 200. Body `decision` = `graduate` | holdout |
| AC-36 | AC-12 just happened, with a price CSV whose prices are all distinct values above 1000 | `GET /api/signals/experiments/<id>` | No JSON number value in the body equals any price value in the uploaded CSV | holdout |
| AC-37 | A run posted with an uploaded CSV, once accepted (AC-12) and once refused (AC-14) | After each response | The uploaded file is no longer on disk | unit |
| AC-38 | The text store seeded with `arp signals ingest-transcripts` (a transcript CSV naming the price file's issuers), and a `narrative_attention` recipe with `terms` = `["growth"]` | `POST /api/signals/runs` with a covering price CSV | 200. `experiment_id` equals the id `arp signals run` prints for the same recipe, price file and text store | holdout |
| AC-39 | A `grounded_llm` experiment registered through the library | `GET /api/signals/experiments` | Its id is in the list | holdout |
| AC-40 | AC-6's two experiments on the Compare part | Press Compare | It shows `<A's method> <A's experiment_id> is higher (36 months, 1 comparison)` | evaluator |
| AC-41 | The Run part | Submit AC-14's recipe and CSV | The API's `detail` text is shown on the Run part, and no experiment opens | evaluator |
| AC-42 | AC-18's experiment, signed in as `approver` | Look at the Graduate button | It is disabled, with `cutoff unknown: not evidence` next to it | evaluator |
| AC-43 | The existing R&D Lab workspace page | Open `#/rdLab` | It shows a process `Research a signal` with steps Run, Evidence, Compare, Decide, in that order | evaluator |
| AC-44 | AC-39's experiment | Open `#/signals` | It is a row of the Experiments table | evaluator |
| AC-45 | AC-15 just happened | `GET /api/signals/experiments` | Exactly 1 item has that id, and its `n_trials` equals the value after the first POST | holdout |
| AC-46 | The app with two registered experiments | Open `#/signals` | The Experiments table's columns are exactly method, category, universe, window, model, decision, trials | evaluator |
| AC-47 | AC-6's A and B, plus a third experiment C comparable to them, registered with series | The AC-6 compare | `n_comparisons` = 3 (every pair in the scope: k(k-1)/2 with k = 3) | holdout |
| AC-48 | AC-35 just happened | `GET /api/signals/experiments/X` | `decision` = `graduate` | holdout |
| AC-49 | AC-35 just happened | `Registry(...).store.read_results("signal_registry")` | Two rows with `type` = `decision` for X, in order `shelve`, `graduate` | holdout |
| AC-50 | An `approver`; X registered with a post-cutoff window whose `ic.n` = 12, `model` = `m_unknown` absent from the cutoff table | `POST .../X/decision` with `{"decision": "graduate"}` | 422. `detail` contains `cutoff unknown: not evidence` | holdout |
| AC-51 | A recipe and a runnable CSV, for each of `panel` (recipe `params.name` = `p1`, with the panel CSV the CLI takes as `--panel p1=<file>` sent as file part `panel_p1`), `sestm` (text store seeded as in AC-38), `transform` over `price_momentum`, and `composite` of two `price_momentum` components | `POST /api/signals/runs` | 200 with an `experiment_id` | holdout |
| AC-52 | AC-17's experiment | Open it on the Evidence part | The `in_window` row shows its `ic.mean`, `ic.t_nw` and `ic.n` values | evaluator |
| AC-53 | Signed in as `approver`, an undecided experiment open | Press Shelve | The decision shown becomes `shelve`, with the approver's user id | evaluator |
| AC-54 | The existing R&D Lab workspace page | Open `#/rdLab` | Every screen and process it lists on `main` is still listed | evaluator |
| AC-55 | An experiment registered with `model` = None | Open it on the Evidence part | Neither `contaminated (in the model's training window)` nor `cutoff unknown: not evidence` appears on the page | evaluator |
| AC-56 | A signed-in `viewer`; a recipe and a covering price CSV | `POST /api/signals/runs` | 403, and the experiment count from `GET /api/signals/experiments` is unchanged | holdout |
| AC-57 | No `Authorization` header | Each of `GET /api/signals/experiments`, `GET /api/signals/methods`, `POST /api/signals/compare` | 401. `detail` = `Missing or invalid bearer token` | holdout |

Must not change:
- CLI and library behaviour (AC-24).
- Experiment ids for the same inputs (AC-12, AC-15, AC-38).
- The registry stays append-only (AC-49).
- The R&D Lab page's existing screens and processes (AC-54).
