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


def test_list_conflicting_observations_finds_flag_despite_append_order(tmp_path):
    # cross_check_and_store always appends the (possibly-flagged) internal_api
    # observation BEFORE the raw extracted one -- so the flagged row is never
    # the last one written for this (company, field). A naive "last row wins"
    # read would miss it entirely; this must go through the same
    # source-priority cascade every other resolution uses.
    store = PortfolioStore(tmp_path)
    flagged = DataPointObservation(
        company_id="bmw", field_id="f1", field_name="F1", value=100.0, source="internal_api",
        observed_at="2026-01-01", conflicting_sources=True, conflicting_value=140.0, conflicting_source_label="extracted",
    )
    store.append_observation(flagged)
    store.append_observation(_obs(140.0, "extracted", "2026-01-01"))

    conflicts = datapoint_mapping.list_conflicting_observations(store)

    assert len(conflicts) == 1
    assert conflicts[0].company_id == "bmw"
    assert conflicts[0].field_id == "f1"
    assert conflicts[0].value == 100.0


def test_list_conflicting_observations_excludes_unflagged(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_observation(_obs(10.0, "internal_api", "2026-01-01"))
    assert datapoint_mapping.list_conflicting_observations(store) == []
