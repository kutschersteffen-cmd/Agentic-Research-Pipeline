"""Discovery review items: which flagged results a reviewer sees (spec: discovery-review-queue)."""

from __future__ import annotations

import shutil
from pathlib import Path

from arp.config import Settings
from arp.discovery.change_detector import ChangeDetector
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import DiscoveryCompanyResult
from arp.schemas.review import ReasonCode
from arp.storage.safe_path import safe_id

_FLAGS = {"none": ReasonCode.MATCH_AMBIGUOUS, "no_text": ReasonCode.CHECK_FAILED}


def review_items(company: CompanyRef, result: DiscoveryCompanyResult, *, triggered_by: str) -> list[tuple[str, dict]]:
    """`(item_key, payload)` per PDF whose check flagged it (unless a reviewer approved it already) and, on a
    manual run, one `no_documents` item for a company with no document at all."""
    if not result.documents_found:
        if triggered_by != "manual":
            return []
        return [(f"no_documents:{company.company_id}", {
            "company_id": company.company_id, "name": company.name, "homepage_used": result.homepage_used,
            "homepage_unreachable": result.homepage_unreachable, "crawl_error": result.crawl_error,
            "reason_codes": [ReasonCode.NO_DOCUMENTS.value],
        })]
    return [
        (f"discovered:{company.company_id}:{d.sha256}", {
            "company_id": company.company_id, "name": company.name, "url": d.url, "doc_type": d.doc_type.value,
            "local_path": d.local_path, "sha256": d.sha256, "company_match": d.company_match,
            "page_count": d.page_count, "reporting_year": d.reporting_year, "reason_codes": [_FLAGS[d.company_match].value],
        })
        for d in result.documents_found
        if d.company_match in _FLAGS and d.review != "approved" and d.sha256
    ]


def apply_decision(settings: Settings, payload: dict, decision: str) -> None:
    """A final decision on a `discovered_document` item. Reject: the file leaves the working folder for
    `_rejected/` and the manifest entry is marked, so warm, the theme run and the next discovery skip it. Approve:
    the entry is marked, so the document is not queued again (an approve never undoes a reject). The blob store
    and the capture log are untouched."""
    if decision not in ("approve", "reject"):
        return
    company_id, url = payload["company_id"], payload["url"]
    detector = ChangeDetector(settings.discovery_state_dir, settings.documents_dir / "_events.jsonl")
    if decision == "approve":
        entry = detector.known_documents(company_id).get(url)
        if entry is None or entry.review != "rejected":
            detector.set_review(company_id, url, "approved")
        return
    src = Path(payload["local_path"]) if payload.get("local_path") else None
    if src is not None and src.exists():
        dest = settings.documents_dir / "_rejected" / safe_id(company_id, label="company_id") / payload["doc_type"] / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        shutil.move(src, dest)
    detector.set_review(company_id, url, "rejected")
