from arp.portfolio.climate.validation import cross_check_and_store
from arp.schemas.portfolio import DataPointObservation
from arp.storage.portfolio_store import PortfolioStore


def _obs(value, source):
    return DataPointObservation(company_id="bmw", field_id="f1", field_name="F1", value=value, source=source, observed_at="2026-01-01")


def test_flags_mismatch_beyond_tolerance(tmp_path):
    store = PortfolioStore(tmp_path)
    resolved = cross_check_and_store(store, _obs(100.0, "internal_api"), _obs(140.0, "extracted"), tolerance_pct=0.15)
    assert resolved.conflicting_sources is True
    assert resolved.conflicting_value == 140.0
    assert resolved.conflicting_source_label == "extracted"
    assert resolved.value == 100.0  # internal-API value is still the one used for computation


def test_no_flag_within_tolerance(tmp_path):
    store = PortfolioStore(tmp_path)
    resolved = cross_check_and_store(store, _obs(100.0, "internal_api"), _obs(105.0, "extracted"), tolerance_pct=0.15)
    assert resolved.conflicting_sources is False
    assert resolved.conflicting_value is None


def test_missing_extracted_returns_internal_unflagged(tmp_path):
    store = PortfolioStore(tmp_path)
    resolved = cross_check_and_store(store, _obs(100.0, "internal_api"), None)
    assert resolved.value == 100.0
    assert resolved.conflicting_sources is False


def test_missing_internal_falls_back_to_extracted(tmp_path):
    store = PortfolioStore(tmp_path)
    resolved = cross_check_and_store(store, None, _obs(75.0, "extracted"))
    assert resolved.value == 75.0
    assert resolved.source == "extracted"


def test_both_missing_returns_none(tmp_path):
    store = PortfolioStore(tmp_path)
    assert cross_check_and_store(store, None, None) is None


def test_persists_both_observations_for_audit(tmp_path):
    store = PortfolioStore(tmp_path)
    cross_check_and_store(store, _obs(100.0, "internal_api"), _obs(140.0, "extracted"), tolerance_pct=0.15)
    stored = store.load_observations("bmw", "f1")
    sources = sorted(o.source for o in stored)
    assert sources == ["extracted", "internal_api"]
