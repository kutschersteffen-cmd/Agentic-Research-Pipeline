from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

THEME_KEYS = (
    "hydrogen",
    "renewable_power",
    "energy_storage",
    "electric_vehicles",
    "grid_electrification",
    "ai_datacentres",
    "water",
    "ccus",
    "critical_minerals_circular",
    "building_efficiency",
)
_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "authority_library"

SourceType = Literal[
    "regulatory_taxonomy", "agency_report", "index_methodology", "standards_body", "statistical_classification", "engineering_paper"
]


class LibraryEntry(BaseModel):
    url: str
    title: str
    source_type: SourceType
    summary: str
    covers: list[str]
    fetchable: bool
    checked_on: str | None = None
    status: Literal["proposed", "approved"]


def _path(theme_key: str, root: Path | None) -> Path:
    return (root or _DEFAULT_ROOT) / f"{theme_key}.json"


def load_library(theme_key: str, root: Path | None = None) -> list[LibraryEntry]:
    if theme_key not in THEME_KEYS:
        return []
    path = _path(theme_key, root)
    if not path.exists():
        return []
    return [LibraryEntry.model_validate(e) for e in json.loads(path.read_text())]


def save_library(theme_key: str, entries: list[LibraryEntry], root: Path | None = None) -> None:
    if theme_key not in THEME_KEYS:
        raise ValueError(f"unknown theme key {theme_key!r}; expected one of {THEME_KEYS}")
    path = _path(theme_key, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([e.model_dump() for e in entries], indent=2) + "\n")
