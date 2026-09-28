"""Where reviewers' level overrides live: beside the table they were set on
(a Decision Studio dataset) or in the run folder (a scored run). One file
holds the overrides in force and the history of every change, so an
override that was later removed is still on record with who and why.
"""

from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.common import now_iso
from arp.schemas.decision import LevelOverride
from arp.storage.atomic_io import atomic_write_text


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"overrides": [], "history": []}


def load(path: Path) -> list[LevelOverride]:
    return [LevelOverride.model_validate(o) for o in _read(path)["overrides"]]


def history(path: Path) -> list[dict]:
    return _read(path)["history"]


def set_override(path: Path, override: LevelOverride) -> list[LevelOverride]:
    """Adds the override, replacing one for the same entity and criterion."""
    data = _read(path)
    data["overrides"] = [o for o in data["overrides"] if (o["entity_key"], o["criterion_id"]) != (override.entity_key, override.criterion_id)]
    data["overrides"].append(json.loads(override.model_dump_json()))
    data["history"].append({"action": "set", **json.loads(override.model_dump_json())})
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data))
    return load(path)


def remove_override(path: Path, entity_key: str, criterion_id: str, reviewer: str, reason: str) -> list[LevelOverride]:
    """Takes an override out; the rules' level applies again. Recorded."""
    data = _read(path)
    before = len(data["overrides"])
    data["overrides"] = [o for o in data["overrides"] if (o["entity_key"], o["criterion_id"]) != (entity_key, criterion_id)]
    if len(data["overrides"]) == before:
        raise KeyError(f"No override for {entity_key} · {criterion_id}.")
    data["history"].append({"action": "removed", "entity_key": entity_key, "criterion_id": criterion_id, "reviewer": reviewer, "reason": reason, "at": now_iso()})
    atomic_write_text(path, json.dumps(data))
    return load(path)
