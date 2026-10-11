"""What a run may publish: the publication rules plus restatement selection (E73)."""

from __future__ import annotations

from dataclasses import dataclass

from arp.orchestration.review_queue import effective_decisions, item_states, latest_decisions
from arp.publish.facts import FactCandidate
from arp.schemas.common import Citation
from arp.schemas.review import field_item_key, period_key

_STATE = {"approve": "approved", "correct": "edited", "edit": "edited"}


def merge_correction(f: dict, decision: dict) -> dict:
    """One field with an `edit`/`correct` decision's edited keys merged over it."""
    edit = decision.get("edited_value") or {}
    merged = {**f, **edit, "field_id": f["field_id"]}
    if decision.get("decision") == "correct" and decision.get("correction_citation"):
        merged["citations"] = [decision["correction_citation"]]  # the correction's own grounded source
        merged["grounded"] = True
    if edit.get("value") is not None and "value_state" not in edit:  # a supplied value is no longer not_found
        merged["value_state"] = "zero" if _is_zero(edit["value"]) else "found"
    if "value" in edit:  # never leave the old conversion beside an edited value
        if not ({"canonical_value", "canonical_unit"} & edit.keys()):
            merged["canonical_value"] = merged["canonical_unit"] = None
        for k in ("fx_rate", "fx_rate_ref", "scale_applied"):
            if k not in edit:
                merged[k] = None
    return merged


def _is_zero(v) -> bool:
    """Zero iff not a bool and float(v) == 0 ("0" is zero, False is not); frontend withEditedValue matches."""
    if isinstance(v, bool):
        return False
    try:
        return float(v) == 0
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Skip:
    item_key: str
    reason: str


def _grounded(f: dict) -> Citation | None:
    c = next((c for c in f.get("citations") or [] if c.get("grounded") and c.get("content_key")), None)
    return Citation(**c) if c else None


def _correction(d: dict) -> Citation | None:
    # never the field's own citation: it supports the old value (pre-flight F4)
    c = d.get("correction_citation") if d.get("decision") == "correct" else None
    return Citation(**c) if c else None


def run_candidates(run_store, run_id: str) -> tuple[list[FactCandidate], list[Skip]]:
    manifest = run_store.load_manifest(run_id)
    if manifest is None or manifest.run_type != "extraction":
        return [], []
    if manifest.params.get("trial"):
        return [], [Skip("*", "trial_run")]
    decisions = effective_decisions(run_store, run_id)
    in_review = set(latest_decisions(run_store, run_id)) - set(decisions)
    rst = {c["item_key"]: c for c in run_store.read_restatements(run_id)}
    cands: list[FactCandidate] = []
    skips: list[Skip] = []
    rows_by_key: dict[str, tuple[dict, dict]] = {}

    def emit(row, f, key, state, citation, period_end, **extra):
        if f.get("value") is None:
            return skips.append(Skip(key, "no_value"))
        if not period_end:
            return skips.append(Skip(key, "no_period"))
        cands.append(FactCandidate(
            issuer_key=row["issuer_key"], issuer_scheme=row["issuer_scheme"], field_id=f["field_id"],
            period_end=period_end, basis=f.get("basis") or "", value=f["value"], unit=f.get("unit"),
            canonical_value=f.get("canonical_value"), canonical_unit=f.get("canonical_unit"), state=state,
            citation=citation, source_run_id=run_id, observed_at=manifest.created_at, item_key=key, **extra,
        ))

    for row in run_store.read_results(run_id):
        if not row.get("issuer_key"):
            skips.append(Skip(row.get("company_id", ""), "no_issuer_key"))
            continue
        for f in row.get("fields", []):
            key = field_item_key(row["issuer_key"], f["field_id"], period_key(f))
            rows_by_key[key] = (row, f)
            if key in rst:
                continue  # only the restatement branch may publish this key
            d = decisions.get(key)
            if d is None:
                if key in in_review or f.get("route") == "review":
                    skips.append(Skip(key, "not_final"))
                elif f.get("route") == "hold":
                    skips.append(Skip(key, "held"))
                elif f.get("route") == "auto_accept":
                    emit(row, f, key, "auto_accepted", _grounded(f), f.get("period_end"))
                else:
                    skips.append(Skip(key, "not_auto_accepted"))
                continue
            kind = d.get("decision")
            if kind == "reject":
                skips.append(Skip(key, "rejected"))
            elif kind == "approve":
                emit(row, f, key, "approved", _grounded(f), f.get("period_end"))
            elif kind in ("correct", "edit"):
                merged = merge_correction(f, d)
                emit(row, merged, key, "edited", _correction(d), merged.get("period_end"))
            else:
                skips.append(Skip(key, "not_final"))

    states = item_states(run_store, run_id)
    for key, c in rst.items():
        d = decisions.get(c["candidate_id"])
        kind = d.get("decision") if d else None
        s = states.get(c["candidate_id"])
        if kind != "reject" and not (d and d.get("step") and (s.state == "second_done" or d["step"] == "resolution")):
            kind = None  # a restatement publishes only after the workbench's second review or a resolution
        if kind not in _STATE or key not in rows_by_key:
            skips.append(Skip(key, "rejected" if kind == "reject" else "restatement_pending"))
            continue
        row, f = rows_by_key[key]
        if kind == "approve":
            f, citation = {**f, "value": c["new_value"]}, _grounded(f)
        else:
            f, citation = merge_correction(f, d), _correction(d)
        doc = citation.doc_id if citation else next(iter(c.get("doc_ids") or []), None)
        emit(row, f, key, _STATE[kind], citation, f.get("period_end"), restated=True, restated_by_doc_id=doc)
    return cands, skips
