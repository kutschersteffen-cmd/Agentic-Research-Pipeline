"""Pure: one run result row -> the observations it carries (spec §2.5). Per run type:
extraction (one per ExtractedField), financials (capex_total, rnd_total), theme
(`theme:<activity_id>`), proxy_voting (`vote:<meeting_id>:<proposal_number>`); anything else none."""

from __future__ import annotations

import logging
import re
from datetime import date
from uuid import UUID

from arp.db.models import CitationRole, Route, SourceKind, ValueState
from arp.db.observations import CitationIn, ObservationIn
from arp.schemas.common import Citation
from arp.schemas.datapoints import ExtractionRecord
from arp.schemas.financials import CompanyFinancialsRecord

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _segment(raw) -> str:
    """An id segment the fields CHECK accepts (no colon, no whitespace)."""
    safe = _UNSAFE.sub("_", str(raw)) or "_"
    if safe != str(raw):
        logger.warning("field id segment %r sanitised to %r", raw, safe)
    return safe


def theme_field_id(activity_id) -> str:
    return f"theme:{_segment(activity_id)}"


def vote_field_id(meeting_id, proposal_number) -> str:
    return f"vote:{_segment(meeting_id)}:{_segment(proposal_number)}"


def review_target(payload: dict) -> tuple[str, str | None] | None:
    """(field_id, ISO period_end) of the observation a review payload is about, if any."""
    if payload.get("field_id"):
        return payload["field_id"], payload.get("period_end")
    if payload.get("activity_id"):
        return theme_field_id(payload["activity_id"]), None
    proposal = payload.get("proposal")
    if isinstance(proposal, dict) and proposal.get("meeting_id") and proposal.get("proposal_number"):
        return vote_field_id(proposal["meeting_id"], proposal["proposal_number"]), None
    return None


def _citation(c: Citation | dict, role: CitationRole) -> CitationIn:
    c = Citation.model_validate(c) if isinstance(c, dict) else c
    return CitationIn(
        doc_id=c.doc_id, role=role, content_key=c.content_key, page=c.page, sheet=c.sheet, location=c.location,
        quote=c.quote, span_text=c.span_text, char_start=c.char_start, char_end=c.char_end,
        table_ref=c.table_ref.model_dump(mode="json") if c.table_ref else None, passage_id=c.passage_id,
        grounded=c.grounded, match_method=c.match_method, match_score=c.match_score,
    )


def _cited(citations) -> list[CitationIn]:
    return [_citation(c, CitationRole.PRIMARY if i == 0 else CitationRole.CORROBORATING) for i, c in enumerate(citations or [])]


def _date(raw: str | None) -> date | None:
    return date.fromisoformat(raw) if raw else None


def _state(value) -> ValueState:
    if value is None:
        return ValueState.NOT_FOUND
    return ValueState.ZERO if not isinstance(value, bool) and value == 0 else ValueState.FOUND


def _extraction(company_id: UUID, run_id: str, result: dict, trial: bool, errors: list[dict]) -> list[ObservationIn]:
    rec = ExtractionRecord.model_validate(result)
    all_held = bool(rec.held_documents) and not rec.documents
    out = []
    for f in rec.fields:
        try:
            period_end = _date(f.period_end)
        except ValueError:
            errors.append({"kind": "invalid_value", "field_id": f.field_id, "raw": f.period_end})
            continue
        try:
            period_start = _date(f.period_start)
        except ValueError:
            errors.append({"kind": "invalid_value", "field_id": f.field_id, "raw": f.period_start})
            continue
        route = f.route or ("review" if f.review_reasons else None)  # route None: a row from before routing
        out.append(ObservationIn(
            company_id=company_id, field_id=f.field_id,
            field_version=(f.provenance.field_version if f.provenance and f.provenance.field_version else 1),
            source_kind=SourceKind.XBRL if f.method == "tagged" else SourceKind.EXTRACTION,
            period_end=period_end, period_start=period_start, basis=f.basis or "", value=f.value,
            value_state=ValueState(f.value_state.value), unit=f.unit, canonical_value=f.canonical_value,
            canonical_unit=f.canonical_unit, scale_applied=f.scale_applied, fx_rate=f.fx_rate, confidence=f.confidence,
            checks=[c.model_dump(mode="json") for c in f.checks], route=Route(route) if route else None, method=f.method,
            run_id=run_id, conflicting_sources=f.conflicting_sources, trial=trial,
            held=all_held or f.route == "hold",
            citations=_cited(f.citations) + [_citation(c, CitationRole.ALTERNATIVE) for a in f.alternatives for c in a.citations],
        ))
    return out


def _financials(company_id: UUID, run_id: str, result: dict, trial: bool) -> list[ObservationIn]:
    rec = CompanyFinancialsRecord.model_validate(result)
    try:
        period_end = _date(rec.fiscal_period)
    except ValueError:  # free text ("FY2024"), not an ISO date
        period_end = None
    return [
        ObservationIn(
            company_id=company_id, field_id=field_id, field_version=1, source_kind=SourceKind.EXTRACTION,
            period_end=period_end, value=s.total.value, value_state=_state(s.total.value), unit=rec.currency,
            confidence=s.confidence, route=Route.REVIEW if rec.needs_review else Route.AUTO_ACCEPT, run_id=run_id,
            conflicting_sources=s.conflicting_sources, trial=trial,
            citations=_cited(s.total.citations),
        )
        for field_id, s in (("capex_total", rec.capex), ("rnd_total", rec.rnd))
    ]


def _theme(company_id: UUID, run_id: str, result: dict, trial: bool) -> list[ObservationIn]:
    return [
        ObservationIn(
            company_id=company_id, field_id=theme_field_id(m["activity_id"]), field_version=1,
            source_kind=SourceKind.EXTRACTION, period_end=None,
            value={"verdict": m.get("verdict"), "exposure_estimate": m.get("exposure_estimate")},
            value_state=ValueState.FOUND, confidence=m.get("confidence"),
            route=Route.REVIEW if m.get("flagged_for_review") else Route.AUTO_ACCEPT, run_id=run_id, trial=trial,
            citations=_cited(m.get("citations")),
        )
        for m in result.get("company_matches") or []
        if m.get("activity_id")
    ]


def _voting(company_id: UUID, run_id: str, result: dict, trial: bool) -> list[ObservationIn]:
    out = []
    for v in result.get("votes") or []:
        p = v.get("proposal") or {}
        if not (p.get("meeting_id") and p.get("proposal_number")):
            continue
        rec = v.get("policy_recommendation") or {}
        value = (v.get("human_decision") or rec).get("vote")
        out.append(ObservationIn(
            company_id=company_id, field_id=vote_field_id(p["meeting_id"], p["proposal_number"]), field_version=1,
            source_kind=SourceKind.EXTRACTION, period_end=None, value=value, value_state=_state(value),
            confidence=rec.get("confidence"), route=Route.REVIEW, run_id=run_id, trial=trial,  # every vote is queued
            citations=_cited(p.get("citations")),
        ))
    return out


def to_observations(
    run_type: str, company_id: UUID, run_id: str, result: dict, *, trial: bool, errors: list[dict] | None = None
) -> list[ObservationIn]:
    """`errors` collects `{"kind": "invalid_value", "field_id", "raw"}` for values left out."""
    if run_type == "extraction":
        return _extraction(company_id, run_id, result, trial, errors if errors is not None else [])
    if run_type == "financials":
        return _financials(company_id, run_id, result, trial)
    if run_type == "theme":
        return _theme(company_id, run_id, result, trial)
    if run_type == "proxy_voting":
        return _voting(company_id, run_id, result, trial)
    return []
