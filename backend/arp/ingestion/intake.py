from __future__ import annotations

import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from arp.storage.jsonl_io import append_jsonl
from arp.storage.locks import KeyedLock

INTAKE_LOG = "_intake.jsonl"
MIN_TEXT_CHARS_PER_PAGE = 25
TEXT_CHECK_PAGES = 5
_ZIP_SUFFIXES = {".xlsx", ".xlsm", ".docx"}

_intake_locks = KeyedLock(lock_path=lambda log: Path(log + ".lock"))


class IntakeState(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    OCR_NEEDED = "ocr_needed"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class IntakeResult:
    state: IntakeState
    reason: str = ""
    duplicate_of: str | None = None


def _check_pdf(path: Path) -> IntakeResult | None:
    from pypdf import PdfReader

    with path.open("rb") as f:
        head = f.read(1024)
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 2048))
        tail = f.read()
    if b"%PDF-" not in head or b"%%EOF" not in tail:
        return IntakeResult(IntakeState.QUARANTINED, "truncated")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and reader.decrypt("") == 0:
            return IntakeResult(IntakeState.QUARANTINED, "password protected")
        pages = reader.pages[:TEXT_CHECK_PAGES]
        text_len = sum(len((p.extract_text() or "").strip()) for p in pages)
        if text_len < MIN_TEXT_CHARS_PER_PAGE * len(pages):
            return IntakeResult(IntakeState.OCR_NEEDED, "no text layer")
    except Exception as exc:  # noqa: BLE001 - any parse failure quarantines the file
        return IntakeResult(IntakeState.QUARANTINED, f"unreadable: {exc}")
    return None


def check_intake(path: Path, content_key: str, *, seen: dict[str, str]) -> IntakeResult:
    if path.stat().st_size == 0:
        return IntakeResult(IntakeState.QUARANTINED, "empty")
    first = seen.get(content_key)
    if first is not None and first != str(path):
        return IntakeResult(IntakeState.DUPLICATE, duplicate_of=first)
    seen[content_key] = str(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        bad = _check_pdf(path)
        if bad:
            return bad
    elif suffix in _ZIP_SUFFIXES:
        try:
            ok = zipfile.is_zipfile(path)
            if ok:
                with zipfile.ZipFile(path) as z:
                    ok = z.testzip() is None
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            return IntakeResult(IntakeState.QUARANTINED, "corrupt archive")
    return IntakeResult(IntakeState.ACCEPTED)


def append_intake(documents_dir: Path, path: Path, content_key: str, result: IntakeResult) -> None:
    log = documents_dir / INTAKE_LOG
    row = {
        "path": str(path),
        "content_key": content_key,
        "state": result.state.value,
        "reason": result.reason,
        "duplicate_of": result.duplicate_of,
    }
    with _intake_locks.acquire(str(log)):
        append_jsonl(log, row)
