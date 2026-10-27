from __future__ import annotations

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


class ValueChainMaterialFootprint(ValueChainFootprint):
    material_note: str


class ValueChainMaterialTreeNode(ValueChainTreeNode):
    extracted_t: float = Field(description="Tonnes of the requested material extracted for this box's share of the amount.")
    children: list[ValueChainMaterialTreeNode]


class ValueChainMaterialTree(ValueChainMaterialTreeNode):
    edition: str
    caveat: str
    material_note: str
