"""Showcase anti-goal (AC-158): none of the new actions edits or deletes a stored governance or alert event."""
import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_identifier_map, get_portfolio_store, get_reporting_store, settings_dep
from arp.api.main import app
from arp.portfolio.monitoring.evaluator import list_alerts
from arp.schemas.reporting import ReportManifest
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.reporting_store import ReportingStore
from tests.test_monthly_run import MONTH, _ids, _ready, settings, store  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures("pg")


def _log_lines(store) -> dict[str, list[str]]:  # noqa: F811
    paths = [store.governance_events_path(), *(store.alert_events_path(s) for s in store.list_all_alert_scope_ids())]
    return {str(p): p.read_text().splitlines(keepends=True) for p in paths if p.exists()}


def test_new_actions_only_append_to_the_logs(store, settings, tmp_path):  # noqa: F811
    reports = ReportingStore(tmp_path / "reports", tmp_path / "templates")
    reports.save_manifest(draft := ReportManifest(status="plan_ready"))
    app.dependency_overrides.update({
        get_portfolio_store: lambda: store, settings_dep: lambda: settings, get_reporting_store: lambda: reports,
        get_identifier_map: lambda: IdentifierMapStore(tmp_path / "idmap.jsonl"),
    })
    try:
        client = TestClient(app)
        _ready(store)
        assert client.post("/api/portfolio/monitoring/evaluate-now").status_code == 200  # alert events to protect
        rule = store.list_rules()[0]
        assert [a for a in list_alerts(store) if a.rule_id == rule.rule_id]
        before = _log_lines(store)
        assert len(before) > 1 and all(before.values())

        rejected = client.post("/api/holdings/upload", files={"file": ("h.csv", b"ISIN\nUS0378331005\n", "text/csv")},
                               data={"holder_id": _ids(store)[0], "kind": "portfolio", "as_of": "2026-08-31"})  # another month: must not block the run
        assert rejected.status_code == 422
        assert client.post("/api/portfolio/monthly-run", json={"month": MONTH}).json()["status"] == "ran"
        cleared = client.post(f"/api/portfolio/monitoring/rules/{rule.rule_id}/clear-alerts", json={"status": "resolved"})
        assert cleared.json()["cleared"] > 0
        assert client.delete(f"/api/portfolio/monitoring/rules/{rule.rule_id}").status_code == 204
        assert client.delete(f"/api/reports/{draft.report_id}").status_code == 204
    finally:
        for dep in (get_portfolio_store, settings_dep, get_reporting_store, get_identifier_map):
            app.dependency_overrides.pop(dep, None)

    after = _log_lines(store)
    for path, lines in before.items():
        assert after[path][: len(lines)] == lines, path  # byte for byte, in the same order
    assert sum(map(len, after.values())) > sum(map(len, before.values()))  # and the actions did write
