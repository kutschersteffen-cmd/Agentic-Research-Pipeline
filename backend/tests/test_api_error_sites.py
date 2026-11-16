"""security-errors-ssrf PR 2: the converted raise sites in routers (AC-49..AC-54)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.api.routers.signals import APP_RUNNABLE
from arp.schemas.common import RunManifest
from arp.signal_lab.methods.base import method_names
from arp.storage.run_store import RunStore
from tests.test_api_signals import _post_run, _recipe_file, client, prices_csv  # noqa: F401

pytestmark = pytest.mark.usefixtures("pg")


@pytest.fixture
def themes(tmp_path, pg):
    rs = RunStore(pg, tmp_path / "runs")
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="approver")
    yield TestClient(app)
    app.dependency_overrides.clear()


def _review(c, key, decision):
    return c.post("/api/themes/runs/r1/review", json={"item_key": key, "decision": decision})


def test_ac50_unknown_decision(themes):
    r = _review(themes, "k", "maybe")
    assert (r.status_code, r.json()["detail"]) == (400, "decision must be one of ['approve', 'edit', 'escalate', 'reject']")


def test_ac51_workbench_key(themes):
    r = _review(themes, "held:x", "approve")
    assert (r.status_code, r.json()["detail"]) == (400, "decide this item through the review workbench")


def test_ac52_workbench_run_type(themes):
    r = _review(themes, "k", "approve")
    assert (r.status_code, r.json()["detail"]) == (400, "decide extraction items through the review workbench")


# Spec says 400 for AC-53/AC-54; on main the router's `except ValueError -> _http` already answers 422.
# Pinned at 422 (behaviour unchanged); raised as a Spec question in the PR.
def test_ac53_invalid_recipe(client, tmp_path):  # noqa: F811
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="analyst")
    prices_csv(tmp_path / "p.csv", 40)
    rec = tmp_path / "r.json"
    rec.write_text("{}")
    r = _post_run(client, rec, tmp_path / "p.csv")
    app.dependency_overrides.clear()
    assert (r.status_code, r.json()["detail"]) == (422, "invalid recipe: " + "; ".join(
        f"{f}: Field required" for f in
        ("category", "method", "text_source", "params", "universe", "window_start", "window_end")))


def test_ac54_method_not_app_runnable(client, tmp_path):  # noqa: F811
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="analyst")
    dates = prices_csv(tmp_path / "p.csv", 40)
    method = sorted(set(method_names()) - APP_RUNNABLE)[0]
    rec = _recipe_file(tmp_path / "r.json", dates, method=method)
    r = _post_run(client, rec, tmp_path / "p.csv")
    app.dependency_overrides.clear()
    assert (r.status_code, r.json()["detail"]) == (
        422, f"{method} runs from the CLI (arp signals run) or a notebook (arp.signal_lab.lab.Lab), not the app")
