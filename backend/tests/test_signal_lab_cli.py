from __future__ import annotations

import calendar
import csv
import json
import random

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.signal_lab.registry import Registry

pytestmark = pytest.mark.usefixtures("pg")  # the CLI and the registry's RunStore need Postgres

TICKERS = [f"T{i:02d}" for i in range(15)]


def _month_ends(n: int) -> list[str]:
    out = []
    for i in range(n):
        year, month = 2015 + i // 12, i % 12 + 1
        out.append(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")
    return out


def _write_panel(tmp_path, n_months: int, *, seed: int = 7):
    """Scores equal next month's return plus small noise, so rank IC is clearly positive."""
    rng = random.Random(seed)
    dates = _month_ends(n_months)
    returns = {t: [rng.gauss(0.01, 0.05) for _ in dates] for t in TICKERS}
    prices: dict[str, list[float]] = {}
    for t in TICKERS:
        level, series = 100.0, []
        for r in returns[t]:
            level *= 1 + r
            series.append(level)
        prices[t] = series
    scores = {
        t: [
            (returns[t][i + 1] if i + 1 < n_months else 0.0) + rng.gauss(0, 0.005)
            for i in range(n_months)
        ]
        for t in TICKERS
    }
    for name, panel in (("prices.csv", prices), ("scores.csv", scores)):
        with (tmp_path / name).open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", *TICKERS])
            for i, d in enumerate(dates):
                writer.writerow([d, *(panel[t][i] for t in TICKERS)])
    return dates


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARP_TRAINING_CUTOFFS_PATH", str(tmp_path / "cutoffs.json"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _cutoff(tmp_path, date: str) -> None:
    (tmp_path / "cutoffs.json").write_text(json.dumps({"m": {"cutoff": date, "source": "test"}}))


def _evaluate(tmp_path, dates, *extra):
    return CliRunner().invoke(
        app,
        [
            "signals", "evaluate",
            "--scores", str(tmp_path / "scores.csv"),
            "--prices", str(tmp_path / "prices.csv"),
            "--category", "sentiment_narrative",
            "--method", "toy",
            "--universe", "toy15",
            "--start", dates[0],
            "--end", dates[-1],
            *extra,
        ],
    )


def _experiment_id(result) -> str:
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("experiment_id: "))
    return line.removeprefix("experiment_id: ").strip()


def _decide(experiment_id: str, decision: str = "graduate"):
    return CliRunner().invoke(
        app, ["signals", "decide", experiment_id, "--decision", decision, "--approver", "x"]
    )


def test_evaluate_registers_and_graduation_is_gated(env):
    dates = _write_panel(env, 40)
    _cutoff(env, dates[32])
    result = _evaluate(env, dates, "--model", "m")
    assert result.exit_code == 0, result.output
    assert "post_cutoff" in result.stdout and "in_window" in result.stdout
    blocked = _decide(_experiment_id(result))
    assert blocked.exit_code == 1
    assert "12 IC months" in blocked.stderr

    dates = _write_panel(env, 60)
    _cutoff(env, dates[20])
    result = _evaluate(env, dates, "--model", "m")
    assert result.exit_code == 0, result.output
    graduated = _decide(_experiment_id(result))
    assert graduated.exit_code == 0, graduated.output


def test_rerunning_identical_inputs_registers_once(env):
    dates = _write_panel(env, 40)
    first = _evaluate(env, dates)
    second = _evaluate(env, dates)
    assert first.exit_code == second.exit_code == 0
    assert _experiment_id(first) == _experiment_id(second)
    listing = CliRunner().invoke(app, ["signals", "list"])
    assert listing.stdout.count(_experiment_id(first)) == 1


def test_list_shows_category_method_and_decision(env):
    dates = _write_panel(env, 40)
    experiment_id = _experiment_id(_evaluate(env, dates))
    assert _decide(experiment_id, "shelve").exit_code == 0
    listing = CliRunner().invoke(app, ["signals", "list"])
    assert listing.exit_code == 0, listing.output
    line = next(ln for ln in listing.stdout.splitlines() if experiment_id in ln)
    assert "sentiment_narrative" in line and "toy" in line and "shelve" in line


def test_decide_unknown_experiment_exits_1(env):
    result = _decide("nope")
    assert result.exit_code == 1
    assert "unknown experiment" in result.stderr


def test_mismatched_grids_exit_1_with_a_message(env):
    dates = _write_panel(env, 40)
    lines = (env / "scores.csv").read_text().splitlines()
    (env / "scores.csv").write_text("\n".join(lines[:-1]) + "\n")  # scores one month shorter than prices
    result = _evaluate(env, dates)
    assert result.exit_code == 1
    assert result.stderr.strip()


def test_rerun_does_not_inflate_trials(env):
    dates = _write_panel(env, 40)
    assert _evaluate(env, dates).exit_code == 0
    second = _evaluate(env, dates, "--out", str(env / "report.json"))
    assert second.exit_code == 0, second.output
    assert json.loads((env / "report.json").read_text())["n_trials"] == 1
    registry = Registry(_run_store())
    [record] = registry.list_experiments()
    assert record.evidence.n_trials == 1
    assert registry.trial_count(record.recipe) == 1


def test_corrected_cutoff_is_a_new_experiment_and_stale_one_cannot_graduate(env):
    dates = _write_panel(env, 60)
    _cutoff(env, dates[20])
    old = _evaluate(env, dates, "--model", "m")
    assert old.exit_code == 0, old.output
    _cutoff(env, dates[52])
    new = _evaluate(env, dates, "--model", "m")
    assert new.exit_code == 0, new.output
    old_id, new_id = _experiment_id(old), _experiment_id(new)
    assert old_id != new_id
    listing = CliRunner().invoke(app, ["signals", "list"]).stdout
    assert old_id in listing and new_id in listing

    stale = _decide(old_id)
    assert stale.exit_code == 1
    assert "changed since the experiment was evaluated" in stale.stderr
    short = _decide(new_id)
    assert short.exit_code == 1
    assert "12 IC months" in short.stderr


def test_evaluate_reports_listed_cutoff(env):
    dates = _write_panel(env, 40)
    _cutoff(env, dates[20])
    result = _evaluate(env, dates, "--model", "m")
    assert result.exit_code == 0, result.output
    assert f"model 'm': cutoff {dates[20]} (test)" in result.stderr
    assert "all periods are in_window" not in result.stderr


def test_evaluate_warns_on_unlisted_model(env):
    dates = _write_panel(env, 40)
    result = _evaluate(env, dates, "--model", "m")
    assert result.exit_code == 0, result.output
    assert (
        f"model 'm' has no recorded cutoff in {env / 'cutoffs.json'}: every period is in_window and cannot graduate"
        in result.stderr
    )


def test_evaluate_warns_when_cutoff_after_end(env):
    dates = _write_panel(env, 40)
    _cutoff(env, "2030-01-31")
    result = _evaluate(env, dates, "--model", "m")
    assert result.exit_code == 0, result.output
    assert "model 'm': cutoff 2030-01-31 (test)" in result.stderr
    assert f"all periods are in_window: cutoff 2030-01-31 is after --end {dates[-1]}" in result.stderr


def test_evaluate_warns_without_model(env):
    dates = _write_panel(env, 40)
    result = _evaluate(env, dates)
    assert result.exit_code == 0, result.output
    assert (
        "no --model given: every period counts as post_cutoff; use this only for a signal that involves no trained model"
        in result.stderr
    )


def test_evaluate_rejects_bad_cutoff_file(env):
    dates = _write_panel(env, 40)
    _cutoff(env, "2024")
    result = _evaluate(env, dates, "--model", "m")
    assert result.exit_code == 1
    assert str(env / "cutoffs.json") in result.stderr
