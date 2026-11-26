from arp.config import Settings
from arp.research.indirect_exposure.company_mapper import _CompanySectorClassification, resolve_company_sector
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.schemas.common import CompanyRef

MACHINERY = "Manufacture of electrical machinery and apparatus n.e.c."


def _model():
    return resolve_indirect_exposure_model(Settings(), use_sample=True)


async def test_supplied_isic_code_skips_llm(fake_llm):
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Mining", isic_code="07")  # links through NACE: no sector to pick
    llm = fake_llm({})
    sector, usage = await resolve_company_sector(company, model, llm)
    assert sector is None
    assert llm.calls == []
    assert usage.input_tokens == 0


async def test_nace_company_skips_llm(fake_llm):  # AC-34
    llm = fake_llm({})
    sector, _ = await resolve_company_sector(CompanyRef(company_id="c1", name="Kupfer", nace_code="24.44", nace_rev="2"), _model(), llm)
    assert sector is None and llm.calls == []


async def test_supplied_unknown_isic_code_falls_back_to_llm(fake_llm):
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Widgets", isic_code="C27")  # an old ICIO code: no NACE route
    draft = _CompanySectorClassification(sector=MACHINERY, rationale="makes electrical widgets")
    llm = fake_llm({_CompanySectorClassification.__name__: [draft]})
    sector, usage = await resolve_company_sector(company, model, llm)
    assert sector == MACHINERY
    assert llm.calls == [_CompanySectorClassification.__name__]


async def test_llm_answers_a_listed_sector(fake_llm):
    draft = _CompanySectorClassification(sector="Copper production", rationale="smelter")
    llm = fake_llm({_CompanySectorClassification.__name__: [draft]})
    sector, _ = await resolve_company_sector(CompanyRef(company_id="c1", name="Kupfer"), _model(), llm)
    assert sector == "Copper production"


async def test_llm_hallucinated_code_treated_as_none(fake_llm):  # AC-35
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Widgets")
    draft = _CompanySectorClassification(sector="Made-up sector", rationale="?")
    llm = fake_llm({_CompanySectorClassification.__name__: [draft]})
    sector, _usage = await resolve_company_sector(company, model, llm)
    assert sector is None


async def test_llm_explicit_none_passthrough(fake_llm):
    model = _model()
    company = CompanyRef(company_id="c1", name="Acme Widgets")
    draft = _CompanySectorClassification(sector=None, rationale="no good match in this narrow list")
    llm = fake_llm({_CompanySectorClassification.__name__: [draft]})
    sector, _usage = await resolve_company_sector(company, model, llm)
    assert sector is None


async def test_llm_prompt_names_the_company_and_says_unknown_for_missing_fields():
    from arp.llm.base import LLMUsage

    prompts = []

    class Recording:
        async def complete_structured(self, *, system, prompt, output_model, **kwargs):
            prompts.append(prompt)
            return output_model(sector=None, rationale="-"), LLMUsage()

    model = _model()
    await resolve_company_sector(CompanyRef(company_id="c1", name="Acme Widgets"), model, Recording())
    await resolve_company_sector(CompanyRef(company_id="c2", name="Kupfer AG", sector="Mining", country="DE"), model, Recording())
    head = "\n\nAvailable EXIOBASE sectors:\n" + model.industry_prompt_list()
    assert prompts == [
        "Company: Acme Widgets\nSector (if known): unknown\nCountry: unknown" + head,
        "Company: Kupfer AG\nSector (if known): Mining\nCountry: DE" + head,
    ]
