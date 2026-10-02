import pytest
from fastapi import HTTPException

from arp.api.routers.documents import ReadinessRequest, document_readiness
from arp.config import Settings
from arp.schemas.common import CompanyRef
from arp.storage.document_store import DocumentContentStore, derive_doc_id


def _register(store, company_id, content_key):
    store.register_document(
        doc_id=derive_doc_id(company_id, "10-K", content_key), company_id=company_id, doc_type="10-K",
        content_key=content_key, title=content_key, local_path=None, source_url=None,
    )


def test_readiness_counts_registered_and_parsed(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    _register(store, "acme", "key_a")
    _register(store, "acme", "key_b")
    store.store("key_a", key_kind="file_bytes", parser_version="v1", source_suffix=".pdf", byte_size=10, text="t", page_breaks=[])

    result = store.readiness_by_company(["acme", "zeta"])

    assert result["acme"]["registered"] == 2
    assert result["acme"]["parsed"] == 1
    assert result["acme"]["doc_types"] == ["10-K"]
    assert "zeta" not in result


def test_readiness_batches_large_id_lists(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    _register(store, "id1500", "key_a")

    result = store.readiness_by_company([f"id{i}" for i in range(2000)])

    assert list(result) == ["id1500"]


def test_endpoint_splits_ready_and_onboard(tmp_path):
    settings = Settings(anthropic_api_key="unused", documents_dir=tmp_path / "docs")
    store = DocumentContentStore(tmp_path / "store")
    (settings.documents_dir / "acme" / "10-K").mkdir(parents=True)
    (settings.documents_dir / "acme" / "10-K" / "a.pdf").write_bytes(b"x")
    _register(store, "beta", "key_b")
    companies = [CompanyRef(company_id=c, name=c.title()) for c in ("acme", "beta", "zeta")]

    out = document_readiness(ReadinessRequest(companies=companies), settings, store)

    assert [c["company_id"] for c in out["ready"]] == ["acme", "beta"]
    assert [c["company_id"] for c in out["onboard"]] == ["zeta"]
    assert out["readiness"]["acme"]["on_disk"] == 1
    assert out["ready"][0]["readiness"]["ready"] is True


def test_endpoint_requires_input(tmp_path):
    settings = Settings(anthropic_api_key="unused", documents_dir=tmp_path / "docs")
    with pytest.raises(HTTPException) as exc_info:
        document_readiness(ReadinessRequest(), settings, DocumentContentStore(tmp_path / "store"))
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("name, content", [("missing.csv", None), ("bad.txt", "x"), ("bad.json", "{not json")])
def test_endpoint_rejects_unreadable_universe(tmp_path, name, content):
    settings = Settings(anthropic_api_key="unused", documents_dir=tmp_path / "docs")
    path = tmp_path / name
    if content is not None:
        path.write_text(content)
    with pytest.raises(HTTPException) as exc_info:
        document_readiness(ReadinessRequest(universe_path=str(path)), settings, DocumentContentStore(tmp_path / "store"))
    assert exc_info.value.status_code == 400
