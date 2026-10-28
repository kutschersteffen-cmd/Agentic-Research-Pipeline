from __future__ import annotations

import csv
import functools
import json
import re
import threading
from collections.abc import Sequence
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
MATERIAL_UNIT = "t"
MATERIAL_NOTE = "Extraction: tonnes taken from nature (metal ores as gross ore), not content in the product"


class NotBuilt(Exception):
    def __init__(self) -> None:
        super().__init__(NOT_BUILT)


class ShockError(ValueError):
    """A shock request the model cannot run (unknown region or sector, bad size, nothing to shock)."""


class UnknownNode(KeyError):
    def __init__(self, node_id: str) -> None:
        super().__init__(f"unknown node '{node_id}'")

    def __str__(self) -> str:
        return self.args[0]


class UnknownMaterial(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(f"unknown material '{key}'")


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
    extracted_t: float | None = None  # embodied tonnes of the requested material; None without one


@dataclass(frozen=True)
class Footprint:
    indicator: str
    unit: str
    total: float
    in_home_region: float | None
    by_region: list[tuple[str, float]]
    by_sector: list[tuple[str, float]]


@dataclass(frozen=True)
class QuantityShock:
    model: str
    unit: str
    change_pct: float
    total_meur: float
    by_region: list[tuple[str, float]]
    by_sector: list[tuple[str, float]]
    nodes: list[tuple[Node, float]]
    shocked: list[tuple[str, float, float]]
    skipped: list[str]
    indicators: dict[str, float]
    focus: tuple[str, float] | None


@dataclass(frozen=True)
class PriceShock:
    carbon_eur_per_t: float
    covered_regions: list[str]
    priced_t: float
    carbon_cost_meur: float
    by_region: list[tuple[str, float]]
    by_sector: list[tuple[str, float]]
    nodes: list[tuple[Node, float]]
    focus: tuple[str, float] | None


def region_label(code: str) -> str:
    return ROW_LABELS.get(code, code)


def sector_name(raw: str) -> str:
    """The sector as the explorer shows it: the archive's name without a trailing " (31)"."""
    return re.sub(r" \(\d+\)$", "", raw)


def _opt(cell: str) -> float | None:
    return float(cell) if cell else None


def _read_nodes(path: Path) -> list[Node]:
    with path.open(newline="") as f:
        return [
            Node(
                r["node_id"], r["region"], region_label(r["region"]), sector_name(r["sector"]),
                float(r["output_meur"]), r["goods"] == "true", _opt(r["ghg_t_per_meur"]),
                _opt(r["energy_tj_per_meur"]), _opt(r["jobs_per_meur"]), _opt(r["va_share"]),
            )
            for r in csv.DictReader(f)
        ]


def _groups(names: np.ndarray, codes: np.ndarray, values: np.ndarray, top: int) -> list[tuple[str, float]]:
    sums = np.bincount(codes, weights=values, minlength=len(names))
    nz = np.flatnonzero(sums)
    return [(str(names[i]), float(sums[i])) for i in nz[np.lexsort((names[nz], -sums[nz]))][:top]]


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
        self._region_codes = np.array([n.region for n in self._nodes])
        self._sector_names = np.array([n.sector for n in self._nodes])
        # only live nodes count: a region or sector with no live node is unknown to the shocks
        self._live_regions = set(self._region_codes[self._live].tolist())
        self._live_sectors = set(self._sector_names[self._live].tolist())
        # shock bases, spec value-chain-shocks Definitions: final demand and primary inputs, from A and x alone
        self._y = self._x - self._a @ self._x
        self._v = self._x * (1 - self._a.sum(axis=0))
        listing = directory / "materials.json"  # absent when the archive had no material/F.txt
        self.materials: list[dict] = json.loads(listing.read_text()) if listing.is_file() else []
        if self.materials:
            self._material_m, self._material_M = (np.load(directory / f"material_{m}.npy") for m in "mM")
        self._material_row = {m["key"]: j for j, m in enumerate(self.materials)}

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

    def _material(self, key: str) -> int:
        if key not in self._material_row:
            raise UnknownMaterial(key)
        return self._material_row[key]

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
        material: str | None = None, amount_meur: float = 1.0,
    ) -> TreeItem:
        root = self._k(node_id)  # an unknown node is a 404 before any material check
        total = None
        if material is not None:
            j = self._material(material)
            total = self._material_M[j]

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
            return TreeItem(self._nodes[k], coef, chain, kids, None if total is None else amount_meur * chain * float(total[k]))

        return grow(root, 1.0, 1.0, 0)

    def footprint(
        self, node_id: str, indicator: str, amount_meur: float = 1.0, top: int = 6,
    ) -> Footprint:
        """`indicator` is ghg, energy, jobs or material:<key>."""
        k = self._k(node_id)
        if indicator.startswith("material:"):
            j = self._material(indicator.removeprefix("material:"))  # before the attribute: F0 builds have none
            intensity, unit = self._material_m[j], MATERIAL_UNIT
        else:
            intensity, unit = self._intensity[indicator], UNITS[indicator]
        contribution = intensity * self._l[:, k] * amount_meur
        total = float(contribution.sum())

        in_home = float(contribution[self._region_of == self._region_of[k]].sum()) / total if total else None
        return Footprint(
            indicator, unit, total, in_home,
            self.by_region(contribution, top), self.by_sector(contribution, top),
        )

    def _check_known(self, regions: Sequence[str], sectors: Sequence[str] = ()) -> None:
        for code in regions:
            if code not in self._live_regions:
                raise ShockError(f"unknown region '{code}'")
        for name in sectors:
            if name not in self._live_sectors:
                raise ShockError(f"unknown sector '{name}'")

    def _selection(self, nodes: Sequence[str], regions: Sequence[str], sectors: Sequence[str]) -> np.ndarray:
        sel = np.zeros(len(self._nodes), dtype=bool)
        for node_id in nodes:
            sel[self._k(node_id)] = True
        self._check_known(regions, sectors)
        sel |= np.isin(self._region_codes, list(regions)) | np.isin(self._sector_names, list(sectors))
        return sel & self._live

    def _by_id(self, mask: np.ndarray) -> np.ndarray:
        idx = np.flatnonzero(mask)
        return idx[np.argsort(self._rank[idx])]

    def _shock_lists(
        self, values: np.ndarray, top: int, by_abs: bool, weights: np.ndarray | None = None,
    ) -> tuple[list[tuple[str, float]], list[tuple[str, float]], list[tuple[Node, float]]]:
        """By-region, by-sector and node lists of a per-node result over live nodes, zeros left out.
        With `weights`, groups are weighted means instead of sums."""
        key = np.abs if by_abs else (lambda a: a)
        live = values * self._live

        def groups(names: np.ndarray, codes: np.ndarray) -> list[tuple[str, float]]:
            if weights is None:
                g = np.bincount(codes, weights=live, minlength=len(names))
            else:
                w = weights * self._live
                den = np.bincount(codes, weights=w, minlength=len(names))
                g = np.divide(np.bincount(codes, weights=live * w, minlength=len(names)), den,
                              out=np.zeros(len(names)), where=den > 0)
            nz = np.flatnonzero(g)
            return [(str(names[i]), float(g[i])) for i in nz[np.lexsort((names[nz], -key(g[nz])))][:top]]

        ranked = self._ranked(key(live), np.flatnonzero(live))[:top]
        return (
            groups(self._regions, self._region_of), groups(self._sectors, self._sector_of),
            [(self._nodes[i], float(values[i])) for i in ranked],
        )

    def shock_quantity(
        self, model: Literal["demand", "supply"], change: float, unit: Literal["pct", "meur"] = "pct",
        nodes: Sequence[str] = (), regions: Sequence[str] = (), sectors: Sequence[str] = (), top: int = 6,
        focus: str | None = None,
    ) -> QuantityShock:
        """Leontief demand shock (dx = L·dy) or Ghosh supply dependency (dx' = dv'·G); spec value-chain-shocks."""
        f = self._k(focus) if focus is not None else None
        if not (nodes or regions or sectors):
            raise ShockError("select at least one node, region or sector")
        sel = self._selection(nodes, regions, sectors)
        base = self._y if model == "demand" else self._v
        # relative tolerance: a true zero base derived from x − A·x can come out as ±1e-13
        positive = base > 1e-9 * self._x
        shocked, skipped = sel & positive, sel & ~positive
        if not shocked.any():
            raise ShockError("no selected node has a positive base")
        if unit == "pct":
            if not -100 <= change <= 100:
                raise ShockError("change in pct must be between -100 and 100")
            change_pct = change
        else:
            total_base = float(base[shocked].sum())
            if change == 0 or abs(change) > total_base:
                raise ShockError(f"change in meur must be non-zero and at most {total_base} in absolute value")
            change_pct = 100 * change / total_base
        d = np.where(shocked, change_pct / 100 * base, 0.0)
        dx = self._l @ d if model == "demand" else d @ self._g
        dx = np.where(self._live, dx, 0.0)
        by_region, by_sector, top_nodes = self._shock_lists(dx, top, by_abs=True)
        return QuantityShock(
            model, unit, change_pct, float(dx.sum()), by_region, by_sector, top_nodes,
            [(self._nodes[i].node_id, float(base[i]), float(d[i])) for i in self._by_id(shocked)],
            [self._nodes[i].node_id for i in self._by_id(skipped)],
            {k: float(self._intensity[k] @ dx) for k in INTENSITY},
            (self._nodes[f].node_id, float(dx[f])) if f is not None else None,
        )

    def shock_price(
        self, carbon_eur_per_t: float, regions: Sequence[str] = (), top: int = 6, focus: str | None = None,
    ) -> PriceShock:
        """Leontief carbon cost-push: dp' = c'·L, c = τ · GHG intensity / 10⁶ in covered regions."""
        f = self._k(focus) if focus is not None else None
        self._check_known(regions)
        covered = sorted(set(regions) if regions else self._live_regions)
        cov = np.isin(self._region_codes, covered) & self._live
        ghg = self._intensity["ghg"]
        c = np.where(cov, carbon_eur_per_t * ghg / 1e6, 0.0)
        dp_pct = np.where(self._live, 100 * (c @ self._l), 0.0)
        priced_t = float(ghg[cov] @ self._x[cov])
        by_region, by_sector, top_nodes = self._shock_lists(dp_pct, top, by_abs=False, weights=self._x)
        return PriceShock(
            carbon_eur_per_t, covered, priced_t, carbon_eur_per_t * priced_t / 1e6, by_region, by_sector,
            top_nodes, (self._nodes[f].node_id, float(dp_pct[f])) if f is not None else None,
        )

    def by_region(self, values: np.ndarray, top: int) -> list[tuple[str, float]]:
        """Per-node values summed by region label; zero groups left out, value descending, ties by name."""
        return _groups(self._regions, self._region_of, values, top)

    def by_sector(self, values: np.ndarray, top: int) -> list[tuple[str, float]]:
        return _groups(self._sectors, self._sector_of, values, top)


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
