from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.grounding import is_grounded
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.portfolio import NewsItem, NewsRiskFlag

_SYSTEM_PROMPT = """\
You screen a news article about a specific company for climate/ESG \
controversy relevance to an investment portfolio -- things like oil \
spills, greenwashing findings, major regulatory action on emissions, \
climate litigation, and supply-chain sourcing controversies. Ignore \
routine business news with no climate/ESG angle.

If relevant, `quote` MUST be a verbatim excerpt copied exactly from the \
supplied headline or excerpt text -- never a paraphrase or summary. If \
nothing in the article is climate/ESG-controversy relevant, set \
relevant=false and leave the other fields at their defaults."""


class _ClassificationOutput(BaseModel):
    relevant: bool
    category: Literal["climate_controversy", "regulatory", "litigation", "other"] = "other"
    severity: Literal["low", "medium", "high"] = "low"
    rationale: str = ""
    quote: str = ""


async def classify_article(
    article: NewsItem, llm: LLMClient, *, fuzzy_threshold: float = 0.92
) -> tuple[NewsRiskFlag | None, LLMUsage]:
    """Classifies one news article for a climate/controversy risk flag.

    The LLM's `quote` is checked against the article's own text by the
    same programmatic grounding checker (`grounding.is_grounded`) used
    everywhere else in this codebase for citations -- an ungrounded quote
    means the flag is dropped entirely, not just marked unverified, so any
    flag that survives is always traceable to real article text, never an
    LLM paraphrase presented as fact.
    """
    if article.company_id is None:
        raise ValueError("classify_article requires an article already resolved to a company_id")

    prompt = f"Headline: {article.headline}\n\nExcerpt: {article.excerpt}\n\nClassify this article for climate/ESG controversy relevance."
    result, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_ClassificationOutput)

    if not result.relevant:
        return None, usage

    source_text = f"{article.headline}\n{article.excerpt}"
    if not is_grounded(result.quote, source_text, fuzzy_threshold):
        return None, usage

    flag = NewsRiskFlag(
        news_id=article.news_id,
        company_id=article.company_id,
        category=result.category,
        severity=result.severity,
        rationale=result.rationale,
        quote=result.quote,
        grounded=True,
    )
    return flag, usage
