"""Argus draft flows: an extraction being set up in steps 1 to 3, before any run exists.

One JSON file per flow under `runs_dir/_flows/`, so no worker, Run History or review code ever sees a draft."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from fastapi import Depends
from pydantic import BaseModel

from arp.api.auth import Principal
from arp.api.deps import settings_dep
from arp.config import Settings
from arp.schemas.common import CompanyRef, now_iso
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.locks import KeyedLock
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

logger = logging.getLogger(__name__)


class ArgusFlow(BaseModel):
    flow_id: str
    created_at: str
    updated_at: str
    started_by: str
    started_by_name: str
    step: int = 1  # the furthest step reached, 1..5
    companies: list[CompanyRef] = []
    identity_run_id: str | None = None


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
        return ArgusFlow.model_validate_json(read_text_utf8(path)) if path and path.is_file() else None

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


def get_flow_store(settings: Settings = Depends(settings_dep)) -> FlowStore:
    return FlowStore(settings.runs_dir / "_flows")
