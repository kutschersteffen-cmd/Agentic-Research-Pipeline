"""Seeds one finished discovery run with three open review items for the evaluator (no network):
`no_documents:C1` and two flagged PDFs of C2. Writes where the app reads: the configured run store,
`documents_dir` and `discovery_state_dir`.

    bash backend/scripts/e2e_stack.sh up && python backend/scripts/seed_discovery_review.py
"""

from __future__ import annotations

import asyncio
import hashlib

from arp.cli._shared import _run_store
from arp.config import Settings, get_settings
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.review import review_items
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.discovery import DiscoveredDocument, DiscoveryCompanyResult, DiscoveryRunParams
from arp.storage.run_store import RunStore

C1 = CompanyRef(company_id="C1", name="First Co", country="DE")
C2 = CompanyRef(company_id="C2", name="Second Co", country="DE")
FILES = {"report-a": "Unrelated Group Alpha", "report-b": "Unrelated Group Beta"}


def _pdf(text: str) -> bytes:
    """A one-page PDF; xref offsets are left to the reader's repair, which is enough for a file on disk."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    return (
        "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        f"4 0 obj<</Length {len(stream)}>>stream\n{stream}\nendstream endobj\n"
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    ).encode()


def main(settings: Settings | None = None, run_store: RunStore | None = None) -> str:
    settings = settings or get_settings()
    run_store = run_store or _run_store()
    doc_dir = settings.documents_dir / "C2" / "10-K"
    doc_dir.mkdir(parents=True, exist_ok=True)
    docs = []
    for name, text in FILES.items():
        path = doc_dir / f"{name}.pdf"
        body = _pdf(text)
        path.write_bytes(body)
        docs.append(DiscoveredDocument(
            company_id="C2", doc_type=DocType.ANNUAL_REPORT_10K, url=f"https://c2.example/{name}.pdf",
            local_path=str(path), sha256=hashlib.sha256(body).hexdigest(), company_match="none", page_count=1,
        ))
    detector = ChangeDetector(settings.discovery_state_dir, settings.documents_dir / "_events.jsonl")
    asyncio.run(detector.diff_and_record(C2, docs))

    jm = JobManager(run_store)
    params = DiscoveryRunParams(universe_source="seed: 2 companies", triggered_by="manual")
    run_id = jm.create_run("discovery", params.model_dump(mode="json"), 2, companies=[C1, C2]).run_id
    for company, found in ((C1, []), (C2, docs)):
        result = DiscoveryCompanyResult(company_id=company.company_id, name=company.name, documents_found=found)
        items = review_items(company, result, triggered_by="manual")
        run_store.record_company_result(
            run_id, {**result.model_dump(mode="json"), "_key": company.company_id},
            observations=[], review_items=items, company=company,
        )
        jm.record_progress(run_id, completed_delta=1, review_delta=len(items))
    jm.finish_run(run_id)
    print(run_id)
    return run_id


if __name__ == "__main__":
    main()
