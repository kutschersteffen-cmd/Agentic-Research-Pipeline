from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_decision_store, get_portfolio_store, get_run_store, settings_dep
from arp.api.routers import decision as decision_router
from arp.config import Settings
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore

SAMPLE = Path(__file__).resolve().parents[1] / "arp" / "decision" / "sample_data" / "example_transition_universe.csv"


@pytest.fixture
def client(tmp_path):
    settings = Settings(frameworks_dir=tmp_path / "frameworks", runs_dir=tmp_path / "runs")
    settings.ensure_dirs()
    store = DecisionStore(settings.frameworks_dir)
    run_store = RunStore(settings.runs_dir)

    app = FastAPI()
    app.include_router(decision_router.router)
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_decision_store] = lambda: store
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[get_portfolio_store] = lambda: None
    with TestClient(app) as c:
        c.run_store = run_store
        yield c


def _upload(client) -> dict:
    with SAMPLE.open("rb") as fh:
        response = client.post("/api/decision/datasets", files={"file": (SAMPLE.name, fh, "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_profiles_the_table_server_side(client):
    """Parsing and scoring happen here, not in the browser: a number
    computed in a tab is not reproducible, citable or reviewable."""
    summary = _upload(client)
    assert summary["row_count"] == 24
    profiles = {p["name"]: p for p in summary["profiles"]}
    assert profiles["Scope3_Reported"]["type"] == "boolean"
    proposals = {p["column"]: p for p in summary["proposals"]}
    assert proposals["Scope12_Intensity_tCO2e_per_mEUR"]["direction"] == "lower"
    assert proposals["Portfolio_Weight_bps"]["role"] == "size"


def test_upload_rejects_a_path_traversing_filename(client):
    response = client.post("/api/decision/datasets", files={"file": ("../../evil.csv", b"a,b\n1,2\n", "text/csv")})
    assert response.status_code == 400


def test_upload_rejects_an_unsupported_format(client):
    response = client.post("/api/decision/datasets", files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")})
    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]


def test_derive_then_score_round_trip(client):
    dataset_id = _upload(client)["dataset_id"]
    derived = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id, "name": "Climate"}).json()
    assert derived["config"]["dimensions"]
    assert any(e["stage"] == "Dimensions" for e in derived["audit"])

    scored = client.post("/api/decision/score", json={"dataset_id": dataset_id, "config": derived["config"]})
    assert scored.status_code == 200, scored.text
    result = scored.json()
    assert result["scored_count"] + result["excluded_count"] + result["insufficient_count"] == 24
    assert len(result["effective_cuts"]) == 3
    assert result["histogram"]


def test_scoring_an_unknown_dataset_is_a_404(client):
    response = client.post("/api/decision/score", json={"dataset_id": "ds_nope", "framework_id": "fw_nope"})
    assert response.status_code == 404


def test_score_requires_a_framework_or_an_inline_config(client):
    dataset_id = _upload(client)["dataset_id"]
    response = client.post("/api/decision/score", json={"dataset_id": dataset_id})
    assert response.status_code == 400


def test_saving_edits_records_them_as_human_decisions(client):
    dataset_id = _upload(client)["dataset_id"]
    derived = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id, "save": True}).json()
    config = derived["config"]
    config["criteria"][0]["direction"] = "lower" if config["criteria"][0]["direction"] == "higher" else "higher"
    config["min_coverage_pct"] = 75

    saved = client.post("/api/decision/mechanisms", json={"config": config, "base_version": 1, "by": "analyst"}).json()
    assert saved["config"]["version"] == 2
    human = [e for e in saved["audit"] if e["origin"] == "human"]
    assert human and all(e["by"] == "analyst" for e in human)
    assert any("direction" in e["decision"] for e in human)
    assert any("60 -> 75" in e["decision"] for e in human)


def test_ratified_versions_are_readable_after_later_edits(client):
    dataset_id = _upload(client)["dataset_id"]
    config = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id, "save": True}).json()["config"]
    client.post(f"/api/decision/mechanisms/{config['framework_id']}/ratify")
    edited = {**config, "min_coverage_pct": 90}
    client.post("/api/decision/mechanisms", json={"config": edited, "base_version": 1})

    v1 = client.get(f"/api/decision/mechanisms/{config['framework_id']}", params={"version": 1}).json()
    assert v1["config"]["ratified"] is True
    assert v1["config"]["min_coverage_pct"] == 60
    assert client.get(f"/api/decision/mechanisms/{config['framework_id']}/versions").json() == [1, 2]


def test_scoring_by_stored_framework_carries_its_audit(client):
    dataset_id = _upload(client)["dataset_id"]
    config = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id, "save": True}).json()["config"]
    result = client.post("/api/decision/score", json={"dataset_id": dataset_id, "framework_id": config["framework_id"]}).json()
    assert any(e["stage"] == "Roles" for e in result["audit"]), "a stored framework's derivation trail comes with it"


def test_csv_export_carries_the_decision_not_just_the_score(client):
    dataset_id = _upload(client)["dataset_id"]
    config = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id}).json()["config"]
    response = client.post("/api/decision/export.csv", json={"dataset_id": dataset_id, "config": config})
    assert response.status_code == 200
    header = response.text.splitlines()[0]
    for column in ("rank", "tier_name", "status", "grounded_coverage_pct", "leverage", "notes"):
        assert column in header


def test_sensitivity_endpoint_answers_how_much_the_weights_matter(client):
    dataset_id = _upload(client)["dataset_id"]
    config = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id}).json()["config"]
    scored = client.post("/api/decision/score", json={"dataset_id": dataset_id, "config": config}).json()
    target = next(e for e in scored["entities"] if e["status"] == "scored")
    response = client.post(
        "/api/decision/sensitivity",
        json={"dataset_id": dataset_id, "config": config, "entity_keys": [target["entity_key"]], "steps": 5},
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["tipping_points"]


def test_compare_endpoint_holds_the_framework_fixed_across_snapshots(client):
    first = _upload(client)["dataset_id"]
    second = _upload(client)["dataset_id"]
    config = client.post("/api/decision/mechanisms/derive", json={"dataset_id": first, "save": True}).json()["config"]
    response = client.post(
        "/api/decision/compare",
        json={"dataset_id_before": first, "dataset_id_after": second, "framework_id": config["framework_id"]},
    )
    assert response.status_code == 200
    comparison = response.json()
    assert comparison["comparable"] is True
    assert comparison["improved"] == 0 and comparison["worsened"] == 0, "the same table twice moves nothing"


def test_from_source_builds_a_table_from_a_transition_plan_run(client):
    run_id = "tp_run_1"
    path = client.run_store.results_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "company_id": f"c{i}",
            "name": f"Company {i}",
            "company_sector": "Utilities" if i % 2 else "Materials",
            "disclosed_count": 10 + i,
            "walk_disclosed_count": 4 + i,
            "walk_total_count": 30,
            "talk_disclosed_count": 6,
            "overall_confidence": 0.9,
            "by_category": [{"category": "target", "disclosed_count": i, "total_count": 16}],
            "needs_review": False,
        }
        for i in range(8)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    response = client.post("/api/decision/datasets/from-source", json={"source": "transition_plan_run", "run_id": run_id})
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["row_count"] == 8
    assert summary["has_confidence"] is True
    assert "Indicators_Disclosed_Count" in summary["columns"]


def test_from_source_rejects_an_unknown_source(client):
    response = client.post("/api/decision/datasets/from-source", json={"source": "crystal_ball"})
    assert response.status_code == 400


def test_from_source_requires_a_run_id(client):
    response = client.post("/api/decision/datasets/from-source", json={"source": "theme_run"})
    assert response.status_code == 400


def test_from_source_builds_the_barrier_matrix_without_a_run(client):
    """The only source that needs no run at all -- the matrix is shipped
    data, and its entity is a sector in a jurisdiction, not a company."""
    response = client.post("/api/decision/datasets/from-source", json={"source": "transition_barrier", "region": "China"})
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["row_count"] >= 1
    assert all(r["Region"] == "China" for r in summary["preview"])
    assert any(c.endswith("_Feasibility_0_100") for c in summary["columns"])
    assert summary["has_confidence"] is True
    proposals = {p["column"]: p for p in summary["proposals"]}
    feasibility = next(c for c in summary["columns"] if c.endswith("_Feasibility_0_100"))
    assert proposals[feasibility]["direction"] == "higher"
    assert proposals[feasibility]["needs_check"] is False


def test_from_source_rejects_a_barrier_filter_that_matches_nothing(client):
    response = client.post(
        "/api/decision/datasets/from-source", json={"source": "transition_barrier", "region": "Atlantis"}
    )
    assert response.status_code == 400


def test_barrier_matrix_scores_through_the_api(client):
    dataset_id = client.post(
        "/api/decision/datasets/from-source", json={"source": "transition_barrier"}
    ).json()["dataset_id"]
    derived = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id}).json()
    assert derived["config"]["normalise_within"] == "Region"
    result = client.post("/api/decision/score", json={"dataset_id": dataset_id, "config": derived["config"]}).json()
    assert result["scored_count"] > 0
    assert {e["cohort"] for e in result["entities"]} <= {"China", "European Union", "United States"}


def test_replication_source_with_no_runs_is_a_clean_400(client):
    response = client.post("/api/decision/datasets/from-source", json={"source": "replication_runs"})
    assert response.status_code == 400
    assert "strategy_replication" in response.json()["detail"]


def _ratio_graph() -> dict:
    return {
        "nodes": [
            {"id": "in", "type": "inputNode", "name": "Input", "position": {"x": 0, "y": 0}},
            {
                "id": "calc",
                "type": "expressionNode",
                "name": "Calc",
                "position": {"x": 200, "y": 0},
                "content": {
                    "expressions": [{"id": "1", "key": "green_capex_x2", "value": "green_capex_share_pct * 2"}],
                    "passThrough": False,
                    "inputField": None,
                    "outputPath": None,
                    "executionMode": "single",
                },
            },
            {"id": "out", "type": "outputNode", "name": "Output", "position": {"x": 400, "y": 0}},
        ],
        "edges": [
            {"id": "a", "sourceId": "in", "targetId": "calc", "type": "edge"},
            {"id": "b", "sourceId": "calc", "targetId": "out", "type": "edge"},
        ],
    }


def test_summary_carries_the_typed_inputs_the_browser_evaluates(client):
    summary = _upload(client)
    first = summary["rule_inputs"][0]
    assert first["Green_Capex_Share_pct"] == 41 and first["green_capex_share_pct"] == 41
    assert first["Scope3_Reported"] is True


def test_calculated_endpoint_profiles_the_new_columns(client):
    dataset_id = _upload(client)["dataset_id"]
    response = client.post(f"/api/decision/datasets/{dataset_id}/calculated", json={"rule_graph": _ratio_graph()})
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["calculated_columns"] == ["green_capex_x2"]
    profile = next(p for p in summary["profiles"] if p["name"] == "green_capex_x2")
    source = next(p for p in summary["profiles"] if p["name"] == "Green_Capex_Share_pct")
    assert profile["type"] == "numeric" and profile["coverage"] == source["coverage"], "a blank input stays blank"
    assert "green_capex_x2" not in summary["rule_inputs"][0], "the browser evaluates against source columns only"


def test_score_applies_an_inline_rule_graph_and_refuses_code(client):
    dataset_id = _upload(client)["dataset_id"]
    config = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id}).json()["config"]
    config["rule_graph"] = _ratio_graph()
    config["criteria"].append({"column": "green_capex_x2", "dimension_id": config["dimensions"][0]["id"]})
    result = client.post("/api/decision/score", json={"dataset_id": dataset_id, "config": config})
    assert result.status_code == 200, result.text
    assert "green_capex_x2" in result.json()["effective_weights"]

    config["rule_graph"]["nodes"][1]["type"] = "functionNode"
    refused = client.post("/api/decision/score", json={"dataset_id": dataset_id, "config": config})
    assert refused.status_code == 422
