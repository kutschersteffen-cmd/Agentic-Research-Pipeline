import pytest
from fastapi import HTTPException

from arp.api.routers.documents import _enrich_cached_rows, _safe_document_path
from arp.storage.document_store import DocumentContentStore, derive_doc_id


def test_safe_document_path_returns_real_file(tmp_path):
    doc_dir = tmp_path / "ACME" / "sustainability_report"
    doc_dir.mkdir(parents=True)
    (doc_dir / "report.pdf").write_bytes(b"%PDF-1.4 fake")

    resolved = _safe_document_path(tmp_path, "ACME", "sustainability_report", "report.pdf")
    assert resolved == (doc_dir / "report.pdf").resolve()


def test_safe_document_path_rejects_path_traversal_in_filename(tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        _safe_document_path(tmp_path, "ACME", "sustainability_report", "../../../etc/passwd")
    assert exc_info.value.status_code == 400


def test_safe_document_path_rejects_embedded_slash_in_filename(tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        _safe_document_path(tmp_path, "ACME", "sustainability_report", "sub/report.pdf")
    assert exc_info.value.status_code == 400


def test_safe_document_path_404s_on_missing_file(tmp_path):
    (tmp_path / "ACME" / "sustainability_report").mkdir(parents=True)
    with pytest.raises(HTTPException) as exc_info:
        _safe_document_path(tmp_path, "ACME", "sustainability_report", "nope.pdf")
    assert exc_info.value.status_code == 404


def test_enrich_cached_rows_fills_in_registered_document(tmp_path):
    store = DocumentContentStore(tmp_path / "store")
    store.register_document(
        doc_id=derive_doc_id("acme", "10-K", "key_a"), company_id="acme", doc_type="10-K",
        content_key="key_a", title="Acme 10-K", local_path="/docs/acme/10-K/acme.pdf", source_url=None,
    )

    enriched = _enrich_cached_rows([{"content_key": "key_a", "char_len": 100}], store)

    assert enriched == [
        {
            "content_key": "key_a",
            "char_len": 100,
            "company_id": "acme",
            "doc_type": "10-K",
            "title": "Acme 10-K",
            "filename": "acme.pdf",
        }
    ]


def test_enrich_cached_rows_leaves_unregistered_row_as_none(tmp_path):
    store = DocumentContentStore(tmp_path / "store")

    enriched = _enrich_cached_rows([{"content_key": "key_unregistered"}], store)

    assert enriched[0]["company_id"] is None
    assert enriched[0]["filename"] is None


def test_list_documents_rejects_unsafe_company_id(tmp_path):
    from arp.api.routers.documents import list_documents
    from arp.config import Settings

    with pytest.raises(HTTPException) as exc_info:
        list_documents("../etc", Settings(documents_dir=tmp_path))
    assert exc_info.value.status_code == 400


async def test_upload_refuses_oversize_file_and_leaves_nothing(tmp_path):
    import io

    from starlette.datastructures import UploadFile

    from arp.api.routers.documents import upload_document
    from arp.config import Settings
    from arp.schemas.common import DocType

    settings = Settings(documents_dir=tmp_path, max_upload_bytes=10)
    with pytest.raises(HTTPException) as exc_info:
        await upload_document("acme", DocType.OTHER, UploadFile(io.BytesIO(b"x" * 11), filename="big.pdf"), settings)
    assert exc_info.value.status_code == 413
    assert not list(tmp_path.rglob("*.pdf"))


async def test_upload_keeps_both_files_with_the_same_name(tmp_path):
    import io

    from starlette.datastructures import UploadFile

    from arp.api.routers.documents import upload_document
    from arp.config import Settings
    from arp.schemas.common import DocType

    settings = Settings(documents_dir=tmp_path)
    first = await upload_document("acme", DocType.OTHER, UploadFile(io.BytesIO(b"one"), filename="r.pdf"), settings)
    second = await upload_document("acme", DocType.OTHER, UploadFile(io.BytesIO(b"two"), filename="r.pdf"), settings)
    assert first["path"] != second["path"]
    assert sorted(p.read_bytes() for p in (tmp_path / "acme" / "other").iterdir()) == [b"one", b"two"]
