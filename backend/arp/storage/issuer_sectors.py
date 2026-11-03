"""Sector codes from the security master, kept per issuer and applied over a company whenever it is read."""

from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.common import CompanyRef
from arp.storage.atomic_io import atomic_write_text, read_text_utf8


class IssuerSectorStore:
    """One JSON file, issuer_id -> {column: value} with non-empty values only. A missing file is no rows."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def replace(self, rows: dict[str, dict[str, str]]) -> None:
        atomic_write_text(self.path, json.dumps(rows))

    def get(self, issuer_id: str) -> dict[str, str]:
        return self._all().get(issuer_id, {})

    def _all(self) -> dict[str, dict[str, str]]:
        return json.loads(read_text_utf8(self.path)) if self.path.exists() else {}


def apply_master(company: CompanyRef, sectors: IssuerSectorStore) -> CompanyRef:
    """The company with the master's values over its own; matched by `company_id == issuer_id` exactly."""
    row = sectors.get(company.company_id)
    return company.model_copy(update=row) if row else company
