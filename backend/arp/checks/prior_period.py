"""Layer 4 prior-period checks and restatement candidates (E37)."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from arp.checks.plausibility import numeric_of
from arp.checks.runner import threshold_ref
from arp.extraction.history import RunHistory
from arp.schemas.common import new_id, now_iso
from arp.schemas.datapoints import (
    CheckOutcome,
    CheckResult,
    ExtractedField,
    ExtractionRecord,
    FieldDefinition,
    Severity,
)
from arp.schemas.review import field_item_key, period_key
from arp.storage.run_store import RunStore

_NA = CheckOutcome.NOT_APPLICABLE
_LAST_DECIDED = "prior.last_decided"


def _result(check_id: str, outcome: CheckOutcome, detail: str = "", ref: str | None = None) -> list[CheckResult]:
    return [CheckResult(check_id=check_id, layer=4, outcome=outcome, severity=Severity.WARN, detail=detail, threshold_ref=ref)]


def check_comparative_jump(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, limit, new = "prior.comparative_jump", spec.check_config.prior_change_max, numeric_of(field)
    rows = sorted(
        (r for r in ctx.record_fields if r.field_id == field.field_id and r.period_end), key=lambda r: r.period_end, reverse=True
    )
    older = next((r for r in rows if field.period_end and r.period_end < field.period_end), None)
    old = numeric_of(older) if older else None
    if limit is None or new is None or old is None:
        return _result(cid, _NA)
    ref = threshold_ref(spec, "prior_change_max")
    change = abs(new - old) / max(abs(old), 1e-9)
    if change > limit:
        return _result(cid, CheckOutcome.FAIL, f"changed {change:.0%} vs {older.period_end} ({old:g} -> {new:g})", ref)
    return _result(cid, CheckOutcome.PASS, ref=ref)


def check_last_decided(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    if ctx.history is None or period_key(field) == "unspecified":
        return _result(_LAST_DECIDED, _NA)
    prior = ctx.history.last_decided(field_item_key(ctx.issuer_key, field.field_id, period_key(field)))
    if prior is None:
        return _result(_LAST_DECIDED, _NA)
    old = prior.canonical_value
    if old is None and isinstance(prior.value, (int, float)) and not isinstance(prior.value, bool):
        old = float(prior.value)
    new = numeric_of(field)
    differs = (
        not math.isclose(new, old, rel_tol=1e-6) if new is not None and old is not None else str(prior.value) != str(field.value)
    )
    if differs:
        return _result(_LAST_DECIDED, CheckOutcome.FAIL, f"was {prior.value} in run {prior.run_id}, now {field.value}")
    return _result(_LAST_DECIDED, CheckOutcome.PASS)


class RestatementCandidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: new_id("rst"))
    item_key: str
    issuer_key: str
    field_id: str
    period_end: str
    previous_value: str | float | bool | None
    previous_run_id: str
    new_value: str | float | bool | None
    run_id: str
    doc_ids: list[str] = Field(default_factory=list)
    status: Literal["open"] = "open"
    opened_at: str = Field(default_factory=now_iso)


def open_restatement_candidates(run_store: RunStore, run_id: str, record: ExtractionRecord, history: RunHistory) -> int:
    latest: dict[str, str] = {}
    for f in record.fields:
        if f.period_end and f.period_end > latest.get(f.field_id, ""):
            latest[f.field_id] = f.period_end
    n = 0
    for f in record.fields:
        if not f.period_end or f.period_end == latest[f.field_id]:
            continue  # the current period is not a comparative
        if not any(r.check_id == _LAST_DECIDED and r.outcome == CheckOutcome.FAIL for r in f.checks):
            continue
        key = field_item_key(record.issuer_key, f.field_id, f.period_end)
        prior = history.last_decided(key)
        if prior is None:
            continue
        cand = RestatementCandidate(
            item_key=key, issuer_key=record.issuer_key, field_id=f.field_id, period_end=f.period_end,
            previous_value=prior.value, previous_run_id=prior.run_id, new_value=f.value, run_id=run_id,
            doc_ids=sorted({c.doc_id for c in f.citations}),
        )
        run_store.append_jsonl(run_store.restatements_path(run_id), cand.model_dump(mode="json"))
        n += 1
    return n
