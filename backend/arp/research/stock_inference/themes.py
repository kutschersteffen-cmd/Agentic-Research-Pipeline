"""Step 4: common themes -- one model call proposes, code filters, computes shares and ranks."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from arp.grounding import ground_citations
from arp.research.stock_inference.schemas import Cluster, StockProfile, Theme
from arp.schemas.common import Citation, SourceDocument


class Support(BaseModel):
    company_id: str
    reason: str


class ProposedTheme(BaseModel):
    name: str
    description: str
    supporting: list[Support] = Field(default_factory=list)
    cluster_ids: list[int] = Field(default_factory=list)
    stated_in_methodology: bool = False
    methodology_quote: str | None = Field(default=None, description="Verbatim sentence from the methodology.")


class ThemeProposals(BaseModel):
    themes: list[ProposedTheme]


_SYSTEM = (
    "You find the common investment themes of a set of stocks. Return 2-5 themes. For each: a short name, a "
    "one-sentence description, the company_ids that support it with one reason each (only ids from the profiles), "
    "the cluster_ids it draws on, and whether the index methodology states it, with a verbatim quote if so."
)


def _prompt(described: list[StockProfile], clusters: list[Cluster], samples: dict[int, list[str]],
            stated_theme: str | None) -> str:
    payload = {
        "profiles": [{"company_id": p.company_id, "name": p.name, "description": p.description} for p in described],
        "clusters": [{"cluster_id": c.cluster_id, "terms": c.terms, "members": c.members,
                      "sample_chunks": samples.get(c.cluster_id, [])} for c in clusters],
        "stated_theme": stated_theme,
    }
    return json.dumps(payload, indent=1)


def _grounded(quote: str | None, docs: list[SourceDocument], fuzzy_threshold: float) -> bool:
    if not quote or not docs:
        return False
    cites = [Citation(doc_id=d.doc_id, doc_type=d.doc_type, quote=quote) for d in docs]
    return any(c.grounded for c in ground_citations(cites, {d.doc_id: d for d in docs}, fuzzy_threshold))


async def propose_themes(
    profiles: list[StockProfile], clusters: list[Cluster], stated_theme: str | None,
    methodology_docs: list[SourceDocument], llm, *, samples: dict[int, list[str]] | None = None,
    fuzzy_threshold: float = 0.92,
) -> tuple[list[Theme], list[str]]:
    described = {p.company_id: p for p in profiles if p.description}
    weighted = any(p.weight is not None for p in described.values())
    total_weight = sum(p.weight or 0.0 for p in described.values())
    reply, _ = await llm.complete_structured(
        system=_SYSTEM, prompt=_prompt(list(described.values()), clusters, samples or {}, stated_theme),
        output_model=ThemeProposals,
    )
    kept: list[Theme] = []
    known_clusters = {c.cluster_id for c in clusters}
    for t in reply.themes:
        ids = sorted({s.company_id for s in t.supporting} & described.keys())
        if not ids:
            continue
        stated = t.stated_in_methodology and _grounded(t.methodology_quote, methodology_docs, fuzzy_threshold)
        weight_share = (round(sum(described[i].weight or 0.0 for i in ids) / total_weight, 4)
                        if weighted and total_weight else None)
        kept.append(Theme(
            rank=0, name=t.name, description=t.description, supporting=ids, count_share=round(len(ids) / len(described), 4),
            weight_share=weight_share, cluster_ids=sorted(set(t.cluster_ids) & known_clusters), stated_in_methodology=stated,
            methodology_quote=t.methodology_quote if stated else None,
        ))
    kept.sort(key=lambda t: (-(t.weight_share if t.weight_share is not None else t.count_share), t.name))
    themes = [t.model_copy(update={"rank": i}) for i, t in enumerate(kept, 1)]
    in_theme = {i for t in themes for i in t.supporting}
    return themes, sorted(described.keys() - in_theme)
