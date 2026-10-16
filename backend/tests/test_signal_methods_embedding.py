from __future__ import annotations

import hashlib
import random

import numpy as np
import pytest

from arp.replication.price_data import PricePanel
from arp.signal_lab.methods import embedding
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.stats import rank_ic_series
from arp.signal_lab.text_store import make_record
from tests.test_signal_methods_base import _month_ends

N = 36
ISSUERS = [f"I{k:02d}" for k in range(12)]
GOOD = ["growth", "record", "beat", "upgrade"]
BAD = ["recall", "probe", "miss", "downgrade"]
DIM = 64


class FakeEmbedder:
    """Hashed bag of words, L2-normalised; remembers every batch it was asked to embed."""

    name = "fake-hash-embedder"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        out = np.zeros((len(texts), DIM))
        for r, text in enumerate(texts):
            for w in text.split():
                out[r, int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1
        return out / np.linalg.norm(out, axis=1, keepdims=True)


def _corpus(*, skip: set[tuple[str, int]] = frozenset()) -> MethodInput:
    """Issuer t's month-j text mixes good and bad words; its return at j + 1 is the good-word share plus noise."""
    rng = random.Random(7)
    ends = _month_ends(N)
    returns: dict[str, list[float | None]] = {t: [None] * N for t in ISSUERS}
    texts = []
    for j in range(N):
        for t in ISSUERS:
            n_good = rng.randint(0, 4)
            words = GOOD[:n_good] + BAD[: 4 - n_good]
            if j + 1 < N:
                returns[t][j + 1] = 0.01 * n_good + rng.gauss(0, 0.002)
            if (t, j) in skip:
                continue
            texts.append(make_record(
                source="tr_news", source_item_id=f"{t}{j}", company_id=t,
                event_time=f"{ends[j][:8]}15T00:00:00Z", knowledge_time=f"{ends[j][:8]}15T00:00:00Z",
                title="", body=" ".join(words),
            ))
    return MethodInput(texts=texts, prices=PricePanel(ends, returns, "test"), resources={"embedder": FakeEmbedder()})


def _spec(**params) -> dict:
    return {"method": "embedding_ridge", "params": params}


def test_ridge_recovers_a_planted_signal():
    inp = _corpus()
    res = run_method(_spec(min_train_months=12), inp)
    ics = [ic for end, ic in rank_ic_series(res.panel, inp.prices) if end >= _month_ends(N)[18]]
    assert len(ics) >= 12
    assert float(np.mean(ics)) > 0.5


def test_first_min_train_months_are_none_and_no_lookahead():
    inp = _corpus()
    res = run_method(_spec(min_train_months=12), inp)
    for t in ISSUERS:
        # Month j is trainable once i > j, so the first scored month is i = min_train_months.
        assert all(v is None for v in res.panel.values[t][:12])
        assert all(isinstance(v, float) for v in res.panel.values[t][12 : N])
    assert lookahead_violations(_spec(min_train_months=12), inp, at=[14, 20, 30]) == []


def test_issuer_without_text_in_a_month_is_none_not_zero():
    inp = _corpus(skip={("I03", 20)})
    res = run_method(_spec(min_train_months=12), inp)
    assert res.panel.values["I03"][20] is None
    assert isinstance(res.panel.values["I03"][21], float)


def test_missing_embedder_raises_value_error():
    inp = _corpus()
    inp.resources.clear()
    with pytest.raises(ValueError, match=r"pass an embedder in resources\['embedder'\]"):
        run_method(_spec(), inp)


def test_result_model_is_the_embedder_name():
    assert run_method(_spec(min_train_months=12), _corpus()).model == "fake-hash-embedder"


def test_embeds_each_item_once():
    inp = _corpus()
    run_method(_spec(min_train_months=12), inp)
    (batch,) = inp.resources["embedder"].calls
    assert len(batch) == len(inp.texts) == N * len(ISSUERS)


def test_ridge_closed_form_matches_hand_solution():
    x = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 0.0]])
    y = np.array([0.1, 0.9, 0.6, 0.3])
    xc, yc = x - x.mean(axis=0), y - y.mean()
    beta = np.linalg.inv(xc.T @ xc + 2.0 * np.eye(2)) @ xc.T @ yc
    got = embedding.ridge_predict(x, y, np.array([[1.0, 2.0]]), alpha=2.0)
    assert got == pytest.approx([y.mean() + (np.array([1.0, 2.0]) - x.mean(axis=0)) @ beta])


@pytest.mark.parametrize(
    "params",
    [{"alpha": 0}, {"alpha": -1.0}, {"alpha": True}, {"alpha": "10"}, {"alpha": float("nan")},
     {"min_train_months": 0}, {"min_train_months": True}, {"min_train_months": 2.5}, {"bogus": 1}],
)
def test_bad_params_raise_value_error(params):
    with pytest.raises(ValueError):
        run_method(_spec(**params), _corpus())


def test_embedder_with_wrong_shape_raises_value_error():
    inp = _corpus()
    inp.resources["embedder"].embed = lambda texts: np.zeros((len(texts) - 1, 3))
    with pytest.raises(ValueError, match="embedder"):
        run_method(_spec(), inp)
