from __future__ import annotations

from pydantic import BaseModel, Field

from arp.discovery.site_finder import WebSearchClient
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.paper_discovery import PaperCandidate
from arp.schemas.strategy_replication import SignalType

# Deliberately varied phrasing per query, same reasoning as
# arp/research/taxonomy_sources/discovery.py's own query templates: a
# single search returns a narrow slice, and different phrasings surface
# different real papers rather than the same handful repeated.
_QUERY_TEMPLATES = [
    "{topic} anomaly stock returns SSRN",
    "{topic} factor cross-section of expected returns",
    "{topic} long-short portfolio returns academic paper",
    "{topic} outperformance strategy journal of finance",
]


async def discover_candidate_papers(topic: str, search_client: WebSearchClient, max_candidates: int = 10) -> list[PaperCandidate]:
    """Searches for candidate academic/practitioner papers describing an
    'outperformance' strategy related to `topic` (e.g. 'momentum',
    'quality investing', 'low volatility anomaly'), for a human to review
    and select one to feed into `arp replicate extract-spec`. Nothing here
    is fetched, read, or converted into a StrategySpec automatically --
    this only proposes candidates, the same 'propose, never auto-apply'
    discipline as the Taxonomy Researcher
    (arp/agents/taxonomy_researcher.py::discover_authority_sources).
    """
    candidates: list[PaperCandidate] = []
    seen_urls: set[str] = set()
    for template in _QUERY_TEMPLATES:
        query = template.format(topic=topic)
        try:
            results = await search_client.search(query, max_results=4)
        except Exception:  # noqa: BLE001 - one bad query shouldn't blank the whole discovery step
            continue
        for r in results:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            candidates.append(PaperCandidate(title=r.title, url=r.url, snippet=r.snippet))
    return candidates[:max_candidates]


_RANK_SYSTEM_PROMPT = """\
You assess candidate academic/practitioner papers (given only title, URL, \
and a search snippet -- you have not read the paper itself) for how \
promising they are as a target for systematic replication in a \
deterministic quant strategy backtest engine.

A good candidate: makes a specific, testable "this cross-sectional sort \
or long-short strategy outperforms" claim (not a general survey, opinion \
piece, or purely theoretical paper); is plausibly replicable with price \
data alone (a momentum-style signal) or with one widely available \
fundamental ratio (a value-style signal, e.g. book-to-market, earnings- \
to-price) or with text/news the strategy scores for sentiment; and \
appears to be a real academic or reputable practitioner source (SSRN, a \
journal, a known working-paper series) rather than a blog post, forum \
post, or marketing page.

For each candidate, assign replication_worthiness_score (0.0 = not worth \
attempting, 1.0 = an excellent, clearly replicable target), a \
one-sentence worthiness_reasoning, and your best-guess \
suggested_signal_type ('momentum', 'value', 'text_sentiment', \
'composite', or null if the snippet gives no basis to guess) -- this is \
only a starting hint for the human reviewer who will actually read the \
paper, never a claim that you have."""


class _CandidateAssessment(BaseModel):
    candidate_id: str
    replication_worthiness_score: float = Field(ge=0.0, le=1.0)
    worthiness_reasoning: str
    suggested_signal_type: SignalType | None = None


class _AssessmentList(BaseModel):
    assessments: list[_CandidateAssessment]


async def rank_candidate_papers(
    topic: str, candidates: list[PaperCandidate], llm: LLMClient
) -> tuple[list[PaperCandidate], LLMUsage]:
    """Scores and explains each already-discovered candidate's replication-
    worthiness, sorted highest first. Purely additive over
    discover_candidate_papers -- ranking never changes which candidates
    were found, only how they're ordered and annotated for the user.
    """
    if not candidates:
        return [], LLMUsage()

    listing = "\n\n".join(f"[{c.candidate_id}] {c.title}\nURL: {c.url}\nSnippet: {c.snippet or '(none)'}" for c in candidates)
    prompt = f"Topic: {topic}\n\nCandidates:\n{listing}"
    draft, usage = await llm.complete_structured(system=_RANK_SYSTEM_PROMPT, prompt=prompt, output_model=_AssessmentList)

    assessments_by_id = {a.candidate_id: a for a in draft.assessments}
    ranked: list[PaperCandidate] = []
    for candidate in candidates:
        assessment = assessments_by_id.get(candidate.candidate_id)
        if assessment is None:
            ranked.append(candidate)
            continue
        ranked.append(
            candidate.model_copy(
                update={
                    "replication_worthiness_score": assessment.replication_worthiness_score,
                    "worthiness_reasoning": assessment.worthiness_reasoning,
                    "suggested_signal_type": assessment.suggested_signal_type,
                }
            )
        )
    ranked.sort(key=lambda c: c.replication_worthiness_score if c.replication_worthiness_score is not None else -1.0, reverse=True)
    return ranked, usage
