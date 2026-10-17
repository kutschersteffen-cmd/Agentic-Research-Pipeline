from __future__ import annotations

import calendar
import random

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.signal_lab.compare import compare_experiments
from arp.signal_lab.evidence import EvidenceReport, WindowEvidence
from arp.signal_lab.registry import Recipe, Registry
from arp.signal_lab.stats import IcSummary
from arp.storage.run_store import RunStore


def _months(n: int, start_year: int = 2016) -> list[str]:
    out = []
    for i in range(n):
        year, month = start_year + i // 12, i % 12 + 1
        out.append(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")
    return out


def _recipe(**kw) -> Recipe:
    base = dict(
        category="sentiment_narrative", method="a", text_source=None, params={},
        universe="sp500", window_start="2010-01", window_end="2020-12", cost_bps=10.0,
    )
    return Recipe(**{**base, **kw})


def _evidence(series: list[tuple[str, float]] | None, window: str = "post_cutoff") -> EvidenceReport:
    windows = []
    if series is not None:
        windows.append(
            WindowEvidence(
                window=window, periods=len(series), ic=IcSummary(n=len(series), mean=0.02, t_nw=1.0, hit_rate=0.5),
                long_short=None, net_long_short=None, monthly_turnover_pct=None, deflated_sharpe=None, series=series,
            )
        )
    return EvidenceReport(windows=windows, contamination_gap_ic=None, overlap={}, n_trials=1)


@pytest.fixture
def registry(pg, tmp_path) -> Registry:
    return Registry(RunStore(pg, tmp_path / "runs"))


def _register(registry, method: str, series, *, window: str = "post_cutoff", **recipe_kw) -> str:
    rec = registry.register(
        _recipe(method=method, **recipe_kw), _evidence(series, window), data_version="v1", model=None, cutoff=None
    )
    return rec.experiment_id


def _pair(n: int = 36, margin: float = 0.5, seed: int = 1):
    """B is noise; A is B plus `margin` plus independent noise, over the same months."""
    rng = random.Random(seed)
    months = _months(n)
    b = [rng.gauss(0, 1) for _ in months]
    a = [x + margin + rng.gauss(0, 1) for x in b]
    return list(zip(months, a, strict=True)), list(zip(months, b, strict=True))


def test_clearly_better_signal_is_ranked(registry):
    months = _months(36)
    rng = random.Random(3)
    b = [(m, rng.gauss(0, 1)) for m in months]
    a = [(m, v + 3.0 + rng.gauss(0, 0.1)) for m, v in b]
    result = compare_experiments(_register(registry, "a", a), _register(registry, "b", b), registry)
    assert (result.verdict, result.months, result.n_comparisons, result.reason) == ("a_higher", 36, 1, None)


def test_noise_is_insufficient_data(registry):
    a, b = _pair(margin=0.0)
    result = compare_experiments(_register(registry, "a", a), _register(registry, "b", b), registry)
    assert (result.verdict, result.months) == ("insufficient_data", 36)


def test_fewer_than_12_common_months_is_insufficient_data(registry):
    months = _months(36)
    a = [(m, 5.0 + i * 0.01) for i, m in enumerate(months)]  # A is far ahead on every month ...
    b = [(m, 0.0) for m in months[:11]] + [(m, 0.0) for m in _months(36, 2030)]  # ... but only 11 months overlap
    result = compare_experiments(_register(registry, "a", a), _register(registry, "b", b), registry)
    assert (result.verdict, result.months) == ("insufficient_data", 11)


def test_more_experiments_in_scope_raise_the_bar(registry):
    a, b = _pair(margin=0.5)
    a_id, b_id = _register(registry, "a", a), _register(registry, "b", b)
    two = compare_experiments(a_id, b_id, registry)
    assert (two.verdict, two.n_comparisons) == ("a_higher", 1)

    for name in ("c", "d"):
        _register(registry, name, [(m, 0.0) for m, _ in a])
    # A different universe is out of scope and must not count.
    _register(registry, "e", [(m, 0.0) for m, _ in a], universe="russell2000")
    four = compare_experiments(a_id, b_id, registry)
    assert (four.verdict, four.n_comparisons) == ("insufficient_data", 6)


@pytest.mark.parametrize(
    ("field", "other"),
    [("universe", "russell2000"), ("window_start", "2011-01"), ("window_end", "2021-12"), ("cost_bps", 25.0)],
)
def test_different_universe_window_or_cost_raises(registry, field, other):
    a, b = _pair()
    a_id = _register(registry, "a", a)
    b_id = _register(registry, "b", b, **{field: other})
    with pytest.raises(ValueError, match=f"not comparable: {field} differs"):
        compare_experiments(a_id, b_id, registry)


def test_no_post_cutoff_window_is_insufficient_with_reason(registry):
    a, b = _pair()
    a_id = _register(registry, "a", a)
    b_id = _register(registry, "b", b, window="in_window")
    result = compare_experiments(a_id, b_id, registry)
    assert result.verdict == "insufficient_data"
    assert result.reason == f"no post-cutoff evidence for {b_id}"
    assert (result.months, result.n_comparisons) == (0, 1)


def test_old_row_without_series_raises_rerun(registry):
    a, b = _pair()
    a_id = _register(registry, "a", a)
    b_id = _register(registry, "b", [])
    with pytest.raises(ValueError, match=f"{b_id} was registered before series were stored; re-run it"):
        compare_experiments(a_id, b_id, registry)


def test_unknown_or_same_id_raises(registry):
    a, _ = _pair()
    a_id = _register(registry, "a", a)
    with pytest.raises(ValueError, match="unknown experiment 'nope'"):
        compare_experiments(a_id, "nope", registry)
    with pytest.raises(ValueError, match="itself"):
        compare_experiments(a_id, a_id, registry)


@pytest.fixture
def env(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    get_settings.cache_clear()
    yield Registry(_run_store())
    get_settings.cache_clear()


def test_cli_compare_prints_verdict_and_counts(env):
    a, b = _pair(margin=3.0)
    a_id, b_id = _register(env, "a", a), _register(env, "b", b)
    result = CliRunner().invoke(app, ["signals", "compare", a_id, b_id])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "a_higher (36 common post-cutoff months, corrected for 1 comparisons)"


def test_cli_compare_unknown_id_exits_1(env):
    a, _ = _pair()
    a_id = _register(env, "a", a)
    result = CliRunner().invoke(app, ["signals", "compare", a_id, "nope"])
    assert result.exit_code == 1
    assert "unknown experiment 'nope'" in result.stderr
