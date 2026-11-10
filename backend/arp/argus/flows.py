"""Argus draft flows: an extraction being set up in steps 1 to 3, before any run exists.

One JSON file per flow under `runs_dir/_flows/`, so no worker, Run History or review code ever sees a draft."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends
from pydantic import BaseModel, Field

from arp.api.auth import Principal
from arp.api.deps import settings_dep
from arp.config import Settings
from arp.schemas.common import CompanyRef, now_iso
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.locks import KeyedLock
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

logger = logging.getLogger(__name__)


def safe_key(value: str) -> str:
    """A company key every documents endpoint accepts (`safe_id`): `Siemens AG` becomes `siemens-ag-<hash>`.
    The hash of the whole value keeps names that slug alike (`ACME, Inc.`, `Acme Inc`) apart, and is stable."""
    try:
        return safe_id(value)
    except UnsafeIdentifierError:
        digest = hashlib.sha1(value.encode()).hexdigest()[:8]
        slug = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-._")[:100].rstrip("-._")
        return f"{slug}-{digest}" if slug else f"company-{digest}"


class SkippedUpload(BaseModel):
    company_id: str
    filename: str
    duplicate_of: str


class SchemaChoice(BaseModel):
    """What step 3 extracts: a saved schema version, or a fixed profile."""

    kind: Literal["schema", "profile"]
    schema_id: str | None = None
    version: int | None = None
    profile: Literal["financials", "tnfd"] | None = None

    def model_post_init(self, _context) -> None:
        if self.kind == "profile":
            self.schema_id = self.version = None
        else:
            self.profile = None


class FlowSettings(BaseModel):
    mode: Literal["cheap", "normal", "max"] = "normal"
    evidence_passages: int | None = Field(default=None, ge=1, le=50)
    batch: bool = False
    decision_framework_id: str | None = None
    decision_framework_version: int | None = None


class ArgusFlow(BaseModel):
    flow_id: str
    created_at: str
    updated_at: str
    started_by: str
    started_by_name: str
    step: int = 1  # the furthest step reached, 1..5
    companies: list[CompanyRef] = []
    identity_run_id: str | None = None
    # step 2
    reporting_year: int | None = None  # None reads as the previous calendar year
    source: Literal["upload", "import", "filings", "filings_web"] | None = None
    discovery_run_id: str | None = None
    decisions: dict[str, Literal["kept", "removed"]] = {}
    skipped_uploads: list[SkippedUpload] = []
    # step 3
    schema_choice: SchemaChoice | None = None
    settings: FlowSettings = FlowSettings()
    repeat: dict[str, Literal["skip", "run"]] = {}
    run_id: str | None = None
    starting: bool = False  # set while a Start is being dispatched


class FlowStore:
    def __init__(self, flows_dir: Path) -> None:
        self.flows_dir = flows_dir
        self._lock = KeyedLock(lambda key: flows_dir / f".{key}.lock")

    def _path(self, flow_id: str) -> Path | None:
        try:
            return self.flows_dir / f"{safe_id(flow_id, label='flow id')}.json"
        except UnsafeIdentifierError:
            return None

    def create(self, principal: Principal) -> ArgusFlow:
        now = now_iso()
        flow = ArgusFlow(flow_id=uuid4().hex, created_at=now, updated_at=now,
                         started_by=principal.user_id, started_by_name=principal.name)
        return self.save(flow)

    def get(self, flow_id: str) -> ArgusFlow | None:
        path = self._path(flow_id)
        if not (path and path.is_file()):
            return None
        flow = ArgusFlow.model_validate_json(read_text_utf8(path))
        for c in flow.companies:  # flows saved before keys were made safe
            c.company_id = safe_key(c.company_id)
        return flow

    def save(self, flow: ArgusFlow) -> ArgusFlow:
        self.flows_dir.mkdir(parents=True, exist_ok=True)
        flow.updated_at = now_iso()
        atomic_write_text(self._path(flow.flow_id), flow.model_dump_json(indent=2))
        return flow

    def list(self) -> list[ArgusFlow]:
        if not self.flows_dir.is_dir():
            return []
        flows = []
        for p in self.flows_dir.glob("*.json"):
            try:
                flows.append(ArgusFlow.model_validate_json(read_text_utf8(p)))
            except (OSError, ValueError):  # one unreadable file must not hide every other flow
                logger.warning("unreadable flow file %s", p.name)
        return sorted(flows, key=lambda f: f.created_at, reverse=True)

    def update(self, flow_id: str, fn: Callable[[ArgusFlow], None]) -> ArgusFlow | None:
        if self._path(flow_id) is None:
            return None
        self.flows_dir.mkdir(parents=True, exist_ok=True)
        with self._lock.acquire(flow_id):
            flow = self.get(flow_id)
            if flow is None:
                return None
            fn(flow)
            return self.save(flow)

    def delete_if_empty(self, flow_id: str) -> bool | None:
        """Remove a draft nobody has used yet (no companies, still at step 1, no run): None if missing, False if in use."""
        if self._path(flow_id) is None:
            return None
        with self._lock.acquire(flow_id):
            flow = self.get(flow_id)
            if flow is None:
                return None
            if flow.companies or flow.step > 1 or flow.run_id:
                return False
            self._path(flow_id).unlink(missing_ok=True)
            return True


def get_flow_store(settings: Settings = Depends(settings_dep)) -> FlowStore:
    return FlowStore(settings.runs_dir / "_flows")
