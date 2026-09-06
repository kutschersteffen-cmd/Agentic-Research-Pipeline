from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import CompanyRole, ExtractedTag

_SYSTEM_PROMPT = """\
You classify how one company relates to a candidate investment theme, \
using only the claims given about that company. Choose exactly one role \
from this fixed list:

- beneficiary: the theme's growth would plausibly increase this \
company's revenue, margin, or demand.
- enabler: this company supplies a critical input, technology, or \
service the theme's core activity depends on.
- adopter: this company is deploying or using the theme's underlying \
technology/practice in its own operations, without being a primary \
beneficiary of the theme's growth itself.
- transition_candidate: this company is shifting its business toward \
the theme, away from a legacy position.
- bottleneck_owner: this company controls a scarce resource, capacity, \
or chokepoint the theme's growth depends on.
- negatively_exposed: the theme's growth would plausibly hurt this \
company (a legacy incumbent it displaces, a cost it raises).
- ambiguous: the claims given don't clearly support any of the above.

Judge only from the claims given about this company -- do not infer a \
role from the theme in general. If the evidence is thin or mixed, prefer \
ambiguous over guessing."""


class CompanyRoleAssessment(BaseModel):
    role: CompanyRole
    rationale: str = Field(description="One sentence, grounded in the claims given about this company.")


async def classify_company_role(
    company: CompanyRef,
    company_tags: list[ExtractedTag],
    theme_name: str,
    theme_description: str,
    llm: LLMClient,
) -> tuple[CompanyRoleAssessment, LLMUsage] | None:
    """Roadmap G4's per-company role classification: a single closed-list
    call per company, mirroring `indirect_exposure/core_sectors.py`'s
    single-call pattern -- not the heavier Advocate/Opposing/Adjudicator
    debate in `research/matcher_agents.py`, which is reserved for Tool 1's
    higher-stakes, post-ratification company-inclusion decisions. Returns
    None (never fabricates a role) when there's no evidence about this
    company to classify from.
    """
    if not company_tags:
        return None

    claims = "\n".join(f"- {tag.claim} (quote: \"{tag.quote}\")" for tag in company_tags[:10])
    prompt = (
        f"Theme: {theme_name}\n"
        f"Theme description: {theme_description}\n\n"
        f"Company: {company.name}\n\n"
        f"Claims about this company:\n{claims}"
    )
    assessment, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=CompanyRoleAssessment)
    return assessment, usage
