from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.snapshots import schema
from arp.snapshots.build import build_snapshot, dataset_path, snapshot_dir
from arp.snapshots.client import SnapshotClient, SnapshotHashMismatch
from arp.snapshots.schema import SnapshotManifest
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from tests.test_snapshots_build import AS_OF, World, _ingest

READER = Principal(user_id="svc_r", name="R", role="viewer", roles=["snapshot_reader"])
FULL = Principal(user_id="svc_f", name="F", role="viewer", roles=["snapshot_reader", "holdings_reader"])
CUTOFF = "2026-11-02T00:00:00.000000+00:00"
BASE = "/api/v1/snapshots"


@pytest.fixture
def build(tmp_path):
    env = PortfolioStore(tmp_path / "pf"), RunStore(tmp_path / "runs"), IdentifierMapStore(tmp_path / "idmap.jsonl")
    _ingest(env, "index", "IX1")
    _ingest(env, "portfolio", "PF1")
    world = World()
    return lambda **kw: build_snapshot(AS_OF, root=tmp_path / "store", portfolio_store=env[0],
                                       facts_as_of=world.facts_as_of, cutoff=CUTOFF, **kw)


@pytest.fixture
def root(tmp_path, build):
    build()
    root = tmp_path / "store"
    app.dependency_overrides[settings_dep] = lambda: Settings(snapshot_store_dir=root, runs_dir=tmp_path / "runs")
    yield root
    app.dependency_overrides.pop(settings_dep, None)


def as_(principal):
    app.dependency_overrides[current_user] = lambda: principal
    return TestClient(app)


def test_manifest_contract(root):
    body = as_(FULL).get(f"{BASE}/2026-10/manifest").json()
    assert set(body) == set(SnapshotManifest.model_fields)
    assert SnapshotManifest.model_validate(body).snapshot_id == "2026-10.r1"


def test_list_and_latest(root):
    snapshot_dir(root, "2026-10", 2).mkdir()  # an incomplete revision is never exposed
    c = as_(READER)
    assert c.get(BASE).json() == {"months": [{"month": "2026-10", "latest_revision": 1, "snapshot_id": "2026-10.r1"}]}
    assert c.get(f"{BASE}/latest").json()["snapshot_id"] == "2026-10.r1"
    assert c.get(f"{BASE}/2026-10/manifest", params={"revision": 2}).status_code == 404
    assert c.get(f"{BASE}/2026-09/manifest").status_code == 404


def test_latest_404_without_snapshots(root, tmp_path):
    app.dependency_overrides[settings_dep] = lambda: Settings(snapshot_store_dir=tmp_path / "empty")
    assert as_(READER).get(f"{BASE}/latest").status_code == 404


def test_dataset_etag_is_hash(root):
    c = as_(FULL)
    m = SnapshotManifest.model_validate(c.get(f"{BASE}/2026-10/manifest").json())
    entry = next(d for d in m.datasets if d.name == "esg_signals")
    for fmt, media in (("csv", "text/csv"), ("jsonl", "application/x-ndjson")):
        r = c.get(f"{BASE}/2026-10/esg_signals", params={"format": fmt})
        assert r.status_code == 200
        assert r.headers["etag"] == f'"{entry.files[fmt]}"'
        assert r.headers["content-type"].startswith(media)
    assert c.get(f"{BASE}/2026-10/nope").status_code == 404
    assert c.get(f"{BASE}/2026-10/esg_signals", params={"major": 9}).status_code == 404
    assert c.get(f"{BASE}/2026-10/esg_signals", params={"revision": 5}).status_code == 404


def test_reader_without_holdings_reader_gets_403(root):
    c = as_(READER)
    assert c.get(f"{BASE}/2026-10/esg_signals").status_code == 200
    r = c.get(f"{BASE}/2026-10/portfolio_holdings")
    assert r.status_code == 403 and "holdings_reader" in r.json()["detail"]


def test_no_snapshot_reader_403(root):
    c = TestClient(app)  # the conftest approver, no grants
    for path in ("", "/latest", "/2026-10/manifest", "/2026-10/esg_signals"):
        assert c.get(BASE + path).status_code == 403


@pytest.mark.parametrize("month", ["..%2F", "2026-1", "2026-13", "..", "x" * 7])
def test_bad_month_400(root, month):
    r = as_(FULL).get(f"{BASE}/{month}/manifest")
    assert r.status_code in (400, 404)
    assert "snapshot_id" not in r.text


def test_pull_writes_verified_files(root, tmp_path):
    dest = tmp_path / "dest"
    paths = SnapshotClient("", None, http=as_(FULL)).pull("2026-10", "all", dest)
    assert sorted(p.name for p in paths) == [f"{d}.v1.csv" for d in sorted(schema.DATASETS)]
    assert (dest / "2026-10" / "manifest.json").exists()
    m = SnapshotManifest.model_validate_json((dest / "2026-10" / "manifest.json").read_text())
    assert m.snapshot_id == "2026-10.r1"


def test_pull_refuses_hash_mismatch(root, tmp_path):
    dataset_path(root, "2026-10", 1, "esg_signals", "csv", 1).write_bytes(b"tampered\n")
    dest = tmp_path / "dest"
    with pytest.raises(SnapshotHashMismatch, match="esg_signals"):
        SnapshotClient("", None, http=as_(FULL)).pull("2026-10", "all", dest)
    assert not (dest / "2026-10" / "esg_signals.v1.csv").exists()


def test_rows_are_verified_jsonl(root):
    m, rows = SnapshotClient("", None, http=as_(FULL)).rows("2026-10", "esg_signals")
    assert m.snapshot_id == "2026-10.r1" and len(rows) == 3 and rows[0]["field_id"] == "f1"


def test_consumer_on_old_major_still_pulls(root, build, tmp_path, monkeypatch):
    v1 = schema.SCHEMAS[1]
    monkeypatch.setattr(schema, "SCHEMAS", {1: {**v1, "retire_after": "2026-11"}, 2: {**v1, "version": "2.0"}})
    monkeypatch.setattr(schema, "CURRENT_MAJOR", 2)
    build(revision=2, supersedes="2026-10.r1")
    paths = SnapshotClient("", None, http=as_(FULL)).pull("2026-10", ["esg_signals"], tmp_path / "dest", major=1)
    assert [p.name for p in paths] == ["esg_signals.v1.csv"]


def test_symlinked_file_is_refused(root, tmp_path):
    path = dataset_path(root, "2026-10", 1, "esg_signals", "csv", 1)
    outside = tmp_path / "secret.csv"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    assert as_(FULL).get(f"{BASE}/2026-10/esg_signals").status_code == 404


def test_file_missing_on_disk_is_404(root):
    dataset_path(root, "2026-10", 1, "esg_signals", "jsonl", 1).unlink()
    assert as_(FULL).get(f"{BASE}/2026-10/esg_signals", params={"format": "jsonl"}).status_code == 404


def test_missing_format_hash(root, monkeypatch):
    import arp.api.routers.snapshots as R

    real = R.read_manifest

    def no_csv_hash(*a, **kw):
        m = real(*a, **kw)
        return m and m.model_copy(update={"datasets": [d.model_copy(update={"files": {"jsonl": d.files["jsonl"]}})
                                                       for d in m.datasets]})

    monkeypatch.setattr(R, "read_manifest", no_csv_hash)
    c = as_(FULL)
    assert c.get(f"{BASE}/2026-10/esg_signals").status_code == 404
    with pytest.raises(SnapshotHashMismatch, match="no csv hash"):
        SnapshotClient("", None, http=c).pull("2026-10", ["esg_signals"], root / "dest")


@pytest.mark.parametrize("url", ["http://arp.example", "ftp://localhost", "localhost:8000", ""])
def test_client_refuses_plain_http_except_loopback(url):
    with pytest.raises(ValueError):
        SnapshotClient(url, None)


@pytest.mark.parametrize("url", ["https://arp.example", "http://localhost:8000", "http://127.0.0.1", "http://[::1]:8000"])
def test_client_accepts_https_and_loopback(url):
    SnapshotClient(url, None).close()
