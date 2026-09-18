from arp.api.company_results import list_company_results, list_known_companies
from arp.schemas.common import JobStatus, RunManifest, now_iso
from arp.storage.run_store import RunStore


def _make_run(run_store: RunStore, run_id: str, run_type: str, created_at: str, rows: list[dict]) -> None:
    manifest = RunManifest(
        run_id=run_id, run_type=run_type, created_at=created_at, updated_at=created_at,
        status=JobStatus.COMPLETED, params={}, company_count=len(rows), completed_count=len(rows),
        failed_count=0, review_count=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
    )
    run_store.save_manifest(manifest)
    for row in rows:
        run_store.append_jsonl(run_store.results_path(run_id), row)


def test_list_company_results_filters_and_orders_newest_run_first(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    _make_run(run_store, "run_old", "extraction", "2025-01-01T00:00:00+00:00", [
        {"company_id": "acme", "name": "Acme", "fields": [{"field_name": "x", "value": 1}]},
        {"company_id": "beta", "name": "Beta", "fields": []},
    ])
    _make_run(run_store, "run_new", "extraction", "2025-06-01T00:00:00+00:00", [
        {"company_id": "acme", "name": "Acme", "fields": [{"field_name": "x", "value": 2}]},
    ])

    results = list_company_results(run_store, "extraction", "acme")

    assert len(results) == 2
    assert results[0]["fields"][0]["value"] == 2  # newest run first
    assert results[1]["fields"][0]["value"] == 1


def test_list_company_results_ignores_other_run_types_and_companies(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    _make_run(run_store, "run_a", "extraction", now_iso(), [{"company_id": "acme"}])
    _make_run(run_store, "run_b", "financials", now_iso(), [{"company_id": "acme"}])

    assert len(list_company_results(run_store, "extraction", "acme")) == 1
    assert len(list_company_results(run_store, "extraction", "nonexistent")) == 0


def test_list_known_companies_dedupes_and_prefers_latest_name(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    _make_run(run_store, "run_old", "extraction", "2025-01-01T00:00:00+00:00", [
        {"company_id": "acme", "name": "Acme Old Name", "ticker": "ACM"},
    ])
    _make_run(run_store, "run_new", "extraction", "2025-06-01T00:00:00+00:00", [
        {"company_id": "acme", "name": "Acme New Name", "ticker": "ACM"},
        {"company_id": "beta", "name": "Beta Corp", "ticker": None},
    ])

    companies = list_known_companies(run_store, "extraction")

    assert companies == [
        {"company_id": "acme", "name": "Acme New Name", "ticker": "ACM"},
        {"company_id": "beta", "name": "Beta Corp", "ticker": None},
    ]


def test_list_known_companies_empty_when_no_runs(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    assert list_known_companies(run_store, "extraction") == []
