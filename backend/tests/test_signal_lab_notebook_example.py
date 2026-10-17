from __future__ import annotations

import random
import runpy
from pathlib import Path

import pytest

from arp.config import get_settings
from tests.test_signal_lab_cli import TICKERS, _write_panel

pytestmark = pytest.mark.usefixtures("pg")

SCRIPT = Path(__file__).resolve().parents[2] / "notebooks" / "signals" / "narrative_momentum.py"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARP_TRAINING_CUTOFFS_PATH", str(tmp_path / "cutoffs.json"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _write_transcripts(path: Path, dates: list[str]) -> None:
    rng = random.Random(3)
    rows = [
        f'{t},{d}T10:00:00Z,"Call {t} {d} #{k}","{"Our AI strategy grew." if rng.random() < 0.5 else "Costs were flat."}"'
        for t in TICKERS
        for d in dates
        for k in range(3)
    ]
    path.write_text("issuer_key,event_time,title,text\n" + "\n".join(rows) + "\n")


def test_example_notebook_runs_end_to_end(env, monkeypatch, capsys):
    dates = _write_panel(env, 40)
    _write_transcripts(env / "t.csv", dates)
    monkeypatch.setenv("ARP_NB_PRICES", str(env / "prices.csv"))
    monkeypatch.setenv("ARP_NB_TRANSCRIPTS", str(env / "t.csv"))

    runpy.run_path(str(SCRIPT))
    first = capsys.readouterr().out
    runpy.run_path(str(SCRIPT))  # safe to re-run: nothing new is ingested, same experiments
    second = capsys.readouterr().out

    lines = first.splitlines()
    assert f"{len(TICKERS) * len(dates) * 3} records, {len(TICKERS) * len(dates) * 3} new" in lines
    assert any(ln.startswith("[unregistered, not evidence]") for ln in lines)
    ids = [ln.split()[1] for ln in lines if ln.startswith("experiment_id: ")]
    assert len(ids) == 2 and len(set(ids)) == 2
    assert "look-ahead violations: []" in lines
    verdict = next(ln for ln in lines if ln.split(" (")[0] in ("a_higher", "b_higher", "insufficient_data"))
    assert " common post-cutoff months, corrected for " in verdict

    assert f"{len(TICKERS) * len(dates) * 3} records, 0 new" in second.splitlines()
    assert [ln for ln in second.splitlines() if ln.startswith("experiment_id: ")] == [f"experiment_id: {i}" for i in ids]
