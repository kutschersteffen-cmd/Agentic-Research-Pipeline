from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.revenue_exposure.resolver import (
    RevenueResolverContext,
    band_exposure,
    is_sector_relevant,
    resolve_company_activity_exposure,
    resolve_from_catalogue,
    resolve_from_extraction,
)
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.revenue_exposure import ActivityCatalogueMapping, CatalogueDataPoint
from arp.schemas.thematic import ActivityDefinition, ExposureEstimate


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


def _activity(core_isic_codes=None) -> ActivityDefinition:
    return ActivityDefinition(
        name="EV manufacturing", in_scope_description="Battery electric vehicle assembly.", out_of_scope_description="",
        seed_keywords=["electric vehicle", "battery electric"], core_isic_codes=core_isic_codes or [],
    )


# --- is_sector_relevant / band_exposure -------------------------------------

def test_is_sector_relevant_exact_and_prefix_match():
    assert is_sector_relevant("29", ["29"]) is True
    assert is_sector_relevant("2910", ["29"]) is True
    assert is_sector_relevant("29", ["2910"]) is True


def test_is_sector_relevant_no_match():
    assert is_sector_relevant("30", ["29"]) is False


def test_is_sector_relevant_defaults_true_when_undetermined():
    assert is_sector_relevant(None, ["29"]) is True
    assert is_sector_relevant("30", []) is True


def test_band_exposure_thresholds(tmp_path):
    settings = _settings(tmp_path)
    assert band_exposure(0.6, settings) == ExposureEstimate.PURE_PLAY
    assert band_exposure(0.3, settings) == ExposureEstimate.SIGNIFICANT
    assert band_exposure(0.1, settings) == ExposureEstimate.MINOR
    assert band_exposure(0.01, settings) == ExposureEstimate.NONE


# --- resolve_from_catalogue --------------------------------------------------

def test_resolve_from_catalogue_direct_pct():
    rows = [CatalogueDataPoint(data_point_id="d1", company_id="c1", metric="revenue", label="EV Sales", as_pct_of_total=0.4)]
    mappings = [ActivityCatalogueMapping(activity_id="act1", metric="revenue", matched_labels=["EV Sales"], rationale="x")]
    result = resolve_from_catalogue("act1", "revenue", rows, mappings)
    assert result.value_pct == 0.4
    assert result.source == "catalogue"


def test_resolve_from_catalogue_computed_from_total():
    rows = [
        CatalogueDataPoint(data_point_id="d0", company_id="c1", metric="revenue", label="Total Revenue", value=1000.0),
        CatalogueDataPoint(data_point_id="d1", company_id="c1", metric="revenue", label="EV Sales", value=250.0),
    ]
    mappings = [ActivityCatalogueMapping(activity_id="act1", metric="revenue", matched_labels=["EV Sales"], rationale="x")]
    result = resolve_from_catalogue("act1", "revenue", rows, mappings)
    assert result.value_pct == 0.25


def test_resolve_from_catalogue_no_mapping_is_unresolved():
    rows = [CatalogueDataPoint(data_point_id="d1", company_id="c1", metric="revenue", label="EV Sales", as_pct_of_total=0.4)]
    result = resolve_from_catalogue("act1", "revenue", rows, mappings=[])
    assert result.source == "unresolved"
    assert result.value_pct is None


def test_resolve_from_catalogue_mapped_label_absent_from_rows_is_unresolved():
    mappings = [ActivityCatalogueMapping(activity_id="act1", metric="revenue", matched_labels=["Nonexistent"], rationale="x")]
    result = resolve_from_catalogue("act1", "revenue", company_rows=[], mappings=mappings)
    assert result.source == "unresolved"


# --- resolve_from_extraction --------------------------------------------------

async def test_resolve_from_extraction_finds_explicit_percentage(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Motors")
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K",
        full_text="Approximately 22% of our total revenue came from battery electric vehicle sales in fiscal 2025.",
    )
    quote = "Approximately 22% of our total revenue came from battery electric vehicle sales"
    draft = ExtractionDraft(value=22.0, raw_value_text=quote, citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], confidence=0.9)
    verifier = VerifierOutput(agrees=True, confidence=0.85, notes="Matches evidence.")
    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result, usage = await resolve_from_extraction(company, _activity(), "revenue", documents=[doc], registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.source == "extracted"
    assert result.value_pct == 0.22
    assert result.citation is not None and result.citation.grounded is True
    assert usage.input_tokens > 0


async def test_resolve_from_extraction_no_evidence_is_unresolved_without_llm_call(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Shoe Co")
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result, _usage = await resolve_from_extraction(company, _activity(), "revenue", documents=[doc], registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.source == "unresolved"
    assert llm.calls == []


# --- resolve_company_activity_exposure (orchestration) -----------------------

async def test_catalogue_hit_short_circuits_extraction(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Motors")
    activity = _activity()
    catalogue_rows = [CatalogueDataPoint(data_point_id="d1", company_id="c1", metric="revenue", label="EV Sales", as_pct_of_total=0.4)]
    mappings = [ActivityCatalogueMapping(activity_id=activity.activity_id, metric="revenue", matched_labels=["EV Sales"], rationale="x")]
    registry = DocumentSourceRegistry([_FixedDocSource([])])
    ctx = RevenueResolverContext(catalogue_by_company={"c1": catalogue_rows}, mappings=mappings, registry=registry, settings=_settings(tmp_path))

    llm = fake_llm({})  # no extraction/LLM calls expected for revenue (catalogue hit); capex has no mapping either
    result, _usage = await resolve_company_activity_exposure(company, activity, company_isic=None, documents=[], ctx=ctx, llm=llm)
    assert result.revenue.source == "catalogue"
    assert result.revenue.value_pct == 0.4
    assert llm.calls == []


async def test_irrelevant_sector_skips_extraction(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Retail")
    activity = _activity(core_isic_codes=["29"])  # motor vehicles
    registry = DocumentSourceRegistry([_FixedDocSource([])])
    ctx = RevenueResolverContext(catalogue_by_company={}, mappings=[], registry=registry, settings=_settings(tmp_path))

    llm = fake_llm({})  # company_isic="45" (retail) doesn't overlap "29" -- extraction must be skipped
    result, _usage = await resolve_company_activity_exposure(company, activity, company_isic="45", documents=[], ctx=ctx, llm=llm)
    assert result.sector_relevant is False
    assert result.revenue.source == "unresolved"
    assert llm.calls == []
