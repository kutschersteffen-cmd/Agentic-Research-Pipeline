from __future__ import annotations

from pydantic import BaseModel, Field

from arp.grounding import is_grounded
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.emerging_themes import ExtractedTag, RawMention

_SYSTEM_PROMPT = """\
You read one short news, filing, or regulatory item and identify up to 3 \
distinct, concrete business or market topics it evidences -- a new \
product or technology, a regulatory shift, a supply-chain move, a \
business-model change, or a market entry a company or industry is \
engaged in. Ignore routine items with no substantive business/market \
topic (a stock-price update, a procedural filing, an unrelated \
announcement) -- return an empty tags list rather than inventing one.

For each topic:
- label: a short 2-5 word label for the topic ITSELF, e.g. "solid-state \
battery commercialization" -- never a broad market category like \
"batteries" or "energy".
- claim: one sentence stating the specific fact this item reports.
- entity_names: company/issuer names mentioned in connection with this \
topic, exactly as they appear in the text.
- quote: a verbatim excerpt copied exactly from the supplied title/text \
that backs the claim -- never a paraphrase or summary.

Every quote MUST be copied verbatim from the supplied text. If you cannot \
find real supporting text for a topic, drop that topic rather than \
inventing a quote."""


class _TagDraft(BaseModel):
    label: str
    claim: str
    entity_names: list[str] = Field(default_factory=list)
    quote: str


class _TagDraftList(BaseModel):
    tags: list[_TagDraft] = Field(default_factory=list)


async def tag_mention(mention: RawMention, llm: LLMClient, fuzzy_threshold: float = 0.92) -> tuple[list[ExtractedTag], LLMUsage]:
    """The Extract layer's per-mention step: one LLM call producing up to
    3 topic tags, each backed by a grounding-checked verbatim quote --
    same discipline as `portfolio/news/classifier.py`, generalized beyond
    climate/ESG-controversy screening to open-ended topic extraction. A
    tag whose quote doesn't ground is dropped entirely, not flagged, so
    every tag that survives is traceable to real mention text.
    """
    if not mention.text.strip():
        return [], LLMUsage()

    prompt = f"Title: {mention.title}\n\nText: {mention.text}"
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_TagDraftList)

    source_text = f"{mention.title}\n{mention.text}"
    tags: list[ExtractedTag] = []
    for candidate in draft.tags:
        if not is_grounded(candidate.quote, source_text, fuzzy_threshold):
            continue
        tags.append(
            ExtractedTag(
                mention_id=mention.mention_id,
                label=candidate.label,
                claim=candidate.claim,
                entity_names=candidate.entity_names,
                quote=candidate.quote,
                grounded=True,
            )
        )
    return tags, usage
