from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

from arp.ingestion.xbrl import CAPEX_TAGS, REVENUE_TAGS
from arp.storage.atomic_io import atomic_write_text
from arp.storage.jsonl_io import read_jsonl
from arp.xbrl_pipeline.models import TagEntry
from arp.xbrl_pipeline.store import XbrlStore

_XS = "{http://www.w3.org/2001/XMLSchema}"
_LINK = "{http://www.xbrl.org/2003/linkbase}"
_XLINK = "{http://www.w3.org/1999/xlink}"
_XBRLI = "{http://www.xbrl.org/2003/instance}"
_ROLE = "http://www.xbrl.org/2003/role/"
_DEPRECATED = re.compile(r"\(Deprecated\b")
_SNAPSHOT = re.compile(r"^(?P<tax>.+)-(?P<year>\d{4})$")
_PINNED = [f"us-gaap:{c}" for c in (*REVENUE_TAGS, *CAPEX_TAGS)]


@dataclass(frozen=True)
class TaxonomySource:
    year: int
    url: str | None  # elements schema; None = official file not confirmed, update refuses to run
    labels: tuple[str, ...] = ()  # label and documentation linkbases


# Official files, confirmed reachable on 2026-10-09.
TAXONOMY_SOURCES: dict[str, TaxonomySource] = {
    "us-gaap": TaxonomySource(
        2026,
        "https://xbrl.fasb.org/us-gaap/2026/elts/us-gaap-2026.xsd",
        (
            "https://xbrl.fasb.org/us-gaap/2026/elts/us-gaap-lab-2026.xml",
            "https://xbrl.fasb.org/us-gaap/2026/elts/us-gaap-doc-2026.xml",
        ),
    ),
    "ifrs-full": TaxonomySource(
        2025,
        "https://xbrl.ifrs.org/taxonomy/2025-03-27/full_ifrs/full_ifrs-cor_2025-03-27.xsd",
        ("https://xbrl.ifrs.org/taxonomy/2025-03-27/full_ifrs/labels/lab_full_ifrs-en_2025-03-27.xml",),
    ),
    "dei": TaxonomySource(
        2026,
        "https://xbrl.sec.gov/dei/2026/dei-2026.xsd",
        ("https://xbrl.sec.gov/dei/2026/dei-2026_lab.xsd", "https://xbrl.sec.gov/dei/2026/dei-2026_doc.xsd"),
    ),
}


MAX_TAXONOMY_BYTES = 64 * 1024 * 1024
_ENTITY_FORMS = tuple("<!ENTITY".encode(enc) for enc in ("utf-8", "utf-16-le", "utf-16-be"))


def _parse(data: bytes, taxonomy: str) -> ET.Element:
    # Third-party input: ElementTree never fetches external entities; refuse entity declarations
    # (UTF-8 and UTF-16 spellings) and oversized files outright.
    if len(data) > MAX_TAXONOMY_BYTES:
        raise ValueError(f"taxonomy {taxonomy!r}: file larger than {MAX_TAXONOMY_BYTES} bytes")
    if any(form in data for form in _ENTITY_FORMS):
        raise ValueError(f"taxonomy {taxonomy!r}: file declares XML entities")
    return ET.fromstring(data)


def parse_taxonomy(xsd: bytes, labels: bytes | Sequence[bytes], *, taxonomy: str) -> list[TagEntry]:
    names: dict[str, tuple[str, dict[str, str]]] = {}  # element id -> (concept, attributes)
    for el in _parse(xsd, taxonomy).iter(f"{_XS}element"):
        if el.get("abstract") != "true" and el.get("id") and el.get("name"):
            names[el.get("id", "")] = (el.get("name", ""), el.attrib)

    label: dict[str, str] = {}
    doc: dict[str, str] = {}
    for blob in [labels] if isinstance(labels, bytes) else labels:
        for link in _parse(blob, taxonomy).iter(f"{_LINK}labelLink"):
            locs = {x.get(f"{_XLINK}label"): (x.get(f"{_XLINK}href") or "").partition("#")[2]
                    for x in link.iter(f"{_LINK}loc")}
            res = {x.get(f"{_XLINK}label"): (x.get(f"{_XLINK}role"), (x.text or "").strip())
                   for x in link.iter(f"{_LINK}label")}
            for arc in link.iter(f"{_LINK}labelArc"):
                eid, (role, text) = locs.get(arc.get(f"{_XLINK}from")), res.get(arc.get(f"{_XLINK}to"), (None, ""))
                if eid in names and text:
                    if role == _ROLE + "label":
                        label.setdefault(eid, text)
                    elif role == _ROLE + "documentation":
                        doc.setdefault(eid, text)

    return [
        TagEntry(
            taxonomy=taxonomy,
            concept=concept,
            label=label.get(eid),
            data_type=(attrs.get("type") or "").rpartition(":")[2] or None,
            period_type=attrs.get(f"{_XBRLI}periodType"),
            balance=attrs.get(f"{_XBRLI}balance"),
            documentation=doc.get(eid),
            deprecated=bool(_DEPRECATED.search(label.get(eid, ""))),
        )
        for eid, (concept, attrs) in names.items()
    ]


class TaxonomyRegistry:
    def __init__(self, store: XbrlStore) -> None:
        self.store = store

    def write_snapshot(self, taxonomy: str, year: int, entries: list[TagEntry]) -> None:
        lines = "".join(e.model_dump_json() + "\n" for e in entries)
        atomic_write_text(self.store.taxonomy_dir / f"{taxonomy}-{year}.jsonl", lines)

    def _latest_snapshots(self) -> list[dict]:
        latest: dict[str, tuple[int, object]] = {}
        for p in self.store.taxonomy_dir.glob("*.jsonl") if self.store.taxonomy_dir.exists() else []:
            m = _SNAPSHOT.match(p.stem)
            if m and int(m["year"]) > latest.get(m["tax"], (-1, p))[0]:
                latest[m["tax"]] = (int(m["year"]), p)
        return [r for _, p in latest.values() for r in read_jsonl(p)]  # type: ignore[arg-type]

    def search(self, q: str = "", *, taxonomy: str | None = None, seen_only: bool = False,
               extension_only: bool = False, include_deprecated: bool = True, offset: int = 0,
               limit: int = 50) -> tuple[list[TagEntry], int]:
        # ponytail: seen counts scan every catalogue per search, memoise on directory mtime if slow
        seen: Counter[str] = Counter()
        cat_labels: dict[str, str | None] = {}
        for cik in self.store.ciks():
            ids = set()
            for c in self.store.read_catalog(cik):
                ids.add(f"{c.taxonomy}:{c.concept}")
                cat_labels.setdefault(f"{c.taxonomy}:{c.concept}", c.label)
            seen.update(ids)

        rows = self._latest_snapshots()
        known = {f"{r['taxonomy']}:{r['concept']}" for r in rows}
        rows += [{"taxonomy": t, "concept": c, "label": cat_labels[i], "data_type": None, "period_type": None,
                 "balance": None, "documentation": None,
                 "extension": i.partition(":")[0] not in TAXONOMY_SOURCES}
                 for i in seen if i not in known for t, _, c in [i.partition(":")]]
        for r in rows:
            r["seen_count"] = seen[f"{r['taxonomy']}:{r['concept']}"]

        needle = q.strip().lower()
        hits = [
            r for r in rows
            if (taxonomy is None or r["taxonomy"] == taxonomy)
            and (not seen_only or r["seen_count"])
            and (not extension_only or r.get("extension"))
            and (include_deprecated or not r.get("deprecated"))
            and (not needle or needle in r["concept"].lower() or needle in (r.get("label") or "").lower())
        ]
        pin = {t: i for i, t in enumerate(_PINNED)}
        hits.sort(key=lambda r: ((pin.get(f"{r['taxonomy']}:{r['concept']}", len(pin)) if not needle else 0),
                                 r["concept"], r["taxonomy"]))
        return [TagEntry.model_validate(r) for r in hits[offset:offset + limit]], len(hits)


async def update_taxonomies(
    store: XbrlStore, *, fetch: Callable[[str], Awaitable[bytes]], taxonomies: list[str] | None = None,
) -> dict[str, int]:
    names = taxonomies or list(TAXONOMY_SOURCES)
    for name in names:
        if name not in TAXONOMY_SOURCES:
            raise ValueError(f"unknown taxonomy {name!r}")
        if TAXONOMY_SOURCES[name].url is None:
            raise ValueError(f"no official source url configured for taxonomy {name!r}")
    registry, written = TaxonomyRegistry(store), {}
    for name in names:
        src = TAXONOMY_SOURCES[name]
        xsd, *labels = await asyncio.gather(fetch(src.url or ""), *(fetch(u) for u in src.labels))
        entries = parse_taxonomy(xsd, labels, taxonomy=name)
        registry.write_snapshot(name, src.year, entries)
        written[name] = len(entries)
    return written


async def http_fetch(url: str, *, user_agent: str) -> bytes:
    # sec.gov rejects requests without a descriptive User-Agent.
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0, headers={"User-Agent": user_agent}) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
