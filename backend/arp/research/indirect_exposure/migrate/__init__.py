"""Convert ICIO-code data (core_isic_codes, icio_code link parts) to EXIOBASE sector names."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from functools import cache
from pathlib import Path

from arp.research.indirect_exposure.nace import code_set_sectors
from arp.research.value_chain.model import sector_name
from arp.storage.atomic_io import atomic_write_text


class UnknownIcioCode(ValueError):
    def __init__(self, code: str):
        super().__init__(f"unknown ICIO code {code!r}")
        self.code = code


@cache
def _crosswalk() -> list[dict[str, str]]:
    with (Path(__file__).parent / "exiobase_ixi_to_icio2025.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# In icio2025_industries.csv but matched no EXIOBASE sector, so old results never used them.
ICIO_CODES_WITHOUT_SECTORS = frozenset({"B09", "C21", "C301", "H53", "J58T60"})


def icio_sectors(code: str) -> list[str]:
    """S(code): sorted distinct sector names of the rows whose icio_code or split_code is `code`; a digit-only
    code is an old hand-supplied ISIC Rev.4 division or class and goes through the NACE table."""
    if code in ICIO_CODES_WITHOUT_SECTORS:
        return []
    if code.isdigit():
        out = sorted(code_set_sectors("isic4", code, "2"))
    else:
        out = sorted({sector_name(r["exiobase_sector"]) for r in _crosswalk() if code in (r["icio_code"], r["split_code"])})
    if not out:
        raise UnknownIcioCode(code)
    return out


def _union(codes: list[str]) -> list[str]:
    return sorted({s for c in codes for s in icio_sectors(c)})


def _convert_mapping(sm) -> bool:
    if isinstance(sm, dict) and "unmapped_isic_codes" in sm:
        sm["unmapped_sectors"] = _union(sm.pop("unmapped_isic_codes"))
        return True
    return False


def convert_theme(theme: dict) -> bool:
    changed = False
    for act in theme.get("activities", []):
        if "core_isic_codes" in act:
            # rebuild so core_sectors keeps the old key's position; a core_sectors already there is kept in the union
            sectors = sorted({*act.get("core_sectors", []), *_union(act["core_isic_codes"])})
            items = [("core_sectors", sectors) if k == "core_isic_codes" else (k, v) for k, v in act.items() if k != "core_sectors"]
            act.clear()
            act.update(items)
            changed = True
        changed |= _convert_mapping(act.get("standards_mapping"))
    return _convert_mapping(theme.get("standards_mapping")) | changed


def convert_document(doc: dict) -> bool:
    if "theme" in doc:
        return convert_theme(doc["theme"])
    return convert_theme(doc)


def convert_parts(kind: str, parts: list[dict]) -> list[dict] | None:
    if kind not in ("split", "llm") or not any("icio_code" in p for p in parts):
        return None
    return [{"sectors": icio_sectors(p["icio_code"]), "share": p["share"]} if "icio_code" in p else p for p in parts]


# --- runners (arp io migrate-exiobase) ---

Plan = list[tuple[str, Callable[[], None]]]


def _convert_where(convert: Callable[[], bool], where: str) -> bool:
    try:
        return convert()
    except UnknownIcioCode as e:
        raise ValueError(f"unknown ICIO code '{e.code}' in {where}") from e


def _plan_doc(path: Path, line: str, where: str) -> Plan:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not _convert_where(lambda: convert_document(doc), where):
        return []
    return [(line, lambda: atomic_write_text(path, json.dumps(doc, indent=2, ensure_ascii=False)))]


def plan_file(path: Path, shown: str) -> Plan:
    return _plan_doc(path, f"file {shown}", f"file {shown}")


def plan_all(taxonomies_dir: Path, store) -> Plan:
    plan: Plan = []
    versions = sorted(
        (int(p.stem[1:]), p) for p in taxonomies_dir.glob("*/v*.json") if p.stem[1:].isdigit()
    ) if taxonomies_dir.is_dir() else []
    for n, p in sorted(versions, key=lambda t: (t[1].parent.name, t[0])):
        where = f"taxonomy {p.parent.name} v{n}"
        plan += _plan_doc(p, where, where)
    for subject, rule in sorted(store.list_link_rules().items()):
        where = f"link {subject}"
        parts = _convert_where(lambda r=rule: convert_parts(r.kind, r.parts), where)
        if parts is not None:
            plan.append((where, lambda s=subject, r=rule.model_copy(update={"parts": parts}): store.save_link_rule(s, r)))
    return plan
