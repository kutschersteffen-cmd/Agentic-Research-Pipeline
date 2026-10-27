from __future__ import annotations

from pydantic import BaseModel, Field


class ValueChainStatus(BaseModel):
    edition: str
    version: str = Field(description="EXIOBASE version from the archive's metadata.json.")
    year: int
    n_nodes: int
    n_regions: int
    n_sectors: int
    built_at: str
    caveat: str


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
