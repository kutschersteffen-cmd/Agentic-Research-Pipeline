from __future__ import annotations

import csv
import functools
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

# Read-only queries on a build from `arp io build-full`; spec Appendix B:
# docs/superpowers/specs/2026-10-24-value-chain-explorer-design.md. float64 throughout, nothing rounded.

NOT_BUILT = "value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR"
ROW_LABELS = {
    "WA": "RoW Asia-Pacific", "WE": "RoW Europe", "WF": "RoW Africa", "WL": "RoW Americas", "WM": "RoW Middle East",
}
UNITS = {"ghg": "t CO₂e", "energy": "TJ", "jobs": "people"}
INTENSITY = {"ghg": "ghg_t_per_meur", "energy": "energy_tj_per_meur", "jobs": "jobs_per_meur"}


class NotBuilt(Exception):
    def __init__(self) -> None:
        super().__init__(NOT_BUILT)


class UnknownNode(KeyError):
    def __init__(self, node_id: str) -> None:
        super().__init__(f"unknown node '{node_id}'")

    def __str__(self) -> str:
        return self.args[0]


@dataclass(frozen=True)
class Node:
    node_id: str
    region: str
    region_label: str
    sector: str
    output_meur: float
    goods: bool
    ghg_t_per_meur: float | None
    energy_tj_per_meur: float | None
    jobs_per_meur: float | None
    va_share: float | None


@dataclass(frozen=True)
class Link:
    node: Node
    direct: float
    total: float


@dataclass(frozen=True)
class TreeItem:
    node: Node
    coef: float
    chain: float
    children: list[TreeItem]


@dataclass(frozen=True)
class Footprint:
    indicator: str
    unit: str
    total: float
    in_home_region: float | None
    by_region: list[tuple[str, float]]
    by_sector: list[tuple[str, float]]


def region_label(code: str) -> str:
    return ROW_LABELS.get(code, code)


def _opt(cell: str) -> float | None:
    return float(cell) if cell else None


def _read_nodes(path: Path) -> list[Node]:
    with path.open(newline="") as f:
        return [
            Node(
                r["node_id"], r["region"], region_label(r["region"]), re.sub(r" \(\d+\)$", "", r["sector"]),
                float(r["output_meur"]), r["goods"] == "true", _opt(r["ghg_t_per_meur"]),
                _opt(r["energy_tj_per_meur"]), _opt(r["jobs_per_meur"]), _opt(r["va_share"]),
            )
            for r in csv.DictReader(f)
        ]


class ValueChain:
    def __init__(self, directory: Path, manifest: dict) -> None:
        self.manifest = manifest
        self._nodes = _read_nodes(directory / "nodes.csv")
        self._index = {n.node_id: i for i, n in enumerate(self._nodes)}
        self._a, self._l, self._g = (np.load(directory / f"{m}.npy") for m in "ALG")
        self._x = np.array([n.output_meur for n in self._nodes])
        self._live = self._x > 0
        # position of each node in node-id string order: the tie-break of every ranked list
        self._rank = np.empty(len(self._nodes), dtype=np.int64)
        self._rank[sorted(range(len(self._nodes)), key=lambda i: self._nodes[i].node_id)] = np.arange(len(self._nodes))
        self._goods = np.array([n.goods for n in self._nodes])
        # a null intensity counts 0 in a footprint
        self._intensity = {k: np.array([getattr(n, f) or 0.0 for n in self._nodes]) for k, f in INTENSITY.items()}
        self._search_text = [(n.sector.lower(), n.region_label.lower(), n.region.lower()) for n in self._nodes]
        self._regions, self._region_of = np.unique([n.region_label for n in self._nodes], return_inverse=True)
        self._sectors, self._sector_of = np.unique([n.sector for n in self._nodes], return_inverse=True)

    @property
    def caveat(self) -> str:
        return (
            f"EXIOBASE {self.manifest['exiobase_version']} · {self.manifest['year']} · basic prices, M EUR · "
            "now-cast years are estimates · capital goods not included in flows"
        )

    def _k(self, node_id: str) -> int:
        k = self._index.get(node_id)
        if k is None or not self._live[k]:
            raise UnknownNode(node_id)
        return k

    def _ranked(self, values: np.ndarray, candidates: np.ndarray) -> np.ndarray:
        """Candidate indices by value descending, ties by node id ascending."""
        return candidates[np.lexsort((self._rank[candidates], -values[candidates]))]

    def search(self, q: str, limit: int = 20) -> list[Node]:
        q = q.strip().lower()
        exact, rest = [], []
        for i, (sector, label, code) in enumerate(self._search_text):
            if not self._live[i]:
                continue
            if q in (code, label):
                exact.append(i)
            elif q in sector or q in label:
                rest.append(i)
        by_id = lambda i: self._rank[i]  # noqa: E731
        return [self._nodes[i] for i in (sorted(exact, key=by_id) + sorted(rest, key=by_id))[:limit]]

    def node(self, node_id: str) -> Node:
        return self._nodes[self._k(node_id)]

    def links(
        self, node_id: str, side: Literal["suppliers", "customers"], order: Literal["total", "direct"] = "total",
        limit: int = 10, exclude_own: bool = False,
    ) -> list[Link]:
        k = self._k(node_id)
        if side == "suppliers":
            direct, total = self._a[:, k], self._l[:, k].copy()
        else:
            direct, total = self._a[k, :] * self._x / self._x[k], self._g[k, :].copy()
        total[k] -= 1
        measure = total if order == "total" else direct
        keep = self._live & (measure > 0)
        if exclude_own:
            keep[k] = False
        top = self._ranked(measure, np.flatnonzero(keep))[:limit]
        return [Link(self._nodes[i], float(direct[i]), float(total[i])) for i in top]

    def tree(
        self, node_id: str, depth: int = 2, width: int = 3, cutoff: float = 0.01, goods_only: bool = False,
    ) -> TreeItem:
        def grow(k: int, coef: float, chain: float, level: int) -> TreeItem:
            kids: list[TreeItem] = []
            if level < depth:
                col = self._a[:, k]
                keep = self._live & (col > 0) & (col >= cutoff)
                keep[k] = False
                if goods_only:
                    keep &= self._goods
                kids = [
                    grow(int(i), float(col[i]), chain * float(col[i]), level + 1)
                    for i in self._ranked(col, np.flatnonzero(keep))[:width]
                ]
            return TreeItem(self._nodes[k], coef, chain, kids)

        return grow(self._k(node_id), 1.0, 1.0, 0)

    def footprint(
        self, node_id: str, indicator: Literal["ghg", "energy", "jobs"], amount_meur: float = 1.0, top: int = 6,
    ) -> Footprint:
        k = self._k(node_id)
        contribution = self._intensity[indicator] * self._l[:, k] * amount_meur
        total = float(contribution.sum())

        def groups(names: np.ndarray, codes: np.ndarray) -> list[tuple[str, float]]:
            sums = np.bincount(codes, weights=contribution, minlength=len(names))
            nz = np.flatnonzero(sums)
            return [(str(names[i]), float(sums[i])) for i in nz[np.lexsort((names[nz], -sums[nz]))][:top]]

        in_home = float(contribution[self._region_of == self._region_of[k]].sum()) / total if total else None
        return Footprint(
            indicator, UNITS[indicator], total, in_home,
            groups(self._regions, self._region_of), groups(self._sectors, self._sector_of),
        )


_load_lock = threading.Lock()  # lru_cache lets concurrent misses each load the 1.5 GB matrices


@functools.lru_cache(maxsize=1)
def _load(directory: str, manifest_text: str) -> ValueChain:
    return ValueChain(Path(directory), json.loads(manifest_text))


def load_value_chain(directory: Path | None) -> ValueChain:
    """Cached on the manifest text, so a rebuild (new built_at or label) reloads."""
    manifest = Path(directory) / "manifest.json" if directory else None
    if manifest is None or not manifest.is_file():
        raise NotBuilt
    with _load_lock:
        return _load(str(directory), manifest.read_text())
