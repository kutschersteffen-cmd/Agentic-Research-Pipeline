from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Market = Literal["sec", "esef"]


class FactRow(BaseModel):
    company_id: str
    cik: str
    taxonomy: str
    concept: str
    unit: str
    value: float
    period_start: str | None
    period_end: str
    fiscal_year: int | None
    fiscal_period: str | None
    form: str
    filed: str | None
    accession: str | None
    source_sha: str
    market: Market = "sec"

    @property
    def tag_id(self) -> str:
        return f"{self.taxonomy}:{self.concept}"


class FactView(FactRow):
    label: str | None


class CatalogEntry(BaseModel):
    taxonomy: str
    concept: str
    label: str | None
    fact_count: int
    first_year: int | None
    last_year: int | None
    units: list[str]


class RequiredRow(BaseModel):
    company_id: str
    cik: str
    metric: Literal["revenue", "capex"]
    fiscal_year: int | None
    status: Literal["found", "not_found"]
    concept: str | None
    value: float | None
    unit: str | None
    period_start: str | None
    period_end: str | None
    form: str | None
    filed: str | None
    market: Market = "sec"


class ReportMeta(BaseModel):
    accession: str
    form: str
    filing_date: str | None
    source_url: str
    primary_document: str
    filename: str
    sha256: str
    size: int
    inline_xbrl: bool


class CompanyStatus(BaseModel):
    company_id: str
    cik: str | None
    status: Literal["ok", "unchanged", "no_cik", "no_lei", "not_found"]
    source_sha: str | None
    fact_count: int
    report: Literal["stored", "unchanged", "none", "error"]
    market: Market = "sec"


class CompanyFiles(BaseModel):
    cik: str
    company_id: str
    name: str | None
    fetched_at: str
    fact_count: int
    tags: list[str] | None
    original_size: int
    report: ReportMeta | None
    market: Market = "sec"


class TagEntry(BaseModel):
    taxonomy: str
    concept: str
    label: str | None
    data_type: str | None
    period_type: str | None
    balance: str | None
    documentation: str | None
    deprecated: bool = False
    extension: bool = False
    seen_count: int = 0

    @property
    def tag_id(self) -> str:
        return f"{self.taxonomy}:{self.concept}"


class PivotRow(BaseModel):
    tag_id: str
    label: str | None
    unit: str
    values: dict[int, float | None]


class PivotTable(BaseModel):
    years: list[int]  # newest first
    rows: list[PivotRow]
    total: int


class VerifyRow(BaseModel):
    company_id: str
    metric: str
    fiscal_year: int
    outcome: Literal["match", "mismatch", "missing_in_run", "missing_in_xbrl"]
    run_value: float | None
    xbrl_value: float | None
    unit: str | None  # the XBRL unit for found XBRL values
    run_unit: str | None = None
    detail: str
