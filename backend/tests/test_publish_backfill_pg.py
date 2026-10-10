from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from arp.config import Settings
from arp.schemas.common import RunManifest
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.run_store import RunStore
from tests.postgres_helpers import reset_postgres_tables
from tests.test_publish_release_pg import HASH, ORIG, _decide, _field, _run

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")


@pytest.fixture(autouse=True)
def _db():
    from arp.storage.postgres import ensure_schema

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    yield
    reset_postgres_tables(DSN)


@pytest.fixture
def backfill(tmp_path, monkeypatch):
    from arp.cli import publish as cli

    rs, blobs = RunStore(tmp_path / "runs"), LocalBlobStore(tmp_path / "blobs")
    for d, data in ORIG.items():
        blobs.put(HASH[d], data)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(postgres_dsn=DSN))
    monkeypatch.setattr(cli, "_run_store", lambda: rs)
    monkeypatch.setattr(cli, "_document_content_store", lambda: None)
    monkeypatch.setattr(cli, "blob_store_for", lambda _cfg: blobs)

    def run():
        return CliRunner().invoke(cli.publish_app, ["backfill"])

    run.rs = rs
    return run


def _checkpoint():
    from arp.storage.postgres_checkpoints import get_checkpoint

    return get_checkpoint(DSN, "published_facts")


def test_backfill_publishes_old_runs_then_later_decisions_pg(backfill, monkeypatch):
    rs = backfill.rs
    _run(rs, "r1", 1, [_field(1000)])
    _run(rs, "r2", 2, [_field(7, period="2023-12-31", doc="d2", route="review")])
    rs.save_manifest(RunManifest(run_id="rt", run_type="extraction", params={"trial": True}))
    rs.append_jsonl(rs._results_path("rt"), {"company_id": "c1", "issuer_key": "ISS", "issuer_scheme": "LEI",
                                            "fields": [_field(5, period="2022-12-31", doc="d3")]})

    first = backfill()
    assert first.exit_code == 0, first.output
    assert "releases=1 " in first.output and "skipped=1" in first.output  # r2 not final; trial run never read
    mark = _checkpoint()
    assert mark is not None

    again = backfill()
    assert "releases=0 reconfirmed=1 " in again.output, again.output

    _decide(rs, "r2", "ISS:f1:2023-12-31", "first", "u_alice")  # the manifest is not touched
    later = backfill()
    assert "releases=1 " in later.output, later.output
    mark = _checkpoint()

    import arp.cli.publish as cli

    def boom(*a, **k):
        raise RuntimeError("publish failed")

    monkeypatch.setattr(cli, "publish_run", boom)
    failed = backfill()
    assert failed.exit_code != 0 and _checkpoint() == mark
