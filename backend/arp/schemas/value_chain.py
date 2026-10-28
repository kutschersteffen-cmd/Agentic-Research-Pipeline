from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ValueChainMaterial(BaseModel):
    key: str
    label: str
    group: str = Field(description="EXIOBASE material category, e.g. Metal Ores.")


class ValueChainStatus(BaseModel):
    edition: str
    version: str = Field(description="EXIOBASE version from the archive's metadata.json.")
    year: int
    n_nodes: int
    n_regions: int
    n_sectors: int
    built_at: str
    caveat: str
    materials: list[ValueChainMaterial] = Field(description="Materials of the build's extraction accounts; empty without them.")


class ValueChainNodeRef(BaseModel):
    node_id: str
    region: str
    region_label: str
    sector: str


class ValueChainSearch(BaseModel):
    edition: str
    caveat: str
    items: list[ValueChainNodeRef]


class ValueChainLink(ValueChainNodeRef):
    direct: float = Field(description="Euro of this node's output per euro of the opened node's output, direct.")
    total: float = Field(description="The same including intermediaries (Leontief for suppliers, Ghosh for customers).")


class ValueChainNode(ValueChainNodeRef):
    edition: str
    caveat: str
    output_meur: float
    ghg_t_per_meur: float | None
    energy_tj_per_meur: float | None
    jobs_per_meur: float | None
    va_share: float | None
    suppliers: list[ValueChainLink]
    customers: list[ValueChainLink]


class ValueChainTreeNode(BaseModel):
    node_id: str
    region_label: str
    sector: str
    coef: float = Field(description="Direct euro from this node per euro of its parent's output (1 at the root).")
    chain: float = Field(description="Product of coef down the path from the root (1 at the root).")
    children: list[ValueChainTreeNode]


class ValueChainTree(ValueChainTreeNode):
    edition: str
    caveat: str


class ValueChainFootprint(BaseModel):
    edition: str
    caveat: str
    indicator: str
    unit: str
    total: float
    in_home_region: float | None = Field(description="Share of total arising in the node's own region; null when total is 0.")
    by_region: list[tuple[str, float]]
    by_sector: list[tuple[str, float]]


class ShockIndicators(BaseModel):
    ghg: float = Field(description="t CO₂e")
    energy: float = Field(description="TJ")
    jobs: float = Field(description="people")


class ShockedNode(BaseModel):
    node_id: str
    base_meur: float = Field(description="Final demand (demand model) or primary inputs (supply model), M EUR.")
    shock_meur: float


class QuantityShockNode(BaseModel):
    node_id: str
    region_label: str
    sector: str
    delta_meur: float


class QuantityShockFocus(BaseModel):
    node_id: str
    delta_meur: float


class ValueChainQuantityShock(BaseModel):
    edition: str
    caveat: str
    model_caveat: str
    model: str
    unit: str
    change_pct: float
    total_meur: float
    by_region: list[tuple[str, float]]
    by_sector: list[tuple[str, float]]
    nodes: list[QuantityShockNode]
    shocked: list[ShockedNode]
    skipped: list[str]
    indicators: ShockIndicators
    focus: QuantityShockFocus | None


class PriceShockNode(BaseModel):
    node_id: str
    region_label: str
    sector: str
    dp_pct: float


class PriceShockFocus(BaseModel):
    node_id: str
    dp_pct: float


class ValueChainPriceShock(BaseModel):
    edition: str
    caveat: str
    model_caveat: str
    carbon_eur_per_t: float
    covered_regions: list[str]
    priced_t: float
    carbon_cost_meur: float
    by_region: list[tuple[str, float]] = Field(description="Output-weighted mean price change, %.")
    by_sector: list[tuple[str, float]] = Field(description="Output-weighted mean price change, %.")
    nodes: list[PriceShockNode]
    focus: PriceShockFocus | None

class ValueChainMaterialFootprint(ValueChainFootprint):
    material_note: str


class ValueChainMaterialTreeNode(ValueChainTreeNode):
    extracted_t: float = Field(description="Tonnes of the requested material extracted for this box's share of the amount.")
    children: list[ValueChainMaterialTreeNode]


class ValueChainMaterialTree(ValueChainMaterialTreeNode):
    edition: str
    caveat: str
    material_note: str


class LinkRule(BaseModel):
    """An analyst's (or Scope 6's LLM) link of a company or taxonomy activity to value-chain nodes, stored as
    ICIO codes or region + sector names, never node ids. docs/superpowers/specs/2026-10-27-value-chain-links-overlays-design.md"""

    kind: Literal["split", "nodes", "llm"]
    parts: list[dict] = Field(description="split/llm: [{icio_code, share}]; nodes: [{region, sector, share}].")
    set_by: str
    set_at: str


class IcioCode(BaseModel):
    code: str
    label: str


class LinkRuleIn(BaseModel):
    kind: Literal["split", "nodes"]
    parts: list[dict] = Field(description="split: [{icio_code, share}]; nodes: [{region, sector, share}]; shares sum to 1.")


class WeightedNode(BaseModel):
    node_id: str
    region_label: str
    sector: str
    weight: float


class ValueChainLinks(BaseModel):
    edition: str
    caveat: str
    subject: str
    source: Literal["nodes", "split", "code", "llm", "none"]
    region: str | None = Field(description="The company's EXIOBASE region; null for activities.")
    nodes: list[WeightedNode]
    unresolved: list[dict] = Field(description="Rule parts the current build has no node for.")
    rule: LinkRule | None


class PortfolioHoldingLink(BaseModel):
    security_id: str
    company_id: str | None
    name: str
    market_value_eur: float
    weight: float
    link_source: Literal["nodes", "split", "code", "llm", "none"]
    top_node: WeightedNode | None
    owned_output_meur: float | None


class PortfolioFootprint(BaseModel):
    indicator: str
    unit: str
    total: float
    per_meur_invested: float | None
    by_region: list[tuple[str, float]]


class PortfolioActivity(BaseModel):
    taxonomy_id: str
    activity_id: str
    name: str
    direct_weight: float = Field(description="Share of NAV on the activity's nodes.")
    upstream_share: float | None


class ValueChainPortfolio(BaseModel):
    edition: str
    caveat: str
    portfolio_id: str
    as_of: str
    nav_eur: float
    linked_weight: float
    attributed_weight: float
    holdings: list[PortfolioHoldingLink]
    nodes: list[WeightedNode]
    direct_by_region: list[tuple[str, float]]
    upstream_total: float
    upstream_by_region: list[tuple[str, float]]
    upstream_by_sector: list[tuple[str, float]]
    upstream_nodes: list[WeightedNode] = Field(description="weight: euro from the node per euro of the linked output mix.")
    footprint: PortfolioFootprint
    activity: PortfolioActivity | None
