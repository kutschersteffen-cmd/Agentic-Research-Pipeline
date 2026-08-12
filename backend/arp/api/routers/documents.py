from __future__ import annotations

from fastapi import APIRouter, Depends, Form, UploadFile

from arp.api.deps import settings_dep
from arp.config import Settings
from arp.schemas.common import DocType

router = APIRouter(prefix="/api/documents", tags=["documents"])


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
    dest_dir = settings.documents_dir / company_id / doc_type.value
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    dest_path.write_bytes(await file.read())
    return {"path": str(dest_path)}


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
