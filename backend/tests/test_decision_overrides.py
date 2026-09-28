"""A reviewer setting one criterion's level for one entity by hand."""

import json

from arp.decision import overrides, templates
from arp.decision.mechanism import apply_mechanism
from arp.orchestration.job_manager import JobManager
from arp.schemas.decision import LevelOverride
from tests.test_decision_levels import _by_name, _config, _dataset
from tests.test_decision_templates import client  # noqa: F401 - the API fixture


def _override(**fields):
    return LevelOverride(**{"entity_key": "Gamma", "criterion_id": "cov", "level": 6, "reason": "Coverage is in the 2025 CDP response", "reviewer": "Ana", **fields})


def test_an_override_replaces_the_rules_level_and_keeps_the_original():
    before = _by_name(apply_mechanism(_dataset(), _config()))["Gamma"]
    result = apply_mechanism(_dataset(), _config(), overrides=[_override()])
    gamma = _by_name(result)["Gamma"]

    cov = next(c for c in gamma.contributions if c.criterion_id == "cov")
    assert cov.normalised == 6 and cov.overridden_from == 1  # the rules said 1 (coverage not disclosed)
    assert cov.override.reviewer == "Ana" and "CDP" in cov.override.reason
    assert gamma.score > before.score
    assert any(n.startswith("Override: Target coverage 1 → 6") for n in gamma.notes)
    entry = next(a for a in result.audit if a.stage == "Overrides")
    assert entry.decision == "level 1 -> 6 by Ana" and "CDP" in entry.why and not entry.needs_check
    # Nobody else moved.
    assert _by_name(result)["Alpha"].score == _by_name(apply_mechanism(_dataset(), _config()))["Alpha"].score


def test_an_override_that_no_longer_fits_is_left_out_and_says_so():
    result = apply_mechanism(
        _dataset(), _config(), overrides=[_override(level=9), _override(entity_key="Nobody"), _override(criterion_id="gone")]
    )
    assert _by_name(result)["Gamma"].score == _by_name(apply_mechanism(_dataset(), _config()))["Gamma"].score
    problems = [a.why for a in result.audit if a.stage == "Overrides"]
    assert len(problems) == 3 and all(a.needs_check for a in result.audit if a.stage == "Overrides")
    assert any("off the 1-7 scale" in p for p in problems) and any("not in this table" in p for p in problems)


def test_relative_mode_does_not_apply_overrides():
    result = apply_mechanism(_dataset(), _config(mode="relative"), overrides=[_override()])
    assert any(a.stage == "Overrides" and a.decision == "not applied" for a in result.audit)


def test_the_override_book_keeps_history(tmp_path):
    path = tmp_path / "o.json"
    overrides.set_override(path, _override(level=5))
    overrides.set_override(path, _override(level=6))  # same entity and criterion: replaced
    assert [o.level for o in overrides.load(path)] == [6]
    overrides.remove_override(path, "Gamma", "cov", "Ben", "Rules are right after all")
    assert overrides.load(path) == []
    assert [h["action"] for h in overrides.history(path)] == ["set", "set", "removed"]


def test_a_run_override_rescores_the_finished_run(client):  # noqa: F811
    store, run_store = client.store, client.run_store
    config = store.save(_config(framework_id="levels_fw", name="Levels", source_columns=["Company", "Company_Id", "Target_Coverage_pct", "Net_Zero_Target", "Board_Oversight"]))
    store.ratify(config.framework_id, config.version, ratified_by="IC")
    run_id = JobManager(run_store).create_run("extraction", {}, 3).run_id
    records = [
        {"company_id": cid, "name": name, "overall_confidence": 0.9, "needs_review": False, "fields": [
            {"field_name": "Target_Coverage_pct", "value": cov, "confidence": 0.9, "grounded": True},
            {"field_name": "Net_Zero_Target", "value": nz, "confidence": 0.9, "grounded": True},
            {"field_name": "Board_Oversight", "value": bo, "confidence": 0.9, "grounded": True},
        ]}
        for cid, name, cov, nz, bo in [("a", "Alpha", 80, "Yes", "Yes"), ("b", "Beta", 50, "Yes", "No"), ("c", "Gamma", None, "No", "No")]
    ]
    run_store.results_path(run_id).write_text("".join(json.dumps(r) + "\n" for r in records))
    templates.attach_to_run(run_store, run_id, store.get(config.framework_id))
    templates.score_run(run_store, run_id)
    JobManager(run_store).finish_run(run_id)

    body = json.loads(_override().model_dump_json())
    decision = client.post(f"/api/decision/runs/{run_id}/overrides", json=body).json()
    gamma = next(e for e in decision["result"]["entities"] if e["name"] == "Gamma")
    cov = next(c for c in gamma["contributions"] if c["criterion_id"] == "cov")
    assert (cov["normalised"], cov["overridden_from"]) == (6, 1)
    # Stored, so the run serves it without a rescore.
    stored = templates.stored_decision(run_store, run_id)
    assert any(c.get("override") for e in stored["result"]["entities"] for c in e["contributions"])

    assert client.post(f"/api/decision/runs/{run_id}/overrides", json={**body, "level": 12}).status_code == 400
    removed = client.post(
        f"/api/decision/runs/{run_id}/overrides/remove", json={"entity_key": "Gamma", "criterion_id": "cov", "reviewer": "Ben", "reason": "Not verifiable"}
    ).json()
    cov = next(c for e in removed["result"]["entities"] if e["name"] == "Gamma" for c in e["contributions"] if c["criterion_id"] == "cov")
    assert cov["normalised"] == 1 and cov["override"] is None
    view = client.get(f"/api/decision/runs/{run_id}/overrides").json()
    assert view["overrides"] == [] and [h["action"] for h in view["history"]] == ["set", "removed"]


def test_a_table_override_applies_to_every_score_of_that_table(client):  # noqa: F811
    dataset = _dataset()
    client.store.save_dataset(dataset)
    config = json.loads(_config().model_dump_json())
    base = client.post("/api/decision/score", json={"dataset_id": dataset.dataset_id, "config": config}).json()

    view = client.post(f"/api/decision/datasets/{dataset.dataset_id}/overrides", json=json.loads(_override().model_dump_json())).json()
    assert [o["level"] for o in view["overrides"]] == [6]
    scored = client.post("/api/decision/score", json={"dataset_id": dataset.dataset_id, "config": config}).json()
    gamma = next(e for e in scored["entities"] if e["name"] == "Gamma")
    assert gamma["score"] > next(e for e in base["entities"] if e["name"] == "Gamma")["score"]
    assert any(a["stage"] == "Overrides" for a in scored["audit"])

    missing = client.post(
        f"/api/decision/datasets/{dataset.dataset_id}/overrides/remove", json={"entity_key": "Nobody", "criterion_id": "cov", "reviewer": "Ben", "reason": "typo"}
    )
    assert missing.status_code == 404
    assert client.post(f"/api/decision/datasets/{dataset.dataset_id}/overrides", json={**json.loads(_override().model_dump_json()), "reason": ""}).status_code == 422
