from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.indirect_exposure.icio_loader import load_sample_icio
from arp.research.indirect_exposure.leontief import build_model
from arp.research.matcher_agents import AdjudicatorOutput
from arp.research.pipeline import _match_company
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.revenue_exposure import ActivityCatalogueMapping, CatalogueDataPoint
from arp.schemas.thematic import ActivityDefinition, AgentOpinion, ExposureEstimate, MatchVerdict, ThemeDefinition


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
    )


def _theme() -> tuple[ThemeDefinition, ActivityDefinition]:
    activity = ActivityDefinition(
        name="EV manufacturing",
        in_scope_description="Designs/manufactures battery electric vehicles.",
        out_of_scope_description="Traditional ICE-only vehicle manufacturing.",
        seed_keywords=["electric vehicle", "battery electric"],
    )
    return ThemeDefinition(name="Electrification", description="", activities=[activity]), activity


async def test_match_company_include_with_grounded_citation(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1",
        doc_type=DocType.ANNUAL_REPORT_10K,
        title="10-K",
        full_text="We are a leading manufacturer of battery electric vehicles for the mass market.",
    )
    theme, _activity = _theme()
    company = CompanyRef(company_id="c1", name="Acme Motors", ticker="ACME")

    good_quote = "leading manufacturer of battery electric vehicles"
    advocate = AgentOpinion(
        stance="include",
        rationale="Core business is BEV manufacturing.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=good_quote)],
        exposure_estimate=ExposureEstimate.PURE_PLAY,
    )
    opposing = AgentOpinion(
        stance="no strong counter-argument",
        rationale="Evidence is credible and specific.",
        citations=[],
        exposure_estimate=ExposureEstimate.PURE_PLAY,
    )
    adjudication = AdjudicatorOutput(
        verdict=MatchVerdict.INCLUDE,
        exposure_estimate=ExposureEstimate.PURE_PLAY,
        confidence=0.95,
        adjudicator_rationale="Clear, specific, grounded evidence of BEV manufacturing as the core business.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=good_quote)],
    )

    llm = fake_llm({"AgentOpinion": [advocate, opposing], "AdjudicatorOutput": [adjudication]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _match_company(company, theme, registry=registry, llm=llm, settings=_settings(tmp_path))
    match = result.matches[0]
    assert match.verdict == MatchVerdict.INCLUDE
    assert match.citations[0].grounded is True
    assert match.flagged_for_review is False


async def test_match_company_hallucinated_citation_flags_for_review(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1",
        doc_type=DocType.ANNUAL_REPORT_10K,
        title="10-K",
        full_text="We are a leading manufacturer of battery electric vehicles.",
    )
    theme, _activity = _theme()
    company = CompanyRef(company_id="c1", name="Acme Motors", ticker="ACME")

    fabricated_quote = "we generated $4 billion in EV revenue last year"  # not present in the source text
    advocate = AgentOpinion(
        stance="include",
        rationale="Strong EV revenue.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=fabricated_quote)],
        exposure_estimate=ExposureEstimate.PURE_PLAY,
    )
    opposing = AgentOpinion(
        stance="no counter", rationale="n/a", citations=[], exposure_estimate=ExposureEstimate.NONE
    )
    adjudication = AdjudicatorOutput(
        verdict=MatchVerdict.INCLUDE,
        exposure_estimate=ExposureEstimate.PURE_PLAY,
        confidence=0.9,
        adjudicator_rationale="Advocate cited strong revenue figures.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=fabricated_quote)],
    )

    llm = fake_llm({"AgentOpinion": [advocate, opposing], "AdjudicatorOutput": [adjudication]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _match_company(company, theme, registry=registry, llm=llm, settings=_settings(tmp_path))
    match = result.matches[0]
    assert match.citations[0].grounded is False
    assert match.flagged_for_review is True  # ungrounded citation on an "include" verdict must be caught


async def test_match_company_no_evidence_skips_llm_calls_entirely(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    theme, _activity = _theme()
    company = CompanyRef(company_id="c1", name="Shoe Co", ticker="SHOE")

    llm = fake_llm({})  # no scripted responses -- the pipeline must not call the LLM at all
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _match_company(company, theme, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.matches[0].verdict == MatchVerdict.EXCLUDE
    assert llm.calls == []


async def test_match_company_no_evidence_with_high_structural_exposure_is_flagged(tmp_path, fake_llm):
    """No direct textual evidence, but the company's own industry IS the
    theme's core sector -- indirect exposure should be high and the
    no-evidence auto-exclude should be upgraded to a review flag instead
    of a flat, unreviewed exclude."""
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    theme, activity = _theme()
    activity.core_isic_codes = ["27"]
    company = CompanyRef(company_id="c1", name="Acme Electricals", ticker="ACME", isic_code="27")

    llm = fake_llm({})  # company_isic is supplied and matches the model, so no LLM call should occur
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])
    model = build_model(load_sample_icio(), "test-sample")

    result = await _match_company(
        company, theme, registry=registry, llm=llm, settings=_settings(tmp_path), indirect_model=model
    )
    match = result.matches[0]
    assert match.verdict == MatchVerdict.EXCLUDE
    assert match.indirect_exposure is not None
    assert match.indirect_exposure.core_sector is True
    assert match.flagged_for_review is True
    assert llm.calls == []


async def test_match_company_no_evidence_with_low_structural_exposure_not_flagged(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    theme, activity = _theme()
    activity.core_isic_codes = ["27"]
    # retail/trade (45) has low structural linkage to electrical equipment (27) in the sample model
    company = CompanyRef(company_id="c1", name="Acme Retail", ticker="ACME", isic_code="45")

    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])
    model = build_model(load_sample_icio(), "test-sample")

    result = await _match_company(
        company, theme, registry=registry, llm=llm, settings=_settings(tmp_path), indirect_model=model
    )
    match = result.matches[0]
    assert match.indirect_exposure is not None
    assert match.flagged_for_review is False
    assert match.confidence == 1.0


async def test_match_company_catalogue_hit_skips_qualitative_debate_entirely(tmp_path, fake_llm):
    theme, activity = _theme()
    company = CompanyRef(company_id="c1", name="Acme Motors", ticker="ACME")
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    catalogue_rows = [CatalogueDataPoint(data_point_id="d1", company_id="c1", metric="revenue", label="EV Sales", as_pct_of_total=0.4)]
    mappings = [ActivityCatalogueMapping(activity_id=activity.activity_id, metric="revenue", matched_labels=["EV Sales"], rationale="x")]
    revenue_resolver = RevenueResolverContext(catalogue_by_company={"c1": catalogue_rows}, mappings=mappings, registry=registry, settings=_settings(tmp_path))

    llm = fake_llm({})  # catalogue alone resolves it -- zero LLM calls (no debate, no extraction)
    result = await _match_company(
        company, theme, registry=registry, llm=llm, settings=_settings(tmp_path), revenue_resolver=revenue_resolver
    )
    match = result.matches[0]
    assert match.advocate is None
    assert match.opposing is None
    assert match.revenue_exposure is not None
    assert match.revenue_exposure.revenue.source == "catalogue"
    assert match.revenue_exposure.revenue.value_pct == 0.4
    assert match.exposure_estimate == ExposureEstimate.SIGNIFICANT
    assert match.verdict == MatchVerdict.INCLUDE
    assert llm.calls == []


async def test_match_company_extraction_hit_skips_qualitative_debate(tmp_path, fake_llm):
    theme, activity = _theme()
    company = CompanyRef(company_id="c1", name="Acme Motors", ticker="ACME")
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K",
        full_text="Approximately 22% of our total revenue came from battery electric vehicle sales in fiscal 2025.",
    )
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    quote = "Approximately 22% of our total revenue came from battery electric vehicle sales"
    revenue_draft = ExtractionDraft(value=22.0, raw_value_text=quote, citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], confidence=0.9)
    revenue_verifier = VerifierOutput(agrees=True, confidence=0.85, notes="Matches evidence.")
    no_value_draft = ExtractionDraft(value=None, confidence=0.0, citations=[])
    no_value_verifier = VerifierOutput(agrees=True, confidence=0.0, notes="")

    revenue_resolver = RevenueResolverContext(catalogue_by_company={}, mappings=[], registry=registry, settings=_settings(tmp_path))
    llm = fake_llm({
        "ExtractionDraft": [revenue_draft, no_value_draft],  # revenue hit, capex miss
        "VerifierOutput": [revenue_verifier, no_value_verifier],
    })

    result = await _match_company(
        company, theme, registry=registry, llm=llm, settings=_settings(tmp_path), revenue_resolver=revenue_resolver
    )
    match = result.matches[0]
    assert match.advocate is None
    assert match.revenue_exposure.revenue.source == "extracted"
    assert match.revenue_exposure.revenue.value_pct == 0.22
    assert match.revenue_exposure.capex.source == "unresolved"
    assert match.exposure_estimate == ExposureEstimate.SIGNIFICANT


async def test_match_company_revenue_unresolved_falls_through_to_qualitative_debate(tmp_path, fake_llm):
    theme, activity = _theme()
    company = CompanyRef(company_id="c1", name="Acme Motors", ticker="ACME")
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K",
        full_text="We are a leading manufacturer of battery electric vehicles.",
    )
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    no_value_draft = ExtractionDraft(value=None, confidence=0.0, citations=[])
    no_value_verifier = VerifierOutput(agrees=True, confidence=0.0, notes="")

    good_quote = "leading manufacturer of battery electric vehicles"
    advocate = AgentOpinion(
        stance="include", rationale="Core business is BEV manufacturing.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=good_quote)], exposure_estimate=ExposureEstimate.PURE_PLAY,
    )
    opposing = AgentOpinion(stance="no strong counter", rationale="Evidence is credible.", citations=[], exposure_estimate=ExposureEstimate.PURE_PLAY)
    adjudication = AdjudicatorOutput(
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.PURE_PLAY, confidence=0.9,
        adjudicator_rationale="Clear, specific evidence.", citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=good_quote)],
    )

    revenue_resolver = RevenueResolverContext(catalogue_by_company={}, mappings=[], registry=registry, settings=_settings(tmp_path))
    llm = fake_llm({
        "ExtractionDraft": [no_value_draft, no_value_draft],  # revenue miss, capex miss
        "VerifierOutput": [no_value_verifier, no_value_verifier],
        "AgentOpinion": [advocate, opposing],
        "AdjudicatorOutput": [adjudication],
    })

    result = await _match_company(
        company, theme, registry=registry, llm=llm, settings=_settings(tmp_path), revenue_resolver=revenue_resolver
    )
    match = result.matches[0]
    assert match.advocate is not None  # fell through to path 3, the qualitative debate ran
    assert match.revenue_exposure is not None
    assert match.revenue_exposure.revenue.source == "unresolved"
    assert match.verdict == MatchVerdict.INCLUDE
