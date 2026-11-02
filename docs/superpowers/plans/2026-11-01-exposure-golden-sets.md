# Exposure Golden Sets (A3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A validated file format and CLI for company-level exposure golden sets, plus three checked sets (electrolyser makers, AI data-centre operators, water-scarcity exposed) with a deterministic tune/holdout split.

**Architecture:** A pydantic model validates `cases.json`; three subcommands (`validate`, `split`, `stats`) under `arp golden-set exposure`; the three sets live as data under `backend/tests/golden/exposure/`. No model or LLM is involved; labelling is research plus human checking.

**Tech Stack:** Python 3.11, pydantic v2, Typer (existing `golden_set_app`), pytest with `typer.testing.CliRunner`.

**Spec:** `docs/superpowers/specs/2026-11-01-exposure-golden-sets-design.md` (approved 2026-11-01).

## Global Constraints

- Location: `backend/tests/golden/exposure/<set_id>/cases.json`; documents under `…/<set_id>/documents/` only when the licence allows.
- Required set keys: `set_id, kind, subject, labels, checked_on (ISO date), cases`. Required case keys: `case_id, company, label, role, rationale, label_sources (≥ 1, each http(s) URL), documents (≥ 1, each with url or path; a path must exist under documents/)`. Optional: `lei, isin, split`.
- `kind` ∈ {`activity`, `risk`}. Risk labels: `exposed_disclosed`, `exposed_undisclosed`, `not_exposed`.
- Split rule: cases sorted by `case_id`; within each label, every second case `holdout`, starting with the first; existing `split` never changed.
- `stats` line format: `<label> tune=<n> holdout=<n>`.
- Each set ≥ 55 cases; every label ≥ 8 `holdout`.
- Commands: `arp golden-set exposure validate|split|stats --set <dir>`; `validate` exits 1 and prints each problem.

## Review Focus

1. **Non-UTF-8 or invalid JSON file**: `validate` prints `cases.json: invalid JSON (<error>)` and exits 1, no traceback. → test in Task 1.
2. **`split` on a file with mixed existing/missing splits across labels**: only missing ones are assigned, counting position within the label among all cases (sorted), so re-running gives the same result. → test in Task 2.
3. **Company names with non-ASCII characters** (e.g. "Hexagon Purus ASA", "LONGi 隆基"): written back by `split` unchanged (`ensure_ascii=False`, key order preserved). → test in Task 2.
4. **A path with `..`** (`documents[].path = "../x.pdf"`): rejected, since documents must be under `documents/`. → test in Task 1.
5. **Empty `cases` list**: `validate` reports `cases: empty` and exits 1. → test in Task 1.

---

### Task 1: Schema and `validate`

**Files:**
- Create: `backend/arp/golden_set/exposure.py`
- Modify: `backend/arp/cli/golden_set.py` (add `exposure_app = typer.Typer()` registered as `golden_set_app.add_typer(exposure_app, name="exposure")`)
- Test: `backend/tests/test_golden_exposure.py`, fixtures under `backend/tests/fixtures/golden_exposure/`

**Interfaces:**
- Produces: `ExposureSet`, `ExposureCase`, `ExposureDocument` (pydantic); `validate_set(set_dir: Path) -> list[str]` returning human-readable problems, each containing the `case_id` (when case-level) and the field name; `load_set(set_dir: Path) -> ExposureSet`.

- [ ] **Step 1: Write failing tests** (one per spec row, each builds a small `cases.json` in `tmp_path` and runs `CliRunner().invoke(app, ["golden-set", "exposure", "validate", "--set", str(d)])`):

```python
@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["cases"][0].pop("label_sources"), "label_sources"),        # AC-1
    (lambda c: c["cases"][0].update(label_sources=[]), "label_sources"),     # AC-2
    (lambda c: c["cases"][0].update(label_sources=["see report"]), "label_sources"),  # AC-3
    (lambda c: c["cases"][0].pop("rationale"), "rationale"),                 # AC-4
    (lambda c: c["cases"][0].update(label="maybe"), "maybe"),                # AC-5
    (lambda c: c["cases"].append(dict(c["cases"][0])), "c1"),                # AC-6 (duplicate id c1)
    (lambda c: c.update(kind="sector"), "kind"),                             # AC-7
    (lambda c: c.pop("checked_on"), "checked_on"),                           # AC-8
    (lambda c: c.update(checked_on="last week"), "checked_on"),              # AC-9
    (lambda c: c["cases"][0].update(documents=[{"kind": "annual_report"}]), "documents"),  # AC-10
    (lambda c: c["cases"][0].update(documents=[{"path": "missing.pdf"}]), "missing.pdf"),  # AC-11
    (lambda c: c["cases"][0].update(documents=[{"path": "../x.pdf"}]), "../x.pdf"),        # Review Focus 4
    (lambda c: c.update(cases=[]), "cases"),                                 # Review Focus 5
])
def test_validate_rejects(tmp_path, mutate, needle): ...
    # assert result.exit_code == 1 and needle in result.output (and "c1" in output for case-level rows)

def test_validate_ok_activity(tmp_path): ...   # AC-12: exit_code == 0
def test_validate_ok_risk(tmp_path): ...       # AC-13: labels exposed_disclosed/exposed_undisclosed/not_exposed, exit 0
def test_validate_bad_json(tmp_path): ...      # Review Focus 1: "invalid JSON" in output, exit 1
```

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_golden_exposure.py -v` → FAIL.
- [ ] **Step 3: Implement** `exposure.py` (pydantic models with `extra="forbid"` off — unknown keys allowed; URL check `^https?://`; path check `(set_dir/"documents"/p).resolve()` is inside `set_dir/"documents"` and exists) and the `validate` command (print each problem on its own line; exit 1 if any).
- [ ] **Step 4: Run** → PASS; `ruff check .`.
- [ ] **Step 5: Commit** `feat(golden-set): exposure set schema and validate`.

### Task 2: `split` and `stats`

**Files:**
- Modify: `backend/arp/golden_set/exposure.py`, `backend/arp/cli/golden_set.py`
- Test: `backend/tests/test_golden_exposure.py`

**Interfaces:**
- Produces: `assign_splits(s: ExposureSet) -> ExposureSet` (pure); `stats_lines(s: ExposureSet) -> list[str]` in the spec format, labels in the order of `s.labels`.

- [ ] **Step 1: Write failing tests**

```python
def test_split_alternates_per_label(tmp_path):  # AC-14
    # cases a,b core; c,d not; no split
    run(["split"]); s = load(tmp_path)
    assert {c.case_id: c.split for c in s.cases} == {"a": "holdout", "b": "tune", "c": "holdout", "d": "tune"}

def test_split_keeps_existing(tmp_path):  # AC-15: a preset "tune" stays "tune"
def test_split_idempotent_mixed(tmp_path):  # Review Focus 2: running split twice gives identical files
def test_split_keeps_unicode(tmp_path):  # Review Focus 3: "LONGi 隆基" round-trips byte-identically in the company field
def test_stats_lines(tmp_path):  # AC-16
    run(["split"]); out = run(["stats"]).output
    assert "core tune=1 holdout=1" in out and "not tune=1 holdout=1" in out
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (`split` rewrites `cases.json` with `json.dumps(..., ensure_ascii=False, indent=2)` preserving key order; position counted among all cases of the label sorted by `case_id`, so a preset value takes its slot).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(golden-set): exposure split and stats`.

### Task 3: README and the electrolyser set

**Files:**
- Create: `backend/tests/golden/exposure/README.md`, `backend/tests/golden/exposure/electrolyser_makers/cases.json`
- Test: `backend/tests/test_golden_exposure_sets.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Source data: `docs/golden_drafts/electrolyser_manufacturers.md` (27 checked companies) and `docs/golden_drafts/electrolyser_funnel_results.md` (document URLs for 26).

- [ ] **Step 1: Write failing tests**

```python
SETS = ["electrolyser_makers", "ai_datacentre_operators", "water_scarcity_exposed"]

@pytest.mark.parametrize("set_id", SETS)
def test_set_validates(set_id): ...          # AC-17: validate exit 0
@pytest.mark.parametrize("set_id", SETS)
def test_set_size(set_id): ...               # AC-18: sum of stats counts >= 55
@pytest.mark.parametrize("set_id", SETS)
def test_holdout_per_label(set_id): ...      # AC-19: every label holdout >= 8
def test_readme_steps(): ...                 # AC-20: README exists, contains "1.", "2.", "3." and the three step texts from the spec
```
(The two sets added in Tasks 4–5 are marked `xfail(strict=True)` until their task lands; remove the marker there.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Write the README** with the spec's three labelling steps verbatim.
- [ ] **Step 4: Build `electrolyser_makers`**: the 27 checked companies, plus ≥ 28 more found by a research pass (listed makers in China, Japan, Korea; more suppliers, buyers, fuel-cell makers). Each new label checked against a primary source by a person (the owner signs off on the label table in the PR). Run `split`.
- [ ] **Step 5: Run** `python3 -m pytest tests/test_golden_exposure_sets.py -k electrolyser -v` → PASS.
- [ ] **Step 6: Commit** `test(golden): electrolyser makers exposure set`.

### Task 4: AI data-centre operators set

**Files:** Create `backend/tests/golden/exposure/ai_datacentre_operators/cases.json`.

- [ ] **Step 1: Research pass** (agent) proposes ≥ 55 companies across operators, data-centre REITs, hyperscalers, equipment and chip suppliers, utilities; labels `core` / `peripheral` / `not`; `role` per company; sources.
- [ ] **Step 2: Owner checks** each label against a primary source; set `checked_on`.
- [ ] **Step 3: Run** `split`, remove the `xfail` marker, `python3 -m pytest tests/test_golden_exposure_sets.py -k ai_datacentre -v` → PASS.
- [ ] **Step 4: Commit** `test(golden): AI data-centre operators exposure set`.

### Task 5: Water-scarcity exposed set (risk)

**Files:** Create `backend/tests/golden/exposure/water_scarcity_exposed/cases.json`.

- [ ] **Step 1: Research pass** proposes ≥ 55 companies (cement, mining, semiconductors, beverages, utilities); labels `exposed_disclosed` / `exposed_undisclosed` / `not_exposed`; `exposed_undisclosed` needs a non-company source (site locations against a water-stress map) in `label_sources`.
- [ ] **Step 2: Owner checks** labels; set `checked_on`.
- [ ] **Step 3: Run** `split`, remove `xfail`, run the set tests → PASS.
- [ ] **Step 4: Commit** `test(golden): water-scarcity exposure set`.

### Task 6: Regression gate

- [ ] **Step 1: Run** the full backend suite on this branch and `main`, excluding the new test files → identical pass/fail per test (AC-21).
- [ ] **Step 2: Commit** nothing; record the comparison in the PR description.

## Self-review notes

- Spec coverage: AC-1…AC-13 → Task 1; AC-14…AC-16 → Task 2; AC-17…AC-20 → Tasks 3–5; AC-21 → Task 6.
- Tasks 3–5 need human label checks: the owner's time is the critical path, not code.
