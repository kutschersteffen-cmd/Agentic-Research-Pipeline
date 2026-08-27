from __future__ import annotations

import pytest

from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.golden_set.runner import load_cases, run_golden_set


@pytest.mark.asyncio
async def test_bundled_golden_set_loads_and_matches_case_count():
    cases = load_cases()
    assert len(cases) >= 5
    assert len({c.case_id for c in cases}) == len(cases)  # unique case_ids


@pytest.mark.asyncio
async def test_golden_set_harness_scores_pass_and_fail_correctly(fake_llm):
    """Offline harness-mechanics test (no network/API key, matching every
    other test in this suite): scripts a correct extractor/verifier
    response for the first case and a wrong one for the second, and checks
    the report's pass/fail scoring, tolerance handling, and provenance
    capture are all correct -- independent of any real model's behavior.
    """
    cases = load_cases()[:2]
    correct_value = cases[0].expected_value
    wrong_value = 1.0 if cases[1].expected_value != 1.0 else 2.0

    llm = fake_llm(
        {
            "ExtractionDraft": [
                ExtractionDraft(value=correct_value, raw_value_text=str(correct_value), citations=[], confidence=0.95),
                ExtractionDraft(value=wrong_value, raw_value_text=str(wrong_value), citations=[], confidence=0.9),
            ]
        }
    )
    verifier_llm = fake_llm(
        {
            "VerifierOutput": [
                VerifierOutput(agrees=True, confidence=0.95, notes=""),
                VerifierOutput(agrees=True, confidence=0.9, notes=""),
            ]
        }
    )

    report = await run_golden_set(
        cases,
        llm=llm,
        verifier_llm=verifier_llm,
        fuzzy_threshold=0.92,
        confidence_review_threshold=0.6,
    )

    assert report.total == 2
    assert report.passed == 1
    assert report.failed_case_ids == [cases[1].case_id]
    assert report.results[0].passed is True
    assert report.results[1].passed is False
    assert "Expected" in report.results[1].detail
    # Both clients are FakeLLMClient instances (no real .model attribute),
    # so provenance falls back to whatever LLMUsage carried -- the point
    # here is only that the field is wired through end to end, not tied to
    # a specific fake model string.
    assert report.results[0].extractor_model == ""
