"""Argus step 1: adding companies to a flow registers them by LEI/ISIN/CIK; a list's own id becomes scheme USER."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.db.models import Company, CompanyIdentifier
from arp.db.session import engine

CSV = ("name,lei,isin,cik,sector,country,company_id\n"
       "Apple,HWUPKR0MPOU8FGXBT394,US0378331005,0000320193,Information Technology,US,AAPL-X\n"
       "Microsoft,,US5949181045,,Information Technology,US,\n"
       "SAP,529900D6BF99LW9R2E68,,,Information Technology,DE,\n"
       "Acme,,,,,,\n")


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", postgres_dsn=pg)


@pytest.fixture
def client(settings):
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


@pytest.fixture
def fid(client):
    return client.post("/api/argus/flows").json()["flow_id"]


def upload(client, fid, text, name="u.csv"):
    r = client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": (name, text)})
    assert r.status_code == 200, r.text
    return r.json()


def count(pg):
    with Session(engine(pg)) as s:
        return s.scalar(select(func.count()).select_from(Company))


def seed(pg, name, **ids):
    with Session(engine(pg)) as s, s.begin():
        c = Company(name=name)
        s.add(c)
        s.flush()
        for scheme, value in ids.items():
            s.add(CompanyIdentifier(company_id=c.id, scheme=scheme.upper(), value=value))
        return c.id


def identifiers(pg, company_id):
    with Session(engine(pg)) as s:
        return set(s.execute(select(CompanyIdentifier.scheme, CompanyIdentifier.value).where(
            CompanyIdentifier.company_id == company_id, CompanyIdentifier.valid_to.is_(None))).all())


def test_upload_registers_matched_rows_and_keeps_acme_unmatched(client, fid, pg):
    flow = upload(client, fid, CSV)
    assert [c["name"] for c in flow["companies"]] == ["Apple", "Microsoft", "SAP", "Acme"]
    assert [c["entity_id"] is not None for c in flow["companies"]] == [True, True, True, False]
    assert count(pg) == 3
    apple = flow["companies"][0]
    assert (apple["company_id"], apple["sector"], apple["country"]) == ("AAPL-X", "Information Technology", "US")
    assert flow["companies"][1]["company_id"] == flow["companies"][1]["entity_id"]  # no own id: the central id
    assert client.get(f"/api/argus/flows/{fid}").json()["companies"] == flow["companies"]
    assert [r["problem"] for r in flow["rows"]] == [None, None, None, "No identifier: add an ISIN, LEI or CIK"]
    assert flow["rows"][0]["identifiers"]["USER"] == ["AAPL-X"]


def test_user_id_attaches_to_the_existing_company(client, fid, pg):
    apple = seed(pg, "Apple", lei="HWUPKR0MPOU8FGXBT394")
    before = count(pg)
    upload(client, fid, "name,lei,company_id\nApple,HWUPKR0MPOU8FGXBT394,AAPL-X\n")
    assert count(pg) == before
    assert {("USER", "AAPL-X"), ("LEI", "HWUPKR0MPOU8FGXBT394")} <= identifiers(pg, apple)


def test_same_list_twice_gives_one_row_each(client, fid, pg):
    upload(client, fid, CSV)
    flow = upload(client, fid, CSV)
    assert [c["name"] for c in flow["companies"]] == ["Apple", "Microsoft", "SAP", "Acme"]
    assert count(pg) == 3


def test_user_id_owned_by_another_company_is_left_alone(client, fid, pg):
    other = seed(pg, "Other", user="1")
    flow = upload(client, fid, "name,isin,company_id\nMicrosoft,US5949181045,1\n")
    ms = flow["companies"][0]["entity_id"]
    assert ms is not None and ms != str(other)
    assert ("USER", "1") in identifiers(pg, other)
    assert ("USER", "1") not in identifiers(pg, ms)


def test_a_user_id_owned_elsewhere_is_not_the_row_key(client, fid, pg):
    upload(client, fid, "name,lei,company_id\nApple,HWUPKR0MPOU8FGXBT394,1\n")
    flow = upload(client, fid, "name,isin,company_id\nMicrosoft,US5949181045,1\n")
    apple, ms = flow["companies"]
    assert apple["company_id"] == "1" and ms["company_id"] == ms["entity_id"]


def test_matched_without_own_id_keeps_its_universe_id(client, fid, pg):
    seed(pg, "Apple", lei="HWUPKR0MPOU8FGXBT394", universe="AAPL")
    flow = client.post(f"/api/argus/flows/{fid}/companies", json={"company": {"name": "Apple", "lei": "HWUPKR0MPOU8FGXBT394"}}).json()
    assert flow["companies"][0]["company_id"] == "AAPL"


def test_conflicting_identifiers_create_nothing(client, fid, pg):
    seed(pg, "A", lei="529900D6BF99LW9R2E68")
    seed(pg, "B", isin="US5949181045")
    before = count(pg)
    flow = upload(client, fid, "name,lei,isin\nMixed,529900D6BF99LW9R2E68,US5949181045\n")
    assert flow["companies"][0]["entity_id"] is None
    assert count(pg) == before


def test_add_one_company_and_saved_universe(client, fid, settings):
    flow = client.post(f"/api/argus/flows/{fid}/companies", json={"company": {"name": "SAP", "lei": "529900D6BF99LW9R2E68"}}).json()
    assert [c["name"] for c in flow["companies"]] == ["SAP"]
    saved = settings.runs_dir / "_universes" / "u.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps([{"company_id": "MSFT", "name": "Microsoft", "isin": "US5949181045"}]))
    flow = client.post(f"/api/argus/flows/{fid}/companies", json={"universe_path": str(saved)}).json()
    assert [c["name"] for c in flow["companies"]] == ["SAP", "Microsoft"]
    outside = settings.runs_dir / "x.json"
    outside.write_text("[]")
    assert client.post(f"/api/argus/flows/{fid}/companies", json={"universe_path": str(outside)}).status_code == 400


def test_bad_file_is_400_and_unknown_flow_is_404(client, fid):
    assert client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.txt", "x")}).status_code == 400
    assert client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.json", "{")}).status_code == 400
    assert client.post("/api/argus/flows/nope/companies/upload", files={"file": ("u.csv", CSV)}).status_code == 404
