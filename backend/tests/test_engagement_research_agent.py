from arp.engagement.research_agent import ResearchDossierDraft, research_company_issue
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.engagement import EngagementIssue, EngagementRecord, TriggerSource


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


async def test_research_company_issue_grounded_citation_not_flagged(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="C1",
        doc_type=DocType.SUSTAINABILITY_REPORT,
        title="ESG report",
        full_text="Our climate transition plan targets net zero by 2040 across our operations.",
    )
    company = CompanyRef(company_id="C1", name="Acme Corp")
    issue = EngagementIssue(theme="climate", source=TriggerSource.MANUAL)
    record = EngagementRecord(company_id="C1", name="Acme Corp")

    draft = ResearchDossierDraft(
        summary="The company discloses a net-zero-by-2040 transition plan.",
        controversy_context="No open controversy identified.",
        peer_benchmark_notes="In line with sector peers.",
        recommended_contacts=[],
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="climate transition plan targets net zero by 2040")],
        confidence=0.9,
    )
    llm = fake_llm({"ResearchDossierDraft": [draft]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    dossier, needs_review, _usage = await research_company_issue(
        company, issue, record, registry=registry, llm=llm, fuzzy_threshold=0.92, confidence_review_threshold=0.6
    )

    assert dossier.citations[0].grounded is True
    assert needs_review is False
    assert dossier.confidence == 0.9


async def test_research_company_issue_ungrounded_citation_flags_review(tmp_path, fake_llm):
    doc = SourceDocument(company_id="C1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG report", full_text="We sell shoes.")
    company = CompanyRef(company_id="C1", name="Shoe Co")
    issue = EngagementIssue(theme="climate", source=TriggerSource.MANUAL)
    record = EngagementRecord(company_id="C1", name="Shoe Co")

    draft = ResearchDossierDraft(
        summary="Fabricated summary.",
        controversy_context="None.",
        peer_benchmark_notes="None.",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="a quote that does not appear anywhere in the source")],
        confidence=0.9,
    )
    llm = fake_llm({"ResearchDossierDraft": [draft]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    dossier, needs_review, _usage = await research_company_issue(
        company, issue, record, registry=registry, llm=llm, fuzzy_threshold=0.92, confidence_review_threshold=0.6
    )

    assert dossier.citations[0].grounded is False
    assert needs_review is True
