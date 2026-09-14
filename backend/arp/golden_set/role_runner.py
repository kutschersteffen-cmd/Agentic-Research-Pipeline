from __future__ import annotations

import json
from pathlib import Path

from arp.emerging_themes.company_role import classify_company_role
from arp.golden_set.role_schema import RoleGoldenSetCase, RoleGoldenSetCaseResult, RoleGoldenSetReport
from arp.llm.base import LLMClient
from arp.schemas.common import CompanyRef, now_iso
from arp.schemas.emerging_themes import ExtractedTag

_BUNDLED_CASES_PATH = Path(__file__).parent / "data" / "role_cases.json"


def load_role_cases(path: Path | None = None) -> list[RoleGoldenSetCase]:
    """Loads the bundled role golden set by default, or a user-supplied
    file of the same shape -- mirrors `golden_set/runner.py::load_cases`."""
    raw = json.loads((path or _BUNDLED_CASES_PATH).read_text())
    return [RoleGoldenSetCase.model_validate(c) for c in raw]


async def run_role_golden_set(cases: list[RoleGoldenSetCase], *, llm: LLMClient) -> RoleGoldenSetReport:
    """Runs every case through the real `classify_company_role` function
    and compares the result against the human-verified expected role.
    Intended to run before any change to the role-classification prompt
    or model reaches production -- same discipline as
    `golden_set/runner.py::run_golden_set`, applied to a categorical
    (exact-match) comparison instead of a tolerance-banded numeric one.
    """
    results: list[RoleGoldenSetCaseResult] = []

    for case in cases:
        company = CompanyRef(company_id="golden-set", name=case.company_name)
        tags = [
            ExtractedTag(mention_id="golden", label=case.case_id, claim=quote, quote=quote, grounded=True)
            for quote in case.evidence_quotes
        ]
        role_result = await classify_company_role(company, tags, case.theme_name, case.theme_description, llm)

        if role_result is None:
            results.append(RoleGoldenSetCaseResult(
                case_id=case.case_id, description=case.description, passed=False,
                expected_role=case.expected_role, actual_role=None,
                detail="classify_company_role returned None (no evidence) -- check the case's evidence_quotes.",
            ))
            continue

        assessment, _usage = role_result
        passed = assessment.role == case.expected_role
        detail = "" if passed else f"Expected {case.expected_role.value!r}, got {assessment.role.value!r}."
        results.append(RoleGoldenSetCaseResult(
            case_id=case.case_id, description=case.description, passed=passed,
            expected_role=case.expected_role, actual_role=assessment.role,
            rationale=assessment.rationale, detail=detail,
        ))

    passed_count = sum(1 for r in results if r.passed)
    return RoleGoldenSetReport(
        total=len(results),
        passed=passed_count,
        failed_case_ids=[r.case_id for r in results if not r.passed],
        results=results,
        run_at=now_iso(),
    )
