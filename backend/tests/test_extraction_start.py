"""/api/extraction/start hands each profile to that pipeline's own start endpoint."""

import asyncio

import pytest
from fastapi import HTTPException

from arp.api.routers import extraction, financials, tnfd, transition_plan
from arp.schemas.datapoints import DataPointSchema


def _fake(name, calls):
    async def start(req, **kwargs):
        calls.append((name, req, kwargs))
        return {"run_id": f"{name}-1", "company_count": 1}

    return start


@pytest.fixture
def calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(extraction, "start_extraction_run", _fake("custom", calls))
    monkeypatch.setattr(financials, "start_financials_extraction_run", _fake("financials", calls))
    monkeypatch.setattr(tnfd, "start_tnfd_extraction_run", _fake("tnfd", calls))
    monkeypatch.setattr(transition_plan, "start_transition_plan_run", _fake("transition_plan", calls))
    return calls


def _start(**body):
    req = extraction.StartRequest(universe_path="u.csv", decision_framework_id="fw", **body)
    return asyncio.run(extraction.start_extraction(req, settings=None, run_store=None, registry=None, decision_store=None, xbrl_source="xbrl"))


def test_each_profile_reaches_its_pipeline(calls):
    schema = DataPointSchema.model_validate({"schema_id": "s", "name": "s", "fields": []})
    assert _start(profile="custom", datapoint_schema=schema)["run_type"] == "extraction"
    assert _start(profile="financials")["run_type"] == "financials"
    assert _start(profile="tnfd", as_of="FY2025")["run_type"] == "tnfd"
    started = _start(profile="transition_plan")
    assert started == {"run_id": "transition_plan-1", "company_count": 1, "run_type": "transition_plan"}

    assert [c[0] for c in calls] == ["custom", "financials", "tnfd", "transition_plan"]
    assert calls[0][1].datapoint_schema == schema
    assert calls[1][2]["xbrl_source"] == "xbrl"
    assert calls[2][1].as_of == "FY2025"
    assert "xbrl_source" not in calls[3][2]
    assert all(c[1].universe_path == "u.csv" and c[1].decision_framework_id == "fw" for c in calls)


@pytest.mark.parametrize("profile", ["custom", "tnfd"])
def test_missing_profile_input_is_a_400(calls, profile):
    with pytest.raises(HTTPException) as err:
        _start(profile=profile)
    assert err.value.status_code == 400
    assert calls == []
