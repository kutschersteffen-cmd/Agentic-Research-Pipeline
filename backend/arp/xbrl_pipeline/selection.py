from __future__ import annotations

import json

from arp.schemas.common import now_iso
from arp.storage.atomic_io import atomic_write_text
from arp.storage.jsonl_io import read_jsonl
from arp.storage.safe_path import safe_id
from arp.xbrl_pipeline.flatten import flatten_company_facts
from arp.xbrl_pipeline.models import FactRow
from arp.xbrl_pipeline.store import XbrlStore


def _paths(store: XbrlStore, name: str):
    name = safe_id(name, label="selection name")
    return store.selections_dir / f"{name}.json", store.selections_dir / f"{name}.jsonl"


def cut_selection(store: XbrlStore, name: str, tags: frozenset[str]) -> int:
    """Cut `tags` out of every stored original (never the network) into a named selection."""
    meta_path, rows_path = _paths(store, name)
    lines: list[str] = []
    # ponytail: re-reads every stored original, add a per-concept index if cuts get slow
    for cik in store.ciks():
        original, meta = store.original(cik), store.meta(cik)
        if original is None or meta is None:
            continue
        for row in flatten_company_facts(
            original, company_id=meta["company_id"], cik=cik, source_sha=meta["source_sha"], concepts=tags
        ):
            lines.append(row.model_dump_json() + "\n")
    atomic_write_text(rows_path, "".join(lines))
    info = {"name": name, "tags": sorted(tags), "created_at": now_iso()}
    atomic_write_text(meta_path, json.dumps(info, indent=2))
    return len(lines)


def list_selections(store: XbrlStore) -> list[dict]:
    if not store.selections_dir.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(store.selections_dir.glob("*.json"))]


def read_selection_facts(
    store: XbrlStore, name: str, *, offset: int = 0, limit: int = 100
) -> tuple[list[FactRow], int]:
    rows = read_jsonl(_paths(store, name)[1])
    return [FactRow.model_validate(r) for r in rows[offset : offset + limit]], len(rows)
