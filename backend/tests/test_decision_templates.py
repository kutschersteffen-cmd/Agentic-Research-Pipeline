from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import current_user
from arp.api.deps import get_decision_store, get_portfolio_store, get_run_store, settings_dep
from arp.api.routers import decision as decision_router
from arp.config import Settings
from arp.decision import sources, templates
from arp.decision.mechanism import derive_mechanism
from arp.orchestration.job_manager import JobManager
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore
from tests.conftest import PRINCIPAL

FIELDS = ["Green capex", "Net zero target"]


def _extraction_run(run_store: RunStore, fields: list[str] = FIELDS) -> str:
    run_id = JobManager(run_store).create_run("extraction", {"schema_id": "sch_1"}, 8).run_id
    (run_store.run_dir(run_id) / "schema.json").write_text(json.dumps({"fields": [{"name": f} for f in fields]}))
    rows = [
        {
            "company_id": f"c{i}",
            "name": f"Company {i}",
            "overall_confidence": 0.9,
            "needs_review": False,
            "fields": [
                {"field_name": "Green capex", "value": 10.0 * i, "confidence": 0.9, "grounded": True},
                {"field_name": "Net zero target", "value": i % 2 == 0, "confidence": 0.9, "grounded": True},
            ],
        }
        for i in range(8)
    ]
    run_store.results_path(run_id).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return run_id


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
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        c.store, c.run_store = store, run_store
        yield c


def _template(client) -> str:
    """A framework derived on one extraction run, saved -- the template."""
    dataset = sources.from_extraction_run(client.run_store, _extraction_run(client.run_store))
    config, audit = derive_mechanism(dataset, name="Green capex scoring")
    client.store.save(config, audit)
    return config.framework_id


def test_rule_calculated_columns_are_not_required_of_the_table(client):
    """A column the framework's own rule graph produces is not a gap in the
    table it is applied to; a source column the rules read is."""
    config = client.store.get(_template(client))
    graph = {
        "nodes": [
            {"id": "in", "type": "inputNode", "name": "Input"},
            {"id": "ex", "type": "expressionNode", "name": "Calc", "content": {"expressions": [{"key": "capex_x2", "value": "green_capex * 2"}]}},
            {"id": "out", "type": "outputNode", "name": "Output"},
        ],
        "edges": [{"id": "e1", "sourceId": "in", "targetId": "ex"}, {"id": "e2", "sourceId": "ex", "targetId": "out"}],
    }
    config = config.model_copy(update={"rule_graph": graph, "criteria": [*config.criteria, config.criteria[0].model_copy(update={"column": "capex_x2"})]})
    required = templates.required_columns(config)
    assert "capex_x2" not in required
    assert "Green capex" in required, "read by the rule graph under its slug"
    assert templates.missing_columns(config, sources.extraction_columns(["Net zero target"])) == ["Green capex"]


def test_export_import_round_trip_starts_a_new_unratified_framework(client):
    framework_id = _template(client)
    client.store.ratify(framework_id, ratified_by="IC")
    exported = client.get(f"/api/decision/mechanisms/{framework_id}/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    payload = exported.json()
    assert payload["format"] == templates.TEMPLATE_FORMAT and payload["origin"]["ratified"] is True

    imported = client.post("/api/decision/mechanisms/import", json={"template": payload}).json()
    assert imported["config"]["framework_id"] != framework_id
    assert imported["config"]["ratified"] is False and imported["config"]["version"] == 1
    assert imported["config"]["criteria"] == payload["config"]["criteria"]
    assert imported["audit"][-1]["stage"] == "Import" and "ratified by IC" in imported["audit"][-1]["decision"]


def test_import_refuses_foreign_files_and_code_nodes(client):
    assert client.post("/api/decision/mechanisms/import", json={"template": {"format": "other"}}).status_code == 400
    payload = templates.export_template(client.store.get(_template(client)), [])
    payload["config"]["rule_graph"] = {"nodes": [{"id": "f", "type": "functionNode"}], "edges": []}
    response = client.post("/api/decision/mechanisms/import", json={"template": payload})
    assert response.status_code == 400 and "functionNode" in response.text


def test_match_ranks_templates_by_fit_for_a_schema(client):
    _template(client)
    fits = client.post("/api/decision/templates/match", json={"run_type": "extraction", "field_names": FIELDS}).json()
    assert fits[0]["missing_columns"] == []
    gaps = client.post("/api/decision/templates/match", json={"run_type": "extraction", "field_names": ["Other"]}).json()
    assert set(gaps[0]["missing_columns"]) >= {"Green capex"}


def test_attached_template_scores_the_run_with_its_pinned_version(client):
    framework_id = _template(client)
    run_id = _extraction_run(client.run_store)
    assert client.get(f"/api/decision/runs/{run_id}/decision").status_code == 404, "nothing attached yet"

    pinned = client.put(f"/api/decision/runs/{run_id}/framework", json={"framework_id": framework_id}).json()
    assert pinned["version"] == 1
    client.store.new_version(client.store.get(framework_id).model_copy(update={"name": "edited"}))

    scored = client.get(f"/api/decision/runs/{run_id}/decision").json()
    assert scored["framework"]["version"] == 1 and scored["result"]["framework_version"] == 1
    assert scored["missing_columns"] == []
    assert scored["result"]["scored_count"] + scored["result"]["excluded_count"] + scored["result"]["insufficient_count"] == 8


def test_publishing_from_a_run_needs_a_finished_run_and_a_ratified_version(client):
    framework_id = _template(client)
    run_id = _extraction_run(client.run_store)
    client.put(f"/api/decision/runs/{run_id}/framework", json={"framework_id": framework_id})
    body = {"published_by": "ana"}  # ignored: the principal publishes

    running = client.post(f"/api/decision/runs/{run_id}/publish", json=body)
    assert running.status_code == 409, "half a run's tiers are not the universe's tiers"

    JobManager(client.run_store).finish_run(run_id)
    assert client.get(f"/api/decision/runs/{run_id}/decision").json()["ratified"] is False
    assert client.post(f"/api/decision/runs/{run_id}/publish", json=body).status_code == 422

    client.store.ratify(framework_id, 1, ratified_by="IC")
    published = client.post(f"/api/decision/runs/{run_id}/publish", json=body)
    assert published.status_code == 200, published.text
    snapshot = published.json()
    assert snapshot["framework_version"] == 1 and snapshot["id_column"] == "Company_Id"
    assert sorted(r["entity_id"] for r in snapshot["rows"]) == [f"c{i}" for i in range(8)]
    assert client.store.get_dataset(snapshot["dataset_id"]) is not None, "the snapshot's table opens in the studio"
    assert [p["snapshot_id"] for p in client.get("/api/decision/published").json()] == [snapshot["snapshot_id"]]


def test_attach_refuses_a_template_the_schema_cannot_feed(client):
    framework_id = _template(client)
    run_id = _extraction_run(client.run_store, fields=["Something else"])
    response = client.put(f"/api/decision/runs/{run_id}/framework", json={"framework_id": framework_id})
    assert response.status_code == 400 and "Green capex" in response.text


def test_transition_plan_indicators_become_yes_no_columns(tmp_path):
    run_store = RunStore(tmp_path)
    path = run_store.results_path("tp")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "company_id": "a",
        "name": "Alpha",
        "disclosed_count": 1,
        "indicators": [
            {"identifier": "A_headline_1", "verdict": "YES", "confidence": 1.0},
            {"identifier": "A_headline_2", "verdict": "NA", "confidence": 0.0},
        ],
    }
    path.write_text(json.dumps(record) + "\n")
    assert "Ind_A_headline_1_Disclosed" not in sources.from_transition_plan_run(run_store, "tp").columns
    dataset = sources.from_transition_plan_run(run_store, "tp", include_indicators=True)
    assert dataset.rows[0]["Ind_A_headline_1_Disclosed"] == "Yes"
    assert dataset.rows[0]["Ind_A_headline_2_Disclosed"] == "", "NA is not a No"
    assert set(dataset.columns) <= set(sources.expected_transition_plan_columns())


# --- the rules step at the end of every extraction pipeline ---


class _Result:
    def __init__(self, record: dict) -> None:
        from arp.llm.base import LLMUsage

        self.record = record
        self.usage = LLMUsage()


def _run_pipeline(run_store: RunStore, run_id: str, companies: list[dict]) -> None:
    import asyncio

    from arp.orchestration.batch_runner import run_company_batch
    from arp.schemas.common import CompanyRef

    by_id = {c["company_id"]: c for c in companies}

    async def worker(company):
        return _Result(by_id[company.company_id])

    asyncio.run(
        run_company_batch(
            run_id,
            [CompanyRef(company_id=c["company_id"], name=c["name"]) for c in companies],
            run_store=run_store,
            worker=worker,
            result_to_json=lambda r: r.record,
            review_items=lambda c, r: [],
            cost_usd=lambda r: 0.0,
            concurrency=2,
        )
    )


def _extraction_records() -> list[dict]:
    return [
        {
            "company_id": f"c{i}",
            "name": f"Company {i}",
            "overall_confidence": 0.9,
            "needs_review": False,
            "fields": [
                {"field_name": "Green capex", "value": 10.0 * i, "confidence": 0.9, "grounded": True},
                {"field_name": "Net zero target", "value": i % 2 == 0, "confidence": 0.9, "grounded": True},
            ],
        }
        for i in range(8)
    ]


def test_the_pipeline_scores_its_results_as_the_last_step(client):
    config = client.store.get(_template(client))
    run_id = JobManager(client.run_store).create_run("extraction", {}, 8).run_id
    templates.attach_to_run(client.run_store, run_id, config)
    assert templates.stored_decision(client.run_store, run_id) is None

    _run_pipeline(client.run_store, run_id, _extraction_records())

    manifest = client.run_store.load_manifest(run_id)
    assert manifest.status.value == "completed"
    assert manifest.params["decision_framework"]["status"] == "scored"
    stored = templates.stored_decision(client.run_store, run_id)
    assert stored["error"] is None and len(stored["result"]["entities"]) == 8
    served = client.get(f"/api/decision/runs/{run_id}/decision").json()
    assert served["scored_at"] == stored["scored_at"], "a finished run serves what its last step stored"


def test_a_failing_rules_step_never_fails_the_run(client):
    config = client.store.get(_template(client))
    run_id = JobManager(client.run_store).create_run("extraction", {}, 0).run_id
    templates.attach_to_run(client.run_store, run_id, config)

    _run_pipeline(client.run_store, run_id, [])  # no results -> no table to score

    manifest = client.run_store.load_manifest(run_id)
    assert manifest.status.value == "completed"
    assert manifest.params["decision_framework"]["status"] == "failed"
    assert "no results" in templates.stored_decision(client.run_store, run_id)["error"]


def test_a_run_without_a_template_has_no_rules_step(client):
    run_id = JobManager(client.run_store).create_run("extraction", {}, 8).run_id
    _run_pipeline(client.run_store, run_id, _extraction_records())
    assert templates.stored_decision(client.run_store, run_id) is None
    assert "decision_framework" not in client.run_store.load_manifest(run_id).params


def test_the_pinned_copy_scores_the_run_even_after_the_framework_is_deleted(client):
    """The rules that scored a run travel with it."""
    import shutil

    framework_id = _template(client)
    run_id = _extraction_run(client.run_store)
    client.put(f"/api/decision/runs/{run_id}/framework", json={"framework_id": framework_id})
    shutil.rmtree(client.store.frameworks_dir / framework_id)
    JobManager(client.run_store).finish_run(run_id)
    rescored = client.post(f"/api/decision/runs/{run_id}/decision/rescore")
    assert rescored.status_code == 200, rescored.text
    assert rescored.json()["framework"]["framework_id"] == framework_id


def test_financials_and_tnfd_runs_become_tables_with_their_expected_columns(tmp_path):
    run_store = RunStore(tmp_path)
    for run_id, record in (
        (
            "fin",
            {
                "company_id": "a",
                "name": "Alpha",
                "currency": "EUR",
                "capex": {"total": {"value": 120.0}, "confidence": 0.9, "grounded": True},
                "rnd": {"total": {"value": None}},
                "segments": [{"revenue": {"value": 60.0}}, {"revenue": {"value": 40.0}}],
                "overall_confidence": 0.8,
            },
        ),
        (
            "tn",
            {
                "company_id": "a",
                "name": "Alpha",
                "disclosures": [
                    {"recommendation_id": "governance.A", "disclosed": True, "confidence": 0.9, "grounded": True},
                    {"recommendation_id": "strategy.B", "disclosed": False, "confidence": 0.7, "grounded": False},
                ],
                "core_global_metrics": [{"category": "pollution", "grounded": True}, {"category": "pollution", "grounded": False}],
            },
        ),
    ):
        path = run_store.results_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record) + "\n")

    fin = sources.from_financials_run(run_store, "fin")
    assert fin.columns == templates.expected_run_columns("financials")
    assert fin.rows[0]["Capex_Total"] == "120" and fin.rows[0]["Rnd_Total"] == ""
    assert fin.rows[0]["Segment_Revenue_Total"] == "100"
    assert fin.confidence["Capex_Total"] == [0.9]

    tnfd = sources.from_tnfd_run(run_store, "tn")
    assert tnfd.columns == templates.expected_run_columns("tnfd")
    row = tnfd.rows[0]
    assert (row["Governance_A_Disclosed"], row["Strategy_B_Disclosed"], row["Metrics_C_Disclosed"]) == ("Yes", "No", "")
    assert row["Recommendations_Disclosed_Count"] == "1"
    assert row["Pollution_Metrics_Count"] == "1", "only grounded metrics count"
