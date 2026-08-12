from arp.config import Settings
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.matcher_agents import AdjudicatorOutput
from arp.research.pipeline import _match_company
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
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
