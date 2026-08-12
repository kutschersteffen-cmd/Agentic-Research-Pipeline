from __future__ import annotations

from pydantic import BaseModel, Field

from arp.discovery.site_finder import WebSearchClient
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.taxonomy_sources import SourceCandidate, SourceCandidateType

# Query templates for each candidate type. Deliberately varied phrasing per
# query rather than one query repeated, since a single search engine call
# returns a narrow slice and different phrasings surface different real
# organizations/funds.
_AUTHORITY_QUERY_TEMPLATES = [
    "{theme} official taxonomy classification",
    "{theme} IEA definition taxonomy",
    "{theme} EU taxonomy sustainable activities",
    "{theme} industry standard classification body",
]
_FUND_QUERY_TEMPLATES = [
    "{theme} ETF",
    "{theme} thematic index fund",
    "{theme} index methodology",
]


async def _run_queries(
    theme_name: str, templates: list[str], source_type: SourceCandidateType, search_client: WebSearchClient, per_query: int
) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    seen_urls: set[str] = set()
    for template in templates:
        query = template.format(theme=theme_name)
        try:
            results = await search_client.search(query, max_results=per_query)
        except Exception:  # noqa: BLE001 - one bad query shouldn't blank the whole discovery step
            continue
        for r in results:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            candidates.append(SourceCandidate(source_type=source_type, name=r.title, url=r.url, snippet=r.snippet))
    return candidates


async def discover_authority_sources(
    theme_name: str, search_client: WebSearchClient, max_candidates: int = 10
) -> list[SourceCandidate]:
    """Searches for candidate authoritative sources for a theme -- official
    taxonomies, standards-body definitions, government/IGO classifications
    (IEA, EU taxonomy, etc.) -- for the user to review and select from.
    Nothing here is fetched or used automatically; this only proposes.
    """
    candidates = await _run_queries(theme_name, _AUTHORITY_QUERY_TEMPLATES, SourceCandidateType.AUTHORITY, search_client, per_query=4)
    return candidates[:max_candidates]


async def discover_thematic_funds(
    theme_name: str, search_client: WebSearchClient, max_candidates: int = 10
) -> list[SourceCandidate]:
    """Searches for existing thematic ETFs/indices already built around
    this (or an adjacent) theme, for the user to select as a bottom-up
    reference -- see arp/research/taxonomy_sources/etf_holdings.py for what
    happens once a fund is selected and its holdings supplied.

    Also usable for sector/index lookups by passing a sector or index name
    (e.g. "S&P 500", "US technology sector") instead of a theme name --
    the query templates ("{q} ETF", "{q} thematic index fund", ...) are
    generic enough that no separate function is needed; see the Universe
    Builder, which reuses this exact call.
    """
    candidates = await _run_queries(theme_name, _FUND_QUERY_TEMPLATES, SourceCandidateType.THEMATIC_FUND, search_client, per_query=4)
    return candidates[:max_candidates]


_RANK_SYSTEM_PROMPT = """\
You assess how authoritative each candidate source is as a reference for \
defining a macro investment theme's business-activity taxonomy.
Authoritative means: an official body, standards organization, government \
or intergovernmental agency, or established research institute publishing \
a definitional or methodological document -- not a news article, blog \
post, marketing page, or product listing.

For each candidate (given only its title, URL, and search snippet), \
assign an authority_score from 0.0 (not authoritative) to 1.0 (a \
canonical, official definitional source) and a one-sentence \
authority_reasoning a user can read to decide whether to trust it. Be \
honest when a snippet gives too little information to judge confidently \
-- a mid-range score whose reasoning says so plainly is better than false \
confidence."""


class _CandidateAssessment(BaseModel):
    candidate_id: str
    authority_score: float = Field(ge=0.0, le=1.0)
    authority_reasoning: str


class _AssessmentList(BaseModel):
    assessments: list[_CandidateAssessment]


async def rank_authority_sources(
    theme_name: str, candidates: list[SourceCandidate], llm: LLMClient
) -> tuple[list[SourceCandidate], LLMUsage]:
    """Scores and explains each already-discovered candidate's
    authoritativeness, sorted highest first. Purely additive over
    discover_authority_sources -- ranking never changes which candidates
    were found, only how they're ordered and annotated for the user.
    """
    if not candidates:
        return [], LLMUsage()

    listing = "\n\n".join(
        f"[{c.candidate_id}] {c.name}\nURL: {c.url}\nSnippet: {c.snippet or '(none)'}" for c in candidates
    )
    prompt = f"Macro theme: {theme_name}\n\nCandidates:\n{listing}"
    draft, usage = await llm.complete_structured(system=_RANK_SYSTEM_PROMPT, prompt=prompt, output_model=_AssessmentList)

    assessments_by_id = {a.candidate_id: a for a in draft.assessments}
    ranked: list[SourceCandidate] = []
    for candidate in candidates:
        assessment = assessments_by_id.get(candidate.candidate_id)
        if assessment is None:
            ranked.append(candidate)
            continue
        ranked.append(
            candidate.model_copy(
                update={"authority_score": assessment.authority_score, "authority_reasoning": assessment.authority_reasoning}
            )
        )
    ranked.sort(key=lambda c: c.authority_score if c.authority_score is not None else -1.0, reverse=True)
    return ranked, usage
