from __future__ import annotations

from pydantic import BaseModel

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk

# Verbatim from the paper's Figure S.1 prompt template (Colesanti Senni et
# al. 2024), adapted only to hand the model our own pre-selected evidence
# chunks instead of a fresh embedding retrieval call.
_SYSTEM_PROMPT = """\
You are tasked with the role of a climate scientist and assigned to analyze a company's sustainability report. \
Based on the following extracted parts from the sustainability report, answer the given QUESTIONS. If you don't \
know the answer, just say that you don't know by answering "NA". Don't try to make up an answer."""


class BasicCompanyInfo(BaseModel):
    company_name: str
    company_sector: str
    company_location: str


async def get_basic_company_info(chunks: list[DocumentChunk], llm: LLMClient) -> tuple[BasicCompanyInfo, LLMUsage]:
    """One call per company, reused across all 64 indicator prompts as
    `{basic_info}` -- mirrors basicInformation() in the paper's reference
    implementation, which likewise resolves company/sector/location once
    per report rather than per question.
    """
    prompt = (
        "QUESTIONS:\n"
        "1. What is the company of the report?\n"
        "2. What sector does the company belong to?\n"
        "3. Where is the company located?\n\n"
        f"Sources:\n{format_evidence(chunks)}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=BasicCompanyInfo)


def format_basic_info(info: BasicCompanyInfo) -> str:
    return f" - Company name: {info.company_name}\n - Industry: {info.company_sector}\n - Headquarter Location: {info.company_location}"
