"""Step 2: the documents of a flow's companies, each checked (company named, year as expected) and kept or removed.

The file list is read fresh from the documents folder and the registry; only the user's keep/remove choice is
stored on the flow. Removing a file leaves it out of this flow only: the file stays on the company."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

from arp.argus.flows import ArgusFlow
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.doc_check import _contains_name, check_document
from arp.ingestion.doc_identity import reporting_year
from arp.schemas.common import CompanyRef
from arp.storage.atomic_io import atomic_write_text
from arp.storage.document_store import DocumentContentStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_filename, safe_id

NOT_FOUND = "Company not found in document"
YEAR_UNCLEAR = "Year unclear"
_FILING_HOSTS = ("sec.gov", "filings.xbrl.org")
_TAG = re.compile(r"<[^>]+>")


class FlowFile(BaseModel):
    key: str
    company_id: str
    company_name: str
    doc_type: str
    filename: str
    year: int | None
    source: Literal["upload", "filings", "web"]
    check: str
    passes: bool
    state: Literal["kept", "removed"] | None = None
    raw_url: str | None = None  # the file itself, for the side panel
    page_url: str | None = None  # page 1 as an image, PDFs only
    duplicate_of: str | None = None


def expected_year(flow: ArgusFlow, today: date | None = None) -> int:
    return flow.reporting_year or (today or date.today()).year - 1


def check_text(match: str, year: int | None, name: str, expected: int) -> tuple[str, bool]:
    """The step 2 check line and whether the file passes it."""
    if match in ("none", "no_text"):
        return NOT_FOUND, False
    if year is None:
        return YEAR_UNCLEAR, False
    if year != expected:
        return f"Year {year}, expected {expected}", False
    return f"✓ {name}, {year}", True


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inspect(path: Path, company: CompanyRef, checks_dir: Path) -> tuple[str, int | None]:
    """(company match, year) for one file, cached by content and company: checking a PDF reads it."""
    cache = checks_dir / f"{_sha(path)}-{company.company_id}.json"
    if cache.is_file():
        match, year = json.loads(cache.read_text())
        return match, year
    year = reporting_year(path.name, "")  # the file name first, as the import folder does
    if path.suffix.lower() == ".pdf":
        c = check_document(path, company)
        match, year = c.company_match, year or c.reporting_year
    else:  # HTML and text pages: the same checks on their text
        try:
            text = _TAG.sub(" ", path.read_bytes()[:2_000_000].decode("utf-8", "ignore"))
        except OSError:
            text = ""
        match = "name" if _contains_name(text, company.name) else ("no_text" if len(text.split()) < 30 else "none")
        year = year or reporting_year("", text)
    checks_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(cache, json.dumps([match, year]))
    return match, year


def _source(url: str | None) -> Literal["upload", "filings", "web"]:
    if not url:
        return "upload"
    host = urlparse(url).hostname or ""
    return "filings" if any(host == h or host.endswith("." + h) for h in _FILING_HOSTS) else "web"


def flow_files(
    flow: ArgusFlow, *, documents_dir: Path, content_store: DocumentContentStore, checks_dir: Path, discovery_state_dir: Path,
) -> list[FlowFile]:
    expected = expected_year(flow)
    companies = {c.company_id: c for c in flow.companies}
    registered = [d for d in content_store.list_all_documents() if d.company_id in companies]
    url_of = {Path(d.local_path).resolve(): d.source_url for d in registered if d.local_path}
    # the crawler's downloads are not registered with their URL; discovery's manifest has it
    detector = ChangeDetector(state_dir=discovery_state_dir, global_events_path=documents_dir / "_events.jsonl")
    for cid in companies:
        for url, d in detector.known_documents(cid).items():
            if d.local_path:
                url_of.setdefault(Path(d.local_path).resolve(), url)
    out: list[FlowFile] = []
    for cid, company in companies.items():
        try:
            folder = documents_dir / safe_id(cid, label="company_id")
        except UnsafeIdentifierError:
            continue
        on_disk = set()
        for path in sorted(folder.glob("*/*")) if folder.is_dir() else []:
            if not path.is_file() or path.name.startswith("."):
                continue
            on_disk.add(path.resolve())
            doc_type, key = path.parent.name, f"{cid}/{path.parent.name}/{path.name}"
            match, year = _inspect(path, company, checks_dir)
            check, passes = check_text(match, year, company.name, expected)
            base = f"/api/documents/{cid}/{doc_type}/{path.name}"
            out.append(FlowFile(
                key=key, company_id=cid, company_name=company.name, doc_type=doc_type, filename=path.name, year=year,
                source=_source(url_of.get(path.resolve())), check=check, passes=passes, state=flow.decisions.get(key),
                raw_url=f"{base}/raw", page_url=f"{base}/pages/1" if path.suffix.lower() == ".pdf" else None,
            ))
        for d in registered:  # filings stored without a file in the folder (SEC)
            if d.company_id != cid or (d.local_path and Path(d.local_path).resolve() in on_disk):
                continue
            # shortcut: a filing fetched by the company's CIK names the company; its year comes from the title, else
            # the publication year. Upgrade when filings carry their fiscal period.
            year = reporting_year(d.title or "", "") or (int(d.published_at[:4]) if d.published_at else None)
            check, passes = check_text("identifier", year, company.name, expected)
            key = f"doc:{d.doc_id}"
            out.append(FlowFile(key=key, company_id=cid, company_name=company.name, doc_type=d.doc_type,
                                filename=d.title or d.doc_id, year=year, source=_source(d.source_url), check=check,
                                passes=passes, state=flow.decisions.get(key), raw_url=d.source_url))
    for s in flow.skipped_uploads:
        out.append(FlowFile(key=f"skipped:{s.company_id}/{s.filename}", company_id=s.company_id,
                            company_name=companies[s.company_id].name if s.company_id in companies else s.company_id,
                            doc_type="", filename=s.filename, year=None, source="upload",
                            check=f"Duplicate of {s.duplicate_of}, skipped", passes=False, duplicate_of=s.duplicate_of))
    return out


def store_upload(documents_dir: Path, company_id: str, doc_type: str, filename: str, data: bytes) -> tuple[Path | None, str | None]:
    """Files an upload as `/api/documents/upload` does: (stored path, None), or (None, name of the file it duplicates)."""
    folder = documents_dir / safe_id(company_id, label="company_id")
    name = safe_filename(filename)
    digest = hashlib.sha256(data).hexdigest()
    for existing in sorted(folder.glob("*/*")) if folder.is_dir() else []:
        if existing.is_file() and existing.stat().st_size == len(data) and _sha(existing) == digest:
            return None, existing.name
    dest_dir = folder / doc_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest, n = dest_dir / name, 1
    while dest.exists():  # never overwrite an earlier upload
        n += 1
        dest = dest_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
    dest.write_bytes(data)
    return dest, None


def decide(flow: ArgusFlow, files: list[FlowFile], *, keys: list[str] | None, state: str | None, all_that_pass: bool,
           every: bool) -> None:
    """Keep or remove files in this flow. `Keep all that pass` never keeps a failing file."""
    real = [f for f in files if f.duplicate_of is None]
    if all_that_pass:
        for f in real:
            if f.passes:
                flow.decisions[f.key] = "kept"
    elif every:
        for f in real:
            flow.decisions[f.key] = state
    else:
        known = {f.key for f in real}
        for k in keys or []:
            if k in known:
                flow.decisions[k] = state
