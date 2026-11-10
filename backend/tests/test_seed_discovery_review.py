"""The evaluator's seed: one finished discovery run with three open review items (spec: discovery-review-queue, DRUN)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.config import Settings
from arp.storage.run_store import RunStore

pytestmark = pytest.mark.usefixtures("pg")
SCRIPT = Path(__file__).parents[1] / "scripts" / "seed_discovery_review.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_discovery_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_writes_run_items_files_and_manifest(tmp_path, pg):
    settings = Settings(documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state", runs_dir=tmp_path / "runs")
    rs = RunStore(pg, settings.runs_dir)
    run_id = _load().main(settings=settings, run_store=rs)

    files = sorted((settings.documents_dir / "C2" / "10-K").glob("*.pdf"))
    shas = sorted(hashlib.sha256(f.read_bytes()).hexdigest() for f in files)
    assert len(files) == 2
    want = sorted(["no_documents:C1", *(f"discovered:C2:{s}" for s in shas)])
    assert sorted({q["item_key"] for q in rs.read_review_queue(run_id)}) == want

    manifest = json.loads((settings.discovery_state_dir / "C2.json").read_text())
    assert set(manifest) == {"https://c2.example/report-a.pdf", "https://c2.example/report-b.pdf"}
    assert all(e["review"] is None and e["company_match"] == "none" for e in manifest.values())
    assert rs.load_manifest(run_id).review_count == 3

    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="analyst")
    try:
        r = TestClient(app).get("/api/review/items", params={"run_id": run_id})
    finally:
        app.dependency_overrides.clear()
    assert len(r.json()["items"]) == 3
