from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import now_iso


class IndustryNode(BaseModel):
    """One industry in the input-output model."""

    isic_code: str
    label: str
    total_output: float = Field(description="Gross total output, denominator for technical coefficients.")


class IndirectExposureResult(BaseModel):
    """A company's structural (supply-chain) exposure to a theme's core
    industries, computed via Leontief input-output propagation -- entirely
    deterministic, no LLM judgment involved in the number itself.
    """

    company_id: str
    isic_code: str
    isic_label: str | None = None
    upstream_exposure: float = Field(
        ge=0.0, le=1.0, description="Share of this industry's total input requirement traceable to core sectors."
    )
    downstream_exposure: float = Field(
        ge=0.0, le=1.0, description="Share of this industry's total downstream propagation landing in core sectors."
    )
    core_sector: bool = Field(description="True if the company's own industry is itself one of the theme's core sectors.")
    icio_edition: str = Field(description="Label identifying which input-output dataset produced this result.")
    generated_at: str = Field(default_factory=now_iso)
