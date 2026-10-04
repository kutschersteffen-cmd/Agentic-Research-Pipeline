from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from arp.schemas.common import CompanyRef
from arp.schemas.discovery import DiscoveredDocument, DocumentEvent, DocumentEventType
from arp.storage.jsonl_io import append_jsonl, read_jsonl
from arp.storage.safe_path import safe_id

if TYPE_CHECKING:
    from arp.ingestion.esef import EsefDocumentSource

logger = logging.getLogger(__name__)


class ChangeDetector:
    """The "new document" hook.

    Maintains a per-company manifest of previously-seen document URLs and
    their content hashes under `discovery_state_dir/<company_id>.json`.
    Every discovery run diffs freshly downloaded documents against that
    manifest and emits a DocumentEvent (new or updated) for anything that
    wasn't seen before or whose hash changed. Events are:
      1. appended to a global rolling JSONL feed the UI/API can poll, and
      2. POSTed (best-effort) to a configured webhook URL, if any, and
      3. handed to `on_events(events, company)` (event-driven refresh, E20), if given; its
         errors are logged, never raised.
    """

    def __init__(
        self,
        state_dir: Path,
        global_events_path: Path,
        webhook_url: str | None = None,
        on_events: Callable[[list[DocumentEvent], CompanyRef], Awaitable[object]] | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.global_events_path = global_events_path
        self.webhook_url = webhook_url
        self.on_events = on_events
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, company_id: str) -> Path:
        return self.state_dir / f"{safe_id(company_id, label='company_id')}.json"

    def _load_manifest(self, company_id: str) -> dict[str, dict]:
        path = self._manifest_path(company_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_manifest(self, company_id: str, manifest: dict[str, dict]) -> None:
        self._manifest_path(company_id).write_text(json.dumps(manifest, indent=2))

    async def diff_and_record(
        self, company: CompanyRef, discovered_docs: list[DiscoveredDocument]
    ) -> list[DocumentEvent]:
        manifest = self._load_manifest(company.company_id)
        events: list[DocumentEvent] = []

        for doc in discovered_docs:
            prior = manifest.get(doc.url)
            if prior is None:
                events.append(
                    DocumentEvent(event_type=DocumentEventType.NEW_DOCUMENT, company_id=company.company_id,
                                  company_name=company.name, document=doc)
                )
            elif prior.get("sha256") != doc.sha256:
                events.append(
                    DocumentEvent(event_type=DocumentEventType.UPDATED_DOCUMENT, company_id=company.company_id,
                                  company_name=company.name, document=doc)
                )
            manifest[doc.url] = doc.model_dump(mode="json")

        self._save_manifest(company.company_id, manifest)

        for event in events:
            self._append_global_event(event)
            await self._notify_webhook(event)

        if events and self.on_events is not None:
            try:
                await self.on_events(events, company)
            except Exception:  # noqa: BLE001 - a refresh failure never fails discovery
                logger.exception("on_events hook failed for %s", company.company_id)

        return events

    def _append_global_event(self, event: DocumentEvent) -> None:
        append_jsonl(self.global_events_path, event.model_dump(mode="json"))

    async def _notify_webhook(self, event: DocumentEvent) -> None:
        if not self.webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(self.webhook_url, json=event.model_dump(mode="json"))
        except httpx.HTTPError as exc:
            logger.warning("Discovery webhook notification failed: %s", exc)

    @staticmethod
    def read_recent_events(global_events_path: Path, since: str | None = None, limit: int = 200) -> list[dict]:
        if not global_events_path.exists():
            return []
        rows = [row for row in read_jsonl(global_events_path) if not (since and row.get("created_at", "") <= since)]
        return rows[-limit:]


async def poll_esef_filings(
    company: CompanyRef, source: EsefDocumentSource, detector: ChangeDetector, doc_types: list | None = None
) -> list[DocumentEvent]:
    """ESEF feed polling (E16): the company's latest ESEF filing from the index (by LEI), recorded
    like any discovered document, so a new or changed filing raises a DocumentEvent."""
    try:
        docs = await source.fetch(company, doc_types)
    except Exception as exc:  # noqa: BLE001 - a polling failure never discards the company's crawl result
        logger.warning("ESEF filing poll failed for %s: %s", company.company_id, exc)
        return []
    found = [
        DiscoveredDocument(company_id=company.company_id, doc_type=d.doc_type, url=d.source_url,
                           local_path=d.local_path, sha256=d.content_key or d.sha256)
        for d in docs if d.source_url
    ]
    return await detector.diff_and_record(company, found) if found else []
