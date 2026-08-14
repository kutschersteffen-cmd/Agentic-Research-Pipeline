from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from arp.schemas.common import CompanyRef
from arp.schemas.discovery import DiscoveredDocument, DocumentEvent, DocumentEventType
from arp.storage.safe_path import safe_id

logger = logging.getLogger(__name__)


class ChangeDetector:
    """The "new document" hook.

    Maintains a per-company manifest of previously-seen document URLs and
    their content hashes under `discovery_state_dir/<company_id>.json`.
    Every discovery run diffs freshly downloaded documents against that
    manifest and emits a DocumentEvent (new or updated) for anything that
    wasn't seen before or whose hash changed. Events are:
      1. appended to a global rolling JSONL feed the UI/API can poll, and
      2. POSTed (best-effort) to a configured webhook URL, if any.
    """

    def __init__(self, state_dir: Path, global_events_path: Path, webhook_url: str | None = None) -> None:
        self.state_dir = state_dir
        self.global_events_path = global_events_path
        self.webhook_url = webhook_url
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

        return events

    def _append_global_event(self, event: DocumentEvent) -> None:
        self.global_events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.global_events_path.open("a") as f:
            f.write(event.model_dump_json() + "\n")

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
        rows: list[dict] = []
        with global_events_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since and row.get("created_at", "") <= since:
                    continue
                rows.append(row)
        return rows[-limit:]
