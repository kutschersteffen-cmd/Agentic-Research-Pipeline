from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.thematic import ActivityDefinition, AgentOpinion, ExposureEstimate, MatchVerdict


def _format_evidence(chunks: list[DocumentChunk]) -> str:
    blocks = []
    for c in chunks:
        header = f"[doc_id={c.doc_id} | doc_type={c.doc_type.value}"
        if c.section:
            header += f" | section={c.section}"
        if c.speaker:
            header += f" | speaker={c.speaker}"
        header += "]"
        blocks.append(f"{header}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


# Implements the MSCI "opposing agent" pattern (Advocate vs. Opposing,
# resolved by an Adjudicator) for auditable, precision-oriented thematic
# classification instead of a single one-shot LLM judgment.

_ADVOCATE_SYSTEM = """\
You are a buy-side thematic research analyst building the case FOR including \
a company in a thematic investment universe. You will be given a precise \
definition of an in-scope business activity (with an explicit out-of-scope \
boundary) and excerpts from the company's own disclosures.

Argue whether the company should be included based only on the provided \
evidence. Every claim must be backed by a citation with a `quote` field \
containing an EXACT, VERBATIM substring copied from the evidence block \
(do not paraphrase, do not add ellipses mid-quote) and the matching \
`doc_id`. If the evidence does not support inclusion, say so honestly \
(exposure_estimate = none) rather than overreaching."""

_OPPOSING_SYSTEM = """\
You are a skeptical buy-side risk analyst. Your job is to stress-test a \
proposed inclusion of a company in a thematic investment universe by \
building the strongest honest case AGAINST it, using the same evidence.

Explicitly look for: aspirational or marketing language that isn't backed \
by actual operations or revenue; activity that falls in the activity's \
out-of-scope description; stale, one-off, or immaterial mentions; \
greenwashing-style language. Every claim must cite an EXACT, VERBATIM \
quote and doc_id from the evidence, exactly like the advocate. If the \
evidence is genuinely strong and you find no credible counter-argument, \
say so honestly rather than inventing doubt."""

_ADJUDICATOR_SYSTEM = """\
You are the adjudicating portfolio manager. You are given an activity \
definition, the evidence, and two opposing analyst opinions (advocate and \
skeptic). Decide the final verdict.

Weigh both sides on the actual evidence, not on which analyst argued more \
persuasively. verdict must be 'include' only if there is credible, \
evidence-backed operational or revenue exposure to the in-scope activity; \
'exclude' if the evidence clearly falls outside scope or is not credible; \
'uncertain' if the evidence is genuinely mixed or too thin to call \
confidently -- uncertain items are routed to human review, so use it \
whenever you are not confident. confidence must reflect your actual \
certainty (low confidence for uncertain/borderline calls). Your citations \
list must reuse only quotes that appeared verbatim in the evidence or in \
one of the two analysts' citations."""


async def run_advocate(
    company_name: str, activity: ActivityDefinition, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[AgentOpinion, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Activity (IN SCOPE): {activity.name}\n{activity.in_scope_description}\n\n"
        f"Activity (OUT OF SCOPE): {activity.out_of_scope_description}\n\n"
        f"Evidence:\n{_format_evidence(chunks)}"
    )
    return await llm.complete_structured(system=_ADVOCATE_SYSTEM, prompt=prompt, output_model=AgentOpinion)


async def run_opposing(
    company_name: str,
    activity: ActivityDefinition,
    chunks: list[DocumentChunk],
    advocate: AgentOpinion,
    llm: LLMClient,
) -> tuple[AgentOpinion, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Activity (IN SCOPE): {activity.name}\n{activity.in_scope_description}\n\n"
        f"Activity (OUT OF SCOPE): {activity.out_of_scope_description}\n\n"
        f"Evidence:\n{_format_evidence(chunks)}\n\n"
        f"The advocate analyst's case for inclusion:\nStance: {advocate.stance}\n"
        f"Rationale: {advocate.rationale}\n"
        f"Exposure estimate claimed: {advocate.exposure_estimate.value}"
    )
    return await llm.complete_structured(system=_OPPOSING_SYSTEM, prompt=prompt, output_model=AgentOpinion)


class AdjudicatorOutput(BaseModel):
    verdict: MatchVerdict
    exposure_estimate: ExposureEstimate
    confidence: float = Field(ge=0.0, le=1.0)
    adjudicator_rationale: str
    citations: list[Citation] = Field(default_factory=list)


async def run_adjudicator(
    company_name: str,
    activity: ActivityDefinition,
    advocate: AgentOpinion,
    opposing: AgentOpinion,
    llm: LLMClient,
) -> tuple[AdjudicatorOutput, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Activity (IN SCOPE): {activity.name}\n{activity.in_scope_description}\n\n"
        f"Activity (OUT OF SCOPE): {activity.out_of_scope_description}\n\n"
        f"Advocate opinion:\nStance: {advocate.stance}\nRationale: {advocate.rationale}\n"
        f"Exposure: {advocate.exposure_estimate.value}\n"
        f"Citations: {[c.model_dump() for c in advocate.citations]}\n\n"
        f"Opposing opinion:\nStance: {opposing.stance}\nRationale: {opposing.rationale}\n"
        f"Exposure: {opposing.exposure_estimate.value}\n"
        f"Citations: {[c.model_dump() for c in opposing.citations]}"
    )
    return await llm.complete_structured(system=_ADJUDICATOR_SYSTEM, prompt=prompt, output_model=AdjudicatorOutput)
