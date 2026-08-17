from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.transition_plan import IndicatorCategory, TransitionPlanIndicator, Verdict, WalkOrTalk
from arp.transition_plan import company_assessment
from arp.transition_plan.basic_info_agent import BasicCompanyInfo
from arp.transition_plan.indicator_agent import IndicatorAnswerDraft

_TWO_INDICATORS = [
    TransitionPlanIndicator(
        number=1, identifier="A_headline_1", category=IndicatorCategory.TARGET, walk_or_talk=WalkOrTalk.TALK,
        question="Does the company report an absolute GHG emission reduction target?", guideline="No additional guidelines",
    ),
    TransitionPlanIndicator(
        number=46, identifier="A_emissions_59", category=IndicatorCategory.TRACKING, walk_or_talk=WalkOrTalk.WALK,
        question="Does the company report its scope 1 GHG emissions for the past year?", guideline="No additional guidelines",
    ),
]

_TEXT = (
    "Climate Strategy\n\nWe target a 50% absolute reduction in GHG emissions by 2030. "
    "Our scope 1 GHG emissions for FY2025 were 1.2 million tonnes CO2e."
)


def _doc() -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="CSR", full_text=_TEXT)


async def test_assess_company_summarizes_walk_talk_and_category_counts(monkeypatch, fake_llm):
    monkeypatch.setattr(company_assessment, "load_indicators", lambda: _TWO_INDICATORS)
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME", sector="Industrials")

    basic_info = BasicCompanyInfo(company_name="Acme Corp", company_sector="Industrials", company_location="Zurich, Switzerland")
    target_draft = IndicatorAnswerDraft(
        verdict=Verdict.YES, answer="Reports a 50% absolute reduction target by 2030.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="target a 50% absolute reduction in GHG emissions by 2030")],
    )
    tracking_draft = IndicatorAnswerDraft(
        verdict=Verdict.NO, answer="No scope 1 emissions figure is disclosed.", citations=[],
    )

    llm = fake_llm({"BasicCompanyInfo": [basic_info], "IndicatorAnswerDraft": [target_draft, tracking_draft]})

    record, usages = await company_assessment.assess_company_transition_plan(
        company, documents=[doc], llm=llm, fuzzy_threshold=0.92, run_id="run_1",
    )

    assert record.company_id == "c1"
    assert record.run_id == "run_1"
    assert record.disclosed_count == 1
    assert record.talk_disclosed_count == 1
    assert record.talk_total_count == 1
    assert record.walk_disclosed_count == 0
    assert record.walk_total_count == 1
    breakdown = {b.category: b for b in record.by_category}
    assert breakdown[IndicatorCategory.TARGET].disclosed_count == 1
    assert breakdown[IndicatorCategory.TRACKING].disclosed_count == 0
    assert record.company_sector == "Industrials"  # supplied by the universe, not overwritten
    assert record.company_location == "Zurich, Switzerland"
    # One basic-info call + one call per indicator.
    assert llm.calls == ["BasicCompanyInfo", "IndicatorAnswerDraft", "IndicatorAnswerDraft"]
    assert len(usages) == 3


async def test_assess_company_no_documents_skips_basic_info_call(monkeypatch, fake_llm):
    monkeypatch.setattr(company_assessment, "load_indicators", lambda: _TWO_INDICATORS)
    company = CompanyRef(company_id="c2", name="Empty Co")
    llm = fake_llm({})

    record, usages = await company_assessment.assess_company_transition_plan(
        company, documents=[], llm=llm, fuzzy_threshold=0.92,
    )

    assert record.disclosed_count == 0
    assert all(a.verdict == Verdict.NA for a in record.indicators)
    assert llm.calls == []
    assert usages == []
