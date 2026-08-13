from arp.portfolio.entity_resolution import SecurityMaster, resolve_all, resolve_security
from arp.schemas.portfolio import SecurityRef


def test_exact_isin_match():
    master = SecurityMaster(isin_to_company_id={"DE001": "bmw"}, company_names={"bmw": "BMW AG"})
    security = SecurityRef(security_id="s1", isin="DE001", name="BMW AG", asset_class="equity", currency="EUR")
    resolution = resolve_security(security, master, 0.6)
    assert resolution.company_id == "bmw"
    assert resolution.confidence == 1.0
    assert resolution.method == "isin_exact"
    assert resolution.needs_review is False


def test_fuzzy_fallback_below_threshold_needs_review():
    master = SecurityMaster(isin_to_company_id={"DE001": "bmw"}, company_names={"bmw": "BMW AG"})
    security = SecurityRef(security_id="s2", isin="ZZ999", name="Totally Unrelated Basket Note", asset_class="other", currency="EUR")
    resolution = resolve_security(security, master, 0.6)
    assert resolution.method == "name_fuzzy"
    assert resolution.needs_review is True
    assert resolution.confidence < 0.6


def test_fuzzy_fallback_above_threshold_no_review():
    master = SecurityMaster(isin_to_company_id={}, company_names={"bmw": "Bayerische Motoren Werke AG"})
    security = SecurityRef(security_id="s3", isin=None, name="Bayerische Motoren Werke AG", asset_class="equity", currency="EUR")
    resolution = resolve_security(security, master, 0.6)
    assert resolution.company_id == "bmw"
    assert resolution.needs_review is False
    assert resolution.confidence == 1.0


def test_no_candidates_is_unresolved_and_needs_review():
    master = SecurityMaster(isin_to_company_id={}, company_names={})
    security = SecurityRef(security_id="s4", isin=None, name="Anything", asset_class="other", currency="EUR")
    resolution = resolve_security(security, master, 0.6)
    assert resolution.company_id is None
    assert resolution.needs_review is True


def test_resolve_all_batches():
    master = SecurityMaster(isin_to_company_id={"DE001": "bmw"}, company_names={"bmw": "BMW AG"})
    securities = [SecurityRef(security_id="s1", isin="DE001", name="BMW AG", asset_class="equity", currency="EUR")]
    resolutions = resolve_all(securities, master, 0.6)
    assert len(resolutions) == 1
    assert resolutions[0].company_id == "bmw"
