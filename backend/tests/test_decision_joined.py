"""One Decision Studio table from several company-level runs, joined by company."""

import json

import pytest

from arp.decision import sources
from arp.orchestration.job_manager import JobManager
from arp.storage.run_store import RunStore


def _run(store: RunStore, run_type: str, records: list[dict]) -> str:
    run_id = JobManager(store).create_run(run_type, {}, len(records)).run_id
    store._results_path(run_id).write_text("".join(json.dumps(r) + "\n" for r in records))
    return run_id


def _tp(company_id, name, disclosed, target):
    return {
        "company_id": company_id, "name": name, "disclosed_count": disclosed, "walk_disclosed_count": 3, "walk_total_count": 30,
        "talk_disclosed_count": 5, "overall_confidence": 0.9, "needs_review": False,
        "by_category": [{"category": "target", "disclosed_count": 4, "total_count": 16}],
        "indicators": [{"identifier": "A_ambition_3", "verdict": "YES" if target else "NO", "confidence": 0.8}],
    }


def _ex(company_id, name, coverage, grounded=True):
    return {
        "company_id": company_id, "name": name, "overall_confidence": 0.7, "needs_review": True,
        "fields": [{"field_name": "Target_Coverage_pct", "value": coverage, "confidence": 0.9, "grounded": grounded}],
    }


def test_joins_by_company_and_prefixes_shared_columns(tmp_path):
    store = RunStore(tmp_path)
    tp = _run(store, "transition_plan", [_tp("c1", "Acme", 40, True), _tp("c2", "Beta", 20, False)])
    # Acme matches on its id (the names differ), Beta on its name (no id), Gamma is only in the extraction run.
    ex = _run(store, "extraction", [_ex("c1", "Acme Corp", 70.0), _ex("", "Beta", 30.0, grounded=False), _ex("c3", "Gamma", 90.0)])

    table = sources.from_joined_runs(store, [tp, ex], include_indicators=True)
    assert table.source == "joined_runs" and table.source_ref == f"{tp},{ex}"
    # Both runs' columns, each once; a name both have takes its run's prefix.
    assert {"Indicators_Disclosed_Count", "Ind_A_ambition_3_Disclosed", "Target_Coverage_pct"} <= set(table.columns)
    assert {"TP_Needs_Review_Flag", "Extraction_Needs_Review_Flag"} <= set(table.columns)
    assert "Needs_Review_Flag" not in table.columns

    rows = {r["Company"]: r for r in table.rows}
    assert list(rows) == ["Acme", "Beta", "Gamma"]  # first run's order, then the companies only the second has
    assert rows["Acme"]["Target_Coverage_pct"] == "70.0" and rows["Acme"]["Ind_A_ambition_3_Disclosed"] == "Yes"
    assert rows["Beta"]["Target_Coverage_pct"] == "30.0"  # matched on the name when the id is missing
    assert rows["Gamma"]["Indicators_Disclosed_Count"] == ""  # not in the transition plan run: blank, not zero
    # Per-cell confidence follows the joined rows; an ungrounded value counts as 0.
    assert table.confidence["Target_Coverage_pct"] == [0.9, 0.0, 0.9]
    assert table.confidence["Ind_A_ambition_3_Disclosed"][:2] == [0.8, 0.8] and table.confidence["Ind_A_ambition_3_Disclosed"][2] is None


def test_refuses_fewer_than_two_or_unjoinable_runs(tmp_path):
    store = RunStore(tmp_path)
    tp = _run(store, "transition_plan", [_tp("c1", "Acme", 40, True)])
    theme = _run(store, "theme", [{"company_id": "c1"}])
    with pytest.raises(ValueError, match="at least two"):
        sources.from_joined_runs(store, [tp])
    with pytest.raises(ValueError, match="only transition_plan"):
        sources.from_joined_runs(store, [tp, theme])


def test_two_runs_of_the_same_kind_are_numbered(tmp_path):
    store = RunStore(tmp_path)
    a = _run(store, "extraction", [_ex("c1", "Acme", 70.0)])
    b = _run(store, "extraction", [_ex("c1", "Acme", 75.0)])
    table = sources.from_joined_runs(store, [a, b])
    assert {"Extraction_Target_Coverage_pct", "Extraction2_Target_Coverage_pct"} <= set(table.columns)
    assert len(table.rows) == 1
