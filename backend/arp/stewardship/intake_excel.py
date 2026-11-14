"""Excel side of intake: read an uploaded workbook into the batch `intake_engagements` takes, and build the
empty template workbooks (spec "Intake")."""

from __future__ import annotations

import io
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from openpyxl import Workbook, load_workbook

from arp.schemas import engagement as e
from arp.schemas.vote_ledger import VoteValue
from arp.stewardship.intake import ENGAGEMENT_COLUMNS, VOTE_COLUMNS, Rejection

_LISTS: dict[str, type[StrEnum]] = {
    "fir_theme": e.FirTheme, "esg_pillar": e.EsgPillar, "engager_role": e.EngagerRole, "issue_status": e.IssueStatus,
    "severity": e.IssueSeverity, "objective_type": e.ObjectiveType, "objective_status": e.ObjectiveStatus,
    "result": e.ObjectiveResult, "receptiveness": e.Receptiveness, "influence_level": e.InfluenceLevel,
    "activity_type": e.ActivityType, "interaction_type": e.InteractionType,
}  # fmt: skip
_LABELS = {  # value -> label, from the spec's "VOICE option lists"; lists without labels get no label column
    "fir_theme": {m.value: t for m, t in e.FIR_THEME_LABELS.items()},
    "engager_role": {"lead": "Lead, Co-Lead or equivalent", "passive_support": "Passive support, Signatory"},
    "receptiveness": {"refusal": "Refusal/Blockage"},
    "influence_level": {
        "1": "No influence", "2": "Not demonstrable", "3": "Probable", "4A": "Very likely, converging clues",
        "4B": "Very likely, convergent loop", "5": "Recognised",
    },
}  # fmt: skip
_SPLIT = {"esg_pillars", "categories"}


def _columns(kind: str) -> dict[str, list[str]]:
    return ENGAGEMENT_COLUMNS if kind == "engagements" else {"votes": VOTE_COLUMNS}


def _cell(header: str, v):
    if isinstance(v, datetime):  # midnight is a date typed into Excel; keeps date-only text columns equal
        v = v.date() if v.time() == datetime.min.time() else v
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():  # Excel stores 12345 as 12345.0
        v = int(v)
    if isinstance(v, int) and not isinstance(v, bool):  # ids and numbers are text columns
        return str(v)
    if isinstance(v, str):
        v = v.strip()
    if v in ("", None):
        return None
    if header in _SPLIT and isinstance(v, str):
        return [p.strip() for p in v.split(";") if p.strip()]
    return v


def read_workbook(data: bytes, kind: Literal["engagements", "votes"]) -> tuple[dict[str, list[dict]], list[Rejection]]:
    """Batch keyed by sheet name; each row carries `_row`, its worksheet row (header = 1). Rejections for
    missing sheets and unknown headers; the rest of the validation is `intake_engagements`'."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # openpyxl raises a different error for each kind of bad file
        return {}, [Rejection(sheet="", row=0, field="", reason="not a valid xlsx workbook")]
    batch: dict[str, list[dict]] = {}
    bad: list[Rejection] = []
    for sheet, columns in _columns(kind).items():
        if sheet not in wb.sheetnames:
            bad.append(Rejection(sheet=sheet, row=0, field="", reason="missing sheet"))
            continue
        rows = wb[sheet].iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else None for h in next(rows, ())]
        if not any(headers):
            bad.append(Rejection(sheet=sheet, row=1, field="", reason="missing header"))
            continue
        bad += [Rejection(sheet=sheet, row=1, field=h, reason=f"unknown column {h}") for h in headers if h and h not in columns]
        batch[sheet] = []
        for n, values in enumerate(rows, 2):
            row = {h: _cell(h, v) for h, v in zip(headers, values, strict=False) if h in columns}
            if any(v is not None for v in row.values()):
                batch[sheet].append({**row, "_row": n})
    return batch, bad


def template(kind: Literal["engagements", "votes"]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet, columns in _columns(kind).items():
        wb.create_sheet(sheet).append(columns)
    lists = wb.create_sheet("lists")
    options = {"vote": [v.value for v in VoteValue]} if kind == "votes" else {k: [m.value for m in v] for k, v in _LISTS.items()}
    col = 1
    for name, values in options.items():
        lists.cell(1, col, name)
        for i, v in enumerate(values, 2):
            lists.cell(i, col, v)
        col += 1
        if name in _LABELS:  # the label sits beside the value; blank where the spec gives none
            lists.cell(1, col, f"{name}_label")
            for i, v in enumerate(values, 2):
                lists.cell(i, col, _LABELS[name].get(v))
            col += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
