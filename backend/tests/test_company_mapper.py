from arp.research.indirect_exposure.company_mapper import _CompanyIndustryClassification, resolve_company_isic
from arp.research.indirect_exposure.icio_loader import load_sample_icio
from arp.research.indirect_exposure.leontief import build_model
from arp.schemas.common import CompanyRef


def _model():
    return build_model(load_sample_icio(), "test")


async def test_supplied_known_isic_code_skips_llm(fake_llm):
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Mining", isic_code="07")
    llm = fake_llm({})
    code, usage = await resolve_company_isic(company, model, llm)
    assert code == "07"
    assert llm.calls == []
    assert usage.input_tokens == 0


async def test_supplied_unknown_isic_code_falls_back_to_llm(fake_llm):
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Widgets", isic_code="99")  # not in this model
    draft = _CompanyIndustryClassification(isic_code="27", rationale="makes electrical widgets")
    llm = fake_llm({_CompanyIndustryClassification.__name__: [draft]})
    code, usage = await resolve_company_isic(company, model, llm)
    assert code == "27"
    assert llm.calls == [_CompanyIndustryClassification.__name__]


async def test_llm_hallucinated_code_treated_as_none(fake_llm):
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Widgets")
    draft = _CompanyIndustryClassification(isic_code="not-a-real-code", rationale="?")
    llm = fake_llm({_CompanyIndustryClassification.__name__: [draft]})
    code, _usage = await resolve_company_isic(company, model, llm)
    assert code is None


async def test_llm_explicit_none_passthrough(fake_llm):
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Widgets")
    draft = _CompanyIndustryClassification(isic_code=None, rationale="no good match in this narrow list")
    llm = fake_llm({_CompanyIndustryClassification.__name__: [draft]})
    code, _usage = await resolve_company_isic(company, model, llm)
    assert code is None
