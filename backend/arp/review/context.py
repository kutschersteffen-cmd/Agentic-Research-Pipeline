"""The decision-ready context bundle for one review item (E52) and its stored snapshots (E58)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from arp.config import Settings
from arp.extraction.history import RunHistory
from arp.extraction.pipeline import load_run_schema
from arp.grounding import _page_for_offset
from arp.orchestration.review_queue import ItemState, blind_for, item_states, public_decision
from arp.review.items import cosign_rule, get_item
from arp.schemas.common import new_id
from arp.schemas.datapoints import CheckResult, is_failing
from arp.schemas.review import ReviewItem, ReviewItemKind, field_item_key, period_key
from arp.storage.atomic_io import atomic_write_text
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry

if TYPE_CHECKING:
    from arp.api.auth import Principal

CHECK_WORDS: dict[str, str] = {
    "format.data_type": "The value is not of the field's type.",
    "format.allowed_values": "The value is not one of the allowed values.",
    "numeric.in_span": "The number is not in the quoted source text.",
    "numeric.caption_scale": "The table caption gives a different scale than the value uses.",
    "numeric.row_label": "The table row the number comes from does not name this field.",
    "plausibility.range": "The value is outside the field's allowed range.",
    "plausibility.sign": "The value is negative but the field cannot be.",
    "plausibility.percentage": "The percentage is not between 0 and 100.",
    "plausibility.part_of_whole": "This part is larger than its total.",
    "plausibility.sum_identity": "The total does not equal the sum of its parts.",
    "prior.comparative_jump": "The value changed more than expected from the previous period.",
    "prior.last_decided": "The value differs from the one decided in an earlier run.",
    "prior.rejected": "A reviewer rejected this same value before.",
    "consistency.entity": "The source document may cover a different company.",
    "consistency.period": "The source document does not report this period.",
}

PAGE_CHARS = 10_000
_FIELD_KINDS = (ReviewItemKind.VALUE, ReviewItemKind.RESTATEMENT_CANDIDATE)
_DOC_KEYS = ("doc_id", "doc_type", "title", "company_id", "source_filename")


def _breaks(text: str, page_breaks: list[int]) -> list[int]:
    if page_breaks:
        return page_breaks
    # ponytail: synthetic 10k-char pages for unpaginated text; use parser sections once they carry offsets
    out, start = [0], 0
    while len(text) - start > PAGE_CHARS:
        nl = text.rfind("\n", start, start + PAGE_CHARS)
        start = nl + 1 if nl > start else start + PAGE_CHARS
        out.append(start)
    return out


def page_window(text: str, page_breaks: list[int], page: int) -> tuple[int, int, int]:
    pb = _breaks(text, page_breaks)
    if not 1 <= page <= len(pb):
        raise ValueError(f"page {page} of {len(pb)}")
    return pb[page - 1], pb[page] if page < len(pb) else len(text), len(pb)


def page_of(text: str, page_breaks: list[int], char_start: int) -> int:
    return _page_for_offset(_breaks(text, page_breaks), char_start)


def _text(content_store: DocumentContentStore | None, doc: dict):
    if content_store is None or not doc.get("content_key") or not doc.get("parser_version"):
        return None
    return content_store.lookup(doc["content_key"], doc["parser_version"])


def _results_row(run_store: RunStore, run_id: str, payload: dict) -> dict | None:
    company, issuer = payload.get("company_id"), payload.get("issuer_key")
    return next((r for r in run_store.read_jsonl(run_store.results_path(run_id))
                 if (r.get("company_id") == company if company else r.get("issuer_key") == issuer)), None)


def _value(item: ReviewItem, row: dict | None) -> dict | None:
    if item.kind is ReviewItemKind.VALUE:
        return item.payload.get("field")
    if item.kind is ReviewItemKind.RESTATEMENT_CANDIDATE and row:
        issuer = row.get("issuer_key", "")
        return next((f for f in row.get("fields", [])
                     if field_item_key(issuer, f["field_id"], period_key(f)) == item.payload["item_key"]), None)
    return None


def _grounded(value: dict | None) -> list[dict]:
    return [c for c in (value or {}).get("citations", []) if c.get("grounded") and c.get("char_start") is not None]


def _documents(item: ReviewItem, row: dict | None, value: dict | None, content_store) -> list[dict]:
    if item.kind is ReviewItemKind.QUARANTINED_DOCUMENT:
        docs = [dict(item.payload)]
    elif item.kind in _FIELD_KINDS:
        docs = [dict(d) for d in (row or {}).get("documents", [])]
        for c in _grounded(value):  # old rows carry no documents list
            if c["doc_id"] not in {d["doc_id"] for d in docs}:
                docs.append({k: c.get(k) for k in (*_DOC_KEYS, "content_key", "parser_version")})
    else:
        return []
    for d in docs:
        t = _text(content_store, d)
        d["pages"] = page_window(t.full_text, t.page_breaks, 1)[2] if t else None
    return docs


def _evidence(value: dict | None, docs: list[dict], content_store) -> list[dict]:
    by_id = {d["doc_id"]: d for d in docs}
    out = []
    for c in _grounded(value):
        doc = by_id.get(c["doc_id"], {})
        t = _text(content_store, {**doc, **{k: c[k] for k in ("content_key", "parser_version") if c.get(k)}})
        page, page_start, page_text = c.get("page"), None, None
        if t:
            page = page_of(t.full_text, t.page_breaks, c["char_start"])
            page_start, end, _ = page_window(t.full_text, t.page_breaks, page)
            page_text = t.full_text[page_start:end]
        out.append({
            "doc_id": c["doc_id"], "doc_type": c.get("doc_type") or doc.get("doc_type"), "title": doc.get("title"),
            "company_id": c.get("company_id") or doc.get("company_id"),
            "source_filename": c.get("source_filename") or doc.get("source_filename"),
            "page": page, "quote": c.get("quote"), "char_start": c["char_start"], "char_end": c.get("char_end"),
            "page_start": page_start, "page_text": page_text,
        })
    return out


def _visible(s: ItemState, principal: Principal, *, high_risk: bool) -> tuple[list[dict], bool]:
    blind = blind_for(s, principal, high_risk=high_risk)
    rows = s.rows[: next(i for i, r in enumerate(s.rows) if r is s.first)] if blind else s.rows
    return [public_decision(r, principal) for r in rows], blind


def _state(run_store: RunStore, run_id: str, item_key: str) -> ItemState:
    m = run_store.load_manifest(run_id)
    rule = cosign_rule(m.run_type) if m else set()
    return item_states(run_store, run_id, cosign_required=rule).get(item_key) or ItemState()


def visible_history(run_store: RunStore, run_id: str, item_key: str, principal: Principal, *, high_risk: bool) -> list[dict]:
    return _visible(_state(run_store, run_id, item_key), principal, high_risk=high_risk)[0]


def _field_definition(run_store: RunStore, run_id: str, item: ReviewItem, settings: Settings) -> dict | None:
    schema = load_run_schema(run_store, run_id) if item.kind in _FIELD_KINDS else None
    spec = next((f for f in schema.fields if f.field_id == item.payload.get("field_id")), None) if schema else None
    if spec is None:
        return None
    quality = SchemaRegistry(settings.schema_registry_dir).quality(spec.field_id, spec.version)
    return spec.model_dump(mode="json") | {"first_audit_passed": quality.first_audit_passed}


def _prior_period(row: dict | None, value: dict | None) -> dict | None:
    end = (value or {}).get("period_end")
    older = [f for f in (row or {}).get("fields", [])
             if end and f.get("field_id") == value["field_id"] and f.get("period_end") and f["period_end"] < end]
    f = max(older, key=lambda f: f["period_end"], default=None)
    return {"value": f.get("value"), "period_end": f["period_end"]} if f else None


def _published(run_store: RunStore, run_id: str, item: ReviewItem) -> dict | None:
    if item.kind not in _FIELD_KINDS:
        return None
    key = item.payload["item_key"] if item.kind is ReviewItemKind.RESTATEMENT_CANDIDATE else item.item_key
    # ponytail: full RunHistory scan per bundle; cache per run once review traffic shows it
    p = RunHistory.load(run_store, exclude_run_id=run_id).last_decided(key)
    return {"value": p.value, "run_id": p.run_id, "decided_by": p.decided_by} if p else None


def build_context(
    run_store: RunStore, run_id: str, item_key: str, principal: Principal, *,
    settings: Settings, content_store: DocumentContentStore | None,
) -> dict | None:
    item = get_item(run_store, run_id, item_key, principal)
    if item is None:
        return None
    row = _results_row(run_store, run_id, item.payload) if item.kind in _FIELD_KINDS else None
    value = _value(item, row)
    field_definition = _field_definition(run_store, run_id, item, settings)
    docs = _documents(item, row, value, content_store)
    decisions, blind = _visible(_state(run_store, run_id, item_key), principal, high_risk=item.high_risk)
    v = value or {}
    bundle = {
        "item": item.model_dump(mode="json"),
        "field_definition": field_definition,
        "value": value,
        "evidence": _evidence(value, docs, content_store),
        "documents": docs,
        "failed_checks": [
            {"check_id": c.check_id, "severity": c.severity, "plain": CHECK_WORDS.get(c.check_id, c.detail), "detail": c.detail}
            for c in map(CheckResult.model_validate, v.get("checks", [])) if is_failing(c)
        ],
        "route_reasons": v.get("route_reasons", []),
        "conflict": {"conflicting_sources": v.get("conflicting_sources", False), "alternatives": v.get("alternatives", [])}
        if value else None,
        "prior_period": _prior_period(row, value),
        "published": _published(run_store, run_id, item),
        "confidence": {
            "final": v.get("confidence"), "extractor": v.get("extractor_confidence"),
            "verifier": v.get("verifier_confidence"), "grounded": v.get("grounded"),
            "match_methods": [c.get("match_method") for c in _grounded(value)],
            "auto_accept_min": (field_definition or {}).get("auto_accept_min"),
        } if value else None,
        "state": item.state,
        "escalated": item.escalated,
        "decisions": decisions,
        "blind": blind,
    }
    raw = json.dumps(bundle, sort_keys=True, separators=(",", ":"), default=str)
    return bundle | {"etag": hashlib.sha256(raw.encode()).hexdigest()[:16]}


def item_source(
    run_store: RunStore, run_id: str, item_key: str, doc_id: str, page: int, principal: Principal, *,
    content_store: DocumentContentStore | None,
) -> dict | None:
    item = get_item(run_store, run_id, item_key, principal)
    if item is None:
        return None
    row = _results_row(run_store, run_id, item.payload) if item.kind in _FIELD_KINDS else None
    doc = next((d for d in _documents(item, row, _value(item, row), None) if d["doc_id"] == doc_id), None)
    t = _text(content_store, doc) if doc else None
    if t is None:
        return None
    try:
        start, end, pages = page_window(t.full_text, t.page_breaks, page)
    except ValueError:
        return None
    return {k: doc.get(k) for k in _DOC_KEYS} | {
        "page": page, "pages": pages, "page_start": start, "page_text": t.full_text[start:end],
    }


def write_snapshot(run_store: RunStore, run_id: str, bundle: dict) -> str:
    snapshot_id = new_id("snap")
    path = run_store.snapshot_path(run_id, snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(bundle, sort_keys=True))
    return snapshot_id


def read_snapshot(run_store: RunStore, run_id: str, snapshot_id: str) -> bytes | None:
    path = run_store.snapshot_path(run_id, snapshot_id)
    return path.read_bytes() if path.exists() else None
