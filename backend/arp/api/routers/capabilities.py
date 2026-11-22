"""The capability catalog over HTTP: every function an agent may call (spec agent-panel-code-mode)."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from arp.orchestration.capabilities import CATALOG

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


class CapabilityOut(BaseModel):
    id: str
    summary: str
    effect: Literal["read", "run"]
    lane: Literal["plan", "sandbox"]
    input_schema: dict[str, Any]


@router.get("", response_model=list[CapabilityOut])
def list_capabilities() -> list[CapabilityOut]:
    """Sandbox lane first, then plan lane, each sorted by id; `input_schema` is the input model's JSON schema."""
    ordered = sorted(CATALOG, key=lambda c: (c.lane != "sandbox", c.id))
    return [CapabilityOut(id=c.id, summary=c.summary, effect=c.effect, lane=c.lane,
                          input_schema=c.input_model.model_json_schema()) for c in ordered]
