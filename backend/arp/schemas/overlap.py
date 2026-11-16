"""API models of the fund overlap (spec `stewardship-workbench-overlap`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OverlapFund(BaseModel):
    portfolio_id: str
    name: str
    companies: int


class OverlapPair(BaseModel):
    a: str
    b: str
    shared_companies: int
    shared_weight_pct: float


class PickedScope(BaseModel):
    scope: str
    label: str
    status: Literal["proposed", "confirmed"]


class OverlapHeldIn(BaseModel):
    portfolio_id: str
    name: str
    weight_pct: float


class SharedSelection(BaseModel):
    issuer_id: str
    company: str
    scopes: list[PickedScope]
    held_in: list[OverlapHeldIn]


class FundOverlap(BaseModel):
    as_of: str | None
    cycle: str
    companies: int
    funds: list[OverlapFund]
    pairs: list[OverlapPair]
    shared_selections: list[SharedSelection]


class OverlapMatrixCompany(BaseModel):
    issuer_id: str
    company: str
    house_weight_pct: float | None
    funds: int
    weights: dict[str, float | None]


class OverlapMatrix(BaseModel):
    as_of: str | None
    basis: Literal["top", "selection"]
    scope: str | None
    cycle: str
    funds: list[OverlapFund]
    companies: list[OverlapMatrixCompany]
