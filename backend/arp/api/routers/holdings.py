"""Holdings intake (E77): file upload, template download, holder status and the API pull."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import get_identifier_map, get_portfolio_store, settings_dep
from arp.config import Settings
from arp.holdings.api_source import pull_holder
from arp.holdings.file_source import file_ref, load_mapping, read_rows, template
from arp.holdings.intake import IntakeError, holder_status, ingest, previous_month_end
from arp.holdings.validate import validate
from arp.schemas.common import now_iso
from arp.schemas.portfolio import HolderConfig
from arp.snapshots.client import SnapshotClient, SnapshotHashMismatch, SnapshotInvalid
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.safe_path import safe_id

router = APIRouter(prefix="/api/holdings", tags=["holdings"])
Kind = Literal["index", "portfolio"]
MEDIA = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def _intake_error(e: IntakeError, headers: dict[str, str] | None = None) -> HTTPException:
    """`headers` (a provider mapping's columns) names a missing column as the file should have it ("Weight (%)")."""
    errors = [
        replace(x, column=headers.get(x.column, x.column)) if headers and x.row is None and x.message == "missing required column" else x
        for x in e.errors
    ]
    return HTTPException(e.status, {"message": e.message, "errors": [asdict(x) for x in errors]})


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    holder_id: str = Form(...),
    kind: Kind = Form(...),
    as_of: str = Form(...),
    provider: str = Form("default"),
    decimal: Literal[".", ","] | None = Form(None, description="Overrides the provider mapping's decimal separator."),
    weight_unit: Literal["percent", "fraction"] | None = Form(None, description="Overrides the provider mapping's weight unit."),
    override_reason: str | None = Form(None),
    user: Principal = Depends(current_user),
    settings: Settings = Depends(settings_dep),
    store=Depends(get_portfolio_store),
    idmap: IdentifierMapStore = Depends(get_identifier_map),
) -> dict:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")

    headers: dict[str, str] = {}

    def intake():
        mapping = load_mapping(provider)
        headers.update(mapping.columns)
        raw = read_rows(data, file.filename or "", mapping)
        validated = validate(raw, kind=kind, as_of=as_of, decimal=decimal or mapping.decimal,
                             weight_unit=weight_unit or mapping.weight_unit)
        return ingest(
            store, validated, kind=kind, holder_id=holder_id, as_of=as_of, source="file", source_ref=file_ref(data),
            principal=user, override_reason=override_reason, idmap=idmap,
        )

    try:
        result = await run_in_threadpool(intake)
    except IntakeError as e:
        raise _intake_error(e, headers) from None
    except FileExistsError:
        raise HTTPException(409, "another write took this revision first; retry") from None
    except ValueError as e:  # unreadable file, unknown provider, non-canonical as_of
        raise HTTPException(422, {"message": str(e), "errors": []}) from None
    return asdict(result)


@router.get("/template")
def download_template(kind: Kind = "portfolio", fmt: Literal["csv", "xlsx"] = Query("csv", alias="format")) -> Response:
    return Response(template(kind, fmt), media_type=MEDIA[fmt],
                    headers={"Content-Disposition": f'attachment; filename="holdings-template-{kind}.{fmt}"'})


@router.get("/holders")
def holders(store=Depends(get_portfolio_store)) -> dict:
    """Holder records, plus every portfolio that has none (seeded or imported data): listed read-only, nothing stored."""
    today = date.today()
    rows = holder_status(store, today)
    configured = {r["holder_id"] for r in rows if r["kind"] == "portfolio"}
    expected = previous_month_end(today)
    for p in store.list_portfolios():
        if p.portfolio_id not in configured:
            as_of = store.latest_snapshot_date(p.portfolio_id)
            rows.append({
                "holder_id": p.portfolio_id, "kind": "portfolio", "name": p.name, "source": None, "as_of": as_of,
                "last_pull_at": None, "last_error": None, "expected_as_of": expected,
                "stale": as_of is None or as_of < expected,
                "age_days": (today - date.fromisoformat(as_of)).days if as_of else None,
            })
    return {"holders": rows}


class HolderUpdate(BaseModel):
    name: str = ""
    source: Literal["api", "file"]


@router.put("/holders/{kind}/{holder_id}")
def put_holder(
    kind: Kind,
    holder_id: str,
    req: HolderUpdate,
    user: Principal = Depends(require_role("approver")),
    store=Depends(get_portfolio_store),
) -> HolderConfig:
    safe_id(holder_id, label="holder_id")
    old = store.get_holder(kind, holder_id) or HolderConfig(holder_id=holder_id, kind=kind)
    new = old.model_copy(update={"name": req.name or old.name, "source": req.source})
    store.save_holder(new)
    store.append_holdings_audit({
        "at": now_iso(), "kind": kind, "holder_id": holder_id, "action": "configure", "user_id": user.user_id,
        "role": user.role, "old_source": old.source, "new_source": new.source,
    })
    return new


@router.post("/holders/{kind}/{holder_id}/pull")
def pull(
    kind: Kind,
    holder_id: str,
    as_of: str | None = None,
    settings: Settings = Depends(settings_dep),
    store=Depends(get_portfolio_store),
    idmap: IdentifierMapStore = Depends(get_identifier_map),
) -> dict:
    if not settings.holdings_api_url:
        raise HTTPException(503, "holdings_api_url is not set")
    holder = store.get_holder(kind, holder_id)
    if holder is None:
        raise HTTPException(404, f"unknown holder {kind}/{holder_id}")
    client = SnapshotClient(settings.holdings_api_url, settings.holdings_api_token)
    try:
        result = pull_holder(holder, as_of or previous_month_end(date.today()), client=client,
                             base_url=settings.holdings_api_url, store=store, idmap=idmap)
    except IntakeError as e:
        raise _intake_error(e) from None
    except FileExistsError:
        raise HTTPException(409, "another write took this revision first; retry") from None
    except httpx.HTTPError as e:
        raise HTTPException(502, f"upstream pull failed: {type(e).__name__}") from None
    except (SnapshotHashMismatch, SnapshotInvalid) as e:
        raise HTTPException(502, f"upstream pull failed: {e}") from None
    except ValueError as e:
        raise HTTPException(422, {"message": str(e), "errors": []}) from None
    finally:
        client.close()
    return asdict(result)
