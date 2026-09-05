from __future__ import annotations

import json
from pathlib import Path

from arp.extraction.field_graph import extract_one_field
from arp.golden_set.schema import GoldenSetCase, GoldenSetCaseResult, GoldenSetReport
from arp.llm.base import LLMClient
from arp.schemas.common import SourceDocument, new_id, now_iso

_BUNDLED_CASES_PATH = Path(__file__).parent / "data" / "extraction_cases.json"


def load_cases(path: Path | None = None) -> list[GoldenSetCase]:
    """Loads the bundled golden set by default, or a user-supplied file of
    the same shape (a JSON array of GoldenSetCase objects) -- e.g. a
    deployment's own accumulated set of previously-reviewed extractions,
    which is exactly what a "golden set" is meant to grow into over time.
    """
    raw = json.loads((path or _BUNDLED_CASES_PATH).read_text())
    return [GoldenSetCase.model_validate(c) for c in raw]


def _values_match(expected: str | float | bool | None, actual: str | float | bool | None, tolerance: float) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= tolerance
    return str(expected).strip().lower() == str(actual).strip().lower()


async def run_golden_set(
    cases: list[GoldenSetCase],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> GoldenSetReport:
    """Runs every case through the exact same extract -> independent-verify
    -> programmatic-grounding-check flow a real extraction run uses
    (`extract_one_field`), and compares the result against the
    human-verified expected value. Intended to run before a prompt or
    model change reaches a real batch -- a regression here is cheaper to
    catch than one discovered downstream in the review queue at
    4000-company scale.
    """
    results: list[GoldenSetCaseResult] = []
    extractor_model: str | None = None
    verifier_model: str | None = None

    for case in cases:
        doc = SourceDocument(
            doc_id=new_id("golden"),
            company_id="golden-set",
            doc_type=case.doc_type,
            title=case.case_id,
            full_text=case.document_text,
        )
        extracted, needs_review, _usages = await extract_one_field(
            case.company_name,
            case.field,
            documents=[doc],
            documents_by_id={doc.doc_id: doc},
            llm=llm,
            verifier_llm=verifier_llm,
            fuzzy_threshold=fuzzy_threshold,
            confidence_review_threshold=confidence_review_threshold,
        )
        if extracted.provenance:
            extractor_model = extractor_model or extracted.provenance.extractor_model
            verifier_model = verifier_model or extracted.provenance.verifier_model

        passed = _values_match(case.expected_value, extracted.value, case.value_tolerance)
        detail = "" if passed else f"Expected {case.expected_value!r}, got {extracted.value!r}."
        if not passed and extracted.verifier_notes:
            detail += f" Verifier notes: {extracted.verifier_notes}"

        results.append(
            GoldenSetCaseResult(
                case_id=case.case_id,
                description=case.description,
                passed=passed,
                expected_value=case.expected_value,
                actual_value=extracted.value,
                confidence=extracted.confidence,
                grounded=extracted.grounded,
                needs_review=needs_review,
                extractor_model=extracted.provenance.extractor_model if extracted.provenance else None,
                verifier_model=extracted.provenance.verifier_model if extracted.provenance else None,
                detail=detail,
            )
        )

    passed_count = sum(1 for r in results if r.passed)
    return GoldenSetReport(
        total=len(results),
        passed=passed_count,
        failed_case_ids=[r.case_id for r in results if not r.passed],
        results=results,
        run_at=now_iso(),
        extractor_model=extractor_model,
        verifier_model=verifier_model,
    )
