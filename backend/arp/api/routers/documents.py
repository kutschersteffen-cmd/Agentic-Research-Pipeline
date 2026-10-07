from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from arp.api.deps import get_document_content_store, settings_dep
from arp.config import Settings
from arp.schemas.common import CompanyRef, DocType
from arp.storage.document_store import DocumentContentStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_filename, safe_id
from arp.universe import load_company_universe

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
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")
    dest_dir = settings.documents_dir / safe_company_id / doc_type.value
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Never overwrite an earlier upload: a repeated name gets "-2", "-3", ...
    dest_path, n = dest_dir / safe_name, 1
    while dest_path.exists():
        n += 1
        dest_path = dest_dir / f"{Path(safe_name).stem}-{n}{Path(safe_name).suffix}"
    dest_path.write_bytes(data)
    return {"path": str(dest_path)}


class ReadinessRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None


def _files_on_disk(documents_dir: Path, company_id: str) -> int:
    try:
        company_dir = documents_dir / safe_id(company_id, label="company_id")
    except UnsafeIdentifierError:
        return 0
    return sum(1 for f in company_dir.rglob("*") if f.is_file()) if company_dir.is_dir() else 0


@router.post("/readiness")
def document_readiness(
    req: ReadinessRequest,
    settings: Settings = Depends(settings_dep),
    store: DocumentContentStore = Depends(get_document_content_store),
) -> dict:
    """Splits a company list into `ready` (documents already on disk or
    registered, so identity resolution and discovery can be skipped) and
    `onboard`. Read-only."""
    try:
        companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    except FileNotFoundError as exc:
        raise HTTPException(400, f"Universe file not found: {req.universe_path}") from exc
    except ValueError as exc:  # unsupported type, bad JSON, or rows that fail CompanyRef validation
        raise HTTPException(400, f"Universe file could not be read: {exc}") from exc
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")
    stored = store.readiness_by_company([c.company_id for c in companies])
    empty = {"registered": 0, "parsed": 0, "doc_types": [], "last_seen_at": None}
    readiness: dict[str, dict] = {}
    ready, onboard = [], []
    for c in companies:
        r = {**empty, **stored.get(c.company_id, {}), "on_disk": _files_on_disk(settings.documents_dir, c.company_id)}
        r["ready"] = r["on_disk"] + r["registered"] > 0
        readiness[c.company_id] = r
        row = c.model_dump(mode="json")
        if r["ready"]:
            ready.append({**row, "readiness": r})
        else:
            onboard.append(row)
    return {"ready": ready, "onboard": onboard, "readiness": readiness}


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


def _enrich_cached_rows(rows: list[dict], store: DocumentContentStore) -> list[dict]:
    """Joins a page of parsed_content rows to their documents-registry row
    (company_id/doc_type/title/filename) via the shared content_key -- a
    cached row has no company/doc_type identity of its own. A row with no
    registry match (content cached before its document was registered)
    keeps those fields as None rather than being dropped."""
    refs = store.list_documents_by_content_keys([row["content_key"] for row in rows])
    enriched = []
    for row in rows:
        ref = refs.get(row["content_key"])
        enriched.append(
            {
                **row,
                "company_id": ref.company_id if ref else None,
                "doc_type": ref.doc_type if ref else None,
                "title": ref.title if ref else None,
                "filename": Path(ref.local_path).name if ref and ref.local_path else None,
            }
        )
    return enriched


@router.get("/cache")
def list_cached_documents(
    offset: int = 0, limit: int = 50, store: DocumentContentStore = Depends(get_document_content_store)
) -> dict:
    """Browses every parsed document text this instance has cached --
    across all runs and companies, not just the most recent one -- for the
    "view stored extractions" data library."""
    rows, total = store.list_cached_content(offset, limit)
    return {"total": total, "documents": _enrich_cached_rows(rows, store)}


@router.get("/cache/{row_id}")
def get_cached_document_text(row_id: int, store: DocumentContentStore = Depends(get_document_content_store)) -> dict:
    content = store.get_cached_text(row_id)
    if content is None:
        raise HTTPException(404, "Cached document not found")
    enriched = _enrich_cached_rows([{"content_key": content.content_key}], store)[0]
    return {**enriched, "full_text": content.full_text, "page_breaks": content.page_breaks, "text_sha256": content.text_sha256}


@router.get("/{company_id}")
def list_documents(
    company_id: str, settings: Settings = Depends(settings_dep),
    store: DocumentContentStore = Depends(get_document_content_store),
) -> dict:
    """Files in the company's folder (`documents`) and every registered document (`registered`),
    including SEC filings, which are stored without a file in the folder."""
    try:
        company_dir = settings.documents_dir / safe_id(company_id, label="company_id")
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc
    # ponytail: scans the whole registry; add a by-company query when it holds many thousand documents
    registered = [
        {"doc_id": d.doc_id, "doc_type": d.doc_type, "title": d.title, "source_url": d.source_url,
         "local_path": d.local_path, "published_at": d.published_at, "last_seen_at": d.last_seen_at}
        for d in store.list_all_documents() if d.company_id == company_id
    ]
    if not company_dir.exists():
        return {"documents": [], "registered": registered}
    docs = []
    for doc_type_dir in sorted(company_dir.iterdir()):
        if not doc_type_dir.is_dir():
            continue
        for f in sorted(doc_type_dir.iterdir()):
            if f.is_file():
                docs.append({"doc_type": doc_type_dir.name, "filename": f.name, "size_bytes": f.stat().st_size})
    return {"documents": docs, "registered": registered}
