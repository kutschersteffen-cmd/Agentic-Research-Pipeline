from __future__ import annotations

from pydantic import BaseModel, Field

from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import Citation, CompanyRef, DocumentChunk
from arp.schemas.engagement import EngagementIssue, EngagementRecord, ResearchDossier

_SYSTEM_PROMPT = """\
You are a stewardship research analyst preparing a briefing dossier for a \
portfolio manager ahead of a company engagement. You are given the issue \
theme, the company's own prior engagement history with this fund, and \
excerpts from the company's disclosures.

Write a factual research dossier: what the evidence in the company's own \
disclosures says about this issue (summary), any relevant controversy \
context, how the company compares to what peers in the same sector \
typically disclose on this theme (peer_benchmark_notes -- be explicit when \
you are reasoning from general knowledge rather than the supplied \
evidence), and which of the company's known contacts are most relevant \
for this issue.

Every claim about the company's OWN disclosures must cite an EXACT, \
VERBATIM substring from the evidence block with the matching doc_id. \
Do not fabricate a quote. If the evidence doesn't address the issue at \
all, say so honestly (low confidence) rather than padding the summary."""


def _format_evidence(chunks: list[DocumentChunk]) -> str:
    blocks = []
    for c in chunks:
        header = f"[doc_id={c.doc_id} | doc_type={c.doc_type.value}"
        if c.section:
            header += f" | section={c.section}"
        header += "]"
        blocks.append(f"{header}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


def _format_engagement_history(record: EngagementRecord, issue: EngagementIssue) -> str:
    if not issue.correspondence:
        return "No prior correspondence logged for this issue."
    lines = [f"- {c.date} ({c.type.value}): {c.summary}" for c in issue.correspondence]
    return "\n".join(lines)


class ResearchDossierDraft(BaseModel):
    summary: str
    controversy_context: str
    peer_benchmark_notes: str
    recommended_contacts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


async def draft_dossier(
    company_name: str, issue: EngagementIssue, record: EngagementRecord, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[ResearchDossierDraft, LLMUsage]:
    contacts_text = "\n".join(f"- {c.name} ({c.role})" for c in record.contacts) or "No contacts on file."
    prompt = (
        f"Company: {company_name}\n\n"
        f"Issue theme: {issue.theme}\n"
        f"Severity: {issue.severity.value}\n"
        f"Current milestone stage: {issue.milestone_stage.value}\n\n"
        f"Prior correspondence on this issue:\n{_format_engagement_history(record, issue)}\n\n"
        f"Known contacts:\n{contacts_text}\n\n"
        f"Evidence from company disclosures:\n{_format_evidence(chunks) or '(no matching evidence found)'}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=ResearchDossierDraft)


def build_dossier(
    company_id: str,
    issue_id: str,
    draft: ResearchDossierDraft,
    documents_by_id: dict,
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[ResearchDossier, bool]:
    grounded_citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    all_grounded = all(c.grounded for c in grounded_citations) if grounded_citations else True
    needs_review = not all_grounded or draft.confidence < confidence_review_threshold
    dossier = ResearchDossier(
        company_id=company_id,
        issue_id=issue_id,
        summary=draft.summary,
        controversy_context=draft.controversy_context,
        peer_benchmark_notes=draft.peer_benchmark_notes,
        engagement_history_summary="",
        recommended_contacts=draft.recommended_contacts,
        citations=grounded_citations,
        confidence=draft.confidence,
        needs_review=needs_review,
    )
    return dossier, needs_review


async def research_company_issue(
    company: CompanyRef,
    issue: EngagementIssue,
    record: EngagementRecord,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    fuzzy_threshold: float,
    confidence_review_threshold: float,
    max_chunks: int = 12,
) -> tuple[ResearchDossier, bool, LLMUsage]:
    """Fetches the company's available disclosures, prefilters evidence by
    the issue's theme, and drafts a grounded dossier -- the Research Agent
    step of the engagement data flow, run before the human dossier-accuracy
    checkpoint that gates handoff to the Drafting Agent."""
    documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}
    keywords = [issue.theme.replace("_", " ")]
    all_chunks: list[DocumentChunk] = []
    for doc in documents:
        all_chunks.extend(chunk_document(doc, keywords=keywords))
    evidence = select_relevant_chunks(all_chunks, keywords, max_chunks=max_chunks, fallback_to_all=True)

    draft, usage = await draft_dossier(company.name, issue, record, evidence, llm)
    dossier, needs_review = build_dossier(
        company.company_id, issue.issue_id, draft, documents_by_id, fuzzy_threshold, confidence_review_threshold
    )
    dossier = dossier.model_copy(update={"engagement_history_summary": _format_engagement_history(record, issue)})
    return dossier, needs_review, usage
