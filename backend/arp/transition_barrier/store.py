"""Stored analyst facts, uploaded documents and choices, and the `Value`s they give a cell."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from arp.config import get_settings
from arp.db.models import BarrierChoice, BarrierDocument, BarrierFact
from arp.db.session import transaction
from arp.ingestion.indexing_config import IndexingConfig
from arp.schemas.transition_barrier import PrimarySource
from arp.storage.document_blob_store import blob_store_for
from arp.transition_barrier.engine import Value, _show, fact_confidence
from arp.transition_barrier.facts import FactRefused
from arp.transition_barrier.rule_book import CriterionRules


def _row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def add_document(
    *, title: str, publisher: str, as_of: date, tier: str, filename: str | None, content_key: str,
    page_texts: list[str], uploaded_by: str,
) -> int:
    with transaction() as s:
        row = BarrierDocument(
            title=title, publisher=publisher, as_of=as_of, tier=tier, filename=filename, content_key=content_key,
            page_texts=page_texts, uploaded_by=uploaded_by,
        )
        s.add(row)
        s.flush()
        return row.id


def add_fact(
    *, code: str, region: str, fact: str, value, unit: str | None, quote: str, page: int | None, locator: str | None,
    source_key: str | None, document_id: int | None, entered_by: str, machine_checked: bool,
) -> int:
    with transaction() as s:
        row = BarrierFact(
            code=code, region=region, fact=fact, value=value, unit=unit, quote=quote, page=page, locator=locator,
            source_key=source_key, document_id=document_id, entered_by=entered_by, machine_checked=machine_checked,
        )
        s.add(row)
        s.flush()
        return row.id


def cell_facts(code: str, region: str) -> list[dict]:
    """Every fact entered for the cell, oldest first: the history, replaced facts included."""
    with transaction() as s:
        rows = s.scalars(select(BarrierFact).where(BarrierFact.code == code, BarrierFact.region == region).order_by(BarrierFact.id))
        return [_row(r) for r in rows]


def cell_choices(code: str, region: str) -> list[dict]:
    with transaction() as s:
        rows = s.scalars(select(BarrierChoice).where(BarrierChoice.code == code, BarrierChoice.region == region).order_by(BarrierChoice.id))
        return [_row(r) for r in rows]


def fact_labels(facts: list[dict], registry: list[PrimarySource]) -> dict[str, str]:
    """`<value shown>, <document title>` for each fact row, by fact id (a registered source shows its name)."""
    docs = _documents({f["document_id"] for f in facts if f["document_id"]})
    names = {s.key: s.source_name for s in registry}
    return {
        str(f["id"]): f"{_show(f['value'], f['unit'])}, "
        + (docs[f["document_id"]]["title"] if f["document_id"] else names.get(f["source_key"], f["source_key"]))
        for f in facts
    }


def document(doc_id: int, blobs=None) -> tuple[dict, bytes] | None:
    with transaction() as s:
        row = s.get(BarrierDocument, doc_id)
        if row is None:
            return None
        meta = _row(row)
    blobs = blobs or blob_store_for(IndexingConfig.from_settings(get_settings()))
    return meta, blobs.get(meta["content_key"])


def _documents(ids: set[int]) -> dict[int, dict]:
    with transaction() as s:
        return {d.id: _row(d) for d in s.scalars(select(BarrierDocument).where(BarrierDocument.id.in_(ids)))} if ids else {}


def _current(facts: list[dict], docs: dict[int, dict]) -> list[dict]:
    """The facts that count: a later fact for the same fact and the same source replaces the earlier one.
    Uploads are one source when title and publisher match; a registered source is its own source."""
    latest: dict[tuple, dict] = {}
    for f in facts:  # oldest first
        d = docs.get(f["document_id"])
        source = ("doc", d["title"], d["publisher"]) if d else ("reg", f["source_key"])
        latest[(f["fact"], source)] = f
    return list(latest.values())


def add_choice(*, code: str, region: str, fact: str, value_id: str, reason: str, chosen_by: str) -> int:
    """Records which of the fact's current values counts; `value_ids` is every one of them right now."""
    if not reason.strip():
        raise FactRefused(422, "A reason is required.")
    facts = cell_facts(code, region)
    current = _current(facts, _documents({f["document_id"] for f in facts if f["document_id"]}))
    ids = [str(f["id"]) for f in current if f["fact"] == fact]
    if value_id not in ids:
        raise FactRefused(422, f"Unknown value {value_id}")
    with transaction() as s:
        row = BarrierChoice(
            code=code, region=region, fact=fact, fact_id=value_id, reason=reason.strip(), value_ids=ids, chosen_by=chosen_by
        )
        s.add(row)
        s.flush()
        return row.id


def cell_values(code: str, region: str, rules: CriterionRules, registry: list[PrimarySource], today: date) -> list[Value]:
    defs = {f.id: f for f in rules.facts if f.type}
    facts = [f for f in cell_facts(code, region) if f["fact"] in defs]
    docs = _documents({f["document_id"] for f in facts if f["document_id"]})
    current = _current(facts, docs)

    chosen: dict[str, dict] = {c["fact"]: c for c in cell_choices(code, region)}  # the latest per fact
    for fact, c in chosen.items():
        ids = {str(f["id"]) for f in current if f["fact"] == fact}
        if ids <= set(c["value_ids"]):
            current = [f for f in current if f["fact"] != fact or str(f["id"]) == c["fact_id"]]

    order = {s.key: (i, s.source_name) for i, s in enumerate(registry)}

    def sort_key(f: dict):
        if f["document_id"] is None:
            return (0, order.get(f["source_key"], (len(order),))[0], f["page"] or 0, f["id"])
        return (1, f["document_id"], f["page"] or 0, f["id"])

    out = []
    for f in sorted(current, key=sort_key):
        d = docs.get(f["document_id"])
        value = date.fromisoformat(f["value"]) if defs[f["fact"]].type == "date" else f["value"]
        out.append(
            Value(
                id=str(f["id"]), fact=f["fact"], value=value, unit=f["unit"],
                document=d["title"] if d else order.get(f["source_key"], (0, f["source_key"]))[1],
                page=f["page"], locator=f["locator"],
                confidence=fact_confidence(d and d["tier"], d and d["as_of"], defs[f["fact"]].max_age_days, today, d is not None),
                machine_checked=f["machine_checked"], entered_by=f["entered_by"], document_id=f["document_id"],
                quote=f["quote"] or None,
            )
        )
    return out
