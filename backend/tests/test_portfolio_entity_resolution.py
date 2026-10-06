from arp.portfolio.entity_resolution import SecurityMaster, resolve_all, resolve_security
from arp.schemas.portfolio import SecurityRef

MASTER = SecurityMaster(isin_to_company_id={"DE001": "bmw"})


def test_exact_isin_match():
    security = SecurityRef(security_id="s1", isin="DE001", name="BMW AG", asset_class="equity", currency="EUR")
    resolution = resolve_security(security, MASTER)
    assert (resolution.company_id, resolution.confidence, resolution.method, resolution.needs_review) == ("bmw", 1.0, "isin_exact", False)


def test_unknown_isin_is_unresolved_never_matched_by_name():
    security = SecurityRef(security_id="s2", isin="ZZ999", name="BMW AG", asset_class="equity", currency="EUR")
    resolution = resolve_security(security, MASTER)
    assert resolution.company_id is None and resolution.needs_review is True


def test_no_isin_is_unresolved():
    security = SecurityRef(security_id="s3", isin=None, name="BMW AG", asset_class="equity", currency="EUR")
    assert resolve_security(security, MASTER).company_id is None


def test_resolve_all_batches():
    securities = [SecurityRef(security_id="s1", isin="DE001", name="BMW AG", asset_class="equity", currency="EUR")]
    assert [r.company_id for r in resolve_all(securities, MASTER)] == ["bmw"]
