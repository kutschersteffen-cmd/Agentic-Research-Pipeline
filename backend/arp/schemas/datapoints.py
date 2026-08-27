from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, DocType, ProvenanceInfo, now_iso, new_id


class FieldDataType(StrEnum):
    NUMBER = "number"
    CURRENCY_AMOUNT = "currency_amount"
    PERCENTAGE = "percentage"
    STRING = "string"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"


class FieldDefinition(BaseModel):
    field_id: str = Field(default_factory=lambda: new_id("fld"))
    name: str
    description: str = Field(description="Plain-language definition of exactly what this data point means.")
    data_type: FieldDataType
    unit: str | None = Field(default=None, description="e.g. 'USD millions', '%', 'fiscal year'.")
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


class DataPointSchema(BaseModel):
    schema_id: str = Field(default_factory=lambda: new_id("sch"))
    name: str
    description: str = ""
    fields: list[FieldDefinition] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ExtractedField(BaseModel):
    field_id: str
    field_name: str
    value: str | float | bool | None = Field(description="Normalized value per the field's data_type.")
    raw_value_text: str | None = Field(default=None, description="Verbatim text the value was parsed from.")
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    grounded: bool = Field(default=False)
    verifier_notes: str | None = None
    conflicting_sources: bool = False
    provenance: ProvenanceInfo | None = Field(
        default=None, description="Which extractor/verifier model+prompt version produced this field."
    )


class ExtractionRecord(BaseModel):
    company_id: str
    ticker: str | None = None
    name: str
    schema_id: str
    run_id: str
    fields: list[ExtractedField] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    generated_at: str = Field(default_factory=now_iso)
