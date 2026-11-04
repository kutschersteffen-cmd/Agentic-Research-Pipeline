"""Model registry: pinned Hugging Face revisions, allow-list and provenance."""
import functools
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

REGISTRY_PATH = Path(__file__).with_name("registry.json")
ALLOWED_PATH = Path(__file__).with_name("allowed.txt")


class RegistryEntry(BaseModel):
    key: str
    capability: Literal["embed", "rerank", "classify", "spans", "tag"]
    hf_id: str
    revision: str
    labels: list[str] | None = None


@functools.cache
def _load(path: Path) -> dict[str, RegistryEntry]:
    entries = (RegistryEntry(**d) for d in json.loads(path.read_text()))
    return {e.key: e for e in entries}


def entry(key: str) -> RegistryEntry:
    e = _load(REGISTRY_PATH).get(key)
    if e is None:
        raise KeyError(key)
    allowed = ALLOWED_PATH.read_text().split()
    if e.hf_id not in allowed:
        raise ValueError(f"model {e.hf_id!r} is not in the allow-list")
    return e


def provenance(e: RegistryEntry, where: Literal["cloud", "local"]) -> dict:
    return {"model": e.key, "revision": e.revision, "where": where}


def model_header(e: RegistryEntry) -> str:
    return f"{e.hf_id}@{e.revision}"
