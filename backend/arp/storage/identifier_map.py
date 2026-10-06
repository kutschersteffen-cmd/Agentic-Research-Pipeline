from __future__ import annotations

from datetime import date
from pathlib import Path

from arp.schemas.issuer import IdentifierMap
from arp.storage.jsonl_io import append_jsonl, read_jsonl


def normalise_identifier(scheme: str, value: str) -> str:
    v = "".join(value.split()).upper()
    return v.lstrip("0") if scheme == "CIK" else v


class IdentifierMapStore:
    """Append-only JSONL of external identifiers per issuer. A missing file is no rows."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def add(self, row: IdentifierMap) -> None:
        append_jsonl(self.path, row.model_dump(mode="json"))

    def rows(self) -> list[IdentifierMap]:
        return [IdentifierMap.model_validate(r) for r in read_jsonl(self.path)]

    def resolve(self, scheme: str, value: str, *, on: str | None = None) -> list[str]:
        day = on or date.today().isoformat()
        want = normalise_identifier(scheme, value)
        keys: list[str] = []
        for r in self.rows():
            if r.scheme != scheme or normalise_identifier(scheme, r.value) != want:
                continue
            if (r.valid_from and day < r.valid_from) or (r.valid_to and day >= r.valid_to):
                continue
            if r.issuer_key not in keys:
                keys.append(r.issuer_key)
        return keys

    def rows_for(self, issuer_key: str) -> list[IdentifierMap]:
        return [r for r in self.rows() if r.issuer_key == issuer_key]
