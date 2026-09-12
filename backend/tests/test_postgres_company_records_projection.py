"""Pure-logic unit tests for the results.jsonl -> CompanyRecordModel
mapping -- no real Postgres instance required. The DB-write half
(sync_run/sync_all) needs a real instance and is covered separately,
gated on ARP_TEST_POSTGRES_DSN, mirroring test_postgres_portfolio_store.py."""

from __future__ import annotations

from arp.schemas.common import RunManifest
from arp.storage.postgres_company_records_projection import row_to_record_kwargs


def _manifest(run_type="extraction", run_id="run_1", updated_at="2026-01-01T00:00:00Z") -> RunManifest:
    return RunManifest(run_id=run_id, run_type=run_type, updated_at=updated_at)


def test_row_without_key_returns_none():
    assert row_to_record_kwargs(_manifest(), {"foo": "bar"}) is None


def test_row_with_key_maps_correctly():
    manifest = _manifest(run_type="extraction", run_id="run_1")
    row = {"_key": "acme", "needs_review": True, "overall_confidence": 0.4, "field_id": "scope_1_emissions"}

    kwargs = row_to_record_kwargs(manifest, row)

    assert kwargs == {
        "run_id": "run_1",
        "run_type": "extraction",
        "company_id": "acme",
        "record_key": "",
        "overall_confidence": 0.4,
        "needs_review": True,
        "generated_at": "2026-01-01T00:00:00Z",
        "payload": row,
    }


def test_missing_confidence_and_needs_review_default_to_none():
    kwargs = row_to_record_kwargs(_manifest(), {"_key": "acme"})
    assert kwargs["overall_confidence"] is None
    assert kwargs["needs_review"] is None


def test_confidence_field_name_falls_back():
    """Some pipelines may use `confidence` instead of `overall_confidence`
    -- either is accepted opportunistically."""
    kwargs = row_to_record_kwargs(_manifest(), {"_key": "acme", "confidence": 0.9})
    assert kwargs["overall_confidence"] == 0.9
