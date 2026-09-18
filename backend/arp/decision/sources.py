from __future__ import annotations

from collections import defaultdict

from arp.decision.dataset import Dataset, build_dataset
from arp.storage.run_store import RunStore

# Column names deliberately follow the conventions the role/direction
# dictionaries already recognise (`*_Coverage_pct`, `*_Intensity_*`,
# `*_Flag`, `*_Weight_*`), so role and direction inference works as well on
# a table built from an in-repo run as on an uploaded spreadsheet.

_EXPOSURE_SCALE = {"none": 0.0, "low": 25.0, "medium": 50.0, "high": 75.0, "very_high": 100.0}
_VERDICT_SCALE = {"include": 1, "borderline": 0, "exclude": 0}


def _matrix(columns: list[str], rows: list[list[str]]) -> list[list[str]]:
    return [columns] + rows


def from_transition_plan_run(run_store: RunStore, run_id: str) -> Dataset:
    """A transition-plan assessment run -> a scoreable table.

    The paper's completeness metric is a count, not a decision. This is
    what turns "42 of 64 indicators disclosed" into "Tier 2, engage on
    governance", which is what an investor actually does with it.
    """
    records = run_store.read_jsonl(run_store.results_path(run_id))
    if not records:
        raise ValueError(f"Transition plan run {run_id} has no results.")

    categories = sorted({b.get("category", "") for r in records for b in r.get("by_category", []) if b.get("category")})
    columns = [
        "Company",
        "Company_Id",
        "Sector",
        "Region",
        "Indicators_Disclosed_Count",
        "Walk_Disclosed_Count",
        "Talk_Disclosed_Count",
        "Walk_Share_pct",
        "Assessment_Confidence_pct",
        *[f"{c.title()}_Disclosure_pct" for c in categories],
        "Needs_Review_Flag",
    ]
    rows: list[list[str]] = []
    for record in records:
        by_category = {b.get("category"): b for b in record.get("by_category", [])}
        walk_total = record.get("walk_total_count") or 0
        walk_disclosed = record.get("walk_disclosed_count") or 0
        row = [
            str(record.get("name") or record.get("company_id") or ""),
            str(record.get("company_id") or ""),
            str(record.get("company_sector") or ""),
            str(record.get("company_location") or ""),
            str(record.get("disclosed_count") or 0),
            str(walk_disclosed),
            str(record.get("talk_disclosed_count") or 0),
            f"{(walk_disclosed / walk_total * 100):.1f}" if walk_total else "",
            f"{(record.get('overall_confidence') or 0.0) * 100:.1f}",
        ]
        for category in categories:
            breakdown = by_category.get(category) or {}
            total = breakdown.get("total_count") or 0
            row.append(f"{(breakdown.get('disclosed_count', 0) / total * 100):.1f}" if total else "")
        row.append("Yes" if record.get("needs_review") else "No")
        rows.append(row)

    dataset = build_dataset(
        f"Transition plan run {run_id}", _matrix(columns, rows), source="transition_plan_run", source_ref=run_id
    )
    # The paper's own confidence figure, carried per cell so a framework
    # asking for grounded coverage can act on it.
    confidence = [(float(r.get("overall_confidence") or 0.0)) for r in records]
    for column in ("Indicators_Disclosed_Count", "Walk_Disclosed_Count", "Talk_Disclosed_Count", "Walk_Share_pct"):
        dataset.confidence[column] = list(confidence)
    return dataset


def from_extraction_run(run_store: RunStore, run_id: str) -> Dataset:
    """An extraction run -> one row per company, one column per schema
    field, with each cell's confidence carried alongside it.

    This is the source that makes `require_grounded_coverage` worth having:
    an extracted value the verifier could not ground is present but not
    trustworthy, and a score built mostly on those should say so rather
    than read like any other score.
    """
    records = run_store.read_jsonl(run_store.results_path(run_id))
    if not records:
        raise ValueError(f"Extraction run {run_id} has no results.")

    field_names: list[str] = []
    for record in records:
        for field in record.get("fields", []):
            name = str(field.get("field_name") or field.get("field_id") or "")
            if name and name not in field_names:
                field_names.append(name)

    columns = ["Company", "Company_Id", "Extraction_Confidence_pct", *field_names, "Needs_Review_Flag"]
    rows: list[list[str]] = []
    confidence: dict[str, list[float | None]] = defaultdict(list)
    for record in records:
        by_name = {str(f.get("field_name") or f.get("field_id")): f for f in record.get("fields", [])}
        row = [
            str(record.get("name") or record.get("company_id") or ""),
            str(record.get("company_id") or ""),
            f"{(record.get('overall_confidence') or 0.0) * 100:.1f}",
        ]
        for name in field_names:
            field = by_name.get(name) or {}
            value = field.get("value")
            row.append("" if value is None else str(value))
            # An ungrounded citation is the reason confidence exists here:
            # the extractor's own certainty is not evidence.
            grounded = bool(field.get("grounded"))
            raw_confidence = field.get("confidence")
            confidence[name].append(float(raw_confidence) if raw_confidence is not None and grounded else (0.0 if name in by_name else None))
        row.append("Yes" if record.get("needs_review") else "No")
        rows.append(row)

    dataset = build_dataset(f"Extraction run {run_id}", _matrix(columns, rows), source="extraction_run", source_ref=run_id)
    dataset.confidence = {k: v for k, v in confidence.items()}
    return dataset


def from_theme_run(run_store: RunStore, run_id: str) -> Dataset:
    """A thematic universe run -> one row per company, aggregated over the
    per-activity matches: how many activities it was included on, its best
    exposure estimate, and the adjudicator's mean confidence."""
    matches = run_store.read_jsonl(run_store.results_path(run_id))
    if not matches:
        raise ValueError(f"Theme run {run_id} has no results.")

    grouped: dict[str, list[dict]] = defaultdict(list)
    for match in matches:
        grouped[str(match.get("company_id") or match.get("name") or "")].append(match)

    columns = [
        "Company",
        "Company_Id",
        "Activities_Included_Count",
        "Best_Exposure_Score_0_100",
        "Mean_Exposure_Score_0_100",
        "Adjudicator_Confidence_pct",
        "Flagged_For_Review_Flag",
    ]
    rows: list[list[str]] = []
    for company_id, company_matches in grouped.items():
        included = [m for m in company_matches if str(m.get("verdict", "")).lower() == "include"]
        exposures = [_EXPOSURE_SCALE.get(str(m.get("exposure_estimate", "")).lower(), 0.0) for m in company_matches]
        confidences = [float(m.get("confidence") or 0.0) for m in company_matches]
        rows.append(
            [
                str(company_matches[0].get("name") or company_id),
                company_id,
                str(len(included)),
                f"{max(exposures):.1f}" if exposures else "",
                f"{(sum(exposures) / len(exposures)):.1f}" if exposures else "",
                f"{(sum(confidences) / len(confidences) * 100):.1f}" if confidences else "",
                "Yes" if any(m.get("flagged_for_review") for m in company_matches) else "No",
            ]
        )
    return build_dataset(f"Theme run {run_id}", _matrix(columns, rows), source="theme_run", source_ref=run_id)


def from_portfolio_snapshot(store, as_of: str | None = None, portfolio_ids: list[str] | None = None, field_ids: list[str] | None = None) -> Dataset:
    """Holdings as of one date, joined to whatever data-point observations
    exist for each issuer -- climate metrics included.

    `market_value_eur` becomes the size column, which is what makes the
    leverage ordering (position size x the gap to a perfect score) a real
    portfolio-weighted engagement priority list rather than a
    demonstration.
    """
    resolved = as_of or (store.all_snapshot_dates() or [None])[-1]
    if resolved is None:
        raise ValueError("No holdings snapshots available.")
    holdings = store.load_holdings_as_of(resolved, portfolio_ids)
    if not holdings:
        raise ValueError(f"No holdings as of {resolved}.")

    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}

    exposure: dict[str, float] = defaultdict(float)
    for holding in holdings:
        security = securities.get(holding.security_id)
        company_id = security.company_id if security else None
        if company_id:
            exposure[company_id] += holding.market_value_eur

    from arp.portfolio.climate.schemas import build_climate_schema

    fields = [f for f in build_climate_schema().fields if not field_ids or f.field_id in field_ids]
    observations: dict[str, dict[str, float]] = defaultdict(dict)
    for company_id in exposure:
        for field in fields:
            observation = store.latest_observation(company_id, field.field_id, as_of=resolved)
            if observation is not None and isinstance(observation.value, (int, float)):
                observations[company_id][field.field_id] = float(observation.value)

    used_fields = [f for f in fields if any(f.field_id in values for values in observations.values())]
    columns = ["Company", "Company_Id", "Sector", "Country", "Portfolio_Market_Value_EUR", *[_field_column(f) for f in used_fields]]
    rows: list[list[str]] = []
    for company_id, market_value in sorted(exposure.items(), key=lambda kv: -kv[1]):
        company = companies.get(company_id)
        row = [
            company.name if company else company_id,
            company_id,
            (company.sector if company else "") or "",
            (company.country if company else "") or "",
            f"{market_value:.2f}",
        ]
        for field in used_fields:
            value = observations.get(company_id, {}).get(field.field_id)
            row.append("" if value is None else f"{value:g}")
        rows.append(row)

    return build_dataset(
        f"Portfolio holdings as of {resolved}",
        _matrix(columns, rows),
        source="portfolio_snapshot",
        source_ref=",".join(portfolio_ids) if portfolio_ids else "all",
        as_of=resolved,
    )


def _field_column(field) -> str:
    """A data-point field's column name, keeping the unit in the name where
    the dictionaries key off it (`_pct`, `_Intensity_`)."""
    base = field.name.replace(" ", "_").replace("/", "_")
    unit = (field.unit or "").strip().lower()
    if unit in ("%", "pct", "percent") and not base.lower().endswith("pct"):
        return f"{base}_pct"
    return base
