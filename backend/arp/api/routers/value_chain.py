from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from arp.config import Settings
from arp.research.value_chain.model import (
    MATERIAL_NOTE,
    NOT_BUILT,
    NotBuilt,
    UnknownMaterial,
    UnknownNode,
    ValueChain,
    load_value_chain,
)
from arp.schemas.value_chain import (
    ValueChainFootprint,
    ValueChainLink,
    ValueChainMaterial,
    ValueChainMaterialFootprint,
    ValueChainMaterialTree,
    ValueChainMaterialTreeNode,
    ValueChainNode,
    ValueChainNodeRef,
    ValueChainSearch,
    ValueChainStatus,
    ValueChainTree,
    ValueChainTreeNode,
)

router = APIRouter(prefix="/api/value-chain", tags=["value-chain"])


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
