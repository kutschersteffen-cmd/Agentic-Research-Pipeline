from __future__ import annotations

from pydantic import BaseModel

from arp.discovery.site_finder import SearchResult
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.thematic import ActivityDefinition

_SYSTEM_PROMPT = """\
You assess whether a search result indicates genuine recent momentum -- a \
product launch, partnership, investment, capacity expansion, or executive \
commentary -- specifically tying a company to a specific thematic \
business activity.

Judge only from the title/snippet given. Do not mark a result relevant just \
because the company name and activity keywords both appear -- they may be \
coincidental (e.g. an unrelated announcement on the same page, a \
directory listing, a stock-price page with no substantive content). Be \
conservative: a result you're unsure about should be marked not relevant \
rather than guessed as relevant."""


class _ResultAssessment(BaseModel):
    result_index: int
    relevant: bool
    rationale: str = ""


class _AssessmentList(BaseModel):
    assessments: list[_ResultAssessment]


async def score_news_mentions(
    company_name: str, activity: ActivityDefinition, results: list[SearchResult], llm: LLMClient
) -> tuple[float, list[SearchResult], LLMUsage]:
    """Classifies each search result for genuine relevance to `activity`,
    returning the fraction judged relevant as a 0-1 mention-intensity
    score, plus the relevant subset (for the caller to cite in `notes`).

    Returns (0.0, [], zero usage) with no LLM call for an empty result
    list -- there's nothing to classify.
    """
    if not results:
        return 0.0, [], LLMUsage()

    listing = "\n\n".join(f"[{i}] {r.title}\n{r.snippet}" if r.snippet else f"[{i}] {r.title}" for i, r in enumerate(results))
    prompt = (
        f"Company: {company_name}\n"
        f"Activity: {activity.name} ({activity.in_scope_description})\n\n"
        f"Search results:\n{listing}"
    )
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_AssessmentList)

    relevant_indices = sorted({a.result_index for a in draft.assessments if a.relevant and 0 <= a.result_index < len(results)})
    relevant_results = [results[i] for i in relevant_indices]
    score = len(relevant_results) / len(results)
    return score, relevant_results, usage
