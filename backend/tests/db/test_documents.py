import numpy as np
import pytest
from sqlalchemy.exc import IntegrityError

from arp.db import models as m
from arp.db.companies import lookup
from arp.db.documents import DocumentRegistry, derive_doc_id, get_document
from arp.db.session import transaction
from arp.storage.document_store import DocumentContentStore
from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore


@pytest.fixture
def reg(pg):
    return DocumentRegistry(pg)


def _reg(reg, doc_id="doc_a", company_id="acme", doc_type="annual_report", content_key="k1", title="T"):
    return reg.register_document(
        doc_id=doc_id, company_id=company_id, doc_type=doc_type, content_key=content_key,
        title=title, local_path="/p", source_url=None,
    )


def test_register_resolve_reregister(reg):
    assert _reg(reg) == "doc_a"
    first = reg.resolve_document("doc_a")
    assert (first.company_id, first.doc_type, first.content_key, first.title, first.storage_uri) == (
        "acme", "annual_report", "k1", "T", None,
    )
    assert reg.resolve_document("nope") is None
    _reg(reg, title="T2")
    again = reg.resolve_document("doc_a")
    assert again.title == "T2"
    assert again.first_seen_at == first.first_seen_at
    assert again.last_seen_at >= first.last_seen_at


def test_universe_id_keeps_its_case(reg):
    _reg(reg, company_id="Acme-Corp")
    assert reg.resolve_document("doc_a").company_id == "Acme-Corp"


def test_registering_document_for_new_universe_company_creates_company(pg, reg):
    with transaction(pg) as s:
        assert lookup(s, m.IdScheme.UNIVERSE, "brand-new") is None
    _reg(reg, company_id="brand-new")
    with transaction(pg) as s:
        cid = lookup(s, m.IdScheme.UNIVERSE, "brand-new")
        assert cid is not None
        assert get_document(s, "doc_a").company_id == cid


def test_document_has_company_fk(pg):
    import uuid

    with pytest.raises(IntegrityError), transaction(pg) as s:
        s.add(m.Document(doc_id="d", company_id=uuid.uuid4(), doc_type="t", title="t", content_key="k"))


def test_storage_uri_identity_family_order(reg):
    for d in ("doc_c", "doc_b", "doc_a"):
        _reg(reg, doc_id=d, content_key="k" + d)
    reg.set_storage_uri("doc_a", "s3://b/a")
    for d, v in (("doc_c", 1), ("doc_b", 2), ("doc_a", 2)):
        reg.set_identity(
            d, family_id="fam", version=v, supersedes=None, published_at="2025-01-01", confidence=0.5, needs_review=v == 2
        )
    assert reg.resolve_document("doc_a").storage_uri == "s3://b/a"
    fam = reg.list_family("fam")
    assert [r.doc_id for r in fam] == ["doc_c", "doc_a", "doc_b"]
    assert (fam[1].identity_confidence, fam[1].identity_review, fam[1].published_at) == (0.5, 1, "2025-01-01")
    assert reg.list_family("other") == []


def test_supersedes_links_documents(reg):
    _reg(reg, doc_id="doc_old", content_key="ko")
    _reg(reg, doc_id="doc_new", content_key="kn")
    reg.set_identity("doc_new", family_id="f", version=2, supersedes="doc_old", published_at=None, confidence=1.0, needs_review=False)
    assert reg.resolve_document("doc_new").supersedes == "doc_old"


def test_list_by_content_keys_and_all(reg):
    _reg(reg, doc_id="doc_b", content_key="kb")
    _reg(reg, doc_id="doc_a", content_key="ka")
    assert set(reg.list_by_content_keys(["ka", "zz"])) == {"ka"}
    assert reg.list_by_content_keys([]) == {}
    assert [r.doc_id for r in reg.list_all()] == ["doc_a", "doc_b"]
    assert reg.stats() == {"registered_documents": 2}


def test_readiness_by_company(reg):
    _reg(reg, doc_id="doc_a", content_key="ka", doc_type="annual_report")
    _reg(reg, doc_id="doc_b", content_key="kb", doc_type="esg")
    out = reg.readiness_by_company(["acme", "ghost"], lambda keys: {"ka"} & set(keys))
    assert set(out) == {"acme"}
    assert (out["acme"]["registered"], out["acme"]["parsed"], out["acme"]["doc_types"]) == (
        2, 1, ["annual_report", "esg"],
    )
    assert out["acme"]["last_seen_at"] == max(r.last_seen_at for r in reg.list_all())


def test_collision_assigns_fresh_id(reg):
    assert _reg(reg, doc_id="doc_x", company_id="a", content_key="k1") == "doc_x"
    new = _reg(reg, doc_id="doc_x", company_id="b", content_key="k2")
    assert new != "doc_x"
    kept = reg.resolve_document("doc_x")
    assert (kept.company_id, kept.content_key) == ("a", "k1")
    assert reg.resolve_document(new).company_id == "b"


def test_derive_doc_id_is_deterministic():
    assert derive_doc_id("acme", "10-K", "k") == derive_doc_id("acme", "10-K", "k")
    assert derive_doc_id("acme", "10-K", "k") != derive_doc_id("acme", "10-K", "k2")


def test_facade_readiness_uses_parsed_text(pg, tmp_path):
    store = DocumentContentStore(tmp_path, dsn=pg)
    store.register_document(doc_id="doc_a", company_id="acme", doc_type="t", content_key="ka", title="T", local_path=None, source_url=None)
    assert store.readiness_by_company(["acme"])["acme"]["parsed"] == 0
    store.store("ka", key_kind="file", parser_version="v1", source_suffix=".pdf", byte_size=1, text="x", page_breaks=[])
    assert store.readiness_by_company(["acme"])["acme"]["parsed"] == 1
    assert store.stats()["registered_documents"] == 1


def test_embeddings_roundtrip_pgvector(pg):
    from arp.retrieval.embeddings import EMBED_DIM

    vec = np.arange(EMBED_DIM, dtype=np.float32)
    store = PgVectorEmbeddingsStore(pg)
    assert store.lookup_embeddings(["chk_a"], "model-x") == {}
    store.store_embeddings({"chk_a": vec}, "model-x")
    found = store.lookup_embeddings(["chk_a", "chk_b"], "model-x")
    assert set(found) == {"chk_a"} and np.allclose(found["chk_a"], vec)
    assert store.lookup_embeddings(["chk_a"], "model-y") == {}
