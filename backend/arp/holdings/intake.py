"""One holdings intake for file and API rows (E77): ISIN-to-LEI identity, review of unresolved ISINs,
API-over-file precedence, write-once revisions, an audit row per write, and holder staleness."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal

from arp.holdings.validate import RowError, Validated, iso_date
from arp.orchestration.review_queue import FINAL_STATES, effective_decisions, item_states, queue_for_review
from arp.portfolio.loads import LoadRecord, record_load
from arp.schemas.common import JobStatus, RunManifest, new_id, now_iso
from arp.schemas.issuer import ARP_NAMESPACE, lei_is_valid, normalise_lei
from arp.schemas.portfolio import HolderConfig, Holding, Portfolio, SecurityRef, SecurityResolution
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

if TYPE_CHECKING:
    from arp.api.auth import Principal


class IntakeError(ValueError):
    def __init__(self, status: int, message: str, errors: list[RowError] | None = None) -> None:
        super().__init__(message)
        self.status, self.message, self.errors = status, message, errors or []


@dataclass
class IntakeResult:
    status: Literal["written", "unchanged"]
    revision: int
    rows: int
    unresolved: list[str] = field(default_factory=list)
    review_run_id: str | None = None


def provisional_issuer_key(isin: str) -> str:
    return f"ARP:{uuid.uuid5(ARP_NAMESPACE, 'isin:' + isin)}"


def isin_decisions(run_store) -> dict[str, str]:
    """ISIN -> LEI from every final `security` correction, later runs winning."""
    out: dict[str, str] = {}
    runs = sorted(run_store.list_runs("holdings"), key=lambda m: m.created_at)
    for m in runs:
        for key, row in effective_decisions(run_store, m.run_id, cosign_required=set()).items():
            if key.startswith("isin:") and row.get("decision") == "correct":
                out[key.removeprefix("isin:")] = normalise_lei(str(row["corrected_value"]["value"]))
    return out


def open_isins(run_store) -> set[str]:
    """ISINs with a queued item not yet final in any holdings run: never queued twice."""
    out: set[str] = set()
    for m in run_store.list_runs("holdings"):
        states = item_states(run_store, m.run_id, cosign_required=set())
        for q in run_store.read_jsonl(run_store.review_queue_path(m.run_id)):
            s = states.get(q["item_key"])
            if s is None or s.state not in FINAL_STATES:
                out.add(q["item_key"].removeprefix("isin:"))
    return out


def resolve_issuer(isin: str, lei: str | None, *, idmap, decided: dict[str, str], on: str) -> tuple[str, str, bool]:
    if lei and lei_is_valid(lei):
        return lei, "LEI", False
    keys = idmap.resolve("ISIN", isin, on=on)
    if len(keys) == 1:
        return keys[0], "LEI" if lei_is_valid(keys[0]) else "ARP_PROVISIONAL", False
    if isin in decided:
        return decided[isin], "LEI", False
    return provisional_issuer_key(isin), "ARP_PROVISIONAL", True


def _precedence(store, holder: HolderConfig, kind: str, holder_id: str, as_of: str, source: str, reason: str | None) -> None:
    if source == "api" and holder.source == "file":
        raise IntakeError(409, "holder is configured for file intake")
    if source == "file" and holder.source == "api" and not (reason or "").strip():
        month = [d for d in store.list_snapshot_dates(holder_id, kind=kind) if d[:7] == as_of[:7]]
        if any(store.list_revisions(kind, holder_id, d) for d in month):
            raise IntakeError(409, "this month already has API data; an override needs a reason")


def ingest(
    store, validated: Validated, *, kind, holder_id: str, as_of: str, source, source_ref: str | None,
    principal: Principal | None, override_reason: str | None, run_store, idmap,
) -> IntakeResult:
    try:
        safe_id(holder_id, label="holder_id")
    except UnsafeIdentifierError as e:
        raise IntakeError(422, str(e)) from None
    if not iso_date(as_of):
        raise IntakeError(422, "as_of must be YYYY-MM-DD")
    if validated.errors:
        record_load(store, LoadRecord(kind="holdings", source_id=holder_id, month=as_of[:7], status="failed", content_hash="",
                                      detail=f"{len(validated.errors)} row errors"))
        raise IntakeError(422, "file rejected", validated.errors)
    holder = store.get_holder(kind, holder_id) or HolderConfig(holder_id=holder_id, kind=kind, source=source)
    _precedence(store, holder, kind, holder_id, as_of, source, override_reason)

    decided = isin_decisions(run_store)
    holdings: list[Holding] = []
    unresolved: list[dict] = []
    for r in validated.rows:
        isin = r["isin"]
        key, scheme, open_ = resolve_issuer(isin, r.get("lei"), idmap=idmap, decided=decided, on=as_of)
        currency = r.get("currency")
        fx = r.get("fx_rate_to_eur") if r.get("fx_rate_to_eur") is not None else (1.0 if currency == "EUR" else None)
        mv = r.get("market_value")
        holdings.append(Holding(
            holder_id=holder_id, kind=kind, security_id=isin, as_of_date=as_of, isin=isin, issuer_key=key,
            issuer_scheme=scheme, source=source, source_ref=source_ref, quantity=r.get("quantity"), price=r.get("price"),
            market_value=mv, market_value_eur=mv * fx if mv is not None and fx is not None else None,
            shares=r.get("shares"), free_float=r.get("free_float"), weight_pct=r.get("weight"), currency=currency,
            fx_rate_to_eur=fx,
        ))
        if store.get_security(isin) is None:  # the holdings row's security_id FK
            store.save_security(SecurityRef(
                security_id=isin, isin=isin, name=r.get("name") or isin, asset_class="other", currency=currency or "",
            ))
        res = store.get_resolution(isin)
        if open_:
            unresolved.append(r)
            if res is None:
                store.save_resolution(SecurityResolution(
                    security_id=isin, company_id=None, confidence=0.0, method="isin_exact", needs_review=True,
                ))
        elif res is not None and res.needs_review:
            store.save_resolution(res.model_copy(update={"needs_review": False}))

    def loaded(revision: int) -> None:
        digest = hashlib.sha256(json.dumps([h.model_dump(exclude={"source_ref"}) for h in holdings], sort_keys=True,
                                           default=str).encode()).hexdigest()
        record_load(store, LoadRecord(kind="holdings", source_id=holder_id, month=as_of[:7], status="ok",
                                      content_hash=digest, detail=f"{len(holdings)} rows, revision {revision}"))

    revisions = store.list_revisions(kind, holder_id, as_of)
    isins = [r["isin"] for r in unresolved]
    if revisions:
        latest = [h.model_dump(exclude={"source_ref"}) for h in store.load_revision(kind, holder_id, as_of, revisions[-1])]
        if latest == [h.model_dump(exclude={"source_ref"}) for h in holdings]:
            loaded(revisions[-1])
            return IntakeResult("unchanged", revisions[-1], len(holdings), isins, None)
    revision = len(revisions) + 1
    store.save_revision(kind, holder_id, as_of, revision, holdings)
    store.save_snapshot(holder_id, as_of, holdings, kind=kind)

    run_id = None
    already = open_isins(run_store) if unresolved else set()
    to_queue = [r for r in unresolved if r["isin"] not in already]
    if to_queue:
        run_id = new_id("hold")
        run_store.save_manifest(RunManifest(
            run_id=run_id, run_type="holdings", status=JobStatus.COMPLETED,
            params={"kind": kind, "holder_id": holder_id, "as_of": as_of, "revision": revision},
        ))
        for r in to_queue:
            queue_for_review(run_store, run_id, f"isin:{r['isin']}", {
                "kind": "security", "isin": r["isin"], "name": r.get("name"), "holder_id": holder_id,
                "holder_kind": kind, "as_of": as_of, "provisional_issuer_key": provisional_issuer_key(r["isin"]),
            })
    store.append_holdings_audit({
        "at": now_iso(), "kind": kind, "holder_id": holder_id, "as_of": as_of, "revision": revision, "source": source,
        "source_ref": source_ref, "rows": len(holdings), "user_id": principal.user_id if principal else "system",
        "role": principal.role if principal else "system", "override_reason": override_reason,
    })
    if kind == "portfolio" and store.get_portfolio(holder_id) is None:  # file-store analytics read the registry
        store.save_portfolio(Portfolio(portfolio_id=holder_id, name=holder.name or holder_id))
    store.save_holder(holder.model_copy(update={"as_of": max(holder.as_of or "", as_of), "last_error": None}))
    loaded(revision)
    return IntakeResult("written", revision, len(holdings), isins, run_id)


def previous_month_end(today: date) -> str:
    return (today.replace(day=1) - timedelta(days=1)).isoformat()


def holder_status(store, today: date) -> list[dict]:
    expected = previous_month_end(today)
    return [{
        "holder_id": h.holder_id, "kind": h.kind, "name": h.name, "source": h.source, "as_of": h.as_of,
        "last_pull_at": h.last_pull_at, "last_error": h.last_error, "expected_as_of": expected,
        "stale": h.as_of is None or h.as_of < expected,
        "age_days": (today - date.fromisoformat(h.as_of)).days if h.as_of else None,
    } for h in store.list_holders()]
