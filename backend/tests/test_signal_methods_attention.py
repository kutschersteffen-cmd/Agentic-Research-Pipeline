from __future__ import annotations

import pytest

from arp.signal_lab.methods import attention  # noqa: F401  (registers the method)
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.text_store import make_record
from tests.test_signal_methods_base import _month_ends, _prices


def _item(issuer: str, when: str, title: str = "t", body: str = "b", n: int = 0):
    return make_record(
        source="tr_news", source_item_id=f"{issuer}{when}{n}", company_id=issuer,
        event_time=when, knowledge_time=when, title=title, body=body,
    )


def _run(texts, **params):
    params = {"terms": ["tariff"], "mode": "intensity", "lookback_months": 12, **params}
    inp = MethodInput(texts=texts, prices=_prices(30))
    return run_method({"method": "narrative_attention", "params": params}, inp), inp


def test_intensity_counts_matching_items_per_month():
    texts = [
        _item("A", "2018-01-10T00:00:00Z", title="New Tariff announced"),
        _item("A", "2018-01-12T00:00:00Z", body="about the TARIFF.", n=1),
        _item("A", "2018-01-15T00:00:00Z", title="nothing", n=2),
        _item("A", "2018-02-10T00:00:00Z", title="tariffs"),  # plural is not the whole word
        _item("B", "2018-02-10T00:00:00Z", title="tariff"),
    ]
    res, _ = _run(texts)
    assert res.model is None
    assert res.panel.values["A"][:3] == [2.0, 0.0, 0.0]
    assert res.panel.values["B"][:3] == [None, 1.0, 0.0]
    assert set(res.panel.values) == set("ABCDEF")


def test_phrase_and_whole_word_matching():
    texts = [
        _item("A", "2018-01-10T00:00:00Z", title="supply   chain\nshock"),
        _item("A", "2018-01-11T00:00:00Z", title="supply and chain", n=1),
        _item("A", "2018-01-12T00:00:00Z", title="sustain growth", n=2),
        _item("A", "2018-01-13T00:00:00Z", body="AI is here", n=3),
    ]
    res, _ = _run(texts, terms=["supply chain"])
    assert res.panel.values["A"][0] == 1.0
    res, _ = _run(texts, terms=["AI"])
    assert res.panel.values["A"][0] == 1.0  # "AI is here" only, not "sustain"


def test_change_is_intensity_minus_trailing_mean():
    texts = [_item("A", f"2018-{m:02d}-10T00:00:00Z", title="tariff", n=k)
             for m, count in {1: 1, 2: 3, 3: 2, 4: 6}.items() for k in range(count)]
    res, _ = _run(texts, mode="change")
    vals = res.panel.values["A"]
    assert vals[:3] == [None, None, None]  # fewer than 3 prior months
    assert vals[3] == pytest.approx(6 - (1 + 3 + 2) / 3)
    assert vals[4] == pytest.approx(0 - (1 + 3 + 2 + 6) / 4)


def test_no_coverage_is_none_but_no_matches_is_zero():
    texts = [
        _item("A", "2018-01-10T00:00:00Z", title="tariff"),
        _item("B", "2018-01-10T00:00:00Z", title="weather"),
    ]
    res, _ = _run(texts, lookback_months=2)
    assert res.panel.values["A"][:4] == [1.0, 0.0, 0.0, None]  # window [1, 3] is empty at index 3
    assert res.panel.values["B"][:4] == [0.0, 0.0, 0.0, None]
    assert res.panel.values["C"][0] is None


def test_errors():
    with pytest.raises(ValueError, match="terms"):
        _run([], terms=[])
    with pytest.raises(ValueError, match="mode"):
        _run([], mode="nope")


def test_no_lookahead():
    texts = [_item("A", f"{p[:7]}-10T00:00:00Z", title="tariff", n=k) for p in _month_ends(12) for k in range(int(p[5:7]) % 4)]
    for mode in ("intensity", "change"):
        spec = {"method": "narrative_attention", "params": {"terms": ["tariff"], "mode": mode, "lookback_months": 4}}
        assert lookahead_violations(spec, MethodInput(texts=texts, prices=_prices(30))) == []
