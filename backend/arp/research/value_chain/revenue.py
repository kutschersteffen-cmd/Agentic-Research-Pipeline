from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from arp.research.value_chain.model import ValueChain
from arp.schemas.value_chain import Recipe, RecipeIn

# Revenue shares to a target and the routes behind them, and the product recipes a target can be:
# docs/superpowers/specs/2026-10-27-value-chain-revenue-routes-design.md. float64, nothing rounded.

MODEL_CAVEAT = (
    "Revenue shares assume every node sells to its buyers in the table's proportions; "
    "a recipe replaces its home node's purchases only for the recipe's output."
)
RECIPE_PREFIX = "recipe:"
TOL = 1e-9
_RID = re.compile(r"[0-9a-f]{32}")


class UnknownRecipe(KeyError):
    def __init__(self, rid: str) -> None:
        super().__init__(f"unknown recipe '{rid}'")

    def __str__(self) -> str:
        return self.args[0]


class RecipeError(ValueError):
    """A recipe that fails a save check on the current build; `unresolved` when a name has no live node."""

    def __init__(self, detail: str, unresolved: bool = False) -> None:
        super().__init__(detail)
        self.unresolved = unresolved


# --- recipe store ------------------------------------------------------------


class RecipeStore:
    """One `<recipe_id>.json` per recipe. Ids are random uuid4 hex, so a deleted id never comes back."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, rid: str) -> Path:
        if not _RID.fullmatch(rid):  # also keeps a crafted id from naming a path outside the directory
            raise UnknownRecipe(rid)
        return self.directory / f"{rid}.json"

    def list(self) -> list[Recipe]:
        if not self.directory.is_dir():
            return []
        found = [Recipe.model_validate_json(p.read_text()) for p in self.directory.glob("*.json") if _RID.fullmatch(p.stem)]
        return sorted(found, key=lambda r: (r.name, r.recipe_id))

    def get(self, rid: str) -> Recipe:
        path = self._path(rid)
        if not path.is_file():
            raise UnknownRecipe(rid)
        return Recipe.model_validate_json(path.read_text())

    def save(self, recipe: Recipe) -> None:
        path = self._path(recipe.recipe_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(recipe.model_dump(), indent=2) + "\n")
        tmp.replace(path)

    def delete(self, rid: str) -> None:
        self.get(rid)
        self._path(rid).unlink()

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex


# --- recipe checks -----------------------------------------------------------


@dataclass(frozen=True)
class Resolved:
    home: int
    inputs: np.ndarray  # node indices, in input order
    purchases: np.ndarray  # z_i = s_i * q, M EUR


def _fmt(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".")


def check(vc: ValueChain, body: RecipeIn) -> Resolved:
    """The save checks in the spec's order; the first failing one raises RecipeError with its detail."""
    by_name = {(n.region, n.sector): i for i, n in enumerate(vc._nodes)}

    def node(region: str, sector: str) -> int:
        k = by_name.get((region, sector))
        if k is None:
            raise RecipeError(f"unknown node {region} · {sector}", unresolved=True)
        if not vc._live[k]:
            raise RecipeError(f"no output: {region} · {sector}", unresolved=True)
        return k

    home = node(body.home.region, body.home.sector)
    idx = [node(i.region, i.sector) for i in body.inputs]
    if not 1 <= len(idx) <= 50:
        raise RecipeError("a recipe has 1 to 50 inputs")
    seen: set[int] = set()
    for k, i in zip(idx, body.inputs, strict=True):
        if k in seen:
            raise RecipeError(f"input named twice: {i.region} · {i.sector}")
        seen.add(k)
    for i in body.inputs:
        if not i.share > 0:
            raise RecipeError(f"input share must be above 0: {i.region} · {i.sector}")
    if sum(i.share for i in body.inputs) > 1 + TOL:
        raise RecipeError("input shares add up to more than 1")
    x_h = float(vc._x[home])
    if not 0 < body.output_meur < x_h:
        raise RecipeError(f"output_meur must be below the home node's output ({_fmt(x_h)} M EUR)")
    inputs = np.array(idx)
    purchases = np.array([i.share for i in body.inputs]) * body.output_meur
    bought = vc._a[inputs, home] * x_h  # Z[i, h]
    for k, z, total in zip(inputs, purchases, bought, strict=True):
        if z > total + TOL:
            n, h = vc._nodes[k], vc._nodes[home]
            raise RecipeError(
                f"the recipe buys more from {n.sector} · {n.region_label} than {h.sector} · {h.region_label} does in total"
            )
    return Resolved(home, inputs, purchases)


def status(vc: ValueChain, recipe: RecipeIn) -> str:
    try:
        check(vc, recipe)
    except RecipeError as e:
        return "unresolved" if e.unresolved else "inconsistent"
    return "ok"


# --- revenue shares and routes ------------------------------------------------


@dataclass(frozen=True)
class Target:
    key: str  # as requested: a node id or recipe:<rid>
    d: np.ndarray  # direct share of each node's sales going to the target
    r: np.ndarray  # revenue share to the target
    col: int  # the column of B that B' changes
    recipe: bool


def _sales_row(vc: ValueChain, m: int) -> np.ndarray:
    """B[m, :]: the share of m's sales going to each node."""
    return vc._a[m] * vc._x / vc._x[m]


def node_target(vc: ValueChain, node_id: str) -> Target:
    t = vc._k(node_id)
    d = np.divide(vc._a[:, t] * vc._x[t], vc._x, out=np.zeros(len(vc._x)), where=vc._live)
    # B' = B - B e_t e_tᵀ, so by Sherman-Morrison r = (I - B')⁻¹ B e_t = (G[:, t] - e_t) / G[t, t].
    r = vc._g[:, t].copy()
    r[t] -= 1
    r /= vc._g[t, t]
    return Target(node_id, d, r, t, recipe=False)


def recipe_target(vc: ValueChain, key: str, resolved: Resolved) -> Target:
    h = resolved.home
    d = np.zeros(len(vc._x))
    d[resolved.inputs] = resolved.purchases / vc._x[resolved.inputs]
    # B' = B - d e_hᵀ, so r = (I - B')⁻¹ d = G d / (1 + (G d)_h).
    gd = vc._g[:, resolved.inputs] @ d[resolved.inputs]
    return Target(key, d, gd / (1 + gd[h]), h, recipe=True)


def _bprime_row(vc: ValueChain, target: Target, m: int) -> np.ndarray:
    row = _sales_row(vc, m)
    if target.recipe:
        row[target.col] = max(row[target.col] - target.d[m], 0.0)  # a consistent recipe keeps it ≥ 0 up to rounding
    else:
        row[target.col] = 0.0
    return row


def sellers(vc: ValueChain, target: Target, top: int) -> list[int]:
    """Live nodes with a revenue share above 0, by share descending, ties by node id."""
    return [int(k) for k in vc._ranked(target.r, np.flatnonzero(vc._live & (target.r > 0)))[:top]]


def routes(
    vc: ValueChain, target: Target, from_id: str, max_hops: int, min_share: float, top: int,
) -> tuple[float, list[tuple[list[str], float]]]:
    """The seller's revenue share and its route list: routes of ≤ max_hops hops with share ≥ min_share, ranked
    and cut to top.

    Depth-first over buyers. A prefix ending at m with product p can add at most p · r_m in routes, so a
    branch is dropped once that falls below min_share; every route found that way is exact."""
    # 1e-12 relative slack: a share that equals min_share in decimals is not lost to float rounding.
    start = vc._k(from_id)
    floor = min_share * (1 - 1e-12)
    rows: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def buyers(m: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Buyers j of m with B'[m, j] · r_j ≥ floor (p ≤ 1 only raises the bar), by that bound descending."""
        if m not in rows:
            row = _bprime_row(vc, target, m)
            bound = row * target.r
            j = np.flatnonzero((row > 0) & (bound >= floor))
            j = j[np.argsort(-bound[j], kind="stable")]
            rows[m] = (j, row[j], -bound[j])
        return rows[m]

    found: list[tuple[tuple[int, ...], float]] = []
    stack: list[tuple[tuple[int, ...], float]] = [((start,), 1.0)]
    while stack:
        path, p = stack.pop()
        m = path[-1]
        share = p * target.d[m]
        if target.d[m] > 0 and share >= floor:
            found.append((path, share))
        if len(path) < max_hops:
            j, b, neg_bound = buyers(m)
            cut = np.searchsorted(neg_bound, -floor / p, side="right")  # bound ≥ floor / p
            stack.extend((path + (int(k),), p * float(v)) for k, v in zip(j[:cut], b[:cut], strict=True))

    def named(path: tuple[int, ...]) -> list[str]:
        return [vc._nodes[k].node_id for k in path] + [target.key]

    listed = [(named(path), share) for path, share in found]
    listed.sort(key=lambda x: (-round(x[1], 12), len(x[0]), ">".join(x[0])))
    return float(target.r[start]), listed[:top]
