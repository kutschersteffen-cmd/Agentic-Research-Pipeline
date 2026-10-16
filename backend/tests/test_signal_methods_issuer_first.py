from __future__ import annotations

import pytest

from arp.replication.price_data import PricePanel
from arp.replication.sentiment_scoring import SentimentScoreDraft
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.methods.issuer_first import SearchHit
from tests.conftest import FakeLLMClient
from tests.test_signal_methods_base import _month_ends

_SPEC = {"method": "issuer_first", "params": {"peer_group": None}}


class ModelLLM(FakeLLMClient):
    def __init__(self, scores, *, model="m1"):
        super().__init__({"SentimentScoreDraft": [SentimentScoreDraft(score=s, quote="rose", confidence=0.9) for s in scores]})
        self._model = model

    async def complete_structured(self, **kw):
        out, usage = await super().complete_structured(**kw)
        return out, usage.model_copy(update={"model": self._model})


class FakeSearch:
    """Returns one in-window hit per query; `late` maps a query to the `before` values at which it also returns a post-cutoff hit."""

    def __init__(self, late=None, extra=None):
        self.late, self.extra, self.calls = late or {}, extra or {}, []

    def search(self, query, *, before):
        self.calls.append((query, before))
        hits = [SearchHit(f"http://x/{query}", "Head", "Sales rose.", "2018-01-05T00:00:00Z")]
        if before in self.late.get(query, ()):
            hits.append(SearchHit(f"http://x/late/{query}", "Late", "Sales rose after.", "2018-07-01T00:00:00Z"))
        return hits + self.extra.get(query, [])


def _inp(llm, search, months=6, issuers="ABC") -> MethodInput:
    prices = PricePanel(period_ends=_month_ends(months), returns={t: [None] * months for t in issuers}, source="test")
    resources = {k: v for k, v in (("llm", llm), ("search", search)) if v is not None}
    return MethodInput(texts=[], prices=prices, resources=resources)


def test_hit_after_the_cutoff_never_reaches_the_scorer():
    # The tool ignores `before` and always returns the late hit.
    search = FakeSearch(late={"A 2018Q1 results": {"2018-03-31T23:59:59Z", "2018-03-30T23:59:59Z"}})
    llm = ModelLLM([0.5])
    res = run_method(_SPEC, _inp(llm, search, months=3, issuers="A"))
    assert len(llm.prompts) == 1 and "after" not in llm.prompts[0]
    assert res.panel.values["A"] == [None, None, 0.5]


def test_leak_triggers_one_retry_and_rates_are_reported():
    search = FakeSearch(late={
        "A 2018Q1 results": {"2018-03-31T23:59:59Z"},  # fixed by the retry
        "B 2018Q2 results": {"2018-06-30T23:59:59Z", "2018-06-29T23:59:59Z"},  # still leaks
    })
    res = run_method(_SPEC, _inp(ModelLLM([0.1] * 6), search))
    assert res.notes == {
        "leak_rate_first_try": pytest.approx(2 / 6),
        "leak_rate_after_retry": pytest.approx(1 / 6),
        "cells": 6,
        "undated_dropped": 0,
    }
    assert len(search.calls) == 8
    assert ("A 2018Q1 results", "2018-03-30T23:59:59Z") in search.calls
    assert ("B 2018Q2 results", "2018-06-29T23:59:59Z") in search.calls
    assert [c for c in search.calls if c[0] == "C 2018Q1 results"] == [("C 2018Q1 results", "2018-03-31T23:59:59Z")]


def test_missing_or_bad_published_at_is_dropped_and_not_a_leak():
    extra = {"A 2018Q1 results": [
        SearchHit("http://u/1", "N", "Sales rose.", None),
        SearchHit("http://u/2", "G", "Sales rose.", "garbage"),
        SearchHit("http://u/3", "V", "Sales rose.", "2018-02-01T00:00:00"),  # naive
    ]}
    search = FakeSearch(extra=extra)
    llm = ModelLLM([0.2])
    res = run_method(_SPEC, _inp(llm, search, months=3, issuers="A"))
    assert len(llm.prompts) == 1
    assert res.notes["undated_dropped"] == 3
    assert (res.notes["leak_rate_first_try"], res.notes["leak_rate_after_retry"]) == (0.0, 0.0)
    assert len(search.calls) == 1


def test_non_quarter_months_are_none_and_cell_without_hits_makes_no_call():
    class Empty:
        def search(self, query, *, before):
            return []

    llm = ModelLLM([])
    res = run_method(_SPEC, _inp(llm, Empty(), months=6, issuers="A"))
    assert res.panel.values == {"A": [None] * 6}
    assert (res.model, llm.calls, res.notes["cells"]) == (None, [], 2)


def test_scores_land_on_quarter_end_months_only():
    res = run_method(_SPEC, _inp(ModelLLM([0.1, 0.2]), FakeSearch(), months=6, issuers="A"))
    assert res.panel.values["A"] == [None, None, 0.1, None, None, 0.2]
    assert res.model == "m1"


def test_zero_cells_gives_none_rates():
    res = run_method(_SPEC, _inp(ModelLLM([]), FakeSearch(), months=2))
    assert (res.notes["leak_rate_first_try"], res.notes["leak_rate_after_retry"], res.notes["cells"]) == (None, None, 0)


def test_no_search_tool_raises_the_documented_error():
    with pytest.raises(ValueError, match="no search tool configured; the issuer-first variant is interface-only until the owner allows one"):
        run_method(_SPEC, _inp(ModelLLM([]), None))


def test_missing_llm_and_bad_peer_group_raise_value_error():
    with pytest.raises(ValueError, match="resources\\['llm'\\]"):
        run_method(_SPEC, _inp(None, FakeSearch()))
    with pytest.raises(ValueError, match="peer_group"):
        run_method({"method": "issuer_first", "params": {"peer_group": 3}}, _inp(ModelLLM([]), FakeSearch()))


def test_unnamed_model_raises():
    with pytest.raises(ValueError, match="no model"):
        run_method(_SPEC, _inp(ModelLLM([0.1], model=""), FakeSearch(), months=3, issuers="A"))
