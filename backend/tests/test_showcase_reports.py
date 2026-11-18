"""Showcase defect 2 (backend): an unfinished report can be discarded, a finished one never, and reports are
listed newest first."""
import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_reporting_store
from arp.api.main import app
from arp.schemas.reporting import ReportManifest
from arp.storage.reporting_store import ReportingStore


@pytest.fixture
def env(tmp_path):
    store = ReportingStore(tmp_path / "reports", tmp_path / "templates")
    app.dependency_overrides[get_reporting_store] = lambda: store
    yield TestClient(app), store
    app.dependency_overrides.pop(get_reporting_store, None)


def _saved(store, status, report_id=None) -> str:
    manifest = ReportManifest(status=status, **({"report_id": report_id} if report_id else {}))
    store.save_manifest(manifest)
    return manifest.report_id


def test_discard_removes_the_folder_and_an_unknown_id_creates_none(env):  # AC-90
    client, store = env
    rid = _saved(store, "plan_ready")
    assert client.delete(f"/api/reports/{rid}").status_code == 204
    assert not (store.reports_dir / rid).exists()
    assert client.delete("/api/reports/rpt_000000000000").status_code == 404
    assert not (store.reports_dir / "rpt_000000000000").exists()
    assert client.delete("/api/reports/..%2Fx").status_code in (404, 405)


def test_only_an_unfinished_report_can_be_discarded(env):  # AC-93
    client, store = env
    for status in ("storyline_ready", "failed"):
        assert client.delete(f"/api/reports/{_saved(store, status)}").status_code == 204
    for status in ("planning", "rendering", "pending", "completed"):
        rid = _saved(store, status)
        r = client.delete(f"/api/reports/{rid}")
        assert (r.status_code, r.json()["detail"]) == (409, f"Only an unfinished report can be discarded (status: {status}).")
        assert store.load_manifest(rid).status == status


def test_reports_are_listed_newest_first_by_created_at(env):  # AC-96
    client, store = env
    for rid, day in (("rpt_c00000000000", "01"), ("rpt_a00000000000", "03"), ("rpt_b00000000000", "02")):
        store.save_manifest(ReportManifest(report_id=rid, created_at=f"2026-11-{day}T10:00:00"))
    assert [m.created_at[:10] for m in store.list_reports()] == ["2026-11-03", "2026-11-02", "2026-11-01"]
    assert [m["report_id"] for m in client.get("/api/reports").json()["reports"]] == [
        "rpt_a00000000000", "rpt_b00000000000", "rpt_c00000000000"]


def test_viewer_may_not_discard(env):  # AC-97
    client, store = env
    rid = _saved(store, "plan_ready")
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_v", name="Vera", role="viewer")
    assert client.delete(f"/api/reports/{rid}").status_code == 403
    assert store.load_manifest(rid) is not None


def test_a_report_that_was_finished_once_cannot_be_discarded_after_a_failed_re_render(env):
    """Code review on PR #419: a failed re-render sets a completed report to `failed` and keeps its output
    (ReportingService.render_from_plan / _rerender); discarding it would delete the delivered file."""
    client, store = env
    manifest = ReportManifest(status="failed", output_filename="output.pptx", output_files=["output.pptx"], error="render broke")
    store.save_manifest(manifest)
    store.output_path(manifest.report_id, "output.pptx").write_bytes(b"delivered")
    r = client.delete(f"/api/reports/{manifest.report_id}")
    assert (r.status_code, r.json()["detail"]) == (409, "Only an unfinished report can be discarded (status: failed, with a finished output).")
    assert store.output_path(manifest.report_id, "output.pptx").read_bytes() == b"delivered"
