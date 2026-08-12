from __future__ import annotations

from pydantic import BaseModel, Field

from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.thematic import ActivityDefinition

_MAX_CHUNKS_PER_SOURCE = 15

_SYSTEM_PROMPT = """\
You are a thematic-investment taxonomist extracting a business-activity \
taxonomy from an authoritative source document (an official taxonomy, a \
standards-body definition, a government or research-institute \
publication). Read the excerpts and identify the concrete business \
activities the source itself defines or describes as part of the theme.

For each activity: write in-scope and out-of-scope descriptions in plain, \
checkable language (using the source's own boundaries and terminology \
wherever the source states them), give seed keywords, and -- critically \
-- cite an EXACT, VERBATIM quote copied from the excerpts that supports \
this activity actually being part of the source's taxonomy. Never invent \
an activity that isn't actually grounded in the text; if the source only \
supports two or three activities, extract only those -- don't pad the \
list to look more thorough than the source actually is."""


class _AuthorityActivityDraft(BaseModel):
    name: str
    in_scope_description: str
    out_of_scope_description: str
    seed_keywords: list[str] = Field(default_factory=list)
    source_quote: str = Field(description="Exact, verbatim substring copied from the excerpts.")


class _AuthorityActivityDraftList(BaseModel):
    activities: list[_AuthorityActivityDraft]


def _format_chunks(chunks) -> str:
    return "\n\n---\n\n".join(f"[excerpt {i + 1}]\n{c.text}" for i, c in enumerate(chunks))


async def extract_activities_from_source(
    source_url: str, source_text: str, llm: LLMClient, fuzzy_threshold: float = 0.92
) -> tuple[list[ActivityDefinition], LLMUsage]:
    """Schema-forced, grounded extraction from one fetched authority
    source -- the same discipline the Extraction Engine already applies to
    company disclosures (chunk, extract with a mandatory verbatim
    citation, programmatically verify the citation is real), applied here
    to a taxonomy-defining document instead. An activity whose quote fails
    the grounding check is dropped, not silently kept -- the same
    hard-gate precedent as everywhere else this system checks a citation.
    """
    doc = SourceDocument(company_id=source_url, doc_type=DocType.OTHER, title=source_url, source_url=source_url, full_text=source_text)
    chunks = chunk_document(doc)[:_MAX_CHUNKS_PER_SOURCE]
    if not chunks:
        return [], LLMUsage()

    prompt = f"Source: {source_url}\n\nExcerpts:\n{_format_chunks(chunks)}"
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_AuthorityActivityDraftList)

    documents_by_id = {doc.doc_id: doc}
    activities: list[ActivityDefinition] = []
    for a in draft.activities:
        citation = Citation(doc_id=doc.doc_id, doc_type=DocType.OTHER, quote=a.source_quote, location=source_url)
        grounded_citation = ground_citations([citation], documents_by_id, fuzzy_threshold)[0]
        if not grounded_citation.grounded:
            continue
        activities.append(
            ActivityDefinition(
                name=a.name,
                in_scope_description=a.in_scope_description,
                out_of_scope_description=a.out_of_scope_description,
                seed_keywords=a.seed_keywords,
                source_citation=grounded_citation,
            )
        )
    return activities, usage
