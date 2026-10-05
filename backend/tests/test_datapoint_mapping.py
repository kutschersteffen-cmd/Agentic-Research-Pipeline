from arp.portfolio import datapoint_mapping
from arp.schemas.portfolio import DataPointObservation
from arp.storage.portfolio_store import PortfolioStore


def _obs(value, source, observed_at):
    return DataPointObservation(company_id="bmw", field_id="f1", field_name="F1", value=value, source=source, observed_at=observed_at)


def test_priority_prefers_internal_api_even_if_older(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_observation(_obs(10.0, "internal_api", "2026-01-01"))
    store.append_observation(_obs(99.0, "extracted", "2026-06-01"))
    resolved = datapoint_mapping.resolve_field_value(store, "bmw", "f1")
    assert resolved.value == 10.0
    assert resolved.source == "internal_api"


def test_falls_back_to_extracted_when_no_internal_api(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_observation(_obs(42.0, "extracted", "2026-01-01"))
    resolved = datapoint_mapping.resolve_field_value(store, "bmw", "f1")
    assert resolved.value == 42.0
    assert resolved.source == "extracted"


def test_as_of_excludes_future_observations(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_observation(_obs(10.0, "internal_api", "2026-01-01"))
    store.append_observation(_obs(20.0, "internal_api", "2026-06-01"))
    resolved = datapoint_mapping.resolve_field_value(store, "bmw", "f1", as_of="2026-03-01")
    assert resolved.value == 10.0


def test_no_observations_returns_none(tmp_path):
    store = PortfolioStore(tmp_path)
    assert datapoint_mapping.resolve_field_value(store, "bmw", "f1") is None


def test_resolve_field_values_for_universe_only_includes_numeric(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_observation(_obs(10.0, "internal_api", "2026-01-01"))
    values = datapoint_mapping.resolve_field_values_for_universe(store, ["bmw", "sap"], "f1")
    assert values == {"bmw": 10.0}


def test_coverage_summary_counts_missing(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_observation(_obs(10.0, "internal_api", "2026-01-01"))
    counts = datapoint_mapping.coverage_summary(store, ["bmw", "sap"], "f1")
    assert counts["internal_api"] == 1
    assert counts["missing"] == 1
