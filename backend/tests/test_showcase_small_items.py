"""Showcase defect 12 (backend): 12b a monthly run that ran is recorded and can be read back; 12c a Decision
Studio dataset says when it was added."""
import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_decision_store, get_portfolio_store, settings_dep
from arp.api.main import app
from arp.portfolio.monthly_run import run_month
from arp.storage.decision_store import DecisionStore
from tests.test_monthly_run import MONTH, _ids, _ready, settings, store  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures("pg")
LAST = "/api/portfolio/monthly-run/last"


@pytest.fixture
def client(store, settings):  # noqa: F811
    app.dependency_overrides.update({get_portfolio_store: lambda: store, settings_dep: lambda: settings})
    yield TestClient(app)
    app.dependency_overrides.pop(get_portfolio_store, None)
    app.dependency_overrides.pop(settings_dep, None)


def test_no_monthly_run_yet_is_null(client):  # AC-139
    r = client.get(LAST)
    assert (r.status_code, r.json()) == (200, None)


def test_a_run_that_ran_is_recorded_and_a_blocked_one_is_not(client, store, settings):  # noqa: F811
    assert run_month(store, settings, MONTH, portfolio_ids=_ids(store)).status == "blocked"
    assert client.get(LAST).json() is None
    before = store.list_governance_events()
    _ready(store)
    ran = client.post("/api/portfolio/monthly-run", json={"month": MONTH, "portfolio_ids": _ids(store)}).json()
    assert ran["status"] == "ran"
    last = client.get(LAST).json()
    assert set(last) == {"month", "at", "alerts", "triggers"}
    assert (last["month"], last["alerts"], last["triggers"]) == (MONTH, ran["alerts"], ran["triggers"])
    assert last["at"] >= before[-1]["at"]
    assert store.list_governance_events()[: len(before)] == before  # appended, nothing rewritten
    assert client.post("/api/portfolio/monthly-run", json={"month": "2001-01", "portfolio_ids": _ids(store)}).json()["status"] == "blocked"
    assert client.get(LAST).json() == last


def test_a_dataset_says_when_it_was_added(tmp_path):
    decisions = DecisionStore(tmp_path / "decisions")
    app.dependency_overrides[get_decision_store] = lambda: decisions
    try:
        client = TestClient(app)
        for _ in range(2):
            r = client.post("/api/decision/datasets", files={"file": ("companies.csv", b"Company,Score\nAcme,1\nGlobex,2\n", "text/csv")})
            assert r.status_code == 200, r.text
        listed = client.get("/api/decision/datasets").json()
    finally:
        app.dependency_overrides.pop(get_decision_store, None)
    assert [d["name"] for d in listed] == ["companies.csv", "companies.csv"]
    assert all(isinstance(d["created_at"], str) and "T" in d["created_at"] for d in listed)
    assert listed[0]["created_at"] != listed[1]["created_at"]
