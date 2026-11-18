"""Bilateral picks (spec stewardship-three-tiers, PR C)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("zen")

from arp.api.auth import current_user  # noqa: E402
from arp.api.deps import get_stream_store, settings_dep  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.config import Settings, get_settings  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.tiers import PickStore  # noqa: E402
from tests.conftest import PRINCIPAL  # noqa: E402

URL = "/api/stewardship/tiers"
pytestmark = pytest.mark.usefixtures("sample_house_universe")


@pytest.fixture
def root():
    return get_settings().stewardship_streams_dir


@pytest.fixture
def client(pg, root, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")  # get_engagement_store is cached for the whole session
    get_settings.cache_clear()
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)  # cached too
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _change(body: dict, issuer_id: str) -> dict | None:
    return next((c for c in body["changes"] if c["issuer_id"] == issuer_id), None)


def test_pick_confirm_withdraw(client, root):
    # AC-50 to AC-55: a pick is only a proposal until the tier confirm, and withdrawing returns to the rules
    r = client.post(f"{URL}/bilateral", json={"issuer_id": "SYN01", "reason": "CEO change"})
    assert (r.status_code, r.json()) == (200, {"picked": "SYN01"})
    body = client.get(URL).json()
    change = _change(body, "SYN01")
    assert (change["tier"], change["rule"], change["reason"], change["current_tier"]) == (
        "bilateral",
        "manual",
        "Picked by Test: CEO change",
        None,
    )
    [pick] = body["picks"]
    assert {k: v for k, v in pick.items() if k != "at"} == {
        "issuer_id": "SYN01",
        "name": "Synthetic Company 01",
        "reason": "CEO change",
        "by": "Test",
    }
    assert not (root / "tier_assignments.jsonl").exists()  # AC-51

    assert client.post(f"{URL}/confirm", json={"issuer_ids": ["SYN01"]}).json() == {"confirmed": 1}
    body = client.get(URL).json()
    row = next(a for a in body["assignments"] if a["issuer_id"] == "SYN01")
    assert (row["tier"], row["rule"], row["confirmed_by"]) == ("bilateral", "manual", "Test")
    assert _change(body, "SYN01") is None

    assert client.post(f"{URL}/bilateral/SYN01/withdraw").json() == {"withdrawn": "SYN01"}
    body = client.get(URL).json()
    change = _change(body, "SYN01")
    assert body["picks"] == []
    assert (change["tier"], change["rule"], change["current_tier"]) == ("letter", "default", "bilateral")
    assert next(a for a in body["assignments"] if a["issuer_id"] == "SYN01")["tier"] == "bilateral"


@pytest.mark.parametrize(
    ("path", "payload", "detail"),
    [
        ("/bilateral", {"issuer_id": "SYN01", "reason": "   "}, "A bilateral pick needs a reason"),  # AC-56
        ("/bilateral", {"issuer_id": "NOPE", "reason": "x"}, "Not in the house universe: NOPE"),  # AC-57
        (
            "/bilateral",
            {"issuer_id": "SYN01", "reason": "x" * 501},
            "A bilateral pick reason has at most 500 characters",
        ),  # AC-60
        ("/bilateral/SYN02/withdraw", None, "SYN02 has no bilateral pick"),  # AC-59
    ],
)
def test_pick_errors(client, path, payload, detail):
    r = client.post(URL + path, json=payload)
    assert (r.status_code, r.json()["detail"]) == (422, detail)


def test_second_pick_is_refused(client):
    # AC-58
    client.post(f"{URL}/bilateral", json={"issuer_id": "SYN01", "reason": "CEO change"})
    r = client.post(f"{URL}/bilateral", json={"issuer_id": "SYN01", "reason": "again"})
    assert (r.status_code, r.json()["detail"]) == (422, "SYN01 is already picked for bilateral")


def test_rule_preview_ignores_picks(client, root):
    # AC-64: calibration compares rule versions only
    from arp.stewardship.policies import PolicyStore

    client.post(f"{URL}/bilateral", json={"issuer_id": "SYN01", "reason": "CEO change"})
    graph = PolicyStore(root).active("coverage_rules")
    body = client.post("/api/stewardship/studio/coverage/preview", json={"graph": graph}).json()
    assert body["changes"] == []
    assert next(a for a in body["assignments"] if a["issuer_id"] == "SYN01")["rule"] == "default"
    assert body["distribution_active"] == {"Bilateral": 2, "Letter": 10}


def test_viewer_cannot_pick(tmp_path, pg):
    # AC-61
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"token": "tv", "user_id": "u", "name": "V", "role": "viewer"}]}))
    app.dependency_overrides.clear()  # an autouse fixture signs everyone in
    app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users, auth_mode="local")
    try:
        r = TestClient(app).post(
            f"{URL}/bilateral", json={"issuer_id": "SYN01", "reason": "x"}, headers={"Authorization": "Bearer tv"}
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403


def test_log_keeps_who_picked_and_who_withdrew(tmp_path):
    # AC-63: append-only, one event per action
    store = PickStore(tmp_path)
    store.pick("SYN01", "CEO change", "A", {"SYN01"})
    store.withdraw("SYN01", "B")
    events = [json.loads(line) for line in store.path.read_text().splitlines()]
    assert [(e["event"], e["by"]) for e in events] == [("picked", "A"), ("withdrawn", "B")]
    assert store.standing() == []


def test_pick_outside_the_universe_is_listed_but_proposes_nothing(tmp_path, pg):
    # AC-67
    from arp.api.routers.stewardship import get_tiers
    from arp.storage.engagement_store import EngagementStore

    streams = StreamStore(tmp_path / "streams")
    PickStore(streams.root).pick("X", "gone", "A", {"X"})
    body = get_tiers(streams, EngagementStore(tmp_path / "e"))
    assert [(p["issuer_id"], p["name"]) for p in body["picks"]] == [("X", None)]
    assert _change(body, "X") is None
