from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from arp.schemas.common import now_iso
from arp.storage.atomic_io import atomic_write_bytes, atomic_write_text
from arp.storage.jsonl_io import read_jsonl
from arp.storage.safe_path import safe_id
from arp.xbrl_pipeline.models import CatalogEntry, FactRow, ReportMeta, RequiredRow

_FILES = {"facts": "facts.jsonl", "required": "required.jsonl", "catalog": "catalog.jsonl"}


class XbrlStore:
    """Files under root: <cik10>/{companyfacts-<sha16>.json, meta.json, facts.jsonl, ...}."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def selections_dir(self) -> Path:
        return self.root / "selections"

    @property
    def taxonomy_dir(self) -> Path:
        return self.root / "taxonomy"

    def company_dir(self, cik10: str) -> Path:
        return self.root / safe_id(cik10, label="cik")

    def ciks(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and (p / "meta.json").exists())

    def save_original(self, cik10: str, raw: bytes) -> str:
        sha = hashlib.sha256(raw).hexdigest()
        path = self.company_dir(cik10) / f"companyfacts-{sha[:16]}.json"
        if not path.exists():
            atomic_write_bytes(path, raw)
        return sha

    def meta(self, cik10: str) -> dict | None:
        path = self.company_dir(cik10) / "meta.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def company_ids(self, cik10: str) -> list[str]:
        """Every company_id that fetched this CIK, first fetch first."""
        meta = self.meta(cik10) or {}
        return meta.get("company_ids") or ([meta["company_id"]] if meta.get("company_id") else [])

    def set_meta(self, cik10: str, *, source_sha: str, tags: list[str] | None, company_id: str,
                 company_name: str | None, fact_count: int) -> None:
        ids = list(dict.fromkeys([*self.company_ids(cik10), company_id]))
        meta = {"source_sha": source_sha, "tags": tags, "company_id": company_id, "company_ids": ids,
                "company_name": company_name, "fact_count": fact_count, "fetched_at": now_iso()}
        atomic_write_text(self.company_dir(cik10) / "meta.json", json.dumps(meta, indent=2))

    def add_company_id(self, cik10: str, company_id: str) -> None:
        """Meta-only write: another company_id maps to an already stored CIK."""
        meta = self.meta(cik10) or {}
        ids = self.company_ids(cik10)
        if company_id not in ids:
            meta["company_ids"] = [*ids, company_id]
            atomic_write_text(self.company_dir(cik10) / "meta.json", json.dumps(meta, indent=2))

    def _original_path(self, cik10: str) -> Path | None:
        meta = self.meta(cik10)
        if not meta:
            return None
        path = self.company_dir(cik10) / f"companyfacts-{meta['source_sha'][:16]}.json"
        return path if path.exists() else None

    def original(self, cik10: str) -> dict | None:
        path = self._original_path(cik10)
        return json.loads(path.read_text(encoding="utf-8")) if path else None

    def save_report(self, cik10: str, content: bytes, meta: ReportMeta) -> Path:
        d = self.company_dir(cik10)
        path = d / f"annual-{safe_id(meta.accession, label='accession')}.htm"
        atomic_write_bytes(path, content)
        atomic_write_text(d / "report.json", meta.model_dump_json(indent=2))
        return path

    def report_meta(self, cik10: str) -> ReportMeta | None:
        path = self.company_dir(cik10) / "report.json"
        return ReportMeta.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def _write(self, cik10: str, name: str, rows: Iterable) -> int:
        lines = [r.model_dump_json() for r in rows]
        atomic_write_text(self.company_dir(cik10) / name, "".join(line + "\n" for line in lines))
        return len(lines)

    def write_facts(self, cik10: str, rows: Iterable[FactRow]) -> int:
        return self._write(cik10, _FILES["facts"], rows)

    def read_facts(self, cik10: str) -> Iterator[FactRow]:
        for r in read_jsonl(self.company_dir(cik10) / _FILES["facts"]):
            yield FactRow.model_validate(r)

    def write_catalog(self, cik10: str, entries: Iterable[CatalogEntry]) -> None:
        self._write(cik10, _FILES["catalog"], entries)

    def read_catalog(self, cik10: str) -> list[CatalogEntry]:
        return [CatalogEntry.model_validate(r) for r in read_jsonl(self.company_dir(cik10) / _FILES["catalog"])]

    def write_required(self, cik10: str, rows: Iterable[RequiredRow]) -> None:
        self._write(cik10, _FILES["required"], rows)

    def read_required(self, cik10: str) -> list[RequiredRow]:
        return [RequiredRow.model_validate(r) for r in read_jsonl(self.company_dir(cik10) / _FILES["required"])]

    def file_path(self, cik10: str, kind: str) -> Path | None:
        if kind == "original":
            return self._original_path(cik10)
        if kind == "report":
            meta = self.report_meta(cik10)
            path = self.company_dir(cik10) / meta.filename if meta else None
        elif kind in _FILES:
            path = self.company_dir(cik10) / _FILES[kind]
        else:
            raise KeyError(kind)
        return path if path and path.exists() else None
