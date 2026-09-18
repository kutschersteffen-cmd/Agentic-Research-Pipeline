from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import now_iso

# Sector-pillar code, e.g. "PWR-T1", "OGU-D1". The source data mixed hyphens
# and underscores (shipping used SHP_T1); normalised to hyphens on import and
# pinned here so the inconsistency cannot come back.
CRITERION_CODE_PATTERN = r"^[A-Z]{3}-[TRD]\d+$"


class Region(StrEnum):
    """The three jurisdictions the matrix is rated for. Values are the literal
    strings used in assessment_scores.json, not slugs.
    """

    EUROPEAN_UNION = "European Union"
    UNITED_STATES = "United States"
    CHINA = "China"


class Pillar(StrEnum):
    """The three constraint categories assessed per sector. Values match the
    `category` field in criteria_schema.json.
    """

    TECHNOLOGY = "Technology"
    REGULATION = "Regulation"
    DEMAND_ECONOMICS = "Demand & Economics"


class Rating(StrEnum):
    """Feasibility rating. HIGH means transition is *more* feasible -- fewer
    barriers -- not that the barrier is high.
    """

    HIGH = "H"
    MODERATE = "M"
    LOW = "L"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AccessPattern(StrEnum):
    """How a source can actually be retrieved. Only the six values that appear
    in source_registry.json -- deliberately not aspirational.
    """

    PERIODIC_PDF_REPORT = "periodic_pdf_report"
    GOVERNMENT_AGENCY_PUBLICATION = "government_agency_publication"
    LEGAL_REGULATORY_TEXT = "legal_regulatory_text"
    INDUSTRY_TRACKER_DATABASE = "industry_tracker_database"
    COMPANY_DISCLOSURE = "company_disclosure"
    STRUCTURED_API_OR_DASHBOARD = "structured_api_or_dashboard"


class PrimarySource(BaseModel):
    """One source attached to one criterion in criteria_schema.json. These six
    fields are all that the data actually carries -- the original design notes
    also mentioned url_pattern/data_field/fallback_url, none of which exist.
    """

    source_name: str
    publisher: str
    url: str | None = Field(
        default=None,
        description="None for company_disclosure sources, where the relevant company varies by who is being assessed.",
    )
    access_pattern: AccessPattern
    refresh_cadence: str
    locator: str = Field(description="Where in the source the figure sits. Doubles as the extraction instruction for a refresh run.")


class BarrierCriterion(BaseModel):
    """One of the 35 transition-barrier criteria: a sector x pillar pair with a
    measurable metric and an explicit H/M/L rubric. Static reference data, not a
    per-run record. See arp/transition_barrier/dataset.py for the loader.
    """

    code: str = Field(pattern=CRITERION_CODE_PATTERN, description="Sector-pillar code, e.g. 'PWR-T1'.")
    sector: str
    category: Pillar
    criterion: str
    metric: str = Field(description="What is actually measured, in enough detail to re-derive the rating.")
    unit: str
    rating_rubric: dict[Rating, str] = Field(description="The H/M/L thresholds, verbatim from the research tool.")
    primary_sources: list[PrimarySource]


class BarrierScore(BaseModel):
    """One criterion's rating for one region -- one of the 105 matrix cells."""

    code: str = Field(pattern=CRITERION_CODE_PATTERN)
    sector: str
    category: Pillar
    criterion: str
    region: Region
    rating: Rating
    confidence: Confidence
    evidence: str = Field(description="The prose justification for this rating, with the figures it rests on.")
    source: str = Field(description="Free-text source attribution as recorded by the analyst; not a registry key.")
    last_verified: str = Field(description="ISO date this cell was last checked against its sources. Drives staleness, not confidence.")


class RegistrySource(BaseModel):
    """One of the 86 deduplicated sources behind the matrix. A derived view over
    the primary_sources[] entries in criteria_schema.json, which stays
    authoritative if the two ever disagree.
    """

    key: str = Field(description="The registry's internal identifier (the JSON object key).")
    source_name: str
    publisher: str
    used_by_criteria: list[str]
    access_pattern: AccessPattern
    refresh_cadence: str
    locator: str
    url: str | None = None


class MatrixCell(BaseModel):
    """A single sector x pillar x region cell, joined for display."""

    code: str
    region: Region
    rating: Rating
    confidence: Confidence
    stale: bool
    staleness_days: int


class StalenessReport(BaseModel):
    threshold_days: int
    as_of: str = Field(default_factory=now_iso)
    total: int
    stale: int
    fresh: int
    stale_codes: list[str]


class RefreshOutcome(StrEnum):
    """What a refresh check concluded about one criterion-region cell."""

    UNCHANGED = "unchanged"
    EVIDENCE_DRIFT = "evidence_drift"
    RATING_CHANGE_CANDIDATE = "rating_change_candidate"
    NOT_AUTOMATED = "not_automated"
    FETCH_FAILED = "fetch_failed"


# The only two outcomes that may be written back without human approval, and
# even then only the evidence text and last_verified date -- never the H/M/L
# rating. Defined once here; arp/transition_barrier/refresh/reconciler.py
# exposes it as is_auto_applicable().
_AUTO_APPLICABLE_OUTCOMES = frozenset({RefreshOutcome.UNCHANGED, RefreshOutcome.EVIDENCE_DRIFT})


class BarrierRefreshFinding(BaseModel):
    """The result of re-checking one cell against one source.

    A RATING_CHANGE_CANDIDATE is never applied to assessment_scores.json -- it
    is queued for human review. Only evidence text and last_verified may be
    written back automatically, and only when the rating is unchanged.
    """

    code: str = Field(pattern=CRITERION_CODE_PATTERN)
    region: Region
    source_key: str
    outcome: RefreshOutcome
    current_rating: Rating
    proposed_rating: Rating | None = Field(
        default=None,
        description="Set only for RATING_CHANGE_CANDIDATE. Advisory -- requires human approval before it lands.",
    )
    detail: str = Field(default="", description="Why this outcome, including the quote or version marker it rests on.")
    source_quote: str = Field(default="", description="Exact text from the source. Required before any value is written anywhere.")
    checked_at: str = Field(default_factory=now_iso)

    @property
    def needs_review(self) -> bool:
        """Whether this finding has to go in front of a human.

        The single definition of that rule: everything except an outcome that
        can be written back automatically. A fetch failure counts -- an
        unverifiable cell is not a verified one, and silently dropping it would
        let a stale rating pass as checked.
        """
        return self.outcome not in _AUTO_APPLICABLE_OUTCOMES
