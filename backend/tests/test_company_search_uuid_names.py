"""showcase-stewardship-fixes AC-68, AC-69: a record named only by a UUID is left out of the company search."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from arp.api.main import app
from arp.db.models import Company
from arp.db.session import engine

UUID_NAME = "3f2b8c1e-5d47-4a9b-8c21-0a1b2c3d4e5f"


def test_uuid_named_company_not_listed_but_still_readable(pg):
    with Session(engine(pg)) as s, s.begin():
        hidden, shown = Company(name=UUID_NAME), Company(name="Acme 3f2b")
        s.add_all([hidden, shown])
        s.flush()
        hidden_id = hidden.id
    client = TestClient(app)
    names = [c["name"] for c in client.get("/api/companies", params={"q": ""}).json()]
    assert "Acme 3f2b" in names and UUID_NAME not in names  # AC-68
    r = client.get(f"/api/companies/{hidden_id}")
    assert r.status_code == 200 and r.json()["name"] == UUID_NAME  # AC-69 (must not change)
