from __future__ import annotations

from statistics import fmean

from pydantic import BaseModel, Field

from arp.grounding import ground_citations
from arp.llm.base import LLMClient, LLMUsage
from arp.replication.characteristics_data import CharacteristicPanel
from arp.schemas.common import Citation, SourceDocument
from arp.schemas.portfolio import NewsItem

_SYSTEM_PROMPT = """\
You are scoring how positively or negatively one piece of text (a news \
article, earnings-call transcript excerpt, or similar) reflects on a \
company's near-term business outlook, for use as a cross-sectional \
ranking signal in a systematic strategy backtest.

Score strictly and only from what this text itself says:
- score: a float from -1.0 (strongly negative outlook) to +1.0 (strongly \
  positive outlook); 0.0 for neutral, mixed, or no clear directional signal.
- NEVER let anything you might know about what happened to this company or \
  its stock price AFTER this text was written influence the score -- you \
  are given only the text and its date precisely so that hindsight (which \
  would leak information a real-time investor could not have had at the \
  time) cannot contaminate a historical backtest. Score the text exactly \
  as a contemporary reader would have read it on the date given, using \
  only what the text itself states.
- quote: an EXACT, VERBATIM substring of the text that most supports your \
  score.
- confidence: how clearly the text supports a directional read, 0.0-1.0 \
  (low for text that is ambiguous, mostly factual/backward-looking, or \
  only tangentially about the company's outlook).
"""


class SentimentScoreDraft(BaseModel):
    score: float = Field(ge=-1.0, le=1.0)
    quote: str
    confidence: float = Field(ge=0.0, le=1.0)


async def score_document_sentiment(ticker: str, document: SourceDocument, llm: LLMClient) -> tuple[SentimentScoreDraft, LLMUsage]:
    prompt = (
        f"Ticker: {ticker}\n"
        f"Document date: {document.published_at or document.fiscal_period or document.fetched_at}\n\n"
        f"Text:\n{document.full_text}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=SentimentScoreDraft)


class SentimentScoreRecord(BaseModel):
    """One scored (ticker, period_end, document) cell -- the audit trail
    behind one entry of a sentiment CharacteristicPanel, so a reviewer can
    trace any period's score back to the grounded quote (or see that it
    failed grounding and was excluded) that produced it."""

    ticker: str
    period_end: str
    doc_id: str
    score: float
    citation: Citation
    confidence: float
    grounded: bool
    model: str | None = None


def build_manifest_from_store(items: list[NewsItem]) -> list[dict]:
    """Turns stored NewsItems into the manifest `arp replicate score-sentiment`
    reads. Each item lands in the month of its own `published_at` (event
    time), keyed by company_id; apply any lag via characteristic_lag_months
    downstream, not here. Items with no company_id are skipped (nothing to
    attach the score to)."""
    return [
        {
            "ticker": i.company_id,
            "period_end": f"{i.published_at[:7]}-01",
            "published_at": i.published_at,
            "doc_id": i.news_id,
            "text": f"{i.headline}\n\n{i.excerpt}".strip(),
        }
        for i in items
        if i.company_id
    ]


async def build_sentiment_panel(
    documents_by_ticker_period: dict[str, dict[str, SourceDocument | list[SourceDocument]]],
    period_ends: list[str],
    llm: LLMClient,
    *,
    fuzzy_threshold: float = 0.92,
) -> tuple[CharacteristicPanel, list[SentimentScoreRecord], list[LLMUsage]]:
    """Scores every document in each (ticker, period_end) cell of
    `documents_by_ticker_period` (a cell holds one document or a list; a
    cell's value is the mean of its grounded scores) and assembles the results into a
    CharacteristicPanel ready to feed SignalType.TEXT_SENTIMENT -- the
    plumbing after this point is identical to VALUE (same
    CharacteristicPanel shape, same characteristic_lag_months handling in
    signals.py::value_scores).

    A ticker/period with no document, or whose citation fails the same
    programmatic grounding check used everywhere else in this codebase,
    gets None there -- "no signal that period" is never distinguished from
    "we didn't bother checking", the same discipline arp/grounding.py
    enforces for every other extraction. Returns (panel, records, usages);
    `records` is the full per-cell audit trail (including ungrounded ones,
    for review) -- persist it alongside the panel, don't discard it.
    """
    values: dict[str, list[float | None]] = {t: [None] * len(period_ends) for t in documents_by_ticker_period}
    records: list[SentimentScoreRecord] = []
    usages: list[LLMUsage] = []
    period_index = {p: i for i, p in enumerate(period_ends)}

    for ticker, docs_by_period in documents_by_ticker_period.items():
        for period_end, cell in docs_by_period.items():
            if period_end not in period_index:
                continue
            grounded_scores: list[float] = []
            for document in cell if isinstance(cell, list) else [cell]:
                draft, usage = await score_document_sentiment(ticker, document, llm)
                usages.append(usage)
                citation = Citation(doc_id=document.doc_id, doc_type=document.doc_type, quote=draft.quote)
                grounded_citation = ground_citations([citation], {document.doc_id: document}, fuzzy_threshold)[0]
                if grounded_citation.grounded:
                    grounded_scores.append(draft.score)
                records.append(
                    SentimentScoreRecord(
                        ticker=ticker,
                        period_end=period_end,
                        doc_id=document.doc_id,
                        score=draft.score,
                        citation=grounded_citation,
                        confidence=draft.confidence,
                        grounded=grounded_citation.grounded,
                        model=usage.model,
                    )
                )
            if grounded_scores:
                values[ticker][period_index[period_end]] = fmean(grounded_scores)
    panel = CharacteristicPanel(period_ends=period_ends, values=values, source="llm_sentiment")
    return panel, records, usages
