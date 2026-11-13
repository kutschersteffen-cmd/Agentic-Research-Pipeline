from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from arp.api.deps import settings_dep
from arp.config import Settings
from arp.db.session import require_dsn
from arp.stewardship.intake import IntakeReport, intake_engagements, intake_votes
from arp.stewardship.intake_excel import read_workbook, template

router = APIRouter(prefix="/api/stewardship/intake", tags=["stewardship"])
_REJECTED = {422: {"model": IntakeReport}}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class VotesBody(BaseModel):
    votes: list[dict]


def _reply(report: IntakeReport) -> IntakeReport | JSONResponse:
    # 422 carries the same body as 200, so a client reads one shape
    return JSONResponse(report.model_dump(mode="json"), status_code=422) if report.rejected else report


def _ingest(data: bytes, kind: Literal["engagements", "votes"], settings: Settings) -> IntakeReport | JSONResponse:
    batch, bad = read_workbook(data, kind)
    if bad:  # nothing is written when the workbook itself is wrong
        return _reply(IntakeReport(rejected=bad))
    dsn = require_dsn(settings)
    if kind == "votes":
        return _reply(intake_votes(batch["votes"], dsn, "excel", excel_rows=True))
    return _reply(intake_engagements(batch, dsn, "excel", excel_rows=True))


async def _upload(file: UploadFile, kind: Literal["engagements", "votes"], settings: Settings) -> IntakeReport | JSONResponse:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")
    # openpyxl and the Postgres write (advisory lock wait) are blocking: keep them off the event loop
    return await run_in_threadpool(_ingest, data, kind, settings)


@router.post("/engagements", response_model=IntakeReport, responses=_REJECTED)
def post_engagements(batch: dict[str, list[dict]], settings: Settings = Depends(settings_dep)):
    return _reply(intake_engagements(batch, require_dsn(settings), "api"))


@router.post("/votes", response_model=IntakeReport, responses=_REJECTED)
def post_votes(body: VotesBody, settings: Settings = Depends(settings_dep)):
    return _reply(intake_votes(body.votes, require_dsn(settings), "api"))


@router.post("/engagements.xlsx", response_model=IntakeReport, responses=_REJECTED)
async def post_engagements_xlsx(file: UploadFile, settings: Settings = Depends(settings_dep)):
    return await _upload(file, "engagements", settings)


@router.post("/votes.xlsx", response_model=IntakeReport, responses=_REJECTED)
async def post_votes_xlsx(file: UploadFile, settings: Settings = Depends(settings_dep)):
    return await _upload(file, "votes", settings)


@router.get("/template", response_class=Response, responses={200: {"content": {XLSX: {}}}})
def get_template(kind: Literal["engagements", "votes"]) -> Response:
    return Response(template(kind), media_type=XLSX, headers={"Content-Disposition": f"attachment; filename={kind}_template.xlsx"})
