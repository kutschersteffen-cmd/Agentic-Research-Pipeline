from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from arp.schemas.common import Citation, DocType, ProvenanceInfo, new_id, now_iso
from arp.schemas.review import ReasonCode


class FieldDataType(StrEnum):
    NUMBER = "number"
    CURRENCY_AMOUNT = "currency_amount"
    PERCENTAGE = "percentage"
    STRING = "string"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"


class ValueState(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    NOT_APPLICABLE = "not_applicable"
    ZERO = "zero"


class FieldStatus(StrEnum):
    DRAFT = "draft"
    RELEASED = "released"
    RETIRED = "retired"


class CheckOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class RouteKind(StrEnum):
    AUTO_ACCEPT = "auto_accept"
    REVIEW = "review"
    HOLD = "hold"


class CheckResult(BaseModel):
    check_id: str
    layer: int = Field(ge=1, le=5)
    outcome: CheckOutcome
    severity: Severity = Severity.INFO
    detail: str = ""
    threshold_ref: str | None = None


def is_blocking(r: CheckResult) -> bool:
    return r.outcome == CheckOutcome.FAIL and r.severity == Severity.BLOCK


def is_failing(r: CheckResult) -> bool:
    return r.outcome == CheckOutcome.FAIL and r.severity in (Severity.WARN, Severity.BLOCK)


class CheckConfig(BaseModel):
    min_value: float | None = None
    max_value: float | None = None
    non_negative: bool = False
    part_of: str | None = Field(default=None, description="field_id of the whole this field is part of.")
    sum_of: list[str] = Field(default_factory=list, description="This field equals the sum of these field_ids.")
    sum_tolerance: float = Field(default=0.01, description="Relative.")
    prior_change_max: float | None = Field(default=0.5, description="Relative jump vs. prior value that warns.")
    cross_source_tolerance: float = Field(default=0.01, description="Relative difference vs. another source that warns.")


class ApplicabilityRules(BaseModel):
    """A field applies only to companies matching every non-empty list; unknown company attributes never exclude."""

    sector_codes: list[str] = Field(default_factory=list, description="ISIC Rev.4 code prefixes, e.g. '10'..'33'.")
    countries: list[str] = Field(default_factory=list, description="ISO 3166-1 alpha-2 codes.")
    regimes: list[str] = Field(default_factory=list, description="Reporting regimes, e.g. 'CSRD', 'SEC'.")


class DocumentRouting(BaseModel):
    doc_types: list[DocType] = Field(default_factory=list, description="Document types in preference order.")
    sections: list[str] = Field(default_factory=list, description="Section-heading substrings, case-insensitive.")
    fallback: bool = True


class FieldDefinition(BaseModel):
    field_id: str = Field(default_factory=lambda: new_id("fld"))
    name: str
    description: str = Field(description="Plain-language definition of exactly what this data point means.")
    data_type: FieldDataType
    unit: str | None = Field(
        default=None, description="Canonical unit every value of this field is converted to, e.g. 'tCO2e', 'USD millions', '%'."
    )
    extraction_instructions: str = Field(
        description="Explicit instructions to the extractor agent: where to look, how to disambiguate, edge cases."
    )
    allowed_values: list[str] | None = Field(default=None, description="Required if data_type == enum.")
    required: bool = True
    source_doc_types: list[DocType] = Field(
        default_factory=list, description="Preferred document types to search; empty = search all available."
    )
    seed_keywords: list[str] = Field(
        default_factory=list, description="Seed keywords driving evidence-chunk retrieval for this field."
    )
    version: int = 1
    effective_from: str | None = Field(default=None, description="ISO date the definition took effect.")
    status: FieldStatus = FieldStatus.DRAFT
    check_config: CheckConfig = Field(default_factory=CheckConfig)
    applicability_rules: ApplicabilityRules | None = None
    document_routing: DocumentRouting | None = None
    auto_accept_min: float = Field(default=0.9, ge=0.0, le=1.0)
    high_risk: bool = False
    xbrl_tags: list[str] = Field(
        default_factory=list, description="XBRL concepts, e.g. 'us-gaap:Revenues', tried in order before any model call."
    )


class FieldQuality(BaseModel):
    field_id: str
    version: int
    first_audit_passed: bool = False
    audited_by: str | None = None
    audited_at: str | None = None


class DataPointSchema(BaseModel):
    schema_id: str = Field(default_factory=lambda: new_id("sch"))
    name: str
    description: str = ""
    fields: list[FieldDefinition] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    version: int = 1
    release_flag: bool = False
    released_by: str | None = None
    released_at: str | None = None


class Alternative(BaseModel):
    """A value the extractor, a duplicate reading, the verifier, an adjudicator
    or a tagged fact offered but the row did not keep."""

    value: str | float | bool | None = None
    raw_value_text: str | None = None
    source: Literal["extractor", "duplicate", "verifier", "adjudicator", "tagged"]
    citations: list[Citation] = Field(default_factory=list)


class ExtractedField(BaseModel):
    field_id: str
    field_name: str
    value: str | float | bool | None = Field(description="Normalized value per the field's data_type.")
    raw_value_text: str | None = Field(default=None, description="Verbatim text the value was parsed from.")
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    extractor_confidence: float | None = None
    verifier_confidence: float | None = None
    alternatives: list[Alternative] = Field(default_factory=list)
    grounded: bool = Field(default=False)
    verifier_notes: str | None = None
    conflicting_sources: bool = False
    review_reasons: list[ReasonCode] = Field(default_factory=list)
    provenance: ProvenanceInfo | None = Field(
        default=None, description="Which extractor/verifier model+prompt version produced this field."
    )
    value_state: ValueState = ValueState.NOT_FOUND
    unit: str | None = Field(default=None, description="The unit as reported.")
    canonical_value: float | None = None
    canonical_unit: str | None = None
    scale_applied: float | None = None
    period_text: str | None = None
    period_start: str | None = Field(default=None, description="ISO date.")
    period_end: str | None = Field(default=None, description="ISO date.")
    basis: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    reported_precision: int | None = None
    fx_rate: float | None = None
    fx_rate_ref: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    route_reasons: list[str] = Field(default_factory=list)
    route: RouteKind | None = Field(default=None, description="Set by the pipeline only; None on rows written before routing.")
    input_hash: str | None = None
    reused_from_run: str | None = None
    method: Literal["extracted", "tagged", "adjudicated"] = "extracted"

    @model_validator(mode="before")
    @classmethod
    def _infer_value_state(cls, data):
        # Rows written before value_state existed: derive it from the value.
        if isinstance(data, dict) and "value_state" not in data:
            v = data.get("value")
            if v is None:
                state = ValueState.NOT_FOUND
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0:
                state = ValueState.ZERO
            else:
                state = ValueState.FOUND
            data = {**data, "value_state": state}
        return data


class ExtractionRecord(BaseModel):
    company_id: str
    ticker: str | None = None
    name: str
    schema_id: str
    run_id: str
    issuer_key: str = ""
    issuer_scheme: str = ""
    fields: list[ExtractedField] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    held_documents: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)
