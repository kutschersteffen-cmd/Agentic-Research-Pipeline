from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.replication.spec_extractor_agent import StrategySpecDraft
from arp.schemas.common import DocumentChunk

_SYSTEM_PROMPT = """\
You are an independent verification analyst reviewing another analyst's \
reduction of an academic strategy paper into an executable specification. \
Your job is to catch their mistakes, not rubber-stamp them.

Re-read the same excerpts and check: does formation_period_months/holding_\
period_months/skip_month actually match what's described? Is bucket \
numbering right (bucket 1 = highest signal, consistently)? Do the reported \
performance figures match what the excerpts state, including units (e.g. \
monthly vs. annualized, % vs. decimal)? Is every citation's quote real and \
does it actually support the field it's attached to?

Set agrees=false and provide a full corrected specification (`corrected`, \
every field, not just the ones you disagree with) whenever you find a \
problem, even a small one. Be skeptical."""


class SpecVerifierOutput(BaseModel):
    agrees: bool
    corrected: StrategySpecDraft | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


async def verify_strategy_spec(
    paper_citation: str, chunks: list[DocumentChunk], draft: StrategySpecDraft, llm: LLMClient
) -> tuple[SpecVerifierOutput, LLMUsage]:
    prompt = (
        f"Paper citation: {paper_citation}\n\n"
        f"Excerpts:\n{format_evidence(chunks)}\n\n"
        f"Draft specification to verify:\n{draft.model_dump_json(indent=2)}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=SpecVerifierOutput)
