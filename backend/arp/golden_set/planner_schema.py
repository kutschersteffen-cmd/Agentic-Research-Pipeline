from __future__ import annotations

from pydantic import BaseModel, Field


class PlannerCase(BaseModel):
    """One brief plus the shape of dashboard it must produce.

    The counterpart of `GoldenSetCase` for the generative-BI planner: that
    harness asks "did the extractor read the right number out of this
    document", this one asks "did the planner choose the right *questions*
    to ask of the holdings". Assertions are deliberately about shape --
    which kinds, metrics, dimensions and fields must appear -- never about
    exact titles or panel order, because a planner that phrases a title
    differently has not regressed, and a harness that fails on wording
    would be abandoned within a week.

    Every case is written against the bundled demo dataset
    (`arp/portfolio/mock_data.py`), so a run is reproducible anywhere
    rather than dependent on what a given deployment happens to hold.
    """

    case_id: str
    description: str = Field(description="What planning failure this case is designed to catch.")
    brief: str
    expect_understood: bool = Field(
        default=True, description="False for briefs the planner must refuse to guess at (ambiguous or out of scope)."
    )
    expect_clarification_contains: str = Field(
        default="", description="Substring the clarification must mention, for expect_understood=False cases."
    )
    min_panels: int = 1
    max_panels: int = 6
    require_kinds: list[str] = Field(default_factory=list, description='Each must appear in >=1 panel, e.g. "trend".')
    require_metrics: list[str] = Field(default_factory=list)
    require_dimensions: list[str] = Field(
        default_factory=list, description="Each must be a group_by, row_dim or col_dim of >=1 panel."
    )
    require_field_ids: list[str] = Field(default_factory=list, description="Data-point fields >=1 panel must aggregate.")
    require_portfolio_filter: list[str] = Field(
        default_factory=list, description="Portfolio ids >=1 panel must be restricted to."
    )
    forbid_rejected_panels: bool = Field(
        default=True,
        description="Fail the case if any planned panel failed validation -- a plan is only good if it is also runnable.",
    )
    notes: str = ""


class PlannerCaseResult(BaseModel):
    case_id: str
    description: str
    passed: bool
    failures: list[str] = Field(default_factory=list, description="One line per unmet assertion.")
    panel_count: int = 0
    panels: list[str] = Field(default_factory=list, description="Human-readable summary of each planned panel.")
    warnings: list[str] = Field(default_factory=list)
    clarification: str = ""


class PlannerReport(BaseModel):
    total: int
    passed: int
    failed_case_ids: list[str] = Field(default_factory=list)
    results: list[PlannerCaseResult] = Field(default_factory=list)
    run_at: str = ""
    model: str | None = None
    repair_enabled: bool = False

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total
