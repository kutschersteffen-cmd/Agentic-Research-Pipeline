from arp.config import Settings
from arp.extraction.field_graph import field_evidence
from arp.retrieval.keywords_de import GLOSSARY, with_german
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition


def test_keywords_come_first_then_their_german_terms_once():
    out = with_german(["remuneration report", "annual bonus", "Annual Bonus"])
    assert out[:3] == ["remuneration report", "annual bonus", "Annual Bonus"]
    assert {"Vergütungsbericht", "Jahresbonus", "Tantieme"} <= set(out)
    assert len(out) == len(set(out))


def test_keys_match_whole_words_only():
    assert with_german(["greenhouse"]) == ["greenhouse"]  # not "green"
    assert "taxonomiefähig" not in with_german(["ineligible"])
    assert with_german(["xyz"]) == ["xyz"]
    assert with_german([]) == []


def test_every_glossary_key_is_lowercase_and_has_terms():
    assert all(k == k.lower() and terms for k, terms in GLOSSARY.items())


_DE = SourceDocument(
    company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="Geschäftsbericht",
    full_text="Lagebericht.\n\nDer Vergütungsbericht zeigt den Jahresbonus des Vorstands: 40 % hängen an ESG-Zielen.",
)


def test_a_german_report_now_yields_evidence_for_an_english_keyword_field():
    field = FieldDefinition(
        name="bonus", description="d", data_type=FieldDataType.STRING, extraction_instructions="look",
        seed_keywords=["remuneration report", "annual bonus"],  # low-risk: no unranked fallback
    )
    evidence = field_evidence(field, [_DE], Settings(hybrid_retrieval_enabled=False))
    assert evidence and "Jahresbonus" in evidence[0].text
    assert "Vergütungsbericht" in evidence[0].keyword_hits
