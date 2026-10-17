from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from arp.signal_lab.methods import base
from tests.test_signal_lab_cli import _write_panel

pytestmark = pytest.mark.usefixtures("pg")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARP_TRAINING_CUTOFFS_PATH", str(tmp_path / "cutoffs.json"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _recipe(tmp_path, dates, method="price_momentum", params=None, **extra) -> str:
    path = tmp_path / "r.json"
    recipe = {
        "category": "sentiment_narrative", "method": method, "text_source": None, "params": params or {},
        "universe": "toy15", "window_start": dates[0], "window_end": dates[-1], **extra,
    }
    path.write_text(json.dumps(recipe))
    return str(path)


def _run(tmp_path, recipe, *extra):
    return CliRunner().invoke(
        app, ["signals", "run", "--recipe", recipe, "--prices", str(tmp_path / "prices.csv"), *extra]
    )


def _ingest(tmp_path, rows: list[str]) -> None:
    path = tmp_path / "t.csv"
    path.write_text("issuer_key,event_time,title,text\n" + "\n".join(rows) + "\n")
    result = CliRunner().invoke(app, ["signals", "ingest-transcripts", "--csv", str(path)])
    assert result.exit_code == 0, result.output


def test_run_price_momentum_registers_an_experiment_and_prints_windows(env):
    dates = _write_panel(env, 40)
    result = _run(env, _recipe(env, dates))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].startswith("experiment_id: ") and len(lines[0].split()[1]) == 16
    assert any(ln.startswith("window") and "net Sharpe" in ln for ln in lines)
    listed = CliRunner().invoke(app, ["signals", "list"])
    assert lines[0].split()[1] in listed.stdout and "price_momentum" in listed.stdout


def test_run_twice_registers_once(env):
    dates = _write_panel(env, 40)
    recipe = _recipe(env, dates)
    first, second = _run(env, recipe), _run(env, recipe)
    assert first.exit_code == second.exit_code == 0
    assert first.stdout.splitlines()[0] == second.stdout.splitlines()[0]
    listed = CliRunner().invoke(app, ["signals", "list"]).stdout.strip().splitlines()
    assert len(listed) == 1 and "trials=1" in listed[0]


def test_run_narrative_attention_from_the_store(env):
    dates = _write_panel(env, 40)
    _ingest(env, [f"T00,{d}T10:00:00Z,Call,Our AI strategy grew." for d in dates[:6]])
    recipe = _recipe(env, dates, "narrative_attention", {"terms": ["AI"], "lookback_months": 3})
    result = _run(env, recipe)
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("experiment_id: ")


def test_run_unknown_method_exits_1_and_lists_names(env):
    dates = _write_panel(env, 40)
    result = _run(env, _recipe(env, dates, "nope"))
    assert result.exit_code == 1
    assert "unknown method 'nope'" in result.stderr and "narrative_attention" in result.stderr
    assert "Traceback" not in result.output + result.stderr


def test_run_issuer_first_without_a_tool_exits_1_with_the_documented_message(env):
    dates = _write_panel(env, 40)
    result = _run(env, _recipe(env, dates, "issuer_first", {"queries": ["x"]}))
    assert result.exit_code == 1
    assert "no search tool configured" in result.stderr


def test_run_grounded_llm_over_the_threshold_needs_yes(env, monkeypatch):
    dates = _write_panel(env, 40)
    _ingest(env, [f"T00,{d}T10:00:00Z,Call,Good news." for d in dates[:3]])
    calls = []

    class FakeLLM:
        async def complete_json(self, *a, **k):
            calls.append(1)
            raise AssertionError("must not be called")

    monkeypatch.setattr("arp.cli.signal_lab.build_llm_client", lambda settings: FakeLLM())
    recipe = _recipe(env, dates, "grounded_llm", {"stability_runs": 2})
    result = _run(env, recipe, "--confirm-above", "1")
    assert result.exit_code == 1
    # 3 documents, one pass plus two stability reruns
    assert "LLM calls (estimate): 9, approx input tokens: " in result.stdout
    assert "--yes" in result.stderr
    assert calls == []


def test_run_failure_prints_no_traceback(env, monkeypatch):
    dates = _write_panel(env, 40)

    def boom(params, inp):
        raise RuntimeError("kaput")

    monkeypatch.setitem(base._METHODS, "boom", boom)
    result = _run(env, _recipe(env, dates, "boom"))
    assert result.exit_code == 1
    assert "Run failed: RuntimeError: kaput" in result.stderr
    assert "Traceback" not in result.output + result.stderr


def test_run_bad_recipe_file_exits_1_with_one_line(env):
    _write_panel(env, 40)
    bad = env / "bad.json"
    bad.write_text('{"category": "nope"}')
    for path in (bad, env / "missing.json"):
        result = _run(env, str(path))
        assert result.exit_code == 1 and len(result.stderr.strip().splitlines()) == 1, result.stderr
    bad.write_text("{not json")
    assert _run(env, str(bad)).exit_code == 1


def test_run_window_beyond_the_prices_exits_1(env):
    dates = _write_panel(env, 40)
    result = _run(env, _recipe(env, dates, window_end="2099-12-31"))
    assert result.exit_code == 1
    assert "outside the price file" in result.stderr


def test_run_panel_option_feeds_the_panel_method_and_is_hashed_into_the_data_version(env):
    dates = _write_panel(env, 40)
    recipe = _recipe(env, dates, "panel", {"name": "s"})
    first = _run(env, recipe, "--panel", f"s={env / 'scores.csv'}")
    assert first.exit_code == 0, first.output
    (env / "scores2.csv").write_bytes((env / "scores.csv").read_bytes() + b"\n")
    second = _run(env, recipe, "--panel", f"s={env / 'scores2.csv'}")
    assert second.exit_code == 0 and second.stdout.splitlines()[0] != first.stdout.splitlines()[0]
    bad = _run(env, recipe, "--panel", "no-equals-sign")
    assert bad.exit_code == 1 and "NAME=PATH" in bad.stderr


def test_run_prints_method_notes(env, monkeypatch):
    dates = _write_panel(env, 40)

    def noted(params, inp):
        res = base._price_momentum({}, inp)
        res.notes = {"b": 2, "a": 1}
        return res

    monkeypatch.setitem(base._METHODS, "noted", noted)
    result = _run(env, _recipe(env, dates, "noted"))
    assert result.exit_code == 0, result.output
    assert 'notes: {"a": 1, "b": 2}' in result.stdout
