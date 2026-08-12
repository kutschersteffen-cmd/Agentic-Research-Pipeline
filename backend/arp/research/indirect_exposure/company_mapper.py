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


def _format_industry_list(model: LeontiefModel) -> str:
    return "\n".join(f"{code}: {model.labels.get(code, '')}" for code in model.codes)


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
    """
    if company.isic_code and company.isic_code in model.codes:
        return company.isic_code, LLMUsage()

    prompt = (
        f"Company: {company.name}\n"
        f"Sector (if known): {company.sector or 'unknown'}\n"
        f"Country: {company.country or 'unknown'}\n\n"
        f"Available ISIC Rev.4 industries:\n{_format_industry_list(model)}"
    )
    draft, usage = await llm.complete_structured(
        system=_SYSTEM_PROMPT, prompt=prompt, output_model=_CompanyIndustryClassification
    )
    if draft.isic_code and draft.isic_code in model.codes:
        return draft.isic_code, usage
    return None, usage
