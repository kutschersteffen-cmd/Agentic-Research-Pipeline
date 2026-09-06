from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.emerging_themes import CompanyRole


class RoleGoldenSetCase(BaseModel):
    """One manually verified (company evidence, correct role) pair for
    roadmap G4's company-role classification -- same purpose as
    `golden_set/schema.py::GoldenSetCase`, applied to
    `emerging_themes/company_role.py::classify_company_role` instead of
    field extraction. `evidence_quotes` stand in for a company's own
    grounded claims within a candidate theme.
    """

    case_id: str
    description: str = Field(description="What misclassification risk this case is designed to catch.")
    company_name: str
    theme_name: str
    theme_description: str
    evidence_quotes: list[str] = Field(description="Verbatim claims about this company, as they'd appear as ExtractedTag.claim/quote.")
    expected_role: CompanyRole
    notes: str = ""


class RoleGoldenSetCaseResult(BaseModel):
    case_id: str
    description: str
    passed: bool
    expected_role: CompanyRole
    actual_role: CompanyRole | None
    rationale: str = ""
    detail: str = ""


class RoleGoldenSetReport(BaseModel):
    total: int
    passed: int
    failed_case_ids: list[str] = Field(default_factory=list)
    results: list[RoleGoldenSetCaseResult] = Field(default_factory=list)
    run_at: str = ""

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total
