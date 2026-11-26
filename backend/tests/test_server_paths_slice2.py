"""server-paths-upload-limits slice 2: ETF overlap and the revenue catalogue read only uploaded files
(unit side of AC-26 to AC-31, AC-64, AC-67, AC-68, AC-72, AC-73)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.main import app
from tests.conftest import PRINCIPAL

HOLDINGS = "ticker,name,weight\nAAA,Alpha,60\nBBB,Beta,40\n"
NOT_HOLDINGS = {"detail": "Holdings file must be an uploaded file."}
NOT_CATALOGUE = {"detail": "Catalogue file must be an uploaded file."}
NO_TAXONOMY = {"detail": "Taxonomy not found: none"}
MISSING = "/nonexistent-arp/x.csv"
COMPANIES = [{"company_id": "a", "name": "A"}]


@pytest.fixture
def env(pg, tmp_path, monkeypatch):
    for name, sub in [("RUNS_DIR", "runs"), ("TAXONOMIES_DIR", "tax")]:
        monkeypatch.setenv(f"ARP_{name}", str(tmp_path / sub))
    from arp.config import get_settings

    get_settings.cache_clear()
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    app.dependency_overrides[deps.get_registry] = lambda: None
    client = TestClient(app, raise_server_exceptions=False)
    outside = tmp_path / "outside.csv"
    outside.write_text(HOLDINGS)
    uploaded = [client.post("/api/universe/raw-upload", files={"file": (f"h{i}.csv", HOLDINGS.encode())}).json()["path"]
                for i in (1, 2)]
    yield client, uploaded, str(outside)
    app.dependency_overrides.clear()


def test_etf_overlap_reads_uploaded_holdings_only(env):
    client, (h1, h2), outside = env
    for other in (outside, MISSING, ""):  # AC-26, AC-27, AC-73
        r = client.post("/api/etf-overlap", json={"funds": {"a": h1, "b": other}})
        assert (r.status_code, r.json()) == (400, NOT_HOLDINGS), other
    assert client.post("/api/etf-overlap", json={"funds": {"a": h1, "b": h2}}).status_code == 200  # AC-28
    r = client.post("/api/etf-overlap", json={"funds": {"a": outside}})  # AC-64
    assert (r.status_code, r.json()) == (400, {"detail": "Provide at least two funds to compare."})


def test_suggest_mapping_reads_an_uploaded_catalogue_only(env):
    client, (c, _), outside = env
    for path in (outside, MISSING, ""):  # AC-29, AC-30, AC-68
        r = client.post("/api/revenue-catalogue/suggest-mapping", json={"taxonomy_id": "none", "catalogue_path": path})
        assert (r.status_code, r.json()) == (400, NOT_CATALOGUE), path
    r = client.post("/api/revenue-catalogue/suggest-mapping", json={"taxonomy_id": "none", "catalogue_path": c})
    assert (r.status_code, r.json()) == (404, NO_TAXONOMY)  # AC-67


def test_theme_run_reads_an_uploaded_catalogue_only(env):
    client, (c, _), outside = env
    body = {"taxonomy_id": "none", "companies": COMPANIES}
    r = client.post("/api/themes/runs", json={**body, "revenue_catalogue_path": outside})  # AC-31
    assert (r.status_code, r.json()) == (400, NOT_CATALOGUE)
    for path in ("", c):  # AC-72
        r = client.post("/api/themes/runs", json={**body, "revenue_catalogue_path": path})
        assert (r.status_code, r.json()) == (404, NO_TAXONOMY), path
