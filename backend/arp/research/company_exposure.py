"""Company-level theme exposure (spec theme-company-exposure, slice 1): one row per company of a
theme run, rolled up from its stored match dicts on read. No model call."""

from __future__ import annotations

import json

from arp.config import Settings

TIERS = ["pure_play", "majority", "partial", "ecosystem", "out"]
BASES = ["reported", "catalogue", "extracted", "modelled"]  # strongest first
ESTIMATES = ["pure_play", "significant", "minor", "none"]
LABEL_TIER = {"pure_play": "pure_play", "significant": "partial", "minor": "ecosystem", "none": "ecosystem"}
RELATION_ROLE = {"buys": "adopter", "operates": "operator", "develops": "developer"}


def tier_thresholds(settings: Settings) -> dict[str, float]:
    """The three tier thresholds; ValueError with the 503 detail when they are not valid."""
    t = {"pure_play": settings.theme_tier_pure_play, "majority": settings.theme_tier_majority,
         "partial": settings.theme_tier_partial}
    for key, value in t.items():
        if not 0 < value <= 1:
            raise ValueError(f"ARP_THEME_TIER_{key.upper()} must be greater than 0 and at most 1")
    if not t["partial"] < t["majority"] < t["pure_play"]:
        raise ValueError("ARP_THEME_TIER_PARTIAL < ARP_THEME_TIER_MAJORITY < ARP_THEME_TIER_PURE_PLAY is required")
    return t


def _value(metric: dict | None, sources) -> float | None:
    if metric and metric.get("source") in sources:
        return metric.get("value_pct")
    return None


def _activity(m: dict, activity_tiers: dict[str, str]) -> dict:
    included = m.get("verdict") == "include"
    rev = (m.get("revenue_exposure") or {}).get("revenue") or {}
    share = _value(rev, BASES) if included else None
    modelled = share is not None and rev.get("source") == "modelled"
    relation = m.get("relation")
    role = None
    if included:
        if relation in RELATION_ROLE:
            role = RELATION_ROLE[relation]
        elif relation is None and m.get("company_role") == "innovator":
            role = "developer"
        else:
            role = "maker" if activity_tiers.get(m.get("activity_id"), "core") == "core" else "supplier"
    return {
        "activity_id": m.get("activity_id"), "activity_name": m.get("activity_name"), "verdict": m.get("verdict"),
        "share": share, "share_low": rev.get("low_pct") if modelled else None,
        "share_high": rev.get("high_pct") if modelled else None,
        "basis": (rev.get("source") if share is not None else "label") if included else None,
        "relation": relation, "role": role,
    }


def _max(values) -> float | None:
    values = [v for v in values if v is not None]
    return max(values) if values else None


def company_row(company_id: str, name: str, matches: list[dict], activity_tiers: dict[str, str],
                thresholds: dict[str, float]) -> dict:
    acts = [_activity(m, activity_tiers) for m in matches]
    inc = [(m, a) for m, a in zip(matches, acts, strict=True) if a["verdict"] == "include"]
    with_share = [a for _, a in inc if a["share"] is not None]
    share = min(sum(a["share"] for a in with_share), 1.0) if with_share else None
    low = high = None
    if any(a["basis"] == "modelled" for a in with_share):
        low = min(sum(a["share"] if a["share_low"] is None else a["share_low"] for a in with_share), 1.0)
        high = min(sum(a["share"] if a["share_high"] is None else a["share_high"] for a in with_share), 1.0)
    basis = max((a["basis"] for a in with_share), key=BASES.index) if with_share else "label" if inc else None

    tier = "out"
    if inc:
        candidates = [LABEL_TIER[m.get("exposure_estimate")] for m, a in inc if a["basis"] == "label"]
        if share is not None:
            candidates.append(next((k for k in ("pure_play", "majority", "partial") if share >= thresholds[k]), "ecosystem"))
        tier = min(candidates, key=TIERS.index)

    signals = {
        "rd": _max(_value((m.get("rd_exposure") or {}).get("rd_intensity"), ["extracted"]) for m, _ in inc),
        "capex": _max(_value((m.get("revenue_exposure") or {}).get("capex"), BASES) for m, _ in inc),
        "mentions": _max(_value((m.get("rd_exposure") or {}).get("news_mentions"), ["news"]) for m, _ in inc),
    }
    present = [v for v in signals.values() if v is not None]
    momentum = sum(present) / len(present) if present else None
    band = None if momentum is None else "high" if momentum >= 0.5 else "medium" if momentum >= 0.2 else "low"

    role = None
    if inc:
        lead = min(inc, key=lambda p: (-(p[1]["share"] if p[1]["share"] is not None else float("-inf")),
                                       ESTIMATES.index(p[0].get("exposure_estimate")), p[1]["activity_name"] or ""))
        role = lead[1]["role"]
    needs_check = any(
        m.get("flagged_for_review") or (m.get("arbitration") or {}).get("methods_disagree") for m, _ in inc
    )
    return {
        "company_id": company_id, "name": name, "tier": tier, "share": share, "share_low": low, "share_high": high,
        "share_basis": basis, "momentum": momentum, "momentum_band": band, "momentum_signals": signals,
        "role": role, "needs_check": bool(needs_check), "activities": acts,
    }


def _sort_key(r: dict):
    return (TIERS.index(r["tier"]),
            r["share"] is None, -(r["share"] or 0),
            r["momentum"] is None, -(r["momentum"] or 0),
            r["name"], r["company_id"])


def load_run_exposure(settings: Settings, run_store, run_id: str) -> tuple[dict[str, float], list[dict]]:
    """Thresholds and rows of a theme run. Raises LookupError (no such theme run), then ValueError (bad tier settings)."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None or manifest.run_type != "theme":
        raise LookupError(f"unknown theme run '{run_id}'")
    thresholds = tier_thresholds(settings)
    theme_path = run_store.run_dir(run_id) / "theme.json"
    activities = json.loads(theme_path.read_text())["activities"] if theme_path.exists() else []
    activity_tiers = {a["activity_id"]: a.get("tier", "core") for a in activities}
    results = run_store.read_results(run_id)
    rows = []
    for c in run_store.load_companies(run_id) or []:
        matches = [m for r in results if r.get("_key") == c.company_id for m in r.get("company_matches") or []]
        rows.append(company_row(c.company_id, c.name, matches, activity_tiers, thresholds))
    return thresholds, sorted(rows, key=_sort_key)
