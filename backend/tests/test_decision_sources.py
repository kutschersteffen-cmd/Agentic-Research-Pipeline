from __future__ import annotations

import json

from arp.decision import sources
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.profiling import profile_dataset
from arp.storage.run_store import RunStore


def _write(run_store: RunStore, run_id: str, rows: list[dict]) -> None:
    path = run_store.results_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_transition_plan_run_becomes_a_scoreable_table(tmp_path):
    """The paper's completeness metric is a count, not a decision. This is
    what turns '42 of 64 disclosed' into a tier and an action."""
    run_store = RunStore(tmp_path)
    _write(
        run_store,
        "tp1",
        [
            {
                "company_id": f"c{i}",
                "name": f"Company {i}",
                "company_sector": "Utilities",
                "company_location": "Europe",
                "disclosed_count": 8 + i * 3,
                "walk_disclosed_count": 2 + i,
                "walk_total_count": 30,
                "talk_disclosed_count": 6 + i,
                "overall_confidence": 0.5 + i * 0.05,
                "by_category": [
                    {"category": "target", "disclosed_count": i, "total_count": 16},
                    {"category": "governance", "disclosed_count": 2 * i, "total_count": 16},
                ],
                "needs_review": i == 0,
            }
            for i in range(8)
        ],
    )
    dataset = sources.from_transition_plan_run(run_store, "tp1")
    assert dataset.source == "transition_plan_run" and dataset.source_ref == "tp1"
    assert "Target_Disclosure_pct" in dataset.columns and "Governance_Disclosure_pct" in dataset.columns
    assert dataset.confidence["Indicators_Disclosed_Count"][3] == 0.65

    profiles = profile_dataset(dataset)
    assert profiles["Indicators_Disclosed_Count"].type in ("numeric", "ordinal")
    config, _ = derive_mechanism(dataset)
    directions = {c.column: c.direction for c in config.criteria}
    assert directions["Indicators_Disclosed_Count"] == "higher", "column names follow the conventions the dictionaries know"
    result = apply_mechanism(dataset, config)
    assert result.scored_count > 0


def test_extraction_run_carries_confidence_only_where_the_citation_grounded(tmp_path):
    """An ungrounded value is present but not verified, and the two are
    different claims."""
    run_store = RunStore(tmp_path)
    _write(
        run_store,
        "ex1",
        [
            {
                "company_id": "a",
                "name": "Alpha",
                "overall_confidence": 0.9,
                "fields": [
                    {"field_name": "Green_Capex_Share_pct", "value": 40, "confidence": 0.95, "grounded": True},
                    {"field_name": "Scope1_Intensity", "value": 120, "confidence": 0.9, "grounded": False},
                ],
            },
            {
                "company_id": "b",
                "name": "Bravo",
                "overall_confidence": 0.4,
                "fields": [{"field_name": "Green_Capex_Share_pct", "value": 10, "confidence": 0.8, "grounded": True}],
            },
        ],
    )
    dataset = sources.from_extraction_run(run_store, "ex1")
    assert dataset.confidence["Green_Capex_Share_pct"] == [0.95, 0.8]
    assert dataset.confidence["Scope1_Intensity"][0] == 0.0, "ungrounded means unverified, not confident"
    assert dataset.confidence["Scope1_Intensity"][1] is None, "absent is not the same as unverified"


def test_grounded_coverage_gate_routes_an_unverified_score_to_review(tmp_path):
    run_store = RunStore(tmp_path)
    _write(
        run_store,
        "ex2",
        [
            {
                "company_id": f"c{i}",
                "name": f"Company {i}",
                "overall_confidence": 0.9,
                "fields": [
                    {"field_name": "Green_Capex_Share_pct", "value": 10 * i, "confidence": 0.95, "grounded": i > 2},
                    {"field_name": "Disclosure_Score", "value": 5 * i, "confidence": 0.95, "grounded": i > 2},
                ],
            }
            for i in range(8)
        ],
    )
    dataset = sources.from_extraction_run(run_store, "ex2")
    config, _ = derive_mechanism(dataset)
    config.require_grounded_coverage = True
    config.min_coverage_pct = 60
    result = apply_mechanism(dataset, config)
    ungrounded = [e for e in result.entities if e.name in ("Company 0", "Company 1", "Company 2")]
    assert all(e.status == "insufficient" for e in ungrounded)
    assert all("grounded weight covered" in "".join(e.notes) for e in ungrounded)


def test_asking_for_grounded_coverage_without_confidence_says_so(tmp_path):
    from arp.decision.dataset import build_dataset

    dataset = build_dataset(
        "plain.csv",
        [["Name", "A_Score", "B_Score"]] + [[f"E{i}", str(i * 10), str(i * 5)] for i in range(8)],
    )
    config, _ = derive_mechanism(dataset)
    config.require_grounded_coverage = True
    result = apply_mechanism(dataset, config)
    entry = next(e for e in result.audit if e.stage == "Sufficiency")
    assert entry.needs_check is True
    assert "no per-cell confidence" in entry.why


def test_theme_run_aggregates_per_activity_matches_to_one_row_per_company(tmp_path):
    run_store = RunStore(tmp_path)
    _write(
        run_store,
        "th1",
        [
            {"company_id": "a", "name": "Alpha", "verdict": "include", "exposure_estimate": "high", "confidence": 0.9, "flagged_for_review": False},
            {"company_id": "a", "name": "Alpha", "verdict": "include", "exposure_estimate": "medium", "confidence": 0.7, "flagged_for_review": False},
            {"company_id": "b", "name": "Bravo", "verdict": "exclude", "exposure_estimate": "none", "confidence": 0.8, "flagged_for_review": True},
        ],
    )
    dataset = sources.from_theme_run(run_store, "th1")
    assert dataset.row_count == 2
    alpha = next(r for r in dataset.rows if r["Company"] == "Alpha")
    assert alpha["Activities_Included_Count"] == "2"
    assert alpha["Best_Exposure_Score_0_100"] == "75.0"
    assert alpha["Mean_Exposure_Score_0_100"] == "62.5"
    bravo = next(r for r in dataset.rows if r["Company"] == "Bravo")
    assert bravo["Flagged_For_Review_Flag"] == "Yes"


def test_an_empty_run_is_an_error_not_an_empty_table(tmp_path):
    import pytest

    run_store = RunStore(tmp_path)
    _write(run_store, "empty", [])
    with pytest.raises(ValueError, match="no results"):
        sources.from_transition_plan_run(run_store, "empty")
