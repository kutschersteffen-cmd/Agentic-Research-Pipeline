from __future__ import annotations

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.schemas.common import CompanyRef

_SYSTEM_PROMPT = """\
You classify a company into the single best-fitting industry from a fixed, \
closed list of ISIC Rev.4 industries. This list is deliberately narrow (it \
covers one input-output model's industries, not the whole economy), so if \
none of the listed industries is a good fit for the company's actual \
business, return null rather than forcing the closest-sounding option."""


class _CompanyIndustryClassification(BaseModel):
    isic_code: str | None
    rationale: str


async def resolve_company_isic(
    company: CompanyRef, model: LeontiefModel, llm: LLMClient
) -> tuple[str | None, LLMUsage]:
    """Resolves a company's ISIC industry code against this model's fixed
    industry list.

    A code already supplied on the CompanyRef is used directly (the precise
    path, zero cost) as long as it's actually in this model -- a code from
    a different classification scheme is treated as absent rather than
    silently mismatched. Otherwise falls back to one LLM classification
    call, which the shared disk cache makes free on any rerun.

    In between, an ISIC Rev.4 division (`26`) or NACE class (`35.12`) found,
    as an exact string, in exactly one industry's isic_divisions or
    nace_classes resolves to that industry, also without an LLM call.
    """
    if company.isic_code and company.isic_code in model.codes:
        return company.isic_code, LLMUsage()
    if company.isic_code:
        hits = [
            code for code in model.codes
            if company.isic_code in model.isic_divisions.get(code, []) or company.isic_code in model.nace_classes.get(code, [])
        ]
        if len(hits) == 1:
            return hits[0], LLMUsage()

    prompt = (
        f"Company: {company.name}\n"
        f"Sector (if known): {company.sector or 'unknown'}\n"
        f"Country: {company.country or 'unknown'}\n\n"
        f"Available ISIC Rev.4 industries:\n{model.industry_prompt_list()}"
    )
    draft, usage = await llm.complete_structured(
        system=_SYSTEM_PROMPT, prompt=prompt, output_model=_CompanyIndustryClassification
    )
    if draft.isic_code and draft.isic_code in model.codes:
        return draft.isic_code, usage
    return None, usage
