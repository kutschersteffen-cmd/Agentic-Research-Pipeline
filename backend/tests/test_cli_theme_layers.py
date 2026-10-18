import pytest
from typer.testing import CliRunner

from arp.cli.theme import theme_app
from tests.theme_layers_helpers import fixture_f


def _run(*args):
    return CliRunner().invoke(theme_app, list(args))


def test_import_then_reimport(run_store, neo4j_graph, tmp_path):
    _keys, csv = fixture_f(run_store, tmp_path)
    first = _run("edges", "import", "--csv", str(csv))
    assert first.exit_code == 0 and first.stdout == "2 rows, 2 new\n"
    again = _run("edges", "import", "--csv", str(csv))
    assert again.exit_code == 0 and again.stdout == "2 rows, 0 new\n"


def test_import_bad_row_exits_1(neo4j_graph, tmp_path):
    csv = tmp_path / "bad.csv"
    csv.write_text(
        "supplier_key,supplier_name,customer_key,customer_name,revenue_share,source_doc,source_passage,effective_date,published_at\n"
        "s,S,c,C,1.5,doc,passage,2023-12-31,2024-03-01\n"
    )
    res = _run("edges", "import", "--csv", str(csv))
    assert res.exit_code == 1 and "row 1: revenue_share must be greater than 0 and at most 1" in res.stderr


def test_import_not_configured_checked_before_the_file(monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_NEO4J_URI", "")  # empty, not unset: a .env file would bring it back
    res = _run("edges", "import", "--csv", str(tmp_path / "does-not-exist.csv"))
    assert res.exit_code == 1 and "company graph not configured: set ARP_NEO4J_URI" in res.stderr


def test_layers_output(run_store, neo4j_graph, tmp_path):
    keys, csv = fixture_f(run_store, tmp_path)
    assert _run("edges", "import", "--csv", str(csv)).exit_code == 0
    res = _run("layers", "--run", "R", "--as-of", "2024-06-30")
    assert res.exit_code == 0, res.output
    lines = res.stdout.splitlines()
    assert lines[0] == "rank\tissuer_key\tname\tl1\tl2\tl3\tscore\tstatus"
    assert lines[1] == f"1\t{keys['A']}\tA\t0.6000\t-\t-\t0.2700\tscored"
    assert lines[3] == f"3\t{keys['S1']}\tS1\t-\t0.2040\t-\t0.0714\tscored"
    assert lines[-1] == f"-\t{keys['C']}\tC\t-\t-\t-\t-\tinsufficient data"
    assert len(lines) == 6


@pytest.mark.parametrize(("env", "value"), [("ARP_THEME_LAYER_DECAY", "1.5"), ("ARP_THEME_LAYER_MAX_HOPS", "3"), ("ARP_THEME_LAYER_W1", "-0.1")])
def test_layers_bad_setting(run_store, neo4j_graph, tmp_path, monkeypatch, env, value):
    fixture_f(run_store, tmp_path)
    monkeypatch.setenv(env, value)
    res = _run("layers", "--run", "R", "--as-of", "2024-06-30")
    assert res.exit_code == 1 and env in res.stderr


def test_layers_not_configured(run_store, tmp_path, monkeypatch):
    fixture_f(run_store, tmp_path)
    monkeypatch.setenv("ARP_NEO4J_URI", "")  # empty, not unset: a .env file would bring it back
    res = _run("layers", "--run", "R", "--as-of", "2024-06-30")
    assert res.exit_code == 1 and "company graph not configured: set ARP_NEO4J_URI" in res.stderr


def test_layers_unknown_run(run_store):
    res = _run("layers", "--run", "nope", "--as-of", "2024-06-30")
    assert res.exit_code == 1 and "unknown theme run 'nope'" in res.stderr


def test_layers_bad_date(run_store):
    res = _run("layers", "--run", "R", "--as-of", "30.06.2024")
    assert res.exit_code == 1 and "as_of must be a date in YYYY-MM-DD form" in res.stderr


def test_import_malformed_csv_exits_1(neo4j_graph, tmp_path):
    csv = tmp_path / "huge.csv"
    csv.write_text(
        "supplier_key,supplier_name,customer_key,customer_name,revenue_share,source_doc,source_passage,effective_date,published_at\n"
        f's,S,c,C,0.5,doc,"{"x" * 200_000}",2023-12-31,2024-03-01\n'
    )
    res = _run("edges", "import", "--csv", str(csv))
    assert res.exit_code == 1 and isinstance(res.exception, SystemExit)  # a clean exit, not a traceback
    assert "field larger than field limit" in res.stderr
