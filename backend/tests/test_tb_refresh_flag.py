"""showcase-stewardship-fixes AC-21..AC-23: the matrix and cell answers say whether sources are re-checked."""

import shutil

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings, get_settings
from arp.storage.run_store import RunStore
from arp.transition_barrier import dataset
from tests.transition_barrier_helpers import FIXTURES


@pytest.fixture
def client_with(tmp_path, monkeypatch, pg):
    target = tmp_path / "transition_barrier"
    shutil.copytree(FIXTURES, target)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(target))
    get_settings.cache_clear()
    dataset.reset_caches()
    app.dependency_overrides[get_run_store] = lambda: RunStore(pg, tmp_path / "runs")

    def make(enabled: bool) -> TestClient:
        app.dependency_overrides[settings_dep] = lambda: Settings(transition_barrier_refresh_enabled=enabled)
        return TestClient(app)

    yield make
    for dep in (get_run_store, settings_dep):
        app.dependency_overrides.pop(dep, None)
    get_settings.cache_clear()
    dataset.reset_caches()


@pytest.mark.parametrize("enabled", [False, True])
def test_matrix_and_cell_carry_refresh_enabled(client_with, enabled):  # AC-21, AC-22, AC-23
    client = client_with(enabled)
    assert client.get("/api/transition-barrier/matrix").json()["refresh_enabled"] is enabled
    r = client.get("/api/transition-barrier/cells/STL-R1/European%20Union")
    assert r.status_code == 200, r.text
    assert r.json()["refresh_enabled"] is enabled
