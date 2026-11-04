"""Evidence gate (evidence-gate spec): a cheap model drops retrieved passages that cannot help answer a field, before
the extraction call. Off unless a run opens one (`gate_run`); it fails open (any failure keeps every passage), and
after `evidence_gate_breaker` failures in a row it switches itself off for the rest of the run."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from arp.config import Settings
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk
from arp.schemas.datapoints import FieldDefinition

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You screen evidence for a data extraction. Given a field to extract and numbered passages from a company's "
    "documents, list the numbers of the passages that could help answer the field: they state the value, a figure "
    "it is computed from, or the context needed to read it. Leave out passages that only share words with the field. "
    "When unsure, keep the passage."
)


class GateAnswer(BaseModel):
    keep: list[int] = Field(description="Numbers of the passages that could help answer the field.")
    reason: str = Field(default="", description="One sentence on what was left out and why.")


@dataclass
class GateResult:
    kept: list[DocumentChunk]
    dropped: list[DocumentChunk]
    info: dict  # {"kept", "of", "failed", "skipped"}: the trace's retrieval.gate
    usage: LLMUsage | None = None
    answer: GateAnswer | None = None


@dataclass
class EvidenceGate:
    llm: LLMClient
    min_keep: int = 3
    breaker: int = 3
    timeout_s: float = 20.0
    run_id: str = ""
    failures: int = 0
    open: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def skip(self, evidence: list[DocumentChunk], reason: str) -> GateResult:
        return GateResult(evidence, [], {"kept": len(evidence), "of": len(evidence), "failed": False, "skipped": reason})

    async def apply(self, f: FieldDefinition, evidence: list[DocumentChunk], *, grouped: bool = False,
                    unranked: bool = False) -> GateResult:
        n = len(evidence)
        reason = ("grouped" if grouped else "high risk" if f.high_risk else "unranked" if unranked
                  else "too few passages" if n <= self.min_keep else "breaker open" if self.open else None)
        if reason:
            return self.skip(evidence, reason)
        passages = "\n\n".join(f"[{i}] {c.text}" for i, c in enumerate(evidence, start=1))
        prompt = (f"Field: {f.name}\nDescription: {f.description}\nExtraction instructions: {f.extraction_instructions}"
                  f"\n\nPassages:\n\n{passages}")
        answer = usage = None
        try:
            answer, usage = await asyncio.wait_for(
                self.llm.complete_structured(system=_SYSTEM, prompt=prompt, output_model=GateAnswer), self.timeout_s)
            ids = {i for i in answer.keep if 1 <= i <= n}
        except Exception as exc:  # noqa: BLE001 -- fail open: a gate that cannot answer keeps every passage
            logger.debug("evidence gate failed for %s: %s", f.field_id, exc)
            ids = set()
        async with self._lock:
            if not ids:
                self.failures += 1
                if self.failures >= self.breaker and not self.open:
                    self.open = True
                    logger.warning("evidence gate breaker open: gate off for the rest of run %s", self.run_id)
            else:
                self.failures = 0
        if not ids:
            return GateResult(evidence, [], {"kept": n, "of": n, "failed": True, "skipped": None}, usage, answer)
        kept = [c for i, c in enumerate(evidence, start=1) if i <= self.min_keep or i in ids]
        dropped = [c for c in evidence if c not in kept]
        return GateResult(kept, dropped, {"kept": len(kept), "of": n, "failed": False, "skipped": None}, usage, answer)


_current: ContextVar[EvidenceGate | None] = ContextVar("evidence_gate", default=None)


def current_gate() -> EvidenceGate | None:
    return _current.get()


@contextmanager
def gate_run(settings: Settings, run_id: str = "", llm: LLMClient | None = None, *, enabled: bool | None = None
             ) -> Iterator[EvidenceGate | None]:
    """Opens a gate for every field extracted inside it, when `enabled` (default: the setting); otherwise nothing."""
    if not (settings.evidence_gate_enabled if enabled is None else enabled):
        yield None
        return
    if llm is None:
        from arp.llm.factory import build_llm_client

        llm = build_llm_client(settings, model=settings.evidence_gate_model)
    gate = EvidenceGate(llm, settings.evidence_gate_min_keep, settings.evidence_gate_breaker,
                        settings.evidence_gate_timeout_s, run_id)
    token = _current.set(gate)
    try:
        yield gate
    finally:
        _current.reset(token)
