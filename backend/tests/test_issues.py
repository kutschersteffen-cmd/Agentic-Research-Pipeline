from __future__ import annotations

import json
from datetime import date

from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import append_decision
from arp.portfolio import issues
from arp.schemas.review import ReviewDecision
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore


def _run(rs: RunStore, checks: list[dict], *, issuer="ISS-1", field="scope1", trial=False) -> str:
    run_id = JobManager(rs).create_run("extraction", {"trial": True} if trial else {}, 1).run_id
    row = {"company_id": "c1", "name": "Acme", "issuer_key": issuer,
           "fields": [{"field_id": field, "period_end": "2025-12-31", "value": 1.0, "checks": checks}]}
    rs._results_path(run_id).write_text(json.dumps(row) + "\n")
    return run_id


FAIL_WARN = {"check_id": "plausibility.range", "layer": 3, "outcome": "fail", "severity": "warn", "detail": "above max"}


def env(tmp_path):
    return PortfolioStore(tmp_path / "pf"), IdentifierMapStore(tmp_path / "idmap.jsonl"), RunStore(tmp_path / "runs")


def checks_only(tmp_path, store, idmap, rs):
    return [i for i in issues.open_issues(store, idmap, rs, date(2026, 10, 15)) if i["source"] == "check"]


def test_an_undecided_failing_check_is_an_issue_linked_to_its_run(tmp_path):
    store, idmap, rs = env(tmp_path)
    run_id = _run(rs, [FAIL_WARN, {**FAIL_WARN, "check_id": "info.only", "severity": "info"}])
    found = checks_only(tmp_path, store, idmap, rs)
    assert [(i["severity"], i["run_id"]) for i in found] == [("warn", run_id)]
    assert "plausibility.range" in found[0]["title"]


def test_only_the_latest_value_of_a_field_counts(tmp_path):
    store, idmap, rs = env(tmp_path)
    _run(rs, [FAIL_WARN])
    _run(rs, [{**FAIL_WARN, "outcome": "pass"}])  # re-extracted, now passes
    _run(rs, [FAIL_WARN], trial=True)  # trials never count
    assert checks_only(tmp_path, store, idmap, rs) == []


def test_a_decided_value_drops_its_findings(tmp_path):
    store, idmap, rs = env(tmp_path)
    run_id = _run(rs, [FAIL_WARN])
    append_decision(rs, run_id, ReviewDecision(
        item_key="ISS-1:scope1:2025-12-31", decision="approve", reason_code="other", reviewer="A", user_id="u_a",
        role="analyst", snapshot_id="s1", step="first",
    ))
    assert checks_only(tmp_path, store, idmap, rs) == []


def test_feeds_and_master_problems_lead_the_list(tmp_path):
    store, idmap, rs = env(tmp_path)
    _run(rs, [FAIL_WARN])
    found = issues.open_issues(store, idmap, rs, date(2026, 10, 15))
    assert any(i["source"] == "feed" and "Security master" in i["title"] for i in found), "no master loaded: behind"
    order = [(issues.SEVERITY_ORDER[i["severity"]], issues.SOURCE_ORDER[i["source"]]) for i in found]
    assert order == sorted(order) and found[-1]["source"] == "check", "same severity: feeds before check findings"
