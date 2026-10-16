from __future__ import annotations

import sys

import numpy as np
import pytest

from arp.replication.price_data import PricePanel
from arp.signal_lab.methods import topics
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.text_store import make_record
from arp.signal_lab.times import month_end_time
from tests.test_signal_methods_base import _month_ends
from tests.test_signal_methods_embedding import DIM, FakeEmbedder


class FakeTopicModel:
    """Topic 0 is any text containing this fit's keyword, topic 1 the rest, topic -1 text with 'noise'."""

    def __init__(self, log: list[dict], keywords: list[str], sims: list[float]) -> None:
        self.entry = {"docs": [], "shape": None}
        log.append(self.entry)
        self.keyword = keywords[min(len(log), len(keywords)) - 1]
        self.sims = sims

    def fit(self, docs, embeddings):
        self.entry["docs"], self.entry["shape"] = list(docs), embeddings.shape

    def transform(self, docs, embeddings):
        assert embeddings.shape == (len(docs), DIM)
        return [-1 if "noise" in d else 0 if self.keyword in d else 1 for d in docs], None

    def find_topics(self, query, top_n):
        return ([-1, 0, 1][: top_n + 1], self.sims[: top_n + 1])

    def get_topic(self, topic_id):
        return [(self.keyword, 0.5), ("other", 0.1)]


def _factory(log, keywords=("kw",), sims=(0.9, 0.8, 0.1)):
    return lambda: FakeTopicModel(log, list(keywords), list(sims))


def _inp(items: dict[tuple[str, int], list[str]], n: int, log, **factory_kw) -> MethodInput:
    """items[(issuer, month)] = bodies; every issuer in `issuers` has a price row."""
    ends = _month_ends(n)
    issuers = sorted({t for t, _ in items} | {"B"})
    texts = [
        make_record(
            source="tr_news", source_item_id=f"{t}-{j}-{k}", company_id=t,
            event_time=f"{ends[j][:8]}15T00:00:00Z", knowledge_time=f"{ends[j][:8]}15T00:00:00Z",
            title="", body=f"{body} {t}{j}x{k}",
        )
        for (t, j), bodies in items.items() for k, body in enumerate(bodies)
    ]
    prices = PricePanel(ends, {t: [None] * n for t in issuers}, "test")
    return MethodInput(
        texts=texts, prices=prices,
        resources={"embedder": FakeEmbedder(), "topic_model": _factory(log, **factory_kw)},
    )


def _spec(**params) -> dict:
    return {"method": "topic_attention", "params": {"query": "q", **params}}


def _wide(n: int = 36) -> dict[tuple[str, int], list[str]]:
    return {(t, j): ["kw", "other"] for t in ("A", "C") for j in range(n)}


def test_each_refit_sees_only_published_text():
    log: list[dict] = []
    inp = _inp(_wide(), 36, log)
    run_method(_spec(), inp)
    ends = _month_ends(36)
    when = {f"{r.title} {r.body}".strip(): r.event_time for r in inp.texts}
    assert len(log) == 3
    for entry, r in zip(log, (11, 23, 35), strict=True):
        assert len(entry["docs"]) == 2 * 2 * (r + 1)  # 2 issuers x 2 items x months 0..r
        assert max(when[d] for d in entry["docs"]) <= month_end_time(ends[r])
        assert entry["shape"] == (len(entry["docs"]), DIM)


def test_months_use_the_latest_earlier_refit():
    log: list[dict] = []
    items = {("A", 11): ["alpha"], ("A", 12): ["alpha"], ("A", 22): ["alpha"], ("A", 23): ["beta"], ("A", 24): ["alpha"]}
    res = run_method(_spec(), _inp(items, 36, log, keywords=("alpha", "beta", "gamma")))
    a = res.panel.values["A"]
    # Month 12 is scored by the model fitted at 11 (alpha), month 24 by the one fitted at 23 (beta).
    assert a[12] == 1.0
    assert a[22] == 1.0
    assert a[23] == 1.0
    assert a[24] == 0.0


def test_intensity_share_and_change_values():
    items = {
        ("A", 2): ["kw", "x"], ("A", 3): ["kw"], ("A", 5): ["x", "x", "x"], ("A", 6): ["kw", "kw"],
        ("C", 6): ["kw"],
    }
    base = dict(min_train_months=3, refit_months=100, lookback_months=3)
    got = {
        m: run_method(_spec(mode=m, **base), _inp(items, 8, [])).panel.values
        for m in ("intensity", "share", "change")
    }
    assert got["intensity"]["A"] == [None, None, 1.0, 1.0, 0.0, 0.0, 2.0, 0.0]
    assert got["share"]["A"] == [None, None, 0.5, 1.0, None, 0.0, 1.0, None]
    chg = got["change"]["A"]
    assert chg[:5] == [None] * 5
    assert chg[5:] == pytest.approx([-2 / 3, 5 / 3, -2 / 3])
    assert got["intensity"]["C"] == [None, None, None, None, None, None, 1.0, 0.0]


def test_issuer_with_no_items_is_none_not_zero():
    for mode in ("intensity", "share", "change"):
        res = run_method(_spec(mode=mode, min_train_months=3, refit_months=100), _inp({("A", 4): ["kw"]}, 8, []))
        assert res.panel.values["B"] == [None] * 8


def test_no_topic_over_threshold_gives_none_and_is_counted():
    log: list[dict] = []
    res = run_method(_spec(min_similarity=0.95), _inp(_wide(), 36, log))
    assert res.panel.values["A"] == [None] * 36
    assert res.notes["refits_without_topic"] == 3
    assert all(r["topics"] == [] for r in res.notes["refits"])


def test_outlier_topic_is_never_a_target_and_notes_describe_the_topic():
    items = {("A", 11): ["kw"], ("A", 12): ["kw noise", "kw"]}
    res = run_method(_spec(top_n=2), _inp(items, 14, []))
    # find_topics ranks -1 first at 0.9 and topic 0 at 0.8; only topic 0 counts, and the 'noise' text is topic -1.
    assert res.panel.values["A"][12] == 1.0
    assert res.notes["refits_without_topic"] == 0
    assert res.notes["refits"] == [
        {"refit_index": 11, "period_end": _month_ends(14)[11], "topics": [{"id": 0, "similarity": 0.8, "top_words": ["kw", "other"]}]}
    ]
    assert res.model == "fake-hash-embedder"


def test_missing_embedder_or_topic_model_raises_value_error():
    inp = _inp(_wide(14), 14, [])
    for key in ("embedder", "topic_model"):
        res = {k: v for k, v in inp.resources.items() if k != key}
        with pytest.raises(ValueError, match=key):
            run_method(_spec(), MethodInput(inp.texts, inp.prices, resources=res))


@pytest.mark.parametrize("bad", [
    {"query": ""}, {"query": 3}, {"top_n": 0}, {"top_n": True}, {"min_similarity": "x"}, {"min_similarity": float("nan")},
    {"refit_months": 0}, {"min_train_months": 1.5}, {"lookback_months": -1}, {"mode": "bogus"}, {"nope": 1},
])
def test_bad_params_raise_value_error(bad):
    spec = {"method": "topic_attention", "params": {"query": "q", **bad}}
    with pytest.raises(ValueError):
        run_method(spec, _inp(_wide(14), 14, []))


def test_missing_topics_extra_raises_the_documented_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "bertopic", None)
    with pytest.raises(ValueError, match=r"pip install 'arp\[topics\]'"):
        topics.default_topic_model(FakeEmbedder())


def test_topic_attention_has_no_lookahead():
    for mode in ("intensity", "share", "change"):
        spec = _spec(mode=mode, min_train_months=6, refit_months=6, lookback_months=6)
        assert lookahead_violations(spec, _inp(_wide(24), 24, [])) == []


def test_real_bertopic_smoke():
    pytest.importorskip("bertopic")
    pytest.importorskip("umap")
    vocab = {
        "A": ["oil", "gas", "drilling", "pipeline", "crude", "refinery", "barrel", "rig"],
        "B": ["bank", "loan", "credit", "deposit", "interest", "mortgage", "lender", "branch"],
    }
    rng = np.random.default_rng(0)
    ends = _month_ends(20)
    issuers = [f"I{k}" for k in range(10)]
    texts = []
    for j in range(20):
        for k, t in enumerate(issuers):
            words = vocab["A" if k % 2 else "B"]
            texts.append(make_record(
                source="tr_news", source_item_id=f"{t}-{j}", company_id=t,
                event_time=f"{ends[j][:8]}15T00:00:00Z", knowledge_time=f"{ends[j][:8]}15T00:00:00Z",
                title="", body=" ".join(rng.choice(words, 8)),
            ))
    embedder = FakeEmbedder()
    inp = MethodInput(
        texts=texts, prices=PricePanel(ends, {t: [None] * 20 for t in issuers}, "test"),
        resources={"embedder": embedder, "topic_model": topics.default_topic_model(embedder, min_topic_size=10)},
    )
    res = run_method(_spec(query="oil gas drilling", min_train_months=8, refit_months=12, min_similarity=0.0), inp)
    vals = [v for t in issuers for v in res.panel.values[t] if v is not None]
    assert vals and max(vals) > 0
