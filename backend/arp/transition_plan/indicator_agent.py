from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.transition_plan import TransitionPlanIndicator, Verdict

# The persona and the seven substantive guidelines are verbatim from the
# paper's Figure S.2 RAG prompt template (Colesanti Senni et al. 2024) --
# the greenwashing skepticism, "cheap talk" awareness, and precision/
# grounding instructions are exactly what the paper's human evaluation
# validated with 28 domain experts across 26 institutions. Guideline #8
# ("start your answer with [[YES]]/[[NO]]") is replaced by a structured
# `verdict` field and per-citation `quote`s tied to `doc_id`, so the
# programmatic grounding check (arp/grounding.py) -- rather than a regex
# over the model's free text -- verifies every citation against the
# original document, the same precision discipline this codebase applies
# everywhere else.
_SYSTEM_PROMPT = """\
You are a senior sustainability analyst with expertise in climate science evaluating a company's climate-related \
transition plan and strategy.

Given the source information and no prior knowledge, your main task is to respond to the posed question about the \
company's disclosures. Enforce the following guidelines in your answer:
1. Your response must be precise, thorough, and grounded on specific extracts from the report to verify its \
authenticity.
2. If you are unsure, simply acknowledge the lack of knowledge, rather than fabricating an answer.
3. Keep your answer within the requested word limit.
4. Be skeptical of the information disclosed in the report as there might be greenwashing (exaggerating the firm's \
environmental responsibility). Always answer in a critical tone.
5. Cheap talks are statements that are costless to make and may not necessarily reflect the true intentions or \
future actions of the company. Be critical of all cheap talk you discover in the report.
6. Always acknowledge that the information provided represents the company's view based on its report.
7. Scrutinize whether the report is grounded in quantifiable, concrete data or vague, unverifiable statements, and \
communicate your findings.
8. Every citation's `quote` must be an EXACT, VERBATIM substring copied from the evidence block, tagged with the \
matching doc_id -- never paraphrase a citation."""

_ANSWER_LENGTH_WORDS = 200


class IndicatorAnswerDraft(BaseModel):
    verdict: Verdict = Field(description="YES if the report discloses the requested information, NO if it does not, NA if the question does not apply (e.g. it presupposes a practice -- like using carbon offsets -- the company does not report doing at all).")
    answer: str = Field(description="A precise, critical, evidence-grounded explanation of the verdict, per the guidelines. Do not restate the question.")
    citations: list[Citation] = Field(default_factory=list)


async def answer_indicator(
    company_name: str,
    basic_info_text: str,
    indicator: TransitionPlanIndicator,
    chunks: list[DocumentChunk],
    llm: LLMClient,
) -> tuple[IndicatorAnswerDraft, LLMUsage]:
    prompt = (
        f"This is basic information about the company:\n{basic_info_text}\n\n"
        f"Question: ||{indicator.question}||\n\n"
        "Please consider the following additional explanation to the question as crucial for answering it:\n"
        f"+++++ [BEGIN OF EXPLANATION]\n{indicator.guideline}\n+++++ [END OF EXPLANATION]\n\n"
        f"Keep your answer within {_ANSWER_LENGTH_WORDS} words.\n\n"
        f"Sources from the company's report:\n{format_evidence(chunks)}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=IndicatorAnswerDraft)
