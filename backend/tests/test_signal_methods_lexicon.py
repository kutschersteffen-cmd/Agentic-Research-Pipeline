from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from arp.replication.price_data import PricePanel
from arp.signal_lab.methods import lexicon
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.text_store import make_record
from tests.test_signal_methods_base import _month_ends

N = 30
ISSUERS = "ABCDEF"
POS = "Growth and record results for the company"
NEG = "Recall and probe results for the company"
NEUTRAL = "Results for the company"


def _up(k: int, j: int) -> bool:
    return (k + j) % 6 < 3  # the above-median half rotates every month


def _corpus(*, start: int = 0, neutral_only: bool = False, override: dict | None = None) -> MethodInput:
    """Issuer k's month-j item is planted positive iff its return at j + 1 is above the month's median."""
    ends = _month_ends(N)
    returns: dict[str, list[float | None]] = {t: [None] * N for t in ISSUERS}
    texts = []
    for j in range(N):
        for k, t in enumerate(ISSUERS):
            up = _up(k, j)
            if j + 1 < N:
                returns[t][j + 1] = (1 if up else -1) * (0.02 + 0.001 * k)
            if j < start:
                continue
            body = NEUTRAL if neutral_only else POS if up else NEG
            if up and j < 5 and k == (6 - j % 6) % 6:
                body += " surge"  # charged-looking but seen in fewer than kappa documents
            body = (override or {}).get((t, j), body)
            if body is None:
                continue
            texts.append(make_record(
                source="tr_news", source_item_id=f"{t}{j}", company_id=t,
                event_time=f"{ends[j][:8]}15T00:00:00Z", knowledge_time=f"{ends[j][:8]}15T00:00:00Z",
                title="", body=body,
            ))
    return MethodInput(texts=texts, prices=PricePanel(ends, returns, "test"))


def _run(inp: MethodInput, **params):
    return run_method({"method": "sestm", "params": params}, inp)


def test_screening_keeps_charged_and_drops_neutral_and_rare_words():
    res = _run(_corpus())
    assert res.model is None
    assert res.notes["charged_set_size"] == 4
    assert res.notes["most_positive_words"] == ["growth", "record"]
    assert res.notes["most_negative_words"] == ["probe", "recall"]
    assert res.notes["months_without_model"] == []

    docs = [Counter(POS.lower().split() + ["surge"]) for _ in range(5)] + [Counter(NEG.lower().split())] * 30
    docs += [Counter(POS.lower().split())] * 25
    positive = [True] * 5 + [False] * 30 + [True] * 25
    got = lexicon.screen(docs, positive, alpha_plus=0.05, alpha_minus=0.05, kappa=20)
    assert got == {"growth": 1.0, "record": 1.0, "recall": 0.0, "probe": 0.0}


def test_topic_columns_are_nonnegative_and_sum_to_one():
    docs = [Counter(POS.lower().split())] * 50 + [Counter(NEG.lower().split())] * 50
    rets = list(np.linspace(0.001, 0.1, 50)) + list(np.linspace(-0.1, -0.001, 50))
    charged = ["growth", "probe", "recall", "record"]
    o = lexicon.topics(docs, rets, charged)
    assert (o >= 0).all()
    assert o.sum(axis=0) == pytest.approx([1.0, 1.0])
    assert o[:, 0] == pytest.approx([0.5, 0.0, 0.0, 0.5])
    assert o[:, 1] == pytest.approx([0.0, 0.5, 0.5, 0.0])
    assert lexicon.topics(docs, [0.01] * 100, charged) is None  # p_hat constant: W W' is singular


def test_score_orders_positive_above_negative_documents():
    vals = _run(_corpus()).panel.values
    for i in (24, 25, 29):
        for k, t in enumerate(ISSUERS):
            # O+ = (1/2, 1/2) on the two positive words, so a positive item maximises log(p/2) + log(p(1-p)) at 2/3.
            assert vals[t][i] == pytest.approx(0.667 if _up(k, i) else 0.333, abs=1e-9)


def test_large_lam_pulls_the_score_to_one_half():
    vals = _run(_corpus(), lam=1000).panel.values
    assert all(abs(vals[t][25] - 0.5) < 0.01 for t in ISSUERS)


def test_document_without_charged_words_has_no_score():
    inp = _corpus(override={("A", 25): NEUTRAL, ("B", 25): None})
    vals = _run(inp).panel.values
    assert vals["A"][25] is None
    assert vals["B"][25] is None  # no item at all
    assert vals["C"][25] == pytest.approx(0.333, abs=1e-9)


def test_document_score_counts_every_occurrence():
    o = np.array([[0.5, 0.0], [0.0, 0.5], [0.0, 0.5], [0.5, 0.0]])
    charged = ["growth", "probe", "recall", "record"]
    mixed = [Counter(growth=3, record=1, recall=1), Counter(growth=1, recall=1), Counter(company=2)]
    got = lexicon.score(mixed, charged, o, lam=1.0)
    grid = np.arange(1, 1000) / 1000
    objective = (4 * np.log(0.5 * grid) + np.log(0.5 * (1 - grid))) / 5 + np.log(grid * (1 - grid))
    assert got[0] == pytest.approx(grid[np.argmax(objective)])
    assert got[1] == pytest.approx(0.5)
    assert got[2] is None


def test_first_min_train_months_are_none():
    vals = _run(_corpus()).panel.values
    assert all(vals[t][i] is None for t in ISSUERS for i in range(24))
    assert vals["A"][24] == pytest.approx(0.667, abs=1e-9)
    # Months without a labelled item do not count: text starting at month 2 first scores at 2 + 24.
    vals = _run(_corpus(start=2)).panel.values
    assert all(vals[t][i] is None for t in ISSUERS for i in range(26))
    assert vals["A"][26] == pytest.approx(0.667, abs=1e-9)
    vals = _run(_corpus(), min_train_months=10).panel.values
    assert vals["A"][9] is None and vals["A"][10] == pytest.approx(0.333, abs=1e-9)


def test_labels_not_yet_realised_are_never_used():
    inp = _corpus()
    i = 25
    base = _run(inp).panel.values
    garbage = {t: r[: i + 1] + [(-1) ** k * 1e6 * (k + 1) for k in range(N - i - 1)] for t, r in inp.prices.returns.items()}
    bad = MethodInput(texts=inp.texts, prices=PricePanel(inp.prices.period_ends, garbage, "test"))
    got = _run(bad).panel.values
    assert all(got[t][i] == base[t][i] for t in ISSUERS)
    assert got["A"][i] == pytest.approx(0.667, abs=1e-9)
    assert lookahead_violations({"method": "sestm", "params": {}}, inp, at=[24, 27]) == []


def test_empty_charged_set_gives_none_and_is_listed():
    inp = _corpus(neutral_only=True)
    res = _run(inp)
    assert all(v is None for vals in res.panel.values.values() for v in vals)
    assert set(res.panel.values) == set(ISSUERS)
    assert res.notes["months_without_model"] == inp.prices.period_ends[24:]
    assert res.notes["charged_set_size"] == 0
    assert res.notes["most_positive_words"] == []


@pytest.mark.parametrize("params", [
    {"kappa": "20"}, {"kappa": True}, {"kappa": 0}, {"alpha_plus": -0.1}, {"alpha_minus": 0.6},
    {"alpha_plus": "0.05"}, {"lam": -1}, {"lam": None}, {"lam": float("nan")}, {"min_train_months": 0}, {"min_train_months": 2.5},
    {"kapa": 20},
])
def test_bad_params_raise_value_error(params):
    with pytest.raises(ValueError, match="sestm"):
        _run(_corpus(), **params)
