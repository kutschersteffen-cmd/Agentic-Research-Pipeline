from __future__ import annotations

from arp.emerging_themes.company_role import CompanyRoleAssessment
from arp.golden_set.role_runner import load_role_cases, run_role_golden_set


async def test_bundled_role_golden_set_loads_and_covers_every_role():
    cases = load_role_cases()
    assert len(cases) >= 7
    assert len({c.case_id for c in cases}) == len(cases)  # unique case_ids
    # every role, including ambiguous, has at least one seed case
    from arp.schemas.emerging_themes import CompanyRole
    covered_roles = {c.expected_role for c in cases}
    assert covered_roles == set(CompanyRole)


async def test_role_golden_set_harness_scores_pass_and_fail_correctly(fake_llm):
    """Offline harness-mechanics test (no network/API key): scripts a
    correct role for the first case and a wrong one for the second, and
    checks the report's pass/fail scoring is correct -- independent of any
    real model's behavior. Mirrors test_golden_set.py's own harness test."""
    cases = load_role_cases()[:2]
    correct_role = cases[0].expected_role
    wrong_role = next(r for r in type(cases[1].expected_role) if r != cases[1].expected_role)

    llm = fake_llm({
        "CompanyRoleAssessment": [
            CompanyRoleAssessment(role=correct_role, rationale="matches"),
            CompanyRoleAssessment(role=wrong_role, rationale="does not match"),
        ]
    })

    report = await run_role_golden_set(cases, llm=llm)

    assert report.total == 2
    assert report.passed == 1
    assert report.failed_case_ids == [cases[1].case_id]
    assert report.results[0].passed is True
    assert report.results[1].passed is False
    assert "Expected" in report.results[1].detail
