"""Engagement intake (spec "Intake"): validate a batch of rows keyed by sheet name, then upsert it on
(source, external_id) in one transaction. Nothing is written when any row is rejected."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select

from arp.db.company_view import resolve_ref
from arp.db.session import transaction
from arp.errors import ClientInputError
from arp.schemas.common import new_id, now_iso
from arp.schemas.engagement import (
    ActivityType,
    CorrespondenceType,
    EngagerRole,
    EsgPillar,
    FirTheme,
    InfluenceLevel,
    InteractionType,
    IssueSeverity,
    IssueStatus,
    ObjectiveResult,
    ObjectiveStatus,
    ObjectiveType,
    Receptiveness,
)
from arp.storage.postgres_engagement_store import _LOCK, _ts
from arp.storage.postgres_models import (
    StwActivityModel,
    StwCompanyModel,
    StwEngagementModel,
    StwEventModel,
    StwObjectiveModel,
)
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

ENGAGEMENT_COLUMNS: dict[str, list[str]] = {
    "engagements": [
        "external_id", "company_id", "isin", "company_name", "theme", "fir_theme", "esg_pillars",
        "rationale", "engager_role", "started_at", "status", "severity",
    ],
    "objectives": [
        "external_id", "engagement_external_id", "follows_external_id", "description", "objective_type",
        "status", "result", "receptiveness", "escalated", "started_at", "target_date", "closed_at", "outcome",
        "influence_level", "influence_evidence", "evidence_url",
    ],
    "activities": [
        "external_id", "engagement_external_id", "objective_external_id", "occurred_at", "activity_type",
        "interaction_type", "is_initiation", "summary", "doc_ref", "logged_by",
    ],
}  # fmt: skip
VOTE_COLUMNS: list[str] = [
    "external_id", "company_id", "isin", "cusip", "issuer_name", "meeting_date", "meeting_type", "item_number",
    "description", "categories", "proponent", "management_recommendation", "vote", "shares_voted", "rationale",
    "decided_by", "decided_at", "run_id",
]  # fmt: skip


class Rejection(BaseModel):
    sheet: str
    row: int
    field: str
    reason: str


class IntakeReport(BaseModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: list[Rejection] = Field(default_factory=list)


# sheet -> (model, primary-key column, id prefix, fields that are references or the key, not columns)
_TABLES = {
    "engagements": (StwEngagementModel, "engagement_id", "iss", {"external_id", "company_id", "isin", "company_name"}),
    "objectives": (StwObjectiveModel, "objective_id", "obj", {"external_id", "engagement_external_id", "follows_external_id"}),
    "activities": (StwActivityModel, "activity_id", "corr", {"external_id", "engagement_external_id", "objective_external_id"}),
}
_ENUMS = {
    "engagements": {"fir_theme": FirTheme, "engager_role": EngagerRole, "status": IssueStatus, "severity": IssueSeverity},
    "objectives": {
        "objective_type": ObjectiveType, "status": ObjectiveStatus, "result": ObjectiveResult,
        "receptiveness": Receptiveness, "influence_level": InfluenceLevel,
    },
    "activities": {"activity_type": ActivityType, "interaction_type": InteractionType},
}  # fmt: skip
_REQUIRED = {
    "engagements": ["theme"],
    "objectives": ["engagement_external_id", "description", "objective_type"],
    "activities": ["engagement_external_id"],
}
_TIMES = {"engagements": ["started_at"], "objectives": ["started_at", "closed_at"], "activities": ["occurred_at"]}
_DEFAULTS = {
    "engagements": {"status": "open", "severity": "medium", "engager_role": "bilateral"},
    "objectives": {"status": "initiated"},
    "activities": {},
}
_BOOLS = {"escalated", "is_initiation"}
_TRUE, _FALSE = {"true", "yes", "1"}, {"false", "no", "0"}


def _clean(sheet: str, n: int, raw: dict, bad: list[Rejection]) -> dict:
    """The row with empties as None, enums, timestamps, booleans and pillars checked and normalised."""

    def reject(field: str, reason: str) -> None:
        bad.append(Rejection(sheet=sheet, row=n, field=field, reason=reason))

    row = {}
    for k in ENGAGEMENT_COLUMNS[sheet]:
        v = raw.get(k)
        v = v.strip() if isinstance(v, str) else v
        if k != "esg_pillars" and v is not None and not isinstance(v, str):
            if isinstance(v, (dict, list)):
                reject(k, "not a string")
            v = str(v)
        row[k] = None if v in ("", None) else v
    for k in ["external_id", *_REQUIRED[sheet]]:
        if row[k] is None:
            reject(k, "required")
    for k, enum in _ENUMS[sheet].items():
        if row[k] is not None:
            row[k] = str(row[k])
            if row[k] not in {e.value for e in enum}:
                reject(k, "not one of " + ", ".join(e.value for e in enum))
    for k in _TIMES[sheet]:
        try:
            row[k] = _ts(None if row[k] is None else str(row[k]), k)
        except ClientInputError:
            reject(k, "not an ISO 8601 timestamp")
    for k in _BOOLS & row.keys():
        flag = str(row[k]).lower() if row[k] is not None else "false"
        if flag not in _TRUE | _FALSE:
            reject(k, "not true or false")
        row[k] = flag in _TRUE
    if sheet == "engagements":
        pillars = row["esg_pillars"] or []
        if not isinstance(pillars, (str, list)):
            reject("esg_pillars", "not a list")
            pillars = []
        pillars = [p.strip() for p in pillars.split(";")] if isinstance(pillars, str) else [str(p) for p in pillars]
        if any(p not in {e.value for e in EsgPillar} for p in pillars):
            reject("esg_pillars", "not one of " + ", ".join(e.value for e in EsgPillar))
        row["esg_pillars"] = pillars
    return {**row, **{k: v for k, v in _DEFAULTS[sheet].items() if row.get(k) is None}}


def _company(s, company_id: str | None, isin: str | None) -> str | None:
    """The stewardship company key this row names: `company_id`, else the normalised ISIN, if a stw_companies
    row or the registry knows it."""
    if company_id and _safe(company_id) and (s.get(StwCompanyModel, company_id) or resolve_ref(s, f"UNIVERSE:{company_id}")):
        return company_id
    if isin:
        isin = "".join(isin.split()).upper()
        key = f"isin_{isin}"
        if _safe(key) and (s.get(StwCompanyModel, key) or resolve_ref(s, f"ISIN:{isin}")):
            return key
    return None


def _safe(key: str) -> bool:
    try:
        safe_id(key, label="company_id")
    except UnsafeIdentifierError:
        return False
    return True


def intake_engagements(batch: dict[str, list[dict]], dsn: str, source: str) -> IntakeReport:
    report = IntakeReport()
    bad = report.rejected
    with transaction(dsn) as s:
        rows = {sheet: [_clean(sheet, n, r, bad) for n, r in enumerate(batch.get(sheet) or [], 1)] for sheet in _TABLES}
        # Resolve and lock the companies first: ids and company_of are read after the locks, so a batch that
        # waited on a concurrent one sees the rows it wrote and upserts instead of inserting a duplicate.
        resolved = [_company(s, r["company_id"], r["isin"]) for r in rows["engagements"]]
        wanted = {r["external_id"] for r in rows["engagements"]} | {
            r["engagement_external_id"] for sheet in ("objectives", "activities") for r in rows[sheet]
        }
        stored_companies = s.scalars(
            select(StwEngagementModel.company_id).where(StwEngagementModel.source == source, StwEngagementModel.external_id.in_(wanted - {None}))
        )
        for company in sorted({c for c in resolved if c} | set(stored_companies)):  # as PostgresEngagementStore.lock takes it
            s.execute(_LOCK, {"id": company})
        ids = {}  # sheet -> external_id -> primary key, stored rows of this source plus this batch's new ones
        for sheet, (model, pk, prefix, _) in _TABLES.items():
            ids[sheet] = {e: i for e, i in s.execute(select(model.external_id, getattr(model, pk)).where(model.source == source, model.external_id.is_not(None)))}
            seen = set()
            for n, row in enumerate(rows[sheet], 1):
                ext = row["external_id"]
                if ext is not None and ext in seen:
                    bad.append(Rejection(sheet=sheet, row=n, field="external_id", reason="duplicate in batch"))
                seen.add(ext)
                if ext is not None:
                    ids[sheet].setdefault(ext, new_id(prefix))
        company_of = dict(s.execute(select(StwEngagementModel.engagement_id, StwEngagementModel.company_id)).all())
        names = {}  # company key -> name for a stw_companies row that has to be created
        plan = []  # (sheet, row number, external_id, values)

        def ref(sheet: str, n: int, row: dict, field: str, target: str) -> str | None:
            if row[field] is None:
                return None
            if row[field] not in ids[target]:
                bad.append(Rejection(sheet=sheet, row=n, field=field, reason=f"unknown {field}"))
            return ids[target].get(row[field])

        for n, (row, company) in enumerate(zip(rows["engagements"], resolved, strict=True), 1):
            if company is None:
                bad.append(Rejection(sheet="engagements", row=n, field="company_id", reason="unknown company"))
                continue
            names.setdefault(company, row["company_name"] or company)
            if row["external_id"]:
                company_of[ids["engagements"][row["external_id"]]] = company
                plan.append(("engagements", n, row, {"company_id": company}))
        for sheet, links in (("objectives", {"engagement_external_id": ("engagement_id", "engagements"), "follows_external_id": ("follows_objective_id", "objectives")}),
                             ("activities", {"engagement_external_id": ("engagement_id", "engagements"), "objective_external_id": ("objective_id", "objectives")})):  # fmt: skip
            for n, row in enumerate(rows[sheet], 1):
                if row["external_id"]:
                    plan.append((sheet, n, row, {col: ref(sheet, n, row, f, t) for f, (col, t) in links.items()}))
        # an objective is written after the one it follows (a self-referencing foreign key)
        in_batch = {ids["objectives"][p[2]["external_id"]] for p in plan if p[0] == "objectives"}
        first, objectives, last, placed = [p for p in plan if p[0] == "engagements"], [p for p in plan if p[0] == "objectives"], [p for p in plan if p[0] == "activities"], set()
        ordered = []
        while objectives:
            ready = [p for p in objectives if p[3]["follows_objective_id"] not in in_batch or p[3]["follows_objective_id"] in placed]
            if not ready:
                bad.extend(Rejection(sheet="objectives", row=p[1], field="follows_external_id", reason="circular") for p in objectives)
                break
            ordered += ready
            placed |= {ids["objectives"][p[2]["external_id"]] for p in ready}
            objectives = [p for p in objectives if p not in ready]
        if bad:
            return report

        touched = set()

        def log(company: str, table: str, key: str, changed: list[str]) -> None:
            detail = {"table": table, "key": key, "changed": changed}
            s.add(StwEventModel(source=source, company_id=company, event_type="intake_upserted", detail=detail, at=_ts(now_iso())))
            touched.add(company)

        for company, name in names.items():
            if s.get(StwCompanyModel, company) is None:
                s.add(StwCompanyModel(company_id=company, source=source, name=name, created_at=_ts(now_iso()), updated_at=_ts(now_iso())))
                report.created += 1
                log(company, "stw_companies", company, ["name"])
        s.flush()

        for sheet, _, row, extra in first + ordered + last:
            model, pk, _, skip = _TABLES[sheet]
            values = {k: v for k, v in row.items() if k not in skip} | extra
            if sheet == "activities":  # `type` is today's CorrespondenceType, which has no agm_intervention
                values["type"] = values["activity_type"] if values["activity_type"] in {e.value for e in CorrespondenceType} else "other"
            ext = row["external_id"]
            stored = s.get(model, ids[sheet][ext])
            if stored is None:
                extras = {"tags": [row["theme"]], "trigger_source": "manual", "milestone_stage": "identified", "escalation_stage": "private_engagement"} if sheet == "engagements" else {}
                s.add(model(**{pk: ids[sheet][ext], "source": source, "external_id": ext, **extras, **values}))
                report.created += 1
                changed = sorted(values)
            else:
                changed = sorted(k for k, v in values.items() if getattr(stored, k) != v)
                if not changed:
                    report.unchanged += 1
                    continue
                for k in changed:
                    setattr(stored, k, values[k])
                report.updated += 1
            company = values["company_id"] if sheet == "engagements" else company_of[values["engagement_id"]]
            log(company, model.__tablename__, ext, changed)
            if stored is None:
                s.flush()
        now = _ts(now_iso())
        for company in touched:
            s.get(StwCompanyModel, company).updated_at = now
    return report
