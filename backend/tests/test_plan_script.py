"""Research Orchestrator code mode: checker, interpreter, dry run (spec AC-1..AC-10)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from arp.cli.plan import plan_app
from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import StepLimitExceeded, dry_run, run_script

runner = CliRunner()


def _check_cli(tmp_path, source: str):
    path = tmp_path / "s.py"
    path.write_text(source)
    return runner.invoke(plan_app, ["check", str(path)])


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("import os\n", "line 1: import not allowed"),  # AC-1
        ('open("x")\n', "line 1: call to open not allowed"),  # AC-2
        ("y = x.__class__\n", "line 1: name __class__ not allowed"),  # AC-3
        ("extraction(foo=1)\n", "line 1: extraction: unexpected argument foo"),  # AC-4
        ("w = x * 2\n", "line 1: arithmetic not allowed"),  # AC-5
    ],
)
def test_check_rejects(tmp_path, source, message):
    result = _check_cli(tmp_path, source)
    assert result.exit_code == 1
    assert message in result.stdout


def test_check_rejects_long_script(tmp_path):  # AC-6
    result = _check_cli(tmp_path, 'a = 1\n' * 201)
    assert result.exit_code == 1
    assert "script exceeds 200 lines" in result.stdout


VALID = """u = universe_build(taxonomy_id="t_grid storage", source="u.csv")
for c in u.companies:
    if c.exposure >= 0.1:
        extraction(universe_run_id=u.run_id, schema_id="green_capex", companies=[c.id])
"""


def test_check_accepts_valid(tmp_path):  # AC-7
    result = _check_cli(tmp_path, VALID)
    assert result.exit_code == 0, result.stdout
    assert result.stdout.strip() == "ok"


def test_check_rejects_other_constructs():
    for src in ["def f():\n    pass\n", "while True:\n    pass\n", "f = lambda: 1\n", "x = _y\n",
                "try:\n    a = 1\nexcept Exception:\n    a = 2\n", 'universe_build(theme=1)\n',
                "universe_build()\n"]:
        assert check_script(src), src


def _stubs(companies):
    def universe_build(**_):
        return {"id": "u_1", "run_id": "u_1", "companies": companies}

    def extraction(**kw):
        return {"id": "e", "run_id": "r"}

    return {"universe_build": universe_build, "extraction": extraction}


def test_step_limit():  # AC-8
    src = "for i in range(501):\n    universe_build(taxonomy_id=\"t\", source=\"u.csv\")\n"
    with pytest.raises(StepLimitExceeded, match="step limit 500 exceeded"):
        run_script(src, _stubs([]))


def test_dry_run_with_stubs():  # AC-9
    comps = [{"id": "a", "exposure": 0.2}, {"id": "b", "exposure": 0.05}, {"id": "c", "exposure": 0.5}]
    calls = run_script(VALID, _stubs(comps))
    assert [(c["seq"], c["kind"]) for c in calls] == [(1, "universe_build"), (2, "extraction"), (3, "extraction")]
    assert calls[1]["params"]["universe_run_id"] == "u_1"


def test_dry_run_placeholders():  # AC-10
    calls = dry_run(VALID)
    assert [(c["seq"], c["kind"], c["depends_on"]) for c in calls] == [
        (1, "universe_build", None), (2, "extraction", 1)]


def test_dry_run_cli(tmp_path):
    path = tmp_path / "s.py"
    path.write_text(VALID)
    result = runner.invoke(plan_app, ["dry-run", str(path)])
    assert result.exit_code == 0
    assert "2 extraction" in result.stdout and "depends on 1" in result.stdout


def test_dry_run_list_field_from_comprehension():  # review: an unknown list argument must not fail validation
    src = ('u = universe_build(taxonomy_id="t", source="u.csv")\n'
           "document_discovery(universe_run_id=u.run_id, companies=[c.id for c in u.companies if c.included])\n")
    calls = dry_run(src)
    assert calls[1]["params"]["companies"] == ["<from step 1>"]
    assert calls[1]["depends_on"] == 1


def test_checker_survives_unhashable_literal(pg):
    from arp.orchestration.plan_store import PlanStore

    src = 'extraction(universe_run_id={[1]: 2}, schema_id="s")\n'
    assert check_script(src) == []  # no crash; the dry run rejects it
    with pytest.raises(ValueError, match="unhashable"):
        PlanStore(pg).create("b", src)


def test_long_loops_are_bounded():
    from arp.orchestration.plan_interp import PlanScriptError

    with pytest.raises(PlanScriptError, match="range longer than"):
        dry_run("for i in range(10000000000):\n    pass\n")
    with pytest.raises(PlanScriptError, match="operation limit"):
        dry_run("for i in range(10000):\n    for j in range(10000):\n        pass\n")
