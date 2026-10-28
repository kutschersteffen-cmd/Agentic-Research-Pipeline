from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from arp.api.auth import Principal, current_user
from arp.api.deps import get_portfolio_store, get_taxonomy_store
from arp.config import Settings
from arp.research.indirect_exposure.factory import code_list
from arp.research.value_chain import links as vc_links
from arp.research.value_chain.model import (
    INTENSITY,
    MATERIAL_NOTE,
    NOT_BUILT,
    NotBuilt,
    ShockError,
    UnknownMaterial,
    UnknownNode,
    ValueChain,
    load_value_chain,
)
from arp.schemas.value_chain import (
    IcioCode,
    LinkRuleIn,
    PriceShockFocus,
    PriceShockNode,
    QuantityShockFocus,
    QuantityShockNode,
    ShockedNode,
    ShockIndicators,
    ValueChainFootprint,
    ValueChainLink,
    ValueChainLinks,
    ValueChainMaterial,
    ValueChainMaterialFootprint,
    ValueChainMaterialTree,
    ValueChainMaterialTreeNode,
    ValueChainNode,
    ValueChainNodeRef,
    ValueChainPortfolio,
    ValueChainPriceShock,
    ValueChainQuantityShock,
    ValueChainSearch,
    ValueChainStatus,
    ValueChainTree,
    ValueChainTreeNode,
)
from arp.storage.taxonomy_store import TaxonomyStore

router = APIRouter(prefix="/api/value-chain", tags=["value-chain"])

MODEL_CAVEATS = {
    "demand": "Linear Leontief model: fixed input recipes, no substitution, no capacity limits, no price effects.",
    "supply": (
        "Ghosh dependency indicator, not a forecast: downstream output resting on the lost inputs if every buyer "
        "keeps its sales shares; no substitution or rerouting."
    ),
    "price": (
        "Leontief cost-push: full pass-through of the carbon cost, no substitution, no demand response; producers' "
        "direct emissions only, households' own emissions not priced; basic prices."
    ),
}


def _chain() -> ValueChain:
    # Settings(), not get_settings(): ARP_VALUE_CHAIN_DIR is read on every request.
    try:
        return load_value_chain(Settings().value_chain_dir)
    except (NotBuilt, FileNotFoundError):  # FileNotFoundError: a manifest without its nodes.csv or .npy files
        raise HTTPException(503, NOT_BUILT) from None


@contextmanager
def _unknown_is_404() -> Iterator[None]:
    try:
        yield
    except UnknownNode as e:
        raise HTTPException(404, str(e)) from None
    except UnknownMaterial as e:
        raise HTTPException(422, str(e)) from None


def _ref(n) -> dict:
    return {"node_id": n.node_id, "region": n.region, "region_label": n.region_label, "sector": n.sector}


def _tree(t) -> ValueChainTreeNode:
    fields = {"node_id": t.node.node_id, "region_label": t.node.region_label, "sector": t.node.sector, "coef": t.coef, "chain": t.chain}
    if t.extracted_t is None:
        return ValueChainTreeNode(**fields, children=[_tree(c) for c in t.children])
    return ValueChainMaterialTreeNode(**fields, extracted_t=t.extracted_t, children=[_tree(c) for c in t.children])


@router.get("/status")
def status(vc: ValueChain = Depends(_chain)) -> ValueChainStatus:
    m = vc.manifest
    return ValueChainStatus(
        edition=m["edition"], version=m["exiobase_version"], year=m["year"], n_nodes=m["n_nodes"],
        n_regions=m["n_regions"], n_sectors=m["n_sectors"], built_at=m["built_at"], caveat=vc.caveat,
        materials=[ValueChainMaterial(**x) for x in vc.materials],
    )


@router.get("/nodes")
def search(
    q: Annotated[str, Query(min_length=1, pattern=r"\S", description="Sector or region; blank is rejected.")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    vc: ValueChain = Depends(_chain),
) -> ValueChainSearch:
    return ValueChainSearch(
        edition=vc.manifest["edition"], caveat=vc.caveat,
        items=[ValueChainNodeRef(**_ref(n)) for n in vc.search(q, limit)],
    )


@router.get("/nodes/{node_id}")
def node(
    node_id: str,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    exclude_own: bool = False,
    order: Literal["total", "direct"] = "total",
    vc: ValueChain = Depends(_chain),
) -> ValueChainNode:
    def links(side: Literal["suppliers", "customers"]) -> list[ValueChainLink]:
        return [
            ValueChainLink(**_ref(x.node), direct=x.direct, total=x.total)
            for x in vc.links(node_id, side, order, limit, exclude_own)
        ]

    with _unknown_is_404():
        n = vc.node(node_id)
        return ValueChainNode(
            **_ref(n), edition=vc.manifest["edition"], caveat=vc.caveat, output_meur=n.output_meur,
            ghg_t_per_meur=n.ghg_t_per_meur, energy_tj_per_meur=n.energy_tj_per_meur, jobs_per_meur=n.jobs_per_meur,
            va_share=n.va_share, suppliers=links("suppliers"), customers=links("customers"),
        )


@router.get("/nodes/{node_id}/tree")
def tree(
    node_id: str,
    depth: Annotated[int, Query(ge=1, le=4)] = 2,
    width: Annotated[int, Query(ge=1, le=5)] = 3,
    cutoff: Annotated[float, Query(ge=0, le=1)] = 0.01,
    goods_only: bool = False,
    material: Annotated[str | None, Query(description="A key from /status materials: adds extracted_t to every box.")] = None,
    amount_meur: Annotated[float, Query(allow_inf_nan=False, description="Used only with material; must be > 0.")] = 1.0,
    vc: ValueChain = Depends(_chain),
) -> ValueChainTree | ValueChainMaterialTree:
    if material is not None and amount_meur <= 0:
        raise HTTPException(422, "amount_meur must be greater than 0")
    with _unknown_is_404():
        root = _tree(vc.tree(node_id, depth, width, cutoff, goods_only, material, amount_meur))
    meta = {"edition": vc.manifest["edition"], "caveat": vc.caveat}
    if material is None:
        return ValueChainTree(**root.model_dump(), **meta)
    return ValueChainMaterialTree(**root.model_dump(), **meta, material_note=MATERIAL_NOTE)


@router.get("/nodes/{node_id}/footprint")
def footprint(
    node_id: str,
    indicator: Annotated[str, Query(pattern=r"^(ghg|energy|jobs|material:.+)$", description="ghg, energy, jobs or material:<key>.")] = "ghg",
    amount_meur: Annotated[float, Query(gt=0, allow_inf_nan=False)] = 1.0,
    top: Annotated[int, Query(ge=1, le=20)] = 6,
    vc: ValueChain = Depends(_chain),
) -> ValueChainFootprint | ValueChainMaterialFootprint:
    with _unknown_is_404():
        f = vc.footprint(node_id, indicator, amount_meur, top)
    body = {
        "edition": vc.manifest["edition"], "caveat": vc.caveat, "indicator": f.indicator, "unit": f.unit, "total": f.total,
        "in_home_region": f.in_home_region, "by_region": f.by_region, "by_sector": f.by_sector,
    }
    if indicator.startswith("material:"):
        return ValueChainMaterialFootprint(**body, material_note=MATERIAL_NOTE)
    return ValueChainFootprint(**body)



def _store_if_asked(request: Request):
    """The portfolio store, built only for a shock with ?portfolio=, so a plain shock needs no database;
    looked up through dependency_overrides like Depends(get_portfolio_store) would be."""
    if request.query_params.get("portfolio") is None:
        return None
    return request.app.dependency_overrides.get(get_portfolio_store, get_portfolio_store)()


@contextmanager
def _shock_errors_are_422() -> Iterator[None]:
    try:
        yield
    except (UnknownNode, ShockError) as e:
        raise HTTPException(422, str(e)) from None


# GET so the viewer role can run shocks; selections are repeated query parameters (spec value-chain-shocks).
@router.get("/shock/quantity")
def shock_quantity(
    model: Literal["demand", "supply"],
    change: Annotated[float, Query(allow_inf_nan=False, description="Percent (unit=pct) or total M EUR (unit=meur).")],
    unit: Literal["pct", "meur"] = "pct",
    node: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI copies query defaults
    region: Annotated[list[str], Query(description="Region codes.")] = [],  # noqa: B006
    sector: Annotated[list[str], Query(description="Sector names as the API shows them.")] = [],  # noqa: B006
    top: Annotated[int, Query(ge=1, le=20)] = 6,
    focus: str | None = None,
    portfolio: Annotated[str | None, Query(description="Adds the portfolio's holding-weighted output change.")] = None,
    as_of: Annotated[str | None, Query(description="The portfolio's snapshot on or before this date; default latest.")] = None,
    vc: ValueChain = Depends(_chain),
    store=Depends(_store_if_asked),
) -> ValueChainQuantityShock:
    snapshot = _lens_snapshot(store, portfolio, as_of)
    with _shock_errors_are_422():
        s = vc.shock_quantity(model, change, unit, node, region, sector, top, focus)
    lens = _lens(vc, store, portfolio, snapshot, "change_pct", dx=s.dx) if snapshot else None
    return ValueChainQuantityShock(
        edition=vc.manifest["edition"], caveat=vc.caveat, model_caveat=MODEL_CAVEATS[model], model=s.model,
        unit=s.unit, change_pct=s.change_pct, total_meur=s.total_meur, by_region=s.by_region,
        by_sector=s.by_sector,
        nodes=[
            QuantityShockNode(node_id=n.node_id, region_label=n.region_label, sector=n.sector, delta_meur=v)
            for n, v in s.nodes
        ],
        shocked=[ShockedNode(node_id=i, base_meur=b, shock_meur=d) for i, b, d in s.shocked],
        skipped=s.skipped, indicators=ShockIndicators(**s.indicators),
        focus=QuantityShockFocus(node_id=s.focus[0], delta_meur=s.focus[1]) if s.focus else None, portfolio=lens,
    )


@router.get("/shock/price")
def shock_price(
    carbon_eur_per_t: Annotated[float, Query(ge=0, le=10_000, allow_inf_nan=False)],
    region: Annotated[list[str], Query(description="Covered region codes; all when none.")] = [],  # noqa: B006
    top: Annotated[int, Query(ge=1, le=20)] = 6,
    focus: str | None = None,
    portfolio: Annotated[str | None, Query(description="Adds the portfolio's holding-weighted price change.")] = None,
    as_of: Annotated[str | None, Query(description="The portfolio's snapshot on or before this date; default latest.")] = None,
    vc: ValueChain = Depends(_chain),
    store=Depends(_store_if_asked),
) -> ValueChainPriceShock:
    snapshot = _lens_snapshot(store, portfolio, as_of)
    with _shock_errors_are_422():
        s = vc.shock_price(carbon_eur_per_t, region, top, focus)
    lens = _lens(vc, store, portfolio, snapshot, "dp_pct", dp_pct=s.dp_pct) if snapshot else None
    return ValueChainPriceShock(
        edition=vc.manifest["edition"], caveat=vc.caveat, model_caveat=MODEL_CAVEATS["price"],
        carbon_eur_per_t=s.carbon_eur_per_t, covered_regions=s.covered_regions, priced_t=s.priced_t,
        carbon_cost_meur=s.carbon_cost_meur, by_region=s.by_region, by_sector=s.by_sector,
        nodes=[
            PriceShockNode(node_id=n.node_id, region_label=n.region_label, sector=n.sector, dp_pct=v)
            for n, v in s.nodes
        ],
        focus=PriceShockFocus(node_id=s.focus[0], dp_pct=s.focus[1]) if s.focus else None, portfolio=lens,
    )

# --- links and portfolio overlay: docs/superpowers/specs/2026-10-27-value-chain-links-overlays-design.md ---


@router.get("/codes")
def icio_codes() -> list[IcioCode]:
    """The ICIO codes a revenue split may name: the 50 industries, then the five electricity split codes."""
    codes = code_list()
    return [IcioCode(code=c, label=codes.labels[c]) for c in codes.codes]


def _snapshot(store, portfolio_id: str, as_of: str | None) -> tuple[str, list]:
    """The portfolio's latest snapshot on or before `as_of` (default: its latest): (date, holdings)."""
    if store.get_portfolio(portfolio_id) is None:
        raise HTTPException(404, f"unknown portfolio '{portfolio_id}'")
    dates = [d for d in store.list_snapshot_dates(portfolio_id) if as_of is None or d <= as_of]
    if not dates:
        raise HTTPException(404, f"no holdings for '{portfolio_id}'" + (f" on or before {as_of}" if as_of else ""))
    return dates[-1], store.load_holdings_as_of(dates[-1], [portfolio_id])


def _lens_snapshot(store, portfolio: str | None, as_of: str | None) -> tuple[str, list] | None:
    """The shocks' portfolio lens input (links spec Scope 8), checked before the shock runs."""
    if as_of is not None and portfolio is None:
        raise HTTPException(422, "as_of needs portfolio")
    return _snapshot(store, portfolio, as_of) if portfolio is not None else None


def _lens(vc: ValueChain, store, portfolio: str, snapshot: tuple[str, list], key: str, **vector) -> dict:
    """Holding-weighted output (`dx`) or price (`dp_pct`) change over the portfolio's nodes."""
    linked, change = vc_links.shock_lens(vc, vc_links.portfolio_weights(vc, store, snapshot[1]), **vector)
    return {"portfolio_id": portfolio, "as_of": snapshot[0], "linked_weight": linked, key: change}


def _company(company_id: str, store):
    company = store.get_company(company_id)
    if company is None:
        raise HTTPException(404, f"unknown company '{company_id}'")
    return company


def _activity(taxonomy_id: str, activity_id: str, taxonomies: TaxonomyStore):
    taxonomy = taxonomies.get(taxonomy_id)
    found = [a for a in taxonomy.theme.activities if a.activity_id == activity_id] if taxonomy else []
    if not found:
        raise HTTPException(404, f"unknown activity '{taxonomy_id}/{activity_id}'")
    return found[0]


def _links(vc: ValueChain, subject: str, res: vc_links.Resolution, rule) -> ValueChainLinks:
    return ValueChainLinks(
        edition=vc.manifest["edition"], caveat=vc.caveat, subject=subject, source=res.source, region=res.region,
        nodes=vc_links.weighted_nodes(vc, res.weights), unresolved=res.unresolved, rule=rule,
    )


def _save(vc: ValueChain, store, subject: str, body: LinkRuleIn, user: Principal, *, company: bool) -> None:
    try:
        parts = vc_links.validate_rule(vc, body.kind, body.parts, company=company)
    except vc_links.LinkError as e:
        raise HTTPException(422, str(e)) from None
    store.save_link_rule(subject, vc_links.new_rule(body.kind, parts, user.name))


@router.get("/links/company/{company_id}")
def company_links(company_id: str, vc: ValueChain = Depends(_chain), store=Depends(get_portfolio_store)) -> ValueChainLinks:
    company = _company(company_id, store)
    subject = vc_links.company_subject(company_id)
    rule = store.get_link_rule(subject)
    return _links(vc, subject, vc_links.resolve_company(vc, company, rule), rule)


@router.put("/links/company/{company_id}")
def put_company_links(
    company_id: str, body: LinkRuleIn, vc: ValueChain = Depends(_chain), store=Depends(get_portfolio_store),
    user: Principal = Depends(current_user),
) -> ValueChainLinks:
    _company(company_id, store)
    _save(vc, store, vc_links.company_subject(company_id), body, user, company=True)
    return company_links(company_id, vc, store)


@router.delete("/links/company/{company_id}", status_code=204)
def delete_company_links(company_id: str, vc: ValueChain = Depends(_chain), store=Depends(get_portfolio_store)) -> Response:
    _company(company_id, store)
    store.delete_link_rule(vc_links.company_subject(company_id))
    return Response(status_code=204)


@router.get("/links/activity/{taxonomy_id}/{activity_id}")
def activity_links(
    taxonomy_id: str, activity_id: str, vc: ValueChain = Depends(_chain), store=Depends(get_portfolio_store),
    taxonomies: TaxonomyStore = Depends(get_taxonomy_store),
) -> ValueChainLinks:
    activity = _activity(taxonomy_id, activity_id, taxonomies)
    subject = vc_links.activity_subject(taxonomy_id, activity_id)
    rule = store.get_link_rule(subject)
    return _links(vc, subject, vc_links.resolve_activity(vc, activity, rule), rule)


@router.put("/links/activity/{taxonomy_id}/{activity_id}")
def put_activity_links(
    taxonomy_id: str, activity_id: str, body: LinkRuleIn, vc: ValueChain = Depends(_chain),
    store=Depends(get_portfolio_store), taxonomies: TaxonomyStore = Depends(get_taxonomy_store),
    user: Principal = Depends(current_user),
) -> ValueChainLinks:
    _activity(taxonomy_id, activity_id, taxonomies)
    _save(vc, store, vc_links.activity_subject(taxonomy_id, activity_id), body, user, company=False)
    return activity_links(taxonomy_id, activity_id, vc, store, taxonomies)


@router.delete("/links/activity/{taxonomy_id}/{activity_id}", status_code=204)
def delete_activity_links(
    taxonomy_id: str, activity_id: str, vc: ValueChain = Depends(_chain), store=Depends(get_portfolio_store),
    taxonomies: TaxonomyStore = Depends(get_taxonomy_store),
) -> Response:
    _activity(taxonomy_id, activity_id, taxonomies)
    store.delete_link_rule(vc_links.activity_subject(taxonomy_id, activity_id))
    return Response(status_code=204)


@router.get("/portfolio/{portfolio_id}")
def portfolio_overlay(
    portfolio_id: str,
    as_of: Annotated[str | None, Query(description="Latest snapshot on or before this date; default the latest.")] = None,
    indicator: str = "ghg",
    top: int = 6,
    taxonomy: str | None = None,
    activity: str | None = None,
    vc: ValueChain = Depends(_chain),
    store=Depends(get_portfolio_store),
    taxonomies: TaxonomyStore = Depends(get_taxonomy_store),
) -> ValueChainPortfolio:
    if not 1 <= top <= 20:
        raise HTTPException(422, "top must be 1 to 20")
    if indicator not in INTENSITY:
        raise HTTPException(422, f"unknown indicator '{indicator}'")
    if (taxonomy is None) != (activity is None):
        raise HTTPException(422, "taxonomy and activity go together")
    snapshot, holdings = _snapshot(store, portfolio_id, as_of)
    lens = None
    if taxonomy is not None:
        definition = _activity(taxonomy, activity, taxonomies)
        rule = store.get_link_rule(vc_links.activity_subject(taxonomy, activity))
        lens = (taxonomy, definition, vc_links.resolve_activity(vc, definition, rule))
    result = vc_links.overlay(vc, store, holdings, snapshot, indicator=indicator, top=top, activity=lens)
    return ValueChainPortfolio(edition=vc.manifest["edition"], caveat=vc.caveat, portfolio_id=portfolio_id, **result)
