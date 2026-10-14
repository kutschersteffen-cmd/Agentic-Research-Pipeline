from __future__ import annotations

import pytest

from arp.signal_lab.evidence import EvidenceReport, WindowEvidence
from arp.signal_lab.registry import SIGNAL_REGISTRY_RUN_ID, Recipe, Registry, experiment_id_for
from arp.signal_lab.stats import IcSummary
from arp.storage.run_store import RunStore


def _recipe(**kw) -> Recipe:
    base = dict(
        category="sentiment_narrative",
        method="lm_dictionary",
        text_source="10-K",
        params={},
        universe="sp500",
        window_start="2010-01",
        window_end="2020-12",
    )
    return Recipe(**{**base, **kw})


def _evidence(window: str = "in_window", n: int = 30) -> EvidenceReport:
    w = WindowEvidence(
        window=window,
        periods=n,
        ic=IcSummary(n=n, mean=0.02, t_nw=1.0, hit_rate=0.5),
        long_short=None,
        net_long_short=None,
        monthly_turnover_pct=None,
        deflated_sharpe=None,
    )
    return EvidenceReport(windows=[w], contamination_gap_ic=None, overlap={}, n_trials=1)


@pytest.fixture
def registry(pg, tmp_path) -> Registry:
    return Registry(RunStore(pg, tmp_path / "runs"))


def _register(registry: Registry, recipe: Recipe | None = None, evidence: EvidenceReport | None = None):
    return registry.register(recipe or _recipe(), evidence or _evidence(), data_version="v1", model=None)


def test_register_is_idempotent(registry):
    first = _register(registry)
    second = _register(registry)
    assert first.experiment_id == second.experiment_id
    assert len(registry.list_experiments()) == 1
    assert registry.trial_count(_recipe()) == 1


def test_trial_count_scoped(registry):
    _register(registry, _recipe(method="a"))
    _register(registry, _recipe(method="b"))
    _register(registry, _recipe(universe="russell2000"))
    assert registry.trial_count(_recipe(method="c")) == 2
    assert registry.trial_count(_recipe(universe="russell2000")) == 1


def test_graduate_requires_post_cutoff_evidence(registry):
    rec = _register(registry, evidence=_evidence("in_window"))
    with pytest.raises(ValueError):
        registry.decide(rec.experiment_id, "graduate", approver="ann")
    assert registry.list_experiments()[0].decision == "none"

    short = _register(registry, _recipe(method="short"), _evidence("post_cutoff", n=11))
    with pytest.raises(ValueError):
        registry.decide(short.experiment_id, "graduate", approver="ann")

    ok = _register(registry, _recipe(method="ok"), _evidence("post_cutoff", n=12))
    decided = registry.decide(ok.experiment_id, "graduate", approver="ann")
    assert decided.decision == "graduate"
    assert decided.decided_by == "ann"
    assert decided.decided_at is not None


def test_shelve_has_no_gate(registry):
    rec = _register(registry)
    assert registry.decide(rec.experiment_id, "shelve", approver="ann").decision == "shelve"


def test_decisions_append_only_latest_wins(registry):
    rec = _register(registry, evidence=_evidence("post_cutoff", n=12))
    registry.decide(rec.experiment_id, "graduate", approver="ann")
    registry.decide(rec.experiment_id, "shelve", approver="bob")
    listed = registry.list_experiments()
    assert len(listed) == 1
    assert listed[0].decision == "shelve"
    assert listed[0].decided_by == "bob"
    rows = registry.store.read_results(SIGNAL_REGISTRY_RUN_ID)
    assert [r["decision"] for r in rows if r["type"] == "decision"] == ["graduate", "shelve"]


def test_decide_unknown_id_raises(registry):
    for decision in ("graduate", "shelve"):
        with pytest.raises(ValueError):
            registry.decide("nope", decision, approver="ann")


def test_experiment_id_stable_and_sensitive():
    a = experiment_id_for(_recipe(), data_version="v1", model=None)
    assert len(a) == 16
    assert a == experiment_id_for(Recipe(**dict(reversed(list(_recipe().model_dump().items())))), data_version="v1", model=None)
    assert a != experiment_id_for(_recipe(), data_version="v2", model=None)
    assert a != experiment_id_for(_recipe(), data_version="v1", model="claude-x")


def test_has(registry):
    rec = _recipe()
    eid = experiment_id_for(rec, data_version="v1", model=None)
    assert not registry.has(eid)
    _register(registry, rec)
    assert registry.has(eid)


def test_decide_rejects_bad_decision_without_writing(registry):
    rec = _register(registry, evidence=_evidence("post_cutoff", n=12))
    before = len(registry.store.read_results(SIGNAL_REGISTRY_RUN_ID))
    with pytest.raises(ValueError):
        registry.decide(rec.experiment_id, "graduated", approver="a")
    assert len(registry.store.read_results(SIGNAL_REGISTRY_RUN_ID)) == before
    assert registry.list_experiments()[0].decision == "none"


@pytest.mark.parametrize("approver", ["", "   "])
@pytest.mark.parametrize("decision", ["graduate", "shelve"])
def test_decide_requires_approver_without_writing(registry, decision, approver):
    rec = _register(registry, evidence=_evidence("post_cutoff", n=12))
    before = len(registry.store.read_results(SIGNAL_REGISTRY_RUN_ID))
    with pytest.raises(ValueError):
        registry.decide(rec.experiment_id, decision, approver=approver)
    assert len(registry.store.read_results(SIGNAL_REGISTRY_RUN_ID)) == before
    assert registry.list_experiments()[0].decision == "none"
