"""Score lineage: one published row, traced from its score through each criterion to the authoritative value it read,
that value's derivation inputs, their observations and the document citations behind them. Read only; a link that
cannot be followed is reported as such, never left out."""

from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from arp.schemas.decision import PublishedDecision, PublishedRow

CSV_HEADER = [
    "entity_id", "name", "status", "score", "tier", "rank", "reasons", "criterion", "contribution", "imputed",
    "missing_reason", "value_id", "value", "value_status", "value_reason", "input", "input_value", "observation_id",
    "source", "provider", "period_end", "published_fact_id", "doc_id", "page", "quote",
]


def _values(session: Session, ids: set[int]) -> dict[int, dict]:
    from arp.authoritative.models import AuthoritativeValue
    from arp.authoritative.store import _row

    return {v.id: _row(v, derivation=True) for v in session.scalars(select(AuthoritativeValue).where(AuthoritativeValue.id.in_(ids)))} if ids else {}


def _citations(session: Session, observation_ids: list[int]) -> dict[int, list[dict]]:
    from arp.db.models import ValueCitation

    out: dict[int, list[dict]] = {}
    if observation_ids:
        for c in session.scalars(select(ValueCitation).where(ValueCitation.observation_id.in_(observation_ids))
                                 .order_by(ValueCitation.id)):
            out.setdefault(c.observation_id, []).append(
                {"doc_id": c.doc_id, "page": c.page, "quote": c.quote, "grounded": c.grounded})
    return out


def _inputs(derivation: dict, cited: dict[int, list[dict]]) -> list[dict]:
    inputs = derivation.get("inputs") or {}
    return [
        {
            "name": name, "value": i.get("value"), "status": i.get("status"), "source": i.get("source"),
            "provider": i.get("provider"), "period_end": i.get("period_end"), "unit": i.get("unit"),
            "observation_id": i.get("observation_id"), "published_fact_id": i.get("published_fact_id"),
            "link": "observation" if i.get("observation_id") else "no_observation",
            "citations": cited.get(i["observation_id"], []) if i.get("observation_id") else [],
        }
        for name, i in inputs.items()
    ]


def _criterion(c, values: dict[int, dict], cited: dict[int, list[dict]]) -> dict:
    base = {"column": c.column, "contribution": c.contribution, "imputed": c.imputed,
            "missing_reason": c.missing_reason, "value_id": c.value_id}
    if c.value_id is None:
        return {**base, "link": "dataset_cell", "value": None, "inputs": None}
    v = values.get(c.value_id)
    if v is None:
        return {**base, "link": "missing", "value": None, "inputs": None}
    value = {
        "value": v["value"], "unit": v["unit"], "status": v["status"], "reason": v["reason"],
        "period_end": v["period_end"], "framework_id": v["framework_id"], "framework_version": v["framework_version"],
        # valid_to is today's validity, not the scoring day's: labelled as current, the value itself never changes
        "superseded": v["valid_to"] is not None, "current_valid_to": v["valid_to"],
    }
    return {**base, "link": "authoritative", "value": value, "inputs": _inputs(v["derivation"], cited)}


def _row(snapshot: PublishedDecision, entity_id: str) -> PublishedRow:
    for r in snapshot.rows:
        if r.entity_id == entity_id:
            return r
    raise KeyError(entity_id)


def row_lineage(snapshot: PublishedDecision, entity_id: str, *, values) -> dict:
    """`values` is an AuthoritativeStore. Raises KeyError for an entity the snapshot has no row for."""
    return lineage_rows(snapshot, [_row(snapshot, entity_id)], values=values)[0]


def lineage_rows(snapshot: PublishedDecision, rows: list[PublishedRow], *, values) -> list[dict]:
    """The lineage of `rows` in two queries in all (values, then citations), whatever the number of rows."""
    ids = {c.value_id for r in rows for c in r.criteria or [] if c.value_id is not None}
    with Session(values.engine) as session:
        found = _values(session, ids)
        obs = [i["observation_id"] for v in found.values() for i in (v["derivation"].get("inputs") or {}).values()
               if i.get("observation_id")]
        cited = _citations(session, obs)
    return [_one(snapshot, r, found, cited) for r in rows]


def _one(snapshot: PublishedDecision, r: PublishedRow, found: dict[int, dict], cited: dict[int, list[dict]]) -> dict:
    head = {
        "snapshot_id": snapshot.snapshot_id, "framework_id": snapshot.framework_id,
        "framework_version": snapshot.framework_version, "as_of": snapshot.as_of,
        "published_by": snapshot.published_by, "published_at": snapshot.published_at,
        "entity_id": r.entity_id, "name": r.name, "status": r.status, "reasons": r.reasons,
        "score": r.score, "rank": r.rank, "tier": r.tier, "tier_name": r.tier_name,
    }
    if r.criteria is None:
        return {**head, "criteria": [{"link": "not_recorded"}]}
    return {**head, "criteria": [_criterion(c, found, cited) for c in r.criteria]}


def lineage_csv(rows: list[dict]) -> str:
    """One line per entity x criterion x input x citation; a missing level gives one line with blank columns."""
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(CSV_HEADER)
    for r in rows:
        head = [r["entity_id"], r["name"], r["status"], r["score"], r["tier"], r["rank"], "; ".join(r["reasons"])]
        for k in r["criteria"]:
            value = k.get("value") or {}
            crit = [k.get("column"), k.get("contribution"), k.get("imputed"), k.get("missing_reason"), k.get("value_id"),
                    value.get("value"), value.get("status"), value.get("reason")]
            for i in k.get("inputs") or [None]:
                inp = [] if i is None else [i["name"], i["value"], i["observation_id"], i["source"], i["provider"],
                                            i["period_end"], i["published_fact_id"]]
                inp += [None] * (7 - len(inp))
                for cit in (i or {}).get("citations") or [None]:
                    c = [] if cit is None else [cit["doc_id"], cit["page"], cit["quote"]]
                    out.writerow(head + crit + inp + c + [None] * (3 - len(c)))
    return buf.getvalue()
