"""Check effectiveness (E41): how often a firing check led a reviewer to change the value."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from arp.orchestration.review_queue import _kind, effective_decisions
from arp.review.items import cosign_rule
from arp.schemas.review import field_item_key, period_key
from arp.storage.run_store import RunStore


@dataclass(frozen=True)
class CheckStat:
    check_id: str
    field_id: str
    field_version: int | None
    fired: int
    decided: int
    hits: int  # decided fired items a reviewer corrected or rejected
    overturns: int  # decided fired items a reviewer approved anyway
    hit_rate: float
    overturn_rate: float


def effectiveness(run_store: RunStore, *, run_ids: list[str] | None = None) -> list[CheckStat]:
    runs = [m.run_id for m in run_store.list_runs("extraction") if not m.params.get("trial")]
    if run_ids is not None:
        runs = [r for r in runs if r in run_ids]
    counts: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # fired, decided, hits, overturns
    for run_id in runs:
        decisions = effective_decisions(run_store, run_id, cosign_required=cosign_rule("extraction"))
        for row in run_store.read_jsonl(run_store.results_path(run_id)):
            for f in row.get("fields", []):
                kind = _kind(decisions.get(field_item_key(row.get("issuer_key", ""), f["field_id"], period_key(f))) or {})
                version = (f.get("provenance") or {}).get("field_version")
                for check_id in {c["check_id"] for c in f.get("checks", []) if c.get("outcome") == "fail"}:
                    n = counts[(check_id, f["field_id"], version)]
                    n[0] += 1
                    if kind:
                        n[1] += 1
                        n[2] += kind in ("correct", "reject")
                        n[3] += kind == "approve"
    return [
        CheckStat(c, fid, v, fired, decided, hits, overturns, hits / decided if decided else 0.0, overturns / decided if decided else 0.0)
        for (c, fid, v), (fired, decided, hits, overturns) in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1], -1 if kv[0][2] is None else kv[0][2]))
    ]
