"""Stored analyst facts, uploaded documents and choices, and the `Value`s they give a cell."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from arp.config import get_settings
from arp.db.models import BarrierChoice, BarrierDocument, BarrierExtraction, BarrierFact, BarrierSourceDocument
from arp.db.session import transaction
from arp.ingestion.indexing_config import IndexingConfig
from arp.schemas.transition_barrier import PrimarySource
from arp.storage.document_blob_store import blob_store_for
from arp.transition_barrier import clock
from arp.transition_barrier.engine import Value, _show, fact_confidence
from arp.transition_barrier.extraction import Extraction, fingerprint
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


def save_source_document(
    *, source_key: str, url: str, title: str, publisher: str, tier: str, as_of: date, content_key: str,
    content_type: str, page_texts: list[str], html: bool,
) -> int:
    """Stores a fetched source; the source's latest row with the same bytes is returned instead of a new one."""
    with transaction() as s:
        latest = s.scalar(
            select(BarrierSourceDocument).where(BarrierSourceDocument.source_key == source_key).order_by(BarrierSourceDocument.id.desc()).limit(1)
        )
        if latest is not None and latest.content_key == content_key:
            return latest.id
        row = BarrierSourceDocument(
            source_key=source_key, url=url, title=title, publisher=publisher, tier=tier, as_of=as_of,
            content_key=content_key, content_type=content_type, page_texts=page_texts, html=html,
        )
        s.add(row)
        s.flush()
        return row.id


def latest_source_documents(source_keys: list[str]) -> list[dict]:
    """The newest stored document of each key that has one, in the order given."""
    with transaction() as s:
        rows = s.scalars(select(BarrierSourceDocument).where(BarrierSourceDocument.source_key.in_(source_keys)).order_by(BarrierSourceDocument.id))
        newest = {r.source_key: _row(r) for r in rows}
    return [newest[k] for k in source_keys if k in newest]


def extraction(code: str, region: str, fact: str, doc_id: int, fingerprint: str) -> dict | None:
    with transaction() as s:
        row = s.scalar(select(BarrierExtraction).where(
            BarrierExtraction.code == code, BarrierExtraction.region == region, BarrierExtraction.fact == fact,
            BarrierExtraction.source_document_id == doc_id, BarrierExtraction.fingerprint == fingerprint,
        ))  # fmt: skip
        return row and _row(row)


def add_extraction(
    *, code: str, region: str, fact: str, doc_id: int, fingerprint: str, result: Extraction | None, run_id: str
) -> int:
    """Stores one extraction; `result` None is the model's not-found answer, kept so it is never asked again."""
    found = {} if result is None else {
        "value": result.value, "unit": result.unit, "extracted": result.extracted, "quote": result.quote,
        "page": result.page, "locator": result.locator, "as_of": result.as_of, "reason": result.reason,
    }  # fmt: skip
    key = {"code": code, "region": region, "fact": fact, "source_document_id": doc_id, "fingerprint": fingerprint}
    with transaction() as s:
        new_id = s.scalar(
            insert(BarrierExtraction)
            .values(**key, **found, found=result is not None, counted=bool(result and result.counted), run_id=run_id)
            .on_conflict_do_nothing()  # another run stored the same key first
            .returning(BarrierExtraction.id)
        )
    return new_id or extraction(code, region, fact, doc_id, fingerprint)["id"]


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


def extraction_labels(ids: set[int]) -> dict[str, str]:
    """`<value shown>, <document title>` for each extraction id, keyed by its value id `x<id>`."""
    if not ids:
        return {}
    with transaction() as s:
        rows = s.execute(
            select(BarrierExtraction, BarrierSourceDocument.title)
            .join(BarrierSourceDocument, BarrierExtraction.source_document_id == BarrierSourceDocument.id)
            .where(BarrierExtraction.id.in_(ids))
        ).all()
        return {f"x{x.id}": f"{_show(x.value, x.unit)}, {title}" for x, title in rows}


def document(doc_id: int, blobs=None) -> tuple[dict, bytes] | None:
    with transaction() as s:
        row = s.get(BarrierDocument, doc_id)
        if row is None:
            return None
        meta = _row(row)
    blobs = blobs or blob_store_for(IndexingConfig.from_settings(get_settings()))
    if not blobs.exists(meta["content_key"]):  # removed or expired from the blob store
        return None
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


def add_choice(
    *, code: str, region: str, fact: str, value_id: str, reason: str, chosen_by: str, rules: CriterionRules,
    registry: list[PrimarySource],
) -> int:
    """Records which of the fact's current counted values counts; `value_ids` is every one of them right now."""
    if not reason.strip():
        raise FactRefused(422, "A reason is required.")
    ids = [v.id for v in _values(code, region, rules, registry, clock.today()) if v.fact == fact and v.counted]
    if value_id not in ids:
        raise FactRefused(422, f"Unknown value {value_id}")
    with transaction() as s:
        row = BarrierChoice(
            code=code, region=region, fact=fact, fact_id=value_id, reason=reason.strip(), value_ids=ids, chosen_by=chosen_by
        )
        s.add(row)
        s.flush()
        return row.id


def _values(code: str, region: str, rules: CriterionRules, registry: list[PrimarySource], today: date) -> list[Value]:
    """Every current value of the cell before choices apply: analyst facts, and the extractions from the latest
    document of each registered source. Registered-source values come first, in registry order then by page."""
    defs = {f.id: f for f in rules.facts if f.type}
    facts = [f for f in cell_facts(code, region) if f["fact"] in defs]
    docs = _documents({f["document_id"] for f in facts if f["document_id"]})
    order = {s.key: (i, s.source_name) for i, s in enumerate(registry)}
    keyed: list[tuple[tuple, Value]] = []

    for f in _current(facts, docs):
        d = docs.get(f["document_id"])
        value = date.fromisoformat(f["value"]) if defs[f["fact"]].type == "date" else f["value"]
        if d is None:
            key = (0, order.get(f["source_key"], (len(order),))[0], f["page"] or 0, 0, f["id"])
        else:
            key = (1, f["document_id"], f["page"] or 0, 0, f["id"])
        keyed.append((key, Value(
            id=str(f["id"]), fact=f["fact"], value=value, unit=f["unit"],
            document=d["title"] if d else order.get(f["source_key"], (0, f["source_key"]))[1],
            page=f["page"], locator=f["locator"],
            confidence=fact_confidence(d and d["tier"], d and d["as_of"], defs[f["fact"]].max_age_days, today, d is not None),
            machine_checked=f["machine_checked"], entered_by=f["entered_by"], document_id=f["document_id"],
            quote=f["quote"] or None,
        )))  # fmt: skip

    sources = {d["id"]: d for d in latest_source_documents([s.key for s in registry if s.key])}
    prints = {fid: fingerprint(f, code) for fid, f in defs.items()}
    with transaction() as s:
        rows = [_row(r) for r in s.scalars(select(BarrierExtraction).where(
            BarrierExtraction.code == code, BarrierExtraction.region == region, BarrierExtraction.found,
            BarrierExtraction.source_document_id.in_(sources),
        ))] if sources else []  # fmt: skip
    for x in rows:
        if prints.get(x["fact"]) != x["fingerprint"]:
            continue  # extracted under an older fact definition or prompt
        d = sources[x["source_document_id"]]
        value = date.fromisoformat(x["value"]) if x["counted"] and defs[x["fact"]].type == "date" else x["value"]
        keyed.append(((0, order[d["source_key"]][0], x["page"] or 0, 1, x["id"]), Value(
            id=f"x{x['id']}", fact=x["fact"], value=value, unit=x["unit"], document=d["title"], page=x["page"],
            locator=x["locator"],
            confidence=fact_confidence(d["tier"], x["as_of"] or d["as_of"], defs[x["fact"]].max_age_days, today, True),
            machine_checked=True, counted=x["counted"], reason=x["reason"], quote=x["quote"] or None,
            extracted=x["extracted"],
        )))  # fmt: skip
    return [v for _, v in sorted(keyed, key=lambda kv: kv[0])]


def cell_values(code: str, region: str, rules: CriterionRules, registry: list[PrimarySource], today: date) -> list[Value]:
    values = _values(code, region, rules, registry, today)
    chosen: dict[str, dict] = {c["fact"]: c for c in cell_choices(code, region)}  # the latest per fact
    for fact, c in chosen.items():
        ids = {v.id for v in values if v.fact == fact and v.counted}
        if ids <= set(c["value_ids"]):  # no value appeared since the choice: only the chosen one counts
            values = [v for v in values if v.fact != fact or not v.counted or v.id == c["fact_id"]]
    return values
