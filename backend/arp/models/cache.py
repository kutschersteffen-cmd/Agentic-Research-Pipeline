"""On-disk result cache keyed by (registry key, revision, text, labels)."""
import hashlib
import json
from collections.abc import Callable
from typing import Any

from arp.config import get_settings
from arp.models.registry import RegistryEntry
from arp.storage.atomic_io import atomic_write_text


def cached(e: RegistryEntry, texts: list[str], labels: tuple[str, ...] | None,
           compute: Callable[[list[str]], list[Any]]) -> list[Any]:
    root = get_settings().cache_dir / "models" / e.key / e.revision
    paths = [root / (hashlib.sha256(json.dumps([e.key, e.revision, t, list(labels or [])]).encode()).hexdigest() + ".json")
             for t in texts]
    out: list[Any] = [None] * len(texts)
    miss: dict[Any, list[int]] = {}  # path -> positions, so duplicate texts compute once
    for i, p in enumerate(paths):
        if p.exists():
            out[i] = json.loads(p.read_text())
        else:
            miss.setdefault(p, []).append(i)
    if miss:
        res = compute([texts[v[0]] for v in miss.values()])
        root.mkdir(parents=True, exist_ok=True)
        for (p, idx), r in zip(miss.items(), res, strict=True):
            atomic_write_text(p, json.dumps(r))
            for i in idx:
                out[i] = r
    return out
