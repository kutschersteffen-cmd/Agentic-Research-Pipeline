from arp.ingestion.parsing import chunk_document
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.transition_plan import IndicatorCategory, TransitionPlanIndicator, Verdict, WalkOrTalk
from arp.transition_plan.indicator_agent import IndicatorAnswerDraft
from arp.transition_plan.indicator_graph import assess_one_indicator

_TEXT = (
    "Climate Transition Strategy\n\n"
    "We have set a company-wide net zero target for 2050, covering all scopes. Our board reviews progress "
    "quarterly against interim targets."
)


def _doc() -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="CSR", full_text=_TEXT)


def _indicator() -> TransitionPlanIndicator:
    return TransitionPlanIndicator(
        number=3,
        identifier="A_ambition_3",
        category=IndicatorCategory.TARGET,
        walk_or_talk=WalkOrTalk.TALK,
        question="Does the company report a company-wide net zero GHG emissions target?",
        guideline="State YES if a company-wide net zero or carbon neutrality target is reported.",
    )


async def test_grounded_yes_verdict_is_confident_and_not_flagged(fake_llm):
    doc = _doc()
    draft = IndicatorAnswerDraft(
        verdict=Verdict.YES,
        answer="The company reports a company-wide net zero target for 2050.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="company-wide net zero target for 2050")],
    )
    llm = fake_llm({"IndicatorAnswerDraft": [draft]})

    assessment, usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc),
        documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.verdict == Verdict.YES
    assert assessment.grounded is True
    assert assessment.needs_review is False
    assert assessment.confidence == 1.0
    assert len(usages) == 1


async def test_ungrounded_verdict_is_flagged_for_review(fake_llm):
    doc = _doc()
    draft = IndicatorAnswerDraft(
        verdict=Verdict.YES,
        answer="The company reports a net zero target.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="this exact phrase is not in the document")],
    )
    llm = fake_llm({"IndicatorAnswerDraft": [draft]})

    assessment, _usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc), documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.grounded is False
    assert assessment.needs_review is True
    assert assessment.confidence < 1.0


async def test_no_evidence_skips_llm_and_reports_na(fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="CSR", full_text="")
    llm = fake_llm({})

    assessment, usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=[], documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.verdict == Verdict.NA
    assert assessment.needs_review is False
    assert usages == []
    assert llm.calls == []
