from arp.emerging_themes.entity_resolution import resolve_entity_name, resolve_mention_companies
from arp.schemas.common import CompanyRef


def _universe() -> list[CompanyRef]:
    return [
        CompanyRef(company_id="acme", name="Acme Battery Co", ticker="ACME"),
        CompanyRef(company_id="globex", name="Globex Corporation", ticker="GLBX"),
    ]


def test_exact_name_match():
    result = resolve_entity_name("Acme Battery Co", _universe())
    assert result.company_id == "acme"
    assert result.method == "exact"
    assert result.confidence == 1.0


def test_exact_ticker_match():
    result = resolve_entity_name("GLBX", _universe())
    assert result.company_id == "globex"
    assert result.method == "exact"


def test_close_fuzzy_match_above_threshold():
    result = resolve_entity_name("Acme Battery Company", _universe(), confidence_threshold=0.75)
    assert result.company_id == "acme"
    assert result.method == "fuzzy"
    assert result.confidence >= 0.75


def test_unrelated_name_stays_unresolved_not_guessed():
    result = resolve_entity_name("A completely unrelated business entity", _universe(), confidence_threshold=0.75)
    assert result.company_id is None
    assert result.method == "unresolved"


def test_resolve_mention_companies_dedupes_and_drops_unresolved():
    company_ids = resolve_mention_companies(
        ["Acme Battery Co", "Acme Battery Co", "nonsense unrelated text"], _universe()
    )
    assert company_ids == ["acme"]
