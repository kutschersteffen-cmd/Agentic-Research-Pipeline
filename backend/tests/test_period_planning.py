import asyncio

from arp.extraction.extractor_agent import ExtractionDraft, extract_field
from arp.planning.periods import plan_periods, union_planned
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition


def _doc(title="Annual Report 2024", text="Scope 1 emissions   2024   2023   2022"):
    return SourceDocument(company_id="c", doc_type=DocType.SUSTAINABILITY_REPORT, title=title, full_text=text)


def test_document_with_two_comparatives_plans_three_periods():
    plan = plan_periods(_doc(), fiscal_year_end=None, recorded=set())
    assert plan.planned == ["2024-12-31", "2023-12-31", "2022-12-31"]
    assert plan.current == "2024-12-31"


def test_missing_excludes_recorded():
    plan = plan_periods(_doc(), fiscal_year_end=None, recorded={"2023-12-31"})
    assert plan.missing == ["2024-12-31", "2022-12-31"]


def test_no_year_gives_empty_plan():
    plan = plan_periods(_doc("Report", "no years here"), fiscal_year_end=None, recorded=set())
    assert plan.planned == [] and plan.current is None


def test_april_fye_plan():
    plan = plan_periods(_doc(), fiscal_year_end="04-30", recorded=set())
    assert plan.current == "2024-04-30"


def test_union_planned_latest_first():
    a = plan_periods(_doc(), fiscal_year_end=None, recorded=set())
    b = plan_periods(_doc("Report 2023", "FY2022 comparatives"), fiscal_year_end=None, recorded=set())
    docs = [_doc(), _doc("Report 2023", "FY2022 comparatives")]
    for d, p in zip(docs, (a, b), strict=True):
        d.period_plan = p
    assert union_planned(docs) == ["2024-12-31", "2023-12-31", "2022-12-31"]


def test_prompt_lists_planned_periods(fake_llm):
    llm = fake_llm({"ExtractionDraft": [ExtractionDraft(confidence=0.5)]})
    field = FieldDefinition(name="F", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="i")
    asyncio.run(extract_field("Co", field, [], llm, planned_periods=["2024-12-31", "2023-12-31"]))
    assert "2023-12-31" in llm.prompts[0]
