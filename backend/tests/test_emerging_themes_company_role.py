from arp.emerging_themes.company_role import CompanyRoleAssessment, classify_company_role
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import CompanyRole, ExtractedTag


def _tag(tag_id: str, claim: str) -> ExtractedTag:
    return ExtractedTag(tag_id=tag_id, mention_id="m1", label="l", claim=claim, quote=claim)


async def test_returns_none_with_no_llm_call_for_empty_evidence(fake_llm):
    company = CompanyRef(company_id="acme", name="Acme Battery Co")
    llm = fake_llm({})

    result = await classify_company_role(company, [], "Solid-state batteries", "desc", llm)

    assert result is None
    assert llm.calls == []


async def test_parses_role_and_rationale_from_llm_response(fake_llm):
    company = CompanyRef(company_id="acme", name="Acme Battery Co")
    tags = [_tag("t1", "Acme Battery Co says orders for its cells have tripled.")]
    assessment = CompanyRoleAssessment(role=CompanyRole.BENEFICIARY, rationale="Direct revenue upside from theme growth.")
    llm = fake_llm({"CompanyRoleAssessment": [assessment]})

    result = await classify_company_role(company, tags, "Solid-state batteries", "desc", llm)

    assert result is not None
    result_assessment, usage = result
    assert result_assessment.role == CompanyRole.BENEFICIARY
    assert result_assessment.rationale == "Direct revenue upside from theme growth."
    assert usage.input_tokens > 0
