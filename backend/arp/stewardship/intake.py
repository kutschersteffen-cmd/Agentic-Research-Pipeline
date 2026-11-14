"""Engagement intake (spec "Intake"): validate a batch of rows keyed by sheet name, then upsert it on
(source, external_id) in one transaction. Nothing is written when any row is rejected."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select, text

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
from arp.schemas.vote_ledger import VoteValue, against_management
from arp.storage.postgres_engagement_store import _LOCK, _ts
from arp.storage.postgres_models import (
    StwActivityModel,
    StwCompanyModel,
    StwEngagementModel,
    StwEventModel,
    StwObjectiveModel,
    VoteDecisionModel,
    VoteItemModel,
    VoteMeetingModel,
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
    "engagements": {"status": "open", "severity": "medium"},
    "objectives": {"status": "initiated"},
    "activities": {},
}
_BOOLS = {"escalated", "is_initiation"}
_TRUE, _FALSE = {"true", "yes", "1"}, {"false", "no", "0"}


def _cell(v, k: str, reject, keep_raw: bool = False):
    """A cell as stripped text, empty as None; a dict or list is rejected unless `keep_raw` (the caller parses it)."""
    v = v.strip() if isinstance(v, str) else v
    if not keep_raw and v is not None and not isinstance(v, str):
        if isinstance(v, (dict, list)):
            reject(k, "not a string")
        v = str(v)
    return None if v in ("", None) else v


def _clean(sheet: str, n: int, raw: dict, bad: list[Rejection]) -> dict:
    """The row with empties as None, enums, timestamps, booleans and pillars checked and normalised."""

    def reject(field: str, reason: str) -> None:
        bad.append(Rejection(sheet=sheet, row=n, field=field, reason=reason))

    row = {k: _cell(raw.get(k), k, reject, keep_raw=k == "esg_pillars") for k in ENGAGEMENT_COLUMNS[sheet]}
    for k in raw.keys() - set(ENGAGEMENT_COLUMNS[sheet]) - {"_row"}:
        reject(k, f"unknown column {k}")
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


def intake_engagements(batch: dict[str, list[dict]], dsn: str, source: str, excel_rows: bool = False) -> IntakeReport:
    """`excel_rows`: rows carry `_row` (set by read_workbook); never true for JSON, whose rows are numbered by index."""
    report = IntakeReport()
    bad = report.rejected
    bad.extend(Rejection(sheet=k, row=0, field="", reason="unknown sheet") for k in batch.keys() - _TABLES.keys())
    if bad:
        return report
    with transaction(dsn) as s:
        num = {sheet: [r["_row"] if excel_rows else i for i, r in enumerate(batch.get(sheet) or [], 1)] for sheet in _TABLES}
        rows = {sheet: [_clean(sheet, n, r, bad) for n, r in zip(num[sheet], batch.get(sheet) or [], strict=True)] for sheet in _TABLES}
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
            for n, row in zip(num[sheet], rows[sheet], strict=True):
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

        for n, row, company in zip(num["engagements"], rows["engagements"], resolved, strict=True):
            if company is None:
                bad.append(Rejection(sheet="engagements", row=n, field="company_id", reason="unknown company"))
                continue
            names.setdefault(company, row["company_name"] or company)
            if row["external_id"]:
                company_of[ids["engagements"][row["external_id"]]] = company
                plan.append(("engagements", n, row, {"company_id": company}))
        for sheet, links in (("objectives", {"engagement_external_id": ("engagement_id", "engagements"), "follows_external_id": ("follows_objective_id", "objectives")}),
                             ("activities", {"engagement_external_id": ("engagement_id", "engagements"), "objective_external_id": ("objective_id", "objectives")})):  # fmt: skip
            for n, row in zip(num[sheet], rows[sheet], strict=True):
                if row["external_id"]:
                    plan.append((sheet, n, row, {col: ref(sheet, n, row, f, t) for f, (col, t) in links.items()}))
        obj_engagement = dict(s.execute(select(StwObjectiveModel.objective_id, StwObjectiveModel.engagement_id)).all())
        obj_engagement.update({ids["objectives"][p[2]["external_id"]]: p[3]["engagement_id"] for p in plan if p[0] == "objectives"})
        for p in plan:
            v = p[3]
            if p[0] == "activities" and v["objective_id"] and v["engagement_id"] and obj_engagement.get(v["objective_id"]) != v["engagement_id"]:
                bad.append(Rejection(sheet="activities", row=p[1], field="objective_external_id", reason="objective belongs to another engagement"))
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


_VOTE_LOCK = text("select pg_advisory_xact_lock(hashtext('vote_intake'))")  # one vote intake at a time
_MEETING = ["issuer_name", "isin", "cusip", "meeting_type"]
_KEEP = {"company_id", "isin", "cusip"}
_ITEM = ["description", "categories", "proponent", "management_recommendation"]
_DECISION = ["vote", "vote_label", "against_management", "shares_voted", "rationale", "decided_by", "decided_at", "run_id"]


def meeting_key(company_id: str | None, isin: str | None, cusip: str | None) -> str:
    """The company part of a vote meeting's key: the row's own ids, one namespace per source. A company keyed
    `isin_<ISIN>` shares the `isin:` namespace with ISIN-only rows, so both reach one meeting."""
    if company_id and company_id.startswith("isin_"):
        return f"isin:{company_id[5:]}"
    return next(f"{ns}:{v}" for ns, v in (("cid", company_id), ("isin", isin), ("cusip", cusip)) if v)


def _clean_vote(n: int, raw: dict, source: str, bad: list[Rejection]) -> dict:
    def reject(field: str, reason: str) -> None:
        bad.append(Rejection(sheet="votes", row=n, field=field, reason=reason))

    row = {k: _cell(raw.get(k), k, reject, keep_raw=k == "categories") for k in VOTE_COLUMNS}
    for k in raw.keys() - set(VOTE_COLUMNS) - {"_row"}:
        reject(k, f"unknown column {k}")
    for k in ("external_id", "meeting_date", "item_number", "vote"):  # the decision, meeting and item keys
        if row[k] is None:
            reject(k, "required")
    if not (row["company_id"] or row["isin"] or row["cusip"]):
        reject("company_id", "one of company_id, isin, cusip required")
    options = ", ".join(e.value for e in VoteValue)
    for k in ("vote", "management_recommendation"):
        if row[k] is not None and row[k] not in {e.value for e in VoteValue}:
            reject(k, "not one of " + options)
    if row["proponent"] not in (None, "issuer", "shareholder"):
        reject("proponent", "not one of issuer, shareholder")
    for k in ("meeting_date", "decided_at"):
        try:
            row[k] = _ts(row[k], k)
        except ClientInputError:
            reject(k, "not an ISO 8601 timestamp")
    try:
        row["shares_voted"] = None if row["shares_voted"] is None else float(row["shares_voted"])
    except (TypeError, ValueError):
        reject("shares_voted", "not a number")
    cats = row["categories"] or []
    if not isinstance(cats, (str, list)):
        reject("categories", "not a list")
        cats = []
    row["categories"] = [c.strip() for c in cats.split(";") if c.strip()] if isinstance(cats, str) else [str(c) for c in cats]
    row["isin"] = "".join(row["isin"].split()).upper() if row["isin"] else None
    row["cusip"] = row["cusip"].upper() if row["cusip"] else None
    if row["cusip"] and row["cusip"].isdigit() and len(row["cusip"]) < 9:  # Excel drops leading zeros
        row["cusip"] = row["cusip"].zfill(9)
    row["vote_label"] = row["vote"]
    row["against_management"] = None
    if row["vote"] in {e.value for e in VoteValue}:
        row["against_management"] = against_management(VoteValue(row["vote"]), row["management_recommendation"])
        if row["against_management"] and not row["rationale"] and source != "npx_urth_demo":
            reject("rationale", "rationale required when voting against management")
    return row


def intake_votes(rows: list[dict], dsn: str, source: str, excel_rows: bool = False) -> IntakeReport:
    """Upsert vote rows into meeting, item and decision on (source, external_id). A company matches only if its
    stw_companies row exists, else `company_id` stays null. No events are written for votes."""
    report = IntakeReport()
    bad = report.rejected
    with transaction(dsn) as s:
        clean = [_clean_vote(r["_row"] if excel_rows else i, r, source, bad) for i, r in enumerate(rows, 1)]
        nums = [r["_row"] if excel_rows else i for i, r in enumerate(rows, 1)]
        plan = []  # (meeting ext, meeting values, item ext, item values, decision ext, decision values)
        seen = set()
        for n, row in zip(nums, clean, strict=True):
            company = None
            for key in (row["company_id"], row["isin"] and f"isin_{row['isin']}"):
                if key and _safe(key) and s.get(StwCompanyModel, key):
                    company = key
                    break
            if row["company_id"] and not (row["isin"] or row["cusip"]) and not _company(s, row["company_id"], None):
                # only identifier is a company_id neither stw_companies nor the registry knows (owner decision 14 Nov)
                bad.append(Rejection(sheet="votes", row=n, field="company_id", reason="unknown company"))
            if any(r.row == n for r in bad):  # keys are only built for rows that passed validation
                continue
            key = meeting_key(row["company_id"], row["isin"], row["cusip"])
            if row["external_id"] in seen:
                bad.append(Rejection(sheet="votes", row=n, field="external_id", reason="duplicate in batch"))
            seen.add(row["external_id"])
            meeting = f"{key}:{row['meeting_date'].date().isoformat()}"
            plan.append((
                meeting, {"company_id": company, "meeting_date": row["meeting_date"], **{k: row[k] for k in _MEETING}},
                f"{meeting}:{row['item_number']}", {"item_number": row["item_number"], **{k: row[k] for k in _ITEM}},
                row["external_id"], {k: row[k] for k in _DECISION},
            ))  # fmt: skip
        if bad:
            return report
        s.execute(_VOTE_LOCK)
        tables = {"meeting": (VoteMeetingModel, "meeting_id", "mtg"), "item": (VoteItemModel, "item_id", "vitem"), "decision": (VoteDecisionModel, "decision_id", "vote")}
        ids = {k: {e: i for e, i in s.execute(select(m.external_id, getattr(m, pk)).where(m.source == source, m.external_id.is_not(None)))} for k, (m, pk, _) in tables.items()}  # fmt: skip

        def upsert(kind: str, ext: str, values: dict) -> None:
            model, pk, prefix = tables[kind]
            stored = s.get(model, ids[kind][ext]) if ext in ids[kind] else None
            if stored is None:
                ids[kind][ext] = new_id(prefix)
                s.add(model(**{pk: ids[kind][ext], "source": source, "external_id": ext, **values}))
                s.flush()
                report.created += 1
                return
            # an upsert fills a meeting's company ids but never clears them
            changed = [k for k, v in values.items() if getattr(stored, k) != v and not (v is None and k in _KEEP)]
            for k in changed:
                setattr(stored, k, values[k])
            report.updated += bool(changed)
            report.unchanged += not changed

        done = set()
        for m_ext, m_vals, i_ext, i_vals, d_ext, d_vals in plan:
            if m_ext not in done:  # a meeting or item shared by several rows counts once, from its first row
                done.add(m_ext)
                upsert("meeting", m_ext, m_vals)
            if i_ext not in done:
                done.add(i_ext)
                upsert("item", i_ext, {**i_vals, "meeting_id": ids["meeting"][m_ext]})
            upsert("decision", d_ext, {**d_vals, "item_id": ids["item"][i_ext]})
    return report
