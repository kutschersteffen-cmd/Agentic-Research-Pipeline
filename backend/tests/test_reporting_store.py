from arp.schemas.reporting import (
    AudienceProfile,
    ColumnKind,
    DatasetColumn,
    LayoutInstructions,
    QuantitativeDataset,
    ReportManifest,
    ReportPlan,
    ReportRequest,
    ReportSection,
    ReportStatus,
)
from arp.storage.reporting_store import ReportingStore


def _store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "templates")


def test_manifest_round_trip(tmp_path):
    store = _store(tmp_path)
    manifest = ReportManifest(title="A report", status=ReportStatus.PENDING)

    store.save_manifest(manifest)
    loaded = store.load_manifest(manifest.report_id)

    assert loaded.report_id == manifest.report_id
    assert loaded.title == "A report"
    assert loaded.status == ReportStatus.PENDING


def test_load_manifest_returns_none_when_missing(tmp_path):
    store = _store(tmp_path)
    assert store.load_manifest("rpt_does_not_exist") is None


def test_list_reports_returns_saved_manifests_newest_first(tmp_path):
    store = _store(tmp_path)
    m1 = ReportManifest(report_id="rpt_000000000001", title="first")
    m2 = ReportManifest(report_id="rpt_000000000002", title="second")
    store.save_manifest(m1)
    store.save_manifest(m2)

    reports = store.list_reports()

    assert {r.report_id for r in reports} == {m1.report_id, m2.report_id}


def test_request_and_plan_round_trip(tmp_path):
    store = _store(tmp_path)
    ds = QuantitativeDataset(name="ds", columns=[DatasetColumn(name="x", kind=ColumnKind.NUMBER)], rows=[{"x": 1}])
    request = ReportRequest(title="T", qualitative_notes="notes", datasets=[ds], audience=AudienceProfile(), layout=LayoutInstructions())
    plan = ReportPlan(title="T", sections=[ReportSection(heading="H")])

    store.save_request("rpt_1", request)
    store.save_plan("rpt_1", plan)

    assert store.load_request("rpt_1") == request
    assert store.load_plan("rpt_1") == plan
    assert store.load_plan("rpt_2") is None
