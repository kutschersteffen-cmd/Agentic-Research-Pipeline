"""Argus step 2: the flow's files, each with its check and its keep/remove state."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from arp.argus.flows import ArgusFlow, FlowFile
from arp.schemas.common import DocType
from arp.storage.safe_path import safe_filename, safe_id

PASSED = "✓ name, year"
_NAME_YEAR = re.compile(r"^(20\d\d)_")


def save_upload(documents_dir: Path, company_id: str, doc_type: DocType, filename: str, data: bytes) -> tuple[Path, str | None]:
    """Stores the upload under documents_dir/<company_id>/<doc_type>/ and returns its path, or, when the company already
    has a file with the same content, that file and its name, writing nothing. Raises UnsafeIdentifierError."""
    company_dir = documents_dir / safe_id(company_id, label="company_id")
    name = safe_filename(filename)
    digest = hashlib.sha256(data).digest()
    if company_dir.is_dir():
        # shortcut: hashes every file of the company on each upload; keep a digest index once companies hold hundreds
        for existing in sorted(company_dir.glob("*/*")):
            if existing.is_file() and existing.stat().st_size == len(data) and hashlib.sha256(existing.read_bytes()).digest() == digest:
                return existing, existing.name
    dest_dir = company_dir / doc_type.value
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Never overwrite an earlier upload: a repeated name gets "-2", "-3", ...
    dest, n = dest_dir / name, 1
    while dest.exists():
        n += 1
        dest = dest_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
    dest.write_bytes(data)
    return dest, None


def file_year(file_name: str, read: int | None) -> int | None:
    """A leading `<year>_` in the file name wins over the year read from the document."""
    m = _NAME_YEAR.match(file_name)
    return int(m.group(1)) if m else read


def check_text(f: FlowFile, reporting_year: int) -> str | None:
    """What is wrong with the file, first problem only; None when it passed. Computed on every read, so a changed reporting year re-checks."""
    if f.duplicate_of:
        return f"Duplicate of {f.duplicate_of}, skipped"
    if f.company_match in ("none", "no_text"):
        return "Company not found in document"
    if f.year is None:
        return "Year unclear"
    if f.year != reporting_year:
        return f"Year {f.year}, expected {reporting_year}"
    return None


class FlowFileView(FlowFile):
    check: str
    passed: bool
    state: Literal["kept", "removed"] | None


def file_views(flow: ArgusFlow, discovered: list[FlowFile]) -> list[FlowFileView]:
    """Uploads, then discovered files, one per key. A passing file is kept until someone removes it; a failing one waits for a person."""
    views, seen = [], set()
    for f in [*flow.uploads, *discovered]:
        if f.key in seen:
            continue
        seen.add(f.key)
        problem = check_text(f, flow.reporting_year)
        state = flow.decisions.get(f.key) if not f.duplicate_of else None
        if state is None and problem is None:
            state = "kept"
        views.append(FlowFileView(**f.model_dump(), check=problem or PASSED, passed=problem is None, state=state))
    return views


def discovered_files(rows: list[dict], documents_dir: Path) -> list[FlowFile]:
    """The files a discovery run found: a downloaded file under documents_dir is a web file, anything else an official filing."""
    root = documents_dir.resolve()
    files = []
    for row in rows:
        for d in row.get("documents_found") or []:
            if d.get("alias_of"):  # the same content under another URL, already listed
                continue
            local = Path(d["local_path"]).resolve() if d.get("local_path") else None
            if local and local.is_relative_to(root):
                files.append(FlowFile(key=local.relative_to(root).as_posix(), company_id=d["company_id"], doc_type=d["doc_type"],
                                      file_name=local.name, source="web", on_disk=True, url=d.get("url"),
                                      year=file_year(local.name, d.get("reporting_year")), company_match=d.get("company_match")))
            elif d.get("url"):
                files.append(FlowFile(key=d["url"], company_id=d["company_id"], doc_type=d["doc_type"],
                                      file_name=d["url"].rstrip("/").rsplit("/", 1)[-1], source="filing", on_disk=False,
                                      url=d["url"], year=d.get("reporting_year"), company_match=d.get("company_match")))
    return files
