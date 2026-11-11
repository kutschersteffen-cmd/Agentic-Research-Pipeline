"""Accepted values are never overwritten (spec argus-simplified-pipeline, data rule 1; AC-45..AC-52)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.db import models as m
from arp.db.companies import ensure_universe_company
from arp.db.observations import ObservationIn, record
from arp.db.session import transaction
from arp.db.to_observations import to_observations
from arp.orchestration.review_queue import record_review_decision
from arp.schemas.common import CompanyRef, RunManifest

FY24 = date(2024, 12, 31)
KEY = "LEI:X:revenue:2024-12-31"
CAROL = Principal(user_id="u_carol", name="Carol Approver", role="approver")
DAVE = Principal(user_id="u_dave", name="Dave Approver", role="approver")


def _row(value, *, route="auto_accept", run_id="r1"):
    return {"company_id": "acme", "name": "Acme", "schema_id": "s", "run_id": run_id, "issuer_key": "LEI:X",
            "issuer_scheme": "LEI", "_key": "acme",
            "fields": [{"field_id": "revenue", "field_name": "Revenue", "value": value, "confidence": 0.9,
                        "period_end": "2024-12-31", "route": route}]}


def _run(run_store, pg, value, *, run_id, route="auto_accept", trial=False):
    """One extraction run's result for Acme, as batch_runner commits it; returns the company id."""
    with transaction(pg) as s:
        cid = ensure_universe_company(s, "acme")
    if run_store.load_manifest(run_id) is None:
        run_store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", params={"trial": trial}))
    row = _row(value, route=route, run_id=run_id)
    items = [(KEY, {"item_key": KEY, "company_id": "acme", "field_id": "revenue", "period_end": "2024-12-31",
                    "issuer_key": "LEI:X", "field": row["fields"][0]})] if route == "review" else []
    run_store.record_company_result(
        run_id, row, observations=to_observations("extraction", cid, run_id, row, trial=trial),
        review_items=items, company=CompanyRef(company_id="acme", name="Acme", entity_id=cid),
    )
    return cid


def _facts(pg):
    with transaction(pg) as s:
        return [(f.value, f.status, f.valid_to is None)
                for f in s.scalars(select(m.CompanyFact).where(m.CompanyFact.field_id == "revenue").order_by(m.CompanyFact.id))]


def _observations(pg):
    with transaction(pg) as s:
        return list(s.scalars(select(m.FieldObservation.value).where(m.FieldObservation.field_id == "revenue")
                              .order_by(m.FieldObservation.id)))


def _items(pg, run_id):
    with transaction(pg) as s:
        return [(i.item_key, i.payload, i.observation_id) for i in s.scalars(
            select(m.ReviewItem).where(m.ReviewItem.run_id == run_id).order_by(m.ReviewItem.id))]


def _accept(run_store, pg, status):
    """An accepted fact of 12 with the given status: auto-accepted, approved or edited."""
    if status == m.FactStatus.AUTO_ACCEPTED:
        _run(run_store, pg, 12.0, run_id="r1")
    elif status == m.FactStatus.APPROVED:
        _run(run_store, pg, 12.0, run_id="r1", route="review")
        record_review_decision(run_store, "r1", KEY, "approve", "bob", None)
    else:
        _run(run_store, pg, 11.0, run_id="r1", route="review")
        record_review_decision(run_store, "r1", KEY, "correct", "bob", {"value": 12.0})
        from arp.orchestration.review_queue import record_cosign
        from tests.conftest import PRINCIPAL

        record_cosign(run_store, "r1", KEY, PRINCIPAL)
    assert _facts(pg)[-1] == (12.0, status, True)


@pytest.mark.parametrize("status", [m.FactStatus.APPROVED, m.FactStatus.EDITED, m.FactStatus.AUTO_ACCEPTED])
def test_different_value_raises_a_conflict_and_keeps_the_fact(run_store, pg, status):  # AC-45, AC-46, AC-47
    _accept(run_store, pg, status)
    _run(run_store, pg, 14.0, run_id="r2")
    assert [f for f in _facts(pg) if f[2]] == [(12.0, status, True)]
    assert _observations(pg)[-1] == 14.0
    (key, payload, obs_id), = _items(pg, "r2")
    assert (key, payload["kind"], payload["accepted"]["value"]) == (KEY, "conflict", 12.0)
    with transaction(pg) as s:
        assert s.scalar(select(m.FieldObservation.value).where(m.FieldObservation.id == obs_id)) == 14.0
        fact = s.scalar(select(m.CompanyFact).where(m.CompanyFact.valid_to.is_(None)))
        assert payload["accepted"]["fact_id"] == fact.id


def test_review_routed_value_makes_one_conflict_item(run_store, pg):  # AC-48
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 14.0, run_id="r2", route="review")
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.APPROVED, True)]
    (key, payload, _), = _items(pg, "r2")
    assert (key, payload["kind"]) == (KEY, "conflict")


def test_identical_value_stores_nothing(run_store, pg):  # AC-49
    _accept(run_store, pg, m.FactStatus.APPROVED)
    before = len(_observations(pg))
    _run(run_store, pg, 12.0, run_id="r2")
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.APPROVED, True)]
    assert len(_observations(pg)) == before
    assert _items(pg, "r2") == []


def test_keep_accepted_closes_the_item_and_the_value_is_not_raised_again(run_store, pg):  # AC-50, AC-51
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 14.0, run_id="r2")
    record_review_decision(run_store, "r2", KEY, "reject", "bob", None)
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.APPROVED, True)]
    assert 14.0 in _observations(pg)
    with transaction(pg) as s:
        assert s.scalar(select(m.ReviewDecision.decision).where(m.ReviewDecision.run_id == "r2")) == m.DecisionKind.REJECT
    _run(run_store, pg, 14.0, run_id="r3")
    assert _items(pg, "r3") == []
    _run(run_store, pg, 15.0, run_id="r4")  # a different value raises a conflict again
    assert [p["kind"] for _, p, _ in _items(pg, "r4")] == ["conflict"]


def test_accept_new_supersedes_the_accepted_fact(run_store, pg):  # AC-52
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 14.0, run_id="r2")
    record_review_decision(run_store, "r2", KEY, "approve", "bob", None)
    facts = _facts(pg)
    assert facts[-1] == (14.0, m.FactStatus.APPROVED, True)
    assert (12.0, m.FactStatus.APPROVED, False) in facts


def test_trial_run_raises_no_conflict(run_store, pg):
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 14.0, run_id="t1", trial=True)
    assert _items(pg, "t1") == []
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.APPROVED, True)]


def test_pending_fact_follows_todays_rules(run_store, pg):
    _run(run_store, pg, 12.0, run_id="r1", route="review")  # pending, not accepted
    _run(run_store, pg, 14.0, run_id="r2")
    assert [f for f in _facts(pg) if f[2]] == [(14.0, m.FactStatus.AUTO_ACCEPTED, True)]
    assert _items(pg, "r2") == []


def test_a_value_without_a_run_still_supersedes(pg):
    """Source loads (no run) keep today's rule: the rule is about runs re-extracting a value."""
    with transaction(pg) as s:
        cid = ensure_universe_company(s, "acme")

    def obs(v):
        return ObservationIn(company_id=cid, field_id="revenue", field_version=1, source_kind=m.SourceKind.EXTRACTION,
                             period_end=FY24, value=v, value_state=m.ValueState.FOUND, route=m.Route.AUTO_ACCEPT)

    with transaction(pg) as s:
        record(s, [obs(12.0)])
    with transaction(pg) as s:
        record(s, [obs(14.0)])
    assert [f for f in _facts(pg) if f[2]] == [(14.0, m.FactStatus.AUTO_ACCEPTED, True)]


def test_run_review_count_includes_the_conflict(run_store, pg):
    from arp.orchestration.batch_runner import run_company_batch

    _accept(run_store, pg, m.FactStatus.APPROVED)
    universe = [CompanyRef(company_id="acme", name="Acme")]
    from arp.orchestration.job_manager import JobManager

    run_id = JobManager(run_store).create_run("extraction", {}, 1, companies=universe).run_id

    async def worker(company):
        return _row(14.0, run_id=run_id)

    import asyncio

    asyncio.run(run_company_batch(run_id, universe, run_store=run_store, worker=worker, result_to_json=dict, concurrency=1))
    assert [p["kind"] for _, p, _ in _items(pg, run_id)] == ["conflict"]
    assert run_store.load_manifest(run_id).review_count == 1


@pytest.fixture
def api(run_store, pg, tmp_path):
    settings = Settings(schema_registry_dir=tmp_path / "reg", second_review_sample_rate=0.0)
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[get_document_content_store] = lambda: None
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: CAROL
    yield TestClient(app)
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def test_queue_lists_the_conflict_kind(api, run_store, pg):
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 14.0, run_id="r2")
    r = api.get("/api/review/items", params={"run_id": "r2"})
    assert r.status_code == 200, r.text
    assert [i["kind"] for i in r.json()["items"]] == ["conflict"]


@pytest.mark.parametrize(("decision", "current"), [("reject", 12.0), ("approve", 14.0)])
def test_bare_body_decides_a_conflict(api, run_store, pg, decision, current):  # pinned interface 2
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 14.0, run_id="r2")
    r = api.post(f"/api/review/runs/r2/items/{KEY}/decision", json={"decision": decision})
    assert r.status_code == 200, r.text
    if r.json()["second_reasons"]:  # replacing a person's decision: a second approver confirms (review finding 1)
        app.dependency_overrides[current_user] = lambda: DAVE
        r = api.post(f"/api/review/runs/r2/items/{KEY}/decision", json={"decision": decision})
        assert r.status_code == 200, r.text
    assert [f for f in _facts(pg) if f[2]][0][0] == current


def test_bare_body_on_a_value_item_is_still_422(api, run_store, pg):
    _run(run_store, pg, 12.0, run_id="r1", route="review")
    r = api.post(f"/api/review/runs/r1/items/{KEY}/decision", json={"decision": "reject"})
    assert r.status_code == 422
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(m.ReviewDecision)) == 0


def test_accepting_new_over_a_person_s_decision_needs_a_second_review(api, run_store, pg):  # review finding 1
    _accept(run_store, pg, m.FactStatus.APPROVED)  # 12 approved by a person in r1
    _run(run_store, pg, 14.0, run_id="r2")
    r = api.post(f"/api/review/runs/r2/items/{KEY}/decision", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert "published_change" in r.json()["second_reasons"]
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.APPROVED, True)]  # not until a second reviewer agrees


def test_identical_value_routed_to_review_queues_nothing(run_store, pg):  # review finding 2, AC-49
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 12.0, run_id="r2", route="review")
    assert _items(pg, "r2") == []
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.APPROVED, True)]


def test_kept_value_routed_to_review_is_not_queued_again(run_store, pg):  # review finding 3, AC-51
    _accept(run_store, pg, m.FactStatus.APPROVED)
    _run(run_store, pg, 14.0, run_id="r2")
    record_review_decision(run_store, "r2", KEY, "reject", "bob", None)
    _run(run_store, pg, 14.0, run_id="r3", route="review")
    assert _items(pg, "r3") == []
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.APPROVED, True)]


def test_a_writer_that_loses_the_first_insert_race_raises_a_conflict(run_store, pg, monkeypatch):  # finding 4
    """Run B read no current fact, then run A's accepted 12 committed first: B's retry must not overwrite it."""
    import arp.db.observations as obs_db

    _accept(run_store, pg, m.FactStatus.AUTO_ACCEPTED)  # run A's 12, committed
    real, calls = obs_db._current, {"n": 0}

    def racing(session, o):  # B's first two looks (in record, then in _write_fact) still see no fact
        calls["n"] += 1
        return None if calls["n"] <= 2 else real(session, o)

    monkeypatch.setattr(obs_db, "_current", racing)
    _run(run_store, pg, 14.0, run_id="r2")
    monkeypatch.setattr(obs_db, "_current", real)
    assert [f for f in _facts(pg) if f[2]] == [(12.0, m.FactStatus.AUTO_ACCEPTED, True)]
    assert [p["kind"] for _, p, _ in _items(pg, "r2")] == ["conflict"]
