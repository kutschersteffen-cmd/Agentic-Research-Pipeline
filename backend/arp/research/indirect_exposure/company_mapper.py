from __future__ import annotations

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.schemas.common import CompanyRef

_SYSTEM_PROMPT = """\
You classify a company into the single best-fitting sector from a fixed, \
closed list of EXIOBASE sectors. Answer with the sector name exactly as \
listed. If none of the listed sectors is a good fit for the company's \
actual business, return null rather than forcing the closest-sounding option."""


class _CompanySectorClassification(BaseModel):
    sector: str | None
    rationale: str


async def resolve_company_sector(
    company: CompanyRef, model: LeontiefModel, llm: LLMClient
) -> tuple[str | None, LLMUsage]:
    """The company's EXIOBASE sector when its NACE/ISIC codes don't give one.

    A company `value_chain.links.company_nace` resolves (a NACE code, or a
    2- or 4-digit ISIC Rev.4 code) gets None with no LLM call: its sectors
    come from that code. Otherwise one LLM call picks a sector name from the
    model's closed list (the shared disk cache makes reruns free); an
    answer not in the list gives None.
    """
    from arp.research.value_chain.links import company_nace  # links imports this module

    if company_nace(company) is not None:
        return None, LLMUsage()

    prompt = (
        f"Company: {company.name}\n"
        f"Sector (if known): {company.sector or 'unknown'}\n"
        f"Country: {company.country or 'unknown'}\n\n"
        f"Available EXIOBASE sectors:\n{model.industry_prompt_list()}"
    )
    draft, usage = await llm.complete_structured(
        system=_SYSTEM_PROMPT, prompt=prompt, output_model=_CompanySectorClassification
    )
    return (draft.sector if draft.sector in model.codes else None), usage
