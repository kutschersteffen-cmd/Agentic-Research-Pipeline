"""Convert ICIO-code data (core_isic_codes, icio_code link parts) to EXIOBASE sector names."""

from __future__ import annotations

import csv
from functools import cache
from pathlib import Path

from arp.research.value_chain.model import sector_name


class UnknownIcioCode(ValueError):
    def __init__(self, code: str):
        super().__init__(f"unknown ICIO code {code!r}")
        self.code = code


@cache
def _crosswalk() -> list[dict[str, str]]:
    with (Path(__file__).parent / "exiobase_ixi_to_icio2025.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def icio_sectors(code: str) -> list[str]:
    """S(code): sorted distinct sector names of the rows whose icio_code or split_code is `code`."""
    out = sorted({sector_name(r["exiobase_sector"]) for r in _crosswalk() if code in (r["icio_code"], r["split_code"])})
    if not out:
        raise UnknownIcioCode(code)
    return out


def _union(codes: list[str]) -> list[str]:
    return sorted({s for c in codes for s in icio_sectors(c)})


def convert_theme(theme: dict) -> bool:
    changed = False
    for act in theme.get("activities", []):
        if "core_isic_codes" in act:
            # rebuild so core_sectors keeps the old key's position
            items = [("core_sectors", _union(act["core_isic_codes"])) if k == "core_isic_codes" else (k, v) for k, v in act.items()]
            act.clear()
            act.update(items)
            changed = True
    sm = theme.get("standards_mapping")
    if isinstance(sm, dict) and "unmapped_isic_codes" in sm:
        sm["unmapped_sectors"] = _union(sm.pop("unmapped_isic_codes"))
        changed = True
    return changed


def convert_document(doc: dict) -> bool:
    return convert_theme(doc.get("theme", doc))


def convert_parts(kind: str, parts: list[dict]) -> list[dict] | None:
    if kind not in ("split", "llm") or not any("icio_code" in p for p in parts):
        return None
    return [{"sectors": icio_sectors(p["icio_code"]), "share": p["share"]} if "icio_code" in p else p for p in parts]
