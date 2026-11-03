from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.research.authority_taxonomy.checklist import AUTHORITY_CHECKLIST
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.authority_taxonomy import Criterion, Definition, SectorCode, SourceCitation, Technology, Threshold, merge_key
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.thematic import ActivityDefinition

_FUZZY_THRESHOLD = 0.92
_QUOTE = Field(description="Exact, verbatim substring copied from the excerpts.")

_SYSTEM_PROMPT = """\
You are a thematic-investment taxonomist reading excerpts of an authoritative source \
(an official taxonomy, a standards-body definition, a government or research publication) \
for the theme "{theme_name}".
Scope of this run: {scope}

Answer only this checklist question: {question}

Every element you return must carry an EXACT, VERBATIM quote copied from the excerpts. \
Return nothing the excerpts do not state. Activities outside the scope are never activities: \
they belong in exclude boundaries. Eligibility thresholds (revenue share, capex share, \
pure-play rules) are never part of an activity's description or criteria."""


class _ThemeDescriptionDraft(BaseModel):
    description: str = ""
    quote: str = ""


class _ActivityItem(BaseModel):
    name: str
    in_scope_description: str
    seed_keywords: list[str] = Field(default_factory=list)
    quote: str = _QUOTE


class _ActivitiesDraft(BaseModel):
    activities: list[_ActivityItem] = Field(default_factory=list)


class _BoundaryItem(BaseModel):
    activity_name: str
    kind: Literal["include", "exclude"]
    text: str
    quote: str = _QUOTE


class _BoundariesDraft(BaseModel):
    boundaries: list[_BoundaryItem] = Field(default_factory=list)


class _TechnologyItem(BaseModel):
    name: str
    quote: str = _QUOTE


class _TechnologiesDraft(BaseModel):
    technologies: list[_TechnologyItem] = Field(default_factory=list)


class _DefinitionItem(BaseModel):
    term: str
    text: str
    quote: str = _QUOTE


class _DefinitionsDraft(BaseModel):
    definitions: list[_DefinitionItem] = Field(default_factory=list)


class _SectorCodeItem(BaseModel):
    system: Literal["ISIC", "NACE", "NAICS", "SIC", "GICS"]
    code: str
    quote: str = _QUOTE


class _SectorCodesDraft(BaseModel):
    sector_codes: list[_SectorCodeItem] = Field(default_factory=list)


class _ValueChainItem(_ActivityItem):
    value_chain_role: Literal["upstream", "enabling"]


class _ValueChainDraft(BaseModel):
    activities: list[_ValueChainItem] = Field(default_factory=list)


class _ThresholdItem(BaseModel):
    text: str
    quote: str = _QUOTE


class _ThresholdsDraft(BaseModel):
    thresholds: list[_ThresholdItem] = Field(default_factory=list)


_DRAFTS: dict[str, type[BaseModel]] = {
    "theme_description": _ThemeDescriptionDraft,
    "activities": _ActivitiesDraft,
    "boundaries": _BoundariesDraft,
    "technologies": _TechnologiesDraft,
    "definitions": _DefinitionsDraft,
    "sector_codes": _SectorCodesDraft,
    "value_chain": _ValueChainDraft,
    "thresholds": _ThresholdsDraft,
}


class SourceExtraction(BaseModel):
    url: str
    theme_description: str = ""
    activities: list[ActivityDefinition] = Field(default_factory=list)
    technologies: list[Technology] = Field(default_factory=list)
    definitions: list[Definition] = Field(default_factory=list)
    thresholds: list[Threshold] = Field(default_factory=list)
    sector_codes: list[SectorCode] = Field(default_factory=list)
    report: dict[str, Literal["found", "not_in_source"]] = Field(default_factory=dict)
    usage: LLMUsage = Field(default_factory=LLMUsage)


async def extract_source(
    url: str, text: str, *, theme_name: str, scope: str, value_chain: bool, llm: LLMClient
) -> SourceExtraction:
    """One schema-forced LLM call per checklist item over the chunks relevant to it (the whole
    document is chunked, so nothing past a fixed prefix is lost). Every element must quote the
    source; an element whose quote fails grounding is dropped."""
    doc = SourceDocument(company_id=url, doc_type=DocType.OTHER, title=url, source_url=url, full_text=text)
    chunks = chunk_document(doc)
    docs_by_id = {doc.doc_id: doc}

    def ground(quote: str) -> list[SourceCitation]:
        c = Citation(doc_id=doc.doc_id, doc_type=DocType.OTHER, quote=quote, location=url)
        grounded = ground_citations([c], docs_by_id, _FUZZY_THRESHOLD)[0]
        return [SourceCitation(quote=grounded.quote, source_url=url)] if quote and grounded.grounded else []

    out = SourceExtraction(url=url)
    boundaries: list[_BoundaryItem] = []
    for item in AUTHORITY_CHECKLIST:
        if item.key == "value_chain" and not value_chain:
            continue
        selected = select_relevant_chunks(chunks, item.keywords + [theme_name], max_chunks=6, fallback_to_all=False)
        found = False
        if selected:
            excerpts = "\n\n---\n\n".join(f"[excerpt {i + 1}]\n{c.text}" for i, c in enumerate(selected))
            system = _SYSTEM_PROMPT.format(theme_name=theme_name, scope=scope or "(none given)", question=item.question)
            draft, usage = await llm.complete_structured(
                system=system, prompt=f"Source: {url}\nScope: {scope or '(none given)'}\n\nExcerpts:\n{excerpts}", output_model=_DRAFTS[item.key]
            )
            out.usage.input_tokens += usage.input_tokens
            out.usage.output_tokens += usage.output_tokens
            found = _apply(item.key, draft, out, ground, boundaries)
        out.report[item.key] = "found" if found else "not_in_source"

    # Boundaries run before the activities they refer to may exist (value_chain comes later), so attach at the end.
    if "boundaries" in out.report:
        attached = [b for b in boundaries if _attach_boundary(b, out.activities, ground(b.quote))]
        out.report["boundaries"] = "found" if attached else "not_in_source"
    # Thresholds are theme-level eligibility rules; never let one leak into an activity's scope or criteria.
    rules = [c.quote for t in out.thresholds for c in t.citations]
    out.activities = [a for a in out.activities if not any(r in a.in_scope_description for r in rules)]
    for a in out.activities:
        a.criteria = [c for c in a.criteria if not any(r in c.text for r in rules)]
    return out


def _apply(key: str, draft, out: SourceExtraction, ground, boundaries: list[_BoundaryItem]) -> bool:
    n_before = _count(out) + len(boundaries)
    if key == "theme_description":
        if ground(draft.quote):
            out.theme_description = draft.description
            return True
        return False
    if key in ("activities", "value_chain"):
        for a in draft.activities:
            if cites := ground(a.quote):
                out.activities.append(
                    ActivityDefinition(
                        name=a.name,
                        in_scope_description=a.in_scope_description,
                        out_of_scope_description="",
                        seed_keywords=a.seed_keywords,
                        value_chain_role=getattr(a, "value_chain_role", "core"),
                        citations=cites,
                    )
                )
    elif key == "boundaries":
        boundaries.extend(b for b in draft.boundaries if ground(b.quote))
    elif key == "technologies":
        out.technologies += [Technology(name=t.name, citations=c) for t in draft.technologies if (c := ground(t.quote))]
    elif key == "definitions":
        out.definitions += [Definition(term=d.term, text=d.text, citations=c) for d in draft.definitions if (c := ground(d.quote))]
    elif key == "sector_codes":
        out.sector_codes += [SectorCode(system=s.system, code=s.code, origin="source") for s in draft.sector_codes if ground(s.quote)]
    elif key == "thresholds":
        out.thresholds += [Threshold(text=t.text, citations=c) for t in draft.thresholds if (c := ground(t.quote))]
    return _count(out) + len(boundaries) > n_before


def _count(out: SourceExtraction) -> int:
    return len(out.activities) + len(out.technologies) + len(out.definitions) + len(out.sector_codes) + len(out.thresholds)


def _attach_boundary(b: _BoundaryItem, activities: list[ActivityDefinition], cites: list[SourceCitation]) -> bool:
    target = next((a for a in activities if merge_key(a.name) == merge_key(b.activity_name)), None)
    if target is None:
        return False
    if b.kind == "exclude":
        target.out_of_scope_description = " ".join(filter(None, [target.out_of_scope_description, b.text]))
        target.out_of_scope_citations += cites
    else:
        target.criteria.append(Criterion(text=b.text, citations=cites))
    return True
