from __future__ import annotations

import pytest

from arp.llm.base import LLMUsage
from arp.replication.sentiment_scoring import SentimentScoreDraft
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.methods.llm_scoring import estimate_llm_calls, rerun_stability, to_source_document
from arp.signal_lab.text_store import make_record
from tests.conftest import FakeLLMClient
from tests.test_signal_methods_base import _prices

_SPEC = {"method": "grounded_llm", "params": {}}


class ModelLLM(FakeLLMClient):
    """The fake client, but reporting a model name (and optionally cached answers) like a real one."""

    def __init__(self, drafts, *, model="m1", cached=False):
        super().__init__({"SentimentScoreDraft": drafts})
        self._model, self._cached = model, cached

    async def complete_structured(self, **kw):
        out, usage = await super().complete_structured(**kw)
        return out, usage.model_copy(update={"model": self._model, "cached": self._cached})


def _draft(score: float, quote: str = "rose") -> SentimentScoreDraft:
    return SentimentScoreDraft(score=score, quote=quote, confidence=0.9)


def _text(issuer: str, when: str, tag: str = "x", body: str = "Sales rose."):
    return make_record(
        source="tr_news", source_item_id=f"{issuer}{when}{tag}", company_id=issuer,
        event_time=when, knowledge_time=when, title="Head", body=body,
    )


def _inp(texts, llm=None) -> MethodInput:
    return MethodInput(texts=texts, prices=_prices(3), resources={} if llm is None else {"llm": llm})


def test_to_source_document_joins_title_and_body():
    rec = _text("A", "2018-01-15T00:00:00Z")
    doc = to_source_document(rec)
    assert (doc.doc_id, doc.company_id, doc.full_text, doc.published_at) == (
        rec.item_id, "A", "Head\n\nSales rose.", "2018-01-15T00:00:00Z",
    )


def test_ungrounded_quote_is_excluded_and_counted():
    texts = [_text("A", "2018-01-15T00:00:00Z"), _text("A", "2018-02-15T00:00:00Z")]
    llm = ModelLLM([_draft(0.5), _draft(-0.9, "not in the text")])
    res = run_method(_SPEC, _inp(texts, llm))
    assert res.panel.values["A"] == [0.5, None, None]
    assert res.notes == {"calls": 2, "ungrounded": 1}
    assert res.model == "m1"


def test_cell_is_the_mean_of_grounded_scores():
    texts = [_text("A", "2018-01-10T00:00:00Z", "1"), _text("A", "2018-01-20T00:00:00Z", "2")]
    res = run_method(_SPEC, _inp(texts, ModelLLM([_draft(0.8), _draft(-0.2)])))
    assert res.panel.values["A"] == [pytest.approx(0.3), None, None]


def test_missing_llm_raises_value_error():
    with pytest.raises(ValueError, match="resources\\['llm'\\]"):
        run_method(_SPEC, _inp([_text("A", "2018-01-15T00:00:00Z")]))


def test_no_texts_means_no_calls_and_no_model():
    res = run_method(_SPEC, _inp([], ModelLLM([])))
    assert (res.model, res.notes, res.panel.values) == (None, {"calls": 0, "ungrounded": 0}, {})


def test_unnamed_model_raises_when_calls_were_made():
    with pytest.raises(ValueError, match="no model"):
        run_method(_SPEC, _inp([_text("A", "2018-01-15T00:00:00Z")], ModelLLM([_draft(0.1)], model="")))


def test_two_models_raise():
    class Two(ModelLLM):
        async def complete_structured(self, **kw):
            out, usage = await FakeLLMClient.complete_structured(self, **kw)
            return out, usage.model_copy(update={"model": f"m{len(self.calls)}"})

    texts = [_text("A", "2018-01-15T00:00:00Z"), _text("A", "2018-02-15T00:00:00Z")]
    with pytest.raises(ValueError, match="more than one model"):
        run_method(_SPEC, _inp(texts, Two([_draft(0.1), _draft(0.2)])))


@pytest.mark.parametrize("bad", [True, -1, 1, 2.0, "3"])
def test_stability_runs_is_validated(bad):
    with pytest.raises(ValueError, match="stability_runs"):
        run_method({"method": "grounded_llm", "params": {"stability_runs": bad}}, _inp([], ModelLLM([])))


def test_estimate_counts_items_and_tokens():
    # "Head\n\n" + body: 6 + 10 chars and 6 + 30 chars; the text before the grid is not counted.
    texts = [
        _text("A", "2018-01-15T00:00:00Z", body="0123456789"),
        _text("B", "2018-02-15T00:00:00Z", body="x" * 30),
        _text("B", "2017-06-15T00:00:00Z"),
    ]
    assert estimate_llm_calls(_inp(texts)) == {"calls": 2, "approx_input_tokens": (16 + 36) // 4}


def test_rerun_stability_is_one_for_identical_runs_and_lower_for_noisy_ones():
    same = lambda: ([0.1, 0.5, 0.9, 0.3], [LLMUsage()])  # noqa: E731
    assert rerun_stability(same, 3) == pytest.approx(1.0)
    runs = iter([[1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 4.0, 3.0], [4.0, 3.0, 2.0, 1.0]])
    noisy = rerun_stability(lambda: (next(runs), []), 3)
    assert noisy == pytest.approx((0.8 - 1.0 - 0.8) / 3)


def test_rerun_stability_refuses_cached_answers():
    with pytest.raises(ValueError, match="cached answers make stability meaningless"):
        rerun_stability(lambda: ([1.0, 2.0, 3.0], [LLMUsage(cached=True)]), 2)


def test_rerun_stability_input_errors_and_undefined_pairs():
    with pytest.raises(ValueError, match="runs"):
        rerun_stability(lambda: ([1.0, 2.0, 3.0], []), 1)
    lengths = iter([[1.0, 2.0, 3.0], [1.0, 2.0]])
    with pytest.raises(ValueError, match="differ in length"):
        rerun_stability(lambda: (next(lengths), []), 2)
    assert rerun_stability(lambda: ([2.0, 2.0, 2.0], []), 3) is None


def test_method_reports_rerun_stability_in_notes():
    texts = [_text("A", f"2018-0{m}-15T00:00:00Z") for m in (1, 2, 3)]
    drafts = [_draft(s) for s in (0.1, 0.5, 0.9) * 3]  # the main run plus two identical reruns
    res = run_method(
        {"method": "grounded_llm", "params": {"stability_runs": 2}}, _inp(texts, ModelLLM(drafts))
    )
    assert res.notes == {"calls": 3, "ungrounded": 0, "rerun_stability": pytest.approx(1.0)}


def test_method_refuses_a_caching_client_when_stability_is_asked():
    texts = [_text("A", "2018-01-15T00:00:00Z")]
    llm = ModelLLM([_draft(0.1)] * 3, cached=True)
    with pytest.raises(ValueError, match="cached answers"):
        run_method({"method": "grounded_llm", "params": {"stability_runs": 2}}, _inp(texts, llm))


async def test_works_inside_a_running_event_loop():
    res = run_method(_SPEC, _inp([_text("A", "2018-01-15T00:00:00Z")], ModelLLM([_draft(0.4)])))
    assert res.panel.values["A"] == [0.4, None, None]
