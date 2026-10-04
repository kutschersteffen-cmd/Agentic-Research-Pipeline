"""Monthly holdings pull from another ARP instance's frozen snapshots (E77), through the one intake."""

from __future__ import annotations

from datetime import date

from arp.holdings.intake import IntakeError, IntakeResult, ingest, previous_month_end
from arp.holdings.validate import iso_date, validate
from arp.schemas.common import now_iso
from arp.schemas.portfolio import HolderConfig
from arp.snapshots.client import SnapshotClient

COLUMNS = ("weight", "shares", "free_float", "price", "market_value", "currency", "fx_rate_to_eur")


def pull_holder(
    holder: HolderConfig, as_of: str, *, client: SnapshotClient, base_url: str, store, run_store, idmap,
    today: date | None = None,
) -> IntakeResult:
    """On any error past the request checks the holder is flagged; the previous month stays the readable one."""
    if not iso_date(as_of):
        raise IntakeError(422, "as_of must be YYYY-MM-DD")
    if holder.source != "api":
        raise IntakeError(409, "holder is configured for file intake")
    dataset = "index_holdings" if holder.kind == "index" else "portfolio_holdings"
    id_col = f"{holder.kind}_id"
    try:
        manifest, rows = client.rows(as_of[:7], dataset)
        # Only rows dated as_of: an upstream holder whose newest data is older must not land relabelled.
        mine = [r for r in rows if r.get(id_col) == holder.holder_id and r.get("as_of") == as_of]
        if not mine:
            raise ValueError(f"{manifest.snapshot_id} has no {dataset} rows for {holder.holder_id} as of {as_of}")
        raw = [{
            "_row": n, "isin": r.get("isin"), "lei": r.get("issuer_key") if r.get("issuer_scheme") == "LEI" else None,
            **{c: r[c] for c in COLUMNS if c in r},
        } for n, r in enumerate(mine, start=1)]
        validated = validate(raw, kind=holder.kind, as_of=as_of, today=today)
        result = ingest(
            store, validated, kind=holder.kind, holder_id=holder.holder_id, as_of=as_of, source="api",
            source_ref=f"{base_url}/api/v1/snapshots/{manifest.month}/{dataset}?revision={manifest.revision}",
            principal=None, override_reason=None, run_store=run_store, idmap=idmap,
        )
    except Exception as exc:
        current = store.get_holder(holder.kind, holder.holder_id) or holder
        store.save_holder(current.model_copy(update={"last_pull_at": now_iso(), "last_error": str(exc)[:500]}))
        raise
    current = store.get_holder(holder.kind, holder.holder_id) or holder  # ingest moved as_of forward
    store.save_holder(current.model_copy(update={"last_pull_at": now_iso(), "last_error": None}))
    return result


def pull_due(store, *, settings, client, today: date, run_store, idmap) -> list[dict]:
    as_of = previous_month_end(today)
    out = []
    for h in store.list_holders():
        if h.source != "api" or (h.as_of or "") >= as_of:
            continue
        try:
            r = pull_holder(h, as_of, client=client, base_url=settings.holdings_api_url, store=store,
                            run_store=run_store, idmap=idmap, today=today)
        except Exception as exc:  # one failing holder never stops the others; pull_holder flagged it
            out.append({"holder_id": h.holder_id, "kind": h.kind, "status": "failed", "error": str(exc)[:500]})
            continue
        out.append({"holder_id": h.holder_id, "kind": h.kind, "status": r.status, "revision": r.revision})
    return out
