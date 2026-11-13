from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from typer.testing import CliRunner

from arp.api.auth import current_user
from arp.api.deps import settings_dep
from arp.api.main import app
from arp.cli import app as cli
from arp.config import Settings, get_settings
from arp.stewardship.intake import ENGAGEMENT_COLUMNS, VOTE_COLUMNS
from tests.conftest import PRINCIPAL

URL = "/api/stewardship/intake"


@pytest.fixture
def client(pg, monkeypatch):
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")  # AC-8 creates the companies through the records endpoint
    get_settings.cache_clear()
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _xlsx(sheets: dict[str, list[dict]], columns: dict[str, list[str]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(columns[name])
        for r in rows:
            ws.append([r.get(c) for c in columns[name]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _engagement_batch() -> dict:
    eng = [{"external_id": str(i), "company_id": f"C{i}", "theme": "climate", "started_at": "2026-01-05"} for i in (1, 2)]
    obj = [{"external_id": f"o{i}", "engagement_external_id": str(1 + i % 2), "description": "d", "objective_type": "strategic"} for i in (1, 2, 3)]
    act = [{"external_id": f"a{i}", "engagement_external_id": "1", "occurred_at": "2026-02-01", "summary": "s"} for i in range(1, 6)]
    return {"engagements": eng, "objectives": obj, "activities": act}


def _companies(client, *ids):
    for c in ids:
        assert client.post("/api/engagement/records", json={"company_id": c, "name": c}).status_code == 200


def _votes(n=3, **kw) -> list[dict]:
    return [{"external_id": f"d{i}", "isin": "US0000000001", "issuer_name": "X", "meeting_date": "2026-05-01", "item_number": i,
             "description": f"item {i}", "management_recommendation": "for", "vote": "for", **kw} for i in range(1, n + 1)]  # fmt: skip


def _file(data: bytes):
    return {"file": ("x.xlsx", data, "application/octet-stream")}


def test_engagements_xlsx_ac8(client):
    _companies(client, "C1", "C2")
    r = client.post(f"{URL}/engagements.xlsx", files=_file(_xlsx(_engagement_batch(), ENGAGEMENT_COLUMNS)))
    assert (r.status_code, r.json()) == (200, {"created": 10, "updated": 0, "unchanged": 0, "rejected": []})


def test_engagements_json_ac15(client):
    _companies(client, "C1")
    batch = _engagement_batch()
    batch = {"engagements": batch["engagements"][:1], "objectives": batch["objectives"][1:2]}
    r = client.post(f"{URL}/engagements", json=batch)
    assert (r.status_code, r.json()) == (200, {"created": 2, "updated": 0, "unchanged": 0, "rejected": []})


def test_engagements_json_unknown_company_ac14(client):
    r = client.post(f"{URL}/engagements", json={"engagements": [{"external_id": "1", "company_id": "NOPE", "isin": "XX0000000000", "theme": "climate"}]})
    assert r.status_code == 422
    (rej,) = r.json()["rejected"]
    assert (rej["sheet"], rej["row"], rej["reason"]) == ("engagements", 1, "unknown company")


def test_votes_json_rationale_ac16(client):
    r = client.post(f"{URL}/votes", json={"votes": _votes(1, vote="against", rationale="")})
    assert r.status_code == 422
    (rej,) = r.json()["rejected"]
    assert (rej["field"], rej["reason"]) == ("rationale", "rationale required when voting against management")


def test_votes_xlsx_ac17(client):
    r = client.post(f"{URL}/votes.xlsx", files=_file(_xlsx({"votes": _votes()}, {"votes": VOTE_COLUMNS})))
    assert (r.status_code, r.json()) == (200, {"created": 7, "updated": 0, "unchanged": 0, "rejected": []})


@pytest.mark.parametrize("path,body", [("engagements", [1]), ("engagements", {"engagements": 5}), ("votes", [1]), ("votes", {"votes": "x"})])
def test_wrong_shape_is_422(client, path, body):
    assert client.post(f"{URL}/{path}", json=body).status_code == 422


def test_bad_workbook_is_422_and_writes_nothing(client):
    r = client.post(f"{URL}/engagements.xlsx", files=_file(b"not xlsx"))
    assert r.status_code == 422
    assert r.json()["created"] == 0 and r.json()["rejected"][0]["reason"] == "not a valid xlsx workbook"


@pytest.mark.parametrize("kind", ["engagements", "votes"])
def test_template(client, kind):
    r = client.get(f"{URL}/template", params={"kind": kind})
    assert r.status_code == 200 and r.headers["content-disposition"] == f"attachment; filename={kind}_template.xlsx"
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert load_workbook(io.BytesIO(r.content)).sheetnames
    assert client.get(f"{URL}/template", params={"kind": "x"}).status_code == 422


def test_cli_intake_ac18(client, tmp_path):
    _companies(client, "C1", "C2")
    f = tmp_path / "e.xlsx"
    f.write_bytes(_xlsx(_engagement_batch(), ENGAGEMENT_COLUMNS))
    res = CliRunner().invoke(cli, ["stewardship", "intake", str(f), "--kind", "engagements"])
    assert res.exit_code == 0, res.output
    assert "created 10, updated 0, unchanged 0, rejected 0" in res.output
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"nope")
    res = CliRunner().invoke(cli, ["stewardship", "intake", str(bad), "--kind", "votes"])
    assert res.exit_code == 1 and "rejected 1" in res.output


def test_viewer_forbidden_ac19(tmp_path, pg):
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"token": "tv", "user_id": "u", "name": "V", "role": "viewer"}]}))
    app.dependency_overrides.clear()  # an autouse fixture signs everyone in
    app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users, auth_mode="local")
    try:
        r = TestClient(app).post(f"{URL}/engagements", json={}, headers={"Authorization": "Bearer tv"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403
