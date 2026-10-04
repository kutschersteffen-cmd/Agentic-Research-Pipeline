import os

import pytest

from arp.config import Settings
from arp.retrieval.content_store_factory import content_store_for
from arp.storage.document_store import DocumentContentStore
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")


@pytest.fixture(autouse=True)
def _db():
    from arp.storage.postgres import ensure_schema

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    yield
    reset_postgres_tables(DSN)


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path):
    return DocumentContentStore(tmp_path, postgres_dsn=DSN if request.param == "postgres" else None)


def _reg(store, doc_id="doc_a", company_id="acme", doc_type="annual_report", content_key="k1", title="T"):
    return store.register_document(
        doc_id=doc_id, company_id=company_id, doc_type=doc_type, content_key=content_key,
        title=title, local_path="/p", source_url=None,
    )


def test_register_resolve_reregister(store):
    assert _reg(store) == "doc_a"
    first = store.resolve_document("doc_a")
    assert (first.company_id, first.doc_type, first.content_key, first.title, first.storage_uri) == (
        "acme", "annual_report", "k1", "T", None,
    )
    assert store.resolve_document("nope") is None
    _reg(store, title="T2", content_key="k1")
    again = store.resolve_document("doc_a")
    assert again.title == "T2"
    assert again.first_seen_at == first.first_seen_at
    assert again.last_seen_at >= first.last_seen_at


def test_storage_uri_identity_family_order(store):
    for d in ("doc_c", "doc_b", "doc_a"):
        _reg(store, doc_id=d, content_key="k" + d)
    store.set_storage_uri("doc_a", "s3://b/a")
    for d, v in (("doc_c", 1), ("doc_b", 2), ("doc_a", 2)):
        store.set_identity(
            d, family_id="fam", version=v, supersedes=None, published_at="2025-01-01", confidence=0.5, needs_review=v == 2
        )
    assert store.resolve_document("doc_a").storage_uri == "s3://b/a"
    fam = store.list_family("fam")
    assert [r.doc_id for r in fam] == ["doc_c", "doc_a", "doc_b"]
    assert (fam[1].identity_confidence, fam[1].identity_review, fam[1].published_at) == (0.5, 1, "2025-01-01")
    assert store.list_family("other") == []


def test_list_by_content_keys_and_all(store):
    _reg(store, doc_id="doc_b", content_key="kb")
    _reg(store, doc_id="doc_a", content_key="ka")
    assert set(store.list_documents_by_content_keys(["ka", "zz"])) == {"ka"}
    assert store.list_documents_by_content_keys([]) == {}
    assert [r.doc_id for r in store.list_all_documents()] == ["doc_a", "doc_b"]


def test_readiness_by_company(store):
    _reg(store, doc_id="doc_a", content_key="ka", doc_type="annual_report")
    _reg(store, doc_id="doc_b", content_key="kb", doc_type="esg")
    store.store("ka", key_kind="file", parser_version="v1", source_suffix=".pdf", byte_size=1, text="x", page_breaks=[])
    out = store.readiness_by_company(["acme", "ghost"])
    assert set(out) == {"acme"}
    assert (out["acme"]["registered"], out["acme"]["parsed"], out["acme"]["doc_types"]) == (
        2, 1, ["annual_report", "esg"],
    )
    assert out["acme"]["last_seen_at"] == max(r.last_seen_at for r in store.list_all_documents())


def test_collision_assigns_fresh_id(store):
    assert _reg(store, doc_id="doc_x", company_id="a", content_key="k1") == "doc_x"
    new = _reg(store, doc_id="doc_x", company_id="b", content_key="k2")
    assert new != "doc_x"
    kept = store.resolve_document("doc_x")
    assert (kept.company_id, kept.content_key) == ("a", "k1")
    assert store.resolve_document(new).company_id == "b"


def test_content_store_for_selects_backend(tmp_path):
    pg = Settings(embeddings_backend="postgres", postgres_dsn=DSN, document_store_dir=tmp_path)
    assert content_store_for(pg).stats()["registry_backend"] == "postgres"
    assert "registry_backend" not in content_store_for(Settings(document_store_dir=tmp_path)).stats()


def test_copy_sqlite_registry_is_idempotent(tmp_path):
    from arp.storage.postgres_document_registry import PgDocumentRegistry, copy_sqlite_registry

    src = DocumentContentStore(tmp_path)
    for d, v in (("doc_a", 1), ("doc_b", 2)):
        _reg(src, doc_id=d, content_key="k" + d)
        src.set_identity(d, family_id="f", version=v, supersedes=None, published_at=None, confidence=0.9, needs_review=False)
    src.set_storage_uri("doc_a", "s3://x")
    assert copy_sqlite_registry(tmp_path, DSN) == 2
    pg = PgDocumentRegistry(DSN, True, lambda keys: set())
    assert pg.list_all() == src.list_all_documents()
    assert copy_sqlite_registry(tmp_path, DSN) == 2
    assert pg.list_all() == src.list_all_documents()


def test_migrate_registry_refuses_without_postgres(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from arp.cli.documents import documents_app

    monkeypatch.setenv("ARP_DOCUMENT_STORE_DIR", str(tmp_path))
    monkeypatch.delenv("ARP_EMBEDDINGS_BACKEND", raising=False)
    from arp.config import get_settings

    get_settings.cache_clear()
    try:
        assert CliRunner().invoke(documents_app, ["migrate-registry"]).exit_code == 1
    finally:
        get_settings.cache_clear()
