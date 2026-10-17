# Signals workbench, plan 4: notebook library and honest comparison

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A notebook user can load data, try a method without registering it (clearly labelled "unregistered, not evidence"), run and register a recipe, and compare two registered signals, getting "insufficient data" when they cannot be separated. All of it goes through the same code as `arp signals run`.

**Architecture:** One facade class, `Lab`, in `backend/arp/signal_lab/lab.py`, over what plans 1 to 3 built (registry, `run_recipe`, methods, text store, CSV sources). Two gaps found in plan 3's final review are closed first, because the notebook and the app both need them:
- **Comparison.** `compare_signals` (plan 1's paired bootstrap) exists but nothing calls it, so two signals can't be ranked honestly today. Evidence starts keeping its monthly net long-short series, and `compare_experiments` adds the comparison with a correction for the number of comparisons.
- **Price history.** Prices before the recipe window can feed the methods (walk-forward training, 12-month momentum) without entering the evidence.

Example notebooks are plain-Python percent-format scripts (`# %%`), runnable without Jupyter and opened as notebooks with jupytext.

**Tech Stack:** Python 3.11, pydantic v2, typer, existing plan 1 to 3 modules. Jupyter and jupytext go in an optional extra; **no change to core dependencies.**

**Spec:** `docs/superpowers/specs/2026-10-14-signals-workbench-design.md` (Components 5 and 6, Guardrails "Ranking", "Calls made after a builder read": Enforcement, Insufficient data). Base: plans 1 to 3, merged (PRs #146, #148, #156).

## Roadmap (plan 4 of 5)

1. Evidence core and registry (done).
2. Text store and adapters (done).
3. Methods (done).
4. **This plan.**
5. App screens and API.

Not in this plan: a hosted notebook server (the spec's "My calls" say notebooks run locally); plotting helpers (notebooks use whatever the user likes on the returned data); size/sector-neutral and value-weighted evidence views; any UI.

## Global Constraints

- Python `>=3.11`; every module starts with `from __future__ import annotations`; no new core dependencies. `jupyterlab` and `jupytext` go in an optional extra named `notebooks`.
- **Registration is the enforcement point.** Anything ranked, compared or graduated is a registered experiment. Output that is not registered is labelled exactly `unregistered, not evidence` and has no experiment id, so it cannot be compared or graduated.
- **Insufficient data is an answer.** Two signals are ordered only if `compare_signals` says so; otherwise the result is `insufficient_data`. Only post-cutoff months count. Signals are compared only when they share universe, window and cost.
- **No look-ahead.** Price history before `window_start` may feed methods, but evidence covers only `window_start..window_end` (plan 1's `evaluate_signal` already restricts by the spec window). The history start is part of the experiment's identity.
- Issuer key is the one identity; canonical times as in plans 2 and 3; user-caused errors raise `ValueError` with a clear message; `None`, not `0.0`, for absent values.
- Backend checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`. Postgres tests need `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test` (restart: `bash .claude/hooks/ensure-deps.sh postgres`).
- Never delete or weaken an existing test. Comments only for the why. Do not touch adjacent code. PRs target `main`.

## Review Focus

1. **A comparison never ranks what the data cannot separate.** Fewer than 12 common post-cutoff months, or a bootstrap that does not exclude zero, is `insufficient_data`. (Task 2)
2. **No comparison across different universes, windows or costs**, and none against an experiment registered before the series was stored. (Task 2)
3. **History feeds methods, never evidence**: the same recipe with and without earlier price history gives identical evidence months, and the two are different experiments. (Task 3)
4. **An unregistered preview cannot pass as evidence**: no experiment id, the label is shown wherever it is printed, and `compare` and `decide` refuse it. (Task 4)
5. **The notebook and the CLI give identical results** for the same recipe and data (same experiment id, same evidence). (Tasks 4, 5)

## File structure

| File | Responsibility |
|---|---|
| `backend/arp/signal_lab/evidence.py` | modify: `WindowEvidence.series` (monthly net long-short) |
| `backend/arp/signal_lab/compare.py` | `compare_experiments`, `Comparison` |
| `backend/arp/signal_lab/inputs.py` | `data_version_for`, `load_inputs` (shared by CLI and `Lab`) |
| `backend/arp/signal_lab/methods/base.py` | modify: `panel` method takes an optional `model` |
| `backend/arp/signal_lab/lab.py` | `Lab`, `Preview` |
| `backend/arp/cli/signal_lab.py` | modify: `compare` command, `run --history-from`, `run` uses `load_inputs` |
| `notebooks/signals/narrative_momentum.py`, `notebooks/signals/README.md` | example notebook (percent format) and how to open it |
| `backend/pyproject.toml` | modify: optional extra `notebooks` |
| `docs/TECHNICAL_REFERENCE.md` | modify: `compare`, `--history-from`, the notebook library |
| `backend/tests/test_signal_lab_compare.py`, `test_signal_lab_inputs.py`, `test_signal_lab_lab.py`, `test_signal_lab_notebook_example.py` | tests |

---

### Task 1: Evidence keeps its monthly series

**Files:**
- Modify: `backend/arp/signal_lab/evidence.py`
- Test: `backend/tests/test_signal_lab_evidence.py` (add tests; change none)

**Interfaces:**
- Consumes: plan 1's `evaluate_signal`, `WindowEvidence`.
- Produces: `WindowEvidence.series: list[tuple[str, float]] = []` holds `(period_end, net long-short return in percent)` for each backtest period of that window, the same values `evaluate_signal` already computes for the deflated Sharpe (gross when cost is zero). Rows registered before this change load with `[]`.

- [ ] **Step 1: Write the failing tests:** `test_window_series_matches_the_deflated_sharpe_input` (the series' values equal the list passed to the deflated Sharpe, and its dates are the window's backtest period ends, in order); `test_old_evidence_rows_without_series_still_load` (validate a dict without `series`).
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run** the evidence and registry tests and ruff. Expected: PASS, existing tests unchanged.
- [ ] **Step 5: Commit** `feat(signal-lab): evidence keeps the monthly long-short series`.

---

### Task 2: Compare two registered experiments honestly

**Files:**
- Create: `backend/arp/signal_lab/compare.py`
- Modify: `backend/arp/cli/signal_lab.py` (`compare` command)
- Test: `backend/tests/test_signal_lab_compare.py` (uses `pg` and the registry like `tests/test_signal_lab_registry.py`)

**Interfaces:**
- Consumes: Task 1; `Registry`, `ExperimentRecord`; `compare_signals` (`arp/signal_lab/stats.py`, returns `"a_higher" | "b_higher" | "insufficient_data"`, needs `n_comparisons`).
- Produces: `class Comparison(BaseModel)`: `a: str`, `b: str`, `verdict: Literal["a_higher", "b_higher", "insufficient_data"]`, `months: int`, `n_comparisons: int`, `reason: str | None`. `compare_experiments(a_id: str, b_id: str, registry: Registry, *, confidence: float = 0.95) -> Comparison`:
  - Both ids must be registered (`ValueError` naming the unknown one) and different.
  - They must share `recipe.universe`, `window_start`, `window_end` and `cost_bps`; otherwise `ValueError("not comparable: ...")` naming the field that differs.
  - It uses each experiment's `post_cutoff` window series. An experiment without a post-cutoff window gives `insufficient_data` with reason `"no post-cutoff evidence for <id>"`. An experiment whose post-cutoff window has an empty series (registered before Task 1) gives `ValueError("<id> was registered before series were stored; re-run it")`.
  - The two series are aligned on common period ends only.
  - `n_comparisons = k * (k - 1) / 2`, with `k` the number of registered experiments sharing that universe, window and cost (at least 1). Every pair that could be compared counts, so asking more questions makes each answer harder to win.
  - It calls `compare_signals(a_series, b_series, n_comparisons=..., confidence=...)` and sets `months` to the common count.
  - CLI: `arp signals compare A B [--confidence 0.95]` prints `<verdict> (<months> common post-cutoff months, corrected for <n> comparisons)` plus the reason if any. `ValueError` exits 1 with the message.

- [ ] **Step 1: Write the failing tests** (register synthetic experiments directly with crafted `EvidenceReport`s, so no backtest is needed):
  - `test_clearly_better_signal_is_ranked`: 36 common months where A beats B by a wide, steady margin gives `a_higher`, with `n_comparisons == 1` for two experiments in scope.
  - `test_noise_is_insufficient_data` (Review Focus 1): two near-identical noisy series give `insufficient_data`.
  - `test_fewer_than_12_common_months_is_insufficient_data` (Review Focus 1).
  - `test_more_experiments_in_scope_raise_the_bar`: the same pair that was `a_higher` with 2 experiments becomes `insufficient_data` once enough experiments are registered in the scope (pick a margin that crosses the corrected threshold; assert `n_comparisons` grows as k(k-1)/2).
  - `test_different_universe_window_or_cost_raises` (Review Focus 2), parametrised over the three fields.
  - `test_no_post_cutoff_window_is_insufficient_with_reason`; `test_old_row_without_series_raises_rerun`; `test_unknown_or_same_id_raises`.
  - CLI: `test_cli_compare_prints_verdict_and_counts`; `test_cli_compare_unknown_id_exits_1`.
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): compare registered experiments with insufficient-data verdicts`.

---

### Task 3: Shared inputs, price history and labelled panels

**Files:**
- Create: `backend/arp/signal_lab/inputs.py`
- Modify: `backend/arp/cli/signal_lab.py` (`run` uses `load_inputs`; new `--history-from`), `backend/arp/signal_lab/methods/base.py` (`panel` method's optional `model`)
- Test: `backend/tests/test_signal_lab_inputs.py`; add to `backend/tests/test_signal_methods_base.py` and `backend/tests/test_signal_lab_cli_run.py` (change no existing test)

**Interfaces:**
- Consumes: plan 3's `MethodInput`, `TextStore`, `CsvPriceSource`, `CsvCharacteristicSource`, `read_wide_csv`, the run command's current data-version rule.
- Produces:
  - `data_version_for(item_ids: list[str], price_bytes: bytes, panel_bytes: dict[str, bytes], history_from: str | None) -> str`. It is the hash the run command uses today (sorted item ids joined by newlines, then price bytes, then panel bytes in sorted name order), with `history_from` appended when given, so runs without it keep their current ids. First 12 hex characters.
  - `load_inputs(recipe: Recipe, prices: Path, *, panels: dict[str, Path] | None = None, texts: list[TextRecord] | None = None, history_from: str | None = None) -> tuple[MethodInput, str]` returns the `MethodInput` and its `data_version`. Prices and panels load from `history_from` (default `recipe.window_start`) to `recipe.window_end`. It raises `ValueError` if the recipe window, or `history_from`, lies outside the price file, or if `history_from` is after `window_start`.
  - The `run` command builds its inputs through `load_inputs` (its behaviour without `--history-from` is unchanged, so existing experiment ids are unchanged) and takes `--history-from ISO`.
  - The `panel` method accepts `params: {"name": str, "model": str | None}`; `model` is returned in `MethodResult.model` so a precomputed model panel is split at that model's cutoff. Its type is checked (`ValueError` unless str or None).

- [ ] **Step 1: Write the failing tests:**
  - `test_data_version_unchanged_without_history` (equals the value the run command computed before this task for a fixed input; compute it from the old rule in the test).
  - `test_history_changes_the_data_version`.
  - `test_history_feeds_methods_not_evidence` (Review Focus 3): run the same `price_momentum` recipe through `run_recipe` with and without 12 months of history. Both report the same evidence months (window periods), and the momentum values at the first window month differ (`None` without history, a number with it).
  - `test_history_after_window_start_raises`; `test_window_outside_price_file_raises`.
  - `test_panel_method_passes_model_through`; `test_panel_method_rejects_non_string_model`.
  - CLI: `test_run_with_history_from_registers_a_different_experiment`; existing run tests still pass unchanged.
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run** the new tests, `tests/test_signal_lab_cli_run.py`, `tests/test_signal_methods_base.py` and ruff. Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): shared inputs, price history and model-labelled panels`.

---

### Task 4: The `Lab` notebook facade

**Files:**
- Create: `backend/arp/signal_lab/lab.py`
- Test: `backend/tests/test_signal_lab_lab.py` (uses `pg`)

**Interfaces:**
- Consumes: Tasks 1 to 3; `Registry`, `run_recipe`, `run_method`, `lookahead_violations`, `summarize_ic`/`rank_ic_series`, `load_cutoff_table`, `TextStore`, `Recipe`, `get_settings`, the run store used by the CLI (`arp.cli._shared._run_store`'s construction, reused, not duplicated).
- Produces:
  - `UNREGISTERED = "unregistered, not evidence"`.
  - `@dataclass Preview(panel: CharacteristicPanel, model: str | None, notes: dict, ic: IcSummary, label: str = UNREGISTERED)`. Its `__repr__` starts with `[unregistered, not evidence]`. It has no experiment id.
  - `class Lab` with `__init__(self, *, registry: Registry, cutoffs: CutoffTable, text_store: TextStore | None = None)` and `Lab.from_settings()`, which builds all three from settings the way the CLI does.
    - `texts(self, *, known_by: str | None = None) -> list[TextRecord]` (`ValueError` without a text store).
    - `inputs(self, recipe, prices, *, panels=None, texts=None, history_from=None)` wraps `load_inputs`.
    - `preview(self, spec: dict, inp: MethodInput) -> Preview` runs the method and computes the rank-IC summary over the whole grid. It registers nothing and changes no trial count.
    - `check(self, spec, inp, *, at=None) -> list[tuple[str, int]]` wraps `lookahead_violations`.
    - `run(self, recipe: Recipe, inp: MethodInput, data_version: str) -> ExperimentRecord` wraps `run_recipe`.
    - `experiments(self) -> list[ExperimentRecord]`.
    - `compare(self, a: str, b: str, *, confidence=0.95) -> Comparison` takes experiment ids only; a `Preview` passed in raises `ValueError("a preview is unregistered, not evidence; run it first")`.
    - `decide(self, experiment_id, decision, *, approver)` wraps `Registry.decide` with the cutoff table.
    - `save_recipe(recipe, path)` and `load_recipe(path) -> Recipe` write and read JSON, validating with `Recipe.model_validate`.

- [ ] **Step 1: Write the failing tests:**
  - `test_preview_registers_nothing_and_is_labelled` (Review Focus 4): the trial count and the experiment list are unchanged after a preview, `repr` starts with the label, and the object has no `experiment_id`.
  - `test_compare_and_decide_refuse_a_preview` (Review Focus 4).
  - `test_lab_run_matches_the_cli_run` (Review Focus 5): for the same recipe file and price CSV, `Lab.run` and `arp signals run` give the same experiment id and the same evidence.
  - `test_recipe_round_trips_through_json`; `test_load_recipe_rejects_invalid_files`.
  - `test_texts_without_a_text_store_raises`.
  - `test_check_finds_a_peeking_method` (reuse the peeking-method pattern from `tests/test_signal_methods_base.py`).
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): Lab notebook facade with labelled previews`.

---

### Task 5: Example notebook, extra and docs

**Files:**
- Create: `notebooks/signals/narrative_momentum.py`, `notebooks/signals/README.md`
- Modify: `backend/pyproject.toml` (optional extra `notebooks = ["jupyterlab>=4,<5", "jupytext>=1.16,<2"]`, touching no other entry), `docs/TECHNICAL_REFERENCE.md` (the `arp signals` entry)
- Test: `backend/tests/test_signal_lab_notebook_example.py` (uses `pg`)

**Interfaces:**
- Consumes: Task 4's `Lab`.
- Produces:
  - A percent-format script with `# %%` cells, readable top to bottom. It loads a price CSV and a transcript CSV from paths given by environment variables (`ARP_NB_PRICES`, `ARP_NB_TRANSCRIPTS`; the README says so), and ingests the transcripts. It then previews a `narrative_attention` spec and prints the labelled preview, checks look-ahead, and runs it as a registered recipe with history. Finally it runs a second variant (`transform` z-score of the first), compares the two and prints the verdict.
  - The README explains how to open it as a notebook (`pip install 'arp[notebooks]'`, `jupytext --to ipynb` or opening the `.py` directly in JupyterLab with jupytext), and that previews are not evidence.
  - TECHNICAL_REFERENCE gains `compare`, `--history-from`, and a short "Notebook library" paragraph naming `Lab` and its methods.

- [ ] **Step 1: Write the failing test:** `test_example_notebook_runs_end_to_end` writes synthetic CSVs (reuse the helpers in `tests/test_signal_lab_cli.py` and `tests/test_signal_lab_cli_run.py`), sets the environment variables and the run-store settings as those tests do, executes the script with `runpy.run_path`, and asserts that the output contains `[unregistered, not evidence]`, an `experiment_id`, and one of the three verdict words.
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement** the script, README, extra and docs.
- [ ] **Step 4: Run** the new test, then `python3 -m pytest tests -q -k "signal_lab or signal_methods or news or replication"`, `ruff check .` and `python3 -c "import arp.cli"`. Expected: PASS (one known browser-dependent reporting test and one known flaky extraction test may fail; both unrelated).
- [ ] **Step 5: Commit** `feat(signal-lab): example narrative-momentum notebook and docs`.

---

## Self-review

- **Spec coverage:**
  - Component 6, the notebook library: Tasks 4 and 5.
  - "A signal built in a notebook is saved as a recipe": `save_recipe` and the registry (the app reads the registry in plan 5).
  - Enforcement, where unregistered output is labelled and cannot be graduated: Task 4.
  - Insufficient data and the comparison correction: Task 2.
  - Identical results from app and notebook: the shared `load_inputs` and `run_recipe`, Tasks 3 and 4.
  - The two plan-3 final-review recommendations (history, labelled panels): Task 3.
- **Step scan:** every step names a signature, test or command.
- **Type consistency:** `WindowEvidence.series`, `Comparison`, `compare_experiments`, `data_version_for`, `load_inputs`, `Preview`, `UNREGISTERED`, `Lab` are each defined once and reused.
- **Owner flags:**
  - The comparison correction counts every pair in the scope, `k(k-1)/2`. That is conservative: more experiments make each ranking harder to win.
  - Only post-cutoff months are compared.
  - Notebooks are `.py` percent scripts, not `.ipynb`, so they diff and test cleanly.
