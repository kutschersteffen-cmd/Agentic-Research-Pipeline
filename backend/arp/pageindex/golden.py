"""Score PageIndex answers on the retrieval gold set: a hit is a YES citing a page that holds the gold span."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from arp.grounding import _normalize


class GoldenError(Exception):
    pass


def ensure_document(cases_file: Path, documents_dir: Path, company_id: str, document: str) -> Path:
    """The document from documents.json beside the cases file, downloaded if missing, hash-checked always."""
    listing = cases_file.parent / "documents.json"
    entries = json.loads(listing.read_text()) if listing.exists() else []
    entry = next((e for e in entries if e["company_id"] == company_id and e["document"] == document), None)
    if entry is None:
        raise GoldenError(f"Document {document} is not listed in documents.json.")
    path = documents_dir / company_id / document
    if path.exists():
        data = path.read_bytes()
    else:
        try:
            resp = httpx.get(entry["url"], follow_redirects=True, timeout=120)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise GoldenError(f"Could not fetch {document}: {exc}") from exc
        data = resp.content
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise GoldenError(f"Document {document} does not match its recorded hash.")
    if not path.exists():  # written only once verified, so a bad download is fetched again next run
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def field_id(identifier: str) -> str:
    return f"tp_{identifier.lower()}"


def score(cases: list[dict], results: dict[str, dict], pages: dict[str, list[str]]) -> tuple[int, int, int, float]:
    """(hit, total, stale, yes_rate). `results` and `pages` are keyed by document; results by field id inside."""
    hit = total = stale = yes = 0
    for case in cases:
        doc, res = case["document"], results[case["document"]].get(case["field_id"], {})
        yes += res.get("answer") == "YES"
        norm_pages = [_normalize(p) for p in pages[doc]]
        whole = _normalize("\n".join(pages[doc]))
        for g in case["gold"]:
            span = _normalize(g["span_text"])
            if span not in whole:
                stale += 1
                continue
            total += 1
            cited = [norm_pages[p - 1] for p in res.get("pages", []) if 1 <= p <= len(norm_pages)]
            hit += res.get("answer") == "YES" and any(span in t for t in cited)
    return hit, total, stale, (yes / len(cases) if cases else 0.0)
