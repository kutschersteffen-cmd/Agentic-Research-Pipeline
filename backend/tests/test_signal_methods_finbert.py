from __future__ import annotations

import builtins
import sys

import pytest

from arp.replication.price_data import PricePanel
from arp.signal_lab.methods import finbert
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.text_store import make_record
from tests.test_signal_methods_base import _month_ends

N = 6
TRIPLES = {"up": (0.7, 0.2, 0.1), "down": (0.1, 0.6, 0.3), "flat": (0.2, 0.2, 0.6)}


class FakeFinBert:
    """Scores a document by the first word of its body; remembers every batch and reports 2 texts as cut."""

    name = "fake-finbert"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def score(self, texts: list[str]) -> list[tuple[float, float, float]]:
        self.calls.append(list(texts))
        return [TRIPLES[t.split("\n\n", 1)[1].split()[0]] for t in texts]

    def truncated(self, texts: list[str]) -> int:
        return 2


def _rec(issuer: str, month: int, day: int, body: str, *, title: str = "head"):
    ends = _month_ends(N)
    when = f"{ends[month][:8]}{day:02d}T00:00:00Z"
    return make_record(
        source="tr_news", source_item_id=f"{issuer}{month}{day}{body}", company_id=issuer,
        event_time=when, knowledge_time=when, title=title, body=body,
    )


def _inp(texts, scorer=None) -> MethodInput:
    ends = _month_ends(N)
    prices = PricePanel(ends, {t: [None] * N for t in ("A", "B", "C")}, "test")
    return MethodInput(texts=texts, prices=prices, resources={"finbert": scorer or FakeFinBert()})


SPEC = {"method": "finbert", "params": {}}


def test_score_is_positive_minus_negative_and_cell_is_the_mean():
    inp = _inp([_rec("A", 2, 5, "up x"), _rec("A", 2, 20, "down y"), _rec("B", 2, 5, "flat z")])
    res = run_method(SPEC, inp)
    assert res.panel.values["A"][2] == pytest.approx(((0.7 - 0.2) + (0.1 - 0.6)) / 2)
    assert res.panel.values["B"][2] == pytest.approx(0.0)
    assert res.model == "fake-finbert"


def test_issuer_or_month_without_documents_is_none_not_zero():
    res = run_method(SPEC, _inp([_rec("A", 2, 5, "flat x")]))
    assert res.panel.values["A"][2] == 0.0  # a real neutral score stays a number
    assert res.panel.values["A"][3] is None
    assert res.panel.values["B"] == [None] * N
    assert res.panel.values["C"] == [None] * N


def test_scorer_sees_title_blank_line_body_once_per_document():
    inp = _inp([_rec("A", 1, 5, "up x", title="Hello"), _rec("B", 1, 5, "down y")])
    run_method(SPEC, inp)
    (batch,) = inp.resources["finbert"].calls
    assert sorted(batch) == ["Hello\n\nup x", "head\n\ndown y"]


def test_truncated_note_comes_from_the_scorer_and_is_zero_without_it():
    texts = [_rec("A", 2, 5, "up x")]
    assert run_method(SPEC, _inp(texts)).notes == {"truncated": 2}
    plain = type("Plain", (), {"name": "p", "score": FakeFinBert().score})()
    assert run_method(SPEC, _inp(texts, plain)).notes == {"truncated": 0}


def test_no_documents_does_not_call_the_scorer():
    inp = _inp([])
    res = run_method(SPEC, inp)
    assert inp.resources["finbert"].calls == []
    assert res.panel.values["A"] == [None] * N


def test_missing_scorer_raises_value_error():
    inp = _inp([_rec("A", 2, 5, "up x")])
    inp.resources.clear()
    with pytest.raises(ValueError, match=r"pass a scorer in resources\['finbert'\]"):
        run_method(SPEC, inp)


@pytest.mark.parametrize("params", [{"bogus": 1}, {"alpha": 2}])
def test_params_are_rejected(params):
    with pytest.raises(ValueError, match="no params"):
        run_method({"method": "finbert", "params": params}, _inp([]))


@pytest.mark.parametrize(
    "bad",
    [
        [(0.5, 0.5, 0.0)] * 1,  # one triple short for two documents
        [(0.5, 0.5), (0.5, 0.5)],
        [(0.5, 0.5, float("nan")), (0.5, 0.5, 0.0)],
        [(1.2, 0.0, 0.0), (0.5, 0.5, 0.0)],
        [(-0.1, 0.5, 0.6), (0.5, 0.5, 0.0)],
        [(True, 0.0, 0.0), (0.5, 0.5, 0.0)],
        [("a", "b", "c"), (0.5, 0.5, 0.0)],
        None,
    ],
)
def test_bad_scorer_output_raises_value_error(bad):
    scorer = FakeFinBert()
    scorer.score = lambda texts: bad
    with pytest.raises(ValueError, match="triples"):
        run_method(SPEC, _inp([_rec("A", 2, 5, "up x"), _rec("B", 2, 5, "down y")], scorer))


def test_no_lookahead():
    texts = [_rec(t, m, 10, w) for t in ("A", "B") for m, w in enumerate(["up", "down", "flat", "up", "down", "up"])]
    assert lookahead_violations(SPEC, _inp(texts), at=[2, 3, 4]) == []


def test_default_finbert_without_the_extra_raises_the_documented_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)  # makes `import transformers` raise ImportError
    with pytest.raises(ValueError, match=r"FinBERT needs the finbert extra: pip install 'arp\[finbert\]'"):
        finbert.default_finbert()


def test_default_finbert_turns_a_broken_install_into_the_same_error(monkeypatch):
    real_import = builtins.__import__

    def broken(name, *args, **kwargs):
        if name == "transformers":
            raise RuntimeError("operator torchvision::nms does not exist")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    with pytest.raises(ValueError, match=r"pip install 'arp\[finbert\]'"):
        finbert.default_finbert()


def test_default_finbert_maps_labels_by_name_and_counts_long_texts(monkeypatch):
    class FakePipe:
        @staticmethod
        def tokenizer(texts, truncation):
            return {"input_ids": [[0] * len(t.split()) for t in texts]}

        def __init__(self, *a, **kw) -> None:
            self.kw = kw

        def __call__(self, texts):
            return [[{"label": "Neutral", "score": 0.1}, {"label": "NEGATIVE", "score": 0.2}, {"label": "positive", "score": 0.7}]
                    for _ in texts]

    fake = type(sys)("transformers")
    fake.pipeline = lambda task, **kw: (setattr(FakePipe, "seen", (task, kw)), FakePipe())[1]
    monkeypatch.setitem(sys.modules, "transformers", fake)
    scorer = finbert.default_finbert()
    assert scorer.name == "ProsusAI/finbert"
    assert FakePipe.seen == (
        "text-classification", {"model": "ProsusAI/finbert", "top_k": None, "truncation": True, "max_length": 512}
    )
    assert scorer.score(["a", "b"]) == [(0.7, 0.2, 0.1)] * 2
    assert scorer.truncated(["w " * 600, "short", "w " * 513]) == 2
