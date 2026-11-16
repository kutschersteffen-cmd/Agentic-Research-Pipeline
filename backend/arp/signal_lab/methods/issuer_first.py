from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.sentiment_scoring import build_sentiment_panel
from arp.schemas.common import DocType, SourceDocument
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method
from arp.signal_lab.methods.llm_scoring import _run
from arp.signal_lab.times import month_end_time, normalise_time

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass
class SearchHit:
    url: str
    title: str
    text: str
    published_at: str | None


class SearchTool(Protocol):
    def search(self, query: str, *, before: str) -> list[SearchHit]: ...


def _published(hit: SearchHit) -> str | None:
    """The hit's canonical time, or None when it has no usable date."""
    if not hit.published_at:
        return None
    try:
        return normalise_time(hit.published_at)
    except ValueError:
        return None


def _leaks(hits: list[SearchHit], cutoff: str) -> bool:
    return any((t := _published(h)) is not None and t > cutoff for h in hits)


def _to_document(hit: SearchHit, issuer: str, published_at: str) -> SourceDocument:
    return SourceDocument(
        doc_id=hashlib.sha256(hit.url.encode()).hexdigest()[:16],
        company_id=issuer,
        doc_type=DocType.OTHER,
        title=hit.title,
        full_text=hit.title + "\n\n" + hit.text,
        published_at=published_at,
        source_url=hit.url,
    )


@register_method("issuer_first")
def _issuer_first(params: dict, inp: MethodInput) -> MethodResult:
    peer_group = params.get("peer_group")
    if peer_group is not None and (not isinstance(peer_group, str) or not peer_group.strip()):
        raise ValueError(f"issuer_first 'peer_group' must be a non-empty string or None, got {peer_group!r}")
    search = inp.resources.get("search")
    if search is None:
        raise ValueError("no search tool configured; the issuer-first variant is interface-only until the owner allows one")
    llm = inp.resources.get("llm")
    if llm is None:
        raise ValueError("issuer_first needs an LLM client in resources['llm']")

    period_ends = inp.prices.period_ends
    docs: dict[str, dict[str, list[SourceDocument]]] = {}
    cells = leaked_first = leaked_after = undated = 0
    for issuer in inp.prices.returns:
        for period_end in period_ends:
            year, month = int(period_end[:4]), int(period_end[5:7])
            if month % 3:
                continue
            cutoff = month_end_time(period_end)
            query = f"{issuer} {year}Q{month // 3} results" + (f" {peer_group}" if peer_group else "")
            cells += 1

            hits = search.search(query, before=cutoff)
            if _leaks(hits, cutoff):
                leaked_first += 1
                day_before = (datetime.strptime(cutoff, _TIME_FORMAT) - timedelta(days=1)).strftime(_TIME_FORMAT)
                # The retry is the tool's answer to the tighter cutoff, so its hits replace the first try's.
                hits = search.search(query, before=day_before)
                leaked_after += int(_leaks(hits, cutoff))
            kept = {}
            for h in hits:
                t = _published(h)
                if t is None:
                    undated += 1
                elif t <= cutoff:
                    kept.setdefault(h.url, _to_document(h, issuer, t))  # a repeated url must not double-weight the cell
            if kept:
                docs.setdefault(issuer, {})[period_end] = list(kept.values())

    scored, _, usages = _run(build_sentiment_panel(docs, period_ends, llm))
    values = {i: scored.values.get(i, [None] * len(period_ends)) for i in inp.prices.returns}
    models = {u.model for u in usages if u.model}  # "" means the client did not report one
    if len(models) > 1:
        raise ValueError(f"issuer_first calls used more than one model: {sorted(models)}")
    if usages and not models:
        raise ValueError("the LLM client reported no model name; a model that is unnamed cannot be split at a cutoff")
    notes = {
        "leak_rate_first_try": leaked_first / cells if cells else None,
        "leak_rate_after_retry": leaked_after / cells if cells else None,
        "cells": cells,
        "undated_dropped": undated,
    }
    return MethodResult(
        CharacteristicPanel(period_ends=period_ends, values=values, source="issuer_first"),
        model=next(iter(models), None),
        notes=notes,
    )
