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


async def test_the_prompt_is_dated_by_publication_not_fetch_time(fake_llm):
    llm = fake_llm({"SentimentScoreDraft": [SentimentScoreDraft(score=0.0, quote="x", confidence=0.1)]})
    doc = SourceDocument(doc_id="d1", company_id="AAA", doc_type=DocType.OTHER, title="t", full_text="x",
                         fiscal_period="FY2023", published_at="2024-02-02T16:30:12.000Z", fetched_at="2026-10-13T00:00:00")
    await score_document_sentiment("AAA", doc, llm)
    assert "Document date: 2024-02-02T16:30:12.000Z\n" in llm.prompts[0]


def test_build_manifest_from_store_buckets_by_event_month_and_skips_unlinked():
    from arp.schemas.portfolio import NewsItem

    items = [
        NewsItem(news_id="n1", company_id="AAA", headline="Beat", excerpt="Sales rose.", published_at="2020-01-31T23:10:00Z"),
        NewsItem(news_id="n2", company_id=None, headline="Macro", excerpt="", published_at="2020-01-05T00:00:00Z"),
    ]
    from arp.replication.sentiment_scoring import build_manifest_from_store

    assert build_manifest_from_store(items) == [
        {
            "ticker": "AAA",
            "period_end": "2020-01-01",
            "published_at": "2020-01-31T23:10:00Z",
            "doc_id": "n1",
            "text": "Beat\n\nSales rose.",
        }
    ]


async def test_build_sentiment_panel_averages_grounded_scores_in_a_cell(fake_llm):
    docs = [_doc("a", "Sales rose sharply."), _doc("b", "Margins fell badly."), _doc("c", "Unscorable text here.")]
    llm = fake_llm(
        {
            "SentimentScoreDraft": [
                SentimentScoreDraft(score=0.8, quote="Sales rose sharply", confidence=0.9),
                SentimentScoreDraft(score=-0.2, quote="Margins fell badly", confidence=0.9),
                SentimentScoreDraft(score=1.0, quote="not in the text", confidence=0.9),  # ungrounded -> excluded
            ]
        }
    )
    panel, records, _ = await build_sentiment_panel({"AAA": {"2020-01-01": docs}}, ["2020-01-01"], llm)
    assert panel.values["AAA"] == [pytest.approx(0.3)]
    assert len(records) == 3
