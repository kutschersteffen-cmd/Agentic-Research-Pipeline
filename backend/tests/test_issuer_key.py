from arp.extraction.pipeline import _extract_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.issuer import issuer_key
from tests.test_extraction_pipeline import _FixedDocSource, _schema, _settings

LEI = "5493001KJTIIGC8Y1R12"


def test_valid_lei_accepted():
    assert issuer_key(CompanyRef(company_id="c1", name="A", lei=LEI)) == (LEI, "LEI")


def test_lowercase_and_spaces_normalised():
    spaced = "5493 001k jtii gc8y 1r12"
    assert issuer_key(CompanyRef(company_id="c1", name="A", lei=spaced)) == (LEI, "LEI")


def test_bad_check_digits_falls_back_to_provisional():
    key, scheme = issuer_key(CompanyRef(company_id="c1", name="A", lei="5493001KJTIIGC8Y1R13"))
    assert scheme == "ARP_PROVISIONAL" and key.startswith("ARP:")


def test_provisional_key_is_stable():
    a = issuer_key(CompanyRef(company_id="c1", name="A"))
    assert a == issuer_key(CompanyRef(company_id="c1", name="B")) != issuer_key(CompanyRef(company_id="c2", name="A"))


async def test_extraction_record_carries_issuer_key(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="We sell shoes.")
    company = CompanyRef(company_id="c1", name="Shoe Co", lei=LEI)
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])
    result = await _extract_company(company, _schema(), registry=registry, llm=fake_llm({}), settings=_settings(tmp_path))
    assert (result.record.issuer_key, result.record.issuer_scheme) == (LEI, "LEI")
