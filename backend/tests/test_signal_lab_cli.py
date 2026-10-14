from __future__ import annotations

import calendar
import csv
import json
import random

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings

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
