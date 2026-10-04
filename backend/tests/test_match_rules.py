from arp.discovery.match_rules import MatchRule, apply_identifier_rules, identifiers_of, needs_recheck
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import IdentityResolutionResult, IdentitySignals, IdentityVerdict
from arp.schemas.issuer import IdentifierMap
from arp.storage.identifier_map import IdentifierMapStore

LEI_X = "5493001KJTIIGC8Y1R12"


def test_expired_mapping_ignored(tmp_path):
    store = IdentifierMapStore(tmp_path / "map.jsonl")
    store.add(IdentifierMap(issuer_key=LEI_X, scheme="CIK", value="1", valid_to="2020-01-01"))
    store.add(IdentifierMap(issuer_key="B", scheme="CIK", value="1", valid_from="2020-01-01", valid_to="2020-06-01"))

    assert store.resolve("CIK", "0001") == []
    assert store.resolve("CIK", "1", on="2019-12-31") == [LEI_X]
    assert store.resolve("CIK", "1", on="2020-01-01") == ["B"]  # valid_to is exclusive
    assert apply_identifier_rules(CompanyRef(company_id="c", name="C", cik="1"), store).rule == MatchRule.SUPPLIED


def test_missing_map_file_is_empty_and_isin_normalised(tmp_path):
    store = IdentifierMapStore(tmp_path / "none.jsonl")
    assert store.resolve("ISIN", "us0378331005") == []
    store.add(IdentifierMap(issuer_key=LEI_X, scheme="ISIN", value="US0378331005"))
    assert store.resolve("ISIN", "us03783 31005") == [LEI_X]
    assert [r.issuer_key for r in store.rows_for(LEI_X)] == [LEI_X]
    assert identifiers_of(CompanyRef(company_id="c", name="C", isin=" us0378331005", cik="0012")) == {
        "cik": "12", "isin": "US0378331005"
    }


def test_no_identifiers_gives_no_outcome():
    assert apply_identifier_rules(CompanyRef(company_id="c", name="C"), None) is None


def test_old_identity_result_loads():
    row = {
        "company_id": "a", "input_name": "A", "verdict": "resolved", "confidence": 1.0,
        "signals": IdentitySignals().model_dump(), "rationale": "x",
    }
    result = IdentityResolutionResult.model_validate(row)
    assert result.match_rule == "" and result.identifiers == {} and result.reason_codes == []
    assert result.verdict == IdentityVerdict.RESOLVED


def test_isin_resolves_and_cik_is_tried_first(tmp_path):
    store = IdentifierMapStore(tmp_path / "map.jsonl")
    store.add(IdentifierMap(issuer_key="A", scheme="ISIN", value="US0378331005"))
    isin_only = CompanyRef(company_id="c", name="C", isin="US0378331005")
    assert apply_identifier_rules(isin_only, store).issuer_key == "A"

    store.add(IdentifierMap(issuer_key="B", scheme="CIK", value="7"))
    both = CompanyRef(company_id="c", name="C", cik="7", isin="US0378331005")
    out = apply_identifier_rules(both, store)
    assert (out.rule, out.issuer_key) == (MatchRule.IDENTIFIER_MAP, "B")


def test_legacy_result_always_needs_recheck():
    company = CompanyRef(company_id="a", name="A")
    legacy = IdentityResolutionResult(
        company_id="a", input_name="A", verdict=IdentityVerdict.RESOLVED, confidence=1.0,
        signals=IdentitySignals(), rationale="x",
    )
    assert needs_recheck(legacy, company, None) is True
