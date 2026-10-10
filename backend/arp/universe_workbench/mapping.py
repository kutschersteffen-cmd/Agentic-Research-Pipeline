from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from arp.schemas.common import CompanyRef
from arp.schemas.issuer import normalise_lei
from arp.storage.identifier_map import IdentifierMapStore, normalise_identifier

_SCHEMES = ("LEI", "ISIN", "CIK")  # same order as schemas.issuer.issuer_key


@dataclass(frozen=True)
class Mapping:
    status: Literal["mapped", "ambiguous", "unmapped", "no_identifier"]
    issuer_key: str | None = None
    key_scheme: str | None = None
    identifiers: dict[str, list[str]] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)


class MasterIndex:
    """One-pass index of the identifier map, valid on a given day."""

    def __init__(self) -> None:
        self._by_id: dict[tuple[str, str], list[str]] = {}
        self._by_issuer: dict[str, dict[str, list[str]]] = {}

    @classmethod
    def build(cls, idmap: IdentifierMapStore, *, on: str | None = None) -> MasterIndex:
        day = on or date.today().isoformat()
        idx = cls()
        for r in idmap.rows():
            if (r.valid_from and day < r.valid_from) or (r.valid_to and day >= r.valid_to):
                continue
            keys = idx._by_id.setdefault((r.scheme, normalise_identifier(r.scheme, r.value)), [])
            if r.issuer_key not in keys:
                keys.append(r.issuer_key)
            if r.scheme in _SCHEMES:
                vals = idx._by_issuer.setdefault(r.issuer_key, {}).setdefault(r.scheme, [])
                if r.value not in vals:
                    vals.append(r.value)
        return idx

    def resolve(self, scheme: str, value: str) -> list[str]:
        return list(self._by_id.get((scheme, normalise_identifier(scheme, value)), []))

    def identifiers(self, issuer_key: str) -> dict[str, list[str]]:
        return {s: list(v) for s, v in self._by_issuer.get(issuer_key, {}).items()}


def map_company(company: CompanyRef, index: MasterIndex | None) -> Mapping:
    values = (
        ("LEI", normalise_lei(company.lei or "")),
        ("ISIN", company.isin or ""),
        ("CIK", company.cik or ""),
    )
    values = tuple((s, v) for s, v in values if v.strip())
    if not values:
        return Mapping("no_identifier")
    ambiguous: list[str] = []
    for scheme, value in values:
        keys = index.resolve(scheme, value) if index else []
        if len(keys) == 1:
            return Mapping("mapped", keys[0], "INTERNAL", index.identifiers(keys[0]))
        for k in keys:
            if k not in ambiguous:
                ambiguous.append(k)
    return Mapping("ambiguous", candidates=ambiguous) if ambiguous else Mapping("unmapped")


def enrich(company: CompanyRef, mapping: Mapping) -> CompanyRef:
    """Fill empty lei/cik/isin from the master; never overwrite, never touch country."""
    if mapping.status != "mapped":
        return company
    fill = {}
    for scheme, attr in (("LEI", "lei"), ("CIK", "cik"), ("ISIN", "isin")):
        vals = mapping.identifiers.get(scheme, [])
        if not getattr(company, attr) and len(vals) == 1:
            fill[attr] = vals[0]
    return company.model_copy(update=fill)
