import pytest
from fastapi import HTTPException

from arp.api.routers.documents import _safe_document_path


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
