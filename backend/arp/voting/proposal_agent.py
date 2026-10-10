from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.voting import ProposalType, VotePosition

_SYSTEM_PROMPT = """\
You are a proxy-voting research analyst extracting ballot items from a \
proxy statement (e.g. DEF 14A or an equivalent non-US filing). Identify \
every distinct proposal on the ballot and, for each, extract: its printed \
proposal number, its type, who sponsored it ('Management' for board- \
proposed items, otherwise the filing shareholder's name), the resolution \
text, management's recommended vote if stated, and any structured \
supporting figures explicitly relevant to evaluating it (e.g. \
non-audit-fee ratio for an auditor ratification, CEO pay ratio for a \
say-on-pay item) as a flat string-to-string map -- only include a figure \
if it is explicitly disclosed, never estimated.

Every citation's `quote` must be an EXACT, VERBATIM substring copied from \
the evidence block, tagged with the matching doc_id. If a ballot item's \
type doesn't fit a standard category, use 'other'. If the evidence \
contains no identifiable ballot items, return an empty list rather than \
guessing."""


class ProposalDraft(BaseModel):
    proposal_number: str
    type: ProposalType
    sponsor: str
    resolution_text: str
    management_recommendation: VotePosition | None = None
    supporting_data: dict[str, str] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ProposalListDraft(BaseModel):
    proposals: list[ProposalDraft] = Field(default_factory=list)


async def extract_proposals(
    company_name: str, meeting_date: str | None, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[ProposalListDraft, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n"
        + (f"Meeting date: {meeting_date}\n" if meeting_date else "")
        + f"\nProxy statement evidence:\n{format_evidence(chunks, ('doc_id', 'section')) or '(no proxy statement text available)'}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=ProposalListDraft)
