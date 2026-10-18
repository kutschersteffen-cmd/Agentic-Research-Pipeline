"""Theme exposure layers: Layer 1 (direct revenue share), Layer 2 (revenue from exposed customers
up to two supply hops away), Layer 3 (no data yet) and the score S = w1*L1 + w2*L2 + w3*L3.
Computed on read from a theme run, the supply edges known at `as_of` and the settings
(spec: docs/superpowers/specs/2026-10-18-themes-exposure-layers-design.md)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime

from arp.config import Settings
from arp.schemas.common import CompanyRef
from arp.schemas.issuer import issuer_key


class LayerSettingsError(ValueError):
    """A theme-layer setting is out of range; the message names the setting."""


@dataclass(frozen=True)
class LayerParams:
    w1: float
    w2: float
    w3: float
    decay: float
    max_hops: int
    pure_play_threshold: float


@dataclass(frozen=True)
class Edge:
    """The version of one supplier -> customer edge in force at `as_of`."""

    supplier_key: str
    customer_key: str
    revenue_share: float


@dataclass
class LayerRow:
    issuer_key: str
    name: str
    in_run: bool
    l1: float | None
    l2: float | None
    l3: None
    score: float | None
    pure_play: bool
    status: str
    rank: int | None
    l2_via: list[str] | None


def layer_params(settings: Settings) -> LayerParams:
    for n in (1, 2, 3):
        if getattr(settings, f"theme_layer_w{n}") < 0:
            raise LayerSettingsError(f"ARP_THEME_LAYER_W{n} must be 0 or more")
    if not 0 < settings.theme_layer_decay <= 1:
        raise LayerSettingsError("ARP_THEME_LAYER_DECAY must be greater than 0 and at most 1")
    if settings.theme_layer_max_hops not in (1, 2):
        raise LayerSettingsError("ARP_THEME_LAYER_MAX_HOPS must be 1 or 2")
    return LayerParams(
        settings.theme_layer_w1, settings.theme_layer_w2, settings.theme_layer_w3,
        settings.theme_layer_decay, settings.theme_layer_max_hops, settings.revenue_exposure_pure_play_threshold,
    )


def _l1(matches: list[dict]) -> float | None:
    values = [
        rev["value_pct"]
        for m in matches
        if m.get("verdict") == "include"
        and (rev := (m.get("revenue_exposure") or {}).get("revenue") or {}).get("source") in ("catalogue", "extracted")
        and rev.get("value_pct") is not None
    ]
    return max(values, default=None)


def run_company_l1(companies: list[CompanyRef], result_rows: list[dict]) -> list[tuple[str, str, float | None]]:
    """(issuer_key, name, L1) per run company, in run order; the first company with a key wins."""
    matches: dict[str, list[dict]] = defaultdict(list)
    for row in result_rows:
        for m in row.get("company_matches", []):
            matches[m.get("company_id")].append(m)
    out: dict[str, tuple[str, str, float | None]] = {}
    for ref in companies:
        key = issuer_key(ref)[0]
        out.setdefault(key, (key, ref.name, _l1(matches[ref.company_id])))
    return list(out.values())


def _paths(node, path, product, out, anchors, params):
    """(path, contribution) for every simple path of 1..max_hops edges from path[0] to a company with L1."""
    for e in out.get(node, ()):
        if e.customer_key in path:
            continue
        p, nxt = product * e.revenue_share, path + [e.customer_key]
        hops = len(nxt) - 1
        if anchors.get(e.customer_key) is not None:
            yield nxt, p * anchors[e.customer_key] * params.decay**hops
        if hops < params.max_hops:
            yield from _paths(e.customer_key, nxt, p, out, anchors, params)


def compute_layers(
    run_companies: list[tuple[str, str, float | None]], edges: list[Edge], node_names: dict[str, str], params: LayerParams
) -> list[LayerRow]:
    anchors = {key: l1 for key, _name, l1 in run_companies}
    names = {key: name for key, name, _l1 in run_companies}
    out: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        out[e.supplier_key].append(e)
    l2: dict[str, tuple[float, list[str]]] = {}
    for supplier in out:
        found = list(_paths(supplier, [supplier], 1.0, out, anchors, params))
        if found:
            best_path, _ = min(found, key=lambda pc: (-pc[1], pc[0]))
            l2[supplier] = (min(1.0, sum(c for _, c in found)), best_path)

    rows = []
    for key in list(anchors) + [k for k in l2 if k not in anchors]:
        l1 = anchors.get(key)
        layer2, via = l2.get(key, (None, None))
        scored = l1 is not None or layer2 is not None
        rows.append(LayerRow(
            issuer_key=key,
            name=names.get(key) or node_names.get(key, key),
            in_run=key in anchors,
            l1=l1,
            l2=layer2,
            l3=None,
            score=params.w1 * (l1 or 0) + params.w2 * (layer2 or 0) if scored else None,  # L3 has no data: w3 * 0
            pure_play=l1 is not None and l1 >= params.pure_play_threshold,
            status="scored" if scored else "insufficient data",
            rank=None,
            l2_via=via,
        ))
    rows.sort(key=lambda r: (r.score is None, -(r.score or 0), r.issuer_key))
    for rank, r in enumerate((r for r in rows if r.score is not None), start=1):
        r.rank = rank
    return rows


def load_run_layers(settings: Settings, run_store, run_id: str, as_of: date) -> tuple[LayerParams, list[LayerRow]]:
    """The layers of a theme run at `as_of`. Raises, in this order: LookupError (no such theme run),
    LayerSettingsError, CompanyGraphError (not configured or unreachable)."""
    from arp.company_graph import edges_at, open_graph  # company_graph imports Edge from here

    manifest = run_store.load_manifest(run_id)
    if manifest is None or manifest.run_type != "theme":
        raise LookupError(f"unknown theme run '{run_id}'")
    params = layer_params(settings)
    with open_graph(settings) as driver:
        edges, names = edges_at(driver, as_of)
    run = run_company_l1(run_store.load_companies(run_id) or [], run_store.read_results(run_id))
    return params, compute_layers(run, edges, names, params)


def parse_as_of(value: str | None) -> date:
    """`as_of` in YYYY-MM-DD form; today (UTC) when omitted."""
    if value is None:
        return datetime.now(UTC).date()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("as_of must be a date in YYYY-MM-DD form") from None
