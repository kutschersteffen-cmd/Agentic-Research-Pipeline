from __future__ import annotations

import functools
import math
import weakref
from dataclasses import dataclass

import numpy as np

from arp.llm.base import LLMClient
from arp.portfolio.climate.schemas import FIELD_EVIC, FIELD_REVENUE
from arp.portfolio.datapoint_mapping import resolve_field_values_for_universe
from arp.research.indirect_exposure.company_mapper import lookup_isic, resolve_company_isic
from arp.research.indirect_exposure.factory import code_list
from arp.research.indirect_exposure.io_import import country_regions
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.value_chain.model import UNITS, ValueChain, sector_name
from arp.schemas.common import CompanyRef, now_iso
from arp.schemas.thematic import ActivityDefinition
from arp.schemas.value_chain import LinkRule
from arp.storage.portfolio_store import portfolio_directories

# Company and activity links to value-chain nodes, and the portfolio overlay built on them.
# docs/superpowers/specs/2026-10-27-value-chain-links-overlays-design.md. Rules are resolved against the
# current build on every request; every number here is arithmetic, the LLM only runs in classify_unlinked.


class LinkError(ValueError):
    """A rule the API answers with 422; the message is the response's `detail`."""


@dataclass(frozen=True)
class Resolution:
    source: str  # nodes | split | code | llm | none
    region: str | None
    weights: dict[int, float]  # ValueChain node index -> weight, summing to 1 (or empty)
    unresolved: list[dict]


def company_subject(company_id: str) -> str:
    return f"company:{company_id}"


def activity_subject(taxonomy_id: str, activity_id: str) -> str:
    return f"activity:{taxonomy_id}/{activity_id}"


def _per_build(fn):
    """Caches fn(vc) for as long as that build is alive, so a rebuild frees the old build's lookups with it."""
    cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    @functools.wraps(fn)
    def cached(vc: ValueChain):
        if vc not in cache:
            cache[vc] = fn(vc)
        return cache[vc]

    return cached


@_per_build
def _code_nodes(vc: ValueChain) -> dict[str, np.ndarray]:
    """Live node indices per ICIO code: the nodes whose sector the code covers."""
    covers = {c: {sector_name(s) for s in sectors} for c, sectors in code_list().covers.items()}
    sectors = np.array([n.sector for n in vc._nodes])
    return {c: np.flatnonzero(vc._live & np.isin(sectors, list(names))) for c, names in covers.items()}


@_per_build
def _node_at(vc: ValueChain) -> dict[tuple[str, str], int]:
    return {(n.region, n.sector): i for i, n in enumerate(vc._nodes) if vc._live[i]}


@_per_build
def _live_regions(vc: ValueChain) -> frozenset[str]:
    return frozenset(r for r, _ in _node_at(vc))


def company_region(vc: ValueChain, country: str | None) -> str | None:
    region = country_regions().get(country.upper()) if country else None
    return region if region in _live_regions(vc) else None


def _by_output(vc: ValueChain, idx: np.ndarray) -> dict[int, float]:
    """Each node weighted by x / sum x over the set; empty for an empty set."""
    x = vc._x[idx]
    return dict(zip(idx.tolist(), (x / x.sum()).tolist(), strict=True))


def _code_set(vc: ValueChain, code: str, region: str | None) -> dict[int, float]:
    idx = _code_nodes(vc)[code]
    if region is not None:
        idx = idx[[vc._nodes[i].region == region for i in idx]]
    return _by_output(vc, idx)


def _resolve_parts(vc: ValueChain, rule: LinkRule, region: str | None) -> tuple[dict[int, float], list[dict]]:
    weights: dict[int, float] = {}
    unresolved: list[dict] = []
    for part in rule.parts:
        if rule.kind == "nodes":
            k = _node_at(vc).get((part["region"], part["sector"]))
            found = {} if k is None else {k: 1.0}
        else:
            found = _code_set(vc, part["icio_code"], region)
        if not found:
            unresolved.append(part)
        for k, w in found.items():
            weights[k] = weights.get(k, 0.0) + part["share"] * w
    total = sum(weights.values())  # below 1 only when parts are unresolved: rescale the rest to 1
    if total:
        weights = {k: w / total for k, w in weights.items()}
    return weights, unresolved


def company_source(company: CompanyRef, rule: LinkRule | None) -> str:
    """Which resolution step applies; needs no build, so classify_unlinked can use it."""
    if rule is not None and rule.kind in ("nodes", "split"):
        return rule.kind
    if lookup_isic(company.isic_code, code_list()) is not None:
        return "code"
    return "llm" if rule is not None else "none"


def resolve_company(vc: ValueChain, company: CompanyRef, rule: LinkRule | None) -> Resolution:
    region = company_region(vc, company.country)
    source = company_source(company, rule)
    if source in ("nodes", "split", "llm"):
        return Resolution(source, region, *_resolve_parts(vc, rule, region))
    if source == "none":
        return Resolution(source, region, {}, [])
    code = lookup_isic(company.isic_code, code_list())
    weights = _code_set(vc, code, region)  # a code with no node here is reported like an llm rule's part
    return Resolution(source, region, weights, [] if weights else [{"icio_code": code, "share": 1.0}])


def resolve_activity(vc: ValueChain, activity: ActivityDefinition, rule: LinkRule | None) -> Resolution:
    if rule is not None:
        return Resolution("nodes", None, *_resolve_parts(vc, rule, None))
    idx = np.unique(np.concatenate([_code_nodes(vc)[c] for c in activity.core_isic_codes if c in _code_nodes(vc)] or [[]]))
    weights = _by_output(vc, idx.astype(np.intp))
    return Resolution("code" if weights else "none", None, weights, [])


def weighted_nodes(vc: ValueChain, weights: dict[int, float]) -> list[dict]:
    """{node_id, region_label, sector, weight}, weight descending, ties by node id."""
    return [_ref(vc, k, w) for k, w in sorted(weights.items(), key=lambda p: (-p[1], vc._rank[p[0]]))]


def validate_rule(vc: ValueChain, kind: str, parts: list, *, company: bool) -> list[dict]:
    """The parts as stored; raises LinkError with the first failing check of spec Appendix B, in its order."""
    if kind == "split" and not company:
        raise LinkError("split is for companies only")
    if not 1 <= len(parts) <= 20:
        raise LinkError("1 to 20 parts")
    keys = ("icio_code",) if kind == "split" else ("region", "sector")
    clean = []
    for p in parts:
        share = p.get("share")
        if not all(isinstance(p.get(k), str) for k in keys) or isinstance(share, bool) or not isinstance(share, int | float):
            raise LinkError(f"each part needs {', '.join(keys)} and a numeric share")
        clean.append({**{k: p[k] for k in keys}, "share": float(share)})
    if len({tuple(p[k] for k in keys) for p in clean}) < len(clean):
        raise LinkError("duplicate part")
    if any(not (p["share"] > 0 and math.isfinite(p["share"])) for p in clean):
        raise LinkError("share must be > 0")
    if abs(sum(p["share"] for p in clean) - 1) > 1e-6:
        raise LinkError("shares must sum to 1")
    for p in clean:
        if kind == "split" and p["icio_code"] not in code_list().codes:
            raise LinkError(f"unknown code '{p['icio_code']}'")
        if kind == "nodes" and (p["region"], p["sector"]) not in _node_at(vc):
            raise LinkError(f"unknown node '{p['region']} · {p['sector']}'")
    return clean


def new_rule(kind: str, parts: list[dict], set_by: str) -> LinkRule:
    return LinkRule(kind=kind, parts=parts, set_by=set_by, set_at=now_iso())


# --- portfolio overlay -------------------------------------------------------


def _ref(vc: ValueChain, k: int, weight: float) -> dict:
    n = vc._nodes[k]
    return {"node_id": n.node_id, "region_label": n.region_label, "sector": n.sector, "weight": weight}


def _top_nodes(vc: ValueChain, values: np.ndarray, top: int) -> list[dict]:
    return [_ref(vc, int(k), float(values[k])) for k in vc._ranked(values, np.flatnonzero(values))[:top]]


def _resolved(vc: ValueChain, store, holdings: list) -> list[tuple]:
    """(holding, security, company_id, NAV weight, resolution or None) per holding."""
    securities, companies = portfolio_directories(store)
    rules = store.list_link_rules()
    nav = sum(h.market_value_eur for h in holdings)
    out = []
    for h in holdings:
        security = securities.get(h.security_id)
        company_id = security.company_id if security else None
        company = companies.get(company_id)
        res = resolve_company(vc, company, rules.get(company_subject(company_id))) if company else None
        out.append((h, security, company_id, h.market_value_eur / nav if nav else 0.0, res))
    return out


def _node_weights(vc: ValueChain, resolved: list[tuple]) -> np.ndarray:
    """W: per node, the NAV share of the linked holdings sitting on it."""
    w = np.zeros(len(vc._nodes))
    for *_, weight, res in resolved:
        for k, share in (res.weights if res else {}).items():
            w[k] += weight * share
    return w


def portfolio_weights(vc: ValueChain, store, holdings: list) -> np.ndarray:
    return _node_weights(vc, _resolved(vc, store, holdings))


def shock_lens(vc: ValueChain, w: np.ndarray, *, dx: np.ndarray | None = None, dp_pct: np.ndarray | None = None) -> tuple[float, float | None]:
    """(linked_weight, the portfolio's holding-weighted output change in % (dx) or price change in % (dp_pct))."""
    linked = float(w.sum())
    if not linked:
        return 0.0, None
    held = np.flatnonzero(w)  # live nodes only, so x > 0
    if dx is not None:
        return linked, 100 * float(w[held] @ (dx[held] / vc._x[held])) / linked
    return linked, float(w[held] @ dp_pct[held]) / linked


def overlay(
    vc: ValueChain, store, holdings: list, as_of: str, *, indicator: str, top: int,
    activity: tuple[str, ActivityDefinition, Resolution] | None = None,
) -> dict:
    """The overlay of spec Appendix B (without edition and caveat) for one snapshot's holdings."""
    resolved = _resolved(vc, store, holdings)
    nav = sum(h.market_value_eur for h in holdings)
    company_ids = sorted({c for _, _, c, _, _ in resolved if c})
    evic = resolve_field_values_for_universe(store, company_ids, FIELD_EVIC, as_of)
    revenue = resolve_field_values_for_universe(store, company_ids, FIELD_REVENUE, as_of)

    n = len(vc._nodes)
    portfolio_w = _node_weights(vc, resolved)  # W
    owned = np.zeros(n)  # sum over attributed holdings of o_h * w_h
    attributed_weight = attributed_meur = 0.0
    rows = []
    for h, security, company_id, weight, res in resolved:
        o_h = None
        if res and res.weights and evic.get(company_id, 0) > 0 and company_id in revenue:
            o_h = (h.market_value_eur / 1e6) / evic[company_id] * revenue[company_id]
            attributed_weight += weight
            attributed_meur += h.market_value_eur / 1e6
            for k, w in res.weights.items():
                owned[k] += o_h * w
        rows.append({
            "security_id": h.security_id, "company_id": company_id, "name": security.name if security else h.security_id,
            "market_value_eur": h.market_value_eur, "weight": weight, "link_source": res.source if res else "none",
            "top_node": weighted_nodes(vc, res.weights)[0] if res and res.weights else None,
            "owned_output_meur": o_h,
        })
    rows.sort(key=lambda r: (-r["weight"], r["security_id"]))

    linked_weight = float(portfolio_w.sum())
    mix = portfolio_w / linked_weight if linked_weight else portfolio_w
    upstream = vc._l @ mix - mix
    upstream_total = float(upstream.sum())
    contribution = vc._intensity[indicator] * (vc._l @ owned)
    footprint_total = float(contribution.sum())

    activity_out = None
    if activity is not None:
        taxonomy_id, definition, res = activity
        members = list(res.weights)
        activity_out = {
            "taxonomy_id": taxonomy_id, "activity_id": definition.activity_id, "name": definition.name,
            "direct_weight": float(portfolio_w[members].sum()),
            "upstream_share": float(upstream[members].sum()) / upstream_total if upstream_total else None,
        }
    return {
        "as_of": as_of, "nav_eur": nav, "linked_weight": linked_weight, "attributed_weight": attributed_weight,
        "holdings": rows,
        "nodes": _top_nodes(vc, portfolio_w, top),
        "direct_by_region": vc.by_region(portfolio_w, top),
        "upstream_total": upstream_total,
        "upstream_by_region": vc.by_region(upstream, top),
        "upstream_by_sector": vc.by_sector(upstream, top),
        "upstream_nodes": _top_nodes(vc, upstream, top),
        "footprint": {
            "indicator": indicator, "unit": UNITS[indicator], "total": footprint_total,
            "per_meur_invested": footprint_total / attributed_meur if attributed_meur else None,
            "by_region": vc.by_region(contribution, top),
        },
        "activity": activity_out,
    }


# --- Scope 6: the one place the LLM picks a code ------------------------------


async def classify_unlinked(store, portfolio_id: str, as_of: str, model: LeontiefModel, llm: LLMClient) -> tuple[int, int]:
    """Runs spec 1's resolve_company_isic on every company held on `as_of` whose link resolves to `none`
    and stores each code it gets as an `llm` rule. Returns (classified, left unlinked)."""
    securities, companies = portfolio_directories(store)
    held = dict.fromkeys(
        s.company_id for h in store.load_holdings_as_of(as_of, [portfolio_id])
        if (s := securities.get(h.security_id)) and s.company_id in companies
    )
    classified = unlinked = 0
    for company_id in held:
        company = companies[company_id]
        if company_source(company, store.get_link_rule(company_subject(company_id))) != "none":
            continue
        code, _ = await resolve_company_isic(company, model, llm)
        if code is None:
            unlinked += 1
            continue
        store.save_link_rule(company_subject(company_id), new_rule("llm", [{"icio_code": code, "share": 1.0}], "llm"))
        classified += 1
    return classified, unlinked
