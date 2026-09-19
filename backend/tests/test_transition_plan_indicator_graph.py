from pydantic import ValidationError

from arp.ingestion.parsing import chunk_document
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.transition_plan import IndicatorCategory, TransitionPlanIndicator, Verdict, WalkOrTalk
from arp.transition_plan.indicator_agent import IndicatorAnswerDraft
from arp.transition_plan.indicator_graph import assess_one_indicator
from arp.transition_plan.verifier_agent import IndicatorVerifierOutput

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


def _agreeing_verifier(confidence: float = 1.0) -> IndicatorVerifierOutput:
    return IndicatorVerifierOutput(agrees=True, confidence=confidence, notes="")


async def test_grounded_yes_verdict_is_confident_and_not_flagged(fake_llm):
    doc = _doc()
    draft = IndicatorAnswerDraft(
        verdict=Verdict.YES,
        answer="The company reports a company-wide net zero target for 2050.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="company-wide net zero target for 2050")],
    )
    llm = fake_llm({"IndicatorAnswerDraft": [draft], "IndicatorVerifierOutput": [_agreeing_verifier()]})

    assessment, usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc),
        documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.verdict == Verdict.YES
    assert assessment.grounded is True
    assert assessment.needs_review is False
    assert assessment.confidence == 1.0
    assert assessment.verifier_notes is None
    assert len(usages) == 2


async def test_ungrounded_verdict_is_flagged_for_review(fake_llm):
    doc = _doc()
    draft = IndicatorAnswerDraft(
        verdict=Verdict.YES,
        answer="The company reports a net zero target.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="this exact phrase is not in the document")],
    )
    llm = fake_llm({"IndicatorAnswerDraft": [draft], "IndicatorVerifierOutput": [_agreeing_verifier()]})

    assessment, _usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc), documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.grounded is False
    assert assessment.needs_review is True
    assert assessment.confidence < 1.0


async def test_verifier_disagreement_overrides_verdict_and_flags_review(fake_llm):
    doc = _doc()
    draft = IndicatorAnswerDraft(
        verdict=Verdict.YES,
        answer="The company reports a company-wide net zero target for 2050.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="company-wide net zero target for 2050")],
    )
    verifier = IndicatorVerifierOutput(
        agrees=False,
        corrected_verdict=Verdict.NO,
        confidence=0.9,
        notes="The target covers only Scope 1 emissions, not company-wide.",
    )
    llm = fake_llm({"IndicatorAnswerDraft": [draft], "IndicatorVerifierOutput": [verifier]})

    assessment, usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc), documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.verdict == Verdict.NO
    assert assessment.needs_review is True
    assert assessment.citations == []
    assert assessment.verifier_notes is not None
    assert "Scope 1" in assessment.verifier_notes
    assert len(usages) == 2


async def test_verifier_lower_confidence_caps_final_confidence(fake_llm):
    doc = _doc()
    draft = IndicatorAnswerDraft(
        verdict=Verdict.YES,
        answer="The company reports a company-wide net zero target for 2050.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="company-wide net zero target for 2050")],
    )
    verifier = _agreeing_verifier(confidence=0.4)
    llm = fake_llm({"IndicatorAnswerDraft": [draft], "IndicatorVerifierOutput": [verifier]})

    assessment, _usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc), documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.verdict == Verdict.YES
    assert assessment.confidence == 0.4


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


class _AlwaysInvalidLLM:
    """Simulates LangChainAnthropicClient.complete_structured after it has
    exhausted its own self-correction retries -- raises the ValidationError
    it would otherwise raise, so this test can exercise the graph's own
    isolation of that failure to a single indicator."""

    async def complete_structured(self, *, system, prompt, output_model, max_validation_retries=2, temperature=0.0):
        raise ValidationError.from_exception_data(
            output_model.__name__, [{"type": "missing", "loc": ("verdict",), "input": None}]
        )


async def test_unrecoverable_schema_failure_is_isolated_to_this_indicator(fake_llm):
    """A validation failure that never recovers must not propagate out of
    assess_one_indicator -- it becomes a distinctly-flagged assessment for
    just this indicator, not an exception that would take down the whole
    64-indicator company run one level up."""
    doc = _doc()
    llm = _AlwaysInvalidLLM()

    assessment, usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc), documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.assessment_error is True
    assert assessment.verdict == Verdict.NA
    assert assessment.needs_review is True
    assert "Assessment failed" in assessment.answer
    assert usages == []  # _answer never even started for this indicator


class _ValidAnswerInvalidVerifierLLM:
    """Simulates a draft that answers cleanly but whose independent verifier
    pass never recovers a schema-valid output -- exercises the same
    isolation for the _verify node that _AlwaysInvalidLLM exercises for
    _answer."""

    async def complete_structured(self, *, system, prompt, output_model, max_validation_retries=2, temperature=0.0):
        from arp.llm.base import LLMUsage

        if output_model.__name__ == "IndicatorAnswerDraft":
            return (
                IndicatorAnswerDraft(verdict=Verdict.YES, answer="ok", citations=[]),
                LLMUsage(input_tokens=10, output_tokens=10),
            )
        raise ValidationError.from_exception_data(
            output_model.__name__, [{"type": "missing", "loc": ("agrees",), "input": None}]
        )


async def test_unrecoverable_verifier_failure_is_isolated_to_this_indicator(fake_llm):
    doc = _doc()
    llm = _ValidAnswerInvalidVerifierLLM()

    assessment, usages = await assess_one_indicator(
        "Acme Corp", " - Company name: Acme Corp", _indicator(),
        all_chunks=chunk_document(doc), documents_by_id={doc.doc_id: doc}, llm=llm, fuzzy_threshold=0.92,
    )

    assert assessment.assessment_error is True
    assert assessment.verdict == Verdict.NA
    assert assessment.needs_review is True
    assert "Assessment failed" in assessment.answer
    assert len(usages) == 1  # the draft answer call itself succeeded and is still billed
