import pytest

from arp.replication.sentiment_scoring import SentimentScoreDraft, build_sentiment_panel, score_document_sentiment
from arp.schemas.common import DocType, SourceDocument


def _doc(doc_id: str, text: str) -> SourceDocument:
    return SourceDocument(doc_id=doc_id, company_id="AAA", doc_type=DocType.OTHER, title="t", full_text=text)


async def test_score_document_sentiment_returns_draft_and_usage(fake_llm):
    draft_in = SentimentScoreDraft(score=0.6, quote="strong guidance for next quarter", confidence=0.8)
    llm = fake_llm({"SentimentScoreDraft": [draft_in]})
    draft_out, usage = await score_document_sentiment("AAA", _doc("d1", "The company issued strong guidance for next quarter."), llm)
    assert draft_out.score == 0.6
    assert usage.input_tokens == 10


async def test_build_sentiment_panel_grounded_and_ungrounded_cells(fake_llm):
    period_ends = ["2020-01-01", "2020-02-01", "2020-03-01"]
    doc_jan = _doc("d_jan", "Sales rose sharply this quarter, beating expectations.")
    doc_feb = _doc("d_feb", "Management provided cautious commentary about headwinds.")
    documents_by_ticker_period = {
        "AAA": {"2020-01-01": doc_jan, "2020-02-01": doc_feb},
    }
    llm = fake_llm(
        {
            "SentimentScoreDraft": [
                SentimentScoreDraft(score=0.7, quote="Sales rose sharply this quarter", confidence=0.9),
                # This quote does not appear in doc_feb's text at all -- fails grounding.
                SentimentScoreDraft(score=-0.5, quote="a quote that is not in the document", confidence=0.6),
            ]
        }
    )
    panel, records, usages = await build_sentiment_panel(documents_by_ticker_period, period_ends, llm)

    assert panel.period_ends == period_ends
    assert panel.values["AAA"][0] == pytest.approx(0.7)  # grounded -> score kept
    assert panel.values["AAA"][1] is None  # ungrounded -> excluded, not trusted
    assert panel.values["AAA"][2] is None  # no document that period at all

    assert len(records) == 2
    assert records[0].grounded is True
    assert records[1].grounded is False
    assert len(usages) == 2


async def test_build_sentiment_panel_skips_periods_outside_the_grid(fake_llm):
    period_ends = ["2020-01-01"]
    doc = _doc("d1", "Neutral update with no clear directional signal.")
    documents_by_ticker_period = {"AAA": {"2019-12-01": doc}}  # not in period_ends at all
    llm = fake_llm({"SentimentScoreDraft": []})  # never called -- the period is skipped before any LLM call
    panel, records, usages = await build_sentiment_panel(documents_by_ticker_period, period_ends, llm)
    assert panel.values["AAA"] == [None]
    assert records == []
    assert usages == []
