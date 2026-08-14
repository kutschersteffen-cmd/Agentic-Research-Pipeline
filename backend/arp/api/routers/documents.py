from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from arp.api.deps import settings_dep
from arp.config import Settings
from arp.schemas.common import DocType
from arp.storage.safe_path import UnsafeIdentifierError, safe_filename, safe_id

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _safe_document_path(documents_dir: Path, company_id: str, doc_type: str, filename: str) -> Path:
    """Resolves company_id/doc_type/filename to a real file strictly under
    documents_dir, rejecting any path-traversal attempt (a filename
    containing "/" or ".." segments) before touching the filesystem.
    """
    if Path(filename).name != filename:
        raise HTTPException(400, "Invalid filename")
    resolved = (documents_dir / company_id / doc_type / filename).resolve()
    if not resolved.is_relative_to(documents_dir.resolve()):
        raise HTTPException(400, "Invalid path")
    if not resolved.is_file():
        raise HTTPException(404, "Document not found")
    return resolved


@router.post("/upload")
async def upload_document(
    company_id: str = Form(...),
    doc_type: DocType = Form(...),
    file: UploadFile = None,
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Manually drops a document into the same
    `documents_dir/<company_id>/<doc_type>/` convention the discovery
    crawler writes to, so manual uploads and auto-discovered documents are
    indistinguishable to the extraction pipeline."""
    try:
        safe_company_id = safe_id(company_id, label="company_id")
        safe_name = safe_filename(file.filename)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc
    dest_dir = settings.documents_dir / safe_company_id / doc_type.value
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name
    dest_path.write_bytes(await file.read())
    return {"path": str(dest_path)}


@router.get("/{company_id}/{doc_type}/{filename}/raw")
def get_document_raw(
    company_id: str, doc_type: DocType, filename: str, settings: Settings = Depends(settings_dep)
) -> FileResponse:
    """Serves the raw on-disk file inline (not as a download) so a citation's
    "view source" link opens it directly in the browser's native viewer --
    for a PDF, that's what lets a `#page=N` URL fragment jump straight to
    the cited page."""
    path = _safe_document_path(settings.documents_dir, company_id, doc_type.value, filename)
    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


@router.get("/{company_id}")
def list_documents(company_id: str, settings: Settings = Depends(settings_dep)) -> dict:
    company_dir = settings.documents_dir / company_id
    if not company_dir.exists():
        return {"documents": []}
    docs = []
    for doc_type_dir in sorted(company_dir.iterdir()):
        if not doc_type_dir.is_dir():
            continue
        for f in sorted(doc_type_dir.iterdir()):
            if f.is_file():
                docs.append({"doc_type": doc_type_dir.name, "filename": f.name, "size_bytes": f.stat().st_size})
    return {"documents": docs}
