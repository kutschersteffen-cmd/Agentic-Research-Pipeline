from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import DocType
from arp.schemas.datapoints import FieldDefinition


class GoldenSetCase(BaseModel):
    """One manually verified (evidence, correct answer) pair for a single
    extraction field. The fixture set as a whole is the regression harness
    the METHODOLOGY.md gap analysis calls for: run it against a new
    prompt/model before that change reaches a real batch, not after.

    `document_text` stands in for a company's full disclosure text --
    short and self-contained by design, so a human reviewer can actually
    read and verify every case (the same reasoning `docs/METHODOLOGY.md`
    gives for keeping the LLM's own context narrow).
    """

    case_id: str
    description: str = Field(description="What precision failure this case is designed to catch.")
    company_name: str
    field: FieldDefinition
    document_text: str
    doc_type: DocType = DocType.OTHER
    expected_value: str | float | bool | None
    value_tolerance: float = Field(
        default=0.01, description="Absolute tolerance for numeric comparisons; ignored for non-numeric values."
    )
    expect_not_disclosed: bool = Field(
        default=False, description="True when expected_value is intentionally None (a 'not disclosed' case)."
    )
    notes: str = ""


class GoldenSetCaseResult(BaseModel):
    case_id: str
    description: str
    passed: bool
    expected_value: str | float | bool | None
    actual_value: str | float | bool | None
    confidence: float
    grounded: bool
    needs_review: bool
    extractor_model: str | None = None
    verifier_model: str | None = None
    detail: str = ""


class GoldenSetReport(BaseModel):
    total: int
    passed: int
    failed_case_ids: list[str] = Field(default_factory=list)
    results: list[GoldenSetCaseResult] = Field(default_factory=list)
    run_at: str = ""
    extractor_model: str | None = None
    verifier_model: str | None = None

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total
