# Credibility Framework from an Indicator List: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upload a row-by-row indicator list and get a Decision Studio framework that, applied to a company table, reproduces the deck's five-question verdict, A–E grade, outlook and action.

**Architecture:** A converter turns the list into an ordinary `MechanismConfig`, so nothing downstream changes: levels mode scores the indicators, a generated rule graph (GoRules ZEN expressions) computes questions, verdict, class, cap, grade, outlook, action and views as calculated columns, and a generated tier graph maps the grade letter to a tier and writes the note. One new endpoint and one Data-tab button expose it.

**Tech Stack:** Python 3.11 + Pydantic v2 (`backend/arp/decision`), FastAPI, GoRules ZEN 2.0.2 expressions, React 19 + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-01-credibility-from-indicator-list.md`

## Global Constraints

- No new dependency. Parse uploads with `arp.decision.parsing.load_table`.
- Every indicator reference in a generated expression is written `number(<slug> ?? 0)`. A 0–3 column that holds only 0s and 1s is profiled as yes/no and arrives as `true`/`false`; `number()` turns it back, `?? 0` makes a blank the bottom of the scale.
- All grade logic lives in the rule graph (one expression node, later keys read earlier ones as `$.key`). The tier graph only maps the letter to a tier and passes the note. Reason: calculated columns are re-profiled before the tier graph runs, and a 0/1 count column turns into yes/no.
- Cut-points pinned at `[0, 0, 0, 0]` (credibility preset) so every band is tier 1 and tier rules only move entities down. `ponytail:` comment on it: the band is unused here; replace with a "tier rules decide" switch if a second preset needs bands.
- Framework is saved as version 1, unratified, through `DecisionStore.save`, like template import.
- Audit entries from the list: `stage="Indicator list"`, `origin="derived"`.
- Commits end with the session's two trailer lines; branch `ccr-45c31775-ddris2`; PR against `main`.

## Review Focus

1. A company column with only 0 and 1 values (e.g. A3 = 0, 1, 1): the critical-at-0 red flag must still fire. Test in Task 3.
2. A company table missing an indicator column: the result lists it in `missing_columns` (existing check) and publishing is refused. Test in Task 4.
3. A list with duplicate ids, a blank `group`, mixed scales or a non-numeric weight: rejected with the row number, nothing saved. Tests in Task 1.
4. A list with no `question` column, or four questions: the plain framework is built and the audit says the credibility preset was skipped and why. Test in Task 2.
5. A blank score: counts as 0, so the answer is `No` and the grade is capped, never a silently higher grade. Test in Task 3.

---

### Task 1: Parse and validate the indicator list

**Files:**
- Modify: `backend/arp/schemas/decision.py` (add `IndicatorSpec` next to `LevelCriterion`)
- Create: `backend/arp/decision/indicator_list.py`
- Test: `backend/tests/test_decision_indicator_list.py`

**Interfaces:**
- Produces: `class IndicatorSpec(BaseModel)`: `id: str`, `name: str`, `group: str`, `weight: float = 1.0`, `group_weight: float | None = None`, `scale_min: int = 0`, `scale_max: int = 3`, `direction: Direction = "higher"`, `critical: bool = False`, `question: str | None = None`, `views: dict[str, float] = {}`, `kind: Literal["indicator", "event"] = "indicator"`, `outlook: Literal["Negative", "Watch"] | None = None`.
- Produces: `parse_indicator_list(matrix: list[list[str]]) -> list[IndicatorSpec]` in `indicator_list.py`; raises `ValueError` whose message names the 1-based data row.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_list_parses_with_defaults():
    specs = parse_indicator_list([["ID", "Name", "Group", "Critical", "Question", "View_Disclosure"],
                                  ["A3", "Medium-term GHG target", "Ambition", "yes", "Q2", "2"]])
    s = specs[0]
    assert (s.id, s.group, s.weight, s.scale_min, s.scale_max, s.direction) == ("A3", "Ambition", 1.0, 0, 3, "higher")
    assert s.critical and s.question == "Q2" and s.views == {"Disclosure": 2.0} and s.kind == "indicator"

def test_event_rows_need_an_outlook():
    with pytest.raises(ValueError, match="row 1"):
        parse_indicator_list([["id", "name", "group", "kind"], ["targets_weakened", "Targets weakened", "Events", "event"]])

@pytest.mark.parametrize("row, message", [
    (["A1", "x", ""], "group"), (["A1", "x", "G", "abc"], "weight"),
])
def test_bad_rows_name_the_row(row, message):
    with pytest.raises(ValueError, match=f"row 1.*{message}"):
        parse_indicator_list([["id", "name", "group", "weight"][: len(row)], row])

def test_duplicate_ids_and_mixed_scales_are_refused():
    with pytest.raises(ValueError, match="A1.*twice"):
        parse_indicator_list([["id", "name", "group"], ["A1", "x", "G"], ["A1", "y", "G"]])
    with pytest.raises(ValueError, match="one scale"):
        parse_indicator_list([["id", "name", "group", "scale"], ["A1", "x", "G", "0-3"], ["A2", "y", "G", "1-5"]])
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_indicator_list.py`
Expected: FAIL, `ImportError: cannot import name 'parse_indicator_list'`

- [ ] **Step 3: Implement `IndicatorSpec` and `parse_indicator_list`**

Headers are matched case-insensitively; `view_*` columns collect into `views` keyed by the text after `view_` as written. Booleans via `arp.decision.parsing.to_bool`, numbers via `to_number`. Blank rows are skipped.

- [ ] **Step 4: Run the tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_indicator_list.py && ruff check arp tests`
Expected: all pass, `All checks passed!`

- [ ] **Step 5: Commit**: `git add backend && git commit -m "Decision Studio: parse an indicator list"`

### Task 2: Build the plain framework

**Files:**
- Modify: `backend/arp/decision/indicator_list.py`
- Test: `backend/tests/test_decision_indicator_list.py`

**Interfaces:**
- Consumes: `IndicatorSpec`, `parse_indicator_list` (Task 1).
- Produces: `build_framework(specs: list[IndicatorSpec], *, name: str) -> tuple[MechanismConfig, list[AuditEntry]]`. When the list has questions but not exactly five, it adds the audit entry `item="Credibility preset", decision="skipped"`. The call for exactly five questions is added in Task 3.

- [ ] **Step 1: Write the failing tests**

```python
DECK = Path(__file__).resolve().parents[2] / "docs/decision-studio/example-framework/credibility"

def test_a_plain_list_becomes_a_levels_framework():
    config, audit = build_framework(parse_indicator_list([["id", "name", "group", "weight"],
        ["A1", "Net zero", "Ambition", "2"], ["A3", "Medium-term", "Ambition", "1"], ["G1", "GHG disclosure", "Metrics", "1"]]), name="T")
    assert (config.mode, config.level_min, config.level_max) == ("levels", 0, 3)
    assert [d.name for d in config.dimensions] == ["Ambition", "Metrics"]
    assert [(c.name, c.weight) for c in config.level_criteria] == [("Net zero", 2.0), ("Medium-term", 1.0), ("GHG disclosure", 1.0)]
    assert config.source_columns == ["A1", "A3", "G1"] and not config.ratified
    assert all(a.stage == "Indicator list" and a.origin == "derived" for a in audit)

def test_scores_become_levels_and_cluster_averages(sample_companies):
    # Shell's Ambition A1..A7 = 2,2,0,2,2,1,2 -> 11/7 = 1.57 (deck slide 10: 1.6)
    specs = [s.model_copy(update={"question": None}) for s in parse_indicator_list(load_table(DECK / "indicators.csv"))]
    config, _ = build_framework(specs, name="Credibility")  # no questions: plain framework, Task 3 not needed
    shell = next(e for e in apply_mechanism(sample_companies, config).entities if e.name == "Shell")
    ambition = next(d.id for d in config.dimensions if d.name == "Ambition & targets")
    assert round(shell.dimension_scores[ambition], 2) == 1.57

def test_lower_is_better_flips_the_level():
    config, _ = build_framework(parse_indicator_list([["id", "name", "group", "direction"], ["X", "x", "G", "lower"]]), name="T")
    data = build_dataset("t", [["Company", "X"], ["a", "0"], ["b", "3"]])
    assert [c.normalised for e in apply_mechanism(data, config).entities for c in e.contributions] == [3, 0]

def test_a_list_without_five_questions_skips_the_preset_and_says_why():
    _, audit = build_framework(parse_indicator_list([["id", "name", "group", "question"], ["A1", "x", "G", "Q1"]]), name="T")
    assert any(a.item == "Credibility preset" and a.decision == "skipped" and "five questions" in a.why for a in audit)
```

`sample_companies` fixture: `dataset_from_file(DECK / "companies.csv")`. Both files are created in this task (Step 3).

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_indicator_list.py`
Expected: FAIL, `ImportError: cannot import name 'build_framework'`

- [ ] **Step 3: Write the example files and implement `build_framework`**

- `docs/decision-studio/example-framework/credibility/indicators.csv`: the deck's 27 indicators (appendix slides 42–45) with columns `id,name,group,question,critical`, groups A–G as named on slide 10, questions as on slide 14, criticals A3 A6 B3 C1 D2 G2; plus event rows `targets_weakened` (Negative) and `new_fossil_capacity` (Watch).
- `docs/decision-studio/example-framework/credibility/companies.csv`: `Company` plus the 27 ids and the two events, scores from slides 42–45, events per the spec's acceptance section.
- `build_framework`: one `LevelCriterion` per indicator row with `id` as criterion id, rules `[level k when number(<slug> ?? 0) >= k]` for k from max down to min+1, `otherwise = scale_min`, `otherwise_on_blank = True`; for `lower`, level k when `max - number(<slug> ?? 0) >= k`. Event rows are not criteria. Cluster weight = the group's first non-blank `group_weight`, else 1. `label_column = "Company"`, `min_coverage_pct = 0`, `cut_mode = "absolute"`, pinned cuts evenly spaced on the scale.

- [ ] **Step 4: Run the tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_indicator_list.py tests/test_decision_levels.py && ruff check arp tests`
Expected: all pass

- [ ] **Step 5: Commit**: `git add backend docs/decision-studio/example-framework/credibility && git commit -m "Decision Studio: build a levels framework from an indicator list"`

### Task 3: The credibility preset

**Files:**
- Create: `backend/arp/decision/credibility.py`
- Modify: `backend/arp/decision/indicator_list.py` (call the preset)
- Test: `backend/tests/test_decision_indicator_list.py`

**Interfaces:**
- Consumes: `IndicatorSpec`; `build_framework` from Task 2.
- Produces: `apply_preset(config: MechanismConfig, specs: list[IndicatorSpec], audit: list[AuditEntry]) -> MechanismConfig` setting `rule_graph`, `tier_graph`, the five tiers, `pinned_cuts = [0, 0, 0, 0]`. Calculated columns (exact keys): `q1_pct`…`q5_pct`, `q1_answer`…`q5_answer`, `no_count`, `yes_count`, `verdict`, `tree_class`, `cap_class`, `grade` (`"A"`…`"E"`), `outlook`, `action`, `note`, and `view_<slug>_pct` per view.

- [ ] **Step 1: Write the failing tests**

```python
def _deck_result():
    config, _ = build_framework(parse_indicator_list(load_table(DECK / "indicators.csv")), name="Credibility")
    return {e.name: e for e in apply_mechanism(dataset_from_file(DECK / "companies.csv"), config).entities}

def test_the_deck_is_reproduced():
    r = _deck_result()
    assert [r[c].tier_name for c in ("Shell", "RWE", "Enel")] == ["D Not credible", "B Credible, gaps", "A Credible"]
    assert r["Shell"].notes[-1] == "Not credible (4 No, 0 Yes) · Outlook Negative · Escalate: voting sanctions, support climate resolutions"
    assert r["RWE"].notes[-1] == "Partly credible (0 No, 0 Yes) · Outlook Watch · Engage on flagged issue"
    assert r["Enel"].notes[-1] == "Partly credible (0 No, 1 Yes) · Outlook Watch · Maintain + targeted ask"

def test_a_critical_column_of_only_zeros_and_ones_still_fires():
    rows = list(csv.reader((DECK / "companies.csv").open()))
    a3 = rows[0].index("A3")
    for row, value in zip(rows[1:], ["0", "1", "1"], strict=True):
        row[a3] = value
    config, _ = build_framework(parse_indicator_list(load_table(DECK / "indicators.csv")), name="Credibility")
    shell = next(e for e in apply_mechanism(build_dataset("t", rows), config).entities if e.name == "Shell")
    assert shell.tier_name == "D Not credible"

def test_a_blank_score_counts_as_zero():
    rows = list(csv.reader((DECK / "companies.csv").open()))
    rows[3][rows[0].index("A3")] = ""  # Enel's medium-term target
    config, _ = build_framework(parse_indicator_list(load_table(DECK / "indicators.csv")), name="Credibility")
    enel = next(e for e in apply_mechanism(build_dataset("t", rows), config).entities if e.name == "Enel")
    assert enel.tier_name == "D Not credible" and enel.notes[-1].startswith("Not credible (1 No")

def test_views_are_reported_when_the_list_has_them():
    specs = parse_indicator_list(load_table(DECK / "indicators.csv"))
    for s in specs:
        s.views = {"Disclosure": 1.0} if s.id.startswith("G") else {}
    config, _ = build_framework(specs, name="Credibility")
    assert "view_disclosure_pct" in json.dumps(config.rule_graph)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_indicator_list.py -k "deck or critical or blank or views"`
Expected: FAIL, no `rule_graph` / tier names `Tier 1`

- [ ] **Step 3: Implement `apply_preset` and call it from `build_framework` when the list has exactly five distinct questions**

Expressions follow the spec's numbered rules 1–10 literally; a tested sketch of rules 1–6 is in the session's proof script (`len(filter([..], # == 0))` for counts, `max([tree_class, cap_class])` for the worse grade, nested ternaries for the tree). Counts are formatted into `note` with `string()` inside the rule graph. Tier graph: one expression node, `tier = grade == 'A' ? 1 : (grade == 'B' ? 2 : (grade == 'C' ? 3 : (grade == 'D' ? 4 : 5)))`, `note = note`. Audit: one entry per question listing its indicators, one for the critical list, one stating the cut-points are unused.

- [ ] **Step 4: Run the decision suite**

Run: `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_*.py && ruff check arp tests`
Expected: all pass

- [ ] **Step 5: Commit**: `git add backend && git commit -m "Decision Studio: credibility preset (five questions, class, cap, outlook, action)"`

### Task 4: Endpoint

**Files:**
- Modify: `backend/arp/api/routers/decision.py`
- Test: `backend/tests/test_decision_api.py`

**Interfaces:**
- Consumes: `parse_indicator_list`, `build_framework`.
- Produces: `POST /api/decision/mechanisms/from-indicators` (multipart `file`, form `name`, optional form `by`) → `MechanismEnvelope`; 400 with the parser's message on a bad list. Saves through `store.save(config, audit)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_indicator_list_becomes_a_saved_draft(client):
    env = client.post("/api/decision/mechanisms/from-indicators", files={"file": ("indicators.csv", (DECK / "indicators.csv").read_bytes(), "text/csv")}, data={"name": "Credibility"}).json()
    assert env["config"]["version"] == 1 and not env["config"]["ratified"] and env["config"]["mode"] == "levels"
    companies = upload(client, DECK / "companies.csv")
    result = client.post("/api/decision/score", json={"dataset_id": companies, "framework_id": env["config"]["framework_id"]}).json()
    assert [e["tier_name"] for e in result["entities"]] == ["D Not credible", "B Credible, gaps", "A Credible"]

def test_a_bad_list_is_refused_and_nothing_saved(client):
    before = len(client.get("/api/decision/mechanisms").json())
    r = client.post("/api/decision/mechanisms/from-indicators", files={"file": ("x.csv", b"id,name\nA1,x\n", "text/csv")}, data={"name": "x"})
    assert r.status_code == 400 and "group" in r.json()["detail"]
    assert len(client.get("/api/decision/mechanisms").json()) == before

def test_a_company_table_missing_an_indicator_is_flagged(client, tmp_path):
    framework_id = from_indicators(client)
    rows = list(csv.reader((DECK / "companies.csv").open()))
    c1 = rows[0].index("C1")
    path = tmp_path / "gap.csv"
    csv.writer(path.open("w", newline="")).writerows([r[:c1] + r[c1 + 1:] for r in rows])
    result = client.post("/api/decision/score", json={"dataset_id": upload(client, path), "framework_id": framework_id}).json()
    assert "C1" in result["missing_columns"]
```

Test helpers in the same file: `upload(client, path) -> str` posts the file to `/api/decision/datasets` and returns `dataset_id`; `from_indicators(client) -> str` posts `indicators.csv` to the new route and returns `framework_id`.

- [ ] **Step 2: Run them to see them fail** (404 on the new route)

Run: `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_api.py -k indicator`

- [ ] **Step 3: Implement the route** next to `/mechanisms/import`; write the upload with `safe_filename` into `frameworks_dir / "_uploads"` and read it with `load_table`, as `/datasets` does.

- [ ] **Step 4: Run** `cd backend && PYTHONPATH=. python3 -m pytest -q tests/test_decision_*.py && ruff check arp tests`. Expected: all pass.

- [ ] **Step 5: Commit**: `git add backend && git commit -m "Decision Studio: POST /mechanisms/from-indicators"`

### Task 5: Data-tab button

**Files:**
- Modify: `frontend/src/api/client.ts` (`importIndicatorList(file: File, name: string, by?: string): Promise<MechanismEnvelope>`)
- Modify: `frontend/src/pages/DecisionStudio.tsx` (under "Import a template file")

- [ ] **Step 1: Add the button**: label `Build a framework from an indicator list`, `accept=".csv,.tsv,.txt,.xlsx,.xls"`, name = file name without extension; on success the status reads `Built <name> from <n> indicators as a draft.` and `refreshTemplates()` runs; help text links to `docs/decision-studio/indicator-list.md`.
- [ ] **Step 2: Run** `cd frontend && npm run lint && npm run build`. Expected: no errors.
- [ ] **Step 3: Check in the app**: upload `indicators.csv`, upload `companies.csv`, Apply the new template, Results shows Shell D, RWE B, Enel A with the notes from Task 3; no page errors.
- [ ] **Step 4: Commit**: `git add frontend && git commit -m "Decision Studio: build a framework from an indicator list in the Data tab"`

### Task 6: Docs

**Files:**
- Create: `docs/decision-studio/indicator-list.md` (the spec's list format and preset rules, written for analysts, with the two example files)
- Modify: `docs/DECISION_MECHANISM.md` (new §3l "Frameworks from an indicator list", one paragraph + link)

- [ ] **Step 1: Write both**; every number in them comes from Task 3's tests.
- [ ] **Step 2: Commit, push, open the PR against `main`**: `git add docs && git commit -m "Docs: frameworks from an indicator list" && git push -u origin ccr-45c31775-ddris2`
