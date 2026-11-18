"""showcase-stewardship-fixes AC-1..AC-6: a list's `isic_code` reaches the registry company."""

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings

L1, L2, L3 = "5299000ACMEPOWER1065", "5299000ACMESTEEL2085", "5299000ACMEOIL003076"  # ISO 17442 checksums


@pytest.fixture
def client(tmp_path, pg):
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", postgres_dsn=pg)
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


def upload(client, text):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    r = client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", text)})
    assert r.status_code == 200, r.text
    return r.json()["companies"][0]["entity_id"]


def test_new_company_keeps_isic_and_is_in_scope(client):  # AC-1, AC-2
    e = upload(client, f"name,lei,isic_code\nAcme Power AG,{L1},3510\n")
    assert client.get(f"/api/companies/{e}").json()["isic_code"] == "3510"
    t = client.get(f"/api/companies/{e}/transition").json()
    assert (t["in_scope"], t["sector"]) == (True, "Power & Utilities")


def test_existing_company_without_code_gets_it_and_a_code_is_never_overwritten(client):  # AC-3, AC-4
    e = upload(client, f"name,lei\nAcme Steel AG,{L2}\n")
    assert client.get(f"/api/companies/{e}").json()["isic_code"] is None
    assert upload(client, f"name,lei,isic_code\nAcme Steel AG,{L2},2410\n") == e
    assert client.get(f"/api/companies/{e}").json()["isic_code"] == "2410"
    upload(client, f"name,lei,isic_code\nAcme Steel AG,{L2},3510\n")
    assert client.get(f"/api/companies/{e}").json()["isic_code"] == "2410"


def test_leading_zero_kept(client):  # AC-5
    e = upload(client, f"name,lei,isic_code\nAcme Oil AG,{L3},0610\n")
    assert client.get(f"/api/companies/{e}").json()["isic_code"] == "0610"


def test_list_without_isic_column_is_out_of_scope(client):  # AC-6 (must not change)
    e = upload(client, f"name,lei\nAcme Power AG,{L1}\n")
    t = client.get(f"/api/companies/{e}/transition").json()
    assert (t["in_scope"], t["reason"]) == (False, "No ISIC code")
